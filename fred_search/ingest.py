"""
Ingest pipeline: fetch FRED series metadata → filter → embed → store in LanceDB.

Resumable: all fetch progress is persisted in a local SQLite state DB.
Re-running picks up where it left off across all phases.

Usage (CLI)
-----------
    fred-ingest --api-key <key>
    fred-ingest --api-key <key> --skip-categories --dry-run
    fred-ingest --api-key <key> --force          # full rebuild

Usage (library)
---------------
    from fred_search.ingest import run_ingest
    run_ingest(api_key="...", data_dir=Path("data"))
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections import deque
from pathlib import Path

import numpy as np

from fred_search._client import FREDClient, FREDAPIError
from fred_search._filters import FilterConfig, apply_filters
from fred_search._state import IngestState
from fred_search.models import FREDSeriesMetadata

logger = logging.getLogger(__name__)

# FRED category 0 is the logical root; its "children" are the top-level domains.
_FRED_ROOT_CATEGORY = 0
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_LANCEDB_TABLE = "fred_series"


# ---------------------------------------------------------------------------
# Embedding text construction
# ---------------------------------------------------------------------------

def build_embedding_text(series: FREDSeriesMetadata) -> str:
    """
    Construct the text to embed for a series.

    Notes (first 500 chars) carry the richest semantic signal — they often
    contain the full descriptive sentence that a human analyst would read.
    Title, units, and frequency are appended for structured disambiguation.
    Tags are included if populated (tags require a separate API call so they
    may be absent for most series; the embedding still works well without them).
    """
    parts: list[str] = [series.title]

    if series.notes:
        parts.append(series.notes[:500])

    if series.tags:
        parts.append("Tags: " + ", ".join(series.tags))

    if series.units:
        parts.append(f"Units: {series.units}")

    if series.frequency:
        parts.append(f"Frequency: {series.frequency}")

    if series.category_path:
        parts.append(f"Category: {series.category_path}")

    return " | ".join(p for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Phase 1: Release discovery
# ---------------------------------------------------------------------------

def _fetch_releases(client: FREDClient, state: IngestState) -> int:
    logger.info("Phase 1: fetching release list...")
    releases = list(client.get_all_releases())
    new_count = state.register_releases(releases)
    logger.info(
        "  %d total releases; %d newly registered in state",
        len(releases), new_count,
    )
    return len(releases)


# ---------------------------------------------------------------------------
# Phase 2: Series fetch via releases
# ---------------------------------------------------------------------------

def _fetch_series_by_releases(
    client: FREDClient,
    state: IngestState,
    dry_run: bool,
) -> int:
    try:
        from tqdm import tqdm as _tqdm
        _tqdm_available = True
    except ImportError:
        _tqdm_available = False

    pending = state.get_pending_releases()
    logger.info("Phase 2: fetching series for %d pending releases...", len(pending))

    total_new = 0
    iterable = (_tqdm(pending, desc="releases") if _tqdm_available else pending)

    for release in iterable:
        rid = release["release_id"]
        if dry_run:
            state.mark_release_done(rid, series_count=0)
            continue

        try:
            series_list = list(client.get_release_series(rid))
            new = state.store_series_batch(series_list, source=f"release:{rid}")
            total_new += new
            state.mark_release_done(rid, series_count=len(series_list))
            if new:
                logger.debug(
                    "  release %d (%s): %d series total, %d new",
                    rid, release["name"], len(series_list), new,
                )
        except FREDAPIError as exc:
            logger.error("  release %d failed (non-retryable): %s", rid, exc)
            state.mark_release_error(rid, str(exc))
        except Exception as exc:
            logger.error("  release %d unexpected error: %s", rid, exc)
            state.mark_release_error(rid, str(exc))

    logger.info("Phase 2 done: %d new series discovered via releases", total_new)
    return total_new


# ---------------------------------------------------------------------------
# Phase 3: Category tree walk (supplemental)
# ---------------------------------------------------------------------------

def _fetch_series_by_categories(
    client: FREDClient,
    state: IngestState,
    dry_run: bool,
) -> int:
    """BFS traversal of the FRED category tree.

    Categories are a superset of releases: some series only appear in the
    category tree. The release walk (phase 2) covers the majority; this phase
    picks up the remainder without double-counting (INSERT OR IGNORE).
    """
    logger.info("Phase 3: walking FRED category tree (BFS)...")

    try:
        from tqdm import tqdm as _tqdm
        pbar = _tqdm(desc="categories", unit="cat")
    except ImportError:
        pbar = None

    # Seed the queue from root's children
    queue: deque[tuple[int, str]] = deque()
    try:
        root_children = client.get_category_children(_FRED_ROOT_CATEGORY)
    except Exception as exc:
        logger.error("Could not fetch root category children: %s", exc)
        return 0

    for cat in root_children:
        state.register_category(cat["id"], cat.get("name", ""), parent_id=None)
        queue.append((cat["id"], cat.get("name", "")))

    total_new = 0
    visited = 0

    while queue:
        cat_id, cat_name = queue.popleft()

        if state.is_category_done(cat_id):
            if pbar is not None:
                pbar.update(1)
            continue

        visited += 1
        if pbar is not None:
            pbar.set_postfix(cat=f"{cat_id}", series=total_new)

        # Fetch series in this category
        if not dry_run:
            try:
                series_list = list(client.get_category_series(cat_id))
                new = state.store_series_batch(series_list, source=f"category:{cat_id}")
                total_new += new
                state.mark_category_done(cat_id, series_count=len(series_list))
            except FREDAPIError as exc:
                logger.error("  category %d failed: %s", cat_id, exc)
                state.mark_category_error(cat_id, str(exc))
            except Exception as exc:
                logger.error("  category %d unexpected error: %s", cat_id, exc)
                state.mark_category_error(cat_id, str(exc))
        else:
            state.mark_category_done(cat_id, series_count=0)

        # Enqueue children regardless (even if series fetch failed, we still
        # want to traverse the subtree)
        try:
            children = client.get_category_children(cat_id)
            for child in children:
                is_new = state.register_category(
                    child["id"], child.get("name", ""), parent_id=cat_id
                )
                if is_new or not state.is_category_done(child["id"]):
                    queue.append((child["id"], child.get("name", "")))
        except Exception as exc:
            logger.warning(
                "  Could not fetch children for category %d: %s", cat_id, exc
            )

        if pbar is not None:
            pbar.update(1)

    if pbar is not None:
        pbar.close()

    logger.info(
        "Phase 3 done: visited %d category nodes, %d new series", visited, total_new
    )
    return total_new


# ---------------------------------------------------------------------------
# Phase 4: Load, parse, filter
# ---------------------------------------------------------------------------

def _load_and_filter(
    state: IngestState, cfg: FilterConfig
) -> list[FREDSeriesMetadata]:
    logger.info(
        "Phase 4: loading %d raw series from state DB...",
        state.total_series_count(),
    )
    all_series: list[FREDSeriesMetadata] = []
    for raw, tags in state.iter_all_series():
        meta = FREDSeriesMetadata.from_api_response(raw)
        meta.tags = tags
        all_series.append(meta)

    logger.info("  Loaded %d series; applying filters...", len(all_series))
    filtered, _ = apply_filters(all_series, cfg)

    # Enrich with category paths from the state DB
    logger.info("  Resolving category paths for %d filtered series...", len(filtered))
    cat_paths = state.build_category_paths()
    source_map = state.get_series_source_map()
    enriched = 0
    for s in filtered:
        src = source_map.get(s.series_id, "")
        if src.startswith("category:"):
            try:
                cat_id = int(src.split(":", 1)[1])
                path = cat_paths.get(cat_id, "")
                if path:
                    s.category_path = path
                    enriched += 1
            except (ValueError, IndexError):
                pass
    logger.info("  Category paths resolved for %d / %d series.", enriched, len(filtered))

    return filtered


# ---------------------------------------------------------------------------
# Phase 4.5: Tag enrichment (optional, API-intensive)
# ---------------------------------------------------------------------------

def _enrich_tags(
    client: FREDClient,
    state: IngestState,
    filtered: list[FREDSeriesMetadata],
) -> None:
    """Fetch per-series tags for filtered series that don't already have tags.

    This is the most API-intensive phase: one call per series. At 85 req/min,
    ~35K series takes ~7 hours. Resumable — series with tags already in the
    state DB are skipped automatically.
    """
    try:
        from tqdm import tqdm as _tqdm
        _tqdm_available = True
    except ImportError:
        _tqdm_available = False

    have_tags = state.get_series_ids_with_tags()
    need_tags = [s for s in filtered if s.series_id not in have_tags]

    logger.info(
        "Phase 4.5: enriching tags for %d series (%d already have tags)...",
        len(need_tags), len(filtered) - len(need_tags),
    )

    if not need_tags:
        logger.info("  All filtered series already have tags. Skipping.")
        return

    iterable = (
        _tqdm(need_tags, desc="tags", unit="series")
        if _tqdm_available else need_tags
    )
    enriched = 0
    errors = 0

    for series in iterable:
        try:
            tags = client.get_series_tags(series.series_id)
            state.store_tags_batch(series.series_id, tags)
            series.tags = tags
            enriched += 1
        except FREDAPIError as exc:
            logger.debug("  tags for %s failed: %s", series.series_id, exc)
            errors += 1
        except Exception as exc:
            logger.warning(
                "  tags for %s unexpected error: %s", series.series_id, exc
            )
            errors += 1

    logger.info(
        "Phase 4.5 done: %d enriched, %d errors, %d skipped (had tags)",
        enriched, errors, len(filtered) - len(need_tags),
    )


# ---------------------------------------------------------------------------
# Phase 5: Embedding
# ---------------------------------------------------------------------------

def _embed(
    series: list[FREDSeriesMetadata],
) -> tuple[list[str], "np.ndarray"]:
    logger.info("Phase 5: embedding %d series with %s...", len(series), _EMBEDDING_MODEL)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for embedding. "
            "Install it: pip install sentence-transformers"
        ) from exc

    texts = [build_embedding_text(s) for s in series]
    model = SentenceTransformer(_EMBEDDING_MODEL)
    # normalize_embeddings=True → cosine similarity == dot product at query time.
    embeddings = model.encode(
        texts,
        batch_size=256,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    logger.info("  Embedding complete. Shape: %s", embeddings.shape)
    return texts, embeddings


# ---------------------------------------------------------------------------
# Phase 6: LanceDB storage
# ---------------------------------------------------------------------------

def _store_lancedb(
    series: list[FREDSeriesMetadata],
    texts: list[str],
    embeddings: "np.ndarray",
    lance_path: Path,
) -> None:
    logger.info(
        "Phase 6: writing %d records to LanceDB at %s...", len(series), lance_path
    )
    try:
        import lancedb
    except ImportError as exc:
        raise RuntimeError(
            "lancedb is required for storage. Install it: pip install lancedb"
        ) from exc

    records = [
        {
            "series_id": s.series_id,
            "title": s.title,
            "notes": (s.notes or "")[:500],
            "frequency": s.frequency,
            "units": s.units,
            "seasonal_adjustment": s.seasonal_adjustment,
            "observation_start": s.observation_start,
            "observation_end": s.observation_end,
            "popularity": int(s.popularity),
            "last_updated": s.last_updated,
            "source": s.source,
            "category_path": s.category_path,
            "embedding_text": text,
            "tags": s.tags,               # list[str]; LanceDB stores as List<utf8>
            "vector": vec.tolist(),       # list[float]; 384-dim
        }
        for s, text, vec in zip(series, texts, embeddings)
    ]

    db = lancedb.connect(str(lance_path))
    db.create_table(_LANCEDB_TABLE, data=records, mode="overwrite")
    logger.info("  LanceDB table '%s' written successfully.", _LANCEDB_TABLE)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_ingest(
    api_key: str,
    data_dir: Path | str = "data",
    filter_cfg: FilterConfig | None = None,
    skip_categories: bool = False,
    enrich_tags: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> None:
    """
    Full series metadata ingest pipeline.

    Resumable: re-running after interruption continues from the last checkpoint
    using the SQLite state DB. Pass ``force=True`` to rebuild from scratch.

    Parameters
    ----------
    api_key:
        FRED API key.
    data_dir:
        Root directory for state DB and LanceDB index. Created if absent.
    filter_cfg:
        Filter settings; library defaults applied if None.
    skip_categories:
        Skip the category tree supplemental walk. Faster, but may miss ~5% of
        series that exist only in the category tree and not in any release.
    enrich_tags:
        Fetch per-series tags from the FRED API for every filtered series.
        This is API-intensive (~1 call per series) but produces much richer
        embedding text. Resumable — already-fetched tags are skipped.
    dry_run:
        Register releases and categories in state but do not call FRED, embed,
        or write to LanceDB. Useful to preview scope.
    force:
        Delete the existing state DB before starting, triggering a full fetch.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    filter_cfg = filter_cfg or FilterConfig()
    state_path = data_dir / "fred_ingest_state.db"
    lance_path = data_dir / "fred_vector_index"

    if force and state_path.exists():
        logger.info("--force: removing existing state DB at %s", state_path)
        state_path.unlink()

    t0 = time.monotonic()

    with IngestState(state_path) as state:
        run_id = state.start_run(notes="dry-run" if dry_run else "full")

        with FREDClient(api_key) as client:
            _fetch_releases(client, state)
            _fetch_series_by_releases(client, state, dry_run=dry_run)
            if not skip_categories:
                _fetch_series_by_categories(client, state, dry_run=dry_run)

            logger.info("State summary after fetch: %s", state.summary())

            if dry_run:
                logger.info("Dry run complete — skipping embed + LanceDB write.")
                state.finish_run(run_id)
                return

            filtered = _load_and_filter(state, filter_cfg)

            if not filtered:
                logger.error("No series survived filtering. Check filter config and state DB.")
                state.finish_run(run_id)
                return

            if enrich_tags:
                _enrich_tags(client, state, filtered)
                # Reload tags for series that already had them from a prior run
                have_tags = state.get_series_ids_with_tags()
                for s in filtered:
                    if not s.tags and s.series_id in have_tags:
                        s.tags = state.get_tags_for_series(s.series_id)

        texts, embeddings = _embed(filtered)
        _store_lancedb(filtered, texts, embeddings, lance_path)
        state.finish_run(run_id)

    elapsed = (time.monotonic() - t0) / 60
    logger.info("Ingest complete in %.1f minutes.", elapsed)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch FRED series metadata and build a local vector search index.\n\n"
            "The ingest is resumable: re-running continues from the last checkpoint.\n"
            "Use --force to rebuild from scratch."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FRED_API_KEY", ""),
        metavar="KEY",
        help="FRED API key (default: $FRED_API_KEY)",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="PATH",
        help="Directory for state DB and LanceDB index (default: data/)",
    )
    parser.add_argument(
        "--min-popularity",
        type=int,
        default=0,
        metavar="N",
        help="Minimum FRED popularity score to keep a series (default: 0)",
    )
    parser.add_argument(
        "--skip-categories",
        action="store_true",
        help="Skip the FRED category tree supplemental walk",
    )
    parser.add_argument(
        "--enrich-tags",
        action="store_true",
        help=(
            "Fetch per-series tags for all filtered series (API-intensive; "
            "~1 call per series). Produces richer embeddings but adds hours."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate fetch targets without calling FRED, embedding, or writing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "DESTRUCTIVE: deletes the state DB (all fetch progress) and "
            "rebuilds from scratch. Requires confirmation unless --yes is given."
        ),
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        metavar="LEVEL",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.api_key:
        parser.error(
            "FRED API key is required. "
            "Pass --api-key or set the FRED_API_KEY environment variable."
        )

    if args.force and not args.yes:
        state_path = Path(args.data_dir) / "fred_ingest_state.db"
        if state_path.exists():
            size_mb = state_path.stat().st_size / (1024 * 1024)
            answer = input(
                f"--force will DELETE {state_path} ({size_mb:.1f} MB) "
                f"and re-fetch all series from the FRED API.\n"
                f"Continue? [y/N] "
            )
            if answer.lower() not in ("y", "yes"):
                print("Aborted.")
                return

    run_ingest(
        api_key=args.api_key,
        data_dir=Path(args.data_dir),
        filter_cfg=FilterConfig(min_popularity=args.min_popularity),
        skip_categories=args.skip_categories,
        enrich_tags=args.enrich_tags,
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    main()

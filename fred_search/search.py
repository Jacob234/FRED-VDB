"""
Semantic search interface for the FRED vector index.

Quick usage
-----------
    from fred_search import search_fred

    results = search_fred("indicators of CRE credit stress", top_k=5)
    for r in results:
        print(r.series_id, r.title, f"(score={r.similarity_score:.3f})")

CLI
---
    fred-search "inflation expectations" --top-k 5 --frequency Monthly
    fred-search "housing affordability" --json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

from fred_search._abbreviations import expand_query
from fred_search.models import FREDSearchResult

logger = logging.getLogger(__name__)

_LANCEDB_TABLE = "fred_series"
_DEFAULT_TOP_K = 10
_DEFAULT_DATA_DIR = Path("data")


class FREDSearcher:
    """
    Stateful search client that keeps the embedding model in memory.

    Use this when issuing multiple queries to avoid reloading the model
    on each call.

    Parameters
    ----------
    data_dir:
        Directory containing the ``fred_vector_index`` LanceDB folder.
        Must match the directory passed to ``run_ingest``.
    """

    def __init__(self, data_dir: Path | str = _DEFAULT_DATA_DIR) -> None:
        data_dir = Path(data_dir)
        lance_path = data_dir / "fred_vector_index"

        if not lance_path.exists():
            raise FileNotFoundError(
                f"LanceDB index not found at {lance_path}. "
                "Run `fred-ingest` first to build the index."
            )

        try:
            import lancedb
        except ImportError as exc:
            raise RuntimeError(
                "lancedb is required. Install it: pip install lancedb"
            ) from exc

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required. "
                "Install it: pip install sentence-transformers"
            ) from exc

        self._db = lancedb.connect(str(lance_path))
        self._table = self._db.open_table(_LANCEDB_TABLE)
        self._model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.debug("FREDSearcher ready. Table: %s", lance_path)

    def search(
        self,
        query: str,
        top_k: int = _DEFAULT_TOP_K,
        frequency: str | None = None,
        min_popularity: int | None = None,
        active_only: bool = True,
        max_stale_days: int | None = None,
        popularity_boost: bool = True,
    ) -> list[FREDSearchResult]:
        """
        Semantic search over FRED series metadata.

        Parameters
        ----------
        query:
            Natural language description of the data you're looking for.
            Examples:
              - "indicators of commercial real estate credit stress"
              - "inflation expectations vs realized inflation"
              - "housing supply pipeline for multifamily"
              - "risk-free rate benchmarks at various maturities"
        top_k:
            Number of results to return.
        frequency:
            Restrict results to a specific frequency.
            Common values: "Daily", "Weekly", "Monthly", "Quarterly", "Annual".
        min_popularity:
            Only return series with at least this popularity score.
        active_only:
            If True (default), only return series with a recent observation_end.
            Requires the ``max_stale_days`` parameter to have meaning; defaults
            to 730 days when active_only=True and max_stale_days is not set.
        max_stale_days:
            Maximum age (in days) of the most recent observation. Ignored if
            ``active_only`` is False.
        popularity_boost:
            If True (default), re-rank results by
            ``similarity * (1 + log(popularity + 1) / 10)``.
            This surfaces well-known headline series (UNRATE, DGS10) that
            would otherwise be buried by niche variants with richer metadata.
        """
        # Expand finance abbreviations before embedding
        expanded = expand_query(query)
        if expanded != query:
            logger.info("Query expanded: %r → %r", query, expanded)

        # Build query vector (normalized, same as ingest)
        query_vec = self._model.encode(
            [expanded], normalize_embeddings=True
        )[0].tolist()

        # Compose LanceDB WHERE clause
        filters = _build_where(
            frequency=frequency,
            min_popularity=min_popularity,
            active_only=active_only,
            max_stale_days=max_stale_days,
        )

        # When popularity boosting, fetch extra candidates so re-ranking
        # can surface popular series that rank lower by pure similarity.
        fetch_limit = top_k * 3 if popularity_boost else top_k

        search_builder = self._table.search(query_vec).limit(fetch_limit)
        if filters:
            search_builder = search_builder.where(filters, prefilter=True)

        df = search_builder.to_pandas()

        results: list[FREDSearchResult] = []
        for _, row in df.iterrows():
            # LanceDB returns L2 distance. For normalized unit vectors:
            #   cos_sim = 1 - (l2_dist² / 2)
            # This maps distance 0→sim 1 and distance √2→sim 0.
            l2 = float(row.get("_distance", 0.0))
            cos_sim = max(0.0, 1.0 - (l2 ** 2) / 2.0)

            raw_tags = row.get("tags")
            if raw_tags is None:
                tags = []
            elif isinstance(raw_tags, list):
                tags = raw_tags
            else:
                # LanceDB returns numpy arrays for list columns
                tags = list(raw_tags) if len(raw_tags) > 0 else []

            pop = int(row.get("popularity", 0))

            if popularity_boost:
                score = cos_sim * (1.0 + math.log(pop + 1) / 10.0)
            else:
                score = cos_sim

            results.append(
                FREDSearchResult(
                    series_id=row["series_id"],
                    title=row["title"],
                    notes=row.get("notes", ""),
                    frequency=row.get("frequency", ""),
                    units=row.get("units", ""),
                    seasonal_adjustment=row.get("seasonal_adjustment", ""),
                    tags=tags,
                    popularity=pop,
                    similarity_score=score,
                    source=row.get("source", ""),
                    observation_end=row.get("observation_end", ""),
                    category_path=row.get("category_path", ""),
                )
            )

        # Re-sort by boosted score and trim to top_k
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:top_k]


def _build_where(
    frequency: str | None,
    min_popularity: int | None,
    active_only: bool,
    max_stale_days: int | None,
) -> str | None:
    """Construct a SQL WHERE clause for LanceDB metadata filtering."""
    from datetime import date, timedelta

    clauses: list[str] = []

    if frequency:
        clauses.append(f"frequency = '{frequency}'")

    if min_popularity is not None:
        clauses.append(f"popularity >= {min_popularity}")

    if active_only:
        stale_days = max_stale_days or 730
        cutoff = (date.today() - timedelta(days=stale_days)).isoformat()
        # observation_end is stored as a string "YYYY-MM-DD"; string comparison
        # works correctly for ISO-format dates.
        clauses.append(f"observation_end >= '{cutoff}'")

    return " AND ".join(clauses) if clauses else None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

_default_searcher: FREDSearcher | None = None


def search_fred(
    query: str,
    top_k: int = _DEFAULT_TOP_K,
    data_dir: Path | str = _DEFAULT_DATA_DIR,
    frequency: str | None = None,
    min_popularity: int | None = None,
    active_only: bool = True,
    max_stale_days: int | None = None,
    popularity_boost: bool = True,
) -> list[FREDSearchResult]:
    """
    Semantic search over FRED series metadata.

    Loads the index from ``data_dir/fred_vector_index``. The embedding model
    is initialised on each call; use ``FREDSearcher`` directly if issuing many
    queries in a single session.

    Parameters
    ----------
    query:
        Natural language query.
    top_k:
        Number of results to return.
    data_dir:
        Path to the data directory where the index lives (default: ``data/``).
    frequency:
        Filter by frequency (e.g. "Monthly", "Quarterly").
    min_popularity:
        Minimum FRED popularity score.
    active_only:
        Exclude series whose most recent data is older than ``max_stale_days``.
    max_stale_days:
        Staleness cutoff in days (default 730 when active_only=True).
    popularity_boost:
        Re-rank results with a popularity-weighted score (default True).
    """
    searcher = FREDSearcher(data_dir=data_dir)
    return searcher.search(
        query=query,
        top_k=top_k,
        frequency=frequency,
        min_popularity=min_popularity,
        active_only=active_only,
        max_stale_days=max_stale_days,
        popularity_boost=popularity_boost,
    )


# ---------------------------------------------------------------------------
# CLI formatting
# ---------------------------------------------------------------------------

def _format_results(results: list[FREDSearchResult], as_json: bool) -> str:
    if as_json:
        return json.dumps([r.as_dict() for r in results], indent=2)

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"\n  {i}. {r.series_id}  (similarity: {r.similarity_score:.3f})")
        lines.append(f"     {r.title}")
        lines.append(
            f"     Frequency: {r.frequency} | Units: {r.units} | "
            f"Popularity: {r.popularity} | Data through: {r.observation_end}"
        )
        if r.category_path:
            lines.append(f"     Category: {r.category_path}")
        if r.tags:
            lines.append(f"     Tags: {', '.join(r.tags[:8])}")
        if r.notes:
            snippet = r.notes[:120].replace("\n", " ")
            if len(r.notes) > 120:
                snippet += "…"
            lines.append(f"     {snippet}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semantic search over the local FRED series index.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", help="Natural language search query")
    parser.add_argument(
        "--top-k", type=int, default=_DEFAULT_TOP_K, metavar="N",
        help=f"Number of results (default: {_DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--data-dir", default="data", metavar="PATH",
        help="Data directory containing the fred_vector_index (default: data/)",
    )
    parser.add_argument(
        "--frequency", default=None, metavar="FREQ",
        help="Filter by frequency: Daily, Weekly, Monthly, Quarterly, Annual",
    )
    parser.add_argument(
        "--min-popularity", type=int, default=None, metavar="N",
        help="Minimum FRED popularity score",
    )
    parser.add_argument(
        "--include-stale", action="store_true",
        help="Include series with old observation_end dates",
    )
    parser.add_argument(
        "--no-popularity-boost", action="store_true",
        help="Disable popularity-weighted re-ranking (use pure similarity)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    results = search_fred(
        query=args.query,
        top_k=args.top_k,
        data_dir=Path(args.data_dir),
        frequency=args.frequency,
        min_popularity=args.min_popularity,
        active_only=not args.include_stale,
        popularity_boost=not args.no_popularity_boost,
    )

    if not results:
        print("No results found.")
        return

    print(_format_results(results, as_json=args.json))


if __name__ == "__main__":
    main()

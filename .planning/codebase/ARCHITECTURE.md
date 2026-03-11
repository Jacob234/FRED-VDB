# Architecture

**Analysis Date:** 2026-03-11

## Pattern Overview

**Overall:** Two-phase batch pipeline (Ingest + Search) with shared data models and a file-based vector store

**Key Characteristics:**
- Batch ingest pipeline with 6 sequential phases, each checkpointed to SQLite for resumability
- Stateless search layer that reads from the pre-built LanceDB vector index
- No server process or long-running services; CLI-driven with library API fallback
- Single-package monolith (`fred_search/`) with internal modules prefixed by `_` for private helpers
- All external API interaction isolated behind `FREDClient`; all persistence isolated behind `IngestState`

## Layers

**External API Layer:**
- Purpose: Communicate with the FRED REST API (https://api.stlouisfed.org/fred)
- Location: `fred_search/_client.py`
- Contains: `FREDClient` class with rate limiting (token bucket, 85 req/min), exponential backoff retry (5 attempts), automatic pagination, and connection pooling via `httpx.Client`
- Depends on: `httpx` (HTTP client)
- Used by: `fred_search/ingest.py` (phases 1, 2, 3, 4.5)

**State / Persistence Layer:**
- Purpose: Track ingest progress in SQLite for resumability; store raw API responses
- Location: `fred_search/_state.py`
- Contains: `IngestState` class managing 5 tables: `ingest_runs`, `releases`, `categories`, `series`, `series_tags`. Uses WAL journal mode and `INSERT OR IGNORE` for idempotent writes.
- Depends on: `sqlite3` (stdlib)
- Used by: `fred_search/ingest.py` (all phases)

**Data Model Layer:**
- Purpose: Define the core domain objects shared across ingest and search
- Location: `fred_search/models.py`
- Contains: `FREDSeriesMetadata` (ingest-time representation) and `FREDSearchResult` (search-time representation) as `@dataclass` classes
- Depends on: Nothing (stdlib only)
- Used by: `fred_search/ingest.py`, `fred_search/search.py`, `fred_search/_filters.py`

**Filtering Layer:**
- Purpose: Reduce ~840K raw series to ~35-50K high-quality series before embedding
- Location: `fred_search/_filters.py`
- Contains: `FilterConfig` dataclass, `FilterStats` dataclass, 5 individual filter functions, and `apply_filters()` pipeline entry point
- Depends on: `fred_search/models.py`
- Used by: `fred_search/ingest.py` (phase 4)

**Query Enhancement Layer:**
- Purpose: Expand finance/economics abbreviations in search queries before embedding
- Location: `fred_search/_abbreviations.py`
- Contains: `EXPANSIONS` dict (94 unconditional abbreviation mappings), `CONDITIONAL_EXPANSIONS` dict (5 context-dependent mappings), `expand_query()` function
- Depends on: `re` (stdlib)
- Used by: `fred_search/search.py`

**Ingest Pipeline Layer:**
- Purpose: Orchestrate the full fetch-filter-embed-store pipeline
- Location: `fred_search/ingest.py`
- Contains: 6 phase functions (`_fetch_releases`, `_fetch_series_by_releases`, `_fetch_series_by_categories`, `_load_and_filter`, `_enrich_tags`, `_embed`, `_store_lancedb`), plus `run_ingest()` public API and `main()` CLI entry point
- Depends on: `_client.py`, `_state.py`, `_filters.py`, `models.py`, `sentence-transformers`, `lancedb`, `numpy`
- Used by: CLI (`fred-ingest` command), library consumers

**Search Layer:**
- Purpose: Accept natural language queries and return ranked FRED series
- Location: `fred_search/search.py`
- Contains: `FREDSearcher` class (stateful, keeps model in memory), `search_fred()` convenience function (stateless, loads model per call), `_build_where()` filter builder, `_format_results()` CLI formatter, `main()` CLI entry point
- Depends on: `_abbreviations.py`, `models.py`, `lancedb`, `sentence-transformers`, `pandas`
- Used by: CLI (`fred-search` command), library consumers

**Public API Layer:**
- Purpose: Expose clean public interface from the package
- Location: `fred_search/__init__.py`
- Contains: Re-exports of `search_fred`, `FREDSearcher`, `run_ingest`, `FREDSeriesMetadata`, `FREDSearchResult`
- Depends on: All other modules
- Used by: External consumers via `from fred_search import ...`

## Data Flow

**Ingest Flow (one-time batch, ~hours with API rate limiting):**

1. `run_ingest()` in `fred_search/ingest.py` creates `IngestState` (SQLite) and `FREDClient` (httpx)
2. **Phase 1** — `_fetch_releases()`: Fetches all ~350 FRED releases via `client.get_all_releases()`, registers in SQLite
3. **Phase 2** — `_fetch_series_by_releases()`: For each pending release, fetches all series via `client.get_release_series()`, stores raw JSON in SQLite (`INSERT OR IGNORE` deduplicates)
4. **Phase 3** — `_fetch_series_by_categories()`: BFS traversal of FRED category tree starting from root (category 0), fetches series per category, supplements phase 2 with ~5% additional series
5. **Phase 4** — `_load_and_filter()`: Loads all raw series from SQLite, parses into `FREDSeriesMetadata`, runs `apply_filters()` pipeline (discontinued -> stale -> low-popularity -> short-span -> SA/NSA dedup)
6. **Phase 4.5** (optional) — `_enrich_tags()`: Fetches per-series tags from FRED API for filtered series (~1 API call per series, most expensive phase)
7. **Phase 5** — `_embed()`: Loads `all-MiniLM-L6-v2` model, constructs embedding text via `build_embedding_text()` (title + notes[:500] + tags + units + frequency), batch encodes with normalized embeddings (384-dim)
8. **Phase 6** — `_store_lancedb()`: Writes records (metadata + 384-dim vector) to LanceDB table `fred_series` at `data/fred_vector_index/`, mode="overwrite"

**Search Flow (milliseconds, stateless):**

1. User provides natural language query string
2. `expand_query()` in `_abbreviations.py` expands finance abbreviations inline (e.g., "CRE" -> "CRE (commercial real estate)")
3. Query is embedded with same `all-MiniLM-L6-v2` model (normalized)
4. `_build_where()` constructs SQL WHERE clause for LanceDB (frequency, popularity, observation_end recency)
5. LanceDB vector search with `prefilter=True`: fetches `top_k * 3` candidates when popularity boosting is on
6. L2 distance from LanceDB is converted to cosine similarity: `cos_sim = 1 - (l2^2 / 2)` (works because vectors are unit-normalized)
7. If `popularity_boost=True`, score is adjusted: `cos_sim * (1 + log(popularity + 1) / 10)`
8. Results sorted by boosted score descending, trimmed to `top_k`, returned as `list[FREDSearchResult]`

**State Management:**
- **Ingest state**: SQLite database at `data/fred_ingest_state.db` tracks which releases/categories have been fetched, stores raw JSON for all discovered series, tracks tags. Enables resumability after interruption.
- **Vector index**: LanceDB at `data/fred_vector_index/fred_series.lance` stores the final embedded corpus. Fully overwritten on each ingest run.
- **No runtime state**: Search is stateless (reads LanceDB). `FREDSearcher` holds the model in memory for multi-query sessions but has no mutable state.

## Key Abstractions

**FREDSeriesMetadata:**
- Purpose: Represents a single FRED economic data series during ingest
- Examples: `fred_search/models.py` lines 14-77
- Pattern: `@dataclass` with `from_api_response()` classmethod factory for parsing FRED API JSON

**FREDSearchResult:**
- Purpose: Represents a single search result returned to the user
- Examples: `fred_search/models.py` lines 80-115
- Pattern: `@dataclass` with `as_dict()` for JSON serialization

**FREDClient:**
- Purpose: Encapsulates all FRED API interaction with rate limiting and retry
- Examples: `fred_search/_client.py` lines 40-214
- Pattern: Context manager (`__enter__`/`__exit__`), reusable `httpx.Client` for connection pooling, generic `_paginate()` iterator for all list endpoints

**IngestState:**
- Purpose: SQLite-backed checkpoint/resume system for the multi-phase ingest
- Examples: `fred_search/_state.py` lines 71-295
- Pattern: Context manager, schema auto-migration on init, `INSERT OR IGNORE` for idempotent writes, streaming iteration via batched `LIMIT/OFFSET`

**FilterConfig:**
- Purpose: Tunable parameters for the filter pipeline
- Examples: `fred_search/_filters.py` lines 34-43
- Pattern: `@dataclass` with sensible defaults (min_popularity=5, max_stale_days=730, dedup_seasonal_adjustment=True)

**FREDSearcher:**
- Purpose: Stateful search client that keeps embedding model loaded across queries
- Examples: `fred_search/search.py` lines 38-194
- Pattern: Initialized once with `data_dir`, loads LanceDB table and SentenceTransformer model, exposes `search()` method

## Entry Points

**CLI: `fred-ingest`:**
- Location: `fred_search/ingest.py:main()` (line 483)
- Triggers: `fred-ingest` command (registered in `pyproject.toml` `[project.scripts]`)
- Responsibilities: Parse CLI args (api-key, data-dir, min-popularity, skip-categories, enrich-tags, dry-run, force, log-level), configure logging, call `run_ingest()`

**CLI: `fred-search`:**
- Location: `fred_search/search.py:main()` (line 305)
- Triggers: `fred-search` command (registered in `pyproject.toml` `[project.scripts]`)
- Responsibilities: Parse CLI args (query, top-k, data-dir, frequency, min-popularity, include-stale, no-popularity-boost, json), call `search_fred()`, format and print results

**Library: `run_ingest()`:**
- Location: `fred_search/ingest.py:run_ingest()` (line 391)
- Triggers: `from fred_search import run_ingest; run_ingest(api_key="...")`
- Responsibilities: Full ingest pipeline orchestration

**Library: `search_fred()`:**
- Location: `fred_search/search.py:search_fred()` (line 231)
- Triggers: `from fred_search import search_fred; search_fred("query")`
- Responsibilities: Convenience function; creates a `FREDSearcher` per call

**Library: `FREDSearcher`:**
- Location: `fred_search/search.py:FREDSearcher` (line 38)
- Triggers: `from fred_search import FREDSearcher; s = FREDSearcher(); s.search("query")`
- Responsibilities: Stateful multi-query search with model kept in memory

## Error Handling

**Strategy:** Fail-fast for configuration errors; log-and-continue for per-item API failures during ingest

**Patterns:**
- `FREDAPIError` exception for non-retryable FRED API errors (400, 403, 404) in `fred_search/_client.py`
- Per-release and per-category error tracking in SQLite (`status='error'`, `error_msg` column) so failed items can be retried on next run
- `RuntimeError` with install instructions when optional heavy dependencies (`sentence-transformers`, `lancedb`) are not installed (lazy imports in `fred_search/ingest.py` and `fred_search/search.py`)
- `FileNotFoundError` when LanceDB index does not exist at search time, with guidance to run `fred-ingest` first
- Network errors (`httpx.TimeoutException`, `httpx.NetworkError`) caught and retried with exponential backoff in `FREDClient._get()`
- Filter pipeline never raises; unparseable dates are kept (benefit of the doubt) in `fred_search/_filters.py`

## Cross-Cutting Concerns

**Logging:** Standard library `logging` module throughout. Each module creates its own logger via `logging.getLogger(__name__)`. CLI entry points configure root logger with timestamp format. Default level: INFO for ingest, WARNING for search CLI.

**Validation:** Minimal explicit validation. `FREDSeriesMetadata.from_api_response()` handles missing/null fields with defaults. `FilterConfig` uses dataclass defaults. No schema validation library (pydantic, etc.) is used.

**Authentication:** Single FRED API key passed via `--api-key` CLI flag or `FRED_API_KEY` environment variable. Key is passed to `FREDClient` constructor and included as `api_key` query parameter on every request. No OAuth, no token refresh.

---

*Architecture analysis: 2026-03-11*

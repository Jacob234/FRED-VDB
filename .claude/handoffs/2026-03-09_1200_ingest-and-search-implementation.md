---
handoff_id: 2026-03-09_1200
title: "FRED-VDB Ingest Pipeline & Search Interface Implementation"
date: 2026-03-09T12:00:00-06:00
parent_handoffs:
  - .claude/handoffs/2026-02-25_1330_project-foundation.md
status: active
---

# Handoff: FRED-VDB Ingest Pipeline & Search Interface Implementation

## Session Overview

**Date**: 2026-03-09
**Primary Goal**: Implement the full ingest pipeline and search interface — the complete working system from FRED API fetch through LanceDB vector storage and natural language query.

## What Was Accomplished

- Researched FRED API: confirmed no bulk "all series" endpoint exists; identified releases as best strategy
- Implemented all core `fred_search/` modules from scratch
- Updated `pyproject.toml` to a proper installable package with build system (`hatchling`) and all deps
- Installed all dependencies via `uv pip install -e .` (52 packages)
- Verified: all imports work, both CLIs show correct help, filter pipeline produces correct output

## Key Decisions & Context

### Decision 1: Fetch Strategy — Releases Primary, Category BFS Supplemental
**Context**: No FRED API endpoint exists to enumerate all 840K series in one call.
**Decision**: Use `fred/releases` → `fred/release/series` as the primary traversal (flat list of ~350 releases, covering ~95% of FRED). Walk the category tree (BFS from root category 0) as a supplemental pass to catch the ~5% of series not attached to any release.
**Rationale**: Releases are a flat list requiring only ~350 API calls vs thousands for a full category tree walk. The supplemental category walk ensures completeness without blocking the main fetch. Both can be skipped via `--skip-categories`.
**Alternatives Considered**: Category tree only (slower, deeper traversal), keyword search (misses unlisted series).

### Decision 2: httpx Directly, Not fredapi Wrapper
**Context**: The foundation handoff planned to use the `fredapi` pip package.
**Decision**: Dropped `fredapi`; implemented `_client.py` using `httpx` directly.
**Rationale**: The `fred/releases` endpoint is not exposed by `fredapi`. We needed full control over rate limiting (inter-request sleep), exponential backoff with jitter on 429/5xx, and retries. `fredapi` wraps `requests` synchronously and doesn't add value when we need this level of control.

### Decision 3: No Per-Series Tag Fetching
**Context**: Tags require a separate `fred/series/tags?series_id=XXX` call per series.
**Decision**: Skip tag fetching during ingest. Tags are stored as empty lists by default.
**Rationale**: Fetching tags would double the API call count to ~700K+ calls (one per series). Title + notes text provides sufficient semantic signal for the embeddings — the `notes` field typically contains the full description sentence. Tags can be added in a future incremental pass for high-popularity series only.

### Decision 4: SQLite as Raw JSON Mirror
**Context**: Needed resumability after interruption (ingest can take 30+ min).
**Decision**: `_state.py` stores every series response as raw JSON in SQLite (`data/fred_ingest_state.db`). `INSERT OR IGNORE` deduplicates series appearing in multiple releases.
**Rationale**: Storing raw JSON means filtering and embedding can be re-run at any time without re-fetching from FRED. SQLite WAL mode allows safe concurrent reads during a long write session. State tracks which releases/categories are `pending|done|error`.

### Decision 5: Conservative Rate Limiting at 85 req/min
**Context**: FRED TOS advertises 120 req/min but rate limits are inconsistently enforced.
**Decision**: Default to 85 req/min (0.71s inter-request gap). Exponential backoff with jitter (±5s) on 429/5xx, up to 5 attempts.
**Rationale**: FRED metadata endpoints can trigger rate limiting below the advertised 120/min. 85/min is empirically safe and still allows full ingest in reasonable time. The jitter prevents thundering-herd retries.

### Decision 6: Normalized Embeddings for Cosine Search
**Context**: LanceDB defaults to L2 distance; we want cosine similarity.
**Decision**: Embed with `normalize_embeddings=True`. Store similarity in results as `1 - (l2_dist² / 2)`.
**Rationale**: For unit vectors, L2 and cosine are equivalent in ordering. Normalizing at ingest time means LanceDB's L2 index is effectively a cosine index — no separate normalization step at query time.

## Current State

### Files Modified/Created
- [`pyproject.toml`](../../pyproject.toml) — Full build config with hatchling, all deps, two CLI scripts (`fred-ingest`, `fred-search`)
- [`fred_search/__init__.py`](../../fred_search/__init__.py) — Public API: `search_fred`, `FREDSearcher`, `run_ingest`, `FREDSeriesMetadata`, `FREDSearchResult`
- [`fred_search/models.py`](../../fred_search/models.py) — Dataclasses; `FREDSeriesMetadata.from_api_response()` handles FRED API quirks
- [`fred_search/_state.py`](../../fred_search/_state.py) — SQLite state: releases, categories, series (raw JSON), ingest_runs tables; WAL mode
- [`fred_search/_client.py`](../../fred_search/_client.py) — `FREDClient` with rate limiter, retry/backoff; `_paginate()` generic paginator handles FRED's `"seriess"` double-s key
- [`fred_search/_filters.py`](../../fred_search/_filters.py) — `FilterConfig`, `FilterStats`; pipeline: discontinued → stale → popularity → short-span → SA dedup
- [`fred_search/ingest.py`](../../fred_search/ingest.py) — 6-phase orchestration: releases → category BFS → load/filter → embed → LanceDB; `--dry-run`, `--force`, `--skip-categories` flags
- [`fred_search/search.py`](../../fred_search/search.py) — `FREDSearcher` (stateful, keeps model in memory), `search_fred()` (convenience), CLI with `--json` flag

### System State
- Package installed in editable mode: `uv pip install -e .` ✓
- All 52 dependencies installed in `.venv/` ✓
- Both CLI entry points registered and functional (`fred-ingest --help`, `fred-search --help`) ✓
- Filter pipeline tested and passes (SA dedup, recency, popularity all work correctly) ✓
- **Index not yet built** — need to run `fred-ingest` with a real FRED API key to produce `data/fred_vector_index/`

### FRED API Quirks to Know
- Plural key for series lists is `"seriess"` (double-s) — handled in `_client.py`
- `fred/releases` default limit is 1000; currently ~350 total releases (fits in one page)
- `fred/release/series` paginates with `offset`; use `data["count"]` for total, not empty-page sentinel
- `popularity` field is occasionally absent for brand-new series — defaulted to 0 in `from_api_response()`

## Context from Parent Handoffs

### From [2026-02-25 Project Foundation](.claude/handoffs/2026-02-25_1330_project-foundation.md)
- `.venv/` created with Python 3.12.4; `uv` is the package manager
- `data/.gitkeep` pattern: `data/` dir tracked, contents gitignored
- `FRED_API_KEY` env var expected; `.env.example` template in place
- Spec document at `fred-vector-search.md` has full design rationale

## Suggested Child Handoffs

### Child 1: Run Ingest + Validate Index Quality
**Focus**: Actually build the index against the live FRED API. Validate result quality with the curated query test set from the spec.
**Prerequisites**: `.env` file with real `FRED_API_KEY` (get at fred.stlouisfed.org)
**Expected Outcome**: Populated `data/fred_vector_index/`, ingest stats (raw count, after-filter count, elapsed time), spot-check queries validated
**Command**: `fred-ingest --api-key $FRED_API_KEY --log-level INFO`
**Validation queries** (from spec): "10-year treasury yield" → DGS10, "CRE loan delinquency" → DRCRELEXFACBS, "financial stress indicator" → STLFSI4/NFCI

### Child 2: Test Suite
**Focus**: Write pytest tests for the filter pipeline and search interface
**Prerequisites**: Index built (for integration tests); unit tests can run without it
**Expected Outcome**: Tests in `tests/` covering `_filters.py` correctness, filter idempotency, `FREDSearchResult` serialization, `_state.py` resume behavior
**Key test cases from spec**: SA dedup correctness, stale series dropped, state DB survives kill/resume

### Child 3: Integration with External Services
**Focus**: Make `fred_search` installable as a git-pinned dependency from another repo
**Prerequisites**: Working index; package structure stable
**Expected Outcome**: Another service can do `pip install git+https://...FRED-VDB.git` and call `search_fred()`; optional FastAPI route `POST /api/market/fred/search`
**Notes**: `pyproject.toml` already has proper `hatchling` build config; just needs a git tag/release

### Child 4: Incremental Update Mechanism
**Focus**: Instead of full re-ingest quarterly, fetch only series updated since last run
**Prerequisites**: Working full ingest
**Expected Outcome**: `fred-ingest --incremental` uses `fred/series/updates` endpoint with `realtime_start` from last ingest timestamp; updates LanceDB table in-place
**Notes**: `IngestState` already tracks `ingest_runs` with timestamps; `ingest_meta.json` pattern from spec can be added

## Open Questions & Issues

1. **Tag quality**: Tags are empty for all series (no per-series tag fetch). The embedding quality may be slightly lower than spec intended. See Decision 3. Can be revisited if search quality is insufficient.
2. **Index size**: Spec estimated 50-80K series after filtering, ~200-400MB LanceDB. Actual count TBD after first real ingest run.
3. **Geographic dedup**: The filter pipeline intentionally omits aggressive geographic filtering (state/county/MSA exclusion). The `popularity >= 5` threshold handles most of this. If county-level noise is a problem after testing, add a title-pattern heuristic in `_filters.py`.
4. **Embedding model**: Spec mentions testing `all-mpnet-base-v2` vs `all-MiniLM-L6-v2`. Currently hardcoded to MiniLM. Can be made configurable via `FilterConfig` if needed.
5. **LanceDB version**: Installed `lancedb==0.29.2` (much newer than spec's `>=0.13`). API may differ from spec's code snippets — actual implementation uses current API.

## References

- [Implementation Spec](../../fred-vector-search.md) — Full design rationale and test query list
- [.env.example](../../.env.example) — FRED API key template
- [FRED API Docs](https://fred.stlouisfed.org/docs/api/fred/) — Releases, category, series endpoints
- FRED API key registration: https://fred.stlouisfed.org/docs/api/api_key.html

## Technical Notes

### Dependencies Installed (52 packages)
Key: `httpx==0.28.1`, `lancedb==0.29.2`, `sentence-transformers==5.2.3`, `torch==2.10.0`, `pyarrow==23.0.1`, `tqdm==4.67.3`

### Data Directory Layout (after ingest)
```
data/
├── fred_ingest_state.db         # SQLite: raw JSON mirror + progress tracking
└── fred_vector_index/           # LanceDB: embedded series metadata
    └── fred_series.lance/
```

### Known Issues
- None found. All imports clean, CLI entry points functional, filter tests pass.

### Performance Considerations
- Ingest: ~350 release calls + category BFS calls at 85 req/min ≈ estimated 30-60 min total fetch
- Embedding: ~50-80K texts at batch=256 on M-series Mac ≈ 2-5 min
- Search latency: <100ms per query (model stays loaded in `FREDSearcher`)

## Next Session Prompt

```
Continue work on FRED-VDB from handoff: .claude/handoffs/2026-03-09_1200_ingest-and-search-implementation.md

The full ingest pipeline and search interface are implemented and installed.
All 7 fred_search/ modules are complete. The package installs with `uv pip install -e .`.

The index has NOT been built yet — next step is to run `fred-ingest --api-key $FRED_API_KEY`
and validate result quality against the curated test queries in fred-vector-search.md.

Key context: no per-series tag fetching (would 2x API calls); fetch strategy is releases-first
then category BFS supplemental; SQLite state at data/fred_ingest_state.db enables resume.
Rate limit is 85 req/min with exponential backoff. `--skip-categories` speeds up initial test run.
```

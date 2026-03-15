---
handoff_id: 2026-03-14_1600
title: Documentation, CLI Cheatsheet & FRED API Architecture Analysis
date: 2026-03-14T16:00:00-06:00
parent_handoffs:
  - .claude/handoffs/2026-03-11_1400_query-expansion-abbreviations.md
  - .claude/handoffs/2026-03-10_1500_enrichment-run-and-abbreviation-gap.md
  - .claude/handoffs/2026-03-09_1530_ingest-run-and-search-validation.md
  - .claude/handoffs/2026-03-09_1200_ingest-and-search-implementation.md
  - .claude/handoffs/2026-02-25_1330_project-foundation.md
status: active
---

# Handoff: Documentation, CLI Cheatsheet & FRED API Architecture Analysis

## Session Overview

**Date**: 2026-03-14
**Primary Goal**: Create project documentation — CLI cheatsheet, README, and research the FRED API's own search architecture for comparison

## What Was Accomplished

- **CLI cheatsheet** (`cli-cheatsheet.html`): Single-page dark-themed HTML reference for both `fred-ingest` and `fred-search` commands, with syntax-highlighted examples, flag tables, and quick setup section. Zero-dependency (no JS, CSS-only styling).

- **FRED API architecture research**: Investigated the `series/search` endpoint's methodology by reading the official FRED docs. Key findings:
  - FRED offers two search modes: `full_text` (default, stemmed keyword matching) and `series_id` (substring/wildcard)
  - Full-text searches title, units, frequency, and tags — but **not** the `notes` field
  - Ranking uses an opaque `search_rank` score; the algorithm is undocumented
  - Likely BM25 on Solr/Elasticsearch (standard choice for this type of service), but FRED has never confirmed this
  - Stemming is confirmed (morphological, not semantic: "Industry" → "Industries")

- **README.md**: Comprehensive project README with:
  - Usage example with sample output
  - Side-by-side comparison table: FRED API search vs FRED-VDB (algorithm, fields, capabilities)
  - "Where Each Wins" guidance for when to use which approach
  - Full CLI reference for both commands
  - Python API examples
  - Architecture overview (ingest pipeline, filter pipeline, embedding strategy, scoring formula)
  - Tech stack rationale table

## Key Decisions & Context

### Decision 1: FRED API Comparison as README Section
**Context**: User asked about the FRED API search methodology during conversation
**Decision**: Folded the research into a dedicated README section rather than a separate doc
**Rationale**: The comparison is the project's core value proposition — it belongs front-and-center

### Decision 2: "Where Each Wins" Framing
**Context**: FRED-VDB doesn't replace the API — each has strengths
**Decision**: Documented both approaches honestly with clear guidance on when to use which
**Rationale**: Users need to understand this is a complement to FRED search, not a replacement. FRED API wins for known-concept lookup and real-time coverage; FRED-VDB wins for conceptual queries and notes field access.

### Decision 3: Documenting the Scoring Formula
**Context**: FRED's `search_rank` is opaque; FRED-VDB's scoring is transparent
**Decision**: Included the exact formula `cos_sim × (1 + log(pop + 1) / 10)` in the README
**Rationale**: Explainability matters for research tooling — users need to understand why results rank as they do

## Current State

### Files Created/Modified
- [cli-cheatsheet.html](cli-cheatsheet.html) — Single-page HTML CLI reference (already existed from prior work, overwritten with current version)
- [README.md](README.md) — New comprehensive project README

### System State
- **Index**: Built and operational at `data/fred_vector_index/` (~90MB, 33,230 series)
- **State DB**: `data/fred_ingest_state.db` with 840K raw series + tags
- **Code**: All 8 modules in `fred_search/` implemented and working
- **Abbreviation expansion**: Implemented in `_abbreviations.py`, wired into search (committed in prior session or pending — check git status)
- **Git**: Uncommitted changes include `_filters.py`, `_state.py`, `ingest.py`, `models.py`, `search.py`, plus new files `_abbreviations.py`, `cli-cheatsheet.html`, `README.md`, `uv.lock`

### What's Working
- `fred-ingest` — full 6-phase pipeline, resumable
- `fred-search` — vector search with popularity boost, abbreviation expansion, frequency/popularity filtering
- Both CLI entry points functional
- Python API via `from fred_search import search_fred, FREDSearcher`

## Project History (Full Lineage)

```
2026-02-25  Project Foundation Setup
    └── 2026-03-09  Ingest Pipeline & Search Implementation (7 modules)
        └── 2026-03-09  First Ingest Run & Validation (840K fetched, 11,827 filtered)
            └── 2026-03-10  Tag Enrichment & Abbreviation Gap (33,230 series, scoring)
                └── 2026-03-11  Query Expansion for Abbreviations (75 terms)
                    └── 2026-03-14  Documentation & API Analysis ← YOU ARE HERE
```

### Key Milestones
| Date | Event | Impact |
|---|---|---|
| Feb 25 | Repo initialized | `uv`, `.gitignore`, directory structure |
| Mar 9 | All code written | 7 modules, 2 CLI entry points |
| Mar 9 | First ingest run | 840K series fetched, 11,827 indexed |
| Mar 10 | Tag enrichment | 33,230 series, popularity-boosted scoring |
| Mar 11 | Abbreviation expansion | 75 finance terms, context-gated conditionals |
| Mar 14 | Documentation | README, cheatsheet, API architecture research |

## Suggested Child Handoffs

### Child 1: Test Suite
**Focus**: pytest tests for filter pipeline, search quality regression, abbreviation expansion
**Prerequisites**: All code committed and stable
**Expected Outcome**: Curated test queries from spec validated; filter edge cases covered; CI-ready
**Notes**: Suggested in every prior handoff (5 of 5) but never implemented. This is the highest-priority gap.

### Child 2: Commit Cleanup & Git Hygiene
**Focus**: Stage and commit all pending changes (abbreviations, docs, modified modules); ensure git history is clean
**Prerequisites**: Review `git status` / `git diff` for uncommitted work
**Expected Outcome**: All work on main with conventional commit messages; no uncommitted changes

### Child 3: Distribution & Packaging
**Focus**: PyPI publication, GitHub Release with pre-built index download, `fred-vdb-download-index` CLI helper
**Prerequisites**: Test suite passing, git clean
**Expected Outcome**: `pip install fred-vdb` works; users can download pre-built index without running ingest

### Child 4: Incremental Update Mechanism
**Focus**: `--incremental` flag using `fred/series/updates` endpoint to avoid full re-ingest
**Prerequisites**: Stable index format
**Expected Outcome**: 5-minute refresh instead of 30-minute full rebuild

### Child 5: State DB Normalization
**Focus**: Normalize the SQLite series table with real columns (see `project_normalize_state_db.md` in memory)
**Prerequisites**: None (independent improvement)
**Expected Outcome**: Queryable state DB; faster filtering; reduced JSON parsing overhead

## Open Questions & Issues

1. **Uncommitted work**: Multiple files have pending changes from prior sessions — need to audit what's committed vs staged vs untracked
2. **DGS10 ranking**: Still not #1 for "10-year treasury yield" — may need embedding text tuning or title-weighted scoring
3. **BAMLH0A0HYM2 missing**: High-yield spread series not appearing in spec test queries — investigate if filtered out or embedding distance issue
4. **Filter aggressiveness**: 840K → 33,230 is aggressive; some users may want broader coverage. Consider a `--liberal` preset.
5. **Notes field truncation at 500 chars**: Works well empirically but never validated whether longer truncation improves recall

## References

- [README.md](README.md) — Project README with full documentation
- [cli-cheatsheet.html](cli-cheatsheet.html) — Single-page HTML CLI reference
- [fred-vector-search.md](fred-vector-search.md) — Original design spec with 10 test queries
- [FRED API series/search docs](https://fred.stlouisfed.org/docs/api/fred/series_search.html) — Official endpoint documentation
- [fred_search/_client.py](fred_search/_client.py) — Custom FRED REST client
- [fred_search/_abbreviations.py](fred_search/_abbreviations.py) — Finance abbreviation expansion (75 terms)

## Technical Notes

### FRED API Architecture (from this session's research)
- REST API at `https://api.stlouisfed.org/fred/`
- Three organizational hierarchies: Sources (118), Releases (~350), Categories (tree)
- Series belongs to exactly one release, can appear in multiple categories
- `series/search` endpoint: stemmed keyword matching on {title, units, frequency, tags} — NOT notes
- Ranking: opaque `search_rank`, likely BM25 on Solr/Elasticsearch
- Rate limit: 120 req/min advertised, ~85 practical; API key auth via query param
- Pagination: `offset` + `limit` (max 1000) with `count` in response
- Quirk: series lists use key `seriess` (double-s)

### Dependencies
- Python >= 3.12, `uv` package manager
- `httpx`, `lancedb`, `sentence-transformers`, `tqdm`, `pyarrow`, `pandas`
- Embedding model: `all-MiniLM-L6-v2` (384-dim, 22M params, downloads on first use)

### Known Issues
- No test suite (suggested 5x, never created)
- Some files may have uncommitted changes from multiple sessions
- `search_fred()` convenience function re-loads model each call (use `FREDSearcher` for batches)

## Next Session Prompt

```
Continuing FRED-VDB from .claude/handoffs/2026-03-14_1600_documentation-and-api-analysis.md

The project has a working ingest pipeline, vector search with popularity boosting and
abbreviation expansion, and full documentation (README + CLI cheatsheet). All code is in
fred_search/ (8 modules). Index has 33,230 series from 840K raw.

Priority next steps:
1. Audit git status — commit any uncommitted work with conventional commits
2. Build pytest test suite (suggested in all 5 prior handoffs, never done)
3. Validate the 10 spec test queries from fred-vector-search.md against current index
```

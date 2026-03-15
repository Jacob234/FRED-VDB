---
handoff_id: 2026-03-10_1500
title: "Tag Enrichment Run & Abbreviation Gap Discovery"
date: 2026-03-10T15:00:00-06:00
parent_handoffs:
  - .claude/handoffs/2026-03-09_1530_ingest-run-and-search-validation.md
status: active
---

# Handoff: Tag Enrichment Run & Abbreviation Gap Discovery

## Session Overview

**Date**: 2026-03-10
**Primary Goal**: Enrich the FRED vector index with more series (lower popularity threshold) and richer embedding text (per-series tags), then validate search quality.

## What Was Accomplished

- **Implemented tag enrichment phase** (`--enrich-tags`) — new Phase 4.5 in the ingest pipeline that fetches per-series tags from the FRED API. Resumable: skips series that already have tags in the state DB.
- **Implemented popularity-boosted scoring** — `score = cosine_sim * (1 + log(pop+1) / 10)`. Fetches 3x candidates from LanceDB, re-ranks, returns top_k. Moved UNRATE from #34 to #5 for "unemployment rate".
- **Fixed tqdm bool() crash** — `tqdm` objects raise `TypeError` on `bool()` when created without an iterable. Changed `if pbar:` to `if pbar is not None:` in category BFS.
- **Ran full enriched ingest** — categories + tags + min_popularity=2. Completed in ~10.3 hours (616 minutes). Process crashed once mid-run from network timeout; resumed cleanly.
- **Expanded index**: 11,827 → **33,230 series** with tags populated.
- **Discovered abbreviation gap** — `all-MiniLM-L6-v2` cannot match finance abbreviations to their full forms (CRE↔commercial real estate: 0.217 similarity, MBS↔mortgage backed securities: 0.123). This is a fundamental model limitation, not a regression from enrichment.
- **Committed** all changes in one atomic commit on `main`.

## Key Decisions & Context

### Decision 1: `--enrich-tags` as Opt-In Flag
**Context**: Tag enrichment adds hours of API calls (~1 call per series at 85 req/min).
**Decision**: Made it opt-in rather than default.
**Rationale**: The base ingest completes in ~20 minutes; forcing hours of tag fetching by default would surprise users. Tags are a quality enhancement, not a requirement.

### Decision 2: Popularity Boost Formula
**Context**: Headline series (UNRATE, DGS10) were buried by niche demographic/maturity variants with richer embedding text.
**Decision**: `score = cosine_sim * (1 + log(popularity + 1) / 10)`. Fetch 3x top_k candidates, re-rank, return top_k.
**Rationale**: Multiplicative boost with log dampening. Pop=0→1.0x, pop=10→1.24x, pop=50→1.39x, pop=100→1.46x. Meaningful but not overwhelming. Default on, `--no-popularity-boost` to disable.
**Trade-off**: A very popular but semantically weak match could outrank a perfect-but-obscure match. The 3x fetch window limits this — a series must still be in the similarity ballpark.

### Decision 3: Restructured FREDClient Lifecycle
**Context**: Tag enrichment needs API access after filtering (Phase 4). Previously, the client closed after Phase 3.
**Decision**: Moved `_load_and_filter()` and `_enrich_tags()` inside the `with FREDClient` block. Embed + LanceDB write remain outside (no API needed).

### Decision 4: min_popularity=2 for Overnight Run
**Context**: Previous run used min_popularity=5 (11,827 series). Options ranged from 1 (60-90K) to 5 (12K).
**Decision**: Used 2, yielding 33,230 series. Tag enrichment for 33K at ~2s/series ≈ 10 hours — fit within overnight window.

## Search Quality Results (After Enrichment)

| Query | Expected | Before (11K, no tags) | After (33K, tags, boost) | Verdict |
|-------|----------|----------------------|--------------------------|---------|
| "10-year treasury yield" | DGS10 | #14 | THREEFY10 #1, T10Y2Y #2, DGS10 ~#10 | Improved |
| "unemployment rate" | UNRATE | #34 | #5 | Much improved |
| "CRE loan delinquency" | DRCRELEXFACBS | #2 | DRSREACBS #1 (broader RE delinq) | Good |
| "financial stress indicator" | STLFSI4, NFCI | #1, #4 | **#1, #3** + KCFSI #4 | PASS |
| "housing starts" | HOUST | #1 | **#1** | PASS |
| "inflation expectations" | T5YIE, T10YIE, MICH | #17, #28, #26 | EXPINF1YR **#1**, EXPINF3YR #2 | Much improved |
| "REIT performance" | WILLREITIND | Not in DB | NASDAQNQMAREITT **#1** | Fixed (categories) |
| "high yield credit spread" | BAMLH0A0HYM2 | ~#11-15 | CROASMIDTIER #1 (mortgage HY) | Relevant |
| "multifamily lending" | SUBLPDRCSM | #2 | **#1** | PASS |
| "CRE credit stress" | conceptual | COMREPUSQ159N #1 | 0.32 sim — **REGRESSED** | Abbreviation gap |

### Abbreviation Gap Analysis

The "CRE credit stress" regression root cause: `all-MiniLM-L6-v2` cannot map abbreviations to full forms.

```
CRE    ↔ commercial real estate           sim=0.217
MBS    ↔ mortgage backed securities       sim=0.123
CMBS   ↔ commercial mortgage backed secs  sim=0.197
HY     ↔ high yield                       sim=0.220
IG     ↔ investment grade                 sim=0.152
GDP    ↔ gross domestic product           sim=0.638  ← only common ones work
CPI    ↔ consumer price index             sim=0.548  ← only common ones work
FFR    ↔ federal funds rate               sim=0.242
```

Using "commercial real estate credit stress" (spelled out) returns COMREPUSQ159N at #1 with 0.93 similarity — confirming the issue is abbreviation handling, not data quality.

## Current State

### Files Modified (This Session)
- [`fred_search/ingest.py`](../../fred_search/ingest.py) — Tag enrichment phase, tqdm fix, client lifecycle restructure
- [`fred_search/search.py`](../../fred_search/search.py) — Popularity-boosted scoring, `--no-popularity-boost` CLI flag
- [`fred_search/_state.py`](../../fred_search/_state.py) — `get_tags_for_series()`, `get_series_ids_with_tags()` helpers
- [`docs/plans/2026-03-09-overnight-enrichment-design.md`](../../docs/plans/2026-03-09-overnight-enrichment-design.md) — Design doc

### Generated Artifacts (gitignored)
- `data/fred_ingest_state.db` — SQLite with 840K raw series + 33K series_tags rows
- `data/fred_vector_index/fred_series.lance/` — LanceDB index with 33,230 embedded series (tags populated)

### Git State
```
23aa156 feat: add tag enrichment phase and popularity-boosted search scoring
9c741d0 feat: expose public API from fred_search package
200f0e9 feat: implement semantic search interface with CLI
...
```

### Ingest Statistics
```
Raw series fetched:       840,376
After stale filter:       ~292K
After popularity≥2:       ~34K
After short-span filter:  ~33.5K
After SA dedup:           33,230  ← final corpus
Tags enriched:            33,230 (all)
Embedding dimensions:     384
LanceDB index size:       ~90MB
Total ingest time:        616.1 minutes (~10.3 hours)
```

## Context from Parent Handoffs

### From [First Ingest Run & Search Validation](.claude/handoffs/2026-03-09_1530_ingest-run-and-search-validation.md)
- Initial run: 840K raw → 11,827 indexed with `--skip-categories` and min_popularity=5
- Two runtime bugs fixed: missing pandas dep, numpy array truthiness
- Search quality validated against 10 test queries — conceptual queries strong, generic queries weak
- Suggested: popularity-boosted scoring, full category ingest, tag enrichment

### From [Ingest & Search Implementation](.claude/handoffs/2026-03-09_1200_ingest-and-search-implementation.md)
- All 7 fred_search/ modules implemented
- Key decisions: releases-first fetch, httpx (not fredapi), normalized embeddings, SQLite JSON mirror
- 85 req/min rate limit, 5 retries with exponential backoff

## Suggested Child Handoffs

### Child 1: Query Expansion for Finance Abbreviations
**Focus**: Fix the abbreviation gap — CRE, MBS, CMBS, HY, IG, FFR don't match their full forms.
**Work Items**:
- Build a finance abbreviation dictionary (~50-100 entries)
- Add query expansion in `FREDSearcher.search()` before embedding
- Option A: Simple string replacement (`"CRE" → "CRE (commercial real estate)"`)
- Option B: Expand and embed both original + expanded, take max similarity
- Re-validate all 10 test queries after
**Prerequisites**: Current index exists (it does)
**Expected Outcome**: "CRE credit stress" returns COMREPUSQ159N in top 3

### Child 2: Distribution & Packaging
**Focus**: Make fred-vdb installable and shareable.
**Work Items**:
- Publish to PyPI (`uv build && uv publish`)
- Create GitHub Release with pre-built LanceDB index (~90MB compressed)
- Add `fred-vdb-download-index` CLI command for users who don't want to run 10-hour ingest
- Write README with demo GIF/asciinema
- Consider Hacker News "Show HN" post
**Prerequisites**: Search quality acceptable, abbreviation gap optionally fixed
**Expected Outcome**: `pip install fred-vdb && fred-search "inflation expectations"` works

### Child 3: Test Suite
**Focus**: pytest tests for filter pipeline, search interface, state management, and search quality regression.
**Prerequisites**: Index built, search bugs fixed
**Expected Outcome**: Tests in `tests/` covering filter correctness, tag enrichment resumability, popularity boost math, and the 10 curated test queries as regression tests.

### Child 4: Incremental Updates
**Focus**: `fred-ingest --incremental` using FRED's `series/updates` endpoint.
**Prerequisites**: Full ingest working (done)
**Expected Outcome**: Updates LanceDB in-place; IngestState already tracks timestamps.

## Open Questions & Issues

1. **Abbreviation handling**: Query expansion is the simplest fix. Should the dictionary be user-extensible (config file) or hardcoded? Hardcoded is simpler; config adds flexibility for domain-specific abbreviations.
2. **Embedding model upgrade**: `all-mpnet-base-v2` (5x larger) handles abbreviations marginally better. Worth testing, but query expansion is likely a bigger win.
3. **DGS10 still not #1**: For "10-year treasury yield", DGS10 lands ~#10. The series title is just "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Daily" with no "yield" in it. Yield spread series (T10Y2Y, T10YFF) rank higher because their titles/tags literally contain "yield". Query expansion or a "canonical series" boost could help.
4. **Index distribution**: The 90MB LanceDB index is the main adoption barrier. GitHub Releases supports files up to 2GB. Should we compress it? LZ4 on Lance files should get ~60% compression.

## References

- [Implementation Spec](../../fred-vector-search.md) — Full design rationale and test query list
- [Enrichment Design](../../docs/plans/2026-03-09-overnight-enrichment-design.md) — This session's design doc
- [Parent Handoff](./2026-03-09_1530_ingest-run-and-search-validation.md) — First ingest run
- [Grandparent Handoff](./2026-03-09_1200_ingest-and-search-implementation.md) — Pipeline implementation

## Technical Notes

### Runtime Profile (Enriched Run)
- Phase 1-2 (releases): 0 min (already done, resumable)
- Phase 3 (categories): ~30 min (5,181 categories, 4 errors)
- Phase 4 (load+filter): ~35 sec (840K → 33,230)
- Phase 4.5 (tags): ~10 hours (33,230 series at ~1.1s avg)
- Phase 5 (embed): ~1 min (33,230 texts, MPS GPU)
- Phase 6 (LanceDB): ~2 sec
- **Total: 616.1 minutes**

### Process Reliability
- The overnight run crashed once mid-tag-enrichment from a network timeout. Restarted the same command; it skipped all 10,378 already-tagged series and continued from 10,379. The resumability design worked as intended.
- `caffeinate -i -w <PID>` is needed to prevent macOS sleep during long runs.

### Abbreviation Similarity Table (for future reference)
Only GDP (0.638) and CPI (0.548) are above the useful threshold. All finance-specific abbreviations are below 0.25 — effectively random from the model's perspective.

## Next Session Prompt

```
Continue work on FRED-VDB from handoff: .claude/handoffs/2026-03-10_1500_enrichment-run-and-abbreviation-gap.md

The enriched index is built (33,230 series with tags, popularity-boosted scoring).
Search quality is strong except for finance abbreviations — "CRE", "MBS", "CMBS" etc.
don't match their full forms in the embedding model (all-MiniLM-L6-v2).

Priority: implement query expansion with a finance abbreviation dictionary to fix
"CRE credit stress" and similar queries. Then consider packaging for PyPI distribution.
```

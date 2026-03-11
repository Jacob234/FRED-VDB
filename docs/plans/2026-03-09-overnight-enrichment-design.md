# Overnight Enrichment Run — Design

**Date**: 2026-03-09
**Goal**: More series with richer embedding text for improved search quality.

## Changes

### 1. Tag Enrichment Phase (`ingest.py`)
New Phase 4.5 between filter and embed. For each filtered series without tags,
call `client.get_series_tags()` and store in `series_tags` table. Resumable —
skips series that already have tags. Triggered by `--enrich-tags` flag.

### 2. State DB Helpers (`_state.py`)
- `get_series_ids_with_tags()` — set of series IDs that have tags already
- `get_tags_for_series(series_id)` — load tags for one series

### 3. Popularity-Boosted Scoring (`search.py`)
`boosted = cosine_sim * (1 + log(popularity + 1) / 10)`
Fetch 3x top_k from LanceDB, re-rank by boosted score, return top_k.
Default on; `--no-popularity-boost` to disable.

## Overnight Command
```bash
nohup uv run fred-ingest --enrich-tags --min-popularity 2 > data/ingest_overnight.log 2>&1 &
```

## Estimated Time
~8-11 hours (30min categories + 7-10hr tags + 2min embed/store)

# Codebase Concerns

**Analysis Date:** 2026-03-11

## Tech Debt

**Uncommitted work on `main`:**
- Issue: `fred_search/search.py` has uncommitted changes (abbreviation expansion import and usage). The `fred_search/_abbreviations.py` file is untracked. These are working features but exist only in the working tree.
- Files: `fred_search/search.py`, `fred_search/_abbreviations.py`
- Impact: A `git checkout` or `git stash` would lose the abbreviation expansion feature. Other contributors pulling `main` would not have it.
- Fix approach: Stage and commit the changes and the new file.

**Dead code — `_default_searcher` module variable:**
- Issue: `_default_searcher: FREDSearcher | None = None` is declared at module level but never read or written. The `search_fred()` convenience function creates a new `FREDSearcher` on every call instead of caching in this variable.
- Files: `fred_search/search.py` (line 228)
- Impact: Every `search_fred()` call re-initializes the `SentenceTransformer` model (~1-2 seconds). This is documented in the docstring ("use FREDSearcher directly if issuing many queries") but the caching variable suggests the intent was to fix this and it was never completed.
- Fix approach: Either implement the singleton cache using `_default_searcher`, or remove the dead variable. If caching, add thread-safety guards or document single-thread-only use.

**`is_discontinued` never set to True:**
- Issue: `FREDSeriesMetadata.is_discontinued` defaults to `False` and `from_api_response()` never sets it. The comment in `from_api_response()` says "we derive the flag from the field" but the derivation logic is missing. The `filter_discontinued()` function in `_filters.py` checks this field but it will always be `False`.
- Files: `fred_search/models.py` (lines 27, 41-43), `fred_search/_filters.py` (line 83)
- Impact: The discontinued series filter is a no-op. Discontinued series survive into the index. The stale filter partially compensates (discontinued series have old `observation_end`), but series discontinued recently would leak through.
- Fix approach: Parse the FRED API response to detect discontinued status. The FRED API does not have an explicit `is_discontinued` field; derive it from `observation_end` being far in the past or the notes containing "DISCONTINUED". Example: `is_discontinued = "DISCONTINUED" in raw.get("notes", "").upper()`.

**Misleading docstring on `FREDSearchResult.similarity_score`:**
- Issue: The field comment says "Cosine distance from LanceDB (lower = more similar)" but the actual value is a cosine similarity (higher = more similar), optionally boosted by popularity. The search code converts L2 distance to cosine similarity at `fred_search/search.py` lines 157-158.
- Files: `fred_search/models.py` (line 92)
- Impact: Consumers of the library API would misinterpret the score's semantics.
- Fix approach: Change the comment to `# Similarity score (higher = more similar); optionally popularity-boosted`.

**1.5 GB state DB with no VACUUM or cleanup:**
- Issue: `data/fred_ingest_state.db` is 1.5 GB. It stores 840K series as full JSON blobs plus tags. SQLite WAL mode with many writes can accumulate journal overhead. There is no VACUUM step after ingest, no command to prune error records, and no way to compact the DB.
- Files: `fred_search/_state.py`
- Impact: Disk usage is 17x larger than the final LanceDB index (~90 MB). Developers must carry 1.5 GB of state to avoid re-running the 10-hour ingest.
- Fix approach: Add a `VACUUM` call at the end of `run_ingest()` or a `fred-ingest --vacuum` flag. Consider storing only fields needed for filtering instead of full JSON blobs, or adding a `--prune` flag to remove series that did not survive filtering.

## Known Bugs

**`changes()` returns wrong count after `executemany`:**
- Symptoms: `register_releases()` and `store_series_batch()` return 1 instead of the actual number of inserted rows. `register_category()` also uses `changes()` after `commit()`.
- Files: `fred_search/_state.py` (lines 119-122, 163-164, 213-214)
- Trigger: SQLite's `changes()` function returns the number of rows affected by the *last individual* DML statement, not the total across an `executemany` batch. After `executemany` with 3 inserts, `changes()` returns 1 (the last insert), not 3.
- Workaround: The incorrect counts are only used for logging (`logger.info` / `logger.debug`), so ingest correctness is not affected. The state DB itself is correct.
- Fix: Use `conn.total_changes` before and after the `executemany` call to compute the actual delta: `before = self._conn.total_changes; self._conn.executemany(...); self._conn.commit(); return self._conn.total_changes - before`.

**N+1 query in `iter_all_series`:**
- Symptoms: Loading all series for Phase 4 is slower than necessary.
- Files: `fred_search/_state.py` (lines 239-257)
- Trigger: For each of the 840K series rows, `iter_all_series()` calls `get_tags_for_series()` individually (line 256), resulting in 840K additional SQLite queries. With 33K series having tags, only those need tag data.
- Workaround: The query still completes in ~35 seconds due to SQLite's speed, but it should be faster.
- Fix: Replace the per-row tag fetch with a single JOIN query or a pre-loaded dict: `SELECT s.series_id, s.raw_json, GROUP_CONCAT(st.tag) FROM series s LEFT JOIN series_tags st ON s.series_id = st.series_id GROUP BY s.series_id`.

## Security Considerations

**API key in `.env` file (with real value):**
- Risk: The `.env` file at the repository root contains a real FRED API key (`<REDACTED>` — the literal value was previously committed here and is preserved in commit `2eed6b5` history; key has been rotated). While `.env` is gitignored, the file is present on disk. If the repo is ever shared, zipped, or backed up carelessly, the key leaks — exactly what happened when this concerns doc was first authored.
- Files: `.env` (line 5)
- Current mitigation: `.gitignore` excludes `.env` and `.env.*`. The `.env.example` correctly contains a placeholder.
- Recommendations: Rotate the API key. Consider using a system keyring or environment variable directly instead of a dotfile. FRED API keys are free and low-risk, but the pattern sets a bad precedent for higher-stakes secrets.

**Unparameterized string interpolation in LanceDB WHERE clause:**
- Risk: `_build_where()` interpolates the `frequency` parameter directly into a SQL-like WHERE string: `f"frequency = '{frequency}'"`. If a user passes a malicious `frequency` value via CLI (`--frequency "'; DROP TABLE fred_series; --"`), it could exploit LanceDB's query parser.
- Files: `fred_search/search.py` (line 209)
- Current mitigation: LanceDB uses its own query engine (not raw SQLite), which likely does not support multi-statement injection. The `frequency` parameter comes from CLI `argparse` with no validation.
- Recommendations: Validate `frequency` against a whitelist of known FRED frequencies (`Daily`, `Weekly`, `Biweekly`, `Monthly`, `Quarterly`, `Semiannual`, `Annual`) before interpolation. Alternatively, use LanceDB's programmatic filter API if available.

**API key logged in error messages:**
- Risk: The `FREDClient._get()` method includes `params` in the retry-exhaustion error message (line 113): `f"Exhausted {_MAX_RETRIES} retries for {endpoint} with params {params}"`. The params dict contains `api_key`.
- Files: `fred_search/_client.py` (line 113)
- Current mitigation: None. The API key appears in log output if a request fails after all retries.
- Recommendations: Strip `api_key` from the params dict before including it in error messages. Example: `{k: v for k, v in params.items() if k != "api_key"}`.

## Performance Bottlenecks

**Model reloading on every `search_fred()` call:**
- Problem: The `search_fred()` convenience function creates a new `FREDSearcher` (and loads the SentenceTransformer model into memory) on every call.
- Files: `fred_search/search.py` (line 267)
- Cause: The `_default_searcher` caching mechanism was started but never wired in.
- Improvement path: Cache the searcher in `_default_searcher` keyed by `data_dir`, or document that callers should instantiate `FREDSearcher` directly for batch queries.

**Tag enrichment is 10+ hours (Phase 4.5):**
- Problem: Fetching per-series tags requires one API call per series. At 85 req/min, 33K series takes ~6.5 hours. The actual run took 10.3 hours due to retries and network issues.
- Files: `fred_search/ingest.py` (lines 256-310)
- Cause: FRED does not offer a bulk tags endpoint. Each `series/tags` call returns tags for a single series.
- Improvement path: This is a FRED API limitation. Consider caching tag results more aggressively or adding a `--tag-sample` flag to enrich only the top-N most popular series. Alternatively, explore if FRED's `tags/series` endpoint (tags-to-series mapping) could fetch tags in fewer calls.

**Full table overwrite on re-ingest:**
- Problem: `_store_lancedb()` uses `mode="overwrite"`, destroying and rebuilding the entire LanceDB table on every ingest run, even if only a few series changed.
- Files: `fred_search/ingest.py` (line 383)
- Cause: No incremental update mechanism exists. The spec mentions `fred-ingest --incremental` as future work.
- Improvement path: Implement incremental updates using FRED's `series/updates` endpoint to identify changed series, then use LanceDB's merge/upsert operations.

## Fragile Areas

**Abbreviation expansion — regex over entire query:**
- Files: `fred_search/_abbreviations.py` (lines 157-197)
- Why fragile: The `expand_query()` function iterates over all ~80 abbreviations and applies a regex substitution for each. Abbreviations are matched case-insensitively as whole words. However, some abbreviations are common English words or overlap with other abbreviations (e.g., "ARM" matches "adjustable-rate mortgage" but is also a CPU architecture; "IP" is conditional but "FX" could mean "effects"). The unconditional expansion of "S&P" requires `re.escape()` for the ampersand, which works, but other punctuation in abbreviations could break.
- Safe modification: When adding new abbreviations, always add to `CONDITIONAL_EXPANSIONS` (not `EXPANSIONS`) if the abbreviation is ambiguous. Test with queries that use the abbreviation in a non-finance context.
- Test coverage: No tests exist for abbreviation expansion. This is the highest-priority testing gap.

**LanceDB L2-to-cosine conversion:**
- Files: `fred_search/search.py` (lines 155-158)
- Why fragile: The cosine similarity is derived from L2 distance using the formula `cos_sim = 1 - (l2^2 / 2)`. This formula is only valid when embeddings are unit-normalized. If the normalization in ingest (`normalize_embeddings=True` at `ingest.py` line 333) or search (`normalize_embeddings=True` at `search.py` line 131) is ever changed or removed, the similarity scores become meaningless without any error or warning.
- Safe modification: If changing embedding parameters, always change both ingest and search simultaneously. Consider adding an assertion that `np.linalg.norm(vec) ≈ 1.0` as a sanity check.
- Test coverage: None. A unit test that verifies the L2-to-cosine conversion for known vectors would catch regressions.

**Seasonal adjustment deduplication heuristic:**
- Files: `fred_search/_filters.py` (lines 139-186)
- Why fragile: The SA/NSA dedup groups series by `(normalized_title, frequency, units)` after stripping SA/NSA indicators via regex. The normalization regex and the set of recognized SA values (`_SA_VALUES`, `_NSA_VALUES`) are hardcoded. If FRED introduces new seasonal adjustment labels (e.g., "Seasonally Adjusted Annual Rate" variants), they would not match and dedup would silently stop working for those groups.
- Safe modification: Log the count of groups that have >2 members or unrecognized adjustment values as a diagnostic.
- Test coverage: None.

## Scaling Limits

**In-memory filtering of 840K series:**
- Current capacity: `_load_and_filter()` loads all 840K `FREDSeriesMetadata` objects into a Python list before filtering.
- Limit: At ~1 KB per object, this is ~840 MB of Python objects. On machines with <4 GB free RAM, this could cause swapping or OOM.
- Scaling path: Stream filtering through the SQLite iterator instead of materializing the full list. Apply filters (popularity, staleness) as SQL WHERE clauses on the state DB before loading into Python.

**LanceDB search with large fetch_limit:**
- Current capacity: When `popularity_boost=True`, the search fetches `top_k * 3` candidates (e.g., 30 for the default top_k=10). This is fine for small top_k.
- Limit: If a caller passes `top_k=1000`, the fetch becomes 3000 candidates converted to a pandas DataFrame. For very large top_k values, this could be slow.
- Scaling path: Cap `fetch_limit` at a reasonable maximum (e.g., 500) regardless of top_k.

## Dependencies at Risk

**LanceDB API instability:**
- Risk: LanceDB is pre-1.0 (version >=0.13 required). The Python API has changed between minor versions (e.g., table creation modes, search builder syntax). A `pip install --upgrade lancedb` could break the search or ingest code.
- Impact: Both `fred_search/ingest.py` (line 383: `create_table` with `mode="overwrite"`) and `fred_search/search.py` (line 146: `.search().limit().where()` chaining) depend on specific API shapes.
- Migration plan: Pin the exact LanceDB version in `pyproject.toml` (e.g., `lancedb==0.13.0` instead of `>=0.13`). Add integration tests that exercise table creation and search to catch API breaks.

**sentence-transformers heavy dependency tree:**
- Risk: `sentence-transformers>=3.0` pulls in PyTorch, transformers, huggingface-hub, tokenizers, and numpy. This is ~2 GB of dependencies for a 22M parameter model. Version conflicts with other projects sharing the same environment are common.
- Impact: Installation is slow and can fail on constrained environments (CI, Docker, ARM).
- Migration plan: Consider ONNX runtime for inference (the model has an ONNX export). This would replace the PyTorch dependency with `onnxruntime` (~50 MB). The `optimum` library or manual ONNX inference could be used.

## Missing Critical Features

**No test suite:**
- Problem: The `tests/` directory contains only an empty `__init__.py`. There are zero tests for any module.
- Blocks: Safe refactoring, CI integration, contribution from others, and validation of correctness after dependency upgrades.
- Priority: High. The handoff documents explicitly list test creation as a planned child task ("Child 3: Test Suite"). Key areas needing tests: filter pipeline correctness, abbreviation expansion, L2-to-cosine math, state DB operations, and search quality regression (10 curated queries).

**No input validation on search parameters:**
- Problem: `FREDSearcher.search()` accepts any string for `frequency`, any integer for `top_k` (including 0 or negative), and any value for `min_popularity`. No validation is performed.
- Blocks: Robust library API usage and meaningful error messages.
- Priority: Medium.

**No incremental index updates:**
- Problem: Any change to the corpus requires a full re-ingest (10+ hours with tags). The `--force` flag deletes the entire state DB.
- Blocks: Keeping the index current without re-running the full pipeline.
- Priority: Medium. The FRED API has a `series/updates` endpoint that lists recently changed series.

## Test Coverage Gaps

**All modules are untested:**
- What's not tested: Every module in `fred_search/` — client, state, filters, models, ingest, search, abbreviations.
- Files: `tests/__init__.py` (empty)
- Risk: Filter logic bugs (e.g., the `is_discontinued` no-op, `changes()` miscount) go undetected. Abbreviation expansion could break silently. The L2-to-cosine conversion has no validation. State DB schema changes could corrupt resumability.
- Priority: High

**Specific high-value tests to write first:**
1. `test_abbreviations.py` — Verify expand_query for known abbreviations, conditional expansion context matching, no-expansion for unknown terms, case insensitivity.
2. `test_filters.py` — Verify each filter function independently, verify pipeline ordering, verify SA/NSA dedup with known groups.
3. `test_models.py` — Verify `from_api_response()` parsing with edge cases (missing fields, None popularity, empty notes).
4. `test_state.py` — Verify `changes()` counts (currently buggy), verify resumability (re-run skips completed items), verify `iter_all_series` returns correct data.
5. `test_search.py` — Verify L2-to-cosine conversion math, verify popularity boost formula, verify WHERE clause construction.

---

*Concerns audit: 2026-03-11*

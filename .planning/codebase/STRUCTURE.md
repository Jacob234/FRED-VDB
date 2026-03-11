# Codebase Structure

**Analysis Date:** 2026-03-11

## Directory Layout

```
FRED-VDB/
├── fred_search/                # Main Python package (all application code)
│   ├── __init__.py             # Public API re-exports + package docstring
│   ├── ingest.py               # 6-phase ingest pipeline + CLI entry point
│   ├── search.py               # Semantic search interface + CLI entry point
│   ├── models.py               # FREDSeriesMetadata and FREDSearchResult dataclasses
│   ├── _client.py              # FRED REST API client (rate-limited, retrying)
│   ├── _filters.py             # Series filtering pipeline (5 filter stages)
│   ├── _state.py               # SQLite-backed resumable ingest state
│   └── _abbreviations.py       # Finance abbreviation expansion for queries
├── tests/                      # Test package (currently empty)
│   └── __init__.py
├── data/                       # Generated artifacts (gitignored except .gitkeep)
│   ├── .gitkeep
│   ├── fred_ingest_state.db    # SQLite ingest checkpoint DB (~generated)
│   ├── fred_vector_index/      # LanceDB vector store (~generated)
│   │   └── fred_series.lance/  # Lance columnar files
│   └── ingest_overnight.log    # Log from overnight ingest run (~generated)
├── docs/                       # Documentation
│   └── plans/
│       └── 2026-03-09-overnight-enrichment-design.md
├── .claude/                    # Claude Code configuration
│   ├── settings.local.json
│   └── handoffs/               # Conversation handoff documents
├── .planning/                  # GSD planning artifacts
│   └── codebase/               # Codebase analysis documents (this file)
├── .serena/                    # Serena IDE integration
├── pyproject.toml              # Project metadata, dependencies, CLI scripts
├── uv.lock                     # uv lockfile (pinned dependency versions)
├── .python-version             # Python 3.12
├── .env                        # Real credentials (gitignored)
├── .env.example                # Template for .env
├── .gitignore                  # Comprehensive Python/ML/macOS/IDE ignores
└── fred-vector-search.md       # Original implementation spec document
```

## Directory Purposes

**`fred_search/`:**
- Purpose: All application source code lives here; this is the installable Python package
- Contains: 7 Python modules (3 public, 4 private with `_` prefix)
- Key files: `ingest.py` (567 lines, largest file), `search.py` (364 lines), `_client.py` (214 lines), `_state.py` (295 lines), `_filters.py` (240 lines), `_abbreviations.py` (197 lines), `models.py` (115 lines)

**`tests/`:**
- Purpose: Test package (placeholder, no tests implemented yet)
- Contains: Only `__init__.py`
- Key files: None yet

**`data/`:**
- Purpose: All generated/runtime artifacts from ingest. Fully gitignored except `.gitkeep`
- Contains: SQLite state DB, LanceDB vector index, log files
- Key files: `fred_ingest_state.db` (ingest checkpoint), `fred_vector_index/fred_series.lance/` (vector store)

**`docs/plans/`:**
- Purpose: Design documents for planned features
- Contains: Markdown design docs
- Key files: `2026-03-09-overnight-enrichment-design.md`

**`.claude/handoffs/`:**
- Purpose: Session handoff documents between Claude Code conversations
- Contains: Markdown summaries of completed work sessions

## Key File Locations

**Entry Points:**
- `fred_search/ingest.py:main()`: CLI entry for `fred-ingest` command (line 483)
- `fred_search/search.py:main()`: CLI entry for `fred-search` command (line 305)
- `fred_search/__init__.py`: Library entry point (`from fred_search import search_fred`)

**Configuration:**
- `pyproject.toml`: Project metadata, dependencies, `[project.scripts]` CLI registration, build config
- `.python-version`: Pins Python 3.12
- `.env.example`: Template showing required `FRED_API_KEY` env var
- `.env`: Actual credentials (gitignored)

**Core Logic:**
- `fred_search/ingest.py`: Ingest pipeline orchestration (phases 1-6) and `build_embedding_text()`
- `fred_search/search.py`: `FREDSearcher` class, `search_fred()` function, `_build_where()` filter SQL
- `fred_search/_client.py`: `FREDClient` with rate limiting, retry, pagination
- `fred_search/_state.py`: `IngestState` SQLite manager with 5-table schema
- `fred_search/_filters.py`: `apply_filters()` pipeline with `FilterConfig`
- `fred_search/_abbreviations.py`: `expand_query()` with `EXPANSIONS` and `CONDITIONAL_EXPANSIONS` dicts

**Data Models:**
- `fred_search/models.py`: `FREDSeriesMetadata` (ingest) and `FREDSearchResult` (search)

**Testing:**
- `tests/__init__.py`: Empty test package (no tests written yet)

**Generated Data:**
- `data/fred_ingest_state.db`: SQLite DB with tables: `ingest_runs`, `releases`, `categories`, `series`, `series_tags`
- `data/fred_vector_index/fred_series.lance/`: LanceDB table `fred_series` with 384-dim vectors + metadata columns

## Naming Conventions

**Files:**
- Public modules: `lowercase.py` (e.g., `ingest.py`, `search.py`, `models.py`)
- Private/internal modules: `_lowercase.py` with leading underscore (e.g., `_client.py`, `_filters.py`, `_state.py`, `_abbreviations.py`)
- No hyphens in Python module names; hyphens used in project name (`fred-vdb`) and spec doc (`fred-vector-search.md`)

**Directories:**
- Package directories: `snake_case` (e.g., `fred_search`)
- Non-package directories: lowercase (e.g., `data`, `tests`, `docs`)

**Classes:**
- `PascalCase`: `FREDSeriesMetadata`, `FREDSearchResult`, `FREDClient`, `FREDAPIError`, `IngestState`, `FREDSearcher`, `FilterConfig`, `FilterStats`
- Acronyms kept uppercase: `FRED` prefix on public-facing classes

**Functions:**
- `snake_case`: `search_fred()`, `run_ingest()`, `apply_filters()`, `build_embedding_text()`, `expand_query()`
- Private functions: `_` prefix (e.g., `_fetch_releases()`, `_build_where()`, `_format_results()`)

**Constants:**
- `_UPPER_SNAKE_CASE` with leading underscore for module-private: `_FRED_ROOT_CATEGORY`, `_EMBEDDING_MODEL`, `_LANCEDB_TABLE`, `_DEFAULT_TOP_K`, `_MAX_LIMIT`, `_DEFAULT_RPM`
- `UPPER_SNAKE_CASE` without underscore for public dicts: `EXPANSIONS`, `CONDITIONAL_EXPANSIONS`

**Variables:**
- `snake_case`: `filter_cfg`, `state_path`, `lance_path`, `query_vec`, `cos_sim`

## Where to Add New Code

**New Feature (e.g., LLM re-ranking, clustering):**
- Primary code: Add a new module in `fred_search/` (e.g., `fred_search/rerank.py` or `fred_search/_clusters.py`)
- If it has a CLI, register a new script in `pyproject.toml` `[project.scripts]`
- Re-export public symbols from `fred_search/__init__.py`
- Tests: `tests/test_<module>.py`

**New Filter:**
- Add filter function to `fred_search/_filters.py` following the pattern: `def filter_<name>(series: list[FREDSeriesMetadata], ...) -> list[FREDSeriesMetadata]`
- Add corresponding field to `FilterConfig` dataclass
- Add corresponding tracking field to `FilterStats` dataclass
- Wire into `apply_filters()` pipeline in correct order (cheap filters first)

**New FRED API Endpoint:**
- Add method to `FREDClient` in `fred_search/_client.py`, using `self._get()` for single requests or `self._paginate()` for list endpoints
- Follow existing naming: `get_<noun>()` or `get_<noun>_<relation>()`

**New Abbreviation Expansion:**
- Unconditional: Add entry to `EXPANSIONS` dict in `fred_search/_abbreviations.py`
- Context-dependent: Add entry to `CONDITIONAL_EXPANSIONS` dict with `expansion` and `context` keys

**New SQLite Table for Ingest State:**
- Add `CREATE TABLE IF NOT EXISTS` to `_SCHEMA` string in `fred_search/_state.py`
- Add corresponding methods to `IngestState` class

**New Tests:**
- Add `tests/test_<module>.py` for unit tests
- No test framework configured yet; recommend `pytest` (not yet in dependencies)

**New Search Parameters:**
- Add parameter to `FREDSearcher.search()` method in `fred_search/search.py`
- Add corresponding WHERE clause logic to `_build_where()` helper
- Add CLI flag in `main()` argparse section
- Mirror parameter in `search_fred()` convenience function

## Special Directories

**`data/`:**
- Purpose: All runtime-generated artifacts (SQLite DB, LanceDB index, logs)
- Generated: Yes, by `fred-ingest` command
- Committed: No (gitignored, except `.gitkeep` placeholder)

**`data/fred_vector_index/`:**
- Purpose: LanceDB vector store containing embedded FRED series metadata
- Generated: Yes, by phase 6 of ingest pipeline (`_store_lancedb()`)
- Committed: No (gitignored; rebuilt from `fred-ingest`)

**`.venv/`:**
- Purpose: Python virtual environment managed by `uv`
- Generated: Yes, by `uv sync`
- Committed: No (gitignored)

**`.claude/handoffs/`:**
- Purpose: Session context handoff documents for Claude Code
- Generated: Manually by developer
- Committed: Not currently tracked (in `??` untracked status)

---

*Structure analysis: 2026-03-11*

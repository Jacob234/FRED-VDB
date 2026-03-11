# Technology Stack

**Analysis Date:** 2026-03-11

## Languages

**Primary:**
- Python >=3.12 - All application code. Pinned in `.python-version` to `3.12`.

**Secondary:**
- None. Pure Python project with no secondary languages.

## Runtime

**Environment:**
- Python 3.12 (specified in `.python-version` and `pyproject.toml`)
- macOS development target (Darwin 23.6.0 confirmed)
- No container runtime; runs directly on host

**Package Manager:**
- `uv` (not pip, not poetry)
- Lockfile: `uv.lock` present, revision 3
- Build backend: `hatchling` (specified in `pyproject.toml` `[build-system]`)

## Frameworks

**Core:**
- No web framework. This is a CLI/library tool, not a web application.
- `argparse` (stdlib) for CLI entry points in `fred_search/ingest.py` and `fred_search/search.py`

**ML/Embeddings:**
- `sentence-transformers` 5.2.3 - Local text embedding with `all-MiniLM-L6-v2` model (384-dim, 22M params)
- `torch` 2.10.0 - Backend for sentence-transformers (transitive dependency)

**Data:**
- `lancedb` 0.29.2 - File-based vector database for storing and querying embeddings
- `pandas` 3.0.1 - Used by LanceDB's `.to_pandas()` for search result retrieval
- `pyarrow` 23.0.1 - Required by LanceDB for columnar storage format
- `numpy` 2.4.3 - Array operations for embedding vectors

**Testing:**
- Not detected. No test framework configured. `tests/` directory exists with only an empty `__init__.py`.

**Build/Dev:**
- `hatchling` - Build backend (PEP 517)
- No linter, formatter, or type checker configured in `pyproject.toml`

## Key Dependencies

**Critical (declared in `pyproject.toml`):**
- `httpx` >=0.27 (resolved: 0.28.1) - HTTP client for FRED API calls. Used in `fred_search/_client.py` with connection pooling, timeouts, and retry logic.
- `lancedb` >=0.13 (resolved: 0.29.2) - Vector database. Stores embeddings + metadata at `data/fred_vector_index/`.
- `sentence-transformers` >=3.0 (resolved: 5.2.3) - Embedding model loader. Encodes series metadata and search queries.
- `tqdm` >=4.66 (resolved: 4.67.3) - Progress bars for long-running ingest phases.
- `pyarrow` >=16.0 (resolved: 23.0.1) - Required by LanceDB for Lance columnar format.
- `pandas` >=2.0 (resolved: 3.0.1) - Required by LanceDB's `to_pandas()` results.

**Transitive (not declared, pulled by sentence-transformers):**
- `torch` 2.10.0 - Deep learning backend. Largest dependency (~2GB installed).
- `numpy` 2.4.3 - Numerical arrays for embedding vectors.

**Notably absent:**
- `fredapi` - The spec mentioned it, but the implementation uses a custom `FREDClient` (`fred_search/_client.py`) with `httpx` instead.

## Configuration

**Environment Variables:**
- `FRED_API_KEY` - Required. 32-char hex string from https://fred.stlouisfed.org/docs/api/api_key.html
- Loaded from environment or `--api-key` CLI argument. Not read from `.env` programmatically (no dotenv library).
- Template at `.env.example`; actual `.env` is gitignored.

**Build Configuration:**
- `pyproject.toml` - Single project config file. Defines metadata, dependencies, and CLI entry points.
- No `setup.py`, `setup.cfg`, or `requirements.txt`.

**CLI Entry Points (defined in `pyproject.toml` `[project.scripts]`):**
- `fred-ingest` -> `fred_search.ingest:main`
- `fred-search` -> `fred_search.search:main`

## Data Artifacts

**State Database:**
- `data/fred_ingest_state.db` - SQLite WAL-mode database (~1.5 GB). Stores all fetched FRED metadata for resumable ingest. Schema defined in `fred_search/_state.py`.

**Vector Index:**
- `data/fred_vector_index/fred_series.lance/` - LanceDB table (~115 MB). Contains embeddings + metadata for filtered series.

**All data artifacts are gitignored** via `data/*` rule in `.gitignore` (only `data/.gitkeep` is tracked).

## Platform Requirements

**Development:**
- Python 3.12+
- `uv` package manager
- FRED API key (free registration)
- ~4 GB disk for dependencies (torch is large)
- ~2 GB disk for data artifacts (state DB + vector index)

**Production:**
- Not applicable. This is a local research/analysis tool, not deployed to a server.
- Designed to run offline after initial ingest (no network needed for search).

---

*Stack analysis: 2026-03-11*

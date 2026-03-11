# External Integrations

**Analysis Date:** 2026-03-11

## APIs & External Services

**FRED (Federal Reserve Economic Data) REST API:**
- Purpose: Fetch metadata for ~840K economic time series (releases, categories, series, tags)
- SDK/Client: Custom `FREDClient` class in `fred_search/_client.py` using `httpx`
- Base URL: `https://api.stlouisfed.org/fred`
- Auth: API key passed as `api_key` query parameter on every request
- Auth source: `FRED_API_KEY` env var or `--api-key` CLI argument
- Rate limiting: Self-imposed token bucket at 85 req/min (below advertised 120 req/min limit). Configurable via `requests_per_minute` constructor param.
- Retry: Exponential backoff with jitter on HTTP 429, 500, 502, 503, 504. Up to 5 attempts per request.
- Response format: JSON (`file_type=json` param on all requests)
- Pagination: Offset/limit with 1000 items per page max (`_MAX_LIMIT` in `fred_search/_client.py`)

**FRED API Endpoints Used:**
- `GET /fred/releases` - List all FRED releases (~350 total). Used in Phase 1 of ingest.
- `GET /fred/release/series` - List series for a release. Used in Phase 2 (release-based series fetch).
- `GET /fred/category/children` - Get child categories. Used in Phase 3 (BFS category tree walk).
- `GET /fred/category/series` - List series in a category. Used in Phase 3.
- `GET /fred/series/tags` - Get tags for a single series. Used in Phase 4.5 (tag enrichment, optional).

**HuggingFace Model Hub (implicit):**
- Purpose: Download the `all-MiniLM-L6-v2` sentence-transformers model on first run
- SDK/Client: `sentence_transformers.SentenceTransformer("all-MiniLM-L6-v2")` in `fred_search/ingest.py` and `fred_search/search.py`
- Auth: None required (public model)
- Network: Required only on first run; model is cached locally at `~/.cache/huggingface/` after download (~80 MB)
- Offline: After initial download, embedding works fully offline

## Data Storage

**SQLite (Ingest State):**
- Purpose: Resumable ingest progress tracking. Stores all fetched FRED API responses so re-runs skip already-fetched data.
- Location: `data/fred_ingest_state.db`
- Size: ~1.5 GB (contains raw JSON for ~840K series)
- Client: Python stdlib `sqlite3` module, used in `fred_search/_state.py`
- Schema: 5 tables - `ingest_runs`, `releases`, `categories`, `series`, `series_tags`
- WAL mode enabled (`PRAGMA journal_mode = WAL`)
- Connection: `sqlite3.connect(db_path)` with `row_factory = sqlite3.Row`
- Not thread-safe; designed for single-process sequential use

**LanceDB (Vector Index):**
- Purpose: Store and query 384-dim embedding vectors alongside series metadata
- Location: `data/fred_vector_index/` (Lance columnar format directory)
- Size: ~115 MB
- Client: `lancedb` Python package. `lancedb.connect(str(lance_path))` in `fred_search/ingest.py` and `fred_search/search.py`
- Table name: `fred_series` (constant `_LANCEDB_TABLE` in both modules)
- Write: `db.create_table("fred_series", data=records, mode="overwrite")` - full rebuild each ingest
- Read: `table.search(query_vec).limit(N).where(filter, prefilter=True).to_pandas()`
- Vector search returns L2 distance; converted to cosine similarity in `fred_search/search.py` lines 156-158

**File Storage:**
- Local filesystem only. No cloud storage integration.
- All data under `data/` directory (gitignored except `data/.gitkeep`)

**Caching:**
- HuggingFace model cache at `~/.cache/huggingface/` (managed by `sentence-transformers`)
- No application-level caching beyond SQLite state persistence

## Authentication & Identity

**FRED API Key:**
- Type: 32-character hex string
- Registration: Free at https://fred.stlouisfed.org/docs/api/api_key.html
- Delivery: Query parameter (`api_key=...`) on every API request
- Storage: `.env` file (gitignored) or shell environment variable
- Template: `.env.example` with placeholder value
- Validation: CLI parser checks for empty string and exits with error if missing (`fred_search/ingest.py` line 548-552)

**No other auth providers.** No user authentication, no OAuth, no JWT.

## Monitoring & Observability

**Error Tracking:**
- None. No Sentry, Datadog, or similar.

**Logging:**
- Python stdlib `logging` module throughout all modules
- Logger per module: `logger = logging.getLogger(__name__)`
- CLI configures root logger with `logging.basicConfig()`:
  - Ingest: `%(asctime)s %(levelname)-8s %(name)s -- %(message)s` format, configurable `--log-level` (DEBUG/INFO/WARNING/ERROR)
  - Search: `%(levelname)s %(message)s` format, fixed WARNING level
- Key logged events:
  - Phase transitions and timing (`fred_search/ingest.py`)
  - Filter pipeline statistics (`fred_search/_filters.py` `FilterStats.log()`)
  - API errors and retries (`fred_search/_client.py`)
  - Query expansion (`fred_search/search.py` line 127)

## CI/CD & Deployment

**Hosting:**
- Not deployed. Local development tool only.

**CI Pipeline:**
- None detected. No `.github/workflows/`, no `Makefile`, no `Dockerfile`.

**Version Control:**
- Git repository on `main` branch
- `.gitignore` covers: Python artifacts, `.env`, `data/*`, model files, IDE configs

## Environment Configuration

**Required env vars:**
- `FRED_API_KEY` - Required for ingest. Not required for search (search is fully offline).

**Optional env vars:**
- None. All configuration via CLI arguments.

**Secrets location:**
- `.env` file at project root (gitignored)
- `.env.example` template committed with placeholder

## Webhooks & Callbacks

**Incoming:**
- None. No server component.

**Outgoing:**
- None. No webhook integrations.

## Integration Patterns

**FRED API Client Pattern:**
Use `FREDClient` as a context manager. All methods are synchronous. Rate limiting is automatic.
```python
# fred_search/_client.py
with FREDClient(api_key="...") as client:
    for release in client.get_all_releases():
        for series in client.get_release_series(release["id"]):
            ...
```

**LanceDB Read Pattern:**
```python
# fred_search/search.py
import lancedb
db = lancedb.connect(str(lance_path))
table = db.open_table("fred_series")
df = table.search(query_vec).limit(top_k).where(where_clause, prefilter=True).to_pandas()
```

**LanceDB Write Pattern:**
```python
# fred_search/ingest.py
import lancedb
db = lancedb.connect(str(lance_path))
db.create_table("fred_series", data=records, mode="overwrite")
```

**Embedding Pattern:**
```python
# fred_search/ingest.py (batch encoding for ingest)
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = model.encode(texts, batch_size=256, normalize_embeddings=True)

# fred_search/search.py (single query encoding)
query_vec = model.encode([expanded_query], normalize_embeddings=True)[0].tolist()
```

---

*Integration audit: 2026-03-11*

# FRED-VDB

Semantic search over FRED (Federal Reserve Economic Data) series metadata. Ask natural language questions, get back the most relevant series from ~840K options.

```
$ fred-search "indicators of CRE lending tightening"

  1. SUBLPDRCSM  (similarity: 0.847)
     Net Percentage of Domestic Banks Tightening Standards for CRE Loans, Multifamily
     Frequency: Quarterly | Units: Percent | Popularity: 42

  2. DRCRELEXFACBS  (similarity: 0.812)
     Delinquency Rate on Commercial Real Estate Loans, All Commercial Banks
     Frequency: Quarterly | Units: Percent | Popularity: 55

  3. SUBLPDRCSC  (similarity: 0.779)
     Net Percentage of Domestic Banks Tightening Standards for Construction and Land Development Loans
     Frequency: Quarterly | Units: Percent | Popularity: 31
```

## Why?

FRED has 840,000 time series from 118 sources. Finding the right one means knowing the exact series ID or guessing keywords. The built-in FRED search can find "unemployment rate" but not "indicators of labor market slack" — it has no concept of meaning, only word overlap.

FRED-VDB fixes this by embedding every series' metadata (title, notes, tags, units, frequency, category) into a local vector index, then matching your queries by semantic similarity rather than keywords.

## How It Compares to FRED's API Search

FRED's `series/search` endpoint and FRED-VDB solve the same problem (finding series) in fundamentally different ways:

### FRED API Search (`fred/series/search`)

| Aspect | Details |
|---|---|
| **Method** | Full-text keyword search with linguistic stemming |
| **Algorithm** | Undocumented; likely BM25 (TF-IDF variant) on Solr/Elasticsearch |
| **Fields searched** | title, units, frequency, tags |
| **Notes field** | **Not searched** — the richest semantic content is ignored |
| **Stemming** | Yes — "Industry" matches "Industries" |
| **Conceptual queries** | No — "credit stress" won't find delinquency or lending standards series |
| **Ranking** | Opaque `search_rank` score, appears to blend keyword relevance with popularity |
| **Filtering** | By frequency, units, seasonal adjustment, tags |
| **Rate limit** | 120 req/min (advertised), ~85 req/min practical |
| **Latency** | Network round-trip per query |

### FRED-VDB (this project)

| Aspect | Details |
|---|---|
| **Method** | Vector similarity over sentence embeddings |
| **Algorithm** | Cosine similarity on `all-MiniLM-L6-v2` embeddings (384-dim), with optional popularity boost |
| **Fields embedded** | title, notes (first 500 chars), tags, units, frequency, category path |
| **Notes field** | **Included** — the descriptive paragraph is the strongest semantic signal |
| **Stemming** | N/A — the embedding model captures meaning, not morphology |
| **Conceptual queries** | Yes — "credit stress" finds delinquency rates, lending surveys, spread indices |
| **Ranking** | `cosine_similarity * (1 + log(popularity + 1) / 10)` — transparent, tunable |
| **Filtering** | By frequency, popularity, recency (pre-filter in LanceDB) |
| **Rate limit** | None — fully local, offline |
| **Latency** | ~50ms per query (embedding + vector scan) |

### Where Each Wins

**Use FRED API search when:**
- You know roughly what you're looking for ("10 year treasury", "CPI urban consumers")
- You need tag-based filtering (`tag_names=mortgage,delinquency`)
- You want real-time coverage of newly added series

**Use FRED-VDB when:**
- You have a conceptual question ("what data exists about private credit conditions?")
- You're exploring — you don't know what series exist
- You need offline/local access with no rate limits
- You want to search the `notes` field (FRED's own search doesn't)

### Abbreviation Handling

Finance is full of abbreviations that neither approach handles well out of the box. FRED's stemmer won't expand "CRE" to "commercial real estate." FRED-VDB includes a built-in abbreviation expander with 80+ finance/economics terms that runs before embedding:

```
Query: "CRE credit stress"
Expanded: "CRE (commercial real estate) credit stress"
```

Conditional expansions handle ambiguous abbreviations based on context words in the query (e.g., "MF" → "multifamily" only when housing-related terms are present).

<details>
<summary>Full abbreviation list (80+ terms)</summary>

| Category | Abbreviations |
|---|---|
| **Interest Rates & Monetary Policy** | FFR, EFFR, SOFR, LIBOR, IOER, OBFR, TIPS, UST, YC, QE, QT, FOMC |
| **Fixed Income & Credit** | HY, IG, OAS, MBS, CMBS, RMBS, ABS, CLO, CDO, CDS, GSE, TED |
| **Real Estate** | CRE, REIT, ARM, FRM, LTV, HPI |
| **Banking** | SLOOS, NPL, NIM, FDIC, FHLB |
| **Economic Indicators** | GDP, GNP, GDI, CPI, PPI, PCE, PCEPI, PMI, ISM, NFP, JOLTS, LEI, ECI, M1, M2 |
| **Labor Market** | LFPR, EPOP, AHE, QCEW |
| **Financial Conditions & Stress** | NFCI, STLFSI, KCFSI, CFNAI, VIX |
| **Housing Agencies** | FHFA, FHA, NAHB |
| **Markets & Trade** | FX, FDI, BOP, DXY, REER, ETF, S&P |
| **Government / Fiscal** | DSPIC, SNAP, TANF |
| **Conditional** | MF (multifamily, in housing context), IP (industrial production), CU (capacity utilization), SFR (single-family rental), EM (emerging markets) |

</details>

## Setup

```bash
# Clone and install
git clone <repo-url> && cd FRED-VDB
uv pip install -e .

# Set your FRED API key (free from https://fred.stlouisfed.org/docs/api/api_key.html)
export FRED_API_KEY=your_key_here

# Build the index (~15-30 min, resumable)
fred-ingest

# Search
fred-search "inflation expectations vs realized inflation"
```

Requires Python >= 3.12. Uses `uv` for package management.

## CLI Reference

### `fred-ingest` — Build the Vector Index

Fetches all FRED series metadata, filters, embeds, and stores in a local LanceDB index.

```bash
fred-ingest                              # Standard ingest
fred-ingest --min-popularity 20          # Only popular series
fred-ingest --skip-categories            # Faster (skip category tree walk)
fred-ingest --enrich-tags                # Richer embeddings (~1 API call/series, slow)
fred-ingest --dry-run                    # Preview scope, no writes
fred-ingest --force                      # Wipe state and rebuild from scratch
```

| Flag | Default | Description |
|---|---|---|
| `--api-key KEY` | `$FRED_API_KEY` | FRED API key |
| `--data-dir PATH` | `data` | Output directory for state DB + index |
| `--min-popularity N` | `0` | Min popularity score to keep |
| `--skip-categories` | off | Skip category tree BFS (faster, may miss ~5% of series) |
| `--enrich-tags` | off | Fetch per-series tags (API-intensive, hours) |
| `--dry-run` | off | Enumerate only, no writes |
| `--force` | off | Delete state DB and rebuild |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

The ingest is **resumable** — interrupting and re-running continues from the last checkpoint.

### `fred-search` — Query the Index

```bash
fred-search "consumer price index"
fred-search "GDP growth" --frequency Quarterly
fred-search "fed funds rate" --min-popularity 50 --json
fred-search "housing supply" --top-k 20 --include-stale
fred-search "inflation" --no-popularity-boost
```

| Flag | Default | Description |
|---|---|---|
| `query` | *(required)* | Natural language search query |
| `--top-k N` | `10` | Number of results |
| `--data-dir PATH` | `data` | Directory with `fred_vector_index/` |
| `--frequency FREQ` | none | Filter: `Daily`, `Weekly`, `Monthly`, `Quarterly`, `Annual` |
| `--min-popularity N` | none | Filter: minimum popularity score |
| `--include-stale` | off | Include series with old end dates |
| `--no-popularity-boost` | off | Disable popularity re-ranking (pure vector similarity) |
| `--json` | off | Output as JSON |

### `fred-fetch` — Retrieve Observation Data

Once you've found series IDs via search, fetch the actual time series data from the FRED API.

```bash
fred-fetch UNRATE DGS10 --start 2020-01-01
fred-fetch CPIAUCSL --last 24
fred-fetch PAYEMS --start 2023-01-01 --end 2024-12-31 --json
```

```
$ fred-fetch UNRATE --last 6

UNRATE  (6 observations)
----------------------------------------
  2025-09-01        4.4000
  2025-10-01             .
  2025-11-01        4.5000
  2025-12-01        4.4000
  2026-01-01        4.3000
  2026-02-01        4.4000
```

| Flag | Default | Description |
|---|---|---|
| `SERIES_ID` | *(required)* | One or more FRED series identifiers |
| `--start YYYY-MM-DD` | 5 years ago | Observation start date |
| `--end YYYY-MM-DD` | today | Observation end date |
| `--last N` | none | Return only the last N observations per series |
| `--api-key KEY` | `$FRED_API_KEY` | FRED API key |
| `--json` | off | Output as JSON |

### Python API

```python
from fred_search import search_fred, fetch_series, FREDSearcher

# One-off query (loads model each time)
results = search_fred("indicators of CRE credit stress", top_k=5)

# Multiple queries (keeps model in memory)
searcher = FREDSearcher(data_dir="data")
results = searcher.search("inflation expectations", frequency="Monthly")
results = searcher.search("labor market slack", min_popularity=30)

for r in results:
    print(r.series_id, r.title, f"(score={r.similarity_score:.3f})")

# Fetch observation data for selected series
data = fetch_series(["UNRATE", "DGS10"], start="2020-01-01")
for series_id, observations in data.items():
    print(series_id, len(observations), "observations")
    print(observations[-1])  # most recent: {"date": "...", "value": 4.2}
```

## Agent / Claude Code Integration

This repo ships with a Claude Code skill at `.claude/commands/fred-lookup.md` that teaches an AI agent the search → rerank → fetch workflow. When working in a Claude Code session within this project, the skill auto-activates when the agent encounters questions needing U.S. economic data.

To make it available globally (across all projects), copy it to your user-level commands:

```bash
cp .claude/commands/fred-lookup.md ~/.claude/commands/
```

The skill handles:
1. Running `fred-search` with a natural language query
2. LLM reranking of results to select the best series
3. Running `fred-fetch` to pull observation data
4. Presenting the data with appropriate context

## Architecture

### Ingest Pipeline (6 phases)

```
FRED API ──→ Phase 1: Discover releases (~350)
         ──→ Phase 2: Fetch series by release (bulk of ~840K)
         ──→ Phase 3: BFS category tree walk (catches ~5% more)
             ──→ Phase 4: Load + filter (discontinued, stale, low-pop, SA dedup)
             ──→ Phase 4.5: Tag enrichment (optional, ~1 call/series)
                 ──→ Phase 5: Embed with all-MiniLM-L6-v2 (384-dim)
                     ──→ Phase 6: Write to LanceDB
```

All fetch progress is checkpointed in a SQLite state DB (`data/fred_ingest_state.db`). The pipeline is fully resumable — kill it at any point and re-run to continue.

### Filter Pipeline

Runs in order, cheapest first:

1. **Discontinued** — drop explicitly discontinued series
2. **Recency** — drop series with no data in the last 2 years
3. **Popularity** — drop below threshold (configurable, default 0)
4. **Observation span** — drop series with < 1 year of history
5. **SA/NSA dedup** — when both seasonally adjusted and not-seasonally-adjusted variants exist, keep only the SA version

### Embedding Strategy

Each series is embedded as a single text string:

```
{title} | {notes[:500]} | Tags: {tags} | Units: {units} | Frequency: {freq} | Category: {path}
```

The `notes` field (first 500 characters) carries the strongest signal — it often contains descriptive sentences like *"This series measures the net percentage of domestic banks tightening standards for commercial real estate loans"* that directly answer conceptual queries.

### Scoring

Results are ranked by a popularity-boosted similarity score:

```
score = cosine_similarity × (1 + log(popularity + 1) / 10)
```

This surfaces well-known headline series (UNRATE, DGS10, CPIAUCSL) that would otherwise rank below niche variants with more metadata text. Disable with `--no-popularity-boost` for pure vector similarity.

## Tech Stack

| Component | Choice | Why |
|---|---|---|
| Vector DB | LanceDB | File-based, no server, offline, metadata filtering built-in |
| Embeddings | `all-MiniLM-L6-v2` | 384-dim, 22M params, fast on CPU, good for short text |
| HTTP client | `httpx` | Connection pooling, timeouts, modern Python |
| State tracking | SQLite | Resumable ingest with checkpoint semantics |
| Package manager | `uv` | Fast, deterministic Python dependency management |

## Project Structure

```
fred_search/
├── __init__.py           # Public API exports
├── ingest.py             # 6-phase ingest pipeline + CLI
├── search.py             # Vector search interface + CLI
├── fetch.py              # Observation data retrieval + CLI
├── models.py             # FREDSeriesMetadata, FREDSearchResult
├── _client.py            # FRED REST client (rate-limited, retrying)
├── _filters.py           # Filter pipeline (discontinued, stale, dedup)
├── _abbreviations.py     # Finance abbreviation expansion (80+ terms)
└── _state.py             # SQLite state DB for resumable ingest

data/                     # Generated (gitignored)
├── fred_ingest_state.db  # Ingest checkpoint state
└── fred_vector_index/    # LanceDB index files
```

## License

MIT

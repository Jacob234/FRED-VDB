# FRED Semantic Search — Implementation Spec

**Status**: Implemented
**Created**: 2026-02-25
**Origin**: Conversation about opportunity cost analysis for TheHouse deals. Jacob identified FRED series discovery as a research bottleneck — 840,000 series, keyword search only, hard to find conceptually relevant series for novel research questions.

---

## Problem

FRED (Federal Reserve Economic Data) has ~840,000 time series from 118 sources. Our `market_assumptions.yaml` curates ~30 of them. Finding new relevant series requires knowing the exact series ID or guessing keywords in FRED's basic full-text search, which:

- Returns thousands of results for broad queries (e.g., "unemployment" returns every state/county variant)
- Cannot handle conceptual queries ("indicators of commercial real estate credit stress")
- Cannot reason about which series are useful *together* for a research question
- Makes discovering adjacent/complementary series tedious

We want to ask questions like:
- "What data exists about private credit market conditions?"
- "Series that indicate whether CRE lending is tightening"
- "Inflation expectations vs realized inflation"
- "Housing supply pipeline indicators for multifamily"

...and get back the 5-10 most relevant FRED series with explanations of what they measure and why they're relevant.

---

## Solution Overview

Build a local vector index over FRED series metadata. Two-phase approach:

1. **Ingest**: Pull metadata for all active, national-scope series from FRED API. Embed `title + notes` using a lightweight embedding model. Store in a local file-based vector DB.
2. **Search**: Accept natural language queries. Retrieve top-K similar series. Optionally re-rank with an LLM for explanation quality.

### Why Not Just Use the FRED API Search?

The FRED search API (`fred/series/search`) does TF-IDF stemmed matching on `{title, units, frequency, tags}`. It's good for known-concept lookup but poor for:
- Conceptual/semantic queries (it can't match "credit stress" to "DRCRELEXFACBS")
- Discovering series you don't know exist
- Filtering out the noise of regional/seasonal/discontinued variants

The vector approach adds a semantic layer on top of FRED's structured metadata.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  fred_search/                                           │
│  ├── ingest.py          # Fetch + filter + embed + store│
│  ├── search.py          # Query interface               │
│  ├── models.py          # Data models                   │
│  └── _filters.py        # Dedup/scope filtering logic   │
├─────────────────────────────────────────────────────────┤
│  Storage: data/fred_vector_index/                       │
│  ├── fred_series.lance   (LanceDB table)                │
│  └── ingest_meta.json    (last ingest timestamp, count) │
└─────────────────────────────────────────────────────────┘
```

Lives under `data_sources/fred_search/`. Separate from the existing `fred_client.py` (which fetches *observations* for known series). This module handles *discovery* of which series to care about.

### Dependencies

| Dependency | Purpose | Install Size | Notes |
|------------|---------|-------------|-------|
| `fredapi` | FRED API wrapper — series search, metadata, tags | ~50KB | Returns pandas DataFrames. Handles pagination, auth. Avoids us re-implementing the FRED search/series endpoints. |
| `lancedb` | File-based vector DB | ~30MB | No server process. Stores as local Lance files. Supports filtering + vector search simultaneously. |
| `sentence-transformers` | Embedding model | ~100MB + model | `all-MiniLM-L6-v2` (22M params, 80MB). Fast, good for short text. |

**Why LanceDB over alternatives:**
- **vs ChromaDB**: LanceDB is pure file-based (no SQLite dependency issues), supports metadata filtering natively, and handles our scale (50-100K records) trivially. Lance columnar format is efficient for the metadata columns we'll filter on.
- **vs raw FAISS**: FAISS is a vector index, not a DB — we'd need to manage metadata separately. LanceDB bundles vectors + metadata + filtering in one table.
- **vs Supabase pgvector**: Adds network latency and Supabase dependency for what should be a local research tool. This is for developer/analyst use, not production API.

**Why `fredapi` over our existing `FREDClient`:**
Our `FREDClient` only implements `fred/series/observations` (fetching data points for a known series). The ingest step needs `fred/series/search` (bulk metadata retrieval) and `fred/series` (individual metadata) and `fred/tags/series` (tag-based filtering). `fredapi` already wraps all of these and returns pandas DataFrames, which is exactly what we need for the filtering/embedding pipeline. No reason to reimplement.

**Why `sentence-transformers` over API embeddings:**
- Runs locally — no API costs, no rate limits, no network dependency
- `all-MiniLM-L6-v2` embeds the full corpus (~80K texts) in under 5 minutes on a MacBook
- For short text (series titles are 5-20 words), this model performs within a few percent of larger models
- No Anthropic/OpenAI API key required — this should work offline

---

## Phase 1: Ingest Pipeline

### Step 1: Bulk Metadata Retrieval

Use `fredapi` to pull series metadata. The FRED API `search` endpoint returns up to 1000 results per page and supports pagination.

**Strategy**: Rather than searching for everything (slow, noisy), search by curated category IDs that cover the domains we care about. FRED's category tree is the most structured entry point.

Target categories:

| Category ID | Name | Approx Series |
|-------------|------|---------------|
| 32991 | Interest Rates | ~2,000 |
| 46 | Money, Banking & Finance | ~5,000 |
| 33 | Housing | ~1,500 |
| 32992 | Exchange Rates | ~500 |
| 1 | Production & Business Activity | ~3,000 |
| 32455 | Employment | ~3,000 |
| 32217 | Prices | ~2,000 |
| 32263 | Consumer Price Indexes | ~1,000 |
| 32348 | Population, Employment, & Labor Markets | ~2,000 |
| 33490 | Regional Data (national only) | ~500 |
| 32413 | Financial Indicators | ~500 |
| 33954 | St. Louis Financial Stress | ~50 |
| 32145 | S&P/Case-Shiller | ~200 |

Additionally, pull ALL series matching these search terms (to catch things outside the category tree):
- "commercial real estate"
- "REIT"
- "multifamily"
- "vacancy rate"
- "cap rate"
- "construction"
- "rent"
- "mortgage"
- "CMBS"
- "delinquency"
- "financial conditions"
- "credit spread"
- "high yield"

**Fields to capture per series:**

```python
@dataclass
class FREDSeriesMetadata:
    series_id: str            # e.g., "DGS10"
    title: str                # e.g., "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity"
    notes: str                # Paragraph description (often very informative)
    frequency: str            # "Daily", "Monthly", "Quarterly", "Annual"
    units: str                # "Percent", "Index", "Billions of Dollars"
    seasonal_adjustment: str  # "Seasonally Adjusted", "Not Seasonally Adjusted"
    observation_start: str    # First available date
    observation_end: str      # Most recent date
    popularity: int           # FRED popularity rank (higher = more used)
    tags: list[str]           # e.g., ["interest rate", "treasury", "10-year"]
    source: str               # Publishing organization
    last_updated: str         # Last data update
    is_discontinued: bool     # Whether series is still active
```

### Step 2: Filtering

This is the critical step that reduces ~840K series to ~50-80K useful ones.

**Filters (applied in order):**

1. **Active only**: Drop `is_discontinued == True`. Removes ~30% of series.
2. **National scope**: Drop state/county/MSA-level variants. Heuristic: exclude series where `title` or `tags` contain specific state abbreviations, "SA", county names, or MSA names, UNLESS the series is explicitly about a top metro (NYC, LA, SF, Chicago, Miami — markets relevant to TheHouse deals). This is the hardest filter to get right — some series like "New York Fed" are national despite the name.
3. **Dedup seasonal adjustments**: For each conceptual series that has both SA and NSA variants, keep only the SA version (preferred for analysis). Detect via series_id patterns (e.g., `UNRATE` vs `UNRATENSA`).
4. **Dedup frequency**: If the same concept exists at multiple frequencies (daily, weekly, monthly), keep all — different frequencies are useful for different analyses.
5. **Minimum popularity**: Drop series with `popularity < 5`. Removes obscure one-off series that nobody uses.
6. **Recency**: Drop series with `observation_end` more than 2 years before current date (stale/abandoned).

**Expected result**: ~50,000–80,000 curated series with clean metadata.

### Step 3: Text Preparation

For each series, construct the embedding text:

```python
def build_embedding_text(series: FREDSeriesMetadata) -> str:
    """Construct text for embedding. Concatenate meaningful metadata."""
    parts = [series.title]
    if series.notes:
        # Notes can be very long — truncate to first 500 chars
        # (captures the descriptive paragraph, not the legal boilerplate)
        parts.append(series.notes[:500])
    if series.tags:
        parts.append("Tags: " + ", ".join(series.tags))
    parts.append(f"Units: {series.units}")
    parts.append(f"Frequency: {series.frequency}")
    return " | ".join(parts)
```

The `notes` field is the most semantically rich — it often says things like "This series measures the net percentage of domestic banks tightening standards for commercial real estate loans" which is exactly what we want the embedding to capture.

### Step 4: Embedding

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-dim embeddings
embeddings = model.encode(texts, show_progress_bar=True, batch_size=256)
```

~80K texts at ~256 batch size ≈ 2-4 minutes on M-series Mac.

### Step 5: Store in LanceDB

```python
import lancedb

db = lancedb.connect("data/fred_vector_index")
table = db.create_table("fred_series", data=[
    {
        "series_id": s.series_id,
        "title": s.title,
        "notes": s.notes[:500],
        "frequency": s.frequency,
        "units": s.units,
        "seasonal_adjustment": s.seasonal_adjustment,
        "popularity": s.popularity,
        "tags": s.tags,
        "source": s.source,
        "observation_end": s.observation_end,
        "is_discontinued": s.is_discontinued,
        "embedding_text": embedding_text,
        "vector": embedding,  # 384-dim float32
    }
    for s, embedding_text, embedding in zip(series_list, texts, embeddings)
])
```

LanceDB stores this as a single `.lance` directory. Expected size: ~200-400MB (80K × 384 floats + metadata).

### Ingest Metadata

Write `ingest_meta.json`:
```json
{
    "ingest_date": "2026-02-25",
    "total_raw_series": 120000,
    "after_filtering": 78542,
    "embedding_model": "all-MiniLM-L6-v2",
    "embedding_dim": 384,
    "categories_crawled": [32991, 46, 33, ...],
    "search_terms_used": ["commercial real estate", "REIT", ...],
    "elapsed_minutes": 12.3
}
```

### Refresh Cadence

FRED adds ~50-100 new series per month. Re-ingest quarterly (or on-demand). The ingest script should be idempotent — `create_table(..., mode="overwrite")`.

---

## Phase 2: Search Interface

### Core Search Function

```python
def search_fred(
    query: str,
    top_k: int = 10,
    frequency: str | None = None,       # Filter: "Daily", "Monthly", etc.
    min_popularity: int | None = None,   # Filter: minimum popularity score
    active_only: bool = True,            # Filter: exclude discontinued
    tags: list[str] | None = None,       # Filter: must have these tags
) -> list[FREDSearchResult]:
    """Semantic search over FRED series metadata.

    Args:
        query: Natural language description of what you're looking for.
            Examples:
                "indicators of commercial real estate credit stress"
                "inflation expectations vs realized"
                "housing supply pipeline for multifamily"
                "risk-free rate benchmarks at various maturities"
        top_k: Number of results to return.
        frequency: Restrict to specific frequency.
        min_popularity: Minimum popularity score.
        active_only: Only return series that are still being updated.
        tags: Series must have ALL of these tags.

    Returns:
        List of FREDSearchResult with series metadata and similarity scores.
    """
```

### Result Model

```python
@dataclass
class FREDSearchResult:
    series_id: str
    title: str
    notes: str              # Truncated description
    frequency: str
    units: str
    tags: list[str]
    popularity: int
    similarity_score: float  # Cosine similarity (0-1)
    source: str
    observation_end: str     # How current the data is
```

### Search Implementation

```python
def search_fred(query: str, top_k: int = 10, **filters) -> list[FREDSearchResult]:
    db = lancedb.connect("data/fred_vector_index")
    table = db.open_table("fred_series")

    # Build filter string for LanceDB
    where_clauses = []
    if filters.get("active_only", True):
        where_clauses.append("is_discontinued = false")
    if filters.get("frequency"):
        where_clauses.append(f"frequency = '{filters['frequency']}'")
    if filters.get("min_popularity"):
        where_clauses.append(f"popularity >= {filters['min_popularity']}")

    where = " AND ".join(where_clauses) if where_clauses else None

    # Vector search with metadata filtering
    results = (
        table.search(query)  # LanceDB auto-embeds query if model configured
        .where(where)
        .limit(top_k)
        .to_pandas()
    )

    return [
        FREDSearchResult(
            series_id=row["series_id"],
            title=row["title"],
            notes=row["notes"],
            frequency=row["frequency"],
            units=row["units"],
            tags=row["tags"],
            popularity=row["popularity"],
            similarity_score=row["_distance"],
            source=row["source"],
            observation_end=row["observation_end"],
        )
        for _, row in results.iterrows()
    ]
```

### CLI Entry Point

```bash
# Search
python -m data_sources.fred_search.search "commercial real estate credit stress"
python -m data_sources.fred_search.search "inflation expectations" --frequency Monthly --top-k 5

# Ingest (rebuild index)
python -m data_sources.fred_search.ingest                  # Full rebuild
python -m data_sources.fred_search.ingest --dry-run        # Show filter stats without embedding
python -m data_sources.fred_search.ingest --categories-only # Skip keyword searches
```

### Output Format

```
$ python -m data_sources.fred_search.search "indicators of CRE lending tightening"

  1. SUBLPDRCSM (similarity: 0.89)
     Net Percentage of Domestic Banks Tightening Standards for CRE Loans, Multifamily
     Frequency: Quarterly | Units: Percent | Popularity: 42
     Tags: sloos, commercial real estate, lending standards

  2. SUBLPDRCSN (similarity: 0.87)
     Net Percentage of Domestic Banks Tightening Standards for CRE Loans, Nonfarm Nonresidential
     Frequency: Quarterly | Units: Percent | Popularity: 38
     Tags: sloos, commercial real estate, lending standards

  3. DRCRELEXFACBS (similarity: 0.82)
     Delinquency Rate on Commercial Real Estate Loans, All Commercial Banks
     Frequency: Quarterly | Units: Percent | Popularity: 55
     Tags: delinquency, commercial real estate, banks

  4. SUBLPDRCSC (similarity: 0.79)
     Net Percentage of Domestic Banks Tightening Standards for Construction and Land Development Loans
     Frequency: Quarterly | Units: Percent | Popularity: 31
     Tags: sloos, construction, lending standards

  5. BAMLC0A4CBBB (similarity: 0.71)
     ICE BofA BBB US Corporate Index Option-Adjusted Spread
     Frequency: Daily | Units: Percent | Popularity: 68
     Tags: spread, corporate bonds, bbb
```

---

## Phase 3: Integration Points

### Integration with Existing FREDClient

Once you discover a series via search, you fetch its data with the existing client. Add the series ID to `market_assumptions.yaml` for ongoing use, or fetch ad-hoc:

```python
# Discovery workflow
results = search_fred("housing affordability metrics")
# → Returns FIXHAI, MDSP, MORTGAGE30US, etc.

# Then fetch data with existing client
from data_sources.market.sources.fred_client import FREDClient
client = FREDClient()
# For ad-hoc fetch, extend client to accept raw series IDs
data = client.get_latest_by_id("FIXHAI")
```

Add a `get_latest_by_id(series_id: str)` method to `FREDClient` that bypasses the config lookup — allows fetching any FRED series by ID without adding it to `market_assumptions.yaml` first.

### Integration with Market Context Snapshot

When building the opportunity cost context snapshot (future feature), the search tool helps answer: "For this specific deal, what FRED series are most relevant?" A multifamily deal in a high-inflation environment might want different context series than an industrial development deal in a low-rate environment.

### API Route (Optional, Low Priority)

```
POST /api/market/fred/search
Body: { "query": "...", "top_k": 10, "frequency": "Monthly" }
Response: { "results": [...] }
```

Useful if we want to expose FRED discovery in the frontend dashboard. Not required for the research use case.

---

## Implementation Plan

### Phase 1: Ingest (estimated ~3 hours)

1. Add dependencies: `uv add fredapi lancedb sentence-transformers`
2. Create `data_sources/fred_search/` package
3. Implement `models.py` — `FREDSeriesMetadata`, `FREDSearchResult` dataclasses
4. Implement `_filters.py` — scope/dedup/recency filters
5. Implement `ingest.py` — category crawl + keyword search + filter + embed + store
6. Run ingest, validate counts and a few spot-check queries
7. Write `ingest_meta.json`

### Phase 2: Search (estimated ~2 hours)

1. Implement `search.py` — `search_fred()` with metadata filtering
2. Add CLI entry point with argparse
3. Test with 10-15 natural language queries across domains
4. Add `get_latest_by_id()` to existing `FREDClient`

### Phase 3: Polish (estimated ~1 hour)

1. Add `--dry-run` and `--categories-only` flags to ingest
2. Add JSON output mode for CLI (`--json`)
3. Write tests for filters (the dedup logic is the most error-prone piece)
4. Add to `.gitignore`: `data/fred_vector_index/` (binary data, rebuild from ingest)

**Total estimate**: ~6 hours of implementation. ~15 minutes of FRED API time for full ingest (rate limited at 120 req/min with free key).

---

## Decisions and Tradeoffs

### Why Not LLM Re-ranking?

Vector search alone should be sufficient for our use case. LLM re-ranking (sending top-20 results to Claude for re-ranking + explanation) would improve result quality but adds:
- API cost per query (~$0.01-0.02 for a re-rank call)
- Latency (~2-5 seconds)
- Anthropic API dependency for what should be an offline tool

If vector search quality proves insufficient after testing, we can add LLM re-ranking as an optional `--explain` flag.

### Why Not Embed the Full Notes?

FRED notes can be 2,000+ characters with legal boilerplate, methodology descriptions, and links. Embedding the full text dilutes the semantic signal with noise. The first 500 characters reliably contain the descriptive content ("This series represents the..."). Truncation is intentional.

### Why Keep Discontinued Series Out by Default?

Discontinued series are noise for forward-looking research. However, they're useful for historical analysis. The `active_only=True` default filters them from search but they remain in the index for explicit override.

### Why File-Based (LanceDB) Instead of Supabase pgvector?

This is a developer/analyst research tool, not a production API feature. It should work:
- Offline (on a plane, at a library)
- Without Supabase credentials
- With zero network latency
- Reproducibly (same index = same results)

If we later want this in the web app, we can either serve LanceDB behind an API route or migrate to pgvector.

---

## Testing Strategy

### Ingest Tests

- **Filter correctness**: Given a known set of series metadata, verify filters produce expected output (dedup, scope, recency)
- **Idempotency**: Running ingest twice produces identical index
- **Metadata completeness**: All required fields populated, no nulls in critical columns

### Search Tests

Curated query→expected-series pairs:

| Query | Must Include | Must Not Include |
|-------|-------------|-----------------|
| "10-year treasury yield" | DGS10 | State-level variants |
| "commercial real estate loan delinquency" | DRCRELEXFACBS | Consumer loan delinquency |
| "inflation expectations" | T5YIE, T10YIE, MICH | Realized CPI |
| "housing starts" | HOUST | Home prices |
| "financial stress indicator" | STLFSI4, NFCI | Individual spreads |
| "unemployment rate" | UNRATE | State unemployment |
| "REIT performance" | WILLREITIND | Non-REIT equity indices |
| "high yield credit spread" | BAMLH0A0HYM2 | Investment grade |
| "multifamily lending" | SUBLPDRCSM, SUBLPDRCDM | Nonfarm CRE |
| "construction costs" | WPUSI012011, TLRESCONS | Consumer prices |

These serve as both regression tests and quality benchmarks.

---

## Open Questions

1. **Embedding model choice**: `all-MiniLM-L6-v2` is the standard lightweight choice. `all-mpnet-base-v2` (110M params, 420MB) scores ~3% better on retrieval benchmarks but is 5x larger and 3x slower. Given our corpus is short text (titles + truncated notes), the smaller model is likely sufficient. Test both during Phase 2 and keep whichever performs better on the curated test queries.

2. **Category list completeness**: The 13 categories listed above cover the domains we discussed (rates, housing, employment, financial conditions, prices). Should we also ingest series from categories like `32268` (International), `32360` (Academic/Research)? Broader scope = more discovery potential but larger index and more noise.

3. **Update mechanism**: Full re-ingest quarterly is simple but slow (~15 min). An incremental approach (check for new series since last ingest) would be faster but adds complexity. Start with full re-ingest; optimize only if the 15 minutes becomes painful.

4. **Tag-based grouping**: After ingest, we could auto-generate "topic clusters" by running k-means on the embeddings and labeling clusters. This would give us a browsable taxonomy of FRED content. Nice-to-have, not blocking.

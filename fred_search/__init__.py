"""
fred_search — semantic search over FRED series metadata.

Modules
-------
  ingest.py   — fetch + filter + embed + store in LanceDB
  search.py   — natural language query interface
  fetch.py    — retrieve observation data for discovered series
  models.py   — FREDSeriesMetadata and FREDSearchResult dataclasses
  _filters.py — dedup / scope / recency filtering logic
  _client.py  — FRED API client with rate limiting and retries
  _state.py   — SQLite-backed resumable ingest state

Quick start
-----------
  # 1. Build the index (once; ~15-30 min depending on FRED API)
  fred-ingest --api-key $FRED_API_KEY

  # 2. Search
  fred-search "indicators of commercial real estate credit stress"

  # 3. Fetch observation data for series of interest
  fred-fetch UNRATE DGS10 --last 12 --json

  # Or use the library API:
  from fred_search import search_fred, fetch_series

  results = search_fred("inflation expectations", top_k=5)
  data = fetch_series([r.series_id for r in results[:3]], last=12)
"""

from fred_search.fetch import fetch_series
from fred_search.ingest import run_ingest
from fred_search.models import FREDSearchResult, FREDSeriesMetadata
from fred_search.search import FREDSearcher, search_fred

__all__ = [
    "search_fred",
    "fetch_series",
    "FREDSearcher",
    "run_ingest",
    "FREDSeriesMetadata",
    "FREDSearchResult",
]

__version__ = "0.1.0"

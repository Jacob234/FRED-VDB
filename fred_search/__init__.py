"""
fred_search — semantic search over FRED series metadata.

Phases
------
  ingest.py   — fetch + filter + embed + store in LanceDB
  search.py   — natural language query interface
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

  # Or use the library API:
  from fred_search import search_fred, FREDSearcher

  results = search_fred("inflation expectations", top_k=5)
  for r in results:
      print(r.series_id, r.similarity_score, r.title)
"""

from fred_search.ingest import run_ingest
from fred_search.models import FREDSearchResult, FREDSeriesMetadata
from fred_search.search import FREDSearcher, search_fred

__all__ = [
    "search_fred",
    "FREDSearcher",
    "run_ingest",
    "FREDSeriesMetadata",
    "FREDSearchResult",
]

__version__ = "0.1.0"

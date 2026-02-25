"""
fred_search — semantic search over FRED series metadata.

Phases:
  ingest.py   — fetch + filter + embed + store in LanceDB
  search.py   — natural language query interface
  models.py   — FREDSeriesMetadata and FREDSearchResult dataclasses
  _filters.py — dedup / scope / recency filtering logic
"""

# Testing

## Current State

**No tests written yet.** The project has an empty `tests/` package (`tests/__init__.py` only).

## Test Framework

- No test framework configured in `pyproject.toml`
- No `pytest` or `unittest` dependencies declared
- No test configuration sections (`[tool.pytest.ini_options]`, etc.)

## Test Directory

```
tests/
└── __init__.py          # Empty package marker
```

## What Needs Testing

### Unit Tests
- `fred_search/models.py` — Pydantic models (`SeriesMetadata`, `SearchResult`) serialization and validation
- `fred_search/_filters.py` — Filter parsing, SQL clause generation
- `fred_search/_abbreviations.py` — Abbreviation expansion logic
- `fred_search/ingest.py` — Individual pipeline phases (fetch, deduplicate, embed, store)
- `fred_search/search.py` — Query embedding, result ranking, filter application

### Integration Tests
- End-to-end ingest pipeline with a small FRED API subset
- Search against a pre-built test index
- CLI entry points (`fred-ingest`, `fred-search`)

### Testing Challenges
- **FRED API dependency**: Ingest requires a live API key; tests should mock `httpx` calls or use fixtures
- **Embedding model**: `sentence-transformers` model loading is slow (~2s); tests should share a fixture or use a smaller model
- **LanceDB state**: Vector index stored on disk at `data/fred_vector_index/`; tests need temp directories
- **Large dataset**: Full ingest is ~840K series; tests should use small representative subsets

## Recommendations

- Add `pytest` as a dev dependency
- Create `conftest.py` with shared fixtures (mock API responses, temp LanceDB, pre-loaded model)
- Use `pytest-httpx` or `respx` for mocking HTTP calls to FRED API
- Consider `pytest-tmp-files` or stdlib `tmp_path` for isolated LanceDB instances

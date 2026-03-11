# Coding Conventions

**Analysis Date:** 2026-03-11

## Naming Patterns

**Files:**
- snake_case for all Python modules: `ingest.py`, `search.py`, `models.py`
- Leading underscore for internal/private modules: `_client.py`, `_filters.py`, `_state.py`, `_abbreviations.py`
- Public modules have no underscore prefix: `ingest.py`, `search.py`, `models.py`

**Functions:**
- snake_case for all functions: `build_embedding_text()`, `apply_filters()`, `search_fred()`
- Leading underscore for module-internal helpers: `_fetch_releases()`, `_build_where()`, `_parse_date()`
- `main()` for CLI entry points in `fred_search/ingest.py` and `fred_search/search.py`
- Use verb-first naming: `filter_stale()`, `build_embedding_text()`, `store_series_batch()`

**Variables:**
- snake_case throughout: `total_new`, `series_list`, `lance_path`
- UPPER_SNAKE_CASE for module-level constants: `_FRED_BASE`, `_MAX_LIMIT`, `_DEFAULT_RPM`, `_LANCEDB_TABLE`
- Leading underscore for private constants: `_FRED_ROOT_CATEGORY`, `_EMBEDDING_MODEL`
- Short variable names in tight loops: `s` for series items, `r` for rows, `t` for tags

**Classes:**
- PascalCase: `FREDClient`, `IngestState`, `FREDSearcher`, `FREDSeriesMetadata`
- Prefix domain-specific classes with `FRED`: `FREDSearchResult`, `FREDSeriesMetadata`, `FREDAPIError`
- Exception classes end with `Error`: `FREDAPIError`

**Types:**
- Use `@dataclass` for data transfer objects, not Pydantic: `FREDSeriesMetadata`, `FREDSearchResult`, `FilterConfig`, `FilterStats`
- Type annotations on all function signatures (parameters and return types)

## Code Style

**Formatting:**
- No automated formatter configured (no ruff, black, or isort in `pyproject.toml` or project config)
- 4-space indentation (standard Python)
- Line length appears to be ~100 characters soft limit based on existing code
- Trailing commas used in multi-line function calls and data structures

**Linting:**
- No linter configured (no ruff, flake8, pylint, or mypy in project dependencies or config)
- Code is clean regardless -- no TODO/FIXME/HACK comments exist

## Import Organization

**Order (follow this pattern in all files):**
1. `from __future__ import annotations` (always first, present in every module except `__init__.py`)
2. Standard library imports (alphabetical): `import argparse`, `import json`, `import logging`
3. Blank line
4. Third-party imports: `import httpx`, `import numpy as np`
5. Blank line
6. Local package imports: `from fred_search.models import FREDSeriesMetadata`

**Example from `fred_search/ingest.py`:**
```python
from __future__ import annotations

import argparse
import logging
import os
import time
from collections import deque
from pathlib import Path

import numpy as np

from fred_search._client import FREDClient, FREDAPIError
from fred_search._filters import FilterConfig, apply_filters
from fred_search._state import IngestState
from fred_search.models import FREDSeriesMetadata
```

**Path Aliases:**
- None. All imports use fully qualified package paths: `from fred_search._client import FREDClient`

**Lazy imports for heavy dependencies:**
- `sentence_transformers` and `lancedb` are imported inside function bodies, not at module top level
- This avoids slow startup for CLI commands that may not need ML models
- Pattern used in `fred_search/ingest.py` (`_embed()`, `_store_lancedb()`) and `fred_search/search.py` (`FREDSearcher.__init__()`)
- `tqdm` is also lazily imported with a try/except fallback in `fred_search/ingest.py`

```python
# Lazy import pattern (from fred_search/ingest.py _embed()):
def _embed(series: list[FREDSeriesMetadata]) -> tuple[list[str], "np.ndarray"]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for embedding. "
            "Install it: pip install sentence-transformers"
        ) from exc
```

## Error Handling

**Strategy: hierarchical -- catch specific, log, escalate or continue**

**Custom exceptions:**
- `FREDAPIError` in `fred_search/_client.py` -- raised for unrecoverable FRED API errors (non-retryable HTTP status codes, exhausted retries)

**Pattern 1 -- Catch-and-continue for batch operations:**
- In ingest phases, individual item failures are caught, logged, and the loop continues
- Used in `_fetch_series_by_releases()`, `_fetch_series_by_categories()`, `_enrich_tags()`
```python
try:
    series_list = list(client.get_release_series(rid))
    ...
except FREDAPIError as exc:
    logger.error("  release %d failed (non-retryable): %s", rid, exc)
    state.mark_release_error(rid, str(exc))
except Exception as exc:
    logger.error("  release %d unexpected error: %s", rid, exc)
    state.mark_release_error(rid, str(exc))
```

**Pattern 2 -- Raise RuntimeError for missing dependencies:**
- Used when lazy imports fail for `sentence-transformers`, `lancedb`
- Always chains the original ImportError with `from exc`
```python
except ImportError as exc:
    raise RuntimeError("lancedb is required. Install it: pip install lancedb") from exc
```

**Pattern 3 -- Return None for parse failures:**
- `_parse_date()` and `observation_end_date()` return `None` on `ValueError`/`TypeError`
- Callers treat `None` as "benefit of the doubt" -- keep the item

**Pattern 4 -- Retry with backoff for transient failures:**
- `FREDClient._get()` retries on HTTP 429, 500, 502, 503, 504 and network errors
- Exponential backoff with jitter: `2^attempt * 10 +/- 5 seconds`
- Up to 5 attempts before raising `FREDAPIError`

## Logging

**Framework:** Python stdlib `logging`

**Setup pattern:** Each module creates its own logger at module level:
```python
logger = logging.getLogger(__name__)
```

**Log levels used:**
- `logger.info()` -- Phase transitions, progress milestones, summary stats
- `logger.warning()` -- Transient failures, non-critical issues (e.g., failed child category fetch)
- `logger.error()` -- Per-item failures in batch operations, critical issues
- `logger.debug()` -- Retry sleeps, per-release fetch details, pagination progress

**Format string style:** Use `%s`/`%d` substitution (NOT f-strings) for lazy evaluation:
```python
logger.info("Phase 2: fetching series for %d pending releases...", len(pending))
```

**CLI logging config (set in `main()` functions):**
```python
logging.basicConfig(
    level=getattr(logging, args.log_level),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
```

## Comments

**When to Comment:**
- Module-level docstrings on every file explaining purpose, design decisions, and usage
- Inline comments for non-obvious domain logic (e.g., FRED API quirks, math formulas)
- Section separators using `# ----` comment blocks to delimit logical groups within files

**Section separator pattern (used throughout):**
```python
# ---------------------------------------------------------------------------
# Phase 2: Series fetch via releases
# ---------------------------------------------------------------------------
```

**Docstrings:**
- NumPy-style docstrings with `Parameters` / `Returns` sections on public functions and classes
- Brief single-line docstrings on simple internal helpers
- Class docstrings include parameter descriptions
```python
class FREDClient:
    """
    Thin FRED REST API client focused on series discovery endpoints.

    Parameters
    ----------
    api_key:
        Your FRED API key (32-char hex string).
    requests_per_minute:
        Target request rate. ...
    """
```

## Function Design

**Size:** Functions are focused and single-purpose. Largest functions are ~60 lines (ingest phase functions). Most are 10-30 lines.

**Parameters:**
- Use type annotations for all parameters
- Use `| None` union syntax (not `Optional[]`) for nullable params: `frequency: str | None = None`
- Use default values for optional configuration: `top_k: int = _DEFAULT_TOP_K`
- Configuration objects for groups of related settings: `FilterConfig` dataclass

**Return Values:**
- Always annotated: `-> list[FREDSearchResult]`, `-> int`, `-> None`
- Tuple returns for multi-value: `-> tuple[list[str], np.ndarray]`
- Use `| None` for fallible returns: `-> date | None`
- String-quoted forward references for heavy types: `-> "np.ndarray"`

## Module Design

**Exports:**
- Explicit `__all__` in `fred_search/__init__.py` listing public API: `search_fred`, `FREDSearcher`, `run_ingest`, `FREDSeriesMetadata`, `FREDSearchResult`
- `__version__` defined in `__init__.py`

**Barrel Files:**
- `fred_search/__init__.py` re-exports key symbols from submodules
- Users can `from fred_search import search_fred` instead of `from fred_search.search import search_fred`

**Public vs Private:**
- Underscore-prefixed files (`_client.py`, `_filters.py`, `_state.py`, `_abbreviations.py`) are internal implementation
- Non-prefixed files (`ingest.py`, `search.py`, `models.py`) define the public interface
- Underscore-prefixed functions within modules are private helpers

## Dataclass Patterns

**Use stdlib `@dataclass`, not Pydantic:**
```python
@dataclass
class FREDSeriesMetadata:
    series_id: str
    title: str
    ...
    is_discontinued: bool = False
    tags: list[str] = field(default_factory=list)
```

**Class methods for construction from external data:**
```python
@classmethod
def from_api_response(cls, raw: dict[str, Any], source: str = "") -> "FREDSeriesMetadata":
```

**Custom `__repr__` for readable debug output:**
```python
def __repr__(self) -> str:
    return (
        f"FREDSeriesMetadata({self.series_id!r}, title={self.title[:60]!r}, "
        f"freq={self.frequency!r}, pop={self.popularity})"
    )
```

## Context Manager Pattern

**Classes managing resources implement `__enter__`/`__exit__`:**
- `FREDClient` -- manages `httpx.Client` connection pool
- `IngestState` -- manages SQLite connection

```python
def close(self) -> None:
    self._http.close()

def __enter__(self) -> "FREDClient":
    return self

def __exit__(self, *_: Any) -> None:
    self.close()
```

**Usage:**
```python
with FREDClient(api_key) as client:
    ...
with IngestState(state_path) as state:
    ...
```

## CLI Patterns

**Use `argparse` for CLI interfaces (not click or typer):**
- Each CLI module (`ingest.py`, `search.py`) defines a `main()` function
- Entry points registered in `pyproject.toml` `[project.scripts]`
- `argparse.RawDescriptionHelpFormatter` for multi-line help text
- Environment variable fallback for secrets: `default=os.environ.get("FRED_API_KEY", "")`

---

*Convention analysis: 2026-03-11*

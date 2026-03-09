"""
FRED API client with rate limiting and automatic retry.

Design
------
- All requests are synchronous (sequential batch processing; async adds complexity
  with no throughput benefit when we're intentionally rate-limiting to one requests
  per ~0.7 seconds).
- Rate limiter: token bucket — tracks last request time and sleeps the gap.
  Default: 85 r/min (0.71 s/request), well below the advertised 120 r/min,
  because the actual enforced limit for metadata-heavy endpoints is often lower.
- Retry: exponential backoff with jitter on 429, 500, 502, 503. Up to 5 attempts.
- Pagination: every list endpoint uses offset/limit. Iterators yield individual
  items so callers don't need to manage pages.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Iterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred"
_MAX_LIMIT = 1000           # FRED API hard cap per page
_DEFAULT_RPM = 85           # requests per minute (conservative)
_MAX_RETRIES = 5
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class FREDAPIError(Exception):
    """Raised when the FRED API returns an unrecoverable error."""


class FREDClient:
    """
    Thin FRED REST API client focused on series discovery endpoints.

    Parameters
    ----------
    api_key:
        Your FRED API key (32-char hex string).
    requests_per_minute:
        Target request rate. The FRED TOS advertises 120 r/min but in practice
        metadata endpoints can trigger rate limiting below that. 85 is a safe
        default; lower it if you see persistent 429s.
    """

    def __init__(
        self,
        api_key: str,
        requests_per_minute: int = _DEFAULT_RPM,
    ) -> None:
        self._api_key = api_key
        self._min_interval = 60.0 / requests_per_minute
        self._last_call_at: float = 0.0
        # Reuse a single httpx client for connection pooling.
        self._http = httpx.Client(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait(self) -> None:
        """Enforce the minimum inter-request interval."""
        elapsed = time.monotonic() - self._last_call_at
        remaining = self._min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """Make a single rate-limited, retried GET request."""
        url = f"{_FRED_BASE}/{endpoint}"
        params["api_key"] = self._api_key
        params["file_type"] = "json"

        for attempt in range(_MAX_RETRIES):
            self._wait()
            self._last_call_at = time.monotonic()

            try:
                resp = self._http.get(url, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning("Network error on %s (attempt %d): %s", endpoint, attempt + 1, exc)
                self._backoff(attempt)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in _RETRY_STATUSES:
                logger.warning(
                    "HTTP %d on %s (attempt %d/%d) — backing off",
                    resp.status_code, endpoint, attempt + 1, _MAX_RETRIES,
                )
                self._backoff(attempt)
                continue

            # Non-retryable error (400, 403, 404, etc.)
            raise FREDAPIError(
                f"FRED API error {resp.status_code} on {endpoint}: {resp.text[:300]}"
            )

        raise FREDAPIError(
            f"Exhausted {_MAX_RETRIES} retries for {endpoint} with params {params}"
        )

    @staticmethod
    def _backoff(attempt: int) -> None:
        """Exponential backoff with jitter: 2^n * [5, 15] seconds."""
        base = (2 ** attempt) * 10
        jitter = random.uniform(-5, 5)
        sleep_time = max(1.0, base + jitter)
        logger.debug("Sleeping %.1f s before retry", sleep_time)
        time.sleep(sleep_time)

    def _paginate(self, endpoint: str, key: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Generic paginator for any FRED list endpoint.

        Parameters
        ----------
        endpoint:
            FRED endpoint path (e.g. "releases").
        key:
            The JSON key that holds the list (e.g. "releases", "seriess").
        **params:
            Additional query parameters (order_by, category_id, etc.).
        """
        offset = 0
        total: int | None = None

        while True:
            data = self._get(endpoint, limit=_MAX_LIMIT, offset=offset, **params)
            items: list[dict] = data.get(key, [])
            yield from items

            if total is None:
                total = int(data.get("count", 0))

            offset += len(items)
            if offset >= total or not items:
                break
            logger.debug("%s: fetched %d/%d", endpoint, offset, total)

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------

    def get_all_releases(self) -> Iterator[dict[str, Any]]:
        """Iterate over every FRED release. Typically ~350 total; one page."""
        yield from self._paginate("releases", "releases", order_by="release_id")

    def get_release_series(self, release_id: int) -> Iterator[dict[str, Any]]:
        """Iterate over all series belonging to a release.

        Note: FRED uses the key 'seriess' (double-s) for series lists.
        """
        yield from self._paginate(
            "release/series",
            "seriess",
            release_id=release_id,
            order_by="series_id",
        )

    # ------------------------------------------------------------------
    # Category tree
    # ------------------------------------------------------------------

    def get_category_children(self, category_id: int) -> list[dict[str, Any]]:
        """Return child categories for a given parent category ID."""
        data = self._get("category/children", category_id=category_id)
        return data.get("categories", [])

    def get_category_series(self, category_id: int) -> Iterator[dict[str, Any]]:
        """Iterate over all series in a category.

        Note: also uses 'seriess' key.
        """
        yield from self._paginate(
            "category/series",
            "seriess",
            category_id=category_id,
            order_by="series_id",
        )

    def get_series_tags(self, series_id: str) -> list[str]:
        """Fetch the tag list for a single series.

        This is a supplementary call; during bulk ingest we skip it to avoid
        doubling API calls. Tags are fetched separately only when needed.
        """
        data = self._get("series/tags", series_id=series_id)
        return [t["name"] for t in data.get("tags", [])]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "FREDClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

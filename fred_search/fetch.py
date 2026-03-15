"""
Fetch FRED observation data for one or more series by ID.

This is the "data retrieval" counterpart to ``search.py``. After semantic
search identifies relevant series IDs, use this module to pull the actual
time series values from the FRED API.

CLI
---
    fred-fetch UNRATE DGS10 --start 2020-01-01
    fred-fetch CPIAUCSL --last 24
    fred-fetch PAYEMS --start 2023-01-01 --end 2024-12-31

Library
-------
    from fred_search import fetch_series

    data = fetch_series(["UNRATE", "DGS10"], start="2020-01-01")
    for series_id, observations in data.items():
        print(series_id, len(observations), "observations")
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from typing import Any

from fred_search._client import FREDClient

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_YEARS = 5


def fetch_series(
    series_ids: list[str],
    api_key: str | None = None,
    start: str | None = None,
    end: str | None = None,
    last: int | None = None,
) -> dict[str, list[dict[str, str | float | None]]]:
    """
    Fetch observation data for one or more FRED series.

    Parameters
    ----------
    series_ids:
        One or more FRED series identifiers (e.g. ``["UNRATE", "DGS10"]``).
    api_key:
        FRED API key. Falls back to ``FRED_API_KEY`` env var.
    start:
        Observation start date (YYYY-MM-DD). Defaults to 5 years ago.
    end:
        Observation end date (YYYY-MM-DD). Defaults to today.
    last:
        If set, return only the last N observations per series.
        Overrides ``start`` — fetches all data then truncates.

    Returns
    -------
    Dict mapping each series_id to a list of observations::

        {"UNRATE": [{"date": "2024-01-01", "value": 3.7}, ...]}

    Values are floats where parseable, or None for missing data
    (FRED returns ``"."`` for missing observations).
    """
    key = api_key or os.environ.get("FRED_API_KEY")
    if not key:
        raise ValueError(
            "FRED API key required. Set FRED_API_KEY env var or pass api_key=."
        )

    if not start and not last:
        start = (date.today() - timedelta(days=365 * _DEFAULT_LOOKBACK_YEARS)).isoformat()

    result: dict[str, list[dict[str, str | float | None]]] = {}

    with FREDClient(api_key=key) as client:
        for sid in series_ids:
            sid_upper = sid.upper()
            logger.info("Fetching observations for %s", sid_upper)

            raw = client.get_series_observations(
                series_id=sid_upper,
                observation_start=start,
                observation_end=end,
            )

            observations = _parse_observations(raw)

            if last is not None:
                observations = observations[-last:]

            result[sid_upper] = observations

    return result


def _parse_observations(
    raw: list[dict[str, str]],
) -> list[dict[str, str | float | None]]:
    """Convert FRED string values to floats, treating '.' as None."""
    parsed = []
    for obs in raw:
        val_str = obs["value"]
        if val_str == ".":
            value: float | None = None
        else:
            try:
                value = float(val_str)
            except (ValueError, TypeError):
                value = None
        parsed.append({"date": obs["date"], "value": value})
    return parsed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_output(
    data: dict[str, list[dict[str, str | float | None]]],
    as_json: bool,
) -> str:
    if as_json:
        return json.dumps(data, indent=2)

    lines = []
    for sid, observations in data.items():
        lines.append(f"\n{sid}  ({len(observations)} observations)")
        lines.append("-" * 40)
        for obs in observations:
            val = obs["value"]
            val_str = f"{val:>12.4f}" if val is not None else "           ."
            lines.append(f"  {obs['date']}  {val_str}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch FRED observation data for one or more series.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  fred-fetch UNRATE DGS10 --start 2020-01-01\n"
            "  fred-fetch CPIAUCSL --last 24\n"
            "  fred-fetch PAYEMS --start 2023-01-01 --end 2024-12-31 --json"
        ),
    )
    parser.add_argument(
        "series_ids", nargs="+", metavar="SERIES_ID",
        help="One or more FRED series identifiers",
    )
    parser.add_argument(
        "--start", default=None, metavar="YYYY-MM-DD",
        help=f"Observation start date (default: {_DEFAULT_LOOKBACK_YEARS} years ago)",
    )
    parser.add_argument(
        "--end", default=None, metavar="YYYY-MM-DD",
        help="Observation end date (default: most recent)",
    )
    parser.add_argument(
        "--last", type=int, default=None, metavar="N",
        help="Return only the last N observations per series",
    )
    parser.add_argument(
        "--api-key", default=None, metavar="KEY",
        help="FRED API key (default: FRED_API_KEY env var)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON (default: human-readable table)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    try:
        data = fetch_series(
            series_ids=args.series_ids,
            api_key=args.api_key,
            start=args.start,
            end=args.end,
            last=args.last,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not data or all(len(v) == 0 for v in data.values()):
        print("No observations found.")
        return

    print(_format_output(data, as_json=args.json))


if __name__ == "__main__":
    main()

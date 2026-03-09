"""
Filtering pipeline for FRED series metadata.

Filters are applied in order by apply_filters(). Each filter returns a
(kept, dropped_count) tuple so the caller can log stats at each step.

Filter order matters: cheap structural filters run first to reduce work for
the more expensive text-based ones.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from fred_search.models import FREDSeriesMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_MIN_POPULARITY = 5
_DEFAULT_MAX_STALE_DAYS = 730          # 2 years
_DEFAULT_MIN_OBSERVATION_DAYS = 365    # series with < 1 year of data are noise


@dataclass
class FilterConfig:
    """Tunable knobs for the filter pipeline."""

    min_popularity: int = _DEFAULT_MIN_POPULARITY
    max_stale_days: int = _DEFAULT_MAX_STALE_DAYS
    min_observation_days: int = _DEFAULT_MIN_OBSERVATION_DAYS
    drop_discontinued: bool = True
    # If True, drop one of each SA/NSA pair, keeping the SA version.
    dedup_seasonal_adjustment: bool = True


@dataclass
class FilterStats:
    """Counts how many series were removed at each stage."""

    initial: int = 0
    after_discontinued: int = 0
    after_recency: int = 0
    after_popularity: int = 0
    after_observation_span: int = 0
    after_sa_dedup: int = 0
    final: int = 0

    def log(self) -> None:
        logger.info(
            "Filter pipeline:\n"
            "  initial:          %6d\n"
            "  dropped discontinued: -%d → %d\n"
            "  dropped stale:        -%d → %d\n"
            "  dropped low-pop:      -%d → %d\n"
            "  dropped short-span:   -%d → %d\n"
            "  SA dedup:             -%d → %d (final)",
            self.initial,
            self.initial - self.after_discontinued, self.after_discontinued,
            self.after_discontinued - self.after_recency, self.after_recency,
            self.after_recency - self.after_popularity, self.after_popularity,
            self.after_popularity - self.after_observation_span, self.after_observation_span,
            self.after_observation_span - self.after_sa_dedup, self.after_sa_dedup,
        )


# ---------------------------------------------------------------------------
# Individual filters
# ---------------------------------------------------------------------------

def filter_discontinued(
    series: list[FREDSeriesMetadata],
) -> list[FREDSeriesMetadata]:
    """Drop series explicitly marked as discontinued."""
    return [s for s in series if not s.is_discontinued]


def filter_stale(
    series: list[FREDSeriesMetadata],
    max_stale_days: int = _DEFAULT_MAX_STALE_DAYS,
    reference_date: date | None = None,
) -> list[FREDSeriesMetadata]:
    """
    Drop series whose most recent observation is older than max_stale_days.

    Series with unparseable observation_end are kept (benefit of the doubt).
    """
    ref = reference_date or date.today()
    cutoff = ref - timedelta(days=max_stale_days)
    kept = []
    for s in series:
        obs_end = s.observation_end_date()
        if obs_end is None or obs_end >= cutoff:
            kept.append(s)
    return kept


def filter_popularity(
    series: list[FREDSeriesMetadata],
    min_popularity: int = _DEFAULT_MIN_POPULARITY,
) -> list[FREDSeriesMetadata]:
    """Drop series whose FRED popularity score is below the threshold.

    Popularity 0–100; the vast majority of 840K series have popularity < 5.
    This single filter removes ~60-70% of the corpus.
    """
    return [s for s in series if s.popularity >= min_popularity]


def filter_short_span(
    series: list[FREDSeriesMetadata],
    min_days: int = _DEFAULT_MIN_OBSERVATION_DAYS,
) -> list[FREDSeriesMetadata]:
    """Drop series with fewer than min_days of observation history.

    One-off or experimental series rarely span a full year. This removes
    placeholder series and single-release snapshots.
    """
    kept = []
    for s in series:
        start = _parse_date(s.observation_start)
        end = s.observation_end_date()
        if start is None or end is None:
            kept.append(s)  # keep if we can't parse
            continue
        if (end - start).days >= min_days:
            kept.append(s)
    return kept


def dedup_seasonal_adjustment(
    series: list[FREDSeriesMetadata],
) -> list[FREDSeriesMetadata]:
    """
    When a series exists in both SA and NSA variants, keep only the SA version.

    Detection heuristic: group by (normalised_title, frequency, units). If a
    group contains one SA and one NSA member, drop the NSA. Groups with only
    NSA members are kept unchanged (there's no SA alternative).

    This is intentionally conservative — rather than over-dedup, we require the
    normalised titles to be an exact match (after stripping SA/NSA indicators).
    """
    _SA_INDICATORS = re.compile(
        r",?\s*(seasonally adjusted|not seasonally adjusted|sa|nsa)\b",
        flags=re.IGNORECASE,
    )

    def normalise(title: str) -> str:
        return _SA_INDICATORS.sub("", title).strip().lower()

    _SA_VALUES = {"seasonally adjusted", "annual rate, seasonally adjusted"}
    _NSA_VALUES = {"not seasonally adjusted", "annual rate, not seasonally adjusted"}

    # Group by (normalised_title, frequency, units).
    groups: dict[tuple[str, str, str], list[FREDSeriesMetadata]] = {}
    for s in series:
        key = (normalise(s.title), s.frequency.lower(), s.units.lower())
        groups.setdefault(key, []).append(s)

    kept: list[FREDSeriesMetadata] = []
    for group in groups.values():
        if len(group) == 1:
            kept.append(group[0])
            continue

        sa_members  = [s for s in group if s.seasonal_adjustment.lower() in _SA_VALUES]
        nsa_members = [s for s in group if s.seasonal_adjustment.lower() in _NSA_VALUES]
        other       = [s for s in group if s not in sa_members and s not in nsa_members]

        if sa_members and nsa_members:
            # Keep SA + any "other" (e.g. "Annual Rate" variants without explicit SA label)
            kept.extend(sa_members + other)
        else:
            # All same adjustment — keep all
            kept.extend(group)

    return kept


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def apply_filters(
    series: list[FREDSeriesMetadata],
    cfg: FilterConfig | None = None,
) -> tuple[list[FREDSeriesMetadata], FilterStats]:
    """
    Run the full filter pipeline and return (filtered_series, stats).

    Parameters
    ----------
    series:
        Raw list of FREDSeriesMetadata from the ingest fetch phase.
    cfg:
        Optional FilterConfig; defaults are used if not supplied.
    """
    cfg = cfg or FilterConfig()
    stats = FilterStats(initial=len(series))

    if cfg.drop_discontinued:
        series = filter_discontinued(series)
    stats.after_discontinued = len(series)

    series = filter_stale(series, max_stale_days=cfg.max_stale_days)
    stats.after_recency = len(series)

    series = filter_popularity(series, min_popularity=cfg.min_popularity)
    stats.after_popularity = len(series)

    series = filter_short_span(series, min_days=cfg.min_observation_days)
    stats.after_observation_span = len(series)

    if cfg.dedup_seasonal_adjustment:
        series = dedup_seasonal_adjustment(series)
    stats.after_sa_dedup = len(series)

    stats.final = len(series)
    stats.log()
    return series, stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> date | None:
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None

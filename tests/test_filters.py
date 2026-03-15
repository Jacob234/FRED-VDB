"""Tests for the FRED series filtering pipeline."""

import pytest
from datetime import date, timedelta

from fred_search._filters import (
    FilterConfig,
    FilterStats,
    apply_filters,
    dedup_seasonal_adjustment,
    filter_discontinued,
    filter_popularity,
    filter_short_span,
    filter_stale,
)
from fred_search.models import FREDSeriesMetadata


def _make_series(**overrides) -> FREDSeriesMetadata:
    """Factory for test series with sensible defaults."""
    defaults = {
        "series_id": "TEST001",
        "title": "Test Series",
        "notes": "A test series for unit testing.",
        "frequency": "Monthly",
        "units": "Percent",
        "seasonal_adjustment": "Seasonally Adjusted",
        "observation_start": "2000-01-01",
        "observation_end": date.today().isoformat(),
        "popularity": 50,
        "last_updated": "2024-01-01 08:00:00-06",
        "is_discontinued": False,
        "tags": ["test"],
        "source": "Test Source",
    }
    defaults.update(overrides)
    return FREDSeriesMetadata(**defaults)


class TestFilterDiscontinued:
    def test_keeps_active(self):
        series = [_make_series(is_discontinued=False)]
        assert len(filter_discontinued(series)) == 1

    def test_drops_discontinued(self):
        series = [_make_series(is_discontinued=True)]
        assert len(filter_discontinued(series)) == 0

    def test_mixed(self):
        series = [
            _make_series(series_id="ACTIVE", is_discontinued=False),
            _make_series(series_id="DEAD", is_discontinued=True),
        ]
        result = filter_discontinued(series)
        assert len(result) == 1
        assert result[0].series_id == "ACTIVE"


class TestFilterStale:
    def test_keeps_recent(self):
        series = [_make_series(observation_end=date.today().isoformat())]
        assert len(filter_stale(series, max_stale_days=730)) == 1

    def test_drops_old(self):
        old_date = (date.today() - timedelta(days=1000)).isoformat()
        series = [_make_series(observation_end=old_date)]
        assert len(filter_stale(series, max_stale_days=730)) == 0

    def test_boundary_exactly_at_cutoff(self):
        cutoff_date = (date.today() - timedelta(days=730)).isoformat()
        series = [_make_series(observation_end=cutoff_date)]
        # Exactly at cutoff should be kept (>=)
        assert len(filter_stale(series, max_stale_days=730)) == 1

    def test_keeps_unparseable_dates(self):
        series = [_make_series(observation_end="not-a-date")]
        # Benefit of the doubt — keep it
        assert len(filter_stale(series, max_stale_days=730)) == 1

    def test_reference_date_override(self):
        ref = date(2024, 1, 1)
        series = [_make_series(observation_end="2022-06-01")]
        # 2022-06-01 is ~549 days before 2024-01-01, within 730
        assert len(filter_stale(series, max_stale_days=730, reference_date=ref)) == 1
        # But not within 365
        assert len(filter_stale(series, max_stale_days=365, reference_date=ref)) == 0


class TestFilterPopularity:
    def test_keeps_above_threshold(self):
        series = [_make_series(popularity=50)]
        assert len(filter_popularity(series, min_popularity=10)) == 1

    def test_drops_below_threshold(self):
        series = [_make_series(popularity=3)]
        assert len(filter_popularity(series, min_popularity=5)) == 0

    def test_keeps_at_threshold(self):
        series = [_make_series(popularity=5)]
        assert len(filter_popularity(series, min_popularity=5)) == 1

    def test_zero_threshold_keeps_all(self):
        series = [_make_series(popularity=0)]
        assert len(filter_popularity(series, min_popularity=0)) == 1


class TestFilterShortSpan:
    def test_keeps_long_span(self):
        series = [_make_series(
            observation_start="2000-01-01",
            observation_end="2024-01-01",
        )]
        assert len(filter_short_span(series, min_days=365)) == 1

    def test_drops_short_span(self):
        series = [_make_series(
            observation_start="2024-01-01",
            observation_end="2024-03-01",
        )]
        assert len(filter_short_span(series, min_days=365)) == 0

    def test_keeps_unparseable_start(self):
        series = [_make_series(observation_start="bad")]
        assert len(filter_short_span(series, min_days=365)) == 1

    def test_keeps_unparseable_end(self):
        series = [_make_series(observation_end="bad")]
        assert len(filter_short_span(series, min_days=365)) == 1


class TestDedupSeasonalAdjustment:
    def test_keeps_sa_drops_nsa(self):
        sa = _make_series(
            series_id="UNRATE",
            title="Unemployment Rate",
            seasonal_adjustment="Seasonally Adjusted",
        )
        nsa = _make_series(
            series_id="UNRATENSA",
            title="Unemployment Rate",
            seasonal_adjustment="Not Seasonally Adjusted",
        )
        result = dedup_seasonal_adjustment([sa, nsa])
        assert len(result) == 1
        assert result[0].series_id == "UNRATE"

    def test_keeps_nsa_when_no_sa_exists(self):
        nsa = _make_series(
            series_id="ONLY_NSA",
            title="Unique Series",
            seasonal_adjustment="Not Seasonally Adjusted",
        )
        result = dedup_seasonal_adjustment([nsa])
        assert len(result) == 1

    def test_different_concepts_not_deduped(self):
        s1 = _make_series(
            series_id="A",
            title="Unemployment Rate",
            seasonal_adjustment="Seasonally Adjusted",
        )
        s2 = _make_series(
            series_id="B",
            title="Inflation Rate",
            seasonal_adjustment="Seasonally Adjusted",
        )
        result = dedup_seasonal_adjustment([s1, s2])
        assert len(result) == 2

    def test_different_frequencies_not_grouped(self):
        monthly_sa = _make_series(
            series_id="M_SA",
            title="GDP",
            frequency="Monthly",
            seasonal_adjustment="Seasonally Adjusted",
        )
        quarterly_nsa = _make_series(
            series_id="Q_NSA",
            title="GDP",
            frequency="Quarterly",
            seasonal_adjustment="Not Seasonally Adjusted",
        )
        result = dedup_seasonal_adjustment([monthly_sa, quarterly_nsa])
        # Different frequencies → different groups → both kept
        assert len(result) == 2


class TestApplyFilters:
    def test_full_pipeline_keeps_good_series(self):
        good = _make_series(
            is_discontinued=False,
            popularity=50,
            observation_start="2000-01-01",
            observation_end=date.today().isoformat(),
        )
        result, stats = apply_filters([good])
        assert len(result) == 1
        assert stats.initial == 1
        assert stats.final == 1

    def test_full_pipeline_drops_bad_series(self):
        bad = _make_series(
            is_discontinued=True,
            popularity=0,
            observation_end="1990-01-01",
        )
        result, stats = apply_filters([bad])
        assert len(result) == 0
        assert stats.initial == 1

    def test_custom_config(self):
        series = [_make_series(popularity=3)]
        cfg = FilterConfig(min_popularity=5)
        result, _ = apply_filters(series, cfg)
        assert len(result) == 0

        cfg2 = FilterConfig(min_popularity=0)
        result2, _ = apply_filters(series, cfg2)
        assert len(result2) == 1

    def test_stats_tracking(self):
        series = [
            _make_series(series_id="A", is_discontinued=False, popularity=50),
            _make_series(series_id="B", is_discontinued=True, popularity=50),
            _make_series(series_id="C", is_discontinued=False, popularity=1,
                         observation_end=(date.today() - timedelta(days=1000)).isoformat()),
        ]
        cfg = FilterConfig(min_popularity=5)
        _, stats = apply_filters(series, cfg)
        assert stats.initial == 3
        assert stats.after_discontinued == 2  # B dropped
        assert stats.after_recency == 1       # C dropped (stale)
        # A has pop=50, passes min_popularity=5

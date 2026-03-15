"""Tests for search module helpers."""

import pytest
from datetime import date, timedelta

from fred_search.models import FREDSearchResult
from fred_search.search import _build_where, _format_results


class TestBuildWhere:
    def test_no_filters(self):
        result = _build_where(
            frequency=None,
            min_popularity=None,
            active_only=False,
            max_stale_days=None,
        )
        assert result is None

    def test_frequency_filter(self):
        result = _build_where(
            frequency="Monthly",
            min_popularity=None,
            active_only=False,
            max_stale_days=None,
        )
        assert result == "frequency = 'Monthly'"

    def test_min_popularity_filter(self):
        result = _build_where(
            frequency=None,
            min_popularity=10,
            active_only=False,
            max_stale_days=None,
        )
        assert result == "popularity >= 10"

    def test_active_only_default_stale(self):
        result = _build_where(
            frequency=None,
            min_popularity=None,
            active_only=True,
            max_stale_days=None,
        )
        cutoff = (date.today() - timedelta(days=730)).isoformat()
        assert result == f"observation_end >= '{cutoff}'"

    def test_active_only_custom_stale(self):
        result = _build_where(
            frequency=None,
            min_popularity=None,
            active_only=True,
            max_stale_days=365,
        )
        cutoff = (date.today() - timedelta(days=365)).isoformat()
        assert result == f"observation_end >= '{cutoff}'"

    def test_combined_filters(self):
        result = _build_where(
            frequency="Daily",
            min_popularity=20,
            active_only=True,
            max_stale_days=None,
        )
        assert "frequency = 'Daily'" in result
        assert "popularity >= 20" in result
        assert "observation_end >=" in result
        assert " AND " in result

    def test_min_popularity_zero(self):
        result = _build_where(
            frequency=None,
            min_popularity=0,
            active_only=False,
            max_stale_days=None,
        )
        assert result == "popularity >= 0"


class TestFormatResults:
    def _make_result(self, **overrides) -> FREDSearchResult:
        defaults = {
            "series_id": "UNRATE",
            "title": "Unemployment Rate",
            "notes": "The unemployment rate represents...",
            "frequency": "Monthly",
            "units": "Percent",
            "seasonal_adjustment": "Seasonally Adjusted",
            "tags": ["labor", "unemployment"],
            "popularity": 95,
            "similarity_score": 0.8500,
            "source": "BLS",
            "observation_end": "2024-12-01",
        }
        defaults.update(overrides)
        return FREDSearchResult(**defaults)

    def test_text_format_includes_series_id(self):
        results = [self._make_result()]
        output = _format_results(results, as_json=False)
        assert "UNRATE" in output

    def test_text_format_includes_score(self):
        results = [self._make_result(similarity_score=0.8500)]
        output = _format_results(results, as_json=False)
        assert "0.850" in output

    def test_text_format_includes_tags(self):
        results = [self._make_result(tags=["labor", "bls"])]
        output = _format_results(results, as_json=False)
        assert "labor" in output

    def test_text_format_shows_category_when_present(self):
        results = [self._make_result(category_path="Employment > Labor")]
        output = _format_results(results, as_json=False)
        assert "Category: Employment > Labor" in output

    def test_text_format_omits_category_when_empty(self):
        results = [self._make_result(category_path="")]
        output = _format_results(results, as_json=False)
        assert "Category:" not in output

    def test_json_format(self):
        import json
        results = [self._make_result()]
        output = _format_results(results, as_json=True)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["series_id"] == "UNRATE"

    def test_numbering(self):
        results = [
            self._make_result(series_id="A"),
            self._make_result(series_id="B"),
            self._make_result(series_id="C"),
        ]
        output = _format_results(results, as_json=False)
        assert "1." in output
        assert "2." in output
        assert "3." in output

    def test_notes_truncated_in_display(self):
        long_notes = "x" * 200
        results = [self._make_result(notes=long_notes)]
        output = _format_results(results, as_json=False)
        # Should be truncated with ellipsis
        assert "…" in output

    def test_empty_results(self):
        output = _format_results([], as_json=False)
        assert output == ""  # no results → empty string

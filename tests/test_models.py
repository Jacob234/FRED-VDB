"""Tests for FRED data models."""

import pytest
from datetime import date

from fred_search.models import FREDSearchResult, FREDSeriesMetadata


class TestFREDSeriesMetadata:
    def test_from_api_response_full(self):
        raw = {
            "id": "DGS10",
            "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
            "notes": "For further information...",
            "frequency": "Daily",
            "units": "Percent",
            "seasonal_adjustment": "Not Seasonally Adjusted",
            "observation_start": "1962-01-02",
            "observation_end": "2024-12-31",
            "popularity": 95,
            "last_updated": "2024-12-31 15:17:02-06",
        }
        s = FREDSeriesMetadata.from_api_response(raw, source="H.15")
        assert s.series_id == "DGS10"
        assert s.popularity == 95
        assert s.source == "H.15"
        assert s.frequency == "Daily"

    def test_from_api_response_missing_fields(self):
        raw = {"id": "MINIMAL"}
        s = FREDSeriesMetadata.from_api_response(raw)
        assert s.series_id == "MINIMAL"
        assert s.title == ""
        assert s.notes == ""
        assert s.popularity == 0
        assert s.source == ""

    def test_from_api_response_null_popularity(self):
        raw = {"id": "NEW", "popularity": None}
        s = FREDSeriesMetadata.from_api_response(raw)
        assert s.popularity == 0

    def test_observation_end_date_valid(self):
        s = FREDSeriesMetadata(
            series_id="T", title="", notes="", frequency="",
            units="", seasonal_adjustment="",
            observation_start="", observation_end="2024-06-15",
            popularity=0, last_updated="",
        )
        assert s.observation_end_date() == date(2024, 6, 15)

    def test_observation_end_date_invalid(self):
        s = FREDSeriesMetadata(
            series_id="T", title="", notes="", frequency="",
            units="", seasonal_adjustment="",
            observation_start="", observation_end="not-a-date",
            popularity=0, last_updated="",
        )
        assert s.observation_end_date() is None

    def test_observation_end_date_empty(self):
        s = FREDSeriesMetadata(
            series_id="T", title="", notes="", frequency="",
            units="", seasonal_adjustment="",
            observation_start="", observation_end="",
            popularity=0, last_updated="",
        )
        assert s.observation_end_date() is None

    def test_default_fields(self):
        s = FREDSeriesMetadata(
            series_id="T", title="", notes="", frequency="",
            units="", seasonal_adjustment="",
            observation_start="", observation_end="",
            popularity=0, last_updated="",
        )
        assert s.tags == []
        assert s.source == ""
        assert s.category_path == ""
        assert s.is_discontinued is False


class TestFREDSearchResult:
    def test_as_dict(self):
        r = FREDSearchResult(
            series_id="UNRATE",
            title="Unemployment Rate",
            notes="The unemployment rate...",
            frequency="Monthly",
            units="Percent",
            seasonal_adjustment="Seasonally Adjusted",
            tags=["labor", "unemployment"],
            popularity=95,
            similarity_score=0.85,
            source="BLS",
            observation_end="2024-12-01",
            category_path="Employment",
        )
        d = r.as_dict()
        assert d["series_id"] == "UNRATE"
        assert d["similarity_score"] == 0.85
        assert d["tags"] == ["labor", "unemployment"]
        assert d["category_path"] == "Employment"

    def test_as_dict_keys(self):
        r = FREDSearchResult(
            series_id="X", title="", notes="", frequency="",
            units="", seasonal_adjustment="", tags=[], popularity=0,
            similarity_score=0.0, source="", observation_end="",
        )
        expected_keys = {
            "series_id", "title", "notes", "frequency", "units",
            "seasonal_adjustment", "tags", "popularity",
            "similarity_score", "source", "observation_end", "category_path",
        }
        assert set(r.as_dict().keys()) == expected_keys

    def test_repr(self):
        r = FREDSearchResult(
            series_id="DGS10", title="Market Yield on Treasury", notes="",
            frequency="Daily", units="Percent", seasonal_adjustment="NSA",
            tags=[], popularity=95, similarity_score=0.9123,
            source="", observation_end="",
        )
        rep = repr(r)
        assert "DGS10" in rep
        assert "0.9123" in rep

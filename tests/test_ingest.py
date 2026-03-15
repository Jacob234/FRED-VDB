"""Tests for ingest pipeline helpers."""

import pytest

from fred_search.ingest import build_embedding_text
from fred_search.models import FREDSeriesMetadata


def _make_series(**overrides) -> FREDSeriesMetadata:
    defaults = {
        "series_id": "TEST",
        "title": "Test Series Title",
        "notes": "",
        "frequency": "Monthly",
        "units": "Percent",
        "seasonal_adjustment": "Seasonally Adjusted",
        "observation_start": "2000-01-01",
        "observation_end": "2024-01-01",
        "popularity": 50,
        "last_updated": "2024-01-01",
    }
    defaults.update(overrides)
    return FREDSeriesMetadata(**defaults)


class TestBuildEmbeddingText:
    def test_title_always_present(self):
        s = _make_series(title="Unemployment Rate")
        text = build_embedding_text(s)
        assert text.startswith("Unemployment Rate")

    def test_notes_included(self):
        s = _make_series(notes="Measures the percentage of unemployed persons.")
        text = build_embedding_text(s)
        assert "Measures the percentage" in text

    def test_notes_truncated_at_500(self):
        long_notes = "x" * 1000
        s = _make_series(notes=long_notes)
        text = build_embedding_text(s)
        # The notes portion should be at most 500 chars
        # Find it between the title and the next field
        assert "x" * 500 in text
        assert "x" * 501 not in text

    def test_tags_included(self):
        s = _make_series(tags=["labor", "unemployment", "bls"])
        text = build_embedding_text(s)
        assert "Tags: labor, unemployment, bls" in text

    def test_units_included(self):
        s = _make_series(units="Billions of Dollars")
        text = build_embedding_text(s)
        assert "Units: Billions of Dollars" in text

    def test_frequency_included(self):
        s = _make_series(frequency="Quarterly")
        text = build_embedding_text(s)
        assert "Frequency: Quarterly" in text

    def test_category_path_included(self):
        s = _make_series(category_path="Prices > Consumer Price Indexes")
        text = build_embedding_text(s)
        assert "Category: Prices > Consumer Price Indexes" in text

    def test_pipe_separated(self):
        s = _make_series(
            title="GDP",
            notes="Gross domestic product.",
            tags=["gdp"],
            units="Billions",
            frequency="Quarterly",
        )
        text = build_embedding_text(s)
        assert " | " in text
        parts = text.split(" | ")
        assert len(parts) >= 4  # title, notes, tags, units, frequency

    def test_empty_notes_omitted(self):
        s = _make_series(notes="")
        text = build_embedding_text(s)
        # Should not have an empty part between pipes
        assert "| |" not in text.replace(" ", "||")  # crude check
        parts = [p.strip() for p in text.split("|")]
        assert all(p for p in parts)  # no empty parts

    def test_empty_tags_omitted(self):
        s = _make_series(tags=[])
        text = build_embedding_text(s)
        assert "Tags:" not in text

    def test_minimal_series(self):
        s = _make_series(
            title="X",
            notes="",
            tags=[],
            units="",
            frequency="",
            category_path="",
        )
        text = build_embedding_text(s)
        assert text == "X"

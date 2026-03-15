"""
Data models for FRED series metadata and search results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class FREDSeriesMetadata:
    """Metadata for a single FRED economic data series."""

    series_id: str
    title: str
    notes: str
    frequency: str          # "Daily", "Weekly", "Monthly", "Quarterly", "Annual"
    units: str
    seasonal_adjustment: str  # "Seasonally Adjusted", "Not Seasonally Adjusted", etc.
    observation_start: str  # YYYY-MM-DD
    observation_end: str    # YYYY-MM-DD
    popularity: int
    last_updated: str       # ISO timestamp
    is_discontinued: bool = False
    tags: list[str] = field(default_factory=list)
    source: str = ""        # Originating release name or category path
    category_path: str = "" # e.g. "Prices > Consumer Price Indexes > Special Indexes"

    @classmethod
    def from_api_response(cls, raw: dict[str, Any], source: str = "") -> "FREDSeriesMetadata":
        """Parse a series dict from the FRED API JSON response.

        Handles the quirks of FRED's API field naming and optional fields.
        """
        # FRED uses "Not Seasonally Adjusted" abbreviation inconsistently;
        # normalise to the full string from the non-short field.
        sa = raw.get("seasonal_adjustment", "Not Seasonally Adjusted")

        # Discontinued series have observation_end far in the past or a
        # specific discontinuation marker; we derive the flag from the field.
        obs_end_str = raw.get("observation_end", "")

        # Popularity is occasionally absent for brand-new or very obscure series.
        popularity = raw.get("popularity")
        if popularity is None:
            popularity = 0
        else:
            popularity = int(popularity)

        return cls(
            series_id=raw["id"],
            title=raw.get("title", ""),
            notes=raw.get("notes", ""),
            frequency=raw.get("frequency", ""),
            units=raw.get("units", ""),
            seasonal_adjustment=sa,
            observation_start=raw.get("observation_start", ""),
            observation_end=obs_end_str,
            popularity=popularity,
            last_updated=raw.get("last_updated", ""),
            source=source,
        )

    def observation_end_date(self) -> date | None:
        """Parse observation_end as a date object, or None if unparseable."""
        try:
            return date.fromisoformat(self.observation_end)
        except (ValueError, TypeError):
            return None

    def __repr__(self) -> str:
        return (
            f"FREDSeriesMetadata({self.series_id!r}, title={self.title[:60]!r}, "
            f"freq={self.frequency!r}, pop={self.popularity})"
        )


@dataclass
class FREDSearchResult:
    """A single result returned by semantic search."""

    series_id: str
    title: str
    notes: str              # Truncated description (first 500 chars)
    frequency: str
    units: str
    seasonal_adjustment: str
    tags: list[str]
    popularity: int
    similarity_score: float  # Cosine distance from LanceDB (lower = more similar)
    source: str
    observation_end: str    # Most recent data point date
    category_path: str = "" # e.g. "Prices > Consumer Price Indexes > Special Indexes"

    def __repr__(self) -> str:
        return (
            f"FREDSearchResult({self.series_id!r}, score={self.similarity_score:.4f}, "
            f"title={self.title[:60]!r})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "title": self.title,
            "notes": self.notes,
            "frequency": self.frequency,
            "units": self.units,
            "seasonal_adjustment": self.seasonal_adjustment,
            "tags": self.tags,
            "popularity": self.popularity,
            "similarity_score": self.similarity_score,
            "source": self.source,
            "observation_end": self.observation_end,
            "category_path": self.category_path,
        }

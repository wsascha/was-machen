"""Behavioral unit tests for Pydantic event and database schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.schema import (
    AgeSuitability,
    Coordinates,
    CriteriaRating,
    Event,
    EventSourceRef,
    EventsDatabase,
    HomeBase,
    Metadata,
    ModularSourceEntry,
    SelectedEventRef,
    SourceCatalogEntry,
    SourceTypeMeta,
    SourcesDatabase,
)


class TestCoordinatesSchema:
    """Tests for Coordinates model validation."""

    def test_valid_coordinates(self) -> None:
        coords = Coordinates(lat=48.6953, lon=8.1350)
        assert coords.lat == 48.6953
        assert coords.lon == 8.1350

    def test_invalid_latitude_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            Coordinates(lat=91.0, lon=8.0)

        with pytest.raises(ValidationError):
            Coordinates(lat=-91.0, lon=8.0)

    def test_invalid_longitude_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            Coordinates(lat=48.0, lon=181.0)

        with pytest.raises(ValidationError):
            Coordinates(lat=48.0, lon=-181.0)


class TestCriteriaRatingSchema:
    """Tests for CriteriaRating score bounds and descriptions."""

    def test_valid_score(self) -> None:
        rating = CriteriaRating(score=9.5, reason="Excellent indoor facility")
        assert rating.score == 9.5
        assert rating.reason == "Excellent indoor facility"

    def test_score_out_of_bounds_raises_error(self) -> None:
        with pytest.raises(ValidationError):
            CriteriaRating(score=0.5, reason="Too low")

        with pytest.raises(ValidationError):
            CriteriaRating(score=10.5, reason="Too high")


class TestAgeSuitabilitySchema:
    """Tests for AgeSuitability model defaults and validation."""

    def test_defaults(self) -> None:
        age = AgeSuitability()
        assert age.min == 4
        assert age.max == 9
        assert age.ideal_for_4_5 is True
        assert age.ideal_for_6_9 is True

    def test_negative_age_raises_error(self) -> None:
        with pytest.raises(ValidationError):
            AgeSuitability(min=-1)


class TestEventSchema:
    """Tests for Event model validation and constraints."""

    def test_minimal_event_creation(self) -> None:
        event = Event(
            id="test-event",
            title="Test Workshop",
            category="museum",
            weather_type="indoor",
        )
        assert event.id == "test-event"
        assert event.title == "Test Workshop"
        assert event.country == "DE"
        assert event.family_score == 8.5
        assert event.coordinates.lat == 48.6953

    def test_invalid_category_raises_error(self) -> None:
        with pytest.raises(ValidationError):
            Event.model_validate(
                {
                    "id": "test-event",
                    "title": "Invalid Category",
                    "category": "nightlife",
                    "weather_type": "indoor",
                }
            )

    def test_invalid_weather_type_raises_error(self) -> None:
        with pytest.raises(ValidationError):
            Event.model_validate(
                {
                    "id": "test-event",
                    "title": "Invalid Weather",
                    "category": "action",
                    "weather_type": "underwater",
                }
            )

    def test_invalid_score_raises_error(self) -> None:
        with pytest.raises(ValidationError):
            Event.model_validate(
                {
                    "id": "test-event",
                    "title": "Invalid Score",
                    "category": "theater",
                    "weather_type": "indoor",
                    "family_score": 11.0,
                }
            )

    def test_drive_minutes_and_distance_compatibility_properties(self) -> None:
        event = Event(
            id="test-event",
            title="Test Workshop",
            drive_minutes_from_buehl=25,
            distance_km_from_buehl=30,
        )
        assert event.drive_minutes == 25
        assert event.distance_km == 30

        event.drive_minutes = 40
        event.distance_km = 45
        assert event.drive_minutes_from_buehl == 40
        assert event.distance_km_from_buehl == 45

    def test_drive_minutes_and_distance_validation_aliases(self) -> None:
        event = Event.model_validate(
            {
                "id": "test-event",
                "title": "Alias Test",
                "drive_minutes": 35,
                "distance_km": 42,
            }
        )
        assert event.drive_minutes_from_buehl == 35
        assert event.distance_km_from_buehl == 42


class TestSourceModels:
    """Tests for source references and catalog models."""

    def test_event_source_ref(self) -> None:
        ref = EventSourceRef(name="Portal", url="https://example.com")
        assert ref.name == "Portal"
        assert ref.url == "https://example.com"

    def test_selected_event_ref(self) -> None:
        sel = SelectedEventRef(id="ev-1", title="Title 1")
        assert sel.id == "ev-1"
        assert sel.title == "Title 1"

    def test_source_catalog_entry(self) -> None:
        entry = SourceCatalogEntry(
            id="src-1",
            name="Source 1",
            region="Baden",
            country="DE",
        )
        assert entry.id == "src-1"
        assert entry.events_count == 0
        assert entry.selected_events == []

    def test_modular_source_entry(self) -> None:
        entry = ModularSourceEntry(
            id="mod-1",
            name="Modular 1",
            region="Elsass",
            country="FR",
            url="https://alsace.fr",
            type="family_portal",
        )
        assert entry.id == "mod-1"
        assert entry.country == "FR"
        assert entry.enabled is True


class TestDatabaseSchema:
    """Tests for EventsDatabase and SourcesDatabase models against project data files."""

    def test_database_validation_against_real_dataset(self) -> None:
        data_dir = Path(__file__).resolve().parent.parent / "data"
        events_file = data_dir / "events.json"
        sources_file = data_dir / "sources.json"
        assert events_file.exists()
        assert sources_file.exists()

        raw_events = json.loads(events_file.read_text(encoding="utf-8"))
        events_db = EventsDatabase.model_validate(raw_events)
        assert len(events_db.events) > 0
        assert events_db.metadata.home_base.name == "77815 Bühl (Baden)"
        assert events_db.metadata.total_events == len(events_db.events)

        raw_sources = json.loads(sources_file.read_text(encoding="utf-8"))
        sources_db = SourcesDatabase.model_validate(raw_sources)
        assert len(sources_db.sources) > 0
        assert len(sources_db.source_types) > 0
        assert sources_db.metadata.sources_checked_count == len(sources_db.sources)

    def test_metadata_defaults(self) -> None:
        meta = Metadata()
        assert meta.home_base.lat == 48.6953
        assert meta.sources_checked_count == 0

    def test_source_type_meta(self) -> None:
        st = SourceTypeMeta(label="Museum", icon="🏛️")
        assert st.label == "Museum"
        assert st.icon == "🏛️"

    def test_home_base_bounds(self) -> None:
        with pytest.raises(ValidationError):
            HomeBase(max_drive_minutes=0)

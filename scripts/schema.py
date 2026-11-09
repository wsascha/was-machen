"""Pydantic data models and schemas for events, sources, and metadata."""

from __future__ import annotations

from typing import Literal
from pydantic import AliasChoices, BaseModel, Field

CountryCode = Literal["DE", "FR"]
EventCategory = Literal["action", "creative", "market", "museum", "nature", "theater"]
WeatherType = Literal["indoor", "mixed", "outdoor"]


class Coordinates(BaseModel):
    """Geographic coordinates (WGS 84)."""

    lat: float = Field(
        ..., ge=-90.0, le=90.0, description="Latitude in decimal degrees"
    )
    lon: float = Field(
        ..., ge=-180.0, le=180.0, description="Longitude in decimal degrees"
    )


class CriteriaRating(BaseModel):
    """Individual rating score and explanation for an evaluation criterion."""

    score: float = Field(
        ..., ge=1.0, le=10.0, description="Score on a 1.0 to 10.0 scale"
    )
    reason: str = Field(default="", description="Justification for the criterion score")


class AgeSuitability(BaseModel):
    """Suitability assessment tailored for children aged 4 to 9."""

    min: int = Field(default=4, ge=0, description="Minimum recommended age")
    max: int = Field(default=9, ge=0, description="Maximum recommended age")
    label: str = Field(
        default="4–9 Jahre", description="Human-readable age suitability summary"
    )
    ideal_for_4_5: bool = Field(
        default=True, description="Whether ideal for kindergarten age (4-5)"
    )
    ideal_for_6_9: bool = Field(
        default=True, description="Whether ideal for primary school age (6-9)"
    )
    notes_4_5: str | None = Field(
        default=None, description="Age-specific highlights for 4-5 years"
    )
    notes_6_9: str | None = Field(
        default=None, description="Age-specific highlights for 6-9 years"
    )


class EventSourceRef(BaseModel):
    """Reference to an origin source or booking website."""

    name: str = Field(..., description="Name of the source or provider")
    url: str = Field(..., description="Web link to the event or portal")


class SelectedEventRef(BaseModel):
    """Short summary reference of an event linked to a source in the catalog."""

    id: str = Field(..., description="Unique event identifier")
    title: str = Field(..., description="Event title")


class SourceConfigEntry(BaseModel):
    """Schema for individual source definitions in sources_config.json."""

    id: str = Field(..., description="Unique slug identifier of the source")
    name: str = Field(..., description="Human-readable title of the source")
    region: str = Field(..., description="Geographic region of coverage")
    country: CountryCode = Field(default="DE", description="Country code (DE or FR)")
    url: str = Field(..., description="Base portal or website URL")
    type: str = Field(default="municipal_calendar", description="Category identifier")
    description: str = Field(default="", description="Overview summary of the source")
    enabled: bool = Field(default=True, description="Whether the source is active")


ModularSourceEntry = SourceConfigEntry


class SourceCatalogEntry(BaseModel):
    """Enriched event source metadata in the public catalog."""

    id: str = Field(..., description="Unique slug identifier of the source")
    name: str = Field(..., description="Human-readable title of the source")
    region: str = Field(..., description="Geographic region of coverage")
    country: CountryCode = Field(default="DE", description="Country code (DE or FR)")
    url: str = Field(default="", description="Base portal or website URL")
    type: str = Field(default="municipal_calendar", description="Category identifier")
    type_label: str = Field(
        default="Regionale Quelle", description="Display label for the category"
    )
    type_icon: str = Field(default="📚", description="Emoji icon for the category")
    description: str = Field(default="", description="Overview summary of the source")
    events_count: int = Field(
        default=0, ge=0, description="Number of active events selected from this source"
    )
    selected_events: list[SelectedEventRef] = Field(
        default_factory=list,
        description="List of selected events from this source",
    )


class Event(BaseModel):
    """Core family weekend event schema."""

    id: str = Field(..., description="Unique slug identifier for the event")
    title: str = Field(..., description="Full event title")
    subtitle: str = Field(default="", description="Secondary descriptive subtitle")
    short_pin_label: str = Field(
        default="", description="Concise label for map pin markers"
    )
    category: EventCategory = Field(
        default="museum", description="Primary event category"
    )
    weather_type: WeatherType = Field(
        default="indoor", description="Indoor, mixed, or outdoor activity type"
    )
    country: CountryCode = Field(default="DE", description="Country code (DE or FR)")
    language_badge: str | None = Field(
        default=None, description="Language note for Alsace/cross-border events"
    )
    region: str = Field(
        default="Baden / Elsass",
        description="Regional designation (e.g. Baden-Baden, Elsass)",
    )
    city: str = Field(default="", description="City or municipality name")
    venue_name: str = Field(
        default="", description="Name of the venue, hall, or theater"
    )
    address: str = Field(default="", description="Full postal address")
    coordinates: Coordinates = Field(
        default_factory=lambda: Coordinates(lat=48.6953, lon=8.1350),
        description="Geographic coordinates for map display",
    )
    drive_minutes_from_buehl: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("drive_minutes_from_buehl", "drive_minutes"),
        description="Driving duration in minutes from 77815 Bühl",
    )
    distance_km_from_buehl: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("distance_km_from_buehl", "distance_km"),
        description="Driving distance in kilometers from 77815 Bühl",
    )
    days: list[str] = Field(
        default_factory=list, description="Target weekend dates (YYYY-MM-DD)"
    )
    date_display: str = Field(
        default="", description="Formatted date and opening hours string"
    )
    duration_display: str = Field(
        default="", description="Estimated visit duration recommendation"
    )
    family_score: float = Field(
        default=8.5,
        ge=1.0,
        le=10.0,
        description="Overall weighted family score (1.0 to 10.0)",
    )
    summary: str = Field(default="", description="Brief promotional summary")
    detailed_description: str = Field(
        default="", description="Detailed event description"
    )
    age_suitability: AgeSuitability = Field(
        default_factory=AgeSuitability, description="Evaluation of fit for ages 4-9"
    )
    parking_info: str = Field(
        default="", description="Parking recommendations and accessibility"
    )
    booking_info: str = Field(
        default="", description="Ticketing and reservation guidance"
    )
    criteria_ratings: dict[str, CriteriaRating] = Field(
        default_factory=dict,
        description="Ratings across the 7 family evaluation criteria",
    )
    pros: list[str] = Field(
        default_factory=list, description="Top advantages for families"
    )
    tips_and_watchouts: list[str] = Field(
        default_factory=list, description="Helpful tips and things to watch out for"
    )
    tags: list[str] = Field(default_factory=list, description="Searchable keyword tags")
    sources: list[EventSourceRef] = Field(
        default_factory=list, description="Origin and booking links"
    )
    price_info: str = Field(
        default="", description="Pricing and family ticket information"
    )

    @property
    def drive_minutes(self) -> int:
        """Compatibility property for drive_minutes_from_buehl."""
        return self.drive_minutes_from_buehl

    @drive_minutes.setter
    def drive_minutes(self, value: int) -> None:
        self.drive_minutes_from_buehl = value

    @property
    def distance_km(self) -> int:
        """Compatibility property for distance_km_from_buehl."""
        return self.distance_km_from_buehl

    @distance_km.setter
    def distance_km(self, value: int) -> None:
        self.distance_km_from_buehl = value


class HomeBase(BaseModel):
    """Home base origin configuration."""

    name: str = Field(default="77815 Bühl (Baden)", description="Home base label")
    lat: float = Field(default=48.6953, description="Origin latitude")
    lon: float = Field(default=8.1350, description="Origin longitude")
    max_drive_minutes: int = Field(
        default=60, ge=1, description="Maximum driving radius threshold in minutes"
    )


class Metadata(BaseModel):
    """Top-level database metadata."""

    title: str = Field(
        default="Was machen wir am Wochenende? (Rund um 77815 Bühl)",
        description="App title",
    )
    home_base: HomeBase = Field(
        default_factory=HomeBase, description="Origin location details"
    )
    target_age_group: str = Field(
        default="4–9 Jahre (Kita & Grundschule)", description="Target age description"
    )
    weekend_start: str = Field(
        default="", description="Friday date of target weekend (YYYY-MM-DD)"
    )
    weekend_end: str = Field(
        default="", description="Sunday date of target weekend (YYYY-MM-DD)"
    )
    weekend_label: str = Field(default="", description="Formatted weekend date label")
    last_updated: str = Field(default="", description="ISO timestamp of last update")
    last_updated_display: str = Field(
        default="", description="Human-readable last update label"
    )
    sources_checked_count: int = Field(
        default=0, ge=0, description="Total number of sources pinged"
    )
    total_events: int = Field(
        default=0, ge=0, description="Total number of curated events"
    )
    sources_with_events_count: int = Field(
        default=0, ge=0, description="Number of sources with active events"
    )


class SourceTypeMeta(BaseModel):
    """Metadata describing a source type category."""

    label: str = Field(..., description="Category label")
    icon: str = Field(..., description="Emoji category icon")


class EventsDatabase(BaseModel):
    """Events database structure stored in data/events.json."""

    metadata: Metadata = Field(
        default_factory=Metadata, description="Database metadata"
    )
    events: list[Event] = Field(
        default_factory=list, description="List of validated family events"
    )
    evaluated_sources_catalog: list[SourceCatalogEntry] = Field(
        default_factory=list, description="Catalog of evaluated sources"
    )


class SourcesDatabase(BaseModel):
    """Sources directory database structure stored in data/sources.json."""

    metadata: Metadata = Field(
        default_factory=Metadata, description="Database metadata"
    )
    source_types: dict[str, SourceTypeMeta] = Field(
        default_factory=dict, description="Configured source types"
    )
    sources: list[SourceCatalogEntry] = Field(
        default_factory=list,
        validation_alias=AliasChoices("sources", "evaluated_sources_catalog"),
        description="Public sources directory catalog",
    )

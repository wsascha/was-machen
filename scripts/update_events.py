#!/usr/bin/env python3
"""
Automated multi-source event aggregator and family activity evaluator
for the region around 77815 Bühl, Germany (max 60-minute driving radius:
Karlsruhe, Northern Black Forest, Baden-Baden, Ortenau, and Alsace/France).

Modular source architecture:
- Primary catalog: scripts/sources_config.json
- Drop-in extensions: scripts/sources.d/*.json (single object or list of sources)
- CLI management: uv run python scripts/update_events.py --add-source ...

Executed periodically via GitHub Actions (.github/workflows/update-events.yml)
to update data/events.json for the static web app.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, CliApp, CliImplicitFlag, SettingsConfigDict

from scripts.schema import (
    Event,
    EventsDatabase,
    PastEventsDatabase,
    SelectedEventRef,
    SourceCatalogEntry,
    SourcesDatabase,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "scripts" / "sources_config.json"
EVENTS_JSON_PATH = ROOT_DIR / "data" / "events.json"
PAST_EVENTS_JSON_PATH = ROOT_DIR / "data" / "past_events.json"
SOURCES_JSON_PATH = ROOT_DIR / "data" / "sources.json"

# Default origin coordinates: 77815 Bühl, Germany (Market square / city center)
BUEHL_LAT = 48.6953
BUEHL_LON = 8.1350

USER_AGENT = (
    "Mozilla/5.0 (compatible; FamilyWeekendCompassBot/1.0; "
    "+https://github.com/wsascha/was-machen)"
)

SourceType = Literal[
    "family_portal",
    "municipal_calendar",
    "museum",
    "nature_center",
    "science_center",
    "theater",
]


class Settings(BaseSettings):
    """CLI and environment settings for the event aggregator."""

    model_config = SettingsConfigDict(
        cli_kebab_case=True,
        env_file=".env",
        extra="ignore",
    )

    add_source: str | None = Field(
        default=None,
        description="Name of a new event source to register modularly",
    )
    url: str | None = Field(
        default=None,
        description="URL of the new event source",
    )
    region: str = Field(
        default="Baden / Elsass",
        description="Geographic region of the event source",
    )
    country: str = Field(
        default="DE",
        description="Two-letter country code (DE or FR)",
    )
    source_type: SourceType = Field(
        default="family_portal",
        validation_alias=AliasChoices("type", "source_type"),
        description="Category type of the source",
    )
    description: str = Field(
        default="",
        validation_alias=AliasChoices("desc", "description"),
        description="Short summary of the event source",
    )
    skip_network_check: CliImplicitFlag[bool] = Field(
        default=False,
        description="Synchronize configuration without performing live HTTP checks against all portals",
    )
    target_weekend: str | None = Field(
        default=None,
        description="Target weekend Saturday date in YYYY-MM-DD format (defaults to next Saturday)",
    )
    max_drive_minutes: int = Field(
        default=60,
        description="Maximum drive duration from Bühl in minutes",
    )
    gemini_api_key: str | None = Field(
        default=None,
        description="Gemini API key for AI-based event evaluation",
    )

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in ("DE", "FR"):
            raise ValueError(f"Country must be DE or FR, got: {value}")
        return code

    def cli_cmd(self) -> None:
        """Entry point executed by CliApp."""
        run_aggregator(self)


def slugify(text: str) -> str:
    """Generate a clean URL/file slug from a source name."""
    s = text.lower()
    for char, replacement in {
        "à": "a",
        "â": "a",
        "ä": "ae",
        "ç": "c",
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ö": "oe",
        "ß": "ss",
        "ù": "u",
        "û": "u",
        "ü": "ue",
    }.items():
        s = s.replace(char, replacement)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48]


def load_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Load and enrich source entries configured in scripts/sources_config.json."""
    base_sources: list[dict[str, Any]] = list(config.get("sources", []))
    source_types = config.get("source_types", {})
    enriched: list[dict[str, Any]] = []
    for src in base_sources:
        if src.get("enabled", True) is False:
            continue
        stype = src.get("type", "municipal_calendar")
        tmeta = source_types.get(stype, {"label": "Regionale Quelle", "icon": "📚"})
        enriched.append(
            {
                "id": src.get("id") or slugify(src.get("name", "source")),
                "name": src.get("name", "Unbenannte Quelle"),
                "region": src.get("region", "Region Bühl / Oberrhein"),
                "country": src.get("country", "DE"),
                "url": src.get("url", ""),
                "type": stype,
                "type_label": tmeta.get("label", "Regionale Quelle"),
                "type_icon": tmeta.get("icon", "📚"),
                "description": src.get("description", ""),
            }
        )
    return enriched


load_modular_sources = load_sources


def add_source_via_cli(settings: Settings, config_path: Path = CONFIG_PATH) -> None:
    """Persist a new source directly into scripts/sources_config.json."""
    if not settings.add_source:
        return
    if not settings.url:
        print(
            "[ERROR] When adding a source with --add-source, --url must be provided.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    source_id = slugify(settings.add_source)
    existing_ids = {s.get("id") for s in config.get("sources", [])}
    if source_id in existing_ids:
        print(
            f"[WARN] Source with ID '{source_id}' already exists in {config_path.name}."
        )
        return

    new_entry = {
        "id": source_id,
        "name": settings.add_source,
        "region": settings.region,
        "country": settings.country,
        "url": settings.url,
        "type": settings.source_type,
        "description": settings.description,
        "enabled": True,
    }
    config.setdefault("sources", []).append(new_entry)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[SUCCESS] Source '{new_entry['name']}' saved to: {config_path}")


def get_next_weekend(
    target_date_str: str | None = None,
) -> tuple[dt.date, dt.date, dt.date]:
    """Determine Friday, Saturday, and Sunday dates of the target weekend."""
    if target_date_str and target_date_str.strip():
        try:
            sat = dt.date.fromisoformat(target_date_str.strip())
            return sat - dt.timedelta(days=1), sat, sat + dt.timedelta(days=1)
        except ValueError:
            pass

    today = dt.date.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0 and today.weekday() == 5:
        saturday = today
    elif today.weekday() == 6:
        saturday = today + dt.timedelta(days=6)
    else:
        saturday = today + dt.timedelta(days=days_until_saturday)

    friday = saturday - dt.timedelta(days=1)
    sunday = saturday + dt.timedelta(days=1)
    return friday, saturday, sunday


GERMAN_MONTHS = [
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def format_weekend_label(friday: dt.date, sunday: dt.date) -> str:
    """Format human-readable weekend label, handling month and year transitions."""
    if friday.year == sunday.year:
        if friday.month == sunday.month:
            return f"{friday.day}.–{sunday.day}. {GERMAN_MONTHS[sunday.month]} {sunday.year}"
        return (
            f"{friday.day}. {GERMAN_MONTHS[friday.month]} – "
            f"{sunday.day}. {GERMAN_MONTHS[sunday.month]} {sunday.year}"
        )
    return (
        f"{friday.day}. {GERMAN_MONTHS[friday.month]} {friday.year} – "
        f"{sunday.day}. {GERMAN_MONTHS[sunday.month]} {sunday.year}"
    )


def archive_past_events(
    database: EventsDatabase,
    target_friday: dt.date,
    past_events_path: Path | None = None,
) -> PastEventsDatabase:
    """Archive events occurring before the target weekend into data/past_events.json."""
    archive_path = (
        past_events_path if past_events_path is not None else PAST_EVENTS_JSON_PATH
    )
    if archive_path.exists():
        try:
            raw_past = json.loads(archive_path.read_text(encoding="utf-8"))
            past_db = PastEventsDatabase.model_validate(raw_past)
        except Exception as exc:
            print(
                f"[WARN] Failed to load existing past events ({exc}), creating fresh archive."
            )
            past_db = PastEventsDatabase()
    else:
        past_db = PastEventsDatabase()

    existing_keys = {(ev.id, tuple(sorted(ev.days))) for ev in past_db.events}

    fri_iso = target_friday.isoformat()
    newly_archived = 0

    for ev in database.events:
        if not ev.days or max(ev.days) < fri_iso:
            key = (ev.id, tuple(sorted(ev.days)))
            if key not in existing_keys:
                past_db.events.append(ev.model_copy(deep=True))
                existing_keys.add(key)
                newly_archived += 1

    past_db.events.sort(key=lambda x: max(x.days) if x.days else "", reverse=True)
    past_db.metadata.total_events = len(past_db.events)
    past_db.metadata.last_updated = dt.datetime.now(dt.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    archive_path.write_text(
        json.dumps(past_db.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if newly_archived > 0:
        print(f"[INFO] Archived {newly_archived} past events to {archive_path}.")

    return past_db


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two coordinates in kilometers."""
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_driving_route(lat: float, lon: float) -> tuple[int, int]:
    """
    Calculate real car driving duration (minutes) and distance (km) from origin coordinates
    via the public OSRM routing API, falling back to road-factor estimate.
    """
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{BUEHL_LON},{BUEHL_LAT};{lon},{lat}?overview=false"
    )
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            routes = data.get("routes", [])
            if routes:
                duration_min = round(routes[0]["duration"] / 60.0)
                distance_km = round(routes[0]["distance"] / 1000.0)
                return max(5, duration_min), max(2, distance_km)
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"[DEBUG] Using OSRM fallback estimation ({exc})")

    air_km = haversine_km(BUEHL_LAT, BUEHL_LON, lat, lon)
    road_km = max(2, round(air_km * 1.32))
    drive_min = max(5, round((road_km / 62.0) * 60))
    return drive_min, road_km


compute_driving_route_from_buehl = compute_driving_route


def extract_jsonld_events(
    html: str, source_meta: dict[str, Any]
) -> list[dict[str, Any]]:
    """Extract schema.org/Event items from JSON-LD script blocks of a source page."""
    soup = BeautifulSoup(html, "lxml")
    extracted: list[dict[str, Any]] = []

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph", [item])
            for node in graph if isinstance(graph, list) else [graph]:
                if not isinstance(node, dict):
                    continue
                ev_type = str(node.get("@type", ""))
                if "Event" not in ev_type:
                    continue
                name = str(node.get("name", "")).strip()
                if not name:
                    continue
                desc = str(node.get("description", "")).strip()
                url = str(node.get("url", source_meta["url"])).strip()
                start_date = str(node.get("startDate", "")).strip()
                extracted.append(
                    {
                        "title": name,
                        "description": desc,
                        "start_date": start_date,
                        "source_name": source_meta["name"],
                        "source_url": urljoin(source_meta["url"], url),
                        "region": source_meta["region"],
                        "country": source_meta["country"],
                    }
                )
    return extracted


def enrich_with_gemini_if_available(
    raw_candidates: list[dict[str, Any]],
    weekend_dates: tuple[dt.date, dt.date, dt.date],
    api_key: str | None = None,
    sources_catalog: list[dict[str, Any]] | None = None,
) -> list[Event]:
    """
    Optional AI evaluation step using Google Gemini API to rate newly
    crawled raw events or discover fresh weekend activities for children (4-9 years).
    """
    key = (api_key or "").strip()
    if not key or (not raw_candidates and not sources_catalog):
        return []

    new_events: list[Event] = []
    try:
        from google import genai

        client = genai.Client(api_key=key)
        fri, sat, sun = weekend_dates
        schema_hint = (
            "Jedes Event-Objekt muss dem Schema entsprechen:\n"
            "- id: eindeutiger Slug (z.B. 'unimog-museum-gaggenau-2026-11-21')\n"
            "- title: deutscher Titel\n"
            "- subtitle: kurzer Untertitel\n"
            "- short_pin_label: kurzes Label für die Karte\n"
            "- category: exakt einer aus ['action', 'creative', 'market', 'museum', 'nature', 'theater']\n"
            "- weather_type: exakt einer aus ['indoor', 'mixed', 'outdoor']\n"
            "- country: 'DE' oder 'FR'\n"
            "- region, city, venue_name, address\n"
            "- coordinates: {'lat': float, 'lon': float}\n"
            f"- days: Liste aus passenden ISO-Daten dieses Wochenendes, z.B. ['{sat.isoformat()}', '{sun.isoformat()}']\n"
            "- date_display: formatiertes Datum + Uhrzeiten (z.B. 'Sa, 21.11. & So, 22.11.2026 · 10:00–17:00 Uhr')\n"
            "- duration_display: z.B. '2–3 Stunden'\n"
            "- summary, detailed_description, parking_info, booking_info, price_info\n"
            "- age_suitability: {'min': 4, 'max': 9, 'label': '4–9 Jahre', 'ideal_for_4_5': true, 'ideal_for_6_9': true}\n"
            "- criteria_ratings: Bewertungen (1.0–10.0) für 'age_fit', 'experience_value', 'weather_suitability', 'relaxation_parents', 'travel_parking', 'infrastructure_food', 'language_accessibility'\n"
            "- pros, tips_and_watchouts, tags: Listen von Strings\n"
            "- sources: Liste von {'name': '...', 'url': 'https://...'}\n"
        )
        if raw_candidates:
            prompt = (
                f"Du bist ein Familien-Freizeit-Experte für die Region Bühl (77815), "
                f"Baden, Schwarzwald und Elsass. Bewerte die folgenden Roh-Veranstaltungen "
                f"für das Wochenende {fri.isoformat()} bis {sun.isoformat()} speziell für "
                f"Familien mit Kindern von 4 bis 9 Jahren.\n\n{schema_hint}"
            )
            contents = f"{prompt}\n\nRohdaten:\n{json.dumps(raw_candidates[:15], ensure_ascii=False)}"
        else:
            sources_summary = [
                {
                    "name": s.get("name"),
                    "region": s.get("region"),
                    "url": s.get("url"),
                    "type": s.get("type"),
                }
                for s in (sources_catalog or [])[:30]
            ]
            prompt = (
                f"Du bist ein Familien-Freizeit-Experte für die Region 77815 Bühl, "
                f"Baden, Nordschwarzwald und Elsass (max. 60 Min. Fahrzeit). "
                f"Wähle 8 bis 12 konkrete, herausragende Wochenend-Aktivitäten und Veranstaltungen "
                f"für das Wochenende Freitag {fri.isoformat()} bis Sonntag {sun.isoformat()} aus, "
                f"speziell für Familien mit Kindern von 4 bis 9 Jahren, basierend auf den folgenden regionalen Quellen.\n\n{schema_hint}"
            )
            contents = f"{prompt}\n\nRegionale Quellen:\n{json.dumps(sources_summary, ensure_ascii=False)}"

        gen_config: Any = {
            "response_mime_type": "application/json",
            "response_schema": list[Event],
        }
        response_stream = client.models.generate_content_stream(
            model="gemini-3.8-flash",
            contents=contents,
            config=gen_config,
        )
        print("[AI STREAM: Event Enrichment] Querying Gemini...", flush=True)
        chunks: list[str] = []
        try:
            for chunk in response_stream:
                chunk_text = getattr(chunk, "text", "") or ""
                if chunk_text:
                    print(chunk_text, end="", flush=True)
                    chunks.append(chunk_text)
            raw_text = "".join(chunks).strip()
        except TypeError:
            raw_text = (getattr(response_stream, "text", "") or "").strip()
        print("\n[AI STREAM: Event Enrichment] Stream complete.\n", flush=True)
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        payload = json.loads(raw_text)
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    if not item.get("id") and item.get("title"):
                        item["id"] = slugify(str(item["title"]))
                    try:
                        new_events.append(Event.model_validate(item))
                    except Exception as val_exc:
                        print(f"[WARN] Skipped invalid Gemini event: {val_exc}")
                        continue
    except Exception as exc:
        print(f"[INFO] Gemini enrichment skipped ({exc}). Using curated database.")
    return new_events


def check_sources_health(
    sources: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    """Verify accessibility of configured event sources and extract JSON-LD event items."""
    reachable = 0
    discovered_raw: list[dict[str, Any]] = []

    for src in sources:
        url = src.get("url", "")
        if not url:
            continue
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=6)
            if resp.status_code < 400:
                reachable += 1
                discovered_raw.extend(extract_jsonld_events(resp.text, src))
        except requests.RequestException:
            continue
        time.sleep(0.1)

    return reachable, discovered_raw


def calculate_weighted_score(
    scores: dict[str, float], criteria_cfg: list[dict[str, Any]]
) -> float:
    """Calculate weighted overall family score (scale 1.0 - 10.0)."""
    total_weight = 0.0
    weighted_sum = 0.0
    for crit in criteria_cfg:
        cid = crit["id"]
        weight = float(crit.get("weight", 0.1))
        val = float(scores.get(cid, 8.0))
        weighted_sum += val * weight
        total_weight += weight
    if total_weight <= 0:
        return 8.5
    return round(weighted_sum / total_weight, 1)


def run_aggregator(settings: Settings) -> None:
    """Execute the core event aggregation and scoring pipeline."""
    if settings.add_source:
        add_source_via_cli(settings)

    print("=== Starting Family Weekend Compass update (Home base: 77815 Bühl) ===")
    if not CONFIG_PATH.exists():
        print(f"[ERROR] Configuration not found: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    friday, saturday, sunday = get_next_weekend(settings.target_weekend)
    print(
        f"[INFO] Target weekend: Fri {friday.isoformat()} to Sun {sunday.isoformat()}"
    )

    if not EVENTS_JSON_PATH.exists():
        print(
            f"[ERROR] Events file does not exist: {EVENTS_JSON_PATH}", file=sys.stderr
        )
        sys.exit(1)

    current_data = json.loads(EVENTS_JSON_PATH.read_text(encoding="utf-8"))
    database = EventsDatabase.model_validate(current_data)
    sources_cfg = load_modular_sources(config)
    criteria_cfg = config.get("evaluation_criteria", [])
    old_weekend_start = database.metadata.weekend_start or None
    target_weekend_start = friday.isoformat()

    # For each new weekend, events are reset with no carry-over
    if old_weekend_start != target_weekend_start:
        archive_past_events(database, friday, past_events_path=PAST_EVENTS_JSON_PATH)
        database.events = []
        print(
            f"[INFO] New target weekend detected ({target_weekend_start} to {sunday.isoformat()}). "
            f"Reset active events (no carry-over)."
        )
    else:
        archive_past_events(database, friday, past_events_path=PAST_EVENTS_JSON_PATH)

    if not settings.skip_network_check:
        print(
            f"[INFO] Checking {len(sources_cfg)} modular sources in Baden, "
            f"Black Forest, South Palatinate, and Alsace..."
        )
        reachable_count, raw_candidates = check_sources_health(sources_cfg)
        print(
            f"[INFO] {reachable_count}/{len(sources_cfg)} sources directly reachable, "
            f"{len(raw_candidates)} structured JSON-LD events found."
        )
        new_events = enrich_with_gemini_if_available(
            raw_candidates,
            (friday, saturday, sunday),
            api_key=settings.gemini_api_key,
            sources_catalog=sources_cfg,
        )
        if new_events:
            print(
                f"[INFO] Integrated {len(new_events)} new events from sources via Gemini."
            )
            existing_ids = {e.id for e in database.events}
            for ne in new_events:
                if ne.id not in existing_ids:
                    database.events.append(ne)
                    existing_ids.add(ne.id)
    else:
        print(
            f"[INFO] Synchronizing {len(sources_cfg)} modular sources "
            f"(network check skipped)."
        )

    # Ensure no past-dated events linger in database.events
    fri_iso = friday.isoformat()
    database.events = [
        ev for ev in database.events if not ev.days or max(ev.days) >= fri_iso
    ]

    valid_events: list[Event] = []
    for ev in database.events:
        lat = ev.coordinates.lat
        lon = ev.coordinates.lon

        if not ev.drive_minutes_from_buehl or not ev.distance_km_from_buehl:
            drive_min, dist_km = compute_driving_route(lat, lon)
            ev.drive_minutes_from_buehl = drive_min
            ev.distance_km_from_buehl = dist_km

        if ev.drive_minutes_from_buehl > settings.max_drive_minutes:
            print(
                f"[FILTER] Skipping '{ev.title}' "
                f"({ev.drive_minutes_from_buehl} min > {settings.max_drive_minutes} min)"
            )
            continue

        crit_scores = ev.criteria_ratings.scores()
        if crit_scores:
            ev.family_score = calculate_weighted_score(crit_scores, criteria_cfg)

        valid_events.append(ev)

    valid_events.sort(
        key=lambda x: (
            -float(x.family_score),
            int(x.drive_minutes_from_buehl),
        )
    )

    # Calculate source coverage statistics
    def _clean_domain(url: str) -> str:
        return urlparse(url).netloc.lower().replace("www.", "").strip()

    active_sources_count = 0
    for src in sources_cfg:
        src_domain = _clean_domain(src.get("url", ""))
        src_name = src.get("name", "").lower()
        matched: list[SelectedEventRef] = []

        for ev in valid_events:
            is_matched = False
            for ref in ev.sources:
                ref_url = ref.url
                ref_domain = _clean_domain(ref_url)
                ref_name = ref.name.lower()

                if src_domain and (
                    src_domain in ref_domain or ref_domain in src_domain
                ):
                    is_matched = True
                    break
                if src_name and (src_name in ref_name or ref_name in src_name):
                    is_matched = True
                    break

            if is_matched:
                matched.append(SelectedEventRef(id=ev.id, title=ev.title))

        src["events_count"] = len(matched)
        src["selected_events"] = [m.model_dump() for m in matched]
        if matched:
            active_sources_count += 1

    database.metadata.weekend_start = friday.isoformat()
    database.metadata.weekend_end = sunday.isoformat()
    database.metadata.weekend_label = format_weekend_label(friday, sunday)

    now_utc = dt.datetime.now(dt.UTC)
    database.metadata.last_updated = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        from zoneinfo import ZoneInfo

        now_local = now_utc.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        now_local = now_utc.astimezone(dt.timezone(dt.timedelta(hours=1)))

    database.metadata.last_updated_display = (
        f"{now_local.day}. {GERMAN_MONTHS[now_local.month]} {now_local.year}, "
        f"{now_local.strftime('%H:%M')} Uhr"
    )
    database.metadata.home_base.max_drive_minutes = settings.max_drive_minutes
    database.metadata.sources_checked_count = len(sources_cfg)
    database.metadata.sources_with_events_count = active_sources_count
    database.metadata.total_events = len(valid_events)
    database.events = valid_events

    sources_catalog = [SourceCatalogEntry.model_validate(s) for s in sources_cfg]
    sources_database = SourcesDatabase(
        metadata=database.metadata,
        source_types=config.get("source_types", {}),
        sources=sources_catalog,
    )

    EVENTS_JSON_PATH.write_text(
        json.dumps(database.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    SOURCES_JSON_PATH.write_text(
        json.dumps(sources_database.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[SUCCESS] Saved {len(valid_events)} family events to {EVENTS_JSON_PATH}, "
        f"{len(sources_cfg)} data sources to {SOURCES_JSON_PATH}, "
        f"and updated past events archive at {PAST_EVENTS_JSON_PATH}."
    )


def main() -> None:
    """CLI entrypoint."""
    CliApp.run(Settings)


if __name__ == "__main__":
    main()

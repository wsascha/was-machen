"""Autonomous discovery pipeline for regional event sources.

Finds and verifies new family event calendars, portals, theaters, and museums
within ~60 minutes driving distance from 77815 Bühl (Baden, Black Forest, Alsace)
for children aged 4 to 9. Discovered sources are saved directly to scripts/sources_config.json
and compiled into data/sources.json.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import (
    BaseSettings,
    CliApp,
    CliImplicitFlag,
    SettingsConfigDict,
)
import requests

from scripts.schema import (
    Metadata,
    SourceCatalogEntry,
    SourceConfigEntry,
    SourcesDatabase,
)
from scripts.update_events import load_sources, slugify

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "scripts" / "sources_config.json"
SOURCES_JSON_PATH = PROJECT_ROOT / "data" / "sources.json"
USER_AGENT = (
    "Mozilla/5.0 (compatible; FamilyWeekendCompassSourceFinder/1.0; "
    "+https://github.com/sascha/was-tun-am-wochenende)"
)

SUPPORTED_SOURCE_TYPES = {
    "family_portal",
    "municipal_calendar",
    "museum",
    "nature_center",
    "science_center",
    "theater",
}


class DiscoverySettings(BaseSettings):
    """CLI and environment settings for regional source discovery."""

    model_config = SettingsConfigDict(
        cli_kebab_case=True,
        env_file=".env",
        extra="ignore",
    )

    gemini_api_key: str | None = Field(
        default=None,
        description="Google Gemini API key for AI-assisted source discovery",
    )
    max_sources: int = Field(
        default=3,
        ge=1,
        le=20,
        validation_alias=AliasChoices("max_sources", "MAX_SOURCES"),
        description="Maximum number of new sources to discover and save",
    )
    dry_run: CliImplicitFlag[bool] = Field(
        default=False,
        description="Simulate discovery without writing files",
    )
    skip_network_check: CliImplicitFlag[bool] = Field(
        default=False,
        description="Skip live HTTP accessibility check of candidate URLs",
    )

    def cli_cmd(self) -> None:
        """Entry point executed by CliApp."""
        discover_and_save_sources(self)


def clean_domain(url: str) -> str:
    """Extract a cleaned domain name for duplicate detection."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().strip()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def load_known_identifiers(
    config_path: Path = CONFIG_PATH,
) -> tuple[set[str], set[str]]:
    """Collect all known source IDs and domain names from configuration to prevent duplicates."""
    known_ids: set[str] = set()
    known_domains: set[str] = set()

    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            for src in cfg.get("sources", []):
                sid = src.get("id") or slugify(src.get("name", ""))
                if sid:
                    known_ids.add(sid)
                url = src.get("url", "")
                if url:
                    domain = clean_domain(url)
                    if domain:
                        known_domains.add(domain)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[WARN] Failed to read {config_path.name}: {exc}", file=sys.stderr)

    return known_ids, known_domains


def get_seed_candidates() -> list[SourceConfigEntry]:
    """Curated seed pool of high-value regional event sources around Bühl."""
    raw_seeds: list[dict[str, Any]] = [
        {
            "id": "das-sandkorn-theater-ka",
            "name": "Das Sandkorn Theater Karlsruhe – Kinder- & Jugendprogramm",
            "region": "Karlsruhe",
            "country": "DE",
            "url": "https://www.das-sandkorn.de/programm/kinder.html",
            "type": "theater",
            "description": "Kindertheaterstücke ab 4 Jahren und Mitmach-Aufführungen im Theaterhaus Karlsruhe.",
            "enabled": True,
        },
        {
            "id": "naturzentrum-rheinauen-rust",
            "name": "Naturzentrum Rheinauen Rust – Familien- & Naturerlebnis",
            "region": "Ortenau / Rust",
            "country": "DE",
            "url": "https://www.naturzentrum-rheinauen.de/",
            "type": "nature_center",
            "description": "Naturlehrpfad, Ranger-Führungen und Mitmach-Ausstellung über die Rheinauen für Kita- & Grundschulkinder.",
            "enabled": True,
        },
        {
            "id": "schloss-favorite-rastatt",
            "name": "Schloss Favorite Rastatt – Familienführungen & Schlosspark",
            "region": "Rastatt",
            "country": "DE",
            "url": "https://www.schloss-favorite-rastatt.de/",
            "type": "museum",
            "description": "Ältestes deutsches Porzellanschloss mit weitläufigem Park, Entdecker-Rallyes und Kinderführungen.",
            "enabled": True,
        },
        {
            "id": "ecomusee-d-alsace",
            "name": "Écomusée d'Alsace – Freilichtmuseum für Familien",
            "region": "Elsass",
            "country": "FR",
            "url": "https://www.ecomusee.alsace/",
            "type": "museum",
            "description": "Größtes lebendiges Freilichtmuseum Frankreichs mit Handwerksvorführungen, Bauernhoftieren und Mitmach-Ateliers.",
            "enabled": True,
        },
        {
            "id": "theater-pforzheim-junges-theater",
            "name": "Theater Pforzheim – Junges Theater für Kinder",
            "region": "Nordschwarzwald / Pforzheim",
            "country": "DE",
            "url": "https://www.theater-pforzheim.de/",
            "type": "theater",
            "description": "Märcheninszenierungen, Kinderopern und Figurentheater für Kinder ab 4 Jahren.",
            "enabled": True,
        },
        {
            "id": "badisches-landesmuseum-karlsruhe",
            "name": "Badisches Landesmuseum Karlsruhe – Familien- & Kinderausstellungen",
            "region": "Karlsruhe",
            "country": "DE",
            "url": "https://www.landesmuseum.de/",
            "type": "museum",
            "description": "Schloss Karlsruhe mit archäologischen Mitmach-Stationen, Familien-Werkstätten und Schlossturm.",
            "enabled": True,
        },
        {
            "id": "wildpark-pforzheim",
            "name": "Wildpark Pforzheim – Natur- & Tiererlebnis im Nordschwarzwald",
            "region": "Nordschwarzwald / Pforzheim",
            "country": "DE",
            "url": "https://www.pforzheim.de/freizeit/wildpark.html",
            "type": "nature_center",
            "description": "Wald-Erlebnispfade, Schaufütterungen, Streichelzoo und riesige Abenteuerspielplätze.",
            "enabled": True,
        },
        {
            "id": "baal-novo-theater-baden-alsace",
            "name": "BAAL novo Theater Eurodistrict Baden-Alsace – Grenzüberschreitendes Theater",
            "region": "Ortenau / Elsass",
            "country": "DE",
            "url": "https://www.baalnovo.com/",
            "type": "theater",
            "description": "Zweisprachiges deutsch-französisches Theaterangebot speziell für junge Zuschauer und Familien am Oberrhein.",
            "enabled": True,
        },
        {
            "id": "murgtal-tourismus-familien",
            "name": "Murgtal Tourismus – Familien- & Freizeiterlebnisse",
            "region": "Murgtal / Forbach",
            "country": "DE",
            "url": "https://www.murgtal.org/",
            "type": "municipal_calendar",
            "description": "Erlebniswege, Kletter- & Naturerlebnisse für Familien im wildromantischen Murgtal.",
            "enabled": True,
        },
    ]

    valid_seeds: list[SourceConfigEntry] = []
    for raw in raw_seeds:
        try:
            valid_seeds.append(SourceConfigEntry.model_validate(raw))
        except Exception:
            continue
    return valid_seeds


def fetch_candidates_from_gemini(
    api_key: str, existing_names: list[str]
) -> list[SourceConfigEntry]:
    """Query Google Gemini for newly proposed regional event sources."""
    clean_key = api_key.strip()
    if not clean_key:
        return []

    try:
        from google import genai

        client = genai.Client(api_key=clean_key)
        prompt = (
            "Du bist ein Regionalexperte für Kultur-, Familien- und Freizeiteinrichtungen "
            "im Umkreis von maximal 60 Minuten Autofahrt um 77815 Bühl (Baden, Karlsruhe, "
            "Rastatt, Ortenau, Nordschwarzwald, Straßburg/Elsass). "
            "Schlage 3 bis 5 hochkarätige, offizielle Webseiten oder Kalender vor, die "
            "regelmäßig Veranstaltungen für Kinder von 4 bis 9 Jahren anbieten "
            "(z. B. Kindertheater, Museen mit Familienprogramm, Naturzentren, Familienmagazine).\n\n"
            "Folgende Quellen sind bereits bekannt und dürfen NICHT vorgeschlagen werden:\n"
            f"{', '.join(existing_names[:40])}\n\n"
            "Antworte ausschließlich mit einem validen JSON-Array aus Objekten mit folgenden Schlüsseln:\n"
            "- id: sprechender Slug (z. B. 'puppentheater-ka')\n"
            "- name: Name der Einrichtung/des Portals\n"
            "- region: Region (z. B. 'Karlsruhe', 'Baden-Baden', 'Elsass', 'Ortenau')\n"
            "- country: 'DE' oder 'FR'\n"
            "- url: Gültige, offizielle https://-URL\n"
            "- type: einer aus ['family_portal', 'municipal_calendar', 'museum', 'nature_center', 'science_center', 'theater']\n"
            "- description: Kurze deutsche Beschreibung (1-2 Sätze)\n"
            "- enabled: true\n"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw_text = (response.text or "").strip()
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        payload = json.loads(raw_text)
        candidates: list[SourceConfigEntry] = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    try:
                        candidates.append(SourceConfigEntry.model_validate(item))
                    except Exception:
                        continue
        return candidates
    except Exception as exc:
        print(f"[INFO] Gemini source discovery skipped ({exc}).", file=sys.stderr)
        return []


def verify_source_url(url: str, timeout: float = 6.0) -> bool:
    """Check if the source URL is reachable with an HTTP GET request."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        return resp.status_code < 400
    except requests.RequestException:
        return False


def compile_sources_database(
    config_path: Path = CONFIG_PATH,
    output_path: Path = SOURCES_JSON_PATH,
) -> SourcesDatabase:
    """Compile all sources from sources_config.json into data/sources.json."""
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    sources_cfg = load_sources(config)

    existing_events_by_id: dict[str, list[dict[str, Any]]] = {}
    last_meta = None
    if output_path.exists():
        try:
            prev_data = json.loads(output_path.read_text(encoding="utf-8"))
            last_meta = prev_data.get("metadata")
            for prev_src in prev_data.get("sources", []):
                sid = prev_src.get("id")
                if sid and prev_src.get("selected_events"):
                    existing_events_by_id[sid] = prev_src.get("selected_events", [])
        except (OSError, json.JSONDecodeError):
            pass

    sources_catalog: list[SourceCatalogEntry] = []
    for s in sources_cfg:
        sid = s.get("id")
        if sid and sid in existing_events_by_id:
            s["selected_events"] = existing_events_by_id[sid]
            s["events_count"] = len(existing_events_by_id[sid])
        try:
            sources_catalog.append(SourceCatalogEntry.model_validate(s))
        except Exception:
            continue

    metadata = Metadata.model_validate(last_meta) if last_meta else Metadata()
    metadata.last_updated = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata.sources_checked_count = len(sources_catalog)

    sources_database = SourcesDatabase(
        metadata=metadata,
        source_types=config.get("source_types", {}),
        sources=sources_catalog,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(sources_database.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[SUCCESS] Compiled {len(sources_catalog)} sources into {output_path}")
    return sources_database


def discover_and_save_sources(
    settings: DiscoverySettings,
    config_path: Path = CONFIG_PATH,
    output_path: Path = SOURCES_JSON_PATH,
) -> list[SourceConfigEntry]:
    """Execute the source discovery pipeline and save new sources directly to sources_config.json."""
    print("=== Starting Autonomous Event Source Discovery ===")
    known_ids, known_domains = load_known_identifiers(config_path)
    print(
        f"[INFO] Currently tracking {len(known_ids)} source IDs across {len(known_domains)} unique domains."
    )

    candidate_pool: list[SourceConfigEntry] = []

    # 1. AI candidate discovery if Gemini API key provided
    if settings.gemini_api_key:
        print("[INFO] Querying Google Gemini for new regional event sources...")
        gemini_candidates = fetch_candidates_from_gemini(
            settings.gemini_api_key, sorted(list(known_ids))
        )
        print(f"[INFO] Gemini suggested {len(gemini_candidates)} candidate sources.")
        candidate_pool.extend(gemini_candidates)

    # 2. Curated seed pool
    seed_candidates = get_seed_candidates()
    candidate_pool.extend(seed_candidates)

    saved_sources: list[SourceConfigEntry] = []
    seen_in_run: set[str] = set()

    for candidate in candidate_pool:
        if len(saved_sources) >= settings.max_sources:
            break

        cand_id = slugify(candidate.id or candidate.name)
        cand_domain = clean_domain(candidate.url)

        if not cand_id or not cand_domain:
            continue
        if cand_id in known_ids or cand_id in seen_in_run:
            continue
        if cand_domain in known_domains:
            continue
        if candidate.type not in SUPPORTED_SOURCE_TYPES:
            continue

        # Live reachability check
        if not settings.skip_network_check:
            is_alive = verify_source_url(candidate.url)
            if not is_alive:
                print(
                    f"[SKIP] Candidate '{candidate.name}' ({candidate.url}) unreachable."
                )
                continue

        seen_in_run.add(cand_id)
        known_domains.add(cand_domain)

        candidate_entry = SourceConfigEntry(
            id=cand_id,
            name=candidate.name,
            region=candidate.region,
            country=candidate.country,
            url=candidate.url,
            type=candidate.type,
            description=candidate.description,
            enabled=True,
        )

        if settings.dry_run:
            print(
                f"[DRY-RUN] Discovered candidate: '{candidate_entry.name}' "
                f"({candidate_entry.region}, {candidate_entry.url}) -> would add to {config_path.name}"
            )
        else:
            if config_path.exists():
                cfg_data = json.loads(config_path.read_text(encoding="utf-8"))
            else:
                cfg_data = {"sources": []}
            cfg_data.setdefault("sources", []).append(candidate_entry.model_dump())
            config_path.write_text(
                json.dumps(cfg_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"[SAVED] Added new source: '{candidate_entry.name}' -> {config_path.name}"
            )

        saved_sources.append(candidate_entry)

    if not settings.dry_run:
        compile_sources_database(
            config_path=config_path,
            output_path=output_path,
        )

    action = "Identified" if settings.dry_run else "Persisted"
    print(
        f"[SUCCESS] {action} {len(saved_sources)} new sources (max limit: {settings.max_sources})."
    )
    return saved_sources


def main() -> None:
    """CLI entry point executed via pyproject.toml."""
    CliApp.run(DiscoverySettings)


if __name__ == "__main__":
    main()

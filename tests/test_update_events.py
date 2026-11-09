"""Behavioral unit tests for the event aggregator and evaluation CLI."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import ValidationError

from scripts.update_events import (
    BUEHL_LAT,
    BUEHL_LON,
    Settings,
    add_source_via_cli,
    calculate_weighted_score,
    check_sources_health,
    compute_driving_route_from_buehl,
    enrich_with_gemini_if_available,
    extract_jsonld_events,
    get_next_weekend,
    haversine_km,
    load_modular_sources,
    main,
    run_aggregator,
    slugify,
)


class TestSlugify:
    """Tests for the slugify helper function."""

    def test_basic_slugify(self) -> None:
        assert slugify("Sandkorn Theater") == "sandkorn-theater"

    def test_umlauts_and_accents(self) -> None:
        assert slugify("Bühl & Ötigheim") == "buehl-oetigheim"
        assert slugify("Théâtre d'Alsace") == "theatre-d-alsace"
        assert slugify("Große Straße") == "grosse-strasse"

    def test_special_characters_and_length_limit(self) -> None:
        long_name = "A" * 60 + "!"
        slug = slugify(long_name)
        assert len(slug) <= 48
        assert slug == "a" * 48


class TestSettings:
    """Tests for the Pydantic Settings CLI model."""

    def test_default_values(self) -> None:
        settings = Settings()
        assert settings.country == "DE"
        assert settings.source_type == "family_portal"
        assert settings.max_drive_minutes == 60
        assert settings.skip_network_check is False
        assert settings.target_weekend is None

    def test_country_normalization_and_validation(self) -> None:
        settings_de = Settings(country="de")
        assert settings_de.country == "DE"

        settings_fr = Settings(country="fr")
        assert settings_fr.country == "FR"

        with pytest.raises(ValidationError):
            Settings(country="US")

    def test_cli_cmd_calls_run_aggregator(self) -> None:
        settings = Settings(skip_network_check=True)
        with patch("scripts.update_events.run_aggregator") as mock_run:
            settings.cli_cmd()
            mock_run.assert_called_once_with(settings)


class TestLoadSources:
    """Tests for loading and enriching sources from configuration."""

    def test_enriches_active_sources(self) -> None:
        config = {
            "sources": [
                {
                    "id": "base-1",
                    "name": "Base Source",
                    "url": "https://base.example.com",
                    "type": "museum",
                    "enabled": True,
                },
                {
                    "id": "base-2",
                    "name": "Disabled Source",
                    "url": "https://disabled.example.com",
                    "enabled": False,
                },
            ],
            "source_types": {
                "museum": {"label": "Museum", "icon": "🏛️"},
            },
        }

        sources = load_modular_sources(config)
        assert len(sources) == 1
        assert sources[0]["id"] == "base-1"
        assert sources[0]["type_label"] == "Museum"
        assert sources[0]["type_icon"] == "🏛️"


class TestAddSourceViaCli:
    """Tests for adding a new source via CLI."""

    def test_saves_new_source_to_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "sources_config.json"
        config_file.write_text(json.dumps({"sources": []}), encoding="utf-8")

        settings = Settings(
            add_source="New Puppet Theater",
            url="https://theater.example.com",
            region="Baden",
            country="DE",
            source_type="theater",
            description="Puppet theater for kids",
        )

        add_source_via_cli(settings, config_path=config_file)
        saved_cfg = json.loads(config_file.read_text(encoding="utf-8"))
        assert len(saved_cfg["sources"]) == 1
        saved = saved_cfg["sources"][0]
        assert saved["id"] == "new-puppet-theater"
        assert saved["name"] == "New Puppet Theater"
        assert saved["url"] == "https://theater.example.com"
        assert saved["type"] == "theater"
        assert saved["enabled"] is True

    def test_duplicate_source_is_not_readded(self, tmp_path: Path) -> None:
        config_file = tmp_path / "sources_config.json"
        config_file.write_text(
            json.dumps(
                {"sources": [{"id": "existing-theater", "url": "https://old.de"}]}
            ),
            encoding="utf-8",
        )

        settings = Settings(
            add_source="existing-theater",
            url="https://new.de",
        )
        add_source_via_cli(settings, config_path=config_file)
        saved_cfg = json.loads(config_file.read_text(encoding="utf-8"))
        assert len(saved_cfg["sources"]) == 1

    def test_missing_url_exits_with_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "sources_config.json"
        config_file.write_text(json.dumps({"sources": []}), encoding="utf-8")
        settings = Settings(add_source="No URL Source", url=None)
        with pytest.raises(SystemExit) as exc_info:
            add_source_via_cli(settings, config_path=config_file)
        assert exc_info.value.code == 1

    def test_no_add_source_is_noop(self, tmp_path: Path) -> None:
        config_file = tmp_path / "sources_config.json"
        config_file.write_text(json.dumps({"sources": []}), encoding="utf-8")
        settings = Settings(add_source=None)
        add_source_via_cli(settings, config_path=config_file)
        assert json.loads(config_file.read_text(encoding="utf-8")) == {"sources": []}


class TestGetNextWeekend:
    """Tests for weekend date calculation."""

    def test_explicit_valid_iso_date(self) -> None:
        fri, sat, sun = get_next_weekend("2026-11-14")
        assert fri == dt.date(2026, 11, 13)
        assert sat == dt.date(2026, 11, 14)
        assert sun == dt.date(2026, 11, 15)

    def test_invalid_date_falls_back_to_next_weekend(self) -> None:
        fri, sat, sun = get_next_weekend("invalid-date-format")
        assert sat.weekday() == 5  # Saturday
        assert fri == sat - dt.timedelta(days=1)
        assert sun == sat + dt.timedelta(days=1)

    def test_auto_calculation_always_returns_valid_weekend(self) -> None:
        fri, sat, sun = get_next_weekend(None)
        assert sat.weekday() == 5
        assert fri.weekday() == 4
        assert sun.weekday() == 6


class TestDistanceAndRouting:
    """Tests for geographical distance and driving route estimation."""

    def test_haversine_same_point(self) -> None:
        dist = haversine_km(BUEHL_LAT, BUEHL_LON, BUEHL_LAT, BUEHL_LON)
        assert dist == pytest.approx(0.0, abs=1e-5)

    def test_haversine_buehl_to_karlsruhe(self) -> None:
        karlsruhe_lat, karlsruhe_lon = 49.0069, 8.4037
        dist = haversine_km(BUEHL_LAT, BUEHL_LON, karlsruhe_lat, karlsruhe_lon)
        # Approximate distance Bühl -> Karlsruhe is ~39 km
        assert 35.0 < dist < 45.0

    @patch("requests.get")
    def test_osrm_routing_success(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "routes": [{"duration": 1800.0, "distance": 35000.0}]  # 30 min, 35 km
        }
        mock_get.return_value = mock_resp

        drive_min, dist_km = compute_driving_route_from_buehl(49.0069, 8.4037)
        assert drive_min == 30
        assert dist_km == 35

    @patch("requests.get", side_effect=requests.RequestException("Network down"))
    def test_osrm_routing_fallback_on_network_error(self, mock_get: MagicMock) -> None:
        drive_min, dist_km = compute_driving_route_from_buehl(49.0069, 8.4037)
        assert drive_min > 0
        assert dist_km > 0


class TestExtractJsonldEvents:
    """Tests for extracting schema.org Event metadata from HTML."""

    def test_extracts_single_and_graph_events(self) -> None:
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Event",
                "name": "Kinder-Mitmachzirkus",
                "description": "Zirkus-Workshop für Kinder ab 4 Jahren.",
                "startDate": "2026-11-14T10:00:00",
                "url": "/events/zirkus"
            }
            </script>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Event",
                        "name": "Puppentheater Zauberflöte",
                        "description": "Theaterstück für Grundschüler.",
                        "startDate": "2026-11-15T15:00:00"
                    },
                    {
                        "@type": "Organization",
                        "name": "Kulturverein"
                    }
                ]
            }
            </script>
        </head>
        </html>
        """
        source_meta = {
            "name": "Kulturportal",
            "url": "https://kultur.example.com",
            "region": "Baden",
            "country": "DE",
        }
        events = extract_jsonld_events(html, source_meta)
        assert len(events) == 2
        assert events[0]["title"] == "Kinder-Mitmachzirkus"
        assert events[0]["source_url"] == "https://kultur.example.com/events/zirkus"
        assert events[1]["title"] == "Puppentheater Zauberflöte"

    def test_handles_empty_or_invalid_jsonld(self) -> None:
        html = """
        <html><head>
            <script type="application/ld+json"></script>
            <script type="application/ld+json">{invalid-json}</script>
        </head></html>
        """
        source_meta = {
            "name": "Test",
            "url": "https://example.com",
            "region": "Baden",
            "country": "DE",
        }
        assert extract_jsonld_events(html, source_meta) == []


class TestEnrichWithGeminiIfAvailable:
    """Tests for optional AI enrichment."""

    def test_returns_empty_when_no_api_key_or_empty_candidates(self) -> None:
        weekend = (dt.date(2026, 11, 13), dt.date(2026, 11, 14), dt.date(2026, 11, 15))
        assert enrich_with_gemini_if_available([], weekend, api_key=None) == []
        assert (
            enrich_with_gemini_if_available([{"title": "Test"}], weekend, api_key="")
            == []
        )

    def test_handles_api_exception_gracefully(self) -> None:
        weekend = (dt.date(2026, 11, 13), dt.date(2026, 11, 14), dt.date(2026, 11, 15))
        with patch.dict(
            "sys.modules",
            {"google.genai": MagicMock(side_effect=RuntimeError("API error"))},
        ):
            result = enrich_with_gemini_if_available(
                [{"title": "Test"}], weekend, api_key="test-key"
            )
            assert result == []

    @patch("google.genai.Client")
    def test_parses_gemini_event_objects(
        self, mock_client_cls: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        chunk = MagicMock()
        chunk.text = json.dumps(
            [
                {
                    "id": "new-puppet-theater",
                    "title": "Puppentheater Zauberwald",
                    "category": "theater",
                    "weather_type": "indoor",
                    "country": "DE",
                    "region": "Karlsruhe",
                    "city": "Karlsruhe",
                    "drive_minutes_from_buehl": 35,
                    "distance_km_from_buehl": 40,
                }
            ]
        )
        mock_client.models.generate_content_stream.return_value = [chunk]

        weekend = (dt.date(2026, 11, 13), dt.date(2026, 11, 14), dt.date(2026, 11, 15))
        results = enrich_with_gemini_if_available(
            [{"title": "Raw event"}], weekend, api_key="valid-key"
        )
        assert len(results) == 1
        assert results[0].id == "new-puppet-theater"
        assert results[0].title == "Puppentheater Zauberwald"
        assert results[0].category == "theater"
        captured = capsys.readouterr()
        assert "[AI STREAM: Event Enrichment]" in captured.out
        assert "Puppentheater Zauberwald" in captured.out


class TestCheckSourcesHealth:
    """Tests for source pinging and health verification."""

    @patch("requests.get")
    def test_counts_reachable_sources_and_extracts_events(
        self, mock_get: MagicMock
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <script type="application/ld+json">
        {"@type": "Event", "name": "Museumsfest", "description": "Hands-on"}
        </script>
        """
        mock_get.return_value = mock_resp

        sources = [
            {
                "name": "S1",
                "url": "https://s1.example.com",
                "region": "Baden",
                "country": "DE",
            },
            {"name": "S2", "url": "", "region": "Baden", "country": "DE"},
        ]
        with patch("time.sleep"):
            reachable, events = check_sources_health(sources)

        assert reachable == 1
        assert len(events) == 1
        assert events[0]["title"] == "Museumsfest"


class TestCalculateWeightedScore:
    """Tests for the weighted family score calculation."""

    def test_calculates_weighted_average(self) -> None:
        criteria_cfg = [
            {"id": "c1", "weight": 0.6},
            {"id": "c2", "weight": 0.4},
        ]
        scores = {"c1": 10.0, "c2": 5.0}
        # (10.0 * 0.6 + 5.0 * 0.4) / 1.0 = 8.0
        assert calculate_weighted_score(scores, criteria_cfg) == 8.0

    def test_fallback_when_total_weight_zero(self) -> None:
        assert calculate_weighted_score({}, []) == 8.5


class TestRunAggregator:
    """Tests for the core execution pipeline."""

    def test_run_aggregator_end_to_end(self, tmp_path: Path) -> None:
        config_file = tmp_path / "sources_config.json"
        config_file.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "mock-src",
                            "name": "Mock Portal",
                            "url": "https://mock.example.com",
                            "region": "Bühl",
                            "country": "DE",
                            "type": "museum",
                            "enabled": True,
                        }
                    ],
                    "source_types": {"museum": {"label": "Museum", "icon": "🏛️"}},
                    "evaluation_criteria": [
                        {"id": "hands_on", "weight": 1.0},
                    ],
                }
            ),
            encoding="utf-8",
        )

        events_file = tmp_path / "events.json"
        sources_file = tmp_path / "sources.json"
        events_file.write_text(
            json.dumps(
                {
                    "metadata": {},
                    "events": [
                        {
                            "id": "ev-nearby",
                            "title": "Nearby Event",
                            "coordinates": {"lat": BUEHL_LAT, "lon": BUEHL_LON},
                            "drive_minutes": 10,
                            "distance_km": 5,
                            "criteria_ratings": {"hands_on": {"score": 9.0}},
                            "sources": [
                                {
                                    "name": "Mock Portal",
                                    "url": "https://mock.example.com/event",
                                }
                            ],
                        },
                        {
                            "id": "ev-too-far",
                            "title": "Too Far Away Event",
                            "coordinates": {"lat": 50.0, "lon": 10.0},
                            "drive_minutes": 120,
                            "distance_km": 150,
                            "criteria_ratings": {"hands_on": {"score": 8.0}},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        settings = Settings(
            skip_network_check=True,
            max_drive_minutes=60,
            target_weekend="2026-11-14",
        )

        with (
            patch("scripts.update_events.CONFIG_PATH", config_file),
            patch("scripts.update_events.EVENTS_JSON_PATH", events_file),
            patch("scripts.update_events.SOURCES_JSON_PATH", sources_file),
        ):
            run_aggregator(settings)

            updated = json.loads(events_file.read_text(encoding="utf-8"))
            assert len(updated["events"]) == 1
            assert updated["events"][0]["id"] == "ev-nearby"
            assert updated["events"][0]["family_score"] == 9.0
            assert updated["metadata"]["total_events"] == 1
            assert updated["metadata"]["home_base"]["max_drive_minutes"] == 60

            updated_sources = json.loads(sources_file.read_text(encoding="utf-8"))
            assert len(updated_sources["sources"]) == 1
            assert updated_sources["sources"][0]["id"] == "mock-src"


class TestCliExecution:
    """Behavioral tests for the CLI execution and dry-run via CliApp."""

    def test_cli_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify CLI --help option prints usage and available flags."""
        from pydantic_settings import CliApp

        with pytest.raises(SystemExit) as exc_info:
            CliApp.run(Settings, cli_args=["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--skip-network-check" in captured.out
        assert "--target-weekend" in captured.out
        assert "--max-drive-minutes" in captured.out

    def test_cli_argument_parsing(self) -> None:
        """Verify CLI parses flags into Settings and dispatches to run_aggregator."""
        from pydantic_settings import CliApp

        with patch("scripts.update_events.run_aggregator") as mock_run:
            settings = CliApp.run(
                Settings,
                cli_args=[
                    "--skip-network-check",
                    "--target-weekend",
                    "2026-11-21",
                    "--max-drive-minutes",
                    "45",
                    "--country",
                    "fr",
                ],
            )
            assert settings.skip_network_check is True
            assert settings.target_weekend == "2026-11-21"
            assert settings.max_drive_minutes == 45
            assert settings.country == "FR"
            mock_run.assert_called_once_with(settings)

    def test_cli_dry_run_end_to_end(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Verify full CLI dry run executes pipeline without network calls."""
        import shutil
        from pydantic_settings import CliApp
        from scripts.update_events import CONFIG_PATH, EVENTS_JSON_PATH

        test_config = tmp_path / "sources_config.json"
        test_events = tmp_path / "events.json"
        test_sources = tmp_path / "sources.json"
        shutil.copyfile(CONFIG_PATH, test_config)
        shutil.copyfile(EVENTS_JSON_PATH, test_events)

        with (
            patch("scripts.update_events.CONFIG_PATH", test_config),
            patch("scripts.update_events.EVENTS_JSON_PATH", test_events),
            patch("scripts.update_events.SOURCES_JSON_PATH", test_sources),
        ):
            settings = CliApp.run(
                Settings,
                cli_args=["--skip-network-check", "--target-weekend", "2026-11-14"],
            )
            assert settings.skip_network_check is True

        captured = capsys.readouterr()
        assert "Starting Family Weekend Compass update" in captured.out
        assert "network check skipped" in captured.out
        assert "Saved" in captured.out

        updated_events = json.loads(test_events.read_text(encoding="utf-8"))
        assert len(updated_events["events"]) > 0
        assert updated_events["metadata"]["total_events"] > 0
        assert test_sources.exists()
        updated_sources = json.loads(test_sources.read_text(encoding="utf-8"))
        assert len(updated_sources["sources"]) > 0

    def test_main_invokes_cliapp_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify main() entrypoint delegates to CliApp.run."""
        from pydantic_settings import CliApp

        monkeypatch.setattr("sys.argv", ["update-events", "--skip-network-check"])
        with patch.object(CliApp, "run") as mock_cli_run:
            main()
            mock_cli_run.assert_called_once_with(Settings)

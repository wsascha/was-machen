"""Behavioral unit tests for regional source discovery pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.discover_sources import (
    DiscoverySettings,
    clean_domain,
    compile_sources_database,
    discover_and_save_sources,
    fetch_candidates_from_gemini,
    get_seed_candidates,
    load_known_identifiers,
    verify_source_url,
)
from scripts.schema import SourceConfigEntry, SourcesDatabase


class TestDiscoverySettings:
    """Tests for DiscoverySettings parsing and validation."""

    def test_default_settings(self) -> None:
        settings = DiscoverySettings()
        assert settings.gemini_api_key is None
        assert settings.max_sources == 3
        assert settings.dry_run is False
        assert settings.skip_network_check is False

    def test_custom_settings(self) -> None:
        settings = DiscoverySettings(
            gemini_api_key="secret-key",
            max_sources=5,
            dry_run=True,
            skip_network_check=True,
        )
        assert settings.gemini_api_key == "secret-key"
        assert settings.max_sources == 5
        assert settings.dry_run is True
        assert settings.skip_network_check is True


class TestCleanDomain:
    """Tests for clean_domain helper function."""

    def test_cleans_standard_urls(self) -> None:
        assert clean_domain("https://www.example.com/events") == "example.com"
        assert clean_domain("http://sub.domain.org/path/item") == "sub.domain.org"
        assert clean_domain("https://example.de") == "example.de"

    def test_handles_empty_or_malformed_urls(self) -> None:
        assert clean_domain("") == ""
        assert clean_domain("not-a-valid-url") == ""


class TestLoadKnownIdentifiers:
    """Tests for loading IDs and domains from configuration file."""

    def test_load_from_valid_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "sources_config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "sources": [
                        {"id": "src-1", "url": "https://www.source1.de/events"},
                        {"name": "Source Two", "url": "https://source2.com"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        known_ids, known_domains = load_known_identifiers(cfg_file)
        assert "src-1" in known_ids
        assert "source-two" in known_ids
        assert "source1.de" in known_domains
        assert "source2.com" in known_domains

    def test_handles_missing_file_gracefully(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "non_existent.json"
        known_ids, known_domains = load_known_identifiers(cfg_file)
        assert len(known_ids) == 0
        assert len(known_domains) == 0


class TestGetSeedCandidates:
    """Tests for get_seed_candidates catalog."""

    def test_seed_candidates_validity(self) -> None:
        seeds = get_seed_candidates()
        assert len(seeds) >= 5
        for seed in seeds:
            assert isinstance(seed, SourceConfigEntry)
            assert seed.id
            assert seed.name
            assert seed.region
            assert seed.country in ("DE", "FR")
            assert seed.url.startswith("http")
            assert seed.type in (
                "family_portal",
                "municipal_calendar",
                "museum",
                "nature_center",
                "science_center",
                "theater",
            )


class TestVerifySourceUrl:
    """Tests for HTTP check utility verify_source_url."""

    @patch("scripts.discover_sources.requests.get")
    def test_url_reachable(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert verify_source_url("https://example.com") is True

    @patch("scripts.discover_sources.requests.get")
    def test_url_error_status(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        assert verify_source_url("https://example.com/notfound") is False

    @patch("scripts.discover_sources.requests.get")
    def test_url_connection_exception(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.RequestException("Connection refused")
        assert verify_source_url("https://invalid.example.com") is False


class TestFetchCandidatesFromGemini:
    """Tests for AI candidate generation via Google Gemini API."""

    def test_empty_api_key_returns_empty(self) -> None:
        assert fetch_candidates_from_gemini("", ["existing-src"]) == []
        assert fetch_candidates_from_gemini("   ", ["existing-src"]) == []

    @patch("google.genai.Client")
    def test_parses_json_response(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        chunk = MagicMock()
        chunk.text = json.dumps(
            [
                {
                    "id": "gemini-theater-ka",
                    "name": "Gemini Kindertheater",
                    "region": "Karlsruhe",
                    "country": "DE",
                    "url": "https://www.gemini-theater.de",
                    "type": "theater",
                    "description": "Theater für Kids.",
                    "enabled": True,
                }
            ]
        )
        mock_client.models.generate_content_stream.return_value = [chunk]

        candidates = fetch_candidates_from_gemini("test-key", ["existing"])
        assert len(candidates) == 1
        assert candidates[0].id == "gemini-theater-ka"
        assert candidates[0].name == "Gemini Kindertheater"

    @patch("google.genai.Client")
    def test_handles_markdown_wrapped_json(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        chunk = MagicMock()
        chunk.text = (
            "```json\n"
            '[{"id": "alsace-park", "name": "Alsace Park", "region": "Elsass", '
            '"country": "FR", "url": "https://alsacepark.fr", "type": "nature_center", '
            '"description": "Naturpark", "enabled": true}]\n```'
        )
        mock_client.models.generate_content_stream.return_value = [chunk]

        candidates = fetch_candidates_from_gemini("test-key", ["existing"])
        assert len(candidates) == 1
        assert candidates[0].id == "alsace-park"
        assert candidates[0].country == "FR"

    @patch("google.genai.Client")
    def test_handles_api_exception_gracefully(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content_stream.side_effect = RuntimeError(
            "Quota exceeded"
        )

        candidates = fetch_candidates_from_gemini("test-key", ["existing"])
        assert candidates == []

    @patch("google.genai.Client")
    def test_streams_output_tokens(
        self, mock_client_cls: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        chunk1 = MagicMock()
        chunk1.text = '[{"id": "stream-src", "name": "Stream Source", '
        chunk2 = MagicMock()
        chunk2.text = (
            '"region": "Baden", "country": "DE", "url": "https://stream.de", '
            '"type": "museum", "description": "Streamed Museum", "enabled": true}]'
        )
        mock_client.models.generate_content_stream.return_value = [chunk1, chunk2]

        candidates = fetch_candidates_from_gemini("test-key", ["existing"])
        assert len(candidates) == 1
        assert candidates[0].id == "stream-src"
        captured = capsys.readouterr()
        assert "[AI STREAM: Source Discovery]" in captured.out
        assert "Streamed Museum" in captured.out


class TestDiscoverAndSaveSources:
    """Tests for discover_and_save_sources workflow execution."""

    def test_dry_run_does_not_modify_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "sources_config.json"
        initial_content = json.dumps({"sources": []})
        cfg_file.write_text(initial_content, encoding="utf-8")

        settings = DiscoverySettings(
            max_sources=2,
            dry_run=True,
            skip_network_check=True,
        )

        saved = discover_and_save_sources(
            settings,
            config_path=cfg_file,
            output_path=tmp_path / "sources.json",
        )
        assert len(saved) == 2
        # Config file content must remain unchanged in dry run mode
        assert cfg_file.read_text(encoding="utf-8") == initial_content

    def test_saves_new_sources_directly_to_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "sources_config.json"
        cfg_file.write_text(json.dumps({"sources": []}), encoding="utf-8")
        out_sources_json = tmp_path / "sources.json"

        settings = DiscoverySettings(
            max_sources=2,
            dry_run=False,
            skip_network_check=True,
        )

        saved = discover_and_save_sources(
            settings,
            config_path=cfg_file,
            output_path=out_sources_json,
        )
        assert len(saved) == 2

        # Verify sources_config.json was updated with new sources
        cfg_after = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert len(cfg_after["sources"]) == 2
        entry = SourceConfigEntry.model_validate(cfg_after["sources"][0])
        assert entry.id
        assert entry.enabled is True

        # Verify compiled sources.json was created and validated
        assert out_sources_json.exists()
        compiled = json.loads(out_sources_json.read_text(encoding="utf-8"))
        db = SourcesDatabase.model_validate(compiled)
        assert len(db.sources) == 2

    def test_skips_already_known_sources(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "sources_config.json"
        # Seed candidates have 'das-sandkorn-theater-ka' and 'www.das-sandkorn.de'
        cfg_file.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "das-sandkorn-theater-ka",
                            "url": "https://www.das-sandkorn.de/programm/kinder.html",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        settings = DiscoverySettings(
            max_sources=1,
            dry_run=True,
            skip_network_check=True,
        )

        saved = discover_and_save_sources(
            settings,
            config_path=cfg_file,
            output_path=tmp_path / "sources.json",
        )
        assert len(saved) == 1
        # The first saved candidate should NOT be the already known sandkorn theater
        assert saved[0].id != "das-sandkorn-theater-ka"


class TestCompileSourcesDatabase:
    """Tests for compiling full sources database."""

    def test_compiles_from_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "sources_config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "source_types": {"theater": {"label": "Theater", "icon": "🎭"}},
                    "sources": [
                        {
                            "id": "base-theater",
                            "name": "Base Theater",
                            "region": "Baden",
                            "country": "DE",
                            "url": "https://base.de",
                            "type": "theater",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        out_file = tmp_path / "sources.json"
        db = compile_sources_database(
            config_path=cfg_file,
            output_path=out_file,
        )
        assert len(db.sources) == 1
        assert db.metadata.sources_checked_count == 1
        assert out_file.exists()

    def test_preserves_existing_event_references(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "sources_config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "src-with-events",
                            "name": "Source With Events",
                            "region": "Baden",
                            "country": "DE",
                            "url": "https://events.de",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        out_file = tmp_path / "sources.json"
        out_file.write_text(
            json.dumps(
                {
                    "metadata": {"title": "Existing Title"},
                    "sources": [
                        {
                            "id": "src-with-events",
                            "name": "Source With Events",
                            "region": "Baden",
                            "country": "DE",
                            "url": "https://events.de",
                            "events_count": 1,
                            "selected_events": [{"id": "ev-1", "title": "Event 1"}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        db = compile_sources_database(
            config_path=cfg_file,
            output_path=out_file,
        )
        assert len(db.sources) == 1
        assert db.sources[0].events_count == 1
        assert db.sources[0].selected_events[0].id == "ev-1"


class TestCliExecution:
    """Tests for discover-sources CLI execution via CliApp."""

    def test_cli_execution_with_dry_run_flag(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from pydantic_settings import CliApp

        settings = CliApp.run(
            DiscoverySettings,
            cli_args=["--dry-run", "--skip-network-check", "--max-sources", "1"],
        )
        assert settings.dry_run is True
        assert settings.skip_network_check is True
        assert settings.max_sources == 1

        captured = capsys.readouterr()
        assert "Starting Autonomous Event Source Discovery" in captured.out
        assert "[DRY-RUN]" in captured.out

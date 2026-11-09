"""Behavioral unit tests for release notes generator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.release_notes import (
    ReleaseNotesSettings,
    build_release_summary,
    extract_added_titles,
    get_git_file_content,
    get_previous_git_tag,
    run_release_notes,
)


class TestExtractAddedTitles:
    """Tests for extracting and sorting newly added titles."""

    def test_extract_all_when_no_previous_items(self) -> None:
        items = [
            {"id": "b", "title": "Beta Event"},
            {"id": "a", "title": "Alpha Event"},
            {"id": "c", "title": "Alpha Event"},  # Duplicate title
        ]
        result = extract_added_titles(items, None, title_key="title")
        assert result == ["Alpha Event", "Beta Event"]

    def test_extract_only_new_items_by_id(self) -> None:
        current = [
            {"id": "1", "name": "Source One"},
            {"id": "2", "name": "Source Two"},
            {"id": "3", "name": "Source Three"},
        ]
        previous = [
            {"id": "1", "name": "Source One"},
        ]
        result = extract_added_titles(current, previous, title_key="name")
        assert result == ["Source Three", "Source Two"]

    def test_handles_empty_or_malformed_items(self) -> None:
        assert extract_added_titles([], []) == []
        assert extract_added_titles([{"id": ""}, {"name": ""}], []) == []


class TestBuildReleaseSummary:
    """Tests for constructing release tag, title, and markdown body."""

    def test_summary_with_new_sources_and_events(self) -> None:
        current_sources = {
            "sources": [
                {"id": "s1", "name": "Theater Baden"},
                {"id": "s2", "name": "Museum Karlsruhe"},
            ]
        }
        previous_sources = {"sources": [{"id": "s1", "name": "Theater Baden"}]}
        current_events = {
            "metadata": {
                "weekend_label": "13.–15. November",
                "weekend_start": "2026-11-13",
            },
            "events": [
                {"id": "e1", "title": "Puppentheater"},
                {"id": "e2", "title": "Astronauten-Workshop"},
            ],
        }
        previous_events = {"events": [{"id": "e1", "title": "Puppentheater"}]}

        tag, title, body = build_release_summary(
            current_sources,
            current_events,
            previous_sources,
            previous_events,
        )

        assert tag == "v2026.46"
        assert title == "Wochenende 13.–15. November"
        assert "### 📚 Neue Quellen (1)" in body
        assert "- Museum Karlsruhe" in body
        assert "Theater Baden" not in body
        assert "### 🎈 Neue Veranstaltungen (1)" in body
        assert "- Astronauten-Workshop" in body
        assert "- Puppentheater" not in body

    def test_summary_with_zero_added_items(self) -> None:
        sources = {"sources": [{"id": "s1", "name": "Known Source"}]}
        events = {
            "metadata": {
                "weekend_label": "20.–22. November",
                "weekend_start": "2026-11-20",
            },
            "events": [{"id": "e1", "title": "Known Event"}],
        }
        tag, title, body = build_release_summary(sources, events, sources, events)
        assert tag == "v2026.47"
        assert title == "Wochenende 20.–22. November"
        assert "### 📚 Neue Quellen (0)" in body
        assert "*Keine neuen Quellen in diesem Durchlauf.*" in body
        assert "### 🎈 Neue Veranstaltungen (0)" in body
        assert "*Keine neuen Veranstaltungen in diesem Durchlauf.*" in body


class TestGitHelpers:
    """Tests for git subprocess helper functions."""

    @patch("subprocess.run")
    def test_get_previous_git_tag(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "v2026.45\n"
        mock_run.return_value = mock_proc

        assert get_previous_git_tag() == "v2026.45"

    @patch("subprocess.run")
    def test_get_previous_git_tag_failure(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stdout = ""
        mock_run.return_value = mock_proc

        assert get_previous_git_tag() is None

    @patch("subprocess.run")
    def test_get_git_file_content(self, mock_run: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"title": "File content"}'
        mock_run.return_value = mock_proc

        content = get_git_file_content("HEAD^", "data/events.json")
        assert content == '{"title": "File content"}'


class TestRunReleaseNotes:
    """Tests for run_release_notes execution flow."""

    def test_writes_output_file_and_github_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        test_events = tmp_path / "events.json"
        test_sources = tmp_path / "sources.json"
        test_output = tmp_path / "release_notes.md"
        gh_output = tmp_path / "gh_output.txt"

        test_events.write_text(
            json.dumps(
                {
                    "metadata": {
                        "weekend_label": "13.–15. November",
                        "weekend_start": "2026-11-13",
                    },
                    "events": [{"id": "ev-1", "title": "Herbstfest"}],
                }
            ),
            encoding="utf-8",
        )
        test_sources.write_text(
            json.dumps({"sources": [{"id": "src-1", "name": "Stadtbücherei"}]}),
            encoding="utf-8",
        )

        monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))

        with (
            patch("scripts.release_notes.EVENTS_JSON_PATH", test_events),
            patch("scripts.release_notes.SOURCES_JSON_PATH", test_sources),
            patch("scripts.release_notes.get_previous_git_tag", return_value=None),
        ):
            settings = ReleaseNotesSettings(output_file=str(test_output))
            run_release_notes(settings)

        assert test_output.exists()
        content = test_output.read_text(encoding="utf-8")
        assert "Herbstfest" in content
        assert "Stadtbücherei" in content

        gh_content = gh_output.read_text(encoding="utf-8")
        assert "tag_name=v2026.46" in gh_content
        assert "release_title=Wochenende 13.–15. November" in gh_content


class TestCliExecution:
    """Tests for CLI invocation of release-notes."""

    def test_cli_execution_with_settings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pydantic_settings import CliApp

        test_events = tmp_path / "events.json"
        test_sources = tmp_path / "sources.json"
        test_events.write_text(
            json.dumps({"metadata": {"weekend_label": "Test"}, "events": []}),
            encoding="utf-8",
        )
        test_sources.write_text(json.dumps({"sources": []}), encoding="utf-8")

        with (
            patch("scripts.release_notes.EVENTS_JSON_PATH", test_events),
            patch("scripts.release_notes.SOURCES_JSON_PATH", test_sources),
            patch("scripts.release_notes.get_previous_git_tag", return_value=None),
        ):
            settings = CliApp.run(
                ReleaseNotesSettings,
                cli_args=["--since-ref", "HEAD"],
            )
            assert settings.since_ref == "HEAD"

        captured = capsys.readouterr()
        assert "Wochenend-Kompass" in captured.out

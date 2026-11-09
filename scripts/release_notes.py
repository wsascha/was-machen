"""Release notes generator for weekly Continuous Deployment.

Summarizes added event sources and weekend events (by title) by comparing
the current database against the previous release tag or git revision.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import (
    BaseSettings,
    CliApp,
    SettingsConfigDict,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVENTS_JSON_PATH = PROJECT_ROOT / "data" / "events.json"
SOURCES_JSON_PATH = PROJECT_ROOT / "data" / "sources.json"


class ReleaseNotesSettings(BaseSettings):
    """Configuration settings for release notes generation."""

    model_config = SettingsConfigDict(
        cli_kebab_case=True,
        env_file=".env",
        extra="ignore",
    )

    since_ref: str | None = Field(
        default=None,
        validation_alias=AliasChoices("since_ref", "SINCE_REF"),
        description="Previous git tag or commit to compare against (defaults to latest tag)",
    )
    output_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("output_file", "OUTPUT_FILE"),
        description="Path to write the generated markdown release notes",
    )

    def cli_cmd(self) -> None:
        """Entry point executed by CliApp."""
        run_release_notes(self)


def get_previous_git_tag() -> str | None:
    """Retrieve the most recent git tag from the repository history."""
    try:
        proc = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "HEAD^"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        tag = proc.stdout.strip()
        return tag if proc.returncode == 0 and tag else None
    except OSError:
        return None


def get_git_file_content(git_ref: str, relative_path: str) -> str | None:
    """Fetch file contents from a specific git revision."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{git_ref}:{relative_path}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout if proc.returncode == 0 else None
    except OSError:
        return None


def extract_added_titles(
    current_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]] | None,
    title_key: str = "title",
) -> list[str]:
    """
    Extract and alphabetically sort titles of items added since previous revision.
    If previous_items is None, returns all current item titles.
    """
    if previous_items is None:
        titles = [
            str(item.get(title_key, "")).strip()
            for item in current_items
            if item.get(title_key)
        ]
        return sorted(list(dict.fromkeys(titles)))

    previous_ids = {
        item.get("id")
        for item in previous_items
        if isinstance(item, dict) and item.get("id")
    }
    added_titles: list[str] = []
    for item in current_items:
        if not isinstance(item, dict):
            continue
        iid = item.get("id")
        title = str(item.get(title_key, "")).strip()
        if iid and iid not in previous_ids and title:
            added_titles.append(title)

    return sorted(list(dict.fromkeys(added_titles)))


def build_release_summary(
    current_sources: dict[str, Any],
    current_events: dict[str, Any],
    previous_sources: dict[str, Any] | None = None,
    previous_events: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """
    Construct tag name, release title, and markdown body summarizing added sources and events.
    """
    metadata = current_events.get("metadata", {})
    weekend_label = metadata.get("weekend_label", "")
    weekend_start = metadata.get("weekend_start", "")

    # Calculate tag name (e.g. v2026.46)
    tag_name = ""
    if weekend_start:
        try:
            date_obj = dt.date.fromisoformat(weekend_start)
            year, week_num, _ = date_obj.isocalendar()
            tag_name = f"v{year}.{week_num:02d}"
        except ValueError:
            pass

    if not tag_name:
        now = dt.date.today()
        year, week_num, _ = now.isocalendar()
        tag_name = f"v{year}.{week_num:02d}"

    # Calculate release title
    if weekend_label:
        release_title = f"Wochenende {weekend_label}"
    else:
        release_title = f"Wochenend-Kompass ({tag_name})"

    # Extract added source names and event titles
    curr_src_list = current_sources.get("sources", [])
    prev_src_list = previous_sources.get("sources", []) if previous_sources else None
    added_sources = extract_added_titles(curr_src_list, prev_src_list, title_key="name")

    curr_ev_list = current_events.get("events", [])
    prev_ev_list = previous_events.get("events", []) if previous_events else None
    added_events = extract_added_titles(curr_ev_list, prev_ev_list, title_key="title")

    # Build markdown body
    lines: list[str] = [
        f"## 🧭 Regionaler Wochenend-Kompass für Familien ({weekend_label or tag_name})",
        "",
    ]

    lines.append(f"### 📚 Neue Quellen ({len(added_sources)})")
    if added_sources:
        for title in added_sources:
            lines.append(f"- {title}")
    else:
        lines.append("*Keine neuen Quellen in diesem Durchlauf.*")
    lines.append("")

    lines.append(f"### 🎈 Neue Veranstaltungen ({len(added_events)})")
    if added_events:
        for title in added_events:
            lines.append(f"- {title}")
    else:
        lines.append("*Keine neuen Veranstaltungen in diesem Durchlauf.*")
    lines.append("")

    markdown_body = "\n".join(lines)
    return tag_name, release_title, markdown_body


def run_release_notes(settings: ReleaseNotesSettings) -> None:
    """Generate release notes comparing current files to previous revision."""
    if not SOURCES_JSON_PATH.exists() or not EVENTS_JSON_PATH.exists():
        print(
            f"[ERROR] Required database files not found ({SOURCES_JSON_PATH}, {EVENTS_JSON_PATH})",
            file=sys.stderr,
        )
        sys.exit(1)

    current_sources = json.loads(SOURCES_JSON_PATH.read_text(encoding="utf-8"))
    current_events = json.loads(EVENTS_JSON_PATH.read_text(encoding="utf-8"))

    since_ref = settings.since_ref or get_previous_git_tag()
    previous_sources: dict[str, Any] | None = None
    previous_events: dict[str, Any] | None = None

    if since_ref:
        print(f"[INFO] Comparing changes against git reference: {since_ref}")
        prev_src_text = get_git_file_content(since_ref, "data/sources.json")
        prev_ev_text = get_git_file_content(since_ref, "data/events.json")
        if prev_src_text:
            try:
                previous_sources = json.loads(prev_src_text)
            except json.JSONDecodeError:
                pass
        if prev_ev_text:
            try:
                previous_events = json.loads(prev_ev_text)
            except json.JSONDecodeError:
                pass
    else:
        print("[INFO] No previous git tag found. Summarizing all current items.")

    tag_name, release_title, markdown_body = build_release_summary(
        current_sources,
        current_events,
        previous_sources,
        previous_events,
    )

    # Set GitHub Actions step outputs if running in CI
    github_output_path = os.getenv("GITHUB_OUTPUT")
    if github_output_path:
        with open(github_output_path, "a", encoding="utf-8") as gh_out:
            gh_out.write(f"tag_name={tag_name}\n")
            gh_out.write(f"release_title={release_title}\n")

    if settings.output_file:
        out_path = Path(settings.output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown_body, encoding="utf-8")
        print(f"[SUCCESS] Release notes written to {out_path}")

    print(f"=== {release_title} ({tag_name}) ===")
    print(markdown_body)


def main() -> None:
    """CLI entry point executed via pyproject.toml."""
    CliApp.run(ReleaseNotesSettings)


if __name__ == "__main__":
    main()

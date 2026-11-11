> [!NOTE]
> This project is completely vibe-coded.

# 🧭 "Was machen wir am Wochenende?"

A static web app and automated event crawler for family-friendly weekend activities around **77815 Bühl, Germany** (within a ~60-minute driving radius covering the Black Forest, Karlsruhe, Ortenau, and Alsace/France).

Events are automatically aggregated and scored across 7 criteria tailored for families with kids aged 4–9 (hands-on experience, weather suitability, parent relaxation, OSRM drive time from Bühl, etc.).

---

## 🚀 Local Development

### 1. Run the Web App

Because events are loaded asynchronously from `data/events.json`, run a local HTTP server in the project directory:

```bash
uv run python -m http.server 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

### 2. Update Event Data (Optional)

To crawl regional sources, calculate drive times from Bühl, and update `data/events.json` and `data/sources.json`:

```bash
uv sync
uv run update-events
```

Inspect available CLI options (`pydantic-settings`):

```bash
uv run update-events --help
```

> **Tip:** Configure options via CLI flags or environment variables:
>
> - Enable AI evaluation: `--gemini-api-key <KEY>` (or `GEMINI_API_KEY=...`)
> - Fast local sync without HTTP checks: `--skip-network-check`
> - Target a specific weekend: `--target-weekend YYYY-MM-DD` (or `TARGET_WEEKEND=...`)

### 3. Discover New Sources (Optional)

Search for new regional family event portals, children's theaters, and museums within ~60 minutes of Bühl:

```bash
uv run discover-sources --max-sources 3
```

- Run a dry-run simulation: `uv run discover-sources --dry-run`
- Skip HTTP availability checks: `uv run discover-sources --skip-network-check`
- Use Google Gemini for AI-driven discovery: `uv run discover-sources --gemini-api-key <KEY>`

---

## 🔄 Automated Workflows

The repository uses automated GitHub Actions workflows with distinct responsibilities:

1. **Populate Sources** (`.github/workflows/discover-sources.yml`):
   - Decoupled autonomous pipeline that discovers, validates, and populates regional event sources in `scripts/sources_config.json` and compiles `data/sources.json`.
   - Runs every Friday at 03:00 UTC and on manual dispatch.
2. **Populate Events from Sources** (`.github/workflows/update-events.yml`):
   - Integrated into the Continuous Deployment (CD) pipeline.
   - Crawls active sources, extracts weekend events, computes driving distances from Bühl, scores activities across the 7 family criteria, and writes `data/events.json`.
3. **Continuous Deployment (CD)** (`.github/workflows/cd.yml`):
   - Orchestrates the event crawler and weekly release generation every Monday and Wednesday at 06:00 UTC, and on manual dispatch.
   - Deploys the static web app to GitHub Pages on every change to `main`.
   - Generates release notes summarizing newly added sources and events by title via `uv run release-notes`.
   - Publishes/updates a tagged weekly GitHub release (e.g. `vYYYY.WW`).

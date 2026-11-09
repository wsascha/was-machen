# Agent Guidelines

## Documentation

- `AGENTS.md`: Operational instructions and rules for AI coding agents.
- `README.md`: Written in English for human readers (project overview, features, local setup).

## Git & Commits

- **Atomic Commits**: Keep commits small, self-contained, and easy to review.
- **Conventional Commits**: Format as `<type>(<scope>): <summary>` (imperative, lower-case, English).
  - **Types**: `chore`, `ci`, `data`, `docs`, `feat`, `fix`, `refactor`, `test`.
  - **Scopes**:
    - `ci`: GitHub Actions workflows (`.github/workflows/`).
    - `crawler`: Ingestion, scoring, and source discovery pipeline (`scripts/discover_sources.py`, `scripts/release_notes.py`, `scripts/update_events.py`).
    - `data`: Event database and sources configuration (`data/events.json`, `data/sources.json`, `sources_config.json`).
    - `deps`: Dependencies and lockfile (`pyproject.toml`, `uv.lock`).
    - `docs`: Documentation files.
    - `ui`: Web app interface, maps, styles, scripts (`index.html`, `sources.html`, `js/`, `css/`).
- **Linear History**: Always rebase; avoid merge commits.
- **Pre-Commit**: Ensure hooks are installed via `pre-commit install` so linting and formatting run automatically before each commit.

## GitHub CLI (`gh`)

- **GitHub CLI**: Always use the GitHub CLI (`gh`) for checking workflow runs, inspecting CI failure logs, viewing releases, and querying GitHub repository state instead of guessing or scraping. Ensure `/opt/homebrew/bin` is in `$PATH` when invoking `gh`.

## Language & Code Style

- **Alphabetical Sorting**: Prefer alphabetical sorting in unordered lists.
- **Code in English**: All code (variables, functions, classes, expressions, comments, commit messages, and developer documentation) must be written in English.
- **German Content**: User-facing content and regional data (e.g., event descriptions, categories, UI copy) remain in German.

## Testing

- **Behavioral Unit Tests**: There should be unit tests covering user / call-site behavior for every function.

"""Behavioral unit tests for Web UI assets and accessibility."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = PROJECT_ROOT / "index.html"
SOURCES_HTML = PROJECT_ROOT / "sources.html"
STYLES_CSS = PROJECT_ROOT / "css" / "styles.css"
APP_JS = PROJECT_ROOT / "js" / "app.js"
SOURCES_JS = PROJECT_ROOT / "js" / "sources.js"


class TestBackToTopButtonMarkup:
    """Tests for Back to Top ('Nach oben') HTML markup across pages."""

    def test_index_html_contains_sentinel_and_button(self) -> None:
        content = INDEX_HTML.read_text(encoding="utf-8")
        assert 'id="scroll-sentinel"' in content
        assert 'class="scroll-sentinel"' in content
        assert 'id="btn-back-to-top"' in content
        assert 'class="btn-back-to-top"' in content
        assert "Nach oben" in content
        assert 'aria-label="Nach oben scrollen"' in content
        assert 'type="button"' in content

    def test_sources_html_contains_sentinel_and_button(self) -> None:
        content = SOURCES_HTML.read_text(encoding="utf-8")
        assert 'id="scroll-sentinel"' in content
        assert 'class="scroll-sentinel"' in content
        assert 'id="btn-back-to-top"' in content
        assert 'class="btn-back-to-top"' in content
        assert "Nach oben" in content
        assert 'aria-label="Nach oben scrollen"' in content
        assert 'type="button"' in content


class TestBackToTopStyles:
    """Tests for Back to Top CSS styles and responsive design."""

    def test_styles_css_defines_floating_button_and_sentinel(self) -> None:
        css = STYLES_CSS.read_text(encoding="utf-8")
        assert ".scroll-sentinel" in css
        assert ".btn-back-to-top" in css
        assert "position: fixed" in css
        assert "safe-area-inset-bottom" in css
        assert "min-height: 44px" in css
        assert "visibility: hidden" in css
        assert ".btn-back-to-top.visible" in css
        assert "prefers-reduced-motion" in css

    def test_mobile_breakpoint_optimizations(self) -> None:
        css = STYLES_CSS.read_text(encoding="utf-8")
        assert "@media (max-width: 640px)" in css
        assert "env(safe-area-inset-bottom, 1rem)" in css


class TestBackToTopScripts:
    """Tests for Back to Top JavaScript behavior and initialization."""

    def test_app_js_implements_init_back_to_top(self) -> None:
        js = APP_JS.read_text(encoding="utf-8")
        assert "function initBackToTop()" in js
        assert "initBackToTop();" in js
        assert "IntersectionObserver" in js
        assert "prefers-reduced-motion" in js
        assert "window.scrollTo" in js

    def test_sources_js_implements_init_back_to_top(self) -> None:
        js = SOURCES_JS.read_text(encoding="utf-8")
        assert "function initBackToTop()" in js
        assert "initBackToTop();" in js
        assert "IntersectionObserver" in js
        assert "prefers-reduced-motion" in js
        assert "window.scrollTo" in js

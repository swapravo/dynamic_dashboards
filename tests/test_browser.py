"""Playwright smoke test: dashboards built through the tool path render, and live edits appear
in an open /dynamic page without reloading. Screenshots go to docs/screenshots/."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser


def _chromium_available() -> bool:
    try:
        with playwright.sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def chromium() -> None:
    if not _chromium_available():
        pytest.skip("Chromium not installed: run `uv run playwright install chromium`")


def test_screenshots_and_live_update(chromium: None, state_db: Path) -> None:
    import screenshots  # type: ignore[import-not-found]

    from hearthly import tools

    screenshots.build_sample_dashboards()
    with screenshots.web_server(dict(os.environ)) as url:
        shots, errors = screenshots.capture(url, ROOT / "docs" / "screenshots")
        assert len(shots) >= 6 and all(s.stat().st_size > 20_000 for s in shots)
        assert errors == [], errors

        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport=screenshots.VIEWPORT)
            page.goto(f"{url}/dynamic#coo-overview")
            page.wait_for_selector(".panel[data-panel='net-revenue'] .kpi-value")
            page.wait_for_selector("#live-status.live")
            n_feed = page.locator(".feed-item").count()

            # Claude (here: the same tool code) adds a panel while the page is open
            tools.add_panel("coo-overview", {
                "id": "tickets-by-category", "type": "bar", "title": "Tickets by category (30 days)",
                "sql": "SELECT category, COUNT(*) AS tickets FROM support_tickets "
                       "WHERE created_at > date((SELECT MAX(order_date) FROM orders), '-30 day') "
                       "GROUP BY category ORDER BY tickets DESC",
                "encoding": {"x": "category", "y": "tickets"}, "insight": "Where support load comes from."})
            page.wait_for_selector(".panel[data-panel='tickets-by-category'] canvas", timeout=10_000)
            page.wait_for_function(f"document.querySelectorAll('.feed-item').length > {n_feed}", timeout=10_000)
            assert "add_panel" in page.locator(".feed-item").first.inner_text()

            # a new dashboard: the workspace follows Claude to it
            tools.create_dashboard({"id": "follow-me", "title": "Follow me", "panels": [
                {"id": "orders", "type": "kpi", "title": "Orders", "sql": "SELECT COUNT(*) AS n FROM orders",
                 "encoding": {"value": "n"}, "insight": "All time."},
                {"id": "untrusted", "type": "table", "title": "Untrusted values",
                 "sql": "SELECT '<img src=x onerror=\"window.__pwned=1\">' AS label, 1 AS v", "insight": "x"},
                {"id": "untrusted-bar", "type": "bar", "title": "<b>bold?</b>",
                 "sql": "SELECT '<script>window.__pwned=2</script>' AS label, 1 AS v",
                 "encoding": {"x": "label", "y": "v"}, "insight": "<i>insight</i>"}]})
            page.wait_for_function("document.getElementById('dash-title').textContent === 'Follow me'", timeout=10_000)
            page.wait_for_selector(".panel[data-panel='untrusted'] td")
            page.wait_for_timeout(500)

            # text from the database (and from specs) is rendered as text, never as HTML
            assert page.evaluate("window.__pwned") is None
            assert page.locator(".panel img, .panel script, .panel b, .panel i").count() == 0
            assert "<img" in page.inner_text(".panel[data-panel='untrusted'] td")
            browser.close()

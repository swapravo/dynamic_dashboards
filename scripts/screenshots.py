"""Build sample dashboards through the tool path, start the web app, and screenshot every page.

    uv run python scripts/screenshots.py                 # → docs/screenshots/*.png (uses a scratch state.db)

Needs `uv run playwright install chromium` once.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

VIEWPORT = {"width": 1920, "height": 1080}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def web_server(env: dict[str, str]) -> Iterator[str]:
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "hearthly.web.app:app", "--host", "127.0.0.1",
                             "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{url}/api/meta", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("web app did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def capture(base_url: str, out_dir: Path) -> tuple[list[Path], list[str]]:
    """Screenshot the pages. Returns (files, console errors)."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []
    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ("light", "dark"):
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            ctx.add_init_script(f"localStorage.setItem('hearthly-theme', '{theme}'); "
                                "localStorage.setItem('hearthly-present', '0');")
            page = ctx.new_page()
            # navigating away aborts the open SSE stream; that is expected, not a page error
            benign = ("ERR_NETWORK_IO_SUSPENDED", "ERR_ABORTED")
            page.on("console", lambda m: errors.append(f"{m.type}: {m.text}")
                    if m.type == "error" and not any(b in m.text for b in benign) else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            suffix = "" if theme == "light" else "-dark"
            for name, path, wait in (("evolution", "/", ".timeline"), ("static", "/static", ".panel .kpi-value"),
                                     ("dynamic", "/dynamic#coo-overview", ".panel .kpi-value")):
                if theme == "dark" and name == "evolution":
                    continue
                page.goto(base_url + path)
                page.wait_for_selector(wait, timeout=15000)
                page.wait_for_timeout(1400)  # let entry animations settle
                f = out_dir / f"{name}{suffix}.png"
                page.screenshot(path=str(f))
                shots.append(f)
            if theme == "light":
                page.goto(base_url + "/dynamic#refunddesk-agent")
                page.wait_for_selector(".panel .kpi-value", timeout=15000)
                page.wait_for_timeout(1400)
                f = out_dir / "dynamic-agent.png"
                page.screenshot(path=str(f))
                shots.append(f)
                page.keyboard.press("p")
                page.wait_for_timeout(1200)
                f = out_dir / "dynamic-present.png"
                page.screenshot(path=str(f))
                shots.append(f)
                page.keyboard.press("p")
                page.goto(base_url + "/dynamic#coo-overview")
                page.wait_for_selector(".panel .kpi-value", timeout=15000)
                page.wait_for_timeout(1000)
                page.click(".panel[data-panel='on-time-by-courier'] button[aria-label='View SQL']")
                page.wait_for_timeout(300)
                f = out_dir / "dynamic-sql.png"
                page.screenshot(path=str(f))
                shots.append(f)
            ctx.close()
        browser.close()
    return shots, errors


def build_sample_dashboards() -> None:
    import demo_dashboard  # type: ignore[import-not-found]

    demo_dashboard.agent_dashboard(0)
    demo_dashboard.coo_dashboard(0)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HEARTHLY_STATE_DB": str(Path(tmp) / "state.db")}
        os.environ.update(env)
        build_sample_dashboards()
        with web_server(env) as url:
            shots, errors = capture(url, ROOT / "docs" / "screenshots")
    for s in shots:
        print(s.relative_to(ROOT))
    if errors:
        print("Browser console errors:", *errors, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

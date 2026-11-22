#!/usr/bin/env bash
# Hearthly Live task runner.  Usage: ./run.sh [setup|seed|web|mcp|mcp-http|demo|reset|test|screenshots|config|all]
set -euo pipefail
cd "$(dirname "$0")"

need_uv() {
  command -v uv >/dev/null 2>&1 || { echo "uv is required: https://docs.astral.sh/uv/ (brew install uv)"; exit 1; }
}

cmd="${1:-all}"
case "$cmd" in
  setup)
    need_uv
    uv sync
    uv run playwright install chromium || echo "(Playwright browser download failed; only the screenshot tests need it)"
    ;;
  seed)
    uv run python -m hearthly.seed --reset
    ;;
  web)
    [ -f data/hearthly.db ] || uv run python -m hearthly.seed --reset
    echo "Hearthly Live → http://127.0.0.1:8000"
    uv run uvicorn hearthly.web.app:app --host 127.0.0.1 --port 8000
    ;;
  mcp)
    exec uv run python -m hearthly.mcp_server
    ;;
  mcp-http)
    exec uv run python -m hearthly.mcp_server --http
    ;;
  demo)
    uv run python scripts/demo_dashboard.py
    ;;
  reset)
    uv run python -m hearthly.state --reset
    ;;
  test)
    uv run pytest "${@:2}"
    ;;
  screenshots)
    uv run python scripts/screenshots.py
    ;;
  config)
    uv run python -m hearthly.print_config
    ;;
  all)
    need_uv
    [ -d .venv ] || "$0" setup
    [ -f data/hearthly.db ] || "$0" seed
    "$0" web
    ;;
  *)
    echo "usage: ./run.sh [setup|seed|web|mcp|mcp-http|demo|reset|test|screenshots|config|all]"; exit 2
    ;;
esac

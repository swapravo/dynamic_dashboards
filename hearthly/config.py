"""Filesystem locations and runtime settings. Override with environment variables in tests."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return Path(os.environ.get("HEARTHLY_DATA_DIR", PROJECT_ROOT / "data"))


def business_db_path() -> Path:
    return Path(os.environ.get("HEARTHLY_DB", data_dir() / "hearthly.db"))


def state_db_path() -> Path:
    return Path(os.environ.get("HEARTHLY_STATE_DB", data_dir() / "state.db"))


def metrics_path() -> Path:
    return Path(os.environ.get("HEARTHLY_METRICS", PROJECT_ROOT / "metrics.yaml"))


WEB_HOST = "127.0.0.1"
WEB_PORT = int(os.environ.get("HEARTHLY_WEB_PORT", "8000"))
MCP_HTTP_HOST = "127.0.0.1"
MCP_HTTP_PORT = int(os.environ.get("HEARTHLY_MCP_PORT", "8765"))

QUERY_TIMEOUT_SECONDS = 5.0
MAX_QUERY_ROWS = 1000
MAX_PANEL_ROWS = 5000

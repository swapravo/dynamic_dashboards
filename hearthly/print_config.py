"""Print ready-to-paste MCP client configuration with absolute paths for this machine.

    python -m hearthly.print_config            # Claude Desktop JSON + Claude Code commands
    python -m hearthly.print_config --json     # only the Claude Desktop JSON
"""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import shutil
import sys
from pathlib import Path

from . import config

SERVER_NAME = "hearthly"


def venv_python() -> Path:
    """The interpreter of the project's virtualenv (the one running this, if it is inside the project)."""
    candidates = [config.PROJECT_ROOT / ".venv" / "bin" / "python",
                  config.PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"]
    for c in candidates:
        if c.exists():
            return c
    return Path(sys.executable)


def desktop_config() -> dict:
    return {"mcpServers": {SERVER_NAME: {"command": str(venv_python()), "args": ["-m", "hearthly.mcp_server"]}}}


def desktop_config_path() -> str:
    system = platform.system()
    if system == "Darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    if system == "Windows":
        return r"%APPDATA%\Claude\claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


def claude_code_command() -> str:
    return (f"claude mcp add --transport stdio {SERVER_NAME} -- "
            f"{shlex.quote(str(venv_python()))} -m hearthly.mcp_server")


def claude_code_http_command() -> str:
    return f"claude mcp add --transport http {SERVER_NAME} http://{config.MCP_HTTP_HOST}:{config.MCP_HTTP_PORT}/mcp"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hearthly.print_config", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print only the Claude Desktop JSON")
    args = parser.parse_args(argv)
    cfg = json.dumps(desktop_config(), indent=2)
    if args.json:
        print(cfg)
        return 0
    uv = shutil.which("uv") or "/ABSOLUTE/PATH/TO/uv"
    print(f"""# Claude Desktop
# Edit {desktop_config_path()}
# (Claude Desktop → Settings → Developer → Edit Config). Merge this into "mcpServers",
# save, then fully quit and reopen Claude Desktop.

{cfg}

# Alternative using uv instead of the venv interpreter:
{json.dumps({"mcpServers": {SERVER_NAME: {"command": uv, "args": ["--directory", str(config.PROJECT_ROOT), "run", "python", "-m", "hearthly.mcp_server"]}}}, indent=2)}

# Claude Code (stdio, current project scope; add --scope user to use it everywhere)
{claude_code_command()}

# Claude Code over streamable HTTP (start the server first: ./run.sh mcp-http)
{claude_code_http_command()}
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

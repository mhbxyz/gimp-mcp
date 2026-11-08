"""Issue #40: `gimp-mcp setup` from the installed package, against a real GIMP (temporary HOME)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from gimp_mcp import platforms
from gimp_mcp.headless import HeadlessGimp, find_gimp_console

from .dist_helpers import install_distribution


async def test_setup_installs_configures_and_verifies(tmp_path: Path):
    if find_gimp_console() is None:
        pytest.skip("gimp-console not found")
    # a space and a non-ASCII letter in every path: venv, executable and the configuration it is written to
    spaced = tmp_path / "Program Fïles"
    spaced.mkdir()
    installed = install_distribution(spaced)
    # Claude Desktop is "installed" (its configuration folder exists where this OS keeps it)
    (Path(platforms.config_home(installed.env)) / "Claude").mkdir(parents=True)
    (installed.home / ".cursor").mkdir()  # Cursor too
    gimp = HeadlessGimp(install_plugin=False)
    socket = str(gimp.socket_path)
    installed.env["GIMP_MCP_TOKEN_FILE"] = str(gimp.token_path)  # a pipe's token is not next to it
    common = ["setup", "--yes", "--gimp-dir", str(gimp.config_dir), "--socket", socket,
              "--clients", "claude-desktop,cursor"]  # fmt: skip
    try:
        first = installed.gimp_mcp(*common, "--no-doctor")  # GIMP not running yet
        assert first.returncode == 0, first.stderr
        assert "installed in" in first.stderr and "restart GIMP" in first.stderr
        claude = Path(platforms.config_home(installed.env)) / "Claude"
        desktop = json.loads((claude / "claude_desktop_config.json").read_text(encoding="utf-8"))
        entry = desktop["mcpServers"]["gimp"]
        assert entry["command"] == str(installed.exe) and entry["args"] == ["serve"]
        assert json.loads((installed.home / ".cursor/mcp.json").read_text())["mcpServers"]["gimp"] == entry

        gimp.start()
        second = installed.gimp_mcp(*common)  # with the doctor this time
        assert second.returncode == 0, second.stderr
        assert "up to date" in second.stderr and second.stderr.count("already configured") == 2
        assert "answers" in second.stderr and "0 failure(s)" in second.stderr

        # the configuration written for Claude Desktop really starts a working server
        assert " " in entry["command"] and "ï" in entry["command"]
        params = StdioServerParameters(
            command=entry["command"], args=entry["args"], env={**installed.env, "GIMP_MCP_SOCKET": socket}
        )
        async with Client(params, read_timeout_seconds=60) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            status = await client.call_tool("gimp_status", {})
        assert {"gimp_status", "gimp_create_image", "gimp_export_image", "gimp_list_toolsets"} <= tools
        assert not status.is_error and status.structured_content is not None
    finally:
        gimp.stop()

"""Issue #35: a real MCP client sees a clear error when the installed plug-in is older."""

from __future__ import annotations

import subprocess
import sys

import gimp_mcp
from gimp_mcp.headless import HeadlessGimp, find_gimp_console
from gimp_mcp.installer import install_plugin

from .conftest import mcp_client


async def test_older_plugin_is_reported_with_the_fix(tmp_path):
    gimp = HeadlessGimp(console=find_gimp_console(), install_plugin=False)
    try:
        gimp.config_dir.mkdir(parents=True)
        (install_plugin(gimp.config_dir) / "VERSION").write_text("0.0.1\n")  # simulate an old installation
        gimp.start()
        async with mcp_client(gimp) as client:
            result = await client.call_tool("gimp_status", {})
        doctor = subprocess.run(
            [sys.executable, "-m", "gimp_mcp", "doctor", "--socket", str(gimp.socket_path),
             "--gimp-dir", str(gimp.config_dir)],
            capture_output=True, text=True, timeout=60,
        )  # fmt: skip
    finally:
        gimp.stop()
    assert result.is_error and result.structured_content is not None
    error = result.structured_content["error"]
    assert error["code"] == "PLUGIN_VERSION_MISMATCH"
    assert "gimp-mcp install-plugin" in error["hint"]
    assert error["details"] == {"plugin_version": "0.0.1", "server_version": gimp_mcp.__version__}
    assert doctor.returncode == 1
    assert "0.0.1" in doctor.stderr and gimp_mcp.__version__ in doctor.stderr and "incompatible" in doctor.stderr


async def test_status_reports_both_versions(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        result = await client.call_tool("gimp_status", {})
    assert result.structured_content is not None
    assert result.structured_content["server_version"] == gimp_mcp.__version__
    assert result.structured_content["plugin_version"] == gimp_mcp.__version__

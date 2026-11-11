"""Plug-in / server compatibility on a real GIMP (#35, #120, ADR 0010)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import gimp_mcp
from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.errors import GimpMcpError
from gimp_mcp.headless import HeadlessGimp, find_gimp_console
from gimp_mcp.installer import PLUGIN_NAME, install_plugin

from .conftest import mcp_client
from .dist_helpers import ROOT
from .test_upgrade import previous_release_ref


def doctor(gimp: HeadlessGimp) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "gimp_mcp", "doctor", "--socket", str(gimp.socket_path),
         "--gimp-dir", str(gimp.config_dir)],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "GIMP_MCP_TOKEN_FILE": str(gimp.token_path)},  # a pipe's token is not next to it
    )  # fmt: skip


async def test_a_plugin_with_another_version_number_keeps_working():
    gimp = HeadlessGimp(console=find_gimp_console(), install_plugin=False)
    try:
        gimp.config_dir.mkdir(parents=True)
        (install_plugin(gimp.config_dir) / "VERSION").write_text("0.0.1\n")  # same code, another version
        gimp.start()
        async with mcp_client(gimp) as client:
            status = await client.call_tool("gimp_status", {})
            created = await client.call_tool("gimp_create_image", {"width": 8, "height": 8})
        report = doctor(gimp)
    finally:
        gimp.stop()
    assert status.structured_content is not None and not status.is_error
    assert status.structured_content["plugin_version"] == "0.0.1"
    assert status.structured_content["plugin_compatibility"] == "compatible"
    assert not created.is_error, created.content
    assert "0.0.1" in report.stderr and "protocol 1: compatible" in report.stderr


async def test_the_previous_release_plugin_serves_this_server(tmp_path: Path):
    """An old plug-in (no capability list) with the new server: tools work, an operation it does not
    know fails with PLUGIN_VERSION_MISMATCH and the update hint."""
    ref = previous_release_ref()
    if ref is None or not ref.startswith("v"):
        pytest.skip("git tags are needed to fetch the previous release's plug-in")
    old_version = ref.removeprefix("v")
    archive = subprocess.run(
        ["git", "archive", ref, f"src/gimp_mcp/plugin/{PLUGIN_NAME}"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    source = tmp_path / "previous"
    source.mkdir()
    subprocess.run(["tar", "-x", "-C", str(source)], input=archive, check=True)
    gimp = HeadlessGimp(console=find_gimp_console(), install_plugin=False)
    try:
        target = gimp.config_dir / "plug-ins" / PLUGIN_NAME
        shutil.copytree(source / "src" / "gimp_mcp" / "plugin" / PLUGIN_NAME, target)
        (target / "VERSION").write_text(old_version + "\n")
        (target / f"{PLUGIN_NAME}.py").chmod(0o755)
        gimp.start()
        async with mcp_client(gimp) as client:
            status = await client.call_tool("gimp_status", {})
            created = await client.call_tool("gimp_create_image", {"width": 8, "height": 8})
        bridge = BridgeClient(BridgeEndpoint(socket_path=gimp.socket_path, token_path=gimp.token_path))
        try:
            with pytest.raises(GimpMcpError) as excinfo:
                await bridge.call("operation.from_the_future", {})
        finally:
            await bridge.close()
        report = doctor(gimp)
    finally:
        gimp.stop()
    assert status.structured_content is not None and not status.is_error, status.content
    assert status.structured_content["plugin_version"] == old_version
    assert status.structured_content["plugin_compatibility"] == "partial"
    assert not created.is_error, created.content
    error = excinfo.value
    assert error.code == "PLUGIN_VERSION_MISMATCH" and "gimp-mcp install-plugin" in (error.hint or "")
    assert error.details["plugin_version"] == old_version
    assert "partial" in report.stderr and "gimp-mcp install-plugin" in report.stderr


async def test_status_reports_both_versions(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        result = await client.call_tool("gimp_status", {})
    assert result.structured_content is not None
    assert result.structured_content["server_version"] == gimp_mcp.__version__
    assert result.structured_content["plugin_version"] == gimp_mcp.__version__
    assert result.structured_content["plugin_compatibility"] == "match"

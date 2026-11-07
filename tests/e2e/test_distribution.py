"""Issue #17: the *distributed* package works end to end, outside the source tree."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from PIL import Image

import gimp_mcp
from gimp_mcp.headless import HeadlessGimp, find_gimp_console

from .dist_helpers import REQUIREMENT, ROOT, install_distribution, run


async def test_installed_wheel_installs_the_plugin_and_serves_mcp(tmp_path: Path):
    if find_gimp_console() is None:
        pytest.skip("gimp-console not found")
    installed = install_distribution(tmp_path)
    venv, exe, work, env = installed.venv, installed.exe, installed.work, installed.env
    expected = os.environ.get("GIMP_MCP_DIST_VERSION", gimp_mcp.__version__)

    version = run(str(exe), "--version", cwd=work, env=env)
    assert version.stdout.strip() == f"gimp-mcp {expected}"
    if REQUIREMENT:  # installed from an index: `uvx` must work too
        uvx = run("uvx", "--from", REQUIREMENT, "gimp-mcp", "--version", cwd=work, env=env)
        assert uvx.stdout.strip() == f"gimp-mcp {expected}", uvx.stderr
    location = run(str(venv / "bin" / "python"), "-c", "import gimp_mcp; print(gimp_mcp.__file__)", cwd=work, env=env)
    assert str(venv) in location.stdout and str(ROOT) not in location.stdout  # not the source tree

    gimp = HeadlessGimp(install_plugin=False)
    try:
        gimp.config_dir.mkdir(parents=True)
        plugin = run(str(exe), "install-plugin", "--gimp-dir", str(gimp.config_dir), cwd=work, env=env)
        assert plugin.returncode == 0, plugin.stderr
        assert (gimp.config_dir / "plug-ins" / "gimp-mcp-bridge" / "gimp-mcp-bridge.py").exists()
        gimp.start()
        doctor = run(
            str(exe), "doctor", "--socket", str(gimp.socket_path), "--gimp-dir", str(gimp.config_dir), cwd=work, env=env
        )
        assert doctor.returncode == 0, doctor.stderr
        assert "0 failure(s)" in doctor.stderr and "answers" in doctor.stderr

        out = work / "smoke.png"
        params = StdioServerParameters(
            command=str(exe), args=["serve"], env={**env, "GIMP_MCP_SOCKET": str(gimp.socket_path)}, cwd=str(work)
        )
        async with Client(params, read_timeout_seconds=120) as client:
            status = await client.call_tool("gimp_status", {})
            created = await client.call_tool("gimp_create_image", {"width": 32, "height": 16, "fill": "#00ff00"})
            assert created.structured_content is not None
            exported = await client.call_tool(
                "gimp_export_image", {"image": created.structured_content["id"], "path": str(out)}
            )
        assert not status.is_error and not exported.is_error, exported.content
        with Image.open(out) as png:
            assert png.size == (32, 16) and png.convert("RGB").getpixel((3, 3)) == (0, 255, 0)
        removed = run(str(exe), "uninstall-plugin", "--gimp-dir", str(gimp.config_dir), cwd=work, env=env)
        assert removed.returncode == 0
        assert not (gimp.config_dir / "plug-ins" / "gimp-mcp-bridge").exists()
    finally:
        gimp.stop()

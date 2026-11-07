"""Issue #17: the *distributed* package works end to end, outside the source tree."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from PIL import Image

import gimp_mcp
from gimp_mcp.headless import HeadlessGimp, find_gimp_console, system_path

ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


async def test_installed_wheel_installs_the_plugin_and_serves_mcp(tmp_path: Path):
    if shutil.which("uv") is None:
        pytest.skip("uv is needed to build and install the distribution")
    if find_gimp_console() is None:
        pytest.skip("gimp-console not found")
    dist, work = tmp_path / "dist", tmp_path / "work"
    work.mkdir()
    assert run("uv", "build", "--quiet", "--wheel", "--out-dir", str(dist), cwd=ROOT).returncode == 0
    wheel = next(dist.glob("*.whl"))
    venv = tmp_path / "venv"
    assert run("uv", "venv", "--quiet", "--python", sys.executable, str(venv), cwd=work).returncode == 0
    installed = run("uv", "pip", "install", "--quiet", "--python", str(venv / "bin" / "python"), str(wheel), cwd=work)
    assert installed.returncode == 0, installed.stderr
    exe = venv / "bin" / "gimp-mcp"
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env["PATH"] = system_path(env.get("PATH", ""))

    version = run(str(exe), "--version", cwd=work, env=env)
    assert version.stdout.strip() == f"gimp-mcp {gimp_mcp.__version__}"
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
        assert "connected to GIMP" in doctor.stderr

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

"""Issue #42: upgrade from the previous release and uninstall, from the installed packages."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

import gimp_mcp
from gimp_mcp import platforms
from gimp_mcp.headless import HeadlessGimp, find_gimp_console

from .dist_helpers import ROOT, install_distribution, run, venv_python, venv_script


def previous_release_ref() -> str | None:
    """The latest v* tag older than this version, else the 0.1.0 release commit."""

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    if not (ROOT / ".git").exists():
        return None
    tags = [t for t in git("tag", "--list", "v*", "--sort=-v:refname").splitlines() if t != f"v{gimp_mcp.__version__}"]
    if tags:
        return tags[0]
    return git("log", "--grep", "first usable release (0.1.0)", "-1", "--format=%H") or None


def build_previous_wheel(tmp_path: Path) -> Path:
    ref = previous_release_ref()
    if ref is None:
        pytest.skip("git history is needed to build the previous release")
    source = tmp_path / "previous-src"
    source.mkdir()
    archive = subprocess.run(["git", "archive", ref], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(source)], input=archive, check=True)
    dist = tmp_path / "previous-dist"
    assert run("uv", "build", "--quiet", "--wheel", "--out-dir", str(dist), cwd=source).returncode == 0
    return next(dist.glob("*.whl"))


async def test_upgrade_from_the_previous_release_then_uninstall(tmp_path: Path):
    if find_gimp_console() is None:
        pytest.skip("gimp-console not found")
    previous = build_previous_wheel(tmp_path)
    installed = install_distribution(tmp_path)  # the new version, in its own venv
    old_venv = tmp_path / "old-venv"
    assert run("uv", "venv", "--quiet", str(old_venv), cwd=installed.work).returncode == 0
    assert run("uv", "pip", "install", "--quiet", "--python", str(venv_python(old_venv)), str(previous),
               cwd=installed.work, env=installed.env).returncode == 0  # fmt: skip
    claude = Path(platforms.config_home(installed.env)) / "Claude"  # this OS's location
    claude.mkdir(parents=True)
    gimp = HeadlessGimp(install_plugin=False)
    try:
        gimp.config_dir.mkdir(parents=True)
        old = run(str(venv_script(old_venv, "gimp-mcp")), "install-plugin", "--gimp-dir", str(gimp.config_dir),
                  cwd=installed.work, env=installed.env)  # fmt: skip
        assert old.returncode == 0, old.stderr
        plugin = gimp.config_dir / "plug-ins" / "gimp-mcp-bridge"
        old_version = (plugin / "VERSION").read_text().strip() if (plugin / "VERSION").exists() else None
        assert old_version != gimp_mcp.__version__

        upgrade = installed.gimp_mcp("setup", "--yes", "--gimp-dir", str(gimp.config_dir), "--socket",
                                     str(gimp.socket_path), "--clients", "claude-desktop", "--no-doctor")  # fmt: skip
        assert upgrade.returncode == 0, upgrade.stderr
        assert "updated from" in upgrade.stderr and "restart GIMP" in upgrade.stderr
        assert (plugin / "VERSION").read_text().strip() == gimp_mcp.__version__

        gimp.start()
        params = StdioServerParameters(
            command=str(installed.exe),
            args=["serve"],
            env={
                **installed.env,
                "GIMP_MCP_SOCKET": str(gimp.socket_path),
                "GIMP_MCP_TOKEN_FILE": str(gimp.token_path),
            },
        )
        async with Client(params, read_timeout_seconds=60) as client:
            status = await client.call_tool("gimp_status", {})
        assert status.structured_content is not None
        assert status.structured_content["plugin_version"] == gimp_mcp.__version__

        removed = installed.gimp_mcp("uninstall", "--yes", "--gimp-dir", str(gimp.config_dir))
        assert removed.returncode == 0, removed.stderr
        assert not plugin.exists()
        desktop = json.loads((claude / "claude_desktop_config.json").read_text(encoding="utf-8"))
        assert "gimp" not in desktop["mcpServers"]
        assert "Left for you" in removed.stderr
    finally:
        gimp.stop()

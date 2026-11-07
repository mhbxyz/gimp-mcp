"""Upgrade every installed plug-in and uninstall everything gimp-mcp added (issue #42)."""

from __future__ import annotations

import json
from pathlib import Path

import gimp_mcp
from gimp_mcp.installer import install_plugin
from gimp_mcp.setup import run_setup, run_uninstall

from .test_setup import make_world, options


def profile(world, series: str) -> Path:
    return world.home / ".config" / "GIMP" / series


def plugin(world, series: str) -> Path:
    return profile(world, series) / "plug-ins" / "gimp-mcp-bridge"


async def test_setup_updates_the_plugin_in_every_profile_where_it_is_installed(tmp_path):
    world = make_world(tmp_path)
    for series in ("3.2", "3.0"):
        install_plugin(profile(world, series))
        (plugin(world, series) / "VERSION").write_text("0.0.1\n")
    await run_setup(options(world))
    for series in ("3.2", "3.0"):
        assert (plugin(world, series) / "VERSION").read_text().strip() == gimp_mcp.__version__
    assert world.text.count("updated from 0.0.1") == 2 and "restart GIMP" in world.text


async def test_a_plugin_without_version_file_is_treated_as_older(tmp_path):
    world = make_world(tmp_path)
    install_plugin(profile(world, "3.2"))
    (plugin(world, "3.2") / "VERSION").unlink()  # 0.1.0 did not write one
    await run_setup(options(world))
    assert "updated from an older version" in world.text


async def test_uninstall_removes_plugins_and_our_client_entries_only(tmp_path):
    world = make_world(tmp_path, clients=("claude-desktop", "cursor"))
    for series in ("3.2", "3.0"):
        install_plugin(profile(world, series))
    desktop = world.home / ".config" / "Claude" / "claude_desktop_config.json"
    desktop.write_text(json.dumps({"mcpServers": {
        "gimp": {"command": "/opt/gimp-mcp/bin/gimp-mcp", "args": ["serve"]},
        "other": {"command": "x"},
    }}))  # fmt: skip
    cursor = world.home / ".cursor" / "mcp.json"
    cursor.write_text(json.dumps({"mcpServers": {"gimp": {"command": "docker", "args": ["run", "someone/gimp"]}}}))
    code = await run_uninstall(options(world, assume_yes=True, interactive=False))
    assert code == 0
    assert not plugin(world, "3.2").exists() and not plugin(world, "3.0").exists()
    assert profile(world, "3.2").exists()  # the GIMP profile itself is untouched
    assert json.loads(desktop.read_text())["mcpServers"] == {"other": {"command": "x"}}
    assert list(desktop.parent.glob("claude_desktop_config.json.bak-*"))
    assert "gimp" in json.loads(cursor.read_text())["mcpServers"]  # not ours: kept
    assert "not created by gimp-mcp" in world.text
    assert "uv tool uninstall gimp-mcp" in world.text  # what the user must still do


async def test_uninstall_asks_before_each_removal(tmp_path):
    world = make_world(tmp_path, clients=("claude-desktop",))
    install_plugin(profile(world, "3.2"))
    desktop = world.home / ".config" / "Claude" / "claude_desktop_config.json"
    desktop.write_text(json.dumps({"mcpServers": {"gimp": {"command": "/x/gimp-mcp", "args": ["serve"]}}}))
    world.answers = ["n", "n"]
    await run_uninstall(options(world))
    assert plugin(world, "3.2").exists()
    assert "gimp" in json.loads(desktop.read_text())["mcpServers"]


async def test_uninstall_removes_the_claude_code_entry_through_its_cli(tmp_path):
    world = make_world(tmp_path, clients=("claude",), claude_has_gimp=True)
    await run_uninstall(options(world, assume_yes=True, interactive=False))
    assert any(call.endswith("claude mcp remove gimp --scope user") for call in world.calls()), world.calls()


async def test_uninstall_with_nothing_installed_says_so(tmp_path):
    world = make_world(tmp_path)
    code = await run_uninstall(options(world, assume_yes=True, interactive=False))
    assert code == 0 and "nothing to remove" in world.text.lower()

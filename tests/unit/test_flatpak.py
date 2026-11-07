"""Flatpak GIMP (org.gimp.GIMP): socket location, detection by doctor and setup (#41)."""

from __future__ import annotations

from pathlib import Path

import gmb_server  # type: ignore[import-not-found]

from gimp_mcp.bridge import BridgeEndpoint, default_socket_path
from gimp_mcp.doctor import Status, run_checks
from gimp_mcp.setup import run_setup

from .test_doctor import FakeProbe
from .test_setup import make_world, options


def test_inside_flatpak_the_plugin_uses_the_app_runtime_dir_shared_with_the_host(tmp_path):
    env = {"FLATPAK_ID": "org.gimp.GIMP", "XDG_RUNTIME_DIR": str(tmp_path)}
    assert gmb_server.default_socket_path(env) == str(tmp_path / "app" / "org.gimp.GIMP" / "gimp-mcp" / "bridge.sock")


def test_explicit_socket_still_wins_inside_flatpak(tmp_path):
    env = {"FLATPAK_ID": "org.gimp.GIMP", "XDG_RUNTIME_DIR": str(tmp_path), "GIMP_MCP_SOCKET": "/x.sock"}
    assert gmb_server.default_socket_path(env) == "/x.sock"


def test_the_host_server_finds_a_flatpak_bridge(tmp_path):
    env = {"XDG_RUNTIME_DIR": str(tmp_path)}
    native = tmp_path / "gimp-mcp" / "bridge.sock"
    flatpak = tmp_path / "app" / "org.gimp.GIMP" / "gimp-mcp" / "bridge.sock"
    assert default_socket_path(env) == native  # nothing running: the native location
    flatpak.parent.mkdir(parents=True)
    flatpak.touch()
    assert default_socket_path(env) == flatpak
    native.parent.mkdir(parents=True)
    native.touch()
    assert default_socket_path(env) == native  # both: the native one


FLATPAK_INFO = (
    "GIMP - GNU Image Manipulation Program\n\n          ID: org.gimp.GIMP\n"
    "         Ref: app/org.gimp.GIMP/x86_64/stable\n"
    "     Version: 3.2.8\n     Runtime: org.gnome.Platform/x86_64/51\n"
)


async def test_doctor_recognises_flatpak_gimp(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "GIMP" / "3.2").mkdir(parents=True)
    probe = FakeProbe(
        env={"HOME": str(home), "PATH": "/usr/bin"},
        endpoint=BridgeEndpoint.for_socket(tmp_path / "none.sock"),
        executables={"flatpak": "/usr/bin/flatpak"},
        outputs={"flatpak info org.gimp.GIMP": (0, FLATPAK_INFO), "import gi": (0, "ok")},
    )
    results = {r.id: r for r in await run_checks(probe)}
    assert results["gimp"].status is Status.OK and "Flatpak" in results["gimp"].message
    assert "3.2.8" in results["gimp"].message
    assert results["gimp-python"].status is Status.OK  # Flatpak GIMP brings its own Python and PyGObject


async def test_setup_installs_the_plugin_for_flatpak_gimp(tmp_path):
    world = make_world(tmp_path)
    (world.bin / "gimp-console-3.2").unlink()
    flatpak = world.bin / "flatpak"
    flatpak.write_text(f"#!/bin/sh\nprintf '%s' '{FLATPAK_INFO}'\n")
    flatpak.chmod(0o755)
    world.env["PATH"] = str(world.bin)
    code = await run_setup(options(world))
    assert code == 0
    assert (world.home / ".config/GIMP/3.2/plug-ins/gimp-mcp-bridge/gimp-mcp-bridge.py").exists()
    assert "Flatpak" in world.text


def test_flatpak_socket_dir_is_reported_by_the_endpoint(tmp_path):
    flatpak = tmp_path / "app" / "org.gimp.GIMP" / "gimp-mcp" / "bridge.sock"
    flatpak.parent.mkdir(parents=True)
    flatpak.touch()
    endpoint = BridgeEndpoint.default({"XDG_RUNTIME_DIR": str(tmp_path)})
    assert endpoint.socket_path == flatpak and endpoint.token_path == Path(str(flatpak) + ".token")


async def test_setup_shows_the_flatpak_override_needed_for_a_custom_socket(tmp_path):
    world = make_world(tmp_path)
    (world.bin / "gimp-console-3.2").unlink()
    flatpak = world.bin / "flatpak"
    flatpak.write_text(f"#!/bin/sh\nprintf '%s' '{FLATPAK_INFO}'\n")
    flatpak.chmod(0o755)
    world.env["PATH"] = str(world.bin)
    world.env["GIMP_MCP_SOCKET"] = "/tmp/gimp-mcp/bridge.sock"
    await run_setup(options(world))
    assert "flatpak override --user --env=GIMP_MCP_SOCKET=/tmp/gimp-mcp/bridge.sock org.gimp.GIMP" in world.text
    assert not any("override" in call for call in world.calls())  # shown, never applied

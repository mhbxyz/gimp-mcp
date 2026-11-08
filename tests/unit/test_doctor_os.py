"""`gimp-mcp doctor` on Linux, macOS and Windows (#103): each OS's places, and fixes that work there.

Each test pins the platform layer to one OS and runs the checks against a FakeProbe and a temporary
home, so the three OSes are checked on every runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gimp_mcp import platforms
from gimp_mcp.bridge import BridgeEndpoint
from gimp_mcp.doctor import CHECKS, Status, fix_for, render_troubleshooting, run_checks
from gimp_mcp.installer import install_plugin

from .test_doctor import FakeProbe, by_id

KINDS = ("linux", "macos", "windows")
# commands and places that only exist on one OS
FOREIGN = {
    "linux": ("/Applications", "gimp.org installer", "%APPDATA%", ".exe"),
    "macos": ("pacman", "apt", "sudo", "%APPDATA%", ".exe", "~/.config"),
    "windows": ("pacman", "apt", "sudo", "chmod", "/Applications", "~/.config", "deactivate`)"),
}


@pytest.fixture(params=KINDS)
def kind(request, monkeypatch):
    monkeypatch.setattr(platforms, "CURRENT", request.param)
    return request.param


def world(tmp_path: Path, kind: str, *, gimp: bool = True, plugin: bool = True) -> FakeProbe:
    """A machine of this OS: GIMP where its installer puts it, the plug-in in the default profile."""
    home = tmp_path / "home"
    env = {"HOME": str(home), "PATH": str(tmp_path / "bin")}
    if kind == "windows":
        env |= {"USERPROFILE": str(home), "APPDATA": str(home / "Roaming"), "LOCALAPPDATA": str(home / "Local"),
                "ProgramFiles": str(tmp_path / "Program Files"), "HOME": str(tmp_path / "msys-home")}  # fmt: skip
    console = platforms.gimp_console_candidates(env, kind)[0]  # type: ignore[arg-type]
    profile = Path(platforms.gimp_profile_dir(env, kind))  # type: ignore[arg-type]
    profile.mkdir(parents=True)
    if plugin:
        install_plugin(profile)
    executables = {console: console} if gimp else {}
    return FakeProbe(
        env=env,
        endpoint=BridgeEndpoint.for_socket(tmp_path / "none.sock"),
        executables=executables,
        outputs={"--version": (0, "GNU Image Manipulation Program version 3.2.6"), "import gi": (0, "ok")},
    )


@pytest.mark.parametrize("check", [spec.id for spec in CHECKS])
def test_every_fix_is_written_for_the_os_it_is_shown_on(check, kind):
    fix = fix_for(check, kind)
    assert fix, check
    leaked = [word for word in FOREIGN[kind] if word in fix]
    assert leaked == [], (check, kind, fix)


async def test_a_missing_gimp_says_where_this_os_installs_it(tmp_path, kind):
    results = by_id(await run_checks(world(tmp_path, kind, gimp=False)))
    gimp = results["gimp"]
    assert gimp.status is Status.FAIL
    expected = {"linux": "distribution", "macos": "/Applications/GIMP.app", "windows": "GIMP_MCP_GIMP_CONSOLE"}
    assert expected[kind] in gimp.fix
    if kind != "linux":  # GIMP's Python cannot be checked without GIMP: not a second failure
        assert results["gimp-python"].status is Status.SKIP


async def test_the_plugin_is_found_in_this_os_default_profile(tmp_path, kind):
    results = by_id(await run_checks(world(tmp_path, kind)))
    for check in ("gimp", "gimp-python", "venv-path", "profiles", "plugin", "plugin-version"):
        assert results[check].status is Status.OK, (check, results[check].message)
    places = {"linux": ".config/GIMP/3.2", "macos": "Library/Application Support/GIMP/3.2", "windows": "Roaming"}
    assert places[kind] in results["plugin"].message.replace("\\", "/")


async def test_a_missing_plugin_is_explained_with_this_os_profile(tmp_path, kind):
    plugin = by_id(await run_checks(world(tmp_path, kind, plugin=False)))["plugin"]
    assert plugin.status is Status.FAIL and "gimp-mcp install-plugin" in plugin.fix
    assert not [word for word in FOREIGN[kind] if word in plugin.fix]


async def test_gimp_python_is_the_bundled_one_on_macos_and_windows(tmp_path, kind):
    probe = world(tmp_path, kind)
    probe.outputs["import gi"] = (1, "ModuleNotFoundError: No module named 'gi'")
    python = by_id(await run_checks(probe))["gimp-python"]
    assert python.status is Status.FAIL
    if kind == "linux":
        assert "python3" in python.message and "python3-gi" in python.fix
    else:
        bundled = {"macos": "python3", "windows": "python.exe"}[kind]
        assert "bundled" in python.message and bundled in python.message and "gimp.org" in python.fix


async def test_the_connection_names_the_bridge_this_os_uses(tmp_path, kind):
    probe = world(tmp_path, kind)
    if kind == "windows":
        probe.endpoint = BridgeEndpoint(Path(r"\\.\pipe\gimp-mcp-test-none"), tmp_path / "none.token")
    connection = by_id(await run_checks(probe))["connection"]
    assert connection.status is Status.FAIL and "not running" in connection.message
    assert ("pipe" if kind == "windows" else "socket") in connection.message


@pytest.mark.parametrize(
    ("kind", "output", "expected"),
    [
        ("macos", "  101 /Applications/GIMP.app/Contents/MacOS/gimp\n  102 /usr/bin/login\n"
                  "  103 /Applications/GIMP.app/Contents/MacOS/gimp-console-3.2\n"
                  "  104 /Applications/GIMP.app/Contents/Resources/lib/gimp/3.0/plug-ins/script-fu/script-fu\n",
         [(101, "gimp"), (103, "gimp-console-3.2")]),
        ("windows", '"gimp-3.2.exe","4242","Console","1","250,000 K"\r\n"explorer.exe","10","Console","1","9 K"\r\n'
                    '"gimp-console-3.2.exe","77","Console","1","1 K"\r\n"gimp-mcp.exe","5","Console","1","1 K"\r\n',
         [(4242, "gimp-3.2"), (77, "gimp-console-3.2")]),
    ],
)  # fmt: skip
def test_gimp_processes_are_read_from_the_os_process_list(kind, output, expected):
    assert platforms.parse_gimp_processes(output, kind) == expected


def test_troubleshooting_gives_each_os_its_fix():
    page = render_troubleshooting()
    for label in ("Linux:", "macOS:", "Windows:"):
        assert label in page
    assert "/Applications/GIMP.app" in page and "GIMP_MCP_GIMP_CONSOLE" in page


def test_the_doctor_cli_reports_instead_of_crashing_on_this_host(tmp_path):
    """The real CLI on the runner's own OS, with a socket-style address (GIMP_MCP_SOCKET may be any path)
    and no GIMP: failures are reported (exit 1), the doctor never stops on an OS-specific call (exit 2)."""
    import json
    import os
    import subprocess
    import sys

    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "APPDATA": str(tmp_path / "Roaming"),
           "LOCALAPPDATA": str(tmp_path / "Local"), "GIMP_MCP_SOCKET": str(tmp_path / "x.sock"),
           "GIMP_MCP_GIMP_CONSOLE": str(tmp_path / "no-gimp")}  # fmt: skip
    proc = subprocess.run([sys.executable, "-m", "gimp_mcp", "doctor", "--json"],
                          capture_output=True, text=True, env=env, timeout=60)  # fmt: skip
    assert proc.returncode == 1, proc.stderr
    checks = {check["id"]: check["status"] for check in json.loads(proc.stdout)["checks"]}
    assert checks["gimp"] == "fail" and checks["connection"] == "fail"

"""Per-OS locations (#98): one module answers them for Linux, macOS and Windows.

Expected paths are the documented locations of each OS (GIMP's profile and the clients' configuration
folders), checked on GitHub runners for GIMP 3.2.6 (docs/gimp-notes.md, ADR 0008).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from gimp_mcp import platforms
from gimp_mcp.platforms import OsKind
from gimp_mcp.plugin_modules import load

ROOT = Path(__file__).resolve().parents[2]
LINUX = {"HOME": "/home/ana"}
MACOS = {"HOME": "/Users/ana"}
WINDOWS = {
    "USERPROFILE": r"C:\Users\ana",
    "APPDATA": r"C:\Users\ana\AppData\Roaming",
    "LOCALAPPDATA": r"C:\Users\ana\AppData\Local",
    "USERNAME": "ana",
    "ProgramFiles": r"C:\Program Files",
}


@pytest.mark.parametrize(
    ("name", "kind"), [("linux", "linux"), ("darwin", "macos"), ("win32", "windows"), ("freebsd14", "linux")]
)
def test_os_kind(name, kind):
    assert platforms.os_kind(name) == kind


def test_gimp_profile_follows_each_os_and_gimp3_directory_wins():
    assert platforms.gimp_profile_dir(LINUX, "linux") == PurePosixPath("/home/ana/.config/GIMP/3.2")
    assert platforms.gimp_profile_dir({**LINUX, "XDG_CONFIG_HOME": "/cfg"}, "linux") == PurePosixPath("/cfg/GIMP/3.2")
    assert platforms.gimp_profile_dir(MACOS, "macos") == PurePosixPath(
        "/Users/ana/Library/Application Support/GIMP/3.2"
    )
    assert platforms.gimp_profile_dir(WINDOWS, "windows") == PureWindowsPath(r"C:\Users\ana\AppData\Roaming\GIMP\3.2")
    kinds: list[tuple[dict[str, str], OsKind]] = [(LINUX, "linux"), (MACOS, "macos"), (WINDOWS, "windows")]
    for env, kind in kinds:
        assert str(platforms.gimp_profile_dir({**env, "GIMP3_DIRECTORY": "/x/gimp"}, kind)).replace("\\", "/") == (
            "/x/gimp"
        )


def test_client_configuration_folders():
    assert platforms.config_home(LINUX, "linux") == PurePosixPath("/home/ana/.config")
    assert platforms.config_home({**LINUX, "XDG_CONFIG_HOME": "/cfg"}, "linux") == PurePosixPath("/cfg")
    assert platforms.config_home(MACOS, "macos") == PurePosixPath("/Users/ana/Library/Application Support")
    assert platforms.config_home(WINDOWS, "windows") == PureWindowsPath(r"C:\Users\ana\AppData\Roaming")


def test_bridge_address_per_os():
    linux = platforms.bridge_address(
        {**LINUX, "XDG_RUNTIME_DIR": "/run/user/1000"}, "linux", uid=1000, runtime_exists=lambda _p: True
    )
    assert linux == platforms.BridgeAddress(
        "unix", "/run/user/1000/gimp-mcp/bridge.sock", "/run/user/1000/gimp-mcp/bridge.sock.token"
    )
    fallback = platforms.bridge_address(LINUX, "linux", uid=1000)
    assert fallback.path == "/tmp/gimp-mcp-1000/bridge.sock"
    mac = platforms.bridge_address(MACOS, "macos", uid=501)
    assert mac.kind == "unix" and mac.path == "/Users/ana/Library/Application Support/gimp-mcp/bridge.sock"
    win = platforms.bridge_address(WINDOWS, "windows")
    assert win.kind == "pipe" and win.path == r"\\.\pipe\gimp-mcp-ana"
    assert win.token_path == r"C:\Users\ana\AppData\Local\gimp-mcp\bridge.token"
    override = platforms.bridge_address({**WINDOWS, "GIMP_MCP_SOCKET": r"\\.\pipe\mine"}, "windows")
    assert override.path == r"\\.\pipe\mine"


def test_flatpak_gimp_serves_under_its_app_directory():
    env = {**LINUX, "XDG_RUNTIME_DIR": "/run/user/1000", "FLATPAK_ID": "org.gimp.GIMP"}
    inside = platforms.bridge_address(env, "linux", uid=1000)
    assert inside.path == "/run/user/1000/app/org.gimp.GIMP/gimp-mcp/bridge.sock"


def test_plug_in_and_server_agree_on_the_address():
    gmb_platform = load("gmb_platform")
    cases: list[tuple[dict[str, str], OsKind]] = [
        ({**LINUX, "XDG_RUNTIME_DIR": "/run/user/7"}, "linux"),
        ({**LINUX, "XDG_RUNTIME_DIR": "/run/user/7", "FLATPAK_ID": "org.gimp.GIMP"}, "linux"),
        (LINUX, "linux"),
        (MACOS, "macos"),
        (WINDOWS, "windows"),
        ({**MACOS, "GIMP_MCP_SOCKET": "/s/b.sock"}, "macos"),
        ({**WINDOWS, "GIMP_MCP_SOCKET": r"\\.\pipe\t", "GIMP_MCP_TOKEN_FILE": r"C:\t\bridge.token"}, "windows"),
        ({**LINUX, "GIMP_MCP_SOCKET": "/s/b.sock", "GIMP_MCP_TOKEN_FILE": "/s/t"}, "linux"),
    ]
    for env, kind in cases:
        server = platforms.bridge_address(env, kind, uid=7, runtime_exists=lambda _p: True)
        plugin = gmb_platform.bridge_address(env, kind, uid=7, runtime_exists=lambda _p: True)
        assert (server.kind, server.path, server.token_path) == tuple(plugin), (env, kind)


def test_gimp_console_candidates():
    assert platforms.gimp_console_candidates(LINUX, "linux")[0] == "gimp-console-3.2"
    mac = platforms.gimp_console_candidates(MACOS, "macos")
    assert mac[0] == "/Applications/GIMP.app/Contents/MacOS/gimp-console-3.2"
    assert "/Users/ana/Applications/GIMP.app/Contents/MacOS/gimp-console-3.2" in mac
    win = platforms.gimp_console_candidates(WINDOWS, "windows")
    assert win[0] == r"C:\Program Files\GIMP 3\bin\gimp-console-3.2.exe"
    assert r"C:\Users\ana\AppData\Local\Programs\GIMP 3\bin\gimp-console-3.2.exe" in win


FORBIDDEN = re.compile(r"sys\.platform|/proc\b|XDG_RUNTIME_DIR|XDG_CONFIG_HOME|[\"']\.config[\"']")


def test_only_the_platform_modules_know_os_specific_locations():
    allowed = {"platforms.py", "gmb_platform.py"}
    offenders = []
    for path in sorted((ROOT / "src" / "gimp_mcp").rglob("*.py")):
        if path.name in allowed:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert offenders == []


def _text_io_without_encoding(tree) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "os":
            continue  # os.open, os.fdopen: file descriptors
        if name not in ("open", "read_text", "write_text"):
            continue
        keywords = {k.arg for k in node.keywords}
        mode = node.args[1] if name == "open" and len(node.args) > 1 else None
        binary = isinstance(mode, ast.Constant) and "b" in str(mode.value)
        if "encoding" not in keywords and not binary:
            lines.append(node.lineno)
    return lines


def test_text_files_are_read_and_written_as_utf_8():
    """Windows' default encoding is not UTF-8: every text read or write names its encoding."""
    offenders = []
    for path in sorted((ROOT / "src" / "gimp_mcp").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.relative_to(ROOT)}:{line}" for line in _text_io_without_encoding(tree)]
    assert offenders == []


def test_gimp_bundles_its_own_python_on_macos_and_windows():
    mac = "/Applications/GIMP.app/Contents/MacOS/gimp-console-3.2"
    assert platforms.bundled_gimp_python(mac, "macos") == "/Applications/GIMP.app/Contents/MacOS/python3"
    win = r"C:\Program Files\GIMP 3\bin\gimp-console-3.2.exe"
    assert platforms.bundled_gimp_python(win, "windows") == r"C:\Program Files\GIMP 3\bin\python.exe"
    assert platforms.bundled_gimp_python("/usr/bin/gimp-console-3.2", "linux") is None


def test_the_token_file_can_be_placed_explicitly():
    win = platforms.bridge_address({**WINDOWS, "GIMP_MCP_TOKEN_FILE": r"C:\tmp\t.token"}, "windows")
    assert win.token_path == r"C:\tmp\t.token"
    linux = platforms.bridge_address({**LINUX, "GIMP_MCP_SOCKET": "/s/b.sock", "GIMP_MCP_TOKEN_FILE": "/s/t"}, "linux")
    assert (linux.path, linux.token_path) == ("/s/b.sock", "/s/t")

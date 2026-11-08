"""Every OS-specific location and decision of the server, for Linux, macOS and Windows (ADR 0008).

Other modules ask this one instead of testing ``sys.platform`` or hard-coding Linux paths. Functions
take the environment and the OS kind explicitly, so each OS is unit tested from any machine; the
returned paths are pure paths of the target OS (wrap them in ``Path`` to use them). The plug-in has
its own copy of the bridge-address rule (``gmb_platform.py``, it cannot import this package); a test
keeps both in agreement.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Literal, NamedTuple

OsKind = Literal["linux", "macos", "windows"]
GIMP_SERIES = "3.2"
FLATPAK_APP = "org.gimp.GIMP"
SOCKET_ENV = "GIMP_MCP_SOCKET"
TOKEN_ENV = "GIMP_MCP_TOKEN_FILE"


def os_kind(name: str | None = None) -> OsKind:
    name = sys.platform if name is None else name
    if name == "darwin":
        return "macos"
    if name.startswith(("win32", "cygwin")):
        return "windows"
    return "linux"


CURRENT: OsKind = os_kind()


def _pure(kind: OsKind) -> type[PurePath]:
    return PureWindowsPath if kind == "windows" else PurePosixPath


def _kind(kind: OsKind | None) -> OsKind:
    return CURRENT if kind is None else kind


_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])", re.IGNORECASE)


def path_refusal(path: str, kind: OsKind | None = None) -> str | None:
    """Why file tools refuse ``path`` on this OS, or None for a local path (docs/security.md).

    Windows: UNC paths (``\\\\server\\share``) would make GIMP connect to another machine with the user's
    credentials, and device namespaces (``\\\\?\\``, ``\\\\.\\``) and reserved names (``CON``, ``NUL``,
    ``COM1``...) are not files. Elsewhere every path is local: network file systems are mounted by the user.
    """
    if _kind(kind) != "windows":
        return None
    if path[:2] in ("\\\\", "//", "\\/", "/\\"):
        return "is a network (UNC) or device path"
    for part in PureWindowsPath(path).parts[1:]:
        # Windows ignores the extension and trailing spaces and dots of a reserved name
        if _RESERVED.fullmatch(part.split(".", 1)[0].rstrip(" ")):
            return f"names the Windows device {part!r}"
    return None


def same_file_name(a: str, b: str, kind: OsKind | None = None) -> bool:
    """Whether two paths name the same file for this OS's usual file systems, before either exists.

    NTFS and APFS ignore case by default, and APFS also ignores the Unicode normalization form; the
    comparison takes the safe side (a case-sensitive volume is treated as insensitive).
    """
    if _kind(kind) == "linux":
        return a == b

    def key(path: str) -> str:
        return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())

    if _kind(kind) == "windows":
        a, b = str(PureWindowsPath(a)), str(PureWindowsPath(b))
    return key(a) == key(b)


def home(env: Mapping[str, str], kind: OsKind | None = None) -> PurePath:
    kind = _kind(kind)
    if kind == "windows":
        return PureWindowsPath(env.get("USERPROFILE") or env.get("HOME") or os.path.expanduser("~"))
    return PurePosixPath(env.get("HOME") or os.path.expanduser("~"))


def config_home(env: Mapping[str, str], kind: OsKind | None = None) -> PurePath:
    """Where applications keep their user configuration (GIMP's profile, MCP clients' settings)."""
    kind = _kind(kind)
    if kind == "windows":
        return PureWindowsPath(env.get("APPDATA") or home(env, kind) / "AppData" / "Roaming")
    if kind == "macos":
        return home(env, kind) / "Library" / "Application Support"
    return PurePosixPath(env.get("XDG_CONFIG_HOME") or home(env, kind) / ".config")


def gimp_profile_dir(env: Mapping[str, str], kind: OsKind | None = None, series: str = GIMP_SERIES) -> PurePath:
    """GIMP's user profile (``GIMP3_DIRECTORY`` overrides it on every OS)."""
    kind = _kind(kind)
    if env.get("GIMP3_DIRECTORY"):
        return _pure(kind)(env["GIMP3_DIRECTORY"])
    return config_home(env, kind) / "GIMP" / series


def flatpak_gimp_profile_root(env: Mapping[str, str], kind: OsKind | None = None) -> PurePath | None:
    """The GIMP profiles of a Flatpak GIMP (Linux only)."""
    kind = _kind(kind)
    if kind != "linux":
        return None
    return home(env, kind) / ".var" / "app" / FLATPAK_APP / "config" / "GIMP"


class BridgeAddress(NamedTuple):
    """Where the plug-in serves: a Unix socket path, or a Windows named pipe; and its token file."""

    kind: Literal["unix", "pipe"]
    path: str
    token_path: str


def _user_tag(env: Mapping[str, str]) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", env.get("USERNAME") or "user")


def bridge_address(
    env: Mapping[str, str],
    kind: OsKind | None = None,
    *,
    uid: int | None = None,
    runtime_exists: Callable[[str], bool] = os.path.isdir,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> BridgeAddress:
    """The address shared by the plug-in and the server (``GIMP_MCP_SOCKET`` overrides it)."""
    kind = _kind(kind)
    if kind == "windows":
        local = PureWindowsPath(env.get("LOCALAPPDATA") or home(env, kind) / "AppData" / "Local")
        token = env.get(TOKEN_ENV) or str(local / "gimp-mcp" / "bridge.token")
        return BridgeAddress("pipe", env.get(SOCKET_ENV) or r"\\.\pipe\gimp-mcp-" + _user_tag(env), token)
    explicit = env.get(SOCKET_ENV)
    if explicit:
        path = explicit
    elif kind == "macos":
        path = str(home(env, kind) / "Library" / "Application Support" / "gimp-mcp" / "bridge.sock")
    else:
        path = _linux_socket(env, uid, runtime_exists, path_exists)
    return BridgeAddress("unix", path, env.get(TOKEN_ENV) or path + ".token")


def _linux_socket(env, uid, runtime_exists, path_exists) -> str:
    runtime = env.get("XDG_RUNTIME_DIR")
    if runtime and env.get("FLATPAK_ID"):
        # Inside a Flatpak sandbox only $XDG_RUNTIME_DIR/app/$FLATPAK_ID is shared with the host.
        return f"{runtime}/app/{env['FLATPAK_ID']}/gimp-mcp/bridge.sock"
    if runtime and runtime_exists(runtime):
        native = f"{runtime}/gimp-mcp/bridge.sock"
        flatpak = f"{runtime}/app/{FLATPAK_APP}/gimp-mcp/bridge.sock"
        # seen from the host, a Flatpak GIMP serves under its app directory
        return flatpak if not path_exists(native) and path_exists(flatpak) else native
    return f"/tmp/gimp-mcp-{os.getuid() if uid is None else uid}/bridge.sock"  # type: ignore[attr-defined]


def short_runtime_dir(env: Mapping[str, str], kind: OsKind | None = None) -> str | None:
    """A writable per-user directory with short paths (Unix socket paths are limited to ~104 bytes)."""
    kind = _kind(kind)
    runtime = env.get("XDG_RUNTIME_DIR") if kind == "linux" else None
    if runtime and os.path.isdir(runtime) and os.access(runtime, os.W_OK):
        return runtime
    return None


def gimp_console_candidates(env: Mapping[str, str], kind: OsKind | None = None) -> list[str]:
    """Headless GIMP executables to try: names looked up on PATH (Linux) or install locations."""
    kind = _kind(kind)
    names = ["gimp-console-3.2", "gimp-console-3.0", "gimp-console", "gimp-console-3"]
    if kind == "macos":
        bundle = "GIMP.app/Contents/MacOS/gimp-console-3.2"
        return [f"/Applications/{bundle}", str(home(env, kind) / "Applications" / bundle), *names]
    if kind == "windows":
        program_files = PureWindowsPath(env.get("ProgramFiles") or r"C:\Program Files")
        local = PureWindowsPath(env.get("LOCALAPPDATA") or home(env, kind) / "AppData" / "Local")
        exe = PureWindowsPath("bin") / "gimp-console-3.2.exe"
        return [str(program_files / "GIMP 3" / exe), str(local / "Programs" / "GIMP 3" / exe), *names]
    return names


def bundled_gimp_python(console: str, kind: OsKind | None = None) -> str | None:
    """The Python shipped inside GIMP's bundle next to gimp-console (macOS app, Windows installer), which
    runs its plug-ins; None on Linux, where GIMP uses the system python3."""
    kind = _kind(kind)
    if kind == "linux":
        return None
    name = "python.exe" if kind == "windows" else "python3"
    return str(_pure(kind)(console).parent / name)


_GIMP_PROCESS = re.compile(r"gimp(-console)?(-\d.*)?")


def parse_gimp_processes(output: str, kind: OsKind) -> list[tuple[int, str]]:
    """GIMP main processes in the output of ``ps -x -o pid=,comm=`` (macOS) or ``tasklist /FO CSV /NH``
    (Windows): its plug-ins and gimp-mcp itself are not GIMP."""
    found = []
    for line in output.splitlines():
        if kind == "windows":
            fields = [field.strip('"') for field in line.strip().split('","')]
            if len(fields) < 2 or not fields[1].isdigit():
                continue
            pid, name = int(fields[1]), re.sub(r"\.exe$", "", fields[0], flags=re.IGNORECASE)
        else:
            parts = line.strip().split(None, 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            pid, name = int(parts[0]), PurePosixPath(parts[1]).name
        if _GIMP_PROCESS.fullmatch(name):
            found.append((pid, name))
    return found


def gimp_processes(kind: OsKind | None = None) -> list[tuple[int, str]] | None:
    """GIMP main processes of this user (not its plug-ins); None when they cannot be listed."""
    kind = _kind(kind)
    if kind != "linux":
        if kind == "windows":
            user = os.environ.get("USERNAME", "")
            args = ["tasklist", "/FO", "CSV", "/NH", "/FI", f"USERNAME eq {user}"]
        else:
            args = ["ps", "-x", "-o", "pid=,comm="]  # this user's processes, with or without a terminal
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return parse_gimp_processes(proc.stdout, kind) if proc.returncode == 0 else None
    if not Path("/proc").is_dir():
        return None
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():  # type: ignore[attr-defined]
                continue
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if _GIMP_PROCESS.fullmatch(comm):
            found.append((int(entry.name), comm))
    return found

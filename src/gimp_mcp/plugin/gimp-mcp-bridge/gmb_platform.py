"""OS-specific locations of the plug-in (stdlib only; mirrors gimp_mcp.platforms, ADR 0008).

The plug-in cannot import the gimp_mcp package (GIMP runs it with its own Python), so the rule for
the bridge address is repeated here; a unit test checks both copies give the same answer.
"""

import os
import re
import sys

SOCKET_ENV = "GIMP_MCP_SOCKET"


def os_kind(name=None):
    name = sys.platform if name is None else name
    if name == "darwin":
        return "macos"
    if name.startswith(("win32", "cygwin")):
        return "windows"
    return "linux"


def _home(env, kind):
    if kind == "windows":
        return env.get("USERPROFILE") or env.get("HOME") or "~"
    return env.get("HOME") or os.path.expanduser("~")


def bridge_address(env, kind=None, uid=None, runtime_exists=os.path.isdir):
    """(kind, path, token_path): a Unix socket or a Windows named pipe, and the token file."""
    kind = os_kind() if kind is None else kind
    if kind == "windows":
        local = env.get("LOCALAPPDATA") or _home(env, kind) + "\\AppData\\Local"
        user = re.sub(r"[^A-Za-z0-9._-]", "_", env.get("USERNAME") or "user")
        return ("pipe", env.get(SOCKET_ENV) or "\\\\.\\pipe\\gimp-mcp-" + user, local + "\\gimp-mcp\\bridge.token")
    path = env.get(SOCKET_ENV)
    if not path and kind == "macos":
        path = _home(env, kind) + "/Library/Application Support/gimp-mcp/bridge.sock"
    if not path:
        runtime = env.get("XDG_RUNTIME_DIR")
        if runtime and env.get("FLATPAK_ID"):
            # Inside a Flatpak sandbox only $XDG_RUNTIME_DIR/app/$FLATPAK_ID is shared with the host.
            path = "%s/app/%s/gimp-mcp/bridge.sock" % (runtime, env["FLATPAK_ID"])
        elif runtime and runtime_exists(runtime):
            path = runtime + "/gimp-mcp/bridge.sock"
        else:
            path = "/tmp/gimp-mcp-%d/bridge.sock" % (os.getuid() if uid is None else uid)
    return ("unix", path, path + ".token")


def process_start(pid, kind=None):
    """When a process started, as an opaque string; None where it cannot be read."""
    kind = os_kind() if kind is None else kind
    if kind == "windows":
        return _windows_process_start(pid)
    if kind == "macos":
        import subprocess

        try:
            out = subprocess.run(["/bin/ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                                 timeout=5).stdout.strip()  # fmt: skip
        except (OSError, subprocess.SubprocessError):
            return None
        return out or None
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8") as handle:
            return handle.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _windows_process_start(pid):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        return "%d" % ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


def peer_uid(sock):
    """The uid of the process at the other end of a Unix socket (Linux, macOS); None if unknown."""
    import socket
    import struct

    so_peercred = getattr(socket, "SO_PEERCRED", None)
    if so_peercred is not None:
        _pid, uid, _gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, so_peercred, struct.calcsize("3i")))
        return uid
    local_peercred = getattr(socket, "LOCAL_PEERCRED", None)
    if local_peercred is not None:
        # struct xucred: u_int cr_version, uid_t cr_uid, short cr_ngroups, gid_t cr_groups[16]
        raw = sock.getsockopt(0, local_peercred, struct.calcsize("IIh16I"))  # 0 = SOL_LOCAL
        _version, uid = struct.unpack_from("II", raw)
        return uid
    return None

# ADR 0008 — Windows and macOS: one platform layer, a transport per OS

- Status: accepted (2026-11-08)
- Context issues: #98 (this decision), #99 (macOS), #100 (Windows), milestone v0.5.0

## Context

gimp-mcp ran on Linux only: the bridge is a Unix socket under `$XDG_RUNTIME_DIR`, authenticated by
`SO_PEERCRED` and a token, and paths such as `~/.config/GIMP/3.2` were written in several modules.
Facts checked on 2026-11-08 on GitHub-hosted runners with GIMP 3.2.6 from gimp.org (installers
pinned by SHA-256; `docs/gimp-notes.md`, "Windows and macOS"):

| | macOS 15 (arm64 runner) | Windows Server 2025 (x86_64 runner) |
|---|---|---|
| Install | `gimp-3.2.6-arm64.dmg` → `/Applications/GIMP.app` | `gimp-3.2.6-setup.exe /VERYSILENT /CURRENTUSER /DIR=…` |
| Headless GIMP | `GIMP.app/Contents/MacOS/gimp-console-3.2` | `bin\gimp-console-3.2.exe` |
| GIMP's Python | 3.14.7 (`Contents/MacOS/python3`), PyGObject 3.56, GLib 2.88 | 3.14.7 MinGW (`bin\python.exe`), PyGObject 3.58, GLib 2.90 |
| Profile | `~/Library/Application Support/GIMP/3.2` | `%APPDATA%\GIMP\3.2` |
| In GIMP's Python | `AF_UNIX` ✓, `LOCAL_PEERCRED` ✓, `GLib.unix_fd_add_full` ✓ | no `AF_UNIX`, no `unix_fd_add_full`; `_winapi` named pipes, `ctypes`, `GLib.io_add_watch`; Gio can listen on a Unix socket |
| Server's CPython (3.12+) | `AF_UNIX` ✓, `LOCAL_PEERCRED` ✓, `asyncio.open_unix_connection` ✓ | no `AF_UNIX`, no `open_unix_connection`; named pipes (`_winapi`, Proactor event loop) |
| `XDG_RUNTIME_DIR` | unset | unset |

`gimp-console … --batch-interpreter=python-fu-eval -b …` works on both; `Gimp.quit()` from a batch
command fails there, so headless runs end with `--quit`.

## Decision

**One platform layer.** `gimp_mcp/platforms.py` answers every OS-specific question of the server
(profile, client configuration folders, bridge address, headless GIMP candidates, listing GIMP
processes); `gmb_platform.py` is the plug-in's copy of the bridge-address rule (the plug-in cannot
import the package) and a unit test keeps both in agreement. No other module tests `sys.platform` or
hard-codes `/proc`, `XDG_*` or `~/.config` (checked by a unit test). Functions take the environment
and the OS kind, so every OS is unit tested on every runner.

**Locations.**

| | Linux | macOS | Windows |
|---|---|---|---|
| GIMP profile (`GIMP3_DIRECTORY` wins) | `$XDG_CONFIG_HOME/GIMP/3.2` | `~/Library/Application Support/GIMP/3.2` | `%APPDATA%\GIMP\3.2` |
| Clients' configuration folder | `$XDG_CONFIG_HOME` (`~/.config`) | `~/Library/Application Support` | `%APPDATA%` |
| Bridge (`GIMP_MCP_SOCKET` wins) | `$XDG_RUNTIME_DIR/gimp-mcp/bridge.sock` (Flatpak: ADR 0003; else `/tmp/gimp-mcp-<uid>/`) | `~/Library/Application Support/gimp-mcp/bridge.sock` | named pipe `\\.\pipe\gimp-mcp-<user>` |
| Token | next to the socket (`.token`) | next to the socket | `%LOCALAPPDATA%\gimp-mcp\bridge.token` |
| Headless GIMP | `gimp-console-3.2` on PATH | `/Applications/` or `~/Applications/GIMP.app/Contents/MacOS/gimp-console-3.2` | `%ProgramFiles%\GIMP 3\bin\` or `%LOCALAPPDATA%\Programs\GIMP 3\bin\gimp-console-3.2.exe` |

macOS uses a fixed folder rather than `$TMPDIR`: GIMP and the MCP client must agree on the path
without sharing an environment, and the folder is created `0700` like the Linux one (the path stays
under the 104-byte limit of `sun_path` for usual home folders; `GIMP_MCP_SOCKET` covers the rest).

**Transports and who may connect.** The rule stays: only the current user's processes, and only with
the token.

* macOS: the same Unix socket server as Linux; the peer's uid comes from `LOCAL_PEERCRED`
  (`getsockopt(SOL_LOCAL, LOCAL_PEERCRED)` → `xucred.cr_uid`) instead of `SO_PEERCRED`.
* Windows: a named pipe, because neither the server's CPython nor GIMP's Python has `AF_UNIX`. The
  plug-in creates it with `ctypes` (`CreateNamedPipeW`): a DACL granting access to the current user's
  SID only, `PIPE_REJECT_REMOTE_CLIENTS`, and `FILE_FLAG_FIRST_PIPE_INSTANCE` so another process cannot
  take the name first. The plug-in checks the client's process owner SID
  (`GetNamedPipeClientProcessId` → token user) and the server checks the pipe server's
  (`GetNamedPipeServerProcessId`), the equivalents of the uid check. GIMP calls stay on GIMP's main
  thread: pipe I/O runs in worker threads that hand requests over with `GLib.idle_add`.
  Nothing listens on a network interface.

Loopback TCP was rejected: any local user can connect to it, so the token would be the only barrier,
and it is a network interface. An `AF_UNIX` socket served through Gio was rejected because the
server's CPython cannot connect to it without a native extension.

**What is verified.** CI runs on GitHub's `macos-15` (arm64) and `windows-2025` (x86_64) runners;
`docs/compatibility.md` claims only those (macOS 15 arm64; Windows Server 2025 as the closest runner to
Windows 10/11 x86_64, the desktop versions themselves untested). The unit tests run on the three OS
from this decision on.

## Consequences

* #99 and #100 implement the transports; #101 the install and setup locations; #102 path rules
  (drive letters, case-insensitive file systems); #103 doctor and docs; #104 the release pipeline.
* The doctor cannot list GIMP processes outside Linux yet (`instances` is skipped there).
* A third transport means the bridge client and server hide the transport behind one interface; the
  JSON-lines protocol and the token handshake stay identical (ADR 0001).

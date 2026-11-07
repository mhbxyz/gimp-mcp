# ADR 0001 — Bridge GIMP and MCP through a persistent Python plug-in on a Unix socket

- Status: accepted (2026-11-07)
- Context issue: #1

## Context

An MCP client launches `gimp-mcp` over stdio. The server must drive an
**existing, interactive** GIMP 3 session (the one the user is looking at), not
only a batch process. GIMP 3 does not expose a remote API by itself. The
options explored on GIMP 3.2.6 (Linux, PyGObject 3.58):

| Option | Result of the experiment |
|---|---|
| `gimp-console --batch-interpreter python-fu-eval -b …` | Works, but starts a **new** GIMP each time (≈5 s with fonts), cannot see the user's session. Useful for tooling only. |
| `script-fu-server` (bundled TCP server) | Exposes arbitrary Script-Fu evaluation on TCP: arbitrary code execution, network-reachable, string-based protocol. Rejected. |
| Regular `PLUGIN` procedure started from a menu | Lives only while its run function runs, must be started by hand each session. |
| **`PERSISTENT` procedure with no argument ("extension")** | **Started automatically by GIMP at launch, in the GUI and in `gimp-console`**, lives until GIMP quits, and may call the GIMP API at any time after `persistent_ready()`. Verified: socket served, `Gimp.get_images()` and `Gimp.Image.new` work, `gimp-quit` works, GIMP shuts the plug-in down cleanly on exit. |

## Decision

* Ship a Python 3 plug-in `gimp-mcp-bridge` (stdlib + PyGObject only, since it
  runs on GIMP's Python, not in gimp-mcp's virtualenv) that registers the
  extension `extension-gimp-mcp-bridge`.
* The extension calls `persistent_ready()`, then `persistent_enable()` and runs a
  `GLib.MainLoop`. A Unix stream socket is watched with `GLibUnix.fd_add_full`;
  every request is executed on the plug-in's main thread, one at a time.
  (libgimp is not thread-safe, so no worker threads touch GIMP.)
* Protocol: JSON lines with request ids, a mandatory `hello` carrying a token,
  structured errors (see `docs/bridge-protocol.md`).
* The MCP server (`gimp-mcp serve`) is a separate process using the official
  MCP Python SDK (`mcp` 2.x, `MCPServer`) on stdio; it connects lazily to the
  socket on each tool call, so it starts even when GIMP is not running.
* Python is kept for both sides (the plug-in has to be Python or C anyway; the
  MCP SDK is first-class in Python).

## Consequences

* Installing = copying one directory into `<GIMP config>/plug-ins/` and
  restarting GIMP (`gimp-mcp install-plugin`).
* The bridge only exists while GIMP runs. If the plug-in process crashes, GIMP
  does **not** restart it: restart GIMP. The server reports `GIMP_NOT_RUNNING` /
  `BRIDGE_UNAVAILABLE` with a hint instead of hanging.
* Long GIMP operations block other bridge requests (single thread); every
  client wait is bounded by a timeout and reports an `unknown` outcome.
* The socket path must stay under ~107 bytes (AF_UNIX limit): it lives in
  `$XDG_RUNTIME_DIR/gimp-mcp/` by default.
* Python plug-ins are started via `#!/usr/bin/env python3`: GIMP must not be
  started with a virtualenv first on `PATH` (the venv's Python lacks `gi`). The
  headless launcher strips virtualenvs from `PATH`.
* Linux only for now (`SO_PEERCRED`, `/proc`, XDG runtime dir). Windows/macOS are
  not claimed.

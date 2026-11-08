# Architecture

```
MCP client ──stdio (JSON-RPC)──► gimp-mcp serve ──Unix socket / Windows named pipe (JSON lines)──► gimp-mcp-bridge ──libgimp──► GIMP 3
 (Claude, …)                     (venv, mcp SDK)                                (plug-in, GIMP's Python)
```

| Component | Where | Responsibility |
|---|---|---|
| `gimp_mcp.server` / `gimp_mcp.tools.*` | MCP server process | Tool definitions, argument validation, id encoding, result shaping. |
| `gimp_mcp.toolkit` | MCP server process | Turns `GimpMcpError` into structured tool errors; pins calls to a session; progress heartbeats and resource-list notifications. |
| `gimp_mcp.mcp_resources`, `gimp_mcp.prompts` | MCP server process | `gimp://images…` resources and workflow prompts ([ADR 0007](adr/0007-resources-prompts-progress.md)). |
| `gimp_mcp.bridge` | MCP server process | Asyncio socket client: discovery, token handshake, version check, timeouts, request serialization. |
| `plugin/gimp-mcp-bridge/gmb_server.py` | inside GIMP | Socket server, auth, framing, dispatch. Standard library only, tested without GIMP. |
| `plugin/gimp-mcp-bridge/gmb_ops.py` | inside GIMP | The only code calling the GIMP API. |
| `plugin/gimp-mcp-bridge/gimp-mcp-bridge.py` | inside GIMP | Registers the persistent extension and runs the GLib main loop. |
| `gimp_mcp.headless` | tests / CI / demo | Starts an isolated `gimp-console` with the plug-in. |

Why this shape: see [ADR 0001](adr/0001-bridge-persistent-plugin-unix-socket.md).

## Lifecycle

1. `gimp-mcp install-plugin` copies the plug-in into the GIMP 3.2 profile's `plug-ins/`
   (`~/.config/GIMP/3.2`, `~/Library/Application Support/GIMP/3.2`, `%APPDATA%\GIMP\3.2`).
2. GIMP starts → starts the extension → the bridge creates the socket (Linux, macOS) or named
   pipe (Windows) + token.
3. The MCP client starts `gimp-mcp serve`. The server starts even if GIMP is not
   running; each tool call (re)connects lazily, performs `hello` (token, protocol
   and GIMP version ≥ 3.2 checks) and runs.
4. GIMP quits → the plug-in is terminated by GIMP; a socket file may remain
   and is detected as stale (`GIMP_NOT_RUNNING`), then replaced at next start (a
   Windows pipe disappears with GIMP).
5. The MCP client closes stdin → the server exits; nothing changes in GIMP.

## Guarantees and limits

* **No network exposure**: a Unix socket (`0600`, in a `0700` directory, peer-uid check) or, on
  Windows, a named pipe that admits only the current user and rejects remote clients; token handshake. See [security.md](security.md).
* **Bounded waits** (details and tests in [security.md](security.md#reliability-guarantees)): connect 3 s, handshake 3 s, requests 60 s by default
  (`gimp-mcp serve --timeout`). A timed-out or interrupted mutation is reported
  with `outcome: "unknown"`; the server never claims it was cancelled.
* **Ordering**: one request in flight per server, and GIMP executes requests
  one at a time across all connected servers.
* **stdout** of `gimp-mcp serve` carries only MCP JSON-RPC; logs go to stderr
  (`--verbose` for debug logs). Logs never contain image data or the token.
* Linux, macOS and Windows are supported (verified on GIMP 3.2.6, see
  [compatibility](compatibility.md); ADR 0008). OS-specific locations and rules live in
  `platforms.py` (server) and `gmb_platform.py` (plug-in); the Windows pipe transport is
  `gmb_pipe.py`.

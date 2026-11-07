# Bridge protocol

Local protocol between `gimp-mcp serve` (client) and the GIMP plug-in
`gimp-mcp-bridge` (server). It is an implementation detail of gimp-mcp, not a
public API; it is versioned (`protocol`) so a mismatched plug-in is detected.

## Transport and discovery

* Unix domain stream socket. Path, identical rules on both sides:
  1. `$GIMP_MCP_SOCKET` if set;
  2. `$XDG_RUNTIME_DIR/gimp-mcp/bridge.sock` if the runtime dir exists;
  3. `/tmp/gimp-mcp-<uid>/bridge.sock` otherwise.
* Token file: `<socket path>.token` (mode `0600`), random 256-bit hex token
  regenerated at every GIMP start.
* The directory is created `0700`, the socket is `0600`. Connections whose peer
  uid (`SO_PEERCRED`) differs from GIMP's uid are closed before reading a byte.
* If a live bridge already answers on the path (second GIMP instance), the new
  bridge refuses to start (`BRIDGE_ALREADY_RUNNING` in GIMP's console); a stale
  socket left by a crash is replaced.

## Framing

One JSON object per line (UTF-8, `\n`-terminated).

```json
→ {"id": 1, "method": "hello", "params": {"token": "…", "protocol": 1}}
← {"id": 1, "result": {"protocol": 1, "gimp_version": "3.2.6", "session_id": "e5fec992", "pid": 4242, "bridge_version": "0.2.0"}}
→ {"id": 2, "method": "session.images", "params": {"_session": "e5fec992"}}
← {"id": 2, "result": {"images": [...]}}
← {"id": 3, "error": {"code": "NOT_FOUND", "message": "…", "details": {...}}}
```

* `hello` must be the first request; anything else, or a wrong token, gets
  `UNAUTHORIZED` and the connection is closed. No operation runs before a
  successful `hello`.
* `params._session` (optional) pins a request to a GIMP session; a mismatch is
  refused with `SESSION_CHANGED` without running the operation.
* Requests larger than 8 MiB are refused (`REQUEST_TOO_LARGE`) and the
  connection closed. Images never travel *to* GIMP through the socket (files
  are referenced by path); previews travel back base64-encoded with a size cap.
* The bridge handles requests strictly one at a time on GIMP's plug-in main
  thread, across all connections.

## Sessions

`session_id` = first 8 hex chars of `sha256("<GIMP pid>:<GIMP start time>")`.
It is stable while the GIMP process lives (even if only the bridge restarts)
and changes whenever GIMP restarts. MCP ids embed it (`image:3@e5fec992`).

## Errors

`error.code` is stable; `message` is human text; `details` is optional
structured data. Operations raise anticipated errors **before** modifying
anything. An unexpected exception inside GIMP is reported as `GIMP_ERROR` (the
traceback goes to GIMP's stderr only); for a mutation its outcome is unknown.

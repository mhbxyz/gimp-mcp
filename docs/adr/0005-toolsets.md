# ADR 0005 — Group tools into toolsets; a bounded default selection

- Status: accepted (2026-11-08)
- Context issue: #45

## Context

v0.2.0 exposed 52 tools whose definitions weigh about 140 kB in `tools/list` (two
thirds of it output schemas). v0.3.0 adds analysis, color, paths, resources,
animation, formats, batch… tools. Every listed tool costs context in each
request, slows models down and makes tool choice worse, and some clients cap the
number of tools across all servers.

MCP lets a server change its tool list during a session and notify the client:
`notifications/tools/list_changed` after the initialize handshake (the server
must advertise `tools.listChanged`), or a `subscriptions/listen` stream with the
2026-07-28 protocol. Whether a client refetches on that notification depends on
the client.

## Decision

* Every tool is registered with a **required** `toolset` (`Toolkit.tool(...,
  toolset=)`); an unknown toolset fails at registration. The catalog lives in
  `gimp_mcp/toolsets.py`.
* `core` (status, inspection, previews, `gimp_list_toolsets`,
  `gimp_enable_toolsets`) is always enabled. The selection comes from
  `--toolsets`, else `GIMP_MCP_TOOLSETS`, else the **default** toolsets;
  `default` and `all` are shortcuts. Unknown names stop the server at start
  (exit code 2) rather than silently listing fewer tools.
* The default is the everyday workflow (files, layers, transform, selection,
  paint, filters, text, history). The generic `procedures` toolset leaves the
  default: it is advanced and its four tools invite PDB calls when a dedicated
  tool exists.
* The default selection has a **budget** (50 tools, 140 000 bytes of
  definitions) enforced by a unit test. New capabilities go into new toolsets
  unless they belong to the everyday workflow; growing the default means raising
  the budget on purpose, in review.
* `gimp_enable_toolsets` adds tools for the session (it never removes any) and
  sends both notifications. The server advertises `tools.listChanged`.

## Consequences

* Clients that ignore list-changed notifications see enabled tools only after a
  restart with `--toolsets`; the tool description says so.
* Breaking for v0.2.0 users who relied on the four `procedures` tools being
  listed: noted in the CHANGELOG with the one-word fix (`--toolsets
  default,procedures`).
* Tests that need every tool build the server with `toolsets="all"`
  (`tests/unit/tool_harness.py`, `tests/e2e/conftest.py`). The demo lists only
  its own toolsets.
* Output schemas are the larger part of the definitions. Shrinking them
  (recursive `LayerNode` is repeated in every layer tool) would free budget
  later. Not done here: it changes what clients validate.

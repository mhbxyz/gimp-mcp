# ADR 0012: `gimp_enable_toolsets` says how to call the tools it adds

Status: accepted (2026-11-11, #147)

## Context

The evaluation baseline (#106) showed Claude Code calling tools right after `gimp_enable_toolsets` with no
or wrong arguments (`gimp_convert_mode({})`, `gimp_invert({image})`), then retrying: the client loads
the new tools' schemas lazily (on `notifications/tools/list_changed`, or through its own tool search), so
the model's next turn may not have them yet. Clients differ and none can be fixed from the server.

## Decision

* The result of `gimp_enable_toolsets` carries, for each tool it added, `usage`: `name`, `required`
  (the required parameter names), `call` (a one-line signature: required parameters with their types,
  enum values spelled out, then optional names with `?`, e.g.
  `gimp_convert_mode(image: string, mode: 'rgb'|'gray'|'indexed', palette?, …)`) and `summary` (the
  first sentence of its description). The model reads it in the same turn, whatever the client does
  with the notification.
* Nothing is added for tools that were already enabled.
* The signature comes from the registered input schema (`gimp_mcp.arguments.signature`), the same
  source as the hint of an `INVALID_ARGUMENT` (#146), so the two never disagree.

## Consequences

* The core toolset's schema grows by a few hundred bytes (within the default budget); the result of
  enabling a large toolset is longer (paths: 16 lines).
* A wrong first call still gets an `INVALID_ARGUMENT` naming the fields and the required parameters.

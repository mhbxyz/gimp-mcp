# ADR 0010: Plug-in compatibility from the bridge protocol and its operations

Status: accepted (2026-11-11, #120). Replaces the MAJOR.MINOR rule of #35.

## Context

Until 0.6.0 the server refused a GIMP plug-in whose MAJOR.MINOR differed from its own
(`PLUGIN_VERSION_MISMATCH` on every tool). In 1.x that would force every user to reinstall the plug-in
and restart GIMP at each minor release, although most releases add tools without touching the
operations an older plug-in already serves.

## Decision

* The plug-in's `hello` reports `protocol` (the wire format, `docs/bridge-protocol.md`) and
  `capabilities`: every operation it serves with a **revision** (1 by default,
  `gmb_ops.REVISIONS`).
* The server accepts any plug-in speaking a protocol in `versions.SUPPORTED_PROTOCOLS` (today: 1),
  whatever its version. Another protocol is refused at connection with `PLUGIN_VERSION_MISMATCH`.
* A call names the operation and, when it relies on a newer parameter or meaning, its revision
  (`kit.call(..., revision=N)`). When the plug-in lacks the operation or serves an older revision, the
  call fails **before anything is sent** with `PLUGIN_VERSION_MISMATCH`, the operation in
  `details`, and the hint `gimp-mcp install-plugin`, then restart GIMP. Plug-ins before 0.7.0 list no
  capabilities: they are trusted with revision 1, and their `UNKNOWN_METHOD` becomes the same error.
* An operation whose parameters or meaning change gets a new revision (or a new name); the plug-in
  rejects nothing it does not know, so silently ignoring a new parameter is what the revision prevents.
* The verdict, shown by `gimp_status` (`plugin_compatibility`) and `gimp-mcp doctor`, compares the
  plug-in's capabilities with those of the plug-in bundled with the server (read from its source):
  `match` (same version), `compatible` (another version serving everything), `partial` (some
  operations missing or older, or unknown before 0.7.0) or `incompatible` (refused).

## Consequences

* A newer plug-in works with an older server, and an older plug-in keeps serving every tool whose
  operations it has; only the tools needing something new ask for an update.
* Changing an operation's parameters now means bumping its revision in `gmb_ops.REVISIONS` and passing
  it from the tool; `tests/unit/test_versions.py` covers old plug-in with new server and the reverse,
  `tests/e2e/test_versions.py` runs the previous release's plug-in in a real GIMP.
* A protocol change (the wire format itself) still needs a plug-in update; the server can list several
  supported protocols during a transition.

# ADR 0006 — Batch recipes run in the MCP server, as calls of listed tools

- Status: accepted (2026-11-08)
- Context issue: #61

## Context

Agents need to apply the same edit to many files. Doing it call by call costs one round trip per
step and per file, and a failure halfway leaves images open. Options considered:

1. A bridge operation running a recipe inside GIMP.
2. A server-side tool that calls the existing MCP tools in process.
3. A script language (Script-Fu, Python) sent to GIMP.

## Decision

* `gimp_run_batch` (toolset `batch`) runs in the MCP server. A recipe is a list of
  `{tool, arguments}` steps; each step is an ordinary in-process call of a **listed** tool, so it
  keeps that tool's validation, path rules, allowlists and error codes. Nothing new is exposed to
  GIMP and nothing is evaluated (option 3 is excluded by docs/security.md).
* Placeholders are `str.format` fields restricted to a fixed set (`{image}`, `{layer}`,
  `{output}`, `{file}`, `{name}`, `{stem}`, `{ext}`, `{dir}`, `{index}`); unknown fields,
  attribute or index access are refused.
* Everything that can be checked without GIMP is checked before the first file is opened: tool
  names (tools of disabled toolsets are refused, the batch does not enable them), argument names
  and types (with the first file's values), placeholders, inputs and every output. A recipe that
  fails there changes nothing.
* Inputs are explicit files or a glob confined to one directory (relative pattern, no `..`,
  symlinks leading out are not followed), capped by `max_files`.
* Outputs: one naming pattern, used by steps through `{output}` as a whole value, only in tools
  with an `overwrite` argument; the batch owns `overwrite`. Outputs must be unique, never an input,
  and existing files are refused unless `overwrite=true`.
* Images: the batch closes, without saving, the image it opened and every image id returned by a
  step that was not open before the batch. Images opened by the user before the batch are never
  closed. Recipes cannot call `gimp_close_image`.
* A failure is reported per file (step, tool, code, message); the other files still run unless
  `continue_on_error=false`.

## Consequences

* New tools are usable in recipes without any change to the batch.
* The batch is as fast as the tools it calls; there is no GIMP-side transaction: a file that fails
  halfway is closed without saving, and outputs already written by earlier steps stay on disk.
* An image created by a step whose id is not in the step's result would not be closed; every tool
  that creates an image returns its id.

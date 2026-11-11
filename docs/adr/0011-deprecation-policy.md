# ADR 0011: Deprecation policy

Status: accepted (2026-11-11, #117)

## Context

The public API (`docs/compatibility.md`, snapshot in `docs/api/contract.json`) is about to be frozen for
1.0. It still has to change: the API review (#118) renames tools and parameters, and later versions will
too. Clients must get time and a signal before anything they use disappears.

## Decision

* **What can be deprecated**: any part of the public API: a tool, a tool parameter, an output field, an
  error code, a prompt, a resource, a CLI command or option.
* **Period**: a deprecated item keeps working for at least one minor version, and is removed only in a
  major version: the next major after the version that deprecated it (`0.x` → `1.0.0`, `1.x` → `2.0.0`).
  Removing it is a breaking change, refused by the contract check unless the major version changes
  (from 1.0 on).
* **Mechanism** (`gimp_mcp.toolkit.Deprecation`):
  * a renamed tool keeps its old name as an **alias** (`kit.tool(..., aliases={"old_name": "0.7.0"})`):
    same arguments, same result, same toolset;
  * a tool replaced by another is marked `deprecated=Deprecation(since, replacement)`;
  * a parameter is kept in the signature and listed in `deprecated_parameters`; its schema gets
    `"deprecated": true`;
  * every call to a deprecated tool, or passing a deprecated parameter, returns a **notice**: in the
    result's `_meta` under `io.github.mhbxyz/deprecations` (`name`, `since`, `removal`, `replacement`) and
    as a text block (`Deprecation notice: …`), on success and on error; the server logs a warning.
* **Announcement**: a `### Deprecated` entry in `CHANGELOG.md`; the tool description starts with
  `Deprecated since X: …`; `docs/tools.md` and `docs/upgrading.md` give the replacement; the contract
  snapshot records `deprecated` / `deprecatedParameters` with their removal version.

## Consequences

* Agents see the replacement on every call and can switch without reading the changelog.
* Aliases cost entries in `tools/list`: they count against the default toolset budget until removed.
* `tests/unit/test_deprecations.py` covers aliases, deprecated tools and parameters and the contract.

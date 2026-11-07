# Compatibility and support policy

## Supported and verified

| Component | Supported | Verified by |
|---|---|---|
| Operating system | **Linux** (x86_64) | CI (Ubuntu 24.04 runner + Arch Linux container), developer machine (CachyOS) |
| GIMP | **3.2.x** (3.2.6 tested) | CI pins GIMP 3.2.6-2 (`ci/Dockerfile`); older versions are refused with `VERSION_INCOMPATIBLE` |
| GIMP packaging | distribution packages (`/usr/bin/gimp`, system Python with PyGObject) | CI, developer machine |
| GIMP packaging | **Flatpak from Flathub** (`org.gimp.GIMP`, 3.2.8 tested) | CI job `flatpak` (`ci/Dockerfile.flatpak`, pinned Flathub commit); see [ADR 0003](adr/0003-flatpak-gimp.md) |
| GIMP's Python (runs the plug-in) | Python 3 with PyGObject ≥ 3.50 and the `Gimp-3.0` typelib | CI (Python 3.14, PyGObject 3.58) |
| Python for the MCP server | ≥ 3.11 | CI fast job (3.12), e2e (3.14) |
| MCP | `mcp` Python SDK 2.x, stdio transport | e2e tests use the official client |

## Not supported (not verified)

* **Windows and macOS** — the bridge uses Unix sockets, `SO_PEERCRED`,
  `/proc` and the XDG runtime directory; nothing is claimed for them.
* **Snap GIMP** — different confinement; untested. (Flatpak is supported, see above.)
* **GIMP 2.10 / 3.0** — refused at connection time.
* Remote GIMP over a network — by design the bridge is local only.

## Local permissions

Everything runs as the user, without privileges:

* the plug-in is copied to `~/.config/GIMP/3.2/plug-ins/gimp-mcp-bridge/`
  (or `$GIMP3_DIRECTORY`);
* the socket and its token live in `$XDG_RUNTIME_DIR/gimp-mcp/` (`0700`,
  socket and token `0600`);
* file tools read/write only the absolute paths they are given, with the user's
  permissions, and never overwrite without `overwrite: true`.

## Versioning and compatibility promise

[Semantic versioning](https://semver.org/). While the version is `0.y.z`,
minor versions may break compatibility; every change is listed in
`CHANGELOG.md`.

* **Public API**: MCP tool names, input schemas, output schemas and error
  `code`s, the CLI commands and their options.
* **Internal**: the bridge protocol (versioned: `protocol: 1`) and the Python
  modules.

### Plug-in / server versions

The version is defined once, in `pyproject.toml`; the package, `gimp-mcp
--version`, the built artifacts and the installed plug-in (a `VERSION` file
written by `gimp-mcp install-plugin`) all derive from it. The plug-in reports
its version in the bridge handshake and the server applies this rule:

| Plug-in vs server | Verdict | Effect |
|---|---|---|
| identical | match | — |
| same MAJOR.MINOR, different PATCH | compatible | works; a warning is logged |
| different MAJOR or MINOR, or unknown | incompatible | every tool fails with `PLUGIN_VERSION_MISMATCH` (hint: `gimp-mcp install-plugin`, then restart GIMP) |

`gimp_status` and `gimp-mcp doctor` show both versions and the verdict.
* **GIMP-dependent**: procedure availability and names (`gimp_call_procedure`,
  `gimp_search_procedures`), fonts and rendering details. The coverage matrix
  (`docs/coverage.md`) is regenerated for each supported GIMP version.

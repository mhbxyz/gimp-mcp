# Changelog

All notable changes are documented here. The project follows
[Semantic Versioning](https://semver.org/); see `docs/compatibility.md` for
what is covered by the compatibility promise.

## [Unreleased]

### Added

- `gimp-mcp doctor` detects the known installation problems (GIMP missing or
  too old, GIMP's Python without PyGObject, virtualenv first on PATH, plug-in
  missing/not executable/other version/not registered, wrong profile, stale
  socket, permissions, GIMP running without the bridge, several instances) and
  prints a fix for each; `--json` output and documented exit codes;
  `docs/troubleshooting.md` is generated from its checks (#39).
- Release workflow publishes the same artifacts to TestPyPI, then to PyPI,
  with trusted publishing (no stored token) and maintainer approval, and
  verifies each index serves exactly the built files and that the installed
  package (pip and uvx) drives a real GIMP (#36).
- The package page on PyPI has absolute links, Python version classifiers and
  project URLs (#36).
- The plug-in reports its version; the server refuses an incompatible plug-in
  with `PLUGIN_VERSION_MISMATCH` and warns on a different patch version.
  `gimp_status` and `gimp-mcp doctor` show both versions (#35).

### Changed

- The version is defined only in `pyproject.toml`; the installed plug-in gets
  it from a `VERSION` file written by `gimp-mcp install-plugin` (#35).

## [0.1.0] - 2026-11-07

First usable release. Linux only, GIMP 3.2+.

### Added

- Bridge between GIMP 3.2 and MCP: a persistent GIMP plug-in serving a private
  Unix socket (token, peer-uid check, no network), and `gimp-mcp serve`, an MCP
  server on stdio with structured errors and session-bound ids.
- Session and inspection: `gimp_status`, `gimp_inspect_image`,
  `gimp_inspect_item`, `gimp_preview`.
- Files: `gimp_create_image`, `gimp_open_image`, `gimp_save_image` (XCF),
  `gimp_export_image` (PNG/JPEG with explicit options), `gimp_close_image`.
- Layers and groups: create, import, duplicate, properties and locks, move,
  delete; geometry: scale/resize canvas/crop images, move/scale/rotate/flip
  layers.
- Selections and masks, painting (fill, polylines, shapes), corrections and
  filters (destructive or editable), editable text layers and fonts.
- History: undo groups closed on disconnect; checkpoints to undo/redo.
- Discovery and generic access: PDB search/description, allowlisted
  `gimp_call_procedure`, `gimp-mcp inventory` and a versioned coverage matrix.
- CLI: `serve`, `install-plugin`, `uninstall-plugin`, `doctor`, `inventory`,
  `coverage`.
- Demo (`demo/thumbnail.py`) building a 1280×720 thumbnail through MCP only.
- CI with a real GIMP 3.2.6 pinned through an Arch Linux Archive snapshot.

[0.1.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.1.0

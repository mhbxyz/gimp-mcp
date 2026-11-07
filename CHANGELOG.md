# Changelog

All notable changes are documented here. The project follows
[Semantic Versioning](https://semver.org/); see `docs/compatibility.md` for
what is covered by the compatibility promise.

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

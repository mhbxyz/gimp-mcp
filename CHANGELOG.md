# Changelog

All notable changes are documented here. The project follows
[Semantic Versioning](https://semver.org/); see `docs/compatibility.md` for
what is covered by the compatibility promise.

## [Unreleased]

### Added

- Toolsets (#45): tools are grouped (`core`, `files`, `layers`, `transform`, `selection`, `paint`,
  `filters`, `text`, `history`, `procedures`); the server lists only the enabled ones. Choose them with
  `gimp-mcp serve --toolsets` or `GIMP_MCP_TOOLSETS`; agents list them with `gimp_list_toolsets` and
  add more during a session with `gimp_enable_toolsets` (the client is notified that its tool list
  changed). `gimp-mcp toolsets` prints the catalog and the size of each toolset. See docs/toolsets.md.
- Analysis toolset (#46, read-only): `gimp_histogram` (per-channel statistics, percentiles and
  histogram of a composite, layer, region or selection), `gimp_sample_colors` (points, averaging
  radius), `gimp_compare` (images, layers or checkpoints: changed pixels, bounds, mean/max difference,
  difference preview), `gimp_dominant_colors`, `gimp_preview_region` (full-resolution crops).

### Fixed

- `gimp-mcp doctor` reported "GIMP is running but its bridge does not answer" for a stale socket
  when some other GIMP was running; it now says the socket is stale and that another GIMP runs.

### Changed

- The default tool list no longer includes the `procedures` toolset (`gimp_search_procedures`,
  `gimp_describe_procedure`, `gimp_list_callable_procedures`, `gimp_call_procedure`): add it with
  `--toolsets default,procedures` or `gimp_enable_toolsets`.

### Documentation

- The README now opens with a demo: a real Claude Code session driving GIMP through gimp-mcp
  (animated WebP, full-quality MP4 attached to the v0.2.0 release), followed by what the project
  is for, example prompts and a capability overview. The quickstart is unchanged.
- `demo/video/record.sh` re-records that demo reproducibly (Docker, Xvfb, the published package).

## [0.2.0] - 2026-11-08

Installing and releasing made easy. Linux only, GIMP 3.2+.

### Upgrade note

The plug-in and the server must now share the same MAJOR.MINOR version: a
0.1.0 plug-in is refused by 0.2.0 with `PLUGIN_VERSION_MISMATCH`. Run
`gimp-mcp setup` (or `gimp-mcp install-plugin`) once after upgrading, then
restart GIMP.

### Added

- `gimp-mcp setup`: one guided command that finds GIMP and the profile it
  uses, installs or updates the plug-in (in every profile where it is
  installed), registers the server in Claude Code, Claude Desktop, VS Code and
  Cursor (each change shown, consent or `--yes`, backups, other servers
  untouched, snippets for other clients) and checks the result; safe to run
  again (#40, #42).
- `gimp-mcp doctor` detects the known installation problems (GIMP missing or
  too old, GIMP's Python without PyGObject, virtualenv on PATH, plug-in
  missing/not executable/other version/not registered, wrong profile, stale
  socket, permissions, GIMP running without the bridge, several instances) and
  prints a fix for each; `--json` and documented exit codes;
  `docs/troubleshooting.md` is generated from it (#39).
- `gimp-mcp uninstall` removes the plug-in from every profile and the client
  entries gimp-mcp created (consent, backups, other entries kept) and says how
  to remove the package (#42).
- GIMP from Flathub (`org.gimp.GIMP`) is supported (#41).
- Installation verified in CI on Arch Linux, Ubuntu 26.04, Debian 14,
  Fedora 44, openSUSE Tumbleweed and Alpine 3.24 with each distribution's own
  GIMP, on releases and weekly; the compatibility page is generated from that
  matrix (#38).
- The plug-in reports its version; the server refuses an incompatible plug-in
  with `PLUGIN_VERSION_MISMATCH` and warns on a patch difference;
  `gimp_status` and `doctor` show both versions (#35).
- Documentation: a three-command quickstart and one page per MCP client; their
  commands run in CI in a clean Ubuntu 26.04 and their snippets are checked
  against `setup` (#44).
- Distribution: PyPI and TestPyPI publication with trusted publishing (no
  stored token) and maintainer approval, verification of the published files
  and of the installed package (pip and `uvx`) on a real GIMP (#36); build
  provenance attestations, a release PR prepared by
  `scripts/prepare_release.py`, tagging on merge, safe re-runs, dry runs (#37);
  listing in the official MCP registry as `io.github.mhbxyz/gimp-mcp` (#43).

### Changed

- The version is defined only in `pyproject.toml`; the installed plug-in gets
  it from a `VERSION` file written at installation (#35).
- The PyPI page has absolute links, Python version classifiers and project
  URLs (#36).

### Fixed

- Every virtualenv (including `uv run`/`uvx` environments) is removed from the
  PATH GIMP gets in headless mode, and the doctor no longer reports the
  environment `uvx` runs it from (#44).
- Stopping a headless GIMP waits until all its plug-in processes are gone (#38).

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

[0.2.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.1.0

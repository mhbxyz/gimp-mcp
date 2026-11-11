# Changelog

All notable changes are documented here. The project follows
[Semantic Versioning](https://semver.org/); see `docs/compatibility.md` for
what is covered by the compatibility promise.

## [Unreleased]

### Added

- Public API contract (#116): `docs/api/contract.json` snapshots every tool (toolset, input and output
  schemas, annotations), error code, prompt, resource and CLI option (`uv run scripts/api_contract.py
  write`); the unit tests fail when it is out of date, and CI classifies every difference with the base
  branch as compatible or breaking. A breaking change needs a `### Breaking` CHANGELOG entry, and from
  1.0 on a new major version. Error codes now have one registry, listed in `docs/tools.md`.
- Deprecation policy and mechanism (#117, ADR 0011): a renamed tool keeps its old name as an alias, a
  deprecated tool or parameter keeps working until the next major version, and every call using one
  returns a notice (result `_meta` `io.github.mhbxyz/deprecations` and a text block) naming the
  replacement; the contract snapshot records deprecations.

### Changed

- The GIMP plug-in no longer has to share the server's MAJOR.MINOR version (#120, ADR 0010): any plug-in
  speaking bridge protocol 1 is accepted. Its handshake lists the operations it serves, with a revision;
  a tool that needs one the plug-in lacks fails before anything is sent with `PLUGIN_VERSION_MISMATCH`
  and the hint to run `gimp-mcp install-plugin`, then restart GIMP. `gimp_status` gains
  `plugin_compatibility` (`match`, `compatible`, `partial`), and `gimp-mcp doctor` shows the versions,
  the protocol and the verdict (a different installed version is now a warning, not a failure).

- The README demo is re-recorded with 0.6.0, through `demo/video/record.sh 0.6.0 thumbnail`.
- The README shows Linux, macOS and Windows support: platform badges and a table of what is verified
  on each OS; it also gives the current tool count (159, 50 by default) and the named pipe used on Windows.
- The eval baseline names the commit it ran on by its SHA after the history rewrite of 2026-11-09
  (`fb2b474`, was `f9d1da5`); the evaluated content is unchanged.

### Fixed

- Arguments that do not match a tool's schema no longer reach agents as raw pydantic text (#146): the
  error is `INVALID_ARGUMENT` with each field at fault, unknown argument names (with a "did you mean"),
  and a hint listing the tool's required parameters and their types. Calling a tool of a disabled
  toolset returns the new code `TOOLSET_DISABLED` with the `gimp_enable_toolsets` call to make.
- The agent evaluation runs on GitHub's runners: the container user (uid 1000) could not write its
  transcript and outputs in directories made by the runner user (uid 1001), so every session ended at once.

## [0.6.0] - 2026-11-09

### Added

- Demo: photo montage with sky replacement (#115). `uv run demo/run.py sky-replacement` replaces a sky
  through a color selection and a layer mask and warms the foreground with an editable color balance,
  checked against the known horizon and both pictures; its agent version is an evaluation task.
- Demo: print-ready A5 flyer (#114). `uv run demo/run.py print-flyer` lays out an A5 flyer with 3 mm
  bleed and safe-margin guides at 300 dpi and exports a PDF (page size checked with pypdf) and a TIFF;
  its agent version is an evaluation task.
- Demo: animated sticker (#113). `uv run demo/run.py animated-sticker` builds 12 frames where a logo
  slides and fades in, with per-frame timing and disposal, optimizes them and exports GIF and animated
  WebP under 500 KB, each frame checked; its agent version is an evaluation task.
- Demo: prepare a folder of photos for a website (#112). `uv run demo/run.py web-photo-batch` turns
  twenty photos upright from EXIF, fits them to 1600 px, converts them to sRGB, watermarks them, removes
  GPS but keeps the copyright, exports WebP and JPEG, and reports the corrupt file; its agent version is
  an evaluation task. The demos run GIMP in English (`LANG=C.UTF-8`): metadata values are localized.
- RAW files open through darktable with GIMP's interface, verified (#129): `tests/gui/test_raw.py` opens a
  synthetic DNG with `gimp_open_with_options` (`file-darktable-dng-load`), quits darktable like a user and
  checks the image GIMP receives; the Linux GUI job installs darktable 5.6.2.
- Demo: annotate a screenshot and redact private data (#111). `uv run demo/run.py screenshot-annotation`
  pixelates an e-mail address and an avatar, draws a box, an arrow and numbered callouts, and exports a
  PNG without metadata, every other pixel identical to the input; its agent version is an evaluation task.
- Demo: social media kit from one design (#110). `uv run demo/run.py social-media-kit` makes a post, a
  story, a banner and a thumbnail with safe-area guides, the brand colors, the logo and an editable
  headline, checked in the reopened XCFs and in the PNGs; its agent version is an evaluation task.
- End-to-end tests with GIMP's interface open (#105): `tests/gui` starts GIMP with a window on Linux
  (Xvfb), macOS and Windows and plays the user with the keyboard: images opened by the user are listed
  and editable, one MCP call is one step of GIMP's undo history, user edits keep ids and checkpoints, an
  image closed by the user gives `NOT_FOUND`, and the session recovers after the user quits and restarts
  GIMP. CI jobs `gui-linux`, `gui-macos`, `gui-windows`.
- Demo: product photo cut-out for an online store (#109). `uv run demo/run.py product-cutout` cuts a
  bottle out of its backdrop with a layer mask, adds a contact shadow on pure white, centers it on a
  2000×2000 square and exports JPEG and WebP at three sizes with an sRGB profile; its agent version is an
  evaluation task.
- Demo: restore an old scanned photo (#108). `uv run demo/run.py old-photo-restoration` straightens a
  tilted scan, crops the scanner bed, heals dust, clones over a scratch, restores contrast, reduces grain
  and exports a 16-bit TIFF at 300 dpi and a JPEG, each step checked against the clean print it was made
  from; its agent version is an evaluation task (passed). Agent versions of demos read their files in
  `~/inputs`; `demo/run.py --publish` copies a report to `docs/demos/`.
- Demo scenarios (#107): `uv run demo/run.py <scenario>` or `--all` runs typical GIMP jobs through
  MCP only, each declaring its toolsets, licensed assets (`demo/assets/LICENSES.md`), outputs,
  factual checks and the prompt of its agent version; `demo/video/record.sh VERSION [SCENARIO]`
  records the agent version of any scenario. The thumbnail demo is the first scenario (same outputs
  and checks, now in `demo/out/thumbnail/`); every scenario runs in the end-to-end suite on Linux,
  macOS and Windows.
- Agent evaluation suite (#106): 18 typical GIMP tasks given to a real Claude Code session in an isolated
  container (only the gimp server, default toolsets), with factual checks of the outputs;
  `uv run evals/run.py <task>|--all` reports success, tool calls, errors, duration and tokens per task
  and flags regressions against `docs/evals/baseline.json`. `evals.yml` runs it on demand and on
  release pull requests (secret `CLAUDE_CODE_OAUTH_TOKEN`).

### Changed

- The README demo is re-recorded with 0.5.0, through `demo/video/record.sh 0.5.0 thumbnail` (#107).

### Fixed

- The web photo batch demo reads a photo's EXIF orientation from the file when GIMP for Windows returns none
  (it sometimes does, #173).
- The release waits until PyPI serves a new version to both pip and uv: for v0.5.0, uv could not
  resolve it on the macOS runner seconds after pip could, and the verification failed (passed on re-run).

## [0.5.0] - 2026-11-08

### Added

- Windows support (#100): GIMP 3.2 from gimp.org's installer, verified by the end-to-end suite on GitHub's
  Windows Server 2025 runner. The bridge serves a named pipe that only the current user can open (owner-only
  DACL, remote clients rejected, first instance only), checks the client's and the server's process owner,
  and keeps the token handshake; nothing listens on the network (tested).
- macOS support (#99): GIMP 3.2 from gimp.org on Apple Silicon, verified by the full end-to-end suite
  on GitHub's macOS 15 runner; the bridge's Unix socket checks the peer with `LOCAL_PEERCRED`.
- `gimp-mcp install-plugin`, `setup` and `uninstall` on macOS and Windows (#101): GIMP profile and
  Claude Desktop, Cursor and VS Code configurations at each OS's place (`~/Library/Application Support`,
  `%APPDATA%`, `%USERPROFILE%`), with the same backups; on Windows the configured command is the
  environment's `Scripts\gimp-mcp.exe` (or `uvx`), and works from a path with spaces.

- `gimp-mcp doctor` on macOS and Windows (#103): each fix is written for the OS it is shown on
  (where gimp.org's GIMP is looked for, the default profile, the pipe), GIMP's bundled Python is the
  one checked, and running GIMP processes are listed there too (`ps`, `tasklist`), so the
  `instances` check and "GIMP runs but does not answer" work on every OS. `docs/troubleshooting.md`
  gives the fix of each OS; install, architecture, compatibility (verified platform matrix), client
  guides and the README cover Linux, macOS and Windows.

### Changed

- Releases are tested and verified on Linux, macOS and Windows (#104): the full suite runs with a real
  GIMP on each OS before anything is published (the built wheel is the one installed), and the
  packages on TestPyPI and PyPI are installed and drive GIMP on each OS before PyPI, the public
  GitHub release and the MCP registry.
- The README demo is re-recorded with 0.4.0.
- OS-specific locations (GIMP profile, client configuration folders, bridge address, headless GIMP)
  come from one platform layer that knows Linux, macOS and Windows (#98, ADR 0008). Linux behaves as
  before; `gimp-mcp doctor` skips the GIMP-process check where it cannot list processes.

### Fixed

- `gimp-mcp setup` and `uninstall` print `+`, `x` and `->` instead of `\u2713`-style escapes when their
  output goes to a console or file that cannot encode the symbols (Windows redirects in cp1252) (#103).
- `gimp-mcp doctor` uses `%USERPROFILE%` as home on Windows, even when `HOME` is set (#103).
- `gimp-mcp doctor` no longer stops (exit code 2) on Windows when `GIMP_MCP_SOCKET` is a file path: the
  socket-permissions check is skipped there (#103).
- macOS: the bridge plug-in no longer crashes while listing filters. Operations with a format, pointer or
  buffer parameter (read from GEGL, which the plug-in now initializes) are never instantiated: libgimp
  cannot carry those values, and doing it corrupted the plug-in on macOS. Of the 200 operations GIMP
  3.2.6 offers, only `gegl:checkerboard` changes: it was listed as supported although its `format`
  parameter was silently dropped, and is now refused with that reason. Enum parameters are listed from
  the class of one of their values, once per enum type, instead of `pspec.enum_class`, which crashed the
  plug-in after a few hundred lookups; operations refused by name are no longer instantiated (#99).
- `gimp-mcp doctor` checks the Python bundled with GIMP on macOS and Windows instead of the system
  `python3` (#99).
- The release workflow waits for PyPI's index to serve a new version before installing it: v0.4.0's
  check ran before PyPI's CDN had the release, which stopped the MCP registry and the public release.
- Text files are read and written as UTF-8 on every OS (the default encoding is not UTF-8 on Windows).

### Security

- File tools refuse Windows network (UNC) and device paths and reserved device names: opening a
  UNC path sends the user's credentials to that machine (#102, `docs/security.md#file-paths`).
- Batch globs decide "inside the directory" by file identity, so Windows junctions, case and
  Unicode spellings cannot escape it; an output that is an input under another spelling (`A.PNG`
  for `a.png` on macOS or Windows, another Unicode form on macOS) is refused, and so are two
  outputs the OS would name alike (#102).

- The bridge refuses a connection whose peer uid it cannot read; it used to accept it, which mattered
  on systems without `SO_PEERCRED`. On macOS the uid now comes from `LOCAL_PEERCRED` (#98).

## [0.4.0] - 2026-11-08

### Added

- `gimp_import_palette` imports Adobe Color Tables (`.act`), Photoshop swatches (`.aco`), Adobe Swatch
  Exchange (`.ase`) and RIFF or Paint Shop Pro palettes (`.pal`) by converting them to `.gpl` (#81).
  Their RGB, HSB and grayscale colors are imported; CMYK and Lab colors are refused.
- `gimp_text_along_path` (toolset `paths`) lays a text layer's glyph outlines along a path as a new,
  editable path, with GIMP's Text along Path algorithm (#88): GIMP 3.2 has no procedure for it.

### Changed

- `gimp_open_with_options` loads only the requested PDF pages, in the order given, instead of loading
  every page and removing the others (#86). Page numbers still start at 1.

### Fixed

- `demo/video/record.sh` resolves a relative output directory from the caller's directory, not
  from `demo/video/`. The README demo is re-recorded with 0.3.0.

## [0.3.0] - 2026-11-08

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
- Effects toolset (#47): the whole GEGL filter catalog (about 200 operations, parameters introspected
  from GIMP and validated before anything changes) with `gimp_list_filter_operations`,
  `gimp_describe_filter_operation`, `gimp_apply_filter` (editable or destructive), and editable-filter
  management: `gimp_inspect_filter`, `gimp_set_filter` (parameters, visibility, opacity, blend mode),
  `gimp_move_filter`, `gimp_merge_filters`. New error code `UNSUPPORTED`.
- Color toolset (#48): `gimp_levels`, `gimp_curves`, `gimp_color_balance`, `gimp_colorize`,
  `gimp_desaturate`, `gimp_invert`, `gimp_threshold`, `gimp_posterize`, `gimp_exposure`,
  `gimp_shadows_highlights` and `gimp_auto_adjust` (white balance, equalize, stretch contrast), with
  the ranges of GIMP's dialogs, editable or destructive.
- Modes toolset (#49): `gimp_convert_mode` (RGB, grayscale, indexed with generated, web, mono or
  custom palettes and dithering), `gimp_convert_precision` (8 to 64 bits, linear or not),
  `gimp_get_color_profile` and `gimp_set_color_profile` (assign, convert with rendering intent and
  black point compensation, remove; built-in or ICC file). PNG and JPEG exports take
  `color_profile` (default: embed only a profile the image has; GIMP's own default never embeds).
- Paths toolset (#50): create paths from polylines, Bézier segments, ellipses or a text layer's
  outline; inspect, rename, show, duplicate, delete; edit strokes; length and point at distance;
  path ↔ selection; stroke (line or brush) and fill; SVG import and export. `gimp_inspect_image`
  lists the image's paths.
- Resources toolset (#52): list and inspect brushes, gradients, patterns and palettes with previews;
  create, edit (generated brushes, gradient segments, palette entries), duplicate, rename and delete
  user resources (built-ins are read-only: new error code `READ_ONLY`); import `.gpl` palettes and
  export palettes as gpl, css, text, python, php, java or kpl.
- Compose toolset (#54): copy/cut and paste through named GIMP buffers (the user's clipboard stays
  untouched; pastes never leave a floating selection), merge down/group/visible, flatten, new layer
  from visible, alpha channel and alpha to selection, layer boundary and crop to content, align and
  distribute layers.
- Document toolset (#60): guides and sample points (with their colors), Exif/XMP/IPTC metadata and
  comment, resolution and print size with units (`gimp_inspect_image` reports the unit).
- Formats toolset (#58): export to every format GIMP writes (WebP, AVIF/HEIF, TIFF, BMP, GIF, ICO, PDF,
  PSD, JPEG XL…) with options introspected from GIMP and a report of lossless/lossy and what happens to
  layers; open PDF (pages, size), SVG (size), PSD and multi-page TIFF with options; export layers to
  separate files and regions (slices).
- Painting toolset (#53): paint strokes with GIMP's paintbrush, pencil, airbrush, ink, eraser, smudge,
  dodge/burn, clone and heal (brush, size, hardness, spacing, dynamics all explicit; GIMP's context is
  restored), gradient fills (named or inline gradients, every shape and repeat mode) and bucket fill
  by similar colors or selection with a color, pattern or gradient.
- Geometry toolset (#55): perspective, shear, 3×3 matrices and rotation around any point for layers,
  groups, paths, channels and the selection; whole-image rotation and flips. `gimp_resize_canvas` can
  resize the layers with the canvas and fill the new areas.
- Channels toolset (#51): select by color and fuzzy select (threshold, criterion, sample merged), select
  from alpha, text, paths and channels; grow, shrink, border, feather, sharpen, round, remove holes,
  translate; channels (empty, saved selection, color component) that can be changed, combined and
  deleted. `gimp_inspect_image` lists the image's channels.
- Vector toolset (#57): GIMP 3.2 vector layers (a path rendered with editable fill and stroke) and link
  layers (an external image file); both have their own `kind` in inspection and are refused by
  painting and destructive filters instead of being rasterized.
- Typography toolset (#56): rich text through validated Pango markup, text outlines, kerning, hinting,
  indentation, language, base direction (right-to-left scripts verified with Hebrew, vertical text) and
  fixed text boxes, all keeping text layers editable and surviving XCF round trips.
- Animation toolset (#59): frames as layers with duration and disposal, frame previews, GIMP's animation
  optimizer, animated GIF and WebP export (verified frame by frame).
- Batch toolset (#61): `gimp_run_batch` runs a recipe of tool calls (with placeholders such as
  `{image}`, `{layer}`, `{stem}`, `{output}`) over explicit files or a glob confined to a directory.
  The whole recipe, inputs and outputs are validated before the first file is opened; outputs follow
  a naming pattern and are never overwritten unless asked; the report gives each file's status,
  failed step and outputs; every image the batch opened is closed; `continue_on_error` and
  `dry_run`. See docs/adr/0006-batch-recipes.md.

- MCP resources, prompts and progress (#62): `gimp://images` and, for every open image, its layer
  tree and a PNG preview, with list-change notifications when images are opened or closed; prompts
  for thumbnails, background removal, photo touch-up and batch export; progress heartbeats during
  slow GIMP operations and per-file progress in batches. Cancellation is documented and tested: the
  operation running inside GIMP finishes, a cancelled batch stops and closes its images. See
  docs/adr/0007-resources-prompts-progress.md.

### Fixed

- `gimp-mcp doctor` reported "GIMP is running but its bridge does not answer" for a stale socket
  when some other GIMP was running; it now says the socket is stale and that another GIMP runs.
- After a cancelled or timed-out request, the next call waits for GIMP to finish the abandoned
  operation (up to the request timeout) instead of failing with `BRIDGE_UNAVAILABLE` after 3 s.

### Changed

- Exports write no metadata unless asked: new `metadata` list in `png_options` / `jpeg_options`
  (default empty, which is what v0.2.0 did implicitly).
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

[0.6.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.6.0
[0.5.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.5.0
[0.4.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.4.0
[0.3.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.1.0

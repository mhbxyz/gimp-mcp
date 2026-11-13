# Upgrading

What changes for clients between versions, and how to migrate: every breaking change since 0.3.0, with
a call before and after. Deprecated forms keep working until the next major version and return a
deprecation notice on every call ([deprecation policy](compatibility.md#deprecations), ADR 0011); what
1.x guarantees is in [compatibility.md](compatibility.md#the-1x-compatibility-promise);
`CHANGELOG.md` lists every change.

## 0.7 → 1.0

### Removed: the parameter names deprecated in 0.7

Calls that still used them (and got a deprecation notice) must use the new names; the old ones are now
`INVALID_ARGUMENT` ("unknown argument … did you mean …").

| Before (0.7, deprecated) | After (1.0) |
|---|---|
| `gimp_set_channel({"channel_id": "item:7@…", "opacity": 50})` | `gimp_set_channel({"channel": "item:7@…", "opacity": 50})` |
| `gimp_combine_channels({"channel_id": "item:7@…", "other": "item:8@…"})` | `gimp_combine_channels({"channel": "item:7@…", "other": "item:8@…"})` |
| `gimp_delete_channel({"channel_id": "item:7@…"})` | `gimp_delete_channel({"channel": "item:7@…"})` |
| `gimp_remove_guide({"image": "image:1@…", "id": 3, "kind": "sample_point"})` | `gimp_remove_guide({"image": "image:1@…", "guide": 3, "kind": "sample-point"})` |
| `gimp_import_palette({"file": "/home/me/team.gpl"})` | `gimp_import_palette({"path": "/home/me/team.gpl"})` |
| `gimp_export_palette({"name": "Team", "file": "/home/me/team.css", "format": "css"})` | `gimp_export_palette({"name": "Team", "path": "/home/me/team.css", "format": "css"})` |
| `gimp_create_link_layer({"image": "image:1@…", "file": "/home/me/logo.svg"})` | `gimp_create_link_layer({"image": "image:1@…", "path": "/home/me/logo.svg"})` |
| `gimp_set_link_layer({"item": "item:9@…", "file": "/home/me/logo2.svg"})` | `gimp_set_link_layer({"item": "item:9@…", "path": "/home/me/logo2.svg"})` |

### Batch recipe steps refuse unknown keys

`{"tool": "gimp_resize_image", "args": {...}}` used to run the step without its arguments; it is now
`INVALID_ARGUMENT` (`recipe.0.args: unknown key; expected: tool, arguments`). Write
`{"tool": "gimp_resize_image", "arguments": {...}}`.

### Security review (#122)

Calls that could write a script, read a private file or leave the chosen folder are now refused with
`INVALID_ARGUMENT` before anything runs ([security model](security.md)).

| Before (0.7) | After (1.0) |
|---|---|
| `gimp_export_palette({"name": "Team", "path": "/home/me/team.text", "format": "text"})` | the path ends with the format's extension: `"/home/me/team.txt"` (`.gpl`, `.css`, `.txt`, `.py`, `.php`, `.java`, `.kpl`) |
| `gimp_export_palette({..., "format": "python"})` of a palette whose names hold quotes, backslashes, `<>`, `{}` or control characters | refused for the css, python, php and java exports: rename the entries, or export as `gpl` |
| `gimp_export_path_svg({"image": …, "file": "/home/me/paths.txt"})` | `"file": "/home/me/paths.svg"` |
| `gimp_export_layers({..., "template": "sub/{index}"})` or `"{index:0999999999d}"` | a file name without `/`, `\` or `:`, widths of at most three digits: `"sub-{index:03d}"` |
| `gimp_run_batch({..., "output": "/out/{stem:>500}.png"})` | widths of at most three digits, no `!r` conversion |
| `gimp_call_procedure({"name": "plug-in-gmic-qt", …})` (any third-party plug-in) | only the `plug-in-*` procedures shipped with GIMP are callable |
| `gimp_open_with_options({"path": "/home/me/notes.txt", "procedure": "file-raw-load"})` | `file-raw-load` opens `.data` and `.raw` files only |
| `gimp_export_as({..., "path": "/out/a.html", "options": {"source-file": true}})` | give the characters in `characters`; `source-file` is refused |

Annotations: `gimp_export_as`, `gimp_export_layers`, `gimp_export_region`, `gimp_export_animation`,
`gimp_export_palette` and `gimp_export_path_svg` can replace a file, so they now carry
`destructiveHint: true` (and `gimp_export_path_svg` is no longer `readOnlyHint`). A client that
auto-approves read-only or non-destructive tools now asks before them.

## 0.6 → 0.7

### Renamed parameters (old names deprecated in 0.7, removed in 1.0.0: see above)

| Tool | Old | New |
|---|---|---|
| `gimp_set_channel`, `gimp_combine_channels`, `gimp_delete_channel` | `channel_id` | `channel` |
| `gimp_remove_guide` | `id` | `guide` |
| `gimp_remove_guide` | `kind="sample_point"` | `kind="sample-point"` |
| `gimp_import_palette`, `gimp_export_palette` | `file` | `path` |
| `gimp_create_link_layer`, `gimp_set_link_layer` | `file` | `path` |

A call with the old name works and returns, in the result's `_meta`,
`"io.github.mhbxyz/deprecations": [{"name": "gimp_set_channel.channel_id", "since": "0.7.0",
"removal": "1.0.0", "replacement": "use channel"}]`, plus a `Deprecation notice: …` text block. Giving
both names with different values is `INVALID_ARGUMENT`.

### Moved tools (breaking for clients that list toolsets explicitly)

* `gimp_rotate_image` is in `transform` (default), no longer in `geometry`.
* `gimp_begin_undo_group` and `gimp_end_undo_group` are in the new optional toolset `undo`, no longer
  in `history`.

| Before (0.6) | After (0.7) |
|---|---|
| `gimp-mcp serve --toolsets files,geometry` to rotate images | `gimp-mcp serve --toolsets files,transform` (or the default) |
| `GIMP_MCP_TOOLSETS=core,history` for undo groups | `GIMP_MCP_TOOLSETS=core,history,undo`, or `gimp_enable_toolsets({"toolsets": ["undo"]})` |

### PNG exports without the export time

| Before (0.6) | After (0.7) |
|---|---|
| `gimp_export_image({"image": …, "path": "/out/a.png"})` wrote a `tIME` chunk | the same call writes none; `"png_options": {"metadata": ["time"]}` writes it |

### Argument errors

| Before (0.6) | After (0.7) |
|---|---|
| text `Error executing tool gimp_convert_mode: 2 validation errors for gimp_convert_modeArguments …` | `isError` with `{"error": {"code": "INVALID_ARGUMENT", "details": {"errors": [{"field": "image", "problem": "missing"}, …], "required": ["image", "mode"]}, "hint": "gimp_convert_mode requires image (string), mode ('rgb'\|'gray'\|'indexed'); …"}}` |
| a tool of a disabled toolset: the client's own "unknown tool" error | `TOOLSET_DISABLED` with the `gimp_enable_toolsets` call to make |

### Plug-in and server versions

| Before (0.6) | After (0.7) |
|---|---|
| a plug-in of another MAJOR.MINOR: every tool fails with `PLUGIN_VERSION_MISMATCH` | any plug-in speaking bridge protocol 1 works; only a tool needing an operation it lacks fails with `PLUGIN_VERSION_MISMATCH` (run `gimp-mcp install-plugin`, restart GIMP) |

### New behaviour to know (compatible)

* Every result that creates or changes an image or item names it in a top-level `id`.
* `gimp_paint_stroke` with `clone`/`heal` copies from the painted layer unless `source` is given.
* `gimp_get_metadata` adds `raw` (untranslated values); `gimp_export_as` adds `layers="flatten"` and
  `color_profile`; `gimp_resize_image` and `gimp_scale_layer` accept one dimension.

## 0.5 → 0.6 and 0.4 → 0.5

No change to the public API: new demos, tests, platforms (Windows and macOS in 0.5) and the evaluation
suite. On Windows and macOS, run `gimp-mcp setup`, which installs the plug-in in the right profile.

## 0.3 → 0.4

| Before (0.3) | After (0.4) |
|---|---|
| `gimp_open_with_options({"path": "/doc.pdf", "options": {"pages": [3, 1]}})` loaded every page, then removed the others | the same call loads only pages 3 and 1, in that order (page 1 on top); page numbers still start at 1 |

## 0.2 → 0.3

| Before (0.2) | After (0.3) |
|---|---|
| `gimp_call_procedure` and the other `procedures` tools were listed by default | add them with `--toolsets default,procedures` or `gimp_enable_toolsets({"toolsets": ["procedures"]})` |
| exports wrote no metadata, implicitly | the same, explicitly: `"png_options": {"metadata": ["exif", "xmp"]}` (or `jpeg_options`) writes what is listed |

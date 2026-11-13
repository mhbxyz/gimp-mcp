# Upgrading

What changes for clients between versions, and how to migrate. Deprecated forms keep working until the
next major version and return a deprecation notice on every call
([deprecation policy](compatibility.md#deprecations), ADR 0011); `CHANGELOG.md` lists every change.

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
  in `history`: add `undo` to `--toolsets` / `GIMP_MCP_TOOLSETS`, or call
  `gimp_enable_toolsets(["undo"])`.

### New behaviour to know

* Every result that creates or changes an image or item names it in a top-level `id`.
* Argument errors are `INVALID_ARGUMENT` with `details.errors` (no framework text); a tool of a
  disabled toolset answers `TOOLSET_DISABLED`.
* PNG exports no longer write the `tIME` chunk unless `png_options.metadata` contains `time`.
* The plug-in no longer has to match the server's minor version; tools that need operations an older
  plug-in lacks fail with `PLUGIN_VERSION_MISMATCH`: run `gimp-mcp install-plugin`, then restart GIMP.

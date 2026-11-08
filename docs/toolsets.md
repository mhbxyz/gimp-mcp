# Toolsets

Every tool belongs to one **toolset**. The server lists only the tools of the enabled toolsets, so
a client loads what it needs and no more: long tool lists cost context, slow models down, make tool
choice worse, and some clients cap the number of tools.

```sh
gimp-mcp toolsets          # every toolset, its tools and the size of their definitions
```

## Choosing toolsets

| How | Example |
|---|---|
| Nothing configured | the **default** toolsets (marked below) |
| Command line | `gimp-mcp serve --toolsets files,layers,text` |
| Environment | `GIMP_MCP_TOOLSETS=default,procedures` |
| During a session | the agent calls `gimp_list_toolsets`, then `gimp_enable_toolsets` |

* Names are comma-separated and case-insensitive. `default` stands for the default toolsets, `all`
  for every toolset; they combine with names (`default,procedures`).
* `core` is always enabled.
* `--toolsets` wins over `GIMP_MCP_TOOLSETS`. An unknown name stops the server at start with the
  list of valid names (exit code 2).
* `gimp_enable_toolsets` adds tools for the rest of the session and notifies the client that the
  tool list changed (`notifications/tools/list_changed`, or the `subscriptions/listen` stream with
  the 2026 protocol). Clients that don't refresh their tool list on that notification only see the
  new tools after a restart with the toolsets in `--toolsets` or `GIMP_MCP_TOOLSETS`.

### Budget

The default selection is kept under **50 tools and 140 000 bytes** of tool definitions (name,
description, input and output schemas, as sent in `tools/list`). `tests/unit/test_toolsets.py`
fails when it grows beyond that. New features go into their own toolsets unless they belong to the
everyday workflow. `gimp-mcp toolsets` prints the current numbers.

## Per client

Clients pass the toolsets as server arguments or environment. The `setup` command writes the default
configuration; edit it to narrow or extend the toolsets.

* **Claude Code**:
  `claude mcp add --transport stdio --scope user gimp -- uvx gimp-mcp serve --toolsets default,procedures`
* **Claude Desktop, Cursor** (`mcpServers` JSON):

  ```json
  {"mcpServers": {"gimp": {"command": "uvx", "args": ["gimp-mcp", "serve", "--toolsets", "files,layers,text"]}}}
  ```

* **VS Code** (`mcp.json`): `"args": ["gimp-mcp", "serve"], "env": {"GIMP_MCP_TOOLSETS": "default"}`.

Rules of thumb:

* Most clients work well with the default.
* If your client caps the number of tools (counted across all MCP servers) or warns about too many
  tools, list only what your work needs, e.g. `files,layers,text` (21 tools with `core`). The agent
  can still enable more with `gimp_enable_toolsets` if the client refreshes its tool list.
* Add `analysis` when the agent should check its edits with numbers (histograms, comparisons).
* Add `procedures` for scripted or unusual work: it reaches about 420 allowlisted GIMP procedures.
* Batch or CI scripts that know exactly what they call can list just those toolsets, like
  `demo/thumbnail.py`.

## The toolsets

### `core`

Always enabled. Connection status, inspection, previews and toolset management:
`gimp_status`, `gimp_list_toolsets`, `gimp_enable_toolsets`, `gimp_inspect_image`,
`gimp_inspect_item`, `gimp_preview`.

### `files`

Default. Create, open, save, export and close images: `gimp_create_image`, `gimp_open_image`,
`gimp_save_image`, `gimp_export_image`, `gimp_close_image`.

### `layers`

Default. Create, import, duplicate, group, reorder, change and delete layers: `gimp_create_layer`,
`gimp_create_group`, `gimp_import_layer`, `gimp_duplicate_layer`, `gimp_set_layer_properties`,
`gimp_move_layer`, `gimp_delete_layer`.

### `transform`

Default. Scale and crop images, resize the canvas, move, scale, rotate and flip layers:
`gimp_resize_image`, `gimp_resize_canvas`, `gimp_crop_image`, `gimp_set_layer_offsets`,
`gimp_scale_layer`, `gimp_rotate_layer`, `gimp_flip_layer`.

### `selection`

Default. Rectangle and ellipse selections, selection state, layer masks: `gimp_select_rectangle`,
`gimp_select_ellipse`, `gimp_modify_selection`, `gimp_get_selection`, `gimp_add_layer_mask`,
`gimp_set_layer_mask`, `gimp_remove_layer_mask`.

### `paint`

Default. Fill areas, draw paths and shapes: `gimp_fill`, `gimp_draw_path`, `gimp_draw_shape`.

### `filters`

Default. Color corrections and blur, destructive or as editable filters: `gimp_brightness_contrast`,
`gimp_hue_saturation`, `gimp_gaussian_blur`, `gimp_list_filters`, `gimp_remove_filter`.

### `text`

Default. Editable text layers and fonts: `gimp_create_text_layer`, `gimp_set_text`,
`gimp_inspect_text`, `gimp_list_fonts`.

### `history`

Default. Undo groups and checkpoints: `gimp_begin_undo_group`, `gimp_end_undo_group`,
`gimp_create_checkpoint`, `gimp_list_checkpoints`, `gimp_restore_checkpoint`,
`gimp_delete_checkpoint`.

### `analysis`

Not in the default. Measure pixels, read-only: `gimp_histogram`, `gimp_sample_colors`,
`gimp_compare`, `gimp_dominant_colors`, `gimp_preview_region`.

### `procedures`

Not in the default. Search, describe and call allowlisted GIMP procedures: `gimp_search_procedures`,
`gimp_describe_procedure`, `gimp_list_callable_procedures`, `gimp_call_procedure`.

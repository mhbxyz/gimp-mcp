# Guide: build a thumbnail through MCP

This walk-through builds a 1280×720 thumbnail from a source picture, with an
editable title, using only MCP tool calls. It is what the `thumbnail` demo scenario
(`demo/scenarios/thumbnail.py`) does (run it with `uv run demo/run.py thumbnail`; it writes `demo/out/thumbnail/report.md`
with every call, its duration and the verifications). Any MCP client works:
the calls below are plain `tools/call` requests, independent of the model or
the client library.

## 0. Connect

```json
{"name": "gimp_status", "arguments": {}}
→ {"connected": true, "gimp_version": "3.2.6", "session_id": "e5fec992", "images": []}
```

Ids returned by the tools (`image:…@e5fec992`, `item:…@e5fec992`) are passed
back verbatim.

## 1. Canvas and structure

```json
{"name": "gimp_create_image", "arguments": {"width": 1280, "height": 720, "fill": "#0d0b1a"}}
{"name": "gimp_create_group", "arguments": {"image": "<image>", "name": "Backdrop"}}
{"name": "gimp_create_group", "arguments": {"image": "<image>", "name": "Subject"}}
{"name": "gimp_create_group", "arguments": {"image": "<image>", "name": "Title"}}
```

Each new group is inserted at position 0 (top), so `Title` ends above
`Subject` above `Backdrop`.

## 2. Backdrop: the picture, covering the canvas, blurred and toned down

```json
{"name": "gimp_import_layer", "arguments": {"image": "<image>", "path": "/abs/path/lake-sunset.png", "name": "Backdrop photo", "parent": "<Backdrop>"}}
{"name": "gimp_scale_layer", "arguments": {"item": "<layer>", "width": 1280, "height": 800, "anchor": "top-left"}}
{"name": "gimp_set_layer_offsets", "arguments": {"item": "<layer>", "x": 0, "y": -40}}
{"name": "gimp_gaussian_blur", "arguments": {"item": "<layer>", "radius": 14}}
{"name": "gimp_brightness_contrast", "arguments": {"item": "<layer>", "brightness": -35, "destructive": false}}
{"name": "gimp_hue_saturation", "arguments": {"item": "<layer>", "saturation": -30, "destructive": false}}
```

The blur changes pixels; the two corrections are **editable filters** (listed
by `gimp_list_filters`, kept in the XCF, removable).

## 3. Subject with a vignette

```json
{"name": "gimp_import_layer", "arguments": {"image": "<image>", "path": "/abs/path/lake-sunset.png", "name": "Photo", "parent": "<Subject>"}}
{"name": "gimp_scale_layer", "arguments": {"item": "<photo>", "width": 880, "height": 550, "anchor": "top-left"}}
{"name": "gimp_set_layer_offsets", "arguments": {"item": "<photo>", "x": 200, "y": 20}}
{"name": "gimp_select_ellipse", "arguments": {"image": "<image>", "x": 210, "y": 30, "width": 860, "height": 530, "feather": 70}}
{"name": "gimp_add_layer_mask", "arguments": {"item": "<photo>", "fill": "selection"}}
{"name": "gimp_modify_selection", "arguments": {"image": "<image>", "action": "none"}}
```

## 4. Title

```json
{"name": "gimp_create_layer", "arguments": {"image": "<image>", "name": "Banner", "parent": "<Title>"}}
{"name": "gimp_draw_shape", "arguments": {"item": "<banner>", "shape": "rectangle", "x": 0, "y": 560, "width": 1280, "height": 160, "fill_color": "#000000", "opacity": 70}}
{"name": "gimp_create_text_layer", "arguments": {"image": "<image>", "text": "Sunset over the Lake", "font": "Sans-serif Bold", "size": 64, "color": "#ffffff", "x": 0, "y": 580, "justify": "center", "box_width": 1280, "box_height": 90, "parent": "<Title>"}}
{"name": "gimp_set_text", "arguments": {"item": "<title>", "text": "Golden Hour at the Lake"}}
```

The demo also adds an accent line (`gimp_draw_path`) and a blurred text shadow
(a second text layer with an editable blur).

## 5. Group a change, undo it, redo it

GIMP has no undo/redo for plug-ins: agents use checkpoints (see
`docs/tools.md#history-undo-groups-and-checkpoints`).

```json
{"name": "gimp_create_checkpoint", "arguments": {"image": "<image>", "label": "before badge"}}
{"name": "gimp_begin_undo_group", "arguments": {"image": "<image>", "label": "Add badge"}}
… create the badge layer, draw the circle, add the text …
{"name": "gimp_end_undo_group", "arguments": {"image": "<image>"}}
{"name": "gimp_create_checkpoint", "arguments": {"image": "<image>", "label": "with badge"}}
{"name": "gimp_restore_checkpoint", "arguments": {"image": "<image>", "checkpoint": "<before badge>"}}   ← undo
{"name": "gimp_restore_checkpoint", "arguments": {"image": "<new image>", "checkpoint": "<with badge>"}} ← redo
```

Each restoration returns a **new image id**: re-read ids with
`gimp_inspect_image` afterwards.

## 6. Verify, save, export

```json
{"name": "gimp_preview", "arguments": {"image": "<image>", "max_size": 640}}
{"name": "gimp_inspect_image", "arguments": {"image": "<image>"}}
{"name": "gimp_save_image", "arguments": {"image": "<image>", "path": "/abs/out/thumbnail.xcf", "overwrite": true}}
{"name": "gimp_export_image", "arguments": {"image": "<image>", "path": "/abs/out/thumbnail.png", "overwrite": true}}
{"name": "gimp_export_image", "arguments": {"image": "<image>", "path": "/abs/out/thumbnail.jpg", "overwrite": true, "jpeg_options": {"quality": 88}}}
```

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `GIMP_NOT_RUNNING` | GIMP not started or plug-in not installed | `gimp-mcp doctor`; start GIMP |
| `INVALID_ARGUMENT` "path … is relative" | relative path | use absolute paths (`~` allowed) |
| `FILE_EXISTS` | export/save target exists | `overwrite: true` or another path |
| `FONT_NOT_FOUND` | font not installed on the GIMP machine | `gimp_list_fonts`, use a suggestion from `details.suggestions` |
| `SESSION_CHANGED` | GIMP restarted since the ids were obtained | call `gimp_status` again |
| `EMPTY_SELECTION` | mask/fill from an empty selection | select first, or use `fill: "white"` / `area: "layer"` |
| `WRONG_KIND` | painting or destructive filter on a text layer or group | target a raster layer, or use `destructive: false` |

## Limits

* The demo checks facts (size, layer tree, editable text, filters kept in the
  XCF, pixels, files on disk). It does not judge whether the result looks good.
* Fonts and therefore exact text rendering depend on the machine running GIMP.
* The source picture is generated by `demo/assets/make_source.py` (CC0); to use
  your own picture, change `SOURCE` in the script.

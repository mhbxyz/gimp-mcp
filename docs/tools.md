# Tool reference

All tools return structured content (`structuredContent`) described by their
output schema, plus the same JSON as text. On failure `isError` is `true` and
`structuredContent` is:

```json
{"error": {"code": "NOT_FOUND", "message": "...", "hint": "...", "details": {}, "outcome": "not_applied"}}
```

`outcome`: `not_applied` (nothing changed, safe to retry), `unknown` (a
mutation may have been applied: inspect before retrying), absent for reads.

## Ids

Opaque strings bound to the GIMP session: `image:<n>@<session>` and
`item:<n>@<session>` (layers, groups, text layers, masks, channels, paths).

* **Unique** within the GIMP session: GIMP numbers images and items from two
  global counters, so an item id is unique across all open images.
* **Valid** until the object is deleted (image closed, layer removed) — then
  `NOT_FOUND` — or GIMP restarts — then `SESSION_CHANGED`, even if GIMP reused
  the same number for another object.
* Names are **not** identifiers: GIMP keeps layer names unique *within an
  image* by renaming duplicates (`Title` → `Title #1`), but the same name can
  exist in several images. Always target objects by id.
* Tools never depend on GIMP's active image/layer/selection in the UI.

## Session

### `gimp_status`

Read-only. Returns `connected`, `gimp_version`, `session_id`,
`bridge_protocol`, `socket` and `images[]` (`id`, `name` — GIMP's localized
display name —, `file`, `width`, `height`, `dirty`).

## Inspection

### `gimp_inspect_image(image)`

Read-only. Returns `id`, `name`, `file`, `xcf_file`, `imported_file`,
`exported_file`, `width`, `height` (pixels), `base_type` (`rgb`/`gray`/`indexed`),
`precision` (e.g. `u8-non-linear`), `resolution` (`x`, `y` in ppi), `dirty`
and `layers`: the layer tree, **top-most first**. Each node: `id`, `name`,
`kind` (`layer`/`group`/`text`), `parent` (group id or null), `visible`,
`opacity` (0–100), `mode` (GIMP layer-mode nick: `normal`, `multiply`…), `x`,
`y` (offset of the top-left corner, image pixels), `width`, `height`,
`has_alpha`, `locks` (`content`, `position`, `visibility`, `alpha`), `mask`
(`id`, `apply`, `show`, `edit`, or null) and `children` (groups only).

Errors: `INVALID_ID`, `NOT_FOUND`, `SESSION_CHANGED`.

### `gimp_inspect_item(item)`

Read-only. `id`, `image`, `kind` (`layer`/`group`/`text`/`mask`/`channel`/`path`),
`name`, `parent` (parent group, or the owning layer for a mask), `position`
(index in the parent, 0 = top-most; null for masks), `visible`, and for
layers the same properties as a tree node with `children` as a list of ids.

Errors: `INVALID_ID`, `NOT_FOUND`, `SESSION_CHANGED`.

## Preview

### `gimp_preview(image, max_size?)`

Read-only. Returns an MCP **image content block** (`image/png`) plus
structured metadata: `width`, `height` (preview), `source_width`,
`source_height`, `scale`, `bytes`, `downscaled_for_size`.

* `max_size`: longest side in pixels, 16–1024; default 512, configurable with
  `GIMP_MCP_PREVIEW_MAX_SIZE`. Proportions are kept; images are never upscaled.
* Response limit: if the PNG exceeds `GIMP_MCP_PREVIEW_MAX_BYTES` (default
  2 000 000 bytes, minimum 10 000), the preview is halved until it fits and
  `downscaled_for_size` is `true`.
* Fidelity: rendered by GIMP's own projection of the **visible** layers (blend
  modes, opacity, masks included) through `Gimp.Image.get_thumbnail`, with
  transparency kept as PNG alpha. Pixels are 8-bit sRGB: high bit-depth
  precision and embedded color profiles are not reproduced; small details may
  disappear when scaled down. For full resolution, export the image instead.
* Side effects: none. The image is not modified, not marked dirty, its undo
  history and saved file are untouched (verified by
  `tests/e2e/test_preview.py`).
* Why at most 1024: GIMP's thumbnail renderer returns nothing above 1024 px.

## Files

### Path rules (all file tools)

* Paths are read and written **on the machine running GIMP, with the user's
  permissions**. They must be **absolute** (`~` is expanded): GIMP and the MCP
  server do not share a working directory, so relative paths are refused
  (`INVALID_ARGUMENT`).
* Directories are never created (`WRITE_FAILED` when the parent is missing or
  not writable).
* An existing file is **never replaced** unless `overwrite: true`
  (`FILE_EXISTS`, outcome `not_applied`). The only exception is
  `gimp_save_image` without `path`, which saves the project to its own XCF file
  like GIMP's *Save*.

### `gimp_create_image(width, height, base_type="rgb", fill="white", layer_name="Background", resolution=null)`

Creates an image with one layer filled with an explicit color (`#rrggbb`,
`#rgb`, names `white`, `black`, `red`, `green`, `blue`, or `transparent` for an
alpha layer; semi-transparent fills are refused). Like *File › New*, the new
image has no unsaved changes and no undo history. Returns an image reference
(`id`, `name`, `file`, `xcf_file`, `width`, `height`, `dirty`, `layer_count`,
`displayed`). In a GUI session the image is shown in a new window.

### `gimp_open_image(path)`

Opens any file GIMP can load (XCF, PNG, JPEG, TIFF, WebP…). Errors:
`FILE_NOT_FOUND`, `PERMISSION_DENIED`, `UNSUPPORTED_FORMAT` (unknown or corrupt
content). PNG/JPEG files open as *imported* images (`xcf_file` is null).

### `gimp_save_image(image, path=null, overwrite=false)`

Saves the project as **XCF** (layers, groups, masks, text are kept) and marks
the image clean. `path` must end in `.xcf` (`UNSUPPORTED_FORMAT` otherwise);
without `path`, saves to the current XCF file (`INVALID_ARGUMENT` if the image
was never saved). Returns `xcf_file`, `bytes`, `dirty`.

### `gimp_export_image(image, path, overwrite=false, format=null, png_options=null, jpeg_options=null)`

Writes the composite of the **visible** layers to PNG or JPEG (format from the
extension `.png`, `.jpg`, `.jpeg`; `format` may confirm it). The project is not
modified and stays dirty/clean as before. Metadata (Exif, IPTC, XMP,
thumbnail, comment) is not written, for reproducible files.

| Option | Default | Range |
|---|---|---|
| `png_options.compression` | 9 | 0–9 (lossless) |
| `png_options.interlaced` | false | |
| `jpeg_options.quality` | 90 | 0–100 |
| `jpeg_options.progressive` | false (baseline) | |
| `jpeg_options.optimize` | true | |
| `jpeg_options.smoothing` | 0 | 0–1 |
| `jpeg_options.background` | `#ffffff` | color transparent pixels are flattened onto |

Returns `path`, `format`, `width`, `height`, `bytes` and the effective `options`.
Errors: `FILE_EXISTS`, `WRITE_FAILED`, `UNSUPPORTED_FORMAT` (e.g. `.gif`, `.xcf`).

### `gimp_close_image(image, discard_changes=false)`

Closes the image; refused with `UNSAVED_CHANGES` when it is dirty unless
`discard_changes: true`. The image and item ids become invalid (`NOT_FOUND`).
In a GUI session, images shown in windows the bridge did not open must be
closed in GIMP (`IMAGE_IN_USE`).

## Layers and groups

Common rules:

* Targets are explicit ids; `parent` is a **group id of the same image** or
  `null` for the top level (`WRONG_KIND` when it is not a group,
  `IMAGE_MISMATCH` when it belongs to another image).
* `position` is the index within the parent, **0 = top-most** (in front);
  values beyond the number of siblings are refused (`INVALID_ARGUMENT`).
* Units: pixels in image coordinates; `x`/`y` are the offset of the layer's
  top-left corner (may be negative or beyond the canvas). Opacity 0–100.
* `mode` is a GIMP layer-mode nick (`normal`, `multiply`, `screen`,
  `overlay`, `soft-light`, `hard-light`, `addition`, `subtract`,
  `difference`, `darken-only`, `lighten-only`, `hue`, `saturation`, `color`,
  `dodge`, `burn`, `pass-through` for groups…); unknown names are refused with
  `details.allowed`.
* GIMP keeps layer names unique in an image: the effective name is returned.
* Blending is computed by GIMP in **linear light** (50% blue multiplied over
  white is sRGB 188,188,255).
* Each tool call is **one undo step** in GIMP's history and marks the image
  dirty. All return the resulting layer node (same shape as in
  `gimp_inspect_image`).

| Tool | Effect | Destructive |
|---|---|---|
| `gimp_create_layer(image, name, parent?, position=0, width?, height?, x=0, y=0, fill="transparent", opacity=100, mode="normal", visible=true)` | New RGBA (or gray+alpha) layer, default size = image size | no |
| `gimp_create_group(image, name, parent?, position=0)` | Empty group | no |
| `gimp_import_layer(image, path, name?, parent?, position=0, x=0, y=0)` | Loads a file as **one** layer (multi-layer files are flattened); name defaults to the file name | no |
| `gimp_duplicate_layer(item, parent?, position?)` | Copies a layer or a whole group (masks, children). Default: just above the original, same parent; giving `position` without `parent` targets the top level | no |
| `gimp_set_layer_properties(item, name?, visible?, opacity?, mode?)` | Changes only the given properties (`LOCKED` if visibility is locked) | no |
| `gimp_move_layer(item, parent, position)` | Moves in the layer stack / into another group; never into itself or a descendant | no |
| `gimp_delete_layer(item)` | Removes the layer or the group **with its children**; their ids become invalid | **yes** |

## Geometry and transforms

Coordinates are image pixels, origin at the top-left corner, y downwards.
`interpolation`: `none` (nearest neighbour: exact pixels, hard edges),
`linear`, `cubic` (default), `nohalo`, `lohalo`. Each call is one undo step and
only touches the targeted image.

| Tool | Effect | Lossy / destructive |
|---|---|---|
| `gimp_resize_image(image, width, height, interpolation)` | Scales the image and all layers (sizes and offsets scale proportionally, GIMP rounds offsets) | resampled |
| `gimp_resize_canvas(image, width, height, offset_x=0, offset_y=0)` | Changes the canvas only; layers keep their pixels and move by the offset | no |
| `gimp_crop_image(image, x, y, width, height)` | Crops to a rectangle that must lie inside the canvas (`INVALID_ARGUMENT` otherwise) | **pixels outside are discarded** |
| `gimp_set_layer_offsets(item, x, y)` | Moves a layer/group's top-left corner | no |
| `gimp_scale_layer(item, width, height, anchor="center"\|"top-left", interpolation)` | Resamples a layer/group | resampled |
| `gimp_rotate_layer(item, angle, clip="adjust"\|"clip", interpolation)` | Rotates **clockwise** (degrees) around the center; `adjust` grows the bounds, `clip` keeps them; 0/360 is a no-op | resampled unless a multiple of 90 with `none` |
| `gimp_flip_layer(item, direction)` | Mirrors around the center | no |

Layer transforms are refused with `LOCKED` when the layer (or, for a group,
any descendant) has a locked position, or locked pixels for scale/rotate/flip.
Locks are set with `gimp_set_layer_properties(lock_content, lock_position,
lock_visibility, lock_alpha)`. All layer tools return the updated layer node
(new offsets and size); image tools return `width`, `height`, `dirty`.

## Discovery

Read-only introspection of the installation; **nothing is executed** and a
listed procedure is not necessarily exposed as a tool (see
[coverage.md](coverage.md)).

* `gimp_search_procedures(query="", limit=50)` → `procedures[]` (`name`,
  `description`) and `total`.
* `gimp_describe_procedure(name)` → `type` (`internal`, `plugin`,
  `persistent`, `temporary`), documentation, menu, `arguments[]` and
  `return_values[]` (`name`, GType `type`, `description`, `default`,
  `minimum`, `maximum`, `choices`). `NOT_FOUND` for unknown names.

The full inventory is written by `gimp-mcp inventory --output FILE` (needs a
running GIMP with the plug-in). Procedures whose metadata cannot be read are
listed with an `error` field instead of failing the inventory.

## Error codes

| Code | Meaning |
|---|---|
| `GIMP_NOT_RUNNING` | No bridge socket, or stale socket (GIMP exited). |
| `BRIDGE_UNAVAILABLE` | Socket present but no answer in time (GIMP busy/frozen) or token unreadable. |
| `VERSION_INCOMPATIBLE` | GIMP < 3.2 or plug-in protocol mismatch. |
| `UNAUTHORIZED` | Bad token (stale token file, wrong socket). |
| `TIMEOUT` | No answer within the request timeout; mutation outcome `unknown`. |
| `DISCONNECTED` | Connection lost during a request; mutation outcome `unknown`. |
| `PROTOCOL_ERROR` | Malformed or mismatched bridge message. |
| `SESSION_CHANGED` | Id issued by a previous GIMP session. |
| `INVALID_ID` | Malformed id or wrong kind (item id where an image id is expected…). |
| `NOT_FOUND` | The image/item no longer exists (closed, deleted). |
| `WRONG_KIND` | The id exists but designates another kind of object (e.g. a mask where a layer is required). |
| `INVALID_ARGUMENT` | An argument is out of range or inconsistent. |
| `FILE_NOT_FOUND` | Input file missing. |
| `FILE_EXISTS` | Output exists and `overwrite` is false. |
| `PERMISSION_DENIED` | Input file not readable. |
| `WRITE_FAILED` | Missing/unwritable directory or GIMP failed to write. |
| `UNSUPPORTED_FORMAT` | Extension or file content not supported by this operation. |
| `UNSAVED_CHANGES` | Closing a dirty image without `discard_changes`. |
| `IMAGE_IN_USE` | Image shown in a GIMP window the bridge did not create. |
| `IMAGE_MISMATCH` | Objects from different images combined in one operation. |
| `LOCKED` | The targeted property or content is locked in GIMP. |
| `GIMP_ERROR` | Unexpected failure inside GIMP; for a mutation the outcome is `unknown`. |

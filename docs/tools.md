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

## Toolsets

Tools are grouped into toolsets; the server lists only the enabled ones (default selection,
`gimp-mcp serve --toolsets`, `GIMP_MCP_TOOLSETS`). See [toolsets.md](toolsets.md).

### `gimp_list_toolsets`

Read-only. `toolsets[]`: `name`, `description`, `enabled`, `tools[]` (every toolset, enabled or not).

### `gimp_enable_toolsets(toolsets)`

Adds the tools of the given toolsets for the rest of the session → `enabled[]`, `added_tools[]`
(empty when they were already enabled). Notifies the client that its tool list changed.
`INVALID_ARGUMENT` (nothing enabled) for an unknown name.

## Session

### `gimp_status`

Read-only. Returns `connected`, `gimp_version`, `session_id`,
`bridge_protocol`, `server_version`, `plugin_version`, `socket` and `images[]` (`id`, `name` — GIMP's localized
display name —, `file`, `width`, `height`, `dirty`).

## Inspection

### `gimp_inspect_image(image)`

Read-only. Returns `id`, `name`, `file`, `xcf_file`, `imported_file`,
`exported_file`, `width`, `height` (pixels), `base_type` (`rgb`/`gray`/`indexed`),
`precision` (e.g. `u8-non-linear`), `resolution` (`x`, `y` in ppi), `dirty`
and `layers`: the layer tree, **top-most first**. Each node: `id`, `name`,
`kind` (`layer`/`group`/`text`/`vector`/`link`), `parent` (group id or null), `visible`,
`opacity` (0–100), `mode` (GIMP layer-mode nick: `normal`, `multiply`…), `x`,
`y` (offset of the top-left corner, image pixels), `width`, `height`,
`has_alpha`, `locks` (`content`, `position`, `visibility`, `alpha`), `mask`
(`id`, `apply`, `show`, `edit`, or null) and `children` (groups only).

Errors: `INVALID_ID`, `NOT_FOUND`, `SESSION_CHANGED`.

### `gimp_inspect_item(item)`

Read-only. `id`, `image`, `kind` (`layer`/`group`/`text`/`vector`/`link`/`mask`/`channel`/`path`),
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

## Painting

All painting tools are **destructive for the pixels they cover** (one undo
step each), target one drawable (a layer or a layer mask), and never depend on
GIMP's UI settings: each call pushes a fresh GIMP context (`context_push` +
`context_set_defaults`), sets color, opacity, blend mode, antialiasing, line
width (pixels), cap and join explicitly, strokes with a **plain line** (not
the user's brush) and pops the context afterwards.

| Tool | Effect |
|---|---|
| `gimp_fill(item, color, area="selection", opacity=100, mode="normal")` | `selection`: fills the selected part (`EMPTY_SELECTION` when nothing is selected); `layer`: fills the whole layer, ignoring the selection, which is restored afterwards |
| `gimp_draw_path(item, points, color, width=2, opacity=100, closed=false, antialias=true, cap="round", join="round")` | Polyline through `[[x, y], ...]` (image pixels, ≥ 2 points); the line is centered on the path |
| `gimp_draw_shape(item, shape, x, y, width, height, fill_color?, stroke_color?, stroke_width=2, opacity=100, antialias=true)` | Rectangle or inscribed ellipse, filled and/or outlined (stroke centered on the outline); the selection is left unchanged |

Results: `changed` and `affected` (image-space box of the pixels that may have
changed, clipped to the layer). Drawing completely outside the layer is not an
error: `changed: false`, `affected: null`, nothing is done.

Refused before any change: groups and text layers (`WRONG_KIND` — painting a
text layer would silently rasterize it), layers with locked pixels (`LOCKED`).

## Text

Text layers stay **editable**: no tool rasterizes them silently (painting and
destructive filters are refused with `WRONG_KIND`; transforms and editable
filters keep the text — `tests/e2e/test_text.py`).

* `gimp_create_text_layer(image, text, font="Sans-serif", size=32, size_unit="px", color="#000000", x=0, y=0, justify="left", letter_spacing=0, line_spacing=0, box_width?, box_height?, antialias=true, parent?, position=0)`
  — `x`, `y`: top-left corner in image pixels. `size_unit`: `px` (pixels) or
  `pt` (points, converted by GIMP with the image resolution). Without
  `box_width`/`box_height` the layer grows with the text ("dynamic" box); with
  both, the text wraps inside a fixed box of that size. Spacing in pixels.
* `gimp_set_text(item, ...)` — same properties plus `x`, `y`; only the given
  ones change. The layer is re-rendered by GIMP (not painted over).
* `gimp_inspect_text(item)` — `text`, `font`, `size`, `size_unit`, `color`
  (`#rrggbb`), `justify`, `letter_spacing`, `line_spacing`, `antialias`, `x`,
  `y`, `width`, `height`.
* `gimp_list_fonts(query="", limit=100)` — fontconfig names known to GIMP
  (`Sans-serif`, `Serif`, `Monospace` are always-available aliases).

Errors: `FONT_NOT_FOUND` (with `details.suggestions`, nothing changed),
`WRONG_KIND` for non-text targets, `LOCKED` when moving a position-locked layer.

Limits: fonts depend on the fonts installed on the machine running GIMP;
rendering of a given font name may differ between machines. Rich text
(markup), outlines, kerning, language, base direction and text on paths are not
exposed; whether a box is fixed cannot be read back through libgimp, so
`gimp_inspect_text` reports the layer's actual size.

## Corrections and filters

| Tool | Parameters (0 = unchanged) | GIMP implementation |
|---|---|---|
| `gimp_brightness_contrast(item, brightness=0, contrast=0, destructive=true)` | brightness, contrast: −100…100 (mapped to GIMP's −1…1) | destructive: `gimp-drawable-brightness-contrast`; editable: `gimp:brightness-contrast` |
| `gimp_hue_saturation(item, hue=0, saturation=0, lightness=0, hue_range="all", overlap=0, destructive=true)` | hue: −180…180°; saturation, lightness: −100…100; overlap 0…100; `hue_range`: `all`, `red`, `yellow`, `green`, `cyan`, `blue`, `magenta` | destructive: `gimp-drawable-hue-saturation`; editable: `gimp:hue-saturation` |
| `gimp_gaussian_blur(item, radius, radius_y?, destructive=true)` | radius = Gaussian standard deviation in pixels (0 < r ≤ 1500) | `gegl:gaussian-blur` (merged when destructive) |

`destructive` (verified by `tests/e2e/test_filters.py`):

* `true` — the layer's **pixels are changed** (plain layers only; `LOCKED`
  when its pixels are locked; one undo step). The result has `filter: null`.
* `false` — an **editable GIMP filter** is attached to the layer: pixels are
  untouched, the rendering changes, the filter is listed by
  `gimp_list_filters`, survives an XCF save/reopen and can be removed with
  `gimp_remove_filter`, which restores the original rendering. The returned
  `filter` id is only given after GIMP confirmed the filter is attached.

Both modes **respect the selection** at the time of the call
(`restricted_to_selection: true`); without a selection the whole layer is
affected. Groups and text layers only accept `destructive=false`
(`WRONG_KIND` otherwise, so text is never rasterized).

* `gimp_list_filters(item)` → `filters[]` (top of the filter stack first,
  i.e. most recently added first; order kept in XCF): `id`, `name`,
  `operation`, `visible`, `opacity` (0–100).
* `gimp_remove_filter(item, filter)` → remaining filters; `NOT_FOUND` when the
  filter is not on that layer.

Version note: editable filters on drawables require GIMP ≥ 3.0
(`Gimp.DrawableFilter`); verified on 3.2.6.

## Selections and masks

The selection belongs to the image: it is undoable, **marks the image dirty**
and is saved in XCF. Coordinates are image pixels; parts outside the canvas
are ignored (a rectangle entirely outside gives an empty selection).

* `gimp_select_rectangle(image, x, y, width, height, operation="replace", feather=0)`
* `gimp_select_ellipse(image, x, y, width, height, operation="replace", feather=0)`
  — ellipse inscribed in the rectangle, antialiased.
* `operation`: `replace`, `add`, `subtract`, `intersect`; `feather`: radius in
  pixels.
* `gimp_modify_selection(image, action)` — `all`, `none`, `invert`.
* `gimp_get_selection(image, probe_x?, probe_y?)` (read-only).

All return `empty`, `bounds` (`x`, `y`, `width`, `height`, clipped to the
canvas, null when empty) and `contains` (whether the probe point is selected,
when asked).

Layer masks:

| Tool | Effect | Destructive |
|---|---|---|
| `gimp_add_layer_mask(item, fill="white", invert=false)` | `fill`: `white` (all visible), `black` (all hidden), `alpha`, `selection` (`EMPTY_SELECTION` when nothing is selected), `grayscale`; refused when a mask exists | no |
| `gimp_set_layer_mask(item, apply?, show?, edit?)` | `apply=false` disables the mask without losing it | no |
| `gimp_remove_layer_mask(item, mode)` | `apply`: bakes the mask into the layer's alpha (hidden pixels become transparent); `discard`: drops it, the layer is shown unmasked | `apply`: **yes** |

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

## Generic procedure access

For operations without a dedicated tool, two tools give **controlled** access
to GIMP's procedure database:

* `gimp_list_callable_procedures(query="", limit=50)` — callable procedures
  with their signatures (same argument shape as `gimp_describe_procedure`).
* `gimp_call_procedure(name, arguments={})` — runs one of them. Arguments by
  name; values: numbers, booleans, strings (choices checked), enum **nicks**
  (`"foreground"`), colors `#rrggbb[aa]` (sRGB), image/item **ids**, lists of
  item ids (e.g. `drawables`), lists of numbers/strings. Omitted arguments keep
  GIMP's defaults, except images and items which are required. Results:
  `results` by return-value name, converted the same way (ids, nicks, colors).

**Authorization policy** (`src/gimp_mcp/plugin/gimp-mcp-bridge/gmb_policy.py`,
enforced inside GIMP, before anything runs):

1. Denied names: code evaluation (`*-eval`, Script-Fu, Python-Fu), consoles
   and servers, `gimp-quit`, `gimp-image-delete` (use `gimp_close_image`, which
   protects unsaved changes), changes to the shared GIMP context, displays/UI,
   help, PDB and plug-in management, parasites, refresh procedures, the bridge
   itself, and plug-ins acting outside the image (screenshot, e-mail, print,
   web browser, UI-only browsers and editors).
2. Allowed families only: `gimp-image-*`, `gimp-item-*`, `gimp-layer-*`,
   `gimp-group-layer-*`, `gimp-text-layer-*`, `gimp-drawable-*`,
   `gimp-selection-*`, `gimp-channel-*`, `gimp-path-*`, `gimp-context-get-*`,
   `gimp-get-*`, `plug-in-*`. Files, exports and resources are therefore
   unreachable (file tools enforce their own path rules).
3. Internal or plug-in procedures only.
4. Every argument and return value must be JSON-representable: `GFile`,
   `GBytes`, parasites, units, resources (brushes, fonts...), displays, export
   options and filters make a procedure non-callable.
5. The run mode is always `noninteractive` (`INVALID_ARGUMENT` if another one is
   requested): no dialog is opened.

Errors (all before running): `PROCEDURE_NOT_ALLOWED` (with `details.reason`),
`NOT_FOUND` (unknown procedure or object), `INVALID_ID`, `SESSION_CHANGED`,
`INVALID_ARGUMENT` (unknown name, wrong type, out of range, unknown choice).
A failure reported by GIMP while running is `GIMP_ERROR` (outcome unknown).

**Side effects** are those of the procedure: the tool is annotated as
destructive. When an image is involved the call is one undo step and marks the
image dirty. Procedure names, arguments and availability depend on the GIMP
version; check with `gimp_list_callable_procedures` (the committed matrix lists
422 callable procedures on GIMP 3.2.6).

## Advanced text (toolset `typography`)

* `gimp_set_text_style(item, markup?, outline?, kerning?, hint_style?, indent?, language?,
  base_direction?, box?)` keeps the layer editable text:
  * `markup`: Pango markup, checked before GIMP sees it (well-formed, tags `b i u s big small sub
    sup tt span`, `span` attributes such as `font`, `size`, `foreground`, `background`,
    `letter_spacing`, `rise`, `underline`, `weight`, `style`, `lang`);
  * `outline`: `mode` (`none`, `stroke-only`, `stroke-fill`), `color`, `width` (px), `cap`, `join`,
    `miter_limit`, `antialias`;
  * `kerning`, `hint_style` (`none`, `slight`, `medium`, `full`), `indent` (px of the first line),
    `language` (e.g. `ar`, `he`, `ja`), `box` (fixed width and height: wrapping and alignment);
  * `base_direction`: `ltr`, `rtl`, or vertical `ttb-rtl`, `ttb-rtl-upright`, `ttb-ltr`,
    `ttb-ltr-upright`. For horizontal text GIMP 3.2 lets Pango take the paragraph direction from
    the first strong character, so Hebrew or Arabic text lays out right to left on its own
    (verified: in `שלום A` the A is drawn left of the word); the vertical directions change the
    layout.
* `gimp_inspect_text_style(item)`: markup (null when the text has no per-run style), outline,
  kerning, hinting, indent, language, direction and size. Every property survives an XCF round
  trip (`tests/e2e/test_typography.py`).
* Text to path: `gimp_path_from_text` (toolset `paths`). Text along a path has no GIMP 3.2 API
  for plug-ins (#88).

## Vector and link layers (toolset `vector`, GIMP 3.2)

Both appear in `gimp_inspect_image` with their own `kind` (`vector`, `link`) and are kept in XCF.
Painting tools, `gimp_fill` and destructive filters refuse them (`WRONG_KIND`) instead of turning
them into pixels, as for text layers; layer tools (properties, move, duplicate, delete, transforms)
work on them.

* `gimp_create_vector_layer(path, name?, fill?, stroke?, position)`: renders a path with
  `fill` (`enabled`, `color`) and `stroke` (`enabled`, `color`, `width`, `cap`, `join`,
  `miter_limit`, `dash` in multiples of the width, `dash_offset`). `gimp_set_vector_layer` changes
  only the given values; `gimp_inspect_vector_layer` returns the path id and every setting,
  including a fill or stroke pattern set in GIMP's UI. Patterns cannot be set: GIMP 3.2 has no
  setter for them (#92).
* `gimp_create_link_layer(image, file, name?, position)`, `gimp_set_link_layer(item, file)`,
  `gimp_inspect_link_layer` (file, MIME type). The XCF stores the file's path **and** the last
  pixels: when the XCF is opened GIMP reads the file again (a changed file shows its new
  content), and when the file is gone the layer keeps the pixels saved in the XCF
  (`tests/e2e/test_vector_layers.py`).

## Advanced selections and channels (toolset `channels`)

* `gimp_select_by_color(image, color | point, item?, threshold, criterion, sample_merged,
  diagonal, antialias, feather, operation)`: with `color`, every similar pixel; with `point`, the
  contiguous area around it (fuzzy select). `criterion`: `composite`, `red`, `green`, `blue`,
  `alpha`, `hsv-hue`, `hsv-saturation`, `hsv-value`, `lch-*`. Samples `item`, the top layer by
  default, or every visible layer with `sample_merged`.
* `gimp_select_item(item, operation, antialias, feather)`: from a layer's alpha, a text layer's
  glyphs, a path's enclosed area, a channel or a mask.
* `gimp_modify_selection_shape(image, action, amount, dx, dy)`: `grow`, `shrink`, `border`
  (pixels), `feather` (radius), `sharpen` (partial → full or none), `round` (corner radius in % of
  the smaller side, GIMP's Rounded selection script), `remove-holes` (GIMP's flood), `translate`.
* Channels: `gimp_create_channel(image, name, source=empty|selection|component, component?,
  color, opacity)`, `gimp_set_channel` (name, color, opacity, visible, show_masked),
  `gimp_combine_channels(channel_id, other, operation)`, `gimp_delete_channel`. They are listed in
  `gimp_inspect_image`'s `channels` and kept in XCF; `gimp_select_item` loads one as the selection.

**Antialiasing and feathering, measured** (`tests/e2e/test_channels.py`, the selection filled with
black on white): without antialiasing an ellipse's edge pixels are fully in or out (0 or 255);
with antialiasing some are partly selected (in between). A 10 px feather on a 20 px square leaves
its center almost fully selected (< 60), its edge half selected (40-215) and pixels 9 px outside
nearly unselected (> 235); `sharpen` brings every pixel back to 0 or 255.

## Advanced transforms (toolset `geometry`)

* `gimp_transform(transform, item | image + selection=true, …, interpolation, clip)` on a layer,
  group, text layer, path, channel or the selection:
  * `perspective`: `corners` = new positions of the top-left, top-right, bottom-left and
    bottom-right corners of the item's bounds;
  * `shear`: `orientation` and `magnitude` (pixels the far edge moves);
  * `matrix`: 3×3 matrix in pixel coordinates (`[[1, 0, dx], [0, 1, dy], [0, 0, 1]]` translates);
  * `rotate`: `angle` (degrees, clockwise) around `center_x`, `center_y`.

  `clip`: `adjust` (grow to fit), `clip` (keep the original bounds), `crop` / `crop-with-aspect`
  (largest inner rectangle). With interpolation, a transformed selection gets a soft edge one pixel
  wide (`interpolation="none"` keeps it hard). Locked layers are refused (`LOCKED`).
* `gimp_rotate_image(image, 90|180|270)`, `gimp_flip_image(image, horizontal|vertical)`: the
  whole image, lossless.
* `gimp_resize_canvas` (toolset `transform`) takes `resize_layers` (`none`, `all`, or
  `image-sized` for layers that covered the old canvas) and `fill_color` for the new areas of the
  resized layers (default transparent).

## Painting with GIMP's tools (toolset `painting`)

Every setting is explicit and GIMP's context (colors, brush, dynamics…) is saved before and
restored after (checked through `gimp-context-get-*` in `tests/e2e/test_painting.py`). Like
`gimp_fill`/`gimp_draw_*`: text layers are refused (`WRONG_KIND`, never rasterized), locked pixels
are refused (`LOCKED`), the selection limits the paint. One undo step each.

* `gimp_paint_stroke(item, tool, points, color, brush?, size, hardness, spacing, dynamics?, opacity,
  mode, pressure, exposure, source?, source_x, source_y)`: `tool` is `paintbrush`, `pencil` (no
  antialiasing), `airbrush` (`pressure`), `ink`, `eraser` (to transparency, or to the background
  color without alpha), `smudge` (`pressure`), `dodge`/`burn` (`exposure`, midtones), `clone` (copies
  `source` from `source_x`/`source_y`), `heal` (same, matching the colors around). `brush` defaults
  to a generated round brush, `dynamics` to GIMP's "Dynamics Off" (names are in GIMP's language).
* `gimp_gradient_fill(item, start, end, gradient | segments, shape, repeat, offset, reverse,
  opacity, mode)`: `shape` `linear`, `bilinear`, `radial`, `square`, `conical-*`, `shapeburst-*`,
  `spiral-*`; `repeat` `none`, `sawtooth`, `triangular`. Inline `segments` make a temporary gradient,
  removed afterwards.
* `gimp_bucket_fill(item, point?, fill=color|pattern|gradient, …, threshold 0-255, criterion,
  sample_merged, fill_transparent, diagonal)`: with `point`, fills the contiguous area of similar
  colors; without, fills the selection (`EMPTY_SELECTION` if there is none). A gradient fill of
  similar colors selects them, fills, and restores the user's selection.

## File formats (toolset `formats`)

Beyond `gimp_export_image` (PNG/JPEG) and `gimp_open_image`, every GIMP file procedure is
reachable, with its **options read from GIMP** and validated before anything is written. Path rules
are the same (absolute paths, `overwrite`); metadata is written only when listed in `metadata`.

* `gimp_list_file_formats(mode=export|import)`: procedure, name and extensions. GIMP 3.2 does not
  tell plug-ins which extensions another plug-in handles: they are derived from the procedure name
  (`file-webp-export` → `webp`) with a few aliases (`tif`, `jpg`, `avif`, `heic`, `jxl`, `ora`).
* `gimp_describe_file_format(extension | procedure, mode)`: options with `kind`, range, choices,
  default.
* `gimp_export_as(image, path, options={}, metadata=[], procedure?, overwrite)`: picks the
  procedure from the extension. Returns `lossless` (`true`, `false`, or `null` when it depends on
  the content: GIF palettes, PDF) and `layers`:

  | Format | `layers` | Notes |
  |---|---|---|
  | PNG, JPEG, WebP, AVIF/HEIF, JPEG XL, BMP, GIF, TGA, QOI | `flattened` | WebP/AVIF/HEIF/JPEG XL are lossless with `lossless: true`; WebP `animation` and GIF `as-animation` give `frames` |
  | TIFF | `pages` | one page per layer (verified with Pillow) |
  | PDF | `flattened`, or `pages` with `layers-as-pages: true` | |
  | ICO | `sizes` | one icon size per layer |
  | PSD, OpenRaster | `kept` | layers stay layers |

  The image itself is never changed.
* `gimp_open_with_options(path, options={}, procedure?)`: PDF (`pages`: page numbers from 1 —
  GIMP 3.2 cannot receive its page list from a plug-in, so every page is loaded and the others
  removed; `width`, `height`, `keep-ratio`, `password`…), SVG (`width`, `height`), PSD (layers),
  multi-page TIFF (pages as layers). Without options, a file no procedure matches by name (e.g. RAW
  through darktable or RawTherapee, when installed) goes through GIMP's own format detection.
* `gimp_export_layers(image, directory, extension="png", items?, template="{index:02d}-{name}",
  crop=true, options, overwrite)`: one file per top-level layer (or per given layer/group), cropped
  to the layer unless `crop=false`; names are made file-system safe. Refused as a whole
  (`FILE_EXISTS`) if any target exists without `overwrite`.
* `gimp_export_region(image, path, x, y, width, height, options, overwrite)`: a slice of the
  composite.

## Guides, metadata and print size (toolset `document`)

* `gimp_list_guides(image, values=true)`: `guides[]` (`id`, `orientation`, `position`) and
  `sample_points[]` (`id`, `x`, `y`, with `values` the composite color `rgba`/`hex`, sRGB).
  `gimp_add_guide(image, orientation, position)` (0..height for horizontal, 0..width for
  vertical), `gimp_add_sample_point(image, x, y)` (inside the canvas),
  `gimp_remove_guide(image, id, kind=guide|sample_point)` (`NOT_FOUND` for an unknown id).
* `gimp_get_metadata(image)`: `exif`, `xmp`, `iptc` (tag → interpreted value) and `comment`.
  `gimp_set_metadata(image, set={tag: value}, remove=[tags], comment?)`: tags are full Exiv2 keys
  (`Exif.Image.Artist`, `Xmp.dc.title`, `Iptc.Application2.Keywords`); `comment=""` removes it.
* **Exports write no metadata unless asked**: `png_options.metadata` / `jpeg_options.metadata`
  list what to keep (`exif`, `xmp`, `iptc`, `comment`, `thumbnail`); the default `[]` strips
  everything, so nothing leaks by accident.
* `gimp_set_print_size(image, x_resolution?, y_resolution?, width?, height?, unit?)`: changes
  the resolution (pixels per inch) from a resolution or a print size in `unit` (`inch`, `mm`,
  `point`, `pica`), and/or the image's unit; pixels are unchanged (5-65536 ppi).
  `gimp_inspect_image` reports `resolution` and `unit`; PNG exports carry the resolution (pHYs).

## Layer composition (toolset `compose`)

* `gimp_copy(items? | image + visible=true, cut=false, buffer="gimp-mcp")`: copies the layers'
  pixels (only the selected area when there is a selection; `selection` says so) or the visible
  composite into a **named GIMP buffer** (shown in GIMP's Buffers dialog), so the user's clipboard
  is untouched; `buffer="clipboard"` uses the global clipboard. `cut` empties the copied area.
* `gimp_paste(mode, item?, buffer, into_selection=false)`: `into-layer` merges the pixels into
  `item` (anchored), `new-layer` adds them as a layer above `item`, `new-image` opens a new image.
  A paste never leaves a floating selection; an image that already has one is refused.
  `NOT_FOUND` for an empty or unknown buffer.
* `gimp_merge_layers(mode, item | image, merge_type)`: `down` (into the layer below; refused for
  the bottom layer), `group` (a group becomes one layer), `visible` (all visible layers);
  `merge_type` `expand`, `clip-to-image`, `clip-to-bottom`. `gimp_flatten_image(image)`: one opaque
  layer. `gimp_new_layer_from_visible(image, name)`: a copy of the composite on top, the rest
  untouched. All one undo step; merges and flattening are destructive.
* `gimp_set_alpha_channel(item, add|remove)` (remove flattens onto the background color),
  `gimp_alpha_to_selection(item, operation)`.
* `gimp_fit_layer(item, mode)`: `image-size`, `size` (`width`, `height`, `offset_x`, `offset_y`:
  where the old content goes) or `content` (shrink to the non-empty pixels).
  `gimp_crop_to_content(image)`: GIMP's Crop to Content (`cropped` false when nothing changed).
* `gimp_align_layers(items, reference=image|selection|layer, reference_item?, horizontal?,
  vertical?, distribute?)`: aligns layer **boxes** (not their visible content) left/center/right
  and top/middle/bottom to the reference, or distributes 3+ layers so their centers are evenly
  spaced between the outer ones (to the nearest pixel). Locked positions are refused (`LOCKED`).

## Resources (toolset `resources`)

Brushes, gradients, patterns and palettes are referenced **by name** (`kind` = `brush`,
`gradient`, `pattern`, `palette`). Built-in resources are read-only: renaming, editing or deleting
them is `READ_ONLY` (duplicate first). Names of built-in resources may be translated in GIMP's
language: list them rather than hard-coding them.

* `gimp_list_resources(kind, query, limit)` → `name`, `editable`, `generated` (brushes), `total`.
* `gimp_inspect_resource(kind, name, preview=false)`: brushes `width`, `height`, `color`, `spacing`
  and, for generated brushes, `shape`, `radius`, `hardness`, `angle`, `aspect_ratio`, `spikes`;
  gradients `segments` (`left`, `middle`, `right` positions, colors `#rrggbbaa`, `blending`,
  `coloring`); patterns `width`, `height`, `bpp`; palettes `columns`, `entries`. `preview=true`
  adds an image: the brush (mask as alpha for grayscale brushes), the pattern, a 256×32 gradient
  strip or the palette swatches.
* `gimp_create_resource(kind, name)` (brush, gradient, palette; GIMP makes the name unique),
  `gimp_duplicate_resource(kind, name, new_name?)` (works on built-ins), `gimp_rename_resource`,
  `gimp_delete_resource` (deletes the file, not undoable).
* `gimp_edit_brush(name, shape?, radius?, hardness?, angle?, aspect_ratio?, spikes?, spacing?)`:
  user generated brushes only. `gimp_edit_gradient(name, segments)` replaces the segments (colors,
  `blending` linear/curved/sine/sphere-increasing/sphere-decreasing/step, `coloring`
  rgb/hsv-ccw/hsv-cw, optional increasing end positions). `gimp_edit_palette(name, entries?, columns?)`
  replaces the entries.
* `gimp_import_palette(file)`: a GIMP palette (`.gpl`) is copied into the profile's `palettes`
  folder and loaded. Other formats (`.aco`, `.act`, `.ase`, `.pal`) are `UNSUPPORTED_FORMAT`:
  GIMP 3.2 reads them only through its Palettes dialog (#81).
* `gimp_export_palette(name, file, format="gpl", overwrite)`: `gpl`, or GIMP's own palette exports
  `css`, `text`, `python`, `php`, `java`, and `kpl` (Krita).

**Where resources live.** User resources are files in the GIMP profile (`~/.config/GIMP/3.2/brushes`,
`gradients`, `palettes`, or `$GIMP3_DIRECTORY/…`). GIMP writes a new resource's file as soon as it
is created and saves later edits when it quits normally, like edits made in its own editors. If
GIMP is killed, the resource stays but unsaved edits are lost (tested). The tests only ever use
temporary profiles.

## Paths (toolset `paths`)

A path is an item (`item:N@session`) listed in `gimp_inspect_image`'s `paths` (`id`, `name`,
`visible`, `strokes`). It holds **strokes**, numbered inside the path. Coordinates are image
pixels; paths may extend beyond the canvas. Every change is one undo step.

* **Create**: `gimp_create_path(image, name, strokes=[], position=0)` and
  `gimp_add_path_stroke(path, stroke)` with strokes
  `{"type": "polyline", "points": [[x, y], …], "closed"}`,
  `{"type": "bezier", "start": [x, y], "segments": [{"to": [x, y], "control1"?, "control2"?}], "closed"}`
  (no control: line; `control1` only: quadratic; both: cubic) or
  `{"type": "ellipse", "center": [x, y], "radius_x", "radius_y", "angle"}`.
  `gimp_path_from_text(item)` outlines a text layer's glyphs.
* **Inspect**: `gimp_inspect_path(path, points=false)` → `strokes[]` with `id`, `closed`,
  `length` (pixels), `anchors`, `bounds` of the control points, and with `points=true`
  `control_points` (in-handle, anchor, out-handle per anchor). At most 200 strokes are detailed;
  `stroke_count` is the total. `gimp_path_point_at(path, stroke, distance)` → `x`, `y`, `slope`.
* **Manage**: `gimp_set_path` (name, visible in the canvas), `gimp_duplicate_path`,
  `gimp_delete_path`. `gimp_edit_path_stroke(path, stroke, action)`: `translate` (dx, dy),
  `scale` (sx, sy, around the origin), `rotate` (angle in degrees around center_x, center_y),
  `flip` (orientation around axis), `reverse`, `close`, `remove`.
* **Selections**: `gimp_path_to_selection(path, operation, antialias)`;
  `gimp_selection_to_path(image, name?)` traces the selection (GIMP's Selection to Path,
  `EMPTY_SELECTION` when nothing is selected).
* **Paint**: `gimp_stroke_path(path, item, color, width, method="line", cap, join, miter_limit,
  dash?, brush?, opacity, antialias)`: `line` draws a geometric line (`dash` lengths are multiples
  of the width); `paint` uses GIMP's paintbrush with `brush` (by name) at `width` pixels.
  `gimp_fill_path(path, item, color, opacity, antialias)` fills the enclosed area and restores the
  selection (`INVALID_ARGUMENT` when the path encloses nothing). The path and the layer must belong
  to the same image (`IMAGE_MISMATCH`). The user's context (colors, brush) is untouched.
* **SVG**: `gimp_import_svg_paths(image, file | svg, merge=false, scale=false)` imports every
  `<path>` (one GIMP path each, or one with `merge`; `scale` fits the SVG to the image)
  (`UNSUPPORTED_FORMAT` when there is none). `gimp_export_path_svg(image, path?, file?, overwrite)`
  returns the SVG document of one path or all paths, or writes it (output path rules apply).
* Paths are saved in XCF with their strokes (`tests/e2e/test_paths.py`).

## Image mode, precision and color profiles (toolset `modes`)

### `gimp_convert_mode(image, mode, palette="generate", palette_name?, colors=256, dither="none", dither_alpha=false, remove_unused=true)`

`mode`: `rgb`, `gray`, `indexed` (`changed: false` when the image already is). RGB → gray uses
relative luminance (sRGB red → 130). Indexed: `palette` `generate` (optimal palette of at most
`colors`), `web` (216 web-safe colors), `mono` (black and white) or `custom` (a GIMP palette by
name, `NOT_FOUND` otherwise); `dither` `none`, `floyd-steinberg`, `floyd-steinberg-low-bleed`,
`positioned`; `remove_unused` drops palette entries no pixel uses. Indexed images are 8-bit:
convert the precision to `u8-non-linear` first (`INVALID_ARGUMENT` otherwise). Returns
`base_type`, `precision`, `palette_colors`. Lossy (gray, indexed); one undo step.

### `gimp_convert_precision(image, precision)`

`precision`: `u8`, `u16`, `u32` (integer), `half`, `float`, `double` (floating point), each
`-linear`, `-non-linear` (sRGB curve) or `-perceptual`, e.g. `u16-non-linear`, `float-linear`.
`gimp_inspect_image` reports it (`precision`). Not for indexed images. PNG exports keep 16 bits
(`format` auto). One undo step.

### `gimp_get_color_profile(image)` / `gimp_set_color_profile(image, action, profile?, path?, intent="perceptual", black_point_compensation=true)`

`assigned` (`null` when the image has none) and `effective` (what GIMP uses: the built-in sRGB or
gray profile when none is assigned): `label`, `description`, `model` (`rgb`/`gray`), `linear`,
`icc_bytes`.

* `assign`: tags the pixels with the profile without changing their values (colors look different).
* `convert`: transforms the pixels so colors look the same (`intent`: `perceptual`,
  `relative-colorimetric`, `saturation`, `absolute-colorimetric`; black point compensation).
* `remove`: back to the built-in profile.

`profile`: `srgb`, `srgb-linear`, `gray`, `gray-linear` (built in) or `file` with an ICC `path`
(`FILE_NOT_FOUND`, or `UNSUPPORTED_FORMAT` for a file that is not a usable profile). A gray profile
on an RGB image (or the reverse) is `INVALID_ARGUMENT`. Exports embed the profile when the image
has one assigned (`png_options.color_profile` / `jpeg_options.color_profile`: `true` always embeds,
even GIMP's built-in sRGB; `false` never).

### How colors are interpreted

Every tool that takes a color (`#rrggbb[aa]`) means **sRGB**. GIMP converts it into the image:

* RGB image with another profile (e.g. linear sRGB): the color is converted, so it *looks* the
  same; the stored values differ (`#404040` is stored as 13/255 in a linear-light image).
* Grayscale image: the color's luminance (`#ff0000` → 130).
* Indexed image: the nearest palette entry (`#ff0000` in a palette of orange and blue → orange).

Values *returned* by the analysis tools are sRGB too, whatever the image's profile.

## Color adjustments (toolset `color`)

Dedicated tools with the ranges of GIMP's dialogs. **Editable** mode (default, `destructive=false`)
adds a GIMP filter on the layer (pixels untouched, see `gimp_list_filters`); **destructive** mode
changes the pixels (plain layers only). Both respect the selection. Every tool returns
`adjustment`, `operation` (GIMP/GEGL operation used, `null` for GIMP's built-in destructive tools),
`destructive`, `filter` (editable mode) and `restricted_to_selection`. One undo step each.

| Tool | Parameters (our range → GIMP) | Modes |
|---|---|---|
| `gimp_levels` | `channel` (`value` = all color channels, `red`, `green`, `blue`, `alpha`); `input_low` < `input_high`, `output_low`, `output_high`: 0-255 → 0-1; `gamma` 0.1-10 (>1 brightens midtones). `gimp:levels` on **sRGB values** (`trc=non-linear`, like the Levels dialog; the operation's own default is linear light) | both |
| `gimp_curves` | `channel`; `points` `[[x, y], …]` 0-255, x strictly increasing (spline, `gimp-drawable-curves-spline`) **or** `samples` (outputs for evenly spaced inputs, resampled linearly to 256 values, `gimp-drawable-curves-explicit`) | destructive only: GIMP 3.2 cannot set a curve on an editable filter from a plug-in |
| `gimp_color_balance` | `range` shadows/midtones/highlights; `cyan_red`, `magenta_green`, `yellow_blue` -100..100 → -1..1; `preserve_luminosity` | both |
| `gimp_colorize` | `hue` 0-360° → 0-1, `saturation` 0-100 → 0-1, `lightness` -100..100 → -1..1. `gimp:colorize` follows its `color` property, set to HSL(hue, saturation, 50%) | both |
| `gimp_desaturate` | `mode`: `luminance` (linear light), `luma` (Rec. 709 on sRGB values), `lightness` (HSL), `average`, `value` (HSV) | both |
| `gimp_invert` | `linear` false: 255 − v on sRGB values (`gegl:invert-gamma`, GIMP's Invert); true: in linear light (`gegl:invert-linear`) | both |
| `gimp_threshold` | `channel`; `low` ≤ `high`, 0-255 → 0-1: pixels in the range become white, others black | both |
| `gimp_posterize` | `levels` 2-256 per channel | both |
| `gimp_exposure` | `exposure` -10..10 EV (+1 doubles the light, linear), `black_level` -0.1..0.1 (`gegl:exposure`) | both |
| `gimp_shadows_highlights` | `shadows`, `highlights` -100..100, `whitepoint` -10..10, `radius` 0.1-1500, `compress`, `shadows_color_correction`, `highlights_color_correction` 0-100 (GEGL units); unset values keep GIMP's defaults | both |
| `gimp_auto_adjust` | `method`: `white-balance` (`gimp-drawable-levels-stretch`: stretches each channel, ignoring a tiny share of extreme pixels), `equalize` (`gimp-drawable-equalize`), `stretch-contrast` (`gegl:stretch-contrast`, `keep_colors`) | white-balance, equalize: destructive only (`UNSUPPORTED` with `destructive=false`); stretch-contrast: both, editable by default |

Invalid values are refused before anything changes (`INVALID_ARGUMENT`).

## Effects: the GEGL filter catalog (toolset `effects`)

GIMP 3.2 offers about 200 GEGL operations as filters. Their parameters are **introspected from
GIMP** (once per GIMP session) and every value is validated by the bridge before anything changes
(`INVALID_ARGUMENT` names the parameter and the allowed range or choices).

### `gimp_list_filter_operations(query="", category?)`

`operations[]`: `name` (`gegl:unsharp-mask`…), `title`, `categories` (`blur`, `distort`, `light`,
`noise`…), `supported`, `reason`. Not supported, and listed with the reason:

* scripts and file readers: `gegl:gluas`, `gegl:ctx-script`, `gegl:styles` (denied);
* operations with an auxiliary input (a second image): `gegl:bump-map`, `gegl:displace`,
  `gegl:variable-blur`, and six that GIMP 3.2 silently drops when appended as filters
  (`gegl:gaussian-blur-selective`, `gegl:lens-blur`, `gegl:negative-darkroom`, `gegl:oilify`,
  `gegl:voronoi-diagram`, `gimp:set-alpha`);
* internal GIMP operations (layer modes, compositing, selection helpers);
* operations with a parameter the bridge cannot set (`gimp:curves`: a curve object).

### `gimp_describe_filter_operation(operation)`

`description` and `parameters[]`: `name`, `kind` (`number`, `integer`, `boolean`, `choice`, `enum`,
`color`, `string`, `unsupported`), `min`, `max`, `choices`, `default`, `description` (GIMP's text, in
GIMP's language). Colors are `#rrggbbaa`.

### `gimp_apply_filter(item, operation, parameters={}, destructive=false, name?, opacity?, mode?, visible?)`

Default: adds an **editable filter** on top of the layer's filter stack (pixels untouched; saved in
XCF with its parameters). `destructive=true`: bakes the result into the pixels (plain layers only,
`WRONG_KIND` on groups and text, `LOCKED` on locked pixels). Parameters not given keep GIMP's
defaults. Both modes respect the selection active at that moment (`restricted_to_selection`).
Returns the filter's state (`id` is `null` when destructive). `UNSUPPORTED` for an operation listed
as not supported, `NOT_FOUND` for an unknown one. One undo step.

### `gimp_inspect_filter(item, filter)` / `gimp_set_filter(item, filter, parameters?, visible?, opacity?, mode?)`

State of an editable filter: `operation`, `name`, `visible`, `opacity` (0-100), `mode` (blend
mode nick), `parameters` (current values). `gimp_set_filter` changes only what is given (one undo
step); a hidden filter leaves the layer's rendering exactly as without it.

### `gimp_move_filter(item, filter, position)`

Moves a filter in the stack (0 = top, applied last). GIMP 3.2 can only append filters on top: the
filters from the top down to the lowest moved slot are **re-created** with the same operation,
parameters, name, opacity, mode and visibility, and get new ids (`recreated`: old id → new id).

### `gimp_merge_filters(item, up_to?)`

Bakes filters into the pixels (destructive, plain layers only): the whole stack, or from the bottom
up to and including `up_to`; the filters above stay editable (re-created, new ids). The live stack
computes in floating point while baked pixels are stored in the layer's precision: on 8-bit layers
values may move by 1.

## Analysis (toolset `analysis`, read-only)

Measure instead of guessing from a downscaled preview. Values are **8-bit sRGB (0-255)**
whatever the image precision. A *target* is an image id (its visible composite, rendered from a
temporary flattened copy that is deleted right away) or an item id (the own pixels of a layer, mask
or channel). Regions are in image coordinates and clipped to the target's pixels
(`INVALID_ARGUMENT` when they don't overlap; at most 50 million pixels). None of these tools changes
the image, its undo history, its dirty flag or the list of open images (`tests/e2e/test_analysis.py`).

### `gimp_histogram(target, channels=["red","green","blue","luminance"], region?, selection_only=false, percentiles=[5,25,50,75,95], bins=16)`

Per channel: `pixel_count`, `mean`, `median`, `std_dev`, `min`, `max`, `percentiles` (nearest rank,
keys `"5"`, `"50"`…) and `histogram` (`bins` equal bins over 0-255; `bins=0` omits it).
`channels`: `red`, `green`, `blue`, `alpha`, `luminance` (relative luminance with ICC D50
coefficients, encoded with the sRGB curve: pure red → 130). Every pixel counts once, whatever its
alpha. `selection_only`: only pixels selected at 50% or more (`EMPTY_SELECTION` when nothing is
selected). A channel with no pixel returns only `pixel_count: 0`.

### `gimp_sample_colors(target, points, radius=0)`

`points`: up to 64 `[x, y]` (image coordinates, inside the target, else `INVALID_ARGUMENT`).
Each sample: `hex`, `rgba` (0-255), `pixels_averaged` — the mean over the (2·radius+1)² square
around the point, clipped to the target.

### `gimp_compare(a, b, threshold=0, preview=false, max_size=512)`

`a`, `b`: image, item or **checkpoint** ids of the same size (`INVALID_ARGUMENT` with both sizes in
`details` otherwise). A pixel is *changed* when one of its RGBA values differs by more than
`threshold`. Returns `changed_pixels`, `changed_fraction`, `bounds` (bounding box, `null` when
nothing changed), `mean_difference` (mean absolute difference over all pixels and channels),
`max_difference`. `preview=true` adds a PNG image block: changed pixels in red (`#ff0040`) over a
dimmed grayscale of `b`, downscaled by blocks (a block is red if any of its pixels changed).

### `gimp_dominant_colors(target, region?, count=5)`

Up to `count` (1-16) colors with their share of the **opaque** pixels (alpha ≥ 128), most common
first. Colors are grouped by 16 levels per channel and averaged within the group. Areas larger
than 256 pixels per side are examined downscaled (`sampled_scale`).

### `gimp_preview_region(image, x, y, width, height, max_size=1024)`

PNG of a rectangle of the composite (inside the canvas, else `INVALID_ARGUMENT`), at full
resolution when it fits in `max_size` (`scale` = 1), otherwise scaled to fit. Rendered from a
temporary cropped copy.

## History: undo groups and checkpoints

GIMP 3.2 gives plug-ins **no undo/redo procedure** and no way to read the undo
history (only to open and close undo *groups*). Two separate mechanisms are
therefore offered; neither is a transaction and **nothing is ever rolled back
automatically**.

### Undo groups — one step in GIMP's own history

* `gimp_begin_undo_group(image, label?)` → `depth`; `gimp_end_undo_group(image)`
  → `depth` (`NO_OPEN_GROUP` if this client has no open group on the image).
* Every change between them becomes **one** step of GIMP's undo history, which
  a human undoes with Ctrl+Z in GIMP's UI. Groups nest.
* **Always closed**: groups are tracked per client connection and closed by the
  bridge when the client disconnects (exit, crash, timeout), even after errors.
  A tool error inside a group does not close or cancel it; already applied
  changes stay applied.
* Limit: changes made meanwhile in GIMP's UI on the same image join the group.
  Plug-ins cannot read the undo stack, so the grouping itself is not verified
  by automated tests (closing on disconnect is: `tests/unit/test_undo_groups.py`,
  `tests/e2e/test_history.py`).

### Checkpoints — undo/redo for agents

* `gimp_create_checkpoint(image, label?)` keeps a full copy of the image
  (layers, groups, text, masks, editable filters, selection); copies are hidden
  from `gimp_status`, use memory, max. 20 per image.
* `gimp_restore_checkpoint(image, checkpoint)` replaces the image with that
  state. **The image gets a new id and all item ids change** (`previous_image`
  becomes `NOT_FOUND`); GIMP windows showing it are reconnected (verified in the
  GUI); the XCF file association is kept; the image is marked dirty; its GIMP
  undo history starts empty. Checkpoints survive restorations, so: checkpoint
  *A*, change, checkpoint *B*, restore *A* = undo, restore *B* = redo.
* `gimp_list_checkpoints(image)` (oldest first), `gimp_delete_checkpoint(checkpoint)`;
  closing an image deletes its checkpoints.

Errors: `NO_OPEN_GROUP`, `CHECKPOINT_LIMIT`, `IMAGE_MISMATCH` (checkpoint of
another image), `NOT_FOUND`.

## Error codes

| Code | Meaning |
|---|---|
| `GIMP_NOT_RUNNING` | No bridge socket, or stale socket (GIMP exited). |
| `BRIDGE_UNAVAILABLE` | Socket present but no answer in time (GIMP busy/frozen) or token unreadable. |
| `VERSION_INCOMPATIBLE` | GIMP < 3.2 or plug-in protocol mismatch. |
| `PLUGIN_VERSION_MISMATCH` | Plug-in and server versions differ in MAJOR.MINOR (see `docs/compatibility.md`); reinstall the plug-in and restart GIMP. |
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
| `NO_OPEN_GROUP` | `gimp_end_undo_group` without an open group from this client (closed on disconnect). |
| `CHECKPOINT_LIMIT` | 20 checkpoints already kept for the image. |
| `PROCEDURE_NOT_ALLOWED` | The procedure is outside the generic-access allowlist (`details.reason`). |
| `FONT_NOT_FOUND` | Unknown font name; `details.suggestions` lists close names. |
| `EMPTY_SELECTION` | The operation needs a selection and nothing is selected. |
| `IMAGE_MISMATCH` | Objects from different images combined in one operation. |
| `LOCKED` | The targeted property or content is locked in GIMP. |
| `UNSUPPORTED` | The operation exists but cannot be used through this tool (`message` says why). |
| `READ_ONLY` | A built-in resource cannot be changed: duplicate it first. |
| `GIMP_ERROR` | Unexpected failure inside GIMP; for a mutation the outcome is `unknown`. |

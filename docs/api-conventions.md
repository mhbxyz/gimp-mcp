# API conventions

The rules every MCP tool of gimp-mcp follows. They are what the public API (`docs/api/contract.json`)
freezes at 1.0, so a new tool or parameter is designed against them. `uv run scripts/api_review.py`
checks every tool against the rules that can be checked mechanically and writes
[`docs/api/review.md`](api/review.md): each deviation is either fixed or accepted there with its reason.

## Naming

* Tools are `gimp_<verb>_<object>` in snake_case: `gimp_resize_image`, `gimp_add_layer_mask`. Verbs
  are reused with one meaning: `create` (a new object from nothing), `duplicate`, `import` (from a
  file into an open image), `open` / `save` / `export` / `close` (files and images), `list` (several
  objects, short), `inspect` (one object, everything), `set` (change properties), `add` / `remove`
  (attach or detach a part: mask, guide, frame, filter), `delete` (destroy an object), `select`
  (change the selection).
* Parameters and result fields are snake_case nouns. A parameter keeps the same name wherever it has
  the same meaning (`opacity`, `mode`, `antialias`, `interpolation`, `overwrite`).

## References to images and items

* Ids are opaque strings returned by tools (`image:3@1a2b3c4d`, `item:12@1a2b3c4d`, checkpoint and
  filter ids): pass them back verbatim, never build or parse them (`docs/tools.md#ids`).
* The image a tool works on is `image`. The layer, group, mask, channel, path or text layer it works
  on is `item` (several: `items`). Any image or item id is accepted where the tool works on either:
  `target`.
* When a tool takes several items with different roles, each is named by its role: `parent`,
  `source`, `reference_item`, `up_to`, `duplicate_of`, `a` / `b` for a symmetric comparison.
* Other objects are named by their kind: `checkpoint`, `filter`, `channel`, `buffer`, `guide`.
  Resources (brushes, gradients, palettes, patterns, fonts) are referenced by their GIMP name.
* Names are never identifiers: GIMP renames duplicates, so tools target ids.

## Colors

* A color is a string: `#rrggbb`, `#rrggbbaa`, `#rgb` or a CSS-like name (`white`, `transparent`),
  sRGB (`docs/tools.md#how-colors-are-interpreted`). The parameter is `color`, or `<role>_color`
  (`fill_color`, `stroke_color`) when a tool takes several. Results return `#rrggbb` or `#rrggbbaa`.

## Units and coordinates

* Positions and sizes are integer **pixels** in **image coordinates** (origin at the image's top-left,
  y down), whatever the layer: `x`, `y`, `width`, `height`. A rectangle is `x, y, width, height`.
* Angles are **degrees, clockwise**. Opacity is **0–100** (percent). Durations are milliseconds and say
  so (`duration_ms`). Another unit is explicit in the name or in a `*_unit` parameter (`size_unit`).
* Ranges are stated in the schema (`minimum`, `maximum`) and refused before GIMP is called.

## Enumerations

* Lowercase words separated by hyphens: `"image-sized"`, `"top-left"`, `"linear-light"`. Values name
  what they do, not GIMP's internal constants.

## Booleans

* Positive names (`antialias`, `visible`, `overwrite`), never `no_…`. The default is the safe or
  non-destructive choice: `overwrite=false`, `destructive=false`, `discard_changes=false`.

## Files and `overwrite`

* A file system path is an **absolute** path in a parameter named `path` (several: `paths`, a folder:
  `folder` / `output_folder`); results name written files `path`. The extension chooses the format
  unless `format` says otherwise.
* Exception: in tools working on GIMP **paths** (the vector objects of the `paths` toolset), `path` is
  the path's id, as in GIMP, and a file is `file`.
* A tool that writes a file refuses to replace an existing one unless `overwrite=true`
  (`FILE_EXISTS`), and never replaces one of its inputs.
* Exports write no metadata unless asked (Exif, XMP, IPTC, comment, thumbnail, time).

## Results

* Every tool returns structured content matching its output schema, and the same JSON as text.
* The object a call created, or else the image or item it changed, is identified by a top-level `id`
  in its result: a new layer, image, path, channel…, or the image or item it changed. Other fields
  describe it (`image` is the image an item belongs to). A recipe step or an agent can always chain on
  `id`. A tool that changes several objects or none (alignment, deletion, file exports) is exempt and
  says what it changed in named fields.
* Lists are plural nouns (`layers`, `frames`); booleans state facts (`dirty`, `empty`, `editable`).

## Errors and hints

* Every failure is `isError` with `{"error": {"code", "message", "hint"?, "details"?, "outcome"?}}`.
  `code` is one of the registered codes (`docs/tools.md#error-codes`); `message` says what is wrong
  with the values involved; `hint` says what to do next (the tool or argument to use, the toolset to
  enable); `details` carries machine-readable facts (the field at fault, sizes, suggestions).
* Arguments are validated before anything changes (`INVALID_ARGUMENT`, `outcome: not_applied`). An
  unexpected failure inside GIMP during a change is `GIMP_ERROR` with `outcome: unknown`.

## Descriptions

* Lead with the effect in one sentence, then: lossless or lossy (destructive tools carry the
  `destructiveHint`, and so does every tool that can replace a file: an `overwrite` parameter means
  `destructiveHint: true`, checked by `test_api_contract.py`), the undo behaviour (`One undo step`, or not in GIMP's undo history for files,
  resources and toolsets), the errors an agent should expect, and the optional toolset that covers
  related needs (`more formats: gimp_export_as, toolset formats`).
* Facts measured on GIMP (what a value does to pixels) are stated with the measurement; they come from
  `docs/gimp-notes.md`.
* The default toolsets stay within their budget (`docs/toolsets.md#budget`).

# GIMP 3 behaviour notes (verified, not assumed)

Each entry was observed on GIMP 3.2.6 / PyGObject 3.58 / Python 3.14 (Arch).

## Plug-ins and lifecycle

* A `Gimp.Procedure` of type `PERSISTENT` with **no arguments** is started
  automatically at GIMP launch, both in the GUI (`gimp`) and in
  `gimp-console -i`. It must call `procedure.persistent_ready()`.
* After `plug_in.persistent_enable()`, a `GLib.MainLoop` in the plug-in keeps
  servicing GIMP's messages; GIMP's quit terminates the plug-in cleanly.
* `GLib.unix_fd_add_full` is deprecated in PyGObject ≥ 3.52; use
  `GLibUnix.fd_add_full`.
* Python plug-ins run through `#!/usr/bin/env python3`. If GIMP inherits a
  `PATH` whose first `python3` is a virtualenv without PyGObject, *every*
  Python plug-in fails with `ModuleNotFoundError: No module named 'gi'`.
* `gimp-console` without `--quit` stays running in the background until
  SIGTERM/SIGINT.
* Files passed on the command line are opened *after* extensions start: the
  bridge may answer before they are listed by `Gimp.get_images()`.
* `GIMP3_DIRECTORY` replaces the whole user configuration directory (used for
  isolated tests).
* Startup time of `gimp-console -i`: ≈0.8 s with `--no-data --no-fonts`, ≈5 s
  with fonts and data.

## API facts

* There is **no PDB procedure or libgimp function to undo/redo**. Only
  `gimp-image-undo-group-start/end`, `-disable/-enable`, `-freeze/-thaw` and
  `-is-enabled` exist (PDB dump of 3.2.6).
* `Gimp.Image.get_name()` is a localized display name, e.g.
  `"[photo] (importée)"` for an imported PNG.
* Layer names are unique **per image**: inserting a second `Dup` anywhere in
  the same image (even in another group) renames it `Dup #1`. Different images
  may share names.
* `Gimp.Image.id_is_valid(n)` / `Gimp.Item.id_is_valid(n)` and
  `Gimp.Item.get_by_id(n)` (→ `None` when gone) detect stale ids; images and
  items are numbered by two separate global counters.
* `layer.get_offsets()` returns `(ok, x, y)`; `image.get_resolution()` returns
  `(ok, xres, yres)`; a new image defaults to 300 ppi with an empty profile in
  `gimp-console`.
* Enum values expose `.value_nick` (`multiply`, `rgb`, `u8-non-linear`), used as
  stable strings in the API.
* `Gimp.LayerMask` is a subclass of `Gimp.Channel`; `Gimp.Layer.from_mask(mask)`
  finds the owning layer.
* `image.get_thumbnail(w, h, Gimp.PixbufTransparency.KEEP_ALPHA)` renders the
  projection into a `GdkPixbuf` (RGBA, exact requested size when proportional)
  without touching the dirty flag; it returns `None` above 1024 px.
  `pixbuf.save_to_bufferv("png", [], [])` encodes it.
* `Gimp.DrawableFilter.new(drawable, "gegl:<op>", name)` + `get_config()`
  properties + `update()`; `drawable.merge_filter(f)` applies it destructively
  (afterwards `get_filters()` is empty).
* **Colors**: `GeglColor.set_rgba()` and GEGL's CSS `rgb()/rgba()` parser take
  *linear* RGB floats (`rgb(51,102,153)` is *not* 0–255!). `"#336699"` and
  `set_rgba_with_space(r, g, b, a, Babl.space("sRGB"))` are sRGB.
* `Gimp.file_load()` returns `None` (no exception, PDB last error "success")
  for missing, corrupt or unknown files.
* `file-png-export` / `file-jpeg-export` merge the visible layers; JPEG
  flattens alpha onto the context background color. JPEG `quality` is 0–1
  (default 0.9) and `progressive` defaults to true. Exporting through the PDB
  neither cleans the image nor sets `get_exported_file()`.
* `Gimp.file_save(..., "x.xcf")` cleans the image and sets `get_xcf_file()`.
* `Gimp.Display.new(image)` raises `TypeError: constructor returned NULL` in
  `gimp-console`.
* PDB status values: `EXECUTION_ERROR=0`, `CALLING_ERROR=1`, `PASS_THROUGH=2`,
  `SUCCESS=3` (`result.index(0)`).
* Layer blending happens in **linear light** by default: 50% opacity of blue
  multiplied over white gives sRGB (188, 188, 255), not (128, 128, 255).
* Inserting a layer makes GIMP de-duplicate its name in the image; `copy()`
  names the duplicate `"<name> copy"`. `image.reorder_item(item, parent, pos)`
  moves across groups; `Gimp.file_load_layer()` flattens a file into one layer
  named after the file.
* Transforms: `layer.scale(w, h, local_origin=True)` keeps the layer center;
  `transform_rotate(radians, auto_center=True, 0, 0)` rotates clockwise for
  positive angles; `transform_flip_simple(orientation, True, 0)`. Interpolation
  and clipping come from the context (`context_set_interpolation`,
  `context_set_transform_resize`).
* On a position-locked layer GIMP refuses silently: `set_offsets()` returns
  `False`, `transform_flip_simple()` returns `None`. Check locks first.
* `image.scale()` rounds scaled offsets (2.5 → 3).
* `Gimp.Selection.bounds(image)` returns `(ok, non_empty, x1, y1, x2, y2)`
  (x2/y2 exclusive); `Gimp.Selection.value(image, x, y)` is 0–255. Selection
  changes mark the image dirty. Selecting outside the canvas is clipped.
* Masks: `layer.create_mask(Gimp.AddMaskType.X)` + `layer.add_mask(mask)`;
  `remove_mask(Gimp.MaskApplyMode.APPLY|DISCARD)`; masks survive an XCF round
  trip.
* AF_UNIX socket paths longer than ~107 bytes fail with `OSError: AF_UNIX path
  too long`.

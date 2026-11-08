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
* Filters in 3.2: `plug-in-gauss` no longer exists; use GEGL ops through
  `Gimp.DrawableFilter`. `drawable.append_filter(f)` keeps an editable filter
  (listed by `get_filters()`, saved in XCF, removed by `f.delete()`);
  `merge_filter(f)` bakes it. Both respect the selection active when called.
  GIMP's own ops `gimp:brightness-contrast` (brightness/contrast −1…1) and
  `gimp:hue-saturation` (range, hue −1…1 = ±180°, saturation/lightness −1…1,
  overlap 0…1) work as editable filters.
  `DrawableFilter.operation_get_pspecs()` returns a `ValueArray` that is not
  iterable from Python: read properties from `f.get_config()` instead.
* `image.duplicate()` keeps text layers, editable filters, masks and the
  selection; the copy is dirty, has no file. `image.set_file(gfile)` sets the
  XCF file. `Gimp.displays_reconnect(old, new)` moves GUI windows to another
  image (returns `False` when there is no display, e.g. in `gimp-console`).
* **Flatpak GIMP** (Flathub `org.gimp.GIMP` 3.2.8, runtime GNOME 51, checked
  2026-11-08): reads the host `~/.config/GIMP/3.2` (permission
  `xdg-config/GIMP:create`), also sees `/tmp` and the host filesystem; ships
  `gimp-console-3.2`, Python 3.14 and PyGObject; inside the sandbox
  `XDG_RUNTIME_DIR=/run/user/<uid>` is private except `app/org.gimp.GIMP`,
  shared with the host's `$XDG_RUNTIME_DIR/app/org.gimp.GIMP`. `FLATPAK_ID` and
  `/.flatpak-info` exist. Installing the app needs no privilege, running it in
  Docker needs `--privileged` (bubblewrap).
* **Reading pixels** (checked 2026-11-08): `drawable.get_buffer().get(Gegl.Rectangle, scale,
  format, Gegl.AbyssPolicy.CLAMP)` returns Python `bytes` in the requested babl format
  (`"R'G'B'A u8"`, `"Y' u8"`, `"RGBA float"`…), in drawable-local coordinates; with `scale` < 1
  the rectangle is in scaled coordinates. 6 Mpx in `R'G'B'A u8`: ≈20 ms. The selection is a channel
  (`image.get_selection()`, image-sized) readable the same way in `"Y u8"`.
* babl `"Y'"` is relative luminance with **ICC D50** coefficients (red 0.2225) encoded with the
  sRGB curve: pure red reads 130, not 127 (Rec. 709 coefficients) nor 54 (luma).
* Composite at full resolution: `image.duplicate()` then
  `merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)` on the copy, then `copy.delete()`. The
  original stays clean and the copy never appears in `Gimp.get_images()` once deleted.
* `gimp-drawable-histogram` weights pixels by alpha and by the selection and answers one channel
  and one intensity range per call; the analysis tools compute their own statistics instead
  (every pixel once, selection ≥ 50%).
* `Gimp.Image.pick_color(image, drawables, x, y, sample_merged, sample_average, radius)` exists
  (PDB `gimp-image-pick-color`) and returns `(ok, GeglColor)`.
* **Filter catalog** (checked 2026-11-08): GEGL operations are *not* loaded in the plug-in process
  (`Gegl.list_operations()` is empty there). `Gimp.DrawableFilter.operation_get_available()` lists
  the 200 operations GIMP offers as filters (149 `gegl:`, 51 `gimp:` including layer modes and
  internal helpers). `operation_get_details(name)` returns `(ok, keys, ValueArray)`: read values
  with `values.index(i)` (title, description, categories `blur:scramble`, license; localized).
  Parameters: create `Gimp.DrawableFilter.new(layer, name, title)` (not added to the layer until
  `append_filter`) and read `get_config().list_properties()`: `ParamSpecDouble/Int/UInt/Boolean`
  (with `minimum`, `maximum`), `GimpParamChoice` (nicks via
  `Gimp.param_spec_choice_get_choice(p).list_nicks()`), `GeglParamColor`, `ParamSpecEnum`
  (`p.enum_class.__enum_values__`), `ParamSpecString`, and `gimp:curves`' `GimpCurve` object.
  Defaults are the config's initial values. Introspecting all 200: ≈0.3 s.
* Filters with an auxiliary input (`gegl:gaussian-blur-selective`, `lens-blur`,
  `negative-darkroom`, `oilify`, `voronoi-diagram`, `gimp:set-alpha`) are accepted by
  `DrawableFilter.new` but **silently dropped** by `append_filter` (not in `get_filters()`).
* There is no API to reorder filters or to merge a single filter: libgimp has `append_filter`
  (adds on top), `merge_filter` (bakes a filter not in the stack), `merge_filters` (bakes the whole
  stack), `filter.delete()`. Re-creating a filter (same operation, config properties, opacity,
  blend mode, visibility) on top is the only way to move it.
* Editable filters respect the selection active when they are created, like destructive ones;
  a hidden filter (`set_visible(False)`) leaves the rendering byte-identical; XCF keeps editable
  filters with their parameters. Baking a filter stack stores 8-bit values while the live stack
  computes in float: results may differ by 1.
* **Color operations** (checked 2026-11-08): `gimp:levels` defaults to `trc=linear` (64 with
  input 0..128 gives 90); `trc=non-linear` works on sRGB values (gives 128, like the Levels
  dialog). `gimp:colorize` ignores a changed `hue`/`saturation` and follows its `color` property
  (HSL(h, s, 50%); `colorize_hsl(0, 100, 0)` and `color=#ff0000` both give (176, 0, 0) on 50% gray).
  `gimp_drawable_curves_explicit` asserts `num_values >= 256`. `levels_stretch()` (Auto White
  Balance) leaves a 50/200 two-tone image at 3/255, not 0/255. `equalize(False)` maps a two-tone
  image to 128/255. `gimp:curves` needs a `GimpCurve` object, which plug-ins cannot build.
* AF_UNIX socket paths longer than ~107 bytes fail with `OSError: AF_UNIX path
  too long`.

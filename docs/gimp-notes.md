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
* **Modes, precision, profiles** (checked 2026-11-08): `image.convert_grayscale()` turns sRGB red
  into 130 (luminance); filling a gray image with red gives 130 too. `convert_indexed(dither,
  palette_type, num_cols, alpha_dither, remove_unused, palette_name)`: with `remove_unused` a
  uniform image keeps 1 color; a `CUSTOM` palette name that does not exist makes it return
  `False` silently (check `Gimp.Palette.get_by_name` first); filling an indexed image picks the
  nearest palette entry. `convert_precision(Gimp.Precision.X)` keeps the look. Profiles:
  `get_color_profile()` is `None` until one is assigned, `get_effective_color_profile()` is then
  "GIMP built-in sRGB"; `set_color_profile(Gimp.ColorProfile.new_rgb_srgb_linear())` keeps the
  values (64 now reads 137 in sRGB), `convert_color_profile(p, intent, bpc)` keeps the look
  (stored 13/255); assigning a gray profile to an RGB image returns `False`.
  `Gimp.ColorProfile.new_from_file(GFile)` loads ICC files. `file-png-export`/`file-jpeg-export`
  take `include-color-profile`, **false by default** (GIMP does not embed the profile unless asked).
* **Paths** (checked 2026-11-08): `Gimp.Path.new(image, name)` + `image.insert_path(path, None,
  pos)`; `bezier_stroke_new_moveto(x, y)` returns the stroke number; `bezier_stroke_lineto`,
  `cubicto`, `conicto`, `stroke_close`, `bezier_stroke_new_ellipse(cx, cy, rx, ry, angle)`.
  `stroke_get_points(s)` → `(type, flat control points, closed)`, three control points per
  anchor (in-handle, anchor, out-handle). `stroke_get_length(s, precision)`,
  `stroke_get_point_at_dist(s, d, precision)` → `(ok, x, y, slope, valid)`. `stroke_translate`,
  `stroke_scale` (around the origin), `stroke_rotate(s, cx, cy, degrees)`,
  `stroke_flip(s, orientation, axis)`, `stroke_reverse`, `remove_stroke`, `path.copy()`.
  `image.select_item(op, path)` selects the enclosed area. `plug-in-sel2path` traces the selection
  into a new path named after the (localized) word "Selection". `import_paths_from_string(svg,
  length, merge, scale)` → `(ok, paths)`; `export_path_to_string(path or None)` writes inches
  from the image resolution. `Gimp.Path.new_from_text_layer(image, layer)` places the outline at the
  layer's offsets. Paths survive XCF. Text along Path has no PDB procedure in 3.2: the text tool runs
  `gimp_path_warp_path(path, text_outline, 0.5 * layer_height)` (`app/tools/gimptexttool.c`,
  `app/path/gimppath-warp.c`): x is a distance along the strokes, y an offset along the normal
  (estimated over ±2 px); GIMP puts points before the start at (0, 0), gimp-mcp extends the first
  tangent instead.
* **Resources** (checked 2026-11-08): `Gimp.Brush/Gradient/Pattern/Palette.get_by_name(name)`
  (`None` when missing), `Gimp.brushes_get_list(filter)` etc.; built-in names are localized.
  `Gimp.Brush.new(name)` makes an editable generated brush; setters return `(ok, value)`.
  `brush.get_buffer()` exists only for color brushes (a mask-only brush logs a GLib warning and
  returns `None`): use `get_mask(w, h, Babl.format("Y' u8"))`. `Gimp.Gradient.new` starts with one
  black-to-white segment; `segment_range_split_uniform`, `segment_range_delete`,
  `segment_set_right_pos`, `segment_set_left/right_color`, `segment_range_set_blending_function`,
  `segment_range_set_coloring_type`, `get_uniform_samples(n, reverse)`. `Gimp.Palette.add_entry`,
  `delete_entry`, `set_columns`, `get_entry_name(i)` → `(ok, name)`. `resource.duplicate()` names
  the copy after the original (localized "Copy of"), `rename`, `delete` (built-ins:
  `is_editable()` is false). A created resource's file is written at once; edits are written only
  when GIMP exits normally (SIGTERM loses them). The data folder loads palettes from `.gpl` only;
  the dialog's importers (`app/core/gimppalette-load.c`, read 2026-11-08) are not in the PDB. Their
  conventions, followed by `gimp_mcp/palettes.py`: ACO RGB/HSB values are 16-bit (HSB as fractions of
  65536), ACO grayscale 0..10000 is ink (0 = white), ACT/RIFF colors are sRGB bytes; GIMP converts
  CMYK naively (no profile), which gimp-mcp refuses instead. GIMP's ACT loader reads all 256
  triplets and ignores the count stored in 772-byte files;
  `gimp-palette-export-{css,java,php,python,text}` (Script-Fu, context palette, `dirname` +
  file name) and `python-fu-palette-export-as-kpl` export palettes.
* **Composition** (checked 2026-11-08): `Gimp.edit_copy([drawables])`, `edit_cut`,
  `edit_copy_visible(image)` use the global clipboard; `edit_named_copy(drawables, name)`,
  `edit_named_copy_visible`, `edit_named_paste(drawable, name, paste_into)` and
  `edit_named_paste_as_new_image(name)` use named buffers. A paste creates a floating selection
  (`image.get_floating_sel()`), named "<layer> copy" (localized), that must be anchored
  (`Gimp.floating_sel_anchor`) or turned into a layer (`Gimp.floating_sel_to_layer`).
  `Gimp.Layer.new_from_visible(image, dest, name)`, `image.merge_down(layer, type)`,
  `image.merge_visible_layers(type)`, `group.merge()`, `image.flatten()`, `layer.flatten()` (drops
  alpha), `layer.add_alpha()`, `resize_to_image_size()`, `resize(w, h, offx, offy)`,
  `image.autocrop(None)` and `image.autocrop_selected_layers(layer)` exist; `plug-in-autocrop`
  does not in 3.2.
* **Guides, metadata, units** (checked 2026-11-08): `image.add_hguide(y)`/`add_vguide(x)` return
  ids; `find_next_guide(0)` iterates (newest first); `get_guide_orientation`, `get_guide_position`,
  `delete_guide`. `add_sample_point(x, y)`, `find_next_sample_point`, `get_sample_point_position`
  → `(x, y)` (no ok flag), `delete_sample_point`. `image.get_metadata()` is a `Gimp.Metadata`
  (a GExiv2 metadata: `get_exif_tags`, `get_tag_interpreted_string`, `try_set_tag_string`,
  `clear_tag`), stored back with `image.set_metadata`. The comment is the `gimp-comment`
  parasite; the JPEG exporter writes it with a trailing NUL. Exporters take `include-exif`,
  `include-xmp`, `include-iptc`, `include-comment`, `include-thumbnail`. `Gimp.Unit.inch()/mm()/
  point()/pica()` with `get_factor()` (units per inch); `image.set_unit`, `set_resolution`.
* **File procedures** (checked 2026-11-08): `pdb.lookup_procedure("file-png-export")` is a plain
  `GimpPDBProcedure` in another plug-in: no `get_extensions()`/`get_mime_types()`, so extensions
  are not discoverable (61 `file-*-export` procedures in 3.2.6). Export configs take `image`,
  `file`, `options` (default) plus format options; exporters convert a copy as needed (RGB → GIF
  works). TIFF writes one page per layer (background first); PSD keeps layers; ICO writes one size
  per layer; PDF `layers-as-pages` defaults to false. `file-pdf-load`'s `pages` is a
  `GimpInt32Array` of 0-based page numbers: `set_property` refuses a list and a `GObject.Value`, but
  accepts the boxed array (`v = GObject.Value(Gimp.Int32Array); Gimp.value_set_int32_array(v, [0, 2]);
  config.set_property("pages", v.get_boxed())`, checked 2026-11-08). Pages load in the order given,
  the last on top, each layer named after its page number; a page beyond the end makes the
  procedure fail ("Page N is out of range", N 0-based). Without `pages` every page loads.
* RAW (checked 2026-11-08, GIMP 3.2.6, darktable 5.6.2 in a container): `file-darktable` runs
  `darktable --gimp file <path>` (darktable's darkroom window; the image comes back when it is
  closed) and `file-rawtherapee` runs `rawtherapee -gimp <in> <out>` (its editor window): neither is
  non-interactive (`plug-ins/file-raw/*.c` on the `gimp-3-2` branch). GIMP registers the darktable
  loader only if `darktable --gimp version` writes nothing on stderr (or, before 4.6, `--version`
  says "this is darktable" with Lua): darktable's sandbox and input warnings in a container are
  enough to skip it, leaving `file-raw-placeholder-*-load`, which fails. `darktable-cli in.dng
  out.png` itself decodes a linear DNG headless.
  The PDF exporter logs Gtk-CRITICAL warnings headless (harmless).
* **Paint tools** (checked 2026-11-08): the PDB paint procedures (`gimp-paintbrush`, `-pencil`,
  `-airbrush`, `-eraser`, `-smudge`, `-dodgeburn`, `-clone`, `-heal`) take `strokes` as a
  `GimpDoubleArray`, which a procedure config cannot receive from Python ("could not convert");
  libgimp's functions `Gimp.paintbrush(drawable, fade_out, strokes, method, gradient_length)`,
  `Gimp.pencil`, `Gimp.airbrush`, `Gimp.clone(drawable, source, type, x, y, strokes)`, `Gimp.heal`,
  `Gimp.dodgeburn`, `Gimp.smudge`, `Gimp.eraser` accept a Python list. There is no `gimp-ink`:
  stroke a path with `context_set_paint_method("gimp-ink")` + `StrokeMethod.PAINT_METHOD`. Heal
  keeps the colors around the stroke (a uniform area is unchanged). Dynamics names are translated;
  `context_set_dynamics_name("Dynamics Off")` works with the internal name.
  `drawable.edit_gradient_fill(type, offset, supersample, depth, threshold, dither, x1, y1, x2, y2)`
  and `drawable.edit_bucket_fill(fill_type, x, y)` use the context gradient/threshold/criterion.
* **Transforms** (checked 2026-11-08): `item.transform_perspective(x0, y0, x1, y1, x2, y2, x3, y3)`,
  `transform_shear(orientation, magnitude)`, `transform_matrix(c00 … c22)`,
  `transform_rotate(radians, auto_center, cx, cy)` work on layers, paths, channels and the
  selection (`image.get_selection()`), and return the transformed item. Interpolation softens a
  transformed selection's edge by one pixel. `Gimp.TransformResize` nicks: `adjust`, `clip`, `crop`,
  `crop-with-aspect`. `image.rotate(Gimp.RotationType.DEGREES90)`, `image.flip(orientation)`.
* **Selections and channels** (checked 2026-11-08): `image.select_color(op, drawable, color)` and
  `select_contiguous_color(op, drawable, x, y)` use the context's sample threshold (0-1), criterion,
  sample merged/transparent, diagonal neighbours, antialias and feather. `image.select_item(op,
  item)` takes layers (alpha), text layers, paths, channels. `Gimp.Selection.grow/shrink/border/
  feather/sharpen/flood/translate(image, …)`; "Remove holes" is `flood`. Rounding is Script-Fu
  `script-fu-selection-round` (`drawables` through `config.set_core_object_array`, `adjustment` %).
  `Gimp.Selection.save(image)` stores the selection as a channel; `Gimp.Channel.new_from_component`
  must be inserted by hand; `channel.combine_masks(other, op, dx, dy)`. Channels survive XCF.
* **Vector and link layers** (checked 2026-11-08): `Gimp.VectorLayer.new(image, path)` (white fill,
  6 px stroke by default) then `insert_layer`; `set_fill_color`, `set_enable_fill`,
  `set_stroke_*` (`get_stroke_dash_pattern()` returns `(ok, pattern)`), then `refresh()` to render.
  `Gimp.LinkLayer.new(image, GFile)`, `set_file`, `get_file`, `get_mime_type`. Both subclass
  `Gimp.Layer` (test them before `Layer` in type checks). An XCF keeps a link layer's path and
  pixels; opening it re-reads the file, a missing file leaves the saved pixels.
* **Text styling** (checked 2026-11-08): `layer.set_markup(pango_markup)`, `get_markup()` (empty
  without per-run styles). `get_outline_width()` and `get_indent()` return `(value, unit)`;
  `set_outline_width(width, unit)` needs the unit. Enum nicks: `Gimp.TextOutline` `none`,
  `stroke-only`, `stroke-fill`; `Gimp.TextHintStyle` `none`…`full`; `Gimp.TextDirection` `ltr`,
  `rtl`, `ttb-*`. `set_base_direction(RTL)` does not change horizontal layouts: Pango's
  automatic direction (first strong character) wins, so Hebrew renders right to left anyway; the
  `ttb-*` directions make the layout vertical. `layer.resize(w, h)` fixes the text box. There is no
  "text along path" procedure in the 3.2 PDB.
* **Animations** (checked 2026-11-08): `file-gif-export` (`as-animation`, `loop`,
  `default-delay`, `default-dispose`, `force-delay`, `force-dispose`) and `file-webp-export`
  (`animation`, `animation-loop`, `default-delay`, `force-delay`) read `(NNms)` and
  `(combine|replace)` from layer names. `plug-in-animationoptimize`, `-optimize-diff` and
  `-unoptimize` return a new image (`result.index(1)`). There is `file-apng-load` but no APNG
  exporter. Pillow 13 does not report WebP frame durations: read the `ANMF` chunks.
* AF_UNIX socket paths longer than ~107 bytes fail with `OSError: AF_UNIX path
  too long`.
* Vector layers (3.2.6): fill and stroke **patterns** can be read (`get_fill_pattern`,
  `get_stroke_pattern`) but neither libgimp nor the PDB has a setter (no
  `gimp-vector-layer-set-fill-pattern`; `tests/e2e/test_vector_layers.py`), so gimp-mcp sets colors only.
* PyGObject lazy enum lookup can go wrong late in a long plug-in session: after the whole e2e suite
  (many drawable filter configs created), the first access to `Gimp.TransferMode` returned the class
  `GimpDrawableFilterConfig-gegl-hue-chroma` (`AttributeError: ... no attribute 'MIDTONES'`), while
  the same paint test passed alone or after any single other test file. Enums the bridge needs late
  are resolved when the plug-in starts (`TRANSFER_MIDTONES`, `DODGE_BURN_TYPES` in `gmb_ops.py`);
  the full suite then passes.
* Batch (#61): a corrupt PNG makes `Gimp.file_load` return no image (GIMP logs the libpng error):
  the batch reports `UNSUPPORTED_FORMAT` at the opening step, nothing stays open, and the other
  files still run. Closing with `discard_changes` leaves input files byte-for-byte unchanged
  (`tests/e2e/test_batch.py`).
* **Windows and macOS** (checked 2026-11-08 on GitHub runners, GIMP 3.2.6 from gimp.org, ADR 0008):
  macOS: `gimp-3.2.6-arm64.dmg` holds `GIMP.app`; `Contents/MacOS/gimp-console-3.2` (also
  `gimp-console` symlinks) and `python3` (3.14.7, PyGObject 3.56, GLib 2.88); profile
  `~/Library/Application Support/GIMP/3.2`; GIMP's Python has `AF_UNIX`, `LOCAL_PEERCRED` and
  `GLib.unix_fd_add_full` (deprecated for `GLibUnix.fd_add_full`). Windows: `gimp-3.2.6-setup.exe
  /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR=C:\gimp` installs without prompts;
  `bin\gimp-console-3.2.exe` and `bin\python.exe` (3.14.7 MinGW, PyGObject 3.58, GLib 2.90); profile
  `%APPDATA%\GIMP\3.2`; GIMP's Python has no `socket.AF_UNIX` and no `GLib.unix_fd_add_full`, but has
  `_winapi` named pipes, `ctypes` and `GLib.io_add_watch`, and Gio listens on a Unix socket. On both,
  `gimp-console -i --batch-interpreter=python-fu-eval -b <code> --quit` runs Python headless;
  `-b "Gimp.quit()"` fails ("returned no return values") and leaves GIMP running. `XDG_RUNTIME_DIR` is
  unset. The runners' own CPython: macOS has `AF_UNIX`/`LOCAL_PEERCRED`, Windows has neither (named
  pipes only). On macOS a plug-in that walks every filter (`Gimp.DrawableFilter.new(...).get_config()`
  and its properties) crashes with a segmentation fault after "type name GeglBuffer is not registered"
  (`gimp_gp_param_to_value`); touching `Gegl.Buffer.__gtype__` first registers the type and the same
  walk completes (checked by replaying it on the runner). In the bridge itself the crash moved on (the
  opt-in trace `GIMP_MCP_TRACE=<file>` ended on an ordinary operation): the trigger is earlier, when
  libgimp deserializes an operation's `GeglParamFormat` (a `gpointer` value: "unsupported deserialization
  to GValue of type 'gpointer'"), `GeglBuffer`, `GeglNode` or pointer parameter. Linux drops such
  properties silently. GEGL knows each operation's parameters in-process, but only after `Gegl.init(None)`
  in the plug-in (0 operations before, 291 after on 3.2.6); 15 GEGL operations have such parameters, and
  `gegl:checkerboard` is the only one among the 200 GIMP offers as filters. The crash that remained
  was cumulative, located by replaying the catalog walk three times in one process on the runner:
  creating 400 filters and reading their configs is fine, but `pspec.enum_class` (PyGObject's enum
  class of a param spec) crashes the plug-in after about 150 to 190 lookups, with or without
  `filter.delete()`. Reading a value of the enum and using `type(value).__enum_values__`, once per
  enum type, does not (three full walks complete). Operations refused by name (internal `gimp:` layer
  modes, denied, auxiliary) are no longer instantiated at all. The macOS build has no
  `gegl:gluas` (no Lua), and its AVIF exporter fails on lossless output ("AOM encoder error: Invalid
  parameter - Only --enable_chroma_deltaq=0 can be used with --lossless=1"); lossy AVIF is not affected. GIMP's own Python is used for plug-ins
  (`Contents/MacOS/python3`, `bin\python.exe`): the system `python3` does not matter there.
* **Windows named pipes** (checked 2026-11-08 on the `windows-2025` runner, ADR 0008): GIMP's Python
  serves the pipe with `ctypes` (`CreateNamedPipeW`), every Win32 function needs full `argtypes`/
  `restype` (handles are 64-bit; `GetCurrentProcess()` is -1), and the handles must be overlapped: a
  pending synchronous `ReadFile` in the reader thread blocks a `WriteFile` from GIMP's main thread on the
  same handle. GLib's `idle_add` hands requests to GIMP's main thread. `Path(r"\\.\pipe\x").exists()`
  opens the pipe (it consumes an instance, or raises WinError 231 when all are busy): never stat a pipe.
  The runner's user is the built-in Administrator, whose SID an SDDL string writes as `LA`. GIMP keeps
  a CR in palette names read from a `.gpl` written with CRLF: write `.gpl` files with `\n` only. A
  pluginrc on Windows lists the plug-in with escaped backslashes. The CI e2e suite runs on GIMP 3.2.6
  installed with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS`.
  GIMP for Windows starts `gdbus.exe` (GLib's D-Bus session bus, from GIMP's `bin`), which listens on
  TCP loopback (`127.0.0.1` and `::1`, a random port): it is GIMP's, not gimp-mcp's, and nothing in
  GIMP's process tree listens on any other address (`tests/e2e/test_no_network.py`).
* Linear light (seen by the agent evaluation, #106, GIMP 3.2.6): a Normal layer at 50% opacity
  composites in linear RGB, so 50% of (220, 30, 30) over (40, 80, 200) is (163, 61, 148), not the
  sRGB average (130, 55, 115); `gegl:gaussian-blur` also works in linear light, so an 8 px
  black-and-white checkerboard blurred flat becomes (188, 188, 188), the linear midpoint.
* Heal and clone (seen building the restoration demo, #108, GIMP 3.2.6): a single-point `heal` stroke
  (`gimp-heal`) on a 6 px dust spot with a 15 px brush at hardness 1 brings it back to the clean color
  (within 10/255); at hardness 0.6 the soft edge keeps part of the spot. Along a scratch, each heal dab's
  edge lies on the scratch, so heal carries it back in (still visible); `clone` along the stroke with the
  same offset removes it, except where the source offset crosses an edge of the picture.
* Built-in sRGB is "no profile" (seen building the product cut-out demo, #109, GIMP 3.2.6): after
  `set_color_profile` with the built-in sRGB, `get_color_profile()` is still `None`, so an export that
  embeds "the assigned profile" embeds nothing: a lossless WebP comes out as a plain `VP8L` file without
  `ICCP` chunk. Assigning a non-built-in profile (an sRGB ICC file, or sRGB linear) makes
  `file-webp-export` (`include-color-profile`) write a `VP8X` file with an `ICCP` chunk (#158).
* GIMP with its interface (#105, GIMP 3.2.6 on Linux/Xvfb, macOS 15 and Windows Server 2025): an MCP call
  that draws a filled and stroked rectangle is **one** step of GIMP's undo history (one Ctrl+Z restores
  every pixel); a user's Edit › Fill with FG between two calls keeps the layer id, and a checkpoint taken
  before it restores the pixels; Ctrl+W on an unchanged image closes it without asking, and the next call
  on it gets `NOT_FOUND`; Ctrl+Q with nothing unsaved quits GIMP, the next call fails, and the same MCP
  session works again once GIMP is started again. On Xvfb without a window manager, GIMP accepts
  `xdotool key --window` (synthetic events).

"""Bridge operations: the only module that calls the GIMP API.

Each operation takes a ``params`` dict (already JSON-decoded) and returns a
JSON-serializable value. Anticipated failures raise ``BridgeError`` *before*
changing anything; validation of argument types/ranges is done by the MCP
server, the checks here guard against stale ids and GIMP-side conditions.
"""

import os

import gi

gi.require_version("Babl", "0.1")
import gmb_align  # noqa: E402
import gmb_color  # noqa: E402
import gmb_filters  # noqa: E402
import gmb_formats  # noqa: E402
import gmb_policy  # noqa: E402
import gmb_resources  # noqa: E402
import gmb_stats  # noqa: E402
import gmb_undo  # noqa: E402
from gi.repository import Babl, Gegl, Gimp, Gio  # noqa: E402
from gmb_server import BridgeError  # noqa: E402

# Session id of this GIMP process (set by the plug-in entry point).
SESSION = {"id": ""}

# Displays created by the bridge, per image id (GUI sessions only).
_DISPLAYS = {}
_UI = {"available": None}


def mutation(fn):
    """Refresh GIMP's windows after a change (no-op without a UI)."""

    def wrapper(params):
        result = fn(params)
        Gimp.displays_flush()
        return result

    wrapper.__name__ = fn.__name__
    return wrapper


def show(image):
    """Open a window on the image when GIMP has a UI; returns whether it is displayed."""
    if _UI["available"] is False:
        return False
    try:
        display = Gimp.Display.new(image)
    except Exception:
        display = None
    if display is None:
        _UI["available"] = False
        return False
    _UI["available"] = True
    _DISPLAYS.setdefault(image.get_id(), []).append(display)
    return True


def color(rgba):
    """sRGB 0-1 floats -> GeglColor.

    GeglColor.set_rgba() and GEGL's CSS ``rgb()`` parser take *linear* RGB;
    '#rrggbb' in the API means sRGB, so the sRGB babl space is explicit.
    """
    value = Gegl.Color.new("black")
    value.set_rgba_with_space(rgba[0], rgba[1], rgba[2], rgba[3], Babl.space("sRGB"))
    return value


def _int_param(params, key):
    value = params.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise BridgeError("INVALID_ARGUMENT", "%s must be an integer id" % key)
    return value


def get_image(params, key="image"):
    number = _int_param(params, key)
    if not Gimp.Image.id_is_valid(number):
        raise BridgeError("NOT_FOUND", "image %d does not exist (closed?)" % number, {"kind": "image", "id": number})
    return Gimp.Image.get_by_id(number)


def get_item(params, key="item"):
    number = _int_param(params, key)
    if not Gimp.Item.id_is_valid(number):
        raise BridgeError("NOT_FOUND", "item %d does not exist (deleted?)" % number, {"kind": "item", "id": number})
    return Gimp.Item.get_by_id(number)


def item_kind(item):
    if isinstance(item, Gimp.LayerMask):
        return "mask"
    if isinstance(item, Gimp.TextLayer):
        return "text"
    if isinstance(item, Gimp.GroupLayer):
        return "group"
    if isinstance(item, Gimp.Layer):
        return "layer"
    if isinstance(item, Gimp.Channel):
        return "channel"
    if isinstance(item, Gimp.Path):
        return "path"
    return "unknown"


def get_layer(params, key="item"):
    item = get_item(params, key)
    if item_kind(item) not in ("layer", "group", "text"):
        raise BridgeError(
            "WRONG_KIND",
            "item %d is a %s, not a layer" % (item.get_id(), item_kind(item)),
            {"id": item.get_id(), "kind": item_kind(item)},
        )
    return item


# -- describing ------------------------------------------------------------------------


def _path(gfile):
    return None if gfile is None else gfile.get_path()


def image_summary(image):
    return {
        "id": image.get_id(),
        "name": image.get_name(),
        "file": _path(image.get_file()),
        "width": image.get_width(),
        "height": image.get_height(),
        "dirty": bool(image.is_dirty()),
    }


def mask_info(layer):
    mask = layer.get_mask()
    if mask is None:
        return None
    return {
        "id": mask.get_id(),
        "apply": bool(layer.get_apply_mask()),
        "show": bool(layer.get_show_mask()),
        "edit": bool(layer.get_edit_mask()),
    }


def layer_node(layer, recurse=True):
    _ok, x, y = layer.get_offsets()
    parent = layer.get_parent()
    node = {
        "id": layer.get_id(),
        "name": layer.get_name(),
        "kind": item_kind(layer),
        "parent": None if parent is None else parent.get_id(),
        "visible": bool(layer.get_visible()),
        "opacity": float(layer.get_opacity()),
        "mode": layer.get_mode().value_nick,
        "x": x,
        "y": y,
        "width": layer.get_width(),
        "height": layer.get_height(),
        "has_alpha": bool(layer.has_alpha()),
        "locks": {
            "content": bool(layer.get_lock_content()),
            "position": bool(layer.get_lock_position()),
            "visibility": bool(layer.get_lock_visibility()),
            "alpha": bool(layer.get_lock_alpha()),
        },
        "mask": mask_info(layer),
    }
    if node["kind"] == "group":
        children = layer.get_children()
        node["children"] = [layer_node(c) for c in children] if recurse else [c.get_id() for c in children]
    return node


def image_details(image):
    _ok, xres, yres = image.get_resolution()
    data = image_summary(image)
    data.update(
        {
            "xcf_file": _path(image.get_xcf_file()),
            "imported_file": _path(image.get_imported_file()),
            "exported_file": _path(image.get_exported_file()),
            "base_type": image.get_base_type().value_nick,
            "precision": image.get_precision().value_nick,
            "resolution": {"x": float(xres), "y": float(yres)},
            "unit": image.get_unit().get_abbreviation(),
            "layers": [layer_node(layer) for layer in image.get_layers()],
            "paths": [
                {
                    "id": p.get_id(),
                    "name": p.get_name(),
                    "visible": bool(p.get_visible()),
                    "strokes": len(p.get_strokes()),
                }
                for p in image.get_paths()
            ],
        }
    )
    return data


def item_details(item):
    kind = item_kind(item)
    image = item.get_image()
    if kind in ("layer", "group", "text"):
        data = layer_node(item, recurse=False)
        data["position"] = image.get_item_position(item)
    elif kind == "mask":
        owner = Gimp.Layer.from_mask(item)
        data = {
            "id": item.get_id(),
            "name": item.get_name(),
            "kind": kind,
            "parent": None if owner is None else owner.get_id(),
            "position": None,
            "visible": bool(item.get_visible()),
            "width": item.get_width(),
            "height": item.get_height(),
        }
    else:
        parent = item.get_parent()
        data = {
            "id": item.get_id(),
            "name": item.get_name(),
            "kind": kind,
            "parent": None if parent is None else parent.get_id(),
            "position": image.get_item_position(item),
            "visible": bool(item.get_visible()),
        }
    data["image"] = image.get_id()
    return data


# -- operations ------------------------------------------------------------------------


def session_images(params):
    hidden = checkpoint_image_ids()
    return {"images": [image_summary(image) for image in Gimp.get_images() if image.get_id() not in hidden]}


def image_inspect(params):
    return image_details(get_image(params))


def item_inspect(params):
    return item_details(get_item(params))


def _fit(width, height, max_size):
    """Largest size fitting in max_size x max_size with the same proportions, never upscaled."""
    scale = min(1.0, float(max_size) / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def image_preview(params):
    """Composite rendered by GIMP's projection; never modifies the image or its undo stack."""
    import base64

    image = get_image(params)
    max_size = int(params.get("max_size", 512))
    max_bytes = int(params.get("max_bytes", 2000000))
    if not 1 <= max_size <= 1024:
        raise BridgeError("INVALID_ARGUMENT", "max_size must be between 1 and 1024")
    width, height = image.get_width(), image.get_height()
    downscaled = False
    size = max_size
    while True:
        pw, ph = _fit(width, height, size)
        pixbuf = image.get_thumbnail(pw, ph, Gimp.PixbufTransparency.KEEP_ALPHA)
        if pixbuf is None:
            raise BridgeError("GIMP_ERROR", "GIMP could not render a %dx%d preview" % (pw, ph))
        ok, data = pixbuf.save_to_bufferv("png", [], [])
        if not ok:
            raise BridgeError("GIMP_ERROR", "PNG encoding of the preview failed")
        if len(data) <= max_bytes or size <= 16:
            break
        size = size // 2
        downscaled = True
    return {
        "image": image.get_id(),
        "png_base64": base64.b64encode(bytes(data)).decode("ascii"),
        "width": pixbuf.get_width(),
        "height": pixbuf.get_height(),
        "source_width": width,
        "source_height": height,
        "downscaled_for_size": downscaled,
    }


def image_ref(image, displayed=False):
    data = image_summary(image)
    data["xcf_file"] = _path(image.get_xcf_file())
    data["layer_count"] = len(image.get_layers())
    data["displayed"] = displayed or bool(_DISPLAYS.get(image.get_id()))
    return data


BASE_TYPES = {"rgb": Gimp.ImageBaseType.RGB, "gray": Gimp.ImageBaseType.GRAY}


@mutation
def image_create(params):
    base = BASE_TYPES[params["base_type"]]
    width, height, fill = params["width"], params["height"], params["fill"]
    transparent = fill[3] == 0
    if base == Gimp.ImageBaseType.RGB:
        layer_type = Gimp.ImageType.RGBA_IMAGE if transparent else Gimp.ImageType.RGB_IMAGE
    else:
        layer_type = Gimp.ImageType.GRAYA_IMAGE if transparent else Gimp.ImageType.GRAY_IMAGE
    image = Gimp.Image.new(width, height, base)
    image.undo_disable()  # like File > New: the creation is not an undoable step
    try:
        if params.get("resolution"):
            image.set_resolution(params["resolution"], params["resolution"])
        layer = Gimp.Layer.new(image, params["layer_name"], width, height, layer_type, 100.0, Gimp.LayerMode.NORMAL)
        image.insert_layer(layer, None, 0)
        if transparent:
            layer.fill(Gimp.FillType.TRANSPARENT)
        else:
            Gimp.context_push()
            try:
                Gimp.context_set_foreground(color(fill))
                layer.fill(Gimp.FillType.FOREGROUND)
            finally:
                Gimp.context_pop()
    finally:
        image.undo_enable()
    image.clean_all()
    return image_ref(image, show(image))


@mutation
def image_open(params):
    path = params["path"]
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    if image is None:
        raise BridgeError(
            "UNSUPPORTED_FORMAT",
            "GIMP could not load %s (unsupported format or corrupt file)" % os.path.basename(path),
            {"path": path},
        )
    return image_ref(image, show(image))


@mutation
def image_save(params):
    image = get_image(params)
    path = params.get("path")
    if path is None:
        current = image.get_xcf_file()
        if current is None:
            raise BridgeError(
                "INVALID_ARGUMENT",
                "the image was never saved as XCF: give a path",
                {"image": image.get_id()},
            )
        path = current.get_path()
    try:
        ok = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(path), None)
    except Exception as exc:
        raise BridgeError("WRITE_FAILED", "saving %s failed: %s" % (path, exc), {"path": path}) from exc
    if not ok:
        raise BridgeError("WRITE_FAILED", "GIMP could not write %s" % path, {"path": path})
    return {"xcf_file": path, "bytes": os.path.getsize(path), "dirty": bool(image.is_dirty())}


def _run_export(procedure_name, image, path, settings):
    procedure = Gimp.get_pdb().lookup_procedure(procedure_name)
    config = procedure.create_config()
    config.set_property("image", image)
    config.set_property("file", Gio.File.new_for_path(path))
    for key, value in settings.items():
        config.set_property(key, value)
    result = procedure.run(config)
    status = result.index(0)
    if status != Gimp.PDBStatusType.SUCCESS:
        message = ""
        try:
            message = str(result.index(1))
        except Exception:
            pass
        raise BridgeError("WRITE_FAILED", "export to %s failed %s" % (path, message), {"path": path})


def _metadata_settings(options):
    """Nothing is written unless asked: metadata=['exif', 'xmp', 'iptc', 'comment', 'thumbnail']."""
    keep = set(options.get("metadata") or [])
    return {"include-%s" % kind: kind in keep for kind in ("exif", "iptc", "xmp", "thumbnail", "comment")}


def _embed_profile(image, options):
    """Explicit choice, else embed only a profile the image has (GIMP's own default is never)."""
    if options.get("color_profile") is not None:
        return bool(options["color_profile"])
    return image.get_color_profile() is not None


@mutation
def image_export(params):
    image = get_image(params)
    path, kind, options = params["path"], params["format"], params["options"]
    if kind == "png":
        settings = _metadata_settings(options)
        settings.update({"compression": options["compression"], "interlaced": options["interlaced"], "bkgd": False})
        settings["include-color-profile"] = _embed_profile(image, options)
        _run_export("file-png-export", image, path, settings)
    elif kind == "jpeg":
        settings = _metadata_settings(options)
        settings.update(
            {
                "quality": options["quality"] / 100.0,
                "progressive": options["progressive"],
                "optimize": options["optimize"],
                "smoothing": options["smoothing"],
                "include-color-profile": _embed_profile(image, options),
            }
        )
        Gimp.context_push()
        try:
            Gimp.context_set_background(color(options["background"]))
            _run_export("file-jpeg-export", image, path, settings)
        finally:
            Gimp.context_pop()
    else:
        raise BridgeError("UNSUPPORTED_FORMAT", "unknown export format %r" % kind)
    return {"path": path, "width": image.get_width(), "height": image.get_height(), "bytes": os.path.getsize(path)}


@mutation
def image_close(params):
    image = get_image(params)
    if image.is_dirty() and not params.get("discard_changes"):
        raise BridgeError(
            "UNSAVED_CHANGES",
            "the image has unsaved changes",
            {"image": image.get_id()},
        )
    number = image.get_id()
    drop_checkpoints_of(number)
    for display in _DISPLAYS.pop(number, []):
        if display.is_valid():
            display.delete()
    if Gimp.Image.id_is_valid(number) and not image.delete():
        raise BridgeError(
            "IMAGE_IN_USE",
            "the image is shown in a GIMP window the bridge did not open; close it in GIMP",
            {"image": number},
        )
    return {"image": number}


# -- layers ------------------------------------------------------------------------------

LAYER_MODES = {}
for _value in Gimp.LayerMode.__enum_values__.values():
    LAYER_MODES.setdefault(_value.value_nick, _value)


def layer_mode(nick):
    mode = LAYER_MODES.get(nick)
    if mode is None:
        allowed = sorted(n for n in LAYER_MODES if not n.endswith("-legacy") and n != "replace")
        raise BridgeError("INVALID_ARGUMENT", "unknown layer mode %r" % nick, {"allowed": allowed})
    return mode


class undo_step:
    """Group several GIMP calls into one undo step."""

    def __init__(self, image):
        self.image = image

    def __enter__(self):
        self.image.undo_group_start()
        return self

    def __exit__(self, *exc):
        self.image.undo_group_end()
        return False


def same_image(image, item, role):
    if item.get_image().get_id() != image.get_id():
        raise BridgeError(
            "IMAGE_MISMATCH",
            "%s %d belongs to image %d, not image %d"
            % (role, item.get_id(), item.get_image().get_id(), image.get_id()),
            {"item": item.get_id(), "image": image.get_id()},
        )


def resolve_parent(image, params, key="parent"):
    if params.get(key) is None:
        return None
    parent = get_item(params, key)
    if item_kind(parent) != "group":
        raise BridgeError(
            "WRONG_KIND",
            "parent %d is a %s, not a group" % (parent.get_id(), item_kind(parent)),
            {"id": parent.get_id(), "kind": item_kind(parent)},
        )
    same_image(image, parent, "parent")
    return parent


def siblings(image, parent):
    return list(image.get_layers() if parent is None else parent.get_children())


def check_position(image, parent, position, moving=None):
    count = len([s for s in siblings(image, parent) if moving is None or s.get_id() != moving.get_id()])
    if position > count:
        raise BridgeError(
            "INVALID_ARGUMENT",
            "position %d is out of range: the parent has %d other item(s) (0..%d)" % (position, count, count),
            {"position": position, "max": count},
        )


LOCK_SETTERS = {
    "lock_content": "set_lock_content",
    "lock_position": "set_lock_position",
    "lock_visibility": "set_lock_visibility",
    "lock_alpha": "set_lock_alpha",
}


def apply_layer_properties(layer, params):
    for key, setter in LOCK_SETTERS.items():
        if params.get(key) is not None:
            getattr(layer, setter)(bool(params[key]))
    if params.get("mode") is not None:
        layer.set_mode(layer_mode(params["mode"]))
    if params.get("name") is not None:
        layer.set_name(params["name"])
    if params.get("visible") is not None:
        layer.set_visible(params["visible"])
    if params.get("opacity") is not None:
        layer.set_opacity(float(params["opacity"]))


@mutation
def layer_create(params):
    image = get_image(params)
    parent = resolve_parent(image, params)
    check_position(image, parent, params["position"])
    mode = layer_mode(params.get("mode") or "normal")
    width = params.get("width") or image.get_width()
    height = params.get("height") or image.get_height()
    kind = Gimp.ImageType.RGBA_IMAGE if image.get_base_type() == Gimp.ImageBaseType.RGB else Gimp.ImageType.GRAYA_IMAGE
    with undo_step(image):
        layer = Gimp.Layer.new(image, params["name"], width, height, kind, float(params.get("opacity", 100.0)), mode)
        image.insert_layer(layer, parent, params["position"])
        layer.set_offsets(params.get("x", 0), params.get("y", 0))
        fill = params.get("fill")
        if fill and fill[3] > 0:
            Gimp.context_push()
            try:
                Gimp.context_set_foreground(color(fill))
                layer.fill(Gimp.FillType.FOREGROUND)
            finally:
                Gimp.context_pop()
        else:
            layer.fill(Gimp.FillType.TRANSPARENT)
        layer.set_visible(bool(params.get("visible", True)))
        if params.get("name") and layer.get_name() != params["name"]:
            pass  # GIMP de-duplicated the name; the returned node shows the effective one
    return layer_node(layer)


@mutation
def group_create(params):
    image = get_image(params)
    parent = resolve_parent(image, params)
    check_position(image, parent, params["position"])
    with undo_step(image):
        group = Gimp.GroupLayer.new(image, params["name"])
        image.insert_layer(group, parent, params["position"])
    return layer_node(group)


@mutation
def layer_import(params):
    image = get_image(params)
    parent = resolve_parent(image, params)
    check_position(image, parent, params["position"])
    path = params["path"]
    with undo_step(image):
        layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(path))
        if layer is None:
            raise BridgeError(
                "UNSUPPORTED_FORMAT",
                "GIMP could not load %s (unsupported format or corrupt file)" % os.path.basename(path),
                {"path": path},
            )
        image.insert_layer(layer, parent, params["position"])
        layer.set_offsets(params.get("x", 0), params.get("y", 0))
        if params.get("name"):
            layer.set_name(params["name"])
    return layer_node(layer)


@mutation
def layer_duplicate(params):
    original = get_layer(params)
    image = original.get_image()
    if params.get("keep_parent"):
        parent = original.get_parent()
        position = image.get_item_position(original)
    else:
        parent = resolve_parent(image, params)
        position = params.get("position") or 0
        check_position(image, parent, position)
    with undo_step(image):
        copy = original.copy()
        image.insert_layer(copy, parent, position)
    return layer_node(copy)


@mutation
def layer_set(params):
    layer = get_layer(params)
    if params.get("mode") is not None:
        layer_mode(params["mode"])  # validate before changing anything
    if params.get("visible") is not None and layer.get_lock_visibility():
        raise BridgeError("LOCKED", "the layer's visibility is locked", {"item": layer.get_id()})
    with undo_step(layer.get_image()):
        apply_layer_properties(layer, params)
    return layer_node(layer)


def _is_ancestor(candidate, item):
    parent = item if candidate is None else candidate
    while parent is not None:
        if parent.get_id() == item.get_id():
            return True
        parent = parent.get_parent()
    return False


@mutation
def layer_move(params):
    layer = get_layer(params)
    image = layer.get_image()
    parent = resolve_parent(image, params)
    if parent is not None and _is_ancestor(parent, layer):
        raise BridgeError(
            "INVALID_ARGUMENT",
            "a group cannot be moved into itself or one of its descendants",
            {"item": layer.get_id()},
        )
    check_position(image, parent, params["position"], moving=layer)
    with undo_step(image):
        if not image.reorder_item(layer, parent, params["position"]):
            raise BridgeError("GIMP_ERROR", "GIMP refused to move item %d" % layer.get_id())
    return layer_node(layer)


@mutation
def layer_delete(params):
    layer = get_layer(params)
    layer.get_image().remove_layer(layer)
    return {"item": params["item"]}


# -- transforms --------------------------------------------------------------------------

INTERPOLATIONS = {v.value_nick: v for v in Gimp.InterpolationType.__enum_values__.values()}


def descendants(layer):
    yield layer
    if item_kind(layer) == "group":
        for child in layer.get_children():
            yield from descendants(child)


def require_unlocked(layer, position=False, content=False):
    for item in descendants(layer):
        if position and item.get_lock_position():
            raise BridgeError(
                "LOCKED", "the position of %r is locked" % item.get_name(), {"item": item.get_id(), "lock": "position"}
            )
        if content and item_kind(item) != "group" and item.get_lock_content():
            raise BridgeError(
                "LOCKED", "the pixels of %r are locked" % item.get_name(), {"item": item.get_id(), "lock": "content"}
            )


class transform_context:
    def __init__(self, interpolation="cubic", clip="adjust"):
        self.interpolation = INTERPOLATIONS[interpolation]
        self.clip = Gimp.TransformResize.CLIP if clip == "clip" else Gimp.TransformResize.ADJUST

    def __enter__(self):
        Gimp.context_push()
        Gimp.context_set_interpolation(self.interpolation)
        Gimp.context_set_transform_resize(self.clip)
        return self

    def __exit__(self, *exc):
        Gimp.context_pop()
        return False


def geometry(image):
    return {"width": image.get_width(), "height": image.get_height(), "dirty": bool(image.is_dirty())}


@mutation
def image_scale(params):
    image = get_image(params)
    with transform_context(params.get("interpolation", "cubic")):
        image.scale(params["width"], params["height"])
    return geometry(image)


@mutation
def image_resize(params):
    image = get_image(params)
    image.resize(params["width"], params["height"], params.get("offset_x", 0), params.get("offset_y", 0))
    return geometry(image)


@mutation
def image_crop(params):
    image = get_image(params)
    x, y, width, height = params["x"], params["y"], params["width"], params["height"]
    if x < 0 or y < 0 or x + width > image.get_width() or y + height > image.get_height():
        raise BridgeError(
            "INVALID_ARGUMENT",
            "crop rectangle (%d, %d, %dx%d) is not inside the %dx%d canvas"
            % (x, y, width, height, image.get_width(), image.get_height()),
            {"canvas": [image.get_width(), image.get_height()]},
        )
    image.crop(width, height, x, y)
    return geometry(image)


@mutation
def layer_offsets(params):
    layer = get_layer(params)
    require_unlocked(layer, position=True)
    with undo_step(layer.get_image()):
        layer.set_offsets(params["x"], params["y"])
    return layer_node(layer)


@mutation
def layer_scale(params):
    layer = get_layer(params)
    require_unlocked(layer, position=True, content=True)
    _ok, x, y = layer.get_offsets()
    with undo_step(layer.get_image()), transform_context(params.get("interpolation", "cubic")):
        layer.scale(params["width"], params["height"], True)
        if params.get("anchor") == "top-left":
            layer.set_offsets(x, y)
    return layer_node(layer)


@mutation
def layer_rotate(params):
    import math

    layer = get_layer(params)
    require_unlocked(layer, position=True, content=True)
    angle = float(params["angle"]) % 360.0
    if angle == 0.0:
        return layer_node(layer)
    with undo_step(layer.get_image()), transform_context(params.get("interpolation", "cubic"), params.get("clip")):
        result = layer.transform_rotate(math.radians(angle), True, 0, 0)
    if result is None:
        raise BridgeError("GIMP_ERROR", "GIMP refused to rotate item %d" % layer.get_id())
    return layer_node(result)


@mutation
def layer_flip(params):
    layer = get_layer(params)
    require_unlocked(layer, position=True, content=True)
    orientation = (
        Gimp.OrientationType.HORIZONTAL if params["direction"] == "horizontal" else Gimp.OrientationType.VERTICAL
    )
    with undo_step(layer.get_image()):
        result = layer.transform_flip_simple(orientation, True, 0)
    if result is None:
        raise BridgeError("GIMP_ERROR", "GIMP refused to flip item %d" % layer.get_id())
    return layer_node(result)


# -- procedure database (read-only introspection) ----------------------------------------


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    nick = getattr(value, "value_nick", None)
    if nick is not None:
        return nick
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return repr(value)


def describe_argument(pspec):
    data = {"name": pspec.name, "type": pspec.value_type.name, "description": pspec.get_blurb()}
    try:
        data["default"] = _jsonable(pspec.get_default_value())
    except Exception:
        data["default"] = None
    for attr in ("minimum", "maximum"):
        if hasattr(pspec, attr):
            data[attr] = _jsonable(getattr(pspec, attr))
    if type(pspec).__name__ == "ParamChoice":
        try:
            data["choices"] = list(Gimp.param_spec_choice_get_choice(pspec).list_nicks())
        except Exception:
            data["choices"] = None
    enum_class = getattr(pspec, "enum_class", None)
    if enum_class is not None:
        try:
            data["choices"] = [v.value_nick for v in enum_class.__enum_values__.values()]
        except Exception:
            pass
    return data


def describe_procedure(procedure):
    return {
        "name": procedure.get_name(),
        "type": procedure.get_proc_type().value_nick,
        "description": procedure.get_blurb(),
        "help": procedure.get_help(),
        "authors": procedure.get_authors(),
        "date": procedure.get_date(),
        "menu_label": procedure.get_menu_label(),
        "menu_paths": list(procedure.get_menu_paths() or []),
        "image_types": procedure.get_image_types(),
        "arguments": [describe_argument(a) for a in procedure.get_arguments()],
        "return_values": [describe_argument(r) for r in procedure.get_return_values()],
    }


def _all_names(pattern=".*"):
    return sorted(Gimp.get_pdb().query_procedures(pattern, ".*", ".*", ".*", ".*", ".*", ".*", ".*"))


def pdb_search(params):
    import re

    query = params.get("query") or ""
    limit = int(params.get("limit", 50))
    needle = re.escape(query)
    names = _all_names(".*%s.*" % needle) if query else _all_names()
    pdb = Gimp.get_pdb()
    found = []
    for name in names[:limit]:
        procedure = pdb.lookup_procedure(name)
        found.append({"name": name, "description": procedure.get_blurb() if procedure else None})
    return {"procedures": found, "total": len(names)}


def pdb_describe(params):
    name = params["name"]
    procedure = Gimp.get_pdb().lookup_procedure(name) if Gimp.get_pdb().procedure_exists(name) else None
    if procedure is None:
        raise BridgeError("NOT_FOUND", "no procedure named %r" % name, {"name": name})
    return describe_procedure(procedure)


def pdb_inventory(params):
    pdb = Gimp.get_pdb()
    procedures = []
    for name in _all_names():
        try:
            procedures.append(describe_procedure(pdb.lookup_procedure(name)))
        except Exception as exc:  # incomplete metadata must not break the inventory
            procedures.append({"name": name, "error": "%s: %s" % (type(exc).__name__, exc)})
    try:
        gegl = sorted(Gimp.DrawableFilter.operation_get_available())
    except Exception:
        gegl = []
    return {"gimp_version": Gimp.version(), "procedures": procedures, "gegl_operations": gegl}


# -- selections and masks ----------------------------------------------------------------

CHANNEL_OPS = {
    "replace": Gimp.ChannelOps.REPLACE,
    "add": Gimp.ChannelOps.ADD,
    "subtract": Gimp.ChannelOps.SUBTRACT,
    "intersect": Gimp.ChannelOps.INTERSECT,
}


def selection_state(image, probe=None):
    _ok, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
    state = {
        "empty": not non_empty,
        "bounds": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1} if non_empty else None,
        "contains": None,
    }
    if probe is not None:
        x, y = probe
        inside = 0 <= x < image.get_width() and 0 <= y < image.get_height()
        state["contains"] = bool(inside and Gimp.Selection.value(image, x, y) > 127)
    return state


def _select(image, params, shape):
    Gimp.context_push()
    try:
        feather = float(params.get("feather") or 0)
        Gimp.context_set_feather(feather > 0)
        Gimp.context_set_feather_radius(feather, feather)
        Gimp.context_set_antialias(True)
        operation = CHANNEL_OPS[params.get("operation", "replace")]
        if shape == "rect":
            image.select_rectangle(operation, params["x"], params["y"], params["width"], params["height"])
        else:
            image.select_ellipse(operation, params["x"], params["y"], params["width"], params["height"])
    finally:
        Gimp.context_pop()
    return selection_state(image)


@mutation
def selection_rect(params):
    return _select(get_image(params), params, "rect")


@mutation
def selection_ellipse(params):
    return _select(get_image(params), params, "ellipse")


@mutation
def selection_modify(params):
    image = get_image(params)
    action = params["action"]
    if action == "all":
        Gimp.Selection.all(image)
    elif action == "none":
        Gimp.Selection.none(image)
    elif action == "invert":
        Gimp.Selection.invert(image)
    else:
        raise BridgeError("INVALID_ARGUMENT", "unknown selection action %r" % action)
    return selection_state(image)


def selection_get(params):
    image = get_image(params)
    return selection_state(image, params.get("probe"))


MASK_TYPES = {
    "white": Gimp.AddMaskType.WHITE,
    "black": Gimp.AddMaskType.BLACK,
    "alpha": Gimp.AddMaskType.ALPHA,
    "selection": Gimp.AddMaskType.SELECTION,
    "grayscale": Gimp.AddMaskType.COPY,
}


@mutation
def mask_add(params):
    layer = get_layer(params)
    image = layer.get_image()
    if layer.get_mask() is not None:
        raise BridgeError("INVALID_ARGUMENT", "the layer already has a mask", {"item": layer.get_id()})
    if params["fill"] == "selection" and Gimp.Selection.is_empty(image):
        raise BridgeError("EMPTY_SELECTION", "nothing is selected", {"image": image.get_id()})
    with undo_step(image):
        mask = layer.create_mask(MASK_TYPES[params["fill"]])
        if not layer.add_mask(mask):
            raise BridgeError("GIMP_ERROR", "GIMP refused to add the mask")
        if params.get("invert"):
            mask.invert(False)
    return layer_node(layer)


def _require_mask(layer):
    if layer.get_mask() is None:
        raise BridgeError("INVALID_ARGUMENT", "the layer has no mask", {"item": layer.get_id()})


@mutation
def mask_set(params):
    layer = get_layer(params)
    _require_mask(layer)
    with undo_step(layer.get_image()):
        if params.get("apply") is not None:
            layer.set_apply_mask(bool(params["apply"]))
        if params.get("show") is not None:
            layer.set_show_mask(bool(params["show"]))
        if params.get("edit") is not None:
            layer.set_edit_mask(bool(params["edit"]))
    return layer_node(layer)


@mutation
def mask_remove(params):
    layer = get_layer(params)
    _require_mask(layer)
    mode = Gimp.MaskApplyMode.APPLY if params["mode"] == "apply" else Gimp.MaskApplyMode.DISCARD
    layer.remove_mask(mode)
    return layer_node(layer)


# -- painting ----------------------------------------------------------------------------


def get_paintable(params):
    item = get_item(params)
    kind = item_kind(item)
    if kind == "group":
        raise BridgeError("WRONG_KIND", "groups have no pixels: paint on one of their layers", {"item": item.get_id()})
    if kind == "text":
        raise BridgeError(
            "WRONG_KIND",
            "painting on a text layer would silently turn it into pixels; paint on another layer",
            {"item": item.get_id()},
        )
    if kind not in ("layer", "mask", "channel"):
        raise BridgeError("WRONG_KIND", "item %d is a %s, it cannot be painted" % (item.get_id(), kind))
    if kind == "layer" and item.get_lock_content():
        raise BridgeError("LOCKED", "the pixels of %r are locked" % item.get_name(), {"item": item.get_id()})
    return item


def drawable_rect(drawable):
    _ok, x, y = drawable.get_offsets()
    return (x, y, x + drawable.get_width(), y + drawable.get_height())


def intersect(box, rect):
    x1, y1 = max(box[0], rect[0]), max(box[1], rect[1])
    x2, y2 = min(box[2], rect[2]), min(box[3], rect[3])
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": int(x1), "y": int(y1), "width": int(x2 - x1), "height": int(y2 - y1)}


class paint_context:
    """Explicit painting settings; the user's context is restored afterwards."""

    CAPS = (("butt", "BUTT"), ("round", "ROUND"), ("square", "SQUARE"))
    JOINS = (("miter", "MITER"), ("round", "ROUND"), ("bevel", "BEVEL"))

    def __init__(self, params, color_key="color"):
        self.params = params
        self.color_key = color_key

    def __enter__(self):
        params = self.params
        Gimp.context_push()
        Gimp.context_set_defaults()
        if params.get(self.color_key) is not None:
            Gimp.context_set_foreground(color(params[self.color_key]))
        Gimp.context_set_opacity(float(params.get("opacity", 100.0)))
        Gimp.context_set_paint_mode(layer_mode(params.get("mode") or "normal"))
        Gimp.context_set_antialias(bool(params.get("antialias", True)))
        Gimp.context_set_stroke_method(Gimp.StrokeMethod.LINE)
        Gimp.context_set_line_width(float(params.get("width", 2.0)))
        Gimp.context_set_line_width_unit(Gimp.Unit.pixel())
        Gimp.context_set_line_cap_style(getattr(Gimp.CapStyle, dict(self.CAPS)[params.get("cap", "round")]))
        Gimp.context_set_line_join_style(getattr(Gimp.JoinStyle, dict(self.JOINS)[params.get("join", "round")]))
        return self

    def __exit__(self, *exc):
        Gimp.context_pop()
        return False


class saved_selection:
    """Temporarily replace the selection, restoring the user's afterwards."""

    def __init__(self, image):
        self.image = image
        self.channel = None

    def __enter__(self):
        if not Gimp.Selection.is_empty(self.image):
            self.channel = Gimp.Selection.save(self.image)
        Gimp.Selection.none(self.image)
        return self

    def __exit__(self, *exc):
        if self.channel is not None:
            self.image.select_item(Gimp.ChannelOps.REPLACE, self.channel)
            self.image.remove_channel(self.channel)
        else:
            Gimp.Selection.none(self.image)
        return False


@mutation
def paint_fill(params):
    drawable = get_paintable(params)
    layer_mode(params.get("mode") or "normal")
    image = drawable.get_image()
    rect = drawable_rect(drawable)
    if params["area"] == "selection":
        if Gimp.Selection.is_empty(image):
            raise BridgeError("EMPTY_SELECTION", "nothing is selected (use area='layer' to fill the whole layer)")
        _ok, _non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
        affected = intersect((x1, y1, x2, y2), rect)
        if affected is None:
            return {"changed": False, "affected": None}
        with undo_step(image), paint_context(params):
            drawable.edit_fill(Gimp.FillType.FOREGROUND)
    else:
        affected = intersect(rect, rect)
        with undo_step(image), paint_context(params), saved_selection(image):
            drawable.edit_fill(Gimp.FillType.FOREGROUND)
    return {"changed": True, "affected": affected}


def _points_box(points, margin):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


@mutation
def paint_path(params):
    import math

    drawable = get_paintable(params)
    image = drawable.get_image()
    points = params["points"]
    margin = float(params.get("width", 2.0)) / 2.0 + 1
    box = _points_box(points, margin)
    affected = intersect(
        (math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])), drawable_rect(drawable)
    )
    if affected is None:
        return {"changed": False, "affected": None}
    controls = []
    for x, y in points:
        controls += [float(x), float(y)] * 3
    with undo_step(image), paint_context(params):
        path = Gimp.Path.new(image, "gimp-mcp stroke")
        image.insert_path(path, None, 0)
        try:
            path.stroke_new_from_points(Gimp.PathStrokeType.BEZIER, controls, bool(params.get("closed")))
            if not drawable.edit_stroke_item(path):
                raise BridgeError("GIMP_ERROR", "GIMP refused to stroke the path")
        finally:
            image.remove_path(path)
    return {"changed": True, "affected": affected}


@mutation
def paint_shape(params):
    import math

    drawable = get_paintable(params)
    image = drawable.get_image()
    x, y, width, height = params["rect"]
    margin = float(params.get("width", 2.0)) / 2.0 + 1 if params.get("stroke") else 0
    box = (
        math.floor(x - margin),
        math.floor(y - margin),
        math.ceil(x + width + margin),
        math.ceil(y + height + margin),
    )
    affected = intersect(box, drawable_rect(drawable))
    if affected is None:
        return {"changed": False, "affected": None}
    with undo_step(image), saved_selection(image):
        Gimp.context_push()
        try:
            Gimp.context_set_antialias(bool(params.get("antialias", True)))
            Gimp.context_set_feather(False)
            if params["shape"] == "rectangle":
                image.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, width, height)
            else:
                image.select_ellipse(Gimp.ChannelOps.REPLACE, x, y, width, height)
        finally:
            Gimp.context_pop()
        if params.get("fill") is not None:
            with paint_context(params, color_key="fill"):
                drawable.edit_fill(Gimp.FillType.FOREGROUND)
        if params.get("stroke") is not None:
            with paint_context(params, color_key="stroke"):
                if not drawable.edit_stroke_selection():
                    raise BridgeError("GIMP_ERROR", "GIMP refused to stroke the shape")
    return {"changed": True, "affected": affected}


# -- filters -----------------------------------------------------------------------------

HUE_RANGES = {
    "all": "ALL",
    "red": "RED",
    "yellow": "YELLOW",
    "green": "GREEN",
    "cyan": "CYAN",
    "blue": "BLUE",
    "magenta": "MAGENTA",
}

NDE_OPERATIONS = {
    "brightness-contrast": "gimp:brightness-contrast",
    "hue-saturation": "gimp:hue-saturation",
    "gaussian-blur": "gegl:gaussian-blur",
}


def _nde_settings(operation, settings):
    if operation == "brightness-contrast":
        return {"brightness": settings["brightness"], "contrast": settings["contrast"]}
    if operation == "hue-saturation":
        return {
            "range": getattr(Gimp.HueRange, HUE_RANGES[settings["range"]]),
            "hue": settings["hue"] / 180.0,
            "saturation": settings["saturation"] / 100.0,
            "lightness": settings["lightness"] / 100.0,
            "overlap": settings["overlap"] / 100.0,
        }
    return {"std-dev-x": settings["std_dev_x"], "std-dev-y": settings["std_dev_y"]}


def _new_filter(drawable, operation, settings):
    gegl_name = NDE_OPERATIONS[operation]
    drawable_filter = Gimp.DrawableFilter.new(drawable, gegl_name, operation)
    config = drawable_filter.get_config()
    for key, value in _nde_settings(operation, settings).items():
        config.set_property(key, value)
    drawable_filter.update()
    return drawable_filter


def filter_info(drawable_filter):
    return {
        "id": drawable_filter.get_id(),
        "name": drawable_filter.get_name(),
        "operation": drawable_filter.get_operation_name(),
        "visible": bool(drawable_filter.get_visible()),
        "opacity": float(drawable_filter.get_opacity()) * 100.0,
    }


@mutation
def filter_apply(params):
    drawable = get_layer(params)
    image = drawable.get_image()
    operation = params["operation"]
    if operation not in NDE_OPERATIONS:
        raise BridgeError("INVALID_ARGUMENT", "unknown filter %r" % operation)
    settings = params["settings"]
    destructive = bool(params["destructive"])
    kind = item_kind(drawable)
    if destructive and kind != "layer":
        raise BridgeError(
            "WRONG_KIND",
            "a destructive filter needs a plain layer (%s given): use destructive=false on groups and text" % kind,
            {"item": drawable.get_id(), "kind": kind},
        )
    if destructive and drawable.get_lock_content():
        raise BridgeError("LOCKED", "the pixels of %r are locked" % drawable.get_name(), {"item": drawable.get_id()})
    restricted = not Gimp.Selection.is_empty(image)
    with undo_step(image):
        if destructive:
            if operation == "brightness-contrast":
                drawable.brightness_contrast(settings["brightness"], settings["contrast"])
            elif operation == "hue-saturation":
                drawable.hue_saturation(
                    getattr(Gimp.HueRange, HUE_RANGES[settings["range"]]),
                    settings["hue"],
                    settings["lightness"],
                    settings["saturation"],
                    settings["overlap"],
                )
            else:
                drawable.merge_filter(_new_filter(drawable, operation, settings))
            filter_id = None
        else:
            drawable_filter = _new_filter(drawable, operation, settings)
            drawable.append_filter(drawable_filter)
            filter_id = drawable_filter.get_id()
            if filter_id not in [f.get_id() for f in drawable.get_filters()]:
                raise BridgeError("GIMP_ERROR", "GIMP did not keep the editable filter on %r" % drawable.get_name())
    return {
        "operation": NDE_OPERATIONS[operation],
        "destructive": destructive,
        "filter": filter_id,
        "restricted_to_selection": restricted,
    }


def filter_list(params):
    drawable = get_layer(params)
    return {"filters": [filter_info(f) for f in drawable.get_filters()]}


@mutation
def filter_remove(params):
    drawable = get_layer(params)
    wanted = params["filter"]
    for drawable_filter in drawable.get_filters():
        if drawable_filter.get_id() == wanted:
            with undo_step(drawable.get_image()):
                drawable_filter.delete()
            return {"filters": [filter_info(f) for f in drawable.get_filters()]}
    raise BridgeError("NOT_FOUND", "filter %d is not on item %d" % (wanted, drawable.get_id()), {"filter": wanted})


# -- GEGL filter catalog (#47) -----------------------------------------------------------

_CATALOG = {}  # operation -> {"title", "description", "categories", "parameters", "supported", "reason"}


def _param_kind(pspec):
    cls = type(pspec).__name__
    if cls in ("ParamSpecDouble", "ParamSpecFloat"):
        return "number"
    if cls in ("ParamSpecInt", "ParamSpecUInt", "ParamSpecInt64", "ParamSpecUInt64", "ParamSpecLong"):
        return "integer"
    if cls == "ParamSpecBoolean":
        return "boolean"
    if cls == "ParamChoice":
        return "choice"
    if cls == "ParamSpecEnum":
        return "enum"
    if cls == "ParamColor":
        return "color"
    if cls == "ParamSpecString":
        return "string"
    return "unsupported"


def _config_value(value):
    """A filter config value -> JSON."""
    if isinstance(value, Gegl.Color):
        r, g, b, a = value.get_rgba_with_space(Babl.space("sRGB"))
        return "#%02x%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b, a))
    if isinstance(value, float):
        return round(value, 6)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    nick = getattr(value, "value_nick", None)
    return nick if nick is not None else None


def _describe_filter_params(config):
    specs = []
    for pspec in config.list_properties():
        kind = _param_kind(pspec)
        spec = {"name": pspec.name, "kind": kind, "description": pspec.get_blurb()}
        if kind in ("number", "integer"):
            spec["min"], spec["max"] = pspec.minimum, pspec.maximum
            if kind == "number":
                spec["min"], spec["max"] = round(spec["min"], 6), round(spec["max"], 6)
        elif kind == "choice":
            spec["choices"] = list(Gimp.param_spec_choice_get_choice(pspec).list_nicks())
        elif kind == "enum":
            spec["choices"] = [v.value_nick for v in pspec.enum_class.__enum_values__.values()]
        elif kind == "unsupported":
            spec["type"] = pspec.value_type.name
        spec["default"] = _config_value(config.get_property(pspec.name)) if kind != "unsupported" else None
        specs.append(spec)
    return specs


def filter_catalog():
    """Every operation GIMP offers to filters, introspected once per GIMP session."""
    if _CATALOG:
        return _CATALOG
    scratch = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
    try:
        scratch.undo_disable()
        layer = Gimp.Layer.new(scratch, "scratch", 8, 8, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
        scratch.insert_layer(layer, None, 0)
        for name in Gimp.DrawableFilter.operation_get_available():
            _ok, keys, values = Gimp.DrawableFilter.operation_get_details(name)
            details = {key: values.index(i) for i, key in enumerate(keys)}
            categories = [c for c in (details.get("categories") or "").split(":") if c]
            try:
                params = _describe_filter_params(Gimp.DrawableFilter.new(layer, name, "catalog").get_config())
            except Exception as error:  # an operation GIMP lists but cannot instantiate
                params, broken = [], "GIMP could not create it: %s" % error
            else:
                broken = None
            supported, reason = gmb_filters.operation_status(name, categories, [p["kind"] for p in params])
            if broken:
                supported, reason = False, broken
            _CATALOG[name] = {
                "name": name,
                "title": details.get("title") or name,
                "description": details.get("description") or "",
                "categories": categories,
                "parameters": params,
                "supported": supported,
                "reason": reason,
            }
    finally:
        scratch.delete()
    return _CATALOG


def filter_operations(params):
    query = (params.get("query") or "").lower()
    category = params.get("category")
    found = []
    for entry in filter_catalog().values():
        if category and category not in entry["categories"]:
            continue
        if query and query not in (entry["name"] + " " + entry["title"]).lower():
            continue
        found.append({k: entry[k] for k in ("name", "title", "categories", "supported", "reason")})
    return {"operations": sorted(found, key=lambda e: e["name"])}


def _catalog_entry(name):
    entry = filter_catalog().get(name)
    if entry is None:
        raise BridgeError(
            "NOT_FOUND", "GIMP offers no filter operation %r (see gimp_list_filter_operations)" % name, {"name": name}
        )
    return entry


def filter_operation_describe(params):
    return dict(_catalog_entry(params["operation"]))


def _filter_values(entry, parameters):
    try:
        return gmb_filters.validate(entry["parameters"], parameters or {})
    except gmb_filters.InvalidParameter as error:
        raise BridgeError("INVALID_ARGUMENT", "%s: %s" % (entry["name"], error), {"operation": entry["name"]}) from None


def _set_config(drawable_filter, entry, values):
    config = drawable_filter.get_config()
    specs = {spec["name"]: spec for spec in entry["parameters"]}
    for name, value in values.items():
        kind = specs[name]["kind"]
        if kind == "color":
            value = color(value)
        elif kind == "enum":
            pspec = config.find_property(name)
            value = next(v for v in pspec.enum_class.__enum_values__.values() if v.value_nick == value)
        config.set_property(name, value)


def filter_state(drawable_filter):
    entry = filter_catalog().get(drawable_filter.get_operation_name())
    config = drawable_filter.get_config()
    parameters = {}
    for spec in entry["parameters"] if entry else []:
        if spec["kind"] != "unsupported":
            parameters[spec["name"]] = _config_value(config.get_property(spec["name"]))
    data = filter_info(drawable_filter)
    data["mode"] = drawable_filter.get_blend_mode().value_nick
    data["parameters"] = parameters
    return data


def _check_filterable(drawable, destructive):
    kind = item_kind(drawable)
    if destructive and kind != "layer":
        raise BridgeError(
            "WRONG_KIND",
            "a destructive filter needs a plain layer (%s given): use destructive=false on groups and text" % kind,
            {"item": drawable.get_id(), "kind": kind},
        )
    if destructive and drawable.get_lock_content():
        raise BridgeError("LOCKED", "the pixels of %r are locked" % drawable.get_name(), {"item": drawable.get_id()})


def _filter_appearance(params):
    """Validated opacity (0-1), mode and visibility from params, or None for each missing one."""
    opacity = params.get("opacity")
    mode = layer_mode(params["mode"]) if params.get("mode") is not None else None
    return (None if opacity is None else float(opacity) / 100.0), mode, params.get("visible")


def _apply_appearance(drawable_filter, opacity, mode, visible):
    if opacity is not None:
        drawable_filter.set_opacity(opacity)
    if mode is not None:
        drawable_filter.set_blend_mode(mode)
    if visible is not None:
        drawable_filter.set_visible(bool(visible))


@mutation
def filter_apply_any(params):
    drawable = get_layer(params)
    entry = _catalog_entry(params["operation"])
    if not entry["supported"]:
        raise BridgeError(
            "UNSUPPORTED", "%s cannot be applied: %s" % (entry["name"], entry["reason"]), {"operation": entry["name"]}
        )
    values = _filter_values(entry, params.get("parameters"))
    destructive = bool(params.get("destructive"))
    _check_filterable(drawable, destructive)
    opacity, mode, visible = _filter_appearance(params)
    image = drawable.get_image()
    restricted = not Gimp.Selection.is_empty(image)
    with undo_step(image):
        drawable_filter = Gimp.DrawableFilter.new(drawable, entry["name"], params.get("name") or entry["title"])
        _set_config(drawable_filter, entry, values)
        _apply_appearance(drawable_filter, opacity, mode, visible)
        drawable_filter.update()
        if destructive:
            state = filter_state(drawable_filter)
            drawable.merge_filter(drawable_filter)
            state["id"] = None
        else:
            drawable.append_filter(drawable_filter)
            if drawable_filter.get_id() not in [f.get_id() for f in drawable.get_filters()]:
                raise BridgeError("GIMP_ERROR", "GIMP did not keep the editable filter on %r" % drawable.get_name())
            state = filter_state(drawable_filter)
    return {"filter": state, "destructive": destructive, "restricted_to_selection": restricted}


def _get_filter(drawable, number):
    for drawable_filter in drawable.get_filters():
        if drawable_filter.get_id() == number:
            return drawable_filter
    raise BridgeError("NOT_FOUND", "filter %d is not on item %d" % (number, drawable.get_id()), {"filter": number})


def filter_inspect(params):
    drawable = get_layer(params)
    return filter_state(_get_filter(drawable, _int_param(params, "filter")))


@mutation
def filter_set(params):
    drawable = get_layer(params)
    drawable_filter = _get_filter(drawable, _int_param(params, "filter"))
    entry = _catalog_entry(drawable_filter.get_operation_name())
    values = _filter_values(entry, params.get("parameters"))
    opacity, mode, visible = _filter_appearance(params)
    with undo_step(drawable.get_image()):
        _set_config(drawable_filter, entry, values)
        _apply_appearance(drawable_filter, opacity, mode, visible)
        drawable_filter.update()
    return filter_state(drawable_filter)


def _detached_copy(drawable, old):
    """A new filter with the operation, parameters and appearance of ``old``, not yet in the stack."""
    copy = Gimp.DrawableFilter.new(drawable, old.get_operation_name(), old.get_name())
    source, target = old.get_config(), copy.get_config()
    for pspec in source.list_properties():
        target.set_property(pspec.name, source.get_property(pspec.name))
    _apply_appearance(copy, old.get_opacity(), old.get_blend_mode(), old.get_visible())
    return copy


@mutation
def filter_reorder(params):
    drawable = get_layer(params)
    moved = _get_filter(drawable, _int_param(params, "filter")).get_id()
    stack = [f.get_id() for f in drawable.get_filters()]
    try:
        rebuild, _final = gmb_filters.reorder_plan(stack, moved, int(params["position"]))
    except ValueError as error:
        raise BridgeError("INVALID_ARGUMENT", str(error)) from None
    renamed = {}
    with undo_step(drawable.get_image()):
        by_id = {f.get_id(): f for f in drawable.get_filters()}
        copies = [(number, _detached_copy(drawable, by_id[number])) for number in rebuild]
        for number in rebuild:
            by_id[number].delete()
        for number, copy in copies:  # bottom-up
            copy.update()
            drawable.append_filter(copy)
            renamed[number] = copy.get_id()
    return {
        "filters": [filter_info(f) for f in drawable.get_filters()],
        "recreated": {str(old): new for old, new in renamed.items()},
    }


@mutation
def filter_merge(params):
    """Bake the filter stack into the layer's pixels, from the bottom up to ``up_to`` (default: all)."""
    drawable = get_layer(params)
    _check_filterable(drawable, True)
    stack = drawable.get_filters()  # top first
    if not stack:
        raise BridgeError("INVALID_ARGUMENT", "%r has no filter to merge" % drawable.get_name())
    above = []
    if params.get("up_to") is not None:
        target = _get_filter(drawable, _int_param(params, "up_to"))
        above = stack[: [f.get_id() for f in stack].index(target.get_id())]
    with undo_step(drawable.get_image()):
        kept = []
        for drawable_filter in above:  # keep copies of the filters above, outside the stack
            kept.append(_detached_copy(drawable, drawable_filter))
            drawable_filter.delete()
        merged = len(drawable.get_filters())
        drawable.merge_filters()
        for copy in reversed(kept):  # bottom-up
            copy.update()
            drawable.append_filter(copy)
    return {"merged": merged, "filters": [filter_info(f) for f in drawable.get_filters()]}


# -- color adjustments (#48) -------------------------------------------------------------

DESTRUCTIVE_ONLY = {"equalize": "equalize", "white-balance": "levels_stretch"}
HISTOGRAM_CHANNELS = {v.value_nick: v for v in Gimp.HistogramChannel.__enum_values__.values()}


def _config_enum(config, name, nick):
    pspec = config.find_property(name)
    for value in pspec.enum_class.__enum_values__.values():
        if value.value_nick == nick:
            return value
    allowed = [v.value_nick for v in pspec.enum_class.__enum_values__.values()]
    raise BridgeError("INVALID_ARGUMENT", "%s must be one of %s" % (name, ", ".join(allowed)), {"allowed": allowed})


@mutation
def color_adjust(params):
    drawable = get_layer(params)
    adjustment = params["adjustment"]
    destructive = bool(params.get("destructive"))
    try:
        operation, props = gmb_color.plan(adjustment, params.get("settings") or {})
    except ValueError as error:
        raise BridgeError("INVALID_ARGUMENT", str(error)) from None
    if operation is None and not destructive:
        raise BridgeError(
            "UNSUPPORTED", "%s is only available destructively in GIMP 3.2: use destructive=true" % adjustment
        )
    _check_filterable(drawable, destructive)
    drawable_filter = None
    if operation is not None:  # resolve every value before changing anything
        drawable_filter = Gimp.DrawableFilter.new(drawable, operation, adjustment)
        config = drawable_filter.get_config()
        values = {}
        for name, value in props.items():
            if isinstance(value, tuple) and value[0] == "enum":
                value = _config_enum(config, name, value[1])
            elif isinstance(value, tuple) and value[0] == "color":
                value = color(value[1])
            values[name] = value
    image = drawable.get_image()
    restricted = not Gimp.Selection.is_empty(image)
    filter_id = None
    with undo_step(image):
        if drawable_filter is None:
            getattr(drawable, DESTRUCTIVE_ONLY[adjustment])(*([False] if adjustment == "equalize" else []))
        else:
            for name, value in values.items():
                config.set_property(name, value)
            drawable_filter.update()
            if destructive:
                drawable.merge_filter(drawable_filter)
            else:
                drawable.append_filter(drawable_filter)
                filter_id = drawable_filter.get_id()
                if filter_id not in [f.get_id() for f in drawable.get_filters()]:
                    raise BridgeError("GIMP_ERROR", "GIMP did not keep the editable filter on %r" % drawable.get_name())
    return {
        "adjustment": adjustment,
        "operation": operation,
        "destructive": destructive,
        "filter": filter_id,
        "restricted_to_selection": restricted,
    }


@mutation
def color_curves(params):
    drawable = get_layer(params)
    _check_filterable(drawable, True)
    channel = HISTOGRAM_CHANNELS.get(params.get("channel", "value"))
    if channel is None:
        raise BridgeError("INVALID_ARGUMENT", "unknown channel %r" % params.get("channel"))
    try:
        if params.get("points") is not None:
            values, spline = gmb_color.curve_points(params["points"]), True
        else:
            values, spline = gmb_color.curve_samples(params.get("samples") or []), False
    except ValueError as error:
        raise BridgeError("INVALID_ARGUMENT", str(error)) from None
    image = drawable.get_image()
    restricted = not Gimp.Selection.is_empty(image)
    with undo_step(image):
        ok = drawable.curves_spline(channel, values) if spline else drawable.curves_explicit(channel, values)
    if not ok:
        raise BridgeError("GIMP_ERROR", "GIMP refused the curve")
    return {
        "adjustment": "curves",
        "operation": None,
        "destructive": True,
        "filter": None,
        "restricted_to_selection": restricted,
    }


# -- image mode, precision, color profiles (#49) ------------------------------------------

DITHERS = {
    "none": Gimp.ConvertDitherType.NONE,
    "floyd-steinberg": Gimp.ConvertDitherType.FS,
    "floyd-steinberg-low-bleed": Gimp.ConvertDitherType.FS_LOWBLEED,
    "positioned": Gimp.ConvertDitherType.FIXED,
}
PALETTES = {
    "generate": Gimp.ConvertPaletteType.GENERATE,
    "web": Gimp.ConvertPaletteType.WEB,
    "mono": Gimp.ConvertPaletteType.MONO,
    "custom": Gimp.ConvertPaletteType.CUSTOM,
}
PRECISIONS = {v.value_nick: v for v in Gimp.Precision.__enum_values__.values()}
INTENTS = {v.value_nick: v for v in Gimp.ColorRenderingIntent.__enum_values__.values()}
BUILTIN_PROFILES = {
    "srgb": ("rgb", Gimp.ColorProfile.new_rgb_srgb),
    "srgb-linear": ("rgb", Gimp.ColorProfile.new_rgb_srgb_linear),
    "gray": ("gray", Gimp.ColorProfile.new_d65_gray_srgb_trc),
    "gray-linear": ("gray", Gimp.ColorProfile.new_d65_gray_linear),
}


def mode_info(image):
    palette = image.get_palette() if image.get_base_type() == Gimp.ImageBaseType.INDEXED else None
    return {
        "image": image.get_id(),
        "base_type": image.get_base_type().value_nick,
        "precision": image.get_precision().value_nick,
        "palette_colors": palette.get_color_count() if palette is not None else None,
        "dirty": bool(image.is_dirty()),
    }


@mutation
def image_convert_mode(params):
    image = get_image(params)
    mode = params["mode"]
    current = image.get_base_type().value_nick
    if mode == current:
        return {**mode_info(image), "changed": False}
    if mode == "indexed":
        if image.get_precision() != Gimp.Precision.U8_NON_LINEAR:
            raise BridgeError(
                "INVALID_ARGUMENT",
                "indexed images are 8-bit: convert the precision to u8-non-linear first (now %s)"
                % image.get_precision().value_nick,
            )
        palette_type = params.get("palette", "generate")
        name = params.get("palette_name") or ""
        if palette_type == "custom" and Gimp.Palette.get_by_name(name) is None:
            raise BridgeError("NOT_FOUND", "GIMP has no palette named %r" % name, {"palette": name})
        ok = image.convert_indexed(
            DITHERS[params.get("dither", "none")],
            PALETTES[palette_type],
            int(params.get("colors", 256)),
            bool(params.get("dither_alpha", False)),
            bool(params.get("remove_unused", True)),
            name,
        )
    elif mode == "gray":
        ok = image.convert_grayscale()
    else:
        ok = image.convert_rgb()
    if not ok:
        raise BridgeError("GIMP_ERROR", "GIMP could not convert the image to %s" % mode)
    return {**mode_info(image), "changed": True}


@mutation
def image_convert_precision(params):
    image = get_image(params)
    precision = PRECISIONS.get(params["precision"])
    if precision is None:
        raise BridgeError(
            "INVALID_ARGUMENT", "unknown precision %r" % params["precision"], {"allowed": sorted(PRECISIONS)}
        )
    if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
        raise BridgeError("INVALID_ARGUMENT", "indexed images stay 8-bit: convert to rgb or gray first")
    if image.get_precision() == precision:
        return {**mode_info(image), "changed": False}
    if not image.convert_precision(precision):
        raise BridgeError("GIMP_ERROR", "GIMP could not convert the precision to %s" % params["precision"])
    return {**mode_info(image), "changed": True}


def profile_info(profile):
    return {
        "label": profile.get_label(),
        "description": profile.get_description(),
        "model": "gray" if profile.is_gray() else "rgb" if profile.is_rgb() else "other",
        "linear": bool(profile.is_linear()),
        "icc_bytes": len(profile.get_icc_profile()),
    }


def color_profile_get(params):
    image = get_image(params)
    assigned = image.get_color_profile()
    return {
        "image": image.get_id(),
        "assigned": profile_info(assigned) if assigned is not None else None,
        "effective": profile_info(image.get_effective_color_profile()),
    }


def _load_profile(params):
    """-> (model, profile) for a built-in name or an ICC file, checked before anything changes."""
    source = params["profile"]
    if source in BUILTIN_PROFILES:
        model, make = BUILTIN_PROFILES[source]
        return model, make()
    path = params.get("path")
    if source != "file" or not path:
        raise BridgeError("INVALID_ARGUMENT", "profile must be srgb, srgb-linear, gray, gray-linear or file (+ path)")
    try:
        profile = Gimp.ColorProfile.new_from_file(Gio.File.new_for_path(path))
    except Exception as error:
        raise BridgeError(
            "UNSUPPORTED_FORMAT", "%s is not a usable ICC profile: %s" % (path, error), {"path": path}
        ) from None
    if profile is None:
        raise BridgeError("UNSUPPORTED_FORMAT", "%s is not a usable ICC profile" % path, {"path": path})
    return ("gray" if profile.is_gray() else "rgb" if profile.is_rgb() else "other"), profile


@mutation
def color_profile_set(params):
    image = get_image(params)
    action = params["action"]
    if action == "remove":
        with undo_step(image):
            ok = image.set_color_profile(None)
    else:
        model, profile = _load_profile(params)
        wanted = "gray" if image.get_base_type() == Gimp.ImageBaseType.GRAY else "rgb"
        if model != wanted:
            raise BridgeError(
                "INVALID_ARGUMENT",
                "a %s profile does not fit a %s image" % (model, image.get_base_type().value_nick),
                {"profile_model": model, "image": image.get_base_type().value_nick},
            )
        if action == "assign":
            ok = image.set_color_profile(profile)
        else:
            intent = INTENTS.get(params.get("intent", "perceptual"))
            if intent is None:
                raise BridgeError("INVALID_ARGUMENT", "unknown rendering intent", {"allowed": sorted(INTENTS)})
            ok = image.convert_color_profile(profile, intent, bool(params.get("black_point_compensation", True)))
    if not ok:
        raise BridgeError("GIMP_ERROR", "GIMP refused to %s the color profile" % action)
    return color_profile_get(params)


# -- paths (#50) -----------------------------------------------------------------------

MAX_DETAILED_STROKES = 200


def get_path(params, key="path"):
    item = get_item(params, key)
    if item_kind(item) != "path":
        raise BridgeError(
            "WRONG_KIND",
            "item %d is a %s, not a path" % (item.get_id(), item_kind(item)),
            {"id": item.get_id(), "kind": item_kind(item)},
        )
    return item


def _stroke_ids(path):
    return list(path.get_strokes())


def _get_stroke(path, number):
    if number not in _stroke_ids(path):
        raise BridgeError("NOT_FOUND", "stroke %d is not in path %d" % (number, path.get_id()), {"stroke": number})
    return number


def stroke_info(path, stroke, with_points=False):
    _kind, controls, closed = path.stroke_get_points(stroke)
    xs, ys = controls[0::2], controls[1::2]
    data = {
        "id": stroke,
        "closed": bool(closed),
        "length": round(path.stroke_get_length(stroke, 0.5), 3),
        "anchors": len(xs) // 3,
        "bounds": None
        if not xs
        else {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)},
    }
    if with_points:
        data["control_points"] = [[round(x, 3), round(y, 3)] for x, y in zip(xs, ys, strict=True)]
    return data


def path_info(path, with_points=False):
    strokes = _stroke_ids(path)
    return {
        "id": path.get_id(),
        "image": path.get_image().get_id(),
        "name": path.get_name(),
        "visible": bool(path.get_visible()),
        "strokes": [stroke_info(path, s, with_points) for s in strokes[:MAX_DETAILED_STROKES]],
        "stroke_count": len(strokes),
    }


def _check_stroke_spec(spec):
    kind = spec.get("type")
    if kind == "polyline":
        if len(spec.get("points") or []) < 2:
            raise BridgeError("INVALID_ARGUMENT", "a polyline needs at least 2 points")
    elif kind == "bezier":
        if not spec.get("segments"):
            raise BridgeError("INVALID_ARGUMENT", "a bezier stroke needs at least one segment")
    elif kind == "ellipse":
        if spec.get("radius_x", 0) <= 0 or spec.get("radius_y", 0) <= 0:
            raise BridgeError("INVALID_ARGUMENT", "ellipse radii must be positive")
    else:
        raise BridgeError("INVALID_ARGUMENT", "unknown stroke type %r" % kind)


def _add_stroke(path, spec):
    kind = spec["type"]
    if kind == "polyline":
        points = spec["points"]
        stroke = path.bezier_stroke_new_moveto(float(points[0][0]), float(points[0][1]))
        for x, y in points[1:]:
            path.bezier_stroke_lineto(stroke, float(x), float(y))
    elif kind == "bezier":
        start = spec["start"]
        stroke = path.bezier_stroke_new_moveto(float(start[0]), float(start[1]))
        for segment in spec["segments"]:
            x, y = segment["to"]
            c1, c2 = segment.get("control1"), segment.get("control2")
            if c1 and c2:
                path.bezier_stroke_cubicto(stroke, c1[0], c1[1], c2[0], c2[1], float(x), float(y))
            elif c1:
                path.bezier_stroke_conicto(stroke, c1[0], c1[1], float(x), float(y))
            else:
                path.bezier_stroke_lineto(stroke, float(x), float(y))
    else:
        cx, cy = spec["center"]
        return path.bezier_stroke_new_ellipse(
            float(cx), float(cy), float(spec["radius_x"]), float(spec["radius_y"]), float(spec.get("angle", 0.0))
        )
    if spec.get("closed"):
        path.stroke_close(stroke)
    return stroke


@mutation
def path_create(params):
    image = get_image(params)
    strokes = params.get("strokes") or []
    for spec in strokes:
        _check_stroke_spec(spec)
    with undo_step(image):
        path = Gimp.Path.new(image, params.get("name") or "Path")
        image.insert_path(path, None, int(params.get("position", 0)))
        for spec in strokes:
            _add_stroke(path, spec)
    return path_info(path)


@mutation
def path_add_stroke(params):
    path = get_path(params)
    _check_stroke_spec(params["stroke"])
    with undo_step(path.get_image()):
        stroke = _add_stroke(path, params["stroke"])
    return {**path_info(path), "added_stroke": stroke}


@mutation
def path_from_text(params):
    layer = get_text_layer(params)
    image = layer.get_image()
    with undo_step(image):
        path = Gimp.Path.new_from_text_layer(image, layer)
        if path is None:
            raise BridgeError("GIMP_ERROR", "GIMP could not outline the text layer")
        image.insert_path(path, None, 0)
    return path_info(path)


def path_inspect(params):
    return path_info(get_path(params), with_points=bool(params.get("points")))


@mutation
def path_set(params):
    path = get_path(params)
    with undo_step(path.get_image()):
        if params.get("name") is not None:
            path.set_name(params["name"])
        if params.get("visible") is not None:
            path.set_visible(bool(params["visible"]))
    return path_info(path)


@mutation
def path_duplicate(params):
    path = get_path(params)
    image = path.get_image()
    with undo_step(image):
        copy = path.copy()
        image.insert_path(copy, None, image.get_item_position(path))
    return path_info(copy)


@mutation
def path_delete(params):
    path = get_path(params)
    number = path.get_id()
    path.get_image().remove_path(path)
    return {"deleted": number}


FLIPS = {"horizontal": Gimp.OrientationType.HORIZONTAL, "vertical": Gimp.OrientationType.VERTICAL}


@mutation
def path_edit_stroke(params):
    path = get_path(params)
    stroke = _get_stroke(path, _int_param(params, "stroke"))
    action = params["action"]
    with undo_step(path.get_image()):
        if action == "translate":
            ok = path.stroke_translate(stroke, float(params.get("dx", 0)), float(params.get("dy", 0)))
        elif action == "scale":
            ok = path.stroke_scale(stroke, float(params.get("sx", 1)), float(params.get("sy", 1)))
        elif action == "rotate":
            ok = path.stroke_rotate(
                stroke,
                float(params.get("center_x", 0)),
                float(params.get("center_y", 0)),
                float(params.get("angle", 0)),
            )
        elif action == "flip":
            ok = path.stroke_flip(stroke, FLIPS[params.get("orientation", "horizontal")], float(params.get("axis", 0)))
        elif action == "reverse":
            ok = path.stroke_reverse(stroke)
        elif action == "close":
            ok = path.stroke_close(stroke)
        elif action == "remove":
            ok = path.remove_stroke(stroke)
        else:
            raise BridgeError("INVALID_ARGUMENT", "unknown stroke action %r" % action)
    if not ok:
        raise BridgeError("GIMP_ERROR", "GIMP refused to %s the stroke" % action)
    return path_info(path)


def path_point_at(params):
    path = get_path(params)
    stroke = _get_stroke(path, _int_param(params, "stroke"))
    length = path.stroke_get_length(stroke, 0.5)
    distance = float(params["distance"])
    if not 0 <= distance <= length:
        raise BridgeError("INVALID_ARGUMENT", "distance must be between 0 and the stroke length %.3f" % length)
    _ok, x, y, slope, valid = path.stroke_get_point_at_dist(stroke, distance, 0.5)
    return {"x": x, "y": y, "slope": slope, "valid": bool(valid), "length": round(length, 3)}


CHANNEL_OPS = {
    "replace": Gimp.ChannelOps.REPLACE,
    "add": Gimp.ChannelOps.ADD,
    "subtract": Gimp.ChannelOps.SUBTRACT,
    "intersect": Gimp.ChannelOps.INTERSECT,
}


@mutation
def path_to_selection(params):
    path = get_path(params)
    image = path.get_image()
    Gimp.context_push()
    try:
        Gimp.context_set_antialias(bool(params.get("antialias", True)))
        Gimp.context_set_feather(False)
        if not image.select_item(CHANNEL_OPS[params.get("operation", "replace")], path):
            raise BridgeError("GIMP_ERROR", "GIMP could not turn the path into a selection")
    finally:
        Gimp.context_pop()
    return {**selection_state(image), "image": image.get_id()}


@mutation
def selection_to_path(params):
    image = get_image(params)
    if Gimp.Selection.is_empty(image):
        raise BridgeError("EMPTY_SELECTION", "nothing is selected")
    before = {p.get_id() for p in image.get_paths()}
    procedure = Gimp.get_pdb().lookup_procedure("plug-in-sel2path")
    config = procedure.create_config()
    config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    config.set_property("image", image)
    result = procedure.run(config)
    created = [p for p in image.get_paths() if p.get_id() not in before]
    if result.index(0) != Gimp.PDBStatusType.SUCCESS or not created:
        raise BridgeError("GIMP_ERROR", "GIMP could not trace the selection")
    path = created[0]
    if params.get("name"):
        path.set_name(params["name"])
    return path_info(path)


@mutation
def path_stroke(params):
    path = get_path(params)
    drawable = get_paintable(params)
    if drawable.get_image().get_id() != path.get_image().get_id():
        raise BridgeError("IMAGE_MISMATCH", "the path and the layer belong to different images")
    brush = None
    if params.get("method") == "paint" and params.get("brush"):
        brush = Gimp.Brush.get_by_name(params["brush"])
        if brush is None:
            raise BridgeError("NOT_FOUND", "GIMP has no brush named %r" % params["brush"], {"brush": params["brush"]})
    with undo_step(drawable.get_image()), paint_context(params):
        if params.get("dash"):
            Gimp.context_set_line_dash_pattern([float(v) for v in params["dash"]])
        Gimp.context_set_line_miter_limit(float(params.get("miter_limit", 10.0)))
        if params.get("method") == "paint":
            Gimp.context_set_stroke_method(Gimp.StrokeMethod.PAINT_METHOD)
            Gimp.context_set_paint_method("gimp-paintbrush")
            if brush is not None:
                Gimp.context_set_brush(brush)
            Gimp.context_set_brush_size(float(params.get("width", 2.0)))
        if not drawable.edit_stroke_item(path):
            raise BridgeError("GIMP_ERROR", "GIMP refused to stroke the path")
    return {"item": drawable.get_id(), "path": path.get_id(), "method": params.get("method", "line")}


@mutation
def path_fill(params):
    path = get_path(params)
    drawable = get_paintable(params)
    image = drawable.get_image()
    if image.get_id() != path.get_image().get_id():
        raise BridgeError("IMAGE_MISMATCH", "the path and the layer belong to different images")
    with undo_step(image), saved_selection(image), paint_context(params):
        image.select_item(Gimp.ChannelOps.REPLACE, path)
        if Gimp.Selection.is_empty(image):
            raise BridgeError("INVALID_ARGUMENT", "the path encloses no area (open or empty strokes)")
        drawable.edit_fill(Gimp.FillType.FOREGROUND)
    return {"item": drawable.get_id(), "path": path.get_id()}


@mutation
def paths_import_svg(params):
    image = get_image(params)
    merge, scale = bool(params.get("merge")), bool(params.get("scale"))
    before = {p.get_id() for p in image.get_paths()}
    with undo_step(image):
        if params.get("file"):
            ok, _paths = image.import_paths_from_file(Gio.File.new_for_path(params["file"]), merge, scale)
        else:
            svg = params.get("svg") or ""
            ok, _paths = image.import_paths_from_string(svg, len(svg.encode("utf-8")), merge, scale)
    created = [p for p in image.get_paths() if p.get_id() not in before]
    if not ok or not created:
        raise BridgeError("UNSUPPORTED_FORMAT", "no path could be read from the SVG")
    return {"paths": [path_info(p) for p in created]}


def paths_export_svg(params):
    image = get_image(params)
    path = get_path(params) if params.get("path") is not None else None
    if path is not None and path.get_image().get_id() != image.get_id():
        raise BridgeError("IMAGE_MISMATCH", "the path belongs to another image")
    svg = image.export_path_to_string(path)
    if params.get("file"):
        with open(params["file"], "w", encoding="utf-8") as handle:
            handle.write(svg)
    return {"svg": svg if not params.get("file") else None, "file": params.get("file"), "bytes": len(svg.encode())}


# -- resources (#52) ---------------------------------------------------------------------

RESOURCE_CLASSES = {
    "brush": (Gimp.Brush, Gimp.brushes_get_list),
    "gradient": (Gimp.Gradient, Gimp.gradients_get_list),
    "pattern": (Gimp.Pattern, Gimp.patterns_get_list),
    "palette": (Gimp.Palette, Gimp.palettes_get_list),
}
BRUSH_SHAPES = {v.value_nick: v for v in Gimp.BrushGeneratedShape.__enum_values__.values()}
SEGMENT_BLENDS = {v.value_nick: v for v in Gimp.GradientSegmentType.__enum_values__.values()}
SEGMENT_COLORINGS = {v.value_nick: v for v in Gimp.GradientSegmentColor.__enum_values__.values()}
PALETTE_EXPORTS = {
    "css": "gimp-palette-export-css",
    "java": "gimp-palette-export-java",
    "php": "gimp-palette-export-php",
    "python": "gimp-palette-export-python",
    "text": "gimp-palette-export-text",
}


def get_resource(kind, name):
    cls, _lister = RESOURCE_CLASSES[kind]
    resource = cls.get_by_name(name) if name else None
    if resource is None:
        raise BridgeError("NOT_FOUND", "GIMP has no %s named %r" % (kind, name), {"kind": kind, "name": name})
    return resource


def editable_resource(kind, name):
    resource = get_resource(kind, name)
    if not resource.is_editable():
        raise BridgeError(
            "READ_ONLY",
            "%s %r is a built-in (read-only) resource: duplicate it to change a copy" % (kind, name),
            {"kind": kind, "name": name},
        )
    return resource


def _rgba(gegl_color):
    r, g, b, a = gegl_color.get_rgba_with_space(Babl.space("sRGB"))
    return [max(0, min(255, round(v * 255))) for v in (r, g, b, a)]


def _hex8(gegl_color):
    return "#%02x%02x%02x%02x" % tuple(_rgba(gegl_color))


def _buffer_png(buffer):
    extent = buffer.get_extent()
    data = bytes(buffer.get(extent, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.CLAMP))
    return gmb_resources.encode_png(data, extent.width, extent.height, 4)


def _brush_png(brush):
    """Color brushes: their pixels; grayscale brushes (and generated ones): black with the mask as alpha."""
    if brush.get_info()[4] > 0:  # color_bpp: only color brushes have a pixel buffer (else GLib warns)
        return _buffer_png(brush.get_buffer(256, 256, Babl.format("R'G'B'A u8")))
    mask = brush.get_mask(256, 256, Babl.format("Y' u8"))
    extent = mask.get_extent()
    alpha = bytes(mask.get(extent, 1.0, "Y' u8", Gegl.AbyssPolicy.CLAMP))
    rgba = bytearray(len(alpha) * 4)
    rgba[3::4] = alpha
    return gmb_resources.encode_png(bytes(rgba), extent.width, extent.height, 4)


def resource_summary(kind, resource):
    data = {"kind": kind, "name": resource.get_name(), "editable": bool(resource.is_editable())}
    if kind == "brush":
        data["generated"] = bool(resource.is_generated())
    return data


def resources_list(params):
    kind = params["kind"]
    _cls, lister = RESOURCE_CLASSES[kind]
    found = lister(params.get("query") or "")
    limit = int(params.get("limit", 200))
    return {"resources": [resource_summary(kind, r) for r in found[:limit]], "total": len(found)}


def _brush_details(brush):
    _ok, width, height, _mask_bpp, color_bpp = brush.get_info()
    data = {"width": width, "height": height, "color": color_bpp > 0, "spacing": brush.get_spacing()}
    if brush.is_generated():
        data.update(
            {
                "shape": brush.get_shape()[1].value_nick,
                "radius": brush.get_radius()[1],
                "hardness": round(brush.get_hardness()[1], 4),
                "angle": brush.get_angle()[1],
                "aspect_ratio": brush.get_aspect_ratio()[1],
                "spikes": brush.get_spikes()[1],
            }
        )
    return data


def _gradient_details(gradient):
    segments = []
    for i in range(gradient.get_number_of_segments()):
        segments.append(
            {
                "left": round(gradient.segment_get_left_pos(i)[1], 6),
                "middle": round(gradient.segment_get_middle_pos(i)[1], 6),
                "right": round(gradient.segment_get_right_pos(i)[1], 6),
                "left_color": _hex8(gradient.segment_get_left_color(i)),
                "right_color": _hex8(gradient.segment_get_right_color(i)),
                "blending": gradient.segment_get_blending_function(i)[1].value_nick,
                "coloring": gradient.segment_get_coloring_type(i)[1].value_nick,
            }
        )
    return {"segments": segments}


def _palette_details(palette):
    entries = []
    for i in range(palette.get_color_count()):
        name = palette.get_entry_name(i)
        entries.append({"index": i, "name": name[1] if isinstance(name, tuple) else name,
                        "color": _hex8(palette.get_entry_color(i))})  # fmt: skip
    return {"columns": palette.get_columns(), "entries": entries}


def resource_inspect(params):
    import base64

    kind = params["kind"]
    resource = get_resource(kind, params["name"])
    data = resource_summary(kind, resource)
    png = None
    if kind == "brush":
        data.update(_brush_details(resource))
        if params.get("preview"):
            png = _brush_png(resource)
    elif kind == "pattern":
        _ok, width, height, bpp = resource.get_info()
        data.update({"width": width, "height": height, "bpp": bpp})
        if params.get("preview"):
            png = _buffer_png(resource.get_buffer(256, 256, Babl.format("R'G'B'A u8")))
    elif kind == "gradient":
        data.update(_gradient_details(resource))
        if params.get("preview"):
            samples = [c.get_rgba_with_space(Babl.space("sRGB")) for c in resource.get_uniform_samples(256, False)]
            png = gmb_resources.gradient_strip(samples, 32)
    else:
        data.update(_palette_details(resource))
        if params.get("preview"):
            colors = [tuple(_rgba(resource.get_entry_color(i))[:3]) for i in range(resource.get_color_count())]
            png = gmb_resources.palette_swatches(colors, resource.get_columns())
    if png is not None:
        data["preview"] = base64.b64encode(png).decode("ascii")
    return data


@mutation
def resource_create(params):
    kind = params["kind"]
    if kind == "pattern":
        raise BridgeError("UNSUPPORTED", "GIMP 3.2 cannot create patterns from a plug-in")
    cls, _lister = RESOURCE_CLASSES[kind]
    resource = cls.new(params["name"])
    if resource is None:
        raise BridgeError("GIMP_ERROR", "GIMP could not create the %s" % kind)
    return resource_summary(kind, resource)


@mutation
def resource_duplicate(params):
    kind = params["kind"]
    source = get_resource(kind, params["name"])
    copy = source.duplicate()
    if copy is None:
        raise BridgeError("GIMP_ERROR", "GIMP could not duplicate the %s" % kind)
    if params.get("new_name"):
        copy.rename(params["new_name"])
    return resource_summary(kind, copy)


@mutation
def resource_rename(params):
    kind = params["kind"]
    resource = editable_resource(kind, params["name"])
    if not resource.rename(params["new_name"]):
        raise BridgeError("GIMP_ERROR", "GIMP refused the new name")
    return resource_summary(kind, resource)


@mutation
def resource_delete(params):
    kind = params["kind"]
    resource = editable_resource(kind, params["name"])
    name = resource.get_name()
    if not resource.delete():
        raise BridgeError("GIMP_ERROR", "GIMP could not delete the %s" % kind)
    return {"kind": kind, "deleted": name}


@mutation
def brush_edit(params):
    brush = editable_resource("brush", params["name"])
    if not brush.is_generated():
        raise BridgeError("READ_ONLY", "only generated brushes have editable parameters")
    if params.get("shape") is not None and params["shape"] not in BRUSH_SHAPES:
        raise BridgeError("INVALID_ARGUMENT", "unknown shape", {"allowed": sorted(BRUSH_SHAPES)})
    setters = (
        ("shape", lambda v: brush.set_shape(BRUSH_SHAPES[v])),
        ("radius", lambda v: brush.set_radius(float(v))),
        ("hardness", lambda v: brush.set_hardness(float(v))),
        ("angle", lambda v: brush.set_angle(float(v))),
        ("aspect_ratio", lambda v: brush.set_aspect_ratio(float(v))),
        ("spikes", lambda v: brush.set_spikes(int(v))),
        ("spacing", lambda v: brush.set_spacing(int(v))),
    )
    for key, setter in setters:
        if params.get(key) is not None:
            setter(params[key])
    return {**resource_summary("brush", brush), **_brush_details(brush)}


@mutation
def gradient_edit(params):
    gradient = editable_resource("gradient", params["name"])
    segments = params["segments"]
    for segment in segments:
        if segment.get("blending", "linear") not in SEGMENT_BLENDS:
            raise BridgeError("INVALID_ARGUMENT", "unknown blending", {"allowed": sorted(SEGMENT_BLENDS)})
        if segment.get("coloring", "rgb") not in SEGMENT_COLORINGS:
            raise BridgeError("INVALID_ARGUMENT", "unknown coloring", {"allowed": sorted(SEGMENT_COLORINGS)})
    rights = [s.get("right") for s in segments]
    if any(r is not None for r in rights):
        explicit = [r for r in rights[:-1]]
        if None in explicit or explicit != sorted(explicit) or not all(0 < r < 1 for r in explicit):
            raise BridgeError("INVALID_ARGUMENT", "segment ends must be increasing between 0 and 1 (last ends at 1)")
    count = gradient.get_number_of_segments()
    if count > 1:
        gradient.segment_range_delete(1, count - 1)
    if len(segments) > 1:
        gradient.segment_range_split_uniform(0, 0, len(segments))
    for i, segment in enumerate(segments):
        if i < len(segments) - 1 and segment.get("right") is not None:
            gradient.segment_set_right_pos(i, float(segment["right"]))
    for i, segment in enumerate(segments):
        gradient.segment_set_left_color(i, color(segment["left_color"]))
        gradient.segment_set_right_color(i, color(segment["right_color"]))
        gradient.segment_range_set_blending_function(i, i, SEGMENT_BLENDS[segment.get("blending", "linear")])
        gradient.segment_range_set_coloring_type(i, i, SEGMENT_COLORINGS[segment.get("coloring", "rgb")])
    return {**resource_summary("gradient", gradient), **_gradient_details(gradient)}


@mutation
def palette_edit(params):
    palette = editable_resource("palette", params["name"])
    if params.get("entries") is not None:
        while palette.get_color_count():
            palette.delete_entry(palette.get_color_count() - 1)
        for entry in params["entries"]:
            palette.add_entry(entry.get("name") or "", color(entry["color"]))
    if params.get("columns") is not None:
        palette.set_columns(int(params["columns"]))
    return {**resource_summary("palette", palette), **_palette_details(palette)}


@mutation
def palette_import(params):
    import shutil

    source = params["file"]
    folder = os.path.join(Gimp.directory(), "palettes")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, os.path.basename(source))
    if os.path.exists(target):
        raise BridgeError("FILE_EXISTS", "%s is already in your palettes folder" % os.path.basename(source))
    before = {p.get_name() for p in Gimp.palettes_get_list("")}
    shutil.copyfile(source, target)
    Gimp.palettes_refresh()
    created = [p for p in Gimp.palettes_get_list("") if p.get_name() not in before]
    if not created:
        os.remove(target)
        Gimp.palettes_refresh()
        raise BridgeError("UNSUPPORTED_FORMAT", "GIMP could not read a palette from %s" % source, {"path": source})
    return {**resource_summary("palette", created[0]), **_palette_details(created[0]), "file": target}


def palette_export(params):
    palette = get_resource("palette", params["name"])
    path, fmt = params["file"], params["format"]
    if fmt == "gpl":
        entries = []
        for i in range(palette.get_color_count()):
            name = palette.get_entry_name(i)
            entries.append((name[1] if isinstance(name, tuple) else name, tuple(_rgba(palette.get_entry_color(i))[:3])))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(gmb_resources.write_gpl(palette.get_name(), palette.get_columns(), entries))
    else:
        pdb = Gimp.get_pdb()
        name = "python-fu-palette-export-as-kpl" if fmt == "kpl" else PALETTE_EXPORTS[fmt]
        procedure = pdb.lookup_procedure(name)
        if procedure is None:
            raise BridgeError("UNSUPPORTED", "GIMP's %s palette export is not available" % fmt)
        config = procedure.create_config()
        config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        Gimp.context_push()
        try:
            Gimp.context_set_palette(palette)
            if fmt == "kpl":
                config.set_property("palette", palette)
                config.set_property("file", Gio.File.new_for_path(path))
            else:
                config.set_property("dirname", Gio.File.new_for_path(os.path.dirname(path)))
                config.set_property("string", os.path.basename(path))
            result = procedure.run(config)
        finally:
            Gimp.context_pop()
        if result.index(0) != Gimp.PDBStatusType.SUCCESS or not os.path.exists(path):
            raise BridgeError("WRITE_FAILED", "GIMP could not export the palette to %s" % path, {"path": path})
    return {"file": path, "format": fmt, "bytes": os.path.getsize(path)}


# -- composition (#54) -------------------------------------------------------------------

MERGE_TYPES = {
    "expand": Gimp.MergeType.EXPAND_AS_NECESSARY,
    "clip-to-image": Gimp.MergeType.CLIP_TO_IMAGE,
    "clip-to-bottom": Gimp.MergeType.CLIP_TO_BOTTOM_LAYER,
}
CLIPBOARD = "clipboard"


def _same_image(items):
    images = {item.get_image().get_id() for item in items}
    if len(images) > 1:
        raise BridgeError("IMAGE_MISMATCH", "the items belong to different images")
    return items[0].get_image()


@mutation
def clipboard_copy(params):
    """Copy (or cut) drawables or the visible composite into a named GIMP buffer (or the clipboard)."""
    buffer = params.get("buffer") or "gimp-mcp"
    if params.get("visible"):
        image = get_image(params)
        ok = Gimp.edit_copy_visible(image) if buffer == CLIPBOARD else Gimp.edit_named_copy_visible(image, buffer)
    else:
        drawables = [get_paintable({"item": number}) for number in params["items"]]
        image = _same_image(drawables)
        cut = bool(params.get("cut"))
        if buffer == CLIPBOARD:
            ok = (Gimp.edit_cut if cut else Gimp.edit_copy)(drawables)
        else:
            ok = (Gimp.edit_named_cut if cut else Gimp.edit_named_copy)(drawables, buffer)
    if not ok:
        raise BridgeError("INVALID_ARGUMENT", "nothing to copy (empty selection or area)")
    name = buffer if buffer == CLIPBOARD else (ok if isinstance(ok, str) else buffer)
    return {"buffer": name, "selection": not Gimp.Selection.is_empty(image)}


def _floating(image):
    return image.get_floating_sel()


@mutation
def clipboard_paste(params):
    buffer = params.get("buffer") or "gimp-mcp"
    mode = params["mode"]
    if mode == "new-image":
        image = Gimp.edit_paste_as_new_image() if buffer == CLIPBOARD else Gimp.edit_named_paste_as_new_image(buffer)
        if image is None:
            raise BridgeError("NOT_FOUND", "buffer %r is empty or does not exist" % buffer, {"buffer": buffer})
        shown = show(image)
        return {"mode": mode, "image": image_ref(image, shown), "layer": None}
    drawable = get_paintable(params)
    image = drawable.get_image()
    if _floating(image) is not None:
        raise BridgeError("INVALID_ARGUMENT", "the image already has a floating selection: anchor it in GIMP first")
    into = bool(params.get("into_selection"))
    with undo_step(image):
        pasted = (
            Gimp.edit_paste(drawable, into) if buffer == CLIPBOARD else Gimp.edit_named_paste(drawable, buffer, into)
        )
        floating = _floating(image)
        if not pasted or floating is None:
            raise BridgeError("NOT_FOUND", "buffer %r is empty or does not exist" % buffer, {"buffer": buffer})
        if mode == "into-layer":
            Gimp.floating_sel_anchor(floating)
            layer = drawable
        else:
            Gimp.floating_sel_to_layer(floating)
            layer = floating
    return {"mode": mode, "image": image_ref(image), "layer": layer_node(layer, recurse=False)}


@mutation
def layers_merge(params):
    mode = params["mode"]
    merge_type = MERGE_TYPES[params.get("merge_type", "expand")]
    if mode == "visible":
        image = get_image(params)
        visible = [layer for layer in image.get_layers() if layer.get_visible()]
        if len(visible) < 2:
            raise BridgeError("INVALID_ARGUMENT", "merging visible layers needs at least two visible layers")
        merged = image.merge_visible_layers(merge_type)
    elif mode == "down":
        layer = get_layer(params)
        image = layer.get_image()
        siblings = layer.get_parent().get_children() if layer.get_parent() else image.get_layers()
        if siblings.index(next(s for s in siblings if s.get_id() == layer.get_id())) == len(siblings) - 1:
            raise BridgeError("INVALID_ARGUMENT", "there is no layer below %r to merge into" % layer.get_name())
        merged = image.merge_down(layer, merge_type)
    else:
        group = get_layer(params)
        if item_kind(group) != "group":
            raise BridgeError("WRONG_KIND", "item %d is not a group" % group.get_id())
        image = group.get_image()
        merged = group.merge()
    if merged is None:
        raise BridgeError("GIMP_ERROR", "GIMP could not merge the layers")
    return {"image": image_ref(image), "layer": layer_node(merged, recurse=False)}


@mutation
def image_flatten(params):
    image = get_image(params)
    layer = image.flatten()
    if layer is None:
        raise BridgeError("GIMP_ERROR", "GIMP could not flatten the image")
    return {"image": image_ref(image), "layer": layer_node(layer, recurse=False)}


@mutation
def layer_from_visible(params):
    image = get_image(params)
    with undo_step(image):
        layer = Gimp.Layer.new_from_visible(image, image, params.get("name") or "Visible")
        image.insert_layer(layer, None, 0)
    return layer_node(layer, recurse=False)


@mutation
def layer_alpha(params):
    layer = get_layer(params)
    if item_kind(layer) != "layer":
        raise BridgeError("WRONG_KIND", "alpha channels belong to plain layers")
    with undo_step(layer.get_image()):
        if params["action"] == "add":
            layer.add_alpha()
        elif layer.has_alpha():
            layer.flatten()  # removes alpha, filling transparency with the background color
    return layer_node(layer, recurse=False)


@mutation
def selection_from_alpha(params):
    layer = get_layer(params)
    image = layer.get_image()
    image.select_item(CHANNEL_OPS[params.get("operation", "replace")], layer)
    return {**selection_state(image), "image": image.get_id()}


@mutation
def layer_fit(params):
    layer = get_layer(params)
    image = layer.get_image()
    mode = params["mode"]
    with undo_step(image):
        if mode == "image-size":
            ok = layer.resize_to_image_size()
        elif mode == "size":
            ok = layer.resize(int(params["width"]), int(params["height"]), int(params.get("offset_x", 0)),
                              int(params.get("offset_y", 0)))  # fmt: skip
        else:
            image.set_selected_layers([layer])
            ok = image.autocrop_selected_layers(layer)
    if not ok:
        raise BridgeError("GIMP_ERROR", "GIMP could not resize the layer")
    return layer_node(layer, recurse=False)


@mutation
def image_crop_to_content(params):
    image = get_image(params)
    before = (image.get_width(), image.get_height())
    if not image.autocrop(None):
        raise BridgeError("GIMP_ERROR", "GIMP could not crop the image")
    return {**image_ref(image), "cropped": before != (image.get_width(), image.get_height())}


@mutation
def layers_align(params):
    layers = [get_layer({"item": number}) for number in params["items"]]
    image = _same_image(layers)
    boxes = []
    for layer in layers:
        _ok, x, y = layer.get_offsets()
        boxes.append((x, y, layer.get_width(), layer.get_height()))
    reference = params.get("reference", "image")
    if reference == "image":
        box = (0, 0, image.get_width(), image.get_height())
    elif reference == "selection":
        _ok, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
        if not non_empty:
            raise BridgeError("EMPTY_SELECTION", "nothing is selected to align to")
        box = (x1, y1, x2 - x1, y2 - y1)
    else:
        other = get_layer({"item": params["reference_item"]})
        if other.get_image().get_id() != image.get_id():
            raise BridgeError("IMAGE_MISMATCH", "the reference layer belongs to another image")
        _ok, x, y = other.get_offsets()
        box = (x, y, other.get_width(), other.get_height())
    try:
        if params.get("distribute"):
            offsets = gmb_align.distribute(boxes, params["distribute"])
        else:
            offsets = gmb_align.align(boxes, box, params.get("horizontal"), params.get("vertical"))
    except ValueError as error:
        raise BridgeError("INVALID_ARGUMENT", str(error)) from None
    for layer in layers:
        if layer.get_lock_position():
            raise BridgeError("LOCKED", "the position of %r is locked" % layer.get_name())
    with undo_step(image):
        for layer, (x, y) in zip(layers, offsets, strict=True):
            layer.set_offsets(x, y)
    return {"layers": [layer_node(layer, recurse=False) for layer in layers]}


# -- guides, sample points, metadata, resolution (#60) ----------------------------------

UNITS = {"inch": Gimp.Unit.inch, "mm": Gimp.Unit.mm, "point": Gimp.Unit.point, "pica": Gimp.Unit.pica}
METADATA_KINDS = ("exif", "xmp", "iptc")


def _guides(image):
    guides = []
    guide = image.find_next_guide(0)
    while guide:
        orientation = image.get_guide_orientation(guide)
        guides.append(
            {
                "id": guide,
                "orientation": "horizontal" if orientation == Gimp.OrientationType.HORIZONTAL else "vertical",
                "position": image.get_guide_position(guide),
            }
        )
        guide = image.find_next_guide(guide)
    return guides


def _sample_points(image, with_values):
    points = []
    point = image.find_next_sample_point(0)
    while point:
        position = image.get_sample_point_position(point)
        x, y = position[-2], position[-1]  # (x, y)
        points.append({"id": point, "x": x, "y": y})
        point = image.find_next_sample_point(point)
    if with_values and points and image.get_layers():
        with _Pixels("image", image) as pixels:
            for entry in points:
                data = pixels.read((entry["x"], entry["y"], 1, 1))
                entry["rgba"] = list(data[:4])
                entry["hex"] = "#%02x%02x%02x" % tuple(data[:3])
    return points


def guides_list(params):
    image = get_image(params)
    return {
        "image": image.get_id(),
        "guides": _guides(image),
        "sample_points": _sample_points(image, bool(params.get("values", True))),
    }


@mutation
def guide_add(params):
    image = get_image(params)
    position = int(params["position"])
    horizontal = params["orientation"] == "horizontal"
    limit = image.get_height() if horizontal else image.get_width()
    if not 0 <= position <= limit:
        raise BridgeError("INVALID_ARGUMENT", "position must be between 0 and %d" % limit)
    guide = image.add_hguide(position) if horizontal else image.add_vguide(position)
    return {"guide": guide, **guides_list({"image": image.get_id(), "values": False})}


@mutation
def sample_point_add(params):
    image = get_image(params)
    x, y = int(params["x"]), int(params["y"])
    if not (0 <= x < image.get_width() and 0 <= y < image.get_height()):
        raise BridgeError("INVALID_ARGUMENT", "the point must be inside the canvas")
    point = image.add_sample_point(x, y)
    return {"sample_point": point, **guides_list({"image": image.get_id(), "values": False})}


@mutation
def guide_remove(params):
    image = get_image(params)
    kind, number = params["kind"], int(params["id"])
    existing = [g["id"] for g in _guides(image)] if kind == "guide" else [p["id"] for p in _sample_points(image, False)]
    if number not in existing:
        raise BridgeError("NOT_FOUND", "%s %d does not exist in this image" % (kind.replace("_", " "), number))
    if kind == "guide":
        image.delete_guide(number)
    else:
        image.delete_sample_point(number)
    return guides_list({"image": image.get_id(), "values": False})


def _metadata_tags(metadata):
    tags = {}
    for kind, getter in (("exif", "get_exif_tags"), ("xmp", "get_xmp_tags"), ("iptc", "get_iptc_tags")):
        values = {}
        for tag in getattr(metadata, getter)() or []:
            try:
                values[tag] = metadata.get_tag_interpreted_string(tag)
            except Exception:
                values[tag] = None
        tags[kind] = values
    return tags


def _comment(image):
    parasite = image.get_parasite("gimp-comment")
    if parasite is None:
        return None
    return bytes(parasite.get_data()).rstrip(b"\0").decode("utf-8", "replace")


def metadata_get(params):
    image = get_image(params)
    metadata = image.get_metadata()
    tags = _metadata_tags(metadata) if metadata is not None else {kind: {} for kind in METADATA_KINDS}
    return {"image": image.get_id(), **tags, "comment": _comment(image)}


@mutation
def metadata_set(params):
    image = get_image(params)
    updates = params.get("set") or {}
    removals = params.get("remove") or []
    for tag in list(updates) + list(removals):
        if not tag.startswith(("Exif.", "Xmp.", "Iptc.")):
            raise BridgeError("INVALID_ARGUMENT", "tag %r must start with Exif., Xmp. or Iptc." % tag)
    metadata = image.get_metadata() or Gimp.Metadata.new()
    for tag, value in updates.items():
        try:
            ok = metadata.try_set_tag_string(tag, str(value))
        except Exception as error:
            raise BridgeError("INVALID_ARGUMENT", "cannot set %s: %s" % (tag, error), {"tag": tag}) from None
        if not ok:
            raise BridgeError("INVALID_ARGUMENT", "cannot set %s" % tag, {"tag": tag})
    for tag in removals:
        metadata.clear_tag(tag)
    with undo_step(image):
        image.set_metadata(metadata)
        if params.get("comment") is not None:
            if params["comment"] == "":
                image.detach_parasite("gimp-comment")
            else:
                data = params["comment"].encode("utf-8")  # no NUL: exports copy the bytes as they are
                image.attach_parasite(Gimp.Parasite.new("gimp-comment", Gimp.PARASITE_PERSISTENT, data))
    return metadata_get(params)


def print_info(image):
    _ok, xres, yres = image.get_resolution()
    unit = image.get_unit()
    factor = unit.get_factor() if unit.get_factor() else 1.0  # units per inch
    return {
        "resolution": {"x": float(xres), "y": float(yres)},
        "unit": unit.get_abbreviation(),
        "print_size": {
            "width": round(image.get_width() / xres * factor, 4),
            "height": round(image.get_height() / yres * factor, 4),
        },
    }


@mutation
def image_set_print(params):
    image = get_image(params)
    unit = params.get("unit")
    if unit is not None and unit not in UNITS:
        raise BridgeError("INVALID_ARGUMENT", "unit must be one of %s" % ", ".join(UNITS))
    xres, yres = params.get("x_resolution"), params.get("y_resolution")
    if params.get("width") is not None:
        factor = UNITS[unit or "inch"]().get_factor()
        xres = image.get_width() * factor / float(params["width"])
        yres = image.get_height() * factor / float(params["height"])
    for value in (xres, yres):
        if value is not None and not 5.0 <= value <= 65536.0:
            raise BridgeError("INVALID_ARGUMENT", "resolution must stay between 5 and 65536 ppi (got %.2f)" % value)
    with undo_step(image):
        if xres is not None:
            image.set_resolution(float(xres), float(yres if yres is not None else xres))
        if unit is not None:
            image.set_unit(UNITS[unit]())
    return {"image": image.get_id(), **print_info(image)}


# -- file formats (#58) ------------------------------------------------------------------

_FILE_PROCEDURES = {}  # kind -> {procedure name: [extensions]}
LOAD_FIXED = {"run-mode", "file"}


def _file_procedures(kind):
    if kind not in _FILE_PROCEDURES:
        found = {}
        for name in _all_names("^file-.*-%s$" % ("export" if kind == "export" else "load")):
            extensions = gmb_formats.extensions_for(name)
            if extensions:
                found[name] = extensions
        _FILE_PROCEDURES[kind] = found
    return _FILE_PROCEDURES[kind]


def _file_procedure(kind, params):
    procedures = _file_procedures(kind)
    name = params.get("procedure") or gmb_formats.procedure_for(params["path"], procedures)
    if name is None or name not in procedures:
        raise BridgeError(
            "UNSUPPORTED_FORMAT",
            "no GIMP %s procedure for %s" % (kind, params.get("procedure") or os.path.basename(params["path"])),
            {"path": params["path"]},
        )
    return name, Gimp.get_pdb().lookup_procedure(name)


def _option_specs(procedure, fixed):
    config = procedure.create_config()
    specs = []
    for pspec in procedure.get_arguments():
        if pspec.name in fixed or pspec.name in gmb_formats.METADATA_ARGUMENTS:
            continue
        kind = _param_kind(pspec)
        if pspec.value_type.name == "GimpInt32Array":
            kind = "integer-list"
        spec = {"name": pspec.name, "kind": kind if kind != "integer-list" else "unsupported",
                "description": pspec.get_blurb()}  # fmt: skip
        if kind in ("number", "integer"):
            spec["min"], spec["max"] = pspec.minimum, pspec.maximum
        elif kind == "choice":
            spec["choices"] = list(Gimp.param_spec_choice_get_choice(pspec).list_nicks())
        elif kind == "enum":
            spec["choices"] = [v.value_nick for v in pspec.enum_class.__enum_values__.values()]
        elif kind == "unsupported":
            spec["type"] = pspec.value_type.name
        if kind == "integer-list":
            spec["kind"] = "integer-list"
        try:
            spec["default"] = _config_value(config.get_property(pspec.name)) if spec["kind"] != "unsupported" else None
        except Exception:
            spec["default"] = None
        specs.append(spec)
    return specs


def file_formats(params):
    kind = params.get("mode", "export")
    pdb = Gimp.get_pdb()
    formats = []
    for name, extensions in sorted(_file_procedures(kind).items()):
        procedure = pdb.lookup_procedure(name)
        formats.append({"procedure": name, "name": procedure.get_menu_label() or procedure.get_blurb() or name,
                        "extensions": extensions})  # fmt: skip
    return {"mode": kind, "formats": formats}


def file_format_describe(params):
    kind = params.get("mode", "export")
    name, procedure = _file_procedure(kind, {"path": params.get("path") or "", "procedure": params.get("procedure")})
    fixed = gmb_formats.FIXED_ARGUMENTS if kind == "export" else LOAD_FIXED
    return {
        "procedure": name,
        "name": procedure.get_menu_label() or procedure.get_blurb() or name,
        "extensions": _file_procedures(kind)[name],
        "options": _option_specs(procedure, fixed),
    }


def _apply_options(config, specs, values):
    by_name = {spec["name"]: spec for spec in specs}
    for name, value in values.items():
        kind = by_name[name]["kind"]
        if kind == "color":
            value = color(value)
        elif kind == "enum":
            value = _config_enum(config, name, value)
        config.set_property(name, value)


def _validated_options(name, specs, options):
    plain = [s for s in specs if s["kind"] != "integer-list"]
    lists = {s["name"] for s in specs if s["kind"] == "integer-list"}
    values = {k: v for k, v in (options or {}).items() if k not in lists}
    try:
        checked = gmb_filters.validate(plain, values)
    except gmb_filters.InvalidParameter as error:
        raise BridgeError("INVALID_ARGUMENT", "%s: %s" % (name, error)) from None
    for key in lists & set(options or {}):
        value = options[key]
        if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            raise BridgeError("INVALID_ARGUMENT", "%s: %s must be a list of integers" % (name, key))
        checked[key] = value
    return checked


def _export_with(image, path, name, procedure, options, metadata):
    specs = _option_specs(procedure, gmb_formats.FIXED_ARGUMENTS)
    values = _validated_options(name, specs, options)
    config = procedure.create_config()
    config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    config.set_property("image", image)
    config.set_property("file", Gio.File.new_for_path(path))
    for flag in gmb_formats.METADATA_ARGUMENTS:
        if config.find_property(flag) is not None:
            kind = flag[len("include-") :]
            config.set_property(
                flag, kind in metadata or (kind == "color-profile" and image.get_color_profile() is not None)
            )
    _apply_options(config, specs, values)
    effective = {spec["name"]: _config_value(config.get_property(spec["name"])) for spec in specs
                 if spec["kind"] not in ("unsupported", "integer-list")}  # fmt: skip
    result = procedure.run(config)
    if result.index(0) != Gimp.PDBStatusType.SUCCESS or not os.path.exists(path):
        message = ""
        try:
            message = str(result.index(1))
        except Exception:
            pass
        raise BridgeError("WRITE_FAILED", "%s could not write %s %s" % (name, path, message), {"path": path})
    return {"path": path, "procedure": name, "bytes": os.path.getsize(path), "options": effective,
            **gmb_formats.behaviour(name, effective)}  # fmt: skip


@mutation
def image_export_as(params):
    image = get_image(params)
    name, procedure = _file_procedure("export", params)
    return _export_with(image, params["path"], name, procedure, params.get("options"), params.get("metadata") or [])


@mutation
def image_open_with(params):
    path = params["path"]
    known = gmb_formats.procedure_for(path, _file_procedures("load"))
    if not params.get("procedure") and not params.get("options") and known is None:
        # no procedure known by name (e.g. RAW through darktable/RawTherapee): let GIMP choose
        image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
        if image is None:
            raise BridgeError("UNSUPPORTED_FORMAT", "GIMP could not open %s" % path, {"path": path})
        return {**image_ref(image, show(image)), "procedure": "gimp-file-load"}
    name, procedure = _file_procedure("load", params)
    specs = _option_specs(procedure, LOAD_FIXED)
    values = _validated_options(name, specs, params.get("options"))
    # GimpInt32Array options (PDF pages) cannot be set from Python: pages are picked after loading
    pages = values.pop("pages", None) if name == "file-pdf-load" else None
    for key in [k for k, v in values.items() if isinstance(v, list)]:
        raise BridgeError("UNSUPPORTED", "%s: option %s cannot be set from a plug-in" % (name, key))
    config = procedure.create_config()
    config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    config.set_property("file", Gio.File.new_for_path(path))
    _apply_options(config, specs, values)
    result = procedure.run(config)
    if result.index(0) != Gimp.PDBStatusType.SUCCESS:
        raise BridgeError("UNSUPPORTED_FORMAT", "%s could not open %s" % (name, path), {"path": path})
    image = result.index(1)
    if pages is not None:
        layers = image.get_layers()  # one layer per page, the last page on top
        count = len(layers)
        if not pages or any(not 1 <= page <= count for page in pages):
            image.delete()
            raise BridgeError("INVALID_ARGUMENT", "pages must be between 1 and %d" % count, {"pages": count})
        image.undo_disable()
        for index, layer in enumerate(layers):
            if count - index not in pages:
                image.remove_layer(layer)
        image.undo_enable()
    shown = show(image)
    return {**image_ref(image, shown), "procedure": name}


def _export_copy(source_image, layer, path, name, procedure, params):
    """Export one layer (or a region of the composite) through a temporary image."""
    copy = Gimp.Image.new(source_image.get_width(), source_image.get_height(), source_image.get_base_type())
    try:
        copy.undo_disable()
        if source_image.get_base_type() == Gimp.ImageBaseType.INDEXED:
            copy.set_palette(source_image.get_palette())
        layer_copy = Gimp.Layer.new_from_drawable(layer, copy)
        copy.insert_layer(layer_copy, None, 0)
        if params.get("crop", True):
            _ok, x, y = layer.get_offsets()
            copy.crop(layer.get_width(), layer.get_height(), x, y)
        return _export_with(copy, path, name, procedure, params.get("options"), params.get("metadata") or [])
    finally:
        copy.delete()


@mutation
def image_export_layers(params):
    image = get_image(params)
    layers = [get_layer({"item": n}) for n in params["items"]] if params.get("items") else image.get_layers()
    if any(layer.get_image().get_id() != image.get_id() for layer in layers):
        raise BridgeError("IMAGE_MISMATCH", "every layer must belong to the image")
    directory, extension = params["directory"], params["extension"]
    name, procedure = _file_procedure("export", {"path": "x." + extension, "procedure": params.get("procedure")})
    files = []
    for index, layer in enumerate(layers):
        filename = gmb_formats.layer_filename(
            params.get("template", "{index:02d}-{name}"), index, layer.get_name(), extension
        )
        path = os.path.join(directory, filename)
        if os.path.exists(path) and not params.get("overwrite"):
            raise BridgeError("FILE_EXISTS", "%s exists (overwrite=false)" % path, {"path": path})
        files.append((layer, path))
    exported = [
        dict(_export_copy(image, layer, path, name, procedure, params), item=layer.get_id()) for layer, path in files
    ]
    return {"files": exported}


@mutation
def image_export_region(params):
    image = get_image(params)
    x, y, w, h = (int(params["region"][k]) for k in ("x", "y", "width", "height"))
    if x < 0 or y < 0 or w < 1 or h < 1 or x + w > image.get_width() or y + h > image.get_height():
        raise BridgeError("INVALID_ARGUMENT", "the region must lie inside the canvas")
    name, procedure = _file_procedure("export", params)
    copy = image.duplicate()
    try:
        copy.undo_disable()
        copy.crop(w, h, x, y)
        return _export_with(copy, params["path"], name, procedure, params.get("options"), params.get("metadata") or [])
    finally:
        copy.delete()


# -- text --------------------------------------------------------------------------------

JUSTIFICATIONS = {"left": "LEFT", "right": "RIGHT", "center": "CENTER", "fill": "FILL"}


def text_unit(abbreviation):
    return Gimp.Unit.point() if abbreviation == "pt" else Gimp.Unit.pixel()


def get_font(name):
    font = Gimp.Font.get_by_name(name)
    if font is None:
        words = name.split()
        suggestions = [f.get_name() for f in Gimp.fonts_get_list(words[0] if words else "")][:10]
        raise BridgeError(
            "FONT_NOT_FOUND",
            "GIMP has no font named %r" % name,
            {"font": name, "suggestions": suggestions},
        )
    return font


def get_text_layer(params):
    item = get_item(params)
    if item_kind(item) != "text":
        raise BridgeError(
            "WRONG_KIND",
            "item %d is a %s, not a text layer" % (item.get_id(), item_kind(item)),
            {"id": item.get_id(), "kind": item_kind(item)},
        )
    return item


def _hex(gegl_color):
    r, g, b, _a = gegl_color.get_rgba_with_space(Babl.space("sRGB"))
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b))


def apply_text_properties(layer, params, font=None):
    if params.get("text") is not None:
        layer.set_text(params["text"])
    if font is not None:
        layer.set_font(font)
    if params.get("size") is not None or params.get("unit") is not None:
        size, unit = layer.get_font_size()
        if params.get("size") is not None:
            size = params["size"]
        if params.get("unit") is not None:
            unit = text_unit(params["unit"])
        layer.set_font_size(float(size), unit)
    if params.get("color") is not None:
        layer.set_color(color(params["color"]))
    if params.get("justify") is not None:
        layer.set_justification(getattr(Gimp.TextJustification, JUSTIFICATIONS[params["justify"]]))
    if params.get("letter_spacing") is not None:
        layer.set_letter_spacing(float(params["letter_spacing"]))
    if params.get("line_spacing") is not None:
        layer.set_line_spacing(float(params["line_spacing"]))
    if params.get("antialias") is not None:
        layer.set_antialias(bool(params["antialias"]))
    if params.get("box") is not None:
        layer.resize(float(params["box"][0]), float(params["box"][1]))


@mutation
def text_create(params):
    image = get_image(params)
    parent = resolve_parent(image, params)
    check_position(image, parent, params["position"])
    font = get_font(params.get("font") or "Sans-serif")
    with undo_step(image):
        layer = Gimp.TextLayer.new(image, params["text"], font, float(params["size"]), text_unit(params.get("unit")))
        image.insert_layer(layer, parent, params["position"])
        apply_text_properties(layer, dict(params, text=None, size=None, unit=None))
        layer.set_offsets(params.get("x", 0), params.get("y", 0))
    return layer_node(layer)


@mutation
def text_set(params):
    layer = get_text_layer(params)
    font = get_font(params["font"]) if params.get("font") else None
    if (params.get("x") is not None or params.get("y") is not None) and layer.get_lock_position():
        raise BridgeError("LOCKED", "the position of %r is locked" % layer.get_name(), {"item": layer.get_id()})
    with undo_step(layer.get_image()):
        apply_text_properties(layer, params, font)
        if params.get("x") is not None or params.get("y") is not None:
            _ok, x, y = layer.get_offsets()
            layer.set_offsets(
                params["x"] if params.get("x") is not None else x, params["y"] if params.get("y") is not None else y
            )
    return layer_node(layer)


def text_get(params):
    layer = get_text_layer(params)
    size, unit = layer.get_font_size()
    _ok, x, y = layer.get_offsets()
    return {
        "text": layer.get_text() or "",
        "font": layer.get_font().get_name(),
        "size": float(size),
        "size_unit": "pt" if unit.get_abbreviation() == "pt" else "px",
        "color": _hex(layer.get_color()),
        "justify": layer.get_justification().value_nick,
        "letter_spacing": float(layer.get_letter_spacing()),
        "line_spacing": float(layer.get_line_spacing()),
        "antialias": bool(layer.get_antialias()),
        "x": x,
        "y": y,
        "width": layer.get_width(),
        "height": layer.get_height(),
    }


def fonts_list(params):
    fonts = [f.get_name() for f in Gimp.fonts_get_list(params.get("query") or "")]
    return {"fonts": fonts[: int(params.get("limit", 100))], "total": len(fonts)}


# -- generic PDB access ------------------------------------------------------------------


def _lookup(name):
    pdb = Gimp.get_pdb()
    if not isinstance(name, str) or not pdb.procedure_exists(name):
        raise BridgeError("NOT_FOUND", "no procedure named %r" % name, {"name": name})
    return pdb.lookup_procedure(name)


def pdb_callable(params):
    query = params.get("query") or ""
    limit = int(params.get("limit", 50))
    pdb = Gimp.get_pdb()
    found = []
    for name in _all_names():
        if query and query not in name:
            continue
        meta = describe_procedure(pdb.lookup_procedure(name))
        if gmb_policy.evaluate(meta)[0]:
            found.append(meta)
    return {
        "procedures": [
            {
                "name": m["name"],
                "description": m["description"],
                "arguments": m["arguments"],
                "return_values": m["return_values"],
            }
            for m in found[:limit]
        ],
        "total": len(found),
    }


def _enum_value(pspec, nick):
    for value in pspec.enum_class.__enum_values__.values():
        if value.value_nick == nick:
            return value
    raise BridgeError("INVALID_ARGUMENT", "argument %r: unknown value %r" % (pspec.name, nick))


def _resolve_object(kind, number, name):
    if kind == "image":
        if not Gimp.Image.id_is_valid(number):
            raise BridgeError("NOT_FOUND", "argument %r: image %d does not exist" % (name, number), {"argument": name})
        return Gimp.Image.get_by_id(number)
    if not Gimp.Item.id_is_valid(number):
        raise BridgeError("NOT_FOUND", "argument %r: item %d does not exist" % (name, number), {"argument": name})
    return Gimp.Item.get_by_id(number)


def _serialize(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Gimp.Image):
        return "image:%d@%s" % (value.get_id(), SESSION["id"])
    if isinstance(value, Gimp.Item):
        return "item:%d@%s" % (value.get_id(), SESSION["id"])
    if isinstance(value, Gegl.Color):
        r, g, b, a = value.get_rgba_with_space(Babl.space("sRGB"))
        return "#%02x%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b, a))
    nick = getattr(value, "value_nick", None)
    if nick is not None:
        return nick
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return repr(value)


@mutation
def pdb_call(params):
    procedure = _lookup(params.get("name"))
    meta = describe_procedure(procedure)
    try:
        plan = gmb_policy.plan_call(meta, params.get("arguments") or {}, SESSION["id"])
    except gmb_policy.PolicyError as exc:
        raise BridgeError(exc.code, exc.message, exc.details) from exc
    pspecs = {p.name: p for p in procedure.get_arguments()}
    config = procedure.create_config()
    image = None
    for name, kind, value in plan:
        pspec = pspecs[name]
        if kind == "run-mode":
            converted = Gimp.RunMode.NONINTERACTIVE
        elif kind in ("image", "item"):
            converted = _resolve_object(kind, value, name)
            owner = converted if kind == "image" else converted.get_image()
            image = image or owner
        elif kind == "items":
            converted = [_resolve_object("item", number, name) for number in value]
            if converted:
                image = image or converted[0].get_image()
        elif kind == "color":
            converted = Gegl.Color.new(value)
        elif kind == "enum":
            converted = _enum_value(pspec, value)
        else:
            converted = value
        try:
            if kind == "items":
                config.set_core_object_array(name, converted)
            else:
                config.set_property(name, converted)
        except (TypeError, ValueError) as exc:
            raise BridgeError(
                "INVALID_ARGUMENT", "argument %r: %s" % (name, exc), {"argument": name, "expected": meta_type(pspec)}
            ) from exc
    if image is not None:
        image.undo_group_start()
    try:
        result = procedure.run(config)
    finally:
        if image is not None:
            image.undo_group_end()
    status = result.index(0)
    if status != Gimp.PDBStatusType.SUCCESS:
        message = ""
        try:
            message = str(result.index(1) or "")
        except Exception:
            pass
        raise BridgeError(
            "GIMP_ERROR",
            "%s failed (%s) %s" % (meta["name"], getattr(status, "value_nick", status), message),
            {"status": getattr(status, "value_nick", str(status))},
        )
    results = {}
    for index, ret in enumerate(procedure.get_return_values()):
        results[ret.name] = _serialize(result.index(index + 1))
    return {"results": results}


def meta_type(pspec):
    return pspec.value_type.name


# -- history: undo groups and checkpoints ------------------------------------------------

_BRIDGE = {"server": None}


def _undo_start(number):
    Gimp.Image.get_by_id(number).undo_group_start()


def _undo_end(number):
    Gimp.Image.get_by_id(number).undo_group_end()


UNDO_GROUPS = gmb_undo.UndoGroups(start=_undo_start, end=_undo_end, is_valid=Gimp.Image.id_is_valid)


def attach(server):
    """Give operations access to per-connection state and disconnection events."""
    _BRIDGE["server"] = server
    server.on_disconnect.append(UNDO_GROUPS.close_connection)


def _connection():
    server = _BRIDGE["server"]
    return None if server is None else server.current_connection_id


@mutation
def undo_begin(params):
    image = get_image(params)
    return {"depth": UNDO_GROUPS.begin(_connection(), image.get_id())}


@mutation
def undo_end(params):
    image = get_image(params)
    try:
        return {"depth": UNDO_GROUPS.end(_connection(), image.get_id())}
    except gmb_undo.NoOpenGroup as exc:
        raise BridgeError(
            "NO_OPEN_GROUP",
            str(exc),
            {"image": image.get_id(), "hint": "groups are closed automatically when a client disconnects"},
        ) from exc


MAX_CHECKPOINTS = 20
_CHECKPOINTS = {}  # number -> {"lineage", "copy", "label", "created"}
_LINEAGE = {}  # image id -> lineage id (stable across restorations)
_CHECKPOINT_COUNTER = [0]


def lineage_of(image_id):
    return _LINEAGE.setdefault(image_id, image_id)


def checkpoint_image_ids():
    return {c["copy"].get_id() for c in _CHECKPOINTS.values() if c["copy"].is_valid()}


def _current_image_of(lineage):
    for image_id, owner in _LINEAGE.items():
        if owner == lineage and Gimp.Image.id_is_valid(image_id):
            return image_id
    return None


def _checkpoint_info(number, entry):
    copy = entry["copy"]
    return {
        "checkpoint": number,
        "label": entry["label"],
        "image": _current_image_of(entry["lineage"]),
        "width": copy.get_width(),
        "height": copy.get_height(),
        "created": entry["created"],
    }


def drop_checkpoints_of(image_id):
    lineage = lineage_of(image_id)
    for number in [n for n, c in _CHECKPOINTS.items() if c["lineage"] == lineage]:
        entry = _CHECKPOINTS.pop(number)
        if entry["copy"].is_valid():
            entry["copy"].delete()


@mutation
def checkpoint_create(params):
    import time

    image = get_image(params)
    lineage = lineage_of(image.get_id())
    if sum(1 for c in _CHECKPOINTS.values() if c["lineage"] == lineage) >= MAX_CHECKPOINTS:
        raise BridgeError(
            "CHECKPOINT_LIMIT",
            "the image already has %d checkpoints: delete some first" % MAX_CHECKPOINTS,
            {"limit": MAX_CHECKPOINTS},
        )
    copy = image.duplicate()
    copy.undo_disable()
    _CHECKPOINT_COUNTER[0] += 1
    number = _CHECKPOINT_COUNTER[0]
    _CHECKPOINTS[number] = {"lineage": lineage, "copy": copy, "label": params.get("label"), "created": time.time()}
    return _checkpoint_info(number, _CHECKPOINTS[number])


def checkpoint_list(params):
    image = get_image(params)
    if image.get_id() in checkpoint_image_ids():
        raise BridgeError("NOT_FOUND", "image %d does not exist" % image.get_id())
    lineage = lineage_of(image.get_id())
    return {
        "checkpoints": [
            _checkpoint_info(number, entry)
            for number, entry in sorted(_CHECKPOINTS.items())
            if entry["lineage"] == lineage
        ]
    }


def _get_checkpoint(params):
    number = _int_param(params, "checkpoint")
    entry = _CHECKPOINTS.get(number)
    if entry is None or not entry["copy"].is_valid():
        raise BridgeError("NOT_FOUND", "checkpoint %d does not exist" % number, {"checkpoint": number})
    return number, entry


@mutation
def checkpoint_restore(params):
    image = get_image(params)
    number, entry = _get_checkpoint(params)
    lineage = lineage_of(image.get_id())
    if entry["lineage"] != lineage:
        raise BridgeError(
            "IMAGE_MISMATCH",
            "checkpoint %d belongs to another image" % number,
            {"checkpoint": number, "image": image.get_id()},
        )
    restored = entry["copy"].duplicate()
    restored.undo_disable()
    xcf = image.get_xcf_file()
    if xcf is not None:
        restored.set_file(xcf)
    old_id = image.get_id()
    reconnected = Gimp.displays_reconnect(image, restored)
    _LINEAGE[restored.get_id()] = lineage
    displays = _DISPLAYS.pop(old_id, [])
    if reconnected and displays:
        _DISPLAYS[restored.get_id()] = displays
    image.delete()
    _LINEAGE.pop(old_id, None)
    restored.undo_enable()
    shown = bool(reconnected)
    return image_ref(restored, shown)


@mutation
def checkpoint_delete(params):
    number, entry = _get_checkpoint(params)
    _CHECKPOINTS.pop(number)
    entry["copy"].delete()
    return {"checkpoint": number}


# -- analysis (read-only) ------------------------------------------------------------------

MAX_ANALYSIS_PIXELS = 50_000_000
RGBA_U8 = "R'G'B'A u8"
LUMA_U8 = "Y' u8"


def _source(params, key):
    """{"kind": "image"|"item"|"checkpoint", "id": n} -> ("image", image) or ("drawable", drawable)."""
    ref = params.get(key)
    if not isinstance(ref, dict) or ref.get("kind") not in ("image", "item", "checkpoint"):
        raise BridgeError("INVALID_ARGUMENT", "%s must be an image, item or checkpoint reference" % key)
    if ref["kind"] == "image":
        return "image", get_image({"image": ref.get("id")})
    if ref["kind"] == "checkpoint":
        _number, entry = _get_checkpoint({"checkpoint": ref.get("id")})
        return "image", entry["copy"]
    item = get_item({"item": ref.get("id")})
    if not isinstance(item, Gimp.Drawable):
        raise BridgeError(
            "WRONG_KIND",
            "item %d is a %s, which has no pixels" % (item.get_id(), item_kind(item)),
            {"id": item.get_id(), "kind": item_kind(item)},
        )
    return "drawable", item


class _Pixels:
    """Pixels of an image composite (a temporary flattened copy) or of a drawable.

    The analysed image is never changed: the composite comes from a duplicate
    that is deleted on exit.
    """

    def __init__(self, kind, target):
        self.kind = kind
        self.target = target
        self.copy = None

    def __enter__(self):
        if self.kind == "image":
            image = self.target
            if not image.get_layers():
                raise BridgeError("INVALID_ARGUMENT", "the image has no layers")
            self.copy = image.duplicate()
            self.copy.undo_disable()
            merged = self.copy.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
            if merged is None:
                self.copy.delete()
                raise BridgeError("INVALID_ARGUMENT", "the image has no visible layer")
            merged.resize_to_image_size()
            self.drawable = merged
            self.offset = (0, 0)
            self.image = image
        else:
            self.drawable = self.target
            _ok, ox, oy = self.drawable.get_offsets()
            self.offset = (ox, oy)
            self.image = self.drawable.get_image()
        self.width = self.drawable.get_width()
        self.height = self.drawable.get_height()
        return self

    def __exit__(self, *exc):
        if self.copy is not None:
            self.copy.delete()
        return False

    def bounds(self):
        """Area in image coordinates."""
        return self.offset[0], self.offset[1], self.width, self.height

    def region(self, region):
        """Requested region (image coordinates) clipped to the pixels; refused when empty or too large."""
        bx, by, bw, bh = self.bounds()
        if region is None:
            x, y, w, h = bx, by, bw, bh
        else:
            x, y, w, h = (int(region[k]) for k in ("x", "y", "width", "height"))
        x0, y0 = max(x, bx), max(y, by)
        x1, y1 = min(x + w, bx + bw), min(y + h, by + bh)
        if x1 <= x0 or y1 <= y0:
            raise BridgeError(
                "INVALID_ARGUMENT",
                "the region does not overlap the pixels (%d,%d %dx%d)" % (bx, by, bw, bh),
                {"bounds": {"x": bx, "y": by, "width": bw, "height": bh}},
            )
        if (x1 - x0) * (y1 - y0) > MAX_ANALYSIS_PIXELS:
            raise BridgeError("INVALID_ARGUMENT", "region too large: at most %d pixels" % MAX_ANALYSIS_PIXELS)
        return x0, y0, x1 - x0, y1 - y0

    def read(self, area, fmt=RGBA_U8, scale=1.0):
        x, y, w, h = area
        rect = Gegl.Rectangle.new(
            int((x - self.offset[0]) * scale),
            int((y - self.offset[1]) * scale),
            max(1, int(w * scale)),
            max(1, int(h * scale)),
        )
        return bytes(self.drawable.get_buffer().get(rect, scale, fmt, Gegl.AbyssPolicy.CLAMP))


def _area_dict(area):
    return {"x": area[0], "y": area[1], "width": area[2], "height": area[3]}


def analysis_histogram(params):
    kind, target = _source(params, "target")
    channels = params.get("channels") or ["red", "green", "blue", "luminance"]
    with _Pixels(kind, target) as pixels:
        area = pixels.region(params.get("region"))
        mask = None
        if params.get("selection_only"):
            image = pixels.image
            if Gimp.Selection.is_empty(image):
                raise BridgeError("EMPTY_SELECTION", "selection_only is set but nothing is selected")
            selection = image.get_selection()
            x, y, w, h = area
            mask = bytes(selection.get_buffer().get(Gegl.Rectangle.new(x, y, w, h), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
        data = pixels.read(area)
        luminance = pixels.read(area, LUMA_U8) if "luminance" in channels else None
    stats = gmb_stats.channel_stats(
        data,
        channels,
        percentiles=params.get("percentiles", (5, 25, 50, 75, 95)),
        bins=int(params.get("bins", 16)),
        mask=mask,
        luminance=luminance,
    )
    return {"region": _area_dict(area), "selection_only": bool(params.get("selection_only")), "channels": stats}


def analysis_sample(params):
    kind, target = _source(params, "target")
    radius = int(params.get("radius", 0))
    points = params.get("points") or []
    with _Pixels(kind, target) as pixels:
        bx, by, bw, bh = pixels.bounds()
        for x, y in points:
            if not (bx <= x < bx + bw and by <= y < by + bh):
                raise BridgeError(
                    "INVALID_ARGUMENT",
                    "point (%d, %d) is outside the pixels (%d,%d %dx%d)" % (x, y, bx, by, bw, bh),
                    {"point": [x, y]},
                )
        samples = []
        for x, y in points:
            area = pixels.region({"x": x - radius, "y": y - radius, "width": 2 * radius + 1, "height": 2 * radius + 1})
            data = pixels.read(area)
            n = len(data) // 4
            rgba = [round(sum(data[c::4]) / n) for c in range(4)]
            samples.append(
                {
                    "x": x,
                    "y": y,
                    "hex": "#%02x%02x%02x" % tuple(rgba[:3]),
                    "rgba": rgba,
                    "pixels_averaged": n,
                }
            )
    return {"samples": samples}


def analysis_compare(params):
    import base64

    sides = []
    for key in ("a", "b"):
        kind, target = _source(params, key)
        with _Pixels(kind, target) as pixels:
            sides.append((pixels.width, pixels.height, pixels.read(pixels.region(None))))
    (wa, ha, a), (wb, hb, b) = sides
    if (wa, ha) != (wb, hb):
        raise BridgeError(
            "INVALID_ARGUMENT",
            "sizes differ: %dx%d and %dx%d" % (wa, ha, wb, hb),
            {"a": [wa, ha], "b": [wb, hb]},
        )
    threshold = int(params.get("threshold", 0))
    result = gmb_stats.compare(a, b, wa, ha, threshold)
    if params.get("preview"):
        png, pw, ph = gmb_stats.difference_png(a, b, wa, ha, threshold, int(params.get("max_size", 512)))
        result["preview"] = {"png_base64": base64.b64encode(png).decode("ascii"), "width": pw, "height": ph}
    return result


def analysis_dominant(params):
    kind, target = _source(params, "target")
    with _Pixels(kind, target) as pixels:
        area = pixels.region(params.get("region"))
        scale = min(1.0, 256.0 / max(area[2], area[3]))
        data = pixels.read(area, scale=scale)
    return {
        "region": _area_dict(area),
        "sampled_scale": scale,
        "colors": gmb_stats.dominant_colors(data, int(params.get("count", 5))),
    }


def image_preview_region(params):
    """Full-resolution crop of the composite, rendered from a temporary copy."""
    import base64

    kind, image = _source(params, "target")
    if kind != "image":
        raise BridgeError("WRONG_KIND", "target must be an image or a checkpoint")
    region = params["region"]
    x, y, w, h = (int(region[k]) for k in ("x", "y", "width", "height"))
    if x < 0 or y < 0 or w < 1 or h < 1 or x + w > image.get_width() or y + h > image.get_height():
        raise BridgeError(
            "INVALID_ARGUMENT",
            "the region must lie inside the %dx%d canvas" % (image.get_width(), image.get_height()),
        )
    max_size = int(params.get("max_size", 1024))
    copy = image.duplicate()
    try:
        copy.undo_disable()
        copy.crop(w, h, x, y)
        pw, ph = _fit(w, h, max_size)
        pixbuf = copy.get_thumbnail(pw, ph, Gimp.PixbufTransparency.KEEP_ALPHA)
        if pixbuf is None:
            raise BridgeError("GIMP_ERROR", "GIMP could not render a %dx%d preview" % (pw, ph))
        ok, data = pixbuf.save_to_bufferv("png", [], [])
        if not ok:
            raise BridgeError("GIMP_ERROR", "PNG encoding of the preview failed")
    finally:
        copy.delete()
    return {
        "png_base64": base64.b64encode(bytes(data)).decode("ascii"),
        "width": pixbuf.get_width(),
        "height": pixbuf.get_height(),
        "region": {"x": x, "y": y, "width": w, "height": h},
    }


def build_operations():
    return {
        "undo.begin": undo_begin,
        "undo.end": undo_end,
        "checkpoint.create": checkpoint_create,
        "checkpoint.list": checkpoint_list,
        "checkpoint.restore": checkpoint_restore,
        "checkpoint.delete": checkpoint_delete,
        "pdb.callable": pdb_callable,
        "pdb.call": pdb_call,
        "text.create": text_create,
        "text.set": text_set,
        "text.get": text_get,
        "fonts.list": fonts_list,
        "filter.apply": filter_apply,
        "filter.list": filter_list,
        "filter.remove": filter_remove,
        "filter.operations": filter_operations,
        "formats.list": file_formats,
        "formats.describe": file_format_describe,
        "image.export_as": image_export_as,
        "image.open_with": image_open_with,
        "image.export_layers": image_export_layers,
        "image.export_region": image_export_region,
        "guides.list": guides_list,
        "guide.add": guide_add,
        "sample_point.add": sample_point_add,
        "guide.remove": guide_remove,
        "metadata.get": metadata_get,
        "metadata.set": metadata_set,
        "image.set_print": image_set_print,
        "clipboard.copy": clipboard_copy,
        "clipboard.paste": clipboard_paste,
        "layers.merge": layers_merge,
        "image.flatten": image_flatten,
        "layer.from_visible": layer_from_visible,
        "layer.alpha": layer_alpha,
        "selection.from_alpha": selection_from_alpha,
        "layer.fit": layer_fit,
        "image.crop_to_content": image_crop_to_content,
        "layers.align": layers_align,
        "resources.list": resources_list,
        "resource.inspect": resource_inspect,
        "resource.create": resource_create,
        "resource.duplicate": resource_duplicate,
        "resource.rename": resource_rename,
        "resource.delete": resource_delete,
        "brush.edit": brush_edit,
        "gradient.edit": gradient_edit,
        "palette.edit": palette_edit,
        "palette.import": palette_import,
        "palette.export": palette_export,
        "path.create": path_create,
        "path.add_stroke": path_add_stroke,
        "path.from_text": path_from_text,
        "path.inspect": path_inspect,
        "path.set": path_set,
        "path.duplicate": path_duplicate,
        "path.delete": path_delete,
        "path.edit_stroke": path_edit_stroke,
        "path.point_at": path_point_at,
        "path.to_selection": path_to_selection,
        "selection.to_path": selection_to_path,
        "path.stroke": path_stroke,
        "path.fill": path_fill,
        "paths.import_svg": paths_import_svg,
        "paths.export_svg": paths_export_svg,
        "image.convert_mode": image_convert_mode,
        "image.convert_precision": image_convert_precision,
        "profile.get": color_profile_get,
        "profile.set": color_profile_set,
        "color.adjust": color_adjust,
        "color.curves": color_curves,
        "filter.describe": filter_operation_describe,
        "filter.apply_any": filter_apply_any,
        "filter.inspect": filter_inspect,
        "filter.set": filter_set,
        "filter.reorder": filter_reorder,
        "filter.merge": filter_merge,
        "paint.fill": paint_fill,
        "paint.path": paint_path,
        "paint.shape": paint_shape,
        "selection.rect": selection_rect,
        "selection.ellipse": selection_ellipse,
        "selection.modify": selection_modify,
        "selection.get": selection_get,
        "mask.add": mask_add,
        "mask.set": mask_set,
        "mask.remove": mask_remove,
        "pdb.search": pdb_search,
        "pdb.describe": pdb_describe,
        "pdb.inventory": pdb_inventory,
        "image.scale": image_scale,
        "image.resize": image_resize,
        "image.crop": image_crop,
        "layer.offsets": layer_offsets,
        "layer.scale": layer_scale,
        "layer.rotate": layer_rotate,
        "layer.flip": layer_flip,
        "layer.create": layer_create,
        "group.create": group_create,
        "layer.import": layer_import,
        "layer.duplicate": layer_duplicate,
        "layer.set": layer_set,
        "layer.move": layer_move,
        "layer.delete": layer_delete,
        "image.create": image_create,
        "image.open": image_open,
        "image.save": image_save,
        "image.export": image_export,
        "image.close": image_close,
        "image.preview": image_preview,
        "image.preview_region": image_preview_region,
        "analysis.histogram": analysis_histogram,
        "analysis.sample": analysis_sample,
        "analysis.compare": analysis_compare,
        "analysis.dominant": analysis_dominant,
        "session.images": session_images,
        "image.inspect": image_inspect,
        "item.inspect": item_inspect,
    }

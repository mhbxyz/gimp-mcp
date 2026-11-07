"""Bridge operations: the only module that calls the GIMP API.

Each operation takes a ``params`` dict (already JSON-decoded) and returns a
JSON-serializable value. Anticipated failures raise ``BridgeError`` *before*
changing anything; validation of argument types/ranges is done by the MCP
server, the checks here guard against stale ids and GIMP-side conditions.
"""

import os

import gi

gi.require_version("Babl", "0.1")
import gmb_policy  # noqa: E402
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
            "layers": [layer_node(layer) for layer in image.get_layers()],
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
    return {"images": [image_summary(image) for image in Gimp.get_images()]}


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


METADATA_OFF = {
    "include-exif": False,
    "include-iptc": False,
    "include-xmp": False,
    "include-thumbnail": False,
    "include-comment": False,
}


@mutation
def image_export(params):
    image = get_image(params)
    path, kind, options = params["path"], params["format"], params["options"]
    if kind == "png":
        settings = dict(METADATA_OFF)
        settings.update({"compression": options["compression"], "interlaced": options["interlaced"], "bkgd": False})
        _run_export("file-png-export", image, path, settings)
    elif kind == "jpeg":
        settings = dict(METADATA_OFF)
        settings.update(
            {
                "quality": options["quality"] / 100.0,
                "progressive": options["progressive"],
                "optimize": options["optimize"],
                "smoothing": options["smoothing"],
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


def build_operations():
    return {
        "pdb.callable": pdb_callable,
        "pdb.call": pdb_call,
        "text.create": text_create,
        "text.set": text_set,
        "text.get": text_get,
        "fonts.list": fonts_list,
        "filter.apply": filter_apply,
        "filter.list": filter_list,
        "filter.remove": filter_remove,
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
        "session.images": session_images,
        "image.inspect": image_inspect,
        "item.inspect": item_inspect,
    }

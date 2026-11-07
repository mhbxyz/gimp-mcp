"""Bridge operations: the only module that calls the GIMP API.

Each operation takes a ``params`` dict (already JSON-decoded) and returns a
JSON-serializable value. Anticipated failures raise ``BridgeError`` *before*
changing anything; validation of argument types/ranges is done by the MCP
server, the checks here guard against stale ids and GIMP-side conditions.
"""

import os

import gi

gi.require_version("Babl", "0.1")
from gi.repository import Babl, Gegl, Gimp, Gio  # noqa: E402
from gmb_server import BridgeError  # noqa: E402

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


def build_operations():
    return {
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

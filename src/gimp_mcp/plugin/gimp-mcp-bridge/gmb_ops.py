"""Bridge operations: the only module that calls the GIMP API.

Each operation takes a ``params`` dict (already JSON-decoded) and returns a
JSON-serializable value. Anticipated failures raise ``BridgeError`` *before*
changing anything; validation of argument types/ranges is done by the MCP
server, the checks here guard against stale ids and GIMP-side conditions.
"""

from gi.repository import Gimp
from gmb_server import BridgeError

# -- resolving ids ---------------------------------------------------------------------


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


def build_operations():
    return {
        "image.preview": image_preview,
        "session.images": session_images,
        "image.inspect": image_inspect,
        "item.inspect": item_inspect,
    }

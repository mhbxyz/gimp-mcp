"""Bridge operations: the only module that calls the GIMP API.

Each operation takes a ``params`` dict (already JSON-decoded) and returns a
JSON-serializable value. Anticipated failures raise ``BridgeError`` *before*
changing anything; validation of argument types/ranges is done by the MCP
server, the checks here guard against stale ids and GIMP-side conditions.
"""

from gi.repository import Gimp
from gmb_server import BridgeError  # noqa: F401


def _file_path(image):
    gfile = image.get_file()
    if gfile is None:
        return None
    return gfile.get_path()


def image_summary(image):
    return {
        "id": image.get_id(),
        "name": image.get_name(),
        "file": _file_path(image),
        "width": image.get_width(),
        "height": image.get_height(),
        "dirty": bool(image.is_dirty()),
    }


def session_images(params):
    return {"images": [image_summary(image) for image in Gimp.get_images()]}


def build_operations():
    return {
        "session.images": session_images,
    }

"""Authorization policy and argument planning for generic PDB calls.

Standard library only: used inside GIMP by the bridge (with live procedure
metadata) and outside GIMP by tests and the coverage matrix (with the
inventory). A procedure is callable only if

1. its name is not denied (code evaluation, consoles, servers, quitting,
   deleting images, changing the shared GIMP context, UI, help, PDB/plug-in
   management, the bridge itself, and plug-ins acting outside the image:
   screenshots, e-mail, printing, web browser, UI-only browsers/editors);
2. it belongs to an allowed family (image/item/layer/drawable/selection/
   channel/path/text getters and setters, ``gimp-get-*`` and the ``plug-in-*``
   filters shipped with GIMP, never a third-party plug-in) — files, exports
   and resources are therefore excluded;
3. it is an internal or plug-in procedure (not temporary/persistent);
4. every argument and return value has a type that can be converted to and
   from JSON safely (scalars, enums by nick, colors, images and items by id,
   arrays of those). ``GFile``, ``GBytes``, parasites, units, resources,
   displays and export options are not.

The run mode is always forced to non-interactive: no dialog can be opened.
"""

from __future__ import annotations

import re

DENIED_SUBSTRINGS = (
    "eval",
    "console",
    "server",
    "popup",
    "script-fu",
    "python-fu",
    "extension-",
    "gimp-quit",
    "gimp-image-delete",
    "gimp-context-set",
    "gimp-context-push",
    "gimp-context-pop",
    "gimp-display",
    "gimp-help",
    "gimp-online",
    "gimp-plug-in",
    "gimp-pdb",
    "gimp-temp",
    "gimp-message",
    "gimp-fonts-refresh",
    "gimp-gradients-refresh",
    "gimp-brushes-refresh",
    "gimp-patterns-refresh",
    "gimp-palettes-refresh",
    "-parasite",
    # plug-ins with effects outside the image or that only make sense with a UI
    "browser",
    "screenshot",
    "mail",
    "print",
    "dialog",
    "goat-exercise",
    "animationplay",
    "unit-editor",
    "plug-in-details",
    "metadata-",
    "imagemap",
    "gmic",
)

ALLOWED_PREFIXES = (
    "gimp-image-",
    "gimp-item-",
    "gimp-layer-",
    "gimp-group-layer-",
    "gimp-text-layer-",
    "gimp-drawable-",
    "gimp-selection-",
    "gimp-channel-",
    "gimp-path-",
    "gimp-context-get-",
    "gimp-get-",
    "plug-in-",
)

# The plug-in-* procedures shipped with GIMP 3.2.6 (docs/coverage/pdb-inventory.json; a test keeps them equal).
# A third-party plug-in (G'MIC-Qt runs shell commands) is never callable, whatever its name (#122).
GIMP_PLUG_INS = frozenset(
    {
        "plug-in-align-layers",
        "plug-in-animationoptimize",
        "plug-in-animationoptimize-diff",
        "plug-in-animationplay",
        "plug-in-animationunoptimize",
        "plug-in-blinds",
        "plug-in-borderaverage",
        "plug-in-busy-dialog",
        "plug-in-checkerboard",
        "plug-in-cml-explorer",
        "plug-in-colormap-remap",
        "plug-in-colormap-swap",
        "plug-in-compose",
        "plug-in-curve-bend",
        "plug-in-dbbrowser",
        "plug-in-decompose",
        "plug-in-depth-merge",
        "plug-in-despeckle",
        "plug-in-destripe",
        "plug-in-drawable-compose",
        "plug-in-film",
        "plug-in-flame",
        "plug-in-fractalexplorer",
        "plug-in-gegl-filter-browser",
        "plug-in-gfig",
        "plug-in-gflare",
        "plug-in-gimpressionist",
        "plug-in-goat-exercise-c",
        "plug-in-goat-exercise-python",
        "plug-in-goat-exercise-vala",
        "plug-in-gradmap",
        "plug-in-grid",
        "plug-in-guillotine",
        "plug-in-hot",
        "plug-in-ifscompose",
        "plug-in-imagemap",
        "plug-in-jigsaw",
        "plug-in-lic",
        "plug-in-lighting",
        "plug-in-mail-image",
        "plug-in-map-object",
        "plug-in-metadata-editor",
        "plug-in-metadata-viewer",
        "plug-in-nl-filter",
        "plug-in-pagecurl",
        "plug-in-palettemap",
        "plug-in-plug-in-details",
        "plug-in-qbist",
        "plug-in-recompose",
        "plug-in-retinex",
        "plug-in-sample-colorize",
        "plug-in-screenshot",
        "plug-in-script-fu-console",
        "plug-in-script-fu-eval",
        "plug-in-script-fu-server",
        "plug-in-script-fu-text-console",
        "plug-in-sel2path",
        "plug-in-small-tiles",
        "plug-in-smooth-palette",
        "plug-in-sparkle",
        "plug-in-spheredesigner",
        "plug-in-spyrogimp",
        "plug-in-tile",
        "plug-in-unit-editor",
        "plug-in-warp",
        "plug-in-wavelet-decompose",
        "plug-in-web-browser",
        "plug-in-zealouscrop",
    }
)

ALLOWED_PROC_TYPES = ("internal", "plugin")

SCALARS = {
    "gint": int,
    "guint": int,
    "gint64": int,
    "guint64": int,
    "guchar": int,
    "gdouble": float,
    "gfloat": float,
    "gboolean": bool,
    "gchararray": str,
}
IMAGE_TYPES = {"GimpImage"}
ITEM_TYPES = {
    "GimpItem",
    "GimpDrawable",
    "GimpLayer",
    "GimpGroupLayer",
    "GimpTextLayer",
    "GimpChannel",
    "GimpLayerMask",
    "GimpSelection",
    "GimpPath",
}
ARRAYS = {"GimpDoubleArray": float, "GimpInt32Array": int, "GStrv": str}
OBJECT_ARRAYS = {"GimpCoreObjectArray"}
COLORS = {"GeglColor"}
RUN_MODE = "GimpRunMode"

_ID_RE = re.compile(r"^(image|item):(\d+)@([0-9A-Za-z]+)$")
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class PolicyError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def argument_kind(arg):
    """How a value of this argument travels as JSON, or None if unsupported."""
    gtype = arg.get("type")
    if gtype == RUN_MODE:
        return "run-mode"
    if gtype in SCALARS:
        return "scalar"
    if gtype in IMAGE_TYPES:
        return "image"
    if gtype in ITEM_TYPES:
        return "item"
    if gtype in OBJECT_ARRAYS:
        return "items"
    if gtype in ARRAYS:
        return "array"
    if gtype in COLORS:
        return "color"
    if arg.get("choices") and gtype not in SCALARS:
        return "enum"
    return None


def evaluate(meta):
    """Return (allowed, reason). ``meta`` is a describe_procedure() dictionary."""
    name = meta.get("name", "")
    for needle in DENIED_SUBSTRINGS:
        if needle in name:
            return False, "denied by policy (%r)" % needle
    if not name.startswith(ALLOWED_PREFIXES):
        return False, "outside the allowed procedure families"
    if name.startswith("plug-in-") and name not in GIMP_PLUG_INS:
        return False, "a plug-in not shipped with GIMP"
    if meta.get("error"):
        return False, "incomplete metadata: %s" % meta["error"]
    if meta.get("type") not in ALLOWED_PROC_TYPES:
        return False, "procedure type %r is not callable" % meta.get("type")
    for arg in meta.get("arguments", []):
        if argument_kind(arg) is None:
            return False, "argument %r has unsupported type %s" % (arg.get("name"), arg.get("type"))
    for ret in meta.get("return_values", []):
        if argument_kind(ret) in (None, "run-mode"):
            return False, "return value %r has unsupported type %s" % (ret.get("name"), ret.get("type"))
    return True, None


def parse_id(value, kind, session_id, name):
    match = _ID_RE.match(value) if isinstance(value, str) else None
    if match is None or match.group(1) != kind:
        raise PolicyError(
            "INVALID_ID",
            "argument %r must be a %s id like '%s:1@%s'" % (name, kind, kind, session_id),
            {"argument": name},
        )
    if match.group(3) != session_id:
        raise PolicyError("SESSION_CHANGED", "argument %r comes from another GIMP session" % name, {"argument": name})
    return int(match.group(2))


def _scalar(arg, value):
    expected = SCALARS[arg["type"]]
    name = arg["name"]
    if expected is bool:
        if not isinstance(value, bool):
            raise PolicyError("INVALID_ARGUMENT", "argument %r must be a boolean" % name, {"argument": name})
        return value
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise PolicyError("INVALID_ARGUMENT", "argument %r must be an integer" % name, {"argument": name})
    elif expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PolicyError("INVALID_ARGUMENT", "argument %r must be a number" % name, {"argument": name})
        value = float(value)
    elif not isinstance(value, str):
        raise PolicyError("INVALID_ARGUMENT", "argument %r must be a string" % name, {"argument": name})
    if arg.get("choices") and value not in arg["choices"]:
        raise PolicyError(
            "INVALID_ARGUMENT",
            "argument %r must be one of %s" % (name, ", ".join(arg["choices"])),
            {"argument": name, "allowed": arg["choices"]},
        )
    minimum, maximum = arg.get("minimum"), arg.get("maximum")
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if numeric and ((minimum is not None and value < minimum) or (maximum is not None and value > maximum)):
        raise PolicyError(
            "INVALID_ARGUMENT",
            "argument %r = %s is outside [%s, %s]" % (name, value, minimum, maximum),
            {"argument": name, "minimum": minimum, "maximum": maximum},
        )
    return value


def _convert(arg, kind, value, session_id):
    name = arg["name"]
    if kind == "scalar":
        return _scalar(arg, value)
    if kind == "image":
        return parse_id(value, "image", session_id, name)
    if kind == "item":
        return parse_id(value, "item", session_id, name)
    if kind == "items":
        if not isinstance(value, list):
            raise PolicyError("INVALID_ARGUMENT", "argument %r must be a list of item ids" % name, {"argument": name})
        return [parse_id(v, "item", session_id, name) for v in value]
    if kind == "array":
        expected = ARRAYS[arg["type"]]
        if (
            not isinstance(value, list)
            or not all(isinstance(v, expected) or (expected is float and isinstance(v, int)) for v in value)
            or any(isinstance(v, bool) for v in value)
        ):
            raise PolicyError(
                "INVALID_ARGUMENT", "argument %r must be a list of %s" % (name, expected.__name__), {"argument": name}
            )
        return [expected(v) for v in value]
    if kind == "color":
        if not isinstance(value, str) or _HEX_RE.match(value) is None:
            raise PolicyError("INVALID_ARGUMENT", "argument %r must be '#rrggbb' or '#rrggbbaa'" % name)
        return value
    if kind == "enum":
        if value not in arg["choices"]:
            raise PolicyError(
                "INVALID_ARGUMENT",
                "argument %r must be one of %s" % (name, ", ".join(arg["choices"])),
                {"argument": name, "allowed": arg["choices"]},
            )
        return value
    raise PolicyError("UNSUPPORTED_TYPE", "argument %r has an unsupported type" % name)


def plan_call(meta, arguments, session_id):
    """Validate JSON arguments; return [(name, kind, value)] for the given and forced ones.

    Arguments that are not given keep the procedure's defaults, except images and
    items which are required (GIMP has no sensible default for them).
    """
    allowed, reason = evaluate(meta)
    if not allowed:
        raise PolicyError("PROCEDURE_NOT_ALLOWED", "%s: %s" % (meta.get("name"), reason), {"reason": reason})
    if not isinstance(arguments, dict):
        raise PolicyError("INVALID_ARGUMENT", "arguments must be an object")
    specs = {arg["name"]: arg for arg in meta.get("arguments", [])}
    unknown = sorted(set(arguments) - set(specs))
    if unknown:
        raise PolicyError(
            "INVALID_ARGUMENT",
            "unknown argument(s): %s" % ", ".join(unknown),
            {"unknown": unknown, "expected": list(specs)},
        )
    plan = []
    for name, arg in specs.items():
        kind = argument_kind(arg)
        if kind == "run-mode":
            if name in arguments and arguments[name] != "noninteractive":
                raise PolicyError("INVALID_ARGUMENT", "only the noninteractive run mode is allowed")
            plan.append((name, kind, "noninteractive"))
            continue
        if name not in arguments:
            if kind in ("image", "item", "items"):
                raise PolicyError("INVALID_ARGUMENT", "argument %r is required" % name, {"argument": name})
            continue
        plan.append((name, kind, _convert(arg, kind, arguments[name], session_id)))
    return plan

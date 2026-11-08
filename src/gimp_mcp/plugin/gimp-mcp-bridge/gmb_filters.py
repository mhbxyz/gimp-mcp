"""GEGL filter catalog: which operations may be applied, and parameter validation (#47).

Standard library only, no GIMP. gmb_ops.py describes each operation's parameters
in a neutral form (introspected from GIMP) and asks this module what is allowed:

    {"name": "size-x", "kind": "integer", "min": 1, "max": 2147483647, "default": 16}

kinds: number, integer, boolean, choice (string nicks), enum (GIMP enum nicks),
color ("#rrggbb[aa]"), string, unsupported (any other type: listed, never settable).
"""

# Operations that execute scripts or read files given as parameters.
DENIED = {
    "gegl:gluas": "denied: runs Lua scripts and can read files",
    "gegl:ctx-script": "denied: runs a ctx drawing script",
    "gegl:styles": "denied: loads image files given as parameters",
}

# Operations whose result depends on a second image (GEGL aux pad), which GIMP 3.2's
# plug-in API only sets from a drawable (DrawableFilter.set_aux_input) — not exposed yet.
AUXILIARY = {
    "gegl:bump-map": "needs an auxiliary input (bump map image)",
    "gegl:displace": "needs an auxiliary input (displacement maps)",
    "gegl:variable-blur": "needs an auxiliary input (blur radius map)",
    # GIMP 3.2 lists these but drops them silently when appended as filters (they have an aux pad);
    # found by tests/e2e/test_effects.py::test_every_supported_operation_applies_with_its_defaults.
    "gegl:gaussian-blur-selective": "needs an auxiliary input (GIMP 3.2 does not keep it as a filter)",
    "gegl:lens-blur": "needs an auxiliary input (GIMP 3.2 does not keep it as a filter)",
    "gegl:negative-darkroom": "needs an auxiliary input (GIMP 3.2 does not keep it as a filter)",
    "gegl:oilify": "needs an auxiliary input (GIMP 3.2 does not keep it as a filter)",
    "gegl:voronoi-diagram": "needs an auxiliary input (GIMP 3.2 does not keep it as a filter)",
    "gimp:set-alpha": "needs an auxiliary input (GIMP 3.2 does not keep it as a filter)",
}

INTERNAL_REASON = "internal GIMP operation (layer modes and compositing, selection helpers)"


class InvalidParameter(ValueError):
    pass


UNTRANSFERABLE_REASON = "has a parameter of a type the bridge cannot set (use a dedicated tool)"


def untransferable_parameters(pspecs):
    """Parameter types libgimp cannot carry between GIMP and a plug-in, from GEGL's own description
    of an operation: [(param spec class name, value type name)]. Instantiating such an operation as a
    filter crashes the plug-in on macOS (docs/gimp-notes.md), so the catalog never does."""
    found = set()
    for spec_class, value_type in pspecs:
        if spec_class == "ParamFormat":
            found.add("GeglParamFormat")
        elif spec_class == "ParamSpecPointer" or value_type == "gpointer":
            found.add("gpointer")
        elif spec_class == "ParamSpecObject" and value_type in ("GeglBuffer", "GeglNode"):
            found.add(value_type)
    return sorted(found)


def operation_status(name, categories, kinds):
    """-> (supported, reason or None) for an operation listed by GIMP."""
    if name in DENIED:
        return False, DENIED[name]
    if name in AUXILIARY:
        return False, AUXILIARY[name]
    lowered = [category.lower() for category in categories if category]
    if name.startswith("gimp:") and (not lowered or "gimp" in lowered):
        return False, INTERNAL_REASON
    if "unsupported" in kinds:
        return False, UNTRANSFERABLE_REASON
    return True, None


def parse_hex_color(value):
    """'#rgb', '#rrggbb' or '#rrggbbaa' -> sRGB floats (r, g, b, a)."""
    if not isinstance(value, str) or not value.startswith("#"):
        raise InvalidParameter("expected a color '#rrggbb' or '#rrggbbaa'")
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if len(digits) == 6:
        digits += "ff"
    if len(digits) != 8:
        raise InvalidParameter("expected a color '#rrggbb' or '#rrggbbaa'")
    try:
        channels = [int(digits[i : i + 2], 16) for i in range(0, 8, 2)]
    except ValueError:
        raise InvalidParameter("expected a color '#rrggbb' or '#rrggbbaa'") from None
    return tuple(c / 255.0 for c in channels)


def _check(spec, value):
    kind = spec["kind"]
    name = spec["name"]
    if kind == "unsupported":
        raise InvalidParameter("parameter %r has type %s, which cannot be set here" % (name, spec.get("type")))
    if kind == "boolean":
        if not isinstance(value, bool):
            raise InvalidParameter("parameter %r must be true or false" % name)
        return value
    if kind in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidParameter("parameter %r must be a %s" % (name, kind))
        if kind == "integer":
            if isinstance(value, float) and not value.is_integer():
                raise InvalidParameter("parameter %r must be an integer" % name)
            value = int(value)
        else:
            value = float(value)
        low, high = spec.get("min"), spec.get("max")
        if (low is not None and value < low) or (high is not None and value > high):
            raise InvalidParameter("parameter %r must be between %s and %s" % (name, low, high))
        return value
    if kind in ("choice", "enum"):
        choices = spec.get("choices") or []
        if value not in choices:
            raise InvalidParameter("parameter %r must be one of %s" % (name, ", ".join(choices)))
        return value
    if kind == "color":
        try:
            return parse_hex_color(value)
        except InvalidParameter as error:
            raise InvalidParameter("parameter %r: %s" % (name, error)) from None
    if kind == "string":
        if not isinstance(value, str) or len(value) > 4096:
            raise InvalidParameter("parameter %r must be a string (at most 4096 characters)" % name)
        return value
    raise InvalidParameter("parameter %r has an unknown kind %r" % (name, kind))


def validate(specs, values):
    """Check every given value against its spec; returns normalized values. Raises InvalidParameter."""
    if not isinstance(values, dict):
        raise InvalidParameter("parameters must be an object")
    by_name = {spec["name"]: spec for spec in specs}
    result = {}
    for name, value in values.items():
        if name not in by_name:
            raise InvalidParameter("unknown parameter %r (valid: %s)" % (name, ", ".join(sorted(by_name)) or "none"))
        result[name] = _check(by_name[name], value)
    return result


def reorder_plan(stack, moved, position):
    """Move ``moved`` to ``position`` (0 = top) in ``stack`` (top first).

    GIMP 3.2 can only append filters on top, so every filter from the top down
    to the lowest slot that changes is removed and appended again, bottom-up.
    Returns (filters to append in order, final stack).
    """
    if moved not in stack:
        raise ValueError("%r is not in the stack" % (moved,))
    if not 0 <= position < len(stack):
        raise ValueError("position must be between 0 and %d" % (len(stack) - 1))
    final = [entry for entry in stack if entry != moved]
    final.insert(position, moved)
    changed = [index for index, (old, new) in enumerate(zip(stack, final, strict=True)) if old != new]
    if not changed:
        return [], final
    lowest = max(changed)
    return list(reversed(final[: lowest + 1])), final

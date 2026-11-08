"""Color adjustments (#48): documented ranges -> GIMP operations and properties. Stdlib only, no GIMP.

``plan(adjustment, settings)`` returns ``(operation, properties)``: the GEGL/GIMP
operation to use as a filter (editable, or merged for destructive mode) and its
properties in GIMP's units. Enum values are ``("enum", nick)``, colors ``("color", (r, g, b, a))``
(sRGB 0-1). ``operation`` is
None for adjustments GIMP only offers destructively (equalize, white balance).
"""

import colorsys


def _range(settings, key, default, low, high):
    value = settings.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError("%s must be between %s and %s" % (key, low, high))
    return value


def _levels(s):
    low = _range(s, "input_low", 0, 0, 255)
    high = _range(s, "input_high", 255, 0, 255)
    if low >= high:
        raise ValueError("input_low must be lower than input_high")
    return "gimp:levels", {
        "trc": ("enum", "non-linear"),
        "channel": ("enum", s.get("channel", "value")),
        "low-input": low / 255.0,
        "high-input": high / 255.0,
        "gamma": float(_range(s, "gamma", 1.0, 0.1, 10.0)),
        "low-output": _range(s, "output_low", 0, 0, 255) / 255.0,
        "high-output": _range(s, "output_high", 255, 0, 255) / 255.0,
    }


def _color_balance(s):
    return "gimp:color-balance", {
        "range": ("enum", s.get("range", "midtones")),
        "cyan-red": _range(s, "cyan_red", 0, -100, 100) / 100.0,
        "magenta-green": _range(s, "magenta_green", 0, -100, 100) / 100.0,
        "yellow-blue": _range(s, "yellow_blue", 0, -100, 100) / 100.0,
        "preserve-luminosity": bool(s.get("preserve_luminosity", True)),
    }


def _colorize(s):
    hue = _range(s, "hue", 180, 0, 360) / 360.0
    saturation = _range(s, "saturation", 50, 0, 100) / 100.0
    r, g, b = colorsys.hls_to_rgb(hue % 1.0, 0.5, saturation)
    return "gimp:colorize", {
        "hue": hue,
        "saturation": saturation,
        "lightness": _range(s, "lightness", 0, -100, 100) / 100.0,
        "color": ("color", (round(r, 6), round(g, 6), round(b, 6), 1.0)),
    }


def _threshold(s):
    low = _range(s, "low", 128, 0, 255)
    high = _range(s, "high", 255, 0, 255)
    if low > high:
        raise ValueError("low must not exceed high")
    return "gimp:threshold", {"channel": ("enum", s.get("channel", "value")), "low": low / 255.0, "high": high / 255.0}


def _posterize(s):
    return "gimp:posterize", {"levels": int(_range(s, "levels", 3, 2, 256))}


def _desaturate(s):
    return "gimp:desaturate", {"mode": ("enum", s.get("mode", "luminance"))}


def _invert(s):
    return ("gegl:invert-linear" if s.get("linear") else "gegl:invert-gamma"), {}


def _exposure(s):
    return "gegl:exposure", {
        "exposure": float(_range(s, "exposure", 0.0, -10.0, 10.0)),
        "black-level": float(_range(s, "black_level", 0.0, -0.1, 0.1)),
    }


SHADOWS_HIGHLIGHTS = {
    # our name: (GEGL property, low, high)
    "shadows": ("shadows", -100, 100),
    "highlights": ("highlights", -100, 100),
    "whitepoint": ("whitepoint", -10, 10),
    "radius": ("radius", 0.1, 1500),
    "compress": ("compress", 0, 100),
    "shadows_color_correction": ("shadows-ccorrect", 0, 100),
    "highlights_color_correction": ("highlights-ccorrect", 0, 100),
}


def _shadows_highlights(s):
    props = {}
    for key, (prop, low, high) in SHADOWS_HIGHLIGHTS.items():
        if key in s:
            props[prop] = float(_range(s, key, 0, low, high))
    return "gegl:shadows-highlights", props


def _stretch(s):
    return "gegl:stretch-contrast", {"keep-colors": bool(s.get("keep_colors", False))}


PLANS = {
    "levels": _levels,
    "color-balance": _color_balance,
    "colorize": _colorize,
    "threshold": _threshold,
    "posterize": _posterize,
    "desaturate": _desaturate,
    "invert": _invert,
    "exposure": _exposure,
    "shadows-highlights": _shadows_highlights,
    "stretch-contrast": _stretch,
    "equalize": lambda s: (None, {}),
    "white-balance": lambda s: (None, {}),
}


def plan(adjustment, settings):
    if adjustment not in PLANS:
        raise ValueError("unknown adjustment %r" % adjustment)
    return PLANS[adjustment](settings)


def curve_points(points):
    """[[x, y], ...] in 0-255, x strictly increasing -> flat list of 0-1 floats (gimp-drawable-curves-spline)."""
    if len(points) < 2:
        raise ValueError("a curve needs at least 2 points")
    flat = []
    previous = -1
    for x, y in points:
        if not (0 <= x <= 255 and 0 <= y <= 255):
            raise ValueError("curve points must be between 0 and 255")
        if x <= previous:
            raise ValueError("curve points must have strictly increasing x")
        previous = x
        flat += [x / 255.0, y / 255.0]
    return flat


def curve_samples(samples):
    """Output values (0-255) for evenly spaced inputs -> 0-1 floats (gimp-drawable-curves-explicit)."""
    if len(samples) < 2:
        raise ValueError("a curve needs at least 2 samples")
    if any(not 0 <= v <= 255 for v in samples):
        raise ValueError("curve samples must be between 0 and 255")
    if len(samples) >= 256:
        return [v / 255.0 for v in samples]
    # gimp-drawable-curves-explicit needs at least 256 values: interpolate linearly
    last = len(samples) - 1
    resampled = []
    for i in range(256):
        position = i * last / 255.0
        low = int(position)
        high = min(low + 1, last)
        fraction = position - low
        resampled.append((samples[low] * (1 - fraction) + samples[high] * fraction) / 255.0)
    return resampled

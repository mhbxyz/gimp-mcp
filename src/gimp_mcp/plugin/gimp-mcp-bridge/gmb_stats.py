"""Pixel statistics for the analysis operations (#46). Standard library only, no GIMP.

Inputs are 8-bit RGBA bytes (babl "R'G'B'A u8": sRGB-encoded values 0-255, alpha
not premultiplied), row by row. GIMP reads the pixels (gmb_ops.py); everything
here is plain arithmetic, unit tested without GIMP.
"""

import itertools
import math
import struct
import zlib
from collections import Counter

CHANNEL_OFFSETS = {"red": 0, "green": 1, "blue": 2, "alpha": 3}
# selection value >= 128 (half selected or more) counts as selected
_HALF = bytes(1 if value >= 128 else 0 for value in range(256))


def _values(data, channel, luminance):
    if channel == "luminance":
        if luminance is None:
            raise ValueError("luminance values are required for the luminance channel")
        return luminance
    return data[CHANNEL_OFFSETS[channel] :: 4]


def _summary(histogram, total, percentiles, bins):
    mean = sum(value * count for value, count in enumerate(histogram)) / total
    variance = sum(count * (value - mean) ** 2 for value, count in enumerate(histogram)) / total
    ordered = _Ranks(histogram)
    if total % 2:
        median = float(ordered.at(total // 2 + 1))
    else:
        median = (ordered.at(total // 2) + ordered.at(total // 2 + 1)) / 2
    result = {
        "pixel_count": total,
        "mean": round(mean, 4),
        "median": median,
        "std_dev": round(math.sqrt(variance), 4),
        "min": ordered.at(1),
        "max": ordered.at(total),
        "percentiles": {"%g" % p: ordered.at(min(total, max(1, math.ceil(p / 100.0 * total)))) for p in percentiles},
    }
    if bins:
        grouped = [0] * bins
        for value, count in enumerate(histogram):
            grouped[value * bins // 256] += count
        result["histogram"] = grouped
    return result


class _Ranks:
    """Value at a 1-based rank of the sorted values, from a 256-bin histogram."""

    def __init__(self, histogram):
        self.cumulative = list(itertools.accumulate(histogram))

    def at(self, rank):
        for value, upto in enumerate(self.cumulative):
            if upto >= rank:
                return value
        return 255


def channel_stats(data, channels, percentiles=(5, 25, 50, 75, 95), bins=16, mask=None, luminance=None):
    """Statistics per channel. ``mask``: one selection byte per pixel; pixels below 128 are left out."""
    selector = mask.translate(_HALF) if mask is not None else None
    result = {}
    for channel in channels:
        values = _values(data, channel, luminance)
        if selector is not None:
            values = bytes(itertools.compress(values, selector))
        total = len(values)
        if not total:
            result[channel] = {"pixel_count": 0}
            continue
        counts = Counter(values)
        histogram = [counts.get(value, 0) for value in range(256)]
        result[channel] = _summary(histogram, total, percentiles, bins)
    return result


def _changed_mask(a, b, width, height, threshold):
    """Yield (row, [changed x...], row_sum, row_max) for rows that differ."""
    stride = width * 4
    for y in range(height):
        row_a = a[y * stride : (y + 1) * stride]
        row_b = b[y * stride : (y + 1) * stride]
        if row_a == row_b:
            continue
        changed = []
        total = 0
        peak = 0
        for x in range(width):
            o = x * 4
            d0 = abs(row_a[o] - row_b[o])
            d1 = abs(row_a[o + 1] - row_b[o + 1])
            d2 = abs(row_a[o + 2] - row_b[o + 2])
            d3 = abs(row_a[o + 3] - row_b[o + 3])
            pixel = max(d0, d1, d2, d3)
            if pixel:
                total += d0 + d1 + d2 + d3
                if pixel > peak:
                    peak = pixel
                if pixel > threshold:
                    changed.append(x)
        yield y, changed, total, peak


def compare(a, b, width, height, threshold=0):
    """Pixels whose largest channel difference exceeds ``threshold`` (0-255) count as changed."""
    if len(a) != len(b) or len(a) != width * height * 4:
        raise ValueError("both buffers must hold width x height RGBA pixels")
    changed = 0
    total = 0
    peak = 0
    x0 = y0 = None
    x1 = y1 = -1
    for y, xs, row_total, row_peak in _changed_mask(a, b, width, height, threshold):
        total += row_total
        peak = max(peak, row_peak)
        if xs:
            changed += len(xs)
            y0 = y if y0 is None else y0
            y1 = y
            x0 = xs[0] if x0 is None else min(x0, xs[0])
            x1 = max(x1, xs[-1])
    pixels = width * height
    return {
        "width": width,
        "height": height,
        "changed_pixels": changed,
        "changed_fraction": round(changed / pixels, 6) if pixels else 0.0,
        "bounds": None if y0 is None else {"x": x0, "y": y0, "width": x1 - x0 + 1, "height": y1 - y0 + 1},
        "mean_difference": total / (pixels * 4) if pixels else 0.0,
        "max_difference": peak,
        "threshold": threshold,
    }


CHANGED_COLOR = (255, 0, 64)


def difference_png(a, b, width, height, threshold=0, max_size=1024):
    """RGB PNG: changed pixels in CHANGED_COLOR over a dimmed grayscale of ``b``.

    Larger than ``max_size``: downscaled by blocks; a block is marked changed if any of its pixels is.
    """
    step = max(1, math.ceil(max(width, height) / max_size))
    out_w, out_h = math.ceil(width / step), math.ceil(height / step)
    image = bytearray(out_w * out_h * 3)
    for oy in range(out_h):
        y = oy * step
        for ox in range(out_w):
            o = (y * width + ox * step) * 4
            gray = 24 + (b[o] + b[o + 1] + b[o + 2]) // 9
            image[(oy * out_w + ox) * 3 : (oy * out_w + ox) * 3 + 3] = bytes((gray, gray, gray))
    for y, xs, _total, _peak in _changed_mask(a, b, width, height, threshold):
        oy = y // step
        for x in xs:
            p = (oy * out_w + x // step) * 3
            image[p : p + 3] = bytes(CHANGED_COLOR)
    return encode_png_rgb(bytes(image), out_w, out_h), out_w, out_h


def encode_png_rgb(rgb, width, height):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    stride = width * 3
    raw = b"".join(b"\0" + rgb[y * stride : (y + 1) * stride] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def dominant_colors(data, count=5):
    """Most common colors (pixels with alpha >= 128), grouped in 16 levels per channel.

    Each color is the average of its group; ``fraction`` is its share of the opaque pixels.
    """
    groups = {}
    opaque = 0
    for o in range(0, len(data), 4):
        if data[o + 3] < 128:
            continue
        opaque += 1
        r, g, b = data[o], data[o + 1], data[o + 2]
        key = (r >> 4, g >> 4, b >> 4)
        group = groups.get(key)
        if group is None:
            groups[key] = [1, r, g, b]
        else:
            group[0] += 1
            group[1] += r
            group[2] += g
            group[3] += b
    ranked = sorted(groups.values(), key=lambda group: -group[0])[:count]
    colors = []
    for n, r, g, b in ranked:
        rgb = (round(r / n), round(g / n), round(b / n))
        colors.append({"hex": "#%02x%02x%02x" % rgb, "rgb": list(rgb), "fraction": round(n / opaque, 4)})
    return colors

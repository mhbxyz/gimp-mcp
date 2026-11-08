"""Resources (#52): previews and palette files. Standard library only, no GIMP."""

import struct
import zlib


def encode_png(pixels, width, height, channels):
    """8-bit PNG from row-major pixels with 3 (RGB) or 4 (RGBA) channels."""

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    color_type = {3: 2, 4: 6}[channels]
    stride = width * channels
    raw = b"".join(b"\0" + pixels[y * stride : (y + 1) * stride] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _byte(value):
    return max(0, min(255, round(value * 255)))


def gradient_strip(samples, height=32):
    """PNG strip: one column per (r, g, b, a) sample (0-1 floats), ``height`` rows."""
    row = bytes(_byte(v) for sample in samples for v in sample)
    return encode_png(row * height, len(samples), height, 4)


def palette_swatches(colors, columns, cell=16):
    """PNG grid of (r, g, b) 0-255 colors, ``columns`` per row (0 = GIMP's default of 16); empty cells white."""
    columns = columns or 16
    columns = max(1, min(columns, len(colors) or 1))
    rows = max(1, -(-len(colors) // columns))
    width, height = columns * cell, rows * cell
    pixels = bytearray(b"\xff" * (width * height * 3))
    for index, rgb in enumerate(colors):
        cx, cy = (index % columns) * cell, (index // columns) * cell
        for y in range(cy, cy + cell):
            start = (y * width + cx) * 3
            pixels[start : start + cell * 3] = bytes(rgb) * cell
    return encode_png(bytes(pixels), width, height, 3)


def write_gpl(name, columns, entries):
    """GIMP palette file (.gpl) text: entries are (name, (r, g, b)) with 0-255 values."""
    lines = ["GIMP Palette", "Name: %s" % name, "Columns: %d" % columns, "#"]
    for entry_name, (r, g, b) in entries:
        lines.append("%3d %3d %3d\t%s" % (r, g, b, entry_name or "Untitled"))
    return "\n".join(lines) + "\n"

"""A 64x64 linear DNG with four known quadrants (#129): red, green, blue, mid gray; written with the
standard library (LinearRaw, 3 x 16-bit samples, DNG 1.4, ColorMatrix1 = XYZ to linear sRGB, D65,
AsShotNeutral 1,1,1, white level 65535). darktable-cli 5.6.2 decodes it headless (#86)."""

from __future__ import annotations

import struct
from pathlib import Path

W = H = 64
QUAD = [(60000, 4000, 4000), (4000, 60000, 4000), (4000, 4000, 60000), (30000, 30000, 30000)]


def write_dng(path: Path) -> None:

    pixels = bytearray()
    for y in range(H):
        for x in range(W):
            pixels += struct.pack("<HHH", *QUAD[(y >= H // 2) * 2 + (x >= W // 2)])

    def rational(values, signed=False):
        return b"".join(struct.pack("<ii" if signed else "<II", round(v * 10000), 10000) for v in values)

    # XYZ (D65) -> linear sRGB camera space
    xyz_to_srgb = [3.2406, -1.5372, -0.4986, -0.9689, 1.8758, 0.0415, 0.0557, -0.2040, 1.0570]
    make, model = b"gimp-mcp\x00", b"gimp-mcp linear DNG\x00"
    entries = [  # tag, type, count, value bytes
        (254, 4, 1, struct.pack("<I", 0)),
        (256, 3, 1, struct.pack("<H", W)),
        (257, 3, 1, struct.pack("<H", H)),
        (258, 3, 3, struct.pack("<HHH", 16, 16, 16)),
        (259, 3, 1, struct.pack("<H", 1)),
        (262, 3, 1, struct.pack("<H", 34892)),
        (271, 2, len(make), make),
        (272, 2, len(model), model),
        (273, 4, 1, None),  # strip offset, filled below
        (274, 3, 1, struct.pack("<H", 1)),
        (277, 3, 1, struct.pack("<H", 3)),
        (278, 3, 1, struct.pack("<H", H)),
        (279, 4, 1, struct.pack("<I", len(pixels))),
        (284, 3, 1, struct.pack("<H", 1)),
        (50706, 1, 4, bytes([1, 4, 0, 0])),
        (50707, 1, 4, bytes([1, 1, 0, 0])),
        (50708, 2, len(model), model),
        (50714, 4, 1, struct.pack("<I", 0)),
        (50717, 4, 1, struct.pack("<I", 65535)),
        (50721, 10, 9, rational(xyz_to_srgb, signed=True)),
        (50728, 5, 3, rational([1, 1, 1])),
        (50778, 3, 1, struct.pack("<H", 21)),
    ]
    header = 8
    ifd_size = 2 + 12 * len(entries) + 4
    data_offset = header + ifd_size
    extra = bytearray()
    ifd = struct.pack("<H", len(entries))
    strip_offset_pos = None
    for tag, typ, count, value in entries:
        if value is None:
            strip_offset_pos = len(ifd) + 8
            value = b"\0\0\0\0"
        if len(value) <= 4:
            ifd += struct.pack("<HHI", tag, typ, count) + value.ljust(4, b"\0")
        else:
            ifd += struct.pack("<HHII", tag, typ, count, data_offset + len(extra))
            extra += value + (b"\0" if len(value) % 2 else b"")
    ifd += struct.pack("<I", 0)
    strip = data_offset + len(extra)
    ifd = bytearray(ifd)
    assert strip_offset_pos is not None
    ifd[strip_offset_pos : strip_offset_pos + 4] = struct.pack("<I", strip)
    path.write_bytes(b"II*\x00" + struct.pack("<I", 8) + bytes(ifd) + bytes(extra) + bytes(pixels))

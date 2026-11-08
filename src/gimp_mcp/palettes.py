"""Palette files from other applications, read without GIMP (#81).

GIMP 3.2 reads Adobe, RIFF and Paint Shop Pro palettes only in its Palettes dialog; plug-ins reach the
`.gpl` loader alone. These readers turn such files into colors that the bridge writes as a `.gpl`.
Conventions follow GIMP's own loader (`app/core/gimppalette-load.c`) and the Adobe file format
specification. The formats carry no color space: colors are taken as sRGB, as GIMP does. CMYK and
Lab colors are refused rather than converted without a profile.
"""

from __future__ import annotations

import colorsys
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import GimpMcpError

MAX_ENTRIES = 10000


@dataclass(frozen=True)
class PaletteEntry:
    name: str
    rgb: tuple[int, int, int]


@dataclass(frozen=True)
class PaletteFile:
    name: str
    entries: tuple[PaletteEntry, ...]


class _Damaged(Exception):
    pass


def _byte(value: float) -> int:
    return max(0, min(255, round(value * 255)))


def _unpack(fmt: str, data: bytes, offset: int) -> tuple:
    size = struct.calcsize(fmt)
    if offset + size > len(data):
        raise _Damaged("the file ends too early")
    return struct.unpack_from(fmt, data, offset)


def _act(data: bytes) -> list[PaletteEntry]:
    """Adobe Color Table: 256 RGB triplets, then (772-byte files) the color count and a transparent index."""
    if len(data) not in (768, 772):
        raise _Damaged("an Adobe Color Table is 768 or 772 bytes long")
    count = 256
    if len(data) == 772:
        count = _unpack(">H", data, 768)[0]
        if not 0 < count <= 256:
            raise _Damaged(f"invalid color count {count}")
    return [PaletteEntry("", tuple(data[i * 3 : i * 3 + 3])) for i in range(count)]  # type: ignore[arg-type]


def _aco_color(space: int, w: int, x: int, y: int) -> tuple[int, int, int] | str:
    if space == 0:
        return (_byte(w / 65535), _byte(x / 65535), _byte(y / 65535))
    if space == 1:  # HSB, each a fraction of 65536 (as GIMP's loader)
        r, g, b = colorsys.hsv_to_rgb(w / 65536, x / 65536, y / 65536)
        return (_byte(r), _byte(g), _byte(b))
    if space == 8:  # grayscale: 0..10000 is ink coverage, 0 = white
        gray = _byte(1 - min(w, 10000) / 10000)
        return (gray, gray, gray)
    return {2: "CMYK", 7: "Lab", 9: "CMYK"}.get(space, f"color space {space}")


def _aco(data: bytes) -> list[PaletteEntry]:
    """Photoshop swatches: a version 1 section (colors) optionally followed by version 2 (colors and names)."""
    version, count = _unpack(">HH", data, 0)
    if version != 1:
        raise _Damaged("not a Photoshop swatches file")
    offset = 4 + count * 10
    named = len(data) >= offset + 4 and _unpack(">H", data, offset)[0] == 2
    if named:
        count = _unpack(">H", data, offset + 2)[0]
        offset += 4
    else:
        offset = 4
    entries, refused = [], set()
    for _ in range(count):
        space, w, x, y, _z = _unpack(">HHHHH", data, offset)
        offset += 10
        name = ""
        if named:
            _zero, length = _unpack(">HH", data, offset)
            offset += 4
            if offset + length * 2 > len(data):
                raise _Damaged("the file ends too early")
            name = data[offset : offset + length * 2].decode("utf-16-be", errors="replace").rstrip("\x00")
            offset += length * 2
        color = _aco_color(space, w, x, y)
        if isinstance(color, str):
            refused.add(color)
        else:
            entries.append(PaletteEntry(name, color))
    _refuse_models(refused)
    return entries


def _riff(data: bytes) -> list[PaletteEntry]:
    """Microsoft RIFF palette: a `PAL ` form with a `data` chunk (version, count, R G B flags entries)."""
    if data[:4] != b"RIFF" or data[8:12] != b"PAL ":
        raise _Damaged("not a RIFF palette")
    offset = 12
    while offset + 8 <= len(data):
        chunk, size = data[offset : offset + 4], _unpack("<I", data, offset + 4)[0]
        if chunk == b"data":
            _version, count = _unpack("<HH", data, offset + 8)
            start = offset + 12
            if start + count * 4 > len(data):
                raise _Damaged("the file ends too early")
            return [PaletteEntry("", tuple(data[start + i * 4 : start + i * 4 + 3])) for i in range(count)]  # type: ignore[arg-type]
        offset += 8 + size + (size & 1)
    raise _Damaged("no palette data")


def _jasc(data: bytes) -> list[PaletteEntry]:
    """Paint Shop Pro (JASC) palette: text header, color count, then one `R G B` line per color."""
    lines = data.decode("ascii", errors="strict").split()
    if lines[:1] != ["JASC-PAL"] or len(lines) < 3:
        raise _Damaged("not a Paint Shop Pro palette")
    count = int(lines[2])
    values = [int(v) for v in lines[3 : 3 + count * 3]]
    if len(values) != count * 3 or any(not 0 <= v <= 255 for v in values):
        raise _Damaged("invalid colors")
    return [PaletteEntry("", (values[i], values[i + 1], values[i + 2])) for i in range(0, len(values), 3)]


def _pal(data: bytes) -> list[PaletteEntry]:
    return _riff(data) if data[:4] == b"RIFF" else _jasc(data)


def _ase(data: bytes) -> list[PaletteEntry]:
    """Adobe Swatch Exchange: blocks of colors (name, model, float values) inside optional groups."""
    if data[:4] != b"ASEF":
        raise _Damaged("not an Adobe Swatch Exchange file")
    _major, _minor, blocks = _unpack(">HHI", data, 4)
    offset, entries, refused = 12, [], set()
    for _ in range(blocks):
        kind, size = _unpack(">HI", data, offset)
        body = offset + 6
        if body + size > len(data):
            raise _Damaged("the file ends too early")
        offset = body + size
        if kind != 0x0001:  # group start / end
            continue
        length = _unpack(">H", data, body)[0]
        name = data[body + 2 : body + 2 + length * 2].decode("utf-16-be", errors="replace").rstrip("\x00")
        cursor = body + 2 + length * 2
        model = data[cursor : cursor + 4].decode("ascii", errors="replace").strip()
        cursor += 4
        if model == "RGB":
            r, g, b = _unpack(">fff", data, cursor)
            entries.append(PaletteEntry(name, (_byte(r), _byte(g), _byte(b))))
        elif model.upper() == "GRAY":
            gray = _byte(_unpack(">f", data, cursor)[0])
            entries.append(PaletteEntry(name, (gray, gray, gray)))
        else:
            refused.add(model.upper() if model.upper() == "CMYK" else "Lab" if model.upper() == "LAB" else model)
    _refuse_models(refused)
    return entries


def _refuse_models(models: set[str]) -> None:
    if models:
        listed = ", ".join(sorted(models))
        raise GimpMcpError(
            "UNSUPPORTED_FORMAT",
            f"the palette has {listed} colors; only RGB, HSB and grayscale colors are imported",
            hint="Convert the palette to RGB in the application that made it, or in GIMP's Palettes dialog.",
            details={"color_models": sorted(models)},
        )


READERS: dict[str, Callable[[bytes], list[PaletteEntry]]] = {
    ".act": _act,
    ".aco": _aco,
    ".ase": _ase,
    ".pal": _pal,
}


def read_palette(path: Path) -> PaletteFile:
    """Colors of a palette file in a format listed in READERS (the palette is named after the file)."""
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise GimpMcpError(
            "UNSUPPORTED_FORMAT",
            f"{path.name}: palettes are imported from {', '.join(['.gpl', *READERS])} files",
        )
    data = path.read_bytes()
    try:
        entries = reader(data)
    except (_Damaged, UnicodeDecodeError, ValueError, IndexError) as error:
        raise GimpMcpError("UNSUPPORTED_FORMAT", f"{path.name} is not a readable palette: {error}") from None
    if not entries:
        raise GimpMcpError("UNSUPPORTED_FORMAT", f"{path.name} has no colors")
    if len(entries) > MAX_ENTRIES:
        raise GimpMcpError("UNSUPPORTED_FORMAT", f"{path.name} has more than {MAX_ENTRIES} colors")
    return PaletteFile(path.stem, tuple(entries))

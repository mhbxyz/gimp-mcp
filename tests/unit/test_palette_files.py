"""Palette files written by other tools (#81), read without GIMP.

Fixtures and their sources: tests/fixtures/palettes/SOURCES.md. Expected colors come from
independent files of the same palettes (Lospec .gpl exports) or from published values.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from gimp_mcp.errors import GimpMcpError
from gimp_mcp.palettes import read_palette

FIXTURES = Path(__file__).parent.parent / "fixtures" / "palettes"


def gpl_colors(path: Path) -> list[tuple[int, int, int]]:
    """The colors of a GIMP palette exported by Lospec (independent of the code under test)."""
    colors = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
            colors.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return colors


def colors(palette) -> list[tuple[int, int, int]]:
    return [entry.rgb for entry in palette.entries]


def test_one_palette_saved_as_aco_act_and_riff_pal_reads_the_same_colors():
    aco = read_palette(FIXTURES / "arne-v20-16.aco")
    act = read_palette(FIXTURES / "arne-v20-16.act")
    riff = read_palette(FIXTURES / "arne-v20-16.pal")
    assert colors(aco) == colors(act) == colors(riff)
    assert sorted(colors(aco)) == sorted(gpl_colors(FIXTURES / "arne16.gpl"))  # Lospec's copy of Arne's 16
    assert aco.name == "arne-v20-16"


def test_aco_version_2_keeps_color_names():
    material = read_palette(FIXTURES / "Material_Palette.aco")
    assert len(material.entries) == 256
    first = material.entries[0]
    assert first.name == "Red 500 - Primary" and first.rgb == (0xF4, 0x43, 0x36)  # Material Design red 500


def test_ase_rgb_colors_match_the_same_palette_exported_as_gpl():
    pico = read_palette(FIXTURES / "pico-8.ase")
    assert colors(pico) == gpl_colors(FIXTURES / "pico-8.gpl")


def test_paint_shop_pro_pal_matches_the_same_palette_exported_as_gpl():
    pico = read_palette(FIXTURES / "pico-8.pal")
    assert colors(pico) == gpl_colors(FIXTURES / "pico-8.gpl")


def aco_v1(*colors: tuple[int, int, int, int]) -> bytes:
    return struct.pack(">HH", 1, len(colors)) + b"".join(struct.pack(">HHHHH", *c, 0) for c in colors)


def test_aco_hsb_and_grayscale_follow_gimps_loader(tmp_path):
    # GIMP's loader (app/core/gimppalette-load.c): HSB values are fractions of 65536, grayscale 0..10000
    # is ink coverage (0 = white).
    path = tmp_path / "spaces.aco"
    path.write_bytes(aco_v1((1, 0, 65535, 65535), (1, 21845, 65535, 65535), (8, 0, 0, 0), (8, 10000, 0, 0)))
    assert colors(read_palette(path)) == [(255, 0, 0), (0, 255, 0), (255, 255, 255), (0, 0, 0)]


@pytest.mark.parametrize("fixture", ["palette_simple.ase", "ADG3-CMYK.ase"])
def test_cmyk_and_lab_colors_are_refused_rather_than_guessed(fixture):
    with pytest.raises(GimpMcpError) as refused:
        read_palette(FIXTURES / fixture)
    assert refused.value.code == "UNSUPPORTED_FORMAT" and "CMYK" in refused.value.message


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("short.act", b"\x00" * 100),
        ("junk.aco", b"not a palette at all"),
        ("truncated.aco", aco_v1((0, 0, 0, 0))[:-4]),
        ("wrong.pal", b"RIFF\x10\x00\x00\x00WAVEfmt "),
        ("broken.ase", b"ASEF\x00\x01\x00\x00\x00\x00\x00\x05"),
        ("unknown.xyz", b"whatever"),
    ],
)
def test_damaged_or_unknown_files_are_refused(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(GimpMcpError) as refused:
        read_palette(path)
    assert refused.value.code == "UNSUPPORTED_FORMAT"

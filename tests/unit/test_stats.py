"""Pixel statistics of the bridge (#46): pure functions on RGBA bytes, checked against worked examples."""

from __future__ import annotations

import struct
import zlib

import gmb_stats  # type: ignore[import-not-found]
import pytest


def rgba(*pixels: tuple[int, int, int, int]) -> bytes:
    return bytes(value for pixel in pixels for value in pixel)


def test_channel_statistics_of_a_known_distribution():
    # red values 0, 10, 20, ..., 90 (10 pixels)
    data = rgba(*[(10 * i, 0, 255, 255) for i in range(10)])
    stats = gmb_stats.channel_stats(data, channels=("red", "blue"), percentiles=(10, 50, 90), bins=5)
    red = stats["red"]
    assert red["pixel_count"] == 10
    assert red["mean"] == 45.0
    assert red["min"] == 0 and red["max"] == 90
    assert red["median"] == 45.0  # average of the two middle values 40 and 50
    assert red["std_dev"] == pytest.approx(28.7228, abs=1e-3)  # population std dev of 0..90 step 10
    assert red["percentiles"] == {"10": 0, "50": 40, "90": 80}  # nearest rank
    assert red["histogram"] == [6, 4, 0, 0, 0]  # 5 bins of 51.2 values: 0-51 holds 0..50
    assert stats["blue"]["mean"] == 255.0 and stats["blue"]["std_dev"] == 0.0


def test_luminance_and_alpha_channels():
    data = rgba((255, 255, 255, 0), (0, 0, 0, 255))
    luma = bytes([255, 0])  # supplied by GIMP (babl "Y' u8"), passed through
    stats = gmb_stats.channel_stats(data, channels=("luminance", "alpha"), luminance=luma, percentiles=(), bins=0)
    assert stats["luminance"]["mean"] == 127.5
    assert stats["alpha"]["min"] == 0 and stats["alpha"]["max"] == 255
    assert "histogram" not in stats["alpha"]


def test_mask_keeps_pixels_selected_at_least_half():
    data = rgba((0, 0, 0, 255), (100, 0, 0, 255), (200, 0, 0, 255))
    stats = gmb_stats.channel_stats(data, channels=("red",), mask=bytes([255, 128, 127]), percentiles=(), bins=0)
    assert stats["red"]["pixel_count"] == 2
    assert stats["red"]["mean"] == 50.0


def test_empty_mask_gives_no_pixels():
    stats = gmb_stats.channel_stats(rgba((1, 2, 3, 4)), channels=("red",), mask=b"\0", percentiles=(50,), bins=4)
    assert stats["red"] == {"pixel_count": 0}


def test_identical_buffers_have_no_difference():
    data = rgba(*[(i, i, i, 255) for i in range(12)])
    diff = gmb_stats.compare(data, data, width=4, height=3, threshold=0)
    assert diff["changed_pixels"] == 0 and diff["bounds"] is None
    assert diff["mean_difference"] == 0.0 and diff["max_difference"] == 0


def test_differences_are_counted_and_bounded():
    width, height = 5, 4
    a = bytearray(rgba(*[(10, 10, 10, 255)] * (width * height)))
    b = bytearray(a)
    for x, y, delta in ((1, 1, 40), (3, 2, 2), (2, 2, 200)):
        offset = (y * width + x) * 4
        b[offset] = min(255, a[offset] + delta)
    diff = gmb_stats.compare(bytes(a), bytes(b), width=width, height=height, threshold=0)
    assert diff["changed_pixels"] == 3
    assert diff["bounds"] == {"x": 1, "y": 1, "width": 3, "height": 2}
    assert diff["max_difference"] == 200
    # mean over every channel of every pixel: (40 + 2 + 200) / (20 pixels * 4 channels)
    assert diff["mean_difference"] == pytest.approx(242 / 80)
    tolerant = gmb_stats.compare(bytes(a), bytes(b), width=width, height=height, threshold=2)
    assert tolerant["changed_pixels"] == 2  # a difference of 2 is within the threshold
    assert tolerant["bounds"] == {"x": 1, "y": 1, "width": 2, "height": 2}


def test_difference_mask_png_marks_changed_pixels():
    a = rgba((0, 0, 0, 255), (0, 0, 0, 255))
    b = rgba((0, 0, 0, 255), (9, 0, 0, 255))
    png, _, _ = gmb_stats.difference_png(a, b, width=2, height=1, threshold=0)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (2, 1)
    idat = png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    assert raw[0] == 0  # filter byte
    assert raw[1:4] != raw[4:7]  # unchanged and changed pixels differ
    assert tuple(raw[4:7]) == (255, 0, 64)


def test_dominant_colors_with_fractions():
    pixels = [(250, 10, 10, 255)] * 6 + [(10, 10, 250, 255)] * 3 + [(0, 0, 0, 0)] * 5 + [(12, 250, 12, 255)]
    colors = gmb_stats.dominant_colors(rgba(*pixels), count=2)
    assert [color["hex"] for color in colors] == ["#fa0a0a", "#0a0afa"]
    assert colors[0]["fraction"] == pytest.approx(0.6)  # transparent pixels are ignored
    assert colors[1]["fraction"] == pytest.approx(0.3)


def test_dominant_colors_of_a_transparent_area():
    assert gmb_stats.dominant_colors(rgba((1, 2, 3, 0)), count=3) == []

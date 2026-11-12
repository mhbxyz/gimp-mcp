"""The plug-in reads a JPEG's Exif block and orientation without Exiv2 (#173)."""

from __future__ import annotations

import io

import gmb_formats  # type: ignore[import-not-found]
import pytest
from PIL import Image


def jpeg(orientation: int | None, byte_order: str = "<") -> bytes:
    out = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    exif[0x013B] = "Ada"  # Artist, so the block is never empty
    Image.new("RGB", (8, 4)).save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_the_orientation_is_read_from_the_exif_block(orientation):
    blob = gmb_formats.jpeg_exif(jpeg(orientation))
    assert blob is not None and blob[:2] in (b"II", b"MM")
    assert gmb_formats.exif_orientation(blob) == orientation


def test_no_exif_or_no_orientation_gives_none():
    out = io.BytesIO()
    Image.new("RGB", (8, 4)).save(out, format="JPEG")
    assert gmb_formats.jpeg_exif(out.getvalue()) is None
    assert gmb_formats.exif_orientation(gmb_formats.jpeg_exif(jpeg(None))) is None
    assert gmb_formats.jpeg_exif(b"\x89PNG\r\n\x1a\n") is None
    assert gmb_formats.exif_orientation(b"garbage") is None


def test_a_big_endian_block_is_read_too():
    blob = b"MM\x00\x2a\x00\x00\x00\x08" + b"\x00\x01" + b"\x01\x12\x00\x03\x00\x00\x00\x01\x00\x06\x00\x00" + b"\0" * 4
    assert gmb_formats.exif_orientation(blob) == 6

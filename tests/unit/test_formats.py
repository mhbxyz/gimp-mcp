"""File formats (#58): choosing an export procedure and describing what it keeps, without GIMP."""

from __future__ import annotations

import gmb_formats  # type: ignore[import-not-found]
import pytest

PROCEDURES = {
    "file-png-export": ["png"],
    "file-webp-export": ["webp"],
    "file-heif-av1-export": ["avif"],
    "file-heif-export": ["heif", "heic"],
    "file-tiff-export": ["tif", "tiff"],
    "file-gz-export": ["xcf.gz", "gz"],
}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/x/a.png", "file-png-export"),
        ("/x/a.WEBP", "file-webp-export"),
        ("/x/a.avif", "file-heif-av1-export"),
        ("/x/a.tif", "file-tiff-export"),
        ("/x/a.xcf.gz", "file-gz-export"),
        ("/x/a.unknown", None),
    ],
)
def test_procedure_for_a_path_uses_the_longest_matching_extension(path, expected):
    assert gmb_formats.procedure_for(path, PROCEDURES) == expected


@pytest.mark.parametrize(
    ("procedure", "options", "lossless", "layers"),
    [
        ("file-png-export", {}, True, "flattened"),
        ("file-jpeg-export", {}, False, "flattened"),
        ("file-webp-export", {"lossless": True}, True, "flattened"),
        ("file-webp-export", {"animation": True}, False, "frames"),
        ("file-heif-av1-export", {}, False, "flattened"),
        ("file-heif-av1-export", {"lossless": True}, True, "flattened"),
        ("file-gif-export", {"as-animation": True}, None, "frames"),
        ("file-psd-export", {}, True, "kept"),
        ("file-tiff-export", {}, True, "pages"),
        ("file-pdf-export", {}, None, "flattened"),
        ("file-pdf-export", {"layers-as-pages": True}, None, "pages"),
        ("file-ico-export", {}, True, "sizes"),
        ("file-unknown-export", {}, None, None),
    ],
)
def test_behaviour_reports_lossless_and_layers(procedure, options, lossless, layers):
    behaviour = gmb_formats.behaviour(procedure, options)
    assert behaviour["lossless"] is lossless and behaviour["layers"] == layers


def test_hidden_arguments_are_not_options():
    names = ["run-mode", "image", "file", "options", "quality", "include-exif"]
    assert gmb_formats.option_names(names) == ["quality"]


@pytest.mark.parametrize(
    ("procedure", "extensions"),
    [
        ("file-png-export", ["png"]),
        ("file-jpeg-export", ["jpg", "jpeg", "jpe"]),
        ("file-tiff-load", ["tif", "tiff"]),
        ("file-heif-av1-export", ["avif"]),
        ("file-heif-export", ["heif", "heic"]),
        ("file-jpegxl-export", ["jxl"]),
        ("file-gz-export", ["xcf.gz"]),
        ("python-fu-histogram-export", []),
        ("file-png-load-thumb", []),
    ],
)
def test_extensions_are_derived_from_procedure_names(procedure, extensions):
    assert gmb_formats.extensions_for(procedure) == extensions

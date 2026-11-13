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


def test_procedures_that_read_any_file_are_refused():
    # file-raw-load turns any file (an SSH key) into pixels the agent can read back; the colorxhtml export
    # copies the text of a file named in its options into the page (#122).
    refusal = gmb_formats.refusal
    assert refusal("file-raw-load", "/home/u/.ssh/id_ed25519", {}) is not None
    assert refusal("file-raw-load", "/home/u/scan.data", {}) is None
    assert refusal("file-raw-load", "/home/u/scan.RAW", {}) is None
    assert refusal("file-colorxhtml-export", "/x/a.html", {"source-file": True}) is not None
    assert refusal("file-colorxhtml-export", "/x/a.html", {"source-file": False, "characters": "abc"}) is None
    assert refusal("file-png-export", "/x/a.png", {"source-file": True}) is None


def test_a_layer_file_name_never_leaves_its_directory():
    assert gmb_formats.layer_filename("{index:02d}-{name}", 3, "../../etc/x", "png") == "03-_.._etc_x.png"
    for template in ("../{index}", "/tmp/{index}", "a\\{index}"):
        with pytest.raises(ValueError):
            gmb_formats.layer_filename(template, 0, "x", "png")

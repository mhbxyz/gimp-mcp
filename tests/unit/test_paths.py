"""Path rules for file tools: explicit, absolute, no silent overwrite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gimp_mcp.errors import GimpMcpError
from gimp_mcp.paths import check_input_file, check_output_file, export_format


def code_of(fn, *args, **kwargs) -> str:
    with pytest.raises(GimpMcpError) as excinfo:
        fn(*args, **kwargs)
    return excinfo.value.code


def test_relative_paths_are_refused_because_gimp_and_the_server_have_different_cwds():
    assert code_of(check_input_file, "photo.png") == "INVALID_ARGUMENT"
    assert code_of(check_output_file, "out.png", overwrite=False) == "INVALID_ARGUMENT"


def test_home_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows expands ~ from USERPROFILE
    (tmp_path / "a.png").write_bytes(b"x")
    assert check_input_file("~/a.png") == tmp_path / "a.png"


def test_missing_input_file(tmp_path):
    assert code_of(check_input_file, str(tmp_path / "nope.png")) == "FILE_NOT_FOUND"
    assert code_of(check_input_file, str(tmp_path)) == "INVALID_ARGUMENT"  # a directory


def test_existing_output_requires_explicit_overwrite(tmp_path):
    target = tmp_path / "out.png"
    target.write_bytes(b"old")
    assert code_of(check_output_file, str(target), overwrite=False) == "FILE_EXISTS"
    assert check_output_file(str(target), overwrite=True) == target


def test_output_directory_must_exist_and_be_writable(tmp_path):
    assert code_of(check_output_file, str(tmp_path / "missing" / "a.png"), overwrite=False) == "WRITE_FAILED"
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):  # running as root
            pytest.skip("directory permissions are not enforced for this user")
        assert code_of(check_output_file, str(locked / "a.png"), overwrite=False) == "WRITE_FAILED"
    finally:
        locked.chmod(0o700)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.png", "png"), ("a.PNG", "png"), ("a.jpg", "jpeg"), ("a.jpeg", "jpeg"), ("a.JPG", "jpeg")],
)
def test_export_format_is_inferred_from_the_extension(name, expected):
    assert export_format(Path("/x") / name, None) == expected


def test_unsupported_or_contradictory_export_format():
    assert code_of(export_format, Path("/x/a.gif"), None) == "UNSUPPORTED_FORMAT"
    assert code_of(export_format, Path("/x/a.xcf"), None) == "UNSUPPORTED_FORMAT"
    assert code_of(export_format, Path("/x/a.png"), "jpeg") == "INVALID_ARGUMENT"

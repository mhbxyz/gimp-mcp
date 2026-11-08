"""File paths as each OS reads them (#102): local paths only, names compared as the file system does.

Pure rules are checked for every OS on every runner; behaviour on a real file system is checked against
what that file system does (a probe file decides whether it ignores case or Unicode normalization), so
each runner proves the case it actually has.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

import pytest

from gimp_mcp import platforms
from gimp_mcp.errors import GimpMcpError
from gimp_mcp.paths import check_input_file, check_output_file

from .test_batch_tools import EXPORT, FLIP, Gimp, inputs
from .tool_harness import error_code, tool_client

NFC, NFD = unicodedata.normalize("NFC", "é"), unicodedata.normalize("NFD", "é")


@pytest.mark.parametrize(
    "path",
    [
        r"\\server\share\photo.png",  # UNC: GIMP would connect to another machine
        "//server/share/photo.png",
        r"\\?\C:\photos\photo.png",  # device namespaces
        r"\\.\pipe\gimp-mcp-ana",
        r"\\?\UNC\server\share\photo.png",
        r"C:\photos\CON.png",  # reserved device names, with or without extension
        r"C:\photos\nul",
        r"C:\photos\com1.txt",
        r"C:\photos\LPT9.jpg",
        r"C:\photos\aux .png",
    ],
)
def test_windows_refuses_network_and_device_paths(path):
    assert platforms.path_refusal(path, "windows") is not None


@pytest.mark.parametrize(
    "path", [r"C:\photos\photo.png", r"D:\Program Fïles\console.png", r"C:\photos\com10.png", r"C:\nullable.png"]
)
def test_windows_accepts_local_drive_paths(path):
    assert platforms.path_refusal(path, "windows") is None


@pytest.mark.parametrize("kind", ["linux", "macos"])
def test_unix_paths_are_local(kind):
    # mounted network file systems are local paths for the OS; a leading // is the root directory
    for path in ("/home/ana/photo.png", "//server/share/photo.png", "/mnt/CON.png"):
        assert platforms.path_refusal(path, kind) is None


def test_file_tools_refuse_what_the_os_rule_refuses(monkeypatch):
    monkeypatch.setattr(platforms, "CURRENT", "windows")
    for path in (r"\\server\share\photo.png", r"\\?\C:\photo.png"):
        for check in (check_input_file, lambda p: check_output_file(p, overwrite=True)):
            with pytest.raises(GimpMcpError) as refused:
                check(path)
            assert refused.value.code == "INVALID_ARGUMENT" and "network" in (refused.value.hint or "")


def test_names_are_compared_as_each_os_compares_them():
    same = platforms.same_file_name
    assert same(r"C:\Out\A.PNG", r"c:\out\a.png", "windows")
    assert same("/Users/ana/A.png", "/Users/ana/a.png", "macos")
    assert same(f"/Users/ana/{NFC}.png", f"/Users/ana/{NFD}.png", "macos")
    assert not same("/home/ana/A.png", "/home/ana/a.png", "linux")
    assert not same(f"/home/ana/{NFC}.png", f"/home/ana/{NFD}.png", "linux")
    assert not same("/Users/ana/a.png", "/Users/ana/b.png", "macos")


def message(result) -> str:
    return result.structured_content["error"]["message"]


def ignores(directory: Path, name: str, variant: str) -> bool:
    """Whether this file system opens ``name`` when asked for ``variant`` (the ground truth)."""
    probe = directory / name
    probe.write_bytes(b"probe")
    try:
        return (directory / variant).exists()
    finally:
        probe.unlink()


def case_insensitive(directory: Path) -> bool:
    return ignores(directory, "probe-case.txt", "PROBE-CASE.txt")


async def test_glob_does_not_follow_a_directory_link_out_of_its_directory(tmp_path):
    folder = tmp_path / "in"
    inputs(folder, "a.png")
    inputs(tmp_path / "secret", "x.png")
    os.symlink(tmp_path / "secret", folder / "door", target_is_directory=True)
    async with tool_client(Gimp().ops()) as (client, _):
        plan = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "pattern": "**/*.png", "recipe": [FLIP], "dry_run": True}
        )
    assert [Path(f["file"]).name for f in plan.structured_content["files"]] == ["a.png"]


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows directory links")
async def test_glob_does_not_follow_a_junction_out_of_its_directory(tmp_path):
    import _winapi  # type: ignore[import-not-found]

    folder = tmp_path / "in"
    inputs(folder, "a.png")
    inputs(tmp_path / "secret", "x.png")
    _winapi.CreateJunction(str(tmp_path / "secret"), str(folder / "door"))  # pyright: ignore[reportAttributeAccessIssue]
    assert (folder / "door" / "x.png").exists()  # the junction works
    async with tool_client(Gimp().ops()) as (client, _):
        plan = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "pattern": "**/*.png", "recipe": [FLIP], "dry_run": True}
        )
    assert [Path(f["file"]).name for f in plan.structured_content["files"]] == ["a.png"]


async def test_a_link_to_an_inside_file_spelled_with_another_case_stays_inside(tmp_path):
    folder = tmp_path / "in"
    inputs(folder, "a.png")
    if not case_insensitive(folder):
        pytest.skip("this file system distinguishes case")
    os.symlink(tmp_path / "IN" / "a.png", folder / "alias.png")
    os.symlink(tmp_path / "SECRET" / "x.png", folder / "out.png")
    inputs(tmp_path / "secret", "x.png")
    async with tool_client(Gimp().ops()) as (client, _):
        plan = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "pattern": "*.png", "recipe": [FLIP], "dry_run": True}
        )
    assert [Path(f["file"]).name for f in plan.structured_content["files"]] == ["a.png", "alias.png"]


async def test_an_output_spelled_like_an_input_with_another_case_is_refused(tmp_path):
    a, b = inputs(tmp_path / "in", "a.png", "b.png")
    if not case_insensitive(tmp_path / "in"):
        pytest.skip("this file system distinguishes case")
    gimp = Gimp()
    async with tool_client(gimp.ops()) as (client, bridge):
        onto_input = await client.call_tool(
            "gimp_run_batch",
            {"files": [str(a), str(b)], "recipe": [EXPORT], "output": str(tmp_path / "IN" / "{stem}.PNG"),
             "overwrite": True},
        )  # fmt: skip
        twice = await client.call_tool("gimp_run_batch", {"files": [str(a), str(tmp_path / "in" / "A.png")],
                                                          "recipe": [FLIP]})  # fmt: skip
    assert error_code(onto_input) == "INVALID_ARGUMENT", onto_input.content
    assert "replace an input" in message(onto_input)
    assert error_code(twice) == "INVALID_ARGUMENT" and "twice" in message(twice)
    assert a.read_bytes() == b"x" and [name for name, _ in bridge.calls if name != "session.images"] == []


async def test_an_output_spelled_like_an_input_in_another_unicode_form_is_refused(tmp_path):
    folder = tmp_path / "in"
    (photo,) = inputs(folder, f"caf{NFC}.png")
    if not ignores(folder, f"probe-{NFC}.txt", f"probe-{NFD}.txt"):
        pytest.skip("this file system distinguishes Unicode normalization forms")
    async with tool_client(Gimp().ops()) as (client, bridge):
        result = await client.call_tool(
            "gimp_run_batch",
            {"files": [str(photo)], "recipe": [EXPORT], "output": str(folder / f"caf{NFD}.png"), "overwrite": True},
        )
    assert error_code(result) == "INVALID_ARGUMENT" and "replace an input" in message(result)
    assert photo.read_bytes() == b"x" and [name for name, _ in bridge.calls if name != "session.images"] == []


async def test_two_outputs_that_the_os_names_alike_are_refused(tmp_path):
    a = inputs(tmp_path / "one", "a.png")[0]
    b = inputs(tmp_path / "two", "A.png")[0]
    out = tmp_path / "out"
    out.mkdir()
    args = {"files": [str(a), str(b)], "recipe": [EXPORT], "output": str(out / "{name}")}
    async with tool_client(Gimp().ops()) as (client, _):
        result = await client.call_tool("gimp_run_batch", {**args, "dry_run": True})
    if case_insensitive(out):  # a.png and A.png would be one file: the second export would replace the first
        assert error_code(result) == "INVALID_ARGUMENT" and "same file" in message(result)
    elif platforms.CURRENT == "linux":  # (a case-sensitive macOS volume may still refuse: the safe side)
        assert [f["status"] for f in result.structured_content["files"]] == ["planned", "planned"]

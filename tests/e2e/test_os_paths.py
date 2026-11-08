"""File paths on each OS's real file system with a real GIMP (#102): confinement and same-file checks.

Runs on every CI runner (Linux ext4, macOS APFS, Windows NTFS). What the file system does with case and
Unicode forms is probed first, so each runner proves the case it has; outputs are read back with Pillow.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

import pytest
from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error

FLIP = {"tool": "gimp_flip_image", "arguments": {"image": "{image}", "orientation": "horizontal"}}
EXPORT = {"tool": "gimp_export_image", "arguments": {"image": "{image}", "path": "{output}"}}
NFC, NFD = unicodedata.normalize("NFC", "é"), unicodedata.normalize("NFD", "é")


def two_colors(path: Path) -> Path:
    """40x20: red left half, blue right half."""
    img = Image.new("RGB", (40, 20), (255, 0, 0))
    img.paste((0, 0, 255), (20, 0, 40, 20))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def ignores(directory: Path, name: str, variant: str) -> bool:
    probe = directory / name
    probe.write_bytes(b"probe")
    try:
        return (directory / variant).exists()
    finally:
        probe.unlink()


def directory_link(target: Path, link: Path) -> None:
    """A link to a directory: a junction on Windows (no privilege needed), a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi  # type: ignore[import-not-found]

        _winapi.CreateJunction(str(target), str(link))  # pyright: ignore[reportAttributeAccessIssue]
    else:
        os.symlink(target, link, target_is_directory=True)


async def test_a_batch_glob_never_leaves_its_directory(gimp: HeadlessGimp, tmp_path: Path):
    source, secret, out = tmp_path / "in", tmp_path / "secret", tmp_path / "out"
    two_colors(source / "a.png")
    two_colors(source / "sub" / "b.png")
    two_colors(secret / "x.png")
    out.mkdir()
    directory_link(secret, source / "door")
    assert (source / "door" / "x.png").exists()  # the link works
    secret_bytes = (secret / "x.png").read_bytes()
    async with mcp_client(gimp) as client:
        report = await call(
            client, "gimp_run_batch", directory=str(source), pattern="**/*.png", recipe=[FLIP, EXPORT],
            output=str(out / "{stem}.png"),
        )  # fmt: skip
        escapes = [
            await error(client, "gimp_run_batch", directory=str(source), pattern=pattern, recipe=[FLIP])
            for pattern in ("../secret/*.png", str(secret / "*.png"), "sub/../../secret/*.png")
        ]
    assert [Path(f["file"]).name for f in report["files"]] == ["a.png", "b.png"]
    assert sorted(p.name for p in out.iterdir()) == ["a.png", "b.png"]
    for name in ("a.png", "b.png"):
        with Image.open(out / name) as img:
            assert img.convert("RGB").getpixel((0, 0)) == (0, 0, 255)  # flipped
    assert [e["code"] for e in escapes] == ["INVALID_ARGUMENT"] * 3
    assert (secret / "x.png").read_bytes() == secret_bytes


async def test_an_input_is_never_replaced_through_another_spelling(gimp: HeadlessGimp, tmp_path: Path):
    source = tmp_path / "in"
    photo = two_colors(source / f"caf{NFC}.png")
    before = photo.read_bytes()
    spellings = []
    if ignores(source, "probe.txt", "PROBE.TXT"):
        spellings.append(str(tmp_path / "IN" / f"CAF{NFC}.PNG"))
    if ignores(source, f"probe-{NFC}.txt", f"probe-{NFD}.txt"):
        spellings.append(str(source / f"caf{NFD}.png"))
    if not spellings:
        pytest.skip("this file system distinguishes case and Unicode forms: every spelling is another file")
    async with mcp_client(gimp) as client:
        args = {"files": [str(photo)], "recipe": [FLIP, EXPORT], "overwrite": True}
        refused = [await error(client, "gimp_run_batch", **args, output=spelling) for spelling in spellings]
    assert [(r["code"], "replace an input" in r["message"]) for r in refused] == [("INVALID_ARGUMENT", True)] * len(
        spellings
    )
    assert photo.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32", reason="UNC paths are a Windows notion")
async def test_network_paths_are_refused_on_windows(gimp: HeadlessGimp, tmp_path: Path):
    photo = two_colors(tmp_path / "a.png")
    drive, rest = os.path.splitdrive(str(photo))
    unc = rf"\\localhost\{drive[0]}${rest}"  # the same file through the administrative share
    async with mcp_client(gimp) as client:
        opened = await error(client, "gimp_open_image", path=unc)
        exported = await error(client, "gimp_run_batch", files=[str(photo)], recipe=[EXPORT],
                               output=rf"\\localhost\{drive[0]}${os.path.dirname(rest)}\copy.png")  # fmt: skip
    assert opened["code"] == exported["code"] == "INVALID_ARGUMENT"
    assert not (tmp_path / "copy.png").exists()

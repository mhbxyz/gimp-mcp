from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .gimp_batch import run_batch


@pytest.fixture(scope="module")
def layered_xcf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("files") / "layered.xcf"
    run_batch(f"""
from gi.repository import Gegl
img = Gimp.Image.new(60, 40, Gimp.ImageBaseType.RGB)
layer(img, "Background", 60, 40, alpha=False).fill(Gimp.FillType.WHITE)
g = group(img, "Group")
red = layer(img, "Red", 30, 40, parent=g)
Gimp.context_set_foreground(Gegl.Color.new("red"))
red.edit_fill(Gimp.FillType.FOREGROUND)
save_xcf(img, {str(path)!r})
""")
    return path


async def call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def error(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content["error"]


def tree(image: dict[str, Any]) -> list[Any]:
    def walk(nodes):
        return [(n["name"], n["kind"], walk(n["children"] or [])) for n in nodes]

    return walk(image["layers"])


async def test_create_image_with_explicit_fill(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        created = await call(client, "gimp_create_image", width=64, height=32, fill="#336699")
        image = await call(client, "gimp_inspect_image", image=created["id"])
        out = tmp_path / "created.png"
        await call(client, "gimp_export_image", image=created["id"], path=str(out))
        await call(client, "gimp_close_image", image=created["id"], discard_changes=True)
    assert (image["width"], image["height"], image["base_type"]) == (64, 32, "rgb")
    assert tree(image) == [("Background", "layer", [])]
    assert image["dirty"] is False  # like a new image in GIMP's UI
    with Image.open(out) as png:
        assert png.convert("RGB").getpixel((10, 10)) == (0x33, 0x66, 0x99)


async def test_save_xcf_then_reopen_keeps_the_layers(gimp: HeadlessGimp, layered_xcf: Path, tmp_path: Path):
    copy = tmp_path / "copy.xcf"
    async with mcp_client(gimp) as client:
        opened = await call(client, "gimp_open_image", path=str(layered_xcf))
        original = await call(client, "gimp_inspect_image", image=opened["id"])
        saved = await call(client, "gimp_save_image", image=opened["id"], path=str(copy))
        assert saved["dirty"] is False and saved["xcf_file"] == str(copy)
        await call(client, "gimp_close_image", image=opened["id"])
        reopened = await call(client, "gimp_open_image", path=str(copy))
        again = await call(client, "gimp_inspect_image", image=reopened["id"])
        await call(client, "gimp_close_image", image=reopened["id"])
    assert tree(original) == [("Group", "group", [("Red", "layer", [])]), ("Background", "layer", [])]
    assert tree(again) == tree(original)
    assert again["xcf_file"] == str(copy)


async def test_png_and_jpeg_exports_are_read_back(gimp: HeadlessGimp, layered_xcf: Path, tmp_path: Path):
    png, high, low, prog = tmp_path / "out.png", tmp_path / "high.jpg", tmp_path / "low.jpeg", tmp_path / "p.jpg"
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_open_image", path=str(layered_xcf)))["id"]
        exported = await call(client, "gimp_export_image", image=image, path=str(png))
        await call(client, "gimp_export_image", image=image, path=str(high), jpeg_options={"quality": 95})
        await call(client, "gimp_export_image", image=image, path=str(low), jpeg_options={"quality": 20})
        await call(client, "gimp_export_image", image=image, path=str(prog), jpeg_options={"progressive": True})
        state = await call(client, "gimp_inspect_image", image=image)
        await call(client, "gimp_close_image", image=image)
    assert exported["format"] == "png" and exported["bytes"] == png.stat().st_size
    with Image.open(png) as img:
        assert img.size == (60, 40)
        assert img.convert("RGB").getpixel((5, 5)) == (255, 0, 0)  # visible layers are merged
        assert img.convert("RGB").getpixel((50, 5)) == (255, 255, 255)
    with Image.open(high) as img_high, Image.open(prog) as img_prog:
        assert img_high.format == "JPEG" and img_high.size == (60, 40)
        red = img_high.convert("RGB").getpixel((5, 5))
        assert isinstance(red, tuple) and red[0] > 240 and red[1] < 20 and red[2] < 20
        assert not img_high.info.get("progressive")  # documented default: baseline
        assert img_prog.info.get("progressive")
    assert high.stat().st_size > low.stat().st_size  # quality is applied
    assert state["dirty"] is False  # exporting does not change the project


async def test_jpeg_flattens_transparency_on_an_explicit_background(gimp: HeadlessGimp, tmp_path: Path):
    out = tmp_path / "flat.jpg"
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=16, height=16, fill="transparent"))["id"]
        await call(client, "gimp_export_image", image=image, path=str(out), jpeg_options={"background": "#000000"})
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    with Image.open(out) as img:
        pixel = img.convert("RGB").getpixel((8, 8))
        assert isinstance(pixel, tuple) and max(pixel) < 10


async def test_file_errors_are_explicit(gimp: HeadlessGimp, tmp_path: Path):
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_text("not a png")
    existing = tmp_path / "existing.png"
    existing.write_bytes(b"keep me")
    async with mcp_client(gimp) as client:
        assert (await error(client, "gimp_open_image", path=str(tmp_path / "missing.png")))["code"] == "FILE_NOT_FOUND"
        assert (await error(client, "gimp_open_image", path=str(corrupt)))["code"] == "UNSUPPORTED_FORMAT"
        assert (await error(client, "gimp_open_image", path="relative.png"))["code"] == "INVALID_ARGUMENT"
        image = (await call(client, "gimp_create_image", width=8, height=8))["id"]
        refused = await error(client, "gimp_export_image", image=image, path=str(existing))
        assert refused["code"] == "FILE_EXISTS" and refused["outcome"] == "not_applied"
        assert existing.read_bytes() == b"keep me"
        replaced = await call(client, "gimp_export_image", image=image, path=str(existing), overwrite=True)
        assert replaced["path"] == str(existing)
        gif = await error(client, "gimp_export_image", image=image, path=str(tmp_path / "a.gif"))
        assert gif["code"] == "UNSUPPORTED_FORMAT"
        nodir = await error(client, "gimp_save_image", image=image, path=str(tmp_path / "no" / "dir.xcf"))
        assert nodir["code"] == "WRITE_FAILED"
        not_xcf = await error(client, "gimp_save_image", image=image, path=str(tmp_path / "a.png"))
        assert not_xcf["code"] == "UNSUPPORTED_FORMAT"
        unnamed = await error(client, "gimp_save_image", image=image)
        assert unnamed["code"] == "INVALID_ARGUMENT"  # never saved: a path is required
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert Image.open(existing).size == (8, 8)


async def test_closing_invalidates_the_image_id(gimp: HeadlessGimp, layered_xcf: Path):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=8, height=8))["id"]
        await call(client, "gimp_close_image", image=image)  # clean image: closes
        gone = await error(client, "gimp_inspect_image", image=image)
        assert gone["code"] == "NOT_FOUND"
        opened = (await call(client, "gimp_open_image", path=str(layered_xcf)))["id"]
        await call(client, "gimp_close_image", image=opened)
        status = await call(client, "gimp_status")
    assert status["images"] == []

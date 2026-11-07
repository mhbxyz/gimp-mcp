from __future__ import annotations

import base64
import io
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .gimp_batch import run_batch


@pytest.fixture(scope="module")
def half_red(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """300x150 XCF: left half opaque red, right half transparent."""
    path = tmp_path_factory.mktemp("preview") / "half.xcf"
    run_batch(f"""
from gi.repository import Gegl
img = Gimp.Image.new(300, 150, Gimp.ImageBaseType.RGB)
l = layer(img, "Half", 300, 150)
img.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 150, 150)
Gimp.context_set_foreground(Gegl.Color.new("red"))
l.edit_fill(Gimp.FillType.FOREGROUND)
Gimp.Selection.none(img)
save_xcf(img, {str(path)!r})
""")
    return path


async def test_preview_is_faithful_and_leaves_the_document_untouched(
    gimp_factory: Callable[..., HeadlessGimp], half_red: Path
):
    before = half_red.read_bytes()
    gimp = gimp_factory(open_files=[half_red])
    async with mcp_client(gimp) as client:
        status = (await client.call_tool("gimp_status", {})).structured_content
        assert status is not None
        image_id = status["images"][0]["id"]
        assert status["images"][0]["dirty"] is False
        result = await client.call_tool("gimp_preview", {"image": image_id, "max_size": 100})
        after = (await client.call_tool("gimp_inspect_image", {"image": image_id})).structured_content

    assert not result.is_error, result.content
    info = result.structured_content
    assert info is not None
    assert (info["width"], info["height"]) == (100, 50)  # proportions kept
    block = next(block for block in result.content if block.type == "image")
    preview = Image.open(io.BytesIO(base64.b64decode(block.data))).convert("RGBA")
    assert preview.size == (100, 50)
    assert preview.getpixel((20, 25)) == (255, 0, 0, 255)  # opaque red half
    transparent = preview.getpixel((80, 25))
    assert isinstance(transparent, tuple) and transparent[3] == 0  # transparent half stays transparent
    assert after is not None and after["dirty"] is False  # not modified
    assert half_red.read_bytes() == before  # saved file untouched


async def test_preview_never_upscales(gimp_factory: Callable[..., HeadlessGimp], half_red: Path):
    gimp = gimp_factory(open_files=[half_red])
    async with mcp_client(gimp) as client:
        status = (await client.call_tool("gimp_status", {})).structured_content
        assert status is not None
        result = await client.call_tool("gimp_preview", {"image": status["images"][0]["id"], "max_size": 1024})
    assert result.structured_content is not None
    assert (result.structured_content["width"], result.structured_content["height"]) == (300, 150)


@pytest.fixture(scope="module")
def noisy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """600x400 RGB noise: its PNG is ~700 kB, hard to compress."""
    path = tmp_path_factory.mktemp("preview") / "noisy.xcf"
    run_batch(f"""
img = Gimp.Image.new(600, 400, Gimp.ImageBaseType.RGB)
l = layer(img, "Noise", 600, 400, alpha=False)
f = Gimp.DrawableFilter.new(l, "gegl:noise-rgb", "noise")
cfg = f.get_config()
for channel in ("red", "green", "blue"):
    cfg.set_property(channel, 0.5)
f.update()
l.merge_filter(f)
save_xcf(img, {str(path)!r})
""")
    return path


async def test_preview_respects_the_response_size_limit(gimp_factory: Callable[..., HeadlessGimp], noisy: Path):
    gimp = gimp_factory(open_files=[noisy])
    async with mcp_client(gimp, {"GIMP_MCP_PREVIEW_MAX_BYTES": "100000"}) as client:
        status = (await client.call_tool("gimp_status", {})).structured_content
        assert status is not None
        result = await client.call_tool("gimp_preview", {"image": status["images"][0]["id"], "max_size": 600})
    info = result.structured_content
    assert info is not None
    assert info["downscaled_for_size"] is True
    assert info["bytes"] <= 100000
    assert info["width"] < 600 and info["width"] / info["height"] == pytest.approx(1.5, rel=0.02)


async def test_preview_reflects_a_modification(gimp: HeadlessGimp):
    from .helpers import call, preview, rgba

    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=40, height=20, fill="white"))["id"]
        before = await preview(client, image)
        layer = await call(client, "gimp_create_layer", image=image, name="Mark", width=20, height=20, fill="#00ff00")
        during = await preview(client, image)
        await call(client, "gimp_set_layer_properties", item=layer["id"], visible=False)
        after = await preview(client, image)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert rgba(before, 10, 10) == (255, 255, 255, 255)
    assert rgba(during, 10, 10) == (0, 255, 0, 255)
    assert rgba(during, 30, 10) == (255, 255, 255, 255)
    assert rgba(after, 10, 10) == (255, 255, 255, 255)

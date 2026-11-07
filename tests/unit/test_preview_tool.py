from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from .tool_harness import error_code, iid, tool_client


def png_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (255, 0, 0, 255)).save(buffer, "PNG")
    return buffer.getvalue()


def preview_op(params):
    data = png_bytes(100, 50)
    return {
        "image": params["image"],
        "png_base64": base64.b64encode(data).decode(),
        "width": 100,
        "height": 50,
        "source_width": 3000,
        "source_height": 1500,
        "downscaled_for_size": False,
    }


async def test_preview_returns_an_mcp_image_and_its_dimensions():
    async with tool_client({"image.preview": preview_op}) as (client, bridge):
        result = await client.call_tool("gimp_preview", {"image": iid(1), "max_size": 100})
    assert not result.is_error, result.content
    images = [block for block in result.content if block.type == "image"]
    assert len(images) == 1
    assert images[0].mime_type == "image/png"
    decoded = Image.open(io.BytesIO(base64.b64decode(images[0].data)))
    assert decoded.size == (100, 50)
    data = result.structured_content
    assert data is not None
    assert (data["width"], data["height"], data["source_width"], data["source_height"]) == (
        100,
        50,
        3000,
        1500,
    )
    assert data["scale"] == pytest.approx(100 / 3000)
    assert "png_base64" not in data  # the pixels travel once, as image content
    assert bridge.calls[0][1]["max_size"] == 100


@pytest.mark.parametrize("size", [0, 8, 1025, 5000])
async def test_out_of_range_max_size_is_rejected_before_reaching_gimp(size):
    async with tool_client({"image.preview": preview_op}) as (client, bridge):
        result = await client.call_tool("gimp_preview", {"image": iid(1), "max_size": size})
    assert result.is_error
    assert bridge.calls == []


async def test_default_max_size_comes_from_configuration(monkeypatch):
    monkeypatch.setenv("GIMP_MCP_PREVIEW_MAX_SIZE", "256")
    async with tool_client({"image.preview": preview_op}) as (client, bridge):
        await client.call_tool("gimp_preview", {"image": iid(1)})
    assert bridge.calls[0][1]["max_size"] == 256


async def test_preview_errors_are_structured():
    async with tool_client({}) as (client, _):
        result = await client.call_tool("gimp_preview", {"image": "nope"})
    assert error_code(result) == "INVALID_ID"

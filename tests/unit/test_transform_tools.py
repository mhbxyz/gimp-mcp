from __future__ import annotations

import pytest

from .tool_harness import iid, tid, tool_client

GEOMETRY = {"width": 10, "height": 10, "dirty": True}


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_resize_image", {"image": iid(1), "width": 0, "height": 10}),
        ("gimp_resize_canvas", {"image": iid(1), "width": 10, "height": 70000}),
        ("gimp_crop_image", {"image": iid(1), "x": 0, "y": 0, "width": -1, "height": 5}),
        ("gimp_scale_layer", {"item": tid(2), "width": 5, "height": 5, "interpolation": "sharp"}),
        ("gimp_scale_layer", {"item": tid(2), "width": 5, "height": 5, "anchor": "middle"}),
        ("gimp_flip_layer", {"item": tid(2), "direction": "diagonal"}),
        ("gimp_rotate_layer", {"item": tid(2), "angle": 99999}),
    ],
)
async def test_invalid_geometry_never_reaches_gimp(tool, arguments):
    ops = {name: (lambda p: GEOMETRY) for name in ("image.scale", "image.resize", "image.crop")}
    async with tool_client(ops) as (client, bridge):
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert bridge.calls == []


async def test_resize_sends_explicit_interpolation():
    async with tool_client({"image.scale": lambda p: GEOMETRY}) as (client, bridge):
        result = await client.call_tool("gimp_resize_image", {"image": iid(1), "width": 10, "height": 10})
    assert not result.is_error
    assert bridge.calls[0][1]["interpolation"] == "cubic"

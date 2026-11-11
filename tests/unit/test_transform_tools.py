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


INSPECTED = {"id": 1, "width": 400, "height": 300}


@pytest.mark.parametrize(
    ("given", "sent"),
    [
        ({"width": 200}, (200, 150)),
        ({"height": 30}, (40, 30)),
        ({"width": 1}, (1, 1)),
        ({"width": 7, "height": 9}, (7, 9)),
    ],
)
async def test_one_dimension_keeps_the_aspect_ratio(given, sent):
    ops = {"image.inspect": lambda p: INSPECTED, "image.scale": lambda p: GEOMETRY}
    async with tool_client(ops) as (client, bridge):
        result = await client.call_tool("gimp_resize_image", {"image": iid(1), **given})
    assert not result.is_error, result.content
    [scale] = [params for name, params in bridge.calls if name == "image.scale"]
    assert (scale["width"], scale["height"]) == sent


async def test_one_dimension_keeps_the_aspect_ratio_of_a_layer():
    ops = {"item.inspect": lambda p: {"id": 2, "width": 50, "height": 20}, "layer.scale": lambda p: {}}
    async with tool_client(ops) as (client, bridge):
        await client.call_tool("gimp_scale_layer", {"item": tid(2), "height": 10})
    [scale] = [params for name, params in bridge.calls if name == "layer.scale"]
    assert (scale["width"], scale["height"]) == (25, 10)


@pytest.mark.parametrize("tool", ["gimp_resize_image", "gimp_scale_layer"])
async def test_no_dimension_is_refused_before_gimp_is_called(tool):
    target = {"image": iid(1)} if tool == "gimp_resize_image" else {"item": tid(2)}
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, target)
    assert result.is_error and result.structured_content["error"]["code"] == "INVALID_ARGUMENT"
    assert "width" in result.structured_content["error"]["message"]
    assert bridge.calls == []

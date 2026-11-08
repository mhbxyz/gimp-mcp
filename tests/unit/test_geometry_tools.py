"""Geometry tools (#55), MCP side."""

from __future__ import annotations

import pytest

from .tool_harness import iid, tid, tool_client


@pytest.mark.parametrize(
    "arguments",
    [
        {"transform": "shear"},
        {"transform": "shear", "magnitude": 3, "item": tid(2), "image": iid(1), "selection": True},
        {"transform": "shear", "magnitude": 3, "image": iid(1)},
        {"transform": "rotate", "item": tid(2), "angle": 10},
        {"transform": "perspective", "item": tid(2), "corners": [[0, 0], [1, 0], [0, 1]]},
        {"transform": "matrix", "item": tid(2), "matrix": [[1, 0], [0, 1]]},
    ],
)
async def test_incomplete_transforms_never_reach_gimp(arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_transform", arguments)
        assert result.is_error and bridge.calls == []


async def test_canvas_fill_color_is_sent_as_srgb():
    async with tool_client({"image.resize": lambda p: {"width": 4, "height": 4, "dirty": True}}) as (client, bridge):
        await client.call_tool(
            "gimp_resize_canvas",
            {"image": iid(1), "width": 4, "height": 4, "resize_layers": "all", "fill_color": "#ff0000"},
        )
        sent = bridge.calls[0][1]
        assert sent["resize_layers"] == "all" and sent["fill_color"] == [1.0, 0.0, 0.0, 1.0]

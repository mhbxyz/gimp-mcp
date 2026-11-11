"""Painting tools (#53), MCP side."""

from __future__ import annotations

import pytest

from .tool_harness import tid, tool_client


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_paint_stroke", {"tool": "clone", "points": [[0, 0]], "source_offset": [5, 0], "source_x": 3}),
        ("gimp_paint_stroke", {"tool": "pencil", "points": [[0, 0]], "source_offset": [5, 0]}),
        ("gimp_paint_stroke", {"tool": "spray", "points": [[0, 0]]}),
        ("gimp_paint_stroke", {"tool": "pencil", "points": [[0, 0]], "color": "nope"}),
        ("gimp_gradient_fill", {"start": [0, 0], "end": [1, 1]}),
        ("gimp_gradient_fill", {"start": [0, 0], "end": [1, 1], "gradient": "G", "segments": []}),
        ("gimp_bucket_fill", {"fill": "pattern"}),
        ("gimp_bucket_fill", {"fill": "gradient", "gradient": "G"}),
    ],
)
async def test_inconsistent_requests_never_reach_gimp(tool, arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, {"item": tid(2), **arguments})
        assert result.is_error
        assert bridge.calls == []


async def test_stroke_sends_explicit_settings_and_the_source_id():
    def op(params):
        return {"item": params["item"], "tool": params["tool"], "brush": "b", "dynamics": "Dynamics Off"}

    async with tool_client({"paint.stroke": op}) as (client, bridge):
        result = await client.call_tool(
            "gimp_paint_stroke",
            {"item": tid(2), "tool": "clone", "points": [[1, 2], [3, 4]], "source": tid(5), "size": 7},
        )
        assert not result.is_error, result.content
        sent = bridge.calls[0][1]
        assert sent["source"] == 5 and sent["size"] == 7 and sent["hardness"] == 1.0 and sent["color"][3] == 1.0


def stroke_op(params):
    return {"item": params["item"], "tool": params["tool"], "brush": "b", "dynamics": "Dynamics Off"}


async def test_clone_and_heal_copy_from_the_painted_layer_by_default():
    async with tool_client({"paint.stroke": stroke_op}) as (client, bridge):
        for tool in ("clone", "heal"):
            result = await client.call_tool(
                "gimp_paint_stroke", {"item": tid(2), "tool": tool, "points": [[1, 2]], "source_x": 9, "source_y": 8}
            )
            assert not result.is_error, result.content
    assert [(call[1]["source"], call[1]["source_x"], call[1]["source_y"]) for call in bridge.calls] == [(2, 9, 8)] * 2


async def test_a_source_offset_is_relative_to_the_first_point():
    async with tool_client({"paint.stroke": stroke_op}) as (client, bridge):
        result = await client.call_tool(
            "gimp_paint_stroke",
            {"item": tid(2), "tool": "heal", "points": [[40, 20], [44, 20]], "source_offset": [16, -4]},
        )
    assert not result.is_error, result.content
    sent = bridge.calls[0][1]
    assert (sent["source"], sent["source_x"], sent["source_y"]) == (2, 56, 16)

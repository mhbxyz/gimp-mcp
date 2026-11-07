from __future__ import annotations

import pytest

from .tool_harness import error_code, tid, tool_client

RESULT = {"changed": True, "affected": {"x": 0, "y": 0, "width": 1, "height": 1}}


async def test_path_parameters_are_explicit():
    async with tool_client({"paint.path": lambda p: RESULT}) as (client, bridge):
        result = await client.call_tool(
            "gimp_draw_path", {"item": tid(3), "points": [[0, 0], [10, 5]], "color": "#00ff00"}
        )
    assert not result.is_error, result.content
    sent = bridge.calls[0][1]
    assert sent["points"] == [[0, 0], [10, 5]]
    assert sent["color"] == [0.0, 1.0, 0.0, 1.0]
    assert (sent["width"], sent["opacity"], sent["cap"], sent["join"], sent["antialias"]) == (
        2.0,
        100.0,
        "round",
        "round",
        True,
    )


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_draw_path", {"item": tid(1), "points": [[0, 0]], "color": "#000"}),
        ("gimp_draw_path", {"item": tid(1), "points": [[0, 0], [1, 1]], "color": "#000", "width": 0}),
        ("gimp_fill", {"item": tid(1), "color": "#000", "opacity": 101}),
        ("gimp_fill", {"item": tid(1), "color": "#000", "area": "everything"}),
        ("gimp_draw_shape", {"item": tid(1), "shape": "star", "x": 0, "y": 0, "width": 1, "height": 1}),
    ],
)
async def test_invalid_paint_requests_never_reach_gimp(tool, arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert bridge.calls == []


async def test_a_shape_needs_a_fill_or_a_stroke():
    async with tool_client({"paint.shape": lambda p: RESULT}) as (client, bridge):
        result = await client.call_tool(
            "gimp_draw_shape", {"item": tid(1), "shape": "ellipse", "x": 0, "y": 0, "width": 5, "height": 5}
        )
    assert error_code(result) == "INVALID_ARGUMENT"
    assert bridge.calls == []

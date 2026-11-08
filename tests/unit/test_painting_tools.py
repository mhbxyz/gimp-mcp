"""Painting tools (#53), MCP side."""

from __future__ import annotations

import pytest

from .tool_harness import tid, tool_client


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_paint_stroke", {"tool": "clone", "points": [[0, 0]]}),
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

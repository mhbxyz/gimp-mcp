from __future__ import annotations

import pytest

from .tool_harness import iid, tid, tool_client

STATE = {"empty": False, "bounds": {"x": 1, "y": 2, "width": 3, "height": 4}, "contains": None}


async def test_selection_parameters_are_explicit():
    async with tool_client({"selection.rect": lambda p: STATE, "selection.get": lambda p: STATE}) as (client, bridge):
        await client.call_tool(
            "gimp_select_rectangle", {"image": iid(1), "x": 1, "y": 2, "width": 3, "height": 4, "operation": "add"}
        )
        await client.call_tool("gimp_get_selection", {"image": iid(1), "probe_x": 5, "probe_y": 6})
    rect, get = bridge.calls[0][1], bridge.calls[1][1]
    assert (rect["operation"], rect["feather"]) == ("add", 0)
    assert get["probe"] == [5, 6]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_select_rectangle", {"image": iid(1), "x": 0, "y": 0, "width": 1, "height": 1, "operation": "xor"}),
        ("gimp_select_ellipse", {"image": iid(1), "x": 0, "y": 0, "width": 0, "height": 1}),
        ("gimp_select_rectangle", {"image": iid(1), "x": 0, "y": 0, "width": 1, "height": 1, "feather": -1}),
        ("gimp_modify_selection", {"image": iid(1), "action": "grow"}),
        ("gimp_add_layer_mask", {"item": tid(1), "fill": "gray"}),
        ("gimp_remove_layer_mask", {"item": tid(1), "mode": "maybe"}),
    ],
)
async def test_invalid_selection_requests_never_reach_gimp(tool, arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert bridge.calls == []

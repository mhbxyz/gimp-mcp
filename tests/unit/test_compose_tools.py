"""Composition tools (#54), MCP side: argument rules checked before GIMP."""

from __future__ import annotations

import pytest

from .tool_harness import iid, tid, tool_client


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_copy", {}),
        ("gimp_copy", {"image": iid(1)}),
        ("gimp_copy", {"image": iid(1), "visible": True, "cut": True}),
        ("gimp_paste", {"mode": "new-layer"}),
        ("gimp_merge_layers", {"mode": "visible", "item": tid(2)}),
        ("gimp_merge_layers", {"mode": "down"}),
        ("gimp_fit_layer", {"item": tid(2), "mode": "size", "width": 5}),
        ("gimp_align_layers", {"items": [tid(2)]}),
        ("gimp_align_layers", {"items": [tid(2)], "reference": "layer", "horizontal": "left"}),
        ("gimp_align_layers", {"items": [tid(2), tid(3)], "distribute": "vertical"}),
    ],
)
async def test_inconsistent_arguments_never_reach_gimp(tool, arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, arguments)
        assert result.is_error
        assert bridge.calls == []


async def test_copy_defaults_to_the_named_buffer():
    async with tool_client({"clipboard.copy": lambda p: {"buffer": p["buffer"], "selection": False}}) as (
        client,
        bridge,
    ):
        result = await client.call_tool("gimp_copy", {"items": [tid(2)]})
        assert result.structured_content == {"buffer": "gimp-mcp", "selection": False}
        assert bridge.calls[0][1]["items"] == [2] and bridge.calls[0][1]["cut"] is False

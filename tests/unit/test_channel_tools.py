"""Channel and selection tools (#51), MCP side."""

from __future__ import annotations

import pytest

from .tool_harness import iid, tid, tool_client


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_select_by_color", {"image": iid(1)}),
        ("gimp_select_by_color", {"image": iid(1), "color": "#fff", "point": [1, 1]}),
        ("gimp_select_by_color", {"image": iid(1), "color": "nope"}),
        ("gimp_modify_selection_shape", {"image": iid(1), "action": "grow"}),
        ("gimp_create_channel", {"image": iid(1), "source": "component"}),
        ("gimp_set_channel", {"channel": tid(3), "opacity": 150}),
    ],
)
async def test_invalid_requests_never_reach_gimp(tool, arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, arguments)
        assert result.is_error and bridge.calls == []


async def test_channel_ids_are_encoded():
    info = {"id": 9, "name": "C", "visible": True, "opacity": 50.0, "color": "#000000", "show_masked": False}
    async with tool_client({"channel.create": lambda p: info, "channel.delete": lambda p: {"deleted": 9}}) as (
        client,
        bridge,
    ):
        created = await client.call_tool("gimp_create_channel", {"image": iid(1)})
        assert created.structured_content["id"] == tid(9)
        deleted = await client.call_tool("gimp_delete_channel", {"channel": tid(9)})
        assert deleted.structured_content == {"deleted": tid(9)} and bridge.calls[1][1]["channel"] == 9

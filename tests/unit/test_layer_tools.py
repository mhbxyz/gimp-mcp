from __future__ import annotations

from .tool_harness import error_code, iid, tid, tool_client

NODE = {
    "id": 7,
    "name": "L",
    "kind": "layer",
    "parent": 5,
    "visible": True,
    "opacity": 100.0,
    "mode": "normal",
    "x": 0,
    "y": 0,
    "width": 1,
    "height": 1,
    "has_alpha": True,
    "locks": {"content": False, "position": False, "visibility": False, "alpha": False},
    "mask": None,
}


async def test_create_layer_sends_explicit_parameters():
    async with tool_client({"layer.create": lambda p: NODE}) as (client, bridge):
        result = await client.call_tool(
            "gimp_create_layer", {"image": iid(1), "name": "L", "parent": tid(5), "fill": "#ff0000", "opacity": 40}
        )
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["parent"] == tid(5)
    sent = bridge.calls[0][1]
    assert (sent["image"], sent["parent"], sent["position"]) == (1, 5, 0)
    assert sent["fill"] == [1.0, 0.0, 0.0, 1.0] and sent["opacity"] == 40


async def test_out_of_range_values_never_reach_gimp():
    async with tool_client({"layer.create": lambda p: NODE, "layer.set": lambda p: NODE}) as (client, bridge):
        opacity = await client.call_tool("gimp_set_layer_properties", {"item": tid(7), "opacity": 150})
        position = await client.call_tool("gimp_move_layer", {"item": tid(7), "parent": None, "position": -1})
        parent = await client.call_tool("gimp_create_layer", {"image": iid(1), "name": "L", "parent": iid(1)})
    assert opacity.is_error and position.is_error
    assert error_code(parent) == "INVALID_ID"
    assert bridge.calls == []


async def test_duplicate_keeps_the_original_parent_unless_told_otherwise():
    async with tool_client({"layer.duplicate": lambda p: NODE}) as (client, bridge):
        await client.call_tool("gimp_duplicate_layer", {"item": tid(7)})
        await client.call_tool("gimp_duplicate_layer", {"item": tid(7), "parent": None, "position": 0})
        await client.call_tool("gimp_duplicate_layer", {"item": tid(7), "parent": tid(5)})
    assert [call[1]["keep_parent"] for call in bridge.calls] == [True, False, False]
    assert bridge.calls[2][1]["parent"] == 5

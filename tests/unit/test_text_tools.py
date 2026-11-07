from __future__ import annotations

import pytest

from .tool_harness import iid, tid, tool_client

NODE = {
    "id": 9,
    "name": "Hi",
    "kind": "text",
    "parent": None,
    "visible": True,
    "opacity": 100.0,
    "mode": "normal",
    "x": 1,
    "y": 2,
    "width": 30,
    "height": 10,
    "has_alpha": True,
    "locks": {"content": False, "position": False, "visibility": False, "alpha": False},
    "mask": None,
}


async def test_text_parameters_are_explicit_with_units():
    async with tool_client({"text.create": lambda p: NODE}) as (client, bridge):
        result = await client.call_tool(
            "gimp_create_text_layer",
            {"image": iid(1), "text": "Hi", "size": 12, "size_unit": "pt", "box_width": 40, "box_height": 20},
        )
    assert not result.is_error, result.content
    sent = bridge.calls[0][1]
    assert (sent["size"], sent["unit"], sent["font"]) == (12, "pt", "Sans-serif")
    assert sent["box"] == [40, 20] and sent["color"] == [0.0, 0.0, 0.0, 1.0]


async def test_edit_sends_only_given_properties():
    async with tool_client({"text.set": lambda p: NODE}) as (client, bridge):
        await client.call_tool("gimp_set_text", {"item": tid(9), "text": "New"})
    sent = bridge.calls[0][1]
    assert sent["text"] == "New"
    assert all(sent[key] is None for key in ("font", "size", "unit", "color", "justify", "box", "x", "y"))


@pytest.mark.parametrize(
    "arguments",
    [
        {"text": "x", "size": 0},
        {"text": "x", "size_unit": "em"},
        {"text": "x", "justify": "middle"},
        {"text": "x", "color": "not-a-color"},
    ],
)
async def test_invalid_text_requests_never_reach_gimp(arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_create_text_layer", {"image": iid(1), **arguments})
    assert result.is_error
    assert bridge.calls == []

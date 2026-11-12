"""Color adjustment tools (#48), MCP side: validation before the bridge, results."""

from __future__ import annotations

import pytest

from .tool_harness import SESSION, iid, tid, tool_client

RESULT = {"adjustment": "levels", "operation": "gimp:levels", "destructive": False, "filter": 4,
          "restricted_to_selection": False}  # fmt: skip


async def test_levels_send_settings_and_encode_the_filter_id():
    async with tool_client({"color.adjust": lambda p: RESULT}) as (client, bridge):
        result = await client.call_tool("gimp_levels", {"item": tid(2), "input_high": 128, "gamma": 1.5})
        assert not result.is_error, result.content
        assert result.structured_content["filter"] == f"filter:4@{SESSION}"
        params = bridge.calls[0][1]
        assert params["adjustment"] == "levels" and params["destructive"] is False
        assert params["settings"]["input_high"] == 128 and params["settings"]["gamma"] == 1.5


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_levels", {"input_low": 200, "input_high": 100}),
        ("gimp_levels", {"gamma": 20}),
        ("gimp_threshold", {"low": 200, "high": 100}),
        ("gimp_curves", {}),
        ("gimp_curves", {"points": [[0, 0], [255, 255]], "samples": [0, 255]}),
        ("gimp_curves", {"points": [[10, 0], [5, 255]]}),
        ("gimp_color_balance", {"cyan_red": 150}),
        ("gimp_posterize", {"levels": 1}),
        ("gimp_desaturate", {"mode": "sepia"}),
    ],
)
async def test_invalid_settings_never_reach_gimp(tool, arguments):
    async with tool_client({"color.adjust": lambda p: RESULT, "color.curves": lambda p: RESULT}) as (client, bridge):
        result = await client.call_tool(tool, {"item": tid(2), **arguments})
        assert result.is_error
        assert bridge.calls == []


async def test_auto_adjust_defaults_to_the_only_mode_gimp_offers():
    destructive = {**RESULT, "adjustment": "equalize", "operation": None, "destructive": True, "filter": None}
    async with tool_client({"color.adjust": lambda p: destructive}) as (client, bridge):
        await client.call_tool("gimp_auto_adjust", {"item": tid(2), "method": "equalize"})
        await client.call_tool("gimp_auto_adjust", {"item": tid(2), "method": "stretch-contrast", "keep_colors": True})
        assert bridge.calls[0][1]["destructive"] is True
        assert bridge.calls[1][1]["destructive"] is False and bridge.calls[1][1]["settings"] == {"keep_colors": True}


async def test_curves_are_destructive():
    curves = {**RESULT, "adjustment": "curves", "operation": None, "destructive": True, "filter": None}
    async with tool_client({"color.curves": lambda p: curves}) as (client, bridge):
        result = await client.call_tool("gimp_curves", {"item": tid(2), "points": [[0, 0], [128, 64], [255, 255]]})
        assert result.structured_content["destructive"] is True
        assert bridge.calls[0][1]["points"] == [[0, 0], [128, 64], [255, 255]]
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    annotations = tools["gimp_curves"].annotations
    assert annotations is not None and annotations.destructive_hint


async def test_assigning_the_built_in_srgb_says_it_changes_nothing():
    profile = {"label": "sRGB", "description": "GIMP built-in sRGB", "model": "rgb", "linear": False, "icc_bytes": 1}
    state = {"assigned": None, "effective": profile}
    async with tool_client({"profile.set": lambda p: state}) as (client, _bridge):
        result = await client.call_tool(
            "gimp_set_color_profile", {"image": iid(1), "action": "assign", "profile": "srgb"}
        )
    note = result.structured_content["note"]
    assert "built-in sRGB" in note and "color_profile=true" in note

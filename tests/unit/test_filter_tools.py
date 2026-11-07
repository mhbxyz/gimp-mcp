from __future__ import annotations

import pytest

from .tool_harness import error_code, tid, tool_client

APPLIED = {
    "operation": "gimp:brightness-contrast",
    "destructive": True,
    "filter": None,
    "restricted_to_selection": False,
}


async def test_percentages_are_mapped_to_gimp_ranges():
    async with tool_client({"filter.apply": lambda p: APPLIED}) as (client, bridge):
        await client.call_tool("gimp_brightness_contrast", {"item": tid(1), "brightness": 50, "contrast": -25})
        await client.call_tool("gimp_gaussian_blur", {"item": tid(1), "radius": 2})
    assert bridge.calls[0][1]["settings"] == {"brightness": 0.5, "contrast": -0.25}
    assert bridge.calls[1][1]["settings"] == {"std_dev_x": 2, "std_dev_y": 2}


async def test_editable_filter_ids_are_session_bound():
    nde = {**APPLIED, "destructive": False, "filter": 4}
    async with tool_client({"filter.apply": lambda p: nde}) as (client, _):
        result = await client.call_tool("gimp_gaussian_blur", {"item": tid(1), "radius": 2, "destructive": False})
    assert result.structured_content is not None
    assert result.structured_content["filter"] == "filter:4@a1b2c3d4"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_brightness_contrast", {"item": tid(1), "brightness": 101}),
        ("gimp_hue_saturation", {"item": tid(1), "hue": 200}),
        ("gimp_hue_saturation", {"item": tid(1), "hue_range": "orange"}),
        ("gimp_gaussian_blur", {"item": tid(1), "radius": 0}),
    ],
)
async def test_out_of_range_parameters_never_reach_gimp(tool, arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, arguments)
    assert result.is_error
    assert bridge.calls == []


async def test_filter_id_kind_is_checked():
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_remove_filter", {"item": tid(1), "filter": tid(2)})
    assert error_code(result) == "INVALID_ID"
    assert bridge.calls == []

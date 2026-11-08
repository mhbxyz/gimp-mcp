"""Analysis tools (#46), MCP side: argument validation and what reaches the bridge."""

from __future__ import annotations

import base64

import gmb_stats  # type: ignore[import-not-found]
import pytest

from .tool_harness import SESSION, error_code, iid, tid, tool_client


def ok(value):
    return lambda params: value


HISTOGRAM = {
    "region": {"x": 0, "y": 0, "width": 4, "height": 2},
    "selection_only": False,
    "channels": {"red": {"pixel_count": 8, "mean": 255.0, "median": 255.0, "std_dev": 0.0, "min": 255,
                         "max": 255, "percentiles": {"50": 255}, "histogram": [0, 8]}},
}  # fmt: skip


async def test_histogram_targets_an_image_or_an_item_and_passes_options():
    async with tool_client({"analysis.histogram": ok(HISTOGRAM)}) as (client, bridge):
        result = await client.call_tool(
            "gimp_histogram",
            {"target": tid(5), "channels": ["red"], "region": {"x": 0, "y": 0, "width": 4, "height": 2},
             "selection_only": True, "percentiles": [50], "bins": 2},
        )  # fmt: skip
        assert not result.is_error, result.content
        assert result.structured_content["channels"]["red"]["mean"] == 255.0
        params = bridge.calls[0][1]
        assert params["target"] == {"kind": "item", "id": 5}
        assert params["selection_only"] is True and params["bins"] == 2 and params["percentiles"] == [50]
        await client.call_tool("gimp_histogram", {"target": iid(3)})
        assert bridge.calls[1][1]["target"] == {"kind": "image", "id": 3}


@pytest.mark.parametrize(
    "arguments",
    [
        {"target": "filter:1@" + SESSION},
        {"target": iid(1), "channels": ["purple"]},
        {"target": iid(1), "bins": 300},
        {"target": iid(1), "percentiles": [101]},
        {"target": iid(1), "region": {"x": 0, "y": 0, "width": 0, "height": 2}},
    ],
)
async def test_histogram_refuses_invalid_arguments_before_calling_gimp(arguments):
    async with tool_client({"analysis.histogram": ok(HISTOGRAM)}) as (client, bridge):
        result = await client.call_tool("gimp_histogram", arguments)
        assert result.is_error
        assert bridge.calls == []


async def test_sample_colors():
    samples = {"samples": [{"x": 1, "y": 2, "hex": "#ff0000", "rgba": [255, 0, 0, 255], "pixels_averaged": 9}]}
    async with tool_client({"analysis.sample": ok(samples)}) as (client, bridge):
        result = await client.call_tool("gimp_sample_colors", {"target": iid(1), "points": [[1, 2]], "radius": 1})
        assert result.structured_content["samples"][0]["hex"] == "#ff0000"
        assert bridge.calls[0][1]["points"] == [[1, 2]] and bridge.calls[0][1]["radius"] == 1
        empty = await client.call_tool("gimp_sample_colors", {"target": iid(1), "points": []})
        assert empty.is_error and len(bridge.calls) == 1


async def test_compare_accepts_checkpoints_and_returns_the_difference_preview_as_an_image():
    a = bytes([0, 0, 0, 255] * 2)
    b = bytes([0, 0, 0, 255, 9, 0, 0, 255])
    png, width, height = gmb_stats.difference_png(a, b, 2, 1)
    diff = {**gmb_stats.compare(a, b, 2, 1), "preview": {"png_base64": base64.b64encode(png).decode(),
                                                        "width": width, "height": height}}  # fmt: skip
    async with tool_client({"analysis.compare": ok(diff)}) as (client, bridge):
        result = await client.call_tool("gimp_compare", {"a": f"checkpoint:2@{SESSION}", "b": iid(1), "preview": True})
        assert not result.is_error, result.content
        assert bridge.calls[0][1]["a"] == {"kind": "checkpoint", "id": 2}
        data = result.structured_content
        assert data["changed_pixels"] == 1 and data["bounds"] == {"x": 1, "y": 0, "width": 1, "height": 1}
        assert "png_base64" not in str(data)
        assert [block.type for block in result.content].count("image") == 1


async def test_dominant_colors_and_region_preview():
    dominant = {"region": {"x": 0, "y": 0, "width": 2, "height": 2}, "sampled_scale": 1.0,
                "colors": [{"hex": "#ff0000", "rgb": [255, 0, 0], "fraction": 1.0}]}  # fmt: skip
    png, _, _ = gmb_stats.difference_png(b"\0\0\0\xff", b"\0\0\0\xff", 1, 1)
    region = {"png_base64": base64.b64encode(png).decode(), "width": 1, "height": 1,
              "region": {"x": 3, "y": 4, "width": 1, "height": 1}}  # fmt: skip
    async with tool_client({"analysis.dominant": ok(dominant), "image.preview_region": ok(region)}) as (client, bridge):
        colors = await client.call_tool("gimp_dominant_colors", {"target": tid(2), "count": 3})
        assert colors.structured_content["colors"][0]["hex"] == "#ff0000"
        assert bridge.calls[0][1]["count"] == 3
        crop = await client.call_tool("gimp_preview_region", {"image": iid(1), "x": 3, "y": 4, "width": 1, "height": 1})
        assert not crop.is_error, crop.content
        assert bridge.calls[1][1]["region"] == {"x": 3, "y": 4, "width": 1, "height": 1}
        assert [block.type for block in crop.content].count("image") == 1
        bad = await client.call_tool("gimp_preview_region", {"image": tid(1), "x": 0, "y": 0, "width": 1, "height": 1})
        assert error_code(bad) == "INVALID_ID"


async def test_analysis_tools_are_read_only_and_in_their_own_toolset():
    async with tool_client({}) as (client, _bridge):
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    for name in ("gimp_histogram", "gimp_sample_colors", "gimp_compare", "gimp_dominant_colors", "gimp_preview_region"):
        annotations = tools[name].annotations
        assert annotations is not None and annotations.read_only_hint, name

"""Document tools (#60), MCP side."""

from __future__ import annotations

import pytest

from .tool_harness import iid, tool_client


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_set_metadata", {"set": {"Artist": "x"}}),
        ("gimp_set_metadata", {"remove": ["Exif"]}),
        ("gimp_set_print_size", {}),
        ("gimp_set_print_size", {"width": 10}),
        ("gimp_set_print_size", {"width": 10, "height": 5, "x_resolution": 72}),
        ("gimp_set_print_size", {"x_resolution": 1}),
        ("gimp_add_guide", {"orientation": "diagonal", "position": 3}),
    ],
)
async def test_invalid_requests_never_reach_gimp(tool, arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool(tool, {"image": iid(1), **arguments})
        assert result.is_error
        assert bridge.calls == []


async def test_exports_write_no_metadata_unless_asked(tmp_path):
    def export(params):
        return {"path": params["path"], "width": 1, "height": 1, "bytes": 1}

    async with tool_client({"image.export": export}) as (client, bridge):
        await client.call_tool("gimp_export_image", {"image": iid(1), "path": str(tmp_path / "a.jpg")})
        await client.call_tool(
            "gimp_export_image",
            {"image": iid(1), "path": str(tmp_path / "b.png"), "png_options": {"metadata": ["exif", "comment"]}},
        )
    assert bridge.calls[0][1]["options"]["metadata"] == []
    assert bridge.calls[1][1]["options"]["metadata"] == ["exif", "comment"]


METADATA = {
    "image": 1,
    "exif": {"Exif.Image.Orientation": "droit, haut"},
    "xmp": {},
    "iptc": {},
    "raw": {"Exif.Image.Orientation": "6"},
    "comment": None,
}


async def test_metadata_carries_raw_values_next_to_the_localized_ones():
    async with tool_client({"metadata.get": lambda p: METADATA}) as (client, _bridge):
        result = await client.call_tool("gimp_get_metadata", {"image": iid(1)})
    data = result.structured_content
    assert data is not None and data["raw"] == {"Exif.Image.Orientation": "6"}
    assert data["exif"] == {"Exif.Image.Orientation": "droit, haut"}


async def test_an_older_plugin_without_raw_values_is_asked_to_update():
    old = {"metadata.get": 1, "metadata.set": 1}
    async with tool_client({"metadata.get": lambda p: METADATA}, revisions=old) as (client, bridge):
        result = await client.call_tool("gimp_get_metadata", {"image": iid(1)})
    assert result.is_error and result.structured_content["error"]["code"] == "PLUGIN_VERSION_MISMATCH"
    assert bridge.calls == []

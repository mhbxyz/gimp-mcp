"""Vector and link layer tools (#57), MCP side."""

from __future__ import annotations

from .tool_harness import error_code, iid, tid, tool_client

NODE = {"id": 7, "name": "Shape", "kind": "vector", "parent": None, "visible": True, "opacity": 100.0, "mode": "normal",
        "x": 0, "y": 0, "width": 4, "height": 4, "has_alpha": True,
        "locks": {"content": False, "position": False, "alpha": False, "visibility": False}, "mask": None}  # fmt: skip


async def test_vector_layer_colors_are_sent_as_srgb_and_ids_encoded():
    data = {**NODE, "path": 3, "fill": {"enabled": True, "color": "#ff0000ff"}, "stroke": {"enabled": False}}
    async with tool_client({"vector.create": lambda p: data}) as (client, bridge):
        result = await client.call_tool(
            "gimp_create_vector_layer",
            {"path": tid(3), "fill": {"color": "#ff0000"}, "stroke": {"width": 2, "cap": "round"}},
        )
        assert not result.is_error, result.content
        assert result.structured_content["path"] == tid(3) and result.structured_content["id"] == tid(7)
        sent = bridge.calls[0][1]
        assert sent["path"] == 3 and sent["fill"]["color"] == [1.0, 0.0, 0.0, 1.0] and sent["stroke"]["cap"] == "round"


async def test_link_layers_need_an_existing_file(tmp_path):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_create_link_layer", {"image": iid(1), "file": str(tmp_path / "x.png")})
        assert error_code(result) == "FILE_NOT_FOUND" and bridge.calls == []
        bad = await client.call_tool("gimp_set_vector_layer", {"item": tid(7), "stroke": {"cap": "pointy"}})
        assert bad.is_error and bridge.calls == []

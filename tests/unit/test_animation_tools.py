"""Animation tools (#59), MCP side."""

from __future__ import annotations

from .tool_harness import error_code, iid, tool_client


async def test_export_maps_animation_options_per_format(tmp_path):
    def export(params):
        return {"path": params["path"], "procedure": "p", "bytes": 1, "lossless": True, "layers": "frames",
                "options": params["options"]}  # fmt: skip

    async with tool_client({"image.export_as": export}) as (client, bridge):
        await client.call_tool(
            "gimp_export_animation", {"image": iid(1), "path": str(tmp_path / "a.gif"), "loop": False}
        )
        await client.call_tool(
            "gimp_export_animation", {"image": iid(1), "path": str(tmp_path / "a.webp"), "force": True}
        )
        gif, webp = bridge.calls[0][1]["options"], bridge.calls[1][1]["options"]
        assert gif["as-animation"] is True and gif["loop"] is False and gif["default-dispose"] == "combine"
        assert webp["animation"] is True and webp["force-delay"] is True
        png = await client.call_tool("gimp_export_animation", {"image": iid(1), "path": str(tmp_path / "a.png")})
        assert error_code(png) == "UNSUPPORTED_FORMAT" and len(bridge.calls) == 2


async def test_frame_settings_are_validated():
    async with tool_client({}) as (client, bridge):
        bad = await client.call_tool("gimp_add_frame", {"image": iid(1), "disposal": "blend"})
        zero = await client.call_tool("gimp_add_frame", {"image": iid(1), "duration_ms": 0})
        assert bad.is_error and zero.is_error and bridge.calls == []

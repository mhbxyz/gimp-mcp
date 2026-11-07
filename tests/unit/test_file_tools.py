from __future__ import annotations

from gmb_server import BridgeError  # type: ignore[import-not-found]

from .tool_harness import error_code, iid, tool_client


def export_op(params):
    return {"path": params["path"], "width": 8, "height": 8, "bytes": 10}


async def test_export_options_are_explicit_and_validated_before_gimp(tmp_path):
    async with tool_client({"image.export": export_op}) as (client, bridge):
        ok = await client.call_tool(
            "gimp_export_image",
            {"image": iid(1), "path": str(tmp_path / "a.jpg"), "jpeg_options": {"quality": 55, "background": "#000"}},
        )
        bad_quality = await client.call_tool(
            "gimp_export_image", {"image": iid(1), "path": str(tmp_path / "b.jpg"), "jpeg_options": {"quality": 101}}
        )
        bad_color = await client.call_tool(
            "gimp_export_image",
            {"image": iid(1), "path": str(tmp_path / "c.jpg"), "jpeg_options": {"background": "nope"}},
        )
    assert not ok.is_error, ok.content
    assert ok.structured_content is not None
    assert ok.structured_content["options"]["quality"] == 55
    assert ok.structured_content["options"]["background"] == "#000"
    assert bad_quality.is_error and error_code(bad_color) == "INVALID_ARGUMENT"
    assert len(bridge.calls) == 1
    sent = bridge.calls[0][1]
    assert sent["format"] == "jpeg"
    assert sent["options"]["background"] == [0.0, 0.0, 0.0, 1.0]
    assert sent["options"]["progressive"] is False and sent["options"]["optimize"] is True


async def test_png_defaults_are_sent(tmp_path):
    async with tool_client({"image.export": export_op}) as (client, bridge):
        await client.call_tool("gimp_export_image", {"image": iid(1), "path": str(tmp_path / "a.png")})
    assert bridge.calls[0][1]["options"] == {"compression": 9, "interlaced": False}


async def test_path_problems_never_reach_gimp(tmp_path):
    (tmp_path / "exists.png").write_bytes(b"x")
    async with tool_client({"image.export": export_op, "image.open": lambda p: {}}) as (client, bridge):
        exists = await client.call_tool("gimp_export_image", {"image": iid(1), "path": str(tmp_path / "exists.png")})
        relative = await client.call_tool("gimp_open_image", {"path": "rel.png"})
        missing = await client.call_tool("gimp_open_image", {"path": str(tmp_path / "none.png")})
        xcf = await client.call_tool("gimp_export_image", {"image": iid(1), "path": str(tmp_path / "a.xcf")})
    assert error_code(exists) == "FILE_EXISTS"
    assert error_code(relative) == "INVALID_ARGUMENT"
    assert error_code(missing) == "FILE_NOT_FOUND"
    assert error_code(xcf) == "UNSUPPORTED_FORMAT"
    assert bridge.calls == []


async def test_semi_transparent_fill_is_rejected():
    async with tool_client({"image.create": lambda p: {}}) as (client, bridge):
        result = await client.call_tool("gimp_create_image", {"width": 4, "height": 4, "fill": "#ff000080"})
    assert error_code(result) == "INVALID_ARGUMENT"
    assert bridge.calls == []


async def test_closing_an_image_with_unsaved_changes_is_refused():
    def close(params):
        raise BridgeError("UNSAVED_CHANGES", "the image has unsaved changes", {"image": params["image"]})

    async with tool_client({"image.close": close}) as (client, _):
        result = await client.call_tool("gimp_close_image", {"image": iid(1)})
    assert error_code(result) == "UNSAVED_CHANGES"
    assert result.structured_content is not None
    assert result.structured_content["error"]["outcome"] == "not_applied"

"""Path tools (#50), MCP side: stroke specs, ids and validation before the bridge."""

from __future__ import annotations

import pytest

from .tool_harness import SESSION, error_code, iid, tid, tool_client

INFO = {"id": 9, "image": 1, "name": "P", "visible": False, "stroke_count": 1,
        "strokes": [{"id": 1, "closed": True, "length": 160.0, "anchors": 4,
                     "bounds": {"x": 10, "y": 10, "width": 40, "height": 40}}]}  # fmt: skip


async def test_create_path_sends_typed_strokes_and_encodes_ids():
    async with tool_client({"path.create": lambda p: INFO}) as (client, bridge):
        result = await client.call_tool(
            "gimp_create_path",
            {"image": iid(1), "name": "P", "strokes": [
                {"type": "polyline", "points": [[0, 0], [10, 0]], "closed": True},
                {"type": "bezier", "start": [0, 0],
                 "segments": [{"to": [5, 5], "control1": [1, 1], "control2": [4, 4]}]},
                {"type": "ellipse", "center": [5, 5], "radius_x": 2, "radius_y": 3}]},
        )  # fmt: skip
        assert not result.is_error, result.content
        assert result.structured_content["id"] == tid(9) and result.structured_content["image"] == iid(1)
        strokes = bridge.calls[0][1]["strokes"]
        assert [s["type"] for s in strokes] == ["polyline", "bezier", "ellipse"]
        assert strokes[1]["segments"][0]["control2"] == [4.0, 4.0]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_create_path", {"image": iid(1), "strokes": [{"type": "polyline", "points": [[0, 0]]}]}),
        (
            "gimp_create_path",
            {"image": iid(1), "strokes": [{"type": "ellipse", "center": [0, 0], "radius_x": 0, "radius_y": 1}]},
        ),
        ("gimp_create_path", {"image": iid(1), "strokes": [{"type": "spiral"}]}),
        ("gimp_edit_path_stroke", {"path": tid(9), "stroke": 1, "action": "scale", "sx": 0}),
        ("gimp_import_svg_paths", {"image": iid(1)}),
        ("gimp_import_svg_paths", {"image": iid(1), "svg": "<svg/>", "file": "/tmp/x.svg"}),
        ("gimp_stroke_path", {"path": tid(9), "item": tid(2), "color": "nope"}),
    ],
)
async def test_invalid_requests_never_reach_gimp(tool, arguments):
    async with tool_client({"path.create": lambda p: INFO}) as (client, bridge):
        result = await client.call_tool(tool, arguments)
        assert result.is_error
        assert bridge.calls == []


async def test_export_to_an_existing_file_needs_overwrite(tmp_path):
    (tmp_path / "out.svg").write_text("x")
    async with tool_client({"paths.export_svg": lambda p: {"svg": None, "file": p["file"], "bytes": 1}}) as (
        client,
        bridge,
    ):
        refused = await client.call_tool("gimp_export_path_svg", {"image": iid(1), "file": str(tmp_path / "out.svg")})
        assert error_code(refused) == "FILE_EXISTS" and bridge.calls == []
        ok = await client.call_tool(
            "gimp_export_path_svg", {"image": iid(1), "file": str(tmp_path / "out.svg"), "overwrite": True}
        )
        assert not ok.is_error and bridge.calls[0][1]["file"] == str(tmp_path / "out.svg")


async def test_path_to_selection_and_delete_encode_ids():
    selection = {"empty": False, "bounds": {"x": 1, "y": 2, "width": 3, "height": 4}, "contains": None, "image": 1}
    ops = {"path.to_selection": lambda p: selection, "path.delete": lambda p: {"deleted": 9}}
    async with tool_client(ops) as (client, _bridge):
        selected = await client.call_tool("gimp_path_to_selection", {"path": tid(9), "operation": "add"})
        assert selected.structured_content["image"] == f"image:1@{SESSION}"
        deleted = await client.call_tool("gimp_delete_path", {"path": tid(9)})
        assert deleted.structured_content["deleted"] == tid(9)

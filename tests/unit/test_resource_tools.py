"""Resource tools (#52), MCP side."""

from __future__ import annotations

from pathlib import Path

import pytest

from .tool_harness import error_code, tool_client


async def test_import_sends_gimp_palettes_as_files_and_converts_other_formats(tmp_path):
    fixtures = Path(__file__).parent.parent / "fixtures" / "palettes"
    (tmp_path / "b.gpl").write_text("GIMP Palette\nName: B\n#\n")
    (tmp_path / "c.xyz").write_text("x")
    ops = {"palette.import": lambda p: {"kind": "palette", "name": "B", "editable": True, "columns": 0, "entries": []}}
    async with tool_client(ops) as (client, bridge):
        for refused in (tmp_path / "c.xyz", fixtures / "ADG3-CMYK.ase"):
            result = await client.call_tool("gimp_import_palette", {"file": str(refused)})
            assert error_code(result) == "UNSUPPORTED_FORMAT" and bridge.calls == [], refused
        ok = await client.call_tool("gimp_import_palette", {"file": str(tmp_path / "b.gpl")})
        assert not ok.is_error and bridge.calls[0][1] == {"file": str(tmp_path / "b.gpl")}
        converted = await client.call_tool("gimp_import_palette", {"file": str(fixtures / "arne-v20-16.act")})
        sent = bridge.calls[1][1]
        assert not converted.is_error and sent["name"] == "arne-v20-16" and len(sent["entries"]) == 16
        assert sent["entries"][1] == {"name": "", "rgb": [0x9D, 0x9D, 0x9D]}  # second color of the file


async def test_gradient_colors_are_sent_as_srgb_floats_and_positions_checked():
    edited = {"kind": "gradient", "name": "G", "editable": True, "segments": []}
    async with tool_client({"gradient.edit": lambda p: edited}) as (client, bridge):
        await client.call_tool(
            "gimp_edit_gradient",
            {"name": "G", "segments": [{"left_color": "#ff0000", "right_color": "#0000ff80", "right": 0.4},
                                       {"left_color": "#0000ff", "right_color": "#ffffff"}]},
        )  # fmt: skip
        sent = bridge.calls[0][1]["segments"]
        assert sent[0]["left_color"] == [1.0, 0.0, 0.0, 1.0] and sent[0]["right"] == 0.4
        assert sent[0]["right_color"][3] == pytest.approx(128 / 255)
        bad = await client.call_tool(
            "gimp_edit_gradient",
            {"name": "G", "segments": [{"left_color": "#000", "right_color": "#fff", "right": 0.6},
                                       {"left_color": "#000", "right_color": "#fff", "right": 0.3},
                                       {"left_color": "#000", "right_color": "#fff"}]},
        )  # fmt: skip
        assert error_code(bad) == "INVALID_ARGUMENT" and len(bridge.calls) == 1


async def test_export_refuses_existing_files_and_previews_are_images(tmp_path):
    (tmp_path / "p.gpl").write_text("x")
    inspected = {"kind": "palette", "name": "Web", "editable": False, "columns": 6, "entries": [],
                 "preview": "iVBORw0KGgo="}  # fmt: skip
    ops = {"palette.export": lambda p: {"file": p["file"], "format": p["format"], "bytes": 1},
           "resource.inspect": lambda p: inspected}  # fmt: skip
    async with tool_client(ops) as (client, bridge):
        refused = await client.call_tool("gimp_export_palette", {"name": "Web", "file": str(tmp_path / "p.gpl")})
        assert error_code(refused) == "FILE_EXISTS" and bridge.calls == []
        result = await client.call_tool("gimp_inspect_resource", {"kind": "palette", "name": "Web", "preview": True})
        assert [block.type for block in result.content].count("image") == 1
        assert "preview" not in result.structured_content

"""The refusals of the security review that run in the plug-in (#122) need a plug-in that has them: with an
older plug-in installed, the calls they protect fail with PLUGIN_VERSION_MISMATCH instead of running
unprotected."""

from __future__ import annotations

from gimp_mcp.versions import bundled_capabilities

from .tool_harness import error_code, iid, tool_client

# What a 0.7 plug-in serves for the operations that gained a plug-in-side refusal in 1.0.
PLUGIN_0_7 = {**bundled_capabilities(), "pdb.call": 1, "image.open_with": 1, "image.export_as": 2,
              "image.export_layers": 1, "image.export_region": 1, "palette.export": 1, "palette.import": 1}  # fmt: skip


async def test_calls_that_rely_on_a_plugin_side_refusal_need_the_new_plugin(tmp_path):
    (tmp_path / "a.gpl").write_text("GIMP Palette\nName: A\n#\n")
    (tmp_path / "scan.data").write_bytes(b"\0" * 16)
    calls = [
        ("gimp_call_procedure", {"name": "plug-in-despeckle", "arguments": {}}),
        ("gimp_open_with_options", {"path": str(tmp_path / "scan.data"), "procedure": "file-raw-load"}),
        ("gimp_export_as", {"image": iid(1), "path": str(tmp_path / "a.html")}),
        ("gimp_export_layers", {"image": iid(1), "directory": str(tmp_path)}),
        (
            "gimp_export_region",
            {"image": iid(1), "path": str(tmp_path / "r.png"), "x": 0, "y": 0, "width": 1, "height": 1},
        ),
        ("gimp_export_palette", {"name": "Web", "path": str(tmp_path / "w.css"), "format": "css"}),
        ("gimp_import_palette", {"path": str(tmp_path / "a.gpl")}),
    ]
    served = {method: (lambda params: {}) for method in PLUGIN_0_7}  # served: only the revision can refuse
    async with tool_client(served, revisions=PLUGIN_0_7) as (client, bridge):
        for tool, arguments in calls:
            result = await client.call_tool(tool, arguments)
            assert error_code(result) == "PLUGIN_VERSION_MISMATCH", (tool, result.content)
        assert [name for name, _ in bridge.calls] == []

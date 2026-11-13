"""Format tools (#58), MCP side: path rules before GIMP."""

from __future__ import annotations

import pytest

from .tool_harness import error_code, iid, tool_client


async def test_existing_targets_and_bad_directories_never_reach_gimp(tmp_path):
    (tmp_path / "a.webp").write_bytes(b"x")
    async with tool_client({}) as (client, bridge):
        exists = await client.call_tool("gimp_export_as", {"image": iid(1), "path": str(tmp_path / "a.webp")})
        assert error_code(exists) == "FILE_EXISTS"
        relative = await client.call_tool("gimp_export_layers", {"image": iid(1), "directory": "out"})
        missing = await client.call_tool("gimp_export_layers", {"image": iid(1), "directory": str(tmp_path / "no")})
        template = await client.call_tool(
            "gimp_export_layers", {"image": iid(1), "directory": str(tmp_path), "template": "{oops}"}
        )
        assert error_code(relative) == "INVALID_ARGUMENT" and error_code(missing) == "WRITE_FAILED"
        assert error_code(template) == "INVALID_ARGUMENT"
        for bad in ("../{index}", "/tmp/{index}", "sub/{index}", "a\\{index}", "C:{index}", "{index:0999999999d}",
                    "{name!r}", "{index:{index}}"):  # fmt: skip
            escaping = await client.call_tool(
                "gimp_export_layers", {"image": iid(1), "directory": str(tmp_path), "template": bad}
            )
            assert error_code(escaping) == "INVALID_ARGUMENT", bad  # a layer file stays in its directory (#122)
        nothing = await client.call_tool("gimp_open_with_options", {"path": str(tmp_path / "none.pdf")})
        assert error_code(nothing) == "FILE_NOT_FOUND"
        assert bridge.calls == []


@pytest.mark.parametrize("mode", ["export", "import"])
async def test_describe_needs_an_extension_or_a_procedure(mode):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_describe_file_format", {"mode": mode})
        assert result.is_error and bridge.calls == []


EXPORTED = {"path": "/x.tif", "procedure": "file-tiff-export", "bytes": 1, "lossless": True, "layers": "flattened",
            "options": {}}  # fmt: skip


async def test_exports_need_an_up_to_date_plugin_and_say_so(tmp_path):
    # a plug-in before 0.7 would ignore `layers`; one before 1.0 lacks the security review's refusals (#122)
    for old in ({"image.export_as": 1}, {"image.export_as": 2}):
        async with tool_client({"image.export_as": lambda p: EXPORTED}, revisions=old) as (client, bridge):
            flat = await client.call_tool(
                "gimp_export_as", {"image": iid(1), "path": str(tmp_path / "a.tif"), "layers": "flatten"}
            )
            kept = await client.call_tool("gimp_export_as", {"image": iid(1), "path": str(tmp_path / "b.tif")})
        for result in (flat, kept):
            assert result.is_error and result.structured_content["error"]["code"] == "PLUGIN_VERSION_MISMATCH"
            assert "gimp-mcp install-plugin" in result.structured_content["error"]["hint"]
        assert bridge.calls == []


async def test_flatten_is_sent_to_the_plugin(tmp_path):
    async with tool_client({"image.export_as": lambda p: EXPORTED}) as (client, bridge):
        result = await client.call_tool(
            "gimp_export_as", {"image": iid(1), "path": str(tmp_path / "a.tif"), "layers": "flatten"}
        )
    assert not result.is_error, result.content
    assert bridge.calls[0][1]["layers"] == "flatten"


async def test_an_explicit_color_profile_choice_is_sent(tmp_path):
    async with tool_client({"image.export_as": lambda p: EXPORTED}) as (client, bridge):
        await client.call_tool(
            "gimp_export_as", {"image": iid(1), "path": str(tmp_path / "a.webp"), "color_profile": True}
        )
        await client.call_tool("gimp_export_as", {"image": iid(1), "path": str(tmp_path / "b.webp")})
    assert [params["color_profile"] for _name, params in bridge.calls] == [True, None]


async def test_layer_exports_follow_the_path_rules_of_the_os(tmp_path, monkeypatch):
    # A network directory made os.path.isdir contact the server before anything was checked (#122).
    from gimp_mcp import platforms

    async with tool_client({}) as (client, bridge):
        monkeypatch.setattr(platforms, "CURRENT", "windows")
        for directory in (r"\\attacker\share\out", r"\\?\C:\out"):
            result = await client.call_tool("gimp_export_layers", {"image": iid(1), "directory": directory})
            assert error_code(result) == "INVALID_ARGUMENT", directory
        assert bridge.calls == []


async def test_the_default_layer_template_and_widths_are_accepted(tmp_path):
    exported = {"path": str(tmp_path / "00-a.png"), "item": 2, "procedure": "file-png-export", "bytes": 1,
                "lossless": True, "layers": "flattened", "options": {}}  # fmt: skip
    files = {"files": [exported]}
    async with tool_client({"image.export_layers": lambda p: files}) as (client, _bridge):
        for template in ("{index:02d}-{name}", "layer {index:>3}", "{name}"):
            result = await client.call_tool(
                "gimp_export_layers", {"image": iid(1), "directory": str(tmp_path), "template": template}
            )
            assert not result.is_error, (template, result.content)

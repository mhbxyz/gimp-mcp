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
        nothing = await client.call_tool("gimp_open_with_options", {"path": str(tmp_path / "none.pdf")})
        assert error_code(nothing) == "FILE_NOT_FOUND"
        assert bridge.calls == []


@pytest.mark.parametrize("mode", ["export", "import"])
async def test_describe_needs_an_extension_or_a_procedure(mode):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_describe_file_format", {"mode": mode})
        assert result.is_error and bridge.calls == []

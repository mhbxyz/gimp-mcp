"""Default tools point to the optional tools that cover related needs (#148)."""

from __future__ import annotations

import anyio
import pytest
from mcp import Client

from gimp_mcp.bridge import BridgeClient
from gimp_mcp.server import build_server

from .fake_bridge import running_fake_bridge
from .tool_harness import iid


def default_descriptions() -> dict[str, str]:
    async def run() -> dict[str, str]:
        async with Client(build_server(env={})) as client:
            return {tool.name: tool.description or "" for tool in (await client.list_tools()).tools}

    return anyio.run(run)


@pytest.mark.parametrize(
    ("tool", "pointer", "toolset"),
    [
        ("gimp_export_image", "gimp_export_as", "formats"),
        ("gimp_open_image", "gimp_open_with_options", "formats"),
        ("gimp_gaussian_blur", "gimp_apply_filter", "effects"),
        ("gimp_hue_saturation", "gimp_levels", "color"),
        ("gimp_select_ellipse", "gimp_select_by_color", "channels"),
        ("gimp_create_text_layer", "gimp_set_text_style", "typography"),
        ("gimp_rotate_layer", "gimp_transform", "geometry"),
    ],
)
def test_a_default_tool_names_the_optional_tool_and_its_toolset(tool, pointer, toolset):
    description = default_descriptions()[tool]
    assert pointer in description and f"toolset {toolset}" in description, description


async def test_an_unsupported_export_points_to_gimp_export_as(tmp_path):
    with running_fake_bridge({}) as bridge:
        async with Client(build_server(BridgeClient(bridge.endpoint))) as client:
            result = await client.call_tool("gimp_export_image", {"image": iid(1), "path": str(tmp_path / "a.webp")})
    error = result.structured_content["error"]
    assert error["code"] == "UNSUPPORTED_FORMAT"
    assert "gimp_export_as" in error["hint"] and "formats" in error["hint"] and "gimp_enable_toolsets" in error["hint"]

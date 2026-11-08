"""Toolsets (#45) against a real GIMP through `gimp-mcp serve` over stdio."""

from __future__ import annotations

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call


async def test_default_toolsets_then_enabling_procedures_during_the_session(gimp: HeadlessGimp):
    async with mcp_client(gimp, {"GIMP_MCP_TOOLSETS": "default"}) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        assert "gimp_create_image" in listed and "gimp_call_procedure" not in listed

        enabled = await call(client, "gimp_enable_toolsets", toolsets=["procedures"])
        assert "gimp_call_procedure" in enabled["added_tools"]
        assert "gimp_call_procedure" in {tool.name for tool in (await client.list_tools()).tools}

        image = (await call(client, "gimp_create_image", width=8, height=8, resolution=144))["id"]
        result = await call(client, "gimp_call_procedure", name="gimp-image-get-resolution", arguments={"image": image})
        assert result["results"] == {"xresolution": 144.0, "yresolution": 144.0}


async def test_narrow_toolsets_hide_everything_else(gimp: HeadlessGimp):
    async with mcp_client(gimp, {"GIMP_MCP_TOOLSETS": "text"}) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        assert {"gimp_status", "gimp_create_text_layer", "gimp_enable_toolsets"} <= listed
        assert "gimp_create_layer" not in listed
        status = await call(client, "gimp_status")
        assert status["connected"]

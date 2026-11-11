"""Deprecated tools and parameters keep working and say so on every call (#117, ADR 0011)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from mcp import Client
from pydantic import BaseModel, Field

from gimp_mcp.bridge import BridgeClient
from gimp_mcp.contract import collect_contract, compare
from gimp_mcp.server import build_server
from gimp_mcp.toolkit import MUTATING, Deprecation, Toolkit

from .fake_bridge import running_fake_bridge


class Echo(BaseModel):
    value: int


def register_test_tools(kit: Toolkit) -> None:
    @kit.tool(
        toolset="core",
        name="gimp_test_scale",
        title="Test",
        description="Scale something.",
        annotations=MUTATING,
        aliases={"gimp_test_resize": "0.7.0"},
        deprecated_parameters={"factor": Deprecation("0.7.0", "use percent")},
    )
    async def gimp_test_scale(
        percent: int = 100,
        factor: Annotated[float | None, Field(description="Deprecated: use percent.")] = None,
    ) -> Echo:
        return Echo(value=round(factor * 100) if factor is not None else percent)

    @kit.tool(
        toolset="core",
        name="gimp_test_old_way",
        title="Old",
        description="The old way.",
        annotations=MUTATING,
        deprecated=Deprecation("0.7.0", "use gimp_test_scale"),
    )
    async def gimp_test_old_way() -> Echo:
        return Echo(value=1)


@asynccontextmanager
async def client() -> AsyncIterator[Client]:
    with running_fake_bridge({}) as bridge:
        server = build_server(BridgeClient(bridge.endpoint))
        register_test_tools(server.gimp_toolkit)  # type: ignore[attr-defined]
        async with Client(server) as connected:
            yield connected


def notices(result: Any) -> list[dict[str, str]]:
    return (result.meta or {}).get("io.github.mhbxyz/deprecations", [])


async def test_a_renamed_tool_keeps_working_under_its_old_name_with_a_notice():
    async with client() as c:
        tools = {tool.name: tool for tool in (await c.list_tools()).tools}
        old = await c.call_tool("gimp_test_resize", {"percent": 50})
        new = await c.call_tool("gimp_test_scale", {"percent": 50})
    assert (tools["gimp_test_resize"].description or "").startswith("Deprecated since 0.7.0: use gimp_test_scale")
    assert tools["gimp_test_resize"].input_schema == tools["gimp_test_scale"].input_schema
    assert old.structured_content == new.structured_content == {"value": 50}
    [notice] = notices(old)
    assert notice == {
        "name": "gimp_test_resize",
        "since": "0.7.0",
        "removal": "1.0.0",
        "replacement": "use gimp_test_scale (same arguments and result)",
    }
    assert any("gimp_test_resize is deprecated" in getattr(block, "text", "") for block in old.content)
    assert notices(new) == []


async def test_a_deprecated_tool_says_so_on_every_call():
    async with client() as c:
        tools = {tool.name: tool for tool in (await c.list_tools()).tools}
        first = await c.call_tool("gimp_test_old_way", {})
        second = await c.call_tool("gimp_test_old_way", {})
    assert (tools["gimp_test_old_way"].description or "").startswith("Deprecated since 0.7.0: use gimp_test_scale.")
    assert [n["name"] for n in notices(first)] == [n["name"] for n in notices(second)] == ["gimp_test_old_way"]


async def test_a_deprecated_parameter_still_works_and_is_marked_in_the_schema():
    async with client() as c:
        tools = {tool.name: tool for tool in (await c.list_tools()).tools}
        old = await c.call_tool("gimp_test_scale", {"factor": 0.5})
        new = await c.call_tool("gimp_test_scale", {"percent": 50})
    assert tools["gimp_test_scale"].input_schema["properties"]["factor"]["deprecated"] is True
    assert old.structured_content == new.structured_content == {"value": 50}
    assert [(n["name"], n["replacement"]) for n in notices(old)] == [("gimp_test_scale.factor", "use percent")]
    assert notices(new) == []


def test_the_contract_records_deprecations_and_a_new_one_is_compatible():
    contract = collect_contract()
    before = {"tools": {"gimp_x": {"toolset": "core", "annotations": {}, "inputSchema": {"type": "object"}}}}
    after = {"tools": {"gimp_x": {**before["tools"]["gimp_x"], "deprecated": {"since": "0.7.0", "replacement": "y"}}}}
    assert [(c.kind, c.what) for c in compare(before, after)] == [("compatible", "deprecated since 0.7.0: y")]
    assert all("deprecated" not in tool for tool in contract["tools"].values())  # none yet in the real API

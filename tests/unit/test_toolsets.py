"""Toolsets (#45): every tool belongs to a documented toolset, clients load only what they need."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import mcp_types as types
import pytest
from mcp import Client

from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.server import build_server
from gimp_mcp.toolkit import READ_ONLY, Toolkit
from gimp_mcp.toolsets import (
    DEFAULT_MAX_SCHEMA_BYTES,
    DEFAULT_MAX_TOOLS,
    DEFAULT_TOOLSETS,
    TOOLSETS,
    ToolsetError,
    collect_report,
    resolve_toolsets,
    toolset_report,
)

ROOT = Path(__file__).resolve().parents[2]


def offline_server(toolsets: str | None = None, env: dict[str, str] | None = None):
    bridge = BridgeClient(BridgeEndpoint.for_socket(Path("/nonexistent/bridge.sock")))
    return build_server(bridge, toolsets=toolsets, env=env or {})


async def listed(server) -> set[str]:
    async with Client(server) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


def test_every_tool_belongs_to_a_known_toolset_and_sizes_are_reported(capsys):
    report = toolset_report()
    catalog = {tool for entry in report for tool in entry.tools}
    assert {entry.name for entry in report} == set(TOOLSETS)
    assert all(entry.tools for entry in report), "empty toolset"
    assert len(catalog) == sum(len(entry.tools) for entry in report)  # one toolset per tool
    print("\ntoolset            tools   schema bytes")
    for entry in report:
        print(f"{entry.name:18s} {len(entry.tools):5d} {entry.schema_bytes:14d}")
    assert "core" in capsys.readouterr().out


def test_a_tool_without_a_toolset_cannot_be_registered():
    kit = Toolkit(offline_server(), BridgeClient(BridgeEndpoint.for_socket(Path("/x"))))
    with pytest.raises(TypeError):
        kit.tool(name="gimp_x", title="X", description="x", annotations=READ_ONLY)  # type: ignore[call-arg]
    with pytest.raises(ToolsetError, match="unknown toolset 'nope'"):
        kit.tool(name="gimp_x", title="X", description="x", annotations=READ_ONLY, toolset="nope")


async def test_default_server_lists_the_default_toolsets_within_the_budget():
    report = {entry.name: entry for entry in await collect_report()}
    expected = {tool for name in DEFAULT_TOOLSETS for tool in report[name].tools}
    assert await listed(offline_server()) == expected
    assert len(expected) <= DEFAULT_MAX_TOOLS
    assert sum(report[name].schema_bytes for name in DEFAULT_TOOLSETS) <= DEFAULT_MAX_SCHEMA_BYTES


@pytest.mark.parametrize(
    ("spec", "included", "excluded"),
    [
        ("core,text", {"gimp_status", "gimp_create_text_layer"}, {"gimp_create_layer", "gimp_call_procedure"}),
        ("text", {"gimp_status", "gimp_list_toolsets", "gimp_set_text"}, {"gimp_fill"}),  # core is always on
        ("all", {"gimp_call_procedure", "gimp_fill"}, set()),
        ("default,procedures", {"gimp_call_procedure", "gimp_create_layer"}, set()),
        (" Files , layers ", {"gimp_open_image", "gimp_move_layer"}, {"gimp_set_text"}),
    ],
)
async def test_toolsets_are_selected_by_option(spec, included, excluded):
    names = await listed(offline_server(toolsets=spec))
    assert included <= names
    assert not (excluded & names)


async def test_toolsets_are_selected_by_environment_and_the_option_wins():
    assert "gimp_set_text" not in await listed(offline_server(env={"GIMP_MCP_TOOLSETS": "layers"}))
    assert "gimp_set_text" in await listed(offline_server(toolsets="text", env={"GIMP_MCP_TOOLSETS": "layers"}))


def test_unknown_toolsets_are_rejected_with_the_valid_names():
    with pytest.raises(ToolsetError) as error:
        resolve_toolsets("layers,brushes")
    assert "brushes" in str(error.value) and "procedures" in str(error.value)
    with pytest.raises(ToolsetError):
        resolve_toolsets("")


async def test_list_toolsets_describes_every_toolset():
    async with Client(offline_server(toolsets="text")) as client:
        result = await client.call_tool("gimp_list_toolsets", {})
    assert not result.is_error
    toolsets = {entry["name"]: entry for entry in result.structured_content["toolsets"]}
    assert set(toolsets) == set(TOOLSETS)
    assert toolsets["text"]["enabled"] and not toolsets["layers"]["enabled"]
    assert "gimp_create_layer" in toolsets["layers"]["tools"]
    assert toolsets["layers"]["description"]


async def test_enabling_toolsets_at_runtime_adds_tools_and_notifies_legacy_clients():
    notifications: list[object] = []

    async def on_message(message: object) -> None:
        notifications.append(message)

    async with Client(offline_server(toolsets="core"), mode="legacy", message_handler=on_message) as client:
        assert client.session.server_capabilities.tools.list_changed  # type: ignore[union-attr]
        before = {tool.name for tool in (await client.list_tools()).tools}
        assert "gimp_create_layer" not in before
        result = await client.call_tool("gimp_enable_toolsets", {"toolsets": ["layers", "text"]})
        assert not result.is_error, result.content
        assert "gimp_create_layer" in result.structured_content["added_tools"]
        assert {"core", "layers", "text"} <= set(result.structured_content["enabled"])
        after = {tool.name for tool in (await client.list_tools()).tools}
        assert {"gimp_create_layer", "gimp_set_text"} <= after
    assert any(isinstance(n, types.ToolListChangedNotification) for n in notifications), notifications


async def test_enabling_toolsets_notifies_listening_clients():
    async with Client(offline_server(toolsets="core")) as client:
        async with client.listen(tools_list_changed=True) as subscription:
            await client.call_tool("gimp_enable_toolsets", {"toolsets": ["paint"]})
            async for _event in subscription:
                break
        assert "gimp_fill" in {tool.name for tool in (await client.list_tools()).tools}


async def test_enabling_an_enabled_or_unknown_toolset():
    async with Client(offline_server(toolsets="text")) as client:
        again = await client.call_tool("gimp_enable_toolsets", {"toolsets": ["text"]})
        assert again.structured_content["added_tools"] == []
        bad = await client.call_tool("gimp_enable_toolsets", {"toolsets": ["brushes"]})
        assert bad.is_error and bad.structured_content["error"]["code"] == "INVALID_ARGUMENT"


def test_serve_rejects_unknown_toolsets_before_starting():
    proc = subprocess.run(
        [sys.executable, "-m", "gimp_mcp", "serve", "--toolsets", "layers,brushes"],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert proc.returncode == 2 and "brushes" in proc.stderr and proc.stdout == ""


def test_toolsets_command_prints_the_catalog():
    proc = subprocess.run([sys.executable, "-m", "gimp_mcp", "toolsets"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    for name in TOOLSETS:
        assert re.search(rf"^{name}\b", proc.stdout, re.M), name


def test_documentation_lists_every_toolset_with_its_tools():
    doc = (ROOT / "docs" / "toolsets.md").read_text()
    for entry in toolset_report():
        section = re.search(rf"^### `{entry.name}`.*?(?=^### |\Z)", doc, re.M | re.S)
        assert section, entry.name
        documented = set(re.findall(r"`(gimp_[a-z_]+)`", section.group(0)))
        assert documented == set(entry.tools), (entry.name, documented ^ set(entry.tools))
    assert "GIMP_MCP_TOOLSETS" in doc and "--toolsets" in doc


def _titles(schema: object, path: str = "") -> list[str]:
    """Paths of `title` keywords (not properties named title) in a schema."""
    found: list[str] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "title" and isinstance(value, str):
                found.append(path or "(root)")
            elif key in ("properties", "$defs") and isinstance(value, dict):
                for name, sub in value.items():
                    found += _titles(sub, f"{path}.{name}")
            else:
                found += _titles(value, path)
    elif isinstance(schema, list):
        for item in schema:
            found += _titles(item, path)
    return found


async def test_schemas_carry_no_generated_titles():
    """They repeat the property names: a sixth of the default budget (docs/toolsets.md#budget)."""
    async with Client(offline_server(toolsets="all")) as client:
        tools = (await client.list_tools()).tools
    with_titles = {t.name: _titles(t.input_schema) + _titles(t.output_schema) for t in tools}
    assert {name: paths for name, paths in with_titles.items() if paths} == {}

"""The coverage matrix stays consistent with the tools and the committed inventory."""

from __future__ import annotations

import json
from pathlib import Path

from mcp import Client

from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.coverage import CAPABILITIES, Inventory, all_tools, referenced_procedures, render_matrix
from gimp_mcp.server import build_server

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "coverage" / "pdb-inventory.json"


async def registered_tools() -> set[str]:
    server = build_server(BridgeClient(BridgeEndpoint.for_socket(Path("/nonexistent.sock"))), toolsets="all")
    async with Client(server) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


async def test_every_mcp_tool_is_in_the_matrix_and_vice_versa():
    tools = await registered_tools()
    assert tools - all_tools() == set(), "add these tools to src/gimp_mcp/coverage.py"
    assert all_tools() - tools == set(), "the matrix lists tools that do not exist"


def test_every_referenced_procedure_exists_in_the_committed_inventory():
    inventory = Inventory.load(INVENTORY)
    assert referenced_procedures() - set(inventory.procedures) == set()


def test_tested_capabilities_point_to_existing_test_files():
    for capability in CAPABILITIES:
        if capability.status == "tested":
            assert capability.tests, capability.name
        for test in capability.tests:
            assert (ROOT / test).exists(), test


def test_committed_matrix_is_up_to_date():
    expected = render_matrix(INVENTORY)
    assert (ROOT / "docs" / "coverage.md").read_text(encoding="utf-8") == expected, (
        "run: uv run gimp-mcp coverage --inventory docs/coverage/pdb-inventory.json --output docs/coverage.md"
    )


def test_missing_procedures_are_reported_as_version_dependent(tmp_path):
    fake = tmp_path / "inventory.json"
    fake.write_text(json.dumps({"gimp_version": "9.9", "procedures": [{"name": "gimp-image-new"}]}))
    text = render_matrix(fake)
    assert "GIMP **9.9**" in text
    assert "- `gimp-image-scale`" in text

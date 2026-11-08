"""In-process MCP client wired to the real bridge socket server with scripted ops."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client

from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.server import build_server

from .fake_bridge import FakeBridge, Op, running_fake_bridge

SESSION = "a1b2c3d4"


def iid(n: int) -> str:
    return f"image:{n}@{SESSION}"


def tid(n: int) -> str:
    return f"item:{n}@{SESSION}"


@asynccontextmanager
async def tool_client(ops: dict[str, Op]) -> AsyncIterator[tuple[Client, FakeBridge]]:
    with running_fake_bridge(ops) as bridge:
        server = build_server(BridgeClient(BridgeEndpoint.for_socket(bridge.socket_path)), toolsets="all")
        async with Client(server) as client:
            yield client, bridge


def error_code(result: Any) -> str:
    assert result.is_error, result.content
    return result.structured_content["error"]["code"]

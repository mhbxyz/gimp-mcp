"""Plumbing shared by every MCP tool: bridge calls, ids and result shaping."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, ContentBlock, TextContent, ToolAnnotations
from pydantic import BaseModel

from .bridge import BridgeClient
from .errors import GimpMcpError
from .ids import IdCodec
from .toolsets import DEFAULT_TOOLSETS, check_toolset

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


class ToolResult(Generic[ModelT]):
    """A tool's structured output plus optional extra content blocks (e.g. an image)."""

    def __init__(self, data: ModelT, extra_content: list[ContentBlock] | None = None):
        self.data = data
        self.extra_content = extra_content or []


def error_result(error: GimpMcpError) -> CallToolResult:
    payload = {"error": error.to_dict()}
    text = f"{error.code}: {error.message}"
    if error.hint:
        text += f"\nHint: {error.hint}"
    if error.outcome == "unknown":
        text += "\nOutcome: unknown - the change may or may not have been applied; inspect before retrying."
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=payload, is_error=True)


def success_result(data: BaseModel, extra: list[ContentBlock] | None = None) -> CallToolResult:
    structured = data.model_dump(mode="json")
    content: list[ContentBlock] = [TextContent(type="text", text=data.model_dump_json(exclude_none=True))]
    content.extend(extra or [])
    return CallToolResult(content=content, structured_content=structured)


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
MUTATING = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)


@dataclass
class CatalogEntry:
    """A registered tool, listed by the server only while its toolset is enabled."""

    name: str
    toolset: str
    register: Callable[[], None]
    listed: bool = False


class Toolkit:
    def __init__(self, mcp: MCPServer, bridge: BridgeClient, toolsets: Iterable[str] = DEFAULT_TOOLSETS):
        self.mcp = mcp
        self.bridge = bridge
        self.enabled: set[str] = {check_toolset(name) for name in toolsets}
        self.catalog: dict[str, CatalogEntry] = {}

    async def codec(self) -> IdCodec:
        session = await self.bridge.connect()
        return IdCodec(session.session_id)

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        codec: IdCodec | None = None,
        mutating: bool = False,
        timeout: float | None = None,
    ) -> Any:
        """Call a bridge operation, pinned to the session the ids were parsed in."""
        payload = dict(params or {})
        if codec is not None:
            payload["_session"] = codec.session_id
        return await self.bridge.call(method, payload, mutating=mutating, timeout=timeout)

    def enable(self, toolsets: Iterable[str]) -> list[str]:
        """Enable toolsets; returns the tools that were added to the server's list."""
        names = [check_toolset(name) for name in toolsets]
        self.enabled.update(names)
        added = []
        for entry in self.catalog.values():
            if entry.toolset in self.enabled and not entry.listed:
                entry.register()
                entry.listed = True
                added.append(entry.name)
        return added

    def tool(
        self,
        *,
        name: str,
        title: str,
        description: str,
        annotations: ToolAnnotations,
        toolset: str,
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Register an async tool that returns a pydantic model (or ToolResult).

        The tool is listed by the server only while ``toolset`` is enabled.
        ``GimpMcpError`` becomes a structured error result
        (``structuredContent = {"error": {...}}``, ``isError = true``).
        """
        check_toolset(toolset)

        def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            @functools.wraps(fn)
            async def wrapper(*args: Any, **kwargs: Any) -> CallToolResult:
                try:
                    value = await fn(*args, **kwargs)
                except GimpMcpError as error:
                    log.info("tool %s failed: %s", name, error)
                    return error_result(error)
                if isinstance(value, ToolResult):
                    return success_result(value.data, value.extra_content)
                return success_result(value)

            def register() -> None:
                self.mcp.add_tool(wrapper, name=name, title=title, description=description, annotations=annotations)

            if name in self.catalog:
                raise ValueError(f"tool {name} registered twice")
            entry = CatalogEntry(name, toolset, register)
            self.catalog[name] = entry
            if toolset in self.enabled:
                register()
                entry.listed = True
            return fn

        return decorator

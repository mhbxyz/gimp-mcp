"""Plumbing shared by every MCP tool: bridge calls, ids and result shaping."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, ContentBlock, TextContent, ToolAnnotations
from pydantic import BaseModel

from .bridge import BridgeClient
from .errors import GimpMcpError
from .ids import IdCodec
from .toolsets import DEFAULT_TOOLSETS, check_toolset

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

# The MCP request being served (set by GimpServer.call_tool), so tools and bridge calls can send
# notifications without taking a Context argument.
current_context: ContextVar[Context | None] = ContextVar("gimp_mcp_context", default=None)
# True inside a batch, which reports its own progress and resource changes: bridge calls then send
# no heartbeat (the progress values of a request must increase) and nested tools no notification.
_in_batch: ContextVar[bool] = ContextVar("gimp_mcp_in_batch", default=False)
HEARTBEAT_SECONDS = 1.0


@contextlib.contextmanager
def inside_batch() -> Iterator[None]:
    token = _in_batch.set(True)
    try:
        yield
    finally:
        _in_batch.reset(token)


async def notify_resources_changed(ctx: Context) -> None:
    """Tell the client the resource list changed: subscription stream and legacy notification."""
    try:
        await ctx.notify_resources_changed()
    except Exception as error:  # no subscription bus on this connection
        log.debug("no listen subscribers: %s", error)
    try:
        await ctx.request_context.session.send_resource_list_changed()
    except Exception as error:  # not a legacy session
        log.debug("legacy resources/list_changed not sent: %s", error)


async def _heartbeat(ctx: Context, method: str, started: float) -> None:
    """Progress every second while GIMP works (elapsed seconds; GIMP reports no fraction)."""
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        elapsed = round(time.monotonic() - started, 1)
        try:
            await ctx.report_progress(elapsed, None, f"waiting for GIMP ({method}, {elapsed:.0f} s)")
        except Exception as error:  # the client went away: the call itself reports it
            log.debug("progress not sent: %s", error)
            return


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
    handler: Callable[..., Awaitable[Any]] | None = None


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
        ctx = current_context.get()
        if ctx is None or _in_batch.get():
            return await self.bridge.call(method, payload, mutating=mutating, timeout=timeout)
        beat = asyncio.ensure_future(_heartbeat(ctx, method, time.monotonic()))
        try:
            return await self.bridge.call(method, payload, mutating=mutating, timeout=timeout)
        finally:
            beat.cancel()

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
        changes_images: bool = False,
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Register an async tool that returns a pydantic model (or ToolResult).

        The tool is listed by the server only while ``toolset`` is enabled.
        ``GimpMcpError`` becomes a structured error result
        (``structuredContent = {"error": {...}}``, ``isError = true``).
        ``changes_images``: the tool can open or close images; on success the client is told
        that the resource list (``gimp://images/...``) changed.
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
                ctx = current_context.get()
                if changes_images and ctx is not None and not _in_batch.get():
                    await notify_resources_changed(ctx)
                if isinstance(value, ToolResult):
                    return success_result(value.data, value.extra_content)
                return success_result(value)

            def register() -> None:
                self.mcp.add_tool(wrapper, name=name, title=title, description=description, annotations=annotations)

            if name in self.catalog:
                raise ValueError(f"tool {name} registered twice")
            entry = CatalogEntry(name, toolset, register, handler=wrapper)
            self.catalog[name] = entry
            if toolset in self.enabled:
                register()
                entry.listed = True
            return fn

        return decorator

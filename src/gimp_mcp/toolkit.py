"""Plumbing shared by every MCP tool: bridge calls, ids and result shaping."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
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


# Key of the deprecation notices in a result's ``_meta`` (ADR 0011).
DEPRECATIONS_META = "io.github.mhbxyz/deprecations"


@dataclass(frozen=True)
class Deprecation:
    """A deprecated tool or parameter (ADR 0011): it keeps working until ``removal`` (the next major
    version after ``since``) and every call using it returns a notice naming ``replacement``."""

    since: str
    replacement: str

    @property
    def removal(self) -> str:
        return f"{int(self.since.split('.')[0]) + 1}.0.0"

    def notice(self, name: str) -> dict[str, str]:
        return {"name": name, "since": self.since, "removal": self.removal, "replacement": self.replacement}


def _with_notices(result: CallToolResult, notices: list[dict[str, str]]) -> CallToolResult:
    if not notices:
        return result
    for notice in notices:
        text = (
            f"Deprecation notice: {notice['name']} is deprecated since {notice['since']} and will be removed in "
            f"{notice['removal']}: {notice['replacement']}."
        )
        result.content.append(TextContent(type="text", text=text))
    result.meta = {**(result.meta or {}), DEPRECATIONS_META: notices}
    return result


def error_result(error: GimpMcpError, notices: list[dict[str, str]] | None = None) -> CallToolResult:
    payload = {"error": error.to_dict()}
    text = f"{error.code}: {error.message}"
    if error.hint:
        text += f"\nHint: {error.hint}"
    if error.outcome == "unknown":
        text += "\nOutcome: unknown - the change may or may not have been applied; inspect before retrying."
    result = CallToolResult(content=[TextContent(type="text", text=text)], structured_content=payload, is_error=True)
    return _with_notices(result, notices or [])


def success_result(
    data: BaseModel, extra: list[ContentBlock] | None = None, notices: list[dict[str, str]] | None = None
) -> CallToolResult:
    structured = data.model_dump(mode="json")
    content: list[ContentBlock] = [TextContent(type="text", text=data.model_dump_json(exclude_none=True))]
    content.extend(extra or [])
    return _with_notices(CallToolResult(content=content, structured_content=structured), notices or [])


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
    deprecation: Deprecation | None = None
    deprecated_parameters: dict[str, Deprecation] = field(default_factory=dict)


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
        revision: int = 1,
    ) -> Any:
        """Call a bridge operation, pinned to the session the ids were parsed in.

        ``revision``: the plug-in revision of ``method`` this call needs (gmb_ops.REVISIONS); an older
        plug-in is refused with PLUGIN_VERSION_MISMATCH before anything is sent."""
        payload = dict(params or {})
        if codec is not None:
            payload["_session"] = codec.session_id
        ctx = current_context.get()
        if ctx is None or _in_batch.get():
            return await self.bridge.call(method, payload, mutating=mutating, timeout=timeout, revision=revision)
        beat = asyncio.ensure_future(_heartbeat(ctx, method, time.monotonic()))
        try:
            return await self.bridge.call(method, payload, mutating=mutating, timeout=timeout, revision=revision)
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
        deprecated: Deprecation | None = None,
        aliases: dict[str, str] | None = None,
        deprecated_parameters: dict[str, Deprecation] | None = None,
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Register an async tool that returns a pydantic model (or ToolResult).

        The tool is listed by the server only while ``toolset`` is enabled.
        ``GimpMcpError`` becomes a structured error result
        (``structuredContent = {"error": {...}}``, ``isError = true``).
        ``changes_images``: the tool can open or close images; on success the client is told
        that the resource list (``gimp://images/...``) changed.

        Deprecation (ADR 0011): ``deprecated`` marks the whole tool; ``aliases`` maps old names (a renamed
        tool) to the version that deprecated them, registered with the same arguments and result;
        ``deprecated_parameters`` maps parameter names to their deprecation, reported when a call passes
        them (not None). Every such call returns a notice in ``_meta`` and as text.
        """
        check_toolset(toolset)
        parameter_deprecations = deprecated_parameters or {}

        def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            def make_wrapper(tool_name: str, tool_deprecation: Deprecation | None) -> Callable[..., Awaitable[Any]]:
                @functools.wraps(fn)
                async def wrapper(*args: Any, **kwargs: Any) -> CallToolResult:
                    notices = [tool_deprecation.notice(tool_name)] if tool_deprecation else []
                    notices += [
                        deprecation.notice(f"{tool_name}.{parameter}")
                        for parameter, deprecation in parameter_deprecations.items()
                        if kwargs.get(parameter) is not None
                    ]
                    if notices:
                        log.warning("deprecated: %s", ", ".join(notice["name"] for notice in notices))
                    try:
                        value = await fn(*args, **kwargs)
                    except GimpMcpError as error:
                        log.info("tool %s failed: %s", tool_name, error)
                        return error_result(error, notices)
                    ctx = current_context.get()
                    if changes_images and ctx is not None and not _in_batch.get():
                        await notify_resources_changed(ctx)
                    if isinstance(value, ToolResult):
                        return success_result(value.data, value.extra_content, notices)
                    return success_result(value, notices=notices)

                return wrapper

            def add(tool_name: str, tool_description: str, tool_deprecation: Deprecation | None) -> None:
                wrapper = make_wrapper(tool_name, tool_deprecation)

                def register() -> None:
                    self.mcp.add_tool(
                        wrapper, name=tool_name, title=title, description=tool_description, annotations=annotations
                    )
                    tool = self.mcp._tool_manager.get_tool(tool_name)  # pyright: ignore[reportPrivateUsage]
                    assert tool is not None
                    for parameter in parameter_deprecations:
                        tool.parameters["properties"][parameter]["deprecated"] = True

                if tool_name in self.catalog:
                    raise ValueError(f"tool {tool_name} registered twice")
                entry = CatalogEntry(
                    tool_name,
                    toolset,
                    register,
                    handler=wrapper,
                    deprecation=tool_deprecation,
                    deprecated_parameters=dict(parameter_deprecations),
                )
                self.catalog[tool_name] = entry
                if toolset in self.enabled:
                    register()
                    entry.listed = True

            prefix = f"Deprecated since {deprecated.since}: {deprecated.replacement}. " if deprecated else ""
            add(name, prefix + description, deprecated)
            for old_name, since in (aliases or {}).items():
                alias = Deprecation(since, f"use {name} (same arguments and result)")
                add(old_name, f"Deprecated since {since}: use {name} (same arguments and result). {description}", alias)
            return fn

        return decorator

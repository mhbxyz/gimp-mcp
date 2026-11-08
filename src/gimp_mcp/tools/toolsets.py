"""Toolset management tools (always enabled, in ``core``)."""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from ..errors import GimpMcpError
from ..toolkit import MUTATING, READ_ONLY, Toolkit
from ..toolsets import ENV_VAR, TOOLSETS, ToolsetError

log = logging.getLogger(__name__)


class ToolsetInfo(BaseModel):
    name: str
    description: str
    enabled: bool
    tools: list[str]


class ToolsetList(BaseModel):
    toolsets: list[ToolsetInfo]


class EnabledToolsets(BaseModel):
    enabled: list[str] = Field(description="Toolsets enabled now.")
    added_tools: list[str] = Field(description="Tools added to the tool list by this call.")


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="core",
        name="gimp_list_toolsets",
        title="List toolsets",
        description=(
            "List the groups of GIMP tools (toolsets), what each contains and which are enabled. Tools of "
            "disabled toolsets are not in your tool list: enable them with gimp_enable_toolsets."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_list_toolsets() -> ToolsetList:
        tools: dict[str, list[str]] = {name: [] for name in TOOLSETS}
        for entry in kit.catalog.values():
            tools[entry.toolset].append(entry.name)
        return ToolsetList(
            toolsets=[
                ToolsetInfo(name=name, description=text, enabled=name in kit.enabled, tools=tools[name])
                for name, text in TOOLSETS.items()
            ]
        )

    @kit.tool(
        toolset="core",
        name="gimp_enable_toolsets",
        title="Enable toolsets",
        description=(
            "Add the tools of one or more toolsets (see gimp_list_toolsets) to your tool list for this session. "
            "The server notifies the client that its tool list changed; a client that does not refresh its "
            f"tool list needs a restart with the toolsets in --toolsets or {ENV_VAR}."
        ),
        annotations=MUTATING,
    )
    async def gimp_enable_toolsets(
        toolsets: Annotated[list[str], Field(min_length=1, description="Toolset names.")],
        ctx: Context,
    ) -> EnabledToolsets:
        try:
            added = kit.enable(toolsets)
        except ToolsetError as error:
            raise GimpMcpError("INVALID_ARGUMENT", str(error), outcome="not_applied") from error
        if added:
            await notify_tools_changed(ctx)
        return EnabledToolsets(enabled=[name for name in TOOLSETS if name in kit.enabled], added_tools=added)


async def notify_tools_changed(ctx: Context) -> None:
    """Tell the client to refetch tools: subscription stream (2026 protocol) and legacy notification."""
    try:
        await ctx.notify_tools_changed()
    except Exception as error:  # no subscription bus on this connection
        log.debug("no listen subscribers: %s", error)
    try:
        await ctx.request_context.session.send_tool_list_changed()
    except Exception as error:  # not a legacy session
        log.debug("legacy tools/list_changed not sent: %s", error)

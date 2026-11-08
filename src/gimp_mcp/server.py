"""MCP server assembly."""

from __future__ import annotations

import functools
import os
from collections.abc import Mapping
from typing import Any

from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import Resource as MCPResource

from . import __version__, mcp_resources, prompts
from .bridge import BridgeClient
from .toolkit import Toolkit, current_context
from .tools import (
    analysis,
    animation,
    batch,
    channels,
    color,
    compose,
    document,
    effects,
    files,
    filters,
    formats,
    geometry,
    history,
    inspect,
    layers,
    modes,
    paint,
    painting,
    paths,
    pdb,
    preview,
    procedures,
    resources,
    selection,
    session,
    text,
    transform,
    typography,
    vector,
)
from .tools import toolsets as toolset_tools
from .toolsets import toolsets_from

INSTRUCTIONS = """\
Tools to inspect and edit images in a running GIMP 3 session.
Start with gimp_status to get the open images and their ids. More tools (procedures, ...) are grouped in
toolsets: gimp_list_toolsets shows them, gimp_enable_toolsets adds them. Ids are opaque, bound to the current
GIMP session, and must be passed back verbatim. Errors carry a stable `code`; when `outcome` is
"unknown" the change may have been applied: inspect before retrying. Resources gimp://images and
gimp://images/{image}/layers|preview give the same state without tool calls; prompts describe common workflows.
"""


class GimpServer(MCPServer):
    """MCPServer with the request context available to tools, and per-image resources listed."""

    gimp_toolkit: Toolkit

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Context | None = None) -> Any:
        token = current_context.set(context)
        try:
            return await super().call_tool(name, arguments, context)
        finally:
            current_context.reset(token)

    async def list_resources(self) -> list[MCPResource]:
        return [*await super().list_resources(), *await mcp_resources.image_resources(self.gimp_toolkit)]


def build_server(
    bridge: BridgeClient | None = None,
    *,
    toolsets: str | None = None,
    env: Mapping[str, str] | None = None,
) -> MCPServer:
    """``toolsets``: the --toolsets option; when None, $GIMP_MCP_TOOLSETS, else the default toolsets.

    Raises ``ToolsetError`` for unknown toolset names.
    """
    selected = toolsets_from(toolsets, os.environ if env is None else env)
    mcp = GimpServer(name="gimp-mcp", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING")
    # Advertise tools.listChanged and resources.listChanged to clients using the initialize handshake:
    # gimp_enable_toolsets changes the tool list, opening and closing images the resource list.
    lowlevel = mcp._lowlevel_server  # pyright: ignore[reportPrivateUsage]
    lowlevel.create_initialization_options = functools.partial(  # type: ignore[method-assign]
        lowlevel.create_initialization_options, NotificationOptions(tools_changed=True, resources_changed=True)
    )
    kit = Toolkit(mcp, bridge or BridgeClient(), selected)
    mcp.gimp_toolkit = kit
    for module in (
        session,
        toolset_tools,
        inspect,
        preview,
        files,
        layers,
        transform,
        procedures,
        selection,
        paint,
        filters,
        text,
        pdb,
        history,
        analysis,
        color,
        effects,
        modes,
        paths,
        resources,
        compose,
        document,
        formats,
        painting,
        geometry,
        channels,
        vector,
        typography,
        animation,
        batch,
    ):
        module.register(kit)
    mcp_resources.register(kit)
    prompts.register(mcp)
    return mcp

"""MCP server assembly."""

from __future__ import annotations

import functools
import os
from collections.abc import Mapping
from typing import Any

from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import Resource as MCPResource
from pydantic import ValidationError

from . import __version__, mcp_resources, prompts
from .arguments import invalid_arguments, toolset_disabled
from .bridge import BridgeClient
from .toolkit import Toolkit, current_context, error_result
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
GIMP session, and must be passed back verbatim; a result's `id` is the image or item the call created or
changed. Errors carry a stable `code`; when `outcome` is
"unknown" the change may have been applied: inspect before retrying. Resources gimp://images and
gimp://images/{image}/layers|preview give the same state without tool calls; prompts describe common workflows.
"""


class GimpServer(MCPServer):
    """MCPServer with the request context available to tools, and per-image resources listed."""

    gimp_toolkit: Toolkit

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Context | None = None) -> Any:
        tool = self._tool_manager.get_tool(name)
        entry = self.gimp_toolkit.catalog.get(name)
        if tool is None and entry is not None:
            return error_result(toolset_disabled(name, entry.toolset))
        token = current_context.set(context)
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as error:
            # Arguments that do not match the schema: gimp-mcp's error, not the framework's text (#146).
            if tool is not None and isinstance(error.__cause__, ValidationError):
                return error_result(invalid_arguments(name, tool.parameters, arguments, error.__cause__))
            raise
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

"""MCP server assembly."""

from __future__ import annotations

import functools
import os
from collections.abc import Mapping

from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.mcpserver import MCPServer

from . import __version__
from .bridge import BridgeClient
from .toolkit import Toolkit
from .tools import (
    files,
    filters,
    history,
    inspect,
    layers,
    paint,
    pdb,
    preview,
    procedures,
    selection,
    session,
    text,
    transform,
)
from .tools import toolsets as toolset_tools
from .toolsets import toolsets_from

INSTRUCTIONS = """\
Tools to inspect and edit images in a running GIMP 3 session.
Start with gimp_status to get the open images and their ids. More tools (procedures, ...) are grouped in
toolsets: gimp_list_toolsets shows them, gimp_enable_toolsets adds them. Ids are opaque, bound to the current
GIMP session, and must be passed back verbatim. Errors carry a stable `code`; when `outcome` is
"unknown" the change may have been applied: inspect before retrying.
"""


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
    mcp = MCPServer(name="gimp-mcp", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING")
    # Advertise tools.listChanged to clients using the initialize handshake: gimp_enable_toolsets
    # changes the tool list during a session.
    lowlevel = mcp._lowlevel_server  # pyright: ignore[reportPrivateUsage]
    lowlevel.create_initialization_options = functools.partial(  # type: ignore[method-assign]
        lowlevel.create_initialization_options, NotificationOptions(tools_changed=True)
    )
    kit = Toolkit(mcp, bridge or BridgeClient(), selected)
    mcp.gimp_toolkit = kit  # type: ignore[attr-defined]
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
    ):
        module.register(kit)
    return mcp

"""MCP server assembly."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import __version__
from .bridge import BridgeClient
from .toolkit import Toolkit
from .tools import files, inspect, layers, preview, session

INSTRUCTIONS = """\
Tools to inspect and edit images in a running GIMP 3 session.
Start with gimp_status to get the open images and their ids. Ids are opaque, bound to the current
GIMP session, and must be passed back verbatim. Errors carry a stable `code`; when `outcome` is
"unknown" the change may have been applied: inspect before retrying.
"""


def build_server(bridge: BridgeClient | None = None) -> MCPServer:
    mcp = MCPServer(name="gimp-mcp", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING")
    kit = Toolkit(mcp, bridge or BridgeClient())
    session.register(kit)
    inspect.register(kit)
    preview.register(kit)
    files.register(kit)
    layers.register(kit)
    return mcp

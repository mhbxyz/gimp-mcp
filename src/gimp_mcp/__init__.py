"""MCP server for inspecting and editing GIMP 3 projects."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the `version` field of pyproject.toml.
    __version__ = version("gimp-mcp")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled tree
    __version__ = "0+unknown"

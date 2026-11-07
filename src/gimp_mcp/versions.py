"""Version compatibility between the MCP server and the GIMP plug-in.

Rule (also in docs/compatibility.md): the plug-in and the server must share
the same MAJOR.MINOR version. A different PATCH is compatible (a warning is
logged); anything else, including an unknown plug-in version, is refused with
PLUGIN_VERSION_MISMATCH.
"""

from __future__ import annotations

import enum


class Compatibility(enum.Enum):
    MATCH = "match"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"


def _major_minor_patch(version: str) -> tuple[int, int, int] | None:
    parts = version.strip().split(".")
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int("".join(ch for ch in parts[2] if ch.isdigit()) or "0")
    except ValueError:
        return None


def check_plugin_version(server: str, plugin: str | None) -> Compatibility:
    if plugin and plugin == server:
        return Compatibility.MATCH
    ours, theirs = _major_minor_patch(server), _major_minor_patch(plugin or "")
    if ours is None or theirs is None or ours[:2] != theirs[:2]:
        return Compatibility.INCOMPATIBLE
    return Compatibility.COMPATIBLE

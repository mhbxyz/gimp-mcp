"""Compatibility between the MCP server and the GIMP plug-in (docs/adr/0010-plugin-compatibility.md).

The plug-in may be older or newer than the server: what matters is the bridge protocol it speaks and the
operations it serves. Its ``hello`` reports ``protocol`` and, since 0.7.0, ``capabilities`` (every
operation with its revision). The server accepts any plug-in speaking a supported protocol; a call to an
operation the plug-in lacks, or serves at an older revision, fails with PLUGIN_VERSION_MISMATCH and
names the fix (``gimp-mcp install-plugin``, then restart GIMP).
"""

from __future__ import annotations

import ast
import enum
import functools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

# GIMP policy (docs/compatibility.md): the 3.2 series is guaranteed (verified by CI); newer versions are
# accepted as best effort until the gimp-next CI job passes on them; older ones are refused.
MIN_GIMP = (3, 2)
SUPPORTED_GIMP_SERIES = frozenset({(3, 2)})
GimpSupport = Literal["supported", "best_effort", "unsupported"]

# Bridge protocols this server speaks (the wire format, docs/bridge-protocol.md).
SUPPORTED_PROTOCOLS = frozenset({1})


class Compatibility(enum.Enum):
    MATCH = "match"  # same version as the server
    COMPATIBLE = "compatible"  # another version, serving every operation this server uses
    PARTIAL = "partial"  # some operations missing or older: the tools using them ask for a plug-in update
    INCOMPATIBLE = "incompatible"  # unsupported protocol: refused


@dataclass(frozen=True)
class PluginCheck:
    verdict: Compatibility
    # Operations of this server that the plug-in lacks or serves at an older revision; None when the
    # plug-in does not list its operations (before 0.7.0).
    missing: tuple[str, ...] | None = ()


def parse_version(text: str) -> tuple[int, ...]:
    """Leading numeric parts: '3.2.0-RC3' -> (3, 2, 0)."""
    parts: list[int] = []
    for piece in text.split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def gimp_support(version: str) -> GimpSupport:
    series = parse_version(version)[:2]
    if series < MIN_GIMP:
        return "unsupported"
    return "supported" if series in SUPPORTED_GIMP_SERIES else "best_effort"


@functools.cache
def bundled_capabilities() -> dict[str, int]:
    """Operations (and revisions) of the plug-in shipped with this server, read from its source:
    ``build_operations()`` and ``REVISIONS`` in gmb_ops.py (which imports GIMP, so it is not imported)."""
    from .installer import plugin_source_dir

    tree = ast.parse((plugin_source_dir() / "gmb_ops.py").read_text(encoding="utf-8"))
    names: list[str] = []
    revisions: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_operations":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                    names = [str(key.value) for key in inner.value.keys if isinstance(key, ast.Constant)]
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "REVISIONS" for t in node.targets):
            revisions = ast.literal_eval(node.value)
    return {name: revisions.get(name, 1) for name in names}


def check_plugin(
    server_version: str, plugin_version: str | None, protocol: int, capabilities: Mapping[str, int] | None
) -> PluginCheck:
    if protocol not in SUPPORTED_PROTOCOLS:
        return PluginCheck(Compatibility.INCOMPATIBLE)
    if plugin_version and plugin_version == server_version:
        return PluginCheck(Compatibility.MATCH)
    if capabilities is None:
        return PluginCheck(Compatibility.PARTIAL, None)
    missing = tuple(
        sorted(name for name, revision in bundled_capabilities().items() if capabilities.get(name, 0) < revision)
    )
    return PluginCheck(Compatibility.PARTIAL if missing else Compatibility.COMPATIBLE, missing)

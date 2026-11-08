"""Toolsets: named groups of tools, so a client only loads the tools it needs (#45).

Every tool belongs to exactly one toolset (``Toolkit.tool(..., toolset=...)``).
``core`` is always on; the others are chosen with ``gimp-mcp serve --toolsets``
or ``GIMP_MCP_TOOLSETS`` (comma-separated names, ``default`` and ``all`` are
shortcuts), and can be enabled during a session with ``gimp_enable_toolsets``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

ENV_VAR = "GIMP_MCP_TOOLSETS"
ALWAYS = "core"

TOOLSETS: dict[str, str] = {
    "core": "Connection status, inspection, previews and toolset management. Always enabled.",
    "files": "Create, open, save, export and close images.",
    "layers": "Create, import, duplicate, group, reorder, change and delete layers.",
    "transform": "Scale and crop images, resize the canvas, move, scale, rotate and flip layers.",
    "selection": "Rectangle and ellipse selections, selection state, layer masks.",
    "paint": "Fill areas, draw paths and shapes.",
    "filters": "Color corrections and blur, destructive or as editable filters; list and remove filters.",
    "text": "Editable text layers and fonts.",
    "history": "Undo groups and checkpoints (undo/redo for agents).",
    "analysis": "Measure pixels: histograms and statistics, color sampling, image comparison, dominant colors, "
    "full-resolution crops.",
    "color": "Color adjustments: levels, curves, color balance, colorize, desaturate, invert, threshold, "
    "posterize, exposure, shadows-highlights, automatic corrections.",
    "animation": "Animations as layers: frames with duration and disposal, frame previews, optimization, "
    "animated GIF and WebP export.",
    "typography": "Rich text markup, text outlines, kerning, hinting, indentation, language and right-to-left or "
    "vertical text.",
    "vector": "GIMP 3.2 vector layers (a path rendered with editable fill and stroke) and link layers (an "
    "external image file).",
    "channels": "Select by color, fuzzy select, select from items; grow, shrink, border, feather, round, "
    "remove holes; channels to store and combine selections.",
    "geometry": "Perspective, shear, arbitrary matrices and rotation around a point for layers, paths, channels "
    "and the selection; image rotation and flips.",
    "painting": "GIMP's paint tools along strokes (paintbrush, pencil, airbrush, ink, eraser, smudge, dodge/burn, "
    "clone, heal) with explicit brush settings, gradient fills and bucket fill.",
    "formats": "Every file format GIMP reads and writes: options introspected from GIMP, open with options "
    "(PDF pages, SVG size), export layers to separate files and regions.",
    "document": "Guides and sample points, Exif/XMP/IPTC metadata and comment, resolution and print size.",
    "compose": "Copy/paste (named buffers), merge and flatten, alpha channels, layer boundaries, crop to "
    "content, align and distribute layers.",
    "resources": "Brushes, gradients, patterns and palettes: list, inspect with previews, create, edit, "
    "duplicate, rename, delete; palette import and export.",
    "paths": "Paths (vectors): create from points, Bézier segments, ellipses or text; edit strokes; stroke, "
    "fill, convert to and from selections; SVG import and export.",
    "modes": "Image mode (RGB, grayscale, indexed), precision (8 to 64 bits, linear or not) and ICC color profiles.",
    "effects": "The full GEGL filter catalog: list operations, apply any of them, edit, reorder and merge "
    "editable filters.",
    "procedures": "Search, describe and call allowlisted GIMP procedures (advanced).",
}

DEFAULT_TOOLSETS: tuple[str, ...] = (
    "core",
    "files",
    "layers",
    "transform",
    "selection",
    "paint",
    "filters",
    "text",
    "history",
)

# Budget of the default selection: what a client loads when nothing is configured.
# Checked by tests/unit/test_toolsets.py; documented in docs/toolsets.md.
DEFAULT_MAX_TOOLS = 50
DEFAULT_MAX_SCHEMA_BYTES = 140_000


class ToolsetError(ValueError):
    pass


def check_toolset(name: str) -> str:
    if name not in TOOLSETS:
        raise ToolsetError(f"unknown toolset '{name}' (valid: {', '.join(TOOLSETS)})")
    return name


def resolve_toolsets(spec: str | Iterable[str] | None) -> frozenset[str]:
    """``"default"``/``None`` → the default toolsets; ``"all"``; otherwise names, plus ``core``."""
    if spec is None:
        return frozenset(DEFAULT_TOOLSETS)
    parts = spec.split(",") if isinstance(spec, str) else list(spec)
    names = [part.strip().lower() for part in parts if part.strip()]
    if not names:
        raise ToolsetError(f"no toolset given (valid: default, all, {', '.join(TOOLSETS)})")
    selected = {ALWAYS}
    for name in names:
        if name == "default":
            selected.update(DEFAULT_TOOLSETS)
        elif name == "all":
            selected.update(TOOLSETS)
        else:
            selected.add(check_toolset(name))
    return frozenset(selected)


def toolsets_from(option: str | None, env: Mapping[str, str]) -> frozenset[str]:
    """The command-line option wins over the environment variable."""
    return resolve_toolsets(option if option is not None else env.get(ENV_VAR))


@dataclass(frozen=True)
class ToolsetEntry:
    name: str
    description: str
    tools: tuple[str, ...]
    schema_bytes: int  # size of the tools' definitions as sent in tools/list (JSON)


async def collect_report() -> list[ToolsetEntry]:
    """Every toolset with its tools and the size of their definitions (all toolsets enabled)."""
    from mcp import Client

    from .server import build_server

    server = build_server(toolsets="all", env={})
    catalog = server.gimp_toolkit.catalog  # type: ignore[attr-defined]
    async with Client(server) as client:
        definitions = [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in (await client.list_tools()).tools
        ]
    sizes: dict[str, int] = {name: 0 for name in TOOLSETS}
    tools: dict[str, list[str]] = {name: [] for name in TOOLSETS}
    for definition in definitions:
        toolset = catalog[definition["name"]].toolset
        tools[toolset].append(definition["name"])
        sizes[toolset] += len(json.dumps(definition))
    return [ToolsetEntry(name, TOOLSETS[name], tuple(tools[name]), sizes[name]) for name in TOOLSETS]


def toolset_report() -> list[ToolsetEntry]:
    import anyio

    return anyio.run(collect_report)


def render_report(entries: list[ToolsetEntry], enabled: Iterable[str] = DEFAULT_TOOLSETS) -> str:
    on = set(enabled)
    lines = [f"{'toolset':12s} {'default':8s} {'tools':>5s} {'schema bytes':>13s}"]
    for entry in entries:
        lines.append(
            f"{entry.name:12s} {'yes' if entry.name in on else '-':8s} {len(entry.tools):5d} {entry.schema_bytes:13d}"
        )
    default = [entry for entry in entries if entry.name in on]
    lines.append(
        f"{'(default)':12s} {'':8s} {sum(len(e.tools) for e in default):5d} "
        f"{sum(e.schema_bytes for e in default):13d}  budget: {DEFAULT_MAX_TOOLS} tools, "
        f"{DEFAULT_MAX_SCHEMA_BYTES} bytes"
    )
    return "\n".join(lines)

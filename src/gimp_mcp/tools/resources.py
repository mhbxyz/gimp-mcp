"""Resources (#52): brushes, gradients, patterns and palettes — list, inspect, create, edit.

Resources are referenced by name. Built-in resources are read-only (``READ_ONLY``); resources
created here are user resources, saved by GIMP in its profile (docs/tools.md#resources).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp_types import ImageContent
from pydantic import BaseModel, Field

from ..colors import parse_color
from ..errors import GimpMcpError
from ..palettes import read_palette
from ..paths import check_input_file, check_output_file
from ..toolkit import DESTRUCTIVE, MUTATING, READ_ONLY, Toolkit, ToolResult

Kind = Literal["brush", "gradient", "pattern", "palette"]
Editable = Literal["brush", "gradient", "palette"]
Name = Annotated[str, Field(min_length=1, max_length=255, description="Resource name, as listed.")]
PALETTE_SUFFIXES = {"gpl": ".gpl", "css": ".css", "text": ".txt", "python": ".py", "php": ".php", "java": ".java",
                    "kpl": ".kpl"}  # fmt: skip
Color = Annotated[str, Field(description="'#rrggbb' or '#rrggbbaa' (sRGB).")]


class ResourceSummary(BaseModel):
    kind: str
    name: str
    editable: bool = Field(description="False for built-in resources (read-only).")
    generated: bool | None = Field(default=None, description="Brushes: parametric (editable shape).")


class ResourceList(BaseModel):
    resources: list[ResourceSummary]
    total: int


class ResourceDetails(ResourceSummary):
    width: int | None = None
    height: int | None = None
    bpp: int | None = None
    color: bool | None = Field(default=None, description="Brushes: has its own colors.")
    spacing: int | None = Field(default=None, description="Brushes: dab spacing in % of the size.")
    shape: str | None = None
    radius: float | None = None
    hardness: float | None = None
    angle: float | None = None
    aspect_ratio: float | None = None
    spikes: int | None = None
    segments: list[dict[str, Any]] | None = Field(default=None, description="Gradients: segments left to right.")
    columns: int | None = None
    entries: list[dict[str, Any]] | None = Field(default=None, description="Palettes: index, name, color.")
    file: str | None = None


class Deleted(BaseModel):
    kind: str
    deleted: str


class Segment(BaseModel):
    left_color: Color
    right_color: Color
    blending: Literal["linear", "curved", "sine", "sphere-increasing", "sphere-decreasing", "step"] = "linear"
    coloring: Literal["rgb", "hsv-ccw", "hsv-cw"] = "rgb"
    right: Annotated[float | None, Field(gt=0, lt=1, description="End position (0-1); default: even split.")] = None


class PaletteEntry(BaseModel):
    color: Color
    name: str = ""


class ExportResult(BaseModel):
    file: str
    format: str
    bytes: int


def wire(color: str) -> list[float]:
    return parse_color(color).to_wire()


def register(kit: Toolkit) -> None:
    async def call(method: str, params: dict[str, Any], mutating: bool = True) -> dict[str, Any]:
        return await kit.call(method, params, mutating=mutating)

    @kit.tool(
        toolset="resources",
        name="gimp_list_resources",
        title="List resources",
        description="List brushes, gradients, patterns or palettes (built-in and user), optionally filtered by name.",
        annotations=READ_ONLY,
    )
    async def gimp_list_resources(
        kind: Kind, query: str = "", limit: Annotated[int, Field(ge=1, le=1000)] = 200
    ) -> ResourceList:
        return ResourceList(**await call("resources.list", {"kind": kind, "query": query, "limit": limit}, False))

    @kit.tool(
        toolset="resources",
        name="gimp_inspect_resource",
        title="Inspect a resource",
        description=(
            "Details of a resource: brush size and generated parameters, gradient segments, pattern size, "
            "palette entries. preview=true adds an image (brush, pattern, gradient strip, palette swatches)."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_inspect_resource(kind: Kind, name: Name, preview: bool = False) -> ResourceDetails:
        data = await call("resource.inspect", {"kind": kind, "name": name, "preview": preview}, False)
        png = data.pop("preview", None)
        details = ResourceDetails(**data)
        if png is None:
            return details
        return ToolResult(details, [ImageContent(type="image", data=png, mime_type="image/png")])  # type: ignore[return-value]

    @kit.tool(
        toolset="resources",
        name="gimp_create_resource",
        title="Create a resource",
        description=(
            "Create a user brush (generated), gradient or palette; GIMP makes the name unique ('Name #1'). "
            "Edit it with gimp_edit_brush / gimp_edit_gradient / gimp_edit_palette. Resources are not in GIMP's "
            "undo history."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_resource(kind: Editable, name: Name) -> ResourceSummary:
        return ResourceSummary(**await call("resource.create", {"kind": kind, "name": name}))

    @kit.tool(
        toolset="resources",
        name="gimp_duplicate_resource",
        title="Duplicate a resource",
        description=(
            "Copy a resource (built-in or user) into an editable user resource, optionally named. Resources are "
            "not in GIMP's undo history."
        ),
        annotations=MUTATING,
    )
    async def gimp_duplicate_resource(kind: Kind, name: Name, new_name: str | None = None) -> ResourceSummary:
        return ResourceSummary(**await call("resource.duplicate", {"kind": kind, "name": name, "new_name": new_name}))

    @kit.tool(
        toolset="resources",
        name="gimp_rename_resource",
        title="Rename a resource",
        description="Rename a user resource (READ_ONLY for built-in ones). Resources are not in GIMP's undo history.",
        annotations=MUTATING,
    )
    async def gimp_rename_resource(kind: Kind, name: Name, new_name: Name) -> ResourceSummary:
        return ResourceSummary(**await call("resource.rename", {"kind": kind, "name": name, "new_name": new_name}))

    @kit.tool(
        toolset="resources",
        name="gimp_delete_resource",
        title="Delete a resource",
        description="Delete a user resource and its file (READ_ONLY for built-in ones). Not undoable.",
        annotations=DESTRUCTIVE,
    )
    async def gimp_delete_resource(kind: Kind, name: Name) -> Deleted:
        return Deleted(**await call("resource.delete", {"kind": kind, "name": name}))

    @kit.tool(
        toolset="resources",
        name="gimp_edit_brush",
        title="Edit a generated brush",
        description=(
            "Change a user generated brush: shape (circle, square, diamond), radius (px), hardness (0-1), angle "
            "(degrees), aspect_ratio (1-20), spikes (2-20), spacing (% of the size). Only the given values change. "
            "Resources are not in GIMP's undo history."
        ),
        annotations=MUTATING,
    )
    async def gimp_edit_brush(
        name: Name,
        shape: Literal["circle", "square", "diamond"] | None = None,
        radius: Annotated[float | None, Field(ge=0.1, le=4000)] = None,
        hardness: Annotated[float | None, Field(ge=0, le=1)] = None,
        angle: Annotated[float | None, Field(ge=0, le=180)] = None,
        aspect_ratio: Annotated[float | None, Field(ge=1, le=20)] = None,
        spikes: Annotated[int | None, Field(ge=2, le=20)] = None,
        spacing: Annotated[int | None, Field(ge=1, le=5000)] = None,
    ) -> ResourceDetails:
        params = {"name": name, "shape": shape, "radius": radius, "hardness": hardness, "angle": angle,
                  "aspect_ratio": aspect_ratio, "spikes": spikes, "spacing": spacing}  # fmt: skip
        return ResourceDetails(**await call("brush.edit", params))

    @kit.tool(
        toolset="resources",
        name="gimp_edit_gradient",
        title="Edit a gradient",
        description=(
            "Replace a user gradient's segments, left to right: colors at both ends, blending (linear, curved, "
            "sine, sphere-increasing, sphere-decreasing, step), coloring (rgb, hsv-ccw, hsv-cw) and optional end "
            "positions (0-1, increasing; default even split). Resources are not in GIMP's undo history."
        ),
        annotations=MUTATING,
    )
    async def gimp_edit_gradient(
        name: Name, segments: Annotated[list[Segment], Field(min_length=1, max_length=64)]
    ) -> ResourceDetails:
        ends = [s.right for s in segments[:-1]]
        if any(e is not None for e in ends) and (None in ends or ends != sorted(ends)):  # type: ignore[type-var]
            raise GimpMcpError("INVALID_ARGUMENT", "give increasing end positions for every segment but the last")
        wire_segments = [{**s.model_dump(), "left_color": wire(s.left_color), "right_color": wire(s.right_color)}
                         for s in segments]  # fmt: skip
        return ResourceDetails(**await call("gradient.edit", {"name": name, "segments": wire_segments}))

    @kit.tool(
        toolset="resources",
        name="gimp_edit_palette",
        title="Edit a palette",
        description=(
            "Replace a user palette's entries (colors with optional names) and/or set its columns. Resources are "
            "not in GIMP's undo history."
        ),
        annotations=MUTATING,
    )
    async def gimp_edit_palette(
        name: Name,
        entries: Annotated[list[PaletteEntry] | None, Field(max_length=10000)] = None,
        columns: Annotated[int | None, Field(ge=0, le=64)] = None,
    ) -> ResourceDetails:
        wire_entries = None if entries is None else [{"name": e.name, "color": wire(e.color)} for e in entries]
        return ResourceDetails(
            **await call("palette.edit", {"name": name, "entries": wire_entries, "columns": columns})
        )

    @kit.tool(
        toolset="resources",
        name="gimp_import_palette",
        title="Import a palette",
        description=(
            "Import a palette file into GIMP's palettes folder and load it; it stays there (user palette). "
            "Reads GIMP palettes (.gpl), Adobe Color Tables (.act), Photoshop swatches (.aco), Adobe Swatch "
            "Exchange (.ase) and RIFF or Paint Shop Pro palettes (.pal). Other formats are written as a .gpl "
            "named after the file; their RGB, HSB and grayscale colors are imported as sRGB, CMYK and Lab "
            "colors are refused. Resources are not in GIMP's undo history."
        ),
        annotations=MUTATING,
    )
    async def gimp_import_palette(
        path: Annotated[str, Field(description="Absolute path of the palette file.")],
    ) -> ResourceDetails:
        source = check_input_file(path)
        if source.suffix.lower() != ".gpl":
            palette = read_palette(source)
            entries = [{"name": e.name, "rgb": list(e.rgb)} for e in palette.entries]
            return ResourceDetails(
                **await call("palette.import", {"file": str(source), "name": palette.name, "entries": entries})
            )
        return ResourceDetails(**await call("palette.import", {"file": str(source)}))

    @kit.tool(
        toolset="resources",
        name="gimp_export_palette",
        title="Export a palette",
        description=(
            "Write a palette to a file: gpl (GIMP palette), css, text, python, php, java (GIMP's palette exports) "
            "or kpl (Krita), to a file with that format's extension (.gpl, .css, .txt, .py, .php, .java, .kpl). "
            "Writing the file is not in GIMP's undo history."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_export_palette(
        name: Name,
        path: Annotated[str, Field(description="Absolute path of the file to write.")],
        format: Literal["gpl", "css", "text", "python", "php", "java", "kpl"] = "gpl",
        overwrite: bool = False,
    ) -> ExportResult:
        suffix = PALETTE_SUFFIXES[format]
        if not path.lower().endswith(suffix):
            # A palette's text written to ~/.zshenv or a startup script would run (#122).
            raise GimpMcpError(
                "INVALID_ARGUMENT", f"a {format} palette is written to a {suffix} file", details={"path": path}
            )
        target = str(check_output_file(path, overwrite=overwrite))
        return ExportResult(**await call("palette.export", {"name": name, "file": target, "format": format}))

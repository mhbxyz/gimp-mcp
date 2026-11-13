"""Paths (#50): create, inspect, edit, stroke, fill, convert to/from selections, SVG import/export.

A path is an item (``item:N@session``) with strokes (``stroke`` numbers inside the path). Coordinates
are image pixels; paths may extend beyond the canvas.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..errors import GimpMcpError
from ..ids import IdCodec
from ..models import ChangedObject
from ..paths import check_input_file, check_output_file
from ..toolkit import DESTRUCTIVE, MUTATING, READ_ONLY, Toolkit
from .inspect import ImageId, ItemId
from .selection import SelectionState

Point = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in image pixels.")]
PathId = Annotated[str, Field(description="Path id (an item id), from gimp_inspect_image's 'paths'.")]
Color = Annotated[str, Field(description="'#rrggbb' or '#rrggbbaa' (sRGB).")]


class PolylineStroke(BaseModel):
    type: Literal["polyline"]
    points: Annotated[list[Point], Field(min_length=2, max_length=10000)]
    closed: bool = False


class Segment(BaseModel):
    to: Point
    control1: Point | None = Field(default=None, description="With control2: cubic Bézier; alone: quadratic.")
    control2: Point | None = None


class BezierStroke(BaseModel):
    type: Literal["bezier"]
    start: Point
    segments: Annotated[list[Segment], Field(min_length=1, max_length=10000)]
    closed: bool = False


class EllipseStroke(BaseModel):
    type: Literal["ellipse"]
    center: Point
    radius_x: Annotated[float, Field(gt=0)]
    radius_y: Annotated[float, Field(gt=0)]
    angle: float = Field(default=0.0, description="Rotation in degrees.")


Stroke = Annotated[PolylineStroke | BezierStroke | EllipseStroke, Field(discriminator="type")]


class StrokeInfo(BaseModel):
    id: int
    closed: bool
    length: float
    anchors: int
    bounds: dict[str, float] | None
    control_points: list[list[float]] | None = Field(
        default=None, description="Bézier control points: in-handle, anchor, out-handle for each anchor."
    )


class PathInfo(BaseModel):
    id: str
    image: str
    name: str
    visible: bool
    stroke_count: int
    strokes: list[StrokeInfo] = Field(description="At most 200 strokes are detailed.")
    added_stroke: int | None = None


class PathList(BaseModel):
    paths: list[PathInfo]


class PointAt(BaseModel):
    x: float
    y: float
    slope: float
    valid: bool
    length: float = Field(description="Length of the stroke.")


class PathDeleted(BaseModel):
    deleted: str


class PathPainted(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    path: str
    method: str | None = None


class SvgResult(BaseModel):
    svg: str | None = Field(description="The SVG document (when no file was given).")
    file: str | None
    bytes: int


def register(kit: Toolkit) -> None:
    async def path_call(
        method: str, build: Callable[[IdCodec], dict[str, Any]], *, mutating: bool = True
    ) -> tuple[dict[str, Any], IdCodec]:
        codec = await kit.codec()
        data = await kit.call(method, build(codec), codec=codec, mutating=mutating)
        return data, codec

    def info(codec: IdCodec, data: dict[str, Any]) -> PathInfo:
        return PathInfo(**{**data, "id": codec.item(data["id"]), "image": codec.image(data["image"])})

    @kit.tool(
        toolset="paths",
        name="gimp_create_path",
        title="Create path",
        description=(
            "Create a path from strokes: polyline (points), bezier (start + segments with optional control "
            "points) or ellipse (center, radii, angle). It appears in gimp_inspect_image's paths. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_path(
        image: ImageId,
        name: str = "Path",
        strokes: Annotated[list[Stroke], Field(max_length=256)] = [],  # noqa: B006
        position: Annotated[int, Field(ge=0)] = 0,
    ) -> PathInfo:
        data, codec = await path_call(
            "path.create",
            lambda c: {"image": c.parse_image(image), "name": name, "position": position,
                       "strokes": [s.model_dump() for s in strokes]},
        )  # fmt: skip
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_add_path_stroke",
        title="Add a stroke to a path",
        description="Add one stroke (polyline, bezier or ellipse) to a path; returns its number. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_add_path_stroke(path: PathId, stroke: Stroke) -> PathInfo:
        data, codec = await path_call(
            "path.add_stroke", lambda c: {"path": c.parse_item(path), "stroke": stroke.model_dump()}
        )
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_path_from_text",
        title="Path from text",
        description="Create a path from the outline of a text layer's glyphs. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_path_from_text(item: ItemId) -> PathInfo:
        data, codec = await path_call("path.from_text", lambda c: {"item": c.parse_item(item)})
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_text_along_path",
        title="Text along a path",
        description=(
            "Lay a text layer's glyph outlines along a path, as GIMP's Text along Path: the text's middle line "
            "follows the path from its start (stroke after stroke); text longer than the path continues straight. "
            "Creates a new path (fill or stroke it, or make a vector layer from it); the text layer and the path "
            "are unchanged. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_text_along_path(item: ItemId, path: PathId, name: str | None = None) -> PathInfo:
        data, codec = await path_call(
            "path.text_along", lambda c: {"item": c.parse_item(item), "path": c.parse_item(path), "name": name}
        )
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_inspect_path",
        title="Inspect path",
        description="Name, visibility and strokes (closed, length, anchors, bounds; control points on request).",
        annotations=READ_ONLY,
    )
    async def gimp_inspect_path(path: PathId, points: bool = False) -> PathInfo:
        data, codec = await path_call(
            "path.inspect", lambda c: {"path": c.parse_item(path), "points": points}, mutating=False
        )
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_set_path",
        title="Rename or show/hide a path",
        description="Change a path's name and/or visibility (shown in GIMP's canvas). One undo step.",
        annotations=MUTATING,
    )
    async def gimp_set_path(path: PathId, name: str | None = None, visible: bool | None = None) -> PathInfo:
        data, codec = await path_call(
            "path.set", lambda c: {"path": c.parse_item(path), "name": name, "visible": visible}
        )
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_duplicate_path",
        title="Duplicate path",
        description="Copy a path (all strokes) above it. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_duplicate_path(path: PathId) -> PathInfo:
        data, codec = await path_call("path.duplicate", lambda c: {"path": c.parse_item(path)})
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_delete_path",
        title="Delete path",
        description="Remove a path from its image. One undo step.",
        annotations=DESTRUCTIVE,
    )
    async def gimp_delete_path(path: PathId) -> PathDeleted:
        data, codec = await path_call("path.delete", lambda c: {"path": c.parse_item(path)})
        return PathDeleted(deleted=codec.item(data["deleted"]))

    @kit.tool(
        toolset="paths",
        name="gimp_edit_path_stroke",
        title="Edit a path stroke",
        description=(
            "Change one stroke: translate (dx, dy), scale (sx, sy, around the origin), rotate (angle in degrees "
            "around center_x, center_y), flip (orientation around axis), reverse, close, or remove. "
            "One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_edit_path_stroke(
        path: PathId,
        stroke: Annotated[int, Field(ge=1)],
        action: Literal["translate", "scale", "rotate", "flip", "reverse", "close", "remove"],
        dx: float = 0,
        dy: float = 0,
        sx: float = 1,
        sy: float = 1,
        angle: float = 0,
        center_x: float = 0,
        center_y: float = 0,
        orientation: Literal["horizontal", "vertical"] = "horizontal",
        axis: float = 0,
    ) -> PathInfo:
        if action == "scale" and (sx == 0 or sy == 0):
            raise GimpMcpError("INVALID_ARGUMENT", "scale factors must not be 0")
        data, codec = await path_call(
            "path.edit_stroke",
            lambda c: {"path": c.parse_item(path), "stroke": stroke, "action": action, "dx": dx, "dy": dy,
                       "sx": sx, "sy": sy, "angle": angle, "center_x": center_x, "center_y": center_y,
                       "orientation": orientation, "axis": axis},
        )  # fmt: skip
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_path_point_at",
        title="Point along a path",
        description="Position and slope at a distance along a stroke (0 to its length, in pixels).",
        annotations=READ_ONLY,
    )
    async def gimp_path_point_at(
        path: PathId, stroke: Annotated[int, Field(ge=1)], distance: Annotated[float, Field(ge=0)]
    ) -> PointAt:
        data, _codec = await path_call(
            "path.point_at",
            lambda c: {"path": c.parse_item(path), "stroke": stroke, "distance": distance},
            mutating=False,
        )
        return PointAt(**data)

    @kit.tool(
        toolset="paths",
        name="gimp_path_to_selection",
        title="Path to selection",
        description="Select the area enclosed by a path (replace, add, subtract or intersect). One undo step.",
        annotations=MUTATING,
    )
    async def gimp_path_to_selection(
        path: PathId,
        operation: Literal["replace", "add", "subtract", "intersect"] = "replace",
        antialias: bool = True,
    ) -> SelectionState:
        data, codec = await path_call(
            "path.to_selection",
            lambda c: {"path": c.parse_item(path), "operation": operation, "antialias": antialias},
        )
        return SelectionState(**{**data, "image": codec.image(data["image"])})

    @kit.tool(
        toolset="paths",
        name="gimp_selection_to_path",
        title="Selection to path",
        description="Trace the selection's outline into a new path (GIMP's Selection to Path). One undo step.",
        annotations=MUTATING,
    )
    async def gimp_selection_to_path(image: ImageId, name: str | None = None) -> PathInfo:
        data, codec = await path_call("selection.to_path", lambda c: {"image": c.parse_image(image), "name": name})
        return info(codec, data)

    @kit.tool(
        toolset="paths",
        name="gimp_stroke_path",
        title="Stroke path",
        description=(
            "Draw along a path on a layer. method 'line': a geometric line (width, cap, join, miter_limit, "
            "dash pattern in multiples of the width); 'paint': GIMP's paintbrush with a brush (by name, size = "
            "width). Explicit settings; the user's context is untouched. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_stroke_path(
        path: PathId,
        item: ItemId,
        color: Color = "#000000",
        width: Annotated[float, Field(gt=0, le=1000)] = 2.0,
        method: Literal["line", "paint"] = "line",
        cap: Literal["butt", "round", "square"] = "round",
        join: Literal["miter", "round", "bevel"] = "round",
        miter_limit: Annotated[float, Field(ge=0, le=100)] = 10.0,
        dash: Annotated[list[Annotated[float, Field(ge=0)]] | None, Field(max_length=32)] = None,
        brush: str | None = None,
        opacity: Annotated[float, Field(ge=0, le=100)] = 100.0,
        antialias: bool = True,
    ) -> PathPainted:
        data, _codec = await path_call(
            "path.stroke",
            lambda c: {"path": c.parse_item(path), "item": c.parse_item(item), "color": color_wire(color),
                       "width": width, "method": method, "cap": cap, "join": join, "miter_limit": miter_limit,
                       "dash": dash, "brush": brush, "opacity": opacity, "antialias": antialias},
        )  # fmt: skip
        return PathPainted(item=item, path=path, method=data["method"])

    @kit.tool(
        toolset="paths",
        name="gimp_fill_path",
        title="Fill path",
        description="Fill the area enclosed by a path on a layer with a color; the selection is restored. "
        "One undo step.",
        annotations=MUTATING,
    )
    async def gimp_fill_path(
        path: PathId,
        item: ItemId,
        color: Color = "#000000",
        opacity: Annotated[float, Field(ge=0, le=100)] = 100.0,
        antialias: bool = True,
    ) -> PathPainted:
        await path_call(
            "path.fill",
            lambda c: {"path": c.parse_item(path), "item": c.parse_item(item), "color": color_wire(color),
                       "opacity": opacity, "antialias": antialias},
        )  # fmt: skip
        return PathPainted(item=item, path=path)

    @kit.tool(
        toolset="paths",
        name="gimp_import_svg_paths",
        title="Import SVG paths",
        description=(
            "Import the paths of an SVG document (file or string) into an image: merge=true makes one path, "
            "scale=true fits the SVG to the image size. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_import_svg_paths(
        image: ImageId,
        file: str | None = None,
        svg: Annotated[str | None, Field(max_length=4_000_000)] = None,
        merge: bool = False,
        scale: bool = False,
    ) -> PathList:
        if (file is None) == (svg is None):
            raise GimpMcpError("INVALID_ARGUMENT", "give either file or svg")
        source = str(check_input_file(file)) if file else None
        data, codec = await path_call(
            "paths.import_svg",
            lambda c: {"image": c.parse_image(image), "file": source, "svg": svg, "merge": merge, "scale": scale},
        )
        return PathList(paths=[info(codec, p) for p in data["paths"]])

    @kit.tool(
        toolset="paths",
        name="gimp_export_path_svg",
        title="Export path to SVG",
        description=(
            "Export one path (or all paths of the image) as an SVG document, returned or written to file (a .svg path)."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_export_path_svg(
        image: ImageId, path: PathId | None = None, file: str | None = None, overwrite: bool = False
    ) -> SvgResult:
        if file and not file.lower().endswith(".svg"):
            raise GimpMcpError("INVALID_ARGUMENT", "paths are written to a .svg file", {"path": file})  # #122
        target = str(check_output_file(file, overwrite=overwrite)) if file else None
        data, _codec = await path_call(
            "paths.export_svg",
            lambda c: {"image": c.parse_image(image), "path": c.parse_item(path) if path else None, "file": target},
            mutating=False,
        )
        return SvgResult(**data)


def color_wire(value: str) -> list[float]:
    from ..colors import parse_color

    return parse_color(value).to_wire()

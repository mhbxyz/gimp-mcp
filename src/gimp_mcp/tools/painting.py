"""Brush painting, gradient fills and bucket fill (#53).

Every setting is explicit (brush, size, hardness, spacing, dynamics, opacity, mode, colors); GIMP's
context is saved before and restored after, so results never depend on the user's UI state.
Text layers are never rasterized silently and locks are respected (like the existing paint tools).
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..colors import parse_color
from ..errors import GimpMcpError
from ..models import ChangedObject
from ..toolkit import MUTATING, Toolkit
from .inspect import ItemId

Point = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in image pixels.")]
Color = Annotated[str, Field(description="'#rrggbb' or '#rrggbbaa' (sRGB).")]
Shape = Literal[
    "linear", "bilinear", "radial", "square", "conical-symmetric", "conical-asymmetric",
    "shapeburst-angular", "shapeburst-spherical", "shapeburst-dimpled", "spiral-clockwise", "spiral-anticlockwise",
]  # fmt: skip


class Stop(BaseModel):
    left_color: Color
    right_color: Color


Segments = Annotated[
    list[Stop] | None, Field(max_length=32, description="Inline gradient: segments left to right (instead of a name).")
]


class Painted(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    tool: str | None = None
    brush: str | None = None
    dynamics: str | None = None
    gradient: str | None = None
    fill: str | None = None
    mode: str | None = None


def wire(color: str) -> list[float]:
    return parse_color(color).to_wire()


def register(kit: Toolkit) -> None:
    async def paint(method: str, item: str, params: dict[str, Any]) -> Painted:
        codec = await kit.codec()
        if params.get("source"):
            params["source"] = codec.parse_item(params["source"])
        data = await kit.call(method, {"item": codec.parse_item(item), **params}, codec=codec, mutating=True)
        return Painted(**{**data, "item": item})

    @kit.tool(
        toolset="painting",
        name="gimp_paint_stroke",
        title="Paint a stroke",
        description=(
            "Paint along points with a GIMP paint tool: paintbrush, pencil (hard edges), airbrush (pressure), "
            "ink, eraser, smudge (pressure), dodge or burn (exposure), clone or heal (copy from source, default "
            "the painted layer: source_offset [dx, dy] from the first point, or the absolute point "
            "source_x/source_y matching it). Brush by name (default: a generated round brush), size (px), "
            "hardness (0-1), "
            "spacing (% of size), dynamics (default 'Dynamics Off'), opacity, mode, color. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_paint_stroke(
        item: ItemId,
        tool: Literal["paintbrush", "pencil", "airbrush", "ink", "eraser", "smudge", "dodge", "burn", "clone", "heal"],
        points: Annotated[list[Point], Field(min_length=1, max_length=5000)],
        color: Color = "#000000",
        brush: str | None = None,
        size: Annotated[float, Field(gt=0, le=10000)] = 10.0,
        hardness: Annotated[float, Field(ge=0, le=1)] = 1.0,
        spacing: Annotated[float, Field(ge=1, le=5000)] = 10.0,
        dynamics: str | None = None,
        opacity: Annotated[float, Field(ge=0, le=100)] = 100.0,
        mode: str = "normal",
        pressure: Annotated[float, Field(ge=0, le=100, description="Airbrush and smudge.")] = 50.0,
        exposure: Annotated[float, Field(ge=0, le=100, description="Dodge and burn.")] = 50.0,
        source: Annotated[
            str | None, Field(description="Clone and heal: layer to copy from (item id); default: item itself.")
        ] = None,
        source_x: float = 0.0,
        source_y: float = 0.0,
        source_offset: Annotated[
            list[float] | None,
            Field(
                min_length=2,
                max_length=2,
                description="Clone and heal: [dx, dy] from the first point to the point copied from "
                "(e.g. [16, 0]: 16 px to the right); replaces source_x/source_y.",
            ),
        ] = None,
    ) -> Painted:
        if source_offset is not None:
            if tool not in ("clone", "heal"):
                raise GimpMcpError("INVALID_ARGUMENT", f"source_offset is for clone and heal, not {tool}")
            if source_x or source_y:
                raise GimpMcpError(
                    "INVALID_ARGUMENT",
                    "give source_offset or source_x/source_y, not both",
                    hint="source_offset is relative to the first point; source_x/source_y are absolute.",
                )
            source_x, source_y = points[0][0] + source_offset[0], points[0][1] + source_offset[1]
        if tool in ("clone", "heal") and source is None:
            source = item
        return await paint(
            "paint.stroke",
            item,
            {"tool": tool, "points": points, "color": wire(color), "brush": brush, "size": size, "hardness": hardness,
             "spacing": spacing, "dynamics": dynamics, "opacity": opacity, "mode": mode, "pressure": pressure,
             "exposure": exposure, "source": source, "source_x": source_x, "source_y": source_y},
        )  # fmt: skip

    @kit.tool(
        toolset="painting",
        name="gimp_gradient_fill",
        title="Gradient fill",
        description=(
            "Fill the layer (or the selection) with a gradient from start to end: a named gradient (gimp_list_"
            "resources kind=gradient) or inline segments; shape linear, radial, square, conical, shapeburst, "
            "spiral…; repeat none/sawtooth/triangular; offset 0-100; reverse. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_gradient_fill(
        item: ItemId,
        start: Point,
        end: Point,
        gradient: str | None = None,
        segments: Segments = None,
        shape: Shape = "linear",
        repeat: Literal["none", "sawtooth", "triangular"] = "none",
        offset: Annotated[float, Field(ge=0, le=100)] = 0.0,
        reverse: bool = False,
        opacity: Annotated[float, Field(ge=0, le=100)] = 100.0,
        mode: str = "normal",
    ) -> Painted:
        if (gradient is None) == (segments is None):
            raise GimpMcpError("INVALID_ARGUMENT", "give a gradient name or inline segments")
        return await paint(
            "paint.gradient",
            item,
            {"start": start, "end": end, "gradient": gradient, "shape": shape, "repeat": repeat, "offset": offset,
             "reverse": reverse, "opacity": opacity, "mode": mode,
             "segments": None if segments is None else [{"left_color": wire(s.left_color),
                                                         "right_color": wire(s.right_color)} for s in segments]},
        )  # fmt: skip

    @kit.tool(
        toolset="painting",
        name="gimp_bucket_fill",
        title="Bucket fill",
        description=(
            "Fill the area of similar colors around point (threshold 0-255, criterion composite/red/green/blue/"
            "alpha/hue/saturation/value/lch-*, sample_merged reads all visible layers), or the whole selection "
            "when no point is given; with a color, a pattern (by name) or a gradient (start/end). One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_bucket_fill(
        item: ItemId,
        point: Point | None = None,
        fill: Literal["color", "pattern", "gradient"] = "color",
        color: Color = "#000000",
        pattern: str | None = None,
        gradient: str | None = None,
        segments: Segments = None,
        start: Point | None = None,
        end: Point | None = None,
        shape: Shape = "linear",
        threshold: Annotated[float, Field(ge=0, le=255)] = 15,
        criterion: str = "composite",
        sample_merged: bool = False,
        fill_transparent: bool = True,
        diagonal: bool = False,
        opacity: Annotated[float, Field(ge=0, le=100)] = 100.0,
        mode: str = "normal",
    ) -> Painted:
        if fill == "pattern" and not pattern:
            raise GimpMcpError("INVALID_ARGUMENT", "fill='pattern' needs a pattern name")
        if fill == "gradient" and (start is None or end is None or (gradient is None) == (segments is None)):
            raise GimpMcpError("INVALID_ARGUMENT", "fill='gradient' needs start, end and a gradient or segments")
        return await paint(
            "paint.bucket",
            item,
            {"point": point, "fill": fill, "color": wire(color), "pattern": pattern, "gradient": gradient,
             "segments": None if segments is None else [{"left_color": wire(s.left_color),
                                                         "right_color": wire(s.right_color)} for s in segments],
             "start": start, "end": end, "shape": shape, "repeat": "none", "threshold": threshold,
             "criterion": criterion, "sample_merged": sample_merged, "fill_transparent": fill_transparent,
             "diagonal": diagonal, "opacity": opacity, "mode": mode},
        )  # fmt: skip

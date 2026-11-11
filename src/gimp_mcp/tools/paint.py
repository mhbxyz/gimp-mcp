"""Fill and draw on a layer with explicit parameters (no dependency on GIMP's UI settings)."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field

from ..colors import COLOR_DESCRIPTION, parse_color
from ..errors import GimpMcpError
from ..models import ChangedObject
from ..toolkit import DESTRUCTIVE, Toolkit
from .inspect import ItemId
from .layers import MODE_DESCRIPTION
from .selection import Bounds

Color = Annotated[str, Field(description=COLOR_DESCRIPTION)]
Opacity = Annotated[float, Field(ge=0, le=100, description="0-100.")]
Coordinate = Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
StrokeWidth = Annotated[float, Field(gt=0, le=1000, description="Line width in pixels.")]


class PaintResult(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    changed: bool = Field(description="False when the painted area does not intersect the layer.")
    affected: Bounds | None = Field(description="Image-space box of the pixels that may have changed.")


def register(kit: Toolkit) -> None:
    async def paint(method: str, item: str, params: dict[str, Any]) -> PaintResult:
        codec = await kit.codec()
        data = await kit.call(method, {"item": codec.parse_item(item), **params}, codec=codec, mutating=True)
        return PaintResult(item=item, **data)

    @kit.tool(
        toolset="paint",
        name="gimp_fill",
        title="Fill",
        description=(
            "Fill a layer (or layer mask) with a solid color. area='selection' fills the selected part only "
            "(EMPTY_SELECTION if nothing is selected); area='layer' fills the whole layer and ignores (but "
            "keeps) the selection. Destructive for the pixels it covers. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_fill(
        item: ItemId,
        color: Color,
        area: Literal["selection", "layer"] = "selection",
        opacity: Opacity = 100.0,
        mode: Annotated[str, Field(description=MODE_DESCRIPTION)] = "normal",
    ) -> PaintResult:
        return await paint(
            "paint.fill",
            item,
            {"color": parse_color(color).to_wire(), "area": area, "opacity": opacity, "mode": mode},
        )

    @kit.tool(
        toolset="paint",
        name="gimp_draw_path",
        title="Draw line / polyline",
        description=(
            "Stroke a polyline through points [[x, y], ...] (image pixels, at least 2 points) with a plain line "
            "of the given width, color and opacity; closed=true joins the last point to the first. Uses a "
            "solid line, never the user's brush. Points outside the layer are clipped. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_draw_path(
        item: ItemId,
        points: Annotated[list[tuple[Coordinate, Coordinate]], Field(min_length=2, max_length=10_000)],
        color: Color,
        width: StrokeWidth = 2.0,
        opacity: Opacity = 100.0,
        closed: bool = False,
        antialias: bool = True,
        cap: Literal["butt", "round", "square"] = "round",
        join: Literal["miter", "round", "bevel"] = "round",
    ) -> PaintResult:
        return await paint(
            "paint.path",
            item,
            {
                "points": [list(point) for point in points],
                "color": parse_color(color).to_wire(),
                "width": width,
                "opacity": opacity,
                "closed": closed,
                "antialias": antialias,
                "cap": cap,
                "join": join,
            },
        )

    @kit.tool(
        toolset="paint",
        name="gimp_draw_shape",
        title="Draw rectangle / ellipse",
        description=(
            "Draw a rectangle or an ellipse (inscribed in x, y, width, height) on a layer, filled with "
            "fill_color and/or outlined with stroke_color (stroke centered on the outline). The image's "
            "selection is left unchanged. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_draw_shape(
        item: ItemId,
        shape: Literal["rectangle", "ellipse"],
        x: Coordinate,
        y: Coordinate,
        width: Annotated[float, Field(gt=0, le=1_000_000)],
        height: Annotated[float, Field(gt=0, le=1_000_000)],
        fill_color: Annotated[str | None, Field(description=COLOR_DESCRIPTION)] = None,
        stroke_color: Annotated[str | None, Field(description=COLOR_DESCRIPTION)] = None,
        stroke_width: StrokeWidth = 2.0,
        opacity: Opacity = 100.0,
        antialias: bool = True,
    ) -> PaintResult:
        if fill_color is None and stroke_color is None:
            raise GimpMcpError("INVALID_ARGUMENT", "give fill_color, stroke_color or both")
        return await paint(
            "paint.shape",
            item,
            {
                "shape": shape,
                "rect": [x, y, width, height],
                "fill": None if fill_color is None else parse_color(fill_color).to_wire(),
                "stroke": None if stroke_color is None else parse_color(stroke_color).to_wire(),
                "width": stroke_width,
                "opacity": opacity,
                "antialias": antialias,
            },
        )

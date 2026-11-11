"""Parameterized color corrections and filters, destructive or as editable (non-destructive) filters."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..models import ChangedObject
from ..toolkit import DESTRUCTIVE, MUTATING, READ_ONLY, Toolkit
from .inspect import ItemId

Destructive = Annotated[
    bool,
    Field(
        description=(
            "true: change the layer's pixels (respects the selection). false: add an editable GIMP filter "
            "on the layer (pixels untouched, removable, saved in XCF; applied to the whole layer)."
        )
    ),
]


class FilterResult(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    operation: str = Field(description="GEGL/GIMP operation that was applied.")
    destructive: bool = Field(description="True when the layer's pixels were changed.")
    filter: str | None = Field(description="Id of the editable filter (non-destructive only), verified to exist.")
    restricted_to_selection: bool = Field(description="True when only the selected area was changed.")


class FilterInfo(BaseModel):
    id: str
    name: str
    operation: str
    visible: bool
    opacity: float = Field(description="0-100.")


class FilterList(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    filters: list[FilterInfo] = Field(
        description="Editable filters on the layer, top of the filter stack first (most recently added first)."
    )


def register(kit: Toolkit) -> None:
    async def apply(item: str, operation: str, destructive: bool, settings: dict[str, Any]) -> FilterResult:
        codec = await kit.codec()
        data = await kit.call(
            "filter.apply",
            {"item": codec.parse_item(item), "operation": operation, "destructive": destructive, "settings": settings},
            codec=codec,
            mutating=True,
        )
        return FilterResult(
            item=item,
            operation=data["operation"],
            destructive=data["destructive"],
            filter=None if data["filter"] is None else codec.filter(data["filter"]),
            restricted_to_selection=data["restricted_to_selection"],
        )

    @kit.tool(
        toolset="filters",
        name="gimp_brightness_contrast",
        title="Brightness / contrast",
        description=(
            "Adjust brightness and contrast of a layer, each from -100 to 100 (0 = unchanged; GIMP's -1..1 curve, "
            "not a percentage: on mid-gray 128, brightness -30 gives 119 (7% darker), -100 gives 92; contrast "
            "pivots on light gray, +30 turns 128 into 54). For 'N% darker/lighter' use gimp_hue_saturation "
            "lightness -N/+N. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_brightness_contrast(
        item: ItemId,
        brightness: Annotated[float, Field(ge=-100, le=100)] = 0.0,
        contrast: Annotated[float, Field(ge=-100, le=100)] = 0.0,
        destructive: Destructive = True,
    ) -> FilterResult:
        return await apply(
            item, "brightness-contrast", destructive, {"brightness": brightness / 100, "contrast": contrast / 100}
        )

    @kit.tool(
        toolset="filters",
        name="gimp_hue_saturation",
        title="Hue / saturation",
        description=(
            "Rotate hue (degrees, -180..180) and change saturation and lightness (-100..100, 0 = unchanged) of "
            "a layer, for all colors or one hue range. Lightness is proportional: -30 makes it 30% darker "
            "(mid-gray 128 -> 90), +30 goes 30% of the way to white (128 -> 166). One undo step. Levels, "
            "curves, exposure…: gimp_levels (toolset color)."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_hue_saturation(
        item: ItemId,
        hue: Annotated[float, Field(ge=-180, le=180)] = 0.0,
        saturation: Annotated[float, Field(ge=-100, le=100)] = 0.0,
        lightness: Annotated[float, Field(ge=-100, le=100)] = 0.0,
        hue_range: Literal["all", "red", "yellow", "green", "cyan", "blue", "magenta"] = "all",
        overlap: Annotated[float, Field(ge=0, le=100, description="Blend with neighbouring ranges, 0-100.")] = 0.0,
        destructive: Destructive = True,
    ) -> FilterResult:
        return await apply(
            item,
            "hue-saturation",
            destructive,
            {"hue": hue, "saturation": saturation, "lightness": lightness, "range": hue_range, "overlap": overlap},
        )

    @kit.tool(
        toolset="filters",
        name="gimp_gaussian_blur",
        title="Gaussian blur",
        description=(
            "Blur a layer with a Gaussian of standard deviation `radius` pixels (radius_y defaults to radius). "
            "One undo step. Any other GEGL filter: gimp_apply_filter (toolset effects)."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_gaussian_blur(
        item: ItemId,
        radius: Annotated[float, Field(gt=0, le=1500, description="Standard deviation in pixels.")],
        radius_y: Annotated[float | None, Field(gt=0, le=1500)] = None,
        destructive: Destructive = True,
    ) -> FilterResult:
        return await apply(item, "gaussian-blur", destructive, {"std_dev_x": radius, "std_dev_y": radius_y or radius})

    @kit.tool(
        toolset="filters",
        name="gimp_list_filters",
        title="List editable filters",
        description="Editable (non-destructive) filters attached to a layer.",
        annotations=READ_ONLY,
    )
    async def gimp_list_filters(item: ItemId) -> FilterList:
        codec = await kit.codec()
        data = await kit.call("filter.list", {"item": codec.parse_item(item)}, codec=codec)
        return FilterList(
            item=item, filters=[FilterInfo(**{**f, "id": codec.filter(f["id"])}) for f in data["filters"]]
        )

    @kit.tool(
        toolset="filters",
        name="gimp_remove_filter",
        title="Remove editable filter",
        description="Remove an editable filter from a layer: the layer renders as if it had never been applied.",
        annotations=MUTATING,
    )
    async def gimp_remove_filter(
        item: ItemId, filter: Annotated[str, Field(description="Filter id from gimp_list_filters.")]
    ) -> FilterList:
        codec = await kit.codec()
        data = await kit.call(
            "filter.remove",
            {"item": codec.parse_item(item), "filter": codec.parse_filter(filter)},
            codec=codec,
            mutating=True,
        )
        return FilterList(
            item=item, filters=[FilterInfo(**{**f, "id": codec.filter(f["id"])}) for f in data["filters"]]
        )

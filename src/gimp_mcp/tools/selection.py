"""Selections and layer masks for targeted edits."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..models import ChangedObject, LayerNode, encode_layer
from ..toolkit import DESTRUCTIVE, MUTATING, READ_ONLY, Toolkit
from .inspect import ImageId, ItemId

Operation = Annotated[
    Literal["replace", "add", "subtract", "intersect"],
    Field(description="How the new shape combines with the current selection."),
]
Feather = Annotated[float, Field(ge=0, le=1000, description="Feather radius in pixels (0 = hard edge).")]
Size = Annotated[int, Field(ge=1, le=65536)]


class Bounds(BaseModel):
    x: int
    y: int
    width: int
    height: int


class SelectionState(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("image",)
    image: str
    empty: bool
    bounds: Bounds | None = Field(description="Bounding box of the selection, clipped to the canvas; null when empty.")
    contains: bool | None = Field(
        default=None, description="Whether (probe_x, probe_y) is selected (> 50%), when a probe point was given."
    )


def register(kit: Toolkit) -> None:
    async def selection_call(method: str, image: str, **params: Any) -> SelectionState:
        codec = await kit.codec()
        data = await kit.call(method, {"image": codec.parse_image(image), **params}, codec=codec, mutating=True)
        return SelectionState(image=image, **data)

    @kit.tool(
        toolset="selection",
        name="gimp_select_rectangle",
        title="Select rectangle",
        description=(
            "Select a rectangle (image pixels, origin top-left) combined with the current selection. The part "
            "outside the canvas is ignored. Selections are part of the image (undoable, saved in XCF)."
        ),
        annotations=MUTATING,
    )
    async def gimp_select_rectangle(
        image: ImageId,
        x: int,
        y: int,
        width: Size,
        height: Size,
        operation: Operation = "replace",
        feather: Feather = 0,
    ) -> SelectionState:
        return await selection_call(
            "selection.rect", image, x=x, y=y, width=width, height=height, operation=operation, feather=feather
        )

    @kit.tool(
        toolset="selection",
        name="gimp_select_ellipse",
        title="Select ellipse",
        description=(
            "Select the ellipse inscribed in the rectangle (x, y, width, height), antialiased, combined with "
            "the current selection. By color or magic wand: gimp_select_by_color (toolset channels)."
        ),
        annotations=MUTATING,
    )
    async def gimp_select_ellipse(
        image: ImageId,
        x: int,
        y: int,
        width: Size,
        height: Size,
        operation: Operation = "replace",
        feather: Feather = 0,
    ) -> SelectionState:
        return await selection_call(
            "selection.ellipse", image, x=x, y=y, width=width, height=height, operation=operation, feather=feather
        )

    @kit.tool(
        toolset="selection",
        name="gimp_modify_selection",
        title="Select all / none / invert",
        description="'all' selects the whole canvas, 'none' clears the selection, 'invert' inverts it.",
        annotations=MUTATING,
    )
    async def gimp_modify_selection(image: ImageId, action: Literal["all", "none", "invert"]) -> SelectionState:
        return await selection_call("selection.modify", image, action=action)

    @kit.tool(
        toolset="selection",
        name="gimp_get_selection",
        title="Get selection",
        description="Whether the image has a selection, its bounds, and optionally whether a point is selected.",
        annotations=READ_ONLY,
    )
    async def gimp_get_selection(
        image: ImageId, probe_x: int | None = None, probe_y: int | None = None
    ) -> SelectionState:
        codec = await kit.codec()
        params: dict[str, Any] = {"image": codec.parse_image(image)}
        if probe_x is not None and probe_y is not None:
            params["probe"] = [probe_x, probe_y]
        data = await kit.call("selection.get", params, codec=codec)
        return SelectionState(image=image, **data)

    @kit.tool(
        toolset="selection",
        name="gimp_add_layer_mask",
        title="Add layer mask",
        description=(
            "Add a mask to a layer or group. fill: 'white' (everything visible), 'black' (everything hidden), "
            "'alpha' (from the layer's transparency), 'selection' (selected = visible; EMPTY_SELECTION if "
            "nothing is selected), 'grayscale' (from the layer's luminance). invert inverts it. Non-destructive: "
            "the layer's pixels are kept."
        ),
        annotations=MUTATING,
    )
    async def gimp_add_layer_mask(
        item: ItemId,
        fill: Literal["white", "black", "alpha", "selection", "grayscale"] = "white",
        invert: bool = False,
    ) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(
            "mask.add", {"item": codec.parse_item(item), "fill": fill, "invert": invert}, codec=codec, mutating=True
        )
        return encode_layer(codec, data)

    @kit.tool(
        toolset="selection",
        name="gimp_set_layer_mask",
        title="Configure layer mask",
        description=(
            "apply: whether the mask affects the rendering (disable to see the layer unmasked); show: display "
            "the mask itself; edit: make painting tools target the mask."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_layer_mask(
        item: ItemId, apply: bool | None = None, show: bool | None = None, edit: bool | None = None
    ) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(
            "mask.set",
            {"item": codec.parse_item(item), "apply": apply, "show": show, "edit": edit},
            codec=codec,
            mutating=True,
        )
        return encode_layer(codec, data)

    @kit.tool(
        toolset="selection",
        name="gimp_remove_layer_mask",
        title="Remove layer mask",
        description=(
            "Remove a layer's mask. mode='apply' bakes it into the layer's alpha (destructive: hidden pixels "
            "become transparent); mode='discard' drops it (the layer is shown unmasked)."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_remove_layer_mask(item: ItemId, mode: Literal["apply", "discard"]) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call("mask.remove", {"item": codec.parse_item(item), "mode": mode}, codec=codec, mutating=True)
        return encode_layer(codec, data)

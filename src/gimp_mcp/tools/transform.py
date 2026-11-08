"""Resize, crop and transform images and layers."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..colors import parse_color
from ..models import LayerNode, encode_layer
from ..toolkit import DESTRUCTIVE, MUTATING, Toolkit
from .inspect import ImageId, ItemId

Interpolation = Annotated[
    Literal["none", "linear", "cubic", "nohalo", "lohalo"],
    Field(description="Resampling: none (nearest neighbour, hard edges), linear, cubic, nohalo, lohalo."),
]
Size = Annotated[int, Field(ge=1, le=65536, description="Pixels.")]


class ImageGeometry(BaseModel):
    image: str
    width: int
    height: int
    dirty: bool


def register(kit: Toolkit) -> None:
    async def image_call(method: str, image: str, **params: object) -> ImageGeometry:
        codec = await kit.codec()
        data = await kit.call(method, {"image": codec.parse_image(image), **params}, codec=codec, mutating=True)
        return ImageGeometry(image=image, width=data["width"], height=data["height"], dirty=data["dirty"])

    async def layer_call(method: str, item: str, **params: object) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(method, {"item": codec.parse_item(item), **params}, codec=codec, mutating=True)
        return encode_layer(codec, data)

    @kit.tool(
        toolset="transform",
        name="gimp_resize_image",
        title="Scale image",
        description=(
            "Scale the whole image and every layer to width x height pixels (layer sizes and offsets scale "
            "proportionally). Lossy: pixels are resampled with the given interpolation. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_resize_image(
        image: ImageId, width: Size, height: Size, interpolation: Interpolation = "cubic"
    ) -> ImageGeometry:
        return await image_call("image.scale", image, width=width, height=height, interpolation=interpolation)

    @kit.tool(
        toolset="transform",
        name="gimp_resize_canvas",
        title="Resize canvas",
        description=(
            "Change the canvas size without resampling. Layers move by (offset_x, offset_y) and keep their "
            "size, unless resize_layers is 'all' or 'image-sized' (layers that covered the old canvas): those "
            "grow or shrink to the canvas, new areas transparent or fill_color. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_resize_canvas(
        image: ImageId,
        width: Size,
        height: Size,
        offset_x: int = 0,
        offset_y: int = 0,
        resize_layers: Literal["none", "all", "image-sized"] = "none",
        fill_color: Annotated[str | None, Field(description="Fill new layer areas (default: transparent).")] = None,
    ) -> ImageGeometry:
        fill = None if fill_color is None else parse_color(fill_color).to_wire()
        return await image_call("image.resize", image, width=width, height=height, offset_x=offset_x,
                                offset_y=offset_y, resize_layers=resize_layers, fill_color=fill)  # fmt: skip

    @kit.tool(
        toolset="transform",
        name="gimp_crop_image",
        title="Crop image",
        description=(
            "Crop the image to the rectangle (x, y, width, height) in image pixels, which must lie inside "
            "the canvas. Destructive: layer pixels outside the rectangle are discarded. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_crop_image(image: ImageId, x: int, y: int, width: Size, height: Size) -> ImageGeometry:
        return await image_call("image.crop", image, x=x, y=y, width=width, height=height)

    @kit.tool(
        toolset="transform",
        name="gimp_set_layer_offsets",
        title="Move layer (offsets)",
        description=(
            "Place a layer or group so its top-left corner is at (x, y) in image pixels (may be negative or "
            "outside the canvas). Lossless. Refused with LOCKED when its position is locked. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_layer_offsets(item: ItemId, x: int, y: int) -> LayerNode:
        return await layer_call("layer.offsets", item, x=x, y=y)

    @kit.tool(
        toolset="transform",
        name="gimp_scale_layer",
        title="Scale layer",
        description=(
            "Resample a layer or group to width x height pixels. anchor='center' keeps its center, "
            "'top-left' keeps its top-left corner. Lossy. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_scale_layer(
        item: ItemId,
        width: Size,
        height: Size,
        anchor: Literal["center", "top-left"] = "center",
        interpolation: Interpolation = "cubic",
    ) -> LayerNode:
        return await layer_call(
            "layer.scale", item, width=width, height=height, anchor=anchor, interpolation=interpolation
        )

    @kit.tool(
        toolset="transform",
        name="gimp_rotate_layer",
        title="Rotate layer",
        description=(
            "Rotate a layer or group by angle degrees (clockwise) around its center. clip='adjust' grows "
            "the layer to keep all pixels, 'clip' keeps the original bounds. Multiples of 90 are lossless "
            "with interpolation 'none'; other angles resample. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_rotate_layer(
        item: ItemId,
        angle: Annotated[float, Field(ge=-3600, le=3600, description="Degrees, clockwise.")],
        clip: Literal["adjust", "clip"] = "adjust",
        interpolation: Interpolation = "cubic",
    ) -> LayerNode:
        return await layer_call("layer.rotate", item, angle=angle, clip=clip, interpolation=interpolation)

    @kit.tool(
        toolset="transform",
        name="gimp_flip_layer",
        title="Flip layer",
        description="Mirror a layer or group horizontally or vertically around its center. Lossless. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_flip_layer(item: ItemId, direction: Literal["horizontal", "vertical"]) -> LayerNode:
        return await layer_call("layer.flip", item, direction=direction)

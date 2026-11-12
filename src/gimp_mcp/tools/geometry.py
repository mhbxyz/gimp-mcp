"""Advanced transforms (#55): perspective, shear, matrices, rotation around a point; image rotation and flip."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field

from ..errors import GimpMcpError
from ..models import ChangedObject, LayerNode, encode_layer
from ..toolkit import DESTRUCTIVE, MUTATING, Toolkit
from .inspect import ImageId, ItemId
from .selection import SelectionState
from .transform import ImageGeometry, Interpolation

Point = Annotated[list[float], Field(min_length=2, max_length=2)]
Clip = Annotated[
    Literal["adjust", "clip", "crop", "crop-with-aspect"],
    Field(description="adjust: grow to fit; clip: keep the original bounds; crop: largest inner rectangle."),
]


class Transformed(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("layer", "item", "image")
    kind: str = Field(description="layer, group, text, path, channel or selection.")
    image: str
    layer: LayerNode | None = None
    selection: SelectionState | None = None
    item: str | None = None


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="geometry",
        name="gimp_transform",
        title="Perspective, shear, matrix or rotation",
        description=(
            "Transform a layer, group, path or channel (item) or the selection (image + selection=true): "
            "perspective (corners: new positions of the top-left, top-right, bottom-left, bottom-right corners "
            "of the item's bounds), shear (horizontal/vertical magnitude in pixels), matrix (3x3, pixel "
            "coordinates) or rotate (degrees clockwise around center_x, center_y). Explicit interpolation and "
            "clipping; locked layers are refused. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_transform(
        transform: Literal["perspective", "shear", "matrix", "rotate"],
        item: ItemId | None = None,
        image: ImageId | None = None,
        selection: bool = False,
        corners: Annotated[list[Point] | None, Field(min_length=4, max_length=4)] = None,
        orientation: Literal["horizontal", "vertical"] = "horizontal",
        magnitude: float | None = None,
        matrix: Annotated[
            list[Annotated[list[float], Field(min_length=3, max_length=3)]] | None, Field(min_length=3, max_length=3)
        ] = None,
        angle: float | None = None,
        center_x: float | None = None,
        center_y: float | None = None,
        interpolation: Interpolation = "cubic",
        clip: Clip = "adjust",
    ) -> Transformed:
        if selection == (image is None) or (not selection and item is None) or (selection and item is not None):
            raise GimpMcpError("INVALID_ARGUMENT", "give an item, or image with selection=true")
        needed = {"perspective": corners, "shear": magnitude, "matrix": matrix,
                  "rotate": None if angle is None or center_x is None or center_y is None else angle}  # fmt: skip
        if needed[transform] is None:
            raise GimpMcpError("INVALID_ARGUMENT", f"{transform} needs its parameters (see the description)")
        codec = await kit.codec()
        params: dict[str, Any] = {
            "transform": transform, "corners": corners, "orientation": orientation, "magnitude": magnitude,
            "matrix": matrix, "angle": angle, "center_x": center_x, "center_y": center_y,
            "interpolation": interpolation, "clip": clip, "selection": selection,
        }  # fmt: skip
        if selection:
            params["image"] = codec.parse_image(image or "")
        else:
            params["item"] = codec.parse_item(item or "")
        data = await kit.call("item.transform", params, codec=codec, mutating=True)
        image_id = codec.image(data["image"])
        return Transformed(
            kind=data["kind"],
            image=image_id,
            layer=encode_layer(codec, data["layer"]) if data.get("layer") else None,
            selection=SelectionState(**{**data["selection"], "image": image_id}) if data.get("selection") else None,
            item=codec.item(data["item"]) if data.get("item") is not None else None,
        )

    @kit.tool(
        toolset="transform",
        name="gimp_rotate_image",
        title="Rotate image",
        description="Rotate the whole image (canvas, layers, selection, paths) by 90, 180 or 270 degrees "
        "clockwise. Lossless. One undo step.",
        annotations=DESTRUCTIVE,
    )
    async def gimp_rotate_image(image: ImageId, angle: Literal[90, 180, 270]) -> ImageGeometry:
        codec = await kit.codec()
        data = await kit.call("image.rotate", {"image": codec.parse_image(image), "angle": angle}, codec=codec,
                              mutating=True)  # fmt: skip
        return ImageGeometry(image=image, **data)

    @kit.tool(
        toolset="geometry",
        name="gimp_flip_image",
        title="Flip image",
        description="Mirror the whole image horizontally or vertically. Lossless. One undo step.",
        annotations=DESTRUCTIVE,
    )
    async def gimp_flip_image(image: ImageId, orientation: Literal["horizontal", "vertical"]) -> ImageGeometry:
        codec = await kit.codec()
        data = await kit.call("image.flip", {"image": codec.parse_image(image), "orientation": orientation},
                              codec=codec, mutating=True)  # fmt: skip
        return ImageGeometry(image=image, **data)

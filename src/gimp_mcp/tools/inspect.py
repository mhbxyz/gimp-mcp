"""Read-only inspection of images and items."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ..models import ImageDetails, ItemDetails, encode_image, encode_item
from ..toolkit import READ_ONLY, Toolkit

ImageId = Annotated[str, Field(description="Image id from gimp_status, e.g. 'image:1@a1b2c3d4'.")]
ItemId = Annotated[str, Field(description="Item id (layer, group, mask...) e.g. 'item:5@a1b2c3d4'.")]


def register(kit: Toolkit) -> None:
    @kit.tool(
        name="gimp_inspect_image",
        title="Inspect image",
        description=(
            "Describe one image: size, mode, precision, resolution, unsaved changes, associated files and "
            "the full ordered layer tree (groups, children, masks, offsets, opacity, blend mode, locks). "
            "Does not depend on GIMP's active selection."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_inspect_image(image: ImageId) -> ImageDetails:
        codec = await kit.codec()
        data = await kit.call("image.inspect", {"image": codec.parse_image(image)}, codec=codec)
        return encode_image(codec, data)

    @kit.tool(
        name="gimp_inspect_item",
        title="Inspect item",
        description=(
            "Describe one item by id: kind (layer, group, text, mask, channel, path), owning image, "
            "parent and position, and its layer properties. Fails with NOT_FOUND once the item is deleted."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_inspect_item(item: ItemId) -> ItemDetails:
        codec = await kit.codec()
        data = await kit.call("item.inspect", {"item": codec.parse_item(item)}, codec=codec)
        return encode_item(codec, data)

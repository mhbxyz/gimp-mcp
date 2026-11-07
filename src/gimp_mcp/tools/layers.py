"""Create and organize layers and groups."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from ..colors import COLOR_DESCRIPTION, parse_color
from ..ids import IdCodec
from ..models import LayerNode, encode_layer
from ..paths import check_input_file
from ..toolkit import DESTRUCTIVE, MUTATING, Toolkit
from .inspect import ImageId, ItemId

ParentId = Annotated[
    str | None,
    Field(description="Group id to put the layer in; null for the top level of the image."),
]
Position = Annotated[int, Field(ge=0, description="Index within the parent, 0 = top-most (in front).")]
Opacity = Annotated[float, Field(ge=0, le=100, description="0 (transparent) - 100 (opaque).")]
MODE_DESCRIPTION = (
    "GIMP layer mode nick, e.g. normal, multiply, screen, overlay, soft-light, hard-light, addition, "
    "subtract, difference, darken-only, lighten-only, hue, saturation, color, dodge, burn, "
    "pass-through (groups). Invalid names are refused with the list of allowed ones."
)
Mode = Annotated[str, Field(description=MODE_DESCRIPTION)]


class DeleteResult(BaseModel):
    item: str
    deleted: bool


def _parent(codec: IdCodec, parent: str | None) -> int | None:
    return None if parent is None else codec.parse_item(parent)


def register(kit: Toolkit) -> None:
    async def layer_result(codec: IdCodec, data: dict[str, Any]) -> LayerNode:
        return encode_layer(codec, data)

    @kit.tool(
        name="gimp_create_layer",
        title="Create layer",
        description=(
            "Add a new raster layer (with alpha) to an image, at an explicit parent and position. Size and "
            "offset are in image pixels (default: the image size at 0,0). fill: 'transparent' or a color. "
            "One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_layer(
        image: ImageId,
        name: str,
        parent: ParentId = None,
        position: Position = 0,
        width: Annotated[int | None, Field(ge=1, le=65536)] = None,
        height: Annotated[int | None, Field(ge=1, le=65536)] = None,
        x: int = 0,
        y: int = 0,
        fill: Annotated[str, Field(description=COLOR_DESCRIPTION)] = "transparent",
        opacity: Opacity = 100.0,
        mode: Mode = "normal",
        visible: bool = True,
    ) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(
            "layer.create",
            {
                "image": codec.parse_image(image),
                "name": name,
                "parent": _parent(codec, parent),
                "position": position,
                "width": width,
                "height": height,
                "x": x,
                "y": y,
                "fill": parse_color(fill).to_wire(),
                "opacity": opacity,
                "mode": mode,
                "visible": visible,
            },
            codec=codec,
            mutating=True,
        )
        return await layer_result(codec, data)

    @kit.tool(
        name="gimp_create_group",
        title="Create layer group",
        description="Add an empty layer group at an explicit parent and position. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_create_group(
        image: ImageId, name: str, parent: ParentId = None, position: Position = 0
    ) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(
            "group.create",
            {"image": codec.parse_image(image), "name": name, "parent": _parent(codec, parent), "position": position},
            codec=codec,
            mutating=True,
        )
        return await layer_result(codec, data)

    @kit.tool(
        name="gimp_import_layer",
        title="Import file as layer",
        description=(
            "Load an image file (PNG, JPEG, XCF... absolute path) as a new layer of an existing image. "
            "Multi-layer files are flattened into one layer. Placed at x,y (default 0,0); name defaults to "
            "the file name. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_import_layer(
        image: ImageId,
        path: Annotated[str, Field(description="Absolute path of the file to import.")],
        name: str | None = None,
        parent: ParentId = None,
        position: Position = 0,
        x: int = 0,
        y: int = 0,
    ) -> LayerNode:
        source = check_input_file(path)
        codec = await kit.codec()
        data = await kit.call(
            "layer.import",
            {
                "image": codec.parse_image(image),
                "path": str(source),
                "name": name,
                "parent": _parent(codec, parent),
                "position": position,
                "x": x,
                "y": y,
            },
            codec=codec,
            mutating=True,
        )
        return await layer_result(codec, data)

    @kit.tool(
        name="gimp_duplicate_layer",
        title="Duplicate layer",
        description=(
            "Copy a layer or a whole group (with masks and children). By default the copy is placed just "
            "above the original in the same parent. GIMP names it '<name> copy'. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_duplicate_layer(
        item: ItemId, parent: ParentId = None, position: Annotated[int | None, Field(ge=0)] = None
    ) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(
            "layer.duplicate",
            {
                "item": codec.parse_item(item),
                "parent": _parent(codec, parent),
                "keep_parent": parent is None and position is None,
                "position": position,
            },
            codec=codec,
            mutating=True,
        )
        return await layer_result(codec, data)

    @kit.tool(
        name="gimp_set_layer_properties",
        title="Set layer properties",
        description=(
            "Rename a layer or group and/or change its visibility, opacity (0-100) or blend mode. Only the "
            "given properties change. Not destructive: pixels are untouched. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_layer_properties(
        item: ItemId,
        name: str | None = None,
        visible: bool | None = None,
        opacity: Annotated[float | None, Field(ge=0, le=100)] = None,
        mode: Annotated[str | None, Field(description=MODE_DESCRIPTION)] = None,
    ) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(
            "layer.set",
            {"item": codec.parse_item(item), "name": name, "visible": visible, "opacity": opacity, "mode": mode},
            codec=codec,
            mutating=True,
        )
        return await layer_result(codec, data)

    @kit.tool(
        name="gimp_move_layer",
        title="Move layer in the stack",
        description=(
            "Move a layer or group to another parent (a group of the same image, or null for the top level) "
            "and position (0 = top-most). Does not change pixels or offsets. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_move_layer(item: ItemId, parent: ParentId, position: Position) -> LayerNode:
        codec = await kit.codec()
        data = await kit.call(
            "layer.move",
            {"item": codec.parse_item(item), "parent": _parent(codec, parent), "position": position},
            codec=codec,
            mutating=True,
        )
        return await layer_result(codec, data)

    @kit.tool(
        name="gimp_delete_layer",
        title="Delete layer",
        description=(
            "Remove a layer or a group with all its children. Destructive: the pixels are lost unless "
            "undone in GIMP or the image is reverted from a saved file. Ids of removed items become invalid."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_delete_layer(item: ItemId) -> DeleteResult:
        codec = await kit.codec()
        await kit.call("layer.delete", {"item": codec.parse_item(item)}, codec=codec, mutating=True)
        return DeleteResult(item=item, deleted=True)

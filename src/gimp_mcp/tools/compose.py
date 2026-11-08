"""Layer composition (#54): copy/paste, merge and flatten, alpha, layer bounds, crop to content, alignment.

Copies go to a named GIMP buffer ('gimp-mcp' by default, visible in GIMP's Buffers dialog) so the
user's clipboard is left alone; buffer='clipboard' uses GIMP's global clipboard. Pastes never leave
a floating selection: it is anchored or turned into a layer.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ..errors import GimpMcpError
from ..models import LayerNode, encode_layer
from ..toolkit import DESTRUCTIVE, MUTATING, Toolkit
from .inspect import ImageId, ItemId
from .selection import SelectionState

Buffer = Annotated[
    str, Field(min_length=1, max_length=128, description="GIMP buffer name, or 'clipboard' for the global clipboard.")
]
MergeType = Annotated[
    Literal["expand", "clip-to-image", "clip-to-bottom"],
    Field(description="Size of the merged layer: grow to fit, the canvas, or the bottom layer."),
]


class Copied(BaseModel):
    buffer: str
    selection: bool = Field(description="True when only the selected area was copied.")


class Pasted(BaseModel):
    mode: str
    image: str
    layer: LayerNode | None = Field(description="The layer that received the pixels (null for new-image).")


class LayerResult(BaseModel):
    image: str | None = None
    layer: LayerNode


class CropResult(BaseModel):
    image: str
    width: int
    height: int
    cropped: bool


class Aligned(BaseModel):
    layers: list[LayerNode]


def register(kit: Toolkit) -> None:
    async def call(method: str, build: Any, mutating: bool = True) -> tuple[dict[str, Any], Any]:
        codec = await kit.codec()
        return await kit.call(method, build(codec), codec=codec, mutating=mutating), codec

    @kit.tool(
        toolset="compose",
        name="gimp_copy",
        title="Copy or cut",
        description=(
            "Copy (or cut) layers' pixels — only the selected area when there is a selection — or the visible "
            "composite (visible=true, give image) into a GIMP buffer. Default buffer 'gimp-mcp' keeps the "
            "user's clipboard untouched."
        ),
        annotations=MUTATING,
    )
    async def gimp_copy(
        items: Annotated[list[str] | None, Field(max_length=64, description="Layer ids (same image).")] = None,
        image: ImageId | None = None,
        visible: bool = False,
        cut: bool = False,
        buffer: Buffer = "gimp-mcp",
    ) -> Copied:
        if visible == (image is None) or (not visible and not items):
            raise GimpMcpError("INVALID_ARGUMENT", "give items, or visible=true with an image")
        if visible and cut:
            raise GimpMcpError("INVALID_ARGUMENT", "the visible composite can be copied, not cut")
        data, _ = await call(
            "clipboard.copy",
            lambda c: {"items": [c.parse_item(i) for i in items or []],
                       "image": c.parse_image(image) if image else None,
                       "visible": visible, "cut": cut, "buffer": buffer},
        )  # fmt: skip
        return Copied(**data)

    @kit.tool(
        toolset="compose",
        name="gimp_paste",
        title="Paste",
        description=(
            "Paste a buffer: into-layer (merged into item, anchored), new-layer (a new layer above item) or "
            "new-image (opens a new image; no item needed). into_selection pastes inside the selection. "
            "Never leaves a floating selection. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_paste(
        mode: Literal["into-layer", "new-layer", "new-image"],
        item: ItemId | None = None,
        buffer: Buffer = "gimp-mcp",
        into_selection: bool = False,
    ) -> Pasted:
        if mode != "new-image" and item is None:
            raise GimpMcpError("INVALID_ARGUMENT", f"mode={mode!r} needs an item")
        data, codec = await call(
            "clipboard.paste",
            lambda c: {"mode": mode, "item": c.parse_item(item) if item else None, "buffer": buffer,
                       "into_selection": into_selection},
        )  # fmt: skip
        layer = None if data["layer"] is None else encode_layer(codec, data["layer"])
        return Pasted(mode=data["mode"], image=codec.image(data["image"]["id"]), layer=layer)

    @kit.tool(
        toolset="compose",
        name="gimp_merge_layers",
        title="Merge layers",
        description=(
            "Merge a layer into the one below it (mode=down, item), a group into one layer (mode=group, item) "
            "or all visible layers (mode=visible, image). Destructive: the layers become one. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_merge_layers(
        mode: Literal["down", "group", "visible"],
        item: ItemId | None = None,
        image: ImageId | None = None,
        merge_type: MergeType = "expand",
    ) -> LayerResult:
        if (mode == "visible") != (image is not None) or (mode != "visible" and item is None):
            raise GimpMcpError("INVALID_ARGUMENT", "mode=visible needs image; down and group need item")
        data, codec = await call(
            "layers.merge",
            lambda c: {"mode": mode, "item": c.parse_item(item) if item else None,
                       "image": c.parse_image(image) if image else None, "merge_type": merge_type},
        )  # fmt: skip
        return LayerResult(image=codec.image(data["image"]["id"]), layer=encode_layer(codec, data["layer"]))

    @kit.tool(
        toolset="compose",
        name="gimp_flatten_image",
        title="Flatten image",
        description="Merge every layer into one opaque layer (transparency filled with the background color). "
        "Destructive. One undo step.",
        annotations=DESTRUCTIVE,
    )
    async def gimp_flatten_image(image: ImageId) -> LayerResult:
        data, codec = await call("image.flatten", lambda c: {"image": c.parse_image(image)})
        return LayerResult(image=image, layer=encode_layer(codec, data["layer"]))

    @kit.tool(
        toolset="compose",
        name="gimp_new_layer_from_visible",
        title="New layer from visible",
        description="Add a layer at the top holding the visible composite; other layers are untouched. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_new_layer_from_visible(image: ImageId, name: str = "Visible") -> LayerResult:
        data, codec = await call("layer.from_visible", lambda c: {"image": c.parse_image(image), "name": name})
        return LayerResult(image=image, layer=encode_layer(codec, data))

    @kit.tool(
        toolset="compose",
        name="gimp_set_alpha_channel",
        title="Add or remove alpha",
        description=(
            "add: give a layer an alpha channel (needed for transparency). remove: flatten it onto the "
            "background color. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_alpha_channel(item: ItemId, action: Literal["add", "remove"]) -> LayerResult:
        data, codec = await call("layer.alpha", lambda c: {"item": c.parse_item(item), "action": action})
        return LayerResult(layer=encode_layer(codec, data))

    @kit.tool(
        toolset="compose",
        name="gimp_alpha_to_selection",
        title="Alpha to selection",
        description="Select a layer's opaque pixels (by alpha): replace, add, subtract or intersect. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_alpha_to_selection(
        item: ItemId, operation: Literal["replace", "add", "subtract", "intersect"] = "replace"
    ) -> SelectionState:
        data, codec = await call("selection.from_alpha", lambda c: {"item": c.parse_item(item), "operation": operation})
        return SelectionState(**{**data, "image": codec.image(data["image"])})

    @kit.tool(
        toolset="compose",
        name="gimp_fit_layer",
        title="Resize layer boundary",
        description=(
            "Change a layer's boundary without scaling: image-size (fit the canvas), size (width, height and "
            "where the old content goes, offset_x/offset_y) or content (shrink to the non-empty pixels). "
            "One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_fit_layer(
        item: ItemId,
        mode: Literal["image-size", "size", "content"],
        width: Annotated[int | None, Field(ge=1, le=524288)] = None,
        height: Annotated[int | None, Field(ge=1, le=524288)] = None,
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> LayerResult:
        if mode == "size" and (width is None or height is None):
            raise GimpMcpError("INVALID_ARGUMENT", "mode=size needs width and height")
        data, codec = await call(
            "layer.fit",
            lambda c: {"item": c.parse_item(item), "mode": mode, "width": width, "height": height,
                       "offset_x": offset_x, "offset_y": offset_y},
        )  # fmt: skip
        return LayerResult(layer=encode_layer(codec, data))

    @kit.tool(
        toolset="compose",
        name="gimp_crop_to_content",
        title="Crop image to content",
        description="Crop the canvas to the area that differs from the border color (GIMP's Crop to Content). "
        "One undo step.",
        annotations=DESTRUCTIVE,
    )
    async def gimp_crop_to_content(image: ImageId) -> CropResult:
        data, _codec = await call("image.crop_to_content", lambda c: {"image": c.parse_image(image)})
        return CropResult(image=image, width=data["width"], height=data["height"], cropped=data["cropped"])

    @kit.tool(
        toolset="compose",
        name="gimp_align_layers",
        title="Align or distribute layers",
        description=(
            "Move layers so their boxes align to the image, the selection or another layer (horizontal: left, "
            "center, right; vertical: top, middle, bottom), or distribute (3+ layers) their centers evenly "
            "between the outer ones (to the nearest pixel). Uses layer boundaries, not visible content. "
            "One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_align_layers(
        items: Annotated[list[str], Field(min_length=1, max_length=256)],
        reference: Literal["image", "selection", "layer"] = "image",
        reference_item: ItemId | None = None,
        horizontal: Literal["left", "center", "right"] | None = None,
        vertical: Literal["top", "middle", "bottom"] | None = None,
        distribute: Literal["horizontal", "vertical"] | None = None,
    ) -> Aligned:
        if distribute is None and horizontal is None and vertical is None:
            raise GimpMcpError("INVALID_ARGUMENT", "give horizontal and/or vertical, or distribute")
        if reference == "layer" and reference_item is None:
            raise GimpMcpError("INVALID_ARGUMENT", "reference='layer' needs reference_item")
        if distribute is not None and len(items) < 3:
            raise GimpMcpError("INVALID_ARGUMENT", "distributing needs at least 3 layers")
        data, codec = await call(
            "layers.align",
            lambda c: {"items": [c.parse_item(i) for i in items], "reference": reference,
                       "reference_item": c.parse_item(reference_item) if reference_item else None,
                       "horizontal": horizontal, "vertical": vertical, "distribute": distribute},
        )  # fmt: skip
        return Aligned(layers=[encode_layer(codec, node) for node in data["layers"]])

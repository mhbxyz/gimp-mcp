"""Advanced selections and channels (#51): select by color, fuzzy select, from items; modifiers; channels."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ..colors import parse_color
from ..errors import GimpMcpError
from ..toolkit import DESTRUCTIVE, MUTATING, Deprecation, Toolkit, renamed
from .inspect import ImageId, ItemId
from .selection import SelectionState

Operation = Literal["replace", "add", "subtract", "intersect"]
Criterion = Annotated[
    str, Field(description="composite, red, green, blue, alpha, hs-hue, hs-saturation, hs-value, lch-lightness…")
]
ChannelId = Annotated[str, Field(description="Channel id (an item id), from gimp_inspect_image's 'channels'.")]
OptionalChannel = Annotated[
    str | None, Field(description="Channel id (an item id), from gimp_inspect_image's 'channels'.")
]
OldChannelId = Annotated[str | None, Field(description="Deprecated since 0.7.0: use channel.")]
CHANNEL_ID = {"channel_id": Deprecation("0.7.0", "use channel")}


class ChannelInfo(BaseModel):
    id: str
    name: str
    visible: bool
    opacity: float
    color: str
    show_masked: bool


class Deleted(BaseModel):
    deleted: str


def register(kit: Toolkit) -> None:
    async def selection(method: str, params: dict[str, Any]) -> SelectionState:
        codec = await kit.codec()
        if params.get("image"):
            params["image"] = codec.parse_image(params["image"])
        if params.get("item"):
            params["item"] = codec.parse_item(params["item"])
        data = await kit.call(method, params, codec=codec, mutating=True)
        return SelectionState(**{**data, "image": codec.image(data["image"])})

    async def call_channel(method: str, params: dict[str, Any]) -> dict[str, Any]:
        codec = await kit.codec()
        for key in ("channel", "other"):
            if params.get(key):
                params[key] = codec.parse_item(params[key])
        if params.get("image"):
            params["image"] = codec.parse_image(params["image"])
        data = await kit.call(method, params, codec=codec, mutating=True)
        return {**data, "id": codec.item(data["id"])} if "id" in data else {"deleted": codec.item(data["deleted"])}

    @kit.tool(
        toolset="channels",
        name="gimp_select_by_color",
        title="Select by color / fuzzy select",
        description=(
            "Select pixels similar to color everywhere (by color), or the contiguous area around point (fuzzy "
            "select / magic wand). threshold 0-255, criterion, sample_merged (all visible layers instead of item, "
            "default the top layer), antialias, feather radius, operation replace/add/subtract/intersect. One undo "
            "step."
        ),
        annotations=MUTATING,
    )
    async def gimp_select_by_color(
        image: ImageId,
        color: str | None = None,
        point: Annotated[list[int] | None, Field(min_length=2, max_length=2)] = None,
        item: ItemId | None = None,
        threshold: Annotated[float, Field(ge=0, le=255)] = 15,
        criterion: Criterion = "composite",
        sample_merged: bool = False,
        diagonal: bool = False,
        antialias: bool = True,
        feather: Annotated[float, Field(ge=0, le=500)] = 0,
        operation: Operation = "replace",
    ) -> SelectionState:
        if (color is None) == (point is None):
            raise GimpMcpError("INVALID_ARGUMENT", "give a color (select by color) or a point (fuzzy select)")
        return await selection(
            "select.color",
            {"image": image, "item": item, "color": parse_color(color).to_wire() if color else None, "point": point,
             "threshold": threshold, "criterion": criterion, "sample_merged": sample_merged, "diagonal": diagonal,
             "antialias": antialias, "feather": feather, "operation": operation},
        )  # fmt: skip

    @kit.tool(
        toolset="channels",
        name="gimp_select_item",
        title="Select from an item",
        description=(
            "Select from a layer's alpha, a text layer's glyphs, a path's enclosed area, a channel or a mask "
            "(operation replace/add/subtract/intersect, antialias, feather). One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_select_item(
        item: ItemId,
        operation: Operation = "replace",
        antialias: bool = True,
        feather: Annotated[float, Field(ge=0, le=500)] = 0,
    ) -> SelectionState:
        return await selection(
            "select.item", {"item": item, "operation": operation, "antialias": antialias, "feather": feather}
        )

    @kit.tool(
        toolset="channels",
        name="gimp_modify_selection_shape",
        title="Grow, shrink, border, feather…",
        description=(
            "Change the selection: grow / shrink / border (amount in px), feather (radius px), sharpen (remove "
            "partial selection), round (corners, amount in % of the smaller side), remove-holes (flood), translate "
            "(dx, dy). One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_modify_selection_shape(
        image: ImageId,
        action: Literal["grow", "shrink", "border", "feather", "sharpen", "round", "remove-holes", "translate"],
        amount: Annotated[float, Field(ge=0, le=10000)] = 0,
        dx: int = 0,
        dy: int = 0,
    ) -> SelectionState:
        if action in ("grow", "shrink", "border", "feather", "round") and amount <= 0:
            raise GimpMcpError("INVALID_ARGUMENT", f"{action} needs a positive amount")
        return await selection(
            "selection.modify_advanced", {"image": image, "action": action, "amount": amount, "dx": dx, "dy": dy}
        )

    @kit.tool(
        toolset="channels",
        name="gimp_create_channel",
        title="Create a channel",
        description=(
            "Add a channel: empty (color, opacity), the current selection saved (source=selection) or a copy of a "
            "color component (source=component: red, green, blue, gray, indexed, alpha). It appears in "
            "gimp_inspect_image's channels and is saved in XCF. Select it back with gimp_select_item. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_channel(
        image: ImageId,
        name: str = "Channel",
        source: Literal["empty", "selection", "component"] = "empty",
        component: Literal["red", "green", "blue", "gray", "indexed", "alpha"] | None = None,
        color: str = "#000000",
        opacity: Annotated[float, Field(ge=0, le=100)] = 50.0,
    ) -> ChannelInfo:
        if source == "component" and component is None:
            raise GimpMcpError("INVALID_ARGUMENT", "source='component' needs a component")
        data = await call_channel(
            "channel.create",
            {"image": image, "name": name, "source": source, "component": component,
             "color": parse_color(color).to_wire(), "opacity": opacity},
        )  # fmt: skip
        return ChannelInfo(**data)

    @kit.tool(
        toolset="channels",
        name="gimp_set_channel",
        title="Change a channel",
        description=(
            "Rename a channel, set its overlay color, opacity (0-100), visibility or show_masked. One undo step."
        ),
        annotations=MUTATING,
        deprecated_parameters=CHANNEL_ID,
    )
    async def gimp_set_channel(
        channel: OptionalChannel = None,
        name: str | None = None,
        color: str | None = None,
        opacity: Annotated[float | None, Field(ge=0, le=100)] = None,
        visible: bool | None = None,
        show_masked: bool | None = None,
        channel_id: OldChannelId = None,
    ) -> ChannelInfo:
        target = renamed("gimp_set_channel", "channel", channel, "channel_id", channel_id)
        data = await call_channel(
            "channel.set",
            {"channel": target, "name": name, "color": parse_color(color).to_wire() if color else None,
             "opacity": opacity, "visible": visible, "show_masked": show_masked},
        )  # fmt: skip
        return ChannelInfo(**data)

    @kit.tool(
        toolset="channels",
        name="gimp_combine_channels",
        title="Combine channels",
        description=(
            "Combine other into channel (add, subtract, replace, intersect), like selection operations. One undo step."
        ),
        annotations=MUTATING,
        deprecated_parameters=CHANNEL_ID,
    )
    async def gimp_combine_channels(
        other: ChannelId,
        channel: OptionalChannel = None,
        operation: Operation = "add",
        channel_id: OldChannelId = None,
    ) -> ChannelInfo:
        target = renamed("gimp_combine_channels", "channel", channel, "channel_id", channel_id)
        data = await call_channel("channel.combine", {"channel": target, "other": other, "operation": operation})
        return ChannelInfo(**data)

    @kit.tool(
        toolset="channels",
        name="gimp_delete_channel",
        title="Delete a channel",
        description="Remove a channel from its image. One undo step.",
        annotations=DESTRUCTIVE,
        deprecated_parameters=CHANNEL_ID,
    )
    async def gimp_delete_channel(channel: OptionalChannel = None, channel_id: OldChannelId = None) -> Deleted:
        target = renamed("gimp_delete_channel", "channel", channel, "channel_id", channel_id)
        return Deleted(**await call_channel("channel.delete", {"channel": target}))

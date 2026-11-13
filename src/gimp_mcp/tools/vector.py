"""Vector layers and link layers (GIMP 3.2, #57).

A vector layer renders a path with fill and stroke settings that stay editable; a link layer shows an
external image file. Painting and destructive filters refuse both (they would turn them into pixels).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ..colors import parse_color
from ..models import LayerNode, encode_layer
from ..paths import check_input_file
from ..toolkit import MUTATING, READ_ONLY, Toolkit
from .inspect import ImageId, ItemId


class Fill(BaseModel):
    enabled: bool | None = None
    color: str | None = Field(default=None, description="'#rrggbb[aa]'.")


class Stroke(BaseModel):
    enabled: bool | None = None
    color: str | None = None
    width: Annotated[float | None, Field(gt=0, le=10000)] = None
    cap: Literal["butt", "round", "square"] | None = None
    join: Literal["miter", "round", "bevel"] | None = None
    miter_limit: Annotated[float | None, Field(ge=0, le=100)] = None
    dash: Annotated[list[Annotated[float, Field(ge=0)]] | None, Field(max_length=32)] = None
    dash_offset: float | None = None


class VectorLayer(LayerNode):
    path: str | None
    fill: dict[str, Any]
    stroke: dict[str, Any]


class LinkLayer(LayerNode):
    file: str | None
    mime_type: str | None


def wire_settings(fill: Fill | None, stroke: Stroke | None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if fill is not None:
        data["fill"] = fill.model_dump()
        if fill.color:
            data["fill"]["color"] = parse_color(fill.color).to_wire()
    if stroke is not None:
        data["stroke"] = stroke.model_dump()
        if stroke.color:
            data["stroke"]["color"] = parse_color(stroke.color).to_wire()
    return data


def register(kit: Toolkit) -> None:
    async def call(method: str, params: dict[str, Any], mutating: bool = True) -> tuple[dict[str, Any], Any]:
        codec = await kit.codec()
        for key in ("item", "path"):
            if params.get(key):
                params[key] = codec.parse_item(params[key])
        if params.get("image"):
            params["image"] = codec.parse_image(params["image"])
        return await kit.call(method, params, codec=codec, mutating=mutating), codec

    def vector(codec: Any, data: dict[str, Any]) -> VectorLayer:
        base = encode_layer(codec, data).model_dump()
        path = codec.item(data["path"]) if data.get("path") is not None else None
        return VectorLayer(**base, path=path, fill=data["fill"], stroke=data["stroke"])

    def link(codec: Any, data: dict[str, Any]) -> LinkLayer:
        return LinkLayer(**encode_layer(codec, data).model_dump(), file=data["file"], mime_type=data["mime_type"])

    @kit.tool(
        toolset="vector",
        name="gimp_create_vector_layer",
        title="Create a vector layer",
        description=(
            "Create a vector layer that renders a path with fill (color) and stroke (color, width, cap, join, "
            "miter limit, dash pattern in multiples of the width) settings that stay editable. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_vector_layer(
        path: Annotated[str, Field(description="Path id.")],
        name: str | None = None,
        fill: Fill | None = None,
        stroke: Stroke | None = None,
        position: Annotated[int, Field(ge=0)] = 0,
    ) -> VectorLayer:
        data, codec = await call("vector.create", {"path": path, "name": name, "position": position,
                                                   **wire_settings(fill, stroke)})  # fmt: skip
        return vector(codec, data)

    @kit.tool(
        toolset="vector",
        name="gimp_set_vector_layer",
        title="Change a vector layer",
        description="Change a vector layer's fill and/or stroke settings; only the given values change. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_set_vector_layer(
        item: ItemId, fill: Fill | None = None, stroke: Stroke | None = None
    ) -> VectorLayer:
        data, codec = await call("vector.set", {"item": item, **wire_settings(fill, stroke)})
        return vector(codec, data)

    @kit.tool(
        toolset="vector",
        name="gimp_inspect_vector_layer",
        title="Inspect a vector layer",
        description="A vector layer's path, fill and stroke settings.",
        annotations=READ_ONLY,
    )
    async def gimp_inspect_vector_layer(item: ItemId) -> VectorLayer:
        data, codec = await call("vector.inspect", {"item": item}, mutating=False)
        return vector(codec, data)

    @kit.tool(
        toolset="vector",
        name="gimp_create_link_layer",
        title="Create a link layer",
        description=(
            "Add a layer that shows an external image file (any format GIMP opens). GIMP keeps the path and "
            "re-reads the file when the XCF is opened. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_link_layer(
        image: ImageId,
        path: Annotated[str, Field(description="Absolute path of the image file to link.")],
        name: str | None = None,
        position: Annotated[int, Field(ge=0)] = 0,
    ) -> LinkLayer:
        source = str(check_input_file(path))
        data, codec = await call("link.create", {"image": image, "file": source, "name": name, "position": position})
        return link(codec, data)

    @kit.tool(
        toolset="vector",
        name="gimp_set_link_layer",
        title="Change a link layer's file",
        description="Point a link layer at another image file. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_set_link_layer(
        item: ItemId,
        path: Annotated[str, Field(description="Absolute path of the image file to link.")],
    ) -> LinkLayer:
        source = str(check_input_file(path))
        data, codec = await call("link.set", {"item": item, "file": source})
        return link(codec, data)

    @kit.tool(
        toolset="vector",
        name="gimp_inspect_link_layer",
        title="Inspect a link layer",
        description="The file a link layer shows and its MIME type.",
        annotations=READ_ONLY,
    )
    async def gimp_inspect_link_layer(item: ItemId) -> LinkLayer:
        data, codec = await call("link.inspect", {"item": item}, mutating=False)
        return link(codec, data)

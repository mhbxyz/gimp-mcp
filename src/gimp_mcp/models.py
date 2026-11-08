"""Output models shared by tools, and conversion of bridge payloads (raw ints -> opaque ids)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .ids import IdCodec

LayerKind = Literal["layer", "group", "text"]
ItemKind = Literal["layer", "group", "text", "mask", "channel", "path"]


class Locks(BaseModel):
    content: bool
    position: bool
    visibility: bool
    alpha: bool


class MaskInfo(BaseModel):
    id: str = Field(description="Item id of the layer mask.")
    apply: bool = Field(description="Whether the mask is applied to the layer's rendering.")
    show: bool = Field(description="Whether GIMP displays the mask instead of the layer.")
    edit: bool = Field(description="Whether painting targets the mask instead of the layer.")


class LayerNode(BaseModel):
    id: str
    name: str = Field(description="Layer name. GIMP keeps names unique within an image ('Title #1').")
    kind: LayerKind
    parent: str | None = Field(description="Id of the parent group, null at the top level.")
    visible: bool
    opacity: float = Field(description="0-100.")
    mode: str = Field(description="GIMP layer mode nick, e.g. 'normal', 'multiply'.")
    x: int = Field(description="Offset of the layer's top-left corner in image pixels.")
    y: int
    width: int
    height: int
    has_alpha: bool
    locks: Locks
    mask: MaskInfo | None
    children: list[LayerNode] | None = Field(
        default=None, description="Child layers of a group, top-most first; null for non-groups."
    )


class Resolution(BaseModel):
    x: float = Field(description="Pixels per inch.")
    y: float


class PathSummary(BaseModel):
    id: str
    name: str
    visible: bool
    strokes: int


class ChannelSummary(BaseModel):
    id: str
    name: str
    visible: bool
    opacity: float
    color: str
    show_masked: bool


class ImageDetails(BaseModel):
    id: str
    name: str = Field(description="GIMP's display name (may be localized).")
    file: str | None
    xcf_file: str | None = Field(description="XCF file the image was loaded from or saved to.")
    imported_file: str | None
    exported_file: str | None
    width: int
    height: int
    base_type: str = Field(description="'rgb', 'gray' or 'indexed'.")
    precision: str
    resolution: Resolution
    unit: str | None = Field(default=None, description="Display/print unit abbreviation, e.g. 'in', 'mm'.")
    dirty: bool
    layers: list[LayerNode] = Field(description="Layer tree, top-most layer first.")
    paths: list[PathSummary] = Field(default_factory=list, description="Paths (vectors), top first.")
    channels: list[ChannelSummary] = Field(default_factory=list, description="Saved selections and masks.")


class ItemDetails(BaseModel):
    id: str
    image: str
    kind: ItemKind
    name: str
    parent: str | None = Field(description="Parent group id (layers) or owning layer id (masks).")
    position: int | None = Field(description="Index within the parent, 0 = top-most.")
    visible: bool
    opacity: float | None = None
    mode: str | None = None
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    has_alpha: bool | None = None
    locks: Locks | None = None
    mask: MaskInfo | None = None
    children: list[str] | None = Field(default=None, description="Child ids for groups, top-most first.")


def _opt_item(codec: IdCodec, value: int | None) -> str | None:
    return None if value is None else codec.item(value)


def encode_mask(codec: IdCodec, mask: dict[str, Any] | None) -> MaskInfo | None:
    if mask is None:
        return None
    return MaskInfo(**{**mask, "id": codec.item(mask["id"])})


def encode_layer(codec: IdCodec, node: dict[str, Any]) -> LayerNode:
    children = node.get("children")
    return LayerNode(
        **{
            **node,
            "id": codec.item(node["id"]),
            "parent": _opt_item(codec, node.get("parent")),
            "mask": encode_mask(codec, node.get("mask")),
            "children": None if children is None else [encode_layer(codec, child) for child in children],
        }
    )


def encode_image(codec: IdCodec, data: dict[str, Any]) -> ImageDetails:
    return ImageDetails(
        **{
            **data,
            "id": codec.image(data["id"]),
            "layers": [encode_layer(codec, node) for node in data["layers"]],
            "paths": [{**p, "id": codec.item(p["id"])} for p in data.get("paths", [])],
            "channels": [{**c, "id": codec.item(c["id"])} for c in data.get("channels", [])],
        }
    )


def encode_item(codec: IdCodec, data: dict[str, Any]) -> ItemDetails:
    children = data.get("children")
    if children is not None and children and isinstance(children[0], dict):
        children = [child["id"] for child in children]
    return ItemDetails(
        **{
            **data,
            "id": codec.item(data["id"]),
            "image": codec.image(data["image"]),
            "parent": _opt_item(codec, data.get("parent")),
            "mask": encode_mask(codec, data.get("mask")),
            "children": None if children is None else [codec.item(child) for child in children],
        }
    )

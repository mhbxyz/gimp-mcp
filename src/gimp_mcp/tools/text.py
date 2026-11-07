"""Editable text layers."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ..colors import COLOR_DESCRIPTION, parse_color
from ..models import LayerNode, encode_layer
from ..toolkit import MUTATING, READ_ONLY, Toolkit
from .inspect import ImageId, ItemId
from .layers import ParentId, Position

Justify = Literal["left", "right", "center", "fill"]
SizeUnit = Literal["px", "pt"]
FontSize = Annotated[float, Field(gt=0, le=8192, description="Font size, in size_unit.")]


class TextProperties(BaseModel):
    item: str
    text: str
    font: str
    size: float
    size_unit: str = Field(description="'px' (pixels) or 'pt' (points, converted with the image resolution).")
    color: str = Field(description="#rrggbb (sRGB).")
    justify: Justify
    letter_spacing: float = Field(description="Extra pixels between letters.")
    line_spacing: float = Field(description="Extra pixels between lines.")
    antialias: bool
    x: int
    y: int
    width: int
    height: int


class FontList(BaseModel):
    fonts: list[str]
    total: int


def register(kit: Toolkit) -> None:
    def text_params(
        *,
        text: str | None,
        font: str | None,
        size: float | None,
        size_unit: str | None,
        color: str | None,
        justify: str | None,
        letter_spacing: float | None,
        line_spacing: float | None,
        box_width: int | None,
        box_height: int | None,
        antialias: bool | None,
    ) -> dict[str, Any]:
        return {
            "text": text,
            "font": font,
            "size": size,
            "unit": size_unit,
            "color": None if color is None else parse_color(color).to_wire(),
            "justify": justify,
            "letter_spacing": letter_spacing,
            "line_spacing": line_spacing,
            "box": None if box_width is None or box_height is None else [box_width, box_height],
            "antialias": antialias,
        }

    @kit.tool(
        name="gimp_create_text_layer",
        title="Create text layer",
        description=(
            "Add an editable text layer. Position (x, y) is the top-left corner in image pixels. size is in "
            "size_unit ('px' or 'pt'). Without box_width/box_height the layer grows with the text; with both, "
            "the text wraps in a fixed box. The text stays editable (never rasterized). One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_text_layer(
        image: ImageId,
        text: str,
        font: str = "Sans-serif",
        size: FontSize = 32.0,
        size_unit: SizeUnit = "px",
        color: Annotated[str, Field(description=COLOR_DESCRIPTION)] = "#000000",
        x: int = 0,
        y: int = 0,
        justify: Justify = "left",
        letter_spacing: Annotated[float, Field(ge=-1000, le=1000)] = 0.0,
        line_spacing: Annotated[float, Field(ge=-1000, le=1000)] = 0.0,
        box_width: Annotated[int | None, Field(ge=1, le=65536)] = None,
        box_height: Annotated[int | None, Field(ge=1, le=65536)] = None,
        antialias: bool = True,
        parent: ParentId = None,
        position: Position = 0,
    ) -> LayerNode:
        codec = await kit.codec()
        params = text_params(
            text=text,
            font=font,
            size=size,
            size_unit=size_unit,
            color=color,
            justify=justify,
            letter_spacing=letter_spacing,
            line_spacing=line_spacing,
            box_width=box_width,
            box_height=box_height,
            antialias=antialias,
        )
        data = await kit.call(
            "text.create",
            {
                **params,
                "image": codec.parse_image(image),
                "x": x,
                "y": y,
                "parent": None if parent is None else codec.parse_item(parent),
                "position": position,
            },
            codec=codec,
            mutating=True,
        )
        return encode_layer(codec, data)

    @kit.tool(
        name="gimp_set_text",
        title="Edit text layer",
        description=(
            "Change the text, font, size, color, justification, spacing, box or position of an existing text "
            "layer; only given properties change. Refused with WRONG_KIND on non-text layers and with "
            "FONT_NOT_FOUND (nothing changed) for unknown fonts. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_text(
        item: ItemId,
        text: str | None = None,
        font: str | None = None,
        size: FontSize | None = None,
        size_unit: SizeUnit | None = None,
        color: Annotated[str | None, Field(description=COLOR_DESCRIPTION)] = None,
        justify: Justify | None = None,
        letter_spacing: Annotated[float | None, Field(ge=-1000, le=1000)] = None,
        line_spacing: Annotated[float | None, Field(ge=-1000, le=1000)] = None,
        box_width: Annotated[int | None, Field(ge=1, le=65536)] = None,
        box_height: Annotated[int | None, Field(ge=1, le=65536)] = None,
        antialias: bool | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> LayerNode:
        codec = await kit.codec()
        params = text_params(
            text=text,
            font=font,
            size=size,
            size_unit=size_unit,
            color=color,
            justify=justify,
            letter_spacing=letter_spacing,
            line_spacing=line_spacing,
            box_width=box_width,
            box_height=box_height,
            antialias=antialias,
        )
        data = await kit.call(
            "text.set", {**params, "item": codec.parse_item(item), "x": x, "y": y}, codec=codec, mutating=True
        )
        return encode_layer(codec, data)

    @kit.tool(
        name="gimp_inspect_text",
        title="Inspect text layer",
        description="Text, font, size and unit, color, justification, spacing, antialiasing and geometry.",
        annotations=READ_ONLY,
    )
    async def gimp_inspect_text(item: ItemId) -> TextProperties:
        codec = await kit.codec()
        data = await kit.call("text.get", {"item": codec.parse_item(item)}, codec=codec)
        return TextProperties(**{**data, "item": item})

    @kit.tool(
        name="gimp_list_fonts",
        title="List fonts",
        description="Fonts GIMP knows (fontconfig names), filtered by a substring.",
        annotations=READ_ONLY,
    )
    async def gimp_list_fonts(query: str = "", limit: Annotated[int, Field(ge=1, le=2000)] = 100) -> FontList:
        return FontList(**await kit.call("fonts.list", {"query": query, "limit": limit}))

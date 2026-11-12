"""Advanced text (#56): rich text markup, outlines, kerning, hinting, indentation, language, direction.

Text layers stay editable text: every change goes through GIMP's text layer API.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..colors import parse_color
from ..models import ChangedObject
from ..toolkit import MUTATING, READ_ONLY, Toolkit
from .inspect import ItemId


class Outline(BaseModel):
    mode: Literal["none", "stroke-only", "stroke-fill"] | None = None
    color: str | None = Field(default=None, description="'#rrggbb[aa]'.")
    width: Annotated[float | None, Field(ge=0, le=1000)] = None
    cap: Literal["butt", "round", "square"] | None = None
    join: Literal["miter", "round", "bevel"] | None = None
    miter_limit: Annotated[float | None, Field(ge=0, le=100)] = None
    antialias: bool | None = None


class Box(BaseModel):
    width: Annotated[float, Field(gt=0, le=65536)]
    height: Annotated[float, Field(gt=0, le=65536)]


class TextStyle(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    text: str | None
    markup: str | None = Field(description="Pango markup when the text has per-run styles, else null.")
    outline: dict[str, Any]
    kerning: bool
    hint_style: str
    indent: float
    language: str | None
    base_direction: str
    antialias: bool
    width: int
    height: int


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="typography",
        name="gimp_set_text_style",
        title="Rich text and text style",
        description=(
            "Change a text layer, keeping it editable: markup (Pango: <b>, <i>, <u>, <s>, <span font size "
            "foreground letter_spacing rise underline …>, validated), outline (stroke-only or stroke-fill, color, "
            "width, cap, join), kerning, hint_style, indent (px), language (e.g. 'ar', 'he', 'ja'), base_direction "
            "(ltr, rtl, vertical ttb-*), box (fixed width/height for wrapping and alignment). One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_text_style(
        item: ItemId,
        markup: Annotated[str | None, Field(max_length=100_000)] = None,
        outline: Outline | None = None,
        kerning: bool | None = None,
        hint_style: Literal["none", "slight", "medium", "full"] | None = None,
        indent: Annotated[float | None, Field(ge=-10000, le=10000)] = None,
        language: Annotated[str | None, Field(max_length=35)] = None,
        base_direction: Literal["ltr", "rtl", "ttb-rtl", "ttb-rtl-upright", "ttb-ltr", "ttb-ltr-upright"] | None = None,
        box: Box | None = None,
    ) -> TextStyle:
        wire_outline = None
        if outline is not None:
            wire_outline = outline.model_dump()
            if outline.color:
                wire_outline["color"] = parse_color(outline.color).to_wire()
        codec = await kit.codec()
        data = await kit.call(
            "text.style_set",
            {"item": codec.parse_item(item), "markup": markup, "outline": wire_outline, "kerning": kerning,
             "hint_style": hint_style, "indent": indent, "language": language, "base_direction": base_direction,
             "box": box.model_dump() if box else None},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return TextStyle(**{**data, "item": item})

    @kit.tool(
        toolset="typography",
        name="gimp_inspect_text_style",
        title="Inspect text style",
        description="A text layer's markup, outline, kerning, hinting, indent, language, direction and box size.",
        annotations=READ_ONLY,
    )
    async def gimp_inspect_text_style(item: ItemId) -> TextStyle:
        codec = await kit.codec()
        data = await kit.call("text.style_get", {"item": codec.parse_item(item)}, codec=codec)
        return TextStyle(**{**data, "item": item})

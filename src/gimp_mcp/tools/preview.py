"""Visual preview of an image's composite, for observe-modify-verify loops."""

from __future__ import annotations

import os
from typing import Annotated

from mcp_types import ImageContent
from pydantic import BaseModel, Field

from ..toolkit import READ_ONLY, Toolkit, ToolResult
from .inspect import ImageId

MIN_PREVIEW = 16
MAX_PREVIEW = 1024  # GIMP's thumbnail renderer refuses larger sizes
DEFAULT_PREVIEW = 512
DEFAULT_MAX_BYTES = 2_000_000


def default_max_size() -> int:
    try:
        value = int(os.environ.get("GIMP_MCP_PREVIEW_MAX_SIZE", DEFAULT_PREVIEW))
    except ValueError:
        value = DEFAULT_PREVIEW
    return max(MIN_PREVIEW, min(MAX_PREVIEW, value))


def max_bytes() -> int:
    try:
        return max(10_000, int(os.environ.get("GIMP_MCP_PREVIEW_MAX_BYTES", DEFAULT_MAX_BYTES)))
    except ValueError:
        return DEFAULT_MAX_BYTES


class PreviewInfo(BaseModel):
    image: str
    mime_type: str = "image/png"
    width: int = Field(description="Preview width in pixels.")
    height: int
    source_width: int = Field(description="Image width in pixels.")
    source_height: int
    scale: float = Field(description="Preview pixels per image pixel (<= 1).")
    bytes: int = Field(description="Size of the PNG payload.")
    downscaled_for_size: bool = Field(
        description="True when the preview was made smaller than requested to respect the byte limit."
    )


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="core",
        name="gimp_preview",
        title="Preview image",
        description=(
            "Render the composite of an image (all visible layers, with transparency) as a PNG whose "
            f"longest side is at most max_size pixels ({MIN_PREVIEW}-{MAX_PREVIEW}, default "
            f"{DEFAULT_PREVIEW} or $GIMP_MCP_PREVIEW_MAX_SIZE). Proportions are kept and the image is "
            "never upscaled. Does not modify the document, its undo history or its saved state."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_preview(
        image: ImageId,
        max_size: Annotated[
            int | None, Field(ge=MIN_PREVIEW, le=MAX_PREVIEW, description="Longest side of the preview.")
        ] = None,
    ) -> PreviewInfo:
        codec = await kit.codec()
        size = max_size or default_max_size()
        data = await kit.call(
            "image.preview",
            {"image": codec.parse_image(image), "max_size": size, "max_bytes": max_bytes()},
            codec=codec,
        )
        payload = data["png_base64"]
        info = PreviewInfo(
            image=image,
            width=data["width"],
            height=data["height"],
            source_width=data["source_width"],
            source_height=data["source_height"],
            scale=data["width"] / data["source_width"],
            bytes=len(payload) * 3 // 4,
            downscaled_for_size=data["downscaled_for_size"],
        )
        return ToolResult(info, [ImageContent(type="image", data=payload, mime_type="image/png")])  # type: ignore[return-value]

"""Measure pixels (#46): histograms, color samples, comparisons, dominant colors, full-resolution crops.

Every tool is read-only: the image, its undo history and its saved state are left untouched.
Pixel values are 8-bit sRGB (0-255) whatever the image precision.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp_types import ImageContent
from pydantic import BaseModel, Field

from ..ids import IdCodec
from ..toolkit import READ_ONLY, Toolkit, ToolResult
from .inspect import ImageId

Target = Annotated[
    str,
    Field(description="An image id (its visible composite) or an item id (a layer, mask or channel's own pixels)."),
]
Comparable = Annotated[
    str, Field(description="An image id (composite), an item id (drawable pixels) or a checkpoint id.")
]
Channel = Literal["red", "green", "blue", "alpha", "luminance"]


class Region(BaseModel):
    x: int = Field(description="Left edge in image pixels.")
    y: int
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class ChannelStats(BaseModel):
    pixel_count: int
    mean: float | None = None
    median: float | None = None
    std_dev: float | None = None
    min: int | None = None
    max: int | None = None
    percentiles: dict[str, int] | None = Field(default=None, description="Nearest-rank percentiles, keyed '5', '50'...")
    histogram: list[int] | None = Field(default=None, description="Pixel counts in equal bins over 0-255.")


class HistogramResult(BaseModel):
    region: Region = Field(description="Area measured, clipped to the pixels (image coordinates).")
    selection_only: bool
    channels: dict[str, ChannelStats]


class Sample(BaseModel):
    x: int
    y: int
    hex: str
    rgba: list[int] = Field(description="0-255 each.")
    pixels_averaged: int


class SampleResult(BaseModel):
    samples: list[Sample]


class CompareResult(BaseModel):
    width: int
    height: int
    changed_pixels: int = Field(description="Pixels whose largest channel difference exceeds the threshold.")
    changed_fraction: float
    bounds: Region | None = Field(description="Bounding box of the changed pixels, null when nothing changed.")
    mean_difference: float = Field(description="Mean absolute difference over all pixels and RGBA channels (0-255).")
    max_difference: int
    threshold: int
    preview_width: int | None = None
    preview_height: int | None = None


class DominantColor(BaseModel):
    hex: str
    rgb: list[int]
    fraction: float = Field(description="Share of the opaque pixels.")


class DominantResult(BaseModel):
    region: Region
    sampled_scale: float = Field(description="Scale of the pixels examined (<= 1: large areas are downscaled).")
    colors: list[DominantColor]


class RegionPreview(BaseModel):
    image: str
    region: Region
    mime_type: str = "image/png"
    width: int
    height: int
    scale: float = Field(description="Preview pixels per image pixel (1 = full resolution).")


def target_ref(codec: IdCodec, value: str, kinds: tuple[str, ...] = ("image", "item")) -> dict[str, Any]:
    kind, number = codec.parse_any(value, kinds)
    return {"kind": kind, "id": number}


def png_block(payload: str) -> ImageContent:
    return ImageContent(type="image", data=payload, mime_type="image/png")


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="analysis",
        name="gimp_histogram",
        title="Histogram and statistics",
        description=(
            "Measure pixel values per channel (0-255, sRGB): pixel count, mean, median, standard deviation, min, "
            "max, percentiles and a histogram. Target an image (its visible composite) or a layer/mask/channel; "
            "optionally limit to a region (image coordinates) and/or to the selection (pixels selected >= 50%). "
            "'luminance' is relative luminance on the sRGB curve. Read-only."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_histogram(
        target: Target,
        channels: Annotated[list[Channel], Field(min_length=1)] = ["red", "green", "blue", "luminance"],  # noqa: B006
        region: Region | None = None,
        selection_only: bool = False,
        percentiles: Annotated[list[Annotated[float, Field(ge=0, le=100)]], Field(max_length=20)] = [5, 25, 50, 75, 95],  # noqa: B006
        bins: Annotated[int, Field(ge=0, le=256, description="Histogram bins; 0 for none.")] = 16,
    ) -> HistogramResult:
        codec = await kit.codec()
        data = await kit.call(
            "analysis.histogram",
            {
                "target": target_ref(codec, target),
                "channels": list(channels),
                "region": region.model_dump() if region else None,
                "selection_only": selection_only,
                "percentiles": list(percentiles),
                "bins": bins,
            },
            codec=codec,
        )
        return HistogramResult(**data)

    @kit.tool(
        toolset="analysis",
        name="gimp_sample_colors",
        title="Sample colors",
        description=(
            "Read the color at one or more points (image coordinates) of an image composite or a layer, "
            "optionally averaged over a square of (2*radius+1) pixels per side, clipped to the pixels. Read-only."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_sample_colors(
        target: Target,
        points: Annotated[
            list[Annotated[list[int], Field(min_length=2, max_length=2)]],
            Field(min_length=1, max_length=64, description="[[x, y], ...]"),
        ],
        radius: Annotated[int, Field(ge=0, le=50)] = 0,
    ) -> SampleResult:
        codec = await kit.codec()
        data = await kit.call(
            "analysis.sample",
            {"target": target_ref(codec, target), "points": [list(p) for p in points], "radius": radius},
            codec=codec,
        )
        return SampleResult(**data)

    @kit.tool(
        toolset="analysis",
        name="gimp_compare",
        title="Compare pixels",
        description=(
            "Compare two images (composites), layers or checkpoints of the same size: number and bounding box of "
            "changed pixels, mean and max difference. A pixel is changed when one of its RGBA values (0-255) "
            "differs by more than threshold. preview=true adds an image of the changes (red) over a dimmed "
            "copy of b. Read-only."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_compare(
        a: Comparable,
        b: Comparable,
        threshold: Annotated[int, Field(ge=0, le=254)] = 0,
        preview: bool = False,
        max_size: Annotated[int, Field(ge=16, le=1024, description="Longest side of the preview.")] = 512,
    ) -> CompareResult:
        codec = await kit.codec()
        kinds = ("image", "item", "checkpoint")
        data = await kit.call(
            "analysis.compare",
            {
                "a": target_ref(codec, a, kinds),
                "b": target_ref(codec, b, kinds),
                "threshold": threshold,
                "preview": preview,
                "max_size": max_size,
            },
            codec=codec,
        )
        shown = data.pop("preview", None)
        result = CompareResult(**data)
        if not shown:
            return result
        result.preview_width, result.preview_height = shown["width"], shown["height"]
        return ToolResult(result, [png_block(shown["png_base64"])])  # type: ignore[return-value]

    @kit.tool(
        toolset="analysis",
        name="gimp_dominant_colors",
        title="Dominant colors",
        description=(
            "Most common colors of an image composite or a layer (optionally a region), with their share of the "
            "opaque pixels. Colors are grouped in 16 levels per channel; areas larger than 256 pixels are "
            "examined downscaled. Read-only."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_dominant_colors(
        target: Target,
        region: Region | None = None,
        count: Annotated[int, Field(ge=1, le=16)] = 5,
    ) -> DominantResult:
        codec = await kit.codec()
        data = await kit.call(
            "analysis.dominant",
            {"target": target_ref(codec, target), "region": region.model_dump() if region else None, "count": count},
            codec=codec,
        )
        return DominantResult(**data)

    @kit.tool(
        toolset="analysis",
        name="gimp_preview_region",
        title="Preview a region",
        description=(
            "Render a rectangle of an image's composite as a PNG, at full resolution when it fits in max_size "
            "(up to 1024 pixels per side), to inspect details that gimp_preview scales away. Read-only."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_preview_region(
        image: ImageId,
        x: Annotated[int, Field(ge=0)],
        y: Annotated[int, Field(ge=0)],
        width: Annotated[int, Field(ge=1)],
        height: Annotated[int, Field(ge=1)],
        max_size: Annotated[int, Field(ge=16, le=1024)] = 1024,
    ) -> RegionPreview:
        codec = await kit.codec()
        data = await kit.call(
            "image.preview_region",
            {
                "target": {"kind": "image", "id": codec.parse_image(image)},
                "region": {"x": x, "y": y, "width": width, "height": height},
                "max_size": max_size,
            },
            codec=codec,
        )
        info = RegionPreview(
            image=image,
            region=Region(**data["region"]),
            width=data["width"],
            height=data["height"],
            scale=data["width"] / width,
        )
        return ToolResult(info, [png_block(data["png_base64"])])  # type: ignore[return-value]

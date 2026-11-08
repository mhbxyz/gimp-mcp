"""Guides, sample points, metadata and print resolution (#60)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..errors import GimpMcpError
from ..toolkit import MUTATING, READ_ONLY, Toolkit
from .inspect import ImageId

Tag = Annotated[str, Field(pattern=r"^(Exif|Xmp|Iptc)\.[A-Za-z0-9_.:-]+$", description="e.g. 'Exif.Image.Artist'.")]


class Guide(BaseModel):
    id: int
    orientation: str
    position: int


class SamplePoint(BaseModel):
    id: int
    x: int
    y: int
    rgba: list[int] | None = Field(default=None, description="Composite color at the point (sRGB 0-255).")
    hex: str | None = None


class GuideList(BaseModel):
    image: str
    guides: list[Guide]
    sample_points: list[SamplePoint]
    guide: int | None = Field(default=None, description="Id of the guide just added.")
    sample_point: int | None = Field(default=None, description="Id of the sample point just added.")


class Metadata(BaseModel):
    image: str
    exif: dict[str, str | None]
    xmp: dict[str, str | None]
    iptc: dict[str, str | None]
    comment: str | None


class PrintInfo(BaseModel):
    image: str
    resolution: dict[str, float] = Field(description="Pixels per inch, x and y.")
    unit: str
    print_size: dict[str, float] = Field(description="Width and height in the image's unit.")


def register(kit: Toolkit) -> None:
    async def call(method: str, image: str, mutating: bool = True, **params: object) -> dict:
        codec = await kit.codec()
        data = await kit.call(method, {"image": codec.parse_image(image), **params}, codec=codec, mutating=mutating)
        return {**data, "image": image}

    @kit.tool(
        toolset="document",
        name="gimp_list_guides",
        title="List guides and sample points",
        description="Guides (orientation, position) and sample points (position and current composite color).",
        annotations=READ_ONLY,
    )
    async def gimp_list_guides(image: ImageId, values: bool = True) -> GuideList:
        return GuideList(**await call("guides.list", image, mutating=False, values=values))

    @kit.tool(
        toolset="document",
        name="gimp_add_guide",
        title="Add a guide",
        description="Add a horizontal guide at y=position or a vertical guide at x=position (0..image size).",
        annotations=MUTATING,
    )
    async def gimp_add_guide(
        image: ImageId, orientation: Literal["horizontal", "vertical"], position: Annotated[int, Field(ge=0)]
    ) -> GuideList:
        return GuideList(**await call("guide.add", image, orientation=orientation, position=position))

    @kit.tool(
        toolset="document",
        name="gimp_add_sample_point",
        title="Add a sample point",
        description="Add a sample point (GIMP's Pointer/Sample Points dialogs follow it) inside the canvas.",
        annotations=MUTATING,
    )
    async def gimp_add_sample_point(
        image: ImageId, x: Annotated[int, Field(ge=0)], y: Annotated[int, Field(ge=0)]
    ) -> GuideList:
        return GuideList(**await call("sample_point.add", image, x=x, y=y))

    @kit.tool(
        toolset="document",
        name="gimp_remove_guide",
        title="Remove a guide or sample point",
        description="Remove a guide (kind='guide') or a sample point (kind='sample_point') by id.",
        annotations=MUTATING,
    )
    async def gimp_remove_guide(
        image: ImageId, id: Annotated[int, Field(ge=1)], kind: Literal["guide", "sample_point"] = "guide"
    ) -> GuideList:
        return GuideList(**await call("guide.remove", image, kind=kind, id=id))

    @kit.tool(
        toolset="document",
        name="gimp_get_metadata",
        title="Read metadata",
        description="The image's Exif, XMP and IPTC tags (interpreted values) and its comment.",
        annotations=READ_ONLY,
    )
    async def gimp_get_metadata(image: ImageId) -> Metadata:
        return Metadata(**await call("metadata.get", image, mutating=False))

    @kit.tool(
        toolset="document",
        name="gimp_set_metadata",
        title="Write metadata",
        description=(
            "Set or remove Exif/XMP/IPTC tags (e.g. 'Exif.Image.Artist', 'Xmp.dc.title', 'Iptc.Application2.Keywords') "
            "and set the comment ('' removes it). Exports write metadata only when asked (png/jpeg_options.metadata)."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_metadata(
        image: ImageId,
        set: Annotated[dict[Tag, str], Field(max_length=200)] = {},  # noqa: B006
        remove: Annotated[list[Tag], Field(max_length=200)] = [],  # noqa: B006
        comment: Annotated[str | None, Field(max_length=65535)] = None,
    ) -> Metadata:
        return Metadata(**await call("metadata.set", image, set=set, remove=remove, comment=comment))

    @kit.tool(
        toolset="document",
        name="gimp_set_print_size",
        title="Set resolution and print size",
        description=(
            "Change how big the image prints without resampling: give a resolution (pixels per inch, x and y) "
            "or a print width and height in unit (inch, mm, point, pica), and/or the image's unit. "
            "Pixels are unchanged. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_print_size(
        image: ImageId,
        x_resolution: Annotated[float | None, Field(ge=5, le=65536)] = None,
        y_resolution: Annotated[float | None, Field(ge=5, le=65536)] = None,
        width: Annotated[float | None, Field(gt=0)] = None,
        height: Annotated[float | None, Field(gt=0)] = None,
        unit: Literal["inch", "mm", "point", "pica"] | None = None,
    ) -> PrintInfo:
        if (width is None) != (height is None):
            raise GimpMcpError("INVALID_ARGUMENT", "give both width and height")
        if width is not None and x_resolution is not None:
            raise GimpMcpError("INVALID_ARGUMENT", "give a resolution or a print size, not both")
        if width is None and x_resolution is None and unit is None:
            raise GimpMcpError("INVALID_ARGUMENT", "nothing to change")
        data = await call("image.set_print", image, x_resolution=x_resolution, y_resolution=y_resolution,
                          width=width, height=height, unit=unit)  # fmt: skip
        return PrintInfo(**data)

"""Create, open, save (XCF), export (PNG/JPEG) and close images."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..colors import COLOR_DESCRIPTION, parse_color
from ..errors import GimpMcpError
from ..paths import check_input_file, check_output_file, export_format
from ..toolkit import DESTRUCTIVE, MUTATING, Toolkit
from .inspect import ImageId

MAX_DIMENSION = 65536


class ImageRef(BaseModel):
    id: str
    name: str = Field(description="GIMP's display name (may be localized).")
    file: str | None
    xcf_file: str | None
    width: int
    height: int
    dirty: bool
    layer_count: int = Field(description="Number of top-level layers.")
    displayed: bool = Field(description="True when a GIMP window shows the image (GUI sessions only).")


class SaveResult(BaseModel):
    image: str
    xcf_file: str
    bytes: int = Field(description="Size of the written file.")
    dirty: bool


class PngOptions(BaseModel):
    compression: int = Field(default=9, ge=0, le=9, description="zlib level, 0 (none) - 9 (smallest). Lossless.")
    interlaced: bool = Field(default=False, description="Adam7 interlacing.")
    color_profile: bool | None = Field(
        default=None, description="Embed the color profile (iCCP); default: only when the image has one assigned."
    )
    metadata: list[Literal["exif", "xmp", "iptc", "comment", "thumbnail", "time"]] = Field(
        default_factory=list,
        description="Metadata to write (none by default: nothing leaks unless asked); time: the tIME chunk.",
    )


class JpegOptions(BaseModel):
    quality: int = Field(default=90, ge=0, le=100, description="0 (worst) - 100 (best).")
    progressive: bool = Field(default=False, description="Progressive instead of baseline encoding.")
    optimize: bool = Field(default=True, description="Optimized Huffman tables.")
    smoothing: float = Field(default=0.0, ge=0.0, le=1.0)
    color_profile: bool | None = Field(
        default=None, description="Embed the color profile (ICC); default: only when the image has one assigned."
    )
    metadata: list[Literal["exif", "xmp", "iptc", "comment", "thumbnail"]] = Field(
        default_factory=list, description="Metadata to write (none by default: nothing leaks unless asked)."
    )
    background: str = Field(
        default="#ffffff", description="Color transparent pixels are flattened onto. " + COLOR_DESCRIPTION
    )


class ExportResult(BaseModel):
    image: str
    path: str
    format: Literal["png", "jpeg"]
    width: int
    height: int
    bytes: int
    options: dict[str, object] = Field(description="Effective encoder options.")


class CloseResult(BaseModel):
    image: str
    closed: bool


def image_ref(codec, data) -> ImageRef:
    return ImageRef(**{**data, "id": codec.image(data["id"])})


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="files",
        name="gimp_create_image",
        title="Create image",
        description=(
            "Create a new image with a single layer named layer_name filled with an explicit color "
            "(default white; 'transparent' gives an alpha layer). Like a new image in GIMP's UI, it starts "
            "without unsaved changes and without undo history. Shown in a window when GIMP has a UI."
        ),
        annotations=MUTATING,
        changes_images=True,
    )
    async def gimp_create_image(
        width: Annotated[int, Field(ge=1, le=MAX_DIMENSION, description="Pixels.")],
        height: Annotated[int, Field(ge=1, le=MAX_DIMENSION, description="Pixels.")],
        base_type: Literal["rgb", "gray"] = "rgb",
        fill: Annotated[str, Field(description=COLOR_DESCRIPTION)] = "white",
        layer_name: str = "Background",
        resolution: Annotated[float | None, Field(gt=0, le=65536, description="Pixels per inch.")] = None,
    ) -> ImageRef:
        color = parse_color(fill)
        if color.a not in (0.0, 1.0):
            raise GimpMcpError("INVALID_ARGUMENT", "fill must be fully opaque or 'transparent'")
        codec = await kit.codec()
        data = await kit.call(
            "image.create",
            {
                "width": width,
                "height": height,
                "base_type": base_type,
                "fill": color.to_wire(),
                "layer_name": layer_name,
                "resolution": resolution,
            },
            codec=codec,
            mutating=True,
        )
        return image_ref(codec, data)

    @kit.tool(
        toolset="files",
        name="gimp_open_image",
        title="Open image",
        description=(
            "Open a local file (XCF or any format GIMP can load: PNG, JPEG, WebP, TIFF...) as a new image. "
            "The path must be absolute (~ allowed). PDF pages, SVG size, RAW: gimp_open_with_options (toolset "
            "formats)."
        ),
        annotations=MUTATING,
        changes_images=True,
    )
    async def gimp_open_image(
        path: Annotated[str, Field(description="Absolute path of the file to open.")],
    ) -> ImageRef:
        source = check_input_file(path)
        codec = await kit.codec()
        data = await kit.call("image.open", {"path": str(source)}, codec=codec, mutating=True)
        return image_ref(codec, data)

    @kit.tool(
        toolset="files",
        name="gimp_save_image",
        title="Save project (XCF)",
        description=(
            "Save the image as a GIMP project (.xcf), keeping layers, groups, masks and text. Without path, "
            "saves to the image's current XCF file (a normal 'Save'). With a path, an existing file is only "
            "replaced when overwrite=true. Marks the image as having no unsaved changes."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_save_image(
        image: ImageId,
        path: Annotated[str | None, Field(description="Absolute .xcf path; default: current XCF file.")] = None,
        overwrite: bool = False,
    ) -> SaveResult:
        target: str | None = None
        if path is not None:
            resolved = check_output_file(path, overwrite=overwrite)
            if resolved.suffix.lower() != ".xcf":
                raise GimpMcpError(
                    "UNSUPPORTED_FORMAT",
                    f"projects are saved as .xcf, not {resolved.suffix or 'without extension'}",
                    hint="Use gimp_export_image for PNG/JPEG.",
                )
            target = str(resolved)
        codec = await kit.codec()
        data = await kit.call(
            "image.save", {"image": codec.parse_image(image), "path": target}, codec=codec, mutating=True
        )
        return SaveResult(**{**data, "image": image})

    @kit.tool(
        toolset="files",
        name="gimp_export_image",
        title="Export PNG/JPEG",
        description=(
            "Export the visible composite of the image to PNG or JPEG (format from the extension). The image "
            "itself is not modified. Existing files are only replaced when overwrite=true. Defaults: PNG "
            "compression 9, not interlaced; JPEG quality 90, baseline, optimized, transparency flattened on white. "
            "WebP, AVIF, TIFF, PDF…: gimp_export_as (toolset formats)."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_export_image(
        image: ImageId,
        path: Annotated[str, Field(description="Absolute path ending in .png, .jpg or .jpeg.")],
        overwrite: bool = False,
        format: Literal["png", "jpeg"] | None = None,
        png_options: PngOptions | None = None,
        jpeg_options: JpegOptions | None = None,
    ) -> ExportResult:
        target = check_output_file(path, overwrite=overwrite)
        kind = export_format(target, format)
        if kind == "png":
            options: dict[str, object] = (png_options or PngOptions()).model_dump()
        else:
            jpeg = jpeg_options or JpegOptions()
            options = jpeg.model_dump()
            options["background"] = parse_color(jpeg.background).to_wire()
        codec = await kit.codec()
        data = await kit.call(
            "image.export",
            {"image": codec.parse_image(image), "path": str(target), "format": kind, "options": options},
            codec=codec,
            mutating=True,
        )
        if kind == "jpeg":
            options["background"] = (jpeg_options or JpegOptions()).background
        return ExportResult(image=image, format=kind, options=options, **data)

    @kit.tool(
        toolset="files",
        name="gimp_close_image",
        title="Close image",
        description=(
            "Close an image. Refused with UNSAVED_CHANGES when it has unsaved changes, unless "
            "discard_changes=true. Its id (and its items' ids) become invalid."
        ),
        annotations=DESTRUCTIVE,
        changes_images=True,
    )
    async def gimp_close_image(image: ImageId, discard_changes: bool = False) -> CloseResult:
        codec = await kit.codec()
        await kit.call(
            "image.close",
            {"image": codec.parse_image(image), "discard_changes": discard_changes},
            codec=codec,
            mutating=True,
        )
        return CloseResult(image=image, closed=True)

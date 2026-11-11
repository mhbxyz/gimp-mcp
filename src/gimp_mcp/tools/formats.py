"""More file formats (#58): every GIMP export/load procedure, options introspected from GIMP.

Path rules are the same as gimp_export_image / gimp_open_image (absolute paths, overwrite flag).
Exports write no metadata unless asked (``metadata``).
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ..errors import GimpMcpError
from ..paths import check_input_file, check_output_file
from ..toolkit import MUTATING, READ_ONLY, Toolkit
from .inspect import ImageId

Value = bool | int | float | str | list[int]
Options = Annotated[
    dict[str, Value],
    Field(description="Format options by name (gimp_describe_file_format); colors as '#rrggbb'."),
]
Metadata = Annotated[
    list[Literal["exif", "xmp", "iptc", "comment", "thumbnail"]],
    Field(description="Metadata to write when the format supports it (none by default)."),
]
Procedure = Annotated[str | None, Field(description="Force a procedure, e.g. 'file-heif-av1-export'.")]


class FileFormat(BaseModel):
    procedure: str
    name: str
    extensions: list[str]
    mime_types: str = ""


class FormatList(BaseModel):
    mode: str
    formats: list[FileFormat]


class FormatOption(BaseModel):
    name: str
    kind: str = Field(description="number, integer, boolean, choice, enum, color, string, integer-list, unsupported.")
    description: str | None = None
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None
    default: Value | None = None
    type: str | None = None


class FormatDetails(BaseModel):
    procedure: str
    name: str
    extensions: list[str]
    options: list[FormatOption]


class Exported(BaseModel):
    path: str
    procedure: str
    bytes: int
    lossless: bool | None = Field(description="True lossless, False lossy, null when it depends on the content.")
    layers: str | None = Field(description="flattened, kept, frames, pages or sizes; null when unknown.")
    options: dict[str, Any] = Field(description="Effective options (GIMP's defaults + the given ones).")
    item: str | None = None


class LayerFiles(BaseModel):
    files: list[Exported]


class Opened(BaseModel):
    id: str
    name: str
    width: int
    height: int
    layer_count: int
    procedure: str


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="formats",
        name="gimp_list_file_formats",
        title="List file formats",
        description="Every format GIMP can export (mode=export) or open (mode=import): procedure, name, extensions.",
        annotations=READ_ONLY,
    )
    async def gimp_list_file_formats(mode: Literal["export", "import"] = "export") -> FormatList:
        data = await kit.call("formats.list", {"mode": "load" if mode == "import" else "export"})
        return FormatList(mode=mode, formats=[FileFormat(**f) for f in data["formats"]])

    @kit.tool(
        toolset="formats",
        name="gimp_describe_file_format",
        title="Describe a file format",
        description="Options of a format's export (or import) procedure from GIMP: kind, range, choices, default.",
        annotations=READ_ONLY,
    )
    async def gimp_describe_file_format(
        extension: Annotated[str | None, Field(description="e.g. 'webp', 'avif', 'pdf'.")] = None,
        procedure: Procedure = None,
        mode: Literal["export", "import"] = "export",
    ) -> FormatDetails:
        if extension is None and procedure is None:
            raise GimpMcpError("INVALID_ARGUMENT", "give an extension or a procedure")
        data = await kit.call(
            "formats.describe",
            {"mode": "load" if mode == "import" else "export", "procedure": procedure,
             "path": f"x.{extension.lstrip('.')}" if extension else ""},
        )  # fmt: skip
        return FormatDetails(**data)

    @kit.tool(
        toolset="formats",
        name="gimp_export_as",
        title="Export to any format",
        description=(
            "Export an image with the format chosen from the extension (WebP, AVIF/HEIF, TIFF, BMP, GIF, ICO, PDF, "
            "PSD, JPEG XL… see gimp_list_file_formats) and validated options. Reports whether the result is "
            "lossless and what happened to layers (flattened, kept, frames, pages, sizes). layers='flatten' "
            "writes the visible composite as one page or frame (TIFF, PDF, PSD…), as seen. The image is unchanged."
        ),
        annotations=MUTATING,
    )
    async def gimp_export_as(
        image: ImageId,
        path: str,
        options: Options = {},  # noqa: B006
        metadata: Metadata = [],  # noqa: B006
        procedure: Procedure = None,
        overwrite: bool = False,
        layers: Annotated[
            Literal["keep", "flatten"],
            Field(
                description="keep: what the format does with layers (TIFF: one page per layer). flatten: export "
                "the visible composite as a single layer, without changing the image."
            ),
        ] = "keep",
        color_profile: Annotated[
            bool | None,
            Field(
                description="Embed the color profile GIMP uses (the built-in sRGB when none is assigned); default: "
                "only when the image has one assigned."
            ),
        ] = None,
    ) -> Exported:
        target = str(check_output_file(path, overwrite=overwrite))
        codec = await kit.codec()
        data = await kit.call(
            "image.export_as",
            {"image": codec.parse_image(image), "path": target, "options": options, "metadata": metadata,
             "procedure": procedure, "layers": layers, "color_profile": color_profile},
            codec=codec,
            mutating=True,
            # older plug-ins would ignore `layers` and `color_profile`
            revision=2 if layers == "flatten" or color_profile is not None else 1,
        )  # fmt: skip
        return Exported(**data)

    @kit.tool(
        toolset="formats",
        name="gimp_open_with_options",
        title="Open with options",
        description=(
            "Open a file with its load procedure's options: PDF (pages: page numbers from 1, loaded in that order, "
            "the last on top; width/height or resolution), SVG (width, height), and any format GIMP reads (see "
            "gimp_describe_file_format mode=import). RAW files open in darktable's or RawTherapee's window "
            "(installed with GIMP, GIMP with its interface); the call returns once that window is closed."
        ),
        annotations=MUTATING,
        changes_images=True,
    )
    async def gimp_open_with_options(path: str, options: Options = {}, procedure: Procedure = None) -> Opened:  # noqa: B006
        source = str(check_input_file(path))
        codec = await kit.codec()
        data = await kit.call(
            "image.open_with", {"path": source, "options": options, "procedure": procedure}, codec=codec, mutating=True
        )
        return Opened(**{**data, "id": codec.image(data["id"])})

    @kit.tool(
        toolset="formats",
        name="gimp_export_layers",
        title="Export layers to separate files",
        description=(
            "Export each top-level layer (or the given layers/groups) to its own file in directory, named from "
            "template ({index}, {name}); crop=true trims each file to the layer's bounds. The image is unchanged."
        ),
        annotations=MUTATING,
    )
    async def gimp_export_layers(
        image: ImageId,
        directory: str,
        extension: Annotated[str, Field(pattern=r"^[A-Za-z0-9.]{1,10}$")] = "png",
        items: Annotated[list[str] | None, Field(max_length=500)] = None,
        template: Annotated[str, Field(max_length=200)] = "{index:02d}-{name}",
        crop: bool = True,
        options: Options = {},  # noqa: B006
        overwrite: bool = False,
    ) -> LayerFiles:
        folder = os.path.abspath(os.path.expanduser(directory))
        if not os.path.isabs(os.path.expanduser(directory)):
            raise GimpMcpError("INVALID_ARGUMENT", "directory must be an absolute path")
        if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
            raise GimpMcpError("WRITE_FAILED", f"{folder} is not a writable directory", details={"path": folder})
        try:
            template.format(index=0, name="x")
        except (KeyError, IndexError, ValueError) as error:
            raise GimpMcpError("INVALID_ARGUMENT", f"template: {error}") from None
        codec = await kit.codec()
        data = await kit.call(
            "image.export_layers",
            {"image": codec.parse_image(image), "directory": folder, "extension": extension.lstrip("."),
             "items": [codec.parse_item(i) for i in items] if items else None, "template": template, "crop": crop,
             "options": options, "overwrite": overwrite},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return LayerFiles(files=[Exported(**{**f, "item": codec.item(f["item"])}) for f in data["files"]])

    @kit.tool(
        toolset="formats",
        name="gimp_export_region",
        title="Export a region (slice)",
        description="Export a rectangle of the image (inside the canvas) to a file in any format. Image unchanged.",
        annotations=MUTATING,
    )
    async def gimp_export_region(
        image: ImageId,
        path: str,
        x: Annotated[int, Field(ge=0)],
        y: Annotated[int, Field(ge=0)],
        width: Annotated[int, Field(ge=1)],
        height: Annotated[int, Field(ge=1)],
        options: Options = {},  # noqa: B006
        overwrite: bool = False,
    ) -> Exported:
        target = str(check_output_file(path, overwrite=overwrite))
        codec = await kit.codec()
        data = await kit.call(
            "image.export_region",
            {"image": codec.parse_image(image), "path": target, "options": options,
             "region": {"x": x, "y": y, "width": width, "height": height}},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return Exported(**data)

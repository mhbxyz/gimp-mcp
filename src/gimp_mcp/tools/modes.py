"""Image mode, precision and color profiles (#49)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..errors import GimpMcpError
from ..paths import check_input_file
from ..toolkit import DESTRUCTIVE, MUTATING, READ_ONLY, Toolkit
from .inspect import ImageId

Precision = Literal[
    "u8-linear", "u8-non-linear", "u8-perceptual",
    "u16-linear", "u16-non-linear", "u16-perceptual",
    "u32-linear", "u32-non-linear", "u32-perceptual",
    "half-linear", "half-non-linear", "half-perceptual",
    "float-linear", "float-non-linear", "float-perceptual",
    "double-linear", "double-non-linear", "double-perceptual",
]  # fmt: skip


class ModeResult(BaseModel):
    image: str
    base_type: str = Field(description="rgb, gray or indexed.")
    precision: str = Field(description="e.g. u8-non-linear, u16-linear, float-linear.")
    palette_colors: int | None = Field(description="Colors in the palette of an indexed image.")
    changed: bool = Field(description="False when the image already had this mode/precision.")
    dirty: bool


class Profile(BaseModel):
    label: str
    description: str
    model: str = Field(description="rgb or gray.")
    linear: bool = Field(description="True for a linear tone response (no gamma).")
    icc_bytes: int


class ProfileResult(BaseModel):
    image: str
    assigned: Profile | None = Field(description="Profile stored in the image; null = GIMP's built-in default.")
    effective: Profile = Field(description="Profile GIMP uses to interpret the pixels.")


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="modes",
        name="gimp_convert_mode",
        title="Convert image mode",
        description=(
            "Convert the image to rgb, gray or indexed. Indexed: palette 'generate' (optimal, up to colors), "
            "'web' (216 web-safe), 'mono' (black and white) or 'custom' (a GIMP palette by name); dither none, "
            "floyd-steinberg, floyd-steinberg-low-bleed or positioned. Indexed needs an 8-bit (u8-non-linear) "
            "image. Lossy for gray and indexed. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_convert_mode(
        image: ImageId,
        mode: Literal["rgb", "gray", "indexed"],
        palette: Literal["generate", "web", "mono", "custom"] = "generate",
        palette_name: Annotated[str | None, Field(description="GIMP palette name, for palette='custom'.")] = None,
        colors: Annotated[int, Field(ge=2, le=256, description="Maximum colors, for palette='generate'.")] = 256,
        dither: Literal["none", "floyd-steinberg", "floyd-steinberg-low-bleed", "positioned"] = "none",
        dither_alpha: bool = False,
        remove_unused: bool = True,
    ) -> ModeResult:
        if palette == "custom" and not palette_name:
            raise GimpMcpError("INVALID_ARGUMENT", "palette='custom' needs palette_name")
        codec = await kit.codec()
        data = await kit.call(
            "image.convert_mode",
            {"image": codec.parse_image(image), "mode": mode, "palette": palette, "palette_name": palette_name,
             "colors": colors, "dither": dither, "dither_alpha": dither_alpha, "remove_unused": remove_unused},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return ModeResult(**{**data, "image": image})

    @kit.tool(
        toolset="modes",
        name="gimp_convert_precision",
        title="Convert precision",
        description=(
            "Change how pixels are stored: 8/16/32-bit integer, half/float/double floating point, with a linear, "
            "non-linear (sRGB curve) or perceptual tone response. Higher precisions keep more detail for heavy "
            "editing; converting down rounds values. Not for indexed images. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_convert_precision(image: ImageId, precision: Precision) -> ModeResult:
        codec = await kit.codec()
        data = await kit.call(
            "image.convert_precision",
            {"image": codec.parse_image(image), "precision": precision},
            codec=codec,
            mutating=True,
        )
        return ModeResult(**{**data, "image": image})

    @kit.tool(
        toolset="modes",
        name="gimp_get_color_profile",
        title="Get color profile",
        description="The color profile assigned to the image (null if none) and the profile GIMP actually uses.",
        annotations=READ_ONLY,
    )
    async def gimp_get_color_profile(image: ImageId) -> ProfileResult:
        codec = await kit.codec()
        data = await kit.call("profile.get", {"image": codec.parse_image(image)}, codec=codec)
        return ProfileResult(**{**data, "image": image})

    @kit.tool(
        toolset="modes",
        name="gimp_set_color_profile",
        title="Set color profile",
        description=(
            "assign: tag the pixels with a profile without changing them (colors look different); convert: "
            "transform the pixels so colors look the same in the new profile (rendering intent, black point "
            "compensation); remove: back to GIMP's built-in default. Profiles: srgb, srgb-linear, gray, "
            "gray-linear (built in) or file (an ICC file at path). Gray profiles fit gray images only. "
            "One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_color_profile(
        image: ImageId,
        action: Literal["assign", "convert", "remove"],
        profile: Literal["srgb", "srgb-linear", "gray", "gray-linear", "file"] | None = None,
        path: Annotated[str | None, Field(description="ICC file, for profile='file'.")] = None,
        intent: Literal["perceptual", "relative-colorimetric", "saturation", "absolute-colorimetric"] = "perceptual",
        black_point_compensation: bool = True,
    ) -> ProfileResult:
        if action != "remove" and profile is None:
            raise GimpMcpError("INVALID_ARGUMENT", f"action={action!r} needs a profile")
        if profile == "file":
            if not path:
                raise GimpMcpError("INVALID_ARGUMENT", "profile='file' needs a path")
            path = str(check_input_file(path))
        codec = await kit.codec()
        data = await kit.call(
            "profile.set",
            {"image": codec.parse_image(image), "action": action, "profile": profile, "path": path,
             "intent": intent, "black_point_compensation": black_point_compensation},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return ProfileResult(**{**data, "image": image})

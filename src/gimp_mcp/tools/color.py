"""Color adjustment tools (#48): levels, curves, color balance, colorize, desaturate, invert, threshold,
posterize, exposure, shadows-highlights and automatic corrections.

Values use the ranges photographers know (0-255 levels, -100..100 sliders, degrees); the bridge maps
them to GIMP's (docs/tools.md#color-adjustments-toolset-color). Editable mode adds a GIMP filter
(pixels untouched); destructive mode changes the pixels. Both respect the selection.
"""

from __future__ import annotations

import itertools
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ..errors import GimpMcpError
from ..toolkit import DESTRUCTIVE, MUTATING, Toolkit
from .inspect import ItemId

Channel = Annotated[
    Literal["value", "red", "green", "blue", "alpha"],
    Field(description="value = all color channels together."),
]
Level = Annotated[int, Field(ge=0, le=255)]
Slider = Annotated[float, Field(ge=-100, le=100)]
Editable = Annotated[
    bool, Field(description="false (default): editable GIMP filter, pixels untouched. true: change the pixels.")
]


class AdjustmentResult(BaseModel):
    item: str
    adjustment: str
    operation: str | None = Field(description="GIMP/GEGL operation used, null for GIMP's built-in destructive tools.")
    destructive: bool = Field(description="True when the layer's pixels were changed.")
    filter: str | None = Field(description="Id of the editable filter (editable mode only).")
    restricted_to_selection: bool


def register(kit: Toolkit) -> None:
    async def adjust(item: str, adjustment: str, destructive: bool, settings: dict[str, Any]) -> AdjustmentResult:
        codec = await kit.codec()
        data = await kit.call(
            "color.adjust",
            {"item": codec.parse_item(item), "adjustment": adjustment, "destructive": destructive,
             "settings": settings},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return AdjustmentResult(
            item=item,
            adjustment=data["adjustment"],
            operation=data["operation"],
            destructive=data["destructive"],
            filter=None if data["filter"] is None else codec.filter(data["filter"]),
            restricted_to_selection=data["restricted_to_selection"],
        )

    @kit.tool(
        toolset="color",
        name="gimp_levels",
        title="Levels",
        description=(
            "Remap tones like GIMP's Levels: input_low..input_high (0-255) becomes output_low..output_high, with "
            "gamma (0.1-10, >1 brightens midtones). Per channel. Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_levels(
        item: ItemId,
        channel: Channel = "value",
        input_low: Level = 0,
        input_high: Level = 255,
        gamma: Annotated[float, Field(ge=0.1, le=10)] = 1.0,
        output_low: Level = 0,
        output_high: Level = 255,
        destructive: Editable = False,
    ) -> AdjustmentResult:
        if input_low >= input_high:
            raise GimpMcpError("INVALID_ARGUMENT", "input_low must be lower than input_high")
        settings = {"channel": channel, "input_low": input_low, "input_high": input_high, "gamma": gamma,
                    "output_low": output_low, "output_high": output_high}  # fmt: skip
        return await adjust(item, "levels", destructive, settings)

    @kit.tool(
        toolset="color",
        name="gimp_curves",
        title="Curves",
        description=(
            "Apply a tone curve to a channel, destructively (GIMP 3.2 cannot set curves on an editable filter "
            "from a plug-in): either control points [[x, y], ...] (0-255, x increasing, smooth spline through "
            "them) or explicit output samples (0-255) for evenly spaced inputs. One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_curves(
        item: ItemId,
        channel: Channel = "value",
        points: Annotated[
            list[Annotated[list[Annotated[int, Field(ge=0, le=255)]], Field(min_length=2, max_length=2)]] | None,
            Field(min_length=2, max_length=64),
        ] = None,
        samples: Annotated[
            list[Annotated[int, Field(ge=0, le=255)]] | None, Field(min_length=2, max_length=1024)
        ] = None,
    ) -> AdjustmentResult:
        if (points is None) == (samples is None):
            raise GimpMcpError("INVALID_ARGUMENT", "give either points or samples")
        if points is not None and any(b[0] <= a[0] for a, b in itertools.pairwise(points)):
            raise GimpMcpError("INVALID_ARGUMENT", "curve points must have strictly increasing x")
        codec = await kit.codec()
        data = await kit.call(
            "color.curves",
            {"item": codec.parse_item(item), "channel": channel, "points": points, "samples": samples},
            codec=codec,
            mutating=True,
        )
        return AdjustmentResult(item=item, **{**data, "filter": None})

    @kit.tool(
        toolset="color",
        name="gimp_color_balance",
        title="Color balance",
        description=(
            "Shift colors in the shadows, midtones or highlights: cyan_red, magenta_green, yellow_blue from -100 "
            "to 100 (positive = towards red/green/blue). Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_color_balance(
        item: ItemId,
        range: Literal["shadows", "midtones", "highlights"] = "midtones",
        cyan_red: Slider = 0,
        magenta_green: Slider = 0,
        yellow_blue: Slider = 0,
        preserve_luminosity: bool = True,
        destructive: Editable = False,
    ) -> AdjustmentResult:
        settings = {"range": range, "cyan_red": cyan_red, "magenta_green": magenta_green,
                    "yellow_blue": yellow_blue, "preserve_luminosity": preserve_luminosity}  # fmt: skip
        return await adjust(item, "color-balance", destructive, settings)

    @kit.tool(
        toolset="color",
        name="gimp_colorize",
        title="Colorize",
        description=(
            "Render the layer in shades of one hue: hue in degrees (0-360), saturation 0-100, lightness -100..100. "
            "Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_colorize(
        item: ItemId,
        hue: Annotated[float, Field(ge=0, le=360)] = 180,
        saturation: Annotated[float, Field(ge=0, le=100)] = 50,
        lightness: Slider = 0,
        destructive: Editable = False,
    ) -> AdjustmentResult:
        return await adjust(
            item, "colorize", destructive, {"hue": hue, "saturation": saturation, "lightness": lightness}
        )

    @kit.tool(
        toolset="color",
        name="gimp_desaturate",
        title="Desaturate",
        description=(
            "Turn colors into grays: luminance (perceived brightness, linear light), luma, lightness (HSL), "
            "average or value (HSV max). Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_desaturate(
        item: ItemId,
        mode: Literal["luminance", "luma", "lightness", "average", "value"] = "luminance",
        destructive: Editable = False,
    ) -> AdjustmentResult:
        return await adjust(item, "desaturate", destructive, {"mode": mode})

    @kit.tool(
        toolset="color",
        name="gimp_invert",
        title="Invert colors",
        description=(
            "Invert the colors: perceptually (255 - value on sRGB values, like GIMP's Invert) or in linear light "
            "(linear=true). Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_invert(item: ItemId, linear: bool = False, destructive: Editable = False) -> AdjustmentResult:
        return await adjust(item, "invert", destructive, {"linear": linear})

    @kit.tool(
        toolset="color",
        name="gimp_threshold",
        title="Threshold",
        description=(
            "Turn the layer black and white: pixels whose channel value is within low..high (0-255) become white, "
            "the others black. Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_threshold(
        item: ItemId,
        channel: Channel = "value",
        low: Level = 128,
        high: Level = 255,
        destructive: Editable = False,
    ) -> AdjustmentResult:
        if low > high:
            raise GimpMcpError("INVALID_ARGUMENT", "low must not exceed high")
        return await adjust(item, "threshold", destructive, {"channel": channel, "low": low, "high": high})

    @kit.tool(
        toolset="color",
        name="gimp_posterize",
        title="Posterize",
        description="Reduce each channel to a number of levels (2-256). Editable or destructive. One undo step.",
        annotations=MUTATING,
    )
    async def gimp_posterize(
        item: ItemId, levels: Annotated[int, Field(ge=2, le=256)] = 3, destructive: Editable = False
    ) -> AdjustmentResult:
        return await adjust(item, "posterize", destructive, {"levels": levels})

    @kit.tool(
        toolset="color",
        name="gimp_exposure",
        title="Exposure",
        description=(
            "Photographic exposure in linear light: exposure in stops (EV, -10..10; +1 doubles the light) and "
            "black_level (-0.1..0.1). Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_exposure(
        item: ItemId,
        exposure: Annotated[float, Field(ge=-10, le=10)] = 0.0,
        black_level: Annotated[float, Field(ge=-0.1, le=0.1)] = 0.0,
        destructive: Editable = False,
    ) -> AdjustmentResult:
        return await adjust(item, "exposure", destructive, {"exposure": exposure, "black_level": black_level})

    @kit.tool(
        toolset="color",
        name="gimp_shadows_highlights",
        title="Shadows-highlights",
        description=(
            "Lift shadows and recover highlights (GEGL shadows-highlights): shadows and highlights -100..100, "
            "whitepoint -10..10, radius 0.1-1500 px, compress 0-100, color corrections 0-100. Unset values keep "
            "GIMP's defaults. Editable or destructive. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_shadows_highlights(
        item: ItemId,
        shadows: Slider | None = None,
        highlights: Slider | None = None,
        whitepoint: Annotated[float | None, Field(ge=-10, le=10)] = None,
        radius: Annotated[float | None, Field(ge=0.1, le=1500)] = None,
        compress: Annotated[float | None, Field(ge=0, le=100)] = None,
        shadows_color_correction: Annotated[float | None, Field(ge=0, le=100)] = None,
        highlights_color_correction: Annotated[float | None, Field(ge=0, le=100)] = None,
        destructive: Editable = False,
    ) -> AdjustmentResult:
        values = {"shadows": shadows, "highlights": highlights, "whitepoint": whitepoint, "radius": radius,
                  "compress": compress, "shadows_color_correction": shadows_color_correction,
                  "highlights_color_correction": highlights_color_correction}  # fmt: skip
        settings = {key: value for key, value in values.items() if value is not None}
        return await adjust(item, "shadows-highlights", destructive, settings)

    @kit.tool(
        toolset="color",
        name="gimp_auto_adjust",
        title="Automatic correction",
        description=(
            "Automatic corrections: 'white-balance' (GIMP's Auto White Balance: stretches each channel, "
            "destructive only), 'equalize' (flattens the histogram, destructive only), 'stretch-contrast' "
            "(GEGL Stretch Contrast; keep_colors keeps hues; editable or destructive). One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_auto_adjust(
        item: ItemId,
        method: Literal["white-balance", "equalize", "stretch-contrast"],
        keep_colors: bool = False,
        destructive: Annotated[
            bool | None,
            Field(description="Default: true for white-balance and equalize (only mode), false for stretch-contrast."),
        ] = None,
    ) -> AdjustmentResult:
        mode = destructive if destructive is not None else method != "stretch-contrast"
        settings = {"keep_colors": keep_colors} if method == "stretch-contrast" else {}
        return await adjust(item, method, mode, settings)

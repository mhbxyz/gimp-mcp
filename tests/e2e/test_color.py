"""Color adjustments (#48) on a real GIMP. Expected values are computed by hand; pixels read with PIL."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


def srgb_to_linear(v: float) -> float:
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def linear_to_srgb(v: float) -> float:
    return 255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)


class Canvas:
    def __init__(self, client, tmp_path: Path):
        self.client = client
        self.tmp_path = tmp_path
        self.images: list[str] = []

    async def make(self, fill: str, size: int = 16, right: str | None = None) -> str:
        """A layer filled with `fill`; with `right`, the right half has that color."""
        image = (await call(self.client, "gimp_create_image", width=size, height=size, fill=fill))["id"]
        self.images.append(image)
        layer = (await call(self.client, "gimp_inspect_image", image=image))["layers"][0]["id"]
        if right:
            await call(
                self.client, "gimp_select_rectangle", image=image, x=size // 2, y=0, width=size // 2, height=size
            )
            await call(self.client, "gimp_fill", item=layer, color=right)
            await call(self.client, "gimp_modify_selection", image=image, action="none")
        self.layers = getattr(self, "layers", {})
        self.layers[layer] = image
        return layer

    async def pixel(self, layer: str, x: int = 2, y: int = 2) -> tuple[int, int, int]:
        image = self.layers[layer]
        path = self.tmp_path / f"{image.split(':')[1].split('@')[0]}.png"
        await call(self.client, "gimp_export_image", image=image, path=str(path), overwrite=True)
        with Image.open(path) as img:
            r, g, b, *_ = img.convert("RGB").getpixel((x, y))  # type: ignore[misc]
        return r, g, b

    async def close(self) -> None:
        for image in self.images:
            await call(self.client, "gimp_close_image", image=image, discard_changes=True)


def near(actual: tuple[int, ...], expected: tuple[float, ...], tolerance: float = 1.5) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected, strict=True))


async def adjust(client, tool: str, layer: str, **arguments: Any) -> dict[str, Any]:
    return await call(client, tool, item=layer, **arguments)


async def test_levels_curves_and_tone_tools(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        canvas = Canvas(client, tmp_path)
        # levels: input 0..128 -> 0..255 on sRGB values (GIMP's default, perceptual)
        layer = await canvas.make("#404040")
        result = await adjust(client, "gimp_levels", layer, input_high=128, destructive=True)
        assert result["destructive"] is True and result["filter"] is None
        assert near(await canvas.pixel(layer), (127.5,) * 3)

        # editable levels: same pixels, the layer keeps a gimp:levels filter
        editable = await canvas.make("#404040")
        result = await adjust(client, "gimp_levels", editable, input_high=128)
        assert result["destructive"] is False and result["filter"]
        filters = (await call(client, "gimp_list_filters", item=editable))["filters"]
        assert [f["operation"] for f in filters] == ["gimp:levels"]
        assert near(await canvas.pixel(editable), (127.5,) * 3)

        # gamma 2 brightens midtones: out = 255 * (in/255) ** (1/gamma)
        layer = await canvas.make("#404040")
        await adjust(client, "gimp_levels", layer, gamma=2.0, destructive=True)
        assert near(await canvas.pixel(layer), (255 * (64 / 255) ** 0.5,) * 3)

        # curves through (128, 64): a spline through 3 points maps 128 to 64
        layer = await canvas.make("#808080")
        result = await adjust(client, "gimp_curves", layer, points=[[0, 0], [128, 64], [255, 255]])
        assert result["destructive"] is True and result["operation"] is None
        assert near(await canvas.pixel(layer), (64,) * 3, 2)
        # explicit samples [255, 0]: a linear inversion
        layer = await canvas.make("#404040")
        await adjust(client, "gimp_curves", layer, samples=[255, 0])
        assert near(await canvas.pixel(layer), (191,) * 3)

        # invert (perceptual): 255 - v
        layer = await canvas.make("#404040")
        await adjust(client, "gimp_invert", layer, destructive=True)
        assert near(await canvas.pixel(layer), (191,) * 3)

        # threshold 128..255: dark half black, light half white
        layer = await canvas.make("#646464", right="#c8c8c8")
        await adjust(client, "gimp_threshold", layer, low=128, destructive=True)
        assert await canvas.pixel(layer, 2, 2) == (0, 0, 0) and await canvas.pixel(layer, 12, 2) == (255, 255, 255)

        # posterize to 2 levels: 100 -> 0, 200 -> 255
        layer = await canvas.make("#646464", right="#c8c8c8")
        await adjust(client, "gimp_posterize", layer, levels=2, destructive=True)
        assert await canvas.pixel(layer, 2, 2) == (0, 0, 0) and await canvas.pixel(layer, 12, 2) == (255, 255, 255)

        # exposure +1 EV doubles the light in linear space
        layer = await canvas.make("#404040")
        await adjust(client, "gimp_exposure", layer, exposure=1.0, destructive=True)
        assert near(await canvas.pixel(layer), (linear_to_srgb(2 * srgb_to_linear(64)),) * 3, 2)

        # shadows-highlights lifts a dark gray
        layer = await canvas.make("#282828")
        await adjust(client, "gimp_shadows_highlights", layer, shadows=80, destructive=True)
        assert (await canvas.pixel(layer))[0] > 40 + 10
        await canvas.close()


async def test_color_tools(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        canvas = Canvas(client, tmp_path)
        # color balance towards red in the midtones
        layer = await canvas.make("#808080")
        await adjust(client, "gimp_color_balance", layer, cyan_red=100, preserve_luminosity=False, destructive=True)
        r, g, b = await canvas.pixel(layer)
        assert r > g + 20 and r > b + 20

        # colorize in pure red hue: red dominates, gray had none
        layer = await canvas.make("#808080")
        await adjust(client, "gimp_colorize", layer, hue=0, saturation=100, destructive=True)
        r, g, b = await canvas.pixel(layer)
        assert r > g + 50 and g == b

        # desaturate pure red: luma (Rec. 709 on sRGB values) vs luminance (linear light)
        layer = await canvas.make("#ff0000")
        await adjust(client, "gimp_desaturate", layer, mode="luma", destructive=True)
        luma = await canvas.pixel(layer)
        layer = await canvas.make("#ff0000")
        await adjust(client, "gimp_desaturate", layer, mode="luminance", destructive=True)
        luminance = await canvas.pixel(layer)
        assert luma[0] == luma[1] == luma[2] and luminance[0] == luminance[1] == luminance[2]
        assert near(luminance, (linear_to_srgb(0.2126),) * 3, 3)
        assert luma[0] < luminance[0]
        await canvas.close()


async def test_automatic_corrections(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        canvas = Canvas(client, tmp_path)
        # white balance stretches each channel to the full range: 50 -> 0, 200 -> 255
        layer = await canvas.make("#323232", right="#c8c8c8")
        result = await adjust(client, "gimp_auto_adjust", layer, method="white-balance")
        assert result["destructive"] is True and result["operation"] is None
        # GIMP ignores a tiny share of extreme pixels when stretching: the dark half lands near 0, not at 0
        assert near(await canvas.pixel(layer, 2, 2), (0, 0, 0), 5) and await canvas.pixel(layer, 12, 2) == (255,) * 3

        layer = await canvas.make("#323232", right="#c8c8c8")
        await adjust(client, "gimp_auto_adjust", layer, method="equalize")
        dark, light = await canvas.pixel(layer, 2, 2), await canvas.pixel(layer, 12, 2)
        # cumulative histogram: half of the pixels are dark -> they map to the middle
        assert near(dark, (128, 128, 128), 2) and light == (255, 255, 255)

        layer = await canvas.make("#323232", right="#c8c8c8")
        stretched = await adjust(client, "gimp_auto_adjust", layer, method="stretch-contrast")
        assert stretched["destructive"] is False and stretched["filter"]
        assert await canvas.pixel(layer, 2, 2) == (0, 0, 0) and await canvas.pixel(layer, 12, 2) == (255, 255, 255)
        await canvas.close()


async def test_selection_and_invalid_requests(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        canvas = Canvas(client, tmp_path)
        layer = await canvas.make("#404040")
        image = canvas.layers[layer]
        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=8, height=16)
        result = await adjust(client, "gimp_invert", layer)
        assert result["restricted_to_selection"] is True
        assert near(await canvas.pixel(layer, 2, 2), (191,) * 3) and await canvas.pixel(layer, 12, 2) == (64, 64, 64)
        await call(client, "gimp_modify_selection", image=image, action="none")

        untouched = await canvas.make("#404040")
        before = (await call(client, "gimp_list_filters", item=untouched))["filters"]
        for tool, arguments, code in [
            ("gimp_levels", {"input_low": 200, "input_high": 100}, "INVALID_ARGUMENT"),
            ("gimp_threshold", {"low": 200, "high": 100}, "INVALID_ARGUMENT"),
            ("gimp_curves", {"points": [[0, 0], [10, 10], [5, 20]]}, "INVALID_ARGUMENT"),
            ("gimp_curves", {}, "INVALID_ARGUMENT"),
            ("gimp_auto_adjust", {"method": "equalize", "destructive": False}, "UNSUPPORTED"),
        ]:
            assert (await error(client, tool, item=untouched, **arguments))["code"] == code, (tool, arguments)
        group = (await call(client, "gimp_create_group", image=canvas.layers[untouched], name="G"))["id"]
        assert (await error(client, "gimp_curves", item=group, samples=[0, 255]))["code"] == "WRONG_KIND"
        refused = await client.call_tool("gimp_levels", {"item": untouched, "gamma": 20})
        assert refused.is_error
        assert (await call(client, "gimp_list_filters", item=untouched))["filters"] == before
        assert await canvas.pixel(untouched) == (64, 64, 64)
        await canvas.close()

"""Image modes, precision and color profiles (#49) on a real GIMP; files checked with PIL."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error

RED_LUMINANCE = 130  # sRGB red -> gray: relative luminance (D50), sRGB-encoded


async def two_tone(client, left: str, right: str, size: int = 16) -> tuple[str, str]:
    image = (await call(client, "gimp_create_image", width=size, height=size, fill=left))["id"]
    layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    await call(client, "gimp_select_rectangle", image=image, x=size // 2, y=0, width=size // 2, height=size)
    await call(client, "gimp_fill", item=layer, color=right)
    await call(client, "gimp_modify_selection", image=image, action="none")
    return image, layer


async def export(client, image: str, path: Path, **options) -> Image.Image:
    kind = "png_options" if path.suffix == ".png" else "jpeg_options"
    await call(
        client, "gimp_export_image", image=image, path=str(path), overwrite=True, **({kind: options} if options else {})
    )
    img = Image.open(path)
    img.load()
    return img


def first(pixel) -> int:
    return pixel if isinstance(pixel, int) else pixel[0]


def png_bit_depth(path: Path) -> int:
    return path.read_bytes()[24]  # IHDR: width(4) height(4) bit depth(1) after signature(8) + length/type(8)


async def close(client, *images: str) -> None:
    for image in images:
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_rgb_gray_indexed_conversions(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await two_tone(client, "#ff0000", "#0000ff")
        gray = await call(client, "gimp_convert_mode", image=image, mode="gray")
        assert (gray["base_type"], gray["changed"]) == ("gray", True)
        assert (await call(client, "gimp_inspect_image", image=image))["base_type"] == "gray"
        img = await export(client, image, tmp_path / "gray.png")
        assert img.mode in ("L", "LA") and abs(first(img.getpixel((2, 2))) - RED_LUMINANCE) <= 1
        # a color given to a gray image is turned into its luminance
        await call(client, "gimp_fill", item=layer, color="#ff0000", area="layer")
        img = await export(client, image, tmp_path / "gray-fill.png")
        assert abs(first(img.getpixel((12, 2))) - RED_LUMINANCE) <= 1
        again = await call(client, "gimp_convert_mode", image=image, mode="gray")
        assert again["changed"] is False
        assert (await call(client, "gimp_convert_mode", image=image, mode="rgb"))["base_type"] == "rgb"

        indexed, layer = await two_tone(client, "#ff8000", "#0080ff")
        result = await call(client, "gimp_convert_mode", image=indexed, mode="indexed", colors=4)
        assert result["base_type"] == "indexed" and result["palette_colors"] == 2  # unused entries removed
        img = await export(client, indexed, tmp_path / "indexed.png")
        assert img.mode == "P"
        assert {img.convert("RGB").getpixel((2, 2)), img.convert("RGB").getpixel((12, 2))} == {
            (255, 128, 0),
            (0, 128, 255),
        }
        # a color given to an indexed image becomes the nearest palette entry
        await call(client, "gimp_fill", item=layer, color="#ff0000", area="layer")
        img = await export(client, indexed, tmp_path / "indexed-fill.png")
        assert img.convert("RGB").getpixel((12, 2)) == (255, 128, 0)

        web, _ = await two_tone(client, "#123456", "#fedcba")
        result = await call(client, "gimp_convert_mode", image=web, mode="indexed", palette="web", remove_unused=False)
        assert result["palette_colors"] == 216
        custom, _ = await two_tone(client, "#808080", "#ffffff")
        result = await call(
            client, "gimp_convert_mode", image=custom, mode="indexed", palette="custom", palette_name="Web",
            dither="floyd-steinberg",
        )  # fmt: skip
        assert result["base_type"] == "indexed"
        rgb = (await export(client, custom, tmp_path / "custom.png")).convert("RGB")
        assert all(v % 51 == 0 for v in rgb.getpixel((12, 2)))  # type: ignore[union-attr]  # web-safe values
        await close(client, image, indexed, web, custom)


async def test_precision_conversions_are_reported(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _ = await two_tone(client, "#404040", "#c0c0c0")
        for precision in ("u16-non-linear", "float-linear", "u8-non-linear"):
            result = await call(client, "gimp_convert_precision", image=image, precision=precision)
            assert result["precision"] == precision
            assert (await call(client, "gimp_inspect_image", image=image))["precision"] == precision
        await call(client, "gimp_convert_precision", image=image, precision="u16-non-linear")
        await export(client, image, tmp_path / "16bit.png")
        assert png_bit_depth(tmp_path / "16bit.png") == 16  # PIL would reduce 16-bit RGB to 8 bits: read the header
        await call(client, "gimp_convert_precision", image=image, precision="u8-non-linear")
        await export(client, image, tmp_path / "8bit.png")
        assert png_bit_depth(tmp_path / "8bit.png") == 8
        await call(client, "gimp_convert_precision", image=image, precision="u16-non-linear")
        assert (await call(client, "gimp_convert_precision", image=image, precision="u16-non-linear"))[
            "changed"
        ] is False
        await close(client, image)


async def test_color_profiles_assign_convert_remove_and_export(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await two_tone(client, "#404040", "#c0c0c0")
        profile = await call(client, "gimp_get_color_profile", image=image)
        assert profile["assigned"] is None and profile["effective"]["model"] == "rgb"
        assert profile["effective"]["linear"] is False

        # convert: the colors look the same, the profile is now linear
        converted = await call(client, "gimp_set_color_profile", image=image, action="convert", profile="srgb-linear")
        assert converted["assigned"]["linear"] is True
        img = await export(client, image, tmp_path / "linear.png")
        assert img.info.get("icc_profile")  # embedded by default: the image has a profile
        raw = img.convert("RGB").getpixel((2, 2))[0]  # type: ignore[index]
        assert abs(raw - 13) <= 1  # 64 in sRGB is 0.051 in linear light, stored as-is: 13/255
        plain = await export(client, image, tmp_path / "no-profile.png", color_profile=False)
        assert not plain.info.get("icc_profile")

        # a color given to a non-sRGB image is converted: filling with #404040 stores linear 13 again
        await call(client, "gimp_fill", item=layer, color="#404040", area="layer")
        img = await export(client, image, tmp_path / "linear-fill.png")
        assert abs(img.convert("RGB").getpixel((12, 2))[0] - 13) <= 1  # type: ignore[index]

        removed = await call(client, "gimp_set_color_profile", image=image, action="remove")
        assert removed["assigned"] is None
        assert not (await export(client, image, tmp_path / "srgb.png")).info.get("icc_profile")  # none assigned
        forced = await export(client, image, tmp_path / "srgb-forced.png", color_profile=True)
        assert forced.info.get("icc_profile")

        # assign: the pixel values stay, their meaning changes
        assigned, _ = await two_tone(client, "#404040", "#c0c0c0")
        result = await call(client, "gimp_set_color_profile", image=assigned, action="assign", profile="srgb-linear")
        assert result["assigned"]["label"] == result["effective"]["label"]
        img = await export(client, assigned, tmp_path / "assigned.png")
        assert img.convert("RGB").getpixel((2, 2)) == (64, 64, 64)

        # an ICC file: the profile GIMP itself embedded in the previous export
        icc = tmp_path / "linear.icc"
        icc.write_bytes(Image.open(tmp_path / "linear.png").info["icc_profile"])
        from_file, _ = await two_tone(client, "#404040", "#c0c0c0")
        result = await call(
            client, "gimp_set_color_profile", image=from_file, action="assign", profile="file", path=str(icc)
        )
        assert result["assigned"]["linear"] is True
        await close(client, image, assigned, from_file)


async def test_invalid_mode_and_profile_requests_change_nothing(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _ = await two_tone(client, "#404040", "#c0c0c0")
        await call(client, "gimp_convert_precision", image=image, precision="u16-non-linear")
        refused = await error(client, "gimp_convert_mode", image=image, mode="indexed")
        assert refused["code"] == "INVALID_ARGUMENT" and "8-bit" in refused["message"]
        await call(client, "gimp_convert_precision", image=image, precision="u8-non-linear")
        missing = await error(
            client, "gimp_convert_mode", image=image, mode="indexed", palette="custom", palette_name="No such palette"
        )
        assert missing["code"] == "NOT_FOUND"
        gray = await error(client, "gimp_set_color_profile", image=image, action="assign", profile="gray")
        assert gray["code"] == "INVALID_ARGUMENT"
        junk = tmp_path / "junk.icc"
        junk.write_bytes(b"not an icc profile")
        bad = await error(
            client, "gimp_set_color_profile", image=image, action="convert", profile="file", path=str(junk)
        )
        assert bad["code"] == "UNSUPPORTED_FORMAT"
        nofile = await error(
            client, "gimp_set_color_profile", image=image, action="assign", profile="file", path=str(tmp_path / "x.icc")
        )
        assert nofile["code"] == "FILE_NOT_FOUND"
        details = await call(client, "gimp_inspect_image", image=image)
        assert (details["base_type"], details["precision"]) == ("rgb", "u8-non-linear")
        assert (await call(client, "gimp_get_color_profile", image=image))["assigned"] is None
        await close(client, image)

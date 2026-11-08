"""Advanced text (#56) on a real GIMP; rendering checked with PIL."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


def rgb(img: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return img.getpixel((x, y))  # type: ignore[return-value]


def ink_columns(img: Image.Image) -> list[int]:
    """x positions of columns containing dark pixels on a white background."""
    rgb = img.convert("RGB")
    return [x for x in range(rgb.width) if any(rgb.getpixel((x, y))[0] < 128 for y in range(rgb.height))]  # type: ignore[index]


async def text_on_white(client, text: str, size: int = 24) -> tuple[str, str]:
    image = (await call(client, "gimp_create_image", width=240, height=60, fill="#ffffff"))["id"]
    layer = await call(client, "gimp_create_text_layer", image=image, text=text, size=size, x=0, y=0, color="#000000")
    return image, layer["id"]


async def png(client, image: str, path: Path) -> Image.Image:
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    with Image.open(path) as img:
        return img.convert("RGB")


async def test_rich_text_markup_is_applied_and_read_back(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await text_on_white(client, "Hello")
        markup = '<span foreground="#ff0000">Red</span> <b>bold</b>'
        style = await call(client, "gimp_set_text_style", item=layer, markup=markup)
        assert "Red" in (style["markup"] or "") and "bold" in (style["markup"] or "")
        img = await png(client, image, tmp_path / "markup.png")
        reds = [img.getpixel((x, y)) for x in range(60) for y in range(40)]
        assert any(r > 200 and g < 60 and b < 60 for r, g, b in reds)  # type: ignore[misc]
        assert (await call(client, "gimp_inspect_item", item=layer))["kind"] == "text"  # still editable text

        refused = await error(client, "gimp_set_text_style", item=layer, markup="<script>x</script>")
        assert refused["code"] == "INVALID_ARGUMENT"
        assert "Red" in ((await call(client, "gimp_inspect_text_style", item=layer))["markup"] or "")
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_outline_kerning_hinting_indent_and_xcf_round_trip(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await text_on_white(client, "OUT", size=40)
        style = await call(
            client, "gimp_set_text_style", item=layer,
            outline={"mode": "stroke-only", "color": "#0000ff", "width": 2, "join": "round"},
            kerning=True, hint_style="none", indent=10, language="fr",
        )  # fmt: skip
        assert style["outline"]["mode"] == "stroke-only" and style["outline"]["width"] == 2
        assert (style["kerning"], style["hint_style"], style["indent"], style["language"]) == (True, "none", 10.0, "fr")
        img = await png(client, image, tmp_path / "outline.png")
        pixels = [img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)]
        assert any(b > 200 and r < 80 for r, g, b in pixels)  # type: ignore[misc]  # the blue outline is drawn
        assert ink_columns(img)[0] >= 10  # indented

        xcf = tmp_path / "text.xcf"
        await call(client, "gimp_save_image", image=image, path=str(xcf))
        reopened = (await call(client, "gimp_open_image", path=str(xcf)))["id"]
        again = (await call(client, "gimp_inspect_image", image=reopened))["layers"][0]
        kept = await call(client, "gimp_inspect_text_style", item=again["id"])
        assert kept["outline"]["mode"] == "stroke-only" and kept["indent"] == 10.0 and kept["language"] == "fr"
        for each in (image, reopened):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_right_to_left_scripts_and_vertical_direction(gimp: HeadlessGimp, tmp_path: Path):
    """Hebrew text lays out right to left: in 'שלום A' the red A ends up left of the Hebrew word.

    GIMP 3.2 leaves the horizontal paragraph direction to Pango, which takes it from the first
    strong character; base_direction is stored, and the vertical directions change the layout.
    """
    async with mcp_client(gimp) as client:
        image, layer = await text_on_white(client, "x")
        style = await call(
            client, "gimp_set_text_style", item=layer, markup='שלום <span foreground="#ff0000">A</span>',
            language="he", base_direction="rtl",
        )  # fmt: skip
        assert (style["base_direction"], style["language"]) == ("rtl", "he")
        img = await png(client, image, tmp_path / "hebrew.png")
        red = [
            x for x in range(img.width) for y in range(img.height) if rgb(img, x, y)[0] > 200 and rgb(img, x, y)[1] < 80
        ]
        black = [x for x in range(img.width) for y in range(img.height) if sum(rgb(img, x, y)) < 150]
        assert red and black and max(red) < min(black)  # read right to left: the A comes after, on the left
        await call(client, "gimp_close_image", image=image, discard_changes=True)

        image, layer = await text_on_white(client, "ABCD")
        horizontal = await call(client, "gimp_inspect_text_style", item=layer)
        vertical = await call(client, "gimp_set_text_style", item=layer, base_direction="ttb-rtl")
        assert horizontal["width"] > horizontal["height"] and vertical["height"] > vertical["width"]
        await call(client, "gimp_close_image", image=image, discard_changes=True)

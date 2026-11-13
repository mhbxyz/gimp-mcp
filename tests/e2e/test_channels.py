"""Advanced selections and channels (#51) on a real GIMP.

Selections are made visible by filling them with black on white and reading the PNG with PIL:
a pixel's darkness is how much it was selected.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


def gray(img: Image.Image, x: int, y: int) -> int:
    return img.getpixel((x, y))[0]  # type: ignore[index]


async def board(client) -> tuple[str, str]:
    """40x40 white image with a red 10x10 square at (5, 5) and another at (25, 25), a blue one at (25, 5)."""
    image = (await call(client, "gimp_create_image", width=40, height=40, fill="#ffffff"))["id"]
    layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    for x, y, color in ((5, 5, "#ff0000"), (25, 25, "#ff0000"), (25, 5, "#0000ff")):
        await call(client, "gimp_select_rectangle", image=image, x=x, y=y, width=10, height=10)
        await call(client, "gimp_fill", item=layer, color=color)
    await call(client, "gimp_modify_selection", image=image, action="none")
    return image, layer


async def show_selection(client, image: str, path: Path) -> Image.Image:
    """Fill the selection with black on a new white layer on top and export the result."""
    layer = await call(client, "gimp_create_layer", image=image, name="probe", fill="#ffffff")
    await call(client, "gimp_fill", item=layer["id"], color="#000000")
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    await call(client, "gimp_delete_layer", item=layer["id"])
    with Image.open(path) as img:
        return img.convert("RGB")


async def test_select_by_color_fuzzy_and_from_items(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _layer = await board(client)
        everywhere = await call(client, "gimp_select_by_color", image=image, color="#ff0000", threshold=10)
        assert everywhere["bounds"] == {"x": 5, "y": 5, "width": 30, "height": 30}  # both red squares
        fuzzy = await call(client, "gimp_select_by_color", image=image, point=[7, 7], threshold=10)
        assert fuzzy["bounds"] == {"x": 5, "y": 5, "width": 10, "height": 10}  # only the touched one
        by_hue = await call(
            client, "gimp_select_by_color", image=image, color="#ff0000", criterion="hsv-hue", threshold=10,
            operation="add",
        )  # fmt: skip
        assert by_hue["bounds"]["width"] == 30

        path = await call(
            client, "gimp_create_path", image=image,
            strokes=[{"type": "polyline", "points": [[0, 0], [20, 0], [20, 20], [0, 20]], "closed": True}],
        )  # fmt: skip
        from_path = await call(client, "gimp_select_item", item=path["id"])
        assert from_path["bounds"] == {"x": 0, "y": 0, "width": 20, "height": 20}
        sprite = await call(
            client, "gimp_create_layer", image=image, name="sprite", width=6, height=4, x=30, y=30, fill="#00ff00"
        )
        from_alpha = await call(client, "gimp_select_item", item=sprite["id"])
        assert from_alpha["bounds"] == {"x": 30, "y": 30, "width": 6, "height": 4}
        text = await call(client, "gimp_create_text_layer", image=image, text="I", size=20, x=2, y=2)
        glyph = await call(client, "gimp_select_item", item=text["id"])
        assert glyph["bounds"] and glyph["bounds"]["width"] < text["width"] + 1
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_sample_merged_reads_every_visible_layer(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, _ = await board(client)
        top = await call(client, "gimp_create_layer", image=image, name="empty", fill="transparent")
        own = await call(client, "gimp_select_by_color", image=image, item=top["id"], color="#ff0000", threshold=10)
        assert own["empty"] is True  # the transparent top layer has no red
        merged = await call(
            client, "gimp_select_by_color", image=image, item=top["id"], color="#ff0000", threshold=10,
            sample_merged=True,
        )  # fmt: skip
        assert merged["bounds"] == {"x": 5, "y": 5, "width": 30, "height": 30}  # the red squares below
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_selection_modifiers(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _ = await board(client)
        await call(client, "gimp_select_rectangle", image=image, x=10, y=10, width=20, height=20)
        grown = await call(client, "gimp_modify_selection_shape", image=image, action="grow", amount=3)
        assert grown["bounds"] == {"x": 7, "y": 7, "width": 26, "height": 26}
        shrunk = await call(client, "gimp_modify_selection_shape", image=image, action="shrink", amount=5)
        assert shrunk["bounds"] == {"x": 12, "y": 12, "width": 16, "height": 16}
        moved = await call(client, "gimp_modify_selection_shape", image=image, action="translate", dx=4, dy=-2)
        assert moved["bounds"] == {"x": 16, "y": 10, "width": 16, "height": 16}

        await call(client, "gimp_select_rectangle", image=image, x=10, y=10, width=20, height=20)
        await call(client, "gimp_modify_selection_shape", image=image, action="border", amount=2)
        img = await show_selection(client, image, tmp_path / "border.png")
        assert gray(img, 20, 20) == 255 and gray(img, 10, 20) < 128  # inside empty, the edge selected

        await call(client, "gimp_select_rectangle", image=image, x=5, y=5, width=30, height=30)
        await call(client, "gimp_select_rectangle", image=image, x=15, y=15, width=4, height=4, operation="subtract")
        await call(client, "gimp_modify_selection_shape", image=image, action="remove-holes")
        img = await show_selection(client, image, tmp_path / "holes.png")
        assert gray(img, 16, 16) == 0  # the hole is selected again

        await call(client, "gimp_select_rectangle", image=image, x=5, y=5, width=30, height=30)
        await call(client, "gimp_modify_selection_shape", image=image, action="round", amount=50)
        img = await show_selection(client, image, tmp_path / "round.png")
        assert gray(img, 5, 5) == 255 and gray(img, 20, 5) == 0  # the corner is cut, the edge middle kept
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_antialias_and_feather_with_pixel_values(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=40, height=40, fill="#ffffff"))["id"]
        hard = await call(
            client, "gimp_create_path", image=image,
            strokes=[{"type": "ellipse", "center": [20, 20], "radius_x": 12, "radius_y": 12}],
        )  # fmt: skip
        await call(client, "gimp_select_item", item=hard["id"], antialias=False)
        img = await show_selection(client, image, tmp_path / "aliased.png")
        assert {gray(img, x, 20) for x in range(40)} <= {0, 255}  # without antialiasing: in or out
        await call(client, "gimp_select_item", item=hard["id"], antialias=True)
        img = await show_selection(client, image, tmp_path / "antialiased.png")
        row = [gray(img, x, 14) for x in range(40)]
        assert any(0 < value < 255 for value in row)  # antialiasing: partly selected edge pixels

        await call(client, "gimp_select_rectangle", image=image, x=10, y=10, width=20, height=20)
        await call(client, "gimp_modify_selection_shape", image=image, action="feather", amount=10)
        img = await show_selection(client, image, tmp_path / "feathered.png")
        # a 10 px feather on a 20 px square: the center is mostly selected, the edge half, the outside barely
        assert gray(img, 20, 20) < 60 and 40 < gray(img, 10, 20) < 215 and gray(img, 1, 20) > 235
        await call(client, "gimp_modify_selection_shape", image=image, action="sharpen")
        img = await show_selection(client, image, tmp_path / "sharpened.png")
        assert {gray(img, x, 20) for x in range(40)} <= {0, 255}
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_channels_store_combine_and_survive_xcf(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _ = await board(client)
        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=10, height=10)
        saved = await call(client, "gimp_create_channel", image=image, name="Corner", source="selection")
        await call(client, "gimp_select_rectangle", image=image, x=30, y=30, width=10, height=10)
        other = await call(client, "gimp_create_channel", image=image, name="Other", source="selection")
        combined = await call(client, "gimp_combine_channels", channel=saved["id"], other=other["id"], operation="add")
        assert combined["name"] == "Corner"
        await call(client, "gimp_modify_selection", image=image, action="none")
        restored = await call(client, "gimp_select_item", item=saved["id"])
        assert restored["bounds"] == {"x": 0, "y": 0, "width": 40, "height": 40}

        red = await call(client, "gimp_create_channel", image=image, name="Red", source="component", component="red")
        red_selection = await call(client, "gimp_select_item", item=red["id"])
        assert red_selection["bounds"] == {"x": 0, "y": 0, "width": 40, "height": 40}  # white and red are red
        changed = await call(client, "gimp_set_channel", channel=red["id"], color="#00ff00", opacity=75, visible=False)
        assert (changed["color"], changed["opacity"], changed["visible"]) == ("#00ff00", 75.0, False)
        await call(client, "gimp_delete_channel", channel=other["id"])

        xcf = tmp_path / "channels.xcf"
        await call(client, "gimp_save_image", image=image, path=str(xcf))
        reopened = (await call(client, "gimp_open_image", path=str(xcf)))["id"]
        channels = (await call(client, "gimp_inspect_image", image=reopened))["channels"]
        assert sorted(c["name"] for c in channels) == ["Corner", "Red"]
        assert next(c for c in channels if c["name"] == "Red")["color"] == "#00ff00"
        for each in (image, reopened):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_invalid_selection_requests_change_nothing(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, layer = await board(client)
        assert (await error(client, "gimp_modify_selection_shape", image=image, action="grow", amount=2))[
            "code"
        ] == "EMPTY_SELECTION"
        assert (await error(client, "gimp_select_by_color", image=image, point=[50, 1]))["code"] == "INVALID_ARGUMENT"
        assert (await error(client, "gimp_create_channel", image=image, source="selection"))[
            "code"
        ] == "EMPTY_SELECTION"
        assert (await error(client, "gimp_set_channel", channel=layer, name="x"))["code"] == "WRONG_KIND"
        assert (await call(client, "gimp_get_selection", image=image))["empty"] is True
        assert (await call(client, "gimp_inspect_image", image=image))["channels"] == []
        await call(client, "gimp_close_image", image=image, discard_changes=True)

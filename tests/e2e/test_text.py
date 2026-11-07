from __future__ import annotations

from pathlib import Path

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, find, preview


def dark_pixels(img, box) -> int:
    x0, y0, x1, y1 = box
    count = 0
    for x in range(x0, x1):
        for y in range(y0, y1):
            r, g, b, a = img.getpixel((x, y))  # type: ignore[misc]
            if a > 0 and r < 100 and g < 100 and b < 100:
                count += 1
    return count


def red_pixels(img, box) -> int:
    x0, y0, x1, y1 = box
    count = 0
    for x in range(x0, x1):
        for y in range(y0, y1):
            r, g, b, a = img.getpixel((x, y))  # type: ignore[misc]
            if a > 0 and r > 180 and g < 80 and b < 80:
                count += 1
    return count


async def test_create_edit_inspect_render_and_persist_editable_text(gimp: HeadlessGimp, tmp_path: Path):
    project = tmp_path / "text.xcf"
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=300, height=120, fill="white"))["id"]
        text = await call(
            client,
            "gimp_create_text_layer",
            image=image,
            text="Hello",
            font="Sans-serif",
            size=40,
            color="#000000",
            x=10,
            y=10,
        )
        assert text["kind"] == "text" and (text["x"], text["y"]) == (10, 10)
        shot = await preview(client, image)
        assert dark_pixels(shot, (10, 10, 10 + text["width"], 10 + text["height"])) > 50

        edited = await call(
            client,
            "gimp_set_text",
            item=text["id"],
            text="Hello MCP",
            size=32,
            color="#ff0000",
            justify="center",
            x=20,
            y=50,
        )
        props = await call(client, "gimp_inspect_text", item=text["id"])
        assert props["text"] == "Hello MCP" and props["font"] == "Sans-serif"
        assert (props["size"], props["size_unit"], props["justify"]) == (32.0, "px", "center")
        assert props["color"] == "#ff0000" and (edited["x"], edited["y"]) == (20, 50)
        shot = await preview(client, image)
        assert red_pixels(shot, (20, 50, 20 + edited["width"], 50 + edited["height"])) > 50
        assert dark_pixels(shot, (0, 0, 300, 45)) == 0  # the old black text is gone (re-rendered, not painted)

        await call(client, "gimp_save_image", image=image, path=str(project))
        await call(client, "gimp_close_image", image=image)
        reopened = (await call(client, "gimp_open_image", path=str(project)))["id"]
        node = find(await call(client, "gimp_inspect_image", image=reopened), "Hello MCP")
        again = await call(client, "gimp_inspect_text", item=node["id"])
        await call(client, "gimp_close_image", image=reopened)
    assert node["kind"] == "text"
    assert (again["text"], again["size"], again["color"], again["justify"]) == ("Hello MCP", 32.0, "#ff0000", "center")


async def test_fixed_box_points_and_spacing(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=200, height=200))["id"]
        boxed = await call(
            client,
            "gimp_create_text_layer",
            image=image,
            text="A long title that wraps",
            size=12,
            size_unit="pt",
            box_width=80,
            box_height=120,
            letter_spacing=1.5,
            line_spacing=2,
        )
        props = await call(client, "gimp_inspect_text", item=boxed["id"])
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert (boxed["width"], boxed["height"]) == (80, 120)
    assert (props["size"], props["size_unit"]) == (12.0, "pt")
    assert (props["width"], props["height"]) == (80, 120)  # fixed box
    assert (props["letter_spacing"], props["line_spacing"]) == (1.5, 2.0)


async def test_missing_font_and_non_text_targets_are_explicit(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=50, height=50))["id"]
        background = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
        missing = await error(client, "gimp_create_text_layer", image=image, text="x", font="No Such Font 123")
        not_text = await error(client, "gimp_set_text", item=background, text="nope")
        inspect_not_text = await error(client, "gimp_inspect_text", item=background)
        text = await call(client, "gimp_create_text_layer", image=image, text="x")
        bad_font_edit = await error(client, "gimp_set_text", item=text["id"], font="No Such Font 123")
        fonts = await call(client, "gimp_list_fonts", query="Sans")
        still = await call(client, "gimp_inspect_text", item=text["id"])
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert missing["code"] == "FONT_NOT_FOUND" and missing["outcome"] == "not_applied"
    assert not_text["code"] == "WRONG_KIND" and inspect_not_text["code"] == "WRONG_KIND"
    assert bad_font_edit["code"] == "FONT_NOT_FOUND"
    assert "Sans-serif" in fonts["fonts"]
    assert still["font"] == "Sans-serif"  # failed edit changed nothing


async def test_no_operation_silently_rasterizes_text(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=120, height=60))["id"]
        text = (await call(client, "gimp_create_text_layer", image=image, text="Keep me", size=20))["id"]
        await call(client, "gimp_rotate_layer", item=text, angle=15)
        await call(client, "gimp_set_layer_offsets", item=text, x=5, y=5)
        paint = await error(client, "gimp_fill", item=text, color="#ff0000", area="layer")
        blur = await error(client, "gimp_gaussian_blur", item=text, radius=2)
        editable_blur = await call(client, "gimp_gaussian_blur", item=text, radius=2, destructive=False)
        node = await call(client, "gimp_inspect_item", item=text)
        props = await call(client, "gimp_inspect_text", item=text)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert paint["code"] == "WRONG_KIND" and blur["code"] == "WRONG_KIND"
    assert editable_blur["destructive"] is False
    assert node["kind"] == "text" and props["text"] == "Keep me"

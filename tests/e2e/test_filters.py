from __future__ import annotations

from pathlib import Path

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, find, preview, rgba


async def gray_scene(client):
    image = (await call(client, "gimp_create_image", width=40, height=20, fill="#808080"))["id"]
    layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    return image, layer


async def test_destructive_brightness_contrast_respects_the_selection(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, layer = await gray_scene(client)
        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=20, height=20)
        result = await call(client, "gimp_brightness_contrast", item=layer, brightness=50, contrast=0)
        shot = await preview(client, image)
        filters = await call(client, "gimp_list_filters", item=layer)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert result["destructive"] is True and result["filter"] is None
    assert result["restricted_to_selection"] is True
    left, right = rgba(shot, 5, 10), rgba(shot, 35, 10)
    assert left[0] > 160 and left[0] == left[1] == left[2]  # brightened, still gray
    assert right[:3] == (128, 128, 128)  # outside the selection: untouched
    assert filters["filters"] == []


async def test_hue_saturation_changes_colors(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=10, height=10, fill="#ff0000"))["id"]
        layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
        rotated = await call(client, "gimp_hue_saturation", item=layer, hue=120)
        green = rgba(await preview(client, image), 5, 5)
        await call(client, "gimp_hue_saturation", item=layer, saturation=-100)
        gray = rgba(await preview(client, image), 5, 5)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert rotated["destructive"] is True
    assert green[1] > 200 and green[0] < 60 and green[2] < 60  # red rotated by +120° is green
    assert abs(gray[0] - gray[1]) <= 2 and abs(gray[1] - gray[2]) <= 2  # fully desaturated


async def test_non_destructive_blur_is_editable_and_saved(gimp: HeadlessGimp, tmp_path: Path):
    project = tmp_path / "blur.xcf"
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=40, height=20, fill="white"))["id"]
        bar = await call(client, "gimp_create_layer", image=image, name="Bar", fill="transparent")
        await call(
            client,
            "gimp_draw_shape",
            item=bar["id"],
            shape="rectangle",
            x=18,
            y=0,
            width=4,
            height=20,
            fill_color="#000000",
            antialias=False,
        )
        sharp = await preview(client, image)
        blur = await call(client, "gimp_gaussian_blur", item=bar["id"], radius=3, destructive=False)
        blurred = await preview(client, image)
        listed = await call(client, "gimp_list_filters", item=bar["id"])
        await call(client, "gimp_save_image", image=image, path=str(project))
        await call(client, "gimp_close_image", image=image)
        reopened = (await call(client, "gimp_open_image", path=str(project)))["id"]
        bar_again = find(await call(client, "gimp_inspect_image", image=reopened), "Bar")["id"]
        kept = await call(client, "gimp_list_filters", item=bar_again)
        removed = await call(client, "gimp_remove_filter", item=bar_again, filter=kept["filters"][0]["id"])
        restored = await preview(client, reopened)
        await call(client, "gimp_close_image", image=reopened, discard_changes=True)
    assert blur["destructive"] is False and blur["filter"] is not None
    assert [f["operation"] for f in listed["filters"]] == ["gegl:gaussian-blur"]
    assert rgba(sharp, 15, 10)[:3] == (255, 255, 255)
    assert rgba(blurred, 15, 10)[0] < 250  # the blur spreads the bar
    assert [f["operation"] for f in kept["filters"]] == ["gegl:gaussian-blur"]  # persisted in XCF
    assert removed["filters"] == []
    assert rgba(restored, 15, 10)[:3] == (255, 255, 255)  # removing the filter restores the pixels


async def test_invalid_filter_requests(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, layer = await gray_scene(client)
        group = await call(client, "gimp_create_group", image=image, name="G")
        out_of_range = await client.call_tool("gimp_brightness_contrast", {"item": layer, "brightness": 300})
        on_group = await error(client, "gimp_gaussian_blur", item=group["id"], radius=2)
        bad_filter = await error(client, "gimp_remove_filter", item=layer, filter="filter:999@" + layer.split("@")[1])
        filters = await call(client, "gimp_list_filters", item=layer)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert out_of_range.is_error
    assert on_group["code"] == "WRONG_KIND"
    assert bad_filter["code"] == "NOT_FOUND"
    assert filters["filters"] == []  # nothing was applied


async def test_selection_restricts_blur_and_non_destructive_filters(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=40, height=20, fill="white"))["id"]
        bar = (await call(client, "gimp_create_layer", image=image, name="Bar"))["id"]
        await call(
            client,
            "gimp_draw_shape",
            item=bar,
            shape="rectangle",
            x=18,
            y=0,
            width=4,
            height=20,
            fill_color="#000000",
            antialias=False,
        )
        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=20, height=20)
        blur = await call(client, "gimp_gaussian_blur", item=bar, radius=3)
        after_blur = await preview(client, image)
        gray = (await call(client, "gimp_inspect_image", image=image))["layers"][1]["id"]
        nde = await call(client, "gimp_brightness_contrast", item=gray, brightness=-50, destructive=False)
        after_nde = await preview(client, image)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert blur["restricted_to_selection"] is True
    assert rgba(after_blur, 16, 10)[0] < 250  # blurred inside the selection
    assert rgba(after_blur, 23, 10)[:3] == (255, 255, 255)  # outside: the bar edge stays sharp
    assert rgba(after_blur, 21, 10)[:3] == (0, 0, 0)
    assert nde["destructive"] is False and nde["restricted_to_selection"] is True
    assert rgba(after_nde, 5, 10)[0] < 240  # darkened inside the selection (white -> ~225)
    assert rgba(after_nde, 35, 10)[:3] == (255, 255, 255)  # unchanged outside

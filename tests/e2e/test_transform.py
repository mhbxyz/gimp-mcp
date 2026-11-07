from __future__ import annotations

import pytest

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, preview, rgba


async def make_scene(client) -> tuple[str, dict]:
    """100x50 white image with a 20x10 layer: left half red, right half blue, at (10, 5)."""
    image = (await call(client, "gimp_create_image", width=100, height=50, fill="white"))["id"]
    group = await call(client, "gimp_create_group", image=image, name="Mark")
    red = await call(
        client,
        "gimp_create_layer",
        image=image,
        name="Red",
        parent=group["id"],
        width=10,
        height=10,
        x=10,
        y=5,
        fill="#ff0000",
    )
    await call(
        client,
        "gimp_create_layer",
        image=image,
        name="Blue",
        parent=group["id"],
        width=10,
        height=10,
        x=20,
        y=5,
        fill="#0000ff",
    )
    return image, {"group": group["id"], "red": red["id"]}


async def test_layer_transforms_change_geometry_and_rendering(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, ids = await make_scene(client)
        other = (await call(client, "gimp_create_image", width=10, height=10))["id"]

        moved = await call(client, "gimp_set_layer_offsets", item=ids["group"], x=50, y=20)
        assert (moved["x"], moved["y"], moved["width"], moved["height"]) == (50, 20, 20, 10)
        shot = await preview(client, image)
        assert rgba(shot, 55, 25)[:3] == (255, 0, 0) and rgba(shot, 65, 25)[:3] == (0, 0, 255)
        assert rgba(shot, 15, 10)[:3] == (255, 255, 255)

        flipped = await call(client, "gimp_flip_layer", item=ids["group"], direction="horizontal")
        assert (flipped["x"], flipped["width"]) == (50, 20)
        shot = await preview(client, image)
        assert rgba(shot, 55, 25)[:3] == (0, 0, 255) and rgba(shot, 65, 25)[:3] == (255, 0, 0)

        scaled = await call(
            client, "gimp_scale_layer", item=ids["red"], width=20, height=20, anchor="top-left", interpolation="none"
        )
        assert (scaled["x"], scaled["y"], scaled["width"], scaled["height"]) == (60, 20, 20, 20)

        rotated = await call(client, "gimp_rotate_layer", item=ids["red"], angle=90, interpolation="none")
        assert (rotated["width"], rotated["height"]) == (20, 20)
        rotated = await call(client, "gimp_scale_layer", item=ids["red"], width=20, height=10, interpolation="none")
        assert (rotated["x"], rotated["y"]) == (60, 25)  # anchor="center" keeps the center (70, 30)
        rotated = await call(client, "gimp_rotate_layer", item=ids["red"], angle=90, interpolation="none")
        assert (rotated["width"], rotated["height"]) == (10, 20)  # the bounding box follows the rotation

        untouched = await call(client, "gimp_inspect_image", image=other)
        for target in (image, other):
            await call(client, "gimp_close_image", image=target, discard_changes=True)
    assert untouched["dirty"] is False and (untouched["width"], untouched["height"]) == (10, 10)


async def test_image_resize_canvas_and_crop(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, ids = await make_scene(client)
        resized = await call(client, "gimp_resize_image", image=image, width=50, height=25, interpolation="none")
        assert (resized["width"], resized["height"]) == (50, 25)
        red = await call(client, "gimp_inspect_item", item=ids["red"])
        # scaled with the image; GIMP rounds the 2.5 offset up
        assert (red["x"], red["y"], red["width"], red["height"]) == (5, 3, 5, 5)

        canvas = await call(client, "gimp_resize_canvas", image=image, width=60, height=35, offset_x=10, offset_y=10)
        assert (canvas["width"], canvas["height"]) == (60, 35)
        red = await call(client, "gimp_inspect_item", item=ids["red"])
        assert (red["x"], red["y"], red["width"], red["height"]) == (15, 13, 5, 5)  # moved, not resampled

        cropped = await call(client, "gimp_crop_image", image=image, x=15, y=13, width=10, height=5)
        assert (cropped["width"], cropped["height"]) == (10, 5)
        shot = await preview(client, image)
        assert shot.size == (10, 5)
        assert rgba(shot, 2, 2)[:3] == (255, 0, 0) and rgba(shot, 7, 2)[:3] == (0, 0, 255)
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_invalid_transforms_are_rejected(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, ids = await make_scene(client)
        outside = await error(client, "gimp_crop_image", image=image, x=90, y=0, width=20, height=10)
        await call(client, "gimp_set_layer_properties", item=ids["red"], lock_position=True)
        locked_move = await error(client, "gimp_set_layer_offsets", item=ids["red"], x=0, y=0)
        locked_flip = await error(client, "gimp_flip_layer", item=ids["red"], direction="vertical")
        await call(client, "gimp_set_layer_properties", item=ids["red"], lock_position=False, lock_content=True)
        locked_scale = await error(client, "gimp_scale_layer", item=ids["red"], width=5, height=5)
        bad_interp = await client.call_tool(
            "gimp_scale_layer", {"item": ids["red"], "width": 5, "height": 5, "interpolation": "sharp"}
        )
        state = await call(client, "gimp_inspect_item", item=ids["red"])
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert outside["code"] == "INVALID_ARGUMENT"
    assert locked_move["code"] == "LOCKED" and locked_flip["code"] == "LOCKED" and locked_scale["code"] == "LOCKED"
    assert bad_interp.is_error
    assert (state["x"], state["y"], state["width"], state["height"]) == (10, 5, 10, 10)


@pytest.mark.parametrize("angle", [0.0, 360.0])
async def test_trivial_rotation_keeps_the_layer(gimp: HeadlessGimp, angle: float):
    async with mcp_client(gimp) as client:
        image, ids = await make_scene(client)
        node = await call(client, "gimp_rotate_layer", item=ids["red"], angle=angle, interpolation="none")
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert (node["x"], node["y"], node["width"], node["height"]) == (10, 5, 10, 10)


async def test_positive_angles_rotate_clockwise(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, ids = await make_scene(client)  # group 20x10 at (10, 5): red left, blue right
        node = await call(client, "gimp_rotate_layer", item=ids["group"], angle=90, interpolation="none")
        shot = await preview(client, image)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert (node["x"], node["y"], node["width"], node["height"]) == (15, 0, 10, 20)
    assert rgba(shot, 20, 5)[:3] == (255, 0, 0)  # left half went to the top
    assert rgba(shot, 20, 15)[:3] == (0, 0, 255)

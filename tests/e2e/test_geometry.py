"""Advanced transforms (#55) on a real GIMP; geometry checked against computed values, pixels with PIL."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


def px(img: Image.Image, x: int, y: int) -> tuple[int, ...]:
    return img.getpixel((x, y))  # type: ignore[return-value]


async def scene(client, width: int = 100, height: int = 60) -> tuple[str, str]:
    image = (await call(client, "gimp_create_image", width=width, height=height, fill="transparent"))["id"]
    layer = await call(
        client, "gimp_create_layer", image=image, name="Box", width=40, height=20, x=10, y=10, fill="#ff0000"
    )
    return image, layer["id"]


async def png(client, image: str, path: Path) -> Image.Image:
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    with Image.open(path) as img:
        return img.convert("RGBA")


async def test_matrix_shear_perspective_and_rotation_on_layers(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, box = await scene(client)
        moved = await call(
            client, "gimp_transform", item=box, transform="matrix", matrix=[[1, 0, 5], [0, 1, 7], [0, 0, 1]]
        )
        assert (moved["layer"]["x"], moved["layer"]["y"], moved["layer"]["width"]) == (15, 17, 40)

        sheared = await call(client, "gimp_transform", item=box, transform="shear", magnitude=10)
        assert sheared["layer"]["width"] == 50 and sheared["layer"]["height"] == 20

        image2, box2 = await scene(client)
        # perspective: the top edge shrinks to 20 px centered, the bottom stays: a trapezoid
        await call(
            client, "gimp_transform", item=box2, transform="perspective",
            corners=[[20, 10], [40, 10], [10, 30], [50, 30]], interpolation="none",
        )  # fmt: skip
        img = await png(client, image2, tmp_path / "perspective.png")
        assert px(img, 12, 11)[3] == 0 and px(img, 30, 11)[0] == 255 and px(img, 12, 29)[0] == 255

        image3, box3 = await scene(client)
        rotated = await call(
            client,
            "gimp_transform",
            item=box3,
            transform="rotate",
            angle=90,
            center_x=10,
            center_y=10,
            interpolation="none",
        )
        # (10..50, 10..30) rotated 90° clockwise around (10, 10) -> x in -10..10, y in 10..50
        layer = rotated["layer"]
        assert (layer["x"], layer["y"], layer["width"], layer["height"]) == (-10, 10, 20, 40)
        for each in (image, image2, image3):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_selection_and_paths_are_transformed(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, _ = await scene(client)
        await call(client, "gimp_select_rectangle", image=image, x=20, y=20, width=40, height=10)
        result = await call(
            client,
            "gimp_transform",
            image=image,
            selection=True,
            transform="rotate",
            angle=90,
            center_x=40,
            center_y=25,
            interpolation="none",
        )
        assert result["kind"] == "selection"
        assert result["selection"]["bounds"] == {"x": 35, "y": 5, "width": 10, "height": 40}
        # with interpolation the selection edge is softened: one more partly selected pixel on each side
        soft = await call(
            client,
            "gimp_transform",
            image=image,
            selection=True,
            transform="rotate",
            angle=90,
            center_x=40,
            center_y=25,
        )
        assert soft["selection"]["bounds"]["width"] == 40 + 2

        path = await call(
            client, "gimp_create_path", image=image, strokes=[{"type": "polyline", "points": [[0, 0], [10, 0]]}]
        )
        await call(
            client, "gimp_transform", item=path["id"], transform="matrix", matrix=[[2, 0, 3], [0, 1, 4], [0, 0, 1]]
        )
        points = (await call(client, "gimp_inspect_path", path=path["id"], points=True))["strokes"][0]["control_points"]
        assert points[1] == [3.0, 4.0] and points[4] == [23.0, 4.0]
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_image_rotation_flip_and_canvas_options(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _box = await scene(client)
        rotated = await call(client, "gimp_rotate_image", image=image, angle=90)
        assert (rotated["width"], rotated["height"]) == (60, 100)
        img = await png(client, image, tmp_path / "rotated.png")
        # box (10..50, 10..30) -> after 90° clockwise in a 100x60 image: x = 60-1-y, y = x
        assert px(img, 60 - 1 - 20, 30)[0] == 255 and px(img, 5, 5)[3] == 0
        await call(client, "gimp_flip_image", image=image, orientation="horizontal")
        img = await png(client, image, tmp_path / "flipped.png")
        assert px(img, 20, 30)[0] == 255  # mirrored back to the left side

        canvas = (await call(client, "gimp_create_image", width=20, height=20, fill="#0000ff"))["id"]
        grown = await call(
            client, "gimp_resize_canvas", image=canvas, width=40, height=30, offset_x=10, offset_y=5,
            resize_layers="all", fill_color="#ffffff",
        )  # fmt: skip
        assert (grown["width"], grown["height"]) == (40, 30)
        img = await png(client, canvas, tmp_path / "canvas.png")
        assert px(img, 2, 2)[:3] == (255, 255, 255) and px(img, 15, 10)[:3] == (0, 0, 255)
        layer = (await call(client, "gimp_inspect_image", image=canvas))["layers"][0]
        assert (layer["width"], layer["height"]) == (40, 30)
        for each in (image, canvas):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_locks_and_invalid_transforms_change_nothing(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, box = await scene(client)
        assert (await error(client, "gimp_transform", image=image, selection=True, transform="shear", magnitude=3))[
            "code"
        ] == "EMPTY_SELECTION"
        incomplete = await client.call_tool("gimp_transform", {"item": box, "transform": "rotate", "angle": 10})
        assert incomplete.is_error
        group = await call(client, "gimp_create_group", image=image, name="G")
        await call(
            client,
            "gimp_call_procedure",
            name="gimp-item-set-lock-position",
            arguments={"item": box, "lock-position": True},
        )
        assert (await error(client, "gimp_transform", item=box, transform="shear", magnitude=3))["code"] == "LOCKED"
        details = await call(client, "gimp_inspect_item", item=box)
        assert (details["x"], details["width"]) == (10, 40)
        assert group["kind"] == "group"
        await call(client, "gimp_close_image", image=image, discard_changes=True)

"""Layer composition (#54) on a real GIMP; pixels read with PIL."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, find


def px(img: Image.Image, x: int, y: int) -> tuple[int, ...]:
    return img.getpixel((x, y))  # type: ignore[return-value]


async def scene(client) -> tuple[str, str, str]:
    """40x40 red background with a 10x10 blue layer at (5, 5)."""
    image = (await call(client, "gimp_create_image", width=40, height=40, fill="#ff0000"))["id"]
    background = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    blue = await call(
        client, "gimp_create_layer", image=image, name="Blue", width=10, height=10, x=5, y=5, fill="#0000ff"
    )
    return image, background, blue["id"]


async def png(client, image: str, path: Path) -> Image.Image:
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    with Image.open(path) as img:
        return img.convert("RGBA")


async def close(client, *images: str) -> None:
    for image in images:
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_copy_and_paste_into_layer_new_layer_and_new_image(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, background, blue = await scene(client)
        copied = await call(client, "gimp_copy", items=[blue])
        assert copied == {"buffer": "gimp-mcp", "selection": False}

        target, target_bg, _ = await scene(client)
        pasted = await call(client, "gimp_paste", mode="new-layer", item=target_bg)
        assert pasted["layer"]["name"] != "Blue" and pasted["layer"]["width"] == 10
        tree = await call(client, "gimp_inspect_image", image=target)
        assert len(tree["layers"]) == 3  # the paste became a real layer, nothing floats

        into = await call(client, "gimp_paste", mode="into-layer", item=target_bg)
        assert into["layer"]["id"] == target_bg
        assert len((await call(client, "gimp_inspect_image", image=target))["layers"]) == 3  # anchored

        new_image = await call(client, "gimp_paste", mode="new-image")
        opened = await call(client, "gimp_inspect_image", image=new_image["image"])
        assert (opened["width"], opened["height"]) == (10, 10)

        # a selection limits the copy; cut empties the area
        await call(client, "gimp_select_rectangle", image=image, x=5, y=5, width=4, height=4)
        cut = await call(client, "gimp_copy", items=[blue], cut=True, buffer="part")
        assert cut["selection"] is True
        await call(client, "gimp_modify_selection", image=image, action="none")
        img = await png(client, image, tmp_path / "cut.png")
        assert px(img, 6, 6) == (255, 0, 0, 255) and px(img, 12, 12) == (0, 0, 255, 255)
        part = await call(client, "gimp_paste", mode="new-image", buffer="part")
        size = await call(client, "gimp_inspect_image", image=part["image"])
        assert (size["width"], size["height"]) == (4, 4)

        visible = await call(client, "gimp_copy", image=image, visible=True, buffer="flat")
        assert visible["buffer"] == "flat"
        missing = await error(client, "gimp_paste", mode="new-layer", item=background, buffer="never-filled")
        assert missing["code"] == "NOT_FOUND"
        await close(client, image, target, new_image["image"], part["image"])


async def test_merge_flatten_and_new_layer_from_visible(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _background, blue = await scene(client)
        before = await png(client, image, tmp_path / "before.png")
        visible = await call(client, "gimp_new_layer_from_visible", image=image, name="Snapshot")
        assert visible["layer"]["name"] == "Snapshot"
        assert len((await call(client, "gimp_inspect_image", image=image))["layers"]) == 3
        await call(client, "gimp_set_layer_properties", item=visible["layer"]["id"], visible=False)

        merged = await call(client, "gimp_merge_layers", mode="down", item=blue)
        assert merged["layer"]["width"] == 40
        layers = (await call(client, "gimp_inspect_image", image=image))["layers"]
        assert [layer["name"] for layer in layers] == ["Snapshot", merged["layer"]["name"]]
        assert (await png(client, image, tmp_path / "merged.png")).tobytes() == before.tobytes()
        nothing_below = await error(client, "gimp_merge_layers", mode="down", item=merged["layer"]["id"])
        assert nothing_below["code"] == "INVALID_ARGUMENT"

        group = await call(client, "gimp_create_group", image=image, name="Group")
        await call(
            client, "gimp_create_layer", image=image, name="A", parent=group["id"], fill="#00ff00", width=5, height=5
        )
        await call(
            client, "gimp_create_layer", image=image, name="B", parent=group["id"], fill="#ffff00", width=3, height=3
        )
        flattened_group = await call(client, "gimp_merge_layers", mode="group", item=group["id"])
        assert flattened_group["layer"]["kind"] == "layer"

        flat = await call(client, "gimp_flatten_image", image=image)
        assert len((await call(client, "gimp_inspect_image", image=image))["layers"]) == 1
        assert flat["layer"]["has_alpha"] is False
        await close(client, image)


async def test_alpha_bounds_crop_and_alignment(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, background, blue = await scene(client)
        assert (await call(client, "gimp_set_alpha_channel", item=background, action="remove"))["layer"][
            "has_alpha"
        ] is False
        assert (await call(client, "gimp_set_alpha_channel", item=background, action="add"))["layer"][
            "has_alpha"
        ] is True

        selection = await call(client, "gimp_alpha_to_selection", item=blue)
        assert selection["bounds"] == {"x": 5, "y": 5, "width": 10, "height": 10}
        await call(client, "gimp_modify_selection", image=image, action="none")

        grown = await call(
            client, "gimp_fit_layer", item=blue, mode="size", width=20, height=20, offset_x=5, offset_y=5
        )
        assert (grown["layer"]["width"], grown["layer"]["x"], grown["layer"]["y"]) == (20, 0, 0)
        shrunk = await call(client, "gimp_fit_layer", item=blue, mode="content")
        assert (shrunk["layer"]["width"], shrunk["layer"]["x"]) == (10, 5)
        full = await call(client, "gimp_fit_layer", item=blue, mode="image-size")
        assert (full["layer"]["width"], full["layer"]["height"]) == (40, 40)

        # alignment on layer boxes
        small = await call(
            client, "gimp_create_layer", image=image, name="S", width=4, height=6, x=1, y=1, fill="#00ff00"
        )
        tiny = await call(
            client, "gimp_create_layer", image=image, name="T", width=2, height=2, x=30, y=30, fill="#00ff00"
        )
        aligned = await call(
            client, "gimp_align_layers", items=[small["id"], tiny["id"]], horizontal="right", vertical="middle"
        )
        assert [(node["x"], node["y"]) for node in aligned["layers"]] == [(36, 17), (38, 19)]
        third = await call(
            client, "gimp_create_layer", image=image, name="U", width=2, height=2, x=0, y=0, fill="#00ff00"
        )
        spread = await call(
            client, "gimp_align_layers", items=[small["id"], tiny["id"], third["id"]], distribute="vertical"
        )
        ys = sorted(node["y"] + node["height"] / 2 for node in spread["layers"])
        assert abs((ys[1] - ys[0]) - (ys[2] - ys[1])) <= 1  # offsets are whole pixels
        await call(client, "gimp_select_rectangle", image=image, x=10, y=10, width=10, height=10)
        to_selection = await call(
            client, "gimp_align_layers", items=[tiny["id"]], reference="selection", horizontal="left", vertical="top"
        )
        assert (to_selection["layers"][0]["x"], to_selection["layers"][0]["y"]) == (10, 10)
        await call(client, "gimp_modify_selection", image=image, action="none")
        to_layer = await call(
            client,
            "gimp_align_layers",
            items=[tiny["id"]],
            reference="layer",
            reference_item=small["id"],
            horizontal="center",
        )
        assert to_layer["layers"][0]["x"] == 36 + 2 - 1
        await close(client, image)

        # crop to content: a 10x10 blue square on a transparent 40x40 canvas
        canvas = (await call(client, "gimp_create_image", width=40, height=40, fill="transparent"))["id"]
        layer = (await call(client, "gimp_inspect_image", image=canvas))["layers"][0]["id"]
        await call(client, "gimp_select_rectangle", image=canvas, x=8, y=12, width=10, height=10)
        await call(client, "gimp_fill", item=layer, color="#0000ff")
        await call(client, "gimp_modify_selection", image=canvas, action="none")
        cropped = await call(client, "gimp_crop_to_content", image=canvas)
        assert (cropped["width"], cropped["height"], cropped["cropped"]) == (10, 10, True)
        await close(client, canvas)


async def test_invalid_composition_requests_change_nothing(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, background, blue = await scene(client)
        other, other_bg, _ = await scene(client)
        before = await png(client, image, tmp_path / "before.png")
        assert (await error(client, "gimp_copy", items=[blue, other_bg]))["code"] == "IMAGE_MISMATCH"
        assert (await error(client, "gimp_merge_layers", mode="group", item=blue))["code"] == "WRONG_KIND"
        assert (await error(client, "gimp_align_layers", items=[blue], reference="selection", horizontal="left"))[
            "code"
        ] == "EMPTY_SELECTION"
        assert (await error(client, "gimp_align_layers", items=[blue, background], distribute="horizontal"))[
            "code"
        ] == "INVALID_ARGUMENT"
        tree = await call(client, "gimp_inspect_image", image=image)
        assert [layer["name"] for layer in tree["layers"]] == ["Blue", "Background"]
        assert find(tree, "Blue")["x"] == 5
        assert (await png(client, image, tmp_path / "after.png")).tobytes() == before.tobytes()
        await close(client, image, other)

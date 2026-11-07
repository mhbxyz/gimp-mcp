from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, find, preview, rgba, tree


async def test_compose_nested_groups_reorganize_and_verify_tree_and_preview(gimp: HeadlessGimp, tmp_path: Path):
    sticker = tmp_path / "sticker.png"
    Image.new("RGBA", (10, 10), (0, 255, 0, 255)).save(sticker)
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=100, height=50, fill="white"))["id"]
        scene = await call(client, "gimp_create_group", image=image, name="Scene")
        props = await call(client, "gimp_create_group", image=image, name="Props", parent=scene["id"])
        red = await call(
            client,
            "gimp_create_layer",
            image=image,
            name="Red",
            parent=props["id"],
            width=50,
            height=50,
            x=0,
            y=0,
            fill="#ff0000",
        )
        blue = await call(
            client,
            "gimp_create_layer",
            image=image,
            name="Blue",
            parent=scene["id"],
            position=1,
            width=50,
            height=50,
            x=50,
            y=0,
            fill="#0000ff",
            opacity=50,
            mode="multiply",
        )
        imported = await call(client, "gimp_import_layer", image=image, path=str(sticker), x=45, y=20)
        copy = await call(client, "gimp_duplicate_layer", item=red["id"])
        await call(client, "gimp_set_layer_properties", item=copy["id"], name="Red copy", visible=False)

        composed = await call(client, "gimp_inspect_image", image=image)
        assert tree(composed) == [
            ("sticker.png", "layer", []),
            (
                "Scene",
                "group",
                [
                    ("Props", "group", [("Red copy", "layer", []), ("Red", "layer", [])]),
                    ("Blue", "layer", []),
                ],
            ),
            ("Background", "layer", []),
        ]
        blue_node = find(composed, "Blue")
        assert (blue_node["opacity"], blue_node["mode"], blue_node["x"]) == (50.0, "multiply", 50)
        assert find(composed, "sticker.png")["id"] == imported["id"]
        before = await preview(client, image)
        assert rgba(before, 25, 10) == (255, 0, 0, 255)
        assert rgba(before, 50, 25) == (0, 255, 0, 255)  # sticker on top

        # reorganize: Blue moves to the top level, above everything; sticker goes into Props
        await call(client, "gimp_move_layer", item=blue["id"], parent=None, position=0)
        await call(client, "gimp_move_layer", item=imported["id"], parent=props["id"], position=2)
        await call(client, "gimp_delete_layer", item=copy["id"])
        await call(client, "gimp_set_layer_properties", item=props["id"], visible=False)

        final = await call(client, "gimp_inspect_image", image=image)
        after = await preview(client, image)
        gone = await error(client, "gimp_inspect_item", item=copy["id"])
        status = await call(client, "gimp_status")
        await call(client, "gimp_close_image", image=image, discard_changes=True)

    assert tree(final) == [
        ("Blue", "layer", []),
        ("Scene", "group", [("Props", "group", [("Red", "layer", []), ("sticker.png", "layer", [])])]),
        ("Background", "layer", []),
    ]
    assert gone["code"] == "NOT_FOUND"
    # the preview reflects the modifications: hidden group, multiplied blue over white
    assert rgba(after, 25, 10) == (255, 255, 255, 255)
    assert rgba(after, 50, 25)[1] < 200  # sticker hidden with its group
    r, g, b, _ = rgba(after, 75, 10)
    # 50% multiply of blue over white. GIMP blends in linear light: 0.5 linear is 188 in sRGB.
    assert b == 255 and 182 <= r <= 194 and 182 <= g <= 194
    assert next(i for i in status["images"] if i["id"] == image)["dirty"] is True


async def test_invalid_targets_are_explicit(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        a = (await call(client, "gimp_create_image", width=10, height=10))["id"]
        b = (await call(client, "gimp_create_image", width=10, height=10))["id"]
        group_a = await call(client, "gimp_create_group", image=a, name="G")
        layer_a = await call(client, "gimp_create_layer", image=a, name="L", parent=group_a["id"])
        background_b = (await call(client, "gimp_inspect_image", image=b))["layers"][0]

        wrong_image = await error(client, "gimp_create_layer", image=b, name="X", parent=group_a["id"])
        not_a_group = await error(client, "gimp_create_layer", image=a, name="X", parent=layer_a["id"])
        cross_move = await error(client, "gimp_move_layer", item=background_b["id"], parent=group_a["id"], position=0)
        into_itself = await error(client, "gimp_move_layer", item=group_a["id"], parent=group_a["id"], position=0)
        too_far = await error(client, "gimp_move_layer", item=layer_a["id"], parent=None, position=7)
        bad_mode = await error(client, "gimp_set_layer_properties", item=layer_a["id"], mode="sparkly")
        await call(client, "gimp_delete_layer", item=layer_a["id"])
        stale = await error(client, "gimp_set_layer_properties", item=layer_a["id"], name="again")
        for image in (a, b):
            await call(client, "gimp_close_image", image=image, discard_changes=True)

    assert wrong_image["code"] == "IMAGE_MISMATCH"
    assert not_a_group["code"] == "WRONG_KIND"
    assert cross_move["code"] == "IMAGE_MISMATCH"
    assert into_itself["code"] == "INVALID_ARGUMENT"
    assert too_far["code"] == "INVALID_ARGUMENT"
    assert bad_mode["code"] == "INVALID_ARGUMENT" and "multiply" in bad_mode["details"]["allowed"]
    assert stale["code"] == "NOT_FOUND"
    for err in (wrong_image, not_a_group, cross_move, into_itself, too_far, bad_mode, stale):
        assert err["outcome"] == "not_applied"


@pytest.mark.parametrize("missing", ["missing.png"])
async def test_import_errors(gimp: HeadlessGimp, tmp_path: Path, missing: str):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=10, height=10))["id"]
        err = await error(client, "gimp_import_layer", image=image, path=str(tmp_path / missing))
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert err["code"] == "FILE_NOT_FOUND"

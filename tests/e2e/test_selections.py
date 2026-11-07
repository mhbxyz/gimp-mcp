from __future__ import annotations

from pathlib import Path

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, find, preview, rgba


async def test_selections_combine_invert_and_clear(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=100, height=60))["id"]
        empty = await call(client, "gimp_get_selection", image=image)
        assert empty["empty"] is True and empty["bounds"] is None

        rect = await call(client, "gimp_select_rectangle", image=image, x=10, y=10, width=30, height=20)
        assert rect["bounds"] == {"x": 10, "y": 10, "width": 30, "height": 20}
        dirty_after_selecting = (await call(client, "gimp_inspect_image", image=image))["dirty"]
        union = await call(client, "gimp_select_ellipse", image=image, x=50, y=30, width=40, height=20, operation="add")
        assert union["bounds"] == {"x": 10, "y": 10, "width": 80, "height": 40}
        cut = await call(
            client, "gimp_select_rectangle", image=image, x=0, y=0, width=45, height=60, operation="subtract"
        )
        assert cut["bounds"] == {"x": 50, "y": 30, "width": 40, "height": 20}
        inverted = await call(client, "gimp_modify_selection", image=image, action="invert")
        assert inverted["bounds"] == {"x": 0, "y": 0, "width": 100, "height": 60}
        assert inverted["contains"] is None  # no probe point requested
        probe = await call(client, "gimp_get_selection", image=image, probe_x=70, probe_y=40)
        assert probe["contains"] is False  # center of the ellipse is now outside
        cleared = await call(client, "gimp_modify_selection", image=image, action="none")
        assert cleared["empty"] is True
        clipped = await call(client, "gimp_select_rectangle", image=image, x=-10, y=-10, width=30, height=30)
        assert clipped["bounds"] == {"x": 0, "y": 0, "width": 20, "height": 20}  # clipped to the canvas
        outside = await call(client, "gimp_select_rectangle", image=image, x=500, y=500, width=5, height=5)
        assert outside["empty"] is True
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert dirty_after_selecting is True  # selections are undoable changes: GIMP marks the image dirty


async def test_mask_from_selection_is_visible_and_persists_in_xcf(gimp: HeadlessGimp, tmp_path: Path):
    project = tmp_path / "masked.xcf"
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=60, height=40, fill="white"))["id"]
        red = await call(client, "gimp_create_layer", image=image, name="Red", fill="#ff0000")
        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=30, height=40)
        mask = await call(client, "gimp_add_layer_mask", item=red["id"], fill="selection")
        assert mask["mask"]["apply"] is True
        shot = await preview(client, image)
        assert rgba(shot, 10, 20)[:3] == (255, 0, 0)  # inside the selection: red shows
        assert rgba(shot, 50, 20)[:3] == (255, 255, 255)  # masked out: background shows

        disabled = await call(client, "gimp_set_layer_mask", item=red["id"], apply=False)
        assert disabled["mask"]["apply"] is False
        assert rgba(await preview(client, image), 50, 20)[:3] == (255, 0, 0)
        await call(client, "gimp_set_layer_mask", item=red["id"], apply=True)

        await call(client, "gimp_save_image", image=image, path=str(project))
        await call(client, "gimp_close_image", image=image)
        reopened = (await call(client, "gimp_open_image", path=str(project)))["id"]
        tree = await call(client, "gimp_inspect_image", image=reopened)
        again = await preview(client, reopened)
        await call(client, "gimp_close_image", image=reopened)
    layer = find(tree, "Red")
    assert layer["mask"] is not None and layer["mask"]["apply"] is True
    assert rgba(again, 10, 20)[:3] == (255, 0, 0) and rgba(again, 50, 20)[:3] == (255, 255, 255)


async def test_removing_a_mask_applies_or_discards_it_explicitly(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=20, height=10, fill="white"))["id"]
        applied = await call(client, "gimp_create_layer", image=image, name="Applied", fill="#0000ff")
        discarded = await call(
            client, "gimp_create_layer", image=image, name="Discarded", fill="#00ff00", visible=False
        )
        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=10, height=10)
        for layer in (applied, discarded):
            await call(client, "gimp_add_layer_mask", item=layer["id"], fill="selection")
        await call(client, "gimp_modify_selection", image=image, action="none")
        no_mask_twice = await error(client, "gimp_add_layer_mask", item=applied["id"], fill="white")
        after_apply = await call(client, "gimp_remove_layer_mask", item=applied["id"], mode="apply")
        after_discard = await call(client, "gimp_remove_layer_mask", item=discarded["id"], mode="discard")
        none_left = await error(client, "gimp_remove_layer_mask", item=applied["id"], mode="apply")
        await call(client, "gimp_set_layer_properties", item=applied["id"], visible=False)
        await call(client, "gimp_set_layer_properties", item=discarded["id"], visible=True)
        shot_discarded = await preview(client, image)
        await call(client, "gimp_set_layer_properties", item=discarded["id"], visible=False)
        await call(client, "gimp_set_layer_properties", item=applied["id"], visible=True)
        shot_applied = await preview(client, image)
        empty_mask = await error(client, "gimp_add_layer_mask", item=discarded["id"], fill="selection")
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert no_mask_twice["code"] == "INVALID_ARGUMENT"
    assert after_apply["mask"] is None and after_discard["mask"] is None
    assert none_left["code"] == "INVALID_ARGUMENT"
    assert rgba(shot_discarded, 15, 5)[:3] == (0, 255, 0)  # discard: the mask had no effect on pixels
    assert rgba(shot_applied, 5, 5)[:3] == (0, 0, 255)
    assert rgba(shot_applied, 15, 5)[:3] == (255, 255, 255)  # apply: masked pixels became transparent
    assert empty_mask["code"] == "EMPTY_SELECTION"

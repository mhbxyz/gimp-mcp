from __future__ import annotations

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, preview, rgba


async def scene(client):
    """60x40 white image, a transparent 'Ink' layer on top of a blue 'Base' strip (y 30..40)."""
    image = (await call(client, "gimp_create_image", width=60, height=40, fill="white"))["id"]
    base = await call(client, "gimp_create_layer", image=image, name="Base", width=60, height=10, y=30, fill="#0000ff")
    ink = await call(client, "gimp_create_layer", image=image, name="Ink")
    return image, base["id"], ink["id"]


async def test_fill_selection_and_whole_layer_with_explicit_parameters(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, base, ink = await scene(client)
        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=20, height=20)
        filled = await call(client, "gimp_fill", item=ink, color="#ff0000", area="selection")
        assert filled["changed"] is True and filled["affected"] == {"x": 0, "y": 0, "width": 20, "height": 20}
        shot = await preview(client, image)
        assert rgba(shot, 10, 10)[:3] == (255, 0, 0) and rgba(shot, 30, 10)[:3] == (255, 255, 255)

        half = await call(client, "gimp_fill", item=base, color="#ff0000", area="layer", opacity=50)
        selection = await call(client, "gimp_get_selection", image=image)
        shot = await preview(client, image)
        assert half["affected"] == {"x": 0, "y": 30, "width": 60, "height": 10}
        r, g, b, _ = rgba(shot, 50, 35)
        assert r > 150 and g < 10 and b > 150  # 50% red over blue, whole layer despite the selection
        assert selection["bounds"] == {"x": 0, "y": 0, "width": 20, "height": 20}  # selection preserved

        await call(client, "gimp_modify_selection", image=image, action="none")
        empty = await error(client, "gimp_fill", item=ink, color="#00ff00", area="selection")
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert empty["code"] == "EMPTY_SELECTION"


async def test_stroke_a_path_only_changes_the_target_layer(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, _base, ink = await scene(client)
        stroke = await call(
            client,
            "gimp_draw_path",
            item=ink,
            points=[[5, 10], [55, 10]],
            width=4,
            color="#00ff00",
            antialias=False,
        )
        assert stroke["changed"] is True
        shot = await preview(client, image)
        assert rgba(shot, 30, 10)[:3] == (0, 255, 0)  # on the line
        assert rgba(shot, 30, 13)[:3] == (255, 255, 255)  # 4 px wide: y 8..11
        assert rgba(shot, 30, 35)[:3] == (0, 0, 255)

        await call(
            client,
            "gimp_draw_path",
            item=ink,
            points=[[5, 20], [25, 20], [25, 28]],
            width=2,
            color="#000000",
            opacity=100,
        )
        await call(client, "gimp_set_layer_properties", item=ink, visible=False)
        without_ink = await preview(client, image)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    # the other layers did not receive any paint
    assert rgba(without_ink, 30, 10)[:3] == (255, 255, 255)
    assert rgba(without_ink, 25, 24)[:3] == (255, 255, 255)
    assert rgba(without_ink, 30, 35)[:3] == (0, 0, 255)


async def test_shapes_out_of_bounds_and_refusals(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, _base, ink = await scene(client)
        rect = await call(
            client,
            "gimp_draw_shape",
            item=ink,
            shape="rectangle",
            x=40,
            y=0,
            width=10,
            height=10,
            fill_color="#ffff00",
            stroke_color="#000000",
            stroke_width=2,
        )
        shot = await preview(client, image)
        assert rgba(shot, 45, 5)[:3] == (255, 255, 0) and rgba(shot, 40, 5)[:3] == (0, 0, 0)
        assert rect["changed"] is True

        outside = await call(
            client, "gimp_draw_path", item=ink, points=[[500, 500], [600, 600]], width=3, color="#000000"
        )
        assert outside["changed"] is False and outside["affected"] is None

        group = await call(client, "gimp_create_group", image=image, name="G")
        on_group = await error(client, "gimp_fill", item=group["id"], color="#000000", area="layer")
        await call(client, "gimp_set_layer_properties", item=ink, lock_content=True)
        locked = await error(client, "gimp_draw_path", item=ink, points=[[0, 0], [10, 10]], color="#000000")
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert on_group["code"] == "WRONG_KIND"
    assert locked["code"] == "LOCKED" and locked["outcome"] == "not_applied"

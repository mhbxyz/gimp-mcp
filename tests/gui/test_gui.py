"""GIMP with its interface open (#105): the user and the agent work on the same images.

Each test starts its own GIMP window on a fresh profile, opens a known image as a user would (from the
command line, so it has a display), and checks pixels through MCP (sampled or previewed: the
projection is what the display shows).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from tests.e2e.conftest import mcp_client
from tests.e2e.helpers import call, error

from .conftest import press

RED, BLUE = (255, 0, 0), (0, 0, 255)


def picture(path: Path, color: tuple[int, int, int] = BLUE) -> Path:
    Image.new("RGB", (200, 120), color).save(path)
    return path


async def pixel(client, item: str, x: int = 100, y: int = 60) -> tuple[int, ...]:
    sample = (await call(client, "gimp_sample_colors", target=item, points=[[x, y]]))["samples"][0]
    return tuple(sample["rgba"][:3])


async def first_image(client) -> tuple[str, str]:
    images = (await call(client, "gimp_status"))["images"]
    assert len(images) == 1, images
    image = images[0]["id"]
    layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    return image, layer


async def test_an_image_opened_by_the_user_is_listed_with_its_display_and_editable(gui_gimp, tmp_path):
    gimp = gui_gimp([picture(tmp_path / "user.png")])
    async with mcp_client(gimp) as client:
        status = await call(client, "gimp_status")
        assert [Path(i["file"]).name for i in status["images"]] == ["user.png"]  # opened by the user, listed
        image, layer = await first_image(client)
        await call(client, "gimp_fill", item=layer, color="#ff0000", area="layer")
        assert await pixel(client, layer) == RED
        # the display shows the projection: the preview reads it
        preview = await client.call_tool("gimp_preview", {"image": image, "max_size": 100})
        assert not preview.is_error
        created = await call(client, "gimp_create_image", width=64, height=64, fill="#00ff00")
        assert created["displayed"] is True  # "In a GUI session the image is shown in a new window"


async def test_one_call_is_one_undo_step_and_gimp_undo_restores_the_pixels(gui_gimp, tmp_path):
    gimp = gui_gimp([picture(tmp_path / "undo.png")])
    async with mcp_client(gimp) as client:
        _, layer = await first_image(client)
        await call(client, "gimp_draw_shape", item=layer, shape="rectangle", x=40, y=20, width=120, height=80,
                    fill_color="#ff0000", stroke_color="#00ff00", stroke_width=6)  # fmt: skip
        assert await pixel(client, layer) == RED
        press(gimp, "ctrl+z")  # the user's Edit > Undo, once
        assert await pixel(client, layer) == BLUE
        assert await pixel(client, layer, 40, 20) == BLUE  # the stroke too: the whole call was one step


async def test_user_edits_between_calls_keep_ids_and_checkpoints(gui_gimp, tmp_path):
    gimp = gui_gimp([picture(tmp_path / "edit.png")])
    async with mcp_client(gimp) as client:
        image, layer = await first_image(client)
        checkpoint = (await call(client, "gimp_create_checkpoint", image=image, label="before the user"))["checkpoint"]
        press(gimp, "ctrl+a")  # the user selects all and clears the layer
        press(gimp, "Delete")
        assert await pixel(client, layer) != BLUE  # the user's edit happened
        assert (await call(client, "gimp_inspect_item", item=layer))["id"] == layer  # same id
        restored = await call(client, "gimp_restore_checkpoint", image=image, checkpoint=checkpoint)
        layer = (await call(client, "gimp_inspect_image", image=restored["image"]))["layers"][0]["id"]
        assert await pixel(client, layer) == BLUE


async def test_an_image_closed_by_the_user_gives_a_clear_error(gui_gimp, tmp_path):
    gimp = gui_gimp([picture(tmp_path / "close.png")])
    async with mcp_client(gimp) as client:
        image, _ = await first_image(client)
        press(gimp, "ctrl+w")  # no unsaved change: GIMP closes it without asking
        refused = await error(client, "gimp_inspect_image", image=image)
        assert refused["code"] == "NOT_FOUND" and "closed" in refused["message"], refused
        assert (await call(client, "gimp_status"))["images"] == []


async def test_quitting_gimp_from_its_interface_then_starting_it_again(gui_gimp, tmp_path):
    gimp = gui_gimp([picture(tmp_path / "quit.png")])
    async with mcp_client(gimp) as client:
        await call(client, "gimp_status")
        press(gimp, "ctrl+q")  # nothing unsaved: GIMP quits
        assert gimp.process is not None
        gimp.process.wait(timeout=60)
        gone = await error(client, "gimp_status")
        assert gone["code"] in ("BRIDGE_UNAVAILABLE", "GIMP_NOT_RUNNING"), gone
        gimp.open_files = []
        gimp.start()  # the user starts GIMP again: same profile and bridge address
        status = await call(client, "gimp_status")  # the same MCP session recovers
        assert status["connected"] is True and status["images"] == []

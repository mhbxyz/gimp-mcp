"""Issue #9: undo groups and checkpoints (the agent's undo/redo)."""

from __future__ import annotations

from pathlib import Path

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, preview, rgba, tree


async def test_undo_group_is_closed_explicitly_after_errors_and_on_disconnect(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=20, height=20))["id"]
        opened = await call(client, "gimp_begin_undo_group", image=image, label="Two layers")
        assert opened["depth"] == 1
        await call(client, "gimp_create_layer", image=image, name="A")
        failed = await error(client, "gimp_create_layer", image=image, name="B", position=99)  # error inside
        await call(client, "gimp_create_layer", image=image, name="C")
        closed = await call(client, "gimp_end_undo_group", image=image)
        assert closed["depth"] == 0
        not_open = await error(client, "gimp_end_undo_group", image=image)
        await call(client, "gimp_begin_undo_group", image=image)  # left open: the client goes away
    assert failed["code"] == "INVALID_ARGUMENT"
    assert not_open["code"] == "NO_OPEN_GROUP"
    async with mcp_client(gimp) as client:
        # the bridge closed the abandoned group when the first client disconnected
        abandoned = await error(client, "gimp_end_undo_group", image=image)
        assert abandoned["code"] == "NO_OPEN_GROUP"
        reopened = await call(client, "gimp_begin_undo_group", image=image)
        assert reopened["depth"] == 1
        await call(client, "gimp_end_undo_group", image=image)
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_checkpoints_undo_and_redo_a_series_of_changes(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=40, height=20, fill="#ff0000"))["id"]
        before = await call(client, "gimp_create_checkpoint", image=image, label="red")
        layer = await call(client, "gimp_create_layer", image=image, name="Blue", fill="#0000ff")
        await call(client, "gimp_create_text_layer", image=image, text="Hi", size=10)
        after = await call(client, "gimp_create_checkpoint", image=image, label="blue + text")
        listed = await call(client, "gimp_list_checkpoints", image=image)
        assert [c["label"] for c in listed["checkpoints"]] == ["red", "blue + text"]
        status = await call(client, "gimp_status")
        assert [i["id"] for i in status["images"]] == [image]  # checkpoint copies stay hidden

        undone = await call(client, "gimp_restore_checkpoint", image=image, checkpoint=before["checkpoint"])
        restored = undone["image"]
        assert restored != image and undone["previous_image"] == image
        assert rgba(await preview(client, restored), 5, 5)[:3] == (255, 0, 0)
        assert tree(await call(client, "gimp_inspect_image", image=restored)) == [("Background", "layer", [])]
        gone = await error(client, "gimp_inspect_image", image=image)
        stale_layer = await error(client, "gimp_inspect_item", item=layer["id"])

        redone = await call(client, "gimp_restore_checkpoint", image=restored, checkpoint=after["checkpoint"])
        final = redone["image"]
        final_tree = tree(await call(client, "gimp_inspect_image", image=final))
        blue = rgba(await preview(client, final), 30, 15)  # away from the "Hi" text
        still = await call(client, "gimp_list_checkpoints", image=final)
        await call(client, "gimp_delete_checkpoint", checkpoint=before["checkpoint"])
        remaining = await call(client, "gimp_list_checkpoints", image=final)
        await call(client, "gimp_close_image", image=final, discard_changes=True)
        foreign = await error(client, "gimp_list_checkpoints", image=final)
    assert gone["code"] == "NOT_FOUND" and stale_layer["code"] == "NOT_FOUND"
    assert final_tree == [("Hi", "text", []), ("Blue", "layer", []), ("Background", "layer", [])]
    assert blue[:3] == (0, 0, 255)
    assert len(still["checkpoints"]) == 2 and len(remaining["checkpoints"]) == 1
    assert foreign["code"] == "NOT_FOUND"


async def test_restoring_keeps_the_file_association_and_reports_unsaved_changes(gimp: HeadlessGimp, tmp_path: Path):
    project = tmp_path / "keep.xcf"
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=10, height=10))["id"]
        await call(client, "gimp_save_image", image=image, path=str(project))
        checkpoint = await call(client, "gimp_create_checkpoint", image=image)
        await call(client, "gimp_create_layer", image=image, name="Extra")
        restored = await call(client, "gimp_restore_checkpoint", image=image, checkpoint=checkpoint["checkpoint"])
        details = await call(client, "gimp_inspect_image", image=restored["image"])
        await call(client, "gimp_close_image", image=restored["image"], discard_changes=True)
    assert details["xcf_file"] == str(project)
    assert details["dirty"] is True
    assert tree(details) == [("Background", "layer", [])]

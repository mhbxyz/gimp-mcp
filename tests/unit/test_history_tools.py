from __future__ import annotations

from gmb_server import BridgeError  # type: ignore[import-not-found]

from .tool_harness import error_code, iid, tool_client

REF = {"id": 5, "name": "x", "file": None, "xcf_file": None, "width": 4, "height": 4, "dirty": True,
       "layer_count": 1, "displayed": False}  # fmt: skip


async def test_restore_reports_the_new_and_previous_image_ids():
    async with tool_client({"checkpoint.restore": lambda p: REF}) as (client, bridge):
        result = await client.call_tool(
            "gimp_restore_checkpoint", {"image": iid(1), "checkpoint": "checkpoint:2@a1b2c3d4"}
        )
    assert result.structured_content is not None
    assert result.structured_content["image"] == iid(5)
    assert result.structured_content["previous_image"] == iid(1)
    assert bridge.calls[0][1] == {"image": 1, "checkpoint": 2}


async def test_checkpoint_ids_are_checked_before_reaching_gimp():
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_restore_checkpoint", {"image": iid(1), "checkpoint": iid(2)})
    assert error_code(result) == "INVALID_ID"
    assert bridge.calls == []


async def test_ending_without_an_open_group_is_explicit():
    def no_group(params):
        raise BridgeError("NO_OPEN_GROUP", "no undo group opened by this client on image 1")

    async with tool_client({"undo.end": no_group}) as (client, _):
        result = await client.call_tool("gimp_end_undo_group", {"image": iid(1)})
    assert error_code(result) == "NO_OPEN_GROUP"

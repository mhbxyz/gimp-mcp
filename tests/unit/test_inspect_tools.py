from __future__ import annotations

from gmb_server import BridgeError  # type: ignore[import-not-found]

from .tool_harness import error_code, iid, tid, tool_client


def layer(n: int, name: str, kind: str = "layer", children=None, mask=None, parent=None) -> dict:
    node = {
        "id": n,
        "name": name,
        "kind": kind,
        "parent": parent,
        "visible": True,
        "opacity": 100.0,
        "mode": "normal",
        "x": 0,
        "y": 0,
        "width": 10,
        "height": 10,
        "has_alpha": True,
        "locks": {"content": False, "position": False, "visibility": False, "alpha": False},
        "mask": mask,
    }
    if kind == "group":
        node["children"] = children or []
    return node


MASK = {"id": 9, "apply": True, "show": False, "edit": False}

IMAGE = {
    "id": 3,
    "name": "poster.xcf",
    "file": "/x/poster.xcf",
    "xcf_file": "/x/poster.xcf",
    "imported_file": None,
    "exported_file": None,
    "width": 120,
    "height": 80,
    "base_type": "rgb",
    "precision": "u8-non-linear",
    "resolution": {"x": 72.0, "y": 72.0},
    "dirty": False,
    "layers": [
        layer(
            5,
            "Outer",
            "group",
            children=[layer(6, "Title", mask={"id": 9, "apply": True, "show": False, "edit": False}, parent=5)],
        ),
        layer(2, "Background"),
    ],
}


async def test_inspect_image_encodes_every_nested_id():
    async with tool_client({"image.inspect": lambda p: IMAGE}) as (client, bridge):
        result = await client.call_tool("gimp_inspect_image", {"image": iid(3)})
    assert not result.is_error, result.content
    data = result.structured_content
    assert data is not None
    assert data["id"] == iid(3)
    outer = data["layers"][0]
    assert outer["id"] == tid(5)
    title = outer["children"][0]
    assert (title["id"], title["parent"], title["mask"]["id"]) == (tid(6), tid(5), tid(9))
    assert data["layers"][1]["parent"] is None
    assert bridge.calls == [("image.inspect", {"image": 3})]


async def test_malformed_id_is_rejected_without_reaching_gimp():
    async with tool_client({"image.inspect": lambda p: IMAGE}) as (client, bridge):
        result = await client.call_tool("gimp_inspect_image", {"image": tid(3)})
    assert error_code(result) == "INVALID_ID"
    assert bridge.calls == []


async def test_deleted_object_is_reported_as_not_found():
    def gone(params):
        raise BridgeError("NOT_FOUND", "item 6 does not exist (deleted?)", {"item": params["item"]})

    async with tool_client({"item.inspect": gone}) as (client, _):
        result = await client.call_tool("gimp_inspect_item", {"item": tid(6)})
    assert error_code(result) == "NOT_FOUND"


async def test_inspect_item_reports_kind_parent_image_and_position():
    item = {**layer(6, "Title", parent=5), "image": 3, "position": 0}
    async with tool_client({"item.inspect": lambda p: item}) as (client, _):
        result = await client.call_tool("gimp_inspect_item", {"item": tid(6)})
    data = result.structured_content
    assert data is not None
    assert (data["id"], data["image"], data["parent"], data["position"]) == (tid(6), iid(3), tid(5), 0)

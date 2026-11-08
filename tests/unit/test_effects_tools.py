"""GEGL catalog tools (#47), MCP side: ids, arguments and results."""

from __future__ import annotations

from gmb_server import BridgeError  # type: ignore[import-not-found]

from .tool_harness import SESSION, error_code, tid, tool_client

STATE = {"id": 7, "name": "Sharpen", "operation": "gegl:unsharp-mask", "visible": True, "opacity": 100.0,
         "mode": "normal", "parameters": {"std-dev": 3.0, "scale": 0.5, "threshold": 0.0}}  # fmt: skip


def fid(n: int) -> str:
    return f"filter:{n}@{SESSION}"


async def test_apply_passes_parameters_and_returns_an_encoded_filter_id():
    applied = {"filter": STATE, "destructive": False, "restricted_to_selection": False}
    async with tool_client({"filter.apply_any": lambda p: applied}) as (client, bridge):
        result = await client.call_tool(
            "gimp_apply_filter",
            {"item": tid(3), "operation": "gegl:unsharp-mask", "parameters": {"std-dev": 3, "scale": 0.5},
             "opacity": 80, "mode": "screen"},
        )  # fmt: skip
        assert not result.is_error, result.content
        assert result.structured_content["filter"]["id"] == fid(7)
        params = bridge.calls[0][1]
        assert params["item"] == 3 and params["parameters"] == {"std-dev": 3, "scale": 0.5}
        assert params["opacity"] == 80 and params["mode"] == "screen" and params["destructive"] is False


async def test_destructive_apply_has_no_filter_id():
    applied = {"filter": {**STATE, "id": None}, "destructive": True, "restricted_to_selection": True}
    async with tool_client({"filter.apply_any": lambda p: applied}) as (client, _bridge):
        result = await client.call_tool(
            "gimp_apply_filter", {"item": tid(3), "operation": "gegl:pixelize", "destructive": True}
        )
        assert result.structured_content["filter"]["id"] is None


async def test_bridge_refusals_reach_the_client_unchanged():
    def refuse(params):
        raise BridgeError("UNSUPPORTED", "gegl:gluas cannot be applied: denied")

    async with tool_client({"filter.apply_any": refuse}) as (client, _bridge):
        result = await client.call_tool("gimp_apply_filter", {"item": tid(3), "operation": "gegl:gluas"})
        assert error_code(result) == "UNSUPPORTED"


async def test_inspect_set_move_and_merge_encode_ids():
    ops = {
        "filter.inspect": lambda p: STATE,
        "filter.set": lambda p: {**STATE, "visible": False},
        "filter.reorder": lambda p: {
            "filters": [{"id": 9, "name": "a", "operation": "gegl:pixelize", "visible": True, "opacity": 100.0}],
            "recreated": {"7": 9},
        },
        "filter.merge": lambda p: {"merged": 2, "filters": []},
    }
    async with tool_client(ops) as (client, bridge):
        inspected = await client.call_tool("gimp_inspect_filter", {"item": tid(3), "filter": fid(7)})
        assert inspected.structured_content["parameters"]["std-dev"] == 3.0
        assert bridge.calls[0][1]["filter"] == 7
        changed = await client.call_tool("gimp_set_filter", {"item": tid(3), "filter": fid(7), "visible": False})
        assert changed.structured_content["visible"] is False
        assert bridge.calls[1][1]["parameters"] == {} and bridge.calls[1][1]["opacity"] is None
        moved = await client.call_tool("gimp_move_filter", {"item": tid(3), "filter": fid(7), "position": 0})
        assert moved.structured_content["recreated"] == {fid(7): fid(9)}
        merged = await client.call_tool("gimp_merge_filters", {"item": tid(3), "up_to": fid(7)})
        assert merged.structured_content["merged"] == 2 and bridge.calls[3][1]["up_to"] == 7
        bad = await client.call_tool("gimp_inspect_filter", {"item": tid(3), "filter": tid(7)})
        assert error_code(bad) == "INVALID_ID"


async def test_catalog_tools_and_annotations():
    ops = {
        "filter.operations": lambda p: {"operations": [{"name": "gegl:pixelize", "title": "Pixelize",
                                                        "categories": ["blur"], "supported": True, "reason": None}]},
        "filter.describe": lambda p: {"name": "gegl:pixelize", "title": "Pixelize", "categories": ["blur"],
                                      "supported": True, "reason": None, "description": "Blocks",
                                      "parameters": [{"name": "size-x", "kind": "integer", "min": 1, "max": 9,
                                                      "default": 16, "description": "Width"}]},
    }  # fmt: skip
    async with tool_client(ops) as (client, bridge):
        listed = await client.call_tool("gimp_list_filter_operations", {"category": "blur"})
        assert listed.structured_content["operations"][0]["name"] == "gegl:pixelize"
        assert bridge.calls[0][1] == {"query": "", "category": "blur"}
        described = await client.call_tool("gimp_describe_filter_operation", {"operation": "gegl:pixelize"})
        assert described.structured_content["parameters"][0]["kind"] == "integer"
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    merge = tools["gimp_merge_filters"].annotations
    assert merge is not None and merge.destructive_hint
    listing = tools["gimp_list_filter_operations"].annotations
    assert listing is not None and listing.read_only_hint

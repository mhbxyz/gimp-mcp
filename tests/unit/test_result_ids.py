"""Every tool that creates or changes an image or item names it in a top-level `id` (#164,
docs/api-conventions.md, Results)."""

from __future__ import annotations

import anyio
from mcp import Client

from gimp_mcp.server import build_server

from .tool_harness import iid, tid, tool_client

# Tools without `id`, and why (also listed in docs/api/review.md).
EXEMPT = {
    # several objects or none
    "gimp_enable_toolsets", "gimp_call_procedure", "gimp_align_layers", "gimp_export_layers",
    "gimp_import_svg_paths", "gimp_run_batch", "gimp_begin_undo_group", "gimp_end_undo_group",
    # file writes and deletions: the result names the file or the deleted object
    "gimp_save_image", "gimp_export_image", "gimp_export_as", "gimp_export_region", "gimp_export_animation",
    "gimp_export_path_svg",
    "gimp_close_image", "gimp_delete_layer", "gimp_delete_path", "gimp_delete_channel",
    # objects that are not images or items
    "gimp_add_guide", "gimp_add_sample_point", "gimp_remove_guide", "gimp_copy", "gimp_create_checkpoint",
    "gimp_delete_checkpoint", "gimp_create_resource", "gimp_duplicate_resource", "gimp_rename_resource",
    "gimp_delete_resource", "gimp_edit_brush", "gimp_edit_gradient", "gimp_edit_palette", "gimp_import_palette",
    "gimp_export_palette",
}  # fmt: skip


def definitions() -> list:
    async def run() -> list:
        async with Client(build_server(toolsets="all", env={})) as client:
            return (await client.list_tools()).tools

    return anyio.run(run)


def test_every_tool_that_changes_an_image_or_item_returns_its_id():
    missing = []
    for tool in definitions():
        if (tool.annotations and tool.annotations.read_only_hint) or tool.name in EXEMPT:
            continue
        if "id" not in (tool.output_schema or {}).get("properties", {}):
            missing.append(tool.name)
    assert missing == []


def test_no_exemption_is_stale():
    names = {tool.name for tool in definitions()}
    assert names >= EXEMPT


GEOMETRY = {"width": 10, "height": 5, "dirty": True}
LAYER = {"id": 7, "name": "Merged", "kind": "layer", "x": 0, "y": 0, "width": 1, "height": 1, "opacity": 100.0,
         "mode": "normal", "visible": True, "has_alpha": True, "locks": {"content": False, "position": False,
         "visibility": False, "alpha": False}, "parent": None, "mask": None, "children": [], "image": 1}  # fmt: skip


async def test_the_id_is_the_changed_image_the_created_layer_or_the_changed_item():
    ops = {
        "image.scale": lambda p: GEOMETRY,
        "layers.merge": lambda p: {"image": {"id": 1}, "layer": LAYER},
        "paint.fill": lambda p: {"changed": True, "affected": None},
    }
    async with tool_client(ops) as (client, _bridge):
        resized = await client.call_tool("gimp_resize_image", {"image": iid(1), "width": 10, "height": 5})
        merged = await client.call_tool("gimp_merge_layers", {"mode": "visible", "image": iid(1)})
        filled = await client.call_tool("gimp_fill", {"item": tid(3), "color": "red"})
    assert resized.structured_content["id"] == iid(1)
    assert merged.structured_content["id"] == tid(7), merged.content
    assert filled.structured_content["id"] == tid(3), filled.content

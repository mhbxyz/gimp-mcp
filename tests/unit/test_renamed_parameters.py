"""The API review's renames (#119): new names work, old names still work with a deprecation notice."""

from __future__ import annotations

from typing import Any

import pytest

from .tool_harness import iid, tid, tool_client

NOTICES = "io.github.mhbxyz/deprecations"
CHANNEL = {"id": 5, "name": "Saved", "color": "#ff0000", "opacity": 50.0, "visible": False, "show_masked": False,
           "image": 1}  # fmt: skip
GUIDES = {"image": 1, "guides": [], "sample_points": []}


def ops() -> dict[str, Any]:
    return {
        "channel.set": lambda p: CHANNEL,
        "channel.combine": lambda p: CHANNEL,
        "channel.delete": lambda p: {"deleted": p["channel"]},
        "guide.remove": lambda p: GUIDES,
    }


def notices(result: Any) -> list[str]:
    return [notice["name"] for notice in (result.meta or {}).get(NOTICES, [])]


@pytest.mark.parametrize(
    ("tool", "new", "old", "sent", "wire"),
    [
        ("gimp_set_channel", {"channel": tid(5)}, {"channel_id": tid(5)}, ("channel.set", "channel"), 5),
        ("gimp_delete_channel", {"channel": tid(5)}, {"channel_id": tid(5)}, ("channel.delete", "channel"), 5),
        ("gimp_combine_channels", {"channel": tid(5), "other": tid(6)}, {"channel_id": tid(5), "other": tid(6)},
         ("channel.combine", "channel"), 5),
        ("gimp_remove_guide", {"image": iid(1), "guide": 3}, {"image": iid(1), "id": 3}, ("guide.remove", "id"), 3),
    ],
)  # fmt: skip
async def test_new_and_deprecated_names_do_the_same(tool, new, old, sent, wire):
    async with tool_client(ops()) as (client, bridge):
        with_new = await client.call_tool(tool, new)
        with_old = await client.call_tool(tool, old)
    assert not with_new.is_error and not with_old.is_error, (with_new.content, with_old.content)
    method, key = sent
    assert [params[key] for name, params in bridge.calls if name == method] == [wire, wire]
    assert notices(with_new) == []
    [old_name] = [name for name in old if name not in new]
    assert notices(with_old) == [f"{tool}.{old_name}"]


async def test_the_old_sample_point_spelling_still_works_with_a_notice():
    async with tool_client(ops()) as (client, bridge):
        new = await client.call_tool("gimp_remove_guide", {"image": iid(1), "guide": 2, "kind": "sample-point"})
        old = await client.call_tool("gimp_remove_guide", {"image": iid(1), "guide": 2, "kind": "sample_point"})
    assert [params["kind"] for _name, params in bridge.calls] == ["sample_point", "sample_point"]
    assert notices(new) == [] and notices(old) == ["gimp_remove_guide.kind='sample_point'"]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gimp_delete_channel", {}),
        ("gimp_delete_channel", {"channel": tid(5), "channel_id": tid(6)}),
        ("gimp_remove_guide", {"image": iid(1)}),
        ("gimp_import_palette", {}),
    ],
)
async def test_neither_or_two_different_values_are_refused(tool, arguments):
    async with tool_client(ops()) as (client, bridge):
        result = await client.call_tool(tool, arguments)
    assert result.is_error and result.structured_content["error"]["code"] == "INVALID_ARGUMENT"
    assert bridge.calls == []


async def test_file_parameters_are_path_now(tmp_path):
    palette = tmp_path / "p.gpl"
    palette.write_text("GIMP Palette\nName: P\n#\n255 0 0 red\n")
    details = {"kind": "palette", "name": "P", "editable": True, "generated": False, "entries": []}
    async with tool_client({"palette.import": lambda p: details}) as (client, bridge):
        new = await client.call_tool("gimp_import_palette", {"path": str(palette)})
        old = await client.call_tool("gimp_import_palette", {"file": str(palette)})
    assert [params["file"] for _name, params in bridge.calls] == [str(palette)] * 2
    assert notices(new) == [] and notices(old) == ["gimp_import_palette.file"]

"""Batch processing (#61), MCP side: a recipe of tool calls run over many files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from gmb_server import BridgeError  # type: ignore[import-not-found]
from mcp import Client

from gimp_mcp.bridge import BridgeClient
from gimp_mcp.errors import GimpMcpError
from gimp_mcp.server import build_server

from .fake_bridge import running_fake_bridge
from .test_inspect_tools import layer
from .tool_harness import error_code, iid, tool_client

FLIP = {"tool": "gimp_flip_image", "arguments": {"image": "{image}", "orientation": "horizontal"}}
EXPORT = {"tool": "gimp_export_image", "arguments": {"image": "{image}", "path": "{output}"}}


def inputs(directory: Path, *names: str) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / name for name in names]
    for path in paths:
        path.write_bytes(b"x")
    return paths


class Gimp:
    """Scripted GIMP: opened files get image ids 1, 2...; flipping 'bad' files fails."""

    def __init__(self) -> None:
        self.open: dict[int, str] = {}
        self.next = 1

    def ops(self):
        return {
            "session.images": lambda p: {"images": [{"id": n} for n in self.open]},
            "image.open": self.open_image,
            "image.close": self.close,
            "image.flip": self.flip,
            "image.export": self.export,
            "image.inspect": lambda p: {"layers": [{"id": 100 + p["image"]}]},
        }

    def open_image(self, params):
        number, self.next = self.next, self.next + 1
        self.open[number] = params["path"]
        return {"id": number, "name": "x", "file": params["path"], "xcf_file": None, "width": 4, "height": 4,
                "dirty": False, "layer_count": 1, "displayed": False}  # fmt: skip

    def close(self, params):
        del self.open[params["image"]]
        return {}

    def flip(self, params):
        if "bad" in self.open[params["image"]]:
            raise BridgeError("UNSUPPORTED_FORMAT", "cannot flip this one")
        return {"width": 4, "height": 4, "dirty": True}

    def export(self, params):
        Path(params["path"]).write_bytes(b"png")
        return {"path": params["path"], "width": 4, "height": 4, "bytes": 3}


async def test_recipe_runs_on_every_file_writes_outputs_and_closes_images(tmp_path):
    a, b = inputs(tmp_path / "in", "a.png", "b.jpg")
    out = tmp_path / "out"
    out.mkdir()
    gimp = Gimp()
    async with tool_client(gimp.ops()) as (client, bridge):
        result = await client.call_tool(
            "gimp_run_batch",
            {"files": [str(a), str(b)], "recipe": [FLIP, EXPORT], "output": str(out / "{stem}-{index:02d}.png")},
        )
    report = result.structured_content
    assert not result.is_error, result.content
    assert (report["succeeded"], report["failed"], report["skipped"]) == (2, 0, 0)
    assert [f["outputs"] for f in report["files"]] == [[str(out / "a-01.png")], [str(out / "b-02.png")]]
    assert sorted(p.name for p in out.iterdir()) == ["a-01.png", "b-02.png"]
    assert gimp.open == {}  # every image the batch opened is closed
    closes = [params for name, params in bridge.calls if name == "image.close"]
    assert closes == [{"image": 1, "discard_changes": True}, {"image": 2, "discard_changes": True}]
    exports = [params["path"] for name, params in bridge.calls if name == "image.export"]
    assert exports == [str(out / "a-01.png"), str(out / "b-02.png")]


async def test_a_failure_is_reported_and_the_other_files_still_run(tmp_path):
    files = inputs(tmp_path / "in", "a.png", "bad.png", "c.png")
    out = tmp_path / "out"
    out.mkdir()
    gimp = Gimp()
    async with tool_client(gimp.ops()) as (client, _):
        result = await client.call_tool(
            "gimp_run_batch",
            {"files": [str(f) for f in files], "recipe": [FLIP, EXPORT], "output": str(out / "{name}")},
        )
        report = result.structured_content
        assert [f["status"] for f in report["files"]] == ["ok", "failed", "ok"]
        failure = report["files"][1]
        assert failure["error"]["code"] == "UNSUPPORTED_FORMAT" and failure["error"]["step"] == 0
        assert failure["error"]["tool"] == "gimp_flip_image" and failure["outputs"] == []
        assert sorted(p.name for p in out.iterdir()) == ["a.png", "c.png"]
        assert gimp.open == {}  # the failed file's image is closed too

        gimp_stop = Gimp()
        gimp.ops().update(gimp_stop.ops())
        stopped = await client.call_tool(
            "gimp_run_batch",
            {"files": [str(f) for f in files], "recipe": [FLIP], "continue_on_error": False},
        )
    assert [f["status"] for f in stopped.structured_content["files"]] == ["ok", "failed", "skipped"]
    assert stopped.structured_content["skipped"] == 1 and gimp.open == {}


async def test_placeholders_layer_and_index_are_substituted(tmp_path):
    (a,) = inputs(tmp_path / "in", "photo.png")
    seen = []

    def rename(params):
        seen.append(params)
        return layer(params["item"], params["name"])

    gimp = Gimp()
    step = {"tool": "gimp_set_layer_properties", "arguments": {"item": "{layer}", "name": "{stem}-{index:03d}.{ext}"}}
    async with tool_client({**gimp.ops(), "layer.set": rename}) as (client, _):
        result = await client.call_tool("gimp_run_batch", {"files": [str(a)], "recipe": [step]})
    assert not result.is_error, result.content
    assert seen and seen[0]["item"] == 101 and seen[0]["name"] == "photo-001.png"


async def test_invalid_recipes_are_refused_before_any_file_is_opened(tmp_path):
    (a,) = inputs(tmp_path / "in", "a.png")
    out = str(tmp_path / "{stem}.png")
    cases = [
        ([{"tool": "gimp_nope", "arguments": {}}], None),  # unknown tool
        ([{"tool": "gimp_run_batch", "arguments": {}}], None),  # no recursion
        ([{"tool": "gimp_close_image", "arguments": {"image": "{image}"}}], None),  # the batch closes images
        ([{"tool": "gimp_flip_image", "arguments": {"image": "{image}", "orientation": "sideways"}}], None),
        ([{"tool": "gimp_flip_image", "arguments": {"image": "{image}", "orientaton": "vertical"}}], None),
        ([{"tool": "gimp_flip_image", "arguments": {"image": "{img}", "orientation": "vertical"}}], None),
        ([{"tool": "gimp_flip_image", "arguments": {"image": "{image", "orientation": "vertical"}}], None),
        ([EXPORT], None),  # {output} without an output pattern
        ([FLIP], out),  # an output pattern nothing writes to
        ([{**EXPORT, "arguments": {**EXPORT["arguments"], "overwrite": True}}], out),  # overwrite is the batch's
        ([{"tool": "gimp_flip_image", "arguments": {"image": "{output}", "orientation": "vertical"}}], out),
        ([], None),
        ([{"tool": "gimp_enable_toolsets", "arguments": {"toolsets": ["procedures"]}}], None),  # no escalation
        ([EXPORT], str(tmp_path / "{stem:>999999999}.png")),  # a 1 GB file name (#122)
        ([EXPORT], str(tmp_path / "{stem:>{index}}.png")),  # a width taken from another placeholder
    ]
    gimp = Gimp()
    async with tool_client(gimp.ops()) as (client, bridge):
        for recipe, output in cases:
            args = {"files": [str(a)], "recipe": recipe, **({"output": output} if output else {})}
            result = await client.call_tool("gimp_run_batch", args)
            assert result.is_error, recipe
            if result.structured_content:
                assert error_code(result) == "INVALID_ARGUMENT", (recipe, result.content)
        assert [name for name, _ in bridge.calls if name != "session.images"] == []


async def test_tools_of_disabled_toolsets_are_refused_with_a_hint(tmp_path):
    (a,) = inputs(tmp_path / "in", "a.png")
    with running_fake_bridge(Gimp().ops()) as bridge:
        server = build_server(BridgeClient(bridge.endpoint), toolsets="core,batch")
        async with Client(server) as client:
            result = await client.call_tool("gimp_run_batch", {"files": [str(a)], "recipe": [FLIP]})
    assert error_code(result) == "INVALID_ARGUMENT"
    assert "geometry" in result.structured_content["error"]["hint"]
    assert [name for name, _ in bridge.calls if name != "session.images"] == []


async def test_glob_stays_inside_its_directory(tmp_path):
    folder = tmp_path / "in"
    inputs(folder, "b.png", "a.png", "notes.txt")
    inputs(folder / "sub", "c.png")
    outside = inputs(tmp_path / "secret", "x.png")[0]
    os.symlink(outside, folder / "link.png")
    gimp = Gimp()
    async with tool_client(gimp.ops()) as (client, bridge):
        plan = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "pattern": "*.png", "recipe": [FLIP], "dry_run": True}
        )
        deep = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "pattern": "**/*.png", "recipe": [FLIP], "dry_run": True}
        )
        escapes = [
            await client.call_tool("gimp_run_batch", {"directory": str(folder), "pattern": p, "recipe": [FLIP]})
            for p in ("../secret/*.png", "/etc/*", "sub/../../secret/*")
        ]
        relative = await client.call_tool("gimp_run_batch", {"directory": "in", "recipe": [FLIP]})
        none = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "pattern": "*.gif", "recipe": [FLIP]}
        )
        both = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "files": [str(folder / "a.png")], "recipe": [FLIP]}
        )
        too_many = await client.call_tool(
            "gimp_run_batch", {"directory": str(folder), "pattern": "**/*.png", "recipe": [FLIP], "max_files": 2}
        )
    planned = plan.structured_content
    # sorted; the symlink pointing outside the directory is not followed
    assert [Path(f["file"]).name for f in planned["files"]] == ["a.png", "b.png"]
    assert {f["status"] for f in planned["files"]} == {"planned"} and planned["dry_run"] is True
    assert [Path(f["file"]).name for f in deep.structured_content["files"]] == ["a.png", "b.png", "c.png"]
    for result in (*escapes, relative, none, both, too_many):
        assert error_code(result) == "INVALID_ARGUMENT", result.content
    assert [name for name, _ in bridge.calls if name != "session.images"] == []
    assert gimp.open == {}


async def test_outputs_are_never_overwritten_unless_asked(tmp_path):
    a, b = inputs(tmp_path / "in", "a.png", "b.png")
    out = tmp_path / "out"
    out.mkdir()
    (out / "b.png").write_bytes(b"old")
    gimp = Gimp()
    async with tool_client(gimp.ops()) as (client, bridge):
        args = {"files": [str(a), str(b)], "recipe": [EXPORT], "output": str(out / "{name}")}
        refused = await client.call_tool("gimp_run_batch", args)
        assert error_code(refused) == "FILE_EXISTS" and (out / "b.png").read_bytes() == b"old"
        assert not (out / "a.png").exists()  # refused before the first file

        same = await client.call_tool("gimp_run_batch", {**args, "output": str(out / "same.png")})
        assert error_code(same) == "INVALID_ARGUMENT"  # two inputs would write the same file
        onto_input = await client.call_tool(
            "gimp_run_batch", {**args, "output": str(tmp_path / "in" / "{name}"), "overwrite": True}
        )
        assert error_code(onto_input) == "INVALID_ARGUMENT"  # never replaces an input, even with overwrite
        assert [name for name, _ in bridge.calls if name != "session.images"] == []

        done = await client.call_tool("gimp_run_batch", {**args, "overwrite": True})
    assert done.structured_content["succeeded"] == 2 and (out / "b.png").read_bytes() == b"png"
    exports = [params for name, params in bridge.calls if name == "image.export"]
    assert len(exports) == 2


async def test_images_created_by_steps_are_closed_but_not_preexisting_ones(tmp_path):
    (a,) = inputs(tmp_path / "in", "a.png")
    gimp = Gimp()
    gimp.open[50] = "/already/open.png"  # opened by the user before the batch

    def optimize(params):
        number, gimp.next = gimp.next, gimp.next + 1
        gimp.open[number] = "copy"
        return {"id": number, "frames": []}

    step = {"tool": "gimp_optimize_animation", "arguments": {"image": "{image}"}}
    uses_other = {"tool": "gimp_flip_image", "arguments": {"image": iid(50), "orientation": "vertical"}}
    async with tool_client({**gimp.ops(), "anim.optimize": optimize}) as (client, _):
        result = await client.call_tool("gimp_run_batch", {"files": [str(a)], "recipe": [step, uses_other]})
    assert not result.is_error, result.content
    assert sorted(result.structured_content["files"][0]["closed"]) == [iid(1), iid(2)]
    assert list(gimp.open) == [50]


class Layered(Gimp):
    """Also imports a layer (id 500 + image) and records layer property changes."""

    def __init__(self) -> None:
        super().__init__()
        self.changed: list[tuple[int, float]] = []

    def ops(self):
        return {**super().ops(), "layer.import": self.import_layer, "layer.set": self.set_layer}

    def import_layer(self, params):
        return {**layer(500 + params["image"], "Mark"), "image": params["image"]}

    def set_layer(self, params):
        self.changed.append((params["item"], params["opacity"]))
        return {**layer(params["item"], "Mark"), "image": 1}


async def test_a_step_uses_the_object_an_earlier_step_created(tmp_path):
    """#162: import a watermark, then change *that* layer, not the photo's top layer."""
    a, b = inputs(tmp_path / "in", "a.png", "b.png")
    mark = inputs(tmp_path / "assets", "mark.png")[0]
    gimp = Layered()
    recipe = [
        {"tool": "gimp_import_layer", "arguments": {"image": "{image}", "path": str(mark)}},
        {"tool": "gimp_set_layer_properties", "arguments": {"item": "{steps[0].id}", "opacity": 60}},
    ]
    async with tool_client(gimp.ops()) as (client, _bridge):
        result = await client.call_tool("gimp_run_batch", {"files": [str(a), str(b)], "recipe": recipe})
    assert not result.is_error, result.content
    assert result.structured_content["succeeded"] == 2, result.structured_content
    assert gimp.changed == [(501, 60.0), (502, 60.0)]


async def test_a_whole_reference_keeps_the_value_type(tmp_path):
    [a] = inputs(tmp_path / "in", "a.png")
    gimp = Layered()
    recipe = [
        {"tool": "gimp_import_layer", "arguments": {"image": "{image}", "path": str(a)}},
        {"tool": "gimp_resize_canvas", "arguments": {"image": "{image}", "width": "{steps[0].width}", "height": 4}},
    ]
    resized = []
    ops = {**gimp.ops(), "image.resize": lambda p: resized.append(p["width"]) or {"width": 4, "height": 4,
                                                                                    "dirty": True}}  # fmt: skip
    async with tool_client(ops) as (client, _bridge):
        result = await client.call_tool("gimp_run_batch", {"files": [str(a)], "recipe": recipe})
    assert not result.is_error and result.structured_content["succeeded"] == 1, result.content
    assert resized == [layer(501, "Mark")["width"]]


async def test_step_references_are_checked_before_anything_runs(tmp_path):
    [a] = inputs(tmp_path / "in", "a.png")
    later = [{"tool": "gimp_set_layer_properties", "arguments": {"item": "{steps[1].id}", "opacity": 60}}, FLIP]
    itself = [{"tool": "gimp_set_layer_properties", "arguments": {"item": "{steps[0].id}", "opacity": 60}}]
    unknown_field = [FLIP, {"tool": "gimp_set_layer_properties", "arguments": {"item": "{steps[0].nope}"}}]
    for recipe in (later, itself, unknown_field):
        async with tool_client(Layered().ops()) as (client, bridge):
            result = await client.call_tool("gimp_run_batch", {"files": [str(a)], "recipe": recipe})
            assert error_code(result) == "INVALID_ARGUMENT", recipe
            assert bridge.calls == [], recipe
    message = result.structured_content["error"]["message"]
    assert "nope" in message and "gimp_flip_image" in message


async def test_a_step_with_an_unknown_key_is_refused_before_anything_runs(tmp_path):
    """#215: `args` instead of `arguments` was silently dropped; the step then had no arguments."""
    [a] = inputs(tmp_path / "in", "a.png")
    recipe = [{"tool": "gimp_resize_image", "args": {"image": "{image}", "width": 20}}]
    async with tool_client(Gimp().ops()) as (client, bridge):
        result = await client.call_tool("gimp_run_batch", {"files": [str(a)], "recipe": recipe})
    error = result.structured_content["error"]
    assert error["code"] == "INVALID_ARGUMENT" and bridge.calls == []
    [problem] = error["details"]["errors"]
    assert problem["field"] == "recipe.0.args"
    assert "unknown key" in problem["problem"] and "arguments" in problem["problem"] and "tool" in problem["problem"]


def test_a_glob_stops_as_soon_as_it_finds_more_than_max_files(tmp_path, monkeypatch):
    # directory="/" with pattern="**/*" used to walk the whole disk before counting (#122).
    import pathlib

    from gimp_mcp.batch import list_inputs

    inputs(tmp_path, *[f"{i:03d}.png" for i in range(50)])
    seen = 0
    original = pathlib.Path.glob

    def counting(self, pattern, *args, **kwargs):
        nonlocal seen
        for path in original(self, pattern, *args, **kwargs):
            seen += 1
            yield path

    monkeypatch.setattr(pathlib.Path, "glob", counting)
    with pytest.raises(GimpMcpError) as refused:
        list_inputs(None, str(tmp_path), "*.png", 2)
    assert refused.value.code == "INVALID_ARGUMENT" and "max_files=2" in refused.value.message
    assert seen == 3

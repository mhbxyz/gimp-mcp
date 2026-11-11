"""Check every MCP tool against docs/api-conventions.md and write docs/api/review.md (#118).

    uv run scripts/api_review.py          # regenerate docs/api/review.md
    uv run scripts/api_review.py --check  # exit 1 when the report is stale or a deviation is undecided

Each deviation found by the mechanical checks must have a decision in DECISIONS: fixed by an issue, or
accepted with its reason. tests/unit/test_api_review.py fails on an undecided deviation, on a decision
whose deviation is gone, and on a stale report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "api" / "review.md"

ROLE_NAMES = {
    "image", "item", "items", "target", "parent", "source", "reference_item", "up_to", "duplicate_of",
    "a", "b", "other", "checkpoint", "filter", "channel", "buffer", "guide",
}  # fmt: skip
FILE_NAMES = {"path", "paths", "folder", "output_folder"}
# A schema whose text shows it takes an id.
_ID_TEXT = r"(image|item|checkpoint|filter):\d|\b(Image|Item|item|image|layer|channel|guide) id\b"
VERB_EXEMPT_RESULTS = ("gimp_list_", "gimp_inspect_", "gimp_describe_", "gimp_search_", "gimp_get_")


@dataclass(frozen=True)
class Deviation:
    check: str
    tool: str
    subject: str  # parameter, field or value at fault ("" for the tool itself)
    what: str

    @property
    def key(self) -> str:
        return f"{self.check}:{self.tool}" + (f":{self.subject}" if self.subject else "")


# Decision for every deviation: "fix #N: …" (applied by that issue) or "accepted: <reason>".
_RESULT_ID = "fix #164: return the changed object as a top-level `id`"
_UNDO = "fix #119: the description states the undo behaviour"
_PATH_ITEM = (
    "accepted: in tools working on GIMP paths (vector objects) `path` is the path's id, as in GIMP; their "
    "file argument is `file`"
)
_GIMP_COMMAND = "accepted: named after GIMP's command of the same name (Colors, Edit, Filters menus)"
DECISIONS: dict[str, str] = {
    # file parameters named `file`
    # deprecated aliases of the names #119 fixed: kept until 1.0.0 (ADR 0011)
    **{f"files:{t}:file": "accepted: deprecated alias of `path`, removed in 1.0.0" for t in (
        "gimp_import_palette", "gimp_export_palette", "gimp_create_link_layer", "gimp_set_link_layer")},
    "references:gimp_remove_guide:id": "accepted: deprecated alias of `guide`, removed in 1.0.0",
    "enums:gimp_remove_guide:sample_point": "accepted: deprecated spelling of `sample-point`, removed in 1.0.0",
    **{f"files:{t}:file": "accepted: a tool working on GIMP paths, where `path` is the path's id"
       for t in ("gimp_import_svg_paths", "gimp_export_path_svg")},
}  # fmt: skip

# The v0.6.0 findings (evaluation suite, demo scenarios, GUI tests) and what the review decided.
FINDINGS: list[tuple[str, str]] = [
    ("#146 validation errors as raw pydantic text", "`INVALID_ARGUMENT` with the fields at fault and a hint "
     "listing the required parameters; `TOOLSET_DISABLED` for a tool of a disabled toolset."),
    ("#147 tools first called without their schema after gimp_enable_toolsets", "the result lists each added "
     "tool with its required parameters and a one-line usage (ADR 0012)."),
    ("#148 optional toolsets not discovered (WebP given up)", "descriptions and `UNSUPPORTED_FORMAT` hints of "
     "default tools name the optional tool and toolset that cover the need."),
    ("#149 brightness -30 darkens by 7%", "the description states the measured effect and points to "
     "gimp_exposure / gimp_levels for a predictable darkening."),
    ("#150 resize needs both dimensions", "`width` or `height` alone keeps the aspect ratio, for images and layers."),
    ("#151 rotating an image takes 7 calls", "gimp_rotate_image moves to the default `transform` toolset; "
     "to stay within the budget, GIMP undo groups (gimp_begin/end_undo_group, used by no evaluation task: "
     "agents use checkpoints) move from `history` to a new optional toolset `undo`."),
    ("#156 clone/heal repeat the source", "`source` defaults to `item`; `source_offset: [dx, dy]` is the "
     "relative alternative to `source_x`/`source_y`."),
    ("#158 assigning built-in sRGB is a no-op", "gimp_export_as takes `color_profile` like `png_options`; "
     "assigning `srgb` says it changes nothing."),
    ("#160 PNG exports write tIME", "no `tIME` unless `png_options.metadata` contains `time`."),
    ("#161 metadata only localized", "gimp_get_metadata also returns `raw`: each tag's untranslated value."),
    ("#162 recipes cannot use an earlier step's result", "`{steps[N].id}` (and any top-level field) refers to "
     "step N's result, validated before anything runs."),
    ("#164 created objects named differently", "a top-level `id` names the created or changed object "
     "(conventions, Results)."),
    ("#165 TIFF writes one page per layer", "gimp_export_as takes `layers: \"flatten\"` to write the visible "
     "composite as one page, without changing the image."),
    ("#173 EXIF orientation missing on Windows", "investigated separately; no API change."),
]  # fmt: skip


def _defs(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    return schema.get("$defs", {}).get(ref.rsplit("/", 1)[-1], {}) if isinstance(ref, str) else node


def _walk(schema: dict[str, Any], node: dict[str, Any], path: str) -> Iterator[tuple[str, dict[str, Any]]]:
    node = _defs(schema, node)
    yield path, node
    for variant in node.get("anyOf", []):
        yield from _walk(schema, variant, path)
    for name, sub in node.get("properties", {}).items():
        yield from _walk(schema, sub, f"{path}.{name}" if path else name)
    if isinstance(node.get("items"), dict):
        yield from _walk(schema, node["items"], f"{path}[]")


def check_tool(tool: dict[str, Any]) -> Iterator[Deviation]:
    name, description = tool["name"], tool.get("description", "")
    schema = tool["inputSchema"]
    params: dict[str, Any] = schema.get("properties", {})
    if not re.fullmatch(r"gimp_[a-z0-9]+(_[a-z0-9]+)+", name):
        yield Deviation("naming", name, "", "tool name is not gimp_<verb>_<object> in snake_case")
    for param, node in params.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", param):
            yield Deviation("naming", name, param, "parameter is not snake_case")
        text = json.dumps(node)
        refers = re.search(_ID_TEXT, text)
        if param == "id" or (refers and param not in ROLE_NAMES):
            yield Deviation("references", name, param, "an id parameter not named image/item/role")
        if param == "file" or (param not in FILE_NAMES and "absolute path" in text.lower() and "id" not in param):
            yield Deviation("files", name, param, "a file system path not named `path`")
    for path, node in _walk(schema, schema, ""):
        for value in node.get("enum", []):
            if isinstance(value, str) and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*|[a-z0-9.+/#-]*", value):
                yield Deviation("enums", name, value, f"enum value of {path or 'input'} is not lowercase-hyphenated")
    writes = any(word in name for word in ("_export_", "_save_")) or name.startswith(("gimp_export", "gimp_save"))
    if writes and "overwrite" not in params:
        yield Deviation("files", name, "overwrite", "writes a file without an `overwrite` parameter")
    annotations = tool.get("annotations", {})
    mutating = annotations.get("readOnlyHint") is not True
    outputs = tool.get("outputSchema", {}).get("properties", {})
    if mutating and "id" not in outputs and not name.startswith(VERB_EXEMPT_RESULTS):
        yield Deviation("results", name, "id", "no top-level `id` for the object created or changed")
    lowered = description.lower()
    if mutating and "undo" not in lowered and "history" not in lowered:
        yield Deviation("descriptions", name, "", "does not state its undo behaviour")


def deviations(tools: list[dict[str, Any]]) -> list[Deviation]:
    return sorted((d for tool in tools for d in check_tool(tool)), key=lambda d: d.key)


def decision(deviation: Deviation) -> str | None:
    if deviation.key in DECISIONS:
        return DECISIONS[deviation.key]
    if deviation.check == "results":
        return RESULT_DECISIONS.get(deviation.tool, _RESULT_ID)
    if deviation.check == "descriptions":
        return _UNDO
    if deviation.check == "references" and deviation.subject == "path":
        return _PATH_ITEM
    if deviation.check == "naming" and not deviation.subject:
        return _GIMP_COMMAND
    return None


# Tools exempt from the `id` rule, with the reason; every other mutating tool gets `id` (#164).
RESULT_DECISIONS: dict[str, str] = {
    "gimp_enable_toolsets": "accepted: changes the session's tool list, no image or item",
    "gimp_call_procedure": "accepted: generic access; GIMP's return values are in `results`",
    "gimp_align_layers": "accepted: moves several layers, listed in `layers`",
    "gimp_export_layers": "accepted: writes several files, listed in `files`",
    "gimp_import_svg_paths": "accepted: creates several paths, listed in `paths`",
    "gimp_run_batch": "accepted: processes many files, reported per file",
    "gimp_delete_resource": "accepted: resources are named, not identified",
    "gimp_create_resource": "accepted: resources are named, not identified (`name`)",
    "gimp_duplicate_resource": "accepted: resources are named, not identified (`name`)",
    "gimp_rename_resource": "accepted: resources are named, not identified (`name`)",
    "gimp_edit_brush": "accepted: resources are named, not identified (`name`)",
    "gimp_edit_gradient": "accepted: resources are named, not identified (`name`)",
    "gimp_edit_palette": "accepted: resources are named, not identified (`name`)",
    "gimp_import_palette": "accepted: resources are named, not identified (`name`)",
    "gimp_export_palette": "accepted: writes a file, named in `file`",
    "gimp_copy": "accepted: fills a clipboard buffer, named in `buffer`",
    "gimp_create_checkpoint": "accepted: creates a checkpoint, identified by `checkpoint`",
    "gimp_delete_checkpoint": "accepted: deletes a checkpoint, identified by `checkpoint`",
    "gimp_begin_undo_group": "accepted: opens an undo group, reported by `image` and `depth`",
    "gimp_end_undo_group": "accepted: closes an undo group, reported by `image` and `depth`",
    **{tool: "accepted: writes a file, named in `path`" for tool in (
        "gimp_save_image", "gimp_export_image", "gimp_export_as", "gimp_export_region", "gimp_export_animation")},
    **{tool: "accepted: the object is gone; the result names it" for tool in (
        "gimp_close_image", "gimp_delete_layer", "gimp_delete_path", "gimp_delete_channel")},
    **{tool: "accepted: guides and sample points are numbered, not items (`guide`, `sample_point`)" for tool in (
        "gimp_add_guide", "gimp_add_sample_point", "gimp_remove_guide")},
}  # fmt: skip


def render(tools: list[dict[str, Any]], found: list[Deviation]) -> str:
    by_check: dict[str, list[Deviation]] = {}
    for deviation in found:
        by_check.setdefault(deviation.check, []).append(deviation)
    fixed = sum(1 for d in found if (decision(d) or "").startswith("fix"))
    lines = [
        "# API review",
        "",
        "<!-- Generated by scripts/api_review.py from the tool definitions. Do not edit by hand. -->",
        "",
        f"{len(tools)} tools checked against [the API conventions](../api-conventions.md): "
        f"{len(found)} deviations, {fixed} to fix, {len(found) - fixed} accepted.",
        "",
        "## Findings of v0.6.0",
        "",
        "| Finding | Decision |",
        "|---|---|",
        *(f"| {finding} | {text} |" for finding, text in FINDINGS),
    ]
    titles = {
        "naming": "Naming",
        "references": "References to images and items",
        "files": "Files and `overwrite`",
        "enums": "Enumerations",
        "results": "Results: `id` of the object created or changed",
        "descriptions": "Descriptions: undo behaviour",
    }
    for check, title in titles.items():
        lines += ["", f"## {title}", ""]
        rows = by_check.get(check, [])
        if not rows:
            lines.append("No deviation.")
            continue
        lines += ["| Tool | Subject | Deviation | Decision |", "|---|---|---|---|"]
        lines += [f"| `{d.tool}` | {f'`{d.subject}`' if d.subject else ''} | {d.what} | {decision(d)} |" for d in rows]
    return "\n".join(lines) + "\n"


def collect_tools() -> list[dict[str, Any]]:
    import anyio
    from mcp import Client

    from gimp_mcp.server import build_server

    async def run() -> list[dict[str, Any]]:
        async with Client(build_server(toolsets="all", env={})) as client:
            return [
                tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                for tool in (await client.list_tools()).tools
            ]

    return anyio.run(run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    tools = collect_tools()
    found = deviations(tools)
    undecided = [d.key for d in found if decision(d) is None]
    text = render(tools, found)
    if args.check:
        stale = REPORT.read_text(encoding="utf-8") != text
        for key in undecided:
            print(f"undecided deviation: {key}")
        if stale:
            print("docs/api/review.md is out of date: run `uv run scripts/api_review.py`")
        return 1 if undecided or stale else 0
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {REPORT.relative_to(ROOT)}: {len(found)} deviations, {len(undecided)} undecided")
    return 0


if __name__ == "__main__":
    sys.exit(main())

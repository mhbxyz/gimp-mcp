"""The public API contract (#116): snapshot, error code registry and breaking-change checker."""

from __future__ import annotations

import ast
import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gimp_mcp.contract import Change, collect_contract, compare, render_contract, verdict
from gimp_mcp.errors import ERROR_CODES

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "docs" / "api" / "contract.json"


def tool(name: str = "gimp_x", **props: Any) -> dict[str, Any]:
    required = [key for key, value in props.items() if value.pop("_required", False)]
    return {
        "name": name,
        "toolset": "files",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        "inputSchema": {"type": "object", "properties": props, "required": required},
        "outputSchema": {
            "type": "object",
            "properties": {"image": {"type": "string"}, "width": {"type": "integer"}},
            "required": ["image", "width"],
        },
    }


def contract(*tools: dict[str, Any], **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tools": {t["name"]: t for t in tools},
        "error_codes": ["INVALID_ARGUMENT", "NOT_FOUND"],
        "prompts": {"thumbnail": {"arguments": {"path": True, "size": False}}},
        "resources": ["gimp://images"],
        "resource_templates": ["gimp://images/{image}/layers"],
        "cli": {"serve": {"--socket": {"required": False}, "--toolsets": {"required": False}}},
    }
    base.update(extra)
    return base


BASE = contract(
    tool(
        image={"type": "string", "_required": True},
        mode={"enum": ["rgb", "gray"], "type": "string", "default": "rgb"},
        size={"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
    )
)


def edited(edit: Callable[[dict[str, Any]], object]) -> dict[str, Any]:
    new = copy.deepcopy(BASE)
    edit(new)
    return new


def kinds(new: dict[str, Any]) -> set[str]:
    return {change.kind for change in compare(BASE, new)}


def props(c: dict[str, Any]) -> dict[str, Any]:
    return c["tools"]["gimp_x"]["inputSchema"]["properties"]


COMPATIBLE = {
    "new tool": lambda c: c["tools"].update(gimp_y={**c["tools"]["gimp_x"], "name": "gimp_y"}),
    "new optional parameter": lambda c: props(c).update(extra={"type": "boolean", "default": False}),
    "new output field": lambda c: c["tools"]["gimp_x"]["outputSchema"]["properties"].update(dirty={"type": "boolean"}),
    "new error code": lambda c: c["error_codes"].append("LOCKED"),
    "new enum value": lambda c: props(c)["mode"]["enum"].append("indexed"),
    "wider range": lambda c: props(c)["size"].update(maximum=1000),
    "required parameter made optional": lambda c: c["tools"]["gimp_x"]["inputSchema"].update(required=[]),
    "new prompt": lambda c: c["prompts"].update(cleanup={"arguments": {}}),
    "new optional prompt argument": lambda c: c["prompts"]["thumbnail"]["arguments"].update(output=False),
    "new CLI option": lambda c: c["cli"]["serve"].update({"--verbose": {"required": False}}),
    "new CLI command": lambda c: c["cli"].update(doctor={}),
    "new resource template": lambda c: c["resource_templates"].append("gimp://images/{image}/preview"),
}

BREAKING = {
    "removed tool": lambda c: c["tools"].pop("gimp_x"),
    "removed parameter": lambda c: props(c).pop("size"),
    "new required parameter": lambda c: (
        props(c).update(path={"type": "string"}),
        c["tools"]["gimp_x"]["inputSchema"]["required"].append("path"),
    ),
    "optional parameter made required": lambda c: c["tools"]["gimp_x"]["inputSchema"]["required"].append("mode"),
    "narrowed type": lambda c: props(c)["size"].update(maximum=50),
    "removed enum value": lambda c: props(c)["mode"]["enum"].remove("gray"),
    "changed type": lambda c: props(c)["size"].update(type="string"),
    "changed default": lambda c: props(c)["size"].update(default=20),
    "removed output field": lambda c: (
        c["tools"]["gimp_x"]["outputSchema"]["properties"].pop("width"),
        c["tools"]["gimp_x"]["outputSchema"]["required"].remove("width"),
    ),
    "output field may be missing": lambda c: c["tools"]["gimp_x"]["outputSchema"]["required"].remove("width"),
    "removed error code": lambda c: c["error_codes"].remove("NOT_FOUND"),
    "tool moved to another toolset": lambda c: c["tools"]["gimp_x"].update(toolset="formats"),
    "removed prompt": lambda c: c["prompts"].pop("thumbnail"),
    "new required prompt argument": lambda c: c["prompts"]["thumbnail"]["arguments"].update(output=True),
    "removed CLI option": lambda c: c["cli"]["serve"].pop("--socket"),
    "removed CLI command": lambda c: c["cli"].pop("serve"),
    "removed resource": lambda c: c["resources"].remove("gimp://images"),
}


@pytest.mark.parametrize("name", COMPATIBLE)
def test_compatible_changes(name: str) -> None:
    assert kinds(edited(COMPATIBLE[name])) == {"compatible"}, name


@pytest.mark.parametrize("name", BREAKING)
def test_breaking_changes(name: str) -> None:
    assert "breaking" in kinds(edited(BREAKING[name])), name


def test_identical_contracts_have_no_change() -> None:
    assert compare(BASE, copy.deepcopy(BASE)) == []


def test_a_read_only_tool_that_starts_changing_images_is_breaking() -> None:
    old = copy.deepcopy(BASE)
    old["tools"]["gimp_x"]["annotations"]["readOnlyHint"] = True
    assert [c.kind for c in compare(old, BASE)] == ["breaking"]


def test_references_are_followed_into_definitions() -> None:
    def with_ref(maximum: int) -> dict[str, Any]:
        c = copy.deepcopy(BASE)
        schema = c["tools"]["gimp_x"]["inputSchema"]
        schema["$defs"] = {"Opts": {"type": "object", "properties": {"q": {"type": "integer", "maximum": maximum}}}}
        schema["properties"]["opts"] = {"anyOf": [{"$ref": "#/$defs/Opts"}, {"type": "null"}], "default": None}
        return c

    changes = compare(with_ref(100), with_ref(50))
    assert [(c.kind, c.where) for c in changes] == [("breaking", "tool gimp_x: input opts.q")]


def test_each_change_says_where_and_what() -> None:
    [change] = compare(BASE, edited(BREAKING["removed parameter"]))
    assert change == Change("breaking", "tool gimp_x: input size", "parameter removed")


CHANGELOG_WITH_BREAKING = "# Changelog\n\n## [Unreleased]\n\n### Breaking\n\n- `gimp_x` loses `size`.\n\n## [0.6.0]\n"
CHANGELOG_WITHOUT = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- Something.\n\n## [0.6.0]\n### Breaking\n- old\n"


def test_breaking_changes_need_a_changelog_entry_before_1_0() -> None:
    changes = compare(BASE, edited(BREAKING["removed parameter"]))
    assert not verdict(changes, CHANGELOG_WITHOUT, "0.6.0", "0.6.0").ok
    assert verdict(changes, CHANGELOG_WITH_BREAKING, "0.6.0", "0.6.0").ok


def test_breaking_changes_need_a_new_major_version_after_1_0() -> None:
    changes = compare(BASE, edited(BREAKING["removed parameter"]))
    assert not verdict(changes, CHANGELOG_WITH_BREAKING, "1.2.0", "1.2.0").ok
    assert not verdict(changes, CHANGELOG_WITH_BREAKING, "1.2.0", "1.3.0").ok
    assert verdict(changes, CHANGELOG_WITH_BREAKING, "1.2.0", "2.0.0").ok


def test_compatible_changes_always_pass() -> None:
    changes = compare(BASE, edited(COMPATIBLE["new tool"]))
    assert verdict(changes, CHANGELOG_WITHOUT, "1.2.0", "1.2.0").ok


def test_the_snapshot_is_up_to_date() -> None:
    expected = render_contract(collect_contract())
    assert SNAPSHOT.read_text(encoding="utf-8") == expected, (
        "docs/api/contract.json is out of date: run `uv run scripts/api_contract.py write`"
    )


def test_the_snapshot_covers_every_public_surface() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert set(snapshot) >= {"tools", "error_codes", "prompts", "resources", "resource_templates", "cli"}
    export = snapshot["tools"]["gimp_export_image"]
    assert export["toolset"] == "files"
    assert {"inputSchema", "outputSchema", "annotations"} <= set(export)
    assert "--toolsets" in snapshot["cli"]["serve"]
    assert "gimp://images/{image}/layers" in snapshot["resource_templates"]


def _codes_raised_in(path: Path) -> set[str]:
    """Error codes passed to an error constructor (first positional string or ``code=``) or written as
    ``{"code": "..."}`` in a bridge reply."""
    codes = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "code" and isinstance(value, ast.Constant):
                    codes.add(value.value)
            continue
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if not name.endswith("Error"):
            continue
        candidates = [*node.args[:1], *(kw.value for kw in node.keywords if kw.arg == "code")]
        for value in candidates:
            if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.isupper():
                codes.add(value.value)
    return codes


def test_every_error_code_raised_is_registered() -> None:
    raised = set().union(*(_codes_raised_in(path) for path in (ROOT / "src" / "gimp_mcp").rglob("*.py")))
    assert raised, "no error code found: the scan is broken"
    assert raised <= set(ERROR_CODES), sorted(raised - set(ERROR_CODES))


def test_every_registered_error_code_is_documented() -> None:
    """docs/tools.md has one row per code, with the registry's text."""
    tools_md = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
    missing = [code for code, text in ERROR_CODES.items() if f"| `{code}` | {text} |" not in tools_md]
    assert not missing, missing

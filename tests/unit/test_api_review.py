"""Every tool is checked against docs/api-conventions.md; every deviation is decided (#118)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("api_review", ROOT / "scripts" / "api_review.py")
assert spec is not None and spec.loader is not None
review = importlib.util.module_from_spec(spec)
sys.modules["api_review"] = review
spec.loader.exec_module(review)

TOOLS = review.collect_tools()
FOUND = review.deviations(TOOLS)


def test_every_deviation_is_fixed_or_accepted_with_a_reason():
    undecided = [d.key for d in FOUND if review.decision(d) is None]
    assert undecided == []
    assert all(review.decision(d).startswith(("fix #", "accepted: ")) for d in FOUND)


def test_no_decision_outlives_its_deviation():
    keys = {d.key for d in FOUND}
    tools = {d.tool for d in FOUND if d.check == "results"}
    assert sorted(set(review.DECISIONS) - keys) == []
    assert sorted(set(review.RESULT_DECISIONS) - tools) == []


def test_the_report_is_up_to_date():
    assert (ROOT / "docs" / "api" / "review.md").read_text(encoding="utf-8") == review.render(TOOLS, FOUND), (
        "docs/api/review.md is out of date: run `uv run scripts/api_review.py`"
    )


def test_the_checks_catch_known_deviations():
    tool = {
        "name": "gimp_frobnicate",
        "description": "Changes things.",
        "annotations": {"readOnlyHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string", "description": "Item id, e.g. 'item:3@a1b2c3d4'."},
                "file": {"type": "string", "description": "Absolute path of the output."},
                "mode": {"enum": ["Fast_Mode", "slow"]},
            },
        },
        "outputSchema": {"type": "object", "properties": {"done": {"type": "boolean"}}},
    }
    keys = {d.key for d in review.check_tool(tool)}
    assert keys == {
        "naming:gimp_frobnicate",
        "references:gimp_frobnicate:layer_id",
        "files:gimp_frobnicate:file",
        "enums:gimp_frobnicate:Fast_Mode",
        "results:gimp_frobnicate:id",
        "descriptions:gimp_frobnicate",
    }

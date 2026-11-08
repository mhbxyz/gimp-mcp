"""Every demo scenario (#107) on a real GIMP: its own checks pass, and its files are checked again here.

The scenario's checks run through MCP; the verifications below read its output files with Pillow,
independently of the scenario's code.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from demo.harness import Report, load, run_scenario, scenario_names
from gimp_mcp.headless import HeadlessGimp

from .conftest import server_params


def thumbnail(out: Path, report: Report) -> None:
    # toolsets (#45): only what the demo needs was listed, and that was enough
    assert {"gimp_call_procedure", "gimp_search_procedures"}.isdisjoint(report.listed_tools)
    assert len(report.listed_tools) < 52 and len(report.checks) >= 13
    with Image.open(out / "thumbnail.png") as png:
        assert png.size == (1280, 720)
        r, g, b = png.convert("RGB").getpixel((20, 650))  # type: ignore[misc]
        assert max(r, g, b) < 90  # dark banner behind the title
    with Image.open(out / "thumbnail.jpg") as jpg:
        assert jpg.format == "JPEG" and jpg.size == (1280, 720)
    assert (out / "thumbnail.xcf").read_bytes().startswith(b"gimp xcf")
    assert sorted(p.name for p in (out / "previews").iterdir()) == [
        "01-backdrop.png", "02-subject.png", "03-title.png", "04-retitled.png", "05-badge.png",
        "06-undo.png", "07-redo.png", "08-final.png",
    ]  # fmt: skip
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "`gimp_restore_checkpoint`" in text and "`gimp_set_text`" in text and "`gimp_export_image`" in text


INDEPENDENT: dict[str, Callable[[Path, Report], None]] = {"thumbnail": thumbnail}


def test_every_scenario_has_independent_verifications():
    assert set(INDEPENDENT) == set(scenario_names())


@pytest.mark.parametrize("name", scenario_names())
async def test_scenario_produces_verified_outputs(name: str, gimp: HeadlessGimp, tmp_path: Path):
    scenario = load(name)
    report = await run_scenario(scenario, tmp_path, server_params(gimp))
    failed = [check for check in report.checks if not check.passed]
    assert not failed, failed
    assert {call.tool for call in report.calls} <= report.listed_tools
    for output in scenario.outputs:
        assert (tmp_path / output).is_file(), output
    assert "Result: **PASS**" in (tmp_path / "report.md").read_text(encoding="utf-8")
    INDEPENDENT[name](tmp_path, report)

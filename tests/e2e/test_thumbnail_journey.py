"""Issue #15: build a thumbnail end to end through MCP only (runs demo/thumbnail.py)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import server_params

DEMO = Path(__file__).resolve().parents[2] / "demo" / "thumbnail.py"


def load_demo():
    spec = importlib.util.spec_from_file_location("gimp_mcp_demo_thumbnail", DEMO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_thumbnail_journey_produces_verified_outputs(gimp: HeadlessGimp, tmp_path: Path):
    demo = load_demo()
    report = await demo.run_demo(tmp_path, server_params(gimp))

    failed = [check for check in report.checks if not check.passed]
    assert not failed, failed
    # toolsets (#45): only what the demo needs was listed, and that was enough
    called = {call.tool for call in report.calls}
    assert called <= report.listed_tools
    assert {"gimp_call_procedure", "gimp_search_procedures"}.isdisjoint(report.listed_tools)
    assert len(report.listed_tools) < 52
    assert len(report.checks) >= 13

    # independent assertions on the produced files (not only the demo's own checks)
    with Image.open(tmp_path / "thumbnail.png") as png:
        assert png.size == (1280, 720)
        r, g, b = png.convert("RGB").getpixel((20, 650))  # type: ignore[misc]
        assert max(r, g, b) < 90  # dark banner behind the title
    with Image.open(tmp_path / "thumbnail.jpg") as jpg:
        assert jpg.format == "JPEG" and jpg.size == (1280, 720)
    assert (tmp_path / "thumbnail.xcf").read_bytes().startswith(b"gimp xcf")
    assert sorted(p.name for p in (tmp_path / "previews").iterdir()) == [
        "01-backdrop.png", "02-subject.png", "03-title.png", "04-retitled.png", "05-badge.png",
        "06-undo.png", "07-redo.png", "08-final.png",
    ]  # fmt: skip
    assert "`gimp_restore_checkpoint`" in (tmp_path / "report.md").read_text()
    report_text = (tmp_path / "report.md").read_text()
    assert "Result: **PASS**" in report_text
    assert "`gimp_set_text`" in report_text and "`gimp_export_image`" in report_text

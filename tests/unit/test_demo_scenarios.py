"""Demo scenarios (#107): each declares toolsets, licensed assets, outputs and an agent prompt."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from demo.harness import ASSETS, DEMO, agent_inputs, asset_licenses, check_assets, load, scenario_names
from gimp_mcp.toolsets import check_toolset

NAMES = scenario_names()


def test_the_thumbnail_demo_is_a_scenario():
    assert "thumbnail" in NAMES


@pytest.mark.parametrize("name", NAMES)
def test_a_scenario_declares_what_it_needs_and_what_an_agent_is_asked(name):
    scenario = load(name)
    assert scenario.name == name and scenario.title and scenario.outputs
    for toolset in scenario.toolsets:
        check_toolset(toolset)  # raises on an unknown toolset
    check_assets(scenario)  # every asset exists and has a source and a license
    # the agent version exports where the recording waits for it
    assert f"~/out/{scenario.agent_output}" in scenario.prompt


@pytest.mark.parametrize("name", NAMES)
def test_the_agent_finds_every_input_its_prompt_names(name, tmp_path):
    scenario = load(name)
    paths = [path.relative_to(tmp_path) for path in agent_inputs(scenario, tmp_path)]
    files = {str(p) for p in paths} | {str(p.parent) for p in paths}  # a prompt may name a folder
    named = {n.rstrip("/") for n in re.findall(r"~/inputs/([\w./-]+)", scenario.prompt)}
    assert named and named <= files, (named, files)


def test_an_asset_without_source_and_license_is_refused():
    scenario = load("thumbnail")
    with pytest.raises(ValueError, match="no source and license"):
        check_assets(scenario, licenses={})
    with pytest.raises(ValueError, match="no source and license"):
        check_assets(scenario, licenses={"lake-sunset.png": ("generated", "")})
    with pytest.raises(ValueError, match="not in demo/assets"):
        check_assets(replace(scenario, assets=("missing.png",)), licenses={"missing.png": ("x", "CC0 1.0")})


def test_every_asset_file_has_a_source_and_a_license():
    files = {path.name for path in ASSETS.iterdir() if path.is_file()} - {"LICENSES.md", "README.md"}
    licenses = asset_licenses()
    assert files <= set(licenses), files - set(licenses)
    assert all(source and license_ for source, license_ in licenses.values())


def test_the_demo_readme_lists_every_scenario():
    readme = (DEMO / "README.md").read_text(encoding="utf-8")
    for name in NAMES:
        assert f"| `{name}` |" in readme, name


def test_run_lists_the_scenarios_and_prints_prompts():
    run = [sys.executable, str(DEMO / "run.py")]
    listed = subprocess.run([*run, "--list"], capture_output=True, text=True, timeout=60, check=True)
    assert [line.split("\t")[0] for line in listed.stdout.splitlines()] == NAMES
    prompt = subprocess.run([*run, "--prompt", "thumbnail"], capture_output=True, text=True, timeout=60, check=True)
    assert prompt.stdout.strip() == load("thumbnail").prompt
    unknown = subprocess.run([*run, "nope"], capture_output=True, text=True, timeout=60)
    assert unknown.returncode != 0 and "unknown scenario" in unknown.stderr


def test_the_restoration_agent_checks_reject_the_unrestored_scan(tmp_path):
    from PIL import Image

    from demo.scenarios import old_photo_restoration as restoration

    restoration.make_scan(tmp_path / "scan.png")
    scan = Image.open(tmp_path / "scan.png")
    scan.save(tmp_path / "restored-web.jpg")
    restoration.write_tiff16(tmp_path / "restored-print.tif", scan, 300)
    failed = {c.description for c in restoration.agent_check(tmp_path, "") if not c.passed}
    assert "the sky's color bands are level (under 0.5° measured)" in failed
    assert "no scanner bed remains along the edges" in failed
    assert "full contrast again (1%-99%: <=30 and >=225)" in failed


def test_a_headline_on_two_lines_is_the_same_editable_headline():
    from demo.scenarios.social_media_kit import xcf_texts

    xcf = b'gimp xcf v020\x00gimp-text-layer\x00(text "Golden Hour\\nSale") (font "Noto Sans Bold")'
    assert xcf_texts(xcf) == ["Golden Hour Sale"]
    assert xcf_texts(b'(text "Golden Hours Sale")') != ["Golden Hour Sale"]


def test_the_screenshot_checks_reject_an_unredacted_copy(tmp_path):
    from demo.scenarios import screenshot_annotation as screenshot

    screenshot.make_screenshot(tmp_path / "screenshot.png")
    (tmp_path / "tutorial.png").write_bytes((tmp_path / "screenshot.png").read_bytes())
    failed = {c.description for c in screenshot.verify(tmp_path / "screenshot.png", tmp_path / "tutorial.png", False)
              if not c.passed}  # fmt: skip
    assert "the e-mail keeps no detail (no glyph pixel left)" in failed
    assert "the avatar keeps no detail (flatter, eyes and mouth gone)" in failed
    assert "the PNG carries no metadata (no text, Exif, time or profile chunk)" in failed  # the planted tEXt


def test_an_arrow_may_reach_the_e_mail_field_from_the_right(tmp_path):
    # #232: an agent's arrow drawn from the right (evaluation run 43368399766) was refused; the prompt names no side.
    from demo.scenarios import screenshot_annotation as screenshot

    screenshot.make_screenshot(tmp_path / "screenshot.png")
    tutorial = Path(__file__).parent.parent / "fixtures" / "demos" / "screenshot-arrow-from-the-right.png"
    failed = [c for c in screenshot.verify(tmp_path / "screenshot.png", tutorial, False) if not c.passed]
    assert failed == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [("right, top", 6), ("left, bottom", 8), ("bottom, left", 8), ("Left, Bottom", 8), ("6", 6), ("8", 8),
     ("top, left", 1), ("", 1)],
)  # fmt: skip
def test_the_batch_demo_reads_exif_orientation_from_interpreted_values(value, expected):
    from demo.scenarios.web_photo_batch import orientation_of

    assert orientation_of(value) == expected

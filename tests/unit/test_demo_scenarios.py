"""Demo scenarios (#107): each declares toolsets, licensed assets, outputs and an agent prompt."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

import pytest

from demo.harness import ASSETS, DEMO, asset_licenses, check_assets, load, scenario_names
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
    # the agent version exports where the recording waits for it, and uses the same assets
    assert f"~/out/{scenario.agent_output}" in scenario.prompt
    for name_ in scenario.assets:
        assert f"~/assets/{name_}" in scenario.prompt or not name_.endswith((".png", ".jpg", ".svg"))


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

"""The distribution matrix (ci/distros/distros.json) is complete, pinned and documented (#38)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "ci" / "distros" / "distros.json").read_text())


def test_supported_distributions_are_pinned_and_installable():
    supported = [d for d in DATA["distributions"] if d["status"] == "supported"]
    assert len(supported) >= 5
    for item in supported:
        assert "@sha256:" in item["image"], item["id"]  # base image pinned by digest
        assert item["install"] and item["packages"]
        major, minor = map(int, item["gimp"].split(".")[:2])
        assert (major, minor) >= (3, 2), item["id"]


def test_unsupported_distributions_say_why():
    for item in DATA["distributions"]:
        if item["status"] == "unsupported":
            assert item["reason"] and item["gimp"], item["id"]


def test_compatibility_page_is_generated_from_the_matrix():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_distros.py"), "--check"])
    assert proc.returncode == 0


def test_matrix_runs_on_releases_on_a_schedule_and_on_changes():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "distros.yml").read_text())
    triggers = workflow[True]  # YAML 1.1 reads the `on` key as True
    assert triggers["push"]["tags"] == ["v*"] and triggers["schedule"]
    assert "ci/distros/**" in triggers["pull_request"]["paths"]
    smoke = workflow["jobs"]["smoke"]
    assert smoke["strategy"]["fail-fast"] is False
    assert "fromJSON(needs.matrix.outputs.ids)" in smoke["strategy"]["matrix"]["distro"].replace(" ", "")

"""scripts/prepare_release.py: one command prepares a release PR (#37)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare_release.py"
spec = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
assert spec is not None and spec.loader is not None
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

CHANGELOG = """# Changelog

Intro.

## [Unreleased]

### Added

- Something (#40).

## [0.1.0] - 2026-11-07

First.

[0.1.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.1.0
"""


def test_changelog_unreleased_section_becomes_the_release():
    rolled = prepare.roll_changelog(CHANGELOG, "0.2.0", "2026-11-20")
    assert "## [Unreleased]\n\n## [0.2.0] - 2026-11-20\n\n### Added\n\n- Something (#40)." in rolled
    assert "[0.2.0]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v0.2.0" in rolled
    assert rolled.index("[0.2.0]: ") < rolled.index("[0.1.0]: ")


def test_an_empty_unreleased_section_is_refused():
    empty = CHANGELOG.replace("### Added\n\n- Something (#40).\n\n", "")
    with pytest.raises(prepare.ReleaseError, match="nothing"):
        prepare.roll_changelog(empty, "0.2.0", "2026-11-20")


@pytest.mark.parametrize(("current", "new"), [("0.2.0", "0.1.9"), ("0.2.0", "0.2.0"), ("0.2.0", "v0.3")])
def test_version_must_be_a_greater_semver(current, new):
    with pytest.raises(prepare.ReleaseError):
        prepare.check_version(current, new)


def test_pyproject_version_is_bumped():
    text = '[project]\nname = "gimp-mcp"\nversion = "0.1.0"\n[tool.x]\nversion = "9"\n'
    assert (
        prepare.bump_pyproject(text, "0.2.0")
        == '[project]\nname = "gimp-mcp"\nversion = "0.2.0"\n[tool.x]\nversion = "9"\n'
    )


def test_no_git_mode_edits_a_copy_of_the_project(tmp_path):
    for name in ("pyproject.toml", "CHANGELOG.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "9.9.9", "--root", str(tmp_path), "--no-git", "--no-lock",
         "--date", "2030-01-01"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert 'version = "9.9.9"' in (tmp_path / "pyproject.toml").read_text()
    assert "## [9.9.9] - 2030-01-01" in (tmp_path / "CHANGELOG.md").read_text()
    assert "Release v9.9.9" in proc.stderr  # the PR title that triggers tagging once merged


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("0.7.0", "1.0.0rc1"),
        ("1.0.0rc1", "1.0.0rc2"),
        ("1.0.0rc2", "1.0.0"),
        ("1.0.0b1", "1.0.0rc1"),
        ("1.0.0", "1.0.1"),
    ],
)
def test_pre_releases_are_ordered_before_their_release(current, new):
    """#124: release candidates (PEP 440: 1.0.0rc1, also aN and bN) come before 1.0.0."""
    prepare.check_version(current, new)


@pytest.mark.parametrize(("current", "new"), [("1.0.0", "1.0.0rc3"), ("1.0.0rc2", "1.0.0rc1"), ("0.7.0", "1.0.0-rc.1")])
def test_a_pre_release_must_still_be_greater(current, new):
    with pytest.raises(prepare.ReleaseError):
        prepare.check_version(current, new)


def test_a_pre_release_rolls_the_changelog_like_a_release():
    rolled = prepare.roll_changelog(CHANGELOG, "1.0.0rc1", "2026-11-20")
    assert "## [1.0.0rc1] - 2026-11-20" in rolled
    assert "[1.0.0rc1]: https://github.com/mhbxyz/gimp-mcp/releases/tag/v1.0.0rc1" in rolled
    assert prepare.is_pre_release("1.0.0rc1") and not prepare.is_pre_release("1.0.0")

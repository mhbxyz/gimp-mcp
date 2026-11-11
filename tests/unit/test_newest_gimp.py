"""ci/newest_gimp.py picks the newest GIMP gimp.org publishes for the gimp-next job (#121)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("newest_gimp", ROOT / "ci" / "newest_gimp.py")
assert spec is not None and spec.loader is not None
newest_gimp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(newest_gimp)


def release(version: str, *files: str) -> dict:
    return {
        "version": version,
        "macos": [{"filename": name, "sha256": f"sha-{name}"} for name in files],
        "windows": [{"filename": f"gimp-{version}-setup.exe", "sha256": "w"}],
    }


MANIFEST = {
    "STABLE": [release("3.2.8", "gimp-3.2.8-arm64.dmg", "gimp-3.2.8-x86_64.dmg", "bogus-gimp-3.2.8.dmg")],
    "DEVELOPMENT": [release("3.2.0-RC3", "gimp-3.2.0-RC3-arm64.dmg"), release("3.1.4", "gimp-3.1.4-arm64.dmg")],
}


def test_a_stable_release_newer_than_the_development_one_wins():
    assert newest_gimp.newest(MANIFEST, "macos-arm64") == {
        "version": "3.2.8",
        "url": "https://download.gimp.org/gimp/v3.2/macos/gimp-3.2.8-arm64.dmg",
        "sha256": "sha-gimp-3.2.8-arm64.dmg",
    }


def test_a_newer_development_release_wins():
    manifest = {**MANIFEST, "DEVELOPMENT": [release("3.3.2", "gimp-3.3.2-arm64.dmg"), *MANIFEST["DEVELOPMENT"]]}
    picked = newest_gimp.newest(manifest, "macos-arm64")
    assert picked["version"] == "3.3.2" and picked["url"].endswith("/v3.3/macos/gimp-3.3.2-arm64.dmg")
    assert newest_gimp.newest(manifest, "windows")["url"].endswith("/v3.3/windows/gimp-3.3.2-setup.exe")


def test_release_candidates_come_before_the_release():
    key = newest_gimp.version_key
    assert key("3.2.0-RC3") < key("3.2.0") < key("3.2.8") < key("3.3.2") < key("4.0.0-RC1")


def test_the_report_names_the_version_the_verdict_and_the_failures(tmp_path):
    spec = importlib.util.spec_from_file_location("junit_summary", ROOT / "ci" / "junit_summary.py")
    assert spec is not None and spec.loader is not None
    junit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(junit)
    report = tmp_path / "r.xml"
    report.write_text(
        '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1">'
        '<testcase classname="tests.e2e.test_a" name="test_ok"/>'
        '<testcase classname="tests.e2e.test_a" name="test_bad"><failure message="x"/></testcase>'
        "</testsuite></testsuites>"
    )
    text = junit.summary("GIMP 3.3.2", str(report))
    assert text.startswith("## GIMP 3.3.2: red") and "3 tests, 1 failed, 1 skipped." in text
    assert "- tests.e2e.test_a::test_bad" in text and "test_ok" not in text
    assert junit.summary("GIMP 3.3.2", str(tmp_path / "missing.xml")).startswith("## GIMP 3.3.2: no test report")

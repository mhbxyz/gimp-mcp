"""The release workflow publishes with trusted publishing only, TestPyPI first, PyPI after approval (#36)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish@release/v1"


def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


def steps_using(job: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [step for step in job.get("steps", []) if str(step.get("uses", "")).startswith(action)]


def test_publishing_happens_in_this_top_level_workflow():
    # PyPI trusted publishing does not accept reusable workflows: the publish jobs must live here.
    jobs = workflow()["jobs"]
    publishing = {name for name, job in jobs.items() if steps_using(job, PUBLISH_ACTION)}
    assert publishing == {"publish-testpypi", "publish-pypi"}


def test_publish_jobs_use_oidc_and_protected_environments():
    jobs = workflow()["jobs"]
    for name, environment in (("publish-testpypi", "testpypi"), ("publish-pypi", "pypi")):
        job = jobs[name]
        assert job["environment"]["name"] == environment
        assert job["permissions"] == {"id-token": "write"}
    testpypi = steps_using(jobs["publish-testpypi"], PUBLISH_ACTION)[0]
    assert testpypi["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    pypi = steps_using(jobs["publish-pypi"], PUBLISH_ACTION)[0]
    assert "repository-url" not in pypi.get("with", {})
    assert pypi.get("with", {}).get("skip-existing") is not True  # duplicates must fail loudly on PyPI


def test_pypi_receives_the_artifacts_verified_on_testpypi():
    jobs = workflow()["jobs"]
    assert "verify-testpypi" in jobs["publish-pypi"]["needs"]
    assert "publish-testpypi" in jobs["verify-testpypi"]["needs"]
    assert "publish-pypi" in jobs["verify-pypi"]["needs"]
    for name in ("publish-testpypi", "publish-pypi", "verify-testpypi", "verify-pypi"):
        downloads = steps_using(jobs[name], "actions/download-artifact")
        assert downloads and downloads[0]["with"]["name"] == "dist", name


def test_no_long_lived_secret_is_used():
    text = WORKFLOW.read_text()
    assert set(re.findall(r"secrets\.(\w+)", text)) <= {"GITHUB_TOKEN"}
    assert workflow()["permissions"] == {"contents": "read"}  # least privilege by default

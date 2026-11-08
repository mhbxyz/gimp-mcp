"""The release workflow publishes with trusted publishing only, TestPyPI first, PyPI after approval (#36)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish@release/v1"


def workflow() -> dict[Any, Any]:
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


def test_artifacts_get_build_provenance_attestations():
    jobs = workflow()["jobs"]
    attest = next(name for name, job in jobs.items() if steps_using(job, "actions/attest@v4"))
    job = jobs[attest]
    assert job["permissions"] == {"id-token": "write", "attestations": "write", "artifact-metadata": "write"}
    step = steps_using(job, "actions/attest@v4")[0]
    assert "dist/*.whl" in step["with"]["subject-path"] and "dist/*.tar.gz" in step["with"]["subject-path"]


def test_dry_run_publishes_nothing():
    jobs = workflow()["jobs"]
    dispatch = workflow()[True]["workflow_dispatch"]  # YAML 1.1 reads the `on` key as True
    assert dispatch["inputs"]["dry_run"]["type"] == "boolean"
    for name in ("attest", "github-draft", "publish-testpypi", "publish-pypi", "finalize"):
        assert "!inputs.dry_run" in jobs[name]["if"].replace(" ", ""), name


def test_github_release_becomes_public_only_after_pypi_is_verified():
    jobs = workflow()["jobs"]
    assert set(jobs["finalize"]["needs"]) >= {"verify-pypi", "github-draft"}
    assert "--draft=false" in str(jobs["finalize"]["steps"])


def test_reruns_are_safe():
    jobs = workflow()["jobs"]
    pypi_steps = str(jobs["publish-pypi"]["steps"])
    assert "--once" in pypi_steps  # upload skipped when the index already has these exact files
    assert "--clobber" in str(jobs["github-draft"]["steps"])  # the draft is updated, not duplicated


def test_merging_a_release_pr_tags_it_and_starts_the_release():
    tag = yaml.safe_load((ROOT / ".github" / "workflows" / "tag-release.yml").read_text())
    assert tag[True]["push"]["branches"] == ["main"]
    job = next(iter(tag["jobs"].values()))
    assert "Release v" in job["if"]  # only the merge of a "Release vX.Y.Z" PR
    text = str(job["steps"])
    assert "git tag" in text and "gh workflow run release.yml" in text
    assert job["permissions"] == {"contents": "write", "actions": "write"}


def test_installing_from_pypi_waits_for_the_index_to_serve_the_release():
    # PyPI's JSON API can list a release before its simple index (behind a CDN) serves it: v0.4.0's
    # install test failed that way right after upload. The install waits for the index first.
    steps = workflow()["jobs"]["verify-pypi"]["steps"]
    names = [step.get("name", "") for step in steps]
    wait = next(i for i, name in enumerate(names) if "index serves" in name)
    install = next(i for i, name in enumerate(names) if "installed from PyPI" in name)
    assert wait < install
    script = steps[wait]["run"]
    assert "--no-cache-dir" in script and "sleep" in script and "exit 1" in script

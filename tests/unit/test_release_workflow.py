"""The release workflow publishes with trusted publishing only, TestPyPI first, PyPI after approval (#36)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish@"


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
    attest = next(name for name, job in jobs.items() if steps_using(job, "actions/attest@"))
    job = jobs[attest]
    assert job["permissions"] == {"id-token": "write", "attestations": "write", "artifact-metadata": "write"}
    step = steps_using(job, "actions/attest@")[0]
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


def test_the_index_wait_asks_both_installers_used_afterwards():
    # v0.5.0: pip was served the release while uv, seconds later, was not, and the macOS install that
    # followed failed. Each wait now asks both installers the tests use.
    jobs = workflow()["jobs"]
    linux = next(step["run"] for step in jobs["verify-pypi"]["steps"] if "index serves" in step.get("name", ""))
    per_os = yaml.safe_load(OS_WORKFLOW.read_text())["jobs"]["gimp-tests"]["steps"]
    other = next(step["run"] for step in per_os if "index serves" in step.get("name", ""))
    for script in (linux, other):
        assert "pip download" in script and "uvx --no-cache --from" in script, script


# Release on every supported OS (#104): nothing is published before the full suite passed with a real
# GIMP on Linux, macOS and Windows, and the published package is installed and driven on each of them.
OS_WORKFLOW = ROOT / ".github" / "workflows" / "gimp-os-tests.yml"
OS_RUNNERS = {"macos-15", "windows-2025"}


def os_jobs(index: str) -> dict[str, Any]:
    """Jobs of the release that call the per-OS test workflow for ``index`` ('' = the built artifacts)."""
    return {
        name: job
        for name, job in workflow()["jobs"].items()
        if job.get("uses") == "./.github/workflows/gimp-os-tests.yml" and job["with"].get("index", "") == index
    }


def runners(job: dict[str, Any]) -> set[str]:
    return set(job["strategy"]["matrix"]["os"])


def test_the_full_suite_passes_on_every_os_before_anything_is_published():
    jobs = workflow()["jobs"]
    (name, job), *others = os_jobs("").items()
    assert others == [] and runners(job) == OS_RUNNERS and job["strategy"]["fail-fast"] is False
    assert job["with"]["tests"].split() == ["tests/unit", "tests/e2e"]  # the whole suite, built wheel included
    assert job["needs"] == "build" or "build" in job["needs"]
    for publishing in ("attest", "github-draft", "publish-testpypi"):
        assert {"test", name} <= set(jobs[publishing]["needs"]), publishing


def test_the_published_package_drives_gimp_on_every_os():
    jobs = workflow()["jobs"]
    for index, after, gates in (("testpypi", "publish-testpypi", ["publish-pypi"]),
                                ("pypi", "publish-pypi", ["finalize", "publish-mcp-registry"])):  # fmt: skip
        (name, job), *others = os_jobs(index).items()
        assert others == [] and runners(job) == OS_RUNNERS, index
        assert job["with"]["tests"] == "tests/e2e/test_distribution.py"
        assert after in job["needs"]
        for gated in gates:
            assert name in jobs[gated]["needs"], (gated, name)


def test_the_per_os_workflow_installs_pinned_gimp_and_never_publishes():
    os_workflow = yaml.safe_load(OS_WORKFLOW.read_text())
    assert set(os_workflow[True]) == {"workflow_call"}
    text = OS_WORKFLOW.read_text()
    assert "ci/install-gimp-macos.sh" in text and "ci/install-gimp-windows.ps1" in text  # SHA-256 verified
    assert "GIMP_MCP_REQUIRE_GIMP" in text  # a missing GIMP fails instead of skipping
    assert PUBLISH_ACTION not in text and "id-token" not in text
    # packages from TestPyPI are installed only after their SHA-256 matched the built artifacts
    assert "verify_published.py testpypi" in text and "--download" in text
    assert "index serves" in text  # PyPI's CDN lag (see the Linux job)


def test_a_pre_release_is_published_as_a_pre_release_and_not_in_the_mcp_registry():
    """#124: 1.0.0rc1 becomes a GitHub pre-release (not 'latest'); the MCP registry keeps the last release."""
    jobs = workflow()["jobs"]
    assert "--prerelease" in str(jobs["github-draft"]["steps"])
    assert "--prerelease" in str(jobs["finalize"]["steps"]) and "--latest=false" in str(jobs["finalize"]["steps"])
    assert "pre_release" in str(jobs["publish-mcp-registry"].get("if", ""))


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_every_action_is_pinned_to_a_commit():
    # A tag or branch can be moved to other code; the publish jobs run actions with an OIDC token (#122).
    for path in WORKFLOWS:
        for line in path.read_text().splitlines():
            match = re.search(r"uses:\s*([^\s#]+)", line)
            if match and not match.group(1).startswith("./"):
                assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", match.group(1)), f"{path.name}: {line.strip()}"
                assert re.search(r"#\s*v\d", line), f"{path.name}: say which version the commit is: {line.strip()}"


def test_every_workflow_declares_its_token_permissions():
    for path in WORKFLOWS:
        assert "permissions" in yaml.safe_load(path.read_text()), path.name


def test_the_registry_publisher_is_verified_and_cannot_publish_to_pypi():
    # The binary runs with an OIDC token: in the pypi environment it could have published to PyPI (#122).
    job = workflow()["jobs"]["publish-mcp-registry"]
    assert job["environment"]["name"] not in ("pypi", "testpypi")
    install = next(step["run"] for step in job["steps"] if "mcp-publisher" in step.get("name", ""))
    assert re.search(r"sha256sum (-c|--check)", install) and re.search(r"[0-9a-f]{64}", install)
    assert "| tar" not in install  # nothing is extracted before the check


def test_jobs_that_run_downloaded_builds_keep_no_token_in_the_checkout():
    nightly = yaml.safe_load((ROOT / ".github" / "workflows" / "gimp-next.yml").read_text())
    for job in nightly["jobs"].values():
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step.get("with", {}).get("persist-credentials") is False

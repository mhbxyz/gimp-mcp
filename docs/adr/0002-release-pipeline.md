# ADR 0002 — Publish to PyPI with trusted publishing, TestPyPI first

- Status: accepted (2026-11-08)
- Context issues: #36, #37

## Context

Users should install with `uv tool install gimp-mcp`, `pipx install gimp-mcp`
or `uvx gimp-mcp`. Publishing must not rely on long-lived secrets, must not
publish untested files, and must be verifiable afterwards.

Facts checked in the official documentation (2026-11-08):

* PyPI *trusted publishing* lets a GitHub Actions job exchange its OIDC token
  for a short-lived upload token; the job needs `permissions: id-token: write`
  and uses `pypa/gh-action-pypi-publish@release/v1`. A GitHub environment is
  optional but strongly recommended
  (<https://docs.pypi.org/trusted-publishers/using-a-publisher/>).
* A project that does not exist yet is created through a *pending publisher*
  (project name, owner/repository, workflow file, environment). It does **not**
  reserve the name: if someone registers it first, the pending publisher is
  invalidated (<https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>).
  On 2026-11-08 `gimp-mcp` was free on PyPI and TestPyPI.
* **Reusable workflows cannot be used as the workflow of a trusted publisher**
  (<https://docs.pypi.org/trusted-publishers/troubleshooting/>).
* The publish action uploads PEP 740 attestations by default with trusted
  publishing; its README advises `skip-existing` only for TestPyPI
  (<https://github.com/pypa/gh-action-pypi-publish>).

## Decision

* One top-level workflow, `.github/workflows/release.yml`, triggered by a
  `v*` tag (or re-run from the tag). Jobs: `build` (once, artifact `dist`) →
  `test` (full suite in the pinned GIMP image) → `github-draft` and
  `publish-testpypi` → `verify-testpypi` → `publish-pypi` → `verify-pypi`.
* Publish jobs run in the GitHub environments `testpypi` and `pypi`, which
  require the maintainer's approval and only accept `v*` tags. No token is
  stored anywhere.
* The very same `dist` artifact goes to TestPyPI and PyPI;
  `scripts/verify_published.py` checks that each index serves exactly the
  built files (SHA-256).
* TestPyPI verification installs the **downloaded, digest-checked wheel** with
  its dependencies from PyPI, instead of resolving against TestPyPI where
  anyone can upload a package named like a dependency (dependency confusion).
  PyPI verification installs from the index with `uv pip` and `uvx`.

## Consequences

* The maintainer must configure the two pending publishers once
  (`docs/releasing.md`).
* A release cannot reach PyPI without passing the real-GIMP suite twice and two
  explicit approvals.

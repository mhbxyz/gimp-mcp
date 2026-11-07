# Releasing

Releases are reproducible: the same commit always gives byte-identical
artifacts (`tests/unit/test_distribution.py::test_builds_are_reproducible`).

1. Update the version in `pyproject.toml` — the only place it is written
   (`tests/unit/test_versions.py` fails if a version string appears elsewhere) —
   and turn `## [Unreleased]` into a `## [X.Y.Z] - date` section of
   `CHANGELOG.md`.
2. Run the whole suite against the pinned GIMP: `ci/run-e2e.sh` (it includes
   `tests/e2e/test_distribution.py`, which installs the built wheel in a fresh
   virtualenv outside the source tree and drives GIMP through it).
3. Build: `scripts/build-release.sh` → `dist/` with the wheel, the sdist,
   `SHA256SUMS` and `RELEASE_NOTES.md` (the CHANGELOG section).
4. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`. The
   `Release (draft)` workflow re-runs the suite, rebuilds and creates a
   **draft** GitHub release with the artifacts. Review it and publish it by
   hand.
5. PyPI: approve the `publish-testpypi` deployment, check the TestPyPI page,
   then approve `publish-pypi`. Each upload is followed by an automatic check
   that the index serves exactly the built files and that the installed package
   (`uv pip install`, `uvx`) drives a real GIMP. See
   [ADR 0002](adr/0002-release-pipeline.md).

## One-time setup (maintainer)

PyPI uses *trusted publishing*: there is no token to create or store. Do this
once, before the first release:

1. **TestPyPI**: log in at <https://test.pypi.org>, open *Your account →
   Publishing → Add a new pending publisher → GitHub*, and enter exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `gimp-mcp` |
   | Owner | `mhbxyz` |
   | Repository name | `gimp-mcp` |
   | Workflow name | `release.yml` |
   | Environment name | `testpypi` |

2. **PyPI**: same at <https://pypi.org/manage/account/publishing/> with
   environment name `pypi`.
3. The GitHub environments `testpypi` and `pypi` already exist (*Settings →
   Environments*): they require your approval and only accept `v*` tags.

A pending publisher does not reserve the name: until the first upload,
someone else could register `gimp-mcp`. If the first upload fails with
`invalid-publisher`, compare owner, repository, workflow file and environment
on both sides.

Artifacts are checked for secrets and runtime files (tokens, sockets, caches,
`.env`, demo outputs) by `tests/unit/test_distribution.py`.

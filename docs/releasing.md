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
5. PyPI (optional, manual, maintainer only): `uv publish dist/*.whl dist/*.tar.gz`
   with a token that is never stored in the repository.

Artifacts are checked for secrets and runtime files (tokens, sockets, caches,
`.env`, demo outputs) by `tests/unit/test_distribution.py`.

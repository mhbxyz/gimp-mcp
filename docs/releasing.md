# Releasing

Releases are reproducible: the same commit always gives byte-identical
artifacts (`tests/unit/test_distribution.py::test_builds_are_reproducible`).

1. Update the version in `pyproject.toml`, `src/gimp_mcp/__init__.py` and
   `BRIDGE_VERSION` in `src/gimp_mcp/plugin/gimp-mcp-bridge/gimp-mcp-bridge.py`
   (a unit test checks they match), and add a `## [X.Y.Z] - date` section to
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

#!/usr/bin/env bash
# Build the release artifacts reproducibly and prepare the release notes.
#   scripts/build-release.sh            -> dist/ (wheel, sdist, SHA256SUMS, RELEASE_NOTES.md)
# Publishing is a separate, explicit step (see docs/releasing.md).
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(uv run --quiet python -c "import gimp_mcp; print(gimp_mcp.__version__)")
rm -rf dist
uv build --quiet --out-dir dist
(cd dist && sha256sum ./*.whl ./*.tar.gz > SHA256SUMS)
# Release notes = the CHANGELOG section of this version.
awk -v v="$version" '
  $0 ~ "^## \\[" v "\\]" {on=1; next}
  on && /^## \[/ {exit}
  on && /^\[[0-9]/ {exit}
  on {print}
' CHANGELOG.md > dist/RELEASE_NOTES.md
if ! grep -q '[^[:space:]]' dist/RELEASE_NOTES.md; then
  echo "error: no CHANGELOG entry for $version" >&2
  exit 1
fi
echo "Built gimp-mcp $version:" >&2
cat dist/SHA256SUMS >&2

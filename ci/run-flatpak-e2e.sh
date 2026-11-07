#!/usr/bin/env bash
# End-to-end tests against GIMP installed from Flathub, in a throw-away
# privileged container (bubblewrap needs it). The container's HOME is disposable:
# Flatpak GIMP always uses ~/.config/GIMP of the user.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${GIMP_MCP_FLATPAK_IMAGE:-gimp-mcp-flatpak-ci}
if [ -z "${GIMP_MCP_CI_SKIP_BUILD:-}" ]; then
  docker build -q -f ci/Dockerfile.flatpak -t "$IMAGE" ci >/dev/null
fi
docker run --rm --init --privileged -v "$PWD":/src:ro "$IMAGE" bash -euo pipefail -c '
  mkdir -p -m 700 "$XDG_RUNTIME_DIR"
  mkdir repo
  tar -C /src --exclude=.venv --exclude=ci-artifacts -cf - . | tar -C repo -xf -
  cd repo
  uv sync --frozen -q
  uv run pytest -ra tests/e2e/test_flatpak.py "$@"
' bash "$@"

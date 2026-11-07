#!/usr/bin/env bash
# Run the whole test suite (unit + end-to-end with a real GIMP) inside the
# pinned CI image, exactly like GitHub Actions does.
#   ci/run-e2e.sh                # all tests
#   ci/run-e2e.sh tests/e2e -x   # extra pytest arguments
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${GIMP_MCP_CI_IMAGE:-gimp-mcp-ci}
if [ -z "${GIMP_MCP_CI_SKIP_BUILD:-}" ]; then
  docker build -q -t "$IMAGE" ci >/dev/null
fi
mkdir -p ci-artifacts
chmod 777 ci-artifacts  # the container user may have another uid than the host user
docker run --rm \
  -v "$PWD":/src:ro \
  -v "$PWD/ci-artifacts":/artifacts \
  -e GIMP_MCP_REQUIRE_GIMP=1 \
  -e GIMP_MCP_LOG_DIR=/artifacts/gimp-logs \
  "$IMAGE" bash -euo pipefail -c '
    mkdir -p -m 700 "$XDG_RUNTIME_DIR"
    mkdir repo
    tar -C /src --exclude=.venv --exclude=.git --exclude=ci-artifacts -cf - . | tar -C repo -xf -
    cd repo
    gimp-console --version
    uv sync --frozen -q
    uv run pytest -ra --junitxml=/artifacts/junit.xml "$@"
  ' bash "$@"

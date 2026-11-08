#!/usr/bin/env bash
# GUI end-to-end tests (#105) on Linux: GIMP with its interface on a virtual display (Xvfb), keys
# sent with xdotool, inside ci/gui/Dockerfile (pinned Arch snapshot, GIMP 3.2).
#   ci/run-gui.sh                 # tests/gui
#   ci/run-gui.sh -k undo -x      # extra pytest arguments
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=${GIMP_MCP_GUI_IMAGE:-gimp-mcp-gui}
if [ -z "${GIMP_MCP_CI_SKIP_BUILD:-}" ]; then
  docker build -q -t "$IMAGE" ci/gui >/dev/null
fi
mkdir -p ci-artifacts && chmod 777 ci-artifacts
docker run --rm --init \
  -v "$PWD":/src:ro -v "$PWD/ci-artifacts":/artifacts \
  -e GIMP_MCP_GUI=1 -e GIMP_MCP_REQUIRE_GIMP=1 -e GIMP_MCP_LOG_DIR=/artifacts/gimp-logs \
  "$IMAGE" bash -euo pipefail -c '
    mkdir -p -m 700 "$XDG_RUNTIME_DIR"
    Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    export DISPLAY=:99
    for _ in $(seq 50); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.2; done
    mkdir repo && tar -C /src --exclude=.venv --exclude=ci-artifacts -cf - . | tar -C repo -xf -
    cd repo
    uv sync --frozen -q
    uv run pytest -ra --junitxml=/artifacts/junit-gui.xml tests/gui "$@"
  ' bash "$@"

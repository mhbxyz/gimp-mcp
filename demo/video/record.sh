#!/usr/bin/env bash
# Records the README demo: a real Claude Code session (left) driving a real GIMP
# 3.2 (right) through the gimp-mcp package published on PyPI, on a virtual
# 1920x1080 desktop inside Docker. Nothing on the host is read or changed
# besides the output directory.
#
#   CLAUDE_CODE_OAUTH_TOKEN=... demo/video/record.sh [VERSION] [OUTPUT_DIR]
#
# The token is the only credential passed in (`claude setup-token` creates one);
# the client runs in a fresh HOME with only the gimp server (--strict-mcp-config).
# Outputs: raw.mkv, demo.mp4, demo.webp, poster.png, thumbnail.png (see encode.sh).
set -euo pipefail
# OUTPUT_DIR is relative to the caller's directory, so resolve it before cd.
OUT=$(realpath -m "${2:-$(dirname "$0")/out}")
cd "$(dirname "$0")"
VERSION=${1:-$(cd ../.. && uv run --quiet python -c "import gimp_mcp; print(gimp_mcp.__version__)")}
CLAUDE_BIN=${CLAUDE_BIN:-$(readlink -f "$(command -v claude)")}
: "${CLAUDE_CODE_OAUTH_TOKEN:?set CLAUDE_CODE_OAUTH_TOKEN (claude setup-token)}"
NAME=gimp-mcp-video-$$

mkdir -p "$OUT"
docker build -q -t gimp-mcp-video . >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$NAME" --init -e CLAUDE_CODE_OAUTH_TOKEN -e DISABLE_AUTOUPDATER=1 \
  -e GIMP_MCP_VERSION="$VERSION" \
  -v "$PWD:/scene:ro" -v "$PWD/../assets:/home/demo/assets:ro" -v "$OUT:/out" \
  -v "$CLAUDE_BIN:/usr/local/bin/claude:ro" \
  gimp-mcp-video sleep infinity >/dev/null
docker exec "$NAME" /scene/scene.sh desktop
docker exec "$NAME" /scene/scene.sh record
./encode.sh "$OUT/raw.mkv" "$OUT"

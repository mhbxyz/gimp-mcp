#!/usr/bin/env bash
# Run the documented commands (README quickstart, docs/clients/*.md) in a clean Ubuntu 26.04 container.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -q -f ci/Dockerfile.doctests -t gimp-mcp-doctests ci >/dev/null
rm -rf dist-doctests && uv build -q --wheel --out-dir dist-doctests
chmod -R a+rX dist-doctests README.md docs tests
docker run --rm --init -e UV_FIND_LINKS=/dist \
  -v "$PWD/dist-doctests":/dist:ro -v "$PWD/README.md":/src/README.md:ro -v "$PWD/docs":/src/docs:ro \
  -v "$PWD/tests":/src/tests:ro gimp-mcp-doctests \
  uv run --quiet --no-project --python 3.12 /src/tests/docs/run_doctests.py

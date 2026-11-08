#!/usr/bin/env bash
# Runs INSIDE the evaluation container (evals/harness.py): installs gimp-mcp ($EVAL_PACKAGE: a wheel
# or gimp-mcp==X from PyPI) in a fresh virtualenv, starts a headless GIMP 3.2 with the bridge, and runs
# one Claude Code session on /run/eval/prompt.txt with only the gimp server (default toolsets),
# writing its stream-json transcript to /run/eval/transcript.jsonl. Inputs are in ~/inputs (read
# only), outputs go to ~/out. The token comes from CLAUDE_CODE_OAUTH_TOKEN and is never written.
set -euo pipefail
: "${CLAUDE_CODE_OAUTH_TOKEN:?}" "${EVAL_PACKAGE:?}" "${EVAL_BUDGET_USD:?}" "${EVAL_DISALLOWED:?}"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
uv venv --quiet /tmp/venv
uv pip install --quiet --python /tmp/venv/bin/python "$EVAL_PACKAGE"
cd "$HOME"
exec /tmp/venv/bin/python - <<'EOF'
import json, os, subprocess, sys
from pathlib import Path
from gimp_mcp.headless import HeadlessGimp

home = Path.home()
with HeadlessGimp() as gimp:
    config = {"mcpServers": {"gimp": {"command": "/tmp/venv/bin/gimp-mcp", "args": ["serve"],
                                      "env": {"GIMP_MCP_SOCKET": str(gimp.socket_path)}}}}
    (home / "mcp.json").write_text(json.dumps(config), encoding="utf-8")
    command = ["claude", "-p", Path("/run/eval/prompt.txt").read_text(encoding="utf-8"),
               "--output-format", "stream-json", "--verbose",
               "--strict-mcp-config", "--mcp-config", str(home / "mcp.json"),
               "--permission-mode", "dontAsk", "--allowedTools", "mcp__gimp",
               "--disallowedTools", *os.environ["EVAL_DISALLOWED"].split(),
               "--max-budget-usd", os.environ["EVAL_BUDGET_USD"]]
    if os.environ.get("EVAL_MODEL"):
        command += ["--model", os.environ["EVAL_MODEL"]]
    with open("/run/eval/transcript.jsonl", "w", encoding="utf-8") as transcript:
        code = subprocess.run(command, stdout=transcript, stdin=subprocess.DEVNULL, cwd=home).returncode
print(f"claude exited with {code}", file=sys.stderr)
EOF

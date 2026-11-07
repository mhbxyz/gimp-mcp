"""Execute the documented commands in a clean container, as a user would (ci/run-doctests.sh).

* `sudo apt-get update` is run first (a freshly created container has no package index);
* `gimp-mcp` comes from the wheel given in UV_FIND_LINKS until it is on PyPI;
* `claude` and `code` are fakes that record their arguments;
* each command runs in a pseudo-terminal and answers "y" to setup's questions;
* GIMP is started (headless) before the first `gimp-mcp doctor`, as the docs ask the user to.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.docs.doctest_blocks import blocks, commands

HOME = Path.home()
RUNTIME = Path(os.environ["XDG_RUNTIME_DIR"])
BIN = HOME / "fake-bin"
LOG = HOME / "fake-cli.log"
ORDER = ["quickstart", "claude-code", "claude-code-check", "claude-desktop", "claude-desktop-check",
         "vscode-cursor", "vscode-cursor-check", "generic", "generic-check"]  # fmt: skip

FAKE = """#!/bin/sh
echo "$(basename "$0") $*" >> {log}
case "$(basename "$0") $*" in
  "claude mcp add"*) touch {state} ;;
  "claude mcp get gimp"*) if [ -e {state} ]; then echo "gimp: uvx gimp-mcp serve"; exit 0; else exit 1; fi ;;
esac
exit 0
"""


def prepare() -> dict[str, str]:
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    BIN.mkdir(exist_ok=True)
    for name in ("claude", "code"):
        (BIN / name).write_text(FAKE.format(log=LOG, state=HOME / ".fake-claude-has-gimp"))
        (BIN / name).chmod(0o755)
    (HOME / ".config" / "Claude").mkdir(parents=True, exist_ok=True)  # Claude Desktop opened once
    (HOME / ".cursor").mkdir(exist_ok=True)  # Cursor opened once
    subprocess.run(["sudo", "apt-get", "update", "-qq"], check=True)
    env = dict(os.environ)
    # A login shell's PATH (the harness itself runs under `uv run`, which must not leak into it).
    env["PATH"] = f"{BIN}:{HOME / '.local/bin'}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT"):
        env.pop(name, None)
    return env


gimp: subprocess.Popen[bytes] | None = None


def start_gimp(env: dict[str, str]) -> None:
    """The user (re)starts GIMP after setup."""
    global gimp
    if gimp is not None:
        return
    desktop = {**env, "PATH": "/usr/local/bin:/usr/bin:/bin"}  # as started from the desktop
    gimp = subprocess.Popen(["gimp-console", "--no-interface"], env=desktop, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)  # fmt: skip
    socket = RUNTIME / "gimp-mcp" / "bridge.sock"
    deadline = time.monotonic() + 120
    while not socket.exists():
        assert time.monotonic() < deadline and gimp.poll() is None, "GIMP did not start the bridge"
        time.sleep(0.5)


def run(command: str, env: dict[str, str]) -> None:
    if "gimp-mcp doctor" in command:
        start_gimp(env)
    print(f"$ {command}", flush=True)
    proc = subprocess.run(["script", "-qec", command, "/dev/null"], input="y\n" * 8, text=True, env=env,
                          capture_output=True)  # fmt: skip
    print(proc.stdout[-3000:], flush=True)
    assert proc.returncode == 0, f"`{command}` exited with {proc.returncode}"


def main() -> int:
    env = prepare()
    found = {b.name: b for b in blocks("doctest")}
    assert sorted(found) == sorted(ORDER), sorted(found)
    try:
        for name in ORDER:
            for command in commands(found[name]):
                run(command, env)
    finally:
        if gimp is not None:
            os.killpg(gimp.pid, 15)
    calls = LOG.read_text()
    assert "claude mcp add --transport stdio --scope user gimp --" in calls, calls
    assert "code --add-mcp" in calls, calls
    for config in (HOME / ".config/Claude/claude_desktop_config.json", HOME / ".cursor/mcp.json"):
        entry = json.loads(config.read_text())["mcpServers"]["gimp"]
        assert entry["args"][-1] == "serve" and "gimp-mcp" in " ".join(entry["args"]), entry
    assert (HOME / ".config/GIMP/3.2/plug-ins/gimp-mcp-bridge/gimp-mcp-bridge.py").exists()
    print("documentation commands: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

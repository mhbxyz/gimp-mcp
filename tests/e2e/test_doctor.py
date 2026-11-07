"""Issue #39: the doctor on a real GIMP (temporary HOME: no real profile is read)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from gimp_mcp.headless import HeadlessGimp
from gimp_mcp.installer import uninstall_plugin


def doctor(gimp: HeadlessGimp, home: Path) -> tuple[int, dict]:
    env = {**os.environ, "HOME": str(home)}
    env.pop("XDG_CONFIG_HOME", None)
    proc = subprocess.run(
        [sys.executable, "-m", "gimp_mcp", "doctor", "--json", "--socket", str(gimp.socket_path),
         "--gimp-dir", str(gimp.config_dir)],
        capture_output=True, text=True, env=env, timeout=120,
    )  # fmt: skip
    data = json.loads(proc.stdout)
    return proc.returncode, {check["id"]: check for check in data["checks"]}


def test_doctor_passes_on_a_working_installation(gimp_factory: Callable[..., HeadlessGimp], tmp_path: Path):
    gimp = gimp_factory()
    code, checks = doctor(gimp, tmp_path)
    failures = {key: c["message"] for key, c in checks.items() if c["status"] == "fail"}
    assert code == 0 and failures == {}
    for key in ("gimp", "gimp-python", "plugin", "plugin-version", "plugin-registered", "socket-permissions",
                "connection"):  # fmt: skip
        assert checks[key]["status"] == "ok", (key, checks[key])


def test_doctor_explains_a_missing_plugin_and_a_stale_socket(gimp_factory: Callable[..., HeadlessGimp], tmp_path: Path):
    gimp = gimp_factory()
    gimp.kill()  # GIMP crashes: the socket file stays behind
    uninstall_plugin(gimp.config_dir)
    code, checks = doctor(gimp, tmp_path)
    assert code == 1
    assert checks["plugin"]["status"] == "fail" and "install-plugin" in checks["plugin"]["fix"]
    assert checks["connection"]["status"] == "fail" and "stale" in checks["connection"]["message"]

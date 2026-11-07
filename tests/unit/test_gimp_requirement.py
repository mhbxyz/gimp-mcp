"""An absent GIMP must never look like a passing end-to-end suite."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_e2e(require: bool) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["GIMP_MCP_GIMP_CONSOLE"] = "gimp-console-that-does-not-exist"
    env.pop("GIMP_MCP_REQUIRE_GIMP", None)
    if require:
        env["GIMP_MCP_REQUIRE_GIMP"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/e2e/test_connection.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_missing_gimp_is_skipped_with_an_explicit_reason_locally():
    proc = run_e2e(require=False)
    assert proc.returncode == 0, proc.stdout
    assert "skipped" in proc.stdout
    assert "gimp-console" in proc.stdout  # the reason is shown (-ra)


def test_missing_gimp_fails_when_gimp_is_required():
    proc = run_e2e(require=True)
    assert proc.returncode != 0, proc.stdout
    assert "GIMP_MCP_REQUIRE_GIMP" in proc.stdout

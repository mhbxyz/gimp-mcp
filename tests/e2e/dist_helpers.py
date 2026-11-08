"""Install gimp-mcp from a distribution into a fresh virtualenv, outside the source tree."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from gimp_mcp import platforms
from gimp_mcp.headless import system_path

ROOT = Path(__file__).resolve().parents[2]
# What to install (default: a wheel built from this tree):
#   GIMP_MCP_DIST_WHEEL=path/to.whl         a given wheel (e.g. downloaded from TestPyPI, digest verified)
#   GIMP_MCP_DIST_REQUIREMENT=gimp-mcp==X   from the configured index (PyPI), also checked with uvx
#   GIMP_MCP_DIST_VERSION=X                 expected version when it differs from this tree
WHEEL = os.environ.get("GIMP_MCP_DIST_WHEEL")
REQUIREMENT = os.environ.get("GIMP_MCP_DIST_REQUIREMENT")


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


@dataclass
class Installed:
    venv: Path
    exe: Path
    work: Path
    home: Path
    env: dict[str, str]

    def gimp_mcp(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run(str(self.exe), *args, cwd=self.work, env=self.env)


def package_to_install(tmp_path: Path) -> str:
    if WHEEL:
        return WHEEL
    if REQUIREMENT:
        return REQUIREMENT
    dist = tmp_path / "dist"
    assert run("uv", "build", "--quiet", "--wheel", "--out-dir", str(dist), cwd=ROOT).returncode == 0
    return str(next(dist.glob("*.whl")))


def venv_script(venv: Path, name: str) -> Path:
    """A console script of a virtual environment (Scripts\\*.exe on Windows, bin/* elsewhere)."""
    if platforms.CURRENT == "windows":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def venv_python(venv: Path) -> Path:
    return venv_script(venv, "python")


def install_distribution(tmp_path: Path) -> Installed:
    import shutil

    if shutil.which("uv") is None:
        pytest.skip("uv is needed to build and install the distribution")
    work, home = tmp_path / "work", tmp_path / "home"
    work.mkdir()
    home.mkdir()  # never read the real user's profiles or client configurations
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "XDG_CONFIG_HOME")}
    env["PATH"] = system_path(env.get("PATH", ""))
    env["HOME"] = str(home)
    target = package_to_install(tmp_path)
    venv = tmp_path / "venv"
    assert run("uv", "venv", "--quiet", "--python", sys.executable, str(venv), cwd=work).returncode == 0
    installed = run("uv", "pip", "install", "--quiet", "--python", str(venv_python(venv)), target, cwd=work, env=env)
    assert installed.returncode == 0, installed.stderr
    return Installed(venv, venv_script(venv, "gimp-mcp"), work, home, env)

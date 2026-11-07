"""The distributed artifacts are complete, consistent, reproducible and free of secrets (issue #17)."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

import gimp_mcp

ROOT = Path(__file__).resolve().parents[2]
SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
]
FORBIDDEN_NAMES = re.compile(r"(\.token$|\.sock$|__pycache__|\.pyc$|\.env$|ci-artifacts|demo/out|\.venv)")


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if shutil.which("uv") is None:
        pytest.skip("uv is needed to build the distribution")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "--quiet", "--out-dir", str(out)], cwd=ROOT, check=True, timeout=300)
    return {"wheel": next(out.glob("*.whl")), "sdist": next(out.glob("*.tar.gz"))}


def wheel_files(wheel: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel) as archive:
        return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def test_wheel_contains_the_server_and_the_complete_plugin(artifacts):
    names = set(wheel_files(artifacts["wheel"]))
    plugin = "gimp_mcp/plugin/gimp-mcp-bridge/"
    for module in ("gimp-mcp-bridge.py", "gmb_server.py", "gmb_ops.py", "gmb_policy.py", "gmb_undo.py"):
        assert plugin + module in names
    assert "gimp_mcp/server.py" in names


def test_artifacts_contain_no_secrets_nor_runtime_files(artifacts):
    contents = wheel_files(artifacts["wheel"])
    with tarfile.open(artifacts["sdist"]) as sdist:
        for member in sdist.getmembers():
            if member.isfile():
                extracted = sdist.extractfile(member)
                assert extracted is not None
                contents[member.name] = extracted.read()
    for name, data in contents.items():
        assert not FORBIDDEN_NAMES.search(name), name
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(data), f"{pattern.pattern!r} in {name}"


def test_metadata_declares_version_license_and_python(artifacts):
    contents = wheel_files(artifacts["wheel"])
    metadata = next(data for name, data in contents.items() if name.endswith("METADATA")).decode()
    assert f"Version: {gimp_mcp.__version__}" in metadata
    assert "License-Expression: MIT" in metadata
    assert "Requires-Python: >=3.11" in metadata
    license_files = [name for name in contents if name.endswith("licenses/LICENSE")]
    assert license_files and b"MIT License" in contents[license_files[0]]


def test_artifacts_derive_their_version_from_pyproject(artifacts):
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{gimp_mcp.__version__}"' in pyproject
    assert f"gimp_mcp-{gimp_mcp.__version__}-" in artifacts["wheel"].name
    plugin = wheel_files(artifacts["wheel"])["gimp_mcp/plugin/gimp-mcp-bridge/gimp-mcp-bridge.py"]
    assert b"BRIDGE_VERSION = _installed_version()" in plugin  # read from VERSION at install time


def test_changelog_has_an_entry_for_this_version():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## [{gimp_mcp.__version__}]" in changelog


def test_builds_are_reproducible(artifacts, tmp_path):
    subprocess.run(["uv", "build", "--quiet", "--wheel", "--out-dir", str(tmp_path)], cwd=ROOT, check=True)
    again = next(tmp_path.glob("*.whl"))

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert digest(again) == digest(artifacts["wheel"])

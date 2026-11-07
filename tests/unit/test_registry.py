"""MCP registry metadata (server.json) is valid, consistent and published by the release (#43)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

import gimp_mcp

ROOT = Path(__file__).resolve().parents[2]
SERVER = json.loads((ROOT / "server.json").read_text())
SCHEMA = json.loads((ROOT / "ci" / "schemas" / "server.schema.2025-12-11.json").read_text())
NAME = "io.github.mhbxyz/gimp-mcp"


def test_server_json_matches_the_official_schema():
    assert SERVER["$schema"] == SCHEMA["$id"]
    jsonschema.validate(SERVER, SCHEMA)


def test_server_json_describes_the_pypi_package_of_this_version():
    assert SERVER["name"] == NAME
    assert SERVER["version"] == gimp_mcp.__version__
    package = SERVER["packages"][0]
    assert (package["registryType"], package["identifier"], package["version"]) == (
        "pypi",
        "gimp-mcp",
        gimp_mcp.__version__,
    )
    assert package["runtimeHint"] == "uvx" and package["transport"] == {"type": "stdio"}
    socket = next(v for v in package["environmentVariables"] if v["name"] == "GIMP_MCP_SOCKET")
    assert socket["isRequired"] is False


def test_readme_proves_ownership_of_the_pypi_package():
    # The registry checks PyPI ownership through this marker in the package README.
    assert f"mcp-name: {NAME}" in (ROOT / "README.md").read_text()


def test_release_publishes_to_the_registry_after_pypi_with_oidc():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    job = workflow["jobs"]["publish-mcp-registry"]
    assert "verify-pypi" in job["needs"]
    assert job["permissions"] == {"id-token": "write"}
    assert job["environment"]["name"] == "pypi"
    text = str(job["steps"])
    assert "mcp-publisher login github-oidc" in text and "mcp-publisher publish" in text
    assert "v1.8.3" in text  # pinned publisher version
    assert "!inputs.dry_run" in job["if"].replace(" ", "")


def test_prepare_release_bumps_server_json(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("prepare_release", ROOT / "scripts" / "prepare_release.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bumped = json.loads(module.bump_server_json(json.dumps(SERVER), "9.9.9"))
    assert bumped["version"] == "9.9.9" and bumped["packages"][0]["version"] == "9.9.9"

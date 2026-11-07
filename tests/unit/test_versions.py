"""One version, and a clear error when the plug-in and the server disagree (issue #35)."""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

import pytest

import gimp_mcp
from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.errors import GimpMcpError
from gimp_mcp.installer import install_plugin
from gimp_mcp.versions import Compatibility, check_plugin_version

from .fake_bridge import DEFAULT_SESSION, running_fake_bridge

ROOT = Path(__file__).resolve().parents[2]


def test_the_package_version_comes_from_the_project_metadata():
    assert gimp_mcp.__version__ == importlib.metadata.version("gimp-mcp")


def test_no_version_number_is_hard_coded_outside_pyproject():
    version = re.escape(gimp_mcp.__version__)
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if re.search(rf"['\"]{version}['\"]", path.read_text())
    ]
    assert offenders == []


def test_installed_plugin_carries_the_package_version(tmp_path):
    target = install_plugin(tmp_path)
    assert (target / "VERSION").read_text().strip() == gimp_mcp.__version__


@pytest.mark.parametrize(
    ("server", "plugin", "verdict"),
    [
        ("0.2.0", "0.2.0", Compatibility.MATCH),
        ("0.2.3", "0.2.1", Compatibility.COMPATIBLE),
        ("1.4.0", "1.4.2", Compatibility.COMPATIBLE),
        ("0.2.0", "0.1.0", Compatibility.INCOMPATIBLE),
        ("1.0.0", "2.0.0", Compatibility.INCOMPATIBLE),
        ("0.2.0", "unknown", Compatibility.INCOMPATIBLE),
        ("0.2.0", "", Compatibility.INCOMPATIBLE),
    ],
)
def test_compatibility_rule(server, plugin, verdict):
    assert check_plugin_version(server, plugin) == verdict


async def test_connecting_to_an_incompatible_plugin_is_an_actionable_error():
    session = {**DEFAULT_SESSION, "bridge_version": "0.0.1"}
    with running_fake_bridge({"x": lambda p: {}}, session=session) as bridge:
        client = BridgeClient(BridgeEndpoint.for_socket(bridge.socket_path))
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("x")
        assert bridge.calls == []
    error = excinfo.value
    assert error.code == "PLUGIN_VERSION_MISMATCH"
    assert "gimp-mcp install-plugin" in (error.hint or "")
    assert error.details == {"plugin_version": "0.0.1", "server_version": gimp_mcp.__version__}


async def test_a_compatible_patch_difference_only_warns(caplog):
    major, minor, _patch = gimp_mcp.__version__.split(".")[:3]
    session = {**DEFAULT_SESSION, "bridge_version": f"{major}.{minor}.999"}
    with running_fake_bridge({"x": lambda p: {"ok": True}}, session=session) as bridge:
        client = BridgeClient(BridgeEndpoint.for_socket(bridge.socket_path))
        assert await client.call("x") == {"ok": True}
        await client.close()
    assert "plug-in" in caplog.text and "999" in caplog.text

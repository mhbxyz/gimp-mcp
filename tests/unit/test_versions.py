"""One version, and a clear error when the plug-in and the server disagree (issue #35)."""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

import pytest

import gimp_mcp
from gimp_mcp import versions
from gimp_mcp.bridge import BridgeClient
from gimp_mcp.errors import GimpMcpError
from gimp_mcp.installer import install_plugin
from gimp_mcp.versions import Compatibility, bundled_capabilities, check_plugin, gimp_support

from .fake_bridge import DEFAULT_SESSION, gmb_server, running_fake_bridge

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


def operations(names, value=None):
    return {name: (lambda p: value if value is not None else {}) for name in names}


CURRENT = bundled_capabilities()  # what an up-to-date plug-in serves
ALL = list(CURRENT)


@pytest.mark.parametrize(
    ("server", "plugin", "protocol", "capabilities", "verdict"),
    [
        ("0.7.0", "0.7.0", 1, None, Compatibility.MATCH),
        ("0.7.0", "0.8.3", 1, CURRENT | {"new.op": 1}, Compatibility.COMPATIBLE),
        ("1.4.0", "1.2.0", 1, dict(CURRENT), Compatibility.COMPATIBLE),
        ("0.7.0", "0.6.0", 1, None, Compatibility.PARTIAL),  # before 0.7.0: no capability list
        ("0.7.0", "0.7.1", 1, {name: CURRENT[name] for name in ALL[1:]}, Compatibility.PARTIAL),
        ("0.7.0", "0.7.0", 2, None, Compatibility.INCOMPATIBLE),
        ("0.7.0", "9.0.0", 99, dict(CURRENT), Compatibility.INCOMPATIBLE),
    ],
)
def test_compatibility_comes_from_the_protocol_and_the_operations(server, plugin, protocol, capabilities, verdict):
    assert check_plugin(server, plugin, protocol, capabilities).verdict is verdict


def test_partial_lists_the_missing_operations():
    check = check_plugin("0.7.0", "0.7.1", 1, {name: CURRENT[name] for name in ALL[1:]})
    assert check.missing == (ALL[0],)
    assert check_plugin("0.7.0", "0.6.0", 1, None).missing is None  # unknown: the plug-in does not say


def test_an_older_revision_is_partial(monkeypatch):
    monkeypatch.setattr(versions, "bundled_capabilities", lambda: {"image.scale": 2, "layer.create": 1})
    assert check_plugin("0.7.0", "0.6.9", 1, {"image.scale": 1, "layer.create": 1}).missing == ("image.scale",)


def test_the_bundled_plugin_lists_its_operations():
    capabilities = bundled_capabilities()
    assert {"hello", "session.images", "image.scale", "layer.create"} - {"hello"} <= set(capabilities)
    assert all(isinstance(revision, int) and revision >= 1 for revision in capabilities.values())


async def test_a_plugin_from_another_minor_version_is_accepted():
    session = {**DEFAULT_SESSION, "bridge_version": "0.0.1"}
    with running_fake_bridge({"x": lambda p: {"ok": True}}, session=session) as bridge:
        client = BridgeClient(bridge.endpoint)
        assert await client.call("x") == {"ok": True}
        await client.close()


async def test_a_newer_plugin_with_more_operations_is_accepted():
    session = {**DEFAULT_SESSION, "bridge_version": "9.1.0"}
    with running_fake_bridge(operations([*ALL, "x", "future.op"], {"ok": True}), session=session) as bridge:
        client = BridgeClient(bridge.endpoint)
        assert await client.call("x") == {"ok": True}
        assert client.plugin_check is not None and client.plugin_check.verdict is Compatibility.COMPATIBLE
        await client.close()


async def test_a_plugin_speaking_another_protocol_is_refused(monkeypatch):
    monkeypatch.setattr(gmb_server, "PROTOCOL_VERSION", 99)
    with running_fake_bridge({"x": lambda p: {}}) as bridge:
        client = BridgeClient(bridge.endpoint)
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("x")
        assert bridge.calls == []
    assert excinfo.value.code == "PLUGIN_VERSION_MISMATCH"
    assert "gimp-mcp install-plugin" in (excinfo.value.hint or "")
    assert excinfo.value.details["plugin_protocol"] == 99


async def test_an_operation_the_plugin_lacks_fails_before_anything_is_sent():
    session = {**DEFAULT_SESSION, "bridge_version": "0.0.1"}
    with running_fake_bridge({"x": lambda p: {}}, session=session) as bridge:
        client = BridgeClient(bridge.endpoint)
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("image.scale", {"image": 1})
        assert bridge.calls == []
        await client.close()
    error = excinfo.value
    assert error.code == "PLUGIN_VERSION_MISMATCH" and error.outcome == "not_applied"
    assert "gimp-mcp install-plugin" in (error.hint or "") and "restart GIMP" in (error.hint or "")
    assert error.details == {
        "operation": "image.scale",
        "revision": 1,
        "plugin_version": "0.0.1",
        "server_version": gimp_mcp.__version__,
    }


async def test_an_older_revision_of_an_operation_is_refused():
    with running_fake_bridge({"x": lambda p: {}}) as bridge:
        client = BridgeClient(bridge.endpoint)
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("x", revision=2)
        assert bridge.calls == []
        await client.close()
    assert excinfo.value.code == "PLUGIN_VERSION_MISMATCH" and excinfo.value.details["revision"] == 2


async def test_a_plugin_without_capability_list_gets_a_clear_error_for_unknown_operations():
    session = {**DEFAULT_SESSION, "bridge_version": "0.5.0"}
    with running_fake_bridge({"x": lambda p: {}}, session=session, legacy=True) as bridge:
        client = BridgeClient(bridge.endpoint)
        assert await client.call("x") == {}
        with pytest.raises(GimpMcpError) as unknown:
            await client.call("image.scale")
        with pytest.raises(GimpMcpError) as newer:
            await client.call("x", revision=2)
        assert client.plugin_check is not None and client.plugin_check.verdict is Compatibility.PARTIAL
        await client.close()
    assert unknown.value.code == "PLUGIN_VERSION_MISMATCH" and unknown.value.outcome == "not_applied"
    assert "0.5.0" in unknown.value.message and "image.scale" in unknown.value.message
    assert newer.value.code == "PLUGIN_VERSION_MISMATCH"


@pytest.mark.parametrize(
    ("gimp", "support"),
    [
        ("3.2.6", "supported"),
        ("3.2.8", "supported"),
        ("3.3.2", "best_effort"),
        ("3.4.0", "best_effort"),
        ("4.0.0", "best_effort"),
        ("3.0.4", "unsupported"),
        ("2.10.38", "unsupported"),
    ],
)
def test_gimp_version_policy(gimp, support):
    assert gimp_support(gimp) == support


async def test_a_newer_gimp_is_accepted_as_best_effort(caplog):
    session = {**DEFAULT_SESSION, "gimp_version": "3.4.0"}
    with running_fake_bridge({"x": lambda p: {"ok": True}}, session=session) as bridge:
        client = BridgeClient(bridge.endpoint)
        assert await client.call("x") == {"ok": True}
        await client.close()
    assert "3.4.0" in caplog.text and "best effort" in caplog.text


async def test_an_older_gimp_is_refused():
    session = {**DEFAULT_SESSION, "gimp_version": "3.0.4"}
    with running_fake_bridge({"x": lambda p: {}}, session=session) as bridge:
        client = BridgeClient(bridge.endpoint)
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("x")
        assert bridge.calls == []
    assert excinfo.value.code == "VERSION_INCOMPATIBLE"

"""Unit-test configuration per OS (ADR 0008).

* Tests of Linux behaviour (Flatpak, the Linux paths written by setup and doctor, the documented
  snippets) run with the platform layer pinned to Linux, so they check the same thing on every runner.
* On Windows, tests that need the Unix-socket bridge are skipped until the named-pipe transport
  exists (#100), and setup/doctor until their Windows locations do (#101, #103). pytest -ra lists them.
"""

from __future__ import annotations

import inspect
import sys

import pytest

from gimp_mcp import platforms

LINUX_SEMANTICS = {"test_flatpak", "test_setup", "test_uninstall", "test_doctor"}
WINDOWS_PENDING = {
    "test_setup": "setup on Windows: #101",
    "test_uninstall": "setup on Windows: #101",
    "test_doctor": "doctor on Windows: #103",
    "test_flatpak": "Flatpak is Linux only",
}
UNIX_BRIDGE_MARKERS = ("tool_client", "running_fake_bridge", "BridgeServer", "AF_UNIX", "HeadlessGimp")


def pytest_configure(config):
    config.addinivalue_line("markers", "linux_paths: run with the platform layer pinned to Linux")


@pytest.fixture(autouse=True)
def _pinned_platform(request, monkeypatch):
    module = request.module.__name__.rsplit(".", 1)[-1]
    if module in LINUX_SEMANTICS or request.node.get_closest_marker("linux_paths"):
        import gmb_platform  # type: ignore[import-not-found]  # the plug-in's copy

        monkeypatch.setattr(platforms, "CURRENT", "linux")
        monkeypatch.setattr(gmb_platform, "os_kind", lambda name=None: "linux")


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    sources: dict[str, str] = {}
    for item in items:
        module = item.module
        name = module.__name__.rsplit(".", 1)[-1]
        if item.get_closest_marker("linux_paths"):
            item.add_marker(pytest.mark.skip(reason="Linux paths cannot be written on Windows"))
            continue
        if name in WINDOWS_PENDING:
            item.add_marker(pytest.mark.skip(reason=WINDOWS_PENDING[name]))
            continue
        source = sources.setdefault(name, inspect.getsource(module))
        if any(marker in source for marker in UNIX_BRIDGE_MARKERS):
            item.add_marker(pytest.mark.skip(reason="the bridge has no Windows transport yet: #100"))

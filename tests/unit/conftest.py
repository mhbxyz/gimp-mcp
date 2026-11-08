"""Unit-test configuration per OS (ADR 0008).

* Tests of Linux behaviour (Flatpak, the Linux paths written by setup and doctor, the documented
  snippets) run with the platform layer pinned to Linux, so they check the same thing on every runner.
* On Windows the bridge is a named pipe (#100): tests of Unix-socket specifics (raw AF_UNIX
  clients, POSIX permissions) are skipped there, and setup/doctor until their Windows locations
  exist (#101, #103). pytest -ra lists every skip with its reason.
"""

from __future__ import annotations

import inspect
import sys

import pytest

from gimp_mcp import platforms

LINUX_SEMANTICS = {"test_flatpak", "test_setup", "test_uninstall", "test_doctor"}
WINDOWS_PENDING_TESTS = {
    "test_glob_stays_inside_its_directory": "batch globs on Windows paths: #102",
    "test_second_bridge_on_the_same_socket_refuses_to_start": "Unix socket; on Windows see "
    "test_a_second_bridge_cannot_take_the_pipe_name",
}
WINDOWS_PENDING = {
    "test_setup": "setup on Windows: #101",
    "test_uninstall": "setup on Windows: #101",
    "test_doctor": "doctor on Windows: #103",
    "test_flatpak": "Flatpak is Linux only",
}
UNIX_ONLY_MARKERS = (
    "AF_UNIX", "S_IMODE", "HeadlessGimp", "SO_PEERCRED", "os.getuid", "allowed_uid", "peer_uid",
    "running_fake_bridge_at",
)  # fmt: skip


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
    for item in items:
        name = item.module.__name__.rsplit(".", 1)[-1]
        if item.get_closest_marker("linux_paths"):
            item.add_marker(pytest.mark.skip(reason="Linux paths cannot be written on Windows"))
            continue
        if item.originalname in WINDOWS_PENDING_TESTS:
            item.add_marker(pytest.mark.skip(reason=WINDOWS_PENDING_TESTS[item.originalname]))
            continue
        if name in WINDOWS_PENDING:
            item.add_marker(pytest.mark.skip(reason=WINDOWS_PENDING[name]))
            continue
        source = inspect.getsource(item.function)
        if any(marker in source for marker in UNIX_ONLY_MARKERS):
            item.add_marker(pytest.mark.skip(reason="Unix-socket specifics (Windows uses a named pipe)"))

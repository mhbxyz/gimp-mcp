"""The Windows named-pipe bridge (#100, ADR 0008): only the current user may connect.

Runs on Windows only (the CI job `unit-os`); elsewhere the Unix-socket tests cover the same rules.
"""

from __future__ import annotations

import re

import pytest

from gimp_mcp import platforms
from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.errors import GimpMcpError

from .fake_bridge import running_fake_bridge

pytestmark = pytest.mark.skipif(platforms.CURRENT != "windows", reason="Windows named pipes")


def client_for(bridge, **kwargs) -> BridgeClient:
    return BridgeClient(BridgeEndpoint(socket_path=bridge.socket_path, token_path=bridge.token_path), **kwargs)


async def test_a_request_goes_through_the_pipe():
    with running_fake_bridge({"echo": lambda p: {"got": p["x"]}}) as bridge:
        assert str(bridge.socket_path).startswith("\\\\.\\pipe\\")
        assert (await client_for(bridge).call("echo", {"x": 7})) == {"got": 7}
        assert bridge.calls == [("echo", {"x": 7})]


def test_a_second_bridge_cannot_take_the_pipe_name():
    import gmb_pipe  # type: ignore[import-not-found]

    with running_fake_bridge({}) as bridge:
        listener = gmb_pipe.PipeListener(str(bridge.socket_path), gmb_pipe.process_user_sid())
        with pytest.raises(OSError, match="already serves"):
            listener.create_instance()


async def test_a_client_of_another_user_is_refused_before_any_request(monkeypatch):
    import gmb_pipe  # type: ignore[import-not-found]

    # the server's copy of gmb_pipe (on sys.path) sees every client as another user; the client side
    # loads its own copy (gimp_mcp.plugin_modules), so its check of the server is unaffected
    real = gmb_pipe.process_user_sid
    monkeypatch.setattr(gmb_pipe, "process_user_sid", lambda pid=None: real() if pid is None else "S-1-5-21-0-0-0-1")
    with running_fake_bridge({"echo": lambda p: {}}) as bridge:
        with pytest.raises(GimpMcpError) as refused:
            await client_for(bridge, connect_timeout=2).call("echo")
        assert refused.value.code in ("BRIDGE_UNAVAILABLE", "GIMP_NOT_RUNNING")
        assert bridge.calls == []


def test_the_pipe_dacl_names_only_the_current_user():
    import ctypes
    from ctypes import wintypes

    import gmb_pipe  # type: ignore[import-not-found]

    with running_fake_bridge({}) as bridge:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        # READ_CONTROL | GENERIC_READ | GENERIC_WRITE, OPEN_EXISTING
        handle = kernel32.CreateFileW(
            str(bridge.socket_path), 0x00020000 | 0x80000000 | 0x40000000, 0, None, 3, 0, None
        )
        assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()  # type: ignore[attr-defined]
        try:
            sddl = gmb_pipe.dacl_sddl(handle)
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
    me = gmb_pipe.process_user_sid()
    aces = re.findall(r"\(([^)]*)\)", sddl)
    owners = {gmb_pipe.canonical_sid(ace.split(";")[-1]) for ace in aces}  # "LA" is the built-in Administrator
    assert sddl.startswith("D:P") and owners == {me}, sddl

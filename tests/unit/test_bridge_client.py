from __future__ import annotations

import time

import pytest

from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.errors import GimpMcpError

from .fake_bridge import running_fake_bridge, short_tmpdir


def endpoint_for(bridge) -> BridgeEndpoint:
    return BridgeEndpoint(socket_path=bridge.socket_path, token_path=bridge.token_path)


async def test_client_handshakes_and_calls_an_operation():
    ops = {"session.images": lambda params: {"images": [{"id": 1, "name": "a.png"}]}}
    with running_fake_bridge(ops) as bridge:
        client = BridgeClient(endpoint_for(bridge))
        try:
            result = await client.call("session.images")
            assert result == {"images": [{"id": 1, "name": "a.png"}]}
            assert client.session is not None
            assert client.session.gimp_version == "3.2.6"
            assert client.session.session_id == "a1b2c3d4"
        finally:
            await client.close()


async def test_missing_bridge_fails_fast_with_actionable_error():
    directory = short_tmpdir()
    endpoint = BridgeEndpoint(socket_path=directory / "nope.sock", token_path=directory / "nope.sock.token")
    client = BridgeClient(endpoint, connect_timeout=1.0)
    started = time.monotonic()
    with pytest.raises(GimpMcpError) as excinfo:
        await client.call("session.images")
    assert time.monotonic() - started < 2.0
    assert excinfo.value.code == "GIMP_NOT_RUNNING"
    assert "install-plugin" in (excinfo.value.hint or "")
    directory.rmdir()


async def test_incompatible_gimp_version_is_reported():
    session = {"gimp_version": "3.0.4", "session_id": "s", "pid": 1}
    with running_fake_bridge({"x": lambda p: {}}, session=session) as bridge:
        client = BridgeClient(endpoint_for(bridge))
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("x")
        assert excinfo.value.code == "VERSION_INCOMPATIBLE"
        assert excinfo.value.details["gimp_version"] == "3.0.4"
        assert bridge.calls == []


async def test_wrong_token_is_rejected_before_any_operation_runs():
    with running_fake_bridge({"x": lambda p: {}}) as bridge:
        bridge.token_path.write_text("not-the-token")
        client = BridgeClient(endpoint_for(bridge))
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("x")
        assert excinfo.value.code == "UNAUTHORIZED"
        assert bridge.calls == []


async def test_operation_errors_are_structured():
    from gmb_server import BridgeError  # type: ignore[import-not-found]

    def failing(params):
        raise BridgeError("NOT_FOUND", "image 7 does not exist", {"image": 7})

    with running_fake_bridge({"image.get": failing}) as bridge:
        client = BridgeClient(endpoint_for(bridge))
        try:
            with pytest.raises(GimpMcpError) as excinfo:
                await client.call("image.get", {"image": 7})
            assert excinfo.value.code == "NOT_FOUND"
            assert excinfo.value.details == {"image": 7}
            # the connection survives an operation error
            bridge.ops["image.get"] = lambda p: {"ok": True}
            bridge.server.operations["image.get"] = lambda p: {"ok": True}
            assert await client.call("image.get") == {"ok": True}
        finally:
            await client.close()


async def test_request_pinned_to_another_session_is_refused_by_the_bridge():
    with running_fake_bridge({"x": lambda p: {"ran": True}}) as bridge:
        client = BridgeClient(endpoint_for(bridge))
        try:
            with pytest.raises(GimpMcpError) as excinfo:
                await client.call("x", {"_session": "deadbeef"}, mutating=True)
            assert excinfo.value.code == "SESSION_CHANGED"
            assert excinfo.value.outcome == "not_applied"
            assert bridge.calls == []
            assert await client.call("x", {"_session": "a1b2c3d4"}) == {"ran": True}
            assert bridge.calls == [("x", {})]
        finally:
            await client.close()


async def test_frozen_gimp_does_not_block_forever():
    """A socket that accepts but never answers (GIMP busy or hung)."""
    import socket as socketlib

    directory = short_tmpdir()
    path = directory / "frozen.sock"
    listener = socketlib.socket(socketlib.AF_UNIX)
    listener.bind(str(path))
    listener.listen(1)
    (directory / "frozen.sock.token").write_text("t")
    client = BridgeClient(BridgeEndpoint.for_socket(path), connect_timeout=0.5)
    started = time.monotonic()
    try:
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("session.images")
        assert excinfo.value.code == "BRIDGE_UNAVAILABLE"
        assert time.monotonic() - started < 2.0
    finally:
        listener.close()
        for p in directory.iterdir():
            p.unlink()
        directory.rmdir()


async def test_stale_socket_after_gimp_exit_reports_not_running():
    import socket as socketlib

    directory = short_tmpdir()
    path = directory / "stale.sock"
    listener = socketlib.socket(socketlib.AF_UNIX)
    listener.bind(str(path))
    listener.close()  # file stays, nobody listens
    (directory / "stale.sock.token").write_text("t")
    client = BridgeClient(BridgeEndpoint.for_socket(path), connect_timeout=0.5)
    with pytest.raises(GimpMcpError) as excinfo:
        await client.call("session.images")
    assert excinfo.value.code == "GIMP_NOT_RUNNING"
    for p in directory.iterdir():
        p.unlink()
    directory.rmdir()

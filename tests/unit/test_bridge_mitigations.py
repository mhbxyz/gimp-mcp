"""Bridge mitigations that the security review for 1.0 found without a test (#122, docs/security.md)."""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import time

import gmb_server  # type: ignore[import-not-found]
import pytest

from gimp_mcp.bridge import BridgeClient
from gimp_mcp.errors import GimpMcpError

from .fake_bridge import running_fake_bridge, short_tmpdir

unix_only = pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets (Windows: test_windows_pipe.py)")


def hello(token: str) -> bytes:
    return json.dumps({"id": 1, "method": "hello", "params": {"token": token, "protocol": 1}}).encode() + b"\n"


def server_at(directory, **kwargs) -> gmb_server.BridgeServer:
    return gmb_server.BridgeServer(
        str(directory / "bridge.sock"), token="t" * 64, operations={}, session_info={"session_id": "a1b2c3d4"}, **kwargs
    )


@unix_only
def test_the_plugin_refuses_a_socket_directory_of_another_user(monkeypatch):
    # The /tmp fallback is predictable: another user may create the directory first (C1).
    directory = short_tmpdir()
    try:
        server = server_at(directory)
        me = os.getuid()
        monkeypatch.setattr(gmb_server.os, "getuid", lambda: me + 1)
        with pytest.raises(gmb_server.BridgeError) as refused:
            server.start()
        assert refused.value.code == "UNSAFE_SOCKET_DIR"
        assert not (directory / "bridge.sock").exists() and not (directory / "bridge.sock.token").exists()
    finally:
        directory.rmdir()


@unix_only
def test_the_plugin_makes_its_socket_directory_private_and_binds_with_a_private_umask(monkeypatch):
    directory = short_tmpdir()
    directory.chmod(0o755)
    masks: list[int] = []

    class Spy(socket.socket):
        def bind(self, address):
            mask = os.umask(0)
            os.umask(mask)
            masks.append(mask)
            super().bind(address)

    try:
        server = server_at(directory)
        monkeypatch.setattr(gmb_server.socket, "socket", Spy)
        server.start()
        try:
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700  # C1: tightened
            assert masks == [0o177]  # C11: the socket is never accessible to others, not even briefly
        finally:
            server.close()
        # C10: the token does not outlive the session.
        assert not (directory / "bridge.sock.token").exists() and not (directory / "bridge.sock").exists()
    finally:
        directory.rmdir()


async def test_an_answer_to_another_request_drops_the_connection():
    # C5: a response whose id is not the request's cannot be trusted to describe what happened.
    with running_fake_bridge({"x": lambda p: {"ok": True}}) as bridge:
        original = bridge.server._send

        def shifted(conn, message):
            if "session_id" not in (message.get("result") or {}):
                message = {**message, "id": message["id"] + 1}
            return original(conn, message)

        bridge.server._send = shifted
        client = BridgeClient(bridge.endpoint)
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("x", mutating=True)
        assert excinfo.value.code == "PROTOCOL_ERROR" and excinfo.value.outcome == "unknown"
        bridge.server._send = original
        assert await client.call("x") == {"ok": True}  # on a new connection
        await client.close()


async def test_an_oversized_answer_drops_the_connection_and_the_server_keeps_working(monkeypatch):
    # C7: the client reads at most MAX_RESPONSE_BYTES per answer.
    from gimp_mcp import bridge as bridge_module

    monkeypatch.setattr(bridge_module, "MAX_RESPONSE_BYTES", 64 * 1024)
    with running_fake_bridge({"big": lambda p: {"data": "x" * 100_000}, "x": lambda p: {}}) as bridge:
        client = BridgeClient(bridge.endpoint)
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("big")
        assert excinfo.value.code == "DISCONNECTED"
        assert await client.call("x") == {}
        await client.close()


@unix_only
def test_a_client_that_never_reads_cannot_block_the_bridge(monkeypatch):
    # C6: the answer is abandoned after the send timeout, and the next client is served.
    monkeypatch.setattr(gmb_server, "SEND_TIMEOUT_SECONDS", 0.5)
    with running_fake_bridge({"big": lambda p: {"data": "x" * (32 * 1024 * 1024)}, "x": lambda p: {}}) as bridge:
        token = bridge.token_path.read_text()
        stalled = socket.socket(socket.AF_UNIX)
        stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        stalled.connect(str(bridge.socket_path))
        stalled.sendall(hello(token) + json.dumps({"id": 2, "method": "big", "params": {}}).encode() + b"\n")
        try:
            started = time.monotonic()
            with socket.socket(socket.AF_UNIX) as other:
                other.settimeout(10)
                other.connect(str(bridge.socket_path))
                other.sendall(hello(token))
                assert b"session_id" in other.makefile("rb").readline()
            assert time.monotonic() - started < 8
        finally:
            stalled.close()

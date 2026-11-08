"""The bridge protocol without a transport (#100): bytes in, JSON lines out.

The Unix socket (Linux, macOS) and the Windows named pipe feed the same protocol core, so its rules
(hello first, token, framing, size limit) are checked here once for both.
"""

from __future__ import annotations

import json

import gmb_server  # type: ignore[import-not-found]


class Recorder:
    """A transport double: records what the server sends."""

    def __init__(self):
        self.sent = b""
        self.closed = False

    def sendall(self, data):
        self.sent += data

    def settimeout(self, _value):
        pass

    def setblocking(self, _flag):
        pass

    def close(self):
        self.closed = True

    def fileno(self):
        return id(self)

    def lines(self):
        return [json.loads(line) for line in self.sent.splitlines()]


def server(**kwargs):
    return gmb_server.BridgeServer(
        "unused", token="t0k", operations={"echo": lambda p: p}, session_info={"session_id": "s"}, allowed_uid=0,
        **kwargs,
    )  # fmt: skip


def test_bytes_split_anywhere_still_make_requests():
    bridge = server()
    wire = Recorder()
    conn = bridge.add_connection(wire, peer_uid=None)
    data = (
        b'{"id": 1, "method": "hello", "params": {"token": "t0k"}}\n{"id": 2, "method": "echo", "params": {"a": 1}}\n'
    )
    for i in range(0, len(data), 7):  # arbitrary chunks, as a pipe or a socket may deliver them
        assert bridge.handle_data(conn, data[i : i + 7])
    assert [m["id"] for m in wire.lines()] == [1, 2] and wire.lines()[1]["result"] == {"a": 1}


def test_wrong_token_closes_the_connection_before_any_operation():
    calls = []
    bridge = gmb_server.BridgeServer(
        "unused", token="t0k", operations={"echo": calls.append}, session_info={}, allowed_uid=0
    )
    wire = Recorder()
    conn = bridge.add_connection(wire, peer_uid=None)
    ok = bridge.handle_data(conn, b'{"id": 1, "method": "hello", "params": {"token": "nope"}}\n')
    assert ok is False and wire.closed and calls == []
    assert wire.lines()[0]["error"]["code"] == "UNAUTHORIZED"


def test_an_oversized_request_is_refused():
    bridge = server(max_request_bytes=64)
    wire = Recorder()
    conn = bridge.add_connection(wire, peer_uid=None)
    assert bridge.handle_data(conn, b"x" * 100) is False
    assert wire.lines()[0]["error"]["code"] == "REQUEST_TOO_LARGE" and wire.closed

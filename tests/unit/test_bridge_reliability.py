"""Security and reliability of the local bridge (issue #4)."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import stat
import time

import pytest

from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.errors import GimpMcpError

from .fake_bridge import running_fake_bridge


def client_for(bridge, **kwargs) -> BridgeClient:
    return BridgeClient(BridgeEndpoint.for_socket(bridge.socket_path), **kwargs)


# -- access control ---------------------------------------------------------------


def test_bridge_listens_on_a_private_unix_socket_only():
    with running_fake_bridge({}) as bridge:
        listener = bridge.server.listener
        assert listener.family == socket.AF_UNIX
        assert stat.S_IMODE(os.stat(bridge.socket_path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(bridge.socket_path.parent).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(bridge.token_path).st_mode) == 0o600


async def test_connection_from_another_uid_is_closed_before_any_request():
    with running_fake_bridge({"x": lambda p: {}}, allowed_uid=os.getuid() + 1) as bridge:
        with pytest.raises(GimpMcpError) as excinfo:
            await client_for(bridge, connect_timeout=1).call("x")
        assert excinfo.value.code == "BRIDGE_UNAVAILABLE"
        assert bridge.calls == []


def test_request_before_hello_is_refused_and_connection_closed():
    with running_fake_bridge({"x": lambda p: {"ran": True}}) as bridge:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(2)
            sock.connect(str(bridge.socket_path))
            sock.sendall(b'{"id": 1, "method": "x", "params": {}}\n')
            data = sock.makefile("rb").readline()
            assert b"UNAUTHORIZED" in data
            assert sock.recv(10) == b""  # closed by the bridge
        assert bridge.calls == []


def test_oversized_request_is_refused():
    with running_fake_bridge({}) as bridge:
        bridge.server.max_request_bytes = 1024
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(2)
            sock.connect(str(bridge.socket_path))
            sock.sendall(b"x" * 4096)
            data = sock.makefile("rb").readline()
            assert b"REQUEST_TOO_LARGE" in data


def test_second_bridge_on_the_same_socket_refuses_to_start():
    import gmb_server  # type: ignore[import-not-found]

    with running_fake_bridge({}) as bridge:
        other = gmb_server.BridgeServer(bridge.socket_path, token="t", operations={}, session_info={"session_id": "x"})
        with pytest.raises(gmb_server.BridgeError) as excinfo:
            other.start()
        assert excinfo.value.code == "BRIDGE_ALREADY_RUNNING"


# -- timeouts, disconnections, cancellation ----------------------------------------


def slow(seconds: float):
    def op(params):
        time.sleep(seconds)
        return {"slow": True}

    return op


async def test_timed_out_mutation_reports_unknown_outcome_and_next_call_gets_its_own_answer():
    ops = {"slow": slow(0.6), "fast": lambda p: {"echo": p["n"]}}
    with running_fake_bridge(ops) as bridge:
        client = client_for(bridge, request_timeout=0.2)
        try:
            with pytest.raises(GimpMcpError) as excinfo:
                await client.call("slow", mutating=True)
            assert excinfo.value.code == "TIMEOUT"
            assert excinfo.value.outcome == "unknown"
            assert await client.call("fast", {"n": 7}, timeout=5) == {"echo": 7}
        finally:
            await client.close()


async def test_timed_out_read_has_no_outcome():
    with running_fake_bridge({"slow": slow(0.5)}) as bridge:
        client = client_for(bridge, request_timeout=0.2)
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("slow")
        assert excinfo.value.outcome is None
        await client.close()


async def test_cancelled_request_never_leaks_its_late_answer_into_the_next_one():
    ops = {"slow": slow(0.5), "fast": lambda p: {"echo": p["n"]}}
    with running_fake_bridge(ops) as bridge:
        client = client_for(bridge)
        try:
            task = asyncio.create_task(client.call("slow", mutating=True))
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await client.call("fast", {"n": 1}) == {"echo": 1}
        finally:
            await client.close()


async def test_after_a_cancelled_request_the_next_call_waits_for_gimp_to_finish_it():
    """GIMP answers the reconnection handshake only after the abandoned operation: wait for it."""
    ops = {"slow": slow(1.5), "fast": lambda p: {"echo": p["n"]}}
    with running_fake_bridge(ops) as bridge:
        client = client_for(bridge, connect_timeout=0.5, request_timeout=10)
        try:
            task = asyncio.create_task(client.call("slow", mutating=True))
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            started = time.monotonic()
            assert await client.call("fast", {"n": 2}) == {"echo": 2}
            assert time.monotonic() - started > 1  # it waited for the slow operation
            # once GIMP answered, a busy-looking bridge fails fast again
            assert client._handshake_timeout() == 0.5  # pyright: ignore[reportPrivateUsage]
        finally:
            await client.close()


async def test_bridge_dying_mid_request_reports_disconnected_with_unknown_outcome():
    holder = {}

    def die(params):
        holder["bridge"].server.close()  # GIMP crashes while executing
        return {"never": "sent"}

    with running_fake_bridge({"die": die}) as bridge:
        holder["bridge"] = bridge
        client = client_for(bridge, request_timeout=3)
        started = time.monotonic()
        with pytest.raises(GimpMcpError) as excinfo:
            await client.call("die", mutating=True)
        assert time.monotonic() - started < 3
        assert excinfo.value.code == "DISCONNECTED"
        assert excinfo.value.outcome == "unknown"
        await client.close()


async def test_client_reconnects_after_the_bridge_restarts():
    with running_fake_bridge({"x": lambda p: {"gen": 1}}) as first:
        path = first.socket_path
        client = client_for(first)
        assert await client.call("x") == {"gen": 1}
    # same path, new bridge (GIMP restarted)
    from .fake_bridge import running_fake_bridge_at

    with running_fake_bridge_at(path, {"x": lambda p: {"gen": 2}}, session_id="newsess2"):
        # a mutation must not fail just because the old connection died meanwhile
        assert await client.call("x", mutating=True) == {"gen": 2}
        assert client.session is not None
        assert client.session.session_id == "newsess2"
    await client.close()


# -- ordering ------------------------------------------------------------------------


async def test_concurrent_mutations_run_in_issue_order_and_answers_are_not_mixed():
    seen: list[int] = []

    def record(params):
        seen.append(params["n"])
        time.sleep(0.005)
        return {"n": params["n"]}

    with running_fake_bridge({"record": record}) as bridge:
        client = client_for(bridge)
        try:
            results = await asyncio.gather(*(client.call("record", {"n": n}, mutating=True) for n in range(30)))
        finally:
            await client.close()
    assert [r["n"] for r in results] == list(range(30))
    assert seen == list(range(30))


async def test_two_clients_are_served_one_request_at_a_time():
    active = {"now": 0, "max": 0}

    def critical(params):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        time.sleep(0.01)
        active["now"] -= 1
        return {}

    with running_fake_bridge({"critical": critical}) as bridge:
        a, b = client_for(bridge), client_for(bridge)
        try:
            await asyncio.gather(*(c.call("critical", mutating=True) for c in (a, b) for _ in range(10)))
        finally:
            await a.close()
            await b.close()
    assert active["max"] == 1


# -- logs -----------------------------------------------------------------------------


async def test_logs_never_contain_the_token(caplog, capfd):
    caplog.set_level(logging.DEBUG)
    with running_fake_bridge({"x": lambda p: {}}) as bridge:
        client = client_for(bridge)
        await client.call("x")
        await client.close()
        bridge.token_path.write_text("wrong-token-value")
        with pytest.raises(GimpMcpError):
            await client_for(bridge).call("x")
        token = bridge.token
    captured = capfd.readouterr()
    everything = caplog.text + captured.out + captured.err
    assert token not in everything
    assert "wrong-token-value" not in everything

"""Run the real plug-in bridge server (GIMP-independent part) with scripted operations.

This is the seam used by unit tests: the socket protocol, authentication,
framing and error mapping are the production code that runs inside GIMP; only
the operations (which would call the GIMP API) are replaced by test doubles.
"""

from __future__ import annotations

import os
import secrets
import selectors
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gmb_server  # type: ignore[import-not-found]

import gimp_mcp
from gimp_mcp import platforms
from gimp_mcp.bridge import BridgeEndpoint

Op = Callable[[dict[str, Any]], Any]


@dataclass
class FakeBridge:
    socket_path: Path
    token_path: Path
    token: str
    server: Any
    ops: dict[str, Op]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @property
    def endpoint(self) -> BridgeEndpoint:
        """Where a client finds this bridge: its socket or pipe, and its token file."""
        return BridgeEndpoint(socket_path=self.socket_path, token_path=self.token_path)


def short_tmpdir() -> Path:
    """AF_UNIX paths are limited to ~107 bytes: keep socket directories short."""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    if not os.path.isdir(base) or not os.access(base, os.W_OK):
        base = tempfile.gettempdir()
    return Path(tempfile.mkdtemp(prefix="gmcp-t-", dir=base))


DEFAULT_SESSION = {
    "gimp_version": "3.2.6",
    "session_id": "a1b2c3d4",
    "pid": 4242,
    "bridge_version": gimp_mcp.__version__,
}


@contextmanager
def running_fake_bridge(
    ops: dict[str, Op] | None = None,
    *,
    session: dict[str, Any] | None = None,
    allowed_uid: int | None = None,
    legacy: bool = False,
) -> Iterator[FakeBridge]:
    """``legacy``: play a plug-in from before 0.7.0, whose hello lists no capabilities."""
    directory = short_tmpdir()
    try:
        with running_fake_bridge_at(
            directory / "bridge.sock", ops, session=session, allowed_uid=allowed_uid, legacy=legacy
        ) as bridge:
            yield bridge
    finally:
        for p in directory.iterdir():
            p.unlink()
        directory.rmdir()


@contextmanager
def running_fake_bridge_at(
    socket_path: Path,
    ops: dict[str, Op] | None = None,
    *,
    session: dict[str, Any] | None = None,
    session_id: str | None = None,
    allowed_uid: int | None = None,
    legacy: bool = False,
) -> Iterator[FakeBridge]:
    token = secrets.token_hex(16)
    calls: list[tuple[str, dict[str, Any]]] = []

    def recording(name: str, fn: Op) -> Op:
        def wrapper(params: dict[str, Any]) -> Any:
            calls.append((name, params))
            return fn(params)

        return wrapper

    dispatch = {name: recording(name, fn) for name, fn in (ops or {}).items()}
    info = dict(session or DEFAULT_SESSION)
    if session_id is not None:
        info["session_id"] = session_id
    server = gmb_server.BridgeServer(
        socket_path,
        token=token,
        operations=dispatch,
        session_info=info,
        allowed_uid=getattr(os, "getuid", lambda: -1)() if allowed_uid is None else allowed_uid,
        advertise_capabilities=not legacy,
    )
    if platforms.CURRENT == "windows":
        with _serving_pipe(server) as served:
            yield FakeBridge(Path(served.socket_path), Path(served.token_path), token, served, dispatch, calls)
        return
    server.start()
    stop = threading.Event()

    def loop() -> None:
        gmb_server.run_with_selector(server, selectors.DefaultSelector(), stop)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield FakeBridge(socket_path, Path(server.token_path), token, server, dispatch, calls)
    finally:
        stop.set()
        thread.join(timeout=5)
        server.close()


@contextmanager
def _serving_pipe(server: Any) -> Iterator[Any]:
    """Windows: serve a unique named pipe; a worker thread plays GIMP's main loop (ADR 0008)."""
    import queue

    server.socket_path = r"\\.\pipe\gimp-mcp-test-" + secrets.token_hex(6)
    server.token_path = str(Path(tempfile.mkdtemp(prefix="gmcp-t-")) / "bridge.token")
    tasks: queue.Queue[Any] = queue.Queue()

    def main_loop() -> None:
        while (task := tasks.get()) is not None:
            fn, args = task
            fn(*args)

    worker = threading.Thread(target=main_loop, daemon=True)
    worker.start()
    server.start_pipe(lambda fn, *args: tasks.put((fn, args)))
    try:
        yield server
    finally:
        done = threading.Event()
        tasks.put((lambda: (server.close(), done.set()), ()))
        done.wait(5)
        tasks.put(None)
        worker.join(timeout=5)

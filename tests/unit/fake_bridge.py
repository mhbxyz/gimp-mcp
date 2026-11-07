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

Op = Callable[[dict[str, Any]], Any]


@dataclass
class FakeBridge:
    socket_path: Path
    token_path: Path
    token: str
    server: Any
    ops: dict[str, Op]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


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
}


@contextmanager
def running_fake_bridge(
    ops: dict[str, Op] | None = None,
    *,
    session: dict[str, Any] | None = None,
    allowed_uid: int | None = None,
) -> Iterator[FakeBridge]:
    directory = short_tmpdir()
    socket_path = directory / "bridge.sock"
    token = secrets.token_hex(16)
    ops = dict(ops or {})
    calls: list[tuple[str, dict[str, Any]]] = []

    def recording(name: str, fn: Op) -> Op:
        def wrapper(params: dict[str, Any]) -> Any:
            calls.append((name, params))
            return fn(params)

        return wrapper

    dispatch = {name: recording(name, fn) for name, fn in ops.items()}
    server = gmb_server.BridgeServer(
        socket_path,
        token=token,
        operations=dispatch,
        session_info=dict(session or DEFAULT_SESSION),
        allowed_uid=os.getuid() if allowed_uid is None else allowed_uid,
    )
    server.start()
    stop = threading.Event()

    def loop() -> None:
        sel = selectors.DefaultSelector()
        gmb_server.run_with_selector(server, sel, stop)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield FakeBridge(socket_path, Path(server.token_path), token, server, dispatch, calls)
    finally:
        stop.set()
        thread.join(timeout=5)
        server.close()
        for p in directory.iterdir():
            p.unlink()
        directory.rmdir()

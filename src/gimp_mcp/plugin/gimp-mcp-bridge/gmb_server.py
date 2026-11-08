"""GIMP-independent part of the gimp-mcp bridge (runs inside GIMP's Python).

This module must only use the standard library: GIMP launches the plug-in with
the system Python, outside of gimp-mcp's virtual environment. It implements the
local socket server, authentication and the JSON-lines protocol. Operations
that touch GIMP are injected as plain callables, which keeps this file testable
without GIMP.

Protocol (one JSON object per line, UTF-8):

    request:  {"id": <int>, "method": "<name>", "params": {...}}
    response: {"id": <int>, "result": {...}}
           or {"id": <int>, "error": {"code": "...", "message": "...", "details": {...}}}

The first request of every connection must be ``hello`` carrying the token
read from the token file; anything else closes the connection.
"""

from __future__ import annotations

import errno
import json
import os
import socket
import stat
import sys
import traceback
from collections.abc import Callable
from typing import Any

import gmb_platform

PROTOCOL_VERSION = 1
DEFAULT_MAX_REQUEST_BYTES = 8 * 1024 * 1024
SEND_TIMEOUT_SECONDS = 10.0


def default_socket_path(environ: dict[str, str]) -> str:
    """Socket location (gmb_platform.bridge_address, mirrored by gimp_mcp.platforms)."""
    return gmb_platform.bridge_address(environ)[1]


def gimp_session_id(gimp_pid: int | None = None) -> str:
    """Identify the GIMP process: stable while it runs, different after a restart.

    Derived from GIMP's pid and start time (where the OS gives it), so restarting only the
    bridge keeps the ids valid while restarting GIMP invalidates them.
    """
    import hashlib

    pid = os.getppid() if gimp_pid is None else gimp_pid
    start = gmb_platform.process_start(pid) or secrets_token()
    return hashlib.sha256(("%d:%s" % (pid, start)).encode()).hexdigest()[:8]


def secrets_token() -> str:
    import secrets

    return secrets.token_hex(8)


class BridgeError(Exception):
    """An anticipated failure, reported to the client as a structured error."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_wire(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        return error


def log(message: str) -> None:
    """Log to stderr (GIMP's console). Never log image data or the token."""
    try:
        sys.stderr.write("[gimp-mcp-bridge] %s\n" % message)
        sys.stderr.flush()
    except Exception:
        pass


def _peer_uid(sock: socket.socket) -> int | None:
    return gmb_platform.peer_uid(sock)


class Connection:
    """A client connection; ``sock`` is any transport with sendall/close (a socket, a Windows pipe)."""

    def __init__(self, sock: Any, peer_uid: int | None, connection_id: int = 0):
        self.id = connection_id
        self.sock = sock
        self.peer_uid = peer_uid
        self.buffer = b""
        self.authenticated = False
        self.dropped = False

    def fileno(self) -> int:
        return self.sock.fileno()


class BridgeServer:
    def __init__(
        self,
        socket_path: Any,
        *,
        token: str,
        operations: dict[str, Callable[[dict[str, Any]], Any]],
        session_info: dict[str, Any],
        allowed_uid: int | None = None,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        token_path: str | None = None,
    ):
        self.socket_path = str(socket_path)
        self.token_path = token_path or self.socket_path + ".token"
        self.token = token
        self.operations = operations
        self.session_info = session_info
        # Unix sockets check the peer uid; Windows pipes check the client's user SID (gmb_pipe).
        self.allowed_uid = getattr(os, "getuid", lambda: -1)() if allowed_uid is None else allowed_uid
        self.pipe_listener: Any = None
        self.max_request_bytes = max_request_bytes
        self.listener: socket.socket | None = None
        self.connections: dict[int, Connection] = {}
        self.on_quit: Callable[[], None] | None = None
        # Called with the connection id when a client goes away.
        self.on_disconnect: list = []
        # Id of the connection whose request is being executed (for operations
        # that keep per-client state, e.g. undo groups).
        self.current_connection_id = None
        self.last_connection_id = None
        self._next_connection_id = 0

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        directory = os.path.dirname(self.socket_path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        info = os.stat(directory)
        if info.st_uid != os.getuid():
            raise BridgeError("UNSAFE_SOCKET_DIR", "socket directory %s is not owned by this user" % directory)
        if stat.S_IMODE(info.st_mode) & 0o077:
            os.chmod(directory, 0o700)
        self._refuse_if_live_bridge()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old_umask = os.umask(0o177)
        try:
            listener.bind(self.socket_path)
        finally:
            os.umask(old_umask)
        os.chmod(self.socket_path, 0o600)
        listener.listen(8)
        listener.setblocking(False)
        self.listener = listener
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, self.token.encode("ascii"))
        finally:
            os.close(fd)
        log("listening on %s" % self.socket_path)

    def start_pipe(self, schedule: Callable[..., Any]) -> None:
        """Serve a Windows named pipe (``socket_path`` is its name); ``schedule(fn, *args)`` runs ``fn`` on
        the thread that owns this server (ADR 0008)."""
        import gmb_pipe

        sid = gmb_pipe.process_user_sid()
        self.pipe_listener = gmb_pipe.serve(self, schedule, sid, log)
        gmb_pipe.write_token(self.token_path, self.token)
        log("listening on %s" % self.socket_path)

    def _refuse_if_live_bridge(self) -> None:
        if not os.path.exists(self.socket_path):
            return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        try:
            probe.connect(self.socket_path)
        except OSError:
            os.unlink(self.socket_path)  # stale socket left by a crashed session
            return
        finally:
            probe.close()
        raise BridgeError(
            "BRIDGE_ALREADY_RUNNING",
            "another gimp-mcp bridge is already listening on %s" % self.socket_path,
        )

    def fileno(self) -> int:
        assert self.listener is not None
        return self.listener.fileno()

    def close(self) -> None:
        for conn in list(self.connections.values()):
            self.drop(conn)
        if self.pipe_listener is not None:
            self.pipe_listener.close()
            self.pipe_listener = None
            try:
                os.unlink(self.token_path)
            except OSError:
                pass
        if self.listener is not None:
            self.listener.close()
            self.listener = None
            for path in (self.socket_path, self.token_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    # -- connection handling ---------------------------------------------------------

    def handle_accept(self) -> Connection | None:
        assert self.listener is not None
        try:
            sock, _ = self.listener.accept()
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return None
            raise
        uid = _peer_uid(sock)
        if uid is None or uid != self.allowed_uid:  # an unidentified peer is refused too
            log("rejected connection from uid %s" % uid)
            sock.close()
            return None
        sock.setblocking(False)
        return self.add_connection(sock, uid)

    def add_connection(self, transport: Any, peer_uid: int | None) -> Connection:
        """Register an accepted, already-verified client (any transport)."""
        self._next_connection_id += 1
        conn = Connection(transport, peer_uid, self._next_connection_id)
        self.connections[conn.fileno()] = conn
        return conn

    def drop(self, conn: Connection) -> None:
        if getattr(conn, "dropped", False):
            return
        conn.dropped = True
        self.connections.pop(conn.fileno(), None)
        try:
            conn.sock.close()
        except OSError:
            pass
        for callback in list(self.on_disconnect):
            try:
                callback(conn.id)
            except Exception:
                log("disconnect hook failed:\n%s" % traceback.format_exc())

    def handle_readable(self, conn: Connection) -> bool:
        """Process available bytes. Returns False when the connection was closed."""
        try:
            chunk = conn.sock.recv(65536)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return True
            self.drop(conn)
            return False
        if not chunk:
            self.drop(conn)
            return False
        return self.handle_data(conn, chunk)

    def handle_data(self, conn: Connection, chunk: bytes) -> bool:
        """Process bytes received from a client. Returns False when the connection was closed."""
        conn.buffer += chunk
        while b"\n" in conn.buffer:
            line, conn.buffer = conn.buffer.split(b"\n", 1)
            if not self._handle_line(conn, line):
                self.drop(conn)
                return False
        if len(conn.buffer) > self.max_request_bytes:
            self._send(conn, {"id": None, "error": {"code": "REQUEST_TOO_LARGE", "message": "request too large"}})
            self.drop(conn)
            return False
        return True

    def _handle_line(self, conn: Connection, line: bytes) -> bool:
        if not line.strip():
            return True
        try:
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                raise ValueError("request must be an object with a method")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send(conn, {"id": None, "error": {"code": "PROTOCOL_ERROR", "message": str(exc)}})
            return False
        request_id = request.get("id")
        method = request["method"]
        params = request.get("params") or {}

        if not conn.authenticated:
            if method != "hello":
                self._send(conn, self._error(request_id, BridgeError("UNAUTHORIZED", "hello required first")))
                return False
            if not isinstance(params, dict) or params.get("token") != self.token:
                log("rejected connection: bad token")
                self._send(conn, self._error(request_id, BridgeError("UNAUTHORIZED", "invalid bridge token")))
                return False
            conn.authenticated = True
            result = dict(self.session_info)
            result["protocol"] = PROTOCOL_VERSION
            return self._send(conn, {"id": request_id, "result": result})

        if method == "hello":
            result = dict(self.session_info)
            result["protocol"] = PROTOCOL_VERSION
            return self._send(conn, {"id": request_id, "result": result})

        operation = self.operations.get(method)
        expected_session = params.pop("_session", None) if isinstance(params, dict) else None
        if expected_session is not None and expected_session != self.session_info.get("session_id"):
            response = self._error(
                request_id,
                BridgeError(
                    "SESSION_CHANGED",
                    "request targets GIMP session %s but this is session %s"
                    % (expected_session, self.session_info.get("session_id")),
                ),
            )
        elif operation is None:
            response = self._error(request_id, BridgeError("UNKNOWN_METHOD", "unknown method %r" % method))
        else:
            self.current_connection_id = conn.id
            self.last_connection_id = conn.id
            try:
                response = {"id": request_id, "result": operation(params)}
            except BridgeError as exc:
                response = self._error(request_id, exc)
            except Exception as exc:  # unexpected: report without leaking a traceback to the client
                log("operation %s failed:\n%s" % (method, traceback.format_exc()))
                response = self._error(
                    request_id,
                    BridgeError("GIMP_ERROR", "%s: %s" % (type(exc).__name__, exc), {"method": method}),
                )
        self.current_connection_id = None
        sent = self._send(conn, response)
        if method == "session.quit" and self.on_quit is not None and "result" in response:
            self.on_quit()
        return sent

    @staticmethod
    def _error(request_id: Any, exc: BridgeError) -> dict[str, Any]:
        return {"id": request_id, "error": exc.to_wire()}

    def _send(self, conn: Connection, message: dict[str, Any]) -> bool:
        try:
            data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            data = (
                json.dumps(
                    {
                        "id": message.get("id"),
                        "error": {"code": "GIMP_ERROR", "message": "unserializable result: %s" % exc},
                    }
                )
                + "\n"
            ).encode("utf-8")
        try:
            conn.sock.settimeout(SEND_TIMEOUT_SECONDS)
            conn.sock.sendall(data)
            conn.sock.setblocking(False)
            return True
        except OSError:
            return False


def run_with_selector(server: BridgeServer, selector: Any, stop_event: Any, poll: float = 0.05) -> None:
    """Pure-Python event loop (used by tests; GIMP uses GLib watches instead)."""
    import selectors

    selector.register(server.fileno(), selectors.EVENT_READ, None)
    registered: dict[int, Connection] = {}
    try:
        while not stop_event.is_set():
            for key, _ in selector.select(timeout=poll):
                if key.data is None:
                    conn = server.handle_accept()
                    if conn is not None:
                        registered[conn.fileno()] = conn
                        selector.register(conn.fileno(), selectors.EVENT_READ, conn)
                else:
                    conn = key.data
                    fd = key.fd
                    if not server.handle_readable(conn):
                        selector.unregister(fd)
                        registered.pop(fd, None)
            for fd in [fd for fd, c in registered.items() if c.fileno() == -1]:
                registered.pop(fd, None)
    finally:
        selector.close()

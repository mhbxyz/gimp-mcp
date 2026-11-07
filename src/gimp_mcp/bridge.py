"""Client side of the local GIMP bridge (asyncio, Unix domain socket).

Guarantees:

* Requests are serialized: at most one request is in flight per client, so
  mutations reach GIMP in the order the MCP server issued them and responses
  can never be attributed to the wrong request.
* Every wait is bounded (connect, handshake, request).
* When a request times out or the connection drops before its response
  arrives, the connection is discarded and the error says the outcome is
  ``unknown``: the operation may still have run inside GIMP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import select
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import INSTALL_HINT, GimpMcpError

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
MIN_GIMP_VERSION = (3, 2)
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
SOCKET_ENV = "GIMP_MCP_SOCKET"
_POLLRDHUP = getattr(select, "POLLRDHUP", 0)


@dataclass(frozen=True)
class BridgeEndpoint:
    socket_path: Path
    token_path: Path

    @classmethod
    def for_socket(cls, socket_path: Path) -> BridgeEndpoint:
        return cls(socket_path=socket_path, token_path=Path(str(socket_path) + ".token"))

    @classmethod
    def default(cls, environ: dict[str, str] | None = None) -> BridgeEndpoint:
        return cls.for_socket(default_socket_path(environ))


def default_socket_path(environ: dict[str, str] | None = None) -> Path:
    """Socket path shared by the plug-in and the server (same rules on both sides)."""
    env = os.environ if environ is None else environ
    explicit = env.get(SOCKET_ENV)
    if explicit:
        return Path(explicit)
    runtime = env.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime):
        return Path(runtime) / "gimp-mcp" / "bridge.sock"
    return Path("/tmp") / f"gimp-mcp-{os.getuid()}" / "bridge.sock"


@dataclass(frozen=True)
class SessionInfo:
    gimp_version: str
    session_id: str
    pid: int | None
    protocol: int
    bridge_version: str | None = None

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> SessionInfo:
        return cls(
            gimp_version=str(data.get("gimp_version", "")),
            session_id=str(data.get("session_id", "")),
            pid=data.get("pid"),
            protocol=int(data.get("protocol", 0)),
            bridge_version=data.get("bridge_version"),
        )


def parse_version(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


class BridgeClient:
    def __init__(
        self,
        endpoint: BridgeEndpoint | None = None,
        *,
        connect_timeout: float = 3.0,
        request_timeout: float = 60.0,
    ):
        self.endpoint = endpoint or BridgeEndpoint.default()
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self.session: SessionInfo | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0

    # -- public API ----------------------------------------------------------------

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        mutating: bool = False,
    ) -> Any:
        async with self._lock:
            await self._ensure_connected()
            try:
                return await self._request(method, params or {}, timeout or self.request_timeout, mutating)
            except GimpMcpError as error:
                # A read can safely be retried once on a fresh connection when the
                # previous one turned out to be dead (e.g. GIMP was restarted).
                if mutating or error.code != "DISCONNECTED":
                    raise
            await self._ensure_connected()
            return await self._request(method, params or {}, timeout or self.request_timeout, mutating)

    async def connect(self) -> SessionInfo:
        async with self._lock:
            await self._ensure_connected()
            assert self.session is not None
            return self.session

    async def close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except (TimeoutError, OSError):
                pass

    # -- internals -----------------------------------------------------------------

    async def _ensure_connected(self) -> None:
        if (
            self._writer is not None
            and self._reader is not None
            and not self._writer.is_closing()
            and not self._reader.at_eof()
            and not self._peer_went_away()
        ):
            return
        await self.close()
        socket_path = self.endpoint.socket_path
        if not socket_path.exists():
            raise GimpMcpError(
                "GIMP_NOT_RUNNING",
                f"no GIMP bridge socket at {socket_path}",
                hint=INSTALL_HINT,
            )
        try:
            token = self.endpoint.token_path.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise GimpMcpError(
                "BRIDGE_UNAVAILABLE",
                f"cannot read bridge token {self.endpoint.token_path}: {exc.strerror}",
                hint=INSTALL_HINT,
            ) from exc
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(socket_path), limit=MAX_RESPONSE_BYTES),
                timeout=self.connect_timeout,
            )
        except TimeoutError as exc:
            raise GimpMcpError(
                "BRIDGE_UNAVAILABLE",
                f"timed out connecting to {socket_path} after {self.connect_timeout:g}s",
                hint="GIMP may be busy or frozen. " + INSTALL_HINT,
            ) from exc
        except OSError as exc:
            raise GimpMcpError(
                "GIMP_NOT_RUNNING",
                f"cannot connect to {socket_path}: {exc.strerror or exc}",
                hint="The socket is stale: GIMP probably exited. " + INSTALL_HINT,
            ) from exc
        self._reader, self._writer = reader, writer
        try:
            hello = await self._request(
                "hello", {"token": token, "protocol": PROTOCOL_VERSION}, self.connect_timeout, False
            )
        except GimpMcpError as exc:
            await self.close()
            if exc.code in ("TIMEOUT", "DISCONNECTED"):
                raise GimpMcpError(
                    "BRIDGE_UNAVAILABLE",
                    f"bridge handshake failed: {exc.message}",
                    hint=INSTALL_HINT,
                ) from exc
            raise
        session = SessionInfo.from_wire(hello)
        if session.protocol != PROTOCOL_VERSION:
            await self.close()
            raise GimpMcpError(
                "VERSION_INCOMPATIBLE",
                f"bridge speaks protocol {session.protocol}, this server needs {PROTOCOL_VERSION}",
                hint="Reinstall the plug-in with `gimp-mcp install-plugin` and restart GIMP.",
            )
        if parse_version(session.gimp_version)[:2] < MIN_GIMP_VERSION:
            await self.close()
            minimum = ".".join(map(str, MIN_GIMP_VERSION))
            raise GimpMcpError(
                "VERSION_INCOMPATIBLE",
                f"GIMP {session.gimp_version} is not supported (minimum {minimum})",
                hint=f"Install GIMP {minimum} or newer.",
                details={"gimp_version": session.gimp_version, "minimum": minimum},
            )
        if self.session is not None and self.session.session_id != session.session_id:
            log.info("GIMP session changed: %s -> %s", self.session.session_id, session.session_id)
        self.session = session

    def _peer_went_away(self) -> bool:
        """Detect a dead idle connection (e.g. GIMP restarted) before sending.

        The bridge never sends unsolicited data, so an idle connection that is
        readable or hung up has been closed by the other side.
        """
        assert self._writer is not None
        sock = self._writer.get_extra_info("socket")
        if sock is None:
            return False
        poller = select.poll()
        poller.register(sock.fileno(), select.POLLIN | select.POLLHUP | select.POLLERR | _POLLRDHUP)
        return bool(poller.poll(0))

    async def _request(self, method: str, params: dict[str, Any], timeout: float, mutating: bool) -> Any:
        assert self._reader is not None and self._writer is not None
        self._next_id += 1
        request_id = self._next_id
        payload = json.dumps({"id": request_id, "method": method, "params": params}, separators=(",", ":"))
        unknown = "unknown" if mutating else None
        try:
            self._writer.write(payload.encode("utf-8") + b"\n")
            await asyncio.wait_for(self._writer.drain(), timeout=timeout)
            line = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
        except asyncio.CancelledError:
            # The caller gave up (e.g. the MCP request was cancelled). GIMP may
            # still run the operation; its late answer must never be read as
            # the answer to a later request, so drop the connection.
            await self.close()
            raise
        except TimeoutError as exc:
            await self.close()
            raise GimpMcpError(
                "TIMEOUT",
                f"GIMP did not answer {method!r} within {timeout:g}s",
                hint="GIMP may still be working. Inspect the image before retrying a modification.",
                outcome=unknown,
            ) from exc
        except (OSError, asyncio.IncompleteReadError, ValueError) as exc:
            await self.close()
            raise GimpMcpError(
                "DISCONNECTED",
                f"connection to GIMP lost during {method!r}: {exc}",
                hint="GIMP may have quit or crashed. " + INSTALL_HINT,
                outcome=unknown,
            ) from exc
        if not line:
            await self.close()
            raise GimpMcpError(
                "DISCONNECTED",
                f"GIMP closed the connection during {method!r}",
                hint="GIMP may have quit or crashed. " + INSTALL_HINT,
                outcome=unknown,
            )
        try:
            response = json.loads(line)
        except ValueError as exc:
            await self.close()
            raise GimpMcpError("PROTOCOL_ERROR", f"invalid response from bridge: {exc}", outcome=unknown) from exc
        if response.get("id") != request_id:
            await self.close()
            raise GimpMcpError(
                "PROTOCOL_ERROR",
                f"response id {response.get('id')!r} does not match request {request_id}",
                outcome=unknown,
            )
        if "error" in response:
            error = response["error"] or {}
            code = str(error.get("code", "GIMP_ERROR"))
            if code in ("UNAUTHORIZED", "PROTOCOL_ERROR", "REQUEST_TOO_LARGE"):
                await self.close()
            # Operations raise anticipated errors before changing anything; an
            # unexpected GIMP failure may have happened half-way through.
            if not mutating:
                outcome = None
            elif code == "GIMP_ERROR":
                outcome = "unknown"
            else:
                outcome = "not_applied"
            raise GimpMcpError(
                code,
                str(error.get("message", "unknown bridge error")),
                details=error.get("details") or {},
                hint=error.get("hint"),
                outcome=outcome,
            )
        return response.get("result")

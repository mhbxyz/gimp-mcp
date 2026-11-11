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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__, platforms
from .errors import INSTALL_HINT, GimpMcpError
from .plugin_modules import load as load_plugin_module
from .versions import SUPPORTED_PROTOCOLS, Compatibility, PluginCheck, check_plugin

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
MIN_GIMP_VERSION = (3, 2)
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
SOCKET_ENV = "GIMP_MCP_SOCKET"
FLATPAK_APP = platforms.FLATPAK_APP
_POLLRDHUP = getattr(select, "POLLRDHUP", 0)


@dataclass(frozen=True)
class BridgeEndpoint:
    socket_path: Path
    token_path: Path

    @property
    def is_pipe(self) -> bool:
        r"""A Windows named pipe (``\\.\pipe\...``) rather than a Unix socket."""
        return str(self.socket_path).replace("/", "\\").lower().startswith("\\\\.\\pipe\\")

    @classmethod
    def for_socket(cls, socket_path: Path) -> BridgeEndpoint:
        return cls(socket_path=socket_path, token_path=Path(str(socket_path) + ".token"))

    @classmethod
    def default(cls, environ: dict[str, str] | None = None) -> BridgeEndpoint:
        address = platforms.bridge_address(os.environ if environ is None else environ)
        return cls(socket_path=Path(address.path), token_path=Path(address.token_path))


def default_socket_path(environ: dict[str, str] | None = None) -> Path:
    """Address shared by the plug-in and the server (``platforms.bridge_address``; a Flatpak GIMP's
    socket is used when only it exists)."""
    return Path(platforms.bridge_address(os.environ if environ is None else environ).path)


async def open_pipe_connection(name: str, limit: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to the bridge's Windows named pipe (asyncio's Proactor loop) and check that the
    process serving it belongs to the current user (ADR 0008)."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=limit, loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    transport, _ = await loop.create_pipe_connection(lambda: protocol, name)  # type: ignore[attr-defined]
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    gmb_pipe = load_plugin_module("gmb_pipe")
    try:
        owner = gmb_pipe.process_user_sid(gmb_pipe.server_process_id(transport.get_extra_info("pipe").handle))
        mine = gmb_pipe.process_user_sid()
    except OSError as exc:
        writer.close()
        raise GimpMcpError("BRIDGE_UNAVAILABLE", f"cannot identify the process serving {name}: {exc}") from exc
    if owner != mine:
        writer.close()
        raise GimpMcpError("BRIDGE_UNAVAILABLE", f"{name} is served by another user's process; refusing it")
    return reader, writer


@dataclass(frozen=True)
class SessionInfo:
    gimp_version: str
    session_id: str
    pid: int | None
    protocol: int
    bridge_version: str | None = None
    # Operation -> revision served by the plug-in; None for plug-ins before 0.7.0, which did not say.
    capabilities: dict[str, int] | None = None

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> SessionInfo:
        capabilities = data.get("capabilities")
        return cls(
            gimp_version=str(data.get("gimp_version", "")),
            session_id=str(data.get("session_id", "")),
            pid=data.get("pid"),
            protocol=int(data.get("protocol", 0)),
            bridge_version=data.get("bridge_version"),
            capabilities={str(k): int(v) for k, v in capabilities.items()} if isinstance(capabilities, dict) else None,
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
        self.plugin_check: PluginCheck | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        # When a request was abandoned (cancelled or timed out), GIMP may still be running it and
        # answers nothing else (not even the next handshake) until it is done.
        self._abandoned_at: float | None = None

    # -- public API ----------------------------------------------------------------

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        mutating: bool = False,
        revision: int = 1,
    ) -> Any:
        """``revision``: the revision of ``method`` the caller relies on (new parameters or meaning); a
        plug-in serving an older one is refused before anything is sent."""
        async with self._lock:
            await self._ensure_connected()
            self._check_capability(method, revision)
            try:
                return await self._request(method, params or {}, timeout or self.request_timeout, mutating)
            except GimpMcpError as error:
                # A read can safely be retried once on a fresh connection when the
                # previous one turned out to be dead (e.g. GIMP was restarted).
                if error.code == "UNKNOWN_METHOD":  # a plug-in from before 0.7.0 lacking the operation
                    raise self._outdated(method, revision) from error
                if mutating or error.code != "DISCONNECTED":
                    raise
            await self._ensure_connected()
            self._check_capability(method, revision)
            return await self._request(method, params or {}, timeout or self.request_timeout, mutating)

    def _check_capability(self, method: str, revision: int) -> None:
        assert self.session is not None
        capabilities = self.session.capabilities
        served = (1 if revision == 1 else 0) if capabilities is None else capabilities.get(method, 0)
        if served < revision:
            raise self._outdated(method, revision)

    def _outdated(self, method: str, revision: int) -> GimpMcpError:
        """The plug-in lacks ``method`` at ``revision``: nothing was applied."""
        plugin = (self.session.bridge_version if self.session else None) or "unknown"
        return GimpMcpError(
            "PLUGIN_VERSION_MISMATCH",
            f"the GIMP plug-in ({plugin}) does not support {method}"
            + (f" revision {revision}" if revision > 1 else "")
            + f": it is older than this server ({__version__})",
            hint="Update the plug-in: run `gimp-mcp install-plugin`, then restart GIMP.",
            details={
                "operation": method,
                "revision": revision,
                "plugin_version": plugin,
                "server_version": __version__,
            },
        )

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
        if not self.endpoint.is_pipe and not socket_path.exists():
            raise GimpMcpError(
                "GIMP_NOT_RUNNING",
                f"no GIMP bridge socket at {socket_path}",
                hint=INSTALL_HINT,
            )
        if self.endpoint.is_pipe and not self.endpoint.token_path.exists():
            raise GimpMcpError("GIMP_NOT_RUNNING", f"no GIMP bridge serves {socket_path}", hint=INSTALL_HINT)
        try:
            token = self.endpoint.token_path.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise GimpMcpError(
                "BRIDGE_UNAVAILABLE",
                f"cannot read bridge token {self.endpoint.token_path}: {exc.strerror}",
                hint=INSTALL_HINT,
            ) from exc
        try:
            opening = (
                open_pipe_connection(str(socket_path), MAX_RESPONSE_BYTES)
                if self.endpoint.is_pipe
                else asyncio.open_unix_connection(str(socket_path), limit=MAX_RESPONSE_BYTES)
            )
            reader, writer = await asyncio.wait_for(opening, timeout=self.connect_timeout)
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
                "hello", {"token": token, "protocol": PROTOCOL_VERSION}, self._handshake_timeout(), False
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
        self._abandoned_at = None  # GIMP answered: whatever was abandoned is finished
        session = SessionInfo.from_wire(hello)
        check = check_plugin(__version__, session.bridge_version, session.protocol, session.capabilities)
        if check.verdict is Compatibility.INCOMPATIBLE:
            await self.close()
            supported = ", ".join(map(str, sorted(SUPPORTED_PROTOCOLS)))
            raise GimpMcpError(
                "PLUGIN_VERSION_MISMATCH",
                f"the GIMP plug-in ({session.bridge_version or 'unknown'}) speaks bridge protocol "
                f"{session.protocol}; this server ({__version__}) speaks {supported}",
                hint="Run `gimp-mcp install-plugin`, then restart GIMP.",
                details={
                    "plugin_version": session.bridge_version or "unknown",
                    "plugin_protocol": session.protocol,
                    "server_version": __version__,
                },
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
        if check.verdict is not Compatibility.MATCH:
            log.warning(
                "GIMP plug-in %s differs from server %s (%s%s); run `gimp-mcp install-plugin` and restart "
                "GIMP to align them",
                session.bridge_version,
                __version__,
                check.verdict.value,
                f", missing {len(check.missing)} operations" if check.missing else "",
            )
        self.plugin_check = check
        if self.session is not None and self.session.session_id != session.session_id:
            log.info("GIMP session changed: %s -> %s", self.session.session_id, session.session_id)
        self.session = session

    def _handshake_timeout(self) -> float:
        """connect_timeout, or longer while an abandoned request may still keep GIMP busy."""
        if self._abandoned_at is None:
            return self.connect_timeout
        remaining = self.request_timeout - (time.monotonic() - self._abandoned_at)
        return max(self.connect_timeout, remaining)

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
            self._abandoned_at = time.monotonic()
            await self.close()
            raise
        except TimeoutError as exc:
            self._abandoned_at = time.monotonic()
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

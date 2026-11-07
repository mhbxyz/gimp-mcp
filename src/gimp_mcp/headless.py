"""Run an isolated, headless GIMP 3 with the bridge plug-in (tests, CI, demo).

The instance uses a throw-away configuration directory (``GIMP3_DIRECTORY``)
so personal settings, plug-ins and recent files are never read or modified.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .bridge import BridgeEndpoint
from .errors import GimpMcpError
from .installer import install_plugin

CONSOLE_CANDIDATES = ("gimp-console-3.2", "gimp-console-3.0", "gimp-console", "gimp-console-3")


def find_gimp_console() -> str | None:
    explicit = os.environ.get("GIMP_MCP_GIMP_CONSOLE")
    if explicit:
        return explicit if shutil.which(explicit) else None
    for name in CONSOLE_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def system_path(path: str) -> str:
    """Drop virtualenv directories from PATH.

    GIMP runs Python plug-ins through ``#!/usr/bin/env python3``; a virtualenv's
    interpreter lacks PyGObject (``gi``) and every Python plug-in would fail.
    """
    venv_bins = {str(Path(sys.prefix) / "bin")}
    if os.environ.get("VIRTUAL_ENV"):
        venv_bins.add(str(Path(os.environ["VIRTUAL_ENV"]) / "bin"))
    kept = [entry for entry in path.split(os.pathsep) if entry and entry not in venv_bins]
    return os.pathsep.join(kept)


def _short_base_dir() -> str:
    # AF_UNIX socket paths are limited to ~107 bytes.
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime) and os.access(runtime, os.W_OK):
        return runtime
    return tempfile.gettempdir()


class HeadlessGimp:
    def __init__(
        self,
        console: str | None = None,
        open_files: list[Path] | None = None,
        startup_timeout: float = 120.0,
        load_fonts: bool = True,
    ):
        found = console or find_gimp_console()
        if found is None:
            raise GimpMcpError("GIMP_NOT_FOUND", "gimp-console (GIMP 3) was not found on PATH")
        self.console = found
        self.open_files = list(open_files or [])
        self.startup_timeout = startup_timeout
        self.load_fonts = load_fonts
        self.root = Path(tempfile.mkdtemp(prefix="gimp-mcp-", dir=_short_base_dir()))
        self.config_dir = self.root / "config"
        self.socket_path = self.root / "bridge.sock"
        self.log_path = self.root / "gimp.log"
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def endpoint(self) -> BridgeEndpoint:
        return BridgeEndpoint.for_socket(self.socket_path)

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env["GIMP3_DIRECTORY"] = str(self.config_dir)
        env["GIMP_MCP_SOCKET"] = str(self.socket_path)
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        env["PATH"] = system_path(env.get("PATH", ""))
        for name in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT"):
            env.pop(name, None)
        return env

    def start(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        install_plugin(self.config_dir)
        args = [self.console, "--no-interface", "--console-messages", "--new-instance"]
        if not self.load_fonts:
            args.append("--no-fonts")
        args += [str(path) for path in self.open_files]
        with open(self.log_path, "wb") as log_file:
            self.process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=self.environment(),
                cwd=self.root,
                start_new_session=True,
            )
        try:
            self._wait_until_ready()
        except BaseException:
            self.stop()
            raise

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.startup_timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            assert self.process is not None
            if self.process.poll() is not None:
                raise GimpMcpError(
                    "GIMP_START_FAILED",
                    f"gimp-console exited with code {self.process.returncode}",
                    details={"log_tail": self.log_tail()},
                )
            if self.socket_path.exists():
                try:
                    self.sync_call("hello")
                    if self._expected_images_open():
                        return
                except (OSError, ValueError, GimpMcpError) as exc:
                    last_error = exc
            time.sleep(0.2)
        raise GimpMcpError(
            "GIMP_START_FAILED",
            f"bridge not ready after {self.startup_timeout:g}s ({last_error})",
            details={"log_tail": self.log_tail()},
        )

    def sync_call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        """Blocking bridge call (readiness probe and test setup helpers)."""
        token = self.endpoint.token_path.read_text().strip()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(self.socket_path))
            reader = sock.makefile("rb")
            requests = [{"id": 1, "method": "hello", "params": {"token": token}}]
            if method != "hello":
                requests.append({"id": 2, "method": method, "params": params or {}})
            result: Any = None
            for request in requests:
                sock.sendall(json.dumps(request).encode() + b"\n")
                line = reader.readline()
                if not line:
                    raise GimpMcpError("BRIDGE_UNAVAILABLE", "bridge closed the connection")
                response = json.loads(line)
                if "error" in response:
                    error = response["error"]
                    raise GimpMcpError(error["code"], error["message"], details=error.get("details") or {})
                result = response["result"]
            return result

    def _expected_images_open(self) -> bool:
        if not self.open_files:
            return True
        images = self.sync_call("session.images")["images"]
        return len(images) >= len(self.open_files)

    def log_tail(self, lines: int = 40) -> str:
        try:
            text = self.log_path.read_text(errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    def kill(self) -> None:
        """Simulate a crash: SIGKILL the whole GIMP process group."""
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=10)

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            except ProcessLookupError:
                pass
        if process is not None:
            try:  # plug-in processes share the group; make sure none survive
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        keep = os.environ.get("GIMP_MCP_LOG_DIR")
        if keep and self.log_path.exists():
            Path(keep).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.log_path, Path(keep) / f"{self.root.name}.log")
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> HeadlessGimp:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

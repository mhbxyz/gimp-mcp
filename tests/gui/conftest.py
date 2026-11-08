"""GIMP with its interface open (#105): a real GIMP window, the bridge, and what a user does with the
keyboard (undo, edits, close, quit), next to the MCP calls.

These tests need a display and keyboard input to GIMP: they run only with ``GIMP_MCP_GUI=1`` (the CI's
GUI jobs: Xvfb + xdotool on Linux, the desktop session of the macOS and Windows runners). The profile
is temporary (``GIMP3_DIRECTORY``), like every e2e test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from gimp_mcp.errors import GimpMcpError
from gimp_mcp.headless import HeadlessGimp, find_gimp_console

ENABLED = os.environ.get("GIMP_MCP_GUI") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/gui/" in str(item.fspath).replace(os.sep, "/") and not ENABLED:
            item.add_marker(pytest.mark.skip(reason="GUI tests need a display: set GIMP_MCP_GUI=1"))


def gui_executable(console: str) -> str:
    """GIMP with its interface, next to gimp-console (same installation)."""
    path = Path(console)
    name = path.name.replace("gimp-console", "gimp")
    for candidate in (
        path.with_name(name),
        path.with_name("gimp"),
        path.with_name("gimp.exe"),
    ):  # macOS: GIMP.app's "gimp"
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name) or shutil.which("gimp-3.2") or shutil.which("gimp")
    if found is None:
        raise GimpMcpError("GIMP_NOT_FOUND", f"no GIMP with an interface next to {console}")
    return found


class GuiGimp(HeadlessGimp):
    """A GIMP with its interface: same isolated profile and bridge as HeadlessGimp."""

    def start(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # no welcome dialog, no update check: nothing between the test and the image windows
        (self.config_dir / "gimprc").write_text(
            "(show-welcome-dialog no)\n(check-updates no)\n(show-tips no)\n(restore-session no)\n"
            "(save-session-info no)\n",
            encoding="utf-8",
        )
        from gimp_mcp.installer import install_plugin

        install_plugin(self.config_dir)
        args = [gui_executable(self.console), "--no-splash", "--new-instance", *map(str, self.open_files)]
        with open(self.log_path, "ab") as log_file:
            self.process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
                env=self.environment(), cwd=self.root, start_new_session=True,
            )  # fmt: skip
        try:
            self._wait_until_ready()
            wait_for_window(self)
        except BaseException:
            self.stop()
            raise

    def environment(self) -> dict[str, str]:
        env = super().environment()
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"):  # the interface needs the display back
            if os.environ.get(name):
                env[name] = os.environ[name]
        return env

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None


def wait_for_window(gimp: GuiGimp, timeout: float = 60.0) -> None:
    if sys.platform.startswith("linux"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if window_ids():
                time.sleep(1.5)  # the window maps before it takes input
                return
            time.sleep(0.3)
        raise AssertionError(f"no GIMP window after {timeout}s\n{gimp.log_tail()}")
    time.sleep(8)  # macOS, Windows: the window opens with the bridge; give it time to take focus


def window_ids() -> list[str]:
    proc = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "gimp"], capture_output=True, text=True)
    return proc.stdout.split()


def press(gimp: GuiGimp, keys: str) -> None:
    """Send a key combination to GIMP's focused image window, like a user (``ctrl+z``)."""
    if sys.platform.startswith("linux"):
        ids = window_ids()
        assert ids, "no GIMP window"
        window = ids[-1]
        subprocess.run(["xdotool", "windowactivate", "--sync", window], check=False, capture_output=True)
        # a key that closes the window (ctrl+w, ctrl+q) can make the key release fail: the window is gone
        sent = subprocess.run(["xdotool", "key", "--clearmodifiers", "--window", window, keys], capture_output=True)
        assert sent.returncode == 0 or keys in ("ctrl+w", "ctrl+q"), sent.stderr
    elif sys.platform == "win32":
        windows_press(gimp, keys)
    else:  # macOS: GIMP uses the Command key where Linux and Windows use Control
        key = {"comma": ","}.get(keys.split("+")[-1], keys.split("+")[-1])
        code = f'keystroke "{key}"'
        modifiers = ", ".join(
            f"{m} down" for m in ("command", "shift") if f"{'ctrl' if m == 'command' else m}+" in keys
        )
        script = f'tell application "GIMP" to activate\ndelay 0.5\ntell application "System Events" to {code}' + (
            f" using {{{modifiers}}}" if modifiers else ""
        )
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    time.sleep(1.0)  # GIMP handles the key on its main loop


VIRTUAL_KEYS = {"ctrl": 0x11, "shift": 0x10, "comma": 0xBC, "Delete": 0x2E}


def windows_press(gimp: GuiGimp, keys: str) -> None:
    """Bring GIMP's largest window to the front and type the keys with keybd_event (WScript's SendKeys
    cannot take the focus from a runner's background session)."""
    assert sys.platform == "win32"  # (also tells the type checker which ctypes it is)
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    assert gimp.process is not None
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd: int, _: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == gimp.process.pid and user32.IsWindowVisible(hwnd):  # type: ignore[union-attr]
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append(((rect.right - rect.left) * (rect.bottom - rect.top), hwnd))
        return True

    user32.EnumWindows(collect, 0)
    assert found, "no GIMP window"
    hwnd = max(found)[1]
    foreground = user32.GetForegroundWindow()
    theirs = user32.GetWindowThreadProcessId(foreground, None)
    ours = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(theirs, ours, True)
    user32.keybd_event(0x12, 0, 0, 0)  # an Alt tap lets a background process take the foreground
    user32.keybd_event(0x12, 0, 2, 0)
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(theirs, ours, False)
    time.sleep(0.4)
    codes = [VIRTUAL_KEYS[k] if k in VIRTUAL_KEYS else ord(k.upper()) for k in keys.split("+")]
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, 2, 0)


@pytest.fixture
def gui_gimp(tmp_path: Path) -> Iterator[callable]:  # type: ignore[valid-type]
    console = find_gimp_console()
    if console is None:
        pytest.fail("GIMP 3 (gimp-console) not found", pytrace=False)
    started: list[GuiGimp] = []

    def start(open_files: list[Path] | None = None) -> GuiGimp:
        instance = GuiGimp(console=console, open_files=open_files or [])
        started.append(instance)
        instance.start()
        return instance

    try:
        yield start
    finally:
        for instance in started:
            instance.stop()

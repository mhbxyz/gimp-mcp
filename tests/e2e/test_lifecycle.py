from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable

import pytest

from gimp_mcp import platforms
from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client


async def test_server_reports_gimp_shutdown_without_hanging(gimp_factory: Callable[..., HeadlessGimp]):
    gimp = gimp_factory()
    async with mcp_client(gimp) as client:
        before = await client.call_tool("gimp_status", {})
        assert not before.is_error
        gimp.stop()
        started = time.monotonic()
        after = await client.call_tool("gimp_status", {})
        assert time.monotonic() - started < 10
    assert after.is_error
    assert after.structured_content is not None
    assert after.structured_content["error"]["code"] in {"GIMP_NOT_RUNNING", "DISCONNECTED"}


def test_stopping_gimp_leaves_no_process_and_no_temporary_file(gimp_factory: Callable[..., HeadlessGimp]):
    gimp = gimp_factory()
    assert gimp.process is not None
    group = gimp.process.pid
    root = gimp.root
    assert gimp.config_dir.is_relative_to(root)  # isolated profile, never ~/.config/GIMP
    gimp.stop()
    assert not root.exists()
    if platforms.CURRENT == "windows":  # no process groups: GIMP itself must be gone
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {group}"], capture_output=True, text=True).stdout
        assert str(group) not in listed
    else:
        with pytest.raises(ProcessLookupError):
            os.killpg(group, 0)  # type: ignore[attr-defined]


def test_isolated_profile_does_not_touch_the_user_gimp_directory(gimp_factory: Callable[..., HeadlessGimp]):
    gimp = gimp_factory()
    env = gimp.environment()
    assert env["GIMP3_DIRECTORY"] == str(gimp.config_dir)
    assert "DISPLAY" not in env
    assert (gimp.config_dir / "plug-ins" / "gimp-mcp-bridge").is_dir()

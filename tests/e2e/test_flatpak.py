"""Issue #41: gimp-mcp with GIMP installed from Flathub (org.gimp.GIMP).

Runs only in the disposable container of ci/run-flatpak-e2e.sh
(GIMP_MCP_FLATPAK_E2E=1): Flatpak GIMP always reads the user's ~/.config/GIMP,
so it must never run on a developer's own account.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from PIL import Image

pytestmark = pytest.mark.skipif(
    os.environ.get("GIMP_MCP_FLATPAK_E2E") != "1", reason="Flatpak e2e runs in ci/run-flatpak-e2e.sh only"
)


def gimp_mcp(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "gimp_mcp", *args], capture_output=True, text=True, env=env,
                          timeout=300)  # fmt: skip


async def test_setup_doctor_and_mcp_calls_with_flatpak_gimp(tmp_path: Path):
    env = {k: v for k, v in os.environ.items() if k not in ("GIMP_MCP_SOCKET", "GIMP3_DIRECTORY")}
    runtime = Path(env["XDG_RUNTIME_DIR"])
    socket = runtime / "app" / "org.gimp.GIMP" / "gimp-mcp" / "bridge.sock"
    profile = Path.home() / ".config" / "GIMP" / "3.2"

    setup = gimp_mcp("setup", "--yes", "--clients", "none", "--no-doctor", env=env)
    assert setup.returncode == 0, setup.stderr
    assert "Flatpak" in setup.stderr
    assert (profile / "plug-ins" / "gimp-mcp-bridge" / "gimp-mcp-bridge.py").exists()

    gimp = subprocess.Popen(
        ["flatpak", "run", "--command=gimp-console-3.2", "org.gimp.GIMP", "--no-interface"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 180
        while not socket.exists() and time.monotonic() < deadline:
            assert gimp.poll() is None, "Flatpak GIMP exited"
            time.sleep(0.5)
        assert socket.exists(), "the bridge socket never appeared in the shared app runtime dir"

        doctor = gimp_mcp("doctor", "--json", env=env)
        checks = {c["id"]: c for c in json.loads(doctor.stdout)["checks"]}
        assert "Flatpak" in checks["gimp"]["message"]
        for key in ("gimp", "gimp-python", "plugin", "plugin-version", "connection"):
            assert checks[key]["status"] == "ok", (key, checks[key])

        out = tmp_path / "flatpak.png"  # /tmp is shared with the Flatpak sandbox
        params = StdioServerParameters(command=sys.executable, args=["-m", "gimp_mcp", "serve"], env=env)
        async with Client(params, read_timeout_seconds=120) as client:
            status = await client.call_tool("gimp_status", {})
            created = await client.call_tool("gimp_create_image", {"width": 20, "height": 10, "fill": "#00ff00"})
            assert created.structured_content is not None, created.content
            exported = await client.call_tool(
                "gimp_export_image", {"image": created.structured_content["id"], "path": str(out)}
            )
        assert not status.is_error and not exported.is_error, exported.content
        assert status.structured_content is not None and status.structured_content["socket"] == str(socket)
        with Image.open(out) as png:
            assert png.size == (20, 10) and png.convert("RGB").getpixel((5, 5)) == (0, 255, 0)
    finally:
        os.killpg(gimp.pid, signal.SIGTERM)
        subprocess.run(["flatpak", "kill", "org.gimp.GIMP"], capture_output=True)
        gimp.wait(timeout=30)

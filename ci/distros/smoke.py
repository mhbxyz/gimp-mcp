"""Smoke test run inside a distribution container with the *installed* package only.

    python smoke.py                 # prints a JSON line with the result; exit 0 when everything passed

Checks: GIMP version, `gimp-mcp doctor`, a headless GIMP with the plug-in installed
by the package, and real MCP calls (status, create, export) over stdio.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import Client, StdioServerParameters

from gimp_mcp import __version__
from gimp_mcp.headless import HeadlessGimp, find_gimp_console

EXE = str(Path(sys.executable).with_name("gimp-mcp"))


def os_release() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.platform()


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


async def mcp_calls(gimp: HeadlessGimp, out: Path) -> dict:
    env = {**os.environ, "GIMP_MCP_SOCKET": str(gimp.socket_path)}
    async with Client(StdioServerParameters(command=EXE, args=["serve"], env=env), read_timeout_seconds=120) as client:
        status = (await client.call_tool("gimp_status", {})).structured_content
        created = await client.call_tool("gimp_create_image", {"width": 32, "height": 16, "fill": "#336699"})
        assert created.structured_content is not None, created.content
        exported = await client.call_tool(
            "gimp_export_image", {"image": created.structured_content["id"], "path": str(out)}
        )
        assert not exported.is_error, exported.content
    assert status is not None and status["plugin_version"] == __version__
    assert png_size(out) == (32, 16)
    return status


def main() -> int:
    report: dict = {"distribution": os_release(), "gimp_mcp": __version__, "python": platform.python_version()}
    console = find_gimp_console()
    report["gimp"] = (
        subprocess.run([console, "--version"], capture_output=True, text=True).stdout.strip() if console else None
    )
    gimp = None
    try:
        assert console, "gimp-console not found"
        gimp = HeadlessGimp(console=console, load_fonts=False)
        gimp.start()
        with tempfile.TemporaryDirectory() as tmp:
            status = asyncio.run(mcp_calls(gimp, Path(tmp) / "smoke.png"))
        report["gimp_version_seen"] = status["gimp_version"]
        doctor = subprocess.run(
            [EXE, "doctor", "--json", "--socket", str(gimp.socket_path), "--gimp-dir", str(gimp.config_dir)],
            capture_output=True, text=True,
        )  # fmt: skip
        checks = {c["id"]: c for c in json.loads(doctor.stdout)["checks"]}
        failing = {k: c["message"] for k, c in checks.items() if c["status"] == "fail"}
        assert not failing, f"doctor failures: {failing}"
        report["ok"] = True
    except Exception as exc:  # report everything needed to diagnose from the CI log
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        if gimp is not None:
            report["gimp_log_tail"] = gimp.log_tail(40)
        doctor = subprocess.run([EXE, "doctor", "--json"], capture_output=True, text=True)
        report["doctor"] = doctor.stdout[-4000:]
    finally:
        if gimp is not None:
            gimp.stop()
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

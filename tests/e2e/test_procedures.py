from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


async def test_search_and_describe_procedures_without_running_them(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        found = await call(client, "gimp_search_procedures", query="image-scale", limit=10)
        described = await call(client, "gimp_describe_procedure", name="gimp-image-scale")
        jpeg = await call(client, "gimp_describe_procedure", name="file-jpeg-export")
        missing = await error(client, "gimp_describe_procedure", name="plug-in-does-not-exist")
        status = await call(client, "gimp_status")
    assert "gimp-image-scale" in [p["name"] for p in found["procedures"]]
    assert described["type"] == "internal"
    width = next(a for a in described["arguments"] if a["name"] == "new-width")
    assert (width["type"], width["minimum"], width["maximum"]) == ("gint", 1, 524288)
    quality = next(a for a in jpeg["arguments"] if a["name"] == "quality")
    assert (quality["default"], quality["maximum"]) == (0.9, 1.0)
    subsampling = next(a for a in jpeg["arguments"] if a["name"] == "sub-sampling")
    assert "sub-sampling-1x1" in subsampling["choices"]
    assert missing["code"] == "NOT_FOUND"
    assert status["images"] == []  # describing never runs anything


def test_inventory_command_writes_a_complete_inventory(gimp: HeadlessGimp, tmp_path: Path):
    out = tmp_path / "inventory.json"
    proc = subprocess.run(
        [sys.executable, "-m", "gimp_mcp", "inventory", "--socket", str(gimp.socket_path), "--output", str(out)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text())
    assert data["gimp_version"].startswith("3.")
    names = {p["name"] for p in data["procedures"]}
    assert {"gimp-image-new", "file-png-export", "gimp-drawable-brightness-contrast"} <= names
    assert len(names) > 500
    assert all("arguments" in p or "error" in p for p in data["procedures"])
    assert data["gegl_operations"] and "gegl:gaussian-blur" in data["gegl_operations"]

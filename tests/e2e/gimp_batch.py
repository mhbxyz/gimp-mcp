"""Build test fixtures with a separate, short-lived batch GIMP.

Used only to prepare input files (e.g. an XCF with nested groups) independently
of the MCP tools under test.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from gimp_mcp.headless import find_gimp_console, system_path

PRELUDE = """
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, Gio

def save_xcf(image, path):
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(path), None)

def layer(image, name, w, h, parent=None, position=0, opacity=100.0, mode=Gimp.LayerMode.NORMAL, alpha=True):
    kind = Gimp.ImageType.RGBA_IMAGE if alpha else Gimp.ImageType.RGB_IMAGE
    created = Gimp.Layer.new(image, name, w, h, kind, opacity, mode)
    image.insert_layer(created, parent, position)
    return created

def group(image, name, parent=None, position=0):
    created = Gimp.GroupLayer.new(image, name)
    image.insert_layer(created, parent, position)
    return created
"""


def run_batch(code: str, timeout: float = 120) -> None:
    console = find_gimp_console()
    assert console is not None, "gimp-console required"
    with tempfile.TemporaryDirectory(prefix="gimp-mcp-batch-") as config:
        env = dict(os.environ)
        env["GIMP3_DIRECTORY"] = config
        env["PATH"] = system_path(env.get("PATH", ""))
        env.pop("VIRTUAL_ENV", None)
        env.pop("DISPLAY", None)
        script = Path(config) / "batch.py"
        script.write_text(PRELUDE + "\n" + code + "\nGimp.get_pdb()\n")
        proc = subprocess.run(
            [
                console,
                "--no-interface",
                "--no-data",
                "--no-fonts",
                "--new-instance",
                "--quit",
                "--batch-interpreter",
                "python-fu-eval",
                "-b",
                f"exec(open({str(script)!r}).read())",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0 or "Traceback" in proc.stderr + proc.stdout:
            raise RuntimeError(f"batch GIMP failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")

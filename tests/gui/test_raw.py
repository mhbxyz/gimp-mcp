"""Opening a RAW file through darktable, with GIMP's interface open (#129).

GIMP 3.2 hands a RAW file to darktable (`file-darktable`), which opens its darkroom window; the image
reaches GIMP when that window is closed. The test plays the user: it waits for darktable's window,
closes it, and checks what GIMP received. The DNG is synthetic, so its four quadrants are known.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time

import pytest
from mcp import Client
from PIL import Image

from tests.e2e.conftest import server_params
from tests.e2e.helpers import call

from .dng import write_dng

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("darktable") is None,
    reason="darktable is installed in the Linux GUI job (ci/gui/Dockerfile)",
)


def darktable_windows() -> list[str]:
    proc = subprocess.run(
        ["xdotool", "search", "--onlyvisible", "--class", "darktable"], capture_output=True, text=True
    )
    return proc.stdout.split()


async def test_a_raw_file_opens_through_darktable_and_keeps_its_quadrants(gui_gimp, tmp_path):
    dng = tmp_path / "quadrants.dng"
    write_dng(dng)
    gimp = gui_gimp()
    params = server_params(gimp)  # a person develops the RAW: the call may take minutes
    params = params.model_copy(update={"args": [*params.args, "--timeout", "300"]})
    async with Client(params, read_timeout_seconds=300) as client:
        formats = await call(client, "gimp_list_file_formats", mode="import")
        procedures = {f["procedure"] for f in formats["formats"]}
        if (
            "file-darktable-dng-load" not in procedures
        ):  # one loader per RAW family  # GIMP skips the loader when `darktable --gimp version` warns
            probe = subprocess.run(["darktable", "--gimp", "version"], capture_output=True, text=True)
            raw = sorted(p for p in procedures if any(k in p for k in ("raw", "dark", "dng")))
            pytest.fail(
                f"GIMP did not register darktable's loader (RAW loaders: {raw}); darktable --gimp version: "
                f"{probe.stderr[:300]!r} / {probe.stdout[:200]!r}; GIMP log: {gimp.log_tail(15)}"
            )
        opening = asyncio.create_task(
            client.call_tool("gimp_open_with_options", {"path": str(dng), "procedure": "file-darktable-dng-load"})
        )
        deadline = time.monotonic() + 120
        while not darktable_windows():  # darktable's darkroom opens: the user looks, then closes it
            assert time.monotonic() < deadline, "darktable's window did not open"
            assert not opening.done(), opening.result()
            await asyncio.sleep(0.5)
        await asyncio.sleep(5)  # darktable shows the image
        window = darktable_windows()[-1]  # the user quits darktable: it hands the developed image to GIMP
        # darktable ignores synthetic key events: focus its window and type with XTEST, like a keyboard
        subprocess.run(["xdotool", "windowfocus", "--sync", window], capture_output=True)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+q"], capture_output=True)
        result = await asyncio.wait_for(opening, timeout=120)
        assert not result.is_error, result.content
        image = result.structured_content
        assert (image["width"], image["height"]) == (64, 64)
        png = tmp_path / "developed.png"
        await call(client, "gimp_export_image", image=image["id"], path=str(png))
    with Image.open(png) as developed:
        rgb = developed.convert("RGB")
        red, green = rgb.getpixel((16, 16)), rgb.getpixel((48, 16))
        blue, gray = rgb.getpixel((16, 48)), rgb.getpixel((48, 48))
    assert max(red) == red[0] and max(green) == green[1] and max(blue) == blue[2], (red, green, blue)  # type: ignore[index]
    assert max(gray) - min(gray) <= 12, gray  # type: ignore[arg-type,operator]  # neutral

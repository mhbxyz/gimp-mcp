"""Animations (#59) on a real GIMP; exported files read frame by frame with Pillow."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image, ImageSequence

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


def webp_animation(path: Path) -> tuple[int, list[int]]:
    """(loop count, frame durations) from the RIFF chunks: Pillow does not expose WebP durations."""
    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    loop, durations, offset = -1, [], 12
    while offset + 8 <= len(data):
        kind, size = data[offset : offset + 4], int.from_bytes(data[offset + 4 : offset + 8], "little")
        body = data[offset + 8 : offset + 8 + size]
        if kind == b"ANIM":
            loop = int.from_bytes(body[4:6], "little")
        elif kind == b"ANMF":
            durations.append(int.from_bytes(body[12:15], "little"))
        offset += 8 + size + (size & 1)
    return loop, durations


async def three_frames(client) -> tuple[str, list[str]]:
    """A 20x20 animation: red, then a green square over it, then blue (replace)."""
    image = (await call(client, "gimp_create_image", width=20, height=20, fill="#ff0000", layer_name="Red"))["id"]
    first = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    await call(client, "gimp_set_frame", item=first, duration_ms=200, disposal="combine")
    added = await call(client, "gimp_add_frame", image=image, name="Square", duration_ms=100, disposal="replace")
    square = added["added"]
    await call(client, "gimp_select_rectangle", image=image, x=5, y=5, width=10, height=10)
    await call(client, "gimp_fill", item=square, color="#00ff00")
    await call(client, "gimp_modify_selection", image=image, action="none")
    blue = await call(client, "gimp_add_frame", image=image, name="Blue", duration_ms=300, fill="#0000ff")
    return image, [first, square, blue["added"]]


async def test_frames_are_built_listed_and_previewed(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, items = await three_frames(client)
        frames = (await call(client, "gimp_list_frames", image=image))["frames"]
        assert [(f["name"], f["duration_ms"], f["disposal"]) for f in frames] == [
            ("Red", 200, "combine"), ("Square", 100, "replace"), ("Blue", 300, "combine"),
        ]  # fmt: skip
        assert [f["item"] for f in frames] == items

        copy = await call(client, "gimp_add_frame", image=image, index=1, duplicate_of=items[2], duration_ms=50)
        assert [f["name"] for f in copy["frames"]] == ["Red", "Blue", "Square", "Blue"]
        await call(client, "gimp_delete_layer", item=copy["added"])

        result = await client.call_tool("gimp_preview_frame", {"image": image, "index": 1})
        assert result.structured_content["frames_shown"] == [0, 1]  # red stays under the square
        block = next(block for block in result.content if block.type == "image")
        img = Image.open(io.BytesIO(base64.b64decode(block.data))).convert("RGB")
        assert img.getpixel((0, 0)) == (255, 0, 0) and img.getpixel((10, 10)) == (0, 255, 0)
        last = await client.call_tool("gimp_preview_frame", {"image": image, "index": 2})
        assert last.structured_content["frames_shown"] == [2]  # the square frame is replaced
        assert (await error(client, "gimp_preview_frame", image=image, index=3))["code"] == "INVALID_ARGUMENT"
        await call(client, "gimp_close_image", image=image, discard_changes=True)


@pytest.mark.parametrize("extension", ["gif", "webp"])
async def test_animated_exports_are_read_back_frame_by_frame(gimp: HeadlessGimp, tmp_path: Path, extension):
    async with mcp_client(gimp) as client:
        image, _ = await three_frames(client)
        path = tmp_path / f"anim.{extension}"
        result = await call(client, "gimp_export_animation", image=image, path=str(path))
        assert result["layers"] == "frames"
        with Image.open(path) as img:
            frames = [(frame.size, frame.info.get("duration")) for frame in ImageSequence.Iterator(img)]
            loop = img.info.get("loop", 0)
        if extension == "webp":
            loop, durations = webp_animation(path)
            frames = [(size, duration) for (size, _), duration in zip(frames, durations, strict=True)]
        assert loop == 0  # loop forever
        assert [size for size, _ in frames] == [(20, 20)] * 3
        assert [duration for _, duration in frames] == [200, 100, 300]

        once = tmp_path / f"once.{extension}"
        await call(
            client, "gimp_export_animation", image=image, path=str(once), loop=False, default_delay=40, force=True
        )
        if extension == "webp":
            loop, durations = webp_animation(once)
        else:
            with Image.open(once) as img:
                durations = [frame.info.get("duration") for frame in ImageSequence.Iterator(img)]
                loop = img.info.get("loop", 1)
        assert durations == [40, 40, 40]  # forced on every frame
        assert loop != 0  # played once
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_optimize_and_unoptimize_make_new_images(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image, _ = await three_frames(client)
        optimized = await call(client, "gimp_optimize_animation", image=image)
        assert optimized["image"] != image and len(optimized["frames"]) == 3
        full = await call(client, "gimp_optimize_animation", image=optimized["image"], mode="unoptimize")
        sizes = [
            (n["width"], n["height"]) for n in (await call(client, "gimp_inspect_image", image=full["image"]))["layers"]
        ]
        assert sizes == [(20, 20)] * 3  # every frame complete again
        assert len((await call(client, "gimp_inspect_image", image=image))["layers"]) == 3  # original unchanged
        refused = await error(client, "gimp_export_animation", image=image, path="/tmp/x.png")
        assert refused["code"] in ("UNSUPPORTED_FORMAT", "FILE_EXISTS")
        for each in (image, optimized["image"], full["image"]):
            await call(client, "gimp_close_image", image=each, discard_changes=True)

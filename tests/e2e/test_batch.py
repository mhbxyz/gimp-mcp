"""Batch processing (#61) on a real GIMP: a generated folder, outputs read back with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error

RESIZE = {"tool": "gimp_resize_image", "arguments": {"image": "{image}", "width": 10, "height": 5}}
FLIP = {"tool": "gimp_flip_image", "arguments": {"image": "{image}", "orientation": "horizontal"}}
WEBP = {"tool": "gimp_export_as", "arguments": {"image": "{image}", "path": "{output}", "options": {"lossless": True}}}


def two_colors(path: Path, left: tuple[int, int, int], right: tuple[int, int, int]) -> Path:
    """A 40x20 image: left half one color, right half another."""
    img = Image.new("RGB", (40, 20), left)
    img.paste(right, (20, 0, 40, 20))
    img.save(path)
    return path


def folder(tmp_path: Path) -> Path:
    source = tmp_path / "in"
    (source / "sub").mkdir(parents=True)
    two_colors(source / "a.png", (255, 0, 0), (0, 0, 255))
    two_colors(source / "b.png", (0, 255, 0), (255, 255, 255))
    two_colors(source / "sub" / "c.png", (0, 0, 0), (255, 255, 0))
    (source / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really a png")
    return source


async def open_images(client) -> list[str]:
    return [image["id"] for image in (await call(client, "gimp_status"))["images"]]


async def test_recipe_over_a_folder_converts_and_reports_failures(gimp: HeadlessGimp, tmp_path: Path):
    source = folder(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    before = {path: path.read_bytes() for path in source.rglob("*.png")}
    async with mcp_client(gimp) as client:
        already = await open_images(client)
        report = await call(
            client, "gimp_run_batch", directory=str(source), pattern="**/*.png", recipe=[RESIZE, FLIP, WEBP],
            output=str(out / "{stem}-small.webp"),
        )  # fmt: skip
        assert [(Path(f["file"]).name, f["status"]) for f in report["files"]] == [
            ("a.png", "ok"), ("b.png", "ok"), ("broken.png", "failed"), ("c.png", "ok"),
        ]  # fmt: skip
        assert (report["succeeded"], report["failed"], report["skipped"]) == (3, 1, 0)
        broken = report["files"][2]
        assert broken["error"]["step"] is None and broken["error"]["tool"] == "gimp_open_image"
        assert broken["error"]["code"] == "UNSUPPORTED_FORMAT"  # GIMP's loader gives no image
        assert broken["outputs"] == [] and not (out / "broken-small.webp").exists()
        assert await open_images(client) == already  # every image the batch opened is closed

    written = sorted(p.name for p in out.iterdir())
    assert written == ["a-small.webp", "b-small.webp", "c-small.webp"]
    expected = {"a": ((0, 0, 255), (255, 0, 0)), "b": ((255, 255, 255), (0, 255, 0)), "c": ((255, 255, 0), (0, 0, 0))}
    for stem, (left, right) in expected.items():
        with Image.open(out / f"{stem}-small.webp") as img:
            assert img.format == "WEBP" and img.size == (10, 5)
            rgb = img.convert("RGB")
            # flipped: the right color is now on the left; lossless WebP keeps exact values
            assert rgb.getpixel((1, 2)) == left and rgb.getpixel((8, 2)) == right
    assert {path: path.read_bytes() for path in source.rglob("*.png")} == before  # inputs untouched


async def test_failures_can_stop_the_batch_and_outputs_are_not_overwritten(gimp: HeadlessGimp, tmp_path: Path):
    source = folder(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    files = [str(source / name) for name in ("a.png", "broken.png", "b.png")]
    async with mcp_client(gimp) as client:
        already = await open_images(client)
        stopped = await call(client, "gimp_run_batch", files=files, recipe=[FLIP], continue_on_error=False)
        assert [f["status"] for f in stopped["files"]] == ["ok", "failed", "skipped"]
        assert await open_images(client) == already

        # a step failing inside GIMP: a.png is 40x20, the crop is outside it
        crop = {"tool": "gimp_crop_image", "arguments": {"image": "{image}", "x": 100, "y": 0, "width": 5, "height": 5}}
        failed = await call(client, "gimp_run_batch", files=files[:1], recipe=[crop])
        assert failed["files"][0]["status"] == "failed" and failed["files"][0]["error"]["step"] == 0
        assert await open_images(client) == already

        export = {"tool": "gimp_export_image", "arguments": {"image": "{image}", "path": "{output}"}}
        (out / "b.png").write_bytes(b"keep me")
        refused = await error(
            client, "gimp_run_batch", files=[files[0], files[2]], recipe=[FLIP, export], output=str(out / "{name}")
        )
        assert refused["code"] == "FILE_EXISTS"
        assert (out / "b.png").read_bytes() == b"keep me" and not (out / "a.png").exists()
        no_orientation = {"tool": "gimp_flip_image", "arguments": {"image": "{image}"}}
        bad_step = await error(client, "gimp_run_batch", files=files[:1], recipe=[no_orientation])
        assert bad_step["code"] == "INVALID_ARGUMENT" and "orientation" in bad_step["message"]
        assert await open_images(client) == already  # refused before anything was opened

        done = await call(
            client, "gimp_run_batch", files=[files[0], files[2]], recipe=[FLIP, export], output=str(out / "{name}"),
            overwrite=True,
        )  # fmt: skip
        assert done["succeeded"] == 2
    with Image.open(out / "b.png") as img:
        assert img.convert("RGB").getpixel((0, 0)) == (255, 255, 255)  # replaced, and flipped

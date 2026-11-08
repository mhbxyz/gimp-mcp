"""Every demo scenario (#107) on a real GIMP: its own checks pass, and its files are checked again here.

The scenario's checks run through MCP; the verifications below read its output files with Pillow,
independently of the scenario's code.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from demo.harness import Report, load, run_scenario, scenario_names
from gimp_mcp.headless import HeadlessGimp

from .conftest import server_params


def thumbnail(out: Path, report: Report) -> None:
    # toolsets (#45): only what the demo needs was listed, and that was enough
    assert {"gimp_call_procedure", "gimp_search_procedures"}.isdisjoint(report.listed_tools)
    assert len(report.listed_tools) < 52 and len(report.checks) >= 13
    with Image.open(out / "thumbnail.png") as png:
        assert png.size == (1280, 720)
        r, g, b = png.convert("RGB").getpixel((20, 650))  # type: ignore[misc]
        assert max(r, g, b) < 90  # dark banner behind the title
    with Image.open(out / "thumbnail.jpg") as jpg:
        assert jpg.format == "JPEG" and jpg.size == (1280, 720)
    assert (out / "thumbnail.xcf").read_bytes().startswith(b"gimp xcf")
    assert sorted(p.name for p in (out / "previews").iterdir()) == [
        "01-backdrop.png", "02-subject.png", "03-title.png", "04-retitled.png", "05-badge.png",
        "06-undo.png", "07-redo.png", "08-final.png",
    ]  # fmt: skip
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "`gimp_restore_checkpoint`" in text and "`gimp_set_text`" in text and "`gimp_export_image`" in text


def old_photo_restoration(out: Path, report: Report) -> None:
    with Image.open(out / "scan.png") as scan:
        assert scan.size == (1400, 950)
    with Image.open(out / "restored-print.tif") as tiff:
        assert tiff.format == "TIFF" and tiff.size == (1176, 726)
        assert set(tiff.tag_v2[258]) == {16}  # BitsPerSample  # type: ignore[attr-defined]
        assert tuple(round(float(v)) for v in tiff.info["dpi"]) == (300, 300)
    with Image.open(out / "restored-web.jpg") as jpeg:
        assert jpeg.format == "JPEG" and jpeg.size == (1176, 726)
        gray = jpeg.convert("L")
        histogram = gray.histogram()
        assert sum(histogram[:26]) > 0.01 * sum(histogram) and sum(histogram[230:]) > 0.01 * sum(histogram)
        border = [gray.getpixel((x, 0)) for x in range(gray.width)] + [
            gray.getpixel((0, y)) for y in range(gray.height)
        ]
        assert max(border) < 250  # type: ignore[type-var]  # no white scanner bed


def product_cutout(out: Path, report: Report) -> None:
    import io

    from PIL import ImageCms

    assert (out / "product.xcf").read_bytes().startswith(b"gimp xcf")
    for size in (2000, 800, 400):
        for ext, fmt in (("jpg", "JPEG"), ("webp", "WEBP")):
            with Image.open(out / f"product-{size}.{ext}") as img:
                assert img.format == fmt and img.size == (size, size)
                profile = ImageCms.ImageCmsProfile(io.BytesIO(img.info["icc_profile"]))
                assert "sRGB" in ImageCms.getProfileDescription(profile)
    with Image.open(out / "product-2000.webp") as webp:
        rgb = webp.convert("RGB")
        corners = [rgb.getpixel(xy) for xy in ((0, 0), (1999, 0), (0, 1999), (1999, 1999), (1000, 5), (5, 1000))]
        assert set(corners) == {(255, 255, 255)}
        saturated = rgb.convert("HSV").split()[1].point([255 if v > 90 else 0 for v in range(256)]).getbbox()
        assert saturated is not None
        x0, y0, x1, y1 = saturated
        assert abs((x0 + x1) / 2 - 1000) <= 20 and abs((y0 + y1) / 2 - 1000) <= 20
        assert abs(max(x1 - x0, y1 - y0) - 1800) <= 24


def social_media_kit(out: Path, report: Report) -> None:
    sizes = {"post": (1080, 1080), "story": (1080, 1920), "banner": (1500, 500), "thumbnail": (1280, 720)}
    for name, size in sizes.items():
        with Image.open(out / f"social-{name}.png") as png:
            assert png.size == size
            navy = png.convert("RGB").getpixel((4, size[1] - 4))  # bottom-left corner: the brand band
            assert navy == (0x1D, 0x35, 0x57), navy
        xcf = (out / f"social-{name}.xcf").read_bytes()
        assert xcf.startswith(b"gimp xcf") and b"gimp-text-layer" in xcf and b"Golden Hour Sale" in xcf
    assert sum("guides on the safe area" in c.description and c.passed for c in report.checks) == 4


def screenshot_annotation(out: Path, report: Report) -> None:
    import struct

    with Image.open(out / "screenshot.png") as before, Image.open(out / "tutorial.png") as after:
        assert after.format == "PNG" and after.size == before.size == (1280, 800)
        a, b = before.convert("RGB"), after.convert("RGB")
        # far from every annotation: the sidebar and the header's left part are untouched
        assert a.crop((0, 140, 260, 800)).tobytes() == b.crop((0, 140, 260, 800)).tobytes()
        assert a.crop((0, 0, 1000, 140)).tobytes() == b.crop((0, 0, 1000, 140)).tobytes()
        # no dark glyph remains in the e-mail field
        assert sum(b.crop((424, 312, 760, 332)).convert("L").histogram()[:100]) == 0
    data, chunks, pos = (out / "tutorial.png").read_bytes(), [], 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        chunks.append(kind)
        pos += 12 + length
    assert not {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"} & set(chunks), chunks


def web_photo_batch(out: Path, report: Report) -> None:
    from demo.scenarios.web_photo_batch import PHOTOS

    web = out / "web"
    assert sorted(p.name for p in web.iterdir()) == sorted(f"{n}-web.{e}" for n in PHOTOS for e in ("jpg", "webp"))
    for name, (w, h, _, _) in PHOTOS.items():
        with Image.open(web / f"{name}-web.jpg") as jpeg:
            assert max(jpeg.size) == 1600, (name, jpeg.size)
            assert w == h or (jpeg.width > jpeg.height) == (w > h), (name, jpeg.size)  # landscape stays landscape
            exif = jpeg.getexif()
            assert not exif.get_ifd(0x8825) and exif.get(0x8298) == "(c) 2026 Ana Lima", name
            r, g, b = jpeg.convert("RGB").getpixel((20, 20))  # type: ignore[misc]
            assert r > 170 and g < 90 and b < 90, (name, (r, g, b))  # upright: the red marker is top-left


def animated_sticker(out: Path, report: Report) -> None:
    from demo.scenarios.animated_sticker import webp_durations

    with Image.open(out / "sticker.gif") as gif:
        frames = getattr(gif, "n_frames", 1)
        assert gif.format == "GIF" and gif.size == (480, 240) and frames == 12 and gif.info["loop"] == 0
        positions = []
        for k in range(12):
            gif.seek(k)
            row = gif.convert("RGB").crop((0, 128, 480, 129))
            background = (253, 246, 227)  # the logo's left edge: the first pixel that is not the background
            pixels = [row.getpixel((x, 0)) for x in range(480)]
            logo = [x for x, p in enumerate(pixels) if max(abs(a - b) for a, b in zip(p, background, strict=True)) > 8]  # type: ignore[arg-type]
            positions.append(min(logo) if logo else None)
        assert positions == [40 + 24 * k for k in range(12)], positions  # the logo slides 24 px per frame
    assert webp_durations(out / "sticker.webp") == [80] * 11 + [1000]
    assert (out / "sticker.gif").stat().st_size < 500 * 1024 and (out / "sticker.webp").stat().st_size < 500 * 1024


INDEPENDENT: dict[str, Callable[[Path, Report], None]] = {
    "thumbnail": thumbnail,
    "old-photo-restoration": old_photo_restoration,
    "product-cutout": product_cutout,
    "social-media-kit": social_media_kit,
    "screenshot-annotation": screenshot_annotation,
    "web-photo-batch": web_photo_batch,
    "animated-sticker": animated_sticker,
}


def test_every_scenario_has_independent_verifications():
    assert set(INDEPENDENT) == set(scenario_names())


@pytest.mark.parametrize("name", scenario_names())
async def test_scenario_produces_verified_outputs(name: str, gimp_factory, tmp_path: Path, monkeypatch):
    # its own GIMP, in English like `demo/run.py` (metadata values are localized: #161)
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    gimp: HeadlessGimp = gimp_factory()
    scenario = load(name)
    report = await run_scenario(scenario, tmp_path, server_params(gimp))
    failed = [check for check in report.checks if not check.passed]
    assert not failed, "\n".join(f"{'ok ' if c.passed else 'FAIL'} {c.description}: {c.detail}" for c in report.checks)
    assert {call.tool for call in report.calls} <= report.listed_tools
    for output in scenario.outputs:
        assert (tmp_path / output).is_file(), output
    assert "Result: **PASS**" in (tmp_path / "report.md").read_text(encoding="utf-8")
    INDEPENDENT[name](tmp_path, report)

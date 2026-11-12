"""Prepare a folder of photos for a website: JPEG (some with an EXIF orientation), PNG and TIFF of mixed
sizes, plus one corrupt file. Rotate as EXIF says, fit the longest side to 1600 px, convert to sRGB,
watermark with the logo at 60% in the bottom-right corner, drop the GPS position but keep the
copyright, and export WebP and JPEG named `<name>-web`.

The photos are drawn by code (CC0): each has a red marker in its top-left corner as it should be seen,
stored rotated when its EXIF orientation says so, a copyright and a GPS position. A batch recipe applies
the same steps to every file, so the files are first read through MCP (size, orientation) and grouped:
one `gimp_run_batch` per group, the corrupt file in one of them.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat

from demo.harness import Check, Report, Scenario, Session

LONGEST = 1600
LOGO = 200  # watermark side (px) on the 1600 px outputs
MARGIN = 32
OPACITY = 60
COPYRIGHT = "(c) 2026 Ana Lima"
GPS_TAGS = ("Exif.GPSInfo.GPSLatitudeRef", "Exif.GPSInfo.GPSLatitude", "Exif.GPSInfo.GPSLongitudeRef",
            "Exif.GPSInfo.GPSLongitude", "Exif.GPSInfo.GPSVersionID", "Exif.Image.GPSTag")  # fmt: skip
TEAL = (42, 157, 143)
# name: (width, height as seen, format, EXIF orientation of the stored file)
PHOTOS: dict[str, tuple[int, int, str, int]] = {
    "beach": (3000, 2000, "JPEG", 1), "harbor": (2400, 1600, "JPEG", 1), "market": (1800, 1200, "JPEG", 1),
    "tower": (2000, 3000, "JPEG", 6), "stairs": (1200, 1800, "JPEG", 8), "door": (1600, 2400, "JPEG", 6),
    "cafe": (2000, 2000, "JPEG", 1), "tiles": (1500, 1500, "PNG", 1), "bridge": (2400, 1600, "PNG", 1),
    "garden": (1600, 2400, "PNG", 1), "river": (3000, 2000, "TIFF", 1), "street": (1800, 1200, "TIFF", 1),
    "lamp": (1200, 1800, "TIFF", 1), "plaza": (2100, 1400, "JPEG", 1), "boat": (1500, 1000, "JPEG", 1),
    "church": (1400, 2100, "JPEG", 8), "dog": (1800, 1800, "JPEG", 6), "roof": (2700, 1800, "PNG", 1),
    "train": (1200, 800, "JPEG", 1), "fountain": (1000, 1500, "TIFF", 1),
}  # fmt: skip
EXT = {"JPEG": "jpg", "PNG": "png", "TIFF": "tif"}
CORRUPT = "broken.jpg"


def exif_bytes(orientation: int) -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x8298] = COPYRIGHT
    exif.get_ifd(0x8825).update({1: "N", 2: (38.0, 42.0, 51.0), 3: "W", 4: (9.0, 8.0, 21.0)})
    return exif


def make_photos(folder: Path) -> None:
    """The input folder: each photo a gradient with a red marker at the top-left as seen."""
    folder.mkdir(parents=True, exist_ok=True)
    for index, (name, (w, h, fmt, orientation)) in enumerate(PHOTOS.items()):
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        for y in range(0, h, 4):
            shade = 40 + (index * 9 + y * 160 // h) % 180
            draw.rectangle((0, y, w, y + 4), fill=(shade, 110 + index * 5 % 90, 200 - shade // 2))
        side = min(w, h) // 8
        draw.rectangle((0, 0, side, side), fill=(230, 20, 20))
        # stored as a camera would: rotated, with the orientation that undoes it
        stored = {1: img, 6: img.transpose(Image.Transpose.ROTATE_90), 8: img.transpose(Image.Transpose.ROTATE_270)}[
            orientation
        ]
        stored.save(folder / f"{name}.{EXT[fmt]}", format=fmt, exif=exif_bytes(orientation),
                    **({"quality": 92} if fmt == "JPEG" else {}))  # fmt: skip
    (folder / CORRUPT).write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg" * 20)


def make_logo(path: Path, alpha: int = 255) -> None:
    img = Image.new("RGBA", (LOGO, LOGO), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, LOGO - 1, LOGO - 1), radius=40, fill=(*TEAL, alpha))
    img.save(path)


def orientation_of(value: object) -> int:
    """EXIF orientation 6 or 8 from what gimp_get_metadata returns: Exiv2's interpreted value in GIMP's
    language ("right, top" for 6, "left, bottom" for 8; the demos run GIMP in English) or a number
    (#161: no raw value yet). Anything else is treated as upright."""
    import re

    text = str(value).strip().lower()
    if text in ("6", "8"):
        return int(text)
    words = set(re.findall(r"[a-z]+", text))
    if {"right", "top"} <= words:
        return 6
    if {"left", "bottom"} <= words:
        return 8
    return 1


def target_size(w: int, h: int) -> tuple[int, int]:
    scale = LONGEST / max(w, h)
    return round(w * scale), round(h * scale)


def digest(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


async def steps(gimp: Session, report: Report) -> None:
    out = gimp.out
    photos, web = out / "photos", out / "web"
    make_photos(photos)
    web.mkdir(exist_ok=True)
    logo, srgb = out / "logo.png", out / "sRGB.icc"
    # a recipe cannot change the layer it imported ({layer} is the top layer at open, #162): the
    # watermark file carries its 60% opacity itself
    make_logo(logo, alpha=round(255 * OPACITY / 100))
    from demo.scenarios.product_cutout import srgb_profile

    srgb.write_bytes(srgb_profile())
    before = digest(photos)
    await gimp.call("gimp_enable_toolsets", toolsets=["batch", "document", "geometry", "modes", "formats"])

    # Read each file once (size and EXIF orientation), then group the files a recipe can share.
    groups: dict[tuple[int, int, int], list[str]] = {}
    read: dict[str, str] = {}  # the orientation value GIMP returned for each file (in the report)
    for path in sorted(photos.iterdir()):
        if path.name == CORRUPT:
            continue
        image = (await gimp.call("gimp_open_image", path=str(path)))["id"]
        info = await gimp.call("gimp_inspect_image", image=image)
        exif = (await gimp.call("gimp_get_metadata", image=image))["exif"]
        await gimp.call("gimp_close_image", image=image)
        value = str(exif.get("Exif.Image.Orientation", "")).strip()  # GIMP reads it on every OS (#173)
        read[path.stem] = f"{info['width']}x{info['height']} {value}"
        orientation = orientation_of(value)
        groups.setdefault((info["width"], info["height"], orientation), []).append(str(path))
    report.check("every photo was read (size, orientation)", sum(len(g) for g in groups.values()) == len(PHOTOS),
                 f"{len(groups)} groups; read: {read}")  # fmt: skip
    first = True
    results: list[dict] = []
    for (w, h, orientation), files in sorted(groups.items()):
        seen = (h, w) if orientation in (6, 8) else (w, h)
        tw, th = target_size(*seen)
        recipe: list[dict] = []
        if orientation in (6, 8):  # 6: the camera was turned right, undo it clockwise; 8: counter-clockwise
            angle = 90 if orientation == 6 else 270
            recipe.append({"tool": "gimp_rotate_image", "arguments": {"image": "{image}", "angle": angle}})
        recipe += [
            {"tool": "gimp_resize_image", "arguments": {"image": "{image}", "width": tw, "height": th}},
            {"tool": "gimp_set_metadata", "arguments": {"image": "{image}", "remove": list(GPS_TAGS),
                                                       "set": {"Exif.Image.Orientation": "1"}}},
            {"tool": "gimp_set_color_profile", "arguments": {"image": "{image}", "action": "convert",
                                                            "profile": "file", "path": str(srgb)}},
            {"tool": "gimp_import_layer", "arguments": {"image": "{image}", "path": str(logo), "name": "Watermark",
                                                       "x": tw - MARGIN - LOGO, "y": th - MARGIN - LOGO}},
            {"tool": "gimp_export_as", "arguments": {"image": "{image}", "path": "{output}", "metadata": ["exif"],
                                                    "options": {"quality": 85}}},
            {"tool": "gimp_export_image", "arguments": {"image": "{image}", "path": str(web / "{stem}-web.jpg"),
                                                       "overwrite": True,
                                                       "jpeg_options": {"quality": 85, "metadata": ["exif"],
                                                                        "color_profile": True}}},
        ]  # fmt: skip
        if first:  # the corrupt file goes with the first group: it must be reported, not stop the others
            files = [*files, str(photos / CORRUPT)]
            first = False
        run = await gimp.call("gimp_run_batch", files=files, recipe=recipe, output=str(web / "{stem}-web.webp"),
                              overwrite=True)  # fmt: skip
        results += run["files"]
    corrupt = [r for r in results if r["file"].endswith(CORRUPT)]
    others = [r for r in results if not r["file"].endswith(CORRUPT)]
    code = corrupt[0]["error"]["code"] if corrupt and corrupt[0]["error"] else "?"
    done = len(corrupt) == 1 and corrupt[0]["status"] == "failed" and all(r["status"] == "ok" for r in others)
    detail = f"{code}; {sum(r['status'] == 'ok' for r in others)} ok"
    report.check("the corrupt file is reported as failed, the others are done", done, detail)
    report.check("the input files are unchanged (SHA-256)", digest(photos) == before)
    shown_files = (
        (photos / "tower.jpg", "01-tower-stored", "1. tower.jpg as stored (EXIF: turn it)"),
        (web / "tower-web.webp", "02-tower-web", "2. tower-web.webp: upright, 1600 px, watermarked"),
    )
    for path, name, title in shown_files:
        shown = (await gimp.call("gimp_open_image", path=str(path)))["id"]
        await gimp.preview(shown, name, title, max_size=480)
        await gimp.call("gimp_close_image", image=shown)
    for check in verify(web):
        report.check(check.description, check.passed, check.detail)


def verify(web: Path) -> list[Check]:
    """Facts on the exports, read with Pillow (shared by the scripted and the agent versions)."""
    sizes, markers, marks, gps, rights, profiles = [], [], [], [], [], []
    for name, (w, h, _, _) in PHOTOS.items():
        for ext in ("webp", "jpg"):
            path = web / f"{name}-web.{ext}"
            try:
                img = Image.open(path)
                img.load()
            except OSError:
                sizes.append(f"{path.name} missing")
                continue
            tw, th = target_size(w, h)
            if img.size != (tw, th):
                sizes.append(f"{path.name} {img.size} != {(tw, th)}")
                continue
            rgb = img.convert("RGB")
            side = min(tw, th) // 8
            r, g, b = rgb.getpixel((side // 2, side // 2))  # type: ignore[misc]
            if not (r > 170 and g < 90 and b < 90):
                markers.append(f"{path.name} {(r, g, b)}")
            center = (tw - MARGIN - LOGO // 2, th - MARGIN - LOGO // 2)
            mark = rgb.getpixel(center)
            under = ImageStat.Stat(rgb.crop((tw - MARGIN - LOGO - 60, th - MARGIN - LOGO // 2 - 5,
                                             tw - MARGIN - LOGO - 40, th - MARGIN - LOGO // 2 + 5))).mean  # fmt: skip
            expected = [0.6 * t + 0.4 * u for t, u in zip(TEAL, under, strict=True)]
            if max(abs(m - e) for m, e in zip(mark, expected, strict=True)) > 40:  # type: ignore[arg-type]
                marks.append(f"{path.name} {mark} ~ {tuple(round(e) for e in expected)}")
            exif = img.getexif()
            if exif.get_ifd(0x8825) or 0x8825 in exif:
                gps.append(path.name)
            if exif.get(0x8298) != COPYRIGHT:
                rights.append(f"{path.name} {exif.get(0x8298)!r}")
            icc = img.info.get("icc_profile") or b""
            if b"sRGB" not in icc and not _srgb_name(icc):
                profiles.append(path.name)
    count = len(PHOTOS) * 2
    return [
        Check(f"every photo has a WebP and a JPEG, longest side {LONGEST} px", not sizes,
              "; ".join(sizes[:6]) or f"{count} files"),
        Check("each is upright as EXIF said (red marker top-left)", not markers, "; ".join(markers[:6])),
        Check("the watermark is in the bottom-right corner at about 60%", not marks, "; ".join(marks[:6])),
        Check("no GPS position in any export", not gps, ", ".join(gps[:6])),
        Check("the copyright is kept in every export", not rights, "; ".join(rights[:6])),
        Check("every export carries an sRGB profile", not profiles, ", ".join(profiles[:6])),
    ]  # fmt: skip


def _srgb_name(icc: bytes) -> bool:
    if not icc:
        return False
    from PIL import ImageCms

    return "sRGB" in ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))


def agent_check(out: Path, answer: str) -> list[Check]:
    return verify(out / "web")


def agent_reference(inputs: Path, out: Path) -> None:
    from PIL import ImageOps

    from demo.scenarios.product_cutout import srgb_profile

    web = out / "web"
    logo = Image.open(inputs / "logo.png").convert("RGBA")
    logo.putalpha(logo.getchannel("A").point([v * OPACITY // 100 for v in range(256)]))
    for name, (w, h, fmt, _) in PHOTOS.items():
        img = ImageOps.exif_transpose(Image.open(inputs / "photos" / f"{name}.{EXT[fmt]}")).convert("RGB")
        tw, th = target_size(w, h)
        img = img.resize((tw, th))
        img.paste(logo, (tw - MARGIN - LOGO, th - MARGIN - LOGO), logo)
        exif = Image.Exif()
        exif[0x8298] = COPYRIGHT
        for ext, fmt_out in (("webp", "WEBP"), ("jpg", "JPEG")):
            img.save(web / f"{name}-web.{ext}", format=fmt_out, exif=exif, icc_profile=srgb_profile())


def inputs_for_the_agent(directory: Path) -> None:
    make_photos(directory / "photos")
    make_logo(directory / "logo.png")


SCENARIO = Scenario(
    name="web-photo-batch",
    title="prepare a folder of photos for a website",
    toolsets=("files", "layers", "transform", "batch", "document", "geometry", "modes", "formats"),
    assets=(),
    outputs=("logo.png", "web/beach-web.webp", "web/beach-web.jpg"),
    steps=steps,
    prompt=(
        "~/inputs/photos/ holds 21 photos for a website (JPEG, PNG and TIFF of mixed sizes, some JPEGs with an "
        "EXIF orientation); one file is corrupt. For every photo: turn it upright as its EXIF orientation says, "
        "scale it so its longest side is 1600 pixels, convert it to sRGB, add the logo ~/inputs/logo.png at 60% "
        "opacity in the bottom-right corner (200x200 px, 32 px from both edges), remove the GPS position but keep "
        "the copyright, and export it as ~/out/web/<name>-web.webp and ~/out/web/<name>-web.jpg, both with an "
        "sRGB profile (for example ~/out/web/train-web.jpg). Do not modify the input files, and tell me which file "
        "could not be processed."
    ),
    agent_output="web/train-web.jpg",
    make_agent_inputs=inputs_for_the_agent,
    agent_check=agent_check,
    agent_reference=agent_reference,
    agent_out_dirs=("web",),
)

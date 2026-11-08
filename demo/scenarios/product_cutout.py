"""Cut a product out of its studio backdrop for an online store: fuzzy-select the backdrop, invert,
refine the edge, keep the cut-out non-destructive (a layer mask), add a soft drop shadow on pure
white, center it on a 2000x2000 canvas with a 5% margin, then export JPEG and WebP at 2000, 800 and
400 px with an sRGB profile.

The product shot is generated (a bottle on a light-gray sweep, drawn by code: CC0), so the product's
outline, colors and bounding box are known in advance.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from demo.harness import Check, Report, Scenario, Session, find

SHOT = (1600, 1200)
BOX = (620, 180, 980, 1080)  # the bottle's bounding box on the shot (x0, y0, x1, y1), exclusive
CANVAS, MARGIN = 2000, 0.05
SIZES = (2000, 800, 400)
BACKDROP_TOP, BACKDROP_BOTTOM = (232, 232, 236), (214, 214, 220)


def make_shot(path: Path) -> None:
    """A red bottle with a dark-blue cap and a yellow label on a light-gray sweep, antialiased (drawn
    at 2x, then halved), with a little sensor noise on the backdrop."""
    rng = random.Random(1909)
    big = Image.new("RGB", (SHOT[0] * 2, SHOT[1] * 2))
    draw = ImageDraw.Draw(big)
    for y in range(big.height):  # the sweep: a vertical gradient
        t = y / (big.height - 1)
        draw.line(
            [(0, y), (big.width, y)],
            fill=tuple(round(a + (b - a) * t) for a, b in zip(BACKDROP_TOP, BACKDROP_BOTTOM, strict=True)),
        )
    x0, y0, x1, y1 = (v * 2 for v in BOX)
    draw.rounded_rectangle((x0, y0 + 360, x1, y1), radius=110, fill=(196, 34, 48))  # body
    draw.rounded_rectangle((x0 + 220, y0 + 150, x1 - 220, y0 + 380), radius=40, fill=(196, 34, 48))  # neck
    draw.rounded_rectangle((x0 + 200, y0, x1 - 200, y0 + 170), radius=24, fill=(28, 40, 96))  # cap
    draw.rectangle((x0 + 40, y0 + 860, x1 - 40, y0 + 1300), fill=(242, 198, 58))  # label
    draw.ellipse((x0 + 230, y0 + 960, x1 - 230, y0 + 1200), fill=(196, 34, 48))  # label mark
    shot = big.resize(SHOT, Image.Resampling.LANCZOS)
    noise = Image.new("L", SHOT)
    noise.putdata([128 + round(rng.gauss(0, 1.5)) for _ in range(SHOT[0] * SHOT[1])])
    shot = Image.merge("RGB", [ImageChops.add(band, noise, 1.0, -128) for band in shot.split()])
    shot.save(path)


def product_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the product's saturated pixels (the shadow and the white are neutral)."""
    return img.convert("RGB").convert("HSV").split()[1].point([255 if v > 90 else 0 for v in range(256)]).getbbox()


def layout() -> tuple[float, int, int]:
    """Scale factor and canvas offsets that put BOX centered with a 5% margin on a 2000x2000 canvas."""
    w, h = BOX[2] - BOX[0], BOX[3] - BOX[1]
    scale = CANVAS * (1 - 2 * MARGIN) / max(w, h)
    cx, cy = (BOX[0] + BOX[2]) / 2 * scale, (BOX[1] + BOX[3]) / 2 * scale
    return scale, round(CANVAS / 2 - cx), round(CANVAS / 2 - cy)


async def steps(gimp: Session, report: Report) -> None:
    out = gimp.out
    shot_path = out / "shot.png"
    make_shot(shot_path)
    image = (await gimp.call("gimp_open_image", path=str(shot_path)))["id"]
    await gimp.call("gimp_enable_toolsets", toolsets=["channels", "formats", "modes", "analysis"])
    await gimp.preview(image, "01-shot", "1. The studio shot")

    # Scale and place first: the cut-out then happens at the final resolution.
    scale, ox, oy = layout()
    await gimp.call("gimp_resize_image", image=image, width=round(SHOT[0] * scale), height=round(SHOT[1] * scale))
    await gimp.call("gimp_resize_canvas", image=image, width=CANVAS, height=CANVAS, offset_x=ox, offset_y=oy)
    product = (await gimp.call("gimp_inspect_image", image=image))["layers"][0]["id"]
    await gimp.call("gimp_set_layer_properties", item=product, name="Product")

    # Cut-out: the backdrop by fuzzy select from a corner of the shot, inverted, edge refined.
    await gimp.call("gimp_select_by_color", image=image, point=[20, 20], item=product, threshold=40)
    await gimp.call("gimp_modify_selection", image=image, action="invert")
    await gimp.call("gimp_modify_selection_shape", image=image, action="shrink", amount=2)
    await gimp.call("gimp_modify_selection_shape", image=image, action="feather", amount=1)
    masked = await gimp.call("gimp_add_layer_mask", item=product, fill="selection")
    report.check("the cut-out is a layer mask (non-destructive)", masked.get("mask") is not None)

    # Drop shadow: a soft contact shadow where the bottle stands, on its own layer under it.
    await gimp.call("gimp_modify_selection", image=image, action="none")
    shadow = (await gimp.call("gimp_create_layer", image=image, name="Shadow", position=1))["id"]
    left, right, bottom = BOX[0] * scale + ox, BOX[2] * scale + ox, BOX[3] * scale + oy
    await gimp.call("gimp_select_ellipse", image=image, x=round(left + 40), y=round(bottom - 30),
                    width=round(right - left - 80), height=70)  # fmt: skip
    await gimp.call("gimp_fill", item=shadow, color="#000000")
    await gimp.call("gimp_modify_selection", image=image, action="none")
    await gimp.call("gimp_gaussian_blur", item=shadow, radius=40)
    await gimp.call("gimp_set_layer_properties", item=shadow, opacity=45)
    await gimp.call("gimp_create_layer", image=image, name="White", position=2, fill="white")
    # assigning GIMP's built-in sRGB is a no-op (it is the default: nothing is embedded in WebP), so an
    # sRGB ICC file is assigned (docs/gimp-notes.md, #158)
    icc = out / "sRGB.icc"
    icc.write_bytes(srgb_profile())
    await gimp.call("gimp_set_color_profile", image=image, action="assign", profile="file", path=str(icc))
    await gimp.preview(image, "02-cutout", "2. Cut out, centered with a 5% margin, soft shadow on white")

    xcf = out / "product.xcf"
    await gimp.call("gimp_save_image", image=image, path=str(xcf), overwrite=True)
    for size in SIZES:
        if size != CANVAS:
            await gimp.call("gimp_resize_image", image=image, width=size, height=size)
        await gimp.call("gimp_export_image", image=image, path=str(out / f"product-{size}.jpg"), overwrite=True,
                        jpeg_options={"quality": 90, "color_profile": True})  # fmt: skip
        await gimp.call("gimp_export_as", image=image, path=str(out / f"product-{size}.webp"), overwrite=True,
                        options={"lossless": True})  # fmt: skip
    await gimp.call("gimp_close_image", image=image, discard_changes=True)  # the XCF keeps the 2000 px master

    # Non-destructive: in the saved XCF, the product layer still holds the backdrop under its mask.
    reopened = (await gimp.call("gimp_open_image", path=str(xcf)))["id"]
    details = await gimp.call("gimp_inspect_image", image=reopened)
    layer = find(details, "Product")
    corner = [30, 30]  # backdrop: the canvas is a window inside the scaled shot
    sample = (await gimp.call("gimp_sample_colors", target=layer["id"], points=[corner], radius=2))["samples"][0]
    rgba = sample["rgba"]
    report.check("the XCF keeps the backdrop pixels under the mask", layer.get("mask") is not None and rgba[3] == 255
                 and all(200 <= v <= 240 for v in rgba[:3]), f"layer pixel at {corner}: {rgba}")  # fmt: skip
    await gimp.call("gimp_close_image", image=reopened)

    for check in verify(out):
        report.check(check.description, check.passed, check.detail)


def verify(out: Path, sizes: tuple[int, ...] = SIZES) -> list[Check]:
    """Facts on the exports, read with Pillow (shared by the scripted and the agent versions)."""
    checks = []
    for size in sizes:
        for ext in ("jpg", "webp"):
            path = out / f"product-{size}.{ext}"
            try:
                img = Image.open(path)
                img.load()
            except OSError as error:
                checks.append(Check(f"{path.name} is an image", False, str(error)))
                continue
            name = profile_name(img.info.get("icc_profile") or b"")
            ok = img.size == (size, size) and "sRGB" in name
            detail = f"{img.size}, profile {name or 'none'}"
            checks.append(Check(f"{path.name} is {size}x{size} with an sRGB profile", ok, detail))
    try:
        master = Image.open(out / "product-2000.webp").convert("RGB")
    except OSError:
        return [*checks, Check("product-2000.webp can be checked", False)]
    box = product_box(master)
    if box is None:
        return [*checks, Check("a product is visible", False)]
    w, h = box[2] - box[0], box[3] - box[1]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    centered = abs(cx - CANVAS / 2) <= 20 and abs(cy - CANVAS / 2) <= 20
    margin = abs(max(w, h) - CANVAS * (1 - 2 * MARGIN)) <= 24
    checks.append(Check("the product is centered with a 5% margin", centered and margin,
                        f"box {box}, center {cx:.0f},{cy:.0f}, largest side {max(w, h)} (target 1800)"))  # fmt: skip
    # outside the product and below it the shadow, everything is exactly white
    shadow_zone = (box[0] - 160, box[1], box[2] + 160, min(CANVAS, box[3] + 260))
    strips = [(0, 0, CANVAS, box[1] - 10), (0, 0, box[0] - 160, CANVAS), (box[2] + 160, 0, CANVAS, CANVAS),
              (0, shadow_zone[3], CANVAS, CANVAS)]  # fmt: skip
    not_white = sum(non_white(master.crop(s)) for s in strips if s[2] > s[0] and s[3] > s[1])
    checks.append(Check("outside the product and its shadow, pixels are exactly white", not_white == 0,
                        f"{not_white} other pixels"))  # fmt: skip
    gray = master.convert("L")
    below = [gray.getpixel((round(cx), y)) for y in range(box[3] + 2, min(CANVAS, box[3] + 60))]
    above = [gray.getpixel((x, box[1] - 6)) for x in range(box[0], box[2], 8)]
    # a visible shadow is darker than 245: one below the bottle, none above it (a blur's last 1-2 levels
    # are invisible; the margins above are checked exactly white just before)
    ok = min(below) < 245 and min(above) >= 245  # type: ignore[type-var,operator]
    checks.append(Check("a soft shadow lies below the product, none visible above it", ok,
                        f"darkest below {min(below)}, above {min(above)}"))  # type: ignore[type-var]  # fmt: skip
    return checks


def non_white(img: Image.Image) -> int:
    """How many pixels of ``img`` are not exactly (255, 255, 255)."""
    marks = [band.point([0] * 255 + [255]) for band in img.convert("RGB").split()]  # 255 where the band is 255
    every = ImageChops.multiply(ImageChops.multiply(marks[0], marks[1]), marks[2])
    return img.width * img.height - every.histogram()[255]


def profile_name(icc: bytes) -> str:
    """The description of an embedded ICC profile ("GIMP built-in sRGB"), or "" without one."""
    if not icc:
        return ""
    from PIL import ImageCms

    return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()


def agent_check(out: Path, answer: str) -> list[Check]:
    return verify(out)


def agent_reference(inputs: Path, out: Path) -> None:
    """A correct result made with Pillow: the bottle's pixels on white, scaled, centered, shadowed."""
    shot = Image.open(inputs / "shot.png").convert("RGB")
    scale, ox, oy = layout()
    scaled = shot.resize((round(SHOT[0] * scale), round(SHOT[1] * scale)), Image.Resampling.LANCZOS)
    mask = (
        scaled.convert("HSV")
        .split()[1]
        .point([255 if v > 60 else 0 for v in range(256)])
        .filter(ImageFilter.MaxFilter(3))
    )
    canvas = Image.new("RGB", (CANVAS, CANVAS), (255, 255, 255))
    shadow = Image.new("L", (CANVAS, CANVAS), 0)
    left, right, bottom = BOX[0] * scale + ox, BOX[2] * scale + ox, BOX[3] * scale + oy
    ImageDraw.Draw(shadow).ellipse((left + 40, bottom - 30, right - 40, bottom + 40), fill=255)
    shadow = shadow.filter(ImageFilter.GaussianBlur(20)).point([v * 45 // 100 for v in range(256)])
    canvas = Image.composite(Image.new("RGB", canvas.size, (0, 0, 0)), canvas, shadow)
    canvas.paste(scaled, (ox, oy), mask)
    srgb = srgb_profile()
    for size in SIZES:
        img = canvas.resize((size, size), Image.Resampling.LANCZOS)
        img.save(out / f"product-{size}.jpg", quality=90, icc_profile=srgb)
        img.save(out / f"product-{size}.webp", lossless=True, icc_profile=srgb)


def srgb_profile() -> bytes:
    from PIL import ImageCms

    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profile.tobytes()


def shot_for_the_agent(directory: Path) -> None:
    make_shot(directory / "shot.png")


SCENARIO = Scenario(
    name="product-cutout",
    title="product photo cut-out for an online store",
    toolsets=(
        "files",
        "layers",
        "transform",
        "selection",
        "paint",
        "filters",
        "channels",
        "formats",
        "modes",
        "analysis",
    ),
    assets=(),
    outputs=("shot.png", "product.xcf", *(f"product-{s}.{e}" for s in SIZES for e in ("jpg", "webp"))),
    steps=steps,
    prompt=(
        "~/inputs/shot.png is a studio photo of a bottle on a light-gray backdrop. Prepare it for an online "
        "store: cut the bottle out without destroying the original pixels, put it on pure white with a soft "
        "drop shadow below it, centered on a 2000x2000 square with a 5% margin around the bottle, and export it "
        "as JPEG and WebP with an sRGB color profile at 2000, 800 and 400 pixels: "
        "~/out/product-2000.jpg, ~/out/product-2000.webp, ~/out/product-800.jpg, ~/out/product-800.webp, "
        "~/out/product-400.jpg and ~/out/product-400.webp. Everything outside the bottle and its shadow must "
        "be pure white."
    ),
    agent_output="product-400.webp",
    make_agent_inputs=shot_for_the_agent,
    agent_check=agent_check,
    agent_reference=agent_reference,
)

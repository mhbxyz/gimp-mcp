"""Turn an application screenshot into a tutorial image: a highlight box, an arrow, numbered callouts and
a label; the e-mail address and the avatar pixelated beyond recovery; metadata removed; a lossless PNG.

The screenshot is drawn by code (CC0), with a planted text chunk (author, software): every position,
color and pixel of the input is known, so the checks compare with it exactly.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat
from PIL.PngImagePlugin import PngInfo

from demo.harness import Check, Report, Scenario, Session

SIZE = (1280, 800)
EMAIL_TEXT = "jane.doe@example.com"
EMAIL = (420, 300, 760, 340)  # the e-mail field's text area (x0, y0, x1, y1)
AVATAR = (1120, 20, 1220, 120)  # the avatar, top-right
SAVE = (980, 700, 1100, 744)  # the Save button
RED, WHITE = "#e63946", "#ffffff"
BLOCK = 40  # pixel blocks: larger than the text height, so no glyph survives
# annotations: a box around Save, an arrow to the e-mail field, callouts 1-3, a label
BOX = (SAVE[0] - 10, SAVE[1] - 10, SAVE[2] + 10, SAVE[3] + 10)
ARROW = ((300, 420), (405, 335))  # tail, head (pointing at the field)
CALLOUTS = {"1": (380, 255), "2": (380, 415), "3": (950, 680)}  # centers, radius 18
LABEL = ("Click Save when done", (720, 760))


def make_screenshot(path: Path) -> None:
    img = Image.new("RGB", SIZE, (246, 247, 249))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, SIZE[0], 140), fill=(36, 41, 56))  # header
    draw.text((40, 55), "Account settings", fill=(255, 255, 255))
    draw.rectangle((0, 140, 260, SIZE[1]), fill=(229, 232, 238))  # sidebar
    for i, item in enumerate(("Profile", "Security", "Billing", "Notifications")):
        draw.text((40, 190 + 50 * i), item, fill=(60, 64, 76))
    for label, y, value in (("Name", 200, "Jane Doe"), ("E-mail", 300, EMAIL_TEXT), ("Phone", 400, "hidden")):
        draw.text((420, y - 30), label, fill=(90, 94, 106))
        draw.rectangle((410, y - 6, 900, y + 46), outline=(190, 194, 204), fill=(255, 255, 255))
        draw.text((424, y + 12), value, fill=(20, 22, 30))
    # the avatar: a face-like pattern (a recognizable detail to remove)
    draw.ellipse(AVATAR, fill=(240, 196, 160))
    draw.ellipse((1145, 50, 1160, 65), fill=(40, 40, 40))
    draw.ellipse((1180, 50, 1195, 65), fill=(40, 40, 40))
    draw.arc((1140, 60, 1200, 100), 20, 160, fill=(150, 40, 40), width=4)
    draw.rectangle(SAVE, fill=(37, 99, 235))
    draw.text((SAVE[0] + 42, SAVE[1] + 16), "Save", fill=(255, 255, 255))
    info = PngInfo()
    info.add_text("Author", "Jane Doe <jane.doe@example.com>")
    info.add_text("Software", "ScreenGrab 2.1")
    img.save(path, pnginfo=info)


def png_chunks(path: Path) -> list[bytes]:
    """The chunk types of a PNG file, in order (standard library only)."""
    data, types, pos = path.read_bytes(), [], 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        types.append(kind)
        pos += 12 + length
    return types


async def steps(gimp: Session, report: Report) -> None:
    out = gimp.out
    source = out / "screenshot.png"
    make_screenshot(source)
    image = (await gimp.call("gimp_open_image", path=str(source)))["id"]
    layer = (await gimp.call("gimp_inspect_image", image=image))["layers"][0]["id"]
    await gimp.call("gimp_enable_toolsets", toolsets=["effects"])
    await gimp.preview(image, "01-screenshot", "1. The screenshot", max_size=800)

    # Redaction: big pixel blocks over the e-mail and the avatar, the selection limiting them.
    for x0, y0, x1, y1 in (EMAIL, AVATAR):
        await gimp.call("gimp_select_rectangle", image=image, x=x0, y=y0, width=x1 - x0, height=y1 - y0)
        await gimp.call("gimp_apply_filter", item=layer, operation="gegl:pixelize", destructive=True,
                        parameters={"size-x": BLOCK, "size-y": BLOCK})  # fmt: skip
    await gimp.call("gimp_modify_selection", image=image, action="none")

    # Annotations on their own layer.
    notes = (await gimp.call("gimp_create_layer", image=image, name="Annotations"))["id"]
    await gimp.call("gimp_draw_shape", item=notes, shape="rectangle", x=BOX[0], y=BOX[1], width=BOX[2] - BOX[0],
                    height=BOX[3] - BOX[1], stroke_color=RED, stroke_width=4)  # fmt: skip
    (tx, ty), (hx, hy) = ARROW
    await gimp.call("gimp_draw_path", item=notes, points=[[tx, ty], [hx, hy]], color=RED, width=5)
    await gimp.call("gimp_draw_path", item=notes, points=[[hx - 20, hy + 4], [hx, hy], [hx - 4, hy + 20]],
                    color=RED, width=5)  # fmt: skip
    for number, (cx, cy) in CALLOUTS.items():
        await gimp.call("gimp_draw_shape", item=notes, shape="ellipse", x=cx - 18, y=cy - 18, width=36, height=36,
                        fill_color=RED)  # fmt: skip
        await gimp.call("gimp_create_text_layer", image=image, text=number, font="Sans-serif Bold", size=22,
                        color=WHITE, x=cx - 18, y=cy - 15, justify="center", box_width=36, box_height=30)  # fmt: skip
    text, (lx, ly) = LABEL
    await gimp.call("gimp_create_text_layer", image=image, text=text, font="Sans-serif Bold", size=20, color=RED,
                    x=lx, y=ly, box_width=250, box_height=30)  # fmt: skip
    await gimp.preview(image, "02-annotated", "2. Annotated, e-mail and avatar pixelated", max_size=800)

    target = out / "tutorial.png"
    # gimp_export_image writes the export time (tIME) in a PNG (#160): export_as turns it off
    await gimp.call("gimp_enable_toolsets", toolsets=["formats"])
    await gimp.call("gimp_export_as", image=image, path=str(target), overwrite=True, options={"time": False})
    await gimp.call("gimp_close_image", image=image, discard_changes=True)
    for check in verify(source, target, exact_zones=True):
        report.check(check.description, check.passed, check.detail)


def px(img: Image.Image, xy: tuple[int, int]) -> tuple[int, ...]:
    value = img.getpixel(xy)
    assert isinstance(value, tuple), value
    return value


def rgb_of(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def near(pixel: tuple[int, ...], color: str, tolerance: int = 24) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(pixel, rgb_of(color), strict=False))


def verify(source: Path, target: Path, exact_zones: bool) -> list[Check]:
    """Facts on the tutorial PNG against the screenshot (shared by the scripted and agent versions)."""
    try:
        out = Image.open(target)
        out.load()
    except OSError as error:
        return [Check("tutorial.png is an image", False, str(error))]
    original = Image.open(source).convert("RGB")
    checks = [Check("tutorial.png is a lossless PNG of the same size", out.format == "PNG" and out.size == SIZE,
                    f"{out.format} {out.size}")]  # fmt: skip
    out = out.convert("RGB")
    # the e-mail: no dark glyph pixel left in its text area (the field is white around it)
    x0, y0, x1, y1 = EMAIL
    region_before, region_after = original.crop(EMAIL).convert("L"), out.crop(EMAIL).convert("L")
    dark_before, dark_after = sum(region_before.histogram()[:100]), sum(region_after.histogram()[:100])
    checks.append(Check("the e-mail keeps no detail (no glyph pixel left)", dark_before > 50 and dark_after == 0,
                        f"dark pixels {dark_after} (were {dark_before})"))  # fmt: skip
    # the avatar: flat blocks, and its features (eyes, mouth) are not there any more
    before = ImageStat.Stat(original.crop(AVATAR).convert("L")).stddev[0]
    after = ImageStat.Stat(out.crop(AVATAR).convert("L")).stddev[0]
    features = [(1152, 57), (1187, 57), (1170, 99)]  # eye centers and the mouth's lowest point
    kept = [xy for xy in features if near(px(out, xy), "#282828", 40) or near(px(out, xy), "#962828", 40)]
    # (the box's corners show the dark header next to the skin: blocks keep that edge, hence 0.75)
    flat = after < before * 0.75 and not kept
    detail = f"std dev {after:.1f} (was {before:.1f}), features still visible at {kept}"
    checks.append(Check("the avatar keeps no detail (flatter, eyes and mouth gone)", flat, detail))
    if exact_zones:  # the scripted version knows where it drew
        top = (BOX[0] + 60, BOX[1] + 1)
        checks.append(Check("a red box around the Save button", near(out.getpixel(top), RED), str(out.getpixel(top))))  # type: ignore[arg-type]
        mid = ((ARROW[0][0] + ARROW[1][0]) // 2, (ARROW[0][1] + ARROW[1][1]) // 2)
        checks.append(Check("a red arrow to the e-mail field", near(out.getpixel(mid), RED), str(out.getpixel(mid))))  # type: ignore[arg-type]
        callouts = []
        for cx, cy in CALLOUTS.values():
            ring = out.getpixel((cx - 14, cy))
            digit = [out.getpixel((x, y)) for x in range(cx - 6, cx + 7) for y in range(cy - 9, cy + 10)]
            callouts.append(near(ring, RED) and any(min(p) > 200 for p in digit))  # type: ignore[arg-type]
        checks.append(Check("three red callouts with a white number", all(callouts), str(callouts)))
    # everything else is the screenshot, pixel for pixel: a changed pixel is in a redaction or within 12 px
    # of the red annotations (their white numbers and antialiased edges included)
    r, g, b = out.split()
    reddish = ImageChops.multiply(ImageChops.multiply(r.point([255 if v > 170 else 0 for v in range(256)]),
                                                      g.point([255 if v < 110 else 0 for v in range(256)])),
                                  b.point([255 if v < 120 else 0 for v in range(256)]))  # fmt: skip
    allowed = reddish.filter(ImageFilter.MaxFilter(25))
    draw = ImageDraw.Draw(allowed)
    room = 8 if exact_zones else 20  # an agent chooses its own rectangle around the e-mail and the avatar
    for x0, y0, x1, y1 in (EMAIL, AVATAR):
        draw.rectangle((x0 - room, y0 - room, x1 + room, y1 + room), fill=255)
    changed = ImageChops.difference(out, original).convert("L").point([0] + [255] * 255)
    stray = ImageChops.subtract(changed, allowed).histogram()[255]
    checks.append(Check("outside the annotations and redactions, pixels are identical to the screenshot",
                        stray == 0, f"{stray} other changed pixels"))  # fmt: skip

    # the annotations are where they were asked for
    def red_near(box: tuple[int, int, int, int]) -> int:
        return reddish.crop(box).histogram()[255]

    near_save = red_near((SAVE[0] - 40, SAVE[1] - 40, SAVE[2] + 40, SAVE[3] + 40))
    near_field = red_near((260, 260, 420, 440))  # left of the E-mail field: the arrow comes from there
    near_name, near_phone = red_near((280, 170, 960, 280)), red_near((280, 370, 960, 480))
    detail = f"red pixels: save {near_save}, e-mail {near_field}, name {near_name}, phone {near_phone}"
    checks.append(Check("red annotations at the Save button, the E-mail field, the Name and Phone fields",
                        min(near_save, near_field, near_name, near_phone) > 40, detail))  # fmt: skip
    chunks = png_chunks(target)
    leaks = [c.decode() for c in chunks if c in (b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"iCCP", b"tIME")]
    checks.append(Check("the PNG carries no metadata (no text, Exif, time or profile chunk)", not leaks,
                        f"chunks {[c.decode() for c in chunks]}"))  # fmt: skip
    return checks


def agent_check(out: Path, answer: str) -> list[Check]:
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / "screenshot.png"
        make_screenshot(source)
        return verify(source, out / "tutorial.png", exact_zones=False)


def agent_reference(inputs: Path, out: Path) -> None:
    img = Image.open(inputs / "screenshot.png").convert("RGB")
    for x0, y0, x1, y1 in (EMAIL, AVATAR):
        region = img.crop((x0, y0, x1, y1))
        small = region.resize((max(1, (x1 - x0) // BLOCK), max(1, (y1 - y0) // BLOCK)), Image.Resampling.BOX)
        img.paste(small.resize(region.size, Image.Resampling.NEAREST), (x0, y0))
    draw = ImageDraw.Draw(img)
    draw.rectangle(BOX, outline=rgb_of(RED), width=4)
    draw.line(ARROW, fill=rgb_of(RED), width=5)
    for cx, cy in CALLOUTS.values():
        draw.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), fill=rgb_of(RED))
    img.save(out / "tutorial.png")


def screenshot_for_the_agent(directory: Path) -> None:
    make_screenshot(directory / "screenshot.png")


SCENARIO = Scenario(
    name="screenshot-annotation",
    title="annotate a screenshot and redact private data",
    toolsets=("files", "layers", "selection", "paint", "text", "effects", "formats"),
    assets=(),
    outputs=("screenshot.png", "tutorial.png"),
    steps=steps,
    prompt=(
        "Turn ~/inputs/screenshot.png into a tutorial image. Pixelate the e-mail address in the E-mail field and the "
        "avatar in the top-right corner so they cannot be read or recognized. Add, in red #e63946: a rectangle "
        "outline around the Save button, an arrow pointing at the E-mail field, numbered round callouts 1, 2 and 3 "
        "next to the Name field, the Phone field and the Save button, and a short label near the Save button. "
        "Change nothing else. Export a lossless PNG without any metadata to ~/out/tutorial.png."
    ),
    agent_output="tutorial.png",
    make_agent_inputs=screenshot_for_the_agent,
    agent_check=agent_check,
    agent_reference=agent_reference,
)

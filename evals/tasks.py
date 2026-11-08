"""The evaluation tasks: typical GIMP requests, on generated inputs, with factual checks.

Inputs are drawn with Pillow so every expected value is known in advance. Each task also has a
``reference``: a correct result made with Pillow, which `tests/unit/test_evals.py` uses to prove the
checks accept a right answer (and reject a missing one). Checks never judge aesthetics.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from demo.harness import agent_inputs, load, scenario_names
from evals.harness import Check, Task

Rgb = tuple[int, int, int]
RED: Rgb = (220, 30, 30)
GREEN: Rgb = (30, 180, 60)
BLUE: Rgb = (40, 80, 200)
YELLOW: Rgb = (240, 210, 40)
WHITE: Rgb = (255, 255, 255)
BLACK: Rgb = (0, 0, 0)
PHOTO: Rgb = (40, 80, 200)


# Helpers.


def opened(path: Path) -> Image.Image | None:
    try:
        img = Image.open(path)
        img.load()
        return img
    except (OSError, ValueError):
        return None


def close(a: tuple[int, ...], b: tuple[int, ...], tolerance: int) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=False))


def rgb(img: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    r, g, b = img.convert("RGB").getpixel((x, y))  # type: ignore[misc]
    return (r, g, b)


def image_checks(path: Path, size: tuple[int, int], fmt: str | None = None) -> tuple[list[Check], Image.Image | None]:
    img = opened(path)
    checks = [Check(f"{path.name} exists and is an image", img is not None)]
    if img is None:
        return checks, None
    if fmt:
        checks.append(Check(f"{path.name} is {fmt}", img.format == fmt, str(img.format)))
    checks.append(Check(f"{path.name} is {size[0]}x{size[1]}", img.size == size, f"{img.size[0]}x{img.size[1]}"))
    return checks, img if img.size == size else None


def pixels(img: Image.Image | None, expected: dict[tuple[int, int], tuple[int, int, int]], tolerance: int,
           what: str) -> list[Check]:  # fmt: skip
    if img is None:
        return [Check(what, False, "no image of the right size")]
    found = {xy: rgb(img, *xy) for xy in expected}
    wrong = {xy: found[xy] for xy, color in expected.items() if not close(found[xy], color, tolerance)}
    return [Check(what, not wrong, f"wrong at {wrong}" if wrong else "")]


def solid(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def quadrants(path: Path) -> None:
    img = Image.new("RGB", (400, 400))
    for (x, y), color in {(0, 0): RED, (200, 0): GREEN, (0, 200): BLUE, (200, 200): YELLOW}.items():
        img.paste(color, (x, y, x + 200, y + 200))
    img.save(path)


def bars(path: Path) -> None:
    img = Image.new("RGB", (400, 100))
    for index, color in enumerate((RED, GREEN, BLUE, YELLOW)):
        img.paste(color, (index * 100, 0, index * 100 + 100, 100))
    img.save(path)


def gradient(path: Path) -> None:
    img = Image.new("RGB", (1200, 800))
    draw = ImageDraw.Draw(img)
    for x in range(1200):
        draw.line([(x, 0), (x, 799)], fill=(x * 255 // 1199, 120, 255 - x * 255 // 1199))
    img.save(path)


def to_linear(v: int) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def to_srgb(c: float) -> int:
    return round(255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055))


def blends(a: Rgb, b: Rgb) -> tuple[Rgb, Rgb]:
    """50% of ``a`` over ``b``: averaged in sRGB, and averaged in linear light (GIMP 3's default for
    layer modes and filters, docs/gimp-notes.md). Either is a correct 50% opacity."""
    perceptual = tuple((x + y) // 2 for x, y in zip(a, b, strict=True))
    linear = tuple(to_srgb((to_linear(x) + to_linear(y)) / 2) for x, y in zip(a, b, strict=True))
    return perceptual, linear  # type: ignore[return-value]


def luminance_stats(img: Image.Image) -> tuple[float, float]:
    from PIL import ImageStat

    stat = ImageStat.Stat(img.convert("L"))
    return stat.mean[0], stat.stddev[0]


# Tasks (default toolsets first, then those needing an optional toolset the agent must enable).


def _resize_inputs(d: Path) -> None:
    gradient(d / "photo.png")


def _resize_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "photo-600.jpg", (600, 400), "JPEG")
    return checks + pixels(
        img, {(5, 200): (2, 120, 253), (595, 200): (253, 120, 2)}, 25, "the gradient is kept, not cropped"
    )


def _resize_reference(i: Path, o: Path) -> None:
    Image.open(i / "photo.png").resize((600, 400)).save(o / "photo-600.jpg", quality=92)


def _crop_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "green.png", (200, 200), "PNG")
    return checks + pixels(
        img, {(0, 0): GREEN, (199, 0): GREEN, (0, 199): GREEN, (199, 199): GREEN}, 6, "only the green quadrant"
    )


def _text_check(out: Path, answer: str) -> list[Check]:
    checks = [Check("hello.xcf is a GIMP project", (out / "hello.xcf").is_file()
                    and (out / "hello.xcf").read_bytes()[:8] == b"gimp xcf")]  # fmt: skip
    found, img = image_checks(out / "hello.png", (800, 200), "PNG")
    checks += found
    if img is None:
        return [*checks, Check("dark text in the middle, white corners", False)]
    gray = img.convert("L")
    middle = gray.crop((150, 50, 650, 150))
    dark = sum(middle.histogram()[:100])
    corners = [gray.getpixel(xy) for xy in ((2, 2), (797, 2), (2, 197), (797, 197))]
    return [*checks, Check("dark text in the middle, white corners", dark > 500 and min(corners) > 240,  # type: ignore[operator]
                           f"{dark} dark pixels, corners {corners}")]  # fmt: skip


def _text_reference(i: Path, o: Path) -> None:
    (o / "hello.xcf").write_bytes(b"gimp xcf v020\x00")
    img = Image.new("RGB", (800, 200), WHITE)
    ImageDraw.Draw(img).rectangle((250, 70, 550, 130), fill=BLACK)
    img.save(o / "hello.png")


def _overlay_inputs(d: Path) -> None:
    solid(d / "photo.png", (1200, 800), PHOTO)
    solid(d / "logo.png", (200, 100), RED)


def _overlay_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "branded.png", (1200, 800), "PNG")
    perceptual, linear = blends(RED, PHOTO)
    blend = linear if img is not None and close(rgb(img, 1100, 750), linear, 14) else perceptual
    return checks + pixels(img, {(1100, 750): blend, (1001, 701): blend, (1198, 798): blend, (100, 100): PHOTO,  # type: ignore[dict-item]
                                 (990, 750): PHOTO, (1100, 690): PHOTO}, 14,
                           "logo at 50% in the bottom-right corner only")  # fmt: skip


def _overlay_reference(i: Path, o: Path) -> None:
    photo = Image.open(i / "photo.png").convert("RGB")
    logo = Image.open(i / "logo.png").convert("RGB")
    region = photo.crop((1000, 700, 1200, 800))
    photo.paste(Image.blend(region, logo, 0.5), (1000, 700))
    photo.save(o / "branded.png")


def _rotate_inputs(d: Path) -> None:
    img = Image.new("RGB", (300, 200), WHITE)
    img.paste(BLACK, (0, 0, 150, 200))
    img.save(d / "halves.png")


def _rotate_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "rotated.png", (200, 300), "PNG")
    # clockwise: the left (black) half goes to the top
    return checks + pixels(img, {(100, 40): BLACK, (100, 260): WHITE}, 10, "rotated clockwise (black half on top)")


def _rotate_reference(i: Path, o: Path) -> None:
    Image.open(i / "halves.png").rotate(-90, expand=True).save(o / "rotated.png")


def _rect_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "rect.png", (400, 300), "PNG")
    return checks + pixels(img, {(200, 100): (255, 0, 0), (102, 52): (255, 0, 0), (297, 147): (255, 0, 0),
                                 (50, 50): WHITE, (200, 40): WHITE, (310, 100): WHITE, (200, 160): WHITE}, 8,
                           "red rectangle at x 100-300, y 50-150 on white")  # fmt: skip


def _rect_reference(i: Path, o: Path) -> None:
    img = Image.new("RGB", (400, 300), WHITE)
    img.paste((255, 0, 0), (100, 50, 300, 150))
    img.save(o / "rect.png")


def _blur_inputs(d: Path) -> None:
    img = Image.new("L", (256, 256))
    for y in range(0, 256, 8):
        for x in range(0, 256, 8):
            if (x // 8 + y // 8) % 2:
                img.paste(255, (x, y, x + 8, y + 8))
    img.convert("RGB").save(d / "checker.png")


def _blur_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "blurred.png", (256, 256), "PNG")
    if img is None:
        return [*checks, Check("the checkerboard is blurred", False)]
    mean, spread = luminance_stats(img)
    # black and white average to 128 in sRGB, or to 188 when blurred in linear light (GIMP 3)
    blurred = spread < 0.4 * 127.5 and 108 <= mean <= 208
    detail = f"mean {mean:.0f}, std dev {spread:.0f} (input 128, 128; 188 is the linear-light average)"
    return [*checks, Check("the checkerboard is blurred (contrast down, average kept)", blurred, detail)]


def _blur_reference(i: Path, o: Path) -> None:
    Image.open(i / "checker.png").filter(ImageFilter.GaussianBlur(6)).save(o / "blurred.png")


def _darker_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "darker.png", (300, 200), "PNG")
    if img is None:
        return [*checks, Check("about 30% darker", False)]
    mean, _ = luminance_stats(img)
    return [
        *checks,
        Check("about 30% darker (mean between 60 and 110, input 128)", 60 <= mean <= 110, f"mean {mean:.0f}"),
    ]


def _darker_reference(i: Path, o: Path) -> None:
    Image.open(i / "gray.png").point(lambda v: int(v * 0.7)).save(o / "darker.png")


def _border_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "framed.png", (240, 140), "PNG")
    return checks + pixels(img, {(3, 3): WHITE, (236, 136): WHITE, (120, 10): WHITE, (25, 25): PHOTO, (120, 70): PHOTO,
                                 (214, 114): PHOTO}, 6, "a 20 px white border around the unchanged image")  # fmt: skip


def _border_reference(i: Path, o: Path) -> None:
    ImageOps.expand(Image.open(i / "small.png"), 20, WHITE).save(o / "framed.png")


def _undo_inputs(d: Path) -> None:
    _blur_inputs(d)


def _undo_check(out: Path, answer: str) -> list[Check]:
    checks, blurred = image_checks(out / "step1-blurred.png", (256, 256), "PNG")
    found, restored = image_checks(out / "step2-restored.png", (256, 256), "PNG")
    checks += found
    if blurred is None or restored is None:
        return [*checks, Check("blurred, then exactly restored", False)]
    _, blurred_spread = luminance_stats(blurred)
    restored_ok = rgb(restored, 3, 3) == BLACK and rgb(restored, 11, 3) == WHITE and luminance_stats(restored)[1] > 120
    detail = f"blurred std dev {blurred_spread:.0f}; restored {rgb(restored, 3, 3)}, {rgb(restored, 11, 3)}"
    return [*checks, Check("blurred, then exactly restored", blurred_spread < 100 and restored_ok, detail)]


def _undo_reference(i: Path, o: Path) -> None:
    source = Image.open(i / "checker.png")
    source.filter(ImageFilter.GaussianBlur(6)).save(o / "step1-blurred.png")
    source.save(o / "step2-restored.png")


def _grayscale_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "gray.png", (400, 100), "PNG")
    if img is None:
        return [*checks, Check("gray tones only, bars still distinct", False)]
    colors = [rgb(img, x, 50) for x in (50, 150, 250, 350)]
    neutral = all(max(c) - min(c) <= 3 for c in colors)
    return [
        *checks,
        Check("gray tones only, bars still distinct", neutral and len({c[0] // 8 for c in colors}) >= 3, str(colors)),
    ]


def _grayscale_reference(i: Path, o: Path) -> None:
    ImageOps.grayscale(Image.open(i / "bars.png")).save(o / "gray.png")


def _invert_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "inverted.png", (400, 400), "PNG")
    inverse = {xy: tuple(255 - v for v in color) for xy, color in
               {(100, 100): RED, (300, 100): GREEN, (100, 300): BLUE, (300, 300): YELLOW}.items()}  # fmt: skip
    return checks + pixels(img, inverse, 4, "every color inverted")  # type: ignore[arg-type]


def _invert_reference(i: Path, o: Path) -> None:
    ImageOps.invert(Image.open(i / "quadrants.png").convert("RGB")).save(o / "inverted.png")


BATCH = {"a": RED, "b": GREEN, "c": BLUE}


def _batch_inputs(d: Path) -> None:
    for name, color in BATCH.items():
        solid(d / "batch" / f"{name}.png", (800, 600), color)


def _batch_check(out: Path, answer: str) -> list[Check]:
    checks = []
    for name, color in BATCH.items():
        found, img = image_checks(out / "batch" / f"{name}.jpg", (200, 150), "JPEG")
        checks += found + pixels(img, {(100, 75): color}, 20, f"{name}.jpg keeps its color")
    extra = sorted(p.name for p in (out / "batch").glob("*")) if (out / "batch").is_dir() else []
    return [*checks, Check("only the three JPEGs in ~/out/batch", extra == ["a.jpg", "b.jpg", "c.jpg"], str(extra))]


def _batch_reference(i: Path, o: Path) -> None:
    for name in BATCH:
        Image.open(i / "batch" / f"{name}.png").resize((200, 150)).save(o / "batch" / f"{name}.jpg")


def _gif_check(out: Path, answer: str) -> list[Check]:
    img = opened(out / "blink.gif")
    if img is None:
        return [Check("blink.gif exists and is an image", False)]
    checks = [Check("blink.gif is an animated GIF of 100x100", img.format == "GIF" and img.size == (100, 100),
                    f"{img.format} {img.size}")]  # fmt: skip
    frames, durations = [], []
    for index in range(getattr(img, "n_frames", 1)):
        img.seek(index)
        frames.append(rgb(img, 50, 50))
        durations.append(img.info.get("duration"))
    expected = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    in_order = len(frames) == 3 and all(close(f, e, 30) for f, e in zip(frames, expected, strict=False))
    checks.append(Check("3 frames: red, green, blue", in_order, str(frames)))
    checks.append(Check("500 ms per frame", durations == [500, 500, 500], str(durations)))
    img.seek(0)
    checks.append(Check("loops forever", img.info.get("loop") == 0, str(img.info.get("loop"))))
    return checks


def _gif_reference(i: Path, o: Path) -> None:
    frames = [Image.new("RGB", (100, 100), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    frames[0].save(o / "blink.gif", save_all=True, append_images=frames[1:], duration=500, loop=0)


def _webp_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "photo.webp", (1200, 800), "WEBP")
    gradient_pixels = {(x, 400): (x * 255 // 1199, 120, 255 - x * 255 // 1199) for x in (0, 300, 600, 1199)}
    return checks + pixels(img, gradient_pixels, 0, "lossless: pixels identical to the source")  # type: ignore[arg-type]


def _webp_reference(i: Path, o: Path) -> None:
    Image.open(i / "photo.png").save(o / "photo.webp", lossless=True)


def _indexed_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "indexed.png", (400, 100), "PNG")
    if img is None:
        return [*checks, Check("indexed, at most 4 colors", False)]
    colors = img.convert("RGB").getcolors(256) or []
    return [
        *checks,
        Check(
            "indexed, at most 4 colors", img.mode == "P" and len(colors) <= 4, f"mode {img.mode}, {len(colors)} colors"
        ),
    ]


def _indexed_reference(i: Path, o: Path) -> None:
    Image.open(i / "bars.png").convert("P", palette=Image.Palette.ADAPTIVE, colors=4).save(o / "indexed.png")


def _flag_inputs(d: Path) -> None:
    img = Image.new("RGB", (300, 200), (230, 57, 70))
    img.paste(WHITE, (0, 140, 300, 200))
    img.save(d / "flag.png")


def _dominant_check(out: Path, answer: str) -> list[Check]:
    codes = [tuple(int(h[k : k + 2], 16) for k in (0, 2, 4)) for h in re.findall(r"#([0-9a-fA-F]{6})\b", answer)]
    hit = any(close(code, (230, 57, 70), 12) for code in codes)
    return [
        Check(
            "the answer gives the dominant color's hex code (#e63946)",
            hit,
            ", ".join(f"#{''.join(f'{v:02x}' for v in c)}" for c in codes) or "no hex code",
        )
    ]


def _dpi_check(out: Path, answer: str) -> list[Check]:
    checks, img = image_checks(out / "print.png", (1200, 800), "PNG")
    dpi = img.info.get("dpi") if img is not None else None
    ok = dpi is not None and all(abs(float(v) - 300) < 1 for v in dpi)
    return [*checks, Check("the PNG says 300 dpi", ok, str(dpi))]


def _dpi_reference(i: Path, o: Path) -> None:
    Image.open(i / "photo.png").save(o / "print.png", dpi=(300, 300))


def _no_reference(i: Path, o: Path) -> None:
    """The answer is in the agent's message, not in a file."""


def _copy_inputs(make: Callable[[Path], None], name: str) -> Callable[[Path], None]:
    def inputs(d: Path) -> None:
        make(d / name)

    return inputs


BASIC_TASKS: tuple[Task, ...] = (
    Task("resize-export", ("files", "transform"),
         "Resize ~/inputs/photo.png to 600 pixels wide, keeping its proportions, and export it as a JPEG to "
         "~/out/photo-600.jpg.", _resize_inputs, _resize_check, _resize_reference),
    Task("crop-quadrant", ("files", "transform"),
         "~/inputs/quadrants.png has four colored quadrants. Crop it to the top-right quadrant (the green one) "
         "and export the result to ~/out/green.png.", _copy_inputs(quadrants, "quadrants.png"), _crop_check,
         lambda i, o: Image.open(i / "quadrants.png").crop((200, 0, 400, 200)).save(o / "green.png")),
    Task("text-title", ("files", "text"),
         'Create a new 800x200 image with a white background and write "Hello GIMP" in black, large, roughly '
         "centered, as an editable text layer. Save the project as ~/out/hello.xcf and export ~/out/hello.png.",
         lambda d: None, _text_check, _text_reference),
    Task("logo-overlay", ("files", "layers", "transform"),
         "Place ~/inputs/logo.png as a new layer in the bottom-right corner of ~/inputs/photo.png, touching both "
         "edges, at 50% opacity, and export the result to ~/out/branded.png.",
         _overlay_inputs, _overlay_check, _overlay_reference),
    Task("rotate", ("files", "transform"),
         "Rotate ~/inputs/halves.png 90 degrees clockwise and export it to ~/out/rotated.png.",
         _rotate_inputs, _rotate_check, _rotate_reference),
    Task("red-rectangle", ("files", "selection", "paint"),
         "Create a 400x300 white image, fill a pure red rectangle whose top-left corner is at x=100, y=50 and "
         "which is 200 pixels wide and 100 pixels high, then export ~/out/rect.png.",
         lambda d: None, _rect_check, _rect_reference),
    Task("blur", ("files", "filters"),
         "Apply a Gaussian blur of about 8 pixels to ~/inputs/checker.png and export it to ~/out/blurred.png.",
         _blur_inputs, _blur_check, _blur_reference),
    Task("darken", ("files", "filters"),
         "~/inputs/gray.png is too bright: make it about 30% darker and export it to ~/out/darker.png.",
         lambda d: solid(d / "gray.png", (300, 200), (128, 128, 128)), _darker_check, _darker_reference),
    Task("white-border", ("files", "transform", "layers"),
         "Add a 20-pixel white border around ~/inputs/small.png (the image becomes 240x140) and export it to "
         "~/out/framed.png.", lambda d: solid(d / "small.png", (200, 100), PHOTO), _border_check, _border_reference),
    Task("undo", ("files", "filters", "history"),
         "Open ~/inputs/checker.png, blur it strongly and export ~/out/step1-blurred.png. Then undo the blur in "
         "the same image and export the restored image to ~/out/step2-restored.png.",
         _undo_inputs, _undo_check, _undo_reference),
    Task("grayscale", ("files", "color"),
         "Turn ~/inputs/bars.png into a black-and-white (gray tones) image and export it to ~/out/gray.png.",
         _copy_inputs(bars, "bars.png"), _grayscale_check, _grayscale_reference),
    Task("invert", ("files", "color"),
         "Invert the colors of ~/inputs/quadrants.png and export the result to ~/out/inverted.png.",
         _copy_inputs(quadrants, "quadrants.png"), _invert_check, _invert_reference),
    Task("batch-thumbnails", ("batch", "files", "transform"),
         "Convert every PNG in ~/inputs/batch/ to a JPEG 200 pixels wide (keep the proportions), written to "
         "~/out/batch/ with the same base names.", _batch_inputs, _batch_check, _batch_reference, out_dirs=("batch",)),
    Task("animated-gif", ("animation", "files", "paint"),
         "Make an animated GIF ~/out/blink.gif, 100x100 pixels, with 3 frames: pure red, pure green, then pure "
         "blue, each shown for 500 ms, looping forever.", lambda d: None, _gif_check, _gif_reference),
    Task("lossless-webp", ("formats", "files"),
         "Export ~/inputs/photo.png as a lossless WebP file, ~/out/photo.webp.", _resize_inputs, _webp_check,
         _webp_reference),
    Task("indexed-4-colors", ("modes", "files"),
         "Convert ~/inputs/bars.png to an indexed-color image with at most 4 colors and export it to "
         "~/out/indexed.png.", _copy_inputs(bars, "bars.png"), _indexed_check, _indexed_reference),
    Task("dominant-color", ("analysis", "files"),
         "What is the dominant color of ~/inputs/flag.png? Measure it in GIMP and answer with its hex code. "
         "(Nothing to write in ~/out.)", _flag_inputs, _dominant_check, _no_reference),
    Task("print-resolution", ("document", "files"),
         "Set the print resolution of ~/inputs/photo.png to 300 dpi, without resampling it, and export it to "
         "~/out/print.png.", _resize_inputs, _dpi_check, _dpi_reference),
)  # fmt: skip


def scenario_task(name: str) -> Task:
    """The agent version of a demo scenario (demo/scenarios/), with the scenario's own agent checks."""
    scenario = load(name)
    assert scenario.agent_check is not None and scenario.agent_reference is not None, name
    agent_check = scenario.agent_check

    def make_inputs(directory: Path) -> None:
        agent_inputs(scenario, directory)

    def check(out: Path, answer: str) -> list[Check]:
        return [Check(c.description, c.passed, c.detail) for c in agent_check(out, answer)]

    toolsets = tuple(t for t in scenario.toolsets if t != "core")
    return Task(
        name, toolsets, scenario.prompt, make_inputs, check, scenario.agent_reference, out_dirs=scenario.agent_out_dirs
    )


SCENARIO_TASKS: tuple[Task, ...] = tuple(scenario_task(n) for n in scenario_names() if load(n).agent_check is not None)
TASKS: tuple[Task, ...] = BASIC_TASKS + SCENARIO_TASKS


def by_name(name: str) -> Task:
    for task in TASKS:
        if task.name == name:
            return task
    raise KeyError(f"unknown task {name!r} (known: {', '.join(t.name for t in TASKS)})")

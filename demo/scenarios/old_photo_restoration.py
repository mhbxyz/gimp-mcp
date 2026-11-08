"""Restore an old scanned photo: straighten the tilted scan, crop the scanner bed, heal dust and a
scratch, restore the faded contrast, reduce the noise, then export a 16-bit TIFF at 300 dpi for
printing and a JPEG for the web.

The scan is generated from `lake-sunset.png` with known defects (a 3° tilt, a white scanner bed, dust
spots and a scratch at known places, levels squeezed into 60-187, seeded noise), so every check has
ground truth: the sky's color bands are horizontal in the source, the dust positions are known, and
the original tonal range is known.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat

from demo.harness import Report, Scenario, Session, asset

PHOTO = (1200, 750)  # the print, before scanning
BED = (1400, 950)  # the scanner bed (white), the print laid at (100, 100)
ORIGIN = (100, 100)
TILT = 3.0  # degrees, counter-clockwise on the scan
CROP = (112, 112, 1176, 726)  # x, y, width, height on the straightened scan: inside the print
LOW, HIGH = 60, 187  # the faded print's tonal range
SKY = (20, 20, 480, 220)  # a region of the output where the source's color bands are horizontal
FLAT = (100, 30, 400, 46)  # sky rows of the output far from the sun: each row is one color in the source


@dataclass(frozen=True)
class Defects:
    dust: tuple[tuple[int, int], ...]  # print coordinates
    scratch: tuple[tuple[int, int], tuple[int, int]]  # print coordinates
    grain: float  # noise of the flat sky patch on the scan


def print_to_output(x: float, y: float) -> tuple[int, int]:
    return round(x + ORIGIN[0] - CROP[0]), round(y + ORIGIN[1] - CROP[1])


def make_scan(path: Path) -> Defects:
    rng = random.Random(1908)
    photo = Image.open(asset("lake-sunset.png")).convert("RGB").resize(PHOTO, Image.Resampling.LANCZOS)
    photo = photo.point([LOW + v * (HIGH - LOW) // 255 for v in range(256)] * 3)  # faded
    bands = []
    for band in photo.split():  # seeded film grain, sigma 6
        grain = Image.new("L", PHOTO)
        grain.putdata([max(0, min(255, v + round(rng.gauss(0, 6)))) for v in band.tobytes()])
        bands.append(grain)
    photo = Image.merge("RGB", bands)
    draw = ImageDraw.Draw(photo)
    dust = tuple((rng.randrange(80, 1120), rng.randrange(80, 680)) for _ in range(14))
    for index, (x, y) in enumerate(dust):
        color = dust_color(index)
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)
    scratch = ((300, 120), (360, 560))
    draw.line(scratch, fill=(245, 245, 245), width=2)
    x0, y0 = FLAT[0] + CROP[0] - ORIGIN[0], FLAT[1] + CROP[1] - ORIGIN[1]
    grain = row_noise(photo, (x0, y0, x0 + FLAT[2] - FLAT[0], y0 + FLAT[3] - FLAT[1]))
    bed = Image.new("RGB", BED, (255, 255, 255))
    bed.paste(photo, ORIGIN)
    bed.rotate(TILT, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255)).save(path)
    return Defects(dust, scratch, grain)


def dust_color(index: int) -> tuple[int, int, int]:
    return (20, 20, 20) if index % 3 else (250, 250, 250)


def tilt(img: Image.Image, box: tuple[int, int, int, int], strip: int = 12) -> float:
    """Angle (degrees) of the color bands in ``box`` from the horizontal, from the mean gradient."""
    gray = img.convert("L").crop(box)
    w, h = gray.size

    def mean(b: tuple[int, int, int, int]) -> float:
        return ImageStat.Stat(gray.crop(b)).mean[0]

    gx = (mean((w - strip, 0, w, h)) - mean((0, 0, strip, h))) / (w - strip)
    gy = (mean((0, h - strip, w, h)) - mean((0, 0, w, strip))) / (h - strip)
    return math.degrees(math.atan2(gx, gy))


def row_noise(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Mean standard deviation of the rows of ``box`` (luminance): the source's sky rows are uniform."""
    gray = img.convert("L").crop(box)
    rows = [ImageStat.Stat(gray.crop((0, y, gray.width, y + 1))).stddev[0] for y in range(gray.height)]
    return sum(rows) / len(rows)


def clean_print() -> Image.Image:
    """The print before any defect: the ground truth of every repaired pixel."""
    return Image.open(asset("lake-sunset.png")).convert("RGB").resize(PHOTO, Image.Resampling.LANCZOS)


def px(img: Image.Image, xy: tuple[int, int]) -> tuple[int, ...]:
    value = img.getpixel(xy)
    assert isinstance(value, tuple), value
    return value


def distance(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return max(abs(x - y) for x, y in zip(a, b, strict=False))


def percentiles(img: Image.Image) -> tuple[int, int]:
    histogram = img.convert("L").histogram()
    total, seen, low, high = sum(histogram), 0, 0, 255
    for value, count in enumerate(histogram):
        seen += count
        if seen <= total * 0.01:
            low = value
        if seen >= total * 0.99:
            high = value
            break
    return low, high


async def steps(gimp: Session, report: Report) -> None:
    out = gimp.out
    scan_path = out / "scan.png"
    defects = make_scan(scan_path)
    scan = Image.open(scan_path)
    report.check("the scan is tilted (ground truth)", abs(tilt(scan, (160, 180, 560, 360)) - TILT) < 0.3,
                 f"{tilt(scan, (160, 180, 560, 360)):.2f}°")  # fmt: skip
    scan_low, scan_high = percentiles(scan.crop((150, 150, 1250, 800)))
    report.check("the scan is faded (ground truth)", scan_low >= 50 and scan_high <= 200, f"{scan_low}-{scan_high}")

    image = (await gimp.call("gimp_open_image", path=str(scan_path)))["id"]
    layer = (await gimp.call("gimp_inspect_image", image=image))["layers"][0]["id"]
    await gimp.preview(image, "01-scan", "1. The scan: tilted, white bed, dust, a scratch, faded")

    # GIMP rotates clockwise: undo the scan's counter-clockwise tilt, keeping the canvas.
    await gimp.call("gimp_rotate_layer", item=layer, angle=TILT, clip="clip")
    await gimp.call("gimp_crop_image", image=image, x=CROP[0], y=CROP[1], width=CROP[2], height=CROP[3])
    await gimp.preview(image, "02-straight", "2. Straightened and cropped")

    # Heal each dust spot and the scratch from a clean area 16 px to the right.
    await gimp.call("gimp_enable_toolsets", toolsets=["painting", "color", "effects", "modes", "formats", "document"])
    for x, y in defects.dust:
        ox, oy = print_to_output(x, y)
        await gimp.call("gimp_paint_stroke", item=layer, tool="heal", points=[[ox, oy]], size=15, hardness=1.0,
                        source=layer, source_x=ox + 16, source_y=oy)  # fmt: skip
    # A scratch crosses the edge of every heal dab, which brings it back: clone over it instead, from the
    # same rows 16 px to the right (the sky's color bands are horizontal).
    (ax, ay), (bx, by) = (print_to_output(*p) for p in defects.scratch)
    await gimp.call("gimp_paint_stroke", item=layer, tool="clone", points=[[ax, ay], [bx, by]], size=9,
                    hardness=1.0, spacing=5, source=layer, source_x=ax + 16, source_y=ay)  # fmt: skip
    await gimp.preview(image, "03-healed", "3. Dust healed, scratch cloned over")

    # Contrast back to the full range, then noise reduction.
    await gimp.call("gimp_levels", item=layer, input_low=LOW, input_high=HIGH)
    await gimp.call("gimp_apply_filter", item=layer, operation="gegl:noise-reduction", parameters={"iterations": 3},
                    destructive=True)  # fmt: skip
    await gimp.preview(image, "04-restored", "4. Contrast restored, noise reduced")

    # Print: 16-bit TIFF at 300 dpi. Web: JPEG.
    await gimp.call("gimp_convert_precision", image=image, precision="u16-non-linear")
    await gimp.call("gimp_set_print_size", image=image, x_resolution=300, y_resolution=300)
    tiff, jpeg = out / "restored-print.tif", out / "restored-web.jpg"
    await gimp.call("gimp_export_as", image=image, path=str(tiff), overwrite=True)
    await gimp.call("gimp_export_image", image=image, path=str(jpeg), overwrite=True, jpeg_options={"quality": 90})
    await gimp.call("gimp_close_image", image=image, discard_changes=True)  # the exports are the results

    # Checks on the exported files, read with Pillow.
    with Image.open(tiff) as img:
        bits = img.tag_v2.get(258)  # type: ignore[attr-defined]
        dpi = img.info.get("dpi")
        report.check(
            "the TIFF is 16 bits per channel", tuple(bits or ()) in ((16, 16, 16), (16, 16, 16, 16)), str(bits)
        )
        report.check(f"the TIFF is {CROP[2]}x{CROP[3]}", img.size == CROP[2:], str(img.size))
        report.check("the TIFF says 300 dpi", dpi is not None and all(abs(float(v) - 300) < 1 for v in dpi), str(dpi))
    web = Image.open(jpeg).convert("RGB")
    report.check(f"the JPEG is {CROP[2]}x{CROP[3]}", web.size == CROP[2:], str(web.size))
    angle = tilt(web, SKY)
    report.check("the sky's color bands are level (tilt under 0.4° measured)", abs(angle) < 0.4, f"{angle:.2f}°")
    edges = [px(web, (x, y)) for x in range(web.width) for y in (0, 1, web.height - 2, web.height - 1)]
    edges += [px(web, (x, y)) for y in range(web.height) for x in (0, 1, web.width - 2, web.width - 1)]
    white = sum(1 for p in edges if min(p) > 245)
    report.check("no scanner bed remains along the edges", white == 0, f"{white} near-white edge pixels")
    clean = clean_print()

    def repaired(x: float, y: float) -> int:
        return distance(px(web, print_to_output(x, y)), px(clean, (round(x), round(y))))

    dust = [repaired(x, y) for x, y in defects.dust]
    before = [distance(dust_color(i), px(clean, p)) for i, p in enumerate(defects.dust)]
    report.check("every dust spot has the clean print's color again (within 30)", max(dust) <= 30,
                 f"worst {max(dust)}/255; the spots were {min(before)}-{max(before)} away")  # fmt: skip
    (ax, ay), (bx, by) = defects.scratch
    line = [(ax + (bx - ax) * i / 20, ay + (by - ay) * i / 20) for i in range(1, 20)]
    # cloning copies the same row 16 px to the right: where the clean print itself changes there (the
    # mountain ridge), no horizontal clone can match, so those points are not judged
    judged = [
        p
        for p in line
        if distance(
            px(clean, (round(p[0]), round(p[1]))),
            px(clean, (round(p[0]) + 16, round(p[1]))),
        )
        <= 30
    ]
    scratch = [repaired(x, y) for x, y in judged]
    report.check("the scratch has the clean print's color again (within 30)", len(judged) >= 15 and max(scratch) <= 30,
                 f"worst {max(scratch)}/255 over {len(judged)} of {len(line)} points")  # fmt: skip
    low, high = percentiles(web)
    report.check("the histogram spans the full range again (1%-99%: <=25 and >=230)", low <= 25 and high >= 230,
                 f"{low}-{high}, scan {scan_low}-{scan_high}")  # fmt: skip
    grain = row_noise(web, FLAT)
    # without noise reduction the levels stretch (x2) would double the scan's grain
    report.check("noise is reduced in flat sky rows", grain < defects.grain,
                 f"row std dev {grain:.1f}, scan {defects.grain:.1f} (x2 after levels without reduction)")  # fmt: skip


def scan_for_the_agent(directory: Path) -> None:
    make_scan(directory / "scan.png")


SCENARIO = Scenario(
    name="old-photo-restoration",
    title="restore an old scanned photo",
    toolsets=("files", "layers", "transform", "painting", "color", "effects", "modes", "formats", "document"),
    assets=("lake-sunset.png",),
    outputs=("scan.png", "restored-print.tif", "restored-web.jpg"),
    steps=steps,
    prompt=(
        "~/inputs/scan.png is a scan of an old photo: it is tilted on the scanner, with the white scanner bed "
        "around it, dust spots, a scratch, faded contrast and noise. Restore it: straighten it, crop away the "
        "scanner bed, remove the dust and the scratch, bring back full contrast and reduce the noise. Export a "
        "16-bit TIFF at 300 dpi for printing to ~/out/restored-print.tif and a JPEG for the web to "
        "~/out/restored-web.jpg."
    ),
    agent_output="restored-web.jpg",
    make_agent_inputs=scan_for_the_agent,
)

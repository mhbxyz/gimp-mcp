"""Replace a dull sky with another photo's sky: select the old sky by color, refine the selection, mask
the new sky into place, warm the foreground to the new light with an editable color balance, and keep
every step as a layer, a mask or an editable filter in the XCF.

Both pictures are drawn by code (CC0): the dull sky's color, the new sky, the foreground and the exact
horizon line are known, so sky, foreground and horizon pixels are checked against them.
"""

from __future__ import annotations

import math
import random
import struct
from pathlib import Path

from PIL import Image, ImageDraw

from demo.harness import Check, Report, Scenario, Session, find

SIZE = (1200, 800)
DULL = (198, 203, 208)
GRADE = 40  # the largest change the color grade may make to a foreground channel


def horizon(x: int) -> int:
    """The horizon's y at column x: rolling hills between y=380 and y=470."""
    return round(425 + 30 * math.sin(x / 110) + 15 * math.sin(x / 37 + 1.3))


def make_landscape(path: Path) -> None:
    rng = random.Random(1915)
    img = Image.new("RGB", SIZE)
    draw = ImageDraw.Draw(img)
    for y in range(SIZE[1]):  # a flat gray sky, then the fields
        draw.line([(0, y), (SIZE[0], y)], fill=DULL)
    for x in range(SIZE[0]):
        top = horizon(x)
        for y in range(top, SIZE[1]):
            t = (y - top) / (SIZE[1] - top)
            shade = rng.randrange(-6, 7)
            draw.point((x, y), fill=(round(70 + 40 * t) + shade, round(110 + 30 * t) + shade, 52 + shade))
    img.save(path)


def make_sky(path: Path) -> None:
    img = Image.new("RGB", SIZE)
    draw = ImageDraw.Draw(img)
    for y in range(SIZE[1]):
        t = y / SIZE[1]
        draw.line([(0, y), (SIZE[0], y)], fill=(round(40 + 150 * t), round(110 + 100 * t), round(220 - 20 * t)))
    for cx, cy, r in ((260, 150, 70), (330, 130, 90), (420, 160, 60), (860, 230, 80), (930, 210, 60)):
        draw.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2), fill=(250, 248, 244))
    img.save(path)


def xcf_layers(data: bytes) -> list[tuple[str, bool]]:
    """(name, has a mask) of each layer of an XCF file, top first, read from its structure."""
    if not data.startswith(b"gimp xcf "):
        return []
    version = 0 if data[9:13] == b"file" else int(data[10:13])
    wide = version >= 11  # 64-bit offsets
    pointer = ">Q" if wide else ">I"
    step = 8 if wide else 4
    offset = 14 + 12 + (4 if version >= 4 else 0)
    while True:  # image properties
        kind, size = struct.unpack(">II", data[offset : offset + 8])
        offset += 8 + size
        if kind == 0:
            break
    layers = []
    while True:
        (where,) = struct.unpack(pointer, data[offset : offset + step])
        offset += step
        if where == 0:
            break
        at = where + 12  # width, height, type
        (length,) = struct.unpack(">I", data[at : at + 4])
        name = data[at + 4 : at + 4 + length].rstrip(b"\x00").decode("utf-8", "replace")
        at += 4 + length
        while True:  # layer properties
            kind, size = struct.unpack(">II", data[at : at + 8])
            at += 8 + size
            if kind == 0:
                break
        (_hierarchy,) = struct.unpack(pointer, data[at : at + step])
        (mask,) = struct.unpack(pointer, data[at + step : at + 2 * step])
        layers.append((name, mask != 0))
    return layers


async def steps(gimp: Session, report: Report) -> None:
    out = gimp.out
    landscape, sky = out / "landscape.png", out / "sky.png"
    make_landscape(landscape)
    make_sky(sky)
    image = (await gimp.call("gimp_open_image", path=str(landscape)))["id"]
    ground = (await gimp.call("gimp_inspect_image", image=image))["layers"][0]["id"]
    await gimp.call("gimp_set_layer_properties", item=ground, name="Landscape")
    await gimp.call("gimp_enable_toolsets", toolsets=["channels", "color"])
    await gimp.preview(image, "01-before", "1. The dull sky", max_size=600)
    # the old sky: its contiguous color from a corner, the edge softened by one pixel
    await gimp.call("gimp_select_by_color", image=image, point=[10, 10], item=ground, threshold=24)
    await gimp.call("gimp_modify_selection_shape", image=image, action="grow", amount=1)
    await gimp.call("gimp_modify_selection_shape", image=image, action="feather", amount=1.5)
    new = (await gimp.call("gimp_import_layer", image=image, path=str(sky), name="New sky"))["id"]
    await gimp.call("gimp_add_layer_mask", item=new, fill="selection")
    await gimp.call("gimp_modify_selection", image=image, action="none")
    # the foreground to the new light: warmer highlights, a little less green, as an editable filter
    graded = await gimp.call("gimp_color_balance", item=ground, range="midtones", cyan_red=18, yellow_blue=-12,
                             preserve_luminosity=True, destructive=False)  # fmt: skip
    report.check("the color grade is an editable filter", not graded["destructive"])
    await gimp.preview(image, "02-after", "2. New sky masked in, foreground warmed", max_size=600)
    xcf, png = out / "montage.xcf", out / "montage.png"
    await gimp.call("gimp_save_image", image=image, path=str(xcf), overwrite=True)
    await gimp.call("gimp_export_image", image=image, path=str(png), overwrite=True)
    filters = (await gimp.call("gimp_list_filters", item=ground))["filters"]
    report.check("the landscape keeps its color balance as a filter in the image", len(filters) == 1,
                 str([f["operation"] for f in filters]))  # fmt: skip
    await gimp.call("gimp_close_image", image=image)
    reopened = (await gimp.call("gimp_open_image", path=str(xcf)))["id"]
    details = await gimp.call("gimp_inspect_image", image=reopened)
    kept = (await gimp.call("gimp_list_filters", item=find(details, "Landscape")["id"]))["filters"]
    report.check(
        "the reopened XCF keeps the editable color balance", len(kept) == 1, str([f["operation"] for f in kept])
    )
    await gimp.call("gimp_close_image", image=reopened)
    for check in verify(out, landscape, sky):
        report.check(check.description, check.passed, check.detail)


def verify(out: Path, landscape: Path, sky: Path) -> list[Check]:
    """Facts on the montage against both pictures (shared by the scripted and agent versions)."""
    try:
        montage = Image.open(out / "montage.png").convert("RGB")
    except OSError as error:
        return [Check("montage.png is an image", False, str(error))]
    old, new = Image.open(landscape).convert("RGB"), Image.open(sky).convert("RGB")
    checks = [Check("montage.png has the landscape's size", montage.size == SIZE, str(montage.size))]
    rng = random.Random(7)
    columns = [rng.randrange(0, SIZE[0]) for _ in range(120)]

    def diff(a: tuple[int, ...], b: tuple[int, ...]) -> int:
        return max(abs(x - y) for x, y in zip(a, b, strict=False))

    sky_off = [diff(px(montage, (x, y)), px(new, (x, y))) for x in columns for y in range(5, horizon(x) - 6, 37)]
    checks.append(Check("sky pixels come from the new sky (within 8)", max(sky_off) <= 8, f"worst {max(sky_off)}"))
    ground = [(px(montage, (x, y)), px(old, (x, y))) for x in columns for y in range(horizon(x) + 6, SIZE[1], 41)]
    moved = [diff(a, b) for a, b in ground]
    checks.append(Check(f"foreground pixels change only by a bounded color grade (at most {GRADE}, not none)",
                        max(moved) <= GRADE and sum(moved) / len(moved) >= 2,
                        f"largest {max(moved)}, mean {sum(moved) / len(moved):.1f}"))  # fmt: skip
    # no halo: two pixels above the horizon it is new sky, not the old gray; two below it is ground
    halo = [x for x in columns if diff(px(montage, (x, horizon(x) - 3)), DULL) < 20]
    under = [x for x in columns if diff(px(montage, (x, horizon(x) + 3)), px(new, (x, horizon(x) + 3))) < 12]
    checks.append(Check("the horizon transition is narrower than 6 px (no gray halo, no sky on the ground)",
                        not halo and not under, f"gray above at x={halo[:5]}, sky below at x={under[:5]}"))  # fmt: skip
    layers = xcf_layers((out / "montage.xcf").read_bytes()) if (out / "montage.xcf").exists() else []
    masked = [name for name, mask in layers if mask]
    checks.append(Check("the XCF keeps the new sky as a masked layer over the landscape",
                        len(layers) >= 2 and len(masked) >= 1, str(layers)))  # fmt: skip
    return checks


def px(img: Image.Image, xy: tuple[int, int]) -> tuple[int, ...]:
    value = img.getpixel(xy)
    assert isinstance(value, tuple), value
    return value


def agent_check(out: Path, answer: str) -> list[Check]:
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        landscape, sky = Path(scratch) / "landscape.png", Path(scratch) / "sky.png"
        make_landscape(landscape)
        make_sky(sky)
        return verify(out, landscape, sky)


def agent_reference(inputs: Path, out: Path) -> None:
    old, new = Image.open(inputs / "landscape.png").convert("RGB"), Image.open(inputs / "sky.png").convert("RGB")
    mask = Image.new("L", SIZE, 0)
    ImageDraw.Draw(mask).polygon(
        [(0, 0), (SIZE[0], 0)] + [(x, horizon(x)) for x in range(SIZE[0] - 1, -1, -1)], fill=255
    )
    warmed = old.point([min(255, v + 10) for v in range(256)] + list(range(256)) + [max(0, v - 6) for v in range(256)])
    montage = Image.composite(new, warmed, mask)
    montage.save(out / "montage.png")
    name = b"New sky\x00"
    layer = struct.pack(">III", *SIZE, 1) + struct.pack(">I", len(name)) + name + struct.pack(">II", 0, 0)
    header = b"gimp xcf v011\x00" + struct.pack(">IIII", *SIZE, 0, 150) + struct.pack(">II", 0, 0)
    first = len(header) + 3 * 8
    ground = struct.pack(">III", *SIZE, 0) + struct.pack(">I", 10) + b"Landscape\x00" + struct.pack(">II", 0, 0)
    layer_at, ground_at = first, first + len(layer) + 16
    body = layer + struct.pack(">QQ", 1, 1) + ground + struct.pack(">QQ", 1, 0)
    (out / "montage.xcf").write_bytes(header + struct.pack(">QQQ", layer_at, ground_at, 0) + body)


def inputs_for_the_agent(directory: Path) -> None:
    make_landscape(directory / "landscape.png")
    make_sky(directory / "sky.png")


SCENARIO = Scenario(
    name="sky-replacement",
    title="photo montage with sky replacement",
    toolsets=("files", "layers", "selection", "filters", "channels", "color"),
    assets=(),
    outputs=("landscape.png", "sky.png", "montage.xcf", "montage.png"),
    steps=steps,
    prompt=(
        "~/inputs/landscape.png has a dull gray sky above green fields. Replace that sky with the sky of "
        "~/inputs/sky.png: select the old sky, put the new sky on its own layer with a mask so it only shows where "
        "the old sky was, with a clean horizon and no gray halo, and warm the fields a little to match the new "
        "light with an adjustment that stays editable. Do not move or resize anything. Save the layered project "
        "as ~/out/montage.xcf and export ~/out/montage.png."
    ),
    agent_output="montage.png",
    make_agent_inputs=inputs_for_the_agent,
    agent_check=agent_check,
    agent_reference=agent_reference,
)

"""A print-ready A5 flyer: 300 dpi with 3 mm bleed (154x216 mm, 1819x2551 px), guides on the trim and
the safe margins, a photo running into the bleed, a title and body text inside the safe area, exported
as a PDF and a TIFF at print size, and saved as XCF.

The photo is `lake-sunset.png` (CC0). Every size, position and resolution is computed from the print
specification, so the checks compare with known values: the PDF's page size in points (pypdf), the
TIFF's resolution (Pillow), the XCF's guides (read from the file), the layers' bounds (through MCP).
"""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

from demo.harness import Check, Report, Scenario, Session, asset, find

DPI = 300
MM = DPI / 25.4  # pixels per millimetre
TRIM_MM, BLEED_MM, SAFE_MM = (148, 210), 3, 5  # A5, bleed on each side, safe margin inside the trim
SIZE = (round((TRIM_MM[0] + 2 * BLEED_MM) * MM), round((TRIM_MM[1] + 2 * BLEED_MM) * MM))  # 1819x2551
BLEED = round(BLEED_MM * MM)  # 35 px
SAFE = round((BLEED_MM + SAFE_MM) * MM)  # 94 px from the canvas edge
PAGE_PT = ((TRIM_MM[0] + 2 * BLEED_MM) * 72 / 25.4, (TRIM_MM[1] + 2 * BLEED_MM) * 72 / 25.4)  # 436.5 x 612.3 pt
PHOTO = (1600, 1000)
TITLE, BODY = "Sunset Concert", "Saturday 14 June, 9 pm\nLakeside Park\nFree entry"
NAVY = "#1d3557"


def guides() -> list[tuple[str, int]]:
    w, h = SIZE
    found = []
    for margin in (BLEED, SAFE):  # the trim, then the safe margin
        found += [("vertical", margin), ("vertical", w - margin), ("horizontal", margin), ("horizontal", h - margin)]
    return sorted(found)


async def steps(gimp: Session, report: Report) -> None:
    w, h = SIZE
    image = (await gimp.call("gimp_create_image", width=w, height=h, fill="#ffffff"))["id"]
    await gimp.call("gimp_enable_toolsets", toolsets=["document", "formats", "compose"])
    await gimp.call("gimp_set_print_size", image=image, x_resolution=DPI, y_resolution=DPI)
    for orientation, position in guides():
        await gimp.call("gimp_add_guide", image=image, orientation=orientation, position=position)
    # the photo: the top 55%, running into the bleed on three sides
    photo = (await gimp.call("gimp_import_layer", image=image, path=str(asset("lake-sunset.png")), name="Photo"))["id"]
    ph = round(h * 0.55)
    pw = round(PHOTO[0] * ph / PHOTO[1])
    await gimp.call("gimp_scale_layer", item=photo, width=pw, height=ph, anchor="top-left")
    await gimp.call("gimp_set_layer_offsets", item=photo, x=(w - pw) // 2, y=0)
    title = await gimp.call("gimp_create_text_layer", image=image, text=TITLE, font="Sans-serif Bold", size=150,
                            color=NAVY, x=SAFE, y=ph + 90, box_width=w - 2 * SAFE, box_height=210)  # fmt: skip
    await gimp.call("gimp_set_layer_properties", item=title["id"], name="Title")
    body = await gimp.call("gimp_create_text_layer", image=image, text=BODY, font="Sans-serif", size=80, color=NAVY,
                           x=SAFE, y=ph + 360, box_width=w - 2 * SAFE, box_height=420, line_spacing=20)  # fmt: skip
    await gimp.call("gimp_set_layer_properties", item=body["id"], name="Body")
    await gimp.preview(image, "flyer", "The flyer (bleed and safe-area guides not printed)", max_size=640)

    details = await gimp.call("gimp_inspect_image", image=image)
    node = find(details, "Photo")
    report.check("the photo reaches the bleed edges (left, top, right)",
                 node["x"] <= 0 and node["y"] <= 0 and node["x"] + node["width"] >= w,
                 f"{node['x']},{node['y']} {node['width']}x{node['height']}")  # fmt: skip
    for name in ("Title", "Body"):
        node = find(details, name)
        inside = node["x"] >= SAFE and node["y"] >= SAFE and node["x"] + node["width"] <= w - SAFE
        inside = inside and node["y"] + node["height"] <= h - SAFE
        detail = f"{node['x']},{node['y']} {node['width']}x{node['height']}"
        report.check(f"the {name.lower()} lies inside the safe area", inside, f"{detail}, safe margin {SAFE} px")
    found = sorted(
        (g["orientation"], g["position"]) for g in (await gimp.call("gimp_list_guides", image=image))["guides"]
    )
    report.check("guides on the trim and the safe margins", found == guides(), str(found))

    out = gimp.out
    await gimp.call("gimp_save_image", image=image, path=str(out / "flyer.xcf"), overwrite=True)
    # a TIFF export writes one page per layer: the printer gets the flattened page
    await gimp.call("gimp_flatten_image", image=image)
    await gimp.call("gimp_export_as", image=image, path=str(out / "flyer.pdf"), overwrite=True)
    await gimp.call("gimp_export_as", image=image, path=str(out / "flyer.tif"), overwrite=True)
    await gimp.call("gimp_close_image", image=image, discard_changes=True)  # flattened: the XCF has the layers
    for check in verify(out):
        report.check(check.description, check.passed, check.detail)


def xcf_guides(path: Path) -> list[tuple[str, int]] | None:
    """The guides stored in an XCF file (image property 18: int32 position, int8 orientation)."""
    data = path.read_bytes()
    if not data.startswith(b"gimp xcf "):
        return None
    version = 0 if data[9:13] == b"file" else int(data[10:13])
    offset = 14 + 12 + (4 if version >= 4 else 0)  # magic, width, height, base type, precision
    found = []
    while offset + 8 <= len(data):
        kind, size = struct.unpack(">II", data[offset : offset + 8])
        body = data[offset + 8 : offset + 8 + size]
        if kind == 0:  # PROP_END
            break
        if kind == 18:
            for i in range(0, size - size % 5, 5):
                position, orientation = struct.unpack(">ib", body[i : i + 5])
                found.append(({1: "horizontal", 2: "vertical"}.get(orientation, "?"), position))
        offset += 8 + size
    return sorted(found)


def verify(out: Path) -> list[Check]:
    """Facts on the files, read without GIMP (shared by the scripted and the agent versions)."""
    from pypdf import PdfReader

    checks = []
    try:
        page = PdfReader(out / "flyer.pdf").pages[0]
        size = (float(page.mediabox.width), float(page.mediabox.height))
        ok = all(abs(a - b) < 1.5 for a, b in zip(size, PAGE_PT, strict=True))
        detail = f"{size[0]:.1f} x {size[1]:.1f} pt, expected {PAGE_PT[0]:.1f} x {PAGE_PT[1]:.1f}"
        checks.append(Check("the PDF page is 154x216 mm (A5 with 3 mm bleed)", ok, detail))
    except Exception as error:
        checks.append(
            Check("the PDF page is 154x216 mm (A5 with 3 mm bleed)", False, f"{type(error).__name__}: {error}")
        )
    try:
        with Image.open(out / "flyer.tif") as tiff:
            dpi = tiff.info.get("dpi")
            ok = tiff.size == SIZE and dpi is not None and all(abs(float(v) - DPI) < 1 for v in dpi)
            checks.append(Check(f"the TIFF is {SIZE[0]}x{SIZE[1]} at 300 dpi", ok, f"{tiff.size}, {dpi}"))
            rgb = tiff.convert("RGB")
            edge = [rgb.getpixel((x, 2)) for x in range(0, SIZE[0], 40)] + [
                rgb.getpixel((2, y)) for y in range(0, 900, 40)
            ]
            white = sum(1 for p in edge if min(p) > 245)  # type: ignore[arg-type]
            checks.append(Check("the photo is printed up to the bleed edge (no white on the top and left edges)",
                                white == 0, f"{white} white samples"))  # fmt: skip
    except OSError as error:
        checks.append(Check(f"the TIFF is {SIZE[0]}x{SIZE[1]} at 300 dpi", False, str(error)))
    found = xcf_guides(out / "flyer.xcf") if (out / "flyer.xcf").exists() else None
    checks.append(Check("the XCF keeps guides on the trim and the safe margins", found == guides(), str(found)))
    return checks


def agent_check(out: Path, answer: str) -> list[Check]:
    return verify(out)


def agent_reference(inputs: Path, out: Path) -> None:
    from PIL import ImageDraw

    w, h = SIZE
    img = Image.new("RGB", SIZE, (255, 255, 255))
    photo = Image.open(inputs / "lake-sunset.png").convert("RGB")
    ph = round(h * 0.55)
    pw = round(PHOTO[0] * ph / PHOTO[1])
    img.paste(photo.resize((pw, ph)), ((w - pw) // 2, 0))
    ImageDraw.Draw(img).rectangle((SAFE, ph + 120, w // 2, ph + 260), fill=(29, 53, 87))
    img.save(out / "flyer.tif", dpi=(DPI, DPI))
    img.save(out / "flyer.pdf", resolution=DPI)
    props = b"".join(struct.pack(">ib", position, 1 if o == "horizontal" else 2) for o, position in guides())
    header = b"gimp xcf v011\x00" + struct.pack(">IIII", w, h, 0, 150)
    (out / "flyer.xcf").write_bytes(header + struct.pack(">II", 18, len(props)) + props + struct.pack(">II", 0, 0))


SCENARIO = Scenario(
    name="print-flyer",
    title="print-ready A5 flyer",
    toolsets=("files", "layers", "transform", "text", "document", "formats", "compose"),
    assets=("lake-sunset.png",),
    outputs=("flyer.xcf", "flyer.pdf", "flyer.tif"),
    steps=steps,
    prompt=(
        "Lay out a print-ready A5 flyer at 300 dpi with 3 mm bleed on each side (the canvas is 154x216 mm, "
        "1819x2551 px). Add guides on the trim (3 mm from each edge, 35 px) and on a 5 mm safe margin inside it "
        "(94 px from each edge). Put ~/inputs/lake-sunset.png across the top part, running into the bleed, and the "
        f'title "{TITLE}" and the text "Saturday 14 June, 9 pm / Lakeside Park / Free entry" below it, all text '
        "inside the safe area. Save it as ~/out/flyer.xcf and export ~/out/flyer.pdf and ~/out/flyer.tif at print "
        "size and 300 dpi."
    ),
    agent_output="flyer.tif",
    agent_check=agent_check,
    agent_reference=agent_reference,
)

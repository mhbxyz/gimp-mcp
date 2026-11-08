"""One design adapted to four social formats: an Instagram post (1080x1080), a story (1080x1920), a
banner (1500x500) and a video thumbnail (1280x720). Each keeps the photo, the brand band and colors,
the logo and an editable headline, with guides on the format's safe area; each is saved as XCF and
exported as PNG.

The photo is `lake-sunset.png` (CC0); the logo is drawn by code (CC0). Brand colors, safe areas,
headline and font are given, so every check compares with known values.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from demo.harness import Check, Report, Scenario, Session, asset, find

HEADLINE = "Golden Hour Sale"
FONT = "Sans-serif Bold"
NAVY, RED, CREAM, TEAL = "#1d3557", "#e63946", "#f1faee", "#2a9d8f"
# format: (width, height, (left, top, right, bottom) safe margins)
FORMATS: dict[str, tuple[int, int, tuple[int, int, int, int]]] = {
    "post": (1080, 1080, (64, 64, 64, 64)),
    "story": (1080, 1920, (64, 250, 64, 250)),
    "banner": (1500, 500, (60, 60, 60, 60)),
    "thumbnail": (1280, 720, (64, 64, 64, 64)),
}
PHOTO = (1600, 1000)


def rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def make_logo(path: Path) -> None:
    """A teal disc with a cream ring and a cream bar: the brand mark (300x300, transparent around)."""
    big = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.ellipse((0, 0, 599, 599), fill=rgb(TEAL))
    draw.ellipse((110, 110, 489, 489), outline=rgb(CREAM), width=48)
    draw.rectangle((280, 180, 320, 420), fill=rgb(CREAM))
    big.resize((300, 300), Image.Resampling.LANCZOS).save(path)


def band_height(name: str, box_h: int) -> int:
    _, h, (_, _, _, bottom) = FORMATS[name]
    return max(round(h * 0.24), box_h + bottom + 24)


def safe_box(name: str) -> tuple[int, int, int, int]:
    w, h, (left, top, right, bottom) = FORMATS[name]
    return left, top, w - right, h - bottom


async def build(gimp: Session, report: Report, name: str, logo: Path) -> None:
    w, h, (left, top, right, bottom) = FORMATS[name]
    image = (await gimp.call("gimp_create_image", width=w, height=h, fill=NAVY))["id"]
    for orientation, position in (("vertical", left), ("vertical", w - right), ("horizontal", top),
                                  ("horizontal", h - bottom)):  # fmt: skip
        await gimp.call("gimp_add_guide", image=image, orientation=orientation, position=position)
    # the photo covers the canvas
    source = str(asset("lake-sunset.png"))
    photo = (await gimp.call("gimp_import_layer", image=image, path=source, name="Photo"))["id"]
    scale = max(w / PHOTO[0], h / PHOTO[1])
    pw, ph = round(PHOTO[0] * scale), round(PHOTO[1] * scale)
    await gimp.call("gimp_scale_layer", item=photo, width=pw, height=ph, anchor="top-left")
    await gimp.call("gimp_set_layer_offsets", item=photo, x=(w - pw) // 2, y=(h - ph) // 2)
    # the brand band at the bottom, its red accent line, the headline inside the safe area
    size = round(min(w, h * 1.6) * 0.075)
    box_w, box_h = w - left - right, round(size * 1.5)
    band_h = band_height(name, box_h)  # the band always holds the headline's box
    band = (await gimp.call("gimp_create_layer", image=image, name="Brand band"))["id"]
    await gimp.call("gimp_draw_shape", item=band, shape="rectangle", x=0, y=h - band_h, width=w, height=band_h,
                    fill_color=NAVY)  # fmt: skip
    await gimp.call("gimp_draw_shape", item=band, shape="rectangle", x=0, y=h - band_h, width=w, height=8,
                    fill_color=RED)  # fmt: skip
    text = await gimp.call("gimp_create_text_layer", image=image, text=HEADLINE, font=FONT, size=size, color=CREAM,
                           x=left, y=h - bottom - box_h, box_width=box_w, box_height=box_h)  # fmt: skip
    await gimp.call("gimp_set_layer_properties", item=text["id"], name="Headline")
    # the logo in the top-right corner of the safe area
    side = round(min(w, h) * 0.16)
    mark = (await gimp.call("gimp_import_layer", image=image, path=str(logo), name="Logo"))["id"]
    await gimp.call("gimp_scale_layer", item=mark, width=side, height=side, anchor="top-left")
    await gimp.call("gimp_set_layer_offsets", item=mark, x=w - right - side, y=top)
    await gimp.preview(image, f"{name}", f"{name} ({w}x{h})", max_size=480)
    xcf, png = gimp.out / f"social-{name}.xcf", gimp.out / f"social-{name}.png"
    await gimp.call("gimp_save_image", image=image, path=str(xcf), overwrite=True)
    await gimp.call("gimp_export_image", image=image, path=str(png), overwrite=True)
    await gimp.call("gimp_close_image", image=image)

    # the reopened XCF: editable headline, guides, logo and text inside them
    again = (await gimp.call("gimp_open_image", path=str(xcf)))["id"]
    details = await gimp.call("gimp_inspect_image", image=again)
    headline = find(details, "Headline")
    props = await gimp.call("gimp_inspect_text", item=headline["id"])
    report.check(f"{name}: the headline is editable text, '{HEADLINE}' in {FONT}",
                 headline["kind"] == "text" and props["text"] == HEADLINE and props["font"] == FONT,
                 f"{props['text']!r}, {props['font']}")  # fmt: skip
    guides = (await gimp.call("gimp_list_guides", image=again))["guides"]
    found = sorted((g["orientation"], g["position"]) for g in guides)
    expected = sorted([("vertical", left), ("vertical", w - right), ("horizontal", top), ("horizontal", h - bottom)])
    report.check(f"{name}: guides on the safe area", found == expected, str(found))
    x0, y0, x1, y1 = safe_box(name)
    for layer_name in ("Headline", "Logo"):
        node = find(details, layer_name)
        inside = x0 <= node["x"] and y0 <= node["y"]
        inside = inside and node["x"] + node["width"] <= x1 and node["y"] + node["height"] <= y1
        report.check(f"{name}: the {layer_name.lower()} lies inside the safe area", inside,
                     f"{node['x']},{node['y']} {node['width']}x{node['height']} in {x0},{y0}-{x1},{y1}")  # fmt: skip
    await gimp.call("gimp_close_image", image=again)


async def steps(gimp: Session, report: Report) -> None:
    logo = gimp.out / "logo.png"
    make_logo(logo)
    for name in FORMATS:
        await build(gimp, report, name, logo)
    for check in verify(gimp.out):
        report.check(check.description, check.passed, check.detail)


def share(img: Image.Image, color: str, tolerance: int = 3) -> float:
    """Fraction of the pixels within ``tolerance`` of ``color``."""
    target = rgb(color)
    bands = img.convert("RGB").split()
    masks = [band.point([255 if abs(v - t) <= tolerance else 0 for v in range(256)])
             for band, t in zip(bands, target, strict=True)]  # fmt: skip
    both = ImageChops.multiply(ImageChops.multiply(masks[0], masks[1]), masks[2])
    return both.histogram()[255] / (img.width * img.height)


def logo_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    target = rgb(TEAL)
    bands = img.convert("RGB").split()
    masks = [band.point([255 if abs(v - t) <= 6 else 0 for v in range(256)])
             for band, t in zip(bands, target, strict=True)]  # fmt: skip
    return ImageChops.multiply(ImageChops.multiply(masks[0], masks[1]), masks[2]).getbbox()


def xcf_texts(data: bytes) -> list[str]:
    """The texts of the text layers of an XCF file (its "gimp-text-layer" parasites), line breaks read as
    spaces: a headline set on two lines is the same headline."""
    import re

    found = re.findall(rb'\(text "((?:[^"\\]|\\.)*)"', data)
    return [" ".join(t.decode("utf-8", "replace").replace("\\n", " ").split()) for t in found]


def verify(out: Path) -> list[Check]:
    """Facts on the files, read without GIMP (shared by the scripted and the agent versions)."""
    checks = []
    for name, (w, h, _) in FORMATS.items():
        png, xcf = out / f"social-{name}.png", out / f"social-{name}.xcf"
        try:
            img = Image.open(png)
            img.load()
        except OSError as error:
            checks.append(Check(f"social-{name}.png is an image", False, str(error)))
            continue
        checks.append(Check(f"social-{name}.png is {w}x{h}", img.size == (w, h), f"{img.width}x{img.height}"))
        navy, cream, red = share(img, NAVY), share(img, CREAM), share(img, RED, 6)
        checks.append(Check(f"{name}: the brand colors are there (navy band, cream text, red accent)",
                            navy >= 0.03 and cream >= 0.002 and red >= 0.0005,
                            f"navy {navy:.1%}, cream {cream:.2%}, red {red:.2%}"))  # fmt: skip
        box = logo_box(img)
        x0, y0, x1, y1 = safe_box(name)
        inside = box is not None and x0 <= box[0] and y0 <= box[1] and box[2] <= x1 and box[3] <= y1
        detail = f"logo {box}, safe {x0},{y0}-{x1},{y1}"
        checks.append(Check(f"{name}: the logo lies inside the safe area", inside, detail))
        # an XCF keeps a text layer as a "gimp-text-layer" parasite with its text, readable in the file
        data = xcf.read_bytes() if xcf.exists() else b""
        editable = data.startswith(b"gimp xcf") and b"gimp-text-layer" in data and HEADLINE in xcf_texts(data)
        checks.append(Check(f"social-{name}.xcf keeps the headline as an editable text layer", editable,
                            f"{len(data)} bytes"))  # fmt: skip
    return checks


def agent_check(out: Path, answer: str) -> list[Check]:
    return verify(out)


def agent_reference(inputs: Path, out: Path) -> None:
    """The four formats drawn with Pillow, and minimal XCF-like files carrying the text-layer parasite."""
    photo = Image.open(inputs / "lake-sunset.png").convert("RGB")
    logo = Image.open(inputs / "logo.png").convert("RGBA")
    for name, (w, h, (left, top, right, _)) in FORMATS.items():
        scale = max(w / PHOTO[0], h / PHOTO[1])
        canvas = Image.new("RGB", (w, h), rgb(NAVY))
        scaled = photo.resize((round(PHOTO[0] * scale), round(PHOTO[1] * scale)))
        canvas.paste(scaled, ((w - scaled.width) // 2, (h - scaled.height) // 2))
        draw = ImageDraw.Draw(canvas)
        band_h = band_height(name, round(round(min(w, h * 1.6) * 0.075) * 1.5))
        draw.rectangle((0, h - band_h, w, h), fill=rgb(NAVY))
        draw.rectangle((0, h - band_h, w, h - band_h + 8), fill=rgb(RED))
        draw.rectangle((left, h - band_h + 40, left + w // 3, h - band_h + 70), fill=rgb(CREAM))  # the text
        side = round(min(w, h) * 0.16)
        canvas.paste(logo.resize((side, side)), (w - right - side, top), logo.resize((side, side)))
        canvas.save(out / f"social-{name}.png")
        parasite = b'gimp-text-layer(text "' + HEADLINE.encode() + b'")'
        (out / f"social-{name}.xcf").write_bytes(b"gimp xcf v020\x00" + parasite)


def inputs_for_the_agent(directory: Path) -> None:
    import shutil

    shutil.copyfile(asset("lake-sunset.png"), directory / "lake-sunset.png")
    make_logo(directory / "logo.png")


SCENARIO = Scenario(
    name="social-media-kit",
    title="social media kit from one design",
    toolsets=("files", "layers", "transform", "paint", "text", "document"),
    assets=("lake-sunset.png",),
    outputs=("logo.png", *(f"social-{n}.{e}" for n in FORMATS for e in ("xcf", "png"))),
    steps=steps,
    prompt=(
        "Make a social media kit from ~/inputs/lake-sunset.png and the logo ~/inputs/logo.png, with the headline "
        f'"{HEADLINE}" in a bold sans-serif font. Brand colors: navy {NAVY} for a band behind the headline, cream '
        f"{CREAM} for the headline, red {RED} for an accent line. Make four versions, each with guides on its safe "
        "area, the headline kept as editable text, and the headline and the logo inside the safe area: an Instagram "
        "post 1080x1080 (safe margins 64 px), a story 1080x1920 (safe margins 64 px left and right, 250 px top and "
        "bottom), a banner 1500x500 (60 px) and a video thumbnail 1280x720 (64 px). Save each as XCF and export it "
        "as PNG: ~/out/social-post.xcf, ~/out/social-post.png, ~/out/social-story.xcf, ~/out/social-story.png, "
        "~/out/social-banner.xcf, ~/out/social-banner.png, ~/out/social-thumbnail.xcf and "
        "~/out/social-thumbnail.png."
    ),
    agent_output="social-thumbnail.png",
    make_agent_inputs=inputs_for_the_agent,
    agent_check=agent_check,
    agent_reference=agent_reference,
)

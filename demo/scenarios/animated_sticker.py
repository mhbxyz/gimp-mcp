"""A looping animated sticker: a logo that slides in from the left and fades in over 12 frames, each
frame with its own timing and disposal, then optimized and exported as GIF and animated WebP under a
500 KB budget.

The logo is drawn by code (CC0); every frame's logo position and opacity are known, so each frame is
checked against them after reading the files back with Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from demo.harness import Check, Report, Scenario, Session

SIZE = (480, 240)
BACKGROUND = (253, 246, 227)
TEAL, CREAM = (42, 157, 143), (241, 250, 238)
LOGO = 96
FRAMES = 12
STEP_MS, HOLD_MS = 80, 1000  # every frame 80 ms, the last one held 1 s
BUDGET = 500 * 1024


def position(k: int) -> tuple[int, int]:
    """Top-left corner of the logo on frame ``k`` (0-based): from x=40 to x=304, y centered."""
    return 40 + k * 24, (SIZE[1] - LOGO) // 2


def opacity(k: int) -> int:
    return round(100 * (k + 1) / FRAMES)


def duration(k: int) -> int:
    return HOLD_MS if k == FRAMES - 1 else STEP_MS


def make_logo(path: Path) -> None:
    img = Image.new("RGBA", (LOGO, LOGO), (*TEAL, 255))
    ImageDraw.Draw(img).ellipse((22, 22, LOGO - 23, LOGO - 23), outline=(*CREAM, 255), width=10)
    img.save(path)


def px(img: Image.Image, xy: tuple[int, int]) -> tuple[int, ...]:
    value = img.getpixel(xy)
    assert isinstance(value, tuple), value
    return value


def hexcolor(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


async def steps(gimp: Session, report: Report) -> None:
    out = gimp.out
    logo = out / "logo.png"
    make_logo(logo)
    await gimp.call("gimp_enable_toolsets", toolsets=["animation", "compose"])
    image = (await gimp.call("gimp_create_image", width=SIZE[0], height=SIZE[1], fill=hexcolor(BACKGROUND)))["id"]
    first = (await gimp.call("gimp_inspect_image", image=image))["layers"][0]["id"]
    for k in range(FRAMES):
        # the new frame goes on top (after the canvas and the frames before it), the logo right above it
        await gimp.call("gimp_add_frame", image=image, index=k + 1, fill=hexcolor(BACKGROUND))
        x, y = position(k)
        mark = (await gimp.call("gimp_import_layer", image=image, path=str(logo), name="Logo", x=x, y=y))["id"]
        await gimp.call("gimp_set_layer_properties", item=mark, opacity=opacity(k))
        merged = await gimp.call("gimp_merge_layers", mode="down", item=mark, merge_type="clip-to-bottom")
        await gimp.call("gimp_set_frame", item=merged["layer"]["id"], name=f"Frame {k + 1}", duration_ms=duration(k),
                        disposal="replace")  # fmt: skip
    await gimp.call("gimp_delete_layer", item=first)  # the canvas the frames were added to
    frames = (await gimp.call("gimp_list_frames", image=image))["frames"]
    report.check("12 frames with their own timing and disposal",
                 [(f["duration_ms"], f["disposal"]) for f in frames]
                 == [(duration(k), "replace") for k in range(FRAMES)],
                 str([(f["duration_ms"], f["disposal"]) for f in frames][:3]) + "...")  # fmt: skip
    for k in (0, 6, 11):
        await gimp.call("gimp_preview_frame", image=image, index=k, max_size=480)
    optimized = (await gimp.call("gimp_optimize_animation", image=image, mode="optimize"))["image"]
    gif, webp = out / "sticker.gif", out / "sticker.webp"
    await gimp.call("gimp_export_animation", image=optimized, path=str(gif), loop=True, overwrite=True)
    await gimp.call("gimp_export_animation", image=image, path=str(webp), loop=True, overwrite=True)
    await gimp.preview(image, "sticker-last", "The last frame (logo in place, fully opaque)", max_size=480)
    for shown in (optimized, image):
        await gimp.call("gimp_close_image", image=shown, discard_changes=True)
    for check in verify(out):
        report.check(check.description, check.passed, check.detail)


def webp_durations(path: Path) -> list[int]:
    """Frame durations from the RIFF chunks (ANMF): Pillow does not expose WebP durations."""
    data, durations, offset = path.read_bytes(), [], 12
    while offset + 8 <= len(data):
        kind, size = data[offset : offset + 4], int.from_bytes(data[offset + 4 : offset + 8], "little")
        if kind == b"ANMF":
            durations.append(int.from_bytes(data[offset + 8 + 12 : offset + 8 + 15], "little"))
        offset += 8 + size + (size & 1)
    return durations


def mixes(a: float) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """The logo at opacity ``a`` over the background: mixed in sRGB, or in linear light (GIMP 3's default,
    docs/gimp-notes.md). Either is a correct opacity."""
    from evals.tasks import to_linear, to_srgb

    perceptual = tuple(round(a * t + (1 - a) * b) for t, b in zip(TEAL, BACKGROUND, strict=True))
    linear = tuple(to_srgb(a * to_linear(t) + (1 - a) * to_linear(b)) for t, b in zip(TEAL, BACKGROUND, strict=True))
    return perceptual, linear


def verify(out: Path) -> list[Check]:
    """Frames, timing, looping, logo position and opacity, size: read with Pillow."""
    checks = []
    for name, tolerance in (("sticker.gif", 40), ("sticker.webp", 6)):
        path = out / name
        try:
            img = Image.open(path)
        except OSError as error:
            checks.append(Check(f"{name} is an animation", False, str(error)))
            continue
        count = getattr(img, "n_frames", 1)
        durations, wrong = [], []
        for k in range(count):
            img.seek(k)
            durations.append(img.info.get("duration"))  # (None for WebP: read from its chunks below)
            if k >= FRAMES:
                continue
            rgb = img.convert("RGB")
            x, y = position(k)
            a = opacity(k) / 100
            got = px(rgb, (x + 8, y + 8))  # inside the logo, away from its ring
            expected = min(mixes(a), key=lambda m: max(abs(g - e) for g, e in zip(got, m, strict=True)))
            behind = px(rgb, (max(0, x - 20), y + 8))  # left of the logo: the background
            if max(abs(g - e) for g, e in zip(got, expected, strict=True)) > tolerance or \
                    max(abs(g - e) for g, e in zip(behind, BACKGROUND, strict=True)) > tolerance:  # type: ignore[arg-type]  # fmt: skip
                wrong.append(f"frame {k + 1}: logo {got} ~ {expected}, before it {behind}")
        img.seek(0)
        if name.endswith(".webp"):
            durations = webp_durations(path)
        checks.append(Check(f"{name} has 12 frames and loops", count == FRAMES and img.info.get("loop") == 0,
                            f"{count} frames, loop {img.info.get('loop')}"))  # fmt: skip
        checks.append(Check(f"{name}: 80 ms per frame, the last held 1 s",
                            durations == [duration(k) for k in range(FRAMES)], str(durations)))  # fmt: skip
        placed = not wrong and count == FRAMES
        checks.append(Check(f"{name}: each frame shows the logo at its place and opacity", placed,
                            "; ".join(wrong[:3])))  # fmt: skip
        checks.append(Check(f"{name} is under 500 KB", path.stat().st_size < BUDGET, f"{path.stat().st_size} bytes"))
    return checks


def agent_check(out: Path, answer: str) -> list[Check]:
    return verify(out)


def agent_reference(inputs: Path, out: Path) -> None:
    logo = Image.open(inputs / "logo.png").convert("RGBA")
    frames = []
    for k in range(FRAMES):
        frame = Image.new("RGB", SIZE, BACKGROUND)
        faded = logo.copy()
        faded.putalpha(logo.getchannel("A").point([v * opacity(k) // 100 for v in range(256)]))
        frame.paste(faded, position(k), faded)
        frames.append(frame)
    durations = [duration(k) for k in range(FRAMES)]
    frames[0].save(out / "sticker.gif", save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=1)
    frames[0].save(out / "sticker.webp", save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   lossless=True)  # fmt: skip


def logo_for_the_agent(directory: Path) -> None:
    make_logo(directory / "logo.png")


SCENARIO = Scenario(
    name="animated-sticker",
    title="animated sticker",
    toolsets=("files", "layers", "animation", "compose"),
    assets=(),
    outputs=("logo.png", "sticker.gif", "sticker.webp"),
    steps=steps,
    prompt=(
        "Make a looping animated sticker, 480x240 on a #fdf6e3 background, from the logo ~/inputs/logo.png (96x96): "
        "in 12 frames the logo slides from x=40 to x=304 (24 px per frame, vertically centered at y=72) while "
        "fading in, from 8% opacity on the first frame to 100% on the last. Each frame lasts 80 ms and the last "
        "one 1000 ms; each frame replaces the previous one. Optimize it and export it as ~/out/sticker.gif and "
        "~/out/sticker.webp, each under 500 KB."
    ),
    agent_output="sticker.webp",
    make_agent_inputs=logo_for_the_agent,
    agent_check=agent_check,
    agent_reference=agent_reference,
)

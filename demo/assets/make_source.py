"""Generate demo/assets/lake-sunset.png, the demo's source image.

The picture is computed (no photo, no network), so it is free of rights:
CC0 1.0 / public domain, like this script. Deterministic: same bytes on every run.

    uv run python demo/assets/make_source.py
"""

from __future__ import annotations

import itertools
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

WIDTH, HEIGHT = 1600, 1000
HORIZON = 620


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))  # type: ignore[return-value]


def sky(img: Image.Image) -> None:
    stops = [(0.0, (38, 24, 74)), (0.45, (164, 62, 112)), (0.8, (247, 132, 72)), (1.0, (255, 206, 120))]
    draw = ImageDraw.Draw(img)
    for y in range(HORIZON):
        t = y / HORIZON
        for (t0, c0), (t1, c1) in itertools.pairwise(stops):
            if t0 <= t <= t1:
                draw.line([(0, y), (WIDTH, y)], fill=lerp(c0, c1, (t - t0) / (t1 - t0)))
                break


def sun(img: Image.Image) -> None:
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx, cy = 1050, 330
    for r in range(260, 0, -4):
        alpha = int(90 * (1 - r / 260) ** 2)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 220, 150, alpha))
    draw.ellipse([cx - 85, cy - 85, cx + 85, cy + 85], fill=(255, 240, 200, 255))
    img.alpha_composite(glow)


def mountains(img: Image.Image, rng: random.Random) -> None:
    draw = ImageDraw.Draw(img)
    for layer, (base, color, amp) in enumerate(
        [(HORIZON - 40, (88, 40, 92), 170), (HORIZON - 5, (58, 26, 66), 120), (HORIZON, (30, 16, 40), 70)]
    ):
        points: list[tuple[float, float]] = [(0, HORIZON)]
        phase = rng.random() * math.tau
        for x in range(0, WIDTH + 20, 20):
            y = base - amp * (0.55 + 0.45 * math.sin(x / (210 - layer * 40) + phase)) * (0.7 + 0.3 * rng.random())
            points.append((x, y))
        points.append((WIDTH, HORIZON))
        draw.polygon(points, fill=color)


def lake(img: Image.Image) -> None:
    reflection = img.crop((0, HORIZON - (HEIGHT - HORIZON), WIDTH, HORIZON)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    reflection = reflection.filter(ImageFilter.GaussianBlur(3))
    water = Image.new("RGBA", reflection.size, (20, 30, 70, 255))
    blended = Image.blend(reflection, water, 0.45)
    ripples = Image.new("RGBA", blended.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ripples)
    rng = random.Random(7)
    for y in range(4, blended.height, 7):
        for _ in range(6):
            x = rng.randrange(0, WIDTH)
            length = rng.randrange(40, 260)
            draw.line([(x, y), (x + length, y)], fill=(255, 214, 170, 26 + y // 12), width=1)
    blended.alpha_composite(ripples)
    img.paste(blended, (0, HORIZON))


def main() -> None:
    rng = random.Random(20261107)
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    sky(img)
    sun(img)
    mountains(img, rng)
    lake(img)
    out = Path(__file__).with_name("lake-sunset.png")
    img.convert("RGB").save(out, optimize=True)
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

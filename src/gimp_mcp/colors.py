"""Explicit colors: '#rgb', '#rrggbb', '#rrggbbaa' or a few names. Values are sRGB."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import GimpMcpError

NAMED = {
    "white": "#ffffff",
    "black": "#000000",
    "red": "#ff0000",
    "green": "#00ff00",
    "blue": "#0000ff",
    "transparent": "#00000000",
}
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

COLOR_DESCRIPTION = "sRGB color as '#rrggbb', '#rrggbbaa', '#rgb' or one of: " + ", ".join(NAMED)


@dataclass(frozen=True)
class Rgba:
    r: float
    g: float
    b: float
    a: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.r, self.g, self.b, self.a)

    def to_wire(self) -> list[float]:
        return list(self.as_tuple())


def parse_color(text: str) -> Rgba:
    value = NAMED.get(text.strip().lower(), text.strip())
    match = _HEX.match(value)
    if match is None:
        raise GimpMcpError("INVALID_ARGUMENT", f"invalid color {text!r}", hint=COLOR_DESCRIPTION)
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    if len(digits) == 6:
        digits += "ff"
    r, g, b, a = (int(digits[i : i + 2], 16) / 255 for i in range(0, 8, 2))
    return Rgba(r, g, b, a)

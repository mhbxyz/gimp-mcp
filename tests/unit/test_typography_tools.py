"""Typography tools (#56), MCP side."""

from __future__ import annotations

import pytest

from .tool_harness import tid, tool_client


@pytest.mark.parametrize(
    "arguments",
    [
        {"base_direction": "upside-down"},
        {"hint_style": "extreme"},
        {"outline": {"mode": "glow"}},
        {"outline": {"color": "nope"}},
        {"box": {"width": 0, "height": 10}},
    ],
)
async def test_invalid_styles_never_reach_gimp(arguments):
    async with tool_client({}) as (client, bridge):
        result = await client.call_tool("gimp_set_text_style", {"item": tid(4), **arguments})
        assert result.is_error and bridge.calls == []


async def test_outline_color_is_sent_as_srgb_floats():
    style = {"item": 4, "text": "x", "markup": None, "outline": {}, "kerning": True, "hint_style": "none",
             "indent": 0.0, "language": None, "base_direction": "ltr", "antialias": True, "width": 10,
             "height": 10}  # fmt: skip
    async with tool_client({"text.style_set": lambda p: style}) as (client, bridge):
        result = await client.call_tool("gimp_set_text_style", {"item": tid(4), "outline": {"color": "#00ff00"}})
        assert not result.is_error, result.content
        assert bridge.calls[0][1]["outline"]["color"] == [0.0, 1.0, 0.0, 1.0]

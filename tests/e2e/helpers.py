"""Small helpers for end-to-end tests."""

from __future__ import annotations

import base64
import io
from typing import Any

from mcp import Client
from PIL import Image


async def call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def error(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    assert result.is_error, f"{tool} unexpectedly succeeded: {result.structured_content}"
    assert result.structured_content is not None, result.content
    return result.structured_content["error"]


async def preview(client: Client, image: str, max_size: int = 1024) -> Image.Image:
    result = await client.call_tool("gimp_preview", {"image": image, "max_size": max_size})
    assert not result.is_error, result.content
    block = next(block for block in result.content if block.type == "image")
    return Image.open(io.BytesIO(base64.b64decode(block.data))).convert("RGBA")


def rgba(img: Image.Image, x: int, y: int) -> tuple[int, int, int, int]:
    pixel = img.getpixel((x, y))
    assert isinstance(pixel, tuple)
    return (pixel[0], pixel[1], pixel[2], pixel[3])


def tree(image: dict[str, Any]) -> list[Any]:
    def walk(nodes: list[dict[str, Any]]) -> list[Any]:
        return [(n["name"], n["kind"], walk(n["children"] or [])) for n in nodes]

    return walk(image["layers"])


def find(image: dict[str, Any], name: str) -> dict[str, Any]:
    stack = list(image["layers"])
    while stack:
        node = stack.pop(0)
        if node["name"] == name:
            return node
        stack.extend(node.get("children") or [])
    raise AssertionError(f"layer {name!r} not found in {tree(image)}")

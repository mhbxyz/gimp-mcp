"""Argument validation failures reach agents as gimp-mcp errors, not framework text (#146)."""

from __future__ import annotations

import json
from typing import Any

from mcp import Client

from gimp_mcp.bridge import BridgeClient
from gimp_mcp.server import build_server

from .fake_bridge import running_fake_bridge
from .tool_harness import iid, tid, tool_client


def text_of(result: Any) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content) + json.dumps(result.structured_content)


def error_of(result: Any) -> dict[str, Any]:
    assert result.is_error, result.content
    return result.structured_content["error"]


async def call(name: str, arguments: dict[str, Any]) -> Any:
    async with tool_client({}) as (client, _bridge):
        return await client.call_tool(name, arguments)


async def test_missing_arguments_name_the_fields_and_the_required_parameters():
    result = await call("gimp_convert_mode", {})
    error = error_of(result)
    assert error["code"] == "INVALID_ARGUMENT" and error["outcome"] == "not_applied"
    assert {e["field"] for e in error["details"]["errors"]} == {"image", "mode"}
    assert all(e["problem"] == "missing" for e in error["details"]["errors"])
    assert error["details"]["required"] == ["image", "mode"]
    assert "gimp_convert_mode" in error["hint"] and "image" in error["hint"] and "mode" in error["hint"]
    assert "mode ('rgb'|'gray'|'indexed')" in error["hint"]


async def test_a_wrong_type_names_the_field_and_what_was_expected():
    result = await call("gimp_resize_image", {"image": iid(1), "width": "big", "height": 10})
    error = error_of(result)
    assert error["code"] == "INVALID_ARGUMENT"
    [problem] = error["details"]["errors"]
    assert problem["field"] == "width" and "integer" in problem["problem"]


async def test_a_wrong_nested_option_names_its_path():
    result = await call(
        "gimp_export_image", {"image": iid(1), "path": "/tmp/x.png", "png_options": {"compression": 42}}
    )
    [problem] = error_of(result)["details"]["errors"]
    assert problem["field"] == "png_options.compression" and "9" in problem["problem"]


async def test_no_framework_text_reaches_the_agent():
    for name, arguments in [
        ("gimp_convert_mode", {}),
        ("gimp_resize_image", {"image": iid(1), "width": "big", "height": 0}),
        ("gimp_export_image", {"image": iid(1), "path": "/tmp/x.png", "png_options": "fast"}),
        ("gimp_sample_colors", {"target": tid(2)}),
    ]:
        text = text_of(await call(name, arguments))
        for leak in (
            "pydantic",
            "errors.pydantic.dev",
            "Arguments",
            "PngOptions",
            "validation error",
            "Error executing",
        ):
            assert leak not in text, (name, leak, text)


async def test_an_unknown_argument_suggests_the_right_name():
    result = await call("gimp_invert", {"image": iid(1)})
    error = error_of(result)
    assert error["details"]["unknown"] == ["image"]
    assert "item" in error["message"] and "did you mean item" in error["message"]


async def test_a_tool_of_a_disabled_toolset_says_how_to_enable_it():
    with running_fake_bridge({}) as bridge:
        server = build_server(BridgeClient(bridge.endpoint))  # default toolsets: no `formats`
        async with Client(server) as client:
            result = await client.call_tool("gimp_export_as", {"image": iid(1), "path": "/tmp/x.webp"})
    error = error_of(result)
    assert error["code"] == "TOOLSET_DISABLED" and error["details"]["toolset"] == "formats"
    assert "gimp_enable_toolsets" in error["hint"] and "formats" in error["hint"]

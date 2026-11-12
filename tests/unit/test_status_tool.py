from mcp import Client

from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.server import build_server

from .fake_bridge import DEFAULT_SESSION, running_fake_bridge, short_tmpdir


def images_op(params):
    return {
        "images": [
            {
                "id": 1,
                "name": "photo.png",
                "file": "/tmp/photo.png",
                "width": 64,
                "height": 32,
                "dirty": False,
            }
        ]
    }


async def test_status_reports_gimp_version_and_open_images():
    with running_fake_bridge({"session.images": images_op}) as bridge:
        server = build_server(BridgeClient(bridge.endpoint))
        async with Client(server) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert "gimp_status" in tools
            result = await client.call_tool("gimp_status", {})
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert data["connected"] is True
    assert data["gimp_version"] == "3.2.6"
    assert data["gimp_support"] == "supported"
    assert data["plugin_compatibility"] == "match"
    assert data["images"] == [
        {
            "id": "image:1@a1b2c3d4",
            "name": "photo.png",
            "file": "/tmp/photo.png",
            "width": 64,
            "height": 32,
            "dirty": False,
        }
    ]


async def test_status_without_gimp_is_a_structured_error():
    directory = short_tmpdir()
    server = build_server(BridgeClient(BridgeEndpoint.for_socket(directory / "missing.sock")))
    async with Client(server) as client:
        result = await client.call_tool("gimp_status", {})
    directory.rmdir()
    assert result.is_error
    assert result.structured_content is not None
    error = result.structured_content["error"]
    assert error["code"] == "GIMP_NOT_RUNNING"
    assert "hint" in error


async def test_status_flags_a_newer_gimp_as_best_effort():
    session = {**DEFAULT_SESSION, "gimp_version": "3.4.0"}
    with running_fake_bridge({"session.images": lambda p: {"images": []}}, session=session) as bridge:
        server = build_server(BridgeClient(bridge.endpoint))
        async with Client(server) as client:
            result = await client.call_tool("gimp_status", {})
    assert result.structured_content is not None
    assert result.structured_content["gimp_support"] == "best_effort"

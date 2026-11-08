"""Resources, prompts and progress (#62), checked with a real MCP client over the fake bridge."""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

import anyio
import mcp_types as types
from mcp import Client

from gimp_mcp.bridge import BridgeClient, BridgeEndpoint
from gimp_mcp.server import build_server

from .fake_bridge import running_fake_bridge
from .test_inspect_tools import IMAGE
from .tool_harness import SESSION, iid, tool_client

PNG_1PX = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201a1b2d5"
        "0e0000000049454e44ae426082"
    )
).decode()


class Images:
    """Scripted GIMP with a set of open images."""

    def __init__(self, *numbers: int) -> None:
        self.numbers = list(numbers)

    def summary(self, n: int) -> dict:
        return {"id": n, "name": f"img{n}", "file": None, "width": 120, "height": 80, "dirty": False}

    def ops(self) -> dict:
        def create(params):
            n = max(self.numbers, default=0) + 1
            self.numbers.append(n)
            return {**self.summary(n), "xcf_file": None, "layer_count": 1, "displayed": False}

        def close(params):
            self.numbers.remove(params["image"])
            return {}

        return {
            "session.images": lambda p: {"images": [self.summary(n) for n in self.numbers]},
            "image.inspect": lambda p: {**IMAGE, "id": p["image"]},
            "image.preview": lambda p: {
                "png_base64": PNG_1PX,
                "width": 1,
                "height": 1,
                "source_width": 120,
                "source_height": 80,
                "downscaled_for_size": False,
            },
            "image.create": create,
            "image.close": close,
            "image.flip": lambda p: {"width": 120, "height": 80, "dirty": True},
        }


async def test_open_images_layer_trees_and_previews_are_resources():
    images = Images(3, 7)
    async with tool_client(images.ops()) as (client, _):
        listed = {str(r.uri): r for r in (await client.list_resources()).resources}
        assert set(listed) == {
            "gimp://images",
            f"gimp://images/{iid(3)}/layers", f"gimp://images/{iid(3)}/preview",
            f"gimp://images/{iid(7)}/layers", f"gimp://images/{iid(7)}/preview",
        }  # fmt: skip
        assert listed[f"gimp://images/{iid(7)}/preview"].mime_type == "image/png"
        templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
        assert templates == {"gimp://images/{image}/layers", "gimp://images/{image}/preview"}

        overview = (await client.read_resource("gimp://images")).contents[0]
        assert overview.mime_type == "application/json"
        assert [image["id"] for image in json.loads(overview.text)["images"]] == [iid(3), iid(7)]  # type: ignore[union-attr]

        tree = json.loads((await client.read_resource(f"gimp://images/{iid(7)}/layers")).contents[0].text)  # type: ignore[union-attr]
        assert tree["id"] == iid(7) and tree["layers"][0]["children"][0]["id"] == f"item:6@{SESSION}"

        preview = (await client.read_resource(f"gimp://images/{iid(3)}/preview")).contents[0]
        assert preview.mime_type == "image/png"
        assert base64.b64decode(preview.blob).startswith(b"\x89PNG")  # type: ignore[union-attr]


async def test_bad_resource_ids_are_errors_not_crashes():
    async with tool_client(Images(3).ops()) as (client, bridge):
        for uri in ("gimp://images/item:3@a1b2c3d4/layers", "gimp://images/image:3@ffffffff/layers"):
            try:
                await client.read_resource(uri)
            except Exception as error:  # MCPError
                assert "id" in str(error).lower() or "session" in str(error).lower(), error
            else:
                raise AssertionError(f"{uri} was read")
        assert [name for name, _ in bridge.calls] == []


async def test_resources_without_gimp_list_only_the_overview(tmp_path: Path):
    server = build_server(BridgeClient(BridgeEndpoint.for_socket(tmp_path / "none.sock")), toolsets="all")
    async with Client(server) as client:
        assert [str(r.uri) for r in (await client.list_resources()).resources] == ["gimp://images"]


async def test_tools_that_open_or_close_images_notify_resource_list_changes():
    notifications: list[object] = []

    async def on_message(message: object) -> None:
        notifications.append(message)

    images = Images(3)
    with running_fake_bridge(images.ops()) as bridge:
        server = build_server(BridgeClient(BridgeEndpoint.for_socket(bridge.socket_path)), toolsets="all")
        async with Client(server, mode="legacy", message_handler=on_message) as client:
            assert client.session.server_capabilities.resources.list_changed  # type: ignore[union-attr]
            await client.call_tool("gimp_flip_image", {"image": iid(3), "orientation": "vertical"})
            await anyio.sleep(0.05)
            changed = [n for n in notifications if isinstance(n, types.ResourceListChangedNotification)]
            assert changed == []  # the set of images did not change
            created = await client.call_tool("gimp_create_image", {"width": 4, "height": 4})
            await client.call_tool("gimp_close_image", {"image": created.structured_content["id"]})
            await anyio.sleep(0.05)
    changed = [n for n in notifications if isinstance(n, types.ResourceListChangedNotification)]
    assert len(changed) == 2


async def test_listening_clients_get_resource_list_changes():
    async with tool_client(Images(3).ops()) as (client, _), client.listen(resources_list_changed=True) as events:
        await client.call_tool("gimp_create_image", {"width": 4, "height": 4})
        with anyio.fail_after(5):
            async for _event in events:
                break


async def test_prompts_reference_existing_tools():
    async with tool_client({}) as (client, _):
        server_tools = {tool.name for tool in (await client.list_tools()).tools}
        prompts = {prompt.name: prompt for prompt in (await client.list_prompts()).prompts}
        assert {"thumbnail", "remove-background", "photo-touch-up", "batch-export"} <= set(prompts)
        arguments = {
            "thumbnail": {"path": "/photos/cat.jpg", "size": "256"},
            "remove-background": {"path": "/photos/cat.jpg"},
            "photo-touch-up": {"path": "/photos/cat.jpg"},
            "batch-export": {"directory": "/photos", "pattern": "*.jpg", "format": "webp"},
        }
        for name, args in arguments.items():
            missing = {a.name for a in prompts[name].arguments or [] if a.required} - set(args)
            assert not missing, (name, missing)
            result = await client.get_prompt(name, args)
            text = " ".join(m.content.text for m in result.messages)  # type: ignore[union-attr]
            referenced = set(re.findall(r"\bgimp_[a-z_]+\b", text))
            assert referenced, name
            assert referenced <= server_tools, (name, referenced - server_tools)
            for value in args.values():
                assert value in text, (name, value)


async def test_batch_reports_progress_per_file(tmp_path: Path):
    files = []
    for name in ("a.png", "b.png", "c.png"):
        (tmp_path / name).write_bytes(b"x")
        files.append(str(tmp_path / name))
    opened: list[int] = []

    def open_image(params):
        opened.append(len(opened) + 1)
        return {"id": len(opened), "name": "x", "file": params["path"], "xcf_file": None, "width": 4, "height": 4,
                "dirty": False, "layer_count": 1, "displayed": False}  # fmt: skip

    seen: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        seen.append((progress, total, message))

    ops = {**Images().ops(), "image.open": open_image, "image.close": lambda p: {}}
    async with tool_client(ops) as (client, _):
        recipe = [{"tool": "gimp_flip_image", "arguments": {"image": "{image}", "orientation": "vertical"}}]
        result = await client.call_tool(
            "gimp_run_batch", {"files": files, "recipe": recipe}, progress_callback=on_progress
        )
        assert not result.is_error, result.content
    assert [(value, total) for value, total, _ in seen] == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert seen[1][2] and "a.png" in seen[1][2]


async def test_slow_gimp_operations_send_progress_while_waiting():
    def slow(params):
        time.sleep(2.3)
        return {"width": 120, "height": 80, "dirty": True}

    seen: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        seen.append((progress, total, message))

    async with tool_client({**Images(3).ops(), "image.flip": slow}) as (client, _):
        await client.call_tool(
            "gimp_flip_image", {"image": iid(3), "orientation": "vertical"}, progress_callback=on_progress
        )
        quick: list[object] = []
        await client.call_tool(
            "gimp_status",
            {},
            progress_callback=lambda *a: quick.append(a),  # type: ignore[arg-type,return-value]
        )
    values = [value for value, _, _ in seen]
    assert len(values) >= 2 and values == sorted(values) and len(set(values)) == len(values)  # increasing
    assert all(total is None for _, total, _ in seen) and "GIMP" in (seen[0][2] or "")
    assert quick == []  # fast calls send nothing

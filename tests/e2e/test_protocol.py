"""Resources, prompts, progress and cancellation (#62) with a real MCP client (stdio) and a real GIMP."""

from __future__ import annotations

import base64
import io
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import mcp_types as types
from mcp import Client
from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import server_params
from .helpers import call

# ~1 s per 500x500 image on a laptop: slow enough to see progress and to cancel in the middle
SLOW = {"operation": "gegl:bilateral-filter", "parameters": {"blur-radius": 40}, "destructive": True}


@asynccontextmanager
async def legacy_client(gimp: HeadlessGimp, notifications: list[object]):
    async def on_message(message: object) -> None:
        notifications.append(message)

    async with Client(
        server_params(gimp), read_timeout_seconds=120, mode="legacy", message_handler=on_message
    ) as client:
        yield client


def list_changes(notifications: list[object]) -> int:
    return sum(isinstance(n, types.ResourceListChangedNotification) for n in notifications)


async def open_images(client: Client) -> list[str]:
    return [image["id"] for image in (await call(client, "gimp_status"))["images"]]


async def test_resources_follow_open_images(gimp: HeadlessGimp):
    notifications: list[object] = []
    async with legacy_client(gimp, notifications) as client:
        image = (await call(client, "gimp_create_image", width=30, height=20, fill="#ff0000", layer_name="Red"))["id"]
        await anyio.sleep(0.2)
        assert list_changes(notifications) == 1
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        assert {f"gimp://images/{image}/layers", f"gimp://images/{image}/preview"} <= uris

        overview = json.loads((await client.read_resource("gimp://images")).contents[0].text)  # type: ignore[union-attr]
        assert image in [entry["id"] for entry in overview["images"]]
        tree = json.loads((await client.read_resource(f"gimp://images/{image}/layers")).contents[0].text)  # type: ignore[union-attr]
        assert (tree["width"], tree["height"]) == (30, 20) and [n["name"] for n in tree["layers"]] == ["Red"]
        preview = (await client.read_resource(f"gimp://images/{image}/preview")).contents[0]
        with Image.open(io.BytesIO(base64.b64decode(preview.blob))) as img:  # type: ignore[union-attr]
            assert img.format == "PNG" and img.size == (30, 20)
            assert img.convert("RGB").getpixel((15, 10)) == (255, 0, 0)

        await call(client, "gimp_close_image", image=image, discard_changes=True)
        await anyio.sleep(0.2)
        assert list_changes(notifications) == 2
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        assert not any(image in uri for uri in uris)
        try:
            await client.read_resource(f"gimp://images/{image}/layers")
        except Exception as error:
            assert "NOT_FOUND" in str(error) or "does not exist" in str(error), error
        else:
            raise AssertionError("a closed image was read")


async def test_slow_operations_report_progress_and_are_not_cancelled_inside_gimp(gimp: HeadlessGimp):
    notifications: list[object] = []
    async with legacy_client(gimp, notifications) as client:
        image = (await call(client, "gimp_create_image", width=1000, height=1000))["id"]
        layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
        seen: list[tuple[float, float | None, str | None]] = []

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            seen.append((progress, total, message))

        started = time.monotonic()
        done = await client.call_tool("gimp_apply_filter", {"item": layer, **SLOW}, progress_callback=on_progress)
        duration = time.monotonic() - started
        assert not done.is_error, done.content
        assert duration > 2, "the operation is too fast to observe progress"
        values = [value for value, _, _ in seen]
        assert len(values) >= 1 and values == sorted(set(values)) and "GIMP" in (seen[0][2] or "")
        await call(client, "gimp_close_image", image=image, discard_changes=True)

        # cancel the same operation as soon as the first progress arrives
        image = (await call(client, "gimp_create_image", width=1000, height=1000))["id"]
        layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
        assert (await call(client, "gimp_inspect_image", image=image))["dirty"] is False
        scope = anyio.CancelScope()

        async def cancel_on_progress(progress: float, total: float | None, message: str | None) -> None:
            scope.cancel()

        started = time.monotonic()
        with scope:
            await client.call_tool("gimp_apply_filter", {"item": layer, **SLOW}, progress_callback=cancel_on_progress)
        cancelled_after = time.monotonic() - started
        assert scope.cancelled_caught and cancelled_after < duration - 0.5  # the client got control back early
        # GIMP is not interrupted: the next request waits for it, then the filter is there
        assert (await call(client, "gimp_inspect_image", image=image))["dirty"] is True
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_cancelling_a_batch_stops_it_and_closes_its_images(gimp: HeadlessGimp, tmp_path: Path):
    source, out = tmp_path / "in", tmp_path / "out"
    source.mkdir()
    out.mkdir()
    for name in ("a", "b", "c", "d"):
        Image.new("RGB", (500, 500), (200, 30, 30)).save(source / f"{name}.png")
    recipe = [
        {"tool": "gimp_apply_filter", "arguments": {"item": "{layer}", **SLOW}},
        {"tool": "gimp_export_image", "arguments": {"image": "{image}", "path": "{output}"}},
    ]
    notifications: list[object] = []
    async with legacy_client(gimp, notifications) as client:
        before = await open_images(client)
        seen: list[tuple[float, float | None]] = []
        scope = anyio.CancelScope()

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            seen.append((progress, total))
            if progress >= 1:  # the first file is done: cancel during the second one
                scope.cancel()

        with scope:
            await client.call_tool(
                "gimp_run_batch",
                {"directory": str(source), "pattern": "*.png", "recipe": recipe, "output": str(out / "{stem}.png")},
                progress_callback=on_progress,
            )
        assert scope.cancelled_caught and seen[:2] == [(0, 4), (1, 4)]
        # the batch closes what it opened, shielded from the cancellation, as soon as GIMP is free
        with anyio.fail_after(60):
            while await open_images(client) != before:
                await anyio.sleep(0.2)
        assert sorted(p.name for p in out.iterdir()) == ["a.png"]  # nothing after the cancellation
        with Image.open(out / "a.png") as img:
            assert img.size == (500, 500)

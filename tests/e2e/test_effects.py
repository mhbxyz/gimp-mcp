"""GEGL filter catalog (#47) on a real GIMP. Pixels are checked on exported PNGs read with PIL."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


async def export(client, image: str, path: Path) -> Image.Image:
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    with Image.open(path) as img:
        return img.convert("RGBA")


async def new_image(client, width: int, height: int, fill: str) -> tuple[str, str]:
    image = (await call(client, "gimp_create_image", width=width, height=height, fill=fill))["id"]
    layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    return image, layer


async def apply(client, item: str, operation: str, **kwargs: Any) -> dict[str, Any]:
    return await call(client, "gimp_apply_filter", item=item, operation=operation, **kwargs)


def gray(img: Image.Image, x: int, y: int) -> int:
    r, g, b, _a = img.getpixel((x, y))  # type: ignore[misc]
    return round((r + g + b) / 3)


def max_difference(a: Image.Image, b: Image.Image) -> int:
    return max(abs(x - y) for x, y in zip(a.tobytes(), b.tobytes(), strict=True))


def spread(img: Image.Image) -> float:
    return statistics.pstdev(gray(img, x, y) for x in range(img.width) for y in range(img.height))


async def noisy(client, size: int = 48) -> tuple[str, str]:
    image, layer = await new_image(client, size, size, "#808080")
    await apply(
        client, layer, "gegl:noise-rgb", destructive=True, parameters={"red": 0.4, "green": 0.4, "blue": 0.4, "seed": 7}
    )
    return image, layer


async def close(client, *images: str) -> None:
    for image in images:
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_curated_filters_change_pixels_as_expected(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        # unsharp mask: contrast grows at a black/gray edge, flat areas stay
        sharp, layer = await new_image(client, 64, 32, "#808080")
        await call(client, "gimp_select_rectangle", image=sharp, x=0, y=0, width=32, height=32)
        await call(client, "gimp_fill", item=layer, color="#000000")
        await call(client, "gimp_modify_selection", image=sharp, action="none")
        await apply(client, layer, "gegl:unsharp-mask", destructive=True, parameters={"std-dev": 2.0, "scale": 2.0})
        img = await export(client, sharp, tmp_path / "sharp.png")
        assert gray(img, 33, 16) > 128 + 20 and gray(img, 60, 16) == 128

        # noise reduction lowers the spread of a noisy image
        noise, layer = await noisy(client)
        before = spread(await export(client, noise, tmp_path / "noise.png"))
        await apply(client, layer, "gegl:noise-reduction", destructive=True, parameters={"iterations": 6})
        after = spread(await export(client, noise, tmp_path / "denoised.png"))
        assert before > 10 and after < before * 0.8

        # pixelize: every 8x8 block is uniform
        blocks, layer = await noisy(client)
        await apply(client, layer, "gegl:pixelize", destructive=True, parameters={"size-x": 8, "size-y": 8})
        img = await export(client, blocks, tmp_path / "pixelized.png")
        for bx in range(0, 48, 8):
            assert len({img.getpixel((bx + dx, 8 + dy)) for dx in range(8) for dy in range(8)}) == 1

        # drop shadow: a dark, partly opaque shadow appears below-right of an opaque square
        shadow = (await call(client, "gimp_create_image", width=64, height=64, fill="transparent"))["id"]
        square = (await call(client, "gimp_inspect_image", image=shadow))["layers"][0]["id"]
        await call(client, "gimp_select_rectangle", image=shadow, x=16, y=16, width=24, height=24)
        await call(client, "gimp_fill", item=square, color="#ffffff")
        await call(client, "gimp_modify_selection", image=shadow, action="none")
        await apply(client, square, "gegl:dropshadow", parameters={"x": 6.0, "y": 6.0, "radius": 0.0, "opacity": 1.0})
        img = await export(client, shadow, tmp_path / "shadow.png")
        r, g, b, a = img.getpixel((43, 43))  # type: ignore[misc]
        assert a > 128 and max(r, g, b) < 60  # in the shadow, outside the square
        assert img.getpixel((4, 4))[3] == 0 and img.getpixel((20, 20))[:3] == (255, 255, 255)  # type: ignore[index]

        # vignette: corners darker than the center
        vignette, layer = await new_image(client, 64, 64, "#ffffff")
        await apply(client, layer, "gegl:vignette")
        img = await export(client, vignette, tmp_path / "vignette.png")
        assert gray(img, 32, 32) == 255 and gray(img, 0, 0) < 128

        # lens distortion moves pixels away from the center: a vertical line near the border bends
        lens, layer = await new_image(client, 64, 64, "#ffffff")
        await call(client, "gimp_select_rectangle", image=lens, x=52, y=0, width=2, height=64)
        await call(client, "gimp_fill", item=layer, color="#000000")
        await call(client, "gimp_modify_selection", image=lens, action="none")
        straight = await export(client, lens, tmp_path / "straight.png")
        await apply(client, layer, "gegl:lens-distortion", parameters={"main": 60.0})
        bent = await export(client, lens, tmp_path / "bent.png")
        assert gray(bent, 32, 32) == gray(straight, 32, 32) == 255
        assert [gray(bent, x, 0) for x in range(64)] != [gray(straight, x, 0) for x in range(64)]
        await close(client, sharp, noise, blocks, shadow, vignette, lens)


async def test_editable_filters_are_inspected_changed_reordered_merged_and_kept_in_xcf(
    gimp: HeadlessGimp, tmp_path: Path
):
    async with mcp_client(gimp) as client:
        image, layer = await noisy(client)
        original = await export(client, image, tmp_path / "original.png")

        sharpen = await apply(client, layer, "gegl:unsharp-mask", parameters={"std-dev": 3.0}, name="Sharpen")
        assert sharpen["destructive"] is False and sharpen["filter"]["id"]
        assert sharpen["filter"]["parameters"]["std-dev"] == 3.0
        unsharp = sharpen["filter"]["id"]

        changed = await call(
            client,
            "gimp_set_filter",
            item=layer,
            filter=unsharp,
            parameters={"std-dev": 5.0},
            opacity=50,
            mode="multiply",
        )
        assert changed["parameters"]["std-dev"] == 5.0 and changed["opacity"] == 50.0 and changed["mode"] == "multiply"
        hidden = await call(client, "gimp_set_filter", item=layer, filter=unsharp, visible=False)
        assert hidden["visible"] is False
        assert (await export(client, image, tmp_path / "hidden.png")).tobytes() == original.tobytes()
        await call(client, "gimp_set_filter", item=layer, filter=unsharp, visible=True)
        assert (await export(client, image, tmp_path / "shown.png")).tobytes() != original.tobytes()

        pixelize = (await apply(client, layer, "gegl:pixelize", parameters={"size-x": 4, "size-y": 4}))["filter"]["id"]
        stack = await call(client, "gimp_list_filters", item=layer)
        assert [f["id"] for f in stack["filters"]] == [pixelize, unsharp]

        moved = await call(client, "gimp_move_filter", item=layer, filter=unsharp, position=0)
        assert [f["operation"] for f in moved["filters"]] == ["gegl:unsharp-mask", "gegl:pixelize"]
        new_unsharp = moved["recreated"][unsharp]
        kept = await call(client, "gimp_inspect_filter", item=layer, filter=new_unsharp)
        assert (kept["parameters"]["std-dev"], kept["opacity"], kept["mode"], kept["name"]) == (
            5.0,
            50.0,
            "multiply",
            "Sharpen",
        )
        assert (await error(client, "gimp_inspect_filter", item=layer, filter=unsharp))["code"] == "NOT_FOUND"

        # XCF keeps editable filters with their parameters
        xcf = tmp_path / "filters.xcf"
        await call(client, "gimp_save_image", image=image, path=str(xcf))
        reopened = (await call(client, "gimp_open_image", path=str(xcf)))["id"]
        reopened_layer = (await call(client, "gimp_inspect_image", image=reopened))["layers"][0]["id"]
        filters = (await call(client, "gimp_list_filters", item=reopened_layer))["filters"]
        assert [f["operation"] for f in filters] == ["gegl:unsharp-mask", "gegl:pixelize"]
        params = await call(client, "gimp_inspect_filter", item=reopened_layer, filter=filters[1]["id"])
        assert params["parameters"]["size-x"] == 4

        # merge the bottom filter only: pixelize is baked, unsharp stays editable on top
        before_merge = await export(client, image, tmp_path / "before-merge.png")
        merged = await call(client, "gimp_merge_filters", item=layer, up_to=moved["filters"][1]["id"])
        assert merged["merged"] == 1 and [f["operation"] for f in merged["filters"]] == ["gegl:unsharp-mask"]
        # baked pixels are stored in 8 bits, the live stack works in float: values may move by 1
        assert max_difference(await export(client, image, tmp_path / "after-merge.png"), before_merge) <= 1
        everything = await call(client, "gimp_merge_filters", item=layer)
        assert everything["merged"] == 1 and everything["filters"] == []
        assert max_difference(await export(client, image, tmp_path / "merged.png"), before_merge) <= 1
        await close(client, image, reopened)


async def test_filters_respect_the_selection(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        for destructive in (True, False):
            image, layer = await noisy(client)
            original = await export(client, image, tmp_path / "selection-original.png")
            await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=24, height=48)
            result = await apply(
                client, layer, "gegl:pixelize", destructive=destructive, parameters={"size-x": 8, "size-y": 8}
            )
            assert result["restricted_to_selection"] is True
            img = await export(client, image, tmp_path / "selection.png")
            right = [img.getpixel((x, y)) for x in range(24, 48) for y in range(48)]
            assert right == [original.getpixel((x, y)) for x in range(24, 48) for y in range(48)], destructive
            assert img.crop((0, 0, 24, 48)).tobytes() != original.crop((0, 0, 24, 48)).tobytes()
            await close(client, image)


async def test_invalid_filters_are_refused_before_anything_changes(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await noisy(client)
        original = await export(client, image, tmp_path / "invalid-original.png")
        cases = [
            ({"operation": "gegl:pixelize", "parameters": {"size": 4}}, "INVALID_ARGUMENT"),
            ({"operation": "gegl:pixelize", "parameters": {"size-x": 0}}, "INVALID_ARGUMENT"),
            ({"operation": "gegl:pixelize", "parameters": {"norm": "hexagon"}}, "INVALID_ARGUMENT"),
            ({"operation": "gegl:pixelize", "mode": "sparkle"}, "INVALID_ARGUMENT"),
            ({"operation": "gegl:gluas"}, "UNSUPPORTED"),
            ({"operation": "gegl:displace"}, "UNSUPPORTED"),
            ({"operation": "gegl:does-not-exist"}, "NOT_FOUND"),
        ]
        for arguments, code in cases:
            assert (await error(client, "gimp_apply_filter", item=layer, **arguments))["code"] == code, arguments
        group = (await call(client, "gimp_create_group", image=image, name="Group"))["id"]
        refused = await error(client, "gimp_apply_filter", item=group, operation="gegl:pixelize", destructive=True)
        assert refused["code"] == "WRONG_KIND"
        assert (await call(client, "gimp_list_filters", item=layer))["filters"] == []
        assert (await export(client, image, tmp_path / "invalid-after.png")).tobytes() == original.tobytes()
        await close(client, image)


async def test_every_supported_operation_applies_with_its_defaults(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        catalog = (await call(client, "gimp_list_filter_operations"))["operations"]
        assert len(catalog) >= 150
        unsupported = {op["name"]: op["reason"] for op in catalog if not op["supported"]}
        assert {"gegl:gluas", "gegl:displace", "gimp:curves"} <= set(unsupported)
        assert all(unsupported.values())
        image, layer = await new_image(client, 24, 24, "#808080")
        failures = {}
        for op in catalog:
            if not op["supported"]:
                continue
            result = await client.call_tool("gimp_apply_filter", {"item": layer, "operation": op["name"]})
            if result.is_error:
                failures[op["name"]] = result.content[0].text  # type: ignore[union-attr]
                continue
            await call(client, "gimp_remove_filter", item=layer, filter=result.structured_content["filter"]["id"])
        assert failures == {}, "\n".join(f"{k}: {v}" for k, v in failures.items())
        described = await call(client, "gimp_describe_filter_operation", operation="gegl:pixelize")
        kinds = {p["name"]: p["kind"] for p in described["parameters"]}
        assert kinds["size-x"] == "integer" and kinds["norm"] == "choice" and kinds["background"] == "color"
        await close(client, image)

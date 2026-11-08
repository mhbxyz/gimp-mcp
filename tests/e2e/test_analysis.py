"""Analysis tools (#46) on a real GIMP, with pixel values known in advance.

Fixture: a 200x100 red image with a 50x40 blue layer at (100, 20), i.e. 2000 blue
pixels and 18000 red pixels in the composite.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


async def close(client, image: str) -> None:
    await call(client, "gimp_close_image", image=image, discard_changes=True)


RED_LUMINANCE = 130  # relative luminance of sRGB red with ICC D50 coefficients (0.2225), sRGB-encoded


async def fixture(client, tmp_path: Path) -> tuple[str, str]:
    image = (await call(client, "gimp_create_image", width=200, height=100, fill="#ff0000"))["id"]
    blue = await call(
        client, "gimp_create_layer", image=image, name="Blue", width=50, height=40, x=100, y=20, fill="#0000ff"
    )
    await call(client, "gimp_save_image", image=image, path=str(tmp_path / "fixture.xcf"))  # clean from here
    return image, blue["id"]


async def test_histogram_of_composite_layer_region_and_selection(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, blue = await fixture(client, tmp_path)

        composite = await call(client, "gimp_histogram", target=image, channels=["red", "blue"], bins=2)
        red = composite["channels"]["red"]
        assert red["pixel_count"] == 20000
        assert red["mean"] == 255 * 18000 / 20000
        assert (red["min"], red["max"], red["median"]) == (0, 255, 255.0)
        assert red["percentiles"]["5"] == 0 and red["percentiles"]["25"] == 255  # 10% of the pixels are blue
        assert red["histogram"] == [2000, 18000]

        region = await call(client, "gimp_histogram", target=blue, region={"x": 90, "y": 10, "width": 20, "height": 20})
        assert region["region"] == {"x": 100, "y": 20, "width": 10, "height": 10}  # clipped to the layer
        assert region["channels"]["blue"]["pixel_count"] == 100 and region["channels"]["blue"]["mean"] == 255

        luminance = await call(
            client, "gimp_histogram", target=image, channels=["luminance"],
            region={"x": 0, "y": 0, "width": 10, "height": 10},
        )  # fmt: skip
        assert luminance["channels"]["luminance"]["mean"] == RED_LUMINANCE

        await call(client, "gimp_select_rectangle", image=image, x=0, y=0, width=100, height=100)
        selected = await call(client, "gimp_histogram", target=image, channels=["red"], selection_only=True)
        assert selected["channels"]["red"]["pixel_count"] == 10000 and selected["channels"]["red"]["mean"] == 255
        await close(client, image)


async def test_sample_compare_dominant_and_crop_leave_the_image_untouched(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, blue = await fixture(client, tmp_path)
        before = await call(client, "gimp_inspect_image", image=image)
        open_before = len((await call(client, "gimp_status"))["images"])

        samples = await call(
            client, "gimp_sample_colors", target=image, points=[[10, 10], [120, 30], [100, 50]], radius=0
        )
        assert [s["hex"] for s in samples["samples"]] == ["#ff0000", "#0000ff", "#0000ff"]
        averaged = await call(client, "gimp_sample_colors", target=image, points=[[100, 50]], radius=1)
        assert averaged["samples"][0]["rgba"] == [85, 0, 170, 255]  # 3 red columns of 3: x=99 red, 100-101 blue
        assert averaged["samples"][0]["pixels_averaged"] == 9
        on_layer = await call(client, "gimp_sample_colors", target=blue, points=[[100, 20]])
        assert on_layer["samples"][0]["hex"] == "#0000ff"

        dominant = await call(client, "gimp_dominant_colors", target=image, count=3)
        assert [(c["hex"], c["fraction"]) for c in dominant["colors"]] == [("#ff0000", 0.9), ("#0000ff", 0.1)]

        crop = await client.call_tool(
            "gimp_preview_region", {"image": image, "x": 95, "y": 15, "width": 20, "height": 20}
        )
        assert not crop.is_error, crop.content
        assert crop.structured_content["scale"] == 1.0
        png = next(block for block in crop.content if block.type == "image")
        pixels = Image.open(io.BytesIO(base64.b64decode(png.data))).convert("RGBA")
        assert pixels.size == (20, 20)
        assert pixels.getpixel((0, 0)) == (255, 0, 0, 255) and pixels.getpixel((10, 10)) == (0, 0, 255, 255)

        # nothing above changed the image
        status = await call(client, "gimp_status")
        assert next(i for i in status["images"] if i["id"] == image)["dirty"] is False
        assert len(status["images"]) == open_before  # temporary copies are gone
        assert await call(client, "gimp_inspect_image", image=image) == before
        await close(client, image)


async def test_compare_a_checkpoint_with_the_edited_image(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, blue = await fixture(client, tmp_path)
        checkpoint = (await call(client, "gimp_create_checkpoint", image=image))["checkpoint"]
        same = await call(client, "gimp_compare", a=checkpoint, b=image)
        assert same["changed_pixels"] == 0 and same["bounds"] is None

        background = (await call(client, "gimp_inspect_image", image=image))["layers"][-1]["id"]
        await call(client, "gimp_select_rectangle", image=image, x=10, y=10, width=5, height=5)
        await call(client, "gimp_fill", item=background, color="#00ff00")
        result = await client.call_tool("gimp_compare", {"a": checkpoint, "b": image, "preview": True})
        assert not result.is_error, result.content
        diff = result.structured_content
        assert diff["changed_pixels"] == 25
        assert diff["bounds"] == {"x": 10, "y": 10, "width": 5, "height": 5}
        assert diff["max_difference"] == 255
        assert diff["mean_difference"] == 25 * (255 + 255) / (20000 * 4)  # red 255->0, green 0->255
        block = next(block for block in result.content if block.type == "image")
        mask = Image.open(io.BytesIO(base64.b64decode(block.data))).convert("RGB")
        assert mask.size == (200, 100)
        assert mask.getpixel((12, 12)) == (255, 0, 64) and mask.getpixel((50, 50)) != (255, 0, 64)

        sizes = await error(client, "gimp_compare", a=image, b=blue)
        assert sizes["code"] == "INVALID_ARGUMENT" and sizes["details"] == {"a": [200, 100], "b": [50, 40]}
        await close(client, image)


async def test_invalid_analysis_requests_are_refused(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, blue = await fixture(client, tmp_path)
        outside = await error(client, "gimp_sample_colors", target=image, points=[[200, 0]])
        assert outside["code"] == "INVALID_ARGUMENT" and "outcome" not in outside  # a read: nothing to apply
        region = await error(client, "gimp_histogram", target=blue, region={"x": 0, "y": 0, "width": 10, "height": 10})
        assert region["code"] == "INVALID_ARGUMENT"
        empty = await error(client, "gimp_histogram", target=image, selection_only=True)
        assert empty["code"] == "EMPTY_SELECTION"
        crop = await error(client, "gimp_preview_region", image=image, x=190, y=0, width=20, height=10)
        assert crop["code"] == "INVALID_ARGUMENT"
        status = await call(client, "gimp_status")
        assert next(i for i in status["images"] if i["id"] == image)["dirty"] is False
        await close(client, image)

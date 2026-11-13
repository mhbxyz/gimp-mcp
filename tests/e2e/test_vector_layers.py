"""Vector layers and link layers (#57) on a real GIMP 3.2; pixels read with PIL."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error

SQUARE = {"type": "polyline", "points": [[10, 10], [30, 10], [30, 30], [10, 30]], "closed": True}


def px(img: Image.Image, x: int, y: int) -> tuple[int, ...]:
    return img.getpixel((x, y))  # type: ignore[return-value]


async def png(client, image: str, path: Path) -> Image.Image:
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    with Image.open(path) as img:
        return img.convert("RGBA")


def green_file(path: Path, color: tuple[int, int, int] = (0, 255, 0)) -> Path:
    Image.new("RGB", (8, 6), color).save(path)
    return path


async def test_vector_layer_renders_a_path_and_stays_editable(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=40, height=40, fill="#ffffff"))["id"]
        path = await call(client, "gimp_create_path", image=image, strokes=[SQUARE])
        layer = await call(
            client, "gimp_create_vector_layer", path=path["id"], name="Shape",
            fill={"enabled": True, "color": "#ff0000"}, stroke={"enabled": True, "color": "#0000ff", "width": 4},
        )  # fmt: skip
        assert layer["kind"] == "vector" and layer["path"] == path["id"]
        assert layer["fill"]["color"] == "#ff0000ff" and layer["stroke"]["width"] == 4
        img = await png(client, image, tmp_path / "vector.png")
        assert (
            px(img, 20, 20)[:3] == (255, 0, 0)
            and px(img, 20, 10)[:3] == (0, 0, 255)
            and px(img, 2, 2)[:3] == (255,) * 3
        )

        changed = await call(
            client, "gimp_set_vector_layer", item=layer["id"], fill={"color": "#00ff00"},
            stroke={"enabled": False, "cap": "square", "join": "bevel", "dash": [2, 1]},
        )  # fmt: skip
        assert changed["stroke"]["enabled"] is False and changed["stroke"]["join"] == "bevel"
        assert changed["stroke"]["dash"] == [2.0, 1.0]
        img = await png(client, image, tmp_path / "edited.png")
        assert px(img, 20, 20)[:3] == (0, 255, 0) and px(img, 20, 10)[:3] != (0, 0, 255)

        tree = await call(client, "gimp_inspect_image", image=image)
        assert [node["kind"] for node in tree["layers"]] == ["vector", "layer"]
        xcf = tmp_path / "vector.xcf"
        await call(client, "gimp_save_image", image=image, path=str(xcf))
        reopened = (await call(client, "gimp_open_image", path=str(xcf)))["id"]
        again = (await call(client, "gimp_inspect_image", image=reopened))["layers"][0]
        assert again["kind"] == "vector"
        kept = await call(client, "gimp_inspect_vector_layer", item=again["id"])
        assert kept["fill"]["color"] == "#00ff00ff" and kept["stroke"]["join"] == "bevel"
        for each in (image, reopened):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_link_layer_follows_its_file(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=20, height=20, fill="#ffffff"))["id"]
        source = green_file(tmp_path / "green.png")
        linked = await call(client, "gimp_create_link_layer", image=image, path=str(source), name="Logo")
        assert linked["kind"] == "link" and linked["file"] == str(source) and linked["width"] == 8
        img = await png(client, image, tmp_path / "linked.png")
        assert px(img, 2, 2)[:3] == (0, 255, 0)

        other = green_file(tmp_path / "red.png", (255, 0, 0))
        changed = await call(client, "gimp_set_link_layer", item=linked["id"], path=str(other))
        assert changed["file"] == str(other)
        img = await png(client, image, tmp_path / "relinked.png")
        assert px(img, 2, 2)[:3] == (255, 0, 0)

        # the XCF keeps the link; a changed file is read again when the XCF is opened
        xcf = tmp_path / "link.xcf"
        await call(client, "gimp_save_image", image=image, path=str(xcf))
        green_file(other, (0, 0, 255))
        reopened = (await call(client, "gimp_open_image", path=str(xcf)))["id"]
        layer = (await call(client, "gimp_inspect_image", image=reopened))["layers"][0]
        assert layer["kind"] == "link"
        img = await png(client, reopened, tmp_path / "reopened.png")
        assert px(img, 2, 2)[:3] == (0, 0, 255)
        await call(client, "gimp_close_image", image=reopened, discard_changes=True)

        # a missing file: the XCF still opens, the layer keeps its last pixels
        other.unlink()
        missing = (await call(client, "gimp_open_image", path=str(xcf)))["id"]
        layer = (await call(client, "gimp_inspect_image", image=missing))["layers"][0]
        assert layer["kind"] in ("link", "layer")
        img = await png(client, missing, tmp_path / "missing.png")
        assert px(img, 2, 2)[:3] == (255, 0, 0)  # the pixels saved in the XCF
        for each in (image, missing):
            await call(client, "gimp_close_image", image=each, discard_changes=True)
        shutil.rmtree(tmp_path, ignore_errors=True)


async def test_destructive_tools_refuse_vector_and_link_layers(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=40, height=40, fill="#ffffff"))["id"]
        path = await call(client, "gimp_create_path", image=image, strokes=[SQUARE])
        vector = await call(client, "gimp_create_vector_layer", path=path["id"], fill={"color": "#ff0000"})
        link = await call(client, "gimp_create_link_layer", image=image, path=str(green_file(tmp_path / "g.png")))
        for item in (vector["id"], link["id"]):
            assert (await error(client, "gimp_fill", item=item, color="#000000", area="layer"))["code"] == "WRONG_KIND"
            assert (await error(client, "gimp_gaussian_blur", item=item, radius=2))["code"] == "WRONG_KIND"
        kinds = [node["kind"] for node in (await call(client, "gimp_inspect_image", image=image))["layers"]]
        assert kinds == ["link", "vector", "layer"]  # nothing was rasterized
        assert (await error(client, "gimp_inspect_vector_layer", item=link["id"]))["code"] == "WRONG_KIND"
        missing = await client.call_tool("gimp_create_link_layer", {"image": image, "path": str(tmp_path / "none.png")})
        assert missing.is_error
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_gimp_3_2_cannot_set_a_pattern_on_vector_layers(gimp: HeadlessGimp):
    """Fill and stroke patterns can be read (inspection reports them) but GIMP 3.2 has no setter."""
    async with mcp_client(gimp) as client:
        found = await call(client, "gimp_search_procedures", query="gimp-vector-layer-", limit=100)
        names = {p["name"] for p in found["procedures"]}
        assert {"gimp-vector-layer-get-fill-pattern", "gimp-vector-layer-set-fill-color"} <= names
        setters = {name for name in names if name.startswith("gimp-vector-layer-set")}
        assert "gimp-vector-layer-set-stroke-dash-pattern" in setters  # dashes, not a fill pattern
        assert not {"gimp-vector-layer-set-fill-pattern", "gimp-vector-layer-set-stroke-pattern"} & setters

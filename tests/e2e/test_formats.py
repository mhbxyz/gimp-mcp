"""More file formats (#58) on a real GIMP; every file is read back with Pillow or pypdf."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from gimp_mcp import platforms
from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


def px(img: Image.Image, x: int, y: int) -> tuple[int, ...]:
    return img.getpixel((x, y))  # type: ignore[return-value]


async def two_layers(client) -> tuple[str, str, str]:
    """32x24: red background, a 10x8 blue layer at (4, 4)."""
    image = (await call(client, "gimp_create_image", width=32, height=24, fill="#ff0000"))["id"]
    background = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    blue = await call(
        client, "gimp_create_layer", image=image, name="Blue box", width=10, height=8, x=4, y=4, fill="#0000ff"
    )
    return image, background, blue["id"]


@pytest.mark.parametrize(
    ("extension", "options", "lossless", "check"),
    [
        ("webp", {"lossless": True}, True, "exact"),
        ("webp", {"quality": 50.0}, False, "close"),
        ("avif", {"lossless": True}, True, "close"),
        ("bmp", {}, True, "exact"),
        ("gif", {}, None, "exact"),
    ],
)
async def test_raster_exports_are_read_back(gimp: HeadlessGimp, tmp_path: Path, extension, options, lossless, check):
    async with mcp_client(gimp) as client:
        image, _, _ = await two_layers(client)
        path = tmp_path / f"out.{extension}"
        if extension == "avif" and lossless and platforms.CURRENT == "macos":
            # gimp.org's macOS 3.2.6 build: AOM refuses lossless with chroma delta-q (docs/gimp-notes.md)
            failed = await error(client, "gimp_export_as", image=image, path=str(path), options=options)
            assert failed["code"] == "WRITE_FAILED" and "enable_chroma_deltaq" in failed["message"]
            assert not path.exists()
            await call(client, "gimp_close_image", image=image, discard_changes=True)
            return
        result = await call(client, "gimp_export_as", image=image, path=str(path), options=options)
        assert result["lossless"] is lossless and result["layers"] == "flattened" and result["bytes"] > 0
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            assert rgb.size == (32, 24)
            red, blue = px(rgb, 1, 1), px(rgb, 8, 8)
        if check == "exact":
            assert (red, blue) == ((255, 0, 0), (0, 0, 255))
        else:
            assert red[0] > 200 and red[2] < 60 and blue[2] > 200 and blue[0] < 60
        details = await call(client, "gimp_inspect_image", image=image)
        assert len(details["layers"]) == 2  # the image itself is untouched
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_layered_formats_keep_layers_pages_or_sizes(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _, _ = await two_layers(client)
        psd = await call(client, "gimp_export_as", image=image, path=str(tmp_path / "out.psd"))
        assert psd["layers"] == "kept"
        with Image.open(tmp_path / "out.psd") as img:
            assert len(img.layers) == 2  # type: ignore[attr-defined]

        pdf = await call(
            client, "gimp_export_as", image=image, path=str(tmp_path / "pages.pdf"), options={"layers-as-pages": True}
        )
        assert pdf["layers"] == "pages"
        assert len(PdfReader(tmp_path / "pages.pdf").pages) == 2
        flat = await call(client, "gimp_export_as", image=image, path=str(tmp_path / "flat.pdf"))
        assert flat["layers"] == "flattened" and len(PdfReader(tmp_path / "flat.pdf").pages) == 1

        tiff = await call(client, "gimp_export_as", image=image, path=str(tmp_path / "out.tif"))
        assert tiff["layers"] == "pages" and tiff["lossless"] is True
        with Image.open(tmp_path / "out.tif") as img:
            assert img.n_frames == 2  # type: ignore[attr-defined]
            assert px(img.convert("RGB"), 0, 0) == (255, 0, 0)  # first page: the background
            img.seek(1)
            assert img.size == (10, 8) and px(img.convert("RGB"), 0, 0) == (0, 0, 255)

        ico = await call(client, "gimp_export_as", image=image, path=str(tmp_path / "out.ico"))
        assert ico["layers"] == "sizes"
        with Image.open(tmp_path / "out.ico") as img:
            assert len(img.info.get("sizes", ())) == 2  # one icon size per layer

        animated = await call(
            client, "gimp_export_as", image=image, path=str(tmp_path / "anim.gif"), options={"as-animation": True}
        )
        assert animated["layers"] == "frames"
        with Image.open(tmp_path / "anim.gif") as img:
            assert img.n_frames == 2  # type: ignore[attr-defined]
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_open_pdf_pages_svg_size_and_psd_layers(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _, _ = await two_layers(client)
        await call(
            client, "gimp_export_as", image=image, path=str(tmp_path / "pages.pdf"), options={"layers-as-pages": True}
        )
        await call(client, "gimp_export_as", image=image, path=str(tmp_path / "layers.psd"))
        await call(client, "gimp_close_image", image=image, discard_changes=True)

        described = await call(client, "gimp_describe_file_format", extension="pdf", mode="import")
        assert {"pages", "width"} <= {o["name"] for o in described["options"]}
        one_page = await call(
            client, "gimp_open_with_options", path=str(tmp_path / "pages.pdf"), options={"pages": [2]}
        )
        assert one_page["procedure"] == "file-pdf-load" and one_page["layer_count"] == 1
        kept = (await call(client, "gimp_inspect_image", image=one_page["id"]))["layers"][0]
        assert kept["name"] == "2"
        # pages are loaded natively by file-pdf-load (#86), in the order given, the last on top; filtering
        # the pages after loading every page would keep the document's order (page 2 on top)
        reordered = await call(
            client, "gimp_open_with_options", path=str(tmp_path / "pages.pdf"), options={"pages": [2, 1]}
        )
        names = [layer["name"] for layer in (await call(client, "gimp_inspect_image", image=reordered["id"]))["layers"]]
        assert names == ["1", "2"]
        for pages in ([3], [0], []):
            bad_page = await error(
                client, "gimp_open_with_options", path=str(tmp_path / "pages.pdf"), options={"pages": pages}
            )
            assert bad_page["code"] == "INVALID_ARGUMENT", pages
        both = await call(client, "gimp_open_with_options", path=str(tmp_path / "pages.pdf"))
        assert both["layer_count"] == 2

        svg = tmp_path / "shape.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
            '<rect width="40" height="20" fill="#00ff00"/></svg>'
        )
        scaled = await call(client, "gimp_open_with_options", path=str(svg), options={"width": 200, "height": 100})
        assert (scaled["width"], scaled["height"]) == (200, 100)

        psd = await call(client, "gimp_open_with_options", path=str(tmp_path / "layers.psd"))
        assert psd["layer_count"] == 2
        for opened in (one_page, reordered, both, scaled, psd):
            await call(client, "gimp_close_image", image=opened["id"], discard_changes=True)


async def test_export_layers_and_regions(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _background, blue = await two_layers(client)
        out = tmp_path / "layers"
        out.mkdir()
        result = await call(client, "gimp_export_layers", image=image, directory=str(out))
        names = sorted(Path(f["path"]).name for f in result["files"])
        assert names == ["00-Blue box.png", "01-Background.png"]
        with Image.open(out / "00-Blue box.png") as img:
            assert img.size == (10, 8) and px(img.convert("RGB"), 0, 0) == (0, 0, 255)
        uncropped = await call(
            client, "gimp_export_layers", image=image, directory=str(out), items=[blue], crop=False,
            template="full-{name}", extension="webp", options={"lossless": True},
        )  # fmt: skip
        with Image.open(uncropped["files"][0]["path"]) as img:
            assert img.size == (32, 24) and px(img.convert("RGBA"), 1, 1)[3] == 0  # transparent outside the layer
        again = await error(client, "gimp_export_layers", image=image, directory=str(out))
        assert again["code"] == "FILE_EXISTS"

        region = await call(
            client, "gimp_export_region", image=image, path=str(tmp_path / "slice.png"), x=2, y=2, width=6, height=6
        )
        assert region["bytes"] > 0
        with Image.open(tmp_path / "slice.png") as img:
            assert img.size == (6, 6)
            assert px(img.convert("RGB"), 0, 0) == (255, 0, 0) and px(img.convert("RGB"), 5, 5) == (0, 0, 255)
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_invalid_export_requests_write_nothing(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _, _ = await two_layers(client)
        cases = [
            ({"path": str(tmp_path / "a.webp"), "options": {"quality": 500.0}}, "INVALID_ARGUMENT"),
            ({"path": str(tmp_path / "a.webp"), "options": {"nope": 1}}, "INVALID_ARGUMENT"),
            ({"path": str(tmp_path / "a.unknownformat")}, "UNSUPPORTED_FORMAT"),
        ]
        for arguments, code in cases:
            assert (await error(client, "gimp_export_as", image=image, **arguments))["code"] == code, arguments
        outside = await error(
            client, "gimp_export_region", image=image, path=str(tmp_path / "r.png"), x=30, y=0, width=5, height=5
        )
        assert outside["code"] == "INVALID_ARGUMENT"
        assert list(tmp_path.iterdir()) == []
        await call(client, "gimp_close_image", image=image, discard_changes=True)

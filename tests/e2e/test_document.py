"""Guides, sample points, metadata and print size (#60) on a real GIMP; files read with PIL."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


async def test_guides_and_sample_points(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=100, height=50, fill="#336699"))["id"]
        h = await call(client, "gimp_add_guide", image=image, orientation="horizontal", position=20)
        v = await call(client, "gimp_add_guide", image=image, orientation="vertical", position=30)
        listed = await call(client, "gimp_list_guides", image=image)
        assert sorted((g["orientation"], g["position"]) for g in listed["guides"]) == [
            ("horizontal", 20),
            ("vertical", 30),
        ]
        point = await call(client, "gimp_add_sample_point", image=image, x=10, y=10)
        sample = (await call(client, "gimp_list_guides", image=image))["sample_points"][0]
        assert (sample["id"], sample["x"], sample["y"], sample["hex"]) == (point["sample_point"], 10, 10, "#336699")
        await call(client, "gimp_remove_guide", image=image, id=h["guide"])
        await call(client, "gimp_remove_guide", image=image, id=point["sample_point"], kind="sample_point")
        left = await call(client, "gimp_list_guides", image=image)
        assert [g["id"] for g in left["guides"]] == [v["guide"]] and left["sample_points"] == []
        assert (await error(client, "gimp_add_guide", image=image, orientation="horizontal", position=60))[
            "code"
        ] == "INVALID_ARGUMENT"
        assert (await error(client, "gimp_add_sample_point", image=image, x=100, y=0))["code"] == "INVALID_ARGUMENT"
        assert (await error(client, "gimp_remove_guide", image=image, id=999))["code"] == "NOT_FOUND"
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_metadata_is_written_only_when_asked(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=16, height=16, fill="#ffffff"))["id"]
        written = await call(
            client, "gimp_set_metadata", image=image, comment="Made by an agent",
            set={"Exif.Image.Artist": "Ada", "Xmp.dc.title": "Test card", "Iptc.Application2.Keywords": "mcp"},
        )  # fmt: skip
        assert written["exif"]["Exif.Image.Artist"] == "Ada"
        assert "Test card" in (written["xmp"]["Xmp.dc.title"] or "")
        assert written["iptc"]["Iptc.Application2.Keywords"] == "mcp" and written["comment"] == "Made by an agent"

        quiet = tmp_path / "quiet.jpg"
        await call(client, "gimp_export_image", image=image, path=str(quiet))
        with Image.open(quiet) as img:
            assert 315 not in img.getexif() and "comment" not in img.info  # 315 = Artist
        assert b"Test card" not in quiet.read_bytes()

        full = tmp_path / "full.jpg"
        await call(
            client, "gimp_export_image", image=image, path=str(full),
            jpeg_options={"metadata": ["exif", "xmp", "iptc", "comment"]},
        )  # fmt: skip
        with Image.open(full) as img:
            assert img.getexif().get(315) == "Ada"
            assert img.info.get("comment", b"").rstrip(b"\0") == b"Made by an agent"  # GIMP adds a NUL
        assert b"Test card" in full.read_bytes()

        removed = await call(client, "gimp_set_metadata", image=image, remove=["Exif.Image.Artist"], comment="")
        assert "Exif.Image.Artist" not in removed["exif"] and removed["comment"] is None
        bad = await client.call_tool("gimp_set_metadata", {"image": image, "set": {"Artist": "x"}})
        assert bad.is_error
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_resolution_and_print_size(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=600, height=300, fill="#ffffff"))["id"]
        set_res = await call(
            client, "gimp_set_print_size", image=image, x_resolution=150, y_resolution=150, unit="inch"
        )
        assert set_res["print_size"] == {"width": 4.0, "height": 2.0} and set_res["unit"] == "in"
        by_size = await call(client, "gimp_set_print_size", image=image, width=100, height=50, unit="mm")
        assert abs(by_size["resolution"]["x"] - 600 / (100 / 25.4)) < 0.01 and by_size["unit"] == "mm"
        assert by_size["print_size"] == {"width": 100.0, "height": 50.0}
        details = await call(client, "gimp_inspect_image", image=image)
        assert details["unit"] == "mm" and abs(details["resolution"]["x"] - 152.4) < 0.01
        assert (details["width"], details["height"]) == (600, 300)  # pixels untouched
        png = tmp_path / "dpi.png"
        await call(client, "gimp_export_image", image=image, path=str(png))
        with Image.open(png) as img:
            assert abs(img.info["dpi"][0] - 152.4) < 0.1
        too_small = await error(client, "gimp_set_print_size", image=image, width=100000, height=50000, unit="inch")
        assert too_small["code"] == "INVALID_ARGUMENT"
        assert abs((await call(client, "gimp_inspect_image", image=image))["resolution"]["x"] - 152.4) < 0.01
        await call(client, "gimp_close_image", image=image, discard_changes=True)

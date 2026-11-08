"""Paths (#50) on a real GIMP: geometry checked against known values, pixels read with PIL."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error

SQUARE = {"type": "polyline", "points": [[10, 10], [50, 10], [50, 50], [10, 50]], "closed": True}


async def canvas(client, size: int = 64) -> tuple[str, str]:
    image = (await call(client, "gimp_create_image", width=size, height=size, fill="#ffffff"))["id"]
    layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    return image, layer


def rgb(img: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return img.getpixel((x, y))  # type: ignore[return-value]


async def png(client, image: str, path: Path) -> Image.Image:
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    with Image.open(path) as img:
        return img.convert("RGB")


async def test_create_inspect_and_manage_paths(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _ = await canvas(client)
        bezier = {"type": "bezier", "start": [0, 0], "segments": [
            {"to": [30, 0]}, {"to": [30, 30], "control1": [40, 5], "control2": [40, 25]}]}  # fmt: skip
        ellipse = {"type": "ellipse", "center": [32, 32], "radius_x": 20, "radius_y": 10}
        path = await call(client, "gimp_create_path", image=image, name="Shapes", strokes=[SQUARE, bezier, ellipse])
        assert path["name"] == "Shapes" and path["stroke_count"] == 3
        square, curve, oval = path["strokes"]
        assert square["closed"] and square["anchors"] == 4 and math.isclose(square["length"], 160, abs_tol=0.5)
        assert curve["anchors"] == 3 and not curve["closed"]
        assert math.isclose(oval["bounds"]["width"], 40, abs_tol=1) and math.isclose(
            oval["bounds"]["height"], 20, abs_tol=1
        )

        inspected = await call(client, "gimp_inspect_image", image=image)
        assert inspected["paths"] == [{"id": path["id"], "name": "Shapes", "visible": False, "strokes": 3}]
        detailed = await call(client, "gimp_inspect_path", path=path["id"], points=True)
        assert detailed["strokes"][0]["control_points"][1] == [10.0, 10.0]  # anchor of the first point

        point = await call(client, "gimp_path_point_at", path=path["id"], stroke=square["id"], distance=60)
        assert (round(point["x"]), round(point["y"])) == (50, 30)  # 40 along the top, 20 down the right side

        renamed = await call(client, "gimp_set_path", path=path["id"], name="Box", visible=True)
        assert renamed["name"] == "Box" and renamed["visible"] is True
        copy = await call(client, "gimp_duplicate_path", path=path["id"])
        assert copy["id"] != path["id"] and copy["stroke_count"] == 3
        added = await call(client, "gimp_add_path_stroke", path=copy["id"], stroke=SQUARE)
        assert added["stroke_count"] == 4 and added["added_stroke"]

        moved = await call(
            client, "gimp_edit_path_stroke", path=path["id"], stroke=square["id"], action="translate", dx=5, dy=-5
        )
        assert moved["strokes"][0]["bounds"]["x"] == 15 and moved["strokes"][0]["bounds"]["y"] == 5
        scaled = await call(
            client, "gimp_edit_path_stroke", path=path["id"], stroke=square["id"], action="scale", sx=2, sy=2
        )
        assert math.isclose(scaled["strokes"][0]["length"], 320, abs_tol=1)
        flipped = await call(
            client,
            "gimp_edit_path_stroke",
            path=path["id"],
            stroke=curve["id"],
            action="flip",
            orientation="horizontal",
            axis=0,
        )
        assert flipped["strokes"][1]["bounds"]["x"] < 0  # mirrored to the left of x=0
        removed = await call(client, "gimp_edit_path_stroke", path=path["id"], stroke=oval["id"], action="remove")
        assert removed["stroke_count"] == 2

        await call(client, "gimp_delete_path", path=copy["id"])
        assert [p["name"] for p in (await call(client, "gimp_inspect_image", image=image))["paths"]] == ["Box"]
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_paths_selections_stroke_and_fill(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await canvas(client)
        path = await call(client, "gimp_create_path", image=image, strokes=[SQUARE])
        selection = await call(client, "gimp_path_to_selection", path=path["id"])
        assert selection["bounds"] == {"x": 10, "y": 10, "width": 40, "height": 40}

        traced = await call(client, "gimp_selection_to_path", image=image, name="Traced")
        assert traced["name"] == "Traced" and traced["stroke_count"] >= 1
        bounds = traced["strokes"][0]["bounds"]
        assert math.isclose(bounds["x"], 10, abs_tol=1) and math.isclose(bounds["width"], 40, abs_tol=1)
        await call(client, "gimp_modify_selection", image=image, action="none")

        await call(client, "gimp_stroke_path", path=path["id"], item=layer, color="#ff0000", width=4)
        img = await png(client, image, tmp_path / "stroke.png")
        assert rgb(img, 30, 10) == (255, 0, 0) and rgb(img, 30, 30) == (255, 255, 255)

        filled_image, filled_layer = await canvas(client)
        square = await call(client, "gimp_create_path", image=filled_image, strokes=[SQUARE])
        await call(client, "gimp_select_rectangle", image=filled_image, x=0, y=0, width=5, height=5)
        await call(client, "gimp_fill_path", path=square["id"], item=filled_layer, color="#0000ff")
        img = await png(client, filled_image, tmp_path / "fill.png")
        assert rgb(img, 30, 30) == (0, 0, 255) and rgb(img, 5, 5) == (255, 255, 255)
        state = await call(client, "gimp_get_selection", image=filled_image)
        assert state["bounds"] == {"x": 0, "y": 0, "width": 5, "height": 5}  # the user's selection is back

        dashed_image, dashed_layer = await canvas(client)
        line = await call(
            client,
            "gimp_create_path",
            image=dashed_image,
            strokes=[{"type": "polyline", "points": [[0, 32], [64, 32]]}],
        )
        await call(client, "gimp_stroke_path", path=line["id"], item=dashed_layer, width=4, cap="butt", dash=[2, 2])
        img = await png(client, dashed_image, tmp_path / "dashed.png")
        row = [rgb(img, x, 32)[0] < 128 for x in range(64)]
        assert any(row) and not all(row)  # dashes: dark and light runs

        painted_image, painted_layer = await canvas(client)
        line = await call(
            client,
            "gimp_create_path",
            image=painted_image,
            strokes=[{"type": "polyline", "points": [[0, 32], [64, 32]]}],
        )
        result = await call(
            client, "gimp_stroke_path", path=line["id"], item=painted_layer, method="paint", width=10, color="#00ff00"
        )
        assert result["method"] == "paint"
        img = await png(client, painted_image, tmp_path / "painted.png")
        assert rgb(img, 32, 32)[1] > 200 and rgb(img, 32, 32)[0] < 60
        for each in (image, filled_image, dashed_image, painted_image):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_text_outline_svg_and_xcf_round_trips(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _ = await canvas(client, 200)
        text = await call(client, "gimp_create_text_layer", image=image, text="Hi", size=60, x=10, y=10)
        outline = await call(client, "gimp_path_from_text", item=text["id"])
        assert outline["stroke_count"] >= 3  # H and i: outer contours and the dot

        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
            '<path id="tri" d="M 20 20 L 180 20 L 100 160 Z"/></svg>'
        )
        imported = await call(client, "gimp_import_svg_paths", image=image, svg=svg)
        assert len(imported["paths"]) == 1
        triangle = imported["paths"][0]
        assert triangle["strokes"][0]["closed"] and triangle["strokes"][0]["anchors"] == 3
        file_svg = tmp_path / "in.svg"
        file_svg.write_text(svg.replace('id="tri"', 'id="tri2"'))
        from_file = await call(client, "gimp_import_svg_paths", image=image, file=str(file_svg))
        assert len(from_file["paths"]) == 1

        exported = await call(client, "gimp_export_path_svg", image=image, path=triangle["id"])
        root = ET.fromstring(exported["svg"])
        d = next(el for el in root.iter() if el.tag.endswith("path")).attrib["d"]
        numbers = [
            float(v)
            for v in d.replace(",", " ").replace("M", " ").replace("L", " ").replace("C", " ").replace("Z", " ").split()
        ]
        assert {20.0, 180.0, 100.0, 160.0} <= set(numbers)
        out = tmp_path / "all.svg"
        written = await call(client, "gimp_export_path_svg", image=image, file=str(out))
        assert written["svg"] is None and out.read_text().count("<path") == 3

        xcf = tmp_path / "paths.xcf"
        await call(client, "gimp_save_image", image=image, path=str(xcf))
        reopened = (await call(client, "gimp_open_image", path=str(xcf)))["id"]
        paths = (await call(client, "gimp_inspect_image", image=reopened))["paths"]
        assert sorted(p["strokes"] for p in paths) == sorted(
            p["stroke_count"] for p in (outline, triangle, from_file["paths"][0])
        )
        reopened_triangle = next(p for p in paths if p["strokes"] == 1 and p["name"] == triangle["name"])
        again = await call(client, "gimp_inspect_path", path=reopened_triangle["id"])
        assert again["strokes"][0]["length"] == triangle["strokes"][0]["length"]
        for each in (image, reopened):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_invalid_path_requests_change_nothing(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await canvas(client)
        path = await call(client, "gimp_create_path", image=image, strokes=[SQUARE])
        stroke = path["strokes"][0]["id"]
        assert (await error(client, "gimp_edit_path_stroke", path=path["id"], stroke=99, action="close"))[
            "code"
        ] == "NOT_FOUND"
        assert (await error(client, "gimp_path_point_at", path=path["id"], stroke=stroke, distance=1000))[
            "code"
        ] == "INVALID_ARGUMENT"
        assert (await error(client, "gimp_inspect_path", path=layer))["code"] == "WRONG_KIND"
        assert (await error(client, "gimp_selection_to_path", image=image))["code"] == "EMPTY_SELECTION"
        bad_svg = await error(
            client, "gimp_import_svg_paths", image=image, svg="<svg xmlns='http://www.w3.org/2000/svg'/>"
        )
        assert bad_svg["code"] == "UNSUPPORTED_FORMAT"
        open_line = await call(
            client, "gimp_create_path", image=image, strokes=[{"type": "polyline", "points": [[0, 0], [1, 0]]}]
        )
        assert (await error(client, "gimp_fill_path", path=open_line["id"], item=layer))["code"] == "INVALID_ARGUMENT"
        other, other_layer = await canvas(client)
        assert (await error(client, "gimp_stroke_path", path=path["id"], item=other_layer))["code"] == "IMAGE_MISMATCH"
        bad_brush = await error(
            client, "gimp_stroke_path", path=path["id"], item=layer, method="paint", brush="No brush"
        )
        assert bad_brush["code"] == "NOT_FOUND"
        img = await png(client, image, tmp_path / "untouched.png")
        assert img.getextrema() == ((255, 255), (255, 255), (255, 255))  # every pixel is white
        assert len((await call(client, "gimp_inspect_image", image=image))["paths"]) == 2
        for each in (image, other):
            await call(client, "gimp_close_image", image=each, discard_changes=True)

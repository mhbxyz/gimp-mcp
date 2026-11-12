"""Brush painting, gradient fills and bucket fill (#53) on a real GIMP; pixels read with PIL."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error

LINE = [[4, 16], [60, 16]]


def px(img: Image.Image, x: int, y: int) -> tuple[int, ...]:
    return img.getpixel((x, y))  # type: ignore[return-value]


async def canvas(client, fill: str = "#808080", alpha: bool = False) -> tuple[str, str]:
    image = (await call(client, "gimp_create_image", width=64, height=32, fill=fill))["id"]
    layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
    if alpha:
        await call(client, "gimp_set_alpha_channel", item=layer, action="add")
    return image, layer


async def png(client, image: str, path: Path) -> Image.Image:
    await call(client, "gimp_export_image", image=image, path=str(path), overwrite=True)
    with Image.open(path) as img:
        return img.convert("RGBA")


async def stroke(client, expect_error: bool = False, **arguments):
    """gimp_paint_stroke takes an argument named 'tool', like the call() helper: call it directly."""
    result = await client.call_tool("gimp_paint_stroke", arguments)
    assert result.is_error is expect_error, result.content
    return result.structured_content["error"] if expect_error else result.structured_content


async def context_colors(client) -> list:
    """GIMP's own foreground color and brush, read through the PDB (not through the tools under test)."""
    values = []
    for name in ("gimp-context-get-foreground", "gimp-context-get-brush-size"):
        values.append((await call(client, "gimp_call_procedure", name=name, arguments={}))["results"])
    return values


@pytest.mark.parametrize(
    ("tool", "extra", "check"),
    [
        ("paintbrush", {"color": "#ff0000"}, lambda on, off: on[:3] == (255, 0, 0) and off[:3] == (128, 128, 128)),
        (
            "pencil",
            {"color": "#0000ff", "size": 3},
            lambda on, off: on[:3] == (0, 0, 255) and off[:3] == (128, 128, 128),
        ),
        (
            "airbrush",
            {"color": "#ff0000", "pressure": 20},
            lambda on, off: 128 < on[0] < 255 and off[:3] == (128, 128, 128),
        ),
        ("ink", {"color": "#00ff00"}, lambda on, off: on[1] > 200 and on[0] < 60),
        ("burn", {"exposure": 80}, lambda on, off: on[0] < 120 and off[0] == 128),
        ("dodge", {"exposure": 80}, lambda on, off: on[0] > 136 and off[0] == 128),
    ],
)
async def test_paint_tools_change_pixels_on_the_stroke_only(gimp: HeadlessGimp, tmp_path: Path, tool, extra, check):
    async with mcp_client(gimp) as client:
        image, layer = await canvas(client)
        before = await context_colors(client)
        result = await stroke(client, item=layer, tool=tool, points=LINE, **{"size": 6, "hardness": 1.0, **extra})
        assert result["tool"] == tool and result["dynamics"]  # "Dynamics Off", in GIMP's language
        img = await png(client, image, tmp_path / f"{tool}.png")
        assert check(px(img, 32, 16), px(img, 32, 4)), (px(img, 32, 16), px(img, 32, 4))
        assert await context_colors(client) == before  # the user's context is restored
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_eraser_smudge_clone_and_heal(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await canvas(client, alpha=True)
        await stroke(client, item=layer, tool="eraser", points=LINE, size=6)
        img = await png(client, image, tmp_path / "erased.png")
        assert px(img, 32, 16)[3] == 0 and px(img, 32, 4)[3] == 255

        image2, layer2 = await canvas(client)
        await call(client, "gimp_select_rectangle", image=image2, x=32, y=0, width=32, height=32)
        await call(client, "gimp_fill", item=layer2, color="#000000")
        await call(client, "gimp_modify_selection", image=image2, action="none")
        await stroke(client, item=layer2, tool="smudge", points=[[20, 16], [44, 16]], size=10, pressure=90)
        img = await png(client, image2, tmp_path / "smudged.png")
        assert px(img, 36, 16)[0] > 0 and px(img, 36, 4)[0] == 0  # gray dragged into the black half, only there

        # clone: copy a red square from (2, 2) to the stroke around (40, 20)
        image3, layer3 = await canvas(client)
        await call(client, "gimp_select_rectangle", image=image3, x=0, y=0, width=12, height=12)
        await call(client, "gimp_fill", item=layer3, color="#ff0000")
        await call(client, "gimp_modify_selection", image=image3, action="none")
        await stroke(client, item=layer3, tool="clone", points=[[40, 20], [42, 20]], size=4,
            source=layer3, source_x=6, source_y=6,
        )  # fmt: skip
        # the same with the default source (the painted layer) and an offset: (50, 20) from (6, 6)
        await stroke(client, item=layer3, tool="clone", points=[[50, 20], [52, 20]], size=4, source_offset=[-44, -14])
        img = await png(client, image3, tmp_path / "cloned.png")
        assert px(img, 41, 20)[0] > 240 and px(img, 41, 20)[1] < 30 and px(img, 41, 4)[:3] == (128, 128, 128)
        assert px(img, 51, 20)[0] > 240 and px(img, 51, 20)[1] < 30 and px(img, 51, 4)[:3] == (128, 128, 128)
        # heal: a white speck on the gray area disappears, healed from clean gray (heal keeps the
        # surrounding colors, so the result matches the gray around the speck)
        await call(client, "gimp_select_rectangle", image=image3, x=30, y=24, width=2, height=2)
        await call(client, "gimp_fill", item=layer3, color="#ffffff")
        await call(client, "gimp_modify_selection", image=image3, action="none")
        await stroke(client, item=layer3, tool="heal", points=[[30, 24], [32, 25]], size=8, source_offset=[20, 0])
        healed = await png(client, image3, tmp_path / "healed.png")
        assert abs(px(healed, 31, 25)[0] - 128) < 40  # the speck is close to the gray around it
        missing = await stroke(client, expect_error=True, item=layer3, tool="paintbrush", points=LINE, brush="No brush")
        assert missing["code"] == "NOT_FOUND"
        for each in (image, image2, image3):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_gradient_fills(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await canvas(client)
        black_white = [{"left_color": "#000000", "right_color": "#ffffff"}]
        result = await call(client, "gimp_gradient_fill", item=layer, start=[0, 0], end=[63, 0], segments=black_white)
        assert result["gradient"] == "inline"
        img = await png(client, image, tmp_path / "linear.png")
        row = [px(img, x, 10)[0] for x in range(64)]
        assert row[0] < 10 and row[-1] > 245 and row == sorted(row)
        names = {r["name"] for r in (await call(client, "gimp_list_resources", kind="gradient"))["resources"]}
        assert "gimp-mcp temporary gradient" not in names  # the inline gradient was removed

        radial = await call(client, "gimp_create_resource", kind="gradient", name="MCP red to blue")
        await call(
            client,
            "gimp_edit_gradient",
            name=radial["name"],
            segments=[{"left_color": "#ff0000", "right_color": "#0000ff"}],
        )
        await call(
            client,
            "gimp_gradient_fill",
            item=layer,
            start=[32, 16],
            end=[32, 0],
            gradient=radial["name"],
            shape="radial",
        )
        img = await png(client, image, tmp_path / "radial.png")
        assert px(img, 32, 16)[0] > 240 and px(img, 0, 0)[2] > 240  # red center, blue corners

        await call(
            client, "gimp_gradient_fill", item=layer, start=[0, 0], end=[16, 0], segments=black_white, repeat="sawtooth"
        )
        img = await png(client, image, tmp_path / "repeat.png")
        assert px(img, 15, 5)[0] > 200 and px(img, 17, 5)[0] < 60  # the ramp starts again after 16 px
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_bucket_fill_by_color_selection_pattern_and_gradient(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, layer = await canvas(client)
        await call(client, "gimp_select_rectangle", image=image, x=32, y=0, width=32, height=32)
        await call(client, "gimp_fill", item=layer, color="#848484")  # close to the gray on the left
        await call(client, "gimp_modify_selection", image=image, action="none")

        await call(client, "gimp_bucket_fill", item=layer, point=[5, 5], color="#ff0000", threshold=2)
        img = await png(client, image, tmp_path / "strict.png")
        assert px(img, 5, 5)[:3] == (255, 0, 0) and px(img, 40, 5)[:3] == (132, 132, 132)

        image2, layer2 = await canvas(client)
        await call(client, "gimp_select_rectangle", image=image2, x=32, y=0, width=32, height=32)
        await call(client, "gimp_fill", item=layer2, color="#848484")
        await call(client, "gimp_modify_selection", image=image2, action="none")
        await call(client, "gimp_bucket_fill", item=layer2, point=[5, 5], color="#ff0000", threshold=20)
        img = await png(client, image2, tmp_path / "loose.png")
        assert px(img, 40, 5)[:3] == (255, 0, 0)  # within the threshold: filled too

        await call(client, "gimp_select_rectangle", image=image2, x=0, y=0, width=10, height=10)
        pattern = (await call(client, "gimp_list_resources", kind="pattern"))["resources"][0]["name"]
        await call(client, "gimp_bucket_fill", item=layer2, fill="pattern", pattern=pattern)
        await call(
            client, "gimp_bucket_fill", item=layer2, fill="gradient", start=[0, 0], end=[10, 0],
            segments=[{"left_color": "#000000", "right_color": "#ffffff"}],
        )  # fmt: skip
        img = await png(client, image2, tmp_path / "selection.png")
        assert px(img, 1, 5)[0] < 60 and px(img, 9, 5)[0] > 180 and px(img, 20, 20)[:3] == (255, 0, 0)
        state = await call(client, "gimp_get_selection", image=image2)
        assert state["bounds"] == {"x": 0, "y": 0, "width": 10, "height": 10}
        await call(client, "gimp_modify_selection", image=image2, action="none")
        empty = await error(client, "gimp_bucket_fill", item=layer2, fill="color")
        assert empty["code"] == "EMPTY_SELECTION"
        for each in (image, image2):
            await call(client, "gimp_close_image", image=each, discard_changes=True)


async def test_text_and_locks_are_respected(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        image, _layer = await canvas(client)
        text = await call(client, "gimp_create_text_layer", image=image, text="Hi", size=12)
        assert (await stroke(client, expect_error=True, item=text["id"], tool="paintbrush", points=LINE))[
            "code"
        ] == "WRONG_KIND"
        for name, arguments in [
            (
                "gimp_gradient_fill",
                {"start": [0, 0], "end": [10, 0], "segments": [{"left_color": "#000", "right_color": "#fff"}]},
            ),
            ("gimp_bucket_fill", {"point": [1, 1]}),
        ]:
            assert (await error(client, name, item=text["id"], **arguments))["code"] == "WRONG_KIND", name
        assert (await call(client, "gimp_inspect_item", item=text["id"]))["kind"] == "text"
        clone = await client.call_tool(
            "gimp_paint_stroke", {"item": text["id"], "tool": "clone", "points": LINE, "source_offset": [4, 0]}
        )
        assert clone.is_error  # a text layer cannot be painted, even with its own source
        await call(client, "gimp_close_image", image=image, discard_changes=True)

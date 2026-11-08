"""Resources (#52) on a real GIMP with an isolated profile (never the user's)."""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client, server_params
from .helpers import call, error


def px(img: Image.Image, x: int, y: int) -> tuple[int, ...]:
    return img.getpixel((x, y))  # type: ignore[return-value]


def preview(result) -> Image.Image:
    block = next(block for block in result.content if block.type == "image")
    return Image.open(io.BytesIO(base64.b64decode(block.data))).convert("RGBA")


async def test_list_and_inspect_builtin_resources_with_previews(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        for kind in ("brush", "gradient", "pattern", "palette"):
            listed = await call(client, "gimp_list_resources", kind=kind)
            assert listed["total"] > 0 and listed["resources"], kind
        brush = await client.call_tool(
            "gimp_inspect_resource", {"kind": "brush", "name": "2. Hardness 050", "preview": True}
        )
        assert not brush.is_error, brush.content
        details = brush.structured_content
        assert details["generated"] and details["editable"] is False and details["shape"] == "circle"
        mask = preview(brush)
        assert mask.size[0] > 1 and px(mask, mask.width // 2, mask.height // 2)[3] > 0

        # built-in gradient names are translated in GIMP's language: take one from the list
        first = (await call(client, "gimp_list_resources", kind="gradient"))["resources"][0]["name"]
        gradient = await client.call_tool("gimp_inspect_resource", {"kind": "gradient", "name": first, "preview": True})
        assert not gradient.is_error, gradient.content
        assert preview(gradient).size == (256, 32) and gradient.structured_content["segments"]

        palette = await client.call_tool("gimp_inspect_resource", {"kind": "palette", "name": "Web", "preview": True})
        assert len(palette.structured_content["entries"]) == 216
        assert px(preview(palette), 1, 1)[:3] == tuple(
            int(palette.structured_content["entries"][0]["color"][i : i + 2], 16) for i in (1, 3, 5)
        )
        pattern = (await call(client, "gimp_list_resources", kind="pattern"))["resources"][0]["name"]
        shown = await client.call_tool("gimp_inspect_resource", {"kind": "pattern", "name": pattern, "preview": True})
        assert shown.structured_content["width"] == preview(shown).width


async def test_create_edit_duplicate_rename_and_delete_user_resources(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        brush = await call(client, "gimp_create_resource", kind="brush", name="MCP square")
        assert brush["editable"] and brush["generated"]
        edited = await call(
            client, "gimp_edit_brush", name=brush["name"], shape="square", radius=10, hardness=0.5, angle=45,
            aspect_ratio=2, spikes=4, spacing=30,
        )  # fmt: skip
        assert (edited["shape"], edited["radius"], edited["angle"], edited["spacing"]) == ("square", 10, 45, 30)
        assert abs(edited["hardness"] - 0.5) < 1e-6

        gradient = await call(client, "gimp_create_resource", kind="gradient", name="MCP sunset")
        segments = [
            {"left_color": "#ff0000", "right_color": "#ffff00", "right": 0.25},
            {"left_color": "#ffff00", "right_color": "#0000ff", "blending": "curved", "coloring": "hsv-cw"},
        ]
        edited = await call(client, "gimp_edit_gradient", name=gradient["name"], segments=segments)
        assert [s["right"] for s in edited["segments"]] == [0.25, 1.0]
        assert edited["segments"][1]["blending"] == "curved" and edited["segments"][1]["coloring"] == "hsv-cw"
        assert edited["segments"][0]["left_color"] == "#ff0000ff"
        strip = preview(
            await client.call_tool(
                "gimp_inspect_resource", {"kind": "gradient", "name": gradient["name"], "preview": True}
            )
        )
        assert px(strip, 0, 0)[:3] == (255, 0, 0) and px(strip, 255, 0)[:3] == (0, 0, 255)

        palette = await call(client, "gimp_create_resource", kind="palette", name="MCP brand")
        edited = await call(
            client, "gimp_edit_palette", name=palette["name"], columns=2,
            entries=[{"color": "#112233", "name": "Ink"}, {"color": "#ffcc00", "name": "Sun"}],
        )  # fmt: skip
        assert edited["columns"] == 2 and [e["name"] for e in edited["entries"]] == ["Ink", "Sun"]
        assert edited["entries"][1]["color"] == "#ffcc00ff"

        copy = await call(client, "gimp_duplicate_resource", kind="palette", name="Web", new_name="My web")
        assert copy["name"] == "My web" and copy["editable"]
        renamed = await call(client, "gimp_rename_resource", kind="palette", name="My web", new_name="My web 2")
        assert renamed["name"] == "My web 2"
        await call(client, "gimp_delete_resource", kind="palette", name="My web 2")
        assert (await error(client, "gimp_inspect_resource", kind="palette", name="My web 2"))["code"] == "NOT_FOUND"

        for tool, arguments in [
            ("gimp_rename_resource", {"kind": "palette", "name": "Web", "new_name": "x"}),
            ("gimp_delete_resource", {"kind": "brush", "name": "2. Hardness 050"}),
            ("gimp_edit_palette", {"name": "Web", "columns": 3}),
        ]:
            assert (await error(client, tool, **arguments))["code"] == "READ_ONLY", tool
        assert (await call(client, "gimp_inspect_resource", kind="palette", name="Web"))["columns"] != 3
        assert (await client.call_tool("gimp_create_resource", {"kind": "brush", "name": ""})).is_error
        refused = await client.call_tool("gimp_create_resource", {"kind": "pattern", "name": "x"})
        assert refused.is_error


async def test_palettes_are_imported_exported_and_kept_in_the_profile(
    gimp_factory: Callable[..., HeadlessGimp], tmp_path: Path
):
    gimp = gimp_factory()
    act = tmp_path / "brand.act"
    act.write_bytes(bytes([255, 0, 0, 0, 255, 0]) + bytes(762) + bytes([0, 2, 255, 255]))  # Adobe Color Table
    gpl = tmp_path / "team.gpl"
    gpl.write_text("GIMP Palette\nName: Team colors\nColumns: 3\n#\n 10  20  30\tNavy\n200 100  50\tRust\n")
    async with mcp_client(gimp) as client:
        imported = await call(client, "gimp_import_palette", file=str(gpl))
        assert imported["name"] == "Team colors" and [e["color"] for e in imported["entries"]] == [
            "#0a141eff",
            "#c86432ff",
        ]
        adobe = await error(client, "gimp_import_palette", file=str(act))  # only .gpl is reachable from plug-ins
        assert adobe["code"] == "UNSUPPORTED_FORMAT"
        bad = tmp_path / "junk.gpl"
        bad.write_text("not a palette")
        assert (await error(client, "gimp_import_palette", file=str(bad)))["code"] == "UNSUPPORTED_FORMAT"

        exported = await call(client, "gimp_export_palette", name="Team colors", file=str(tmp_path / "out.gpl"))
        text = (tmp_path / "out.gpl").read_text()
        assert exported["format"] == "gpl" and "Name: Team colors" in text and " 10  20  30\tNavy" in text
        for fmt, needle in (("css", "rgb"), ("text", "#"), ("kpl", None)):
            out = tmp_path / f"out.{fmt}"
            await call(client, "gimp_export_palette", name="Team colors", file=str(out), format=fmt)
            assert out.exists() and out.stat().st_size > 0, fmt
            if needle:
                assert needle in out.read_text(errors="replace").lower(), fmt
        assert (await error(client, "gimp_export_palette", name="Team colors", file=str(tmp_path / "out.gpl")))[
            "code"
        ] == "FILE_EXISTS"

        palette = await call(client, "gimp_create_resource", kind="palette", name="Kept")
        # GIMP writes a new resource's file in the profile right away
        assert any(p.name.startswith("Kept") for p in (gimp.config_dir / "palettes").iterdir())
        await call(client, "gimp_edit_palette", name=palette["name"], entries=[{"color": "#123456", "name": "One"}])
    gimp.restart()  # killed (SIGTERM) then started again on the same profile
    async with mcp_client(gimp) as client:
        kept = await call(client, "gimp_inspect_resource", kind="palette", name="Kept")
        assert kept["entries"] == []  # the resource is kept; GIMP writes edits only when it quits normally
        team = await call(client, "gimp_inspect_resource", kind="palette", name="Team colors")
        assert team["editable"] and len(team["entries"]) == 2  # an imported file stays in the profile
    assert (server_params(gimp).env or {})["GIMP_MCP_SOCKET"]  # isolated profile: gimp.config_dir is temporary

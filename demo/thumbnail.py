"""End-to-end demo: build a 1280x720 thumbnail in GIMP through MCP only.

    uv run demo/thumbnail.py                 # starts an isolated headless GIMP
    uv run demo/thumbnail.py --socket PATH   # uses your running GIMP (plug-in installed)

Everything goes through an MCP client talking to `gimp-mcp serve` over stdio;
the script never calls GIMP directly (it only launches a headless GIMP when no
socket is given). Outputs in demo/out/: thumbnail.xcf, thumbnail.png,
thumbnail.jpg, previews/*.png and report.md (every tool call with its
duration, every verification with its result).

The checks are factual (sizes, layer tree, editable text, files on disk,
pixels): no aesthetic judgement is made.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "assets" / "lake-sunset.png"
WIDTH, HEIGHT = 1280, 720
FIRST_TITLE = "Sunset over the Lake"
FINAL_TITLE = "Golden Hour at the Lake"


@dataclass
class CallRecord:
    tool: str
    arguments: dict[str, Any]
    duration_ms: float
    ok: bool
    summary: str


@dataclass
class Check:
    description: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    out_dir: Path
    calls: list[CallRecord] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    previews: list[tuple[str, str]] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def check(self, description: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(description, bool(passed), detail))

    def markdown(self) -> str:
        total = time.monotonic() - self.started
        lines = [
            "# gimp-mcp thumbnail demo report",
            "",
            f"Result: **{'PASS' if self.ok else 'FAIL'}** — {sum(c.passed for c in self.checks)}/"
            f"{len(self.checks)} checks, {len(self.calls)} MCP tool calls, {total:.1f} s.",
            "",
            "Outputs: `thumbnail.xcf` (editable project), `thumbnail.png`, `thumbnail.jpg`.",
            "",
            "## Previews (from `gimp_preview`)",
            "",
        ]
        lines += [f"**{title}**\n\n![{title}]({path})\n" for title, path in self.previews]
        lines += ["## Checks", "", "| # | Check | Result | Detail |", "|---|---|---|---|"]
        for index, check in enumerate(self.checks, 1):
            lines.append(
                f"| {index} | {check.description} | {'pass' if check.passed else '**FAIL**'} | {check.detail} |"
            )
        lines += ["", "## Tool calls", "", "| # | Tool | Arguments | ms | Result |", "|---|---|---|---|---|"]
        for index, call in enumerate(self.calls, 1):
            args = json.dumps(call.arguments, ensure_ascii=False)
            if len(args) > 120:
                args = args[:117] + "..."
            status = call.summary if call.ok else f"**error** {call.summary}"
            lines.append(f"| {index} | `{call.tool}` | `{args}` | {call.duration_ms:.0f} | {status} |")
        lines.append("")
        return "\n".join(lines)


class Session:
    """Thin recorder around the MCP client: every call is timed and logged."""

    def __init__(self, client: Client, report: Report):
        self.client = client
        self.report = report

    async def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        started = time.monotonic()
        result = await self.client.call_tool(tool, arguments)
        duration = (time.monotonic() - started) * 1000
        data = result.structured_content or {}
        if result.is_error:
            error = data.get("error", {})
            self.report.calls.append(
                CallRecord(tool, arguments, duration, False, f"{error.get('code')}: {error.get('message')}")
            )
            raise RuntimeError(f"{tool} failed: {error.get('code')}: {error.get('message')} ({error.get('hint')})")
        self.report.calls.append(CallRecord(tool, arguments, duration, True, summarize(data)))
        return data

    async def preview(self, image: str, name: str, title: str) -> bytes:
        started = time.monotonic()
        result = await self.client.call_tool("gimp_preview", {"image": image, "max_size": 640})
        duration = (time.monotonic() - started) * 1000
        block = next(block for block in result.content if block.type == "image")
        png = base64.b64decode(block.data)
        directory = self.report.out_dir / "previews"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.png").write_bytes(png)
        info = result.structured_content or {}
        self.report.calls.append(
            CallRecord(
                "gimp_preview",
                {"image": image, "max_size": 640},
                duration,
                True,
                f"{info.get('width')}x{info.get('height')} PNG, {info.get('bytes')} bytes",
            )
        )
        self.report.previews.append((title, f"previews/{name}.png"))
        return png


def summarize(data: dict[str, Any]) -> str:
    keys = ("id", "name", "kind", "width", "height", "x", "y", "path", "bytes", "changed", "destructive", "filter")
    parts = [f"{key}={data[key]}" for key in keys if key in data and data[key] is not None]
    return ", ".join(parts)[:160] or "ok"


def tree(image: dict[str, Any]) -> list[Any]:
    def walk(nodes: list[dict[str, Any]]) -> list[Any]:
        return [[n["name"], n["kind"], walk(n.get("children") or [])] for n in nodes]

    return walk(image["layers"])


def find(image: dict[str, Any], name: str) -> dict[str, Any]:
    stack = list(image["layers"])
    while stack:
        node = stack.pop(0)
        if node["name"] == name:
            return node
        stack.extend(node.get("children") or [])
    raise KeyError(name)


def image_size(data: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        return img.size


def pixel(data: bytes, x: int, y: int) -> tuple[int, int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        r, g, b = img.convert("RGB").getpixel((x, y))  # type: ignore[misc]
        return (r, g, b)


EXPECTED_TREE = [
    ["Title", "group", [
        ["Title text", "text", []],
        ["Title shadow", "text", []],
        ["Accent", "layer", []],
        ["Banner", "layer", []],
    ]],
    ["Subject", "group", [["Photo", "layer", []]]],
    ["Backdrop", "group", [["Backdrop photo", "layer", []]]],
    ["Background", "layer", []],
]  # fmt: skip


async def build(gimp: Session, report: Report) -> dict[str, Any]:
    out = report.out_dir
    status = await gimp.call("gimp_status")
    report.check("connected to GIMP through MCP", status["connected"], f"GIMP {status['gimp_version']}")

    image = (await gimp.call("gimp_create_image", width=WIDTH, height=HEIGHT, fill="#0d0b1a"))["id"]
    backdrop = (await gimp.call("gimp_create_group", image=image, name="Backdrop"))["id"]
    subject = (await gimp.call("gimp_create_group", image=image, name="Subject"))["id"]
    title_group = (await gimp.call("gimp_create_group", image=image, name="Title"))["id"]

    # Backdrop: the source, scaled to cover the canvas, blurred and toned down.
    back = await gimp.call("gimp_import_layer", image=image, path=str(SOURCE), name="Backdrop photo", parent=backdrop)
    await gimp.call("gimp_scale_layer", item=back["id"], width=1280, height=800, anchor="top-left")
    await gimp.call("gimp_set_layer_offsets", item=back["id"], x=0, y=-40)
    await gimp.call("gimp_gaussian_blur", item=back["id"], radius=14)
    dim = await gimp.call("gimp_brightness_contrast", item=back["id"], brightness=-35, destructive=False)
    desat = await gimp.call("gimp_hue_saturation", item=back["id"], saturation=-30, destructive=False)
    report.check("backdrop corrections are editable filters", not dim["destructive"] and not desat["destructive"])
    filters_before = [f["operation"] for f in (await gimp.call("gimp_list_filters", item=back["id"]))["filters"]]
    await gimp.preview(image, "01-backdrop", "1. Blurred, darkened backdrop")

    # Subject: the sharp photo, framed by a feathered elliptical mask (vignette).
    photo = await gimp.call("gimp_import_layer", image=image, path=str(SOURCE), name="Photo", parent=subject)
    await gimp.call("gimp_scale_layer", item=photo["id"], width=880, height=550, anchor="top-left")
    await gimp.call("gimp_set_layer_offsets", item=photo["id"], x=200, y=20)
    await gimp.call("gimp_select_ellipse", image=image, x=210, y=30, width=860, height=530, feather=70)
    masked = await gimp.call("gimp_add_layer_mask", item=photo["id"], fill="selection")
    await gimp.call("gimp_modify_selection", image=image, action="none")
    report.check("vignette mask attached to the photo", masked["mask"] is not None)
    await gimp.preview(image, "02-subject", "2. Photo with a feathered vignette mask")

    # Title: banner, accent line, editable title and its blurred shadow.
    banner = await gimp.call("gimp_create_layer", image=image, name="Banner", parent=title_group)
    await gimp.call(
        "gimp_draw_shape",
        item=banner["id"],
        shape="rectangle",
        x=0,
        y=560,
        width=1280,
        height=160,
        fill_color="#000000",
        opacity=70,
    )
    accent = await gimp.call("gimp_create_layer", image=image, name="Accent", parent=title_group)
    await gimp.call("gimp_draw_path", item=accent["id"], points=[[440, 672], [840, 672]], width=5, color="#ffb347")
    shadow = await gimp.call(
        "gimp_create_text_layer",
        image=image,
        text=FIRST_TITLE,
        font="Sans-serif Bold",
        size=64,
        color="#000000",
        x=4,
        y=584,
        justify="center",
        box_width=1280,
        box_height=90,
        parent=title_group,
    )
    await gimp.call("gimp_set_layer_properties", item=shadow["id"], name="Title shadow", opacity=80)
    await gimp.call("gimp_gaussian_blur", item=shadow["id"], radius=4, destructive=False)
    title = await gimp.call(
        "gimp_create_text_layer",
        image=image,
        text=FIRST_TITLE,
        font="Sans-serif Bold",
        size=64,
        color="#ffffff",
        x=0,
        y=580,
        justify="center",
        box_width=1280,
        box_height=90,
        parent=title_group,
    )
    await gimp.call("gimp_set_layer_properties", item=title["id"], name="Title text")
    await gimp.preview(image, "03-title", f"3. Title '{FIRST_TITLE}'")

    # Change of mind: the title stays editable text, so it is simply re-typed.
    for item in (title["id"], shadow["id"]):
        await gimp.call("gimp_set_text", item=item, text=FINAL_TITLE)
    await gimp.call("gimp_set_text", item=title["id"], color="#fff3d6")
    props = await gimp.call("gimp_inspect_text", item=title["id"])
    report.check("title is still editable text after the edit", props["text"] == FINAL_TITLE, props["text"])
    final_png = await gimp.preview(image, "04-final", f"4. Final composition, title '{FINAL_TITLE}'")

    details = await gimp.call("gimp_inspect_image", image=image)
    report.check("canvas is 1280x720", (details["width"], details["height"]) == (WIDTH, HEIGHT))
    report.check("layer tree matches the plan", tree(details) == EXPECTED_TREE, json.dumps(tree(details)))
    report.check("preview keeps the 16:9 proportions", image_size(final_png) == (640, 360))
    banner_pixel = pixel(final_png, 20, 330)
    report.check("banner darkens the bottom band", max(banner_pixel) < 80, str(banner_pixel))

    # Save the editable project, reopen it and compare.
    xcf = out / "thumbnail.xcf"
    await gimp.call("gimp_save_image", image=image, path=str(xcf), overwrite=True)
    await gimp.call("gimp_close_image", image=image)
    reopened = (await gimp.call("gimp_open_image", path=str(xcf)))["id"]
    again = await gimp.call("gimp_inspect_image", image=reopened)
    report.check("XCF reopens with the same layer tree", tree(again) == EXPECTED_TREE)
    title_again = await gimp.call("gimp_inspect_text", item=find(again, "Title text")["id"])
    report.check(
        "title is editable text in the reopened XCF",
        find(again, "Title text")["kind"] == "text" and title_again["text"] == FINAL_TITLE,
        f"{title_again['font']} {title_again['size']}{title_again['size_unit']} {title_again['color']}",
    )
    backdrop_filters = await gimp.call("gimp_list_filters", item=find(again, "Backdrop photo")["id"])
    filters_after = [f["operation"] for f in backdrop_filters["filters"]]
    report.check(
        "editable filters survive the XCF round trip",
        filters_after == filters_before
        and sorted(filters_after) == ["gimp:brightness-contrast", "gimp:hue-saturation"],
        json.dumps(filters_after),
    )

    # Final files.
    png, jpg = out / "thumbnail.png", out / "thumbnail.jpg"
    await gimp.call("gimp_export_image", image=reopened, path=str(png), overwrite=True)
    await gimp.call("gimp_export_image", image=reopened, path=str(jpg), overwrite=True, jpeg_options={"quality": 88})
    await gimp.call("gimp_close_image", image=reopened)
    for path in (png, jpg):
        size = image_size(path.read_bytes())
        report.check(
            f"{path.name} is a {WIDTH}x{HEIGHT} image", size == (WIDTH, HEIGHT), f"{path.stat().st_size} bytes"
        )
    return {"xcf": xcf, "png": png, "jpg": jpg}


async def run_demo(out_dir: Path, server: StdioServerParameters) -> Report:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = Report(out_dir=out_dir)
    try:
        async with Client(server, read_timeout_seconds=180) as client:
            await build(Session(client, report), report)
    except Exception as exc:  # the report must show what failed
        report.check("demo ran to completion", False, f"{type(exc).__name__}: {exc}")
    (out_dir / "report.md").write_text(report.markdown(), encoding="utf-8")
    return report


def server_parameters(socket_path: str) -> StdioServerParameters:
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "LANG", "XDG_RUNTIME_DIR")}
    env["GIMP_MCP_SOCKET"] = socket_path
    return StdioServerParameters(command=sys.executable, args=["-m", "gimp_mcp", "serve"], env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "out"), help="output directory (default: demo/out)")
    parser.add_argument("--socket", help="bridge socket of a running GIMP (default: start a headless GIMP)")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if args.socket:
        report = asyncio.run(run_demo(out, server_parameters(args.socket)))
    else:
        from gimp_mcp.headless import HeadlessGimp

        print("starting an isolated headless GIMP...", file=sys.stderr)
        with HeadlessGimp() as gimp:
            report = asyncio.run(run_demo(out, server_parameters(str(gimp.socket_path))))
    status = "PASS" if report.ok else "FAIL"
    print(
        f"{status}: {sum(c.passed for c in report.checks)}/{len(report.checks)} checks, "
        f"{len(report.calls)} tool calls. Report: {out / 'report.md'}",
        file=sys.stderr,
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

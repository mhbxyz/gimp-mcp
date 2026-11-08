"""What every demo scenario shares: an MCP client on `gimp-mcp serve`, a recorder of every tool call
and every check, previews, and the Markdown report.

A scenario (``demo/scenarios/<name>.py``) declares a ``SCENARIO``: its toolsets, the assets it uses
(each with a source and a license in ``demo/assets/LICENSES.md``), the outputs it writes, its steps
and factual checks, and the natural-language prompt of its agent version (``demo/video/record.sh``).
Checks are factual (sizes, layer trees, editable text, pixels, files read with Pillow): no aesthetic
judgement is made.
"""

from __future__ import annotations

import base64
import importlib
import io
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

DEMO = Path(__file__).resolve().parent
ASSETS = DEMO / "assets"
LICENSES = ASSETS / "LICENSES.md"
SCENARIOS = DEMO / "scenarios"


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
    title: str
    out_dir: Path
    outputs: tuple[str, ...] = ()
    calls: list[CallRecord] = field(default_factory=list)
    listed_tools: set[str] = field(default_factory=set)
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
            f"# gimp-mcp demo: {self.title}",
            "",
            f"Result: **{'PASS' if self.ok else 'FAIL'}** — {sum(c.passed for c in self.checks)}/"
            f"{len(self.checks)} checks, {len(self.calls)} MCP tool calls, {total:.1f} s.",
            "",
        ]
        if self.outputs:
            lines += ["Outputs: " + ", ".join(f"`{name}`" for name in self.outputs) + ".", ""]
        if self.previews:
            lines += ["## Previews (from `gimp_preview`)", ""]
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

    @property
    def out(self) -> Path:
        return self.report.out_dir

    async def call(self, tool: str, /, **arguments: Any) -> dict[str, Any]:
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

    async def error(self, tool: str, /, **arguments: Any) -> dict[str, Any]:
        """A call that must be refused: returns its error (code, message, hint)."""
        started = time.monotonic()
        result = await self.client.call_tool(tool, arguments)
        duration = (time.monotonic() - started) * 1000
        data = result.structured_content or {}
        if not result.is_error:
            self.report.calls.append(CallRecord(tool, arguments, duration, True, summarize(data)))
            raise RuntimeError(f"{tool} unexpectedly succeeded")
        error = data.get("error", {})
        summary = f"refused as expected: {error.get('code')}"
        self.report.calls.append(CallRecord(tool, arguments, duration, True, summary))
        return error

    async def preview(self, image: str, name: str, title: str, max_size: int = 640) -> bytes:
        started = time.monotonic()
        result = await self.client.call_tool("gimp_preview", {"image": image, "max_size": max_size})
        duration = (time.monotonic() - started) * 1000
        block = next(block for block in result.content if block.type == "image")
        png = base64.b64decode(block.data)
        directory = self.out / "previews"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.png").write_bytes(png)
        info = result.structured_content or {}
        self.report.calls.append(
            CallRecord(
                "gimp_preview",
                {"image": image, "max_size": max_size},
                duration,
                True,
                f"{info.get('width')}x{info.get('height')} PNG, {info.get('bytes')} bytes",
            )
        )
        self.report.previews.append((title, f"previews/{name}.png"))
        return png


Steps = Callable[[Session, Report], Awaitable[None]]


@dataclass(frozen=True)
class Scenario:
    """One demo: what it needs, what it does, what it proves, and how an agent is asked to do it."""

    name: str
    title: str
    toolsets: tuple[str, ...]  # only these are listed by the server (docs/toolsets.md)
    assets: tuple[str, ...]  # files of demo/assets, each listed in LICENSES.md
    outputs: tuple[str, ...]  # files the scripted version writes in its output directory
    steps: Steps  # the scripted version: MCP calls and factual checks
    prompt: str  # the agent version: one natural-language request, on files in ~/inputs
    agent_output: str  # the file the agent version exports into ~/out (the recording waits for it)
    # the agent version's ~/inputs when it is not simply the assets (e.g. a generated scan: the asset it
    # comes from would give the answer away)
    make_agent_inputs: Callable[[Path], None] | None = None
    # the agent version's checks, on ~/out and its final answer, and a correct result made without GIMP
    # (tests/unit/test_evals.py proves the checks with it); both make it a task of the evaluation suite
    agent_check: Callable[[Path, str], list[Check]] | None = None
    agent_reference: Callable[[Path, Path], None] | None = None


def agent_inputs(scenario: Scenario, directory: Path) -> list[Path]:
    """Fill ``directory`` (the agent's ~/inputs): the scenario's assets, or what it generates instead."""
    import shutil

    directory.mkdir(parents=True, exist_ok=True)
    if scenario.make_agent_inputs is not None:
        scenario.make_agent_inputs(directory)
    else:
        for name in scenario.assets:
            shutil.copyfile(asset(name), directory / name)
    return sorted(path for path in directory.rglob("*") if path.is_file())


def asset(name: str) -> Path:
    return ASSETS / name


def asset_licenses() -> dict[str, tuple[str, str]]:
    """``demo/assets/LICENSES.md``: file → (source, license), from its table."""
    rows = {}
    for line in LICENSES.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and (match := re.fullmatch(r"`([^`]+)`", cells[0])):
            rows[match.group(1)] = (cells[1], cells[2])
    return rows


def check_assets(scenario: Scenario, licenses: dict[str, tuple[str, str]] | None = None) -> None:
    """Refuse a scenario whose assets are missing or have no recorded source and license."""
    licenses = asset_licenses() if licenses is None else licenses
    for name in scenario.assets:
        if not asset(name).is_file():
            raise ValueError(f"scenario {scenario.name!r}: asset {name!r} is not in demo/assets")
        source, license_ = licenses.get(name, ("", ""))
        if not source or not license_:
            raise ValueError(f"scenario {scenario.name!r}: asset {name!r} has no source and license in LICENSES.md")


def scenario_names() -> list[str]:
    """Scenario names use hyphens (`old-photo-restoration`); their modules, underscores."""
    return sorted(path.stem.replace("_", "-") for path in SCENARIOS.glob("*.py") if not path.stem.startswith("_"))


def load(name: str) -> Scenario:
    if name not in scenario_names():
        raise KeyError(f"unknown scenario {name!r} (known: {', '.join(scenario_names())})")
    scenario = importlib.import_module(f"demo.scenarios.{name.replace('-', '_')}").SCENARIO
    assert isinstance(scenario, Scenario) and scenario.name == name, name
    return scenario


async def run_scenario(scenario: Scenario, out_dir: Path, server: StdioServerParameters) -> Report:
    """Run the scripted version against ``server`` and write ``report.md`` in ``out_dir``."""
    check_assets(scenario)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = Report(title=scenario.title, out_dir=out_dir, outputs=scenario.outputs)
    toolsets = ",".join(scenario.toolsets)
    server = server.model_copy(update={"env": {**(server.env or {}), "GIMP_MCP_TOOLSETS": toolsets}})
    try:
        async with Client(server, read_timeout_seconds=180) as client:
            report.listed_tools = {tool.name for tool in (await client.list_tools()).tools}
            await scenario.steps(Session(client, report), report)
            called = {call.tool for call in report.calls}
            report.check(
                f"the server listed only the scenario's toolsets ({len(report.listed_tools)} tools)",
                called <= report.listed_tools and "gimp_call_procedure" not in report.listed_tools,
                toolsets,
            )
    except Exception as exc:  # the report must show what failed
        report.check("scenario ran to completion", False, f"{type(exc).__name__}: {exc}")
    (out_dir / "report.md").write_text(report.markdown(), encoding="utf-8")
    return report


def publish(name: str, out_dir: Path, docs: Path) -> Path:
    """Copy a scenario's report and previews into ``docs/demos/<name>/`` (previews as WebP, to keep
    the repository small), for its documentation page."""
    from PIL import Image

    target = docs / "demos" / name
    (target / "previews").mkdir(parents=True, exist_ok=True)
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    # paths of this machine become repository paths
    report = report.replace(str(out_dir), f"demo/out/{name}").replace(str(ASSETS), "demo/assets")
    for png in sorted((out_dir / "previews").glob("*.png")):
        with Image.open(png) as img:
            img.save(target / "previews" / f"{png.stem}.webp", quality=80, method=6)
        report = report.replace(f"previews/{png.name}", f"previews/{png.stem}.webp")
    (target / "report.md").write_text(report, encoding="utf-8")
    return target


def server_parameters(socket_path: str, token_path: str | None = None) -> StdioServerParameters:
    """`gimp-mcp serve` from this checkout, on the bridge of a running or headless GIMP."""
    keep = ("PATH", "HOME", "LANG", "XDG_RUNTIME_DIR", "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
            "USERNAME", "TEMP", "TMP")  # fmt: skip
    env = {key: value for key, value in os.environ.items() if key in keep}
    env["GIMP_MCP_SOCKET"] = socket_path
    if token_path:
        env["GIMP_MCP_TOKEN_FILE"] = token_path
    return StdioServerParameters(command=sys.executable, args=["-m", "gimp_mcp", "serve"], env=env)


# Helpers for checks.


def summarize(data: dict[str, Any]) -> str:
    keys = ("id", "name", "kind", "width", "height", "x", "y", "path", "bytes", "changed", "destructive", "filter")
    parts = [f"{key}={data[key]}" for key in keys if key in data and data[key] is not None]
    return ", ".join(parts)[:160] or "ok"


def tree(image: dict[str, Any]) -> list[Any]:
    """The layer tree as nested [name, kind, children] lists."""

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

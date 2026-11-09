"""Agent evaluation suite (#106): a real Claude Code session per task, in an isolated container, with
only the gimp server and the default toolsets; the outputs are then checked here, by facts.

Host side: build or pick the package, generate each task's inputs, run the container, parse its
stream-json transcript (tool calls, errors returned, tokens, duration), check the outputs, write a
report and compare it with the committed baseline (docs/evals/baseline.json).

The OAuth token reaches the container only through the CLAUDE_CODE_OAUTH_TOKEN environment variable;
every file the run writes is scanned for it, and a run that finds it deletes that file and fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
BASELINE = ROOT / "docs" / "evals" / "baseline.json"
IMAGE = "gimp-mcp-evals"
DOCKERFILE_DIR = ROOT / "demo" / "video"  # the same pinned Arch + GIMP 3.2 image as the demo videos
DISALLOWED = ("Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Read", "Glob", "Grep", "Task")
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"


@dataclass
class Check:
    description: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Task:
    """A natural-language request on generated inputs, and factual checks of what it produces."""

    name: str
    toolsets: tuple[str, ...]  # the toolsets a solution needs (beyond `core`); optional ones must be enabled
    prompt: str
    make_inputs: Callable[[Path], None]  # writes the inputs into ~/inputs (deterministic)
    check: Callable[[Path, str], list[Check]]  # (~/out, the agent's final answer) -> checks
    reference: Callable[[Path, Path], None]  # a correct result made with Pillow: (inputs, out) -> files
    out_dirs: tuple[str, ...] = ()  # directories created in ~/out beforehand (tools never create them)


@dataclass
class Metrics:
    """What the transcript says about a session."""

    model: str = ""
    gimp_tools: int = 0  # tools the gimp server listed at start
    tool_calls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # gimp tool results flagged as errors: "tool: text"
    other_tools: list[str] = field(default_factory=list)  # non-gimp tools the agent tried (all refused)
    duration_s: float = 0.0
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    answer: str = ""
    finished: bool = False  # a final "result" message was received without error
    stop_reason: str = ""


def parse_transcript(lines: list[str]) -> Metrics:
    """Claude Code's `--output-format stream-json --verbose` lines → Metrics."""
    metrics = Metrics()
    names: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            metrics.model = event.get("model", "")
            metrics.gimp_tools = sum(1 for tool in event.get("tools", []) if str(tool).startswith("mcp__gimp__"))
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = str(block.get("name", ""))
                    names[block.get("id", "")] = name
                    if name.startswith("mcp__gimp__"):
                        metrics.tool_calls.append(name.removeprefix("mcp__gimp__"))
                    else:
                        metrics.other_tools.append(name)
        elif kind == "user":
            content = event.get("message", {}).get("content", [])
            for block in content if isinstance(content, list) else []:
                name = names.get(block.get("tool_use_id", ""), "?")
                if block.get("type") == "tool_result" and block.get("is_error") and name.startswith("mcp__gimp__"):
                    text = block.get("content")
                    if isinstance(text, list):
                        text = " ".join(str(part.get("text", "")) for part in text if isinstance(part, dict))
                    metrics.errors.append(f"{name.removeprefix('mcp__gimp__')}: {str(text)[:200]}")
        elif kind == "result":
            usage = event.get("usage", {})
            metrics.duration_s = round(event.get("duration_ms", 0) / 1000, 1)
            metrics.turns = event.get("num_turns", 0)
            metrics.input_tokens = usage.get("input_tokens", 0)
            metrics.output_tokens = usage.get("output_tokens", 0)
            metrics.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            metrics.cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
            metrics.cost_usd = round(event.get("total_cost_usd", 0.0), 4)
            metrics.answer = str(event.get("result", ""))
            metrics.finished = event.get("subtype") == "success" and not event.get("is_error", False)
            metrics.stop_reason = str(event.get("subtype", ""))
            if event.get("is_error"):  # e.g. the account's usage limit: the reason is the result text
                metrics.stop_reason += f" with an error: {str(event.get('result', ''))[:160]}"
    return metrics


@dataclass
class TaskResult:
    task: str
    passed: bool
    checks: list[Check]
    metrics: Metrics


def oauth_token(env: dict[str, str] | None = None) -> str:
    """CLAUDE_CODE_OAUTH_TOKEN, else the local Claude Code login (~/.claude/.credentials.json)."""
    env = dict(os.environ) if env is None else env
    if env.get(TOKEN_ENV):
        return env[TOKEN_ENV]
    credentials = Path(env.get("HOME", str(Path.home()))) / ".claude" / ".credentials.json"
    try:
        return json.loads(credentials.read_text(encoding="utf-8"))["claudeAiOauth"]["accessToken"]
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit(f"no {TOKEN_ENV} and no Claude Code login to read it from ({type(error).__name__})") from None


def docker_command(
    name: str, work: Path, package: str, claude_bin: str, budget_usd: float, model: str | None
) -> list[str]:
    """The container of one task. The token is passed by name only (`-e VAR`): its value stays in the
    environment of the docker process and never appears on a command line."""
    command = [
        "docker", "run", "--rm", "--name", name, "--init",
        "-e", TOKEN_ENV, "-e", "DISABLE_AUTOUPDATER=1", "-e", "DISABLE_TELEMETRY=1",
        "-e", f"EVAL_PACKAGE={package}", "-e", f"EVAL_BUDGET_USD={budget_usd}",
        "-e", f"EVAL_DISALLOWED={' '.join(DISALLOWED)}",
        "-v", f"{EVALS / 'agent.sh'}:/evals/agent.sh:ro",
        "-v", f"{work / 'inputs'}:/home/demo/inputs:ro",
        "-v", f"{work / 'out'}:/home/demo/out",
        "-v", f"{work / 'run'}:/run/eval",
        "-v", f"{claude_bin}:/usr/local/bin/claude:ro",
    ]  # fmt: skip
    if model:
        command += ["-e", f"EVAL_MODEL={model}"]
    if package.endswith(".whl"):
        command += [
            "-v",
            f"{package}:/wheels/{Path(package).name}:ro",
            "-e",
            f"EVAL_PACKAGE=/wheels/{Path(package).name}",
        ]
    return [*command, IMAGE, "/evals/agent.sh"]


def scrub(directory: Path, token: str) -> list[Path]:
    """Files under ``directory`` that contain the token: deleted, and returned (the run then fails)."""
    leaked = []
    needle = token.encode()
    for path in directory.rglob("*"):
        if path.is_file() and needle in path.read_bytes():
            path.unlink()
            leaked.append(path)
    return leaked


def prepare_work(task: Task, work: Path, prompt_file: Path) -> None:
    """Inputs, prompt and empty output directories of one task under ``work``. The directories the
    agent writes to (``out``, ``run``) are opened to every user: the container runs as uid 1000,
    which is not the host user on a CI runner (uid 1001). Inputs stay closed (mounted read-only)."""
    for sub in ("inputs", "out", "run"):
        (work / sub).mkdir(parents=True, exist_ok=True)
    task.make_inputs(work / "inputs")
    writable = [work / "out", work / "run"]
    for directory in task.out_dirs:
        (work / "out" / directory).mkdir(parents=True, exist_ok=True)
        writable.append(work / "out" / directory)
    shutil.copyfile(prompt_file, work / "run" / "prompt.txt")
    for path in writable:
        path.chmod(0o777)  # chmod, not mkdir(mode=): the umask does not apply


def run_task(task: Task, work: Path, package: str, prompt_file: Path, token: str, *, claude_bin: str,
             budget_usd: float, model: str | None, timeout_s: int) -> TaskResult:  # fmt: skip
    """Run ``task`` in a fresh container and check what it produced."""
    prepare_work(task, work, prompt_file)
    env = {**os.environ, TOKEN_ENV: token}
    name = f"gimp-mcp-eval-{task.name}-{os.getpid()}"
    started = time.monotonic()
    try:
        proc = subprocess.run(docker_command(name, work, package, claude_bin, budget_usd, model), env=env,
                              capture_output=True, text=True, timeout=timeout_s)  # fmt: skip
        (work / "run" / "container.log").write_text(proc.stdout[-20000:] + proc.stderr[-20000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        (work / "run" / "container.log").write_text(f"timeout after {timeout_s} s", encoding="utf-8")
    leaked = scrub(work, token)
    transcript = work / "run" / "transcript.jsonl"
    lines = transcript.read_text(encoding="utf-8").splitlines() if transcript.exists() else []
    metrics = parse_transcript(lines)
    if not metrics.duration_s:
        metrics.duration_s = round(time.monotonic() - started, 1)
    checks = [Check("the session finished", metrics.finished, metrics.stop_reason or "no result message")]
    checks += task.check(work / "out", metrics.answer)
    if leaked:
        checks.append(Check("the token appears in no file", False, ", ".join(str(p) for p in leaked)))
    return TaskResult(task.name, all(c.passed for c in checks), checks, metrics)


def recheck(task: Task, work: Path) -> TaskResult:
    """The checks of ``task`` again, on the outputs and transcript of an earlier run (no agent runs):
    for when a check is corrected."""
    transcript = work / "run" / "transcript.jsonl"
    lines = transcript.read_text(encoding="utf-8").splitlines() if transcript.exists() else []
    metrics = parse_transcript(lines)
    checks = [Check("the session finished", metrics.finished, metrics.stop_reason or "no result message")]
    checks += task.check(work / "out", metrics.answer)
    return TaskResult(task.name, all(c.passed for c in checks), checks, metrics)


# Reports.


def report_json(results: list[TaskResult], meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": meta,
        "tasks": {
            r.task: {
                "passed": r.passed,
                "checks": [asdict(c) for c in r.checks],
                "tool_calls": len(r.metrics.tool_calls),
                "tools": r.metrics.tool_calls,
                "errors": r.metrics.errors,
                "other_tools": r.metrics.other_tools,
                "duration_s": r.metrics.duration_s,
                "turns": r.metrics.turns,
                "input_tokens": r.metrics.input_tokens,
                "output_tokens": r.metrics.output_tokens,
                "cache_read_tokens": r.metrics.cache_read_tokens,
                "cache_creation_tokens": r.metrics.cache_creation_tokens,
                "model": r.metrics.model,
                "gimp_tools": r.metrics.gimp_tools,
                "date": meta.get("date", ""),
                "package": meta.get("package", ""),
            }
            for r in results
        },
    }


def regressions(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Tasks that passed in the baseline and fail now (tasks absent from either side are not compared)."""
    found = []
    for name, now in current["tasks"].items():
        before = baseline.get("tasks", {}).get(name)
        if before and before["passed"] and not now["passed"]:
            failed = [c["description"] for c in now["checks"] if not c["passed"]]
            found.append(f"{name}: passed in the baseline, fails now ({'; '.join(failed)})")
    return found


def report_markdown(data: dict[str, Any], found: list[str] | None = None) -> str:
    meta, tasks = data["meta"], data["tasks"]
    passed = sum(t["passed"] for t in tasks.values())
    lines = [
        "# gimp-mcp agent evaluation",
        "",
        f"**{passed}/{len(tasks)} tasks passed** — gimp-mcp {meta.get('package', '?')}, "
        f"model {meta.get('model', '?')}, {meta.get('date', '?')}. Default toolsets; the agent enables others itself.",
        "",
    ]
    if meta.get("updated"):
        lines += [f"Updated since: {meta['updated']} (each task's package and date are in the JSON).", ""]
    if found is not None:
        lines += ["## Compared with the baseline", ""]
        lines += [f"* **regression** {item}" for item in found] or ["No regression."]
        lines.append("")
    lines += [
        "| Task | Result | Tool calls | Errors returned | Duration | Tokens in / out (cache read) |",
        "|---|---|---|---|---|---|",
    ]
    for name, t in tasks.items():
        result = "pass" if t["passed"] else "**FAIL**"
        tokens = f"{t['input_tokens']} / {t['output_tokens']} ({t['cache_read_tokens']})"
        lines.append(
            f"| `{name}` | {result} | {t['tool_calls']} | {len(t['errors'])} | {t['duration_s']} s | {tokens} |"
        )
    lines += ["", "## Details", ""]
    for name, t in tasks.items():
        lines.append(f"### `{name}`")
        lines.append("")
        for c in t["checks"]:
            detail = f" ({c['detail']})" if c["detail"] else ""
            lines.append(f"* {'pass' if c['passed'] else '**FAIL**'}: {c['description']}{detail}")
        if t["errors"]:
            lines += [f"* error returned: `{e}`" for e in t["errors"]]
        lines.append(f"* gimp tools: {', '.join(t['tools']) or 'none'}")
        if t.get("other_tools"):
            lines.append(f"* other tools tried: {', '.join(t['other_tools'])}")
        lines.append("")
    return "\n".join(lines)

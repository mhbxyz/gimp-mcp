"""Run the agent evaluation suite (docs/evals/README.md).

    uv run evals/run.py --list
    uv run evals/run.py resize-export             # one task (during development: one at a time)
    uv run evals/run.py --all                     # every task, compared with docs/evals/baseline.json
    uv run evals/run.py --all --write-baseline    # also replace the baseline
    uv run evals/run.py --all --package gimp-mcp==0.5.0   # the published package instead of this checkout
    uv run evals/run.py --recheck evals/out/<date>         # checks again on a run's outputs (no agent)

Each task runs a real Claude Code session in a fresh container (demo/video's image: pinned Arch,
GIMP 3.2) with only the gimp server, the default toolsets and no shell or file tools, then its
outputs are checked here. Reports go to evals/out/<date>/ (report.md, report.json, per-task files and
transcripts). Exit code 1 when a task that passed in the baseline fails (a regression).

The token: CLAUDE_CODE_OAUTH_TOKEN, else the local Claude Code login. It is passed to the container
as an environment variable only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `evals` as a package, from a checkout

from evals.harness import (
    BASELINE,
    DOCKERFILE_DIR,
    EVALS,
    IMAGE,
    ROOT,
    oauth_token,
    recheck,
    regressions,
    report_json,
    report_markdown,
    run_task,
)
from evals.tasks import TASKS, by_name


def build_wheel(directory: Path) -> str:
    subprocess.run(["uv", "build", "--quiet", "--wheel", "--out-dir", str(directory)], cwd=ROOT, check=True)
    return str(next(directory.glob("*.whl")).resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tasks", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--package", help="pip requirement to evaluate (default: a wheel of this checkout)")
    parser.add_argument("--model", help="Claude model (default: Claude Code's default)")
    parser.add_argument("--budget-usd", type=float, default=2.0, help="spending limit per task (default 2)")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per task (default 900)")
    parser.add_argument("--out", help="report directory (default: evals/out/<date>)")
    parser.add_argument("--write-baseline", action="store_true", help="write docs/evals/baseline.{json,md}")
    parser.add_argument("--recheck", metavar="DIR", help="run the checks again on an earlier run's outputs")
    args = parser.parse_args()
    if args.recheck:
        return report(Path(args.recheck).resolve(), None, args)
    if args.list:
        for task in TASKS:
            print(f"{task.name}\t{','.join(task.toolsets)}")
        return 0
    tasks = list(TASKS) if args.all else [by_name(name) for name in args.tasks]
    if not tasks:
        parser.error("give task names, or --all")
    claude = shutil.which("claude")
    if claude is None:
        raise SystemExit("the `claude` CLI is needed on this machine (it is mounted read-only into the container)")
    token = oauth_token()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out or EVALS / "out" / stamp).resolve()
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["docker", "build", "-q", "-t", IMAGE, str(DOCKERFILE_DIR)], check=True, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory() as scratch:
        package = args.package or build_wheel(Path(scratch) / "dist")
        results = []
        for task in tasks:
            print(f"{task.name}...", file=sys.stderr)
            prompt = Path(scratch) / f"{task.name}.txt"
            prompt.write_text(task.prompt, encoding="utf-8")
            result = run_task(task, out / task.name, package, prompt, token, claude_bin=str(Path(claude).resolve()),
                              budget_usd=args.budget_usd, model=args.model, timeout_s=args.timeout)  # fmt: skip
            print(f"  {'PASS' if result.passed else 'FAIL'}: {len(result.metrics.tool_calls)} tool calls, "
                  f"{len(result.metrics.errors)} errors, {result.metrics.duration_s} s", file=sys.stderr)  # fmt: skip
            results.append(result)
    return report(out, results, args)


def report(out: Path, results: list | None, args: argparse.Namespace) -> int:
    """Write report.{json,md} for ``results`` (None: recheck the tasks found in ``out``)."""
    meta_package = args.package
    if results is None:
        previous = json.loads((out / "report.json").read_text(encoding="utf-8"))
        results = [recheck(by_name(name), out / name) for name in previous["tasks"]]
        meta_package = previous["meta"]["package"]
    from gimp_mcp import __version__

    model = next((r.metrics.model for r in results if r.metrics.model), args.model or "?")
    meta = {"package": meta_package or f"{__version__} (checkout)", "model": model,
            "date": datetime.date.today().isoformat()}  # fmt: skip
    data = report_json(results, meta)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
    found = regressions(baseline, data) if baseline else None
    (out / "report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (out / "report.md").write_text(report_markdown(data, found), encoding="utf-8")
    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        BASELINE.with_suffix(".md").write_text(report_markdown(data), encoding="utf-8")
    passed = sum(r.passed for r in results)
    print(f"{passed}/{len(results)} tasks passed. Report: {out / 'report.md'}", file=sys.stderr)
    for item in found or []:
        print(f"REGRESSION {item}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

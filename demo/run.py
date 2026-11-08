"""Run demo scenarios through MCP only (demo/README.md lists them).

    uv run demo/run.py thumbnail            # one scenario, in an isolated headless GIMP
    uv run demo/run.py --all                # every scenario
    uv run demo/run.py thumbnail --socket PATH   # your running GIMP (plug-in installed)
    uv run demo/run.py --list               # names and titles
    uv run demo/run.py --prompt thumbnail   # the agent version's prompt (demo/video/record.sh)

Each scenario writes its outputs, previews and report.md (every tool call with its duration, every
check with its result) in demo/out/<scenario>/. Exit code 0 when every check of every scenario passed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `demo` as a package, from a checkout

from demo.harness import DEMO, Report, load, run_scenario, scenario_names, server_parameters


async def run_all(names: list[str], out: Path, socket: str | None, token: str | None) -> list[Report]:
    reports = []
    for name in names:
        scenario = load(name)
        print(f"{name}: {scenario.title}...", file=sys.stderr)
        if socket:
            report = await run_scenario(scenario, out / name, server_parameters(socket, token))
        else:
            from gimp_mcp.headless import HeadlessGimp

            with HeadlessGimp() as gimp:  # a fresh GIMP per scenario: no state leaks between them
                params = server_parameters(str(gimp.socket_path), str(gimp.token_path))
                report = await run_scenario(scenario, out / name, params)
        status = "PASS" if report.ok else "FAIL"
        print(f"  {status}: {sum(c.passed for c in report.checks)}/{len(report.checks)} checks, "
              f"{len(report.calls)} tool calls. Report: {out / name / 'report.md'}", file=sys.stderr)  # fmt: skip
        reports.append(report)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", nargs="*", help="scenario names (see --list)")
    parser.add_argument("--all", action="store_true", help="run every scenario")
    parser.add_argument("--list", action="store_true", help="list the scenarios")
    parser.add_argument("--prompt", metavar="SCENARIO", help="print the agent version's prompt")
    parser.add_argument("--agent-output", metavar="SCENARIO", help="print the file the agent version exports")
    parser.add_argument("--out", default=str(DEMO / "out"), help="output directory (default: demo/out)")
    parser.add_argument("--socket", help="bridge of a running GIMP (default: start a headless GIMP)")
    parser.add_argument("--token-file", help="its token file, when not next to the socket (Windows pipes)")
    args = parser.parse_args()
    if args.list:
        for name in scenario_names():
            print(f"{name}\t{load(name).title}")
        return 0
    if args.prompt:
        print(load(args.prompt).prompt)
        return 0
    if args.agent_output:
        print(load(args.agent_output).agent_output)
        return 0
    names = scenario_names() if args.all else args.scenarios
    if not names:
        parser.error("give scenario names, or --all")
    for name in names:
        load(name)  # unknown names fail before anything runs
    reports = asyncio.run(run_all(names, Path(args.out).resolve(), args.socket, args.token_file))
    return 0 if all(report.ok for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())

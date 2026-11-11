"""The public API contract snapshot (#116).

    uv run scripts/api_contract.py write              # regenerate docs/api/contract.json
    uv run scripts/api_contract.py check --base REF   # classify changes against REF's snapshot

``check`` fails when a breaking change lacks a CHANGELOG 'Breaking' entry (and, from 1.0 on, a new
major version). CI runs it on every pull request against the base branch.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from gimp_mcp.contract import collect_contract, compare, render_contract, verdict

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "docs/api/contract.json"


def _version(pyproject: str) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if not match:
        raise SystemExit("no version in pyproject.toml")
    return match.group(1)


def _show(ref: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def write() -> int:
    (ROOT / SNAPSHOT).write_text(render_contract(collect_contract()), encoding="utf-8", newline="\n")
    print(f"wrote {SNAPSHOT}")
    return 0


def check(base: str) -> int:
    old_text = _show(base, SNAPSHOT)
    if old_text is None:
        print(f"{base} has no {SNAPSHOT}: nothing to compare")
        return 0
    old_pyproject = _show(base, "pyproject.toml") or ""
    changes = compare(json.loads(old_text), collect_contract())
    result = verdict(
        changes,
        (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
        _version(old_pyproject),
        _version((ROOT / "pyproject.toml").read_text(encoding="utf-8")),
    )
    lines = [f"## API contract against {base}", ""]
    if not changes:
        lines.append("No change to the public API.")
    for change in sorted(changes, key=lambda c: (c.kind != "breaking", c.where)):
        lines.append(f"- **{change.kind}** — {change.where}: {change.what}")
    lines += ["", *(f"**Refused:** {reason}" for reason in result.reasons)]
    report = "\n".join(lines).rstrip() + "\n"
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("write", help=f"regenerate {SNAPSHOT}")
    check_parser = sub.add_parser("check", help="classify the changes against a base revision")
    check_parser.add_argument("--base", required=True, help="git revision holding the previous snapshot")
    args = parser.parse_args(argv)
    return write() if args.command == "write" else check(args.base)


if __name__ == "__main__":
    sys.exit(main())

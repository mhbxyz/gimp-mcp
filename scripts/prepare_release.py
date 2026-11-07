#!/usr/bin/env python3
"""Prepare a release pull request in one command.

    scripts/prepare_release.py 0.2.0            # bump, roll the CHANGELOG, branch, commit, push, open the PR
    scripts/prepare_release.py 0.2.0 --no-git   # only edit the files (to review them first)

What it does:
1. checks that the new version is a greater X.Y.Z than the current one;
2. sets `version` in pyproject.toml (the only place it is written) and refreshes uv.lock;
3. turns `## [Unreleased]` of CHANGELOG.md into `## [X.Y.Z] - <date>` (refusing an
   empty section) and adds the link reference;
4. creates the branch `release/vX.Y.Z`, commits "Release vX.Y.Z", pushes it and opens a
   pull request titled "Release vX.Y.Z" whose body is the CHANGELOG section.

Merging that PR (squash) creates the tag and starts the release workflow
(.github/workflows/tag-release.yml). Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY = "https://github.com/mhbxyz/gimp-mcp"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class ReleaseError(Exception):
    pass


def check_version(current: str, new: str) -> None:
    match_new, match_current = SEMVER.match(new), SEMVER.match(current)
    if match_new is None:
        raise ReleaseError(f"{new!r} is not a X.Y.Z version")
    if match_current is not None and tuple(map(int, match_new.groups())) <= tuple(map(int, match_current.groups())):
        raise ReleaseError(f"{new} is not greater than the current version {current}")


def current_version(pyproject: str) -> str:
    match = re.search(r'(?m)^version = "([^"]+)"', pyproject)
    if match is None:
        raise ReleaseError("no version in pyproject.toml")
    return match.group(1)


def bump_pyproject(text: str, version: str) -> str:
    # only the first `version = "..."`, which is in [project]
    return re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', text, count=1)


def bump_server_json(text: str, version: str) -> str:
    """MCP registry metadata: the server and its PyPI package carry the release version."""
    import json

    data = json.loads(text)
    data["version"] = version
    for package in data.get("packages", []):
        package["version"] = version
    return json.dumps(data, indent=2) + "\n"


def roll_changelog(text: str, version: str, date: str) -> str:
    marker = "## [Unreleased]"
    start = text.find(marker)
    if start == -1:
        raise ReleaseError("CHANGELOG.md has no '## [Unreleased]' section")
    body_start = start + len(marker)
    following = re.search(r"(?m)^## \[", text[body_start:])
    body_end = body_start + following.start() if following else len(text)
    body = text[body_start:body_end].strip()
    if not body:
        raise ReleaseError("the Unreleased section is empty: nothing to release")
    rolled = text[:start] + f"{marker}\n\n## [{version}] - {date}\n\n{body}\n\n" + text[body_end:].lstrip("\n")
    link = f"[{version}]: {REPOSITORY}/releases/tag/v{version}\n"
    first_link = re.search(r"(?m)^\[\d+\.\d+\.\d+\]: ", rolled)
    if first_link:
        rolled = rolled[: first_link.start()] + link + rolled[first_link.start() :]
    else:
        rolled = rolled.rstrip("\n") + "\n\n" + link
    return rolled


def section(changelog: str, version: str) -> str:
    match = re.search(rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[\d)", changelog)
    return match.group(1).strip() if match else ""


def run(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReleaseError(f"`{' '.join(args)}` failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help="new version, X.Y.Z")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    parser.add_argument("--no-git", action="store_true", help="only edit the files")
    parser.add_argument("--no-lock", action="store_true", help="do not refresh uv.lock")
    args = parser.parse_args(argv)
    root = Path(args.root)
    title = f"Release v{args.version}"
    try:
        pyproject_path, changelog_path = root / "pyproject.toml", root / "CHANGELOG.md"
        pyproject = pyproject_path.read_text(encoding="utf-8")
        check_version(current_version(pyproject), args.version)
        changelog = roll_changelog(changelog_path.read_text(encoding="utf-8"), args.version, args.date)
        if not args.no_git:
            if run(["git", "status", "--porcelain"], root):
                raise ReleaseError("the working tree is not clean")
            run(["git", "switch", "-c", f"release/v{args.version}"], root)
        pyproject_path.write_text(bump_pyproject(pyproject, args.version), encoding="utf-8")
        server_path = root / "server.json"
        if server_path.exists():
            server_path.write_text(bump_server_json(server_path.read_text(encoding="utf-8"), args.version), "utf-8")
        changelog_path.write_text(changelog, encoding="utf-8")
        if not args.no_lock:
            run(["uv", "lock", "--quiet"], root)
        if not args.no_git:
            run(["git", "add", "pyproject.toml", "CHANGELOG.md", "uv.lock", "server.json"], root)
            run(["git", "commit", "--quiet", "-m", title], root)
            run(["git", "push", "--quiet", "-u", "origin", f"release/v{args.version}"], root)
            url = run(
                ["gh", "pr", "create", "--title", title, "--body", section(changelog, args.version), "--base", "main"],
                root,
            )
            print(f"Opened {url}", file=sys.stderr)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"{title}: files updated. Merging a PR titled '{title}' tags the release.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

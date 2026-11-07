#!/usr/bin/env python3
"""Check that an index serves exactly the artifacts we built (same names, same SHA-256).

    python scripts/verify_published.py testpypi 0.2.0 dist/SHA256SUMS
    python scripts/verify_published.py pypi 0.2.0 dist/SHA256SUMS
    python scripts/verify_published.py testpypi 0.2.0 dist/SHA256SUMS --download wheels/
    python scripts/verify_published.py pypi 0.2.0 dist/SHA256SUMS --once   # no waiting (re-runs)

With --download, the verified files are saved (to install them without
resolving dependencies against TestPyPI, which anyone can upload to).

Polls the index JSON API for a while (uploads take time to appear). Exit code
0 when every file matches, 1 otherwise. Standard library only.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

INDEXES = {"pypi": "https://pypi.org", "testpypi": "https://test.pypi.org"}
PROJECT = "gimp-mcp"


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.strip().removeprefix("./").removeprefix("*")] = digest
    return sums


def compare(release: dict, sums: dict[str, str]) -> list[str]:
    published = {item["filename"]: item["digests"]["sha256"] for item in release.get("urls", [])}
    problems = []
    for name, digest in sorted(sums.items()):
        if name not in published:
            problems.append(f"{name}: missing from the index")
        elif published[name] != digest:
            problems.append(f"{name}: differs (index {published[name]}, built {digest})")
    problems += [f"{name}: on the index but not built here" for name in sorted(set(published) - set(sums))]
    return problems


def fetch(index: str, version: str) -> dict | None:
    url = f"{INDEXES[index]}/pypi/{PROJECT}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def download(release: dict, directory: str) -> None:
    import os

    os.makedirs(directory, exist_ok=True)
    for item in release["urls"]:
        urllib.request.urlretrieve(item["url"], os.path.join(directory, item["filename"]))


def main(argv: list[str]) -> int:
    attempts = 30
    if "--once" in argv:  # single check, no waiting: exit 0 identical, 1 different, 2 absent
        argv = [a for a in argv if a != "--once"]
        attempts = 1
    target = None
    if "--download" in argv:
        position = argv.index("--download")
        target = argv[position + 1]
        argv = argv[:position] + argv[position + 2 :]
    index, version, sums_path = argv
    with open(sums_path, encoding="utf-8") as handle:
        sums = parse_sums(handle.read())
    problems = ["not published yet"]
    for attempt in range(attempts):
        release = fetch(index, version)
        if release is None and attempts == 1:
            return 2
        if release is not None:
            problems = compare(release, sums)
            if not problems:
                print(f"{PROJECT} {version} on {index}: {len(sums)} file(s) match the build", file=sys.stderr)
                if target:
                    download(release, target)
                return 0
        if attempt + 1 < attempts:
            time.sleep(10)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

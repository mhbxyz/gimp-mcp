"""The newest GIMP gimp.org publishes (stable or development release), for the gimp-next CI job (#121).

    python3 ci/newest_gimp.py macos-arm64 [manifest.json]

Prints ``version=…``, ``url=…`` and ``sha256=…`` lines (for $GITHUB_OUTPUT), read from gimp.org's release
manifest (https://www.gimp.org/gimp_versions.json), which carries the SHA-256 of every download.
Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from typing import Any

MANIFEST = "https://www.gimp.org/gimp_versions.json"
PLATFORMS = {"macos-arm64": ("macos", "-arm64.dmg"), "windows": ("windows", "-setup.exe")}


def version_key(version: str) -> tuple[tuple[int, ...], int, int]:
    """Order releases: 3.2.0-RC3 < 3.2.0 < 3.2.8 < 3.3.2."""
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-RC(\d+))?", version)
    if not match:
        return ((), 0, 0)
    numbers = tuple(int(part) for part in match.group(1).split("."))
    candidate = match.group(2)
    return (numbers, 0 if candidate else 1, int(candidate or 0))


def newest(manifest: dict[str, Any], platform: str) -> dict[str, str]:
    folder, suffix = PLATFORMS[platform]
    releases = [*manifest.get("STABLE", []), *manifest.get("DEVELOPMENT", [])]
    for release in sorted(releases, key=lambda r: version_key(r["version"]), reverse=True):
        for download in release.get(folder, []):
            name = download.get("filename", "")
            if name.startswith("gimp-") and name.endswith(suffix) and download.get("sha256"):
                major_minor = ".".join(release["version"].split(".")[:2])
                return {
                    "version": release["version"],
                    "url": f"https://download.gimp.org/gimp/v{major_minor}/{folder}/{name}",
                    "sha256": download["sha256"],
                }
    raise SystemExit(f"no {platform} download in the manifest")


def main(argv: list[str]) -> int:
    platform = argv[0]
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as handle:
            manifest = json.load(handle)
    else:
        with urllib.request.urlopen(MANIFEST, timeout=60) as response:
            manifest = json.load(response)
    for key, value in newest(manifest, platform).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

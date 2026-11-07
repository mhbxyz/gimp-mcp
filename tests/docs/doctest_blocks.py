"""Extract the documentation blocks that are executed or checked by tests.

A block is marked by an HTML comment on the line before its fence:

    <!-- doctest: quickstart -->        shell commands executed in a clean container (ci/run-doctests.sh)
    <!-- snippet: claude-desktop -->    a client configuration compared with what `gimp-mcp setup` writes
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs" / "clients").glob("*.md"))]
_BLOCK = re.compile(r"<!-- (doctest|snippet): ([\w.-]+) -->\n```(\w+)\n(.*?)\n```", re.S)


@dataclass(frozen=True)
class Block:
    kind: str
    name: str
    language: str
    body: str
    page: Path


def blocks(kind: str | None = None) -> list[Block]:
    found = []
    for page in PAGES:
        for match in _BLOCK.finditer(page.read_text(encoding="utf-8")):
            block = Block(match.group(1), match.group(2), match.group(3), match.group(4), page)
            if kind is None or block.kind == kind:
                found.append(block)
    return found


def commands(block: Block) -> list[str]:
    """Shell commands of a block (comments and blank lines dropped)."""
    return [line for line in block.body.splitlines() if line.strip() and not line.lstrip().startswith("#")]

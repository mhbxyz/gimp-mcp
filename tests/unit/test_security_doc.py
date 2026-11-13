"""docs/security.md links every mitigation to a test (#122): the links must lead somewhere."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "security.md").read_text(encoding="utf-8")


def test_every_test_named_in_the_security_model_exists():
    current = None
    missing = []
    for match in re.finditer(r"`((?:e2e/)?test_[a-z0-9_]+\.py)?::(test_[a-z0-9_]+)`", DOC):
        current = match.group(1) or current
        assert current is not None, match.group(0)
        path = ROOT / "tests" / (current if current.startswith("e2e/") else f"unit/{current}")
        if not path.exists() or f"def {match.group(2)}(" not in path.read_text(encoding="utf-8"):
            missing.append(f"{current}::{match.group(2)}")
    assert missing == []


def test_every_area_of_the_threat_model_has_a_table_row_with_a_test():
    for area in ("Transport and peer check", "Token", "Files", "Generic PDB access", "Batch",
                 "Resources and prompts", "Supply chain"):  # fmt: skip
        section = DOC.split(f"## {area}", 1)[1].split("\n## ", 1)[0]
        rows = [line for line in section.splitlines() if line.startswith("| ") and "---" not in line][1:]
        assert rows and all("::test_" in row for row in rows), area

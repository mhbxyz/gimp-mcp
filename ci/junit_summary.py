"""Markdown summary of a pytest JUnit report: verdict, counts and failed tests (gimp-next job, #121).

python3 ci/junit_summary.py TITLE report.xml >> "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def summary(title: str, path: str) -> str:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        return f"## {title}: no test report ({error})\n"
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return f"## {title}: empty test report\n"
    total = int(suite.get("tests", 0))
    failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    verdict = "green" if failed == 0 else "red"
    lines = [f"## {title}: {verdict}", "", f"{total} tests, {failed} failed, {skipped} skipped."]
    for case in suite.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            lines.append(f"- {case.get('classname')}::{case.get('name')}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(summary(sys.argv[1], sys.argv[2]))

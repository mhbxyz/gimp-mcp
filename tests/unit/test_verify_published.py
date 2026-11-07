"""scripts/verify_published.py: the files on the index are exactly the built artifacts (#36)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_published.py"
spec = importlib.util.spec_from_file_location("verify_published", SCRIPT)
assert spec is not None and spec.loader is not None
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

SUMS = "aaa  ./gimp_mcp-0.2.0-py3-none-any.whl\nbbb  ./gimp_mcp-0.2.0.tar.gz\n"


def release(*files: tuple[str, str]) -> dict:
    return {"urls": [{"filename": name, "digests": {"sha256": digest}} for name, digest in files]}


def test_identical_files_pass():
    data = release(("gimp_mcp-0.2.0-py3-none-any.whl", "aaa"), ("gimp_mcp-0.2.0.tar.gz", "bbb"))
    assert verify.compare(data, verify.parse_sums(SUMS)) == []


def test_a_different_or_missing_file_is_reported():
    data = release(("gimp_mcp-0.2.0-py3-none-any.whl", "zzz"))
    problems = verify.compare(data, verify.parse_sums(SUMS))
    assert any("gimp_mcp-0.2.0-py3-none-any.whl" in p and "differs" in p for p in problems)
    assert any("gimp_mcp-0.2.0.tar.gz" in p and "missing" in p for p in problems)


def test_unexpected_extra_files_are_reported():
    data = release(("gimp_mcp-0.2.0-py3-none-any.whl", "aaa"), ("gimp_mcp-0.2.0.tar.gz", "bbb"), ("other.whl", "ccc"))
    assert any("other.whl" in p for p in verify.compare(data, verify.parse_sums(SUMS)))

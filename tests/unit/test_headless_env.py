import sys
from pathlib import Path

from gimp_mcp.headless import system_path


def test_virtualenv_bin_is_removed_from_gimp_path():
    venv_bin = str(Path(sys.prefix) / "bin")
    assert system_path(f"{venv_bin}:/usr/local/bin:/usr/bin") == "/usr/local/bin:/usr/bin"


def test_gimp_log_is_kept_for_diagnosis_when_requested(tmp_path, monkeypatch):
    from gimp_mcp.headless import HeadlessGimp

    keep = tmp_path / "logs"
    monkeypatch.setenv("GIMP_MCP_LOG_DIR", str(keep))
    gimp = HeadlessGimp(console=sys.executable)  # never started
    gimp.log_path.write_text("GIMP-Message: boom\n")
    gimp.stop()
    kept = list(keep.glob("*.log"))
    assert len(kept) == 1
    assert kept[0].read_text() == "GIMP-Message: boom\n"
    assert not gimp.root.exists()

import sys
from pathlib import Path

from gimp_mcp.headless import system_path


def test_virtualenv_bin_is_removed_from_gimp_path():
    venv_bin = str(Path(sys.prefix) / "bin")
    assert system_path(f"{venv_bin}:/usr/local/bin:/usr/bin") == "/usr/local/bin:/usr/bin"

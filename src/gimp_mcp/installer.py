"""Install / uninstall the bridge plug-in into a GIMP 3 configuration directory."""

from __future__ import annotations

import os
import shutil
import stat
from importlib import resources
from pathlib import Path

from . import __version__

PLUGIN_NAME = "gimp-mcp-bridge"
DEFAULT_GIMP_SERIES = "3.2"


def plugin_source_dir() -> Path:
    return Path(str(resources.files("gimp_mcp") / "plugin" / PLUGIN_NAME))


def default_gimp_config_dir(environ: dict[str, str] | None = None, series: str = DEFAULT_GIMP_SERIES) -> Path:
    """Where GIMP reads its user configuration (``GIMP3_DIRECTORY`` overrides it)."""
    env = os.environ if environ is None else environ
    if env.get("GIMP3_DIRECTORY"):
        return Path(env["GIMP3_DIRECTORY"])
    config_home = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME", "~")).expanduser() / ".config")
    return Path(config_home) / "GIMP" / series


def installed_plugin_dir(gimp_config_dir: Path) -> Path:
    return gimp_config_dir / "plug-ins" / PLUGIN_NAME


def install_plugin(gimp_config_dir: Path) -> Path:
    target = installed_plugin_dir(gimp_config_dir)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plugin_source_dir(), target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The plug-in reports this version in its handshake (single source: pyproject.toml).
    (target / "VERSION").write_text(__version__ + "\n", encoding="utf-8")
    entry = target / f"{PLUGIN_NAME}.py"
    entry.chmod(entry.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def uninstall_plugin(gimp_config_dir: Path) -> bool:
    target = installed_plugin_dir(gimp_config_dir)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True

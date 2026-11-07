"""Load GIMP-independent modules of the bridge plug-in (shared logic) from the server side."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from .installer import plugin_source_dir


def load(name: str) -> ModuleType:
    """Import ``<plugin dir>/<name>.py`` (must be standard-library only)."""
    key = f"gimp_mcp._plugin_{name}"
    if key in sys.modules:
        return sys.modules[key]
    path = plugin_source_dir() / f"{name}.py"
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module

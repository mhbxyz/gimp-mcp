"""Shared test configuration.

The GIMP-side plug-in modules (``gmb_*.py``) are not part of the importable
``gimp_mcp`` package: GIMP executes them from the plug-in directory. Their
GIMP-independent parts are tested directly, so the plug-in directory is put on
``sys.path`` here.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "src" / "gimp_mcp" / "plugin" / "gimp-mcp-bridge"
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

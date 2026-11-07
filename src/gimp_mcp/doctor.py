"""`gimp-mcp doctor`: explain what is missing, step by step (output on stderr)."""

from __future__ import annotations

import sys
from pathlib import Path

from . import __version__
from .bridge import BridgeClient, BridgeEndpoint
from .errors import GimpMcpError
from .headless import find_gimp_console
from .installer import default_gimp_config_dir, installed_plugin_dir
from .versions import Compatibility, check_plugin_version


def _say(ok: bool, text: str) -> None:
    print(("[ok]   " if ok else "[FAIL] ") + text, file=sys.stderr)


async def run_doctor(endpoint: BridgeEndpoint, gimp_dir: Path | None) -> int:
    failures = 0
    console = find_gimp_console()
    _say(console is not None, f"gimp-console found: {console or 'no'}")
    failures += console is None
    config = gimp_dir or default_gimp_config_dir()
    plugin = installed_plugin_dir(config)
    installed = (plugin / "gimp-mcp-bridge.py").exists()
    _say(installed, f"bridge plug-in installed in {plugin}")
    failures += not installed
    installed_version = None
    if installed:
        try:
            installed_version = (plugin / "VERSION").read_text().strip()
        except OSError:
            installed_version = "unknown"
        verdict = check_plugin_version(__version__, installed_version)
        _say(
            verdict is not Compatibility.INCOMPATIBLE,
            f"installed plug-in version {installed_version} / server {__version__}: {verdict.value}",
        )
        failures += verdict is Compatibility.INCOMPATIBLE
    client = BridgeClient(endpoint, connect_timeout=3)
    try:
        session = await client.connect()
        verdict = check_plugin_version(__version__, session.bridge_version)
        _say(
            verdict is not Compatibility.INCOMPATIBLE,
            f"running plug-in version {session.bridge_version} / server {__version__}: {verdict.value}",
        )
        _say(
            True,
            f"connected to GIMP {session.gimp_version} (session {session.session_id}) via {endpoint.socket_path}",
        )
    except GimpMcpError as error:
        failures += 1
        if error.code == "PLUGIN_VERSION_MISMATCH":
            _say(
                False,
                f"running plug-in version {error.details.get('plugin_version')} / server "
                f"{error.details.get('server_version')}: incompatible",
            )
        else:
            _say(False, f"bridge connection: {error}")
        if error.hint:
            print(f"       hint: {error.hint}", file=sys.stderr)
    finally:
        await client.close()
    return 0 if failures == 0 else 1

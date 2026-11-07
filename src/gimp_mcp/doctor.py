"""`gimp-mcp doctor`: explain what is missing, step by step (output on stderr)."""

from __future__ import annotations

import sys
from pathlib import Path

from .bridge import BridgeClient, BridgeEndpoint
from .errors import GimpMcpError
from .headless import find_gimp_console
from .installer import default_gimp_config_dir, installed_plugin_dir


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
    client = BridgeClient(endpoint, connect_timeout=3)
    try:
        session = await client.connect()
        _say(
            True,
            f"connected to GIMP {session.gimp_version} (session {session.session_id}) via {endpoint.socket_path}",
        )
    except GimpMcpError as error:
        failures += 1
        _say(False, f"bridge connection: {error}")
        if error.hint:
            print(f"       hint: {error.hint}", file=sys.stderr)
    finally:
        await client.close()
    return 0 if failures == 0 else 1

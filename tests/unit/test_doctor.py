"""`gimp-mcp doctor` diagnoses known installation problems and says how to fix them (issue #39).

Every check runs against a simulated environment (FakeProbe): no real GIMP,
profile or process of this machine is read.
"""

from __future__ import annotations

import json
import os
import socket
import stat
from dataclasses import dataclass, field
from pathlib import Path

import gimp_mcp
from gimp_mcp.bridge import BridgeEndpoint
from gimp_mcp.doctor import CHECKS, Probe, Status, render_text, run_checks
from gimp_mcp.installer import install_plugin

from .fake_bridge import DEFAULT_SESSION, running_fake_bridge, short_tmpdir


@dataclass
class FakeProbe(Probe):
    """Probe with scripted answers; the filesystem part is a temporary HOME."""

    executables: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, tuple[int, str]] = field(default_factory=dict)
    processes: list[tuple[int, str]] = field(default_factory=list)

    def which(self, name: str) -> str | None:
        return self.executables.get(name)

    def run(self, args: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
        for key, answer in self.outputs.items():
            if key in " ".join(args):
                return answer
        return (127, "not found")

    def gimp_processes(self) -> list[tuple[int, str]]:
        return list(self.processes)


GIMP_OK = {"gimp-console": "/usr/bin/gimp-console", "gimp": "/usr/bin/gimp"}
VERSION_OK = {"--version": (0, "GNU Image Manipulation Program version 3.2.6")}
PYTHON_OK = {"import gi": (0, "ok")}


def healthy(tmp_path: Path, endpoint: BridgeEndpoint | None = None, **overrides) -> FakeProbe:
    home = tmp_path / "home"
    profile = home / ".config" / "GIMP" / "3.2"
    profile.mkdir(parents=True, exist_ok=True)
    install_plugin(profile)
    (profile / "pluginrc").write_text('(plug-in-def "${gimp_dir}/plug-ins/gimp-mcp-bridge/gimp-mcp-bridge.py" 1)\n')
    probe = FakeProbe(
        env={"HOME": str(home), "PATH": "/usr/bin"},
        endpoint=endpoint or BridgeEndpoint.for_socket(tmp_path / "none.sock"),
        executables=dict(GIMP_OK),
        outputs={**VERSION_OK, **PYTHON_OK},
    )
    for key, value in overrides.items():
        setattr(probe, key, value)
    return probe


def by_id(results):
    return {result.id: result for result in results}


async def test_a_healthy_installation_passes_every_check(tmp_path):
    with running_fake_bridge({}) as bridge:
        probe = healthy(tmp_path, bridge.endpoint, processes=[(4242, "gimp")])
        results = by_id(await run_checks(probe))
    failing = {k: (r.status, r.message) for k, r in results.items() if r.status is not Status.OK}
    assert failing == {}


async def test_missing_gimp_is_a_failure_with_a_fix(tmp_path):
    probe = healthy(tmp_path, executables={})
    result = by_id(await run_checks(probe))["gimp"]
    assert result.status is Status.FAIL and "GIMP 3.2" in result.fix


async def test_old_gimp_is_refused(tmp_path):
    probe = healthy(tmp_path, outputs={**PYTHON_OK, "--version": (0, "GNU Image Manipulation Program version 3.0.4")})
    result = by_id(await run_checks(probe))["gimp"]
    assert result.status is Status.FAIL and "3.0.4" in result.message


async def test_missing_plugin(tmp_path):
    probe = healthy(tmp_path)
    plugin = Path(probe.env["HOME"]) / ".config/GIMP/3.2/plug-ins/gimp-mcp-bridge"
    for child in plugin.iterdir():
        child.unlink()
    plugin.rmdir()
    result = by_id(await run_checks(probe))["plugin"]
    assert result.status is Status.FAIL and "gimp-mcp install-plugin" in result.fix


async def test_plugin_not_executable(tmp_path):
    probe = healthy(tmp_path)
    entry = Path(probe.env["HOME"]) / ".config/GIMP/3.2/plug-ins/gimp-mcp-bridge/gimp-mcp-bridge.py"
    entry.chmod(0o644)
    result = by_id(await run_checks(probe))["plugin"]
    assert result.status is Status.FAIL and "executable" in result.message


async def test_plugin_from_another_version(tmp_path):
    probe = healthy(tmp_path)
    (Path(probe.env["HOME"]) / ".config/GIMP/3.2/plug-ins/gimp-mcp-bridge/VERSION").write_text("0.0.1\n")
    result = by_id(await run_checks(probe))["plugin-version"]
    assert result.status is Status.WARN and "0.0.1" in result.message and gimp_mcp.__version__ in result.message
    assert "when GIMP connects" in result.message


async def test_connection_shows_versions_protocol_and_verdict(tmp_path):
    with running_fake_bridge({}) as bridge:
        result = by_id(await run_checks(healthy(tmp_path, bridge.endpoint)))["connection"]
    assert result.status is Status.OK
    assert f"plug-in {gimp_mcp.__version__}" in result.message and "protocol 1" in result.message
    assert "match" in result.message


async def test_connection_to_an_older_plugin_is_a_warning(tmp_path):
    session = {**DEFAULT_SESSION, "bridge_version": "0.5.0"}
    with running_fake_bridge({}, session=session, legacy=True) as bridge:
        result = by_id(await run_checks(healthy(tmp_path, bridge.endpoint)))["connection"]
    assert result.status is Status.WARN and "0.5.0" in result.message and "partial" in result.message
    assert "gimp-mcp install-plugin" in result.fix


async def test_gimp_python_without_pygobject(tmp_path):
    probe = healthy(tmp_path, outputs={**VERSION_OK, "import gi": (1, "ModuleNotFoundError: No module named 'gi'")})
    result = by_id(await run_checks(probe))["gimp-python"]
    assert result.status is Status.FAIL and "PyGObject" in result.fix


async def test_virtualenv_first_on_path_is_a_warning(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python3").write_text("")
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    probe = healthy(tmp_path)
    probe.env = {**probe.env, "PATH": f"{venv / 'bin'}:/usr/bin"}
    probe.executables = {**probe.executables, "python3": str(venv / "bin" / "python3")}
    result = by_id(await run_checks(probe))["venv-path"]
    assert result.status is Status.WARN and "virtualenv" in result.message


async def test_plugin_not_registered_by_gimp(tmp_path):
    probe = healthy(tmp_path)
    (Path(probe.env["HOME"]) / ".config/GIMP/3.2/pluginrc").write_text('(plug-in-def "other.py" 1)\n')
    result = by_id(await run_checks(probe))["plugin-registered"]
    assert result.status is Status.WARN and "restart gimp" in result.fix.lower()


async def test_plugin_registered_with_windows_separators(tmp_path):
    # GIMP for Windows writes the plug-in path with escaped backslashes in pluginrc
    probe = healthy(tmp_path)
    pluginrc = Path(probe.env["HOME"]) / ".config/GIMP/3.2/pluginrc"
    pluginrc.write_text('(plug-in-def "C:\\\\Users\\\\a\\\\gimp-mcp-bridge\\\\gimp-mcp-bridge.py" 1)\n')
    assert by_id(await run_checks(probe))["plugin-registered"].status is Status.OK


async def test_gimp_running_without_the_bridge(tmp_path):
    probe = healthy(tmp_path, processes=[(31337, "gimp")])
    result = by_id(await run_checks(probe))["connection"]
    assert result.status is Status.FAIL
    assert "running" in result.message and "restart GIMP" in result.fix


async def test_stale_socket(tmp_path):
    directory = short_tmpdir()
    path = directory / "bridge.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    listener.close()
    (directory / "bridge.sock.token").write_text("t")
    os.chmod(directory / "bridge.sock.token", 0o600)
    try:
        probe = healthy(tmp_path, BridgeEndpoint.for_socket(path))
        result = by_id(await run_checks(probe))["connection"]
    finally:
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
    assert result.status is Status.FAIL and "stale" in result.message


async def test_stale_socket_while_another_gimp_runs(tmp_path):
    """A crashed GIMP left its socket; another GIMP (another socket) runs: the socket is still stale."""
    directory = short_tmpdir()
    path = directory / "bridge.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    listener.close()
    (directory / "bridge.sock.token").write_text("t")
    os.chmod(directory / "bridge.sock.token", 0o600)
    try:
        probe = healthy(tmp_path, BridgeEndpoint.for_socket(path), processes=[(4242, "gimp-console-3.2")])
        result = by_id(await run_checks(probe))["connection"]
    finally:
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
    assert result.status is Status.FAIL and "stale" in result.message and "4242" in result.message


async def test_token_and_directory_permissions(tmp_path):
    with running_fake_bridge({}) as bridge:
        bridge.token_path.chmod(0o644)
        bridge.socket_path.parent.chmod(0o755)
        probe = healthy(tmp_path, bridge.endpoint)
        result = by_id(await run_checks(probe))["socket-permissions"]
        bridge.socket_path.parent.chmod(0o700)
    assert result.status is Status.FAIL
    assert "0644" in result.message or "0755" in result.message
    assert "chmod" in result.fix


async def test_several_gimp_processes_for_one_bridge(tmp_path):
    with running_fake_bridge({}) as bridge:
        probe = healthy(tmp_path, bridge.endpoint, processes=[(1, "gimp"), (2, "gimp")])
        result = by_id(await run_checks(probe))["instances"]
    assert result.status is Status.WARN and "GIMP_MCP_SOCKET" in result.fix


async def test_several_profiles_are_listed_and_the_wrong_one_detected(tmp_path):
    probe = healthy(tmp_path)
    home = Path(probe.env["HOME"])
    other = home / ".config" / "GIMP" / "3.0"
    other.mkdir(parents=True)
    result = by_id(await run_checks(probe))["profiles"]
    assert result.status is Status.OK and "3.0" in result.message and "3.2" in result.message
    # plug-in only in a profile that this GIMP does not use
    for child in (home / ".config/GIMP/3.2/plug-ins/gimp-mcp-bridge").iterdir():
        child.unlink()
    (home / ".config/GIMP/3.2/plug-ins/gimp-mcp-bridge").rmdir()
    install_plugin(other)
    result = by_id(await run_checks(probe))["profiles"]
    assert result.status is Status.WARN and "3.0" in result.message


async def test_every_check_has_a_documented_fix():
    ids = [check.id for check in CHECKS]
    assert len(ids) == len(set(ids))
    assert all(check.title and check.fix for check in CHECKS)


async def test_text_and_json_outputs(tmp_path):
    probe = healthy(tmp_path, executables={})
    results = await run_checks(probe)
    text = render_text(results)
    assert "[FAIL]" in text and "fix:" in text
    payload = json.loads(json.dumps([r.to_dict() for r in results]))
    assert {"id", "status", "message", "fix"} <= set(payload[0])


def test_cli_exit_codes_and_json(tmp_path):
    import subprocess
    import sys

    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "GIMP_MCP_SOCKET": str(tmp_path / "x.sock"),
        "PATH": "/nonexistent",
        "GIMP_MCP_GIMP_CONSOLE": str(tmp_path / "no-gimp"),
    }  # not the GIMP installed in /Applications
    proc = subprocess.run(
        [sys.executable, "-m", "gimp_mcp", "doctor", "--json"], capture_output=True, text=True, env=env, timeout=60
    )
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["ok"] is False and any(c["id"] == "gimp" and c["status"] == "fail" for c in data["checks"])
    assert stat.S_ISDIR(os.stat(tmp_path).st_mode)


def test_troubleshooting_doc_is_generated_from_the_checks():
    from gimp_mcp.doctor import render_troubleshooting

    doc = Path(__file__).resolve().parents[2] / "docs" / "troubleshooting.md"
    assert doc.read_text() == render_troubleshooting(), (
        "run: uv run gimp-mcp doctor --troubleshooting > docs/troubleshooting.md"
    )


async def test_the_environment_running_gimp_mcp_itself_is_not_reported(tmp_path):
    """`uvx gimp-mcp doctor` puts its own environment first on PATH: that is not the user's shell."""
    import sys

    probe = healthy(tmp_path)
    own = Path(sys.prefix) / "bin"
    probe.env = {**probe.env, "PATH": f"{own}:/usr/bin"}
    probe.executables = {**probe.executables, "python3": str(own / "python3")}
    result = by_id(await run_checks(probe))["venv-path"]
    assert result.status is Status.OK, result.message

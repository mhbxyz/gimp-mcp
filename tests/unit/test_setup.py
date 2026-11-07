"""`gimp-mcp setup` (issue #40). Everything runs in a temporary HOME with fake client CLIs."""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import gimp_mcp
from gimp_mcp.bridge import BridgeEndpoint
from gimp_mcp.setup import SetupOptions, run_setup, server_command

from .fake_bridge import running_fake_bridge

FAKE_CLI = """#!/bin/sh
echo "$0 $*" >> "{log}"
case "$*" in
  "mcp get gimp") {get_behaviour} ;;
  "mcp get gimp --scope user") {get_behaviour} ;;
esac
exit 0
"""


@dataclass
class World:
    home: Path
    bin: Path
    log: Path
    env: dict[str, str]
    answers: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)

    def ask(self, question: str) -> bool:
        self.output.append(question)
        answer = self.answers.pop(0) if self.answers else "n"
        return answer.lower().startswith("y")

    def say(self, text: str) -> None:
        self.output.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.output)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


def make_world(tmp_path: Path, clients: tuple[str, ...] = (), claude_has_gimp: bool = False) -> World:
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    log = tmp_path / "cli.log"
    # gimp-console reporting 3.2.6
    console = bin_dir / "gimp-console-3.2"
    console.write_text("#!/bin/sh\necho 'GNU Image Manipulation Program version 3.2.6'\n")
    console.chmod(0o755)
    for name in ("claude", "code"):
        if name in clients:
            script = bin_dir / name
            get = "echo '  Command: /opt/gimp-mcp/bin/gimp-mcp serve'; exit 0" if claude_has_gimp else "exit 1"
            script.write_text(FAKE_CLI.format(log=log, get_behaviour=get))
            script.chmod(0o755)
    if "claude-desktop" in clients:
        (home / ".config" / "Claude").mkdir(parents=True)
    if "cursor" in clients:
        (home / ".cursor").mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    return World(home, bin_dir, log, env)


def options(world: World, **overrides) -> SetupOptions:
    values = {
        "env": world.env,
        "endpoint": BridgeEndpoint.for_socket(world.home / "none.sock"),
        "ask": world.ask,
        "say": world.say,
        "assume_yes": False,
        "interactive": True,
        "server": ["/opt/gimp-mcp/bin/gimp-mcp", "serve"],
        "run_doctor": False,
    }
    values.update(overrides)
    return SetupOptions(**values)


def plugin_dir(world: World) -> Path:
    return world.home / ".config" / "GIMP" / "3.2" / "plug-ins" / "gimp-mcp-bridge"


async def test_detects_gimp_and_installs_the_plugin_in_the_profile_it_uses(tmp_path):
    world = make_world(tmp_path)
    code = await run_setup(options(world))
    assert code == 0
    assert (plugin_dir(world) / "VERSION").read_text().strip() == gimp_mcp.__version__
    assert "GIMP 3.2.6" in world.text and "restart GIMP" in world.text


async def test_gimp3_directory_overrides_the_profile(tmp_path):
    world = make_world(tmp_path)
    custom = tmp_path / "custom-profile"
    world.env["GIMP3_DIRECTORY"] = str(custom)
    await run_setup(options(world))
    assert (custom / "plug-ins" / "gimp-mcp-bridge" / "gimp-mcp-bridge.py").exists()


async def test_missing_gimp_stops_with_instructions(tmp_path):
    world = make_world(tmp_path)
    (world.bin / "gimp-console-3.2").unlink()
    world.env["PATH"] = str(world.bin)  # the machine's own GIMP must not be found
    code = await run_setup(options(world))
    assert code == 1 and "Install GIMP 3.2" in world.text
    assert not plugin_dir(world).exists()


async def test_claude_desktop_entry_is_merged_with_backup_after_consent(tmp_path):
    world = make_world(tmp_path, clients=("claude-desktop",))
    config = world.home / ".config" / "Claude" / "claude_desktop_config.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "globalShortcut": "Ctrl+Space"}))
    world.answers = ["y"]
    await run_setup(options(world))
    data = json.loads(config.read_text())
    assert data["mcpServers"]["other"] == {"command": "x"}  # other servers untouched
    assert data["globalShortcut"] == "Ctrl+Space"
    assert data["mcpServers"]["gimp"] == {"command": "/opt/gimp-mcp/bin/gimp-mcp", "args": ["serve"]}
    backups = list(config.parent.glob("claude_desktop_config.json.bak-*"))
    assert len(backups) == 1 and "gimp" not in json.loads(backups[0].read_text())["mcpServers"]
    assert '"gimp"' in world.text  # the exact change was shown


async def test_nothing_is_written_without_consent(tmp_path):
    world = make_world(tmp_path, clients=("claude-desktop", "cursor", "claude"))
    world.answers = ["n", "n", "n"]
    await run_setup(options(world))
    assert not (world.home / ".config" / "Claude" / "claude_desktop_config.json").exists()
    assert not (world.home / ".cursor" / "mcp.json").exists()
    assert not any("mcp add" in call for call in world.calls())


async def test_non_interactive_without_yes_only_prints_snippets(tmp_path):
    world = make_world(tmp_path, clients=("cursor",))
    await run_setup(options(world, interactive=False))
    assert not (world.home / ".cursor" / "mcp.json").exists()
    assert '"mcpServers"' in world.text


async def test_yes_configures_every_detected_client(tmp_path):
    world = make_world(tmp_path, clients=("claude", "code", "claude-desktop", "cursor"))
    await run_setup(options(world, assume_yes=True, interactive=False))
    calls = world.calls()
    assert any(
        call.endswith("claude mcp add --transport stdio --scope user gimp -- /opt/gimp-mcp/bin/gimp-mcp serve")
        for call in calls
    ), calls
    vscode = next(call for call in calls if "--add-mcp" in call)
    payload = json.loads(vscode.split("--add-mcp ", 1)[1])
    assert payload == {"name": "gimp", "type": "stdio", "command": "/opt/gimp-mcp/bin/gimp-mcp", "args": ["serve"]}
    cursor = json.loads((world.home / ".cursor" / "mcp.json").read_text())
    assert cursor["mcpServers"]["gimp"]["command"] == "/opt/gimp-mcp/bin/gimp-mcp"
    assert (world.home / ".config" / "Claude" / "claude_desktop_config.json").exists()


async def test_running_twice_changes_nothing_the_second_time(tmp_path):
    world = make_world(tmp_path, clients=("claude-desktop", "cursor"))
    await run_setup(options(world, assume_yes=True, interactive=False))
    config = world.home / ".config" / "Claude" / "claude_desktop_config.json"
    first = config.read_text()
    world.output.clear()
    await run_setup(options(world, assume_yes=True, interactive=False))
    assert config.read_text() == first
    assert len(list(config.parent.glob("*.bak-*"))) == 0  # nothing to back up the first time, nothing changed after
    assert "already configured" in world.text and "up to date" in world.text


async def test_existing_claude_code_entry_is_left_alone(tmp_path):
    world = make_world(tmp_path, clients=("claude",), claude_has_gimp=True)
    await run_setup(options(world, assume_yes=True, interactive=False))
    assert not any("mcp add" in call for call in world.calls())
    assert "already has a 'gimp' server" in world.text


async def test_undetected_clients_get_a_snippet(tmp_path):
    world = make_world(tmp_path)
    await run_setup(options(world, assume_yes=True, interactive=False))
    assert "claude mcp add --transport stdio --scope user gimp -- /opt/gimp-mcp/bin/gimp-mcp serve" in world.text
    assert '"mcpServers"' in world.text


async def test_an_invalid_client_config_is_never_overwritten(tmp_path):
    world = make_world(tmp_path, clients=("cursor",))
    broken = world.home / ".cursor" / "mcp.json"
    broken.write_text("{ not json")
    code = await run_setup(options(world, assume_yes=True, interactive=False))
    assert broken.read_text() == "{ not json"
    assert "not valid JSON" in world.text and code == 1


async def test_live_check_when_gimp_runs(tmp_path):
    world = make_world(tmp_path)
    with running_fake_bridge({"session.images": lambda p: {"images": []}}) as bridge:
        code = await run_setup(options(world, endpoint=BridgeEndpoint.for_socket(bridge.socket_path)))
    assert code == 0 and "GIMP 3.2.6 answers" in world.text


def test_server_command_is_absolute_and_pinned_when_run_through_uvx(tmp_path):
    exe = tmp_path / "venv" / "bin" / "gimp-mcp"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    assert server_command(prefix=str(tmp_path / "venv"), env={"PATH": "/usr/bin"}) == [str(exe), "serve"]
    uv_cache = tmp_path / ".cache" / "uv" / "archive-v0" / "abc"
    (uv_cache / "bin").mkdir(parents=True)
    (uv_cache / "bin" / "gimp-mcp").write_text("")
    uvx = tmp_path / "bin" / "uvx"
    uvx.parent.mkdir()
    uvx.write_text("")
    uvx.chmod(0o755)
    command = server_command(prefix=str(uv_cache), env={"PATH": str(uvx.parent)})
    assert command == [str(uvx), "--from", f"gimp-mcp=={gimp_mcp.__version__}", "gimp-mcp", "serve"]


def test_cli_entry_point(tmp_path):
    import subprocess

    world = make_world(tmp_path, clients=("cursor",))
    env = {**os.environ, **world.env, "PATH": f"{world.bin}:{os.environ['PATH']}"}
    proc = subprocess.run(
        [sys.executable, "-m", "gimp_mcp", "setup", "--yes", "--no-doctor"],
        capture_output=True, text=True, env=env, timeout=60, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert json.loads((world.home / ".cursor" / "mcp.json").read_text())["mcpServers"]["gimp"]["args"][-1] == "serve"


@pytest.mark.parametrize("flag", ["--help"])
def test_setup_is_documented_in_the_cli(flag):
    import subprocess

    proc = subprocess.run([sys.executable, "-m", "gimp_mcp", "setup", flag], capture_output=True, text=True)
    assert "--yes" in proc.stdout and "--clients" in proc.stdout

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
from gimp_mcp import platforms
from gimp_mcp.bridge import BridgeEndpoint
from gimp_mcp.setup import SetupOptions, run_setup, server_command

from .fake_bridge import running_fake_bridge

# Windows: a .cmd relay to Python, which logs argv as the program received it (cmd.exe's %* is the
# raw command line, quotes still escaped)
FAKE_CLI_PY = """import sys
log, has_gimp, name, args = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
with open(log, "a", encoding="utf-8") as out:
    out.write(" ".join([name, *args]) + "\\n")
if args[:3] == ["mcp", "get", "gimp"] and args[3:] in ([], ["--scope", "user"]):
    if has_gimp == "yes":
        print("  Command: /opt/gimp-mcp/bin/gimp-mcp serve")
        sys.exit(0)
    sys.exit(1)
"""

FAKE_CLI_CMD = '@"{python}" "{relay}" "{log}" {has_gimp} "%~dpn0" %*\n@exit /b %ERRORLEVEL%\n'

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


WINDOWS = platforms.CURRENT == "windows"


def fake_program(bin_dir: Path, name: str, posix: str, cmd: str) -> None:
    """A fake command-line program: a shell script, or a .cmd file on Windows."""
    if WINDOWS:
        (bin_dir / f"{name}.cmd").write_text(cmd, encoding="utf-8")
    else:
        script = bin_dir / name
        script.write_text(posix, encoding="utf-8")
        script.chmod(0o755)


def remove_program(bin_dir: Path, name: str) -> None:
    (bin_dir / (f"{name}.cmd" if WINDOWS else name)).unlink()


def isolated_env(home: Path, bin_dir: Path) -> dict[str, str]:
    """Every per-user location of every OS inside ``home``; only the fake programs on PATH."""
    env = {"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
           "LOCALAPPDATA": str(home / "AppData" / "Local")}  # fmt: skip
    if WINDOWS:  # cmd.exe needs these to run the fake .cmd programs
        for name in ("SYSTEMROOT", "COMSPEC", "PATHEXT"):
            env[name] = os.environ.get(name, "")
        env["PATH"] = os.pathsep.join([str(bin_dir), os.environ.get("SYSTEMROOT", "") + "\\System32"])
    else:
        env["PATH"] = os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])
    return env


def config_home(world: World) -> Path:
    return Path(platforms.config_home(world.env))


def make_world(tmp_path: Path, clients: tuple[str, ...] = (), claude_has_gimp: bool = False) -> World:
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    log = tmp_path / "cli.log"
    # gimp-console reporting 3.2.6
    fake_program(bin_dir, "gimp-console-3.2", "#!/bin/sh\necho 'GNU Image Manipulation Program version 3.2.6'\n",
                 "@echo GNU Image Manipulation Program version 3.2.6\n")  # fmt: skip
    relay = tmp_path / "fake_cli.py"
    relay.write_text(FAKE_CLI_PY, encoding="utf-8")
    for name in ("claude", "code"):
        if name in clients:
            get = "echo '  Command: /opt/gimp-mcp/bin/gimp-mcp serve'; exit 0" if claude_has_gimp else "exit 1"
            cmd = FAKE_CLI_CMD.format(python=sys.executable, relay=relay, log=log,
                                      has_gimp="yes" if claude_has_gimp else "no")  # fmt: skip
            fake_program(bin_dir, name, FAKE_CLI.format(log=log, get_behaviour=get), cmd)
    env = isolated_env(home, bin_dir)
    world = World(home, bin_dir, log, env)
    if "claude-desktop" in clients:
        (config_home(world) / "Claude").mkdir(parents=True)
    if "cursor" in clients:
        (home / ".cursor").mkdir()
    return world


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
    return Path(platforms.gimp_profile_dir(world.env)) / "plug-ins" / "gimp-mcp-bridge"


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
    remove_program(world.bin, "gimp-console-3.2")
    world.env["PATH"] = str(world.bin)  # the machine's own GIMP must not be found
    code = await run_setup(options(world))
    assert code == 1 and "Install GIMP 3.2" in world.text
    assert not plugin_dir(world).exists()


async def test_claude_desktop_entry_is_merged_with_backup_after_consent(tmp_path):
    world = make_world(tmp_path, clients=("claude-desktop",))
    config = config_home(world) / "Claude" / "claude_desktop_config.json"
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
    assert not (config_home(world) / "Claude" / "claude_desktop_config.json").exists()
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
    assert (config_home(world) / "Claude" / "claude_desktop_config.json").exists()


@pytest.mark.skipif(not WINDOWS, reason="USERPROFILE is the home directory on Windows only")
async def test_cursor_on_windows_lives_in_userprofile_even_when_home_is_set(tmp_path):
    world = make_world(tmp_path, clients=("cursor",))
    world.env["HOME"] = str(tmp_path / "msys-home")  # Git Bash and MSYS2 set HOME to their own directory
    await run_setup(options(world, assume_yes=True, interactive=False))
    assert (world.home / ".cursor" / "mcp.json").exists()
    assert not (tmp_path / "msys-home").exists()


async def test_running_twice_changes_nothing_the_second_time(tmp_path):
    world = make_world(tmp_path, clients=("claude-desktop", "cursor"))
    await run_setup(options(world, assume_yes=True, interactive=False))
    config = config_home(world) / "Claude" / "claude_desktop_config.json"
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
        code = await run_setup(options(world, endpoint=bridge.endpoint))
    assert code == 0 and "GIMP 3.2.6 answers" in world.text


def test_server_command_is_absolute_and_pinned_when_run_through_uvx(tmp_path):
    exe = tmp_path / "venv" / ("Scripts/gimp-mcp.exe" if WINDOWS else "bin/gimp-mcp")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    assert server_command(prefix=str(tmp_path / "venv"), env={"PATH": str(tmp_path / "none")}) == [str(exe), "serve"]
    # uv's cache: ~/.cache/uv/archive-v0/… on Linux and macOS, %LOCALAPPDATA%\uv\cache\archive-v0\… on Windows
    uv_cache = tmp_path / ("AppData/Local/uv/cache" if WINDOWS else ".cache/uv") / "archive-v0" / "abc"
    (uv_cache / "bin").mkdir(parents=True)
    uvx = tmp_path / "bin" / ("uvx.exe" if WINDOWS else "uvx")
    uvx.parent.mkdir()
    uvx.write_text("")
    uvx.chmod(0o755)
    command = server_command(prefix=str(uv_cache), env={"PATH": str(uvx.parent)})
    # shutil.which spells the extension as PATHEXT does (uvx.EXE); Windows paths ignore case
    command[0] = os.path.normcase(command[0])
    assert command == [os.path.normcase(uvx), "--from", f"gimp-mcp=={gimp_mcp.__version__}", "gimp-mcp", "serve"]


def test_cli_entry_point(tmp_path):
    import subprocess

    world = make_world(tmp_path, clients=("cursor",))
    env = {**os.environ, **world.env, "PATH": os.pathsep.join([str(world.bin), os.environ["PATH"]])}
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


async def test_without_gimp_running_setup_says_what_to_do_instead_of_failing_checks(tmp_path):
    world = make_world(tmp_path)
    code = await run_setup(options(world, run_doctor=True))
    assert code == 0
    assert "[FAIL]" not in world.text
    assert "then run `gimp-mcp doctor`" in world.text

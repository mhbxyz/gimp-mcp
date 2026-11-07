"""`gimp-mcp setup`: from nothing to a working connection, in one guided command.

1. find GIMP (version, profile it uses);
2. install or update the plug-in in that profile;
3. register the MCP server in the clients found on this machine — Claude
   Code and VS Code through their own CLI, Claude Desktop and Cursor by merging
   their JSON file (backup first, other servers never touched). Every change
   is shown first and applied only with consent (or --yes); clients that are
   not installed get a copy-paste snippet;
4. check the result (live call when GIMP runs, then the doctor).

Running it again changes nothing that is already right.
Client configuration formats are documented in docs/clients.md (with sources).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import __version__
from .bridge import BridgeClient, BridgeEndpoint
from .errors import GimpMcpError
from .installer import PLUGIN_NAME, install_plugin, installed_plugin_dir

if TYPE_CHECKING:
    from .doctor import Probe

SERVER_NAME = "gimp"


@dataclass
class SetupOptions:
    env: dict[str, str]
    endpoint: BridgeEndpoint
    ask: Callable[[str], bool]
    say: Callable[[str], None]
    assume_yes: bool = False
    interactive: bool = True
    server: list[str] | None = None
    run_doctor: bool = True
    gimp_dir: Path | None = None
    clients: set[str] | None = None  # None = every supported client


class ClientError(Exception):
    pass


def server_command(prefix: str | None = None, env: dict[str, str] | None = None) -> list[str]:
    """How MCP clients must start this server: an absolute command that keeps working.

    GUI clients (Claude Desktop) do not get the shell's PATH, so the command is
    absolute. When setup itself runs from a throw-away `uvx` environment, the
    command is `uvx --from gimp-mcp==<this version> gimp-mcp serve`, pinned so the
    server always matches the plug-in that was just installed.
    """
    prefix = prefix or sys.prefix
    path = (env or os.environ).get("PATH")
    ephemeral = "/uv/archive-v" in prefix.replace(os.sep, "/") or "/.cache/uv/" in prefix.replace(os.sep, "/")
    if ephemeral:
        uvx = shutil.which("uvx", path=path)
        if uvx:
            return [uvx, "--from", f"gimp-mcp=={__version__}", "gimp-mcp", "serve"]
    candidate = Path(prefix) / "bin" / "gimp-mcp"
    if candidate.exists():
        return [str(candidate), "serve"]
    found = shutil.which("gimp-mcp", path=path)
    if found:
        return [str(Path(found).resolve()), "serve"]
    return [sys.executable, "-m", "gimp_mcp", "serve"]


# -- clients --------------------------------------------------------------------------


@dataclass
class Change:
    description: str
    apply: Callable[[], None]


@dataclass
class Client:
    key: str
    name: str
    env: dict[str, str]
    server: list[str]

    @property
    def home(self) -> Path:
        return Path(self.env.get("HOME") or Path.home())

    @property
    def config_home(self) -> Path:
        return Path(self.env.get("XDG_CONFIG_HOME") or self.home / ".config")

    def detected(self) -> bool:
        raise NotImplementedError

    def plan(self) -> Change | None:
        """None when already configured. May raise ClientError."""
        raise NotImplementedError

    def snippet(self) -> str:
        raise NotImplementedError

    def removal(self) -> Change | None:
        """None when there is nothing to remove. May raise AlreadyThere / ClientError."""
        raise NotImplementedError


def server_entry(server: list[str], env: dict[str, str]) -> dict[str, Any]:
    entry: dict[str, Any] = {"command": server[0], "args": server[1:]}
    if env.get("GIMP_MCP_SOCKET"):
        entry["env"] = {"GIMP_MCP_SOCKET": env["GIMP_MCP_SOCKET"]}
    return entry


@dataclass
class JsonFileClient(Client):
    """Clients configured by a JSON file with a top-level `mcpServers` object."""

    marker: str = ""

    def path(self) -> Path:
        raise NotImplementedError

    def detected(self) -> bool:
        return self.path().parent.is_dir()

    def plan(self) -> Change | None:
        path = self.path()
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except ValueError as exc:
                raise ClientError(f"{path} is not valid JSON ({exc}); fix it, then run setup again") from exc
            if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
                raise ClientError(f"{path} does not have the expected shape (object with 'mcpServers')")
        wanted = server_entry(self.server, self.env)
        current = data.get("mcpServers", {}).get(SERVER_NAME)
        if current == wanted:
            return None
        new = dict(data)
        new["mcpServers"] = {**data.get("mcpServers", {}), SERVER_NAME: wanted}
        verb = "replace" if current is not None else "add"
        description = (
            f"{self.name}: {verb} the '{SERVER_NAME}' entry in {path}"
            + (" (backup kept next to it)" if path.exists() else "")
            + ":\n"
            + json.dumps({"mcpServers": {SERVER_NAME: wanted}}, indent=2)
        )
        return Change(description, lambda: write_json_with_backup(path, new))

    def removal(self) -> Change | None:
        path = self.path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError as exc:
            raise ClientError(f"{path} is not valid JSON ({exc}); left unchanged") from exc
        entry = (data.get("mcpServers") or {}).get(SERVER_NAME) if isinstance(data, dict) else None
        if entry is None:
            return None
        if not is_ours(entry):
            raise AlreadyThere(f"{self.name}: the '{SERVER_NAME}' entry in {path} was not created by gimp-mcp; left")
        new = dict(data)
        new["mcpServers"] = {k: v for k, v in data["mcpServers"].items() if k != SERVER_NAME}
        return Change(
            f"{self.name}: remove the '{SERVER_NAME}' entry from {path} (backup kept next to it)",
            lambda: write_json_with_backup(path, new),
        )

    def snippet(self) -> str:
        return f"{self.name}: add to {self.path()}:\n" + json.dumps(
            {"mcpServers": {SERVER_NAME: server_entry(self.server, self.env)}}, indent=2
        )


def is_ours(entry: Any) -> bool:
    """An entry gimp-mcp would have written: its command line runs gimp-mcp."""
    if not isinstance(entry, dict):
        return False
    words = [str(entry.get("command", ""))] + [str(a) for a in entry.get("args", []) or []]
    return any("gimp-mcp" in word or "gimp_mcp" in word for word in words)


def write_json_with_backup(path: Path, data: dict[str, Any]) -> None:
    if path.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{stamp}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class ClaudeDesktop(JsonFileClient):
    def path(self) -> Path:
        return self.config_home / "Claude" / "claude_desktop_config.json"


@dataclass
class Cursor(JsonFileClient):
    def path(self) -> Path:
        return self.home / ".cursor" / "mcp.json"


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=120, stdin=subprocess.DEVNULL)


@dataclass
class ClaudeCode(Client):
    def executable(self) -> str | None:
        return shutil.which("claude", path=self.env.get("PATH"))

    def detected(self) -> bool:
        return self.executable() is not None

    def add_command(self, executable: str = "claude") -> list[str]:
        command = [executable, "mcp", "add", "--transport", "stdio", "--scope", "user"]
        if self.env.get("GIMP_MCP_SOCKET"):
            command += ["--env", f"GIMP_MCP_SOCKET={self.env['GIMP_MCP_SOCKET']}"]
        return [*command, SERVER_NAME, "--", *self.server]

    def plan(self) -> Change | None:
        executable = self.executable()
        assert executable is not None
        if _run([executable, "mcp", "get", SERVER_NAME], self.env).returncode == 0:
            raise AlreadyThere(
                f"Claude Code already has a '{SERVER_NAME}' server (see `claude mcp get {SERVER_NAME}`); left "
                f"unchanged. To replace it: `claude mcp remove {SERVER_NAME} --scope user`, then run setup again."
            )
        command = self.add_command(executable)

        def apply() -> None:
            proc = _run(command, self.env)
            if proc.returncode != 0:
                raise ClientError(f"`{shlex.join(command)}` failed: {(proc.stderr or proc.stdout).strip()}")

        return Change(f"Claude Code: run `{shlex.join(self.add_command())}`", apply)

    def removal(self) -> Change | None:
        executable = self.executable()
        assert executable is not None
        found = _run([executable, "mcp", "get", SERVER_NAME], self.env)
        if found.returncode != 0:
            return None
        if "gimp-mcp" not in found.stdout and "gimp_mcp" not in found.stdout:
            raise AlreadyThere(f"Claude Code: the '{SERVER_NAME}' server was not created by gimp-mcp; left")
        command = [executable, "mcp", "remove", SERVER_NAME, "--scope", "user"]

        def apply() -> None:
            proc = _run(command, self.env)
            if proc.returncode != 0:
                raise ClientError(f"`{shlex.join(command)}` failed: {(proc.stderr or proc.stdout).strip()}")

        return Change(f"Claude Code: run `claude mcp remove {SERVER_NAME} --scope user`", apply)

    def snippet(self) -> str:
        return f"Claude Code: {shlex.join(self.add_command())}"


@dataclass
class VSCode(Client):
    def executable(self) -> str | None:
        return shutil.which("code", path=self.env.get("PATH"))

    def detected(self) -> bool:
        return self.executable() is not None

    def payload(self) -> dict[str, Any]:
        entry = server_entry(self.server, self.env)
        return {"name": SERVER_NAME, "type": "stdio", **entry}

    def user_config(self) -> Path:
        # VS Code's user profile directory on Linux (only read, to stay idempotent).
        return self.config_home / "Code" / "User" / "mcp.json"

    def plan(self) -> Change | None:
        try:
            current = json.loads(self.user_config().read_text()).get("servers", {}).get(SERVER_NAME)
        except (OSError, ValueError, AttributeError):
            current = None
        payload = self.payload()
        expected = {k: v for k, v in payload.items() if k != "name"}
        if current == expected:
            return None
        executable = self.executable()
        assert executable is not None
        command = [executable, "--add-mcp", json.dumps(payload, separators=(",", ":"))]

        def apply() -> None:
            proc = _run(command, self.env)
            if proc.returncode != 0:
                raise ClientError(f"`code --add-mcp` failed: {(proc.stderr or proc.stdout).strip()}")

        return Change(f"VS Code: run `code --add-mcp '{command[-1]}'`", apply)

    def removal(self) -> Change | None:
        path = self.user_config()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        entry = (data.get("servers") or {}).get(SERVER_NAME) if isinstance(data, dict) else None
        if entry is None:
            return None
        if not is_ours(entry):
            raise AlreadyThere(f"VS Code: the '{SERVER_NAME}' server was not created by gimp-mcp; left")
        new = dict(data)
        new["servers"] = {k: v for k, v in data["servers"].items() if k != SERVER_NAME}
        return Change(
            f"VS Code: remove the '{SERVER_NAME}' server from {path} (backup kept next to it)",
            lambda: write_json_with_backup(path, new),
        )

    def snippet(self) -> str:
        return f"VS Code: code --add-mcp '{json.dumps(self.payload(), separators=(',', ':'))}'"


class AlreadyThere(Exception):
    """The client has an entry we must not overwrite."""


def clients_for(env: dict[str, str], server: list[str]) -> list[Client]:
    return [
        ClaudeCode("claude-code", "Claude Code", env, server),
        ClaudeDesktop("claude-desktop", "Claude Desktop", env, server),
        VSCode("vscode", "VS Code", env, server),
        Cursor("cursor", "Cursor", env, server),
    ]


CLIENT_KEYS = ("claude-code", "claude-desktop", "vscode", "cursor")


# -- steps ------------------------------------------------------------------------------


@dataclass
class Outcome:
    failures: int = 0
    snippets: list[str] = field(default_factory=list)


def _probe(options: SetupOptions) -> Probe:
    from .doctor import Probe

    return Probe(env=options.env, endpoint=options.endpoint, gimp_dir=options.gimp_dir)


def step_gimp(options: SetupOptions) -> tuple[bool, Path]:
    from .doctor import Context, Status, check_gimp

    ctx = Context(_probe(options))
    found = check_gimp(ctx)
    options.say(f"{'✓' if found.status is Status.OK else '✗'} {found.message}")
    if found.status is not Status.OK:
        options.say(f"  → {found.fix}")
        return False, ctx.active_profile()
    return True, ctx.active_profile()


def installed_profiles(options: SetupOptions, active: Path) -> list[Path]:
    """Every known GIMP profile that has the plug-in (the active one first)."""
    from .doctor import Context, _has_plugin, _profiles

    ctx = Context(_probe(options))
    profiles = [p for p in _profiles(ctx) if _has_plugin(p)]
    return sorted(profiles, key=lambda p: p != active)


def _installed_version(directory: Path) -> str | None:
    try:
        return (directory / "VERSION").read_text().strip() or None
    except OSError:
        return None


def step_plugin(options: SetupOptions, profile: Path) -> None:
    targets = [profile] + [p for p in installed_profiles(options, profile) if p != profile]
    restart = False
    for target in targets:
        directory = installed_plugin_dir(target)
        present = (directory / f"{PLUGIN_NAME}.py").exists()
        installed = _installed_version(directory)
        if present and installed == __version__:
            options.say(f"✓ plug-in {__version__} up to date in {directory}")
            continue
        install_plugin(target)
        restart = True
        if not present:
            action = "installed"
        elif installed is None:
            action = "updated from an older version"
        else:
            action = f"updated from {installed}"
        options.say(f"✓ plug-in {__version__} {action} in {directory}")
    if restart:
        options.say("  → restart GIMP (or start it) so it loads the plug-in")


def step_clients(options: SetupOptions, server: list[str], outcome: Outcome) -> None:
    wanted = options.clients if options.clients is not None else set(CLIENT_KEYS)
    for client in clients_for(options.env, server):
        if client.key not in wanted:
            continue
        if not client.detected():
            outcome.snippets.append(client.snippet())
            continue
        try:
            change = client.plan()
        except AlreadyThere as exc:
            options.say(f"✓ {exc}")
            continue
        except ClientError as exc:
            outcome.failures += 1
            options.say(f"✗ {client.name}: {exc}")
            continue
        if change is None:
            options.say(f"✓ {client.name}: already configured")
            continue
        options.say(change.description)
        if options.assume_yes:
            consent = True
        elif options.interactive:
            consent = options.ask(f"Apply this change to {client.name}? [y/N] ")
        else:
            options.say("  skipped: run `gimp-mcp setup --yes` to apply it, or apply it yourself")
            consent = False
        if not consent:
            outcome.snippets.append(client.snippet())
            continue
        try:
            change.apply()
            options.say(f"✓ {client.name}: configured (restart it to load the server)")
        except ClientError as exc:
            outcome.failures += 1
            options.say(f"✗ {client.name}: {exc}")


async def step_live(options: SetupOptions) -> None:
    client = BridgeClient(options.endpoint, connect_timeout=3)
    try:
        session = await client.connect()
        options.say(f"✓ GIMP {session.gimp_version} answers (plug-in {session.bridge_version})")
    except GimpMcpError as error:
        options.say(f"• live check: {error.code}: {error.message}")
        if error.hint:
            options.say(f"  → {error.hint}")
    finally:
        await client.close()


async def run_setup(options: SetupOptions) -> int:
    ok, profile = step_gimp(options)
    if not ok:
        return 1
    options.say(f"✓ GIMP profile: {profile}")
    step_plugin(options, profile)
    server = options.server or server_command(env=options.env)
    options.say(f"✓ MCP server command: {shlex.join(server)}")
    outcome = Outcome()
    step_clients(options, server, outcome)
    if outcome.snippets:
        options.say("Clients not configured automatically — add the server yourself:")
        for snippet in outcome.snippets:
            options.say(snippet)
    await step_live(options)
    if options.run_doctor:
        from .doctor import render_text, run_checks

        options.say(render_text(await run_checks(_probe(options))))
    return 1 if outcome.failures else 0


def removal_hint(prefix: str | None = None) -> str:
    """How the user removes the package itself, depending on how it was installed."""
    where = (prefix or sys.prefix).replace(os.sep, "/")
    if "/uv/tools/" in where:
        return "uv tool uninstall gimp-mcp"
    if "/pipx/" in where:
        return "pipx uninstall gimp-mcp"
    if "/uv/archive-v" in where or "/.cache/uv/" in where:
        return "nothing to uninstall (run through uvx); `uv cache clean gimp-mcp` frees the cache"
    return "uv tool uninstall gimp-mcp (or pipx uninstall gimp-mcp / pip uninstall gimp-mcp, as you installed it)"


def _confirm(options: SetupOptions, description: str, question: str) -> bool:
    options.say(description)
    if options.assume_yes:
        return True
    if options.interactive:
        return options.ask(question)
    options.say("  skipped: run with --yes to apply it")
    return False


def active_profile(options: SetupOptions) -> Path:
    """The profile GIMP uses; works without GIMP installed (uninstall must)."""
    from .doctor import Context, check_gimp

    ctx = Context(_probe(options))
    check_gimp(ctx)  # sets the GIMP series when GIMP is there
    return ctx.active_profile()


async def run_uninstall(options: SetupOptions) -> int:
    from .installer import uninstall_plugin

    failures = 0
    removed = 0
    for target in installed_profiles(options, active_profile(options)):
        directory = installed_plugin_dir(target)
        if _confirm(options, f"Plug-in: remove {directory}", f"Remove the plug-in from {target}? [y/N] "):
            uninstall_plugin(target)
            removed += 1
            options.say(f"✓ removed {directory}")
    wanted = options.clients if options.clients is not None else set(CLIENT_KEYS)
    for client in clients_for(options.env, options.server or server_command(env=options.env)):
        if client.key not in wanted or not client.detected():
            continue
        try:
            change = client.removal()
        except AlreadyThere as exc:
            options.say(f"• {exc}")
            continue
        except ClientError as exc:
            failures += 1
            options.say(f"✗ {client.name}: {exc}")
            continue
        if change is None:
            continue
        if _confirm(options, change.description, f"Apply this change to {client.name}? [y/N] "):
            try:
                change.apply()
                removed += 1
                options.say(f"✓ {client.name}: entry removed (restart it)")
            except ClientError as exc:
                failures += 1
                options.say(f"✗ {client.name}: {exc}")
    if removed == 0 and failures == 0:
        options.say("Nothing to remove: no plug-in and no client entry created by gimp-mcp were found.")
    elif removed:
        options.say("Restart GIMP and the MCP clients so they forget gimp-mcp.")
    options.say(f"Left for you: the gimp-mcp package itself — {removal_hint()}.")
    return 1 if failures else 0

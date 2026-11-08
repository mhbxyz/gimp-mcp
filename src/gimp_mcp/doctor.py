"""`gimp-mcp doctor`: find out why gimp-mcp does not work, and say how to fix it.

Each check returns a status (ok, warn, fail, skip), what was found and a
concrete fix. All access to the machine goes through a `Probe` (executables,
commands, processes, environment), so every check is unit tested against
simulated environments. `CHECKS` is also the source of
`docs/troubleshooting.md`.

Exit codes: 0 = no failure (warnings allowed), 1 = at least one failure,
2 = the doctor itself could not run.
"""

from __future__ import annotations

import enum
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, platforms
from .bridge import FLATPAK_APP, BridgeClient, BridgeEndpoint, parse_version
from .errors import GimpMcpError
from .headless import system_path
from .installer import PLUGIN_NAME, installed_plugin_dir
from .versions import Compatibility, check_plugin_version

MIN_GIMP = (3, 2)


class Status(enum.Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class CheckSpec:
    id: str
    title: str
    fix: str


CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec(
        "gimp",
        "GIMP 3.2 or newer is installed",
        "Install GIMP 3.2 or newer from your distribution (e.g. `sudo pacman -S gimp`); gimp-mcp needs "
        "`gimp-console` on PATH or GIMP_MCP_GIMP_CONSOLE pointing to it.",
    ),
    CheckSpec(
        "gimp-python",
        "GIMP's Python can load PyGObject and the GIMP typelib",
        "Install PyGObject for the system Python and GIMP's introspection data (Arch: `python-gobject`; "
        "Debian/Ubuntu: `python3-gi gir1.2-gimp-3.0`; Fedora: `python3-gobject`).",
    ),
    CheckSpec(
        "venv-path",
        "No virtualenv shadows the system python3",
        "Start GIMP from your desktop or from a shell without the virtualenv (`deactivate`): GIMP runs "
        "Python plug-ins with the first `python3` on PATH.",
    ),
    CheckSpec(
        "profiles",
        "The plug-in is installed in the GIMP profile actually used",
        "Run `gimp-mcp install-plugin --gimp-dir <profile used by GIMP>` (default ~/.config/GIMP/3.2, or "
        "$GIMP3_DIRECTORY).",
    ),
    CheckSpec(
        "plugin",
        "The bridge plug-in is installed and executable",
        "Run `gimp-mcp install-plugin`, then restart GIMP.",
    ),
    CheckSpec(
        "plugin-version",
        "The installed plug-in matches the server version",
        "Run `gimp-mcp install-plugin` with the gimp-mcp you use as MCP server, then restart GIMP.",
    ),
    CheckSpec(
        "plugin-registered",
        "GIMP has registered the plug-in",
        "Restart GIMP. If the plug-in is still not registered, GIMP could not run it: see the gimp-python "
        "and venv-path checks, and GIMP's error console.",
    ),
    CheckSpec(
        "socket-permissions",
        "The bridge socket directory and token are private",
        "Restart GIMP to recreate them, or fix them: `chmod 700 <socket dir>` and `chmod 600 <token file>` "
        "(they must belong to you).",
    ),
    CheckSpec(
        "connection",
        "A running GIMP answers on the bridge socket",
        "Start GIMP (after `gimp-mcp install-plugin`). If GIMP is already running, restart it so it loads the plug-in.",
    ),
    CheckSpec(
        "instances",
        "Only one GIMP instance competes for the bridge socket",
        "Close the extra GIMP instances, or give each one its own socket with GIMP_MCP_SOCKET (set it for "
        "GIMP and for `gimp-mcp serve`).",
    ),
)
SPECS = {spec.id: spec for spec in CHECKS}


@dataclass
class Result:
    id: str
    status: Status
    message: str
    fix: str = ""

    @property
    def title(self) -> str:
        return SPECS[self.id].title

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "message": self.message,
            "fix": self.fix if self.status in (Status.FAIL, Status.WARN) else "",
        }


def result(check: str, status: Status, message: str, fix: str | None = None) -> Result:
    return Result(check, status, message, fix if fix is not None else SPECS[check].fix)


@dataclass
class Probe:
    """Access to the machine. Tests override it with scripted answers."""

    env: dict[str, str]
    endpoint: BridgeEndpoint
    gimp_dir: Path | None = None

    def which(self, name: str) -> str | None:
        return shutil.which(name, path=self.env.get("PATH"))

    def run(self, args: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=60, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, str(exc)
        return proc.returncode, proc.stdout + proc.stderr

    def gimp_processes(self) -> list[tuple[int, str]] | None:
        """GIMP main processes of this user (not its plug-ins); None where the OS cannot list them here."""
        return platforms.gimp_processes()


@dataclass
class Context:
    probe: Probe
    console: str | None = None
    gimp_series: str | None = None
    flatpak: bool = False
    results: list[Result] = field(default_factory=list)

    @property
    def home(self) -> Path:
        return Path(self.probe.env.get("HOME") or Path.home())

    def active_profile(self) -> Path:
        if self.probe.gimp_dir is not None:
            return self.probe.gimp_dir
        env = {**self.probe.env, "HOME": str(self.home)}
        return Path(platforms.gimp_profile_dir(env, series=self.gimp_series or platforms.GIMP_SERIES))


def check_gimp(ctx: Context) -> Result:
    explicit = ctx.probe.env.get("GIMP_MCP_GIMP_CONSOLE")
    candidates = [explicit] if explicit else platforms.gimp_console_candidates(ctx.probe.env)
    ctx.console = next((path for name in candidates if (path := ctx.probe.which(name))), None)
    if ctx.console is None:
        flatpak = check_flatpak_gimp(ctx)
        if flatpak is not None:
            return flatpak
        return result("gimp", Status.FAIL, "gimp-console (GIMP 3) was not found on PATH, nor a Flatpak GIMP")
    code, output = ctx.probe.run([ctx.console, "--version"])
    match = re.search(r"(\d+\.\d+\.\d+)", output)
    if code != 0 or match is None:
        return result("gimp", Status.FAIL, f"`{ctx.console} --version` failed: {output.strip()[:200]}")
    version = match.group(1)
    ctx.gimp_series = ".".join(version.split(".")[:2])
    if parse_version(version)[:2] < MIN_GIMP:
        return result("gimp", Status.FAIL, f"GIMP {version} is too old (3.2 or newer is required)")
    return result("gimp", Status.OK, f"GIMP {version} ({ctx.console})")


def check_flatpak_gimp(ctx: Context) -> Result | None:
    """GIMP installed from Flathub (org.gimp.GIMP), user or system installation."""
    flatpak = ctx.probe.which("flatpak")
    if flatpak is None:
        return None
    code, output = ctx.probe.run([flatpak, "info", FLATPAK_APP])
    match = re.search(r"Version:\s*(\d+\.\d+\.\d+)", output)
    if code != 0 or match is None:
        return None
    version = match.group(1)
    ctx.flatpak = True
    ctx.gimp_series = ".".join(version.split(".")[:2])
    if parse_version(version)[:2] < MIN_GIMP:
        return result("gimp", Status.FAIL, f"Flatpak GIMP {version} is too old (3.2 or newer is required)")
    return result("gimp", Status.OK, f"GIMP {version} (Flatpak {FLATPAK_APP})")


GI_PROBE = "import gi; gi.require_version('Gimp', '3.0'); from gi.repository import Gimp; print('ok')"


def check_gimp_python(ctx: Context) -> Result:
    if ctx.flatpak:
        flatpak = ctx.probe.which("flatpak") or "flatpak"
        code, output = ctx.probe.run([flatpak, "run", "--command=python3", FLATPAK_APP, "-c", GI_PROBE])
        if code != 0:
            last = output.strip().splitlines()[-1] if output.strip() else f"exit code {code}"
            return result(
                "gimp-python",
                Status.FAIL,
                f"Flatpak GIMP's python3 cannot import GIMP's bindings: {last}",
                "Update the Flatpak: `flatpak update org.gimp.GIMP`.",
            )
        return result("gimp-python", Status.OK, "Flatpak GIMP's python3 imports gi and the Gimp 3.0 typelib")
    env = dict(ctx.probe.env)
    env["PATH"] = system_path(env.get("PATH", ""))
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    bundled = platforms.bundled_gimp_python(ctx.console) if ctx.console else None
    if bundled:  # macOS and Windows: GIMP runs plug-ins with the Python of its own bundle
        code, output = ctx.probe.run([bundled, "-c", GI_PROBE], env=env)
        if code != 0:
            last = output.strip().splitlines()[-1] if output.strip() else f"exit code {code}"
            return result("gimp-python", Status.FAIL, f"GIMP's bundled Python ({bundled}) cannot import gi: {last}",
                          "Reinstall GIMP 3.2 from gimp.org.")  # fmt: skip
        return result("gimp-python", Status.OK, f"GIMP's bundled Python ({bundled}) imports gi and Gimp 3.0")
    code, output = ctx.probe.run(["/usr/bin/env", "python3", "-c", GI_PROBE], env=env)
    if code != 0:
        last = output.strip().splitlines()[-1] if output.strip() else f"exit code {code}"
        return result("gimp-python", Status.FAIL, f"python3 cannot import GIMP's bindings: {last}")
    return result("gimp-python", Status.OK, "python3 imports gi and the Gimp 3.0 typelib")


def check_venv_path(ctx: Context) -> Result:
    if ctx.flatpak:
        return result("venv-path", Status.OK, "Flatpak GIMP uses its own Python: not affected by PATH")
    if ctx.console and platforms.bundled_gimp_python(ctx.console):
        return result("venv-path", Status.OK, "GIMP uses the Python of its own bundle: not affected by PATH")
    # Ignore the environment running gimp-mcp itself: `uvx`/`uv run` put it first on
    # PATH for this process only; it is not the user's shell.
    own = os.path.realpath(Path(sys.prefix) / "bin")
    python = ctx.probe.which("python3")
    if python is not None and os.path.realpath(Path(python).parent) == own:
        others = [e for e in ctx.probe.env.get("PATH", "").split(os.pathsep) if e and os.path.realpath(e) != own]
        python = next((str(Path(e) / "python3") for e in others if (Path(e) / "python3").exists()), None)
    if python is None:
        return result("venv-path", Status.OK, "no python3 on this shell's PATH")
    root = Path(python).parent.parent
    if (root / "pyvenv.cfg").exists():
        return result(
            "venv-path",
            Status.WARN,
            f"the first python3 on PATH is a virtualenv ({root}): a GIMP started from this shell cannot run "
            "Python plug-ins, including the bridge",
        )
    return result("venv-path", Status.OK, f"python3 is {python}")


def _profiles(ctx: Context) -> list[Path]:
    env = {**ctx.probe.env, "HOME": str(ctx.home)}
    flatpak = platforms.flatpak_gimp_profile_root(env)
    roots = [Path(platforms.config_home(env)) / "GIMP", *([Path(flatpak)] if flatpak else [])]
    found = [
        path
        for root in roots
        if root.is_dir()
        for path in sorted(root.iterdir())
        if re.fullmatch(r"\d+\.\d+", path.name)
    ]
    active = ctx.active_profile()
    if active not in found:
        found.append(active)
    return found


def _has_plugin(profile: Path) -> bool:
    return (installed_plugin_dir(profile) / f"{PLUGIN_NAME}.py").exists()


def check_profiles(ctx: Context) -> Result:
    active = ctx.active_profile()
    profiles = _profiles(ctx)
    listing = ", ".join(
        f"{p}{' (used)' if p == active else ''}{' [plug-in]' if _has_plugin(p) else ''}" for p in profiles
    )
    elsewhere = [p for p in profiles if p != active and _has_plugin(p)]
    if not _has_plugin(active) and elsewhere:
        return result(
            "profiles",
            Status.WARN,
            f"the plug-in is installed in {', '.join(map(str, elsewhere))} but GIMP uses {active}. Profiles: {listing}",
            f"Run `gimp-mcp install-plugin --gimp-dir {active}`.",
        )
    return result("profiles", Status.OK, f"profiles: {listing}")


def check_plugin(ctx: Context) -> Result:
    directory = installed_plugin_dir(ctx.active_profile())
    entry = directory / f"{PLUGIN_NAME}.py"
    if not entry.exists():
        return result("plugin", Status.FAIL, f"the bridge plug-in is not installed in {directory}")
    if not os.access(entry, os.X_OK):
        return result(
            "plugin",
            Status.FAIL,
            f"{entry} is not executable: GIMP will ignore it",
            f"Run `gimp-mcp install-plugin` (or `chmod +x {entry}`), then restart GIMP.",
        )
    return result("plugin", Status.OK, f"installed in {directory}")


def check_plugin_version_file(ctx: Context) -> Result:
    directory = installed_plugin_dir(ctx.active_profile())
    if not (directory / f"{PLUGIN_NAME}.py").exists():
        return result("plugin-version", Status.SKIP, "no plug-in installed")
    try:
        installed = (directory / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        installed = "unknown"
    verdict = check_plugin_version(__version__, installed)
    message = f"installed plug-in {installed}, server {__version__}: {verdict.value}"
    status = {Compatibility.MATCH: Status.OK, Compatibility.COMPATIBLE: Status.WARN}.get(verdict, Status.FAIL)
    return result("plugin-version", status, message)


def check_plugin_registered(ctx: Context) -> Result:
    pluginrc = ctx.active_profile() / "pluginrc"
    if not pluginrc.exists():
        return result("plugin-registered", Status.SKIP, "GIMP has not been started with this profile yet")
    # the path separator is "/" on Linux and macOS, "\\" (escaped in the file) on Windows
    if re.search(rf"{PLUGIN_NAME}[/\\\\]+{PLUGIN_NAME}\.py".encode(), pluginrc.read_bytes()):
        return result("plugin-registered", Status.OK, f"listed in {pluginrc}")
    return result(
        "plugin-registered",
        Status.WARN,
        f"GIMP has not registered the plug-in in {pluginrc} (installed after GIMP started, or GIMP failed to run it)",
    )


def check_socket_permissions(ctx: Context) -> Result:
    if ctx.probe.endpoint.is_pipe:
        return result("socket-permissions", Status.SKIP, "Windows named pipe: access is limited by its ACL")
    socket_dir = ctx.probe.endpoint.socket_path.parent
    token = ctx.probe.endpoint.token_path
    if not socket_dir.exists():
        return result("socket-permissions", Status.SKIP, f"{socket_dir} does not exist yet")
    problems = []
    info = socket_dir.stat()
    if info.st_uid != os.getuid():
        problems.append(f"{socket_dir} belongs to uid {info.st_uid}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        problems.append(f"{socket_dir} has mode {stat.S_IMODE(info.st_mode):04o} (expected 0700)")
    if token.exists():
        mode = stat.S_IMODE(token.stat().st_mode)
        if mode & 0o077:
            problems.append(f"{token} has mode {mode:04o} (expected 0600)")
        if not os.access(token, os.R_OK):
            problems.append(f"{token} is not readable")
    if problems:
        return result("socket-permissions", Status.FAIL, "; ".join(problems))
    return result("socket-permissions", Status.OK, f"{socket_dir} is private")


async def check_connection(ctx: Context) -> Result:
    endpoint = ctx.probe.endpoint
    client = BridgeClient(endpoint, connect_timeout=3)
    try:
        session = await client.connect()
    except GimpMcpError as error:
        return _connection_failure(ctx, error)
    finally:
        await client.close()
    return result(
        "connection",
        Status.OK,
        f"GIMP {session.gimp_version} answers (session {session.session_id}, plug-in {session.bridge_version})",
    )


def _connection_failure(ctx: Context, error: GimpMcpError) -> Result:
    endpoint = ctx.probe.endpoint
    running = ctx.probe.gimp_processes() or []
    if error.code == "PLUGIN_VERSION_MISMATCH":
        return result(
            "connection",
            Status.FAIL,
            f"GIMP answers but its plug-in is {error.details.get('plugin_version')} (server "
            f"{error.details.get('server_version')}): incompatible",
            SPECS["plugin-version"].fix,
        )
    pids = ", ".join(str(pid) for pid, _ in running)
    # (a Unix socket file can stay behind; a Windows pipe cannot, and statting it would connect to it)
    if error.code == "GIMP_NOT_RUNNING" and not endpoint.is_pipe and endpoint.socket_path.exists():
        # nothing listens on this socket: the GIMP that created it exited, whatever else runs
        message = f"stale socket {endpoint.socket_path}: the GIMP that created it exited"
        fix = "Start GIMP."
        if running:
            message += f" (another GIMP is running, pid {pids}: it may use another socket)"
            fix = "Restart GIMP, or point the server at the socket of the running GIMP (GIMP_MCP_SOCKET)."
        return result("connection", Status.FAIL, message, fix)
    if error.code == "GIMP_NOT_RUNNING" and running:
        return result(
            "connection",
            Status.FAIL,
            f"GIMP is running (pid {pids}) but its bridge does not answer on {endpoint.socket_path}",
            "Install the plug-in (`gimp-mcp install-plugin`) and restart GIMP; check that GIMP and the server "
            "use the same GIMP_MCP_SOCKET.",
        )
    if error.code == "GIMP_NOT_RUNNING":
        return result("connection", Status.FAIL, f"GIMP is not running (no socket at {endpoint.socket_path})")
    if error.code == "UNAUTHORIZED":
        return result(
            "connection",
            Status.FAIL,
            "the token file does not match the running bridge",
            "Restart GIMP to regenerate the socket and the token.",
        )
    return result("connection", Status.FAIL, f"{error.code}: {error.message}", error.hint or SPECS["connection"].fix)


def check_instances(ctx: Context) -> Result:
    running = ctx.probe.gimp_processes()
    if running is None:
        return result("instances", Status.SKIP, "GIMP processes cannot be listed on this OS yet")
    if len(running) > 1:
        pids = ", ".join(f"{pid} ({name})" for pid, name in running)
        return result(
            "instances",
            Status.WARN,
            f"{len(running)} GIMP processes are running ({pids}); only one can own {ctx.probe.endpoint.socket_path}",
        )
    return result("instances", Status.OK, f"{len(running)} GIMP process(es) running")


async def run_checks(probe: Probe) -> list[Result]:
    ctx = Context(probe)
    sync_checks = (
        check_gimp,
        check_gimp_python,
        check_venv_path,
        check_profiles,
        check_plugin,
        check_plugin_version_file,
        check_plugin_registered,
        check_socket_permissions,
    )
    results = [check(ctx) for check in sync_checks]
    results.append(await check_connection(ctx))
    results.append(check_instances(ctx))
    return results


LABELS = {Status.OK: "[ok]  ", Status.WARN: "[WARN]", Status.FAIL: "[FAIL]", Status.SKIP: "[skip]"}


def render_text(results: list[Result]) -> str:
    lines = []
    for item in results:
        lines.append(f"{LABELS[item.status]} {item.title}: {item.message}")
        if item.status in (Status.FAIL, Status.WARN):
            lines.append(f"       fix: {item.fix}")
    failures = sum(item.status is Status.FAIL for item in results)
    warnings = sum(item.status is Status.WARN for item in results)
    lines.append(f"gimp-mcp {__version__}: {failures} failure(s), {warnings} warning(s)")
    return "\n".join(lines)


def render_json(results: list[Result]) -> str:
    return json.dumps(
        {
            "ok": not any(item.status is Status.FAIL for item in results),
            "server_version": __version__,
            "checks": [item.to_dict() for item in results],
        },
        indent=2,
    )


def exit_code(results: list[Result]) -> int:
    return 1 if any(item.status is Status.FAIL for item in results) else 0


def render_troubleshooting() -> str:
    """docs/troubleshooting.md, derived from CHECKS."""
    lines = [
        "# Troubleshooting",
        "",
        "<!-- Generated from src/gimp_mcp/doctor.py (CHECKS) by `gimp-mcp doctor --troubleshooting`. -->",
        "",
        "Run `gimp-mcp doctor` first: it runs the checks below in order and prints, for each failure or",
        "warning, what it found and how to fix it. `gimp-mcp doctor --json` gives the same result for scripts.",
        "",
        "Exit codes: `0` no failure (warnings allowed), `1` at least one failure, `2` the doctor could not run.",
        "",
        "| Check | What it verifies | Fix when it fails |",
        "|---|---|---|",
    ]
    lines += [f"| `{spec.id}` | {spec.title} | {spec.fix} |" for spec in CHECKS]
    lines.append("")
    return "\n".join(lines)


async def run_doctor(probe: Probe, as_json: bool = False) -> tuple[int, str]:
    results = await run_checks(probe)
    return exit_code(results), (render_json(results) if as_json else render_text(results))

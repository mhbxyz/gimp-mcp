"""Command line entry point: ``gimp-mcp [serve|install-plugin|uninstall-plugin|doctor]``.

stdout is reserved for the MCP protocol when serving; everything else goes to
stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .bridge import BridgeClient, BridgeEndpoint
from .errors import GimpMcpError
from .installer import default_gimp_config_dir, install_plugin, uninstall_plugin


def _endpoint(socket: str | None) -> BridgeEndpoint:
    """The bridge endpoint; an explicit --socket keeps this OS's token rule (and GIMP_MCP_TOKEN_FILE)."""
    return BridgeEndpoint.default({**os.environ, "GIMP_MCP_SOCKET": socket} if socket else None)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import build_server
    from .toolsets import ToolsetError

    endpoint = (
        BridgeEndpoint.default({**os.environ, "GIMP_MCP_SOCKET": args.socket})
        if args.socket
        else BridgeEndpoint.default()
    )
    try:
        server = build_server(BridgeClient(endpoint, request_timeout=args.timeout), toolsets=args.toolsets)
    except ToolsetError as error:
        print(f"gimp-mcp serve: {error}", file=sys.stderr)
        return 2
    _configure_logging(args.verbose)
    server.run("stdio")
    return 0


def cmd_toolsets(args: argparse.Namespace) -> int:
    from .toolsets import render_report, toolset_report

    entries = toolset_report()
    print(render_report(entries))
    for entry in entries:
        print(f"\n{entry.name}: {entry.description}\n  " + ", ".join(entry.tools))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    config = Path(args.gimp_dir) if args.gimp_dir else default_gimp_config_dir()
    target = install_plugin(config)
    print(f"Installed the gimp-mcp bridge plug-in into {target}", file=sys.stderr)
    print("Restart GIMP to load it.", file=sys.stderr)
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    config = Path(args.gimp_dir) if args.gimp_dir else default_gimp_config_dir()
    removed = uninstall_plugin(config)
    print("Removed." if removed else f"Nothing installed in {config}.", file=sys.stderr)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    import os

    from .doctor import Probe, render_troubleshooting, run_doctor

    if args.troubleshooting:
        sys.stdout.write(render_troubleshooting())
        return 0
    endpoint = (
        BridgeEndpoint.default({**os.environ, "GIMP_MCP_SOCKET": args.socket})
        if args.socket
        else BridgeEndpoint.default()
    )
    probe = Probe(env=dict(os.environ), endpoint=endpoint, gimp_dir=Path(args.gimp_dir) if args.gimp_dir else None)
    try:
        code, output = asyncio.run(run_doctor(probe, as_json=args.json))
    except Exception as exc:  # the doctor must never crash silently
        print(f"error: the doctor could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(output, file=sys.stdout if args.json else sys.stderr)
    return code


def cmd_inventory(args: argparse.Namespace) -> int:
    import json

    endpoint = (
        BridgeEndpoint.default({**os.environ, "GIMP_MCP_SOCKET": args.socket})
        if args.socket
        else BridgeEndpoint.default()
    )

    async def fetch() -> dict[str, object]:
        client = BridgeClient(endpoint, request_timeout=args.timeout)
        try:
            return await client.call("pdb.inventory")
        finally:
            await client.close()

    data = asyncio.run(fetch())
    procedures = data["procedures"]
    assert isinstance(procedures, list)
    text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        incomplete = sum(1 for p in procedures if "error" in p)
        print(
            f"{len(procedures)} procedures ({incomplete} with incomplete metadata) written to {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    from .coverage import render_matrix

    text = render_matrix(Path(args.inventory))
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


_ASCII_SYMBOLS = str.maketrans({"\u2713": "+", "\u2717": "x", "\u2192": "->"})


def printable(text: str, encoding: str | None) -> str:
    """``text`` as the stream can print it: setup's symbols become ASCII where the encoding lacks them
    (a redirected Windows console is cp1252), and anything else unprintable becomes ``?``."""
    encoding = encoding or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.translate(_ASCII_SYMBOLS).encode(encoding, errors="replace").decode(encoding)


def cmd_setup(args: argparse.Namespace) -> int:
    import os

    from .setup import CLIENT_KEYS, SetupOptions, run_setup

    endpoint = (
        BridgeEndpoint.default({**os.environ, "GIMP_MCP_SOCKET": args.socket})
        if args.socket
        else BridgeEndpoint.default()
    )
    clients: set[str]
    if args.clients in (None, "all"):
        clients = set(CLIENT_KEYS)
    elif args.clients == "none":
        clients = set()
    else:
        clients = {name.strip() for name in args.clients.split(",") if name.strip()}
        unknown = clients - set(CLIENT_KEYS)
        if unknown:
            print(f"error: unknown client(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    def ask(question: str) -> bool:
        try:
            return input(question).strip().lower().startswith("y")
        except EOFError:
            return False

    def say(text: str) -> None:
        print(printable(text, sys.stderr.encoding), file=sys.stderr)

    options = SetupOptions(
        env=dict(os.environ),
        endpoint=endpoint,
        ask=ask,
        say=say,
        assume_yes=args.yes,
        interactive=sys.stdin.isatty() and not args.yes,
        run_doctor=not args.no_doctor,
        gimp_dir=Path(args.gimp_dir) if args.gimp_dir else None,
        clients=clients,
    )
    return asyncio.run(run_setup(options))


def cmd_uninstall_all(args: argparse.Namespace) -> int:
    import os

    from .setup import SetupOptions, run_uninstall

    def ask(question: str) -> bool:
        try:
            return input(question).strip().lower().startswith("y")
        except EOFError:
            return False

    def say(text: str) -> None:
        print(printable(text, sys.stderr.encoding), file=sys.stderr)

    options = SetupOptions(
        env=dict(os.environ),
        endpoint=BridgeEndpoint.default(),
        ask=ask,
        say=say,
        assume_yes=args.yes,
        interactive=sys.stdin.isatty() and not args.yes,
        run_doctor=False,
        gimp_dir=Path(args.gimp_dir) if args.gimp_dir else None,
    )
    return asyncio.run(run_uninstall(options))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gimp-mcp", description="MCP server for GIMP 3")
    parser.add_argument("--version", action="version", version=f"gimp-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the MCP server on stdio (default)")
    serve.add_argument("--socket", help="bridge socket path (default: $GIMP_MCP_SOCKET or runtime dir)")
    serve.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds")
    serve.add_argument("-v", "--verbose", action="store_true", help="debug logs on stderr")
    serve.add_argument(
        "--toolsets",
        help="comma-separated toolsets to list (default: $GIMP_MCP_TOOLSETS or 'default'; "
        "'all' for everything; see `gimp-mcp toolsets`)",
    )
    serve.set_defaults(func=cmd_serve)

    toolsets = sub.add_parser("toolsets", help="list the toolsets, their tools and the size of their definitions")
    toolsets.set_defaults(func=cmd_toolsets)

    for name, func, text in (
        ("install-plugin", cmd_install, "install the bridge plug-in into GIMP's config directory"),
        ("uninstall-plugin", cmd_uninstall, "remove the bridge plug-in"),
    ):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--gimp-dir", help="GIMP config dir (default: $GIMP3_DIRECTORY or ~/.config/GIMP/3.2)")
        cmd.set_defaults(func=func)

    doctor = sub.add_parser(
        "doctor",
        help="diagnose the installation and the connection to GIMP (exit 0 ok, 1 failures, 2 doctor error)",
    )
    doctor.add_argument("--socket")
    doctor.add_argument("--gimp-dir", help="GIMP profile to check (default: the one GIMP uses)")
    doctor.add_argument("--json", action="store_true", help="machine-readable result on stdout")
    doctor.add_argument("--troubleshooting", action="store_true", help="print the troubleshooting table (Markdown)")
    doctor.set_defaults(func=cmd_doctor)

    setup = sub.add_parser(
        "setup",
        help="install the plug-in in GIMP's profile and register the server in your MCP clients",
        description=(
            "Detect GIMP, install or update the plug-in, register the MCP server in Claude Code, Claude Desktop, "
            "VS Code and Cursor (each change is shown and needs your consent), then check the result. Safe to "
            "run again."
        ),
    )
    setup.add_argument("--yes", action="store_true", help="apply every change without asking (for scripts)")
    setup.add_argument(
        "--clients",
        help="comma-separated clients to configure: claude-code, claude-desktop, vscode, cursor; or all / none "
        "(default: all)",
    )
    setup.add_argument("--gimp-dir", help="GIMP profile (default: the one GIMP uses)")
    setup.add_argument("--socket", help="bridge socket path (default: $GIMP_MCP_SOCKET or runtime dir)")
    setup.add_argument("--no-doctor", action="store_true", help="skip the final doctor checks")
    setup.set_defaults(func=cmd_setup)

    uninstall = sub.add_parser(
        "uninstall",
        help="remove the plug-in from every GIMP profile and the MCP client entries gimp-mcp created",
        description=(
            "Remove what gimp-mcp added: the plug-in in every GIMP profile where it is installed and the 'gimp' "
            "entries it created in MCP clients (entries pointing elsewhere are left). Each removal is shown and "
            "needs your consent (or --yes). The package itself is removed with your installer (printed at the end)."
        ),
    )
    uninstall.add_argument("--yes", action="store_true", help="remove without asking")
    uninstall.add_argument("--gimp-dir", help="also consider this GIMP profile")
    uninstall.set_defaults(func=cmd_uninstall_all)

    inventory = sub.add_parser("inventory", help="dump the procedure database of the running GIMP as JSON")
    inventory.add_argument("--socket")
    inventory.add_argument("--output", help="file to write (default: stdout)")
    inventory.add_argument("--timeout", type=float, default=300.0)
    inventory.set_defaults(func=cmd_inventory)

    coverage = sub.add_parser("coverage", help="render the coverage matrix (Markdown) from an inventory")
    coverage.add_argument("--inventory", required=True)
    coverage.add_argument("--output")
    coverage.set_defaults(func=cmd_coverage)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["serve", *(argv or [])])
    try:
        return args.func(args)
    except GimpMcpError as error:
        print(f"error: {error}", file=sys.stderr)
        if error.hint:
            print(f"hint: {error.hint}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

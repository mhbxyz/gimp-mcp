# Installation (Linux)

## Prerequisites

| Requirement | Version | Check |
|---|---|---|
| Linux | any recent distribution | — |
| GIMP | **3.2 or newer** (verified: 3.2.6) | `gimp --version` |
| GIMP Python support (PyGObject for the system Python) | the one GIMP is built with | `/usr/bin/python3 -c "import gi; gi.require_version('Gimp', '3.0')"` |
| Python for the MCP server | 3.11+ | `python3 --version` |
| [uv](https://docs.astral.sh/uv/) (recommended) | 0.9+ | `uv --version` |

On Arch: `pacman -S gimp python-gobject`. GIMP from Flathub
(`flatpak install flathub org.gimp.GIMP`) works too, with nothing more to
install: it brings its own Python, and `setup`/`doctor` detect it. On Debian/Ubuntu make sure the
distribution ships GIMP ≥ 3.2 (older 3.0 builds are refused with
`VERSION_INCOMPATIBLE`). 

## Install

From PyPI (once published; see `docs/releasing.md`):

```sh
uv tool install gimp-mcp      # or: pipx install gimp-mcp
gimp-mcp install-plugin
# or without installing anything: uvx gimp-mcp install-plugin, and `uvx gimp-mcp serve` as MCP command
```

From a release (wheel attached to the GitHub release):

```sh
uv tool install ./gimp_mcp-0.1.0-py3-none-any.whl   # or: pipx install ./gimp_mcp-…whl
gimp-mcp install-plugin      # copies the plug-in into ~/.config/GIMP/3.2/plug-ins/
```

From a checkout:

```sh
uv sync
uv run gimp-mcp install-plugin
```

Then **restart GIMP**. The bridge starts with GIMP; nothing is shown in the UI.
Use `--gimp-dir DIR` (or `GIMP3_DIRECTORY`) for a non-default GIMP profile.
After upgrading gimp-mcp, run `gimp-mcp install-plugin` again and restart GIMP
(plug-in and server must have the same version).

This procedure is verified from a clean environment by
`tests/e2e/test_distribution.py` (fresh virtualenv, installed wheel, plug-in
installed by the packaged CLI, `doctor`, MCP calls, uninstall) in the CI's
pinned GIMP container.

## One-command setup

```sh
gimp-mcp setup          # interactive: shows each change and asks
gimp-mcp setup --yes    # scripts: applies everything
```

It finds GIMP and the profile it uses (`GIMP3_DIRECTORY` respected), installs
or updates the plug-in, registers the server in the MCP clients it finds
(see [clients.md](clients.md)), prints snippets for the others, and ends with a
live check and `gimp-mcp doctor`. Options: `--clients claude-code,claude-desktop,vscode,cursor|all|none`,
`--gimp-dir`, `--socket`, `--no-doctor`. Running it again changes nothing that
is already right. The manual steps below remain available.

## Configure an MCP client

The server speaks MCP over stdio. With an installed package:

```json
{"mcpServers": {"gimp": {"command": "gimp-mcp", "args": ["serve"]}}}
```

From a checkout:

```json
{"mcpServers": {"gimp": {"command": "uv", "args": ["--directory", "/path/to/gimp-mcp", "run", "gimp-mcp", "serve"]}}}
```

Claude Code: `claude mcp add gimp -- gimp-mcp serve`.
Options: `--socket PATH` (or `GIMP_MCP_SOCKET`), `--timeout SECONDS`,
`--verbose` (debug logs on stderr). `GIMP_MCP_PREVIEW_MAX_SIZE` and
`GIMP_MCP_PREVIEW_MAX_BYTES` tune previews.

## Launch GIMP

Start GIMP normally (`gimp`); the bridge is ready when `gimp-mcp doctor`
reports the connection. For automation without a window, the
`gimp_mcp.headless.HeadlessGimp` class starts an isolated `gimp-console` with
the plug-in (used by the tests and by `uv run demo/thumbnail.py`).

## Check

```sh
uv run gimp-mcp doctor
```

prints, on stderr, whether `gimp-console` is found, whether the plug-in is
installed and whether a running GIMP answers on the socket.

## Upgrade

| Installed with | Upgrade the package | Then |
|---|---|---|
| `uv tool install gimp-mcp` | `uv tool upgrade gimp-mcp` | `gimp-mcp setup` |
| `pipx install gimp-mcp` | `pipx upgrade gimp-mcp` | `gimp-mcp setup` |
| `uvx gimp-mcp …` | nothing (`uvx` takes the latest; setup pins the version it configured) | `uvx gimp-mcp setup` |
| a wheel from a GitHub release | `uv tool install --force ./gimp_mcp-X.Y.Z-py3-none-any.whl` | `gimp-mcp setup` |
| a checkout | `git pull && uv sync` | `uv run gimp-mcp setup` |

`setup` updates the plug-in in **every** GIMP profile where it is installed
and tells you to restart GIMP. A plug-in left at another MAJOR.MINOR version is
never used silently: every tool fails with `PLUGIN_VERSION_MISMATCH` and
`gimp-mcp doctor` reports it.

## Uninstall

```sh
gimp-mcp uninstall           # shows each removal and asks; --yes to remove everything
```

It removes the plug-in from every GIMP profile where it is installed and the
`gimp` entries gimp-mcp created in Claude Code, Claude Desktop, VS Code and
Cursor (backups kept; entries named `gimp` that run something else are left).
It does not touch GIMP's profiles otherwise, nor other servers. It ends by
printing what is left for you:

| Installed with | Remove the package |
|---|---|
| `uv tool install` | `uv tool uninstall gimp-mcp` |
| `pipx install` | `pipx uninstall gimp-mcp` |
| `uvx` | nothing; `uv cache clean gimp-mcp` frees the cache |
| a checkout | delete the directory |

Restart GIMP and your MCP clients afterwards. The socket and token in
`$XDG_RUNTIME_DIR/gimp-mcp/` disappear with the session. The older
`gimp-mcp uninstall-plugin` (plug-in of one profile only) still works.

## Troubleshooting

Run `gimp-mcp doctor`: it checks GIMP, GIMP's Python, the profile and the
plug-in, the socket permissions, the connection and concurrent GIMP instances,
and prints how to fix each problem it finds (`--json` for scripts; exit code 1
when something fails). The list of checks and their fixes is in
[troubleshooting.md](troubleshooting.md), generated from the doctor itself.

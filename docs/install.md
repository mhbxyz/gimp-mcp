# Installation (Linux)

## Prerequisites

| Requirement | Version | Check |
|---|---|---|
| Linux | any recent distribution | — |
| GIMP | **3.2 or newer** (verified: 3.2.6) | `gimp --version` |
| GIMP Python support (PyGObject for the system Python) | the one GIMP is built with | `/usr/bin/python3 -c "import gi; gi.require_version('Gimp', '3.0')"` |
| Python for the MCP server | 3.11+ | `python3 --version` |
| [uv](https://docs.astral.sh/uv/) (recommended) | 0.9+ | `uv --version` |

On Arch: `pacman -S gimp python-gobject`. On Debian/Ubuntu make sure the
distribution ships GIMP ≥ 3.2 (older 3.0 builds are refused with
`VERSION_INCOMPATIBLE`). Flatpak GIMP is not supported yet (sandboxed runtime
directory).

## Install

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

## Uninstall

```sh
gimp-mcp uninstall-plugin    # removes the plug-in; restart GIMP
uv tool uninstall gimp-mcp   # removes the server (or pipx uninstall gimp-mcp)
```

Nothing else is left: the socket and token are recreated by GIMP at each start
in `$XDG_RUNTIME_DIR/gimp-mcp/`, which the system clears at logout.

See also [compatibility.md](compatibility.md) for supported versions and the
compatibility policy.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `GIMP_NOT_RUNNING` | GIMP is not running, the plug-in is not installed, or GIMP was restarted without it. Run `gimp-mcp doctor`. |
| `BRIDGE_UNAVAILABLE` | GIMP is frozen or busy (modal dialog, long filter). Retry later. |
| `VERSION_INCOMPATIBLE` | GIMP older than 3.2, or plug-in from another gimp-mcp version: reinstall the plug-in and restart GIMP. |
| `ModuleNotFoundError: gi` in GIMP's console | GIMP was started from a shell with a virtualenv active; start it normally. |
| Two GIMP instances | Only the first one gets the bridge (`BRIDGE_ALREADY_RUNNING` in the second one's console). Set `GIMP_MCP_SOCKET` per instance to run several. |

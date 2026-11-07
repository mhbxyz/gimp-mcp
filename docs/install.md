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

From a checkout:

```sh
uv sync
uv run gimp-mcp install-plugin      # copies the plug-in into ~/.config/GIMP/3.2/plug-ins/
```

Then **restart GIMP**. The bridge starts with GIMP; nothing is shown in the UI.
Use `--gimp-dir DIR` (or `GIMP3_DIRECTORY`) for a non-default GIMP profile.

## Configure an MCP client

The server speaks MCP over stdio:

```json
{
  "mcpServers": {
    "gimp": {
      "command": "uv",
      "args": ["--directory", "/path/to/gimp-mcp", "run", "gimp-mcp", "serve"]
    }
  }
}
```

Claude Code: `claude mcp add gimp -- uv --directory /path/to/gimp-mcp run gimp-mcp serve`.

## Check

```sh
uv run gimp-mcp doctor
```

prints, on stderr, whether `gimp-console` is found, whether the plug-in is
installed and whether a running GIMP answers on the socket.

## Uninstall

```sh
uv run gimp-mcp uninstall-plugin    # then restart GIMP
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `GIMP_NOT_RUNNING` | GIMP is not running, the plug-in is not installed, or GIMP was restarted without it. Run `gimp-mcp doctor`. |
| `BRIDGE_UNAVAILABLE` | GIMP is frozen or busy (modal dialog, long filter). Retry later. |
| `VERSION_INCOMPATIBLE` | GIMP older than 3.2, or plug-in from another gimp-mcp version: reinstall the plug-in and restart GIMP. |
| `ModuleNotFoundError: gi` in GIMP's console | GIMP was started from a shell with a virtualenv active; start it normally. |
| Two GIMP instances | Only the first one gets the bridge (`BRIDGE_ALREADY_RUNNING` in the second one's console). Set `GIMP_MCP_SOCKET` per instance to run several. |

# MCP client configuration

`gimp-mcp setup` registers the server under the name `gimp` in the clients it
finds. Each change is shown first and applied only with your consent (or
`--yes`); entries of other servers are never modified. The formats below were
checked in each client's official documentation on 2026-11-08.

| Client | How setup configures it | Detected when | Source |
|---|---|---|---|
| Claude Code | `claude mcp add --transport stdio --scope user gimp -- <command> serve` (user scope: `~/.claude.json`). An existing `gimp` entry (`claude mcp get gimp`) is left unchanged. | `claude` is on PATH | <https://code.claude.com/docs/en/mcp> |
| Claude Desktop | merges `mcpServers.gimp = {"command", "args"}` into `claude_desktop_config.json` (location per OS below), after a timestamped backup | its configuration folder exists | <https://modelcontextprotocol.io/docs/develop/connect-local-servers> |
| VS Code | `code --add-mcp '{"name":"gimp","type":"stdio","command":…,"args":["serve"]}'` (user profile `mcp.json`, top-level key `servers`) | `code` is on PATH | <https://code.visualstudio.com/docs/agents/reference/mcp-configuration> |
| Cursor | merges `mcpServers.gimp` into `.cursor/mcp.json` in your home folder, after a timestamped backup | `.cursor/` exists in your home folder | <https://cursor.com/docs/context/mcp> |

Where each file is, per OS (`~` is your home folder: `%USERPROFILE%` on Windows):

| File | Linux | macOS | Windows |
|---|---|---|---|
| GIMP 3.2 profile (plug-in in `plug-ins/gimp-mcp-bridge/`) | `~/.config/GIMP/3.2` (`$XDG_CONFIG_HOME/GIMP/3.2`) | `~/Library/Application Support/GIMP/3.2` | `%APPDATA%\GIMP\3.2` |
| Claude Desktop | `~/.config/Claude/claude_desktop_config.json` (`$XDG_CONFIG_HOME/Claude/...`) | `~/Library/Application Support/Claude/claude_desktop_config.json` | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `~/.cursor/mcp.json` | `~/.cursor/mcp.json` | `%USERPROFILE%\.cursor\mcp.json` |
| VS Code user `mcp.json` (read only) | `~/.config/Code/User/mcp.json` | `~/Library/Application Support/Code/User/mcp.json` | `%APPDATA%\Code\User\mcp.json` |
| Claude Code | `~/.claude.json`, through `claude mcp` | same | same |

`GIMP3_DIRECTORY` (or `--gimp-dir`) replaces the GIMP profile on every OS. On Windows the home folder
is `%USERPROFILE%` even when `HOME` is set (Git Bash and MSYS2 set it). The unit tests run setup and
uninstall on each OS's own locations, and `tests/e2e/test_setup.py` runs the command written for Claude
Desktop on Linux, macOS and Windows, from a path with a space and a non-ASCII letter, and lists its tools.

Notes:

* The command is **absolute** (GUI clients do not inherit your shell's PATH).
  When setup runs through `uvx`, the command is
  `uvx --from gimp-mcp==<version> gimp-mcp serve`, pinned to the version of the
  plug-in it just installed.
* If `GIMP_MCP_SOCKET` is set when you run setup, it is added to the entry.
* Not verified: the location of VS Code's user `mcp.json` is not documented;
  setup only *reads* it (table above) to avoid adding the same entry twice, and
  writes through `code --add-mcp`.
* On Windows the command is the `gimp-mcp.exe` launcher of the environment it is
  installed in (`Scripts\gimp-mcp.exe`).
* A client configuration that is not valid JSON is never overwritten: setup
  reports it and exits with code 1.

To load fewer tools (or more, like `procedures`), add `--toolsets` to the server arguments: see
[toolsets](toolsets.md#per-client).

For another client, use the snippet setup prints (stdio command
`<absolute path>/gimp-mcp serve`).

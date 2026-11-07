# MCP client configuration

`gimp-mcp setup` registers the server under the name `gimp` in the clients it
finds. Each change is shown first and applied only with your consent (or
`--yes`); entries of other servers are never modified. The formats below were
checked in each client's official documentation on 2026-11-08.

| Client | How setup configures it | Detected when | Source |
|---|---|---|---|
| Claude Code | `claude mcp add --transport stdio --scope user gimp -- <command> serve` (user scope: `~/.claude.json`). An existing `gimp` entry (`claude mcp get gimp`) is left unchanged. | `claude` is on PATH | <https://code.claude.com/docs/en/mcp> |
| Claude Desktop | merges `mcpServers.gimp = {"command", "args"}` into `~/.config/Claude/claude_desktop_config.json` (`$XDG_CONFIG_HOME/Claude/...`), after a timestamped backup | `~/.config/Claude/` exists | <https://modelcontextprotocol.io/docs/develop/connect-local-servers> |
| VS Code | `code --add-mcp '{"name":"gimp","type":"stdio","command":…,"args":["serve"]}'` (user profile `mcp.json`, top-level key `servers`) | `code` is on PATH | <https://code.visualstudio.com/docs/agents/reference/mcp-configuration> |
| Cursor | merges `mcpServers.gimp` into `~/.cursor/mcp.json`, after a timestamped backup | `~/.cursor/` exists | <https://cursor.com/docs/context/mcp> |

Notes:

* The command is **absolute** (GUI clients do not inherit your shell's PATH).
  When setup runs through `uvx`, the command is
  `uvx --from gimp-mcp==<version> gimp-mcp serve`, pinned to the version of the
  plug-in it just installed.
* If `GIMP_MCP_SOCKET` is set when you run setup, it is added to the entry.
* Not verified: the location of VS Code's user `mcp.json` on Linux is not
  documented; setup only *reads* `~/.config/Code/User/mcp.json` to avoid adding
  the same entry twice, and writes through `code --add-mcp`.
* A client configuration that is not valid JSON is never overwritten: setup
  reports it and exits with code 1.

For another client, use the snippet setup prints (stdio command
`<absolute path>/gimp-mcp serve`).

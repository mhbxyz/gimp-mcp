# gimp-mcp with VS Code and Cursor

## Install

1. GIMP 3.2 or newer: your distribution's package (Ubuntu 26.04: `sudo apt install gimp python3-gi
   gir1.2-gimp-3.0`; others in [compatibility](../compatibility.md#linux-distributions)) **or** the
   Flatpak from Flathub (`flatpak install flathub org.gimp.GIMP`).
2. [uv](https://docs.astral.sh/uv/getting-started/installation/), and VS Code (with the `code` command on
   PATH) and/or Cursor (opened once, so that `~/.cursor/` exists).

## Configure

<!-- doctest: vscode-cursor -->
```sh
uvx gimp-mcp setup --clients vscode,cursor   # installs the GIMP plug-in, shows each change and asks
```

For VS Code, `setup` runs `code --add-mcp` with this server (absolute, version-pinned command). By hand:

<!-- snippet: vscode -->
```json
{"name": "gimp", "type": "stdio", "command": "uvx", "args": ["gimp-mcp", "serve"]}
```

(pass it to `code --add-mcp '<json>'`, or add it under `servers` with *MCP: Open User Configuration*).
For Cursor, `setup` adds this to `~/.cursor/mcp.json` (backup kept, other servers untouched). By hand:

<!-- snippet: cursor -->
```json
{
  "mcpServers": {
    "gimp": {
      "command": "uvx",
      "args": ["gimp-mcp", "serve"]
    }
  }
}
```

Restart the editor, then start GIMP.

## First prompt

> Use GIMP to create a 1200×630 social card with a dark background and the title "Release 2.0" in white,
> then save it as ~/card.xcf and export ~/card.png.

## Check

<!-- doctest: vscode-cursor-check -->
```sh
uvx gimp-mcp doctor      # GIMP, plug-in and connection are [ok]
```

In VS Code, *MCP: List Servers* shows `gimp`; in Cursor, *Settings → MCP* lists it. See
[troubleshooting](../troubleshooting.md).

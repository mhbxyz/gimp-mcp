# gimp-mcp with Claude Desktop

## Install

1. GIMP 3.2 or newer: your distribution's package (Ubuntu 26.04: `sudo apt install gimp python3-gi
   gir1.2-gimp-3.0`; others in [compatibility](../compatibility.md#linux-distributions)) **or** the
   Flatpak from Flathub (`flatpak install flathub org.gimp.GIMP`). macOS and Windows: GIMP from
   [gimp.org](https://www.gimp.org/downloads/) ([install](../install.md)).
2. [uv](https://docs.astral.sh/uv/getting-started/installation/) and Claude Desktop (opened once, so that
   its configuration folder exists: `~/.config/Claude/`, `~/Library/Application Support/Claude/` on macOS,
   `%APPDATA%\Claude\` on Windows).

## Configure

<!-- doctest: claude-desktop -->
```sh
uvx gimp-mcp setup --clients claude-desktop   # installs the GIMP plug-in, shows the change and asks
```

`setup` adds this entry to `claude_desktop_config.json` in that folder (keeping a backup and your other
servers; it writes an absolute, version-pinned command). To do it by hand:

<!-- snippet: claude-desktop -->
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

GUI applications do not always inherit your shell's `PATH`: if Claude Desktop cannot start `uvx`, use its
absolute path (`which uvx`). Quit Claude Desktop completely and start it again, then start GIMP.

## First prompt

> Use GIMP to open ~/Pictures/photo.jpg, make it 20% brighter and export a copy to ~/photo-bright.jpg.

## Check

<!-- doctest: claude-desktop-check -->
```sh
uvx gimp-mcp doctor      # GIMP, plug-in and connection are [ok]
```

In Claude Desktop, the "+" menu → *Connectors* lists `gimp`. The server's log is
`mcp-server-gimp.log` in `~/.config/Claude/logs/` (Linux), `~/Library/Logs/Claude/` (macOS) or
`%APPDATA%\Claude\logs\` (Windows). More in [troubleshooting](../troubleshooting.md).

# gimp-mcp with any MCP client

## Install

1. GIMP 3.2 or newer: your distribution's package (Ubuntu 26.04: `sudo apt install gimp python3-gi
   gir1.2-gimp-3.0`; others in [compatibility](../compatibility.md#linux-distributions)) **or** the
   Flatpak from Flathub (`flatpak install flathub org.gimp.GIMP`). macOS and Windows: GIMP from
   [gimp.org](https://www.gimp.org/downloads/) ([install](../install.md)).
2. [uv](https://docs.astral.sh/uv/getting-started/installation/).

## Configure

Install the GIMP plug-in once, without touching any client configuration:

<!-- doctest: generic -->
```sh
uvx gimp-mcp setup --clients none   # installs the GIMP plug-in and prints configuration snippets
```

Then declare a **stdio** server in your client:

| Field | Value |
|---|---|
| command | `uvx` (or its absolute path, see `which uvx`) |
| arguments | `gimp-mcp serve` |
| environment | none needed; `GIMP_MCP_SOCKET` only to target a specific GIMP |

With a permanent installation (`uv tool install gimp-mcp`), the command is simply `gimp-mcp serve`.
Start (or restart) GIMP.

## First prompt

> Call gimp_status and tell me which images are open in GIMP.

## Check

<!-- doctest: generic-check -->
```sh
uvx gimp-mcp doctor      # GIMP, plug-in and connection are [ok]
```

The server speaks MCP on stdout and logs on stderr (`gimp-mcp serve --verbose` for debug logs). See
[troubleshooting](../troubleshooting.md).

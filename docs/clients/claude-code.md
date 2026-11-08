# gimp-mcp with Claude Code

## Install

1. GIMP 3.2 or newer: your distribution's package (Ubuntu 26.04: `sudo apt install gimp python3-gi
   gir1.2-gimp-3.0`; others in [compatibility](../compatibility.md#linux-distributions)) **or** the
   Flatpak from Flathub (`flatpak install flathub org.gimp.GIMP`). macOS and Windows: GIMP from
   [gimp.org](https://www.gimp.org/downloads/) ([install](../install.md)).
2. [uv](https://docs.astral.sh/uv/getting-started/installation/) and
   [Claude Code](https://code.claude.com/docs/en/overview).

## Configure

<!-- doctest: claude-code -->
```sh
uvx gimp-mcp setup --clients claude-code   # installs the GIMP plug-in, shows the `claude mcp add` command and asks
```

`setup` runs this command for you (with an absolute, version-pinned path). To do it by hand:

<!-- snippet: claude-code -->
```sh
claude mcp add --transport stdio --scope user gimp -- uvx gimp-mcp serve
```

Then start (or restart) GIMP.

## First prompt

> Use GIMP to list the open images, then create a 800×600 white image with a red circle in the middle and
> export it to ~/circle.png.

## Check

<!-- doctest: claude-code-check -->
```sh
claude mcp get gimp      # the server is registered
uvx gimp-mcp doctor      # GIMP, plug-in and connection are [ok]
```

Inside Claude Code, `/mcp` lists `gimp` as connected. If not, see [troubleshooting](../troubleshooting.md).

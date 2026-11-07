# gimp-mcp

<!-- mcp-name: io.github.mhbxyz/gimp-mcp -->

Let an AI assistant inspect and edit images in **your running GIMP** through the
[Model Context Protocol](https://modelcontextprotocol.io): layers, text, selections, filters, files, previews.
Linux, GIMP 3.2+. MIT licensed.

## Quickstart

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and an MCP client
(Claude Code, Claude Desktop, VS Code, Cursor…). On Ubuntu 26.04:

<!-- doctest: quickstart -->
```sh
sudo apt install -y gimp python3-gi gir1.2-gimp-3.0   # GIMP 3.2+ (other distributions and Flatpak: see below)
uvx gimp-mcp setup                                    # installs the GIMP plug-in, adds the server to your MCP clients
uvx gimp-mcp doctor                                   # after (re)starting GIMP: every check should be [ok]
```

Then ask your assistant: *"Use GIMP to create a 1280×720 image with the title 'Hello' and export it to
~/hello.png"*.

* Other distributions (Arch, Debian 14, Fedora 44, openSUSE Tumbleweed, Alpine 3.24) and their packages:
  [compatibility](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/compatibility.md#linux-distributions).
  GIMP from **Flathub** works too: `flatpak install flathub org.gimp.GIMP`, then the two `uvx` commands.
* Step-by-step per client: [Claude Code](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/clients/claude-code.md),
  [Claude Desktop](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/clients/claude-desktop.md),
  [VS Code and Cursor](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/clients/vscode-cursor.md),
  [any other MCP client](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/clients/generic.md).
* Something wrong? `uvx gimp-mcp doctor` says what and how to fix it
  ([troubleshooting](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/troubleshooting.md)).

Also listed in the [official MCP registry](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.mhbxyz/gimp-mcp)
as `io.github.mhbxyz/gimp-mcp` (from the first PyPI release on).

## What it can do

52 tools: inspect images and layer trees, previews, create/open/save XCF/export PNG and JPEG, layers and
groups, resize/crop/transform, selections and masks, painting, brightness/contrast, hue/saturation, blur
(destructive or editable filters), editable text, undo groups and checkpoints, and allowlisted access to
~420 GIMP procedures. See the [tool reference](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/tools.md)
and the [coverage matrix](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/coverage.md).

## Demo

```sh
uv run demo/thumbnail.py                 # from a checkout: isolated headless GIMP, outputs in demo/out/
```

Builds a 1280×720 thumbnail through MCP only (blurred backdrop with editable corrections, masked photo,
banner, editable title, a badge undone and redone with checkpoints), saves and reopens the XCF, exports PNG
and JPEG, and writes a report of every call and check.
Walk-through: [docs/guide-thumbnail.md](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/guide-thumbnail.md).

## Documentation

- [Installation reference](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/install.md) (manual install, upgrade, uninstall) ·
  [MCP clients](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/clients.md) ·
  [troubleshooting](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/troubleshooting.md) ·
  [compatibility](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/compatibility.md)
- [Tool reference](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/tools.md) ·
  [coverage matrix](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/coverage.md)
- [Architecture](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/architecture.md) ·
  [bridge protocol](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/bridge-protocol.md) ·
  [security](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/security.md) ·
  [decisions](https://github.com/mhbxyz/gimp-mcp/tree/main/docs/adr)
- [Testing](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/testing.md) ·
  [releasing](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/releasing.md) ·
  [GIMP behaviour notes](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/gimp-notes.md) ·
  [changelog](https://github.com/mhbxyz/gimp-mcp/blob/main/CHANGELOG.md)

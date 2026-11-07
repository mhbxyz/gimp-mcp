# gimp-mcp

<!-- mcp-name: io.github.mhbxyz/gimp-mcp -->

A reliable [Model Context Protocol](https://modelcontextprotocol.io) server for inspecting and editing
GIMP projects. It drives a **running GIMP 3.2+ session** (GUI or headless) through a small plug-in
that serves a private local socket.

> Version 0.1.0 — Linux, GIMP 3.2+. 52 MCP tools: inspection, previews, files, layers, geometry,
> selections and masks, painting, filters, editable text, undo groups and checkpoints, and allowlisted
> access to ~420 GIMP procedures ([coverage](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/coverage.md)). MIT licensed.

## Quick start

```sh
uv tool install ./gimp_mcp-0.1.0-py3-none-any.whl   # wheel from the GitHub release (or `uv sync` in a checkout)
gimp-mcp setup                                       # plug-in + MCP clients, guided; then restart GIMP
```

`setup` installs the plug-in in the GIMP profile you use, registers the server in Claude Code, Claude Desktop,
VS Code and Cursor when they are installed (asking before each change), and checks the result.
`gimp-mcp doctor` diagnoses any remaining problem.

Then ask the client to call `gimp_status`.

Also listed in the [official MCP registry](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.mhbxyz/gimp-mcp)
as `io.github.mhbxyz/gimp-mcp` (from the first PyPI release on).

## Demo

```sh
uv run demo/thumbnail.py                 # isolated headless GIMP, outputs in demo/out/
uv run demo/thumbnail.py --socket PATH   # or drive your running GIMP
```

Builds a 1280×720 thumbnail (blurred backdrop with editable corrections,
masked photo, banner, editable title edited afterwards), saves the XCF,
reopens it, exports PNG and JPEG and writes `demo/out/report.md` with every MCP
call and verification. Walk-through: [docs/guide-thumbnail.md](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/guide-thumbnail.md).

## Documentation

- [Installation](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/install.md) · [troubleshooting](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/troubleshooting.md) · [compatibility](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/compatibility.md) · [releasing](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/releasing.md) · [changelog](https://github.com/mhbxyz/gimp-mcp/blob/main/CHANGELOG.md)
- [Tool reference and error codes](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/tools.md) · [coverage matrix](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/coverage.md)
- [Architecture](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/architecture.md) · [bridge protocol](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/bridge-protocol.md) · [security](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/security.md)
- [Testing](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/testing.md) · [GIMP behaviour notes](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/gimp-notes.md) · [decisions](https://github.com/mhbxyz/gimp-mcp/blob/main/docs/adr/)

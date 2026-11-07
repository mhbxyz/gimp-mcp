# gimp-mcp

A reliable [Model Context Protocol](https://modelcontextprotocol.io) server for inspecting and editing
GIMP projects. It drives a **running GIMP 3.2+ session** (GUI or headless) through a small plug-in
that serves a private local socket.

> Version 0.1.0 — Linux, GIMP 3.2+. 52 MCP tools: inspection, previews, files, layers, geometry,
> selections and masks, painting, filters, editable text, undo groups and checkpoints, and allowlisted
> access to ~420 GIMP procedures ([coverage](docs/coverage.md)). MIT licensed.

## Quick start

```sh
uv tool install ./gimp_mcp-0.1.0-py3-none-any.whl   # wheel from the GitHub release (or `uv sync` in a checkout)
gimp-mcp install-plugin                              # then restart GIMP
gimp-mcp doctor                                      # checks GIMP, the plug-in and the connection
```

Register the server in your MCP client (stdio):

```sh
claude mcp add gimp -- gimp-mcp serve
```

Then ask the client to call `gimp_status`.

## Demo

```sh
uv run demo/thumbnail.py                 # isolated headless GIMP, outputs in demo/out/
uv run demo/thumbnail.py --socket PATH   # or drive your running GIMP
```

Builds a 1280×720 thumbnail (blurred backdrop with editable corrections,
masked photo, banner, editable title edited afterwards), saves the XCF,
reopens it, exports PNG and JPEG and writes `demo/out/report.md` with every MCP
call and verification. Walk-through: [docs/guide-thumbnail.md](docs/guide-thumbnail.md).

## Documentation

- [Installation and troubleshooting](docs/install.md) · [compatibility](docs/compatibility.md) · [releasing](docs/releasing.md) · [changelog](CHANGELOG.md)
- [Tool reference and error codes](docs/tools.md) · [coverage matrix](docs/coverage.md)
- [Architecture](docs/architecture.md) · [bridge protocol](docs/bridge-protocol.md) · [security](docs/security.md)
- [Testing](docs/testing.md) · [GIMP behaviour notes](docs/gimp-notes.md) · [decisions](docs/adr/)

# gimp-mcp

A reliable [Model Context Protocol](https://modelcontextprotocol.io) server for inspecting and editing
GIMP projects. It drives a **running GIMP 3.2+ session** (GUI or headless) through a small plug-in
that serves a private local socket.

> Status: early development. Linux only. See the [tool reference](docs/tools.md) for what is available.

## Quick start

```sh
uv sync
uv run gimp-mcp install-plugin    # then restart GIMP
uv run gimp-mcp doctor            # checks GIMP, the plug-in and the connection
```

Register the server in your MCP client (stdio):

```sh
claude mcp add gimp -- uv --directory /path/to/gimp-mcp run gimp-mcp serve
```

Then ask the client to call `gimp_status`.

## Documentation

- [Installation and troubleshooting](docs/install.md)
- [Tool reference and error codes](docs/tools.md)
- [Architecture](docs/architecture.md) · [bridge protocol](docs/bridge-protocol.md) · [security](docs/security.md)
- [Testing](docs/testing.md) · [GIMP behaviour notes](docs/gimp-notes.md) · [decisions](docs/adr/)

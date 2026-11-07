# ADR 0004 — List gimp-mcp in the official MCP registry; no desktop bundle

- Status: accepted (2026-11-08)
- Context issue: #43

## Context (checked 2026-11-08)

* The **official MCP registry** (<https://github.com/modelcontextprotocol/registry>,
  preview, API frozen at v0.1) lists servers published with the `mcp-publisher`
  CLI from a `server.json` (schema
  `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`).
  Names under `io.github.<user>/` are authenticated with GitHub, including
  **GitHub Actions OIDC** (`mcp-publisher login github-oidc`, verified with
  v1.8.3). PyPI packages prove ownership with an `mcp-name: <server name>` line
  (or HTML comment) in the README.
* **MCP Bundles** (`.mcpb`, formerly DXT,
  <https://github.com/modelcontextprotocol/mcpb>) give single-click install, but
  the project names only Claude for **macOS and Windows** as installing them,
  and Python bundles either ship compiled dependencies (not portable) or use the
  `uv` server type.

## Decision

* Publish `server.json` (name `io.github.mhbxyz/gimp-mcp`, PyPI package
  `gimp-mcp`, `runtimeHint: uvx`, stdio, optional `GIMP_MCP_SOCKET`) to the
  official registry from `release.yml` (`publish-mcp-registry`), after PyPI is
  verified, behind the `pypi` environment approval, with GitHub OIDC (no token)
  and a pinned `mcp-publisher` (v1.8.3).
* `server.json` is versioned in the repository, validated against the vendored
  schema in unit tests (`ci/schemas/`) and by `mcp-publisher validate` before
  publishing; `scripts/prepare_release.py` bumps its versions.
* **Rejected: an MCPB bundle.** gimp-mcp supports Linux only and the bundle
  format targets Claude for macOS/Windows; a bundle would also still need the
  GIMP plug-in installed by `gimp-mcp setup`. Revisit if gimp-mcp supports
  those systems or MCPB clients appear on Linux.

## Consequences

* The listing appears after the first published release; the registry is in
  preview, so data resets are possible (re-run `publish-mcp-registry`).
* Clients that read the registry start the server with `uvx gimp-mcp`; users
  still run `uvx gimp-mcp setup` once for the GIMP plug-in.

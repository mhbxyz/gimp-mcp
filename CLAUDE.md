# gimp-mcp

MCP server (Python, `mcp` 2.x `MCPServer`, stdio) driving a running GIMP 3.2+ through a persistent
GIMP plug-in serving a Unix socket. Read `docs/architecture.md` and `docs/adr/` first; GIMP facts
verified so far live in `docs/gimp-notes.md` (add to it, don't re-discover).

## Commands

- Install deps: `uv sync`
- Fast tests (no GIMP): `uv run pytest tests/unit`
- End-to-end (real headless GIMP): `uv run pytest tests/e2e` (`GIMP_MCP_REQUIRE_GIMP=1` to fail when GIMP is absent)
- Lint/format/types: `uv run ruff check . && uv run ruff format --check . && uv run pyright`
- Demo: `uv run demo/thumbnail.py` (headless GIMP, outputs + report in `demo/out/`)
- Guided install (writes client configs! use a temporary HOME when testing): `uv run gimp-mcp setup`
- Troubleshooting doc (generated): `uv run gimp-mcp doctor --troubleshooting > docs/troubleshooting.md`
- Coverage matrix: `uv run gimp-mcp coverage --inventory docs/coverage/pdb-inventory.json --output docs/coverage.md`
- Run the server: `uv run gimp-mcp serve` · install the plug-in: `uv run gimp-mcp install-plugin` · diagnose: `uv run gimp-mcp doctor`

## Rules

- `src/gimp_mcp/plugin/gimp-mcp-bridge/` runs on GIMP's system Python: stdlib + `gi` only. Only
  `gmb_ops.py` may call the GIMP API; `gmb_server.py` must stay GIMP-free (unit tested).
- Operations raise `BridgeError` before mutating; never claim non-destructive/atomic/undoable without a test.
- stdout of the server is MCP-only; log to stderr.
- TDD: failing test first. Unit tests use `tests/unit/fake_bridge.py`; e2e use `tests/e2e/conftest.py` fixtures.
- Never run GIMP from a venv-first PATH for plug-ins (see `gimp_mcp.headless.system_path`).

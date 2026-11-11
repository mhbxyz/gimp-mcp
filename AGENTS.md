# gimp-mcp

MCP server (Python, `mcp` 2.x `MCPServer`, stdio) driving a running GIMP 3.2+ through a persistent
GIMP plug-in serving a Unix socket. Read `docs/architecture.md` and `docs/adr/` first; GIMP facts
verified so far live in `docs/gimp-notes.md` (add to it, don't re-discover).

## Commands

- Install deps: `uv sync`
- Fast tests (no GIMP): `uv run pytest tests/unit`
- End-to-end (real headless GIMP): `uv run pytest tests/e2e` (`GIMP_MCP_REQUIRE_GIMP=1` to fail when GIMP is absent)
- Lint/format/types: `uv run ruff check . && uv run ruff format --check . && uv run pyright`
- Demos: `uv run demo/run.py <scenario>|--all` (headless GIMP, outputs + report in `demo/out/<scenario>/`; `demo/README.md`); videos: `demo/video/record.sh VERSION [SCENARIO]`
- Release: `scripts/prepare_release.py X.Y.Z` (opens the release PR; merging it tags and starts release.yml). Dry run: `gh workflow run release.yml -f dry_run=true --ref main`
- Guided install (writes client configs! use a temporary HOME when testing): `uv run gimp-mcp setup`
- Agent evaluation (real Claude Code in Docker, costs tokens: one task at a time while developing): `uv run evals/run.py <task>|--all` (`docs/evals/README.md`)
- Generated docs, never edited by hand:
  - troubleshooting: `uv run gimp-mcp doctor --troubleshooting > docs/troubleshooting.md`
  - coverage matrix: `uv run gimp-mcp coverage --inventory docs/coverage/pdb-inventory.json --output docs/coverage.md`
  - public API snapshot: `uv run scripts/api_contract.py write` (docs/api/contract.json; CI classifies its changes)
- Run the server: `uv run gimp-mcp serve` · install the plug-in: `uv run gimp-mcp install-plugin` · diagnose: `uv run gimp-mcp doctor`

## Rules

- `src/gimp_mcp/plugin/gimp-mcp-bridge/` runs on GIMP's system Python: stdlib + `gi` only. Only
  `gmb_ops.py` may call the GIMP API; `gmb_server.py` stays GIMP-free (unit tested).
- Operations raise `BridgeError` before mutating; claim non-destructive/atomic/undoable only with a test proving it.
- stdout of the server is MCP-only; log to stderr.
- New tools go in a toolset (`docs/toolsets.md`) within the default-selection budget; PDB access goes
  through the `gmb_policy.py` allowlist.
- Launch GIMP for plug-ins with the system PATH (`gimp_mcp.headless.system_path`), never venv-first.
- Anything touching user configuration is tested with temporary `HOME`, `XDG_CONFIG_HOME` and
  `GIMP3_DIRECTORY`; the machine's real GIMP, Claude and editor configurations stay untouched.

## Workflow

- TDD: failing test first, vertical slices. Unit tests use `tests/unit/fake_bridge.py`; e2e use
  `tests/e2e/conftest.py` fixtures and verify results independently (pixels re-read, files read with
  another library, values known in advance).
- Each change also updates `docs/tools.md`, the generated docs above when affected, `CHANGELOG.md`
  under `## [Unreleased]`, and an ADR in `docs/adr/` for any design decision that binds later work.
- One issue, one branch, one English PR ("Closes #N"), squash-merged once CI is green. Acceptance
  criteria are then ticked on the issue, each with a link to its proof (test, doc or CI run). A
  criterion GIMP cannot meet stays unticked with the proof and a follow-up issue in a later milestone.
- Long test runs go in a `git worktree`, so no branch switches under a running process.

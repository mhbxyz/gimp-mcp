# Testing

```sh
uv run pytest tests/unit          # fast, no GIMP needed
uv run pytest tests/e2e           # real GIMP 3 (headless), ~5 s startup per GIMP
uv run pytest                     # everything
GIMP_MCP_REQUIRE_GIMP=1 uv run pytest   # fail (instead of skip) when GIMP is missing (CI)
```

## Seams

| Seam | Tests | Catches | Misses |
|---|---|---|---|
| MCP tool surface, in-process (`mcp.Client(build_server(...))`) against the real plug-in socket server with scripted operations (`tests/unit/fake_bridge.py`) | `tests/unit/test_*_tool*.py` | tool schemas, argument validation, id encoding, structured errors | real GIMP behaviour |
| Bridge client ↔ plug-in socket server (both real code, GIMP operations stubbed) | `tests/unit/test_bridge_client.py` | handshake, token, version checks, timeouts, disconnections, ordering, session pinning | GIMP API usage |
| stdio process contract | `tests/unit/test_stdio_contract.py` | stdout purity, logs on stderr, behaviour without GIMP | — |
| End to end: `mcp` stdio client → `gimp-mcp serve` → headless GIMP | `tests/e2e/` | real GIMP behaviour: pixels, layer trees, files on disk | GUI-only behaviour |

End-to-end assertions are on verifiable facts (dimensions, layer trees, pixel
values read back from exported files, XCF reopened), never on aesthetics.

## Isolation

`gimp_mcp.headless.HeadlessGimp` starts `gimp-console --no-interface
--new-instance` with:

* a temporary `GIMP3_DIRECTORY` (no personal settings, plug-ins or files),
* the plug-in installed by the real installer,
* a private socket (`GIMP_MCP_SOCKET`) in `$XDG_RUNTIME_DIR` (short path),
* `DISPLAY`/`WAYLAND_DISPLAY` removed and virtualenvs stripped from `PATH`,
* its own process group, killed on teardown; the temporary tree is removed.

GIMP's console output is kept in `<tmp>/gimp.log`; start failures include its
tail in the error details.

## Headless limits

Everything runs without a display (`gimp-console`). GUI-only behaviour
(display shells, dialogs) is not covered by automated tests; the bridge was
verified manually against the GUI build (see ADR 0001).

## Continuous integration

`.github/workflows/ci.yml` runs two jobs on every push and pull request:

| Job | Environment | What |
|---|---|---|
| `fast` | Ubuntu 24.04, Python 3.12, **no GIMP** | ruff, pyright, `tests/unit` |
| `e2e` | Docker image `ci/Dockerfile`: Arch Linux pinned to the Arch Linux Archive snapshot **2026/10/15** → **GIMP 3.2.6-2**, PyGObject 3.58.1, Python 3.14, GEGL 0.4.72 | the whole suite with `GIMP_MCP_REQUIRE_GIMP=1` |

The snapshot pins *every* package, so the GIMP version only changes when the
`ARCH_SNAPSHOT` build argument is bumped (do it deliberately, in its own PR).

Reproduce the CI locally (needs Docker):

```sh
ci/run-e2e.sh                 # build the image, run everything
ci/run-e2e.sh tests/e2e -x    # extra pytest arguments
```

### Diagnosing a failure

* A failing end-to-end test report contains a `GIMP log (...)` section with
  the tail of every live GIMP's console output.
* `GIMP_MCP_LOG_DIR=<dir>` keeps each GIMP's full console log after the test
  (the CI uploads `ci-artifacts/` — logs and `junit.xml` — when a job fails).
* `GIMP_MCP_GIMP_CONSOLE=<executable>` selects a specific `gimp-console`.

### GIMP missing

Without `gimp-console`, end-to-end tests are **skipped** with the reason
`GIMP 3 (gimp-console) not found on PATH` (visible in the `-ra` summary). With
`GIMP_MCP_REQUIRE_GIMP=1` (always set in CI) they **fail** instead, so a broken
GIMP installation can never look like a green build
(`tests/unit/test_gimp_requirement.py`).

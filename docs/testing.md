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

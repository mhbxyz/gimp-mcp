# Demos

Each demo is a **scenario** (`demo/scenarios/<name>.py`): a typical GIMP job done through MCP only,
with factual checks on what it produces (sizes, layer trees, editable text, pixels, files read back
with Pillow), never an aesthetic judgement. It has two versions:

* **scripted**: `uv run demo/run.py <name>` makes the tool calls itself, in an isolated headless GIMP
  (or yours with `--socket`), and writes its outputs, previews and `report.md` (every call, every
  check) in `demo/out/<name>/`. `uv run demo/run.py --all` runs them all; CI runs them all on a real
  GIMP on Linux, macOS and Windows (`tests/e2e/test_demo_scenarios.py`).
* **agent**: one natural-language prompt (`uv run demo/run.py --prompt <name>`) given to a real
  Claude Code session on a virtual desktop, recorded as a video:
  `CLAUDE_CODE_OAUTH_TOKEN=... demo/video/record.sh VERSION <name>` ([video/README.md](video/README.md)).

| Scenario | What it does | Toolsets |
|---|---|---|
| `thumbnail` | 1280×720 video thumbnail from one photo: blurred backdrop, vignetted subject, editable title re-typed after a change of mind, a badge added as one undo step then undone and redone with checkpoints; XCF reopened, PNG and JPEG exported | files, layers, transform, selection, paint, filters, text, history |

## Writing a scenario

A module in `demo/scenarios/` that defines `SCENARIO = Scenario(...)` (`demo/harness.py`):

* `toolsets`: only these are listed by the server, so the scenario proves they are enough;
* `assets`: files of `demo/assets/`, each with a source and a license in
  [assets/LICENSES.md](assets/LICENSES.md) (a scenario with an unlisted asset is refused);
* `outputs`: the files its scripted version writes;
* `steps(gimp, report)`: the scripted version, `gimp.call(...)` for each tool call and
  `report.check(description, passed, detail)` for each verification;
* `prompt` and `agent_output`: the agent version's request and the file it exports into `~/out`.

Add a row to the table above (a test checks every scenario is listed).

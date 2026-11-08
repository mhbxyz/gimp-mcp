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
| `old-photo-restoration` | A tilted, dusty, scratched, faded scan straightened, cropped, healed (heal and clone), leveled and denoised; 16-bit TIFF at 300 dpi and a web JPEG ([page](../docs/demos/old-photo-restoration.md)) | files, layers, transform, painting, color, effects, modes, formats, document |
| `product-cutout` | A bottle cut out of its studio backdrop (fuzzy select, refined edge, layer mask), soft contact shadow on pure white, centered on 2000×2000 with a 5% margin; JPEG and WebP at 2000, 800 and 400 px with an sRGB profile ([page](../docs/demos/product-cutout.md)) | files, layers, transform, selection, paint, filters, channels, formats, modes, analysis |
| `social-media-kit` | One design (photo, brand band and colors, logo, editable headline) in four formats: post, story, banner, thumbnail, each with safe-area guides, saved as XCF and exported as PNG ([page](../docs/demos/social-media-kit.md)) | files, layers, transform, paint, text, document |
| `thumbnail` | 1280×720 video thumbnail from one photo: blurred backdrop, vignetted subject, editable title re-typed after a change of mind, a badge added as one undo step then undone and redone with checkpoints; XCF reopened, PNG and JPEG exported | files, layers, transform, selection, paint, filters, text, history |

## Writing a scenario

A module in `demo/scenarios/` that defines `SCENARIO = Scenario(...)` (`demo/harness.py`):

* `toolsets`: only these are listed by the server, so the scenario proves they are enough;
* `assets`: files of `demo/assets/`, each with a source and a license in
  [assets/LICENSES.md](assets/LICENSES.md) (a scenario with an unlisted asset is refused);
* `outputs`: the files its scripted version writes;
* `steps(gimp, report)`: the scripted version, `gimp.call(...)` for each tool call and
  `report.check(description, passed, detail)` for each verification;
* `prompt` and `agent_output`: the agent version's request and the file it exports into `~/out`;
  its files are in `~/inputs`: the assets, plus what `make_agent_inputs` generates (`demo/run.py --agent-inputs`).

Add a row to the table above (a test checks every scenario is listed).

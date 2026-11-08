# Agent evaluation suite

Measures whether a real agent succeeds with gimp-mcp: each **task** is a natural-language request on
generated inputs (`evals/tasks.py`), given to a real Claude Code session that can only use the gimp
server, with the **default toolsets** (the agent must enable the others itself with
`gimp_enable_toolsets`). What it produces is then checked by facts: sizes, pixels, modes, frames,
metadata and files read with Pillow, never an aesthetic judgement.

```sh
uv run evals/run.py --list                    # the tasks and the toolsets they need
uv run evals/run.py resize-export             # one task (during development: one at a time)
uv run evals/run.py --all                     # every task, compared with the baseline
uv run evals/run.py --all --write-baseline    # replace docs/evals/baseline.{json,md}
uv run evals/run.py --all --package gimp-mcp==0.5.0   # a published version instead of this checkout
```

Needs Docker and the `claude` CLI on the machine (a native build: it is mounted read-only into the
containers).

## Isolation

Each task runs in a fresh container built from `demo/video/Dockerfile` (a pinned Arch Linux snapshot
with GIMP 3.2): gimp-mcp is installed in a new virtualenv (a wheel of this checkout, or `--package`),
a headless GIMP starts with the bridge, and Claude Code runs with a fresh HOME,
`--strict-mcp-config` (only the gimp server), `--permission-mode dontAsk`, only `mcp__gimp` allowed
and shell, file, web and sub-agent tools disallowed. Inputs are mounted read-only in `~/inputs`, and
`~/out` is the only writable folder shared with the host.

The token is `CLAUDE_CODE_OAUTH_TOKEN`, else the local Claude Code login. It reaches the container as
an environment variable only (`docker run -e CLAUDE_CODE_OAUTH_TOKEN`, no value on any command line);
after each task every file of the run is scanned for it, deleted if found, and the task fails.

Cost control: `--budget-usd` per task (default 2, Claude Code's `--max-budget-usd`), `--timeout` per
task (default 900 s), one task at a time.

## Reports

`evals/out/<date>/report.md` and `report.json`: per task, success (every check passed and the session
finished), the gimp tool calls, the errors gimp-mcp returned, other tools the agent tried (all
refused), duration and tokens; plus each task's files, transcript (`run/transcript.jsonl`) and
container log. A task that passed in the [baseline](baseline.md) and fails now is a **regression**:
it is listed at the top of the report, and the run exits with code 1.

## In CI

`.github/workflows/evals.yml` runs the suite on demand (*Actions → Agent evaluation*, tasks and
package as inputs) and on release pull requests (`release/*` branches, opened by
`scripts/prepare_release.py`). It needs the repository secret `CLAUDE_CODE_OAUTH_TOKEN`; without it,
the job warns and stops. The report is uploaded as the `agent-evaluation` artifact.

## Demo scenarios as tasks

The agent version of each demo scenario (`demo/scenarios/`, `agent_check` and `agent_reference`) is a
task too, with the scenario's prompt and inputs: `old-photo-restoration` passed on its first run
(31 gimp calls, 76 s); `product-cutout` did everything but the sRGB profile (assigning GIMP's built-in
sRGB embeds nothing, #158); `social-media-kit` passed once its check read a headline set on two lines
as the same text. A session cut short (e.g. by the account's usage limit) is reported with its reason. `--write-baseline` on some tasks replaces only theirs in the baseline.

## Adding a task

A `Task` in `evals/tasks.py`: name, the toolsets a solution needs, the prompt (naming every input in
`~/inputs` and every output in `~/out`), `make_inputs` (deterministic), `check(out, answer)` and a
`reference` that makes a correct result with Pillow. `tests/unit/test_evals.py` proves the checks
pass on the reference and fail on an empty output folder, and that the prompt names every file.
A failure found by the suite is fixed, or filed as an issue for the API review (milestone v0.7.0).

## Baseline (2026-11-08)

[16 of the first 18 tasks pass](baseline.md) with gimp-mcp 0.5.0 and Claude Sonnet 5.5. What the run
showed, each filed for the API review (v0.7.0):

* `lossless-webp` fails: the agent did not look for the `formats` toolset (#148).
* `darken` fails: `brightness=-30` darkens mid-gray by 7%, not 30% (#149).
* Newly enabled tools are first called without their schema (#147), and the validation error they
  get back is raw framework text (#146).
* Proportional resizing needs both dimensions, which defeats batch recipes (#150); a quarter-turn
  rotation takes 7 calls with the default toolsets (#151).

Two checks were corrected after the run, without running the agent again (`--recheck`): GIMP 3
blends layers and blurs in linear light, so 50% red over blue is (163, 61, 148) and a blurred
black-and-white checkerboard averages 188 (docs/gimp-notes.md).

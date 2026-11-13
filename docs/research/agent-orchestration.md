# Agent orchestration for gimp-mcp

Research note, 2026-11-13, gimp-mcp 0.7.0. Question: which way of organizing an agent (or several)
gets the most out of gimp-mcp, for which kind of work. Every external claim cites a numbered source
(list at the end); every claim about gimp-mcp cites a file of this repository or the evaluation run of
the 0.7.0 release PR [54]. Marked **Hypothesis**: not measured yet, to be tested with
`uv run evals/run.py` (not run for this note).

## Summary

| Kind of work | Recommended orchestration | Why |
|---|---|---|
| Single quick edit (resize, crop, text, export) | One agent, default toolsets, no explicit plan, no subagent; at most one preview | The 18 basic evaluation tasks pass in 3 to 8 gimp calls and about 9 to 25 s [54]; Anthropic advises the simplest solution that works [1] and the main conversation for quick targeted changes [10]. |
| Multi-step creative edit on one image | One agent that plans in its own context, takes a checkpoint before each risky phase, checks each phase on the changed region (`gimp_preview_region`) and with numbers where the target is numeric; optionally one fresh-context critic at the end, comparing before and after | All 8 long scenarios passed with a single agent in 0.7.0 [54]; image checks cost 0.2 to 6 % of the tokens processed (measured below); a fresh reviewer helps because it has not seen the reasoning [8], but pairwise comparison is more reliable than scoring for multimodal judges [41]. |
| Batch over many files | A workflow, not an agent: pilot the edit on one file, encode it as a `gimp_run_batch` recipe, `dry_run`, run, then verify a sample of outputs independently. Subagents (one image each) only when each file needs judgement | Recipes are validated before anything runs and report per-file errors (ADR 0006); loops in code instead of model turns cut tokens [5][6]; the agent in `web-photo-batch` found this pilot-then-scale pattern by itself [54]. |
| Precise or print work (sizes, dpi, profiles, exact colors) | Numeric verification first (`gimp_inspect_image`, `gimp_histogram`, `gimp_sample_colors`, `gimp_compare`, metadata and profile readers), previews second; encode the spec as a check the agent must pass | Claude's localization and counting are approximate [20]; self-correction without external feedback does not help and can hurt [40], tool-based feedback does [39]; "give Claude a check to run" [8]. |
| Human in the loop, in GIMP's window | One agent in the main conversation; workflows offered as MCP prompts the user picks; `undo` toolset so the person can Ctrl+Z; never several agents on the image the person is editing | Prompts are user-controlled by design [22]; restoring a checkpoint replaces the image and changes every item id (docs/tools.md#history-undo-groups-and-checkpoints); fill and paint tools act through the image's single selection (docs/tools.md). |

Cross-cutting:

* **Multi-agent is not the default.** Anthropic's multi-agent research system used about 15x the tokens
  of a chat and suits parallel, context-heavy work, not tasks with many dependencies [2]; Claude Code
  says delegation does not make the answer smarter, only parallel or fresh [8]. Use it for many
  independent images, or for an independent critic.
* **Parallelism is cheap on one GIMP if each agent owns its own image.** GIMP runs one request at a
  time (ADR 0001), but in the scenarios the model's turns, not GIMP, take most of the time: the scripted
  `web-photo-batch` runs 104 calls in 18.3 s, the agent version 73 calls in 126.5 s
  (docs/demos/web-photo-batch/report.md, [54]).
* **Toolsets:** in Claude Code, tool definitions are deferred by default (tool search) [9], so the
  context argument for a small default weakens there while the "schema not loaded yet" argument
  strengthens (ADR 0012). **Hypothesis**: a wider toolset selection plus `anthropic/alwaysLoad` on a few
  core tools lowers calls and errors in Claude Code; other clients keep the bounded default.

## 1. Constraints gimp-mcp puts on any orchestration

| Fact | Source | Consequence for orchestration |
|---|---|---|
| The bridge runs requests one at a time on GIMP's plug-in main thread, across all connections; the server keeps one request in flight per client | docs/adr/0001-bridge-persistent-plugin-unix-socket.md, docs/bridge-protocol.md, src/gimp_mcp/bridge.py | Several agents on one GIMP interleave, they do not run GIMP work in parallel. A long filter blocks everyone. |
| Ids embed the GIMP session (`image:3@e5fec992`); another session's id is refused with `SESSION_CHANGED` | docs/tools.md#ids, docs/bridge-protocol.md#sessions | Ids cannot be passed between GIMP instances by mistake; a plan written with one instance's ids is useless on another. |
| Item ids are unique across all open images of a session | docs/tools.md#ids | Agents on different images of one GIMP cannot collide on ids. |
| Checkpoints are per image (max 20); restoring one gives the image a new id and changes every item id | docs/tools.md#history-undo-groups-and-checkpoints | An agent that restores a checkpoint invalidates the ids every other agent holds on that image. |
| The selection is per image and limits fills and paint | docs/tools.md (Painting) | Two agents doing select-then-fill on one image corrupt each other's work: per-region parallelism on a shared image is unsafe. |
| `buffer="clipboard"` is GIMP's global clipboard; named buffers exist | docs/tools.md (compose) | Parallel agents must use distinct named buffers. |
| `gimp_enable_toolsets` adds tools for the session of the server process | docs/toolsets.md, ADR 0005 | Subagents sharing the parent's connection share its toolsets. |
| A second GIMP on the same socket path refuses to start its bridge; `gimp-mcp serve --socket` and `GIMP_MCP_SOCKET` select an instance; `gimp_mcp.headless.HeadlessGimp` starts an isolated `gimp-console` (about 5 s) | docs/bridge-protocol.md, src/gimp_mcp/cli.py, docs/testing.md | True parallel GIMP work needs one GIMP per worker, each on its own socket, each with its own `gimp-mcp serve`. Only a Python class starts headless instances today, no CLI. |
| Cancellation ends the MCP request but not the operation inside GIMP | ADR 0007 | A cancelled worker can still delay the next request of every other worker on that GIMP. |
| `gimp_run_batch` validates the whole recipe before opening a file, closes the images it opened, reports per-file errors | ADR 0006, docs/tools.md#batch-processing-toolset-batch | Batch is a deterministic workflow primitive; the agent only writes the recipe. |
| Previews: default 512 px, at most 1024 px (GIMP's thumbnail limit) | docs/tools.md#preview | Image tokens per check are bounded (section 3.4). |
| Read-only tools carry `readOnlyHint` | src/gimp_mcp/toolkit.py | Claude Code runs read-only calls in parallel with other read-only calls [9]; the bridge still serializes them. |

## 2. Evidence from this repository

The evaluation suite gives a real Claude Code session only the gimp server with the default toolsets;
shell, file, web and subagent tools are disallowed (docs/evals/README.md, evals/harness.py: `Task`,
the old name of the `Agent` tool [10]). It therefore measures **one agent, free planning, no MCP
prompts, no resources** (resource tools are refused by `--allowedTools mcp__gimp`), model
claude-sonnet-5-5.

### Long scenarios: scripted vs agent

| Scenario | Scripted calls / s (docs/demos/*/report.md) | Agent 0.6.0 calls, result (docs/evals/baseline.md) | Agent 0.7.0 calls / s, result [54] |
|---|---|---|---|
| animated-sticker | 74 / 5.3 | 56, pass | 55 / 140.5, pass |
| old-photo-restoration | 31 / 5.2 | 106, fail | 58 / 106.5, pass |
| print-flyer | 26 / 2.5 | 21, fail | 21 / 35.2, pass |
| product-cutout | 36 / 5.9 | 62, fail | 52 / 70.7, pass |
| screenshot-annotation | 24 / 3.3 | 32, pass | 30 / 59.0, pass |
| sky-replacement | 21 / 2.3 | 17, pass | 17 / 25.9, pass |
| social-media-kit | 100 / 4.3 | 74, pass | 71 / 80.7, pass |
| web-photo-batch | 104 / 18.3 | 73, fail | 73 / 126.5, pass |

Overall: 21/26 with 0.6.0, 26/26 with 0.7.0, one run each, same model.

### What the transcripts show

1. **Tool fixes, not orchestration, moved the success rate.** The 0.6.0 failures were filed as API issues
   (#149 darken scale, #158 sRGB profile, #162 batch step references, #165 TIFF pages) and fixed in 0.7.0
   (docs/evals/README.md); the orchestration did not change. This matches Anthropic's advice to invest
   in the agent-computer interface [1] and to drive tool changes by evaluation [3]. The README also notes
   run-to-run variance (old-photo-restoration passed, failed, passed): one run is not a verdict.
2. **Checkpoints are almost never used spontaneously.** 0.7.0: 0 `gimp_create_checkpoint`, 0 restores
   in 26 tasks. 0.6.0: 2 creates and 2 restores, both in product-cutout, the first restore failing on a
   missing `image` argument (docs/evals/baseline.md). The `CHECKPOINT` advice exists only in the MCP
   prompts (src/gimp_mcp/prompts.py), which the evaluation never uses.
3. **Verification is mostly visual.** 0.7.0, all tasks: 19 `gimp_preview`, 10 `gimp_preview_region`,
   1 `gimp_preview_frame`, 4 `gimp_histogram`, 1 `gimp_dominant_colors`, 0 `gimp_compare`,
   0 `gimp_sample_colors` (computed from report.json [54]). Visual checks did catch real errors: in
   product-cutout the agent wrote "Shadow is above the bottle; move it between the bottle and white";
   in old-photo-restoration it found its dust dabs "too small because the dynamics were on" and redid
   them. Where it could not verify, it said so ("I couldn't confirm the sRGB profile is embedded").
4. **Batch is planned like a workflow when it exists.** In web-photo-batch (0.7.0) the agent ran a
   one-file pilot batch, reopened both outputs to check metadata and profile, previewed one, then split
   the 21 files into groups by orientation and ran one recipe per group, several in the same turn. It
   also opened 19 files and read their metadata one call at a time before that (73 calls, 79 turns).
   batch-thumbnails went from 12 calls (0.6.0) to 5 (0.7.0).
5. **Repetition is the main source of calls.** animated-sticker repeats `import_layer, set_layer_properties,
   merge_layers, add_frame` 12 times; social-media-kit repeats about 17 calls per format, 4 times
   (report.md [54]). These are the sequences #181 and #182 target.
6. **Deferred tool loading causes argument errors.** Every task called Claude Code's `ToolSearch`.
   Three tasks (animated-gif, lossless-webp, animated-sticker) called `gimp_enable_toolsets` with
   `names` instead of `toolsets`; three errors carry Claude Code's note "This tool's input schema was not
   in your prompt when you called it". 8 of the 13 errors of the run are argument-shape errors
   (report.json [54]). ADR 0012 already returns usage lines from `gimp_enable_toolsets` for this reason.
7. **The agent issues parallel tool calls itself.** The 0.7.0 old-photo-restoration transcript has 58 gimp
   calls in 23 distinct assistant messages; web-photo-batch sends several `gimp_open_image` and
   `gimp_run_batch` calls per message. The server and bridge serialize them (section 1); they still
   save model turns.

### Cost of visual checks, measured

Visual tokens per image computed with the current formula, `ceil(width/28) x ceil(height/28)` [20],
from the preview sizes in each 0.7.0 transcript; "re-read" assumes each image is sent again in every
later request (distinct assistant messages), compared with the task's cache-read tokens.

| Task | Images | Visual tokens | Re-read visual tokens | Cache-read tokens | Share |
|---|---|---|---|---|---|
| old-photo-restoration | 9 (up to 1024x694) | 4,695 | 55,786 | 994,180 | 5.6 % |
| screenshot-annotation | 4 | 1,719 | 15,011 | 490,318 | 3.1 % |
| social-media-kit | 5 | 1,725 | 14,540 | 608,253 | 2.4 % |
| product-cutout | 3 | 825 | 12,281 | 1,015,811 | 1.2 % |
| sky-replacement | 3 | 692 | 2,372 | 217,008 | 1.1 % |
| web-photo-batch | 3 | 741 | 1,482 | 836,394 | 0.2 % |

At these sizes previews are not the dominant cost; the number of turns over a growing context is.
Claude Code may scale an image down before sending it [9], so these are upper bounds per image.

## 3. The patterns compared

| Pattern | Wins when | Cost | Risks | What gimp-mcp offers | Evidence |
|---|---|---|---|---|---|
| Single agent with tools (today) | Most single-image work, up to ~70 calls | Lowest: one context; tokens grow with turns | Repetition, no spontaneous checkpoints, argument guesses on first use | Ids in every result, structured errors with hints, previews, analysis | 26/26 in 0.7.0 [54]; ReAct-style interleaving of reasoning and actions with environment feedback [33]; "ground truth from the environment at each step" [1] |
| Plan-then-act (same agent) | Long edits with phases; batch | A few hundred output tokens for the plan | A wrong plan executed blindly if it does not re-check | Checkpoints per phase, `dry_run` for batches | Plan-and-Solve reduces missing-step errors [34]; separating planning from execution helps long-horizon web tasks [36]; decoupling reasoning from observations cut tokens 5x on HotpotQA [35]; Claude Code plan mode exists for planning without edits [14] |
| Planner and executor as separate agents | Unclear for gimp-mcp | Two contexts; planner lacks pixel feedback | Plan built without seeing the image; ids not transferable | Nothing specific | Plan-and-Act used a trained planner [36]; Anthropic: subagents need objective, output format, tools and boundaries in the brief [2] |
| Orchestrator + per-file workers | Many independent images, each needing judgement | ~15x chat tokens for multi-agent systems [2] | Conflicting assumptions between workers [32]; GIMP serializes calls | Ids unique per session; one image per worker is safe; batch for the non-judgement part | Multi-agent beat single-agent Opus 4 by 90.2 % on Anthropic's internal research eval [2]; MAS gains "often minimal" on benchmarks, 14 failure modes [53] |
| Per-step or per-region workers on one image | Not recommended | Same as above plus re-inspection | Shared selection, checkpoint restore changes all ids, style drift | None | Section 1; "actions carry implicit decisions" [32]; agent teams: same-file edits lead to overwrites [13] |
| Separate critic / verifier | End of a creative edit, or when the target is a spec | One extra context plus images | Judge bias; scoring unreliable | `gimp_compare(preview=true)` diff image, checkpoints as the "before", analysis tools | Fresh reviewer not swayed by the producer's reasoning [8]; LLM-as-judge "generally not a very robust method" [7]; MLLM judges closer to humans in pair comparison than in scoring [41] |
| Verification loops inside one agent | Always, bounded | 0.2 to 6 % of tokens for previews (section 2) | Over-iterating; vision imprecise on positions and counts [20] | Previews, `gimp_preview_region` at full resolution, histogram, sample, compare | Self-Refine +~20 % [38]; Reflexion uses environment feedback [37]; CRITIC: external tool feedback is crucial [39]; no gain without it [40] |
| Encoded workflows (recipes, prompts, skills) | Repeated, well-defined procedures | Lowest per run | Rigid; prompts are user-triggered only | `gimp_run_batch` with step references, 4 MCP prompts | Workflows give predictability for well-defined tasks [1]; code instead of chained calls cut 150k to 2k tokens in Anthropic's example [5]; programmatic tool calling -37 % tokens [6] |

### 3.1 Single agent

The evaluation is this pattern and it succeeds at the current task sizes (section 2). Anthropic frames
agents as "LLMs using tools based on environmental feedback in a loop" and recommends the simplest
solution, adding complexity only when it pays [1]. Claude Code's own guidance keeps tasks that need
"frequent back-and-forth or iterative refinement" and tasks whose phases "share significant context"
in the main conversation [10]. An image edit is that: each step depends on what the previous one did to
the pixels.

### 3.2 Planner/executor and plan-then-act with checkpoints

Research supports an explicit plan for long tasks: Plan-and-Solve prompting reduces missing-step errors
[34], Plan-and-Act separates a planner from an executor for long-horizon web tasks [36], ReWOO reports
5x token efficiency by planning tool calls without interleaved observations [35]. In gimp-mcp, a
plan written without looking at the pixels misses what only a preview shows (product-cutout's shadow,
old-photo's dust dabs, section 2). Recommended form: one agent states its phases, takes
`gimp_create_checkpoint` before each risky phase, executes, checks, and restores if the check fails
(restore is undo and redo: docs/tools.md#history-undo-groups-and-checkpoints). Separate planner and executor agents add a
handoff with no image context and ids that may be restored away; no source shows a gain for that split
on stateful image editing (not found).

### 3.3 Multi-agent

* **Per file.** The only form that matches the evidence for multi-agent gains: parallel, independent,
  context-heavy subtasks [2]. Each worker owns its images; previews stay in the worker's context and
  only a summary returns [4][15]. On one GIMP, workers interleave but model latency dominates (section 2),
  so wall-clock can still drop; for GIMP-bound work, one headless GIMP per worker on its own socket
  (section 1). For files that need no judgement, a recipe is cheaper than any worker.
* **Per step or per region on one image.** Unsafe in gimp-mcp (shared selection, checkpoint restore
  changes ids, global clipboard) and inconsistent in style: parallel subagents that cannot see each
  other's work act on "conflicting assumptions not prescribed upfront" [32]. Claude Code's agent teams
  doc states the same for files: same-file edits lead to overwrites [13].
* **Critic.** A reviewer in a fresh context "isn't swayed by the reasoning that produced the code" [8],
  and Cursor lists "independent verification of work" as a reason for subagents [29]. Limits: LLM judging
  is "generally not a very robust method" with latency costs [7]; multimodal judges diverge from humans
  when scoring but are closer in pair comparison [41]. So a critic should compare (before vs after with
  `gimp_compare(preview=true)`, or result vs a stated spec) rather than give a score, and should check
  numbers where the spec has numbers. Image-editing agents in the literature put the check inside the
  loop: GenArtist plans with "step-by-step verification" and self-correction [44]; PhotoArtAgent plans,
  applies Lightroom parameters, "evaluates the resulting images and iteratively refines" [45]; PhotoAgent
  uses closed-loop execution with visual feedback and a learned aesthetic reward [48]. These systems are
  trained or specialized and evaluated on their own benchmarks; their numbers do not transfer to
  gimp-mcp.

### 3.4 Verification loops: visual vs numeric

* **When they help.** The literature gain comes from external feedback: CRITIC shows "the crucial
  importance of external feedback" [39]; without it, LLMs "struggle to self-correct" and can degrade
  [40]; Self-Refine reports ~20 % average improvement with self-feedback on text tasks [38]. In
  gimp-mcp, a preview is external feedback (GIMP's own rendering, docs/tools.md#preview), and analysis
  tools are external measurements. Anthropic lists visual feedback (screenshots, renders) and
  rules-based feedback as verification forms [7].
* **Visual** catches layout, placement, artifacts, things with no numeric spec. Limits: Claude's
  coordinates are approximate, counts are approximate, small images under 200 px are error-prone [20];
  a 512 px preview of a 3000 px photo hides small defects (docs/tools.md#preview). `gimp_preview_region`
  at scale 1 is the right check for local edits.
* **Numeric** catches what vision cannot: exact sizes, dpi, profiles, clipping, color cast, a 30 %
  darkening (the 0.6.0 `darken` failure was a numeric miss no preview would show: mean 119 instead of
  60-110, docs/evals/baseline.md). `gimp_compare` with a checkpoint as `a` measures exactly what an
  edit changed (docs/tools.md#analysis-toolset-analysis-read-only); it was never called in either run.
* **Cost and bounds.** Measured at 0.2 to 6 % of processed tokens per long task (section 2). Bound them by:
  default 512 px previews, regions instead of full images, a maximum number of check-and-fix rounds
  (Anthropic: stopping conditions such as a maximum number of iterations [1]), numeric checks first,
  and moving image-heavy review into a subagent whose images never enter the main context [15].

### 3.5 Encoding workflows

| Mechanism | Who triggers it | Portability | Fit |
|---|---|---|---|
| MCP prompts (`thumbnail`, `remove-background`, `photo-touch-up`, `batch-export`) | The user ("user-controlled" [22]) | Any client that supports prompts: Claude Code `/mcp__gimp__<prompt>` [9], Cursor [28] | Human-in-the-loop work; shipped with the server, versioned with the tools (a unit test checks tool names, ADR 0007) |
| Server `instructions` | Always loaded | All clients that read it; Claude Code loads it at start even with tool search, cut at 4,096 characters [9] | Short cross-cutting rules (current text: src/gimp_mcp/server.py, 648 characters) |
| Skills (`SKILL.md`) | The model when the description matches, or the user with `/name` | Claude Code [11], Agent SDK [17], Cursor [30], claude.ai custom skills with code execution [19] | Longer procedures and **scripts** whose code never enters context, only their output [19]; ~100 tokens of metadata per skill until used [19] |
| Recipes (`gimp_run_batch`) | The model writes one call | Any client (it is a tool) | Same steps over many files; validated before running (ADR 0006) |
| Hooks | The harness, deterministically | Claude Code [12], Agent SDK [18] | Enforcing a check (a `Stop` hook that blocks until an exported file passes) [8][12]; `PostToolUse` matchers like `mcp__gimp__.*` [12] |
| Free planning | The model | Any | Novel tasks; the evaluated default |

Anthropic's guidance: workflows "offer predictability and consistency for well-defined tasks", agents
suit open-ended problems [1]; procedures belong in skills rather than always-loaded instructions [8];
rules that must always hold belong in hooks, not in prompts [8]. The repo's MCP prompts are the only
encoded workflows today and are not measured by the evaluation.

### 3.6 Toolset strategy

* **Evidence on tool count.** More tools do not always mean better outcomes [3]; bloated tool sets
  create "ambiguous decision points" [4]; retrieval of relevant tools more than tripled selection
  accuracy in an MCP stress test (43.13 % vs 13.62 %) [51]; reducing the tools offered improved
  function-calling success on small models [52]; Anthropic's tool search raised MCP evaluation accuracy
  from 49 % to 74 % (Opus 4) and 79.5 % to 88.1 % (Opus 4.5) [6].
* **Sizes here** (measured on this checkout from `build_server(...).list_tools()` serialized as JSON):
  default 49 tools, 117,767 bytes; all 159 tools, 337,460 bytes. Token counts were not measured.
* **Claude Code defers MCP tool definitions by default**: only names and server instructions load at
  start; schemas load on demand [9]. Under that regime the default toolset saves little context, while
  `gimp_list_toolsets` + `gimp_enable_toolsets` + ToolSearch adds calls and the schema-not-loaded errors
  of section 2. Claude Code lets a server mark tools to load upfront with `_meta["anthropic/alwaysLoad"]`
  [9].
* **Clients that load everything upfront or ignore `list_changed`**: the bounded default plus toolsets
  configured up front (docs/toolsets.md#per-client) stays right. Claude Code refreshes on `list_changed`
  (interactive: tools, prompts, resources; `-p` and Agent SDK: tools only) [9]; Cursor's MCP page does
  not mention it [28].
* **Recommendation**: default + dynamic enabling as today for unknown clients; configure the toolsets a
  known workload needs up front (scripts, batch, CI: as the demo scenarios do); **Hypothesis**: in Claude
  Code, `--toolsets all` (or `default` plus the toolsets of the domain) with core tools always loaded
  beats dynamic enabling on calls and errors without hurting selection. `procedures` stays opt-in: its
  four tools "invite PDB calls when a dedicated tool exists" (ADR 0005).

### 3.7 Concurrency

* **One GIMP, shared connection.** Claude Code subagents inherit the main conversation's MCP tools, and
  a server named by string in a subagent's `mcpServers` "share[s] the parent session's connection" [10]:
  one `gimp-mcp serve`, one request in flight. That plain inherited tools also reuse the parent's
  connection is the likely reading but is not stated in [10]. Safe with one image per subagent; toolsets
  enabled by one are enabled for all on a shared server process.
* **One GIMP, a connection per worker.** A subagent with an inline `mcpServers` definition gets its own
  server process, started and stopped with it [10]; the Agent SDK accepts the same per-agent
  `mcpServers` [15]. Still one GIMP executing one request at a time.
* **One GIMP per worker.** Inline definitions can pass `--socket` (or `GIMP_MCP_SOCKET`) so each worker
  drives its own GIMP (src/gimp_mcp/cli.py). Ids cannot cross instances (`SESSION_CHANGED`). Cost: a GIMP
  start (~5 s headless, docs/testing.md) and memory per instance (not measured). Worth it only when GIMP
  time dominates, which it does not in the evaluation scenarios (section 2).
* **Limits on the client side.** Claude Code stops spawning at 20 concurrent subagents by default [10];
  calls from subagents are never auto-backgrounded [9]; background subagents keep every MCP tool [10].
* **The user's image.** In GUI sessions, never run a worker on an image the person is editing:
  checkpoint restore replaces it and UI changes join open undo groups (docs/tools.md#history-undo-groups-and-checkpoints).

## 4. Client support matrix

"Not found" means the official page read for this note does not state it; it may still exist.

| Capability | Claude Code | Claude Agent SDK | Claude Desktop | Cursor |
|---|---|---|---|---|
| MCP tools, stdio | Yes [9] | Yes [16] | Yes [26] | Yes [28] |
| Images in tool results | Shown inline, may be scaled; original saved to a file [9] | Not found | Not found | Attached to the chat [28] |
| MCP prompts | `/server:prompt` or `/mcp__server__prompt`, args split on whitespace [9] | As commands in sessions with MCP servers [17] | Not found in official docs | Supported [28] |
| MCP resources | `@server:uri` mentions, list/read tools [9] | Not found | Not found | Supported [28] |
| `list_changed` refresh | Interactive: tools, prompts, resources; `-p`: tools only [9] | Tools only [9] | Not found | Not found |
| Deferred tools / tool search | On by default; `ENABLE_TOOL_SEARCH`; `alwaysLoad` per server or tool [9] | On by default [16] | Not found | Not found |
| Elicitation | Interactive terminal only [9] | `onElicitation` callback mentioned [9] | Not found | Supported [28] |
| Sampling | Not found | Not found | Not found | Not mentioned [28]; deprecated in MCP 2026-07-28 [24] |
| Subagents with MCP tools | Yes; `tools`, `mcpServers`, `model`, `skills`, background [10] | `agents` option, `AgentDefinition` with `mcpServers` [15] | Not found | Yes, inherit parent MCP tools; cloud subagents use team config [29] |
| Skills | Yes, custom commands merged into skills [11] | Yes, from filesystem [17] | claude.ai custom skills need code execution [19]; Desktop not confirmed | Yes, `.cursor/skills/` [30] |
| Hooks on MCP tools | `PreToolUse`/`PostToolUse`/`Stop`, `mcp__gimp__.*` [12] | Callbacks, same matchers [18] | Not found | Not checked |
| Plan mode | Yes [14] | Not checked | Not found | Not checked |

VS Code: its MCP configuration reference points to a separate support page "for tools, prompts,
resources, roots, sampling, elicitation, and MCP Apps" [31]; that page was not verified for this note.
Codex, Zed and other clients: not researched.

## 5. Recommendations for gimp-mcp

### Evidence-based

1. **Mark the core tools to load upfront in Claude Code.** Add `_meta["anthropic/alwaysLoad"]: true` to
   `gimp_status`, `gimp_list_toolsets`, `gimp_enable_toolsets`, `gimp_inspect_image`, `gimp_preview` (the
   mechanism is documented [9]). Evidence: 3 of 26 tasks guessed `gimp_enable_toolsets` arguments, 8 of 13
   errors were argument-shape errors (section 2). The size of the effect is to be measured.
2. **Put cross-cutting discipline in `INSTRUCTIONS`.** Claude Code always loads server instructions, up to
   4,096 characters, and uses them to decide when to search for the server's tools [9]; today's text is
   648 characters (src/gimp_mcp/server.py). Candidates, each tied to an observed gap: checkpoint before a
   destructive or multi-step change (0 checkpoints in 0.7.0); verify numeric targets with analysis tools
   and `gimp_compare` against the checkpoint (0 compares); for many files, pilot one file, then
   `gimp_run_batch` with `dry_run`; never edit one image from two agents. Keep it short: instructions are
   always-loaded context [4].
3. **Document orchestration for users** (docs/clients.md or a new page): single agent by default; one
   image per subagent; shared GIMP is fine for judgement-heavy per-file work; one GIMP per worker via
   `--socket` for GIMP-bound work; MCP prompt arguments are split on whitespace in Claude Code, so paths
   with spaces break (`/mcp__gimp__thumbnail`) [9].
4. **Do not build a server-side critic on MCP sampling.** Sampling is deprecated as of 2026-07-28; new
   implementations "SHOULD NOT" adopt it [24]. A critic belongs in the client (subagent, skill, hook).
5. **Keep working on fewer calls per gesture (#181, #182).** Evidence: the repeated sequences of section 2;
   loops expressed once instead of as model turns reduce tokens [5][6]; turns, not images, dominate cost
   (section 2). #182 (a recipe on an open image, rolled back on failure) is the in-image form of the batch
   pattern and gives agents an atomic plan-then-act unit.
6. **Elicitation for human-in-the-loop (#188)** is supported by Claude Code (interactive only) and
   Cursor [9][28]; the MCP spec forbids form-mode elicitation for secrets, not for confirmations [25].

### Hypotheses to test with the evaluation suite

Each needs several runs per configuration (the suite's README documents run-to-run variance) and should
report calls, errors, tokens and image tokens, as #184 asks.

| # | Hypothesis | How to test |
|---|---|---|
| [H1](https://github.com/mhbxyz/gimp-mcp/issues/216) | In Claude Code, `GIMP_MCP_TOOLSETS=all` + alwaysLoad core tools gives fewer calls and errors than default + enabling, with no loss of success | Run `--all` twice per configuration; compare `enable_toolsets` calls, argument errors, tokens |
| [H2](https://github.com/mhbxyz/gimp-mcp/issues/217) | Instructions with checkpoint and verification rules raise checkpoint and analysis use and the pass rate on the long scenarios, at bounded token cost | Same suite, INSTRUCTIONS variant; count `create_checkpoint`, `compare`, `histogram`; pass rate over 3 runs |
| [H3](https://github.com/mhbxyz/gimp-mcp/issues/218) | A fresh-context critic subagent (allow `Agent` in evals/harness.py, give it read-only gimp tools) fixes more defects than it costs on creative scenarios | social-media-kit, product-cutout, sky-replacement, with and without the critic |
| [H4](https://github.com/mhbxyz/gimp-mcp/issues/219) | Per-file subagents on one GIMP cut wall-clock time on web-photo-batch versus one agent with batches | Allow `Agent`; compare duration, tokens, success |
| [H5](https://github.com/mhbxyz/gimp-mcp/issues/220) | A Claude Code skill with a Pillow script that checks exported files (size, mode, profile, metadata, the same facts as the evaluation checks) closes the "couldn't confirm" gaps | Ship the skill in the eval container; count unverifiable claims in final answers and failures |
| [H6](https://github.com/mhbxyz/gimp-mcp/issues/221) | Running a scenario through its MCP prompt (where one exists) takes fewer calls than the free-form request | New eval tasks whose prompt is the text of `photo-touch-up`, `remove-background`, `batch-export` |
| [H7](https://github.com/mhbxyz/gimp-mcp/issues/222) | A smaller model (Haiku) gains more from encoded workflows (prompts, recipes, skill) than Sonnet | #184 baselines per model, with and without H2/H5/H6 |

## 6. Open questions

* Claude Desktop: which MCP features (prompts, resources, list_changed, image results) does it support?
  Its official help article lists none of them [27].
* Cursor: does it refresh tools on `list_changed`, and does it defer tool definitions? Its MCP page is
  silent [28].
* How many tokens do the default and full tool definitions cost in practice, per client, and what do
  deferred names alone cost in Claude Code? Not measured.
* Memory and start time of several GIMP instances on a user's machine, and whether the plug-in profile
  can be shared between instances safely.
* Does Claude Code's plan mode block mutating MCP tools? The permission-modes page describes blocked
  source edits but does not say for MCP tools [14].
* Is pairwise judging by the same model family on previews reliable enough for gimp-mcp's creative
  tasks? [41] measured GPT-4V-era models; no current measurement found.
* Single-run evaluation results: how stable are the 0.7.0 numbers (calls, durations) across runs?

## Sources

1. Anthropic, "Building effective agents" (2024-12-19). https://www.anthropic.com/engineering/building-effective-agents — workflows vs agents, simplicity, orchestrator-workers, evaluator-optimizer conditions, ground truth from the environment, stopping conditions, ACI.
2. Anthropic, "How we built our multi-agent research system" (2025-06-13). https://www.anthropic.com/engineering/multi-agent-research-system — +90.2 % vs single agent, ~4x / ~15x tokens, unsuitable for shared-context or dependent tasks, subagent briefs, checkpoints.
3. Anthropic, "Writing effective tools for agents" (2025-09-11). https://www.anthropic.com/engineering/writing-tools-for-agents — more tools not always better, consolidation, error messages, evaluation metrics.
4. Anthropic, "Effective context engineering for AI agents" (2025-09-29). https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents — minimal tool sets, ambiguous decision points, subagents returning 1,000-2,000-token summaries.
5. Anthropic, "Code execution with MCP" (2025-11-04). https://www.anthropic.com/engineering/code-execution-with-mcp — tool definitions and intermediate results cost context; 150,000 to 2,000 tokens; loops in code.
6. Anthropic, advanced tool use engineering post (2025-11-24). https://www.anthropic.com/engineering/advanced-tool-use — tool search accuracy (49→74 %, 79.5→88.1 %), programmatic tool calling -37 % tokens, tool use examples 72→90 %.
7. Anthropic, "Building agents with the Claude Agent SDK" (2025-09-29). https://claude.com/blog/building-agents-with-the-claude-agent-sdk — gather/act/verify loop, visual feedback, LLM judge not robust, subagents for parallelism and isolation.
8. Claude Code docs, "Best practices for Claude Code". https://code.claude.com/docs/en/best-practices — give Claude a check to run, Stop hooks, fresh reviewer, subagent costs, skills for procedures.
9. Claude Code docs, "Connect Claude Code to tools via MCP". https://code.claude.com/docs/en/mcp — list_changed, tool search, alwaysLoad, instruction limits, output limits, images, prompts as commands, resources, elicitation, readOnlyHint parallelism, backgrounding.
10. Claude Code docs, "Create custom subagents". https://code.claude.com/docs/en/sub-agents — mcpServers (shared vs inline), tools inherited, background tool filter, Task renamed Agent, 20 concurrent subagents, when to use the main conversation.
11. Claude Code docs, "Extend Claude with skills". https://code.claude.com/docs/en/skills — skills and merged custom commands, invocation control, context: fork.
12. Claude Code docs, "Hooks reference". https://code.claude.com/docs/en/hooks — MCP tool matchers, events, additionalContext.
13. Claude Code docs, "Orchestrate teams of Claude Code sessions". https://code.claude.com/docs/en/agent-teams — experimental, more tokens, same-file edits overwrite.
14. Claude Code docs, "Permission modes". https://code.claude.com/docs/en/permission-modes — plan mode.
15. Claude Code docs, "Subagents in the SDK". https://code.claude.com/docs/en/agent-sdk/subagents — AgentDefinition fields, context isolation, parallelization.
16. Claude Code docs, "Connect to external tools with MCP" (Agent SDK). https://code.claude.com/docs/en/agent-sdk/mcp — stdio servers, tool search on by default.
17. Claude Code docs, "Extend agents with skills" (Agent SDK). https://code.claude.com/docs/en/agent-sdk/skills — filesystem skills, MCP prompts as commands.
18. Claude Code docs, "Intercept and control agent behavior with hooks" (Agent SDK). https://code.claude.com/docs/en/agent-sdk/hooks — PostToolUse, MCP matchers.
19. Claude Platform docs, "Agent Skills". https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview — progressive disclosure, ~100 tokens metadata, scripts whose code stays out of context, surfaces.
20. Claude Platform docs, "Vision". https://platform.claude.com/docs/en/build-with-claude/vision — 28x28-pixel visual tokens, resolution tiers, limitations on spatial reasoning and counting.
21. MCP specification 2026-07-28, "Tools". https://modelcontextprotocol.io/specification/2026-07-28/server/tools — model-controlled, listChanged, human in the loop.
22. MCP specification 2026-07-28, "Prompts". https://modelcontextprotocol.io/specification/2026-07-28/server/prompts — user-controlled.
23. MCP specification 2026-07-28, "Resources". https://modelcontextprotocol.io/specification/2026-07-28/server/resources — application-driven.
24. MCP specification 2026-07-28, "Sampling". https://modelcontextprotocol.io/specification/2026-07-28/client/sampling — deprecated (SEP-2577).
25. MCP specification 2026-07-28, "Elicitation". https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation — form and URL modes, no secrets in forms.
26. MCP docs, "Connect to local MCP servers". https://modelcontextprotocol.io/docs/develop/connect-local-servers — Claude Desktop stdio servers, per-action approval.
27. Claude Help Center, "Getting Started with Local MCP Servers on Claude Desktop". https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop — extensions; no statement on prompts, resources, subagents.
28. Cursor docs, "Model Context Protocol". https://cursor.com/docs/context/mcp — tools, prompts, resources, roots, elicitation, apps; images attached to chat; approval.
29. Cursor docs, "Subagents". https://cursor.com/docs/subagents — own context window, parallel, MCP tools inherited, independent verification.
30. Cursor docs, "Agent Skills". https://cursor.com/docs/skills — SKILL.md in `.cursor/skills/`.
31. VS Code docs, MCP configuration reference. https://code.visualstudio.com/docs/agents/reference/mcp-configuration — pointer to MCP feature support page.
32. Walden Yan (Cognition), "Don't Build Multi-Agents" (2025-06-12). https://cognition.com/blog/dont-build-multi-agents — share context; actions carry implicit decisions; conflicting parallel subagents.
33. Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models" (2022). https://arxiv.org/abs/2210.03629
34. Wang et al., "Plan-and-Solve Prompting" (2023). https://arxiv.org/abs/2305.04091
35. Xu et al., "ReWOO: Decoupling Reasoning from Observations for Efficient Augmented Language Models" (2023). https://arxiv.org/abs/2305.18323
36. Erdogan et al., "Plan-and-Act: Improving Planning of Agents for Long-Horizon Tasks" (2025). https://arxiv.org/abs/2503.09572
37. Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning" (2023). https://arxiv.org/abs/2303.11366
38. Madaan et al., "Self-Refine: Iterative Refinement with Self-Feedback" (2023). https://arxiv.org/abs/2303.17651
39. Gou et al., "CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing" (2023). https://arxiv.org/abs/2305.11738
40. Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet" (2023). https://arxiv.org/abs/2310.01798
41. Chen et al., "MLLM-as-a-Judge: Assessing Multimodal LLM-as-a-Judge with Vision-Language Benchmark" (2024). https://arxiv.org/abs/2402.04788
42. Gupta and Kembhavi, "Visual Programming: Compositional visual reasoning without training" (2022). https://arxiv.org/abs/2211.11559 — LLM-generated programs over vision and image-processing modules, including language-guided image editing.
43. Surís et al., "ViperGPT: Visual Inference via Python Execution for Reasoning" (2023). https://arxiv.org/abs/2303.08128 — composing vision modules through generated code.
44. Wang et al., "GenArtist: Multimodal LLM as an Agent for Unified Image Generation and Editing" (2024). https://arxiv.org/abs/2407.05600
45. Chen et al., "PhotoArtAgent: Intelligent Photo Retouching with Language Model-Based Artist Agents" (2025). https://arxiv.org/abs/2505.23130
46. Lin et al., "JarvisArt: Liberating Human Artistic Creativity via an Intelligent Photo Retouching Agent" (2025). https://arxiv.org/abs/2506.17612 — 200+ Lightroom tools, trained agent.
47. Dutt et al., "MonetGPT: Solving Puzzles Enhances MLLMs' Image Retouching Skills" (2025). https://arxiv.org/abs/2505.06176 — procedural edits as in GIMP or Lightroom, planned by an MLLM.
48. Yao et al., "PhotoAgent: Exploratory Visual Aesthetic Planning with Large Vision Models" (2026). https://arxiv.org/abs/2602.22809
49. Zhu et al., "CanvasAgent: Enabling Complex Image Creation and Editing via Visual Tool Orchestration" (2026). https://arxiv.org/abs/2607.05465 — inspects intermediate results while orchestrating visual tools.
50. Zhu et al., "IEA: Amateur-Friendly Conversational Image Editing Agent via Three Stages of Multitask Alignment" (2026). https://arxiv.org/abs/2606.08016 — 16 parameterized editing tools, inspectable edit traces.
51. Gan and Sun, "RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection via Retrieval-Augmented Generation" (2025). https://arxiv.org/abs/2505.03275
52. Paramanayakam et al., "Less is More: Optimizing Function Calling for LLM Execution on Edge Devices" (2024). https://arxiv.org/abs/2411.15399
53. Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" (2025). https://arxiv.org/abs/2503.13657
54. gimp-mcp, agent evaluation of the 0.7.0 release PR (2026-11-12, 26/26, claude-sonnet-5-5), artifact `agent-evaluation` (report.md, report.json, transcripts). https://github.com/mhbxyz/gimp-mcp/actions/runs/43156042300

Repository files used: README.md, docs/tools.md, docs/toolsets.md, docs/api-conventions.md,
docs/architecture.md, docs/bridge-protocol.md, docs/testing.md, docs/install.md, docs/clients.md,
docs/adr/0001, 0005, 0006, 0007, 0012, docs/evals/README.md, docs/evals/baseline.md and baseline.json,
docs/demos/*/report.md, evals/harness.py, src/gimp_mcp/server.py, src/gimp_mcp/prompts.py,
src/gimp_mcp/toolkit.py, src/gimp_mcp/bridge.py, src/gimp_mcp/cli.py; open issues #181, #182, #184, #188.

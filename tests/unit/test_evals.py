"""Agent evaluation suite (#106): tasks, checks, transcript parsing, reports, and token handling.

No agent runs here: each task's checks are tried on a correct result made with Pillow (they must pass)
and on an empty output directory (they must fail).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.harness import TOKEN_ENV, docker_command, oauth_token, parse_transcript, regressions, scrub
from evals.tasks import TASKS
from gimp_mcp.toolsets import DEFAULT_TOOLSETS, check_toolset

ANSWERS = {"dominant-color": "The dominant color of flag.png is #E63946 (about 70% of the pixels)."}


def produce(task, tmp_path: Path) -> tuple[Path, Path]:
    inputs, out = tmp_path / "inputs", tmp_path / "out"
    inputs.mkdir()
    out.mkdir()
    task.make_inputs(inputs)
    for directory in task.out_dirs:
        (out / directory).mkdir()
    return inputs, out


def test_at_least_15_tasks_with_unique_names():
    names = [task.name for task in TASKS]
    assert len(names) >= 15 and len(set(names)) == len(names)


def test_tasks_cover_the_default_toolsets_and_optional_ones_the_agent_must_enable():
    used = {toolset for task in TASKS for toolset in task.toolsets}
    for toolset in used:
        check_toolset(toolset)
    assert set(DEFAULT_TOOLSETS) - {"core"} <= used
    assert len(used - set(DEFAULT_TOOLSETS)) >= 5


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.name)
def test_checks_accept_a_correct_result_and_reject_a_missing_one(task, tmp_path):
    inputs, out = produce(task, tmp_path)
    missing = task.check(out, "")
    assert missing and not all(check.passed for check in missing)
    task.reference(inputs, out)
    checks = task.check(out, ANSWERS.get(task.name, ""))
    assert all(check.passed for check in checks), [(c.description, c.detail) for c in checks if not c.passed]


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.name)
def test_the_prompt_names_every_input_and_output(task, tmp_path):
    inputs, out = produce(task, tmp_path)
    task.reference(inputs, out)
    for path in inputs.rglob("*.png"):
        relative = path.relative_to(inputs)
        assert f"~/inputs/{relative}" in task.prompt or f"~/inputs/{relative.parent}/" in task.prompt, relative
    for path in out.rglob("*"):
        if path.is_file():
            relative = path.relative_to(out)
            assert f"~/out/{relative}" in task.prompt or f"~/out/{relative.parent}/" in task.prompt, relative


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.name)
def test_inputs_are_deterministic(task, tmp_path):
    def digest(directory: Path) -> dict[str, str]:
        task.make_inputs(directory)
        return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.rglob("*") if p.is_file()}  # fmt: skip

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert digest(tmp_path / "a") == digest(tmp_path / "b")


TRANSCRIPT = [
    {"type": "system", "subtype": "init", "model": "claude-test",
     "tools": ["mcp__gimp__gimp_status", "mcp__gimp__gimp_open_image", "Task"]},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Opening."},
        {"type": "tool_use", "id": "t1", "name": "mcp__gimp__gimp_open_image", "input": {"path": "/x"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
        "content": [{"type": "text", "text": "FILE_NOT_FOUND: /x does not exist"}]}]}},
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "b1", "is_error": True,
        "content": "No such tool available: Bash"}]}},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t2", "name": "mcp__gimp__gimp_status", "input": {}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "{}"}]}},
    {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 12345, "num_turns": 3,
     "total_cost_usd": 0.12345, "result": "Done: #e63946",
     "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 900,
               "cache_creation_input_tokens": 10}},
]  # fmt: skip


def test_the_transcript_gives_calls_errors_tokens_and_duration():
    metrics = parse_transcript([json.dumps(event) for event in TRANSCRIPT] + ["not json", ""])
    assert metrics.model == "claude-test" and metrics.gimp_tools == 2
    assert metrics.tool_calls == ["gimp_open_image", "gimp_status"]
    assert metrics.errors == ["gimp_open_image: FILE_NOT_FOUND: /x does not exist"]  # gimp errors only
    assert metrics.other_tools == ["Bash"]
    assert (metrics.duration_s, metrics.turns, metrics.input_tokens, metrics.output_tokens) == (12.3, 3, 100, 50)
    assert (metrics.cache_read_tokens, metrics.cache_creation_tokens, metrics.cost_usd) == (900, 10, 0.1235)
    assert metrics.finished and metrics.answer == "Done: #e63946"


def test_a_session_without_result_is_not_finished():
    assert not parse_transcript([json.dumps(TRANSCRIPT[0])]).finished


def task_result(passed: bool) -> dict:
    return {"passed": passed, "checks": [{"description": "the output exists", "passed": passed, "detail": ""}]}


def test_a_task_that_passed_in_the_baseline_and_fails_now_is_a_regression():
    baseline = {"tasks": {"a": task_result(True), "b": task_result(False), "c": task_result(True)}}
    current = {
        "tasks": {"a": task_result(False), "b": task_result(False), "c": task_result(True), "new": task_result(False)}
    }
    assert regressions(baseline, current) == ["a: passed in the baseline, fails now (the output exists)"]


def test_the_token_is_passed_by_name_only(tmp_path):
    command = docker_command("n", tmp_path, "/w/gimp_mcp-1-py3-none-any.whl", "/usr/bin/claude", 2.0, None)
    position = command.index(TOKEN_ENV)
    assert command[position - 1] == "-e" and command.count(TOKEN_ENV) == 1
    assert not any(arg.startswith(f"{TOKEN_ENV}=") for arg in command)
    assert "--network=host" not in command and "--privileged" not in command


def test_a_file_containing_the_token_is_deleted_and_reported(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "transcript.jsonl").write_text('{"x": "sk-ant-oat01-SECRET"}')
    (tmp_path / "run" / "clean.txt").write_text("nothing here")
    leaked = scrub(tmp_path, "sk-ant-oat01-SECRET")
    assert leaked == [tmp_path / "run" / "transcript.jsonl"]
    assert not leaked[0].exists() and (tmp_path / "run" / "clean.txt").exists()


def test_the_token_comes_from_the_environment_or_the_local_login(tmp_path):
    assert oauth_token({TOKEN_ENV: "from-env", "HOME": str(tmp_path)}) == "from-env"
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "from-login"}})
    )
    assert oauth_token({"HOME": str(tmp_path)}) == "from-login"
    with pytest.raises(SystemExit, match="no CLAUDE_CODE_OAUTH_TOKEN") as refused:
        oauth_token({"HOME": str(tmp_path / "nobody")})
    assert "from-login" not in str(refused.value)


def test_the_workflow_runs_on_demand_and_on_release_prs_and_scopes_the_token():
    import yaml

    workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/evals.yml").read_text())
    assert set(workflow[True]) == {"workflow_dispatch", "pull_request"}  # YAML 1.1 reads `on` as True
    job = workflow["jobs"]["evals"]
    assert "startsWith(github.head_ref, 'release/')" in job["if"]
    assert workflow["permissions"] == {"contents": "read"} and "env" not in job
    value = "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
    with_token = [step for step in job["steps"] if value in step.get("env", {}).values()]
    assert len(with_token) == 1 and "evals/run.py" in with_token[0]["run"]  # only the evaluation step
    assert "secrets.CLAUDE_CODE_OAUTH_TOKEN != ''" in str(job["steps"][0])  # skipped, with a warning, without it


def test_gimp_3_linear_light_results_are_accepted(tmp_path):
    """GIMP 3 composites layers and blurs in linear light: 50% red over blue is (163, 61, 148), not the
    sRGB average, and a blurred black-and-white checkerboard averages 188 (both seen in the baseline run)."""
    from PIL import Image

    from evals.tasks import by_name

    overlay, blur = by_name("logo-overlay"), by_name("blur")
    inputs, out = produce(overlay, tmp_path)
    img = Image.open(inputs / "photo.png").convert("RGB")
    img.paste((163, 61, 148), (1000, 700, 1200, 800))
    img.save(out / "branded.png")
    assert all(check.passed for check in overlay.check(out, ""))
    Image.new("RGB", (256, 256), (188, 188, 188)).save(out / "blurred.png")
    assert all(check.passed for check in blur.check(out, ""))

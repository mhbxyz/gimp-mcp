"""Batch processing (#61): one recipe of tool calls run over many files.

The recipe is validated as a whole (tools, argument names and types, placeholders, outputs)
before the first file is opened. Each step is an ordinary call of a listed tool, so it keeps
that tool's own checks. See docs/adr/0006-batch-recipes.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools.base import Tool
from pydantic import BaseModel, Field, ValidationError

from ..batch import file_values, invalid, list_inputs, placeholders_in, plan_outputs, substitute
from ..errors import GimpMcpError
from ..ids import IdCodec
from ..toolkit import DESTRUCTIVE, Toolkit

# Tools a recipe may not call: the batch itself, toolset changes, and closing (the batch closes images).
FORBIDDEN = {"gimp_run_batch", "gimp_enable_toolsets", "gimp_close_image"}
MAX_STEPS = 50


class RecipeStep(BaseModel):
    tool: Annotated[str, Field(max_length=100, description="Name of a listed tool, e.g. gimp_scale_image.")]
    arguments: Annotated[
        dict[str, Any],
        Field(
            description="The tool's arguments. Strings may use placeholders: {image} (the opened image), "
            "{layer} (its top layer), {output} (the output path, as a whole value), {file}, {name}, {stem}, "
            "{ext}, {dir}, {index} (1-based; '{index}' alone is a number, {index:03d} is formatted)."
        ),
    ] = {}


class StepError(BaseModel):
    step: int | None = Field(description="0-based index of the failed step; null when opening the file failed.")
    tool: str
    code: str
    message: str
    hint: str | None = None


class FileResult(BaseModel):
    file: str
    status: Literal["ok", "failed", "skipped", "planned"]
    image: str | None = Field(default=None, description="Id the file had while it was open.")
    output: str | None = Field(default=None, description="Output path from the naming pattern.")
    outputs: list[str] = Field(default_factory=list, description="Files written for this input.")
    closed: list[str] = Field(default_factory=list, description="Images the batch closed after this file.")
    error: StepError | None = None


class BatchReport(BaseModel):
    dry_run: bool
    total: int
    succeeded: int
    failed: int
    skipped: int
    files: list[FileResult]


def register(kit: Toolkit) -> None:
    models: dict[str, Tool] = {}

    def tool_model(name: str) -> Tool:
        entry = kit.catalog[name]
        if name not in models:
            assert entry.handler is not None
            models[name] = Tool.from_function(entry.handler, name=name)
        return models[name]

    def check_steps(recipe: list[RecipeStep]) -> set[str]:
        """Static checks; returns the placeholders the recipe uses."""
        used: set[str] = set()
        for index, step in enumerate(recipe):
            where = f"step {index} ({step.tool})"
            entry = kit.catalog.get(step.tool)
            if entry is None:
                raise invalid(f"{where}: unknown tool", step=index)
            if step.tool in FORBIDDEN:
                raise invalid(f"{where}: this tool cannot be used in a recipe", step=index)
            if entry.toolset not in kit.enabled:
                raise invalid(
                    f"{where}: the {entry.toolset} toolset is not enabled",
                    hint=f"Enable the {entry.toolset} toolset with gimp_enable_toolsets first.",
                    step=index,
                )
            names = {
                field.alias or key for key, field in tool_model(step.tool).fn_metadata.arg_model.model_fields.items()
            }
            unknown = sorted(set(step.arguments) - names)
            if unknown:
                raise invalid(f"{where}: unknown arguments {unknown}", step=index, arguments=sorted(names))
            try:
                step_used = placeholders_in(step.arguments)
            except GimpMcpError as error:
                raise invalid(f"{where}: {error.message}", step=index) from error
            if "output" in step_used:
                if "overwrite" not in names:
                    raise invalid(f"{where}: {{output}} is only for tools that write a file", step=index)
                if "overwrite" in step.arguments:
                    raise invalid(f"{where}: set overwrite on the batch, not on the step", step=index)
                if any(_has_output(v) and v != "{output}" for v in _strings(step.arguments)):
                    raise invalid(f"{where}: {{output}} must be a whole argument value", step=index)
            used |= step_used
        return used

    def step_arguments(step: RecipeStep, values: dict[str, Any], overwrite: bool) -> dict[str, Any]:
        arguments = substitute(step.arguments, values)
        if _has_output_anywhere(step.arguments):
            arguments["overwrite"] = overwrite
        return arguments

    def check_types(recipe: list[RecipeStep], sample: dict[str, Any]) -> None:
        for index, step in enumerate(recipe):
            model = tool_model(step.tool).fn_metadata.arg_model
            try:
                model.model_validate(step_arguments(step, sample, False))
            except ValidationError as error:
                problems = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors(include_url=False)
                )
                raise invalid(f"step {index} ({step.tool}): {problems}", step=index) from error

    @kit.tool(
        toolset="batch",
        name="gimp_run_batch",
        title="Run a recipe over many files",
        description=(
            "Apply the same recipe (a list of tool calls) to many files: explicit files, or a glob pattern "
            "inside a directory (the pattern cannot leave it). Each file is opened, the steps run with "
            "placeholders filled in ({image}, {layer}, {output}, {stem}...), and every image the batch opened "
            "or a step created is closed without saving. Outputs follow the naming pattern `output` "
            "(e.g. ~/out/{stem}.webp), written by a step whose path is '{output}'; existing files are never "
            "replaced unless overwrite=true, and inputs never are. Everything is validated before the first "
            "file is opened; dry_run=true only validates and returns the plan. Reports success, failure "
            "(step, error) and outputs per file; continue_on_error=false stops at the first failure."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_run_batch(
        recipe: Annotated[list[RecipeStep], Field(min_length=1, max_length=MAX_STEPS)],
        ctx: Context,
        files: Annotated[list[str] | None, Field(max_length=10_000, description="Absolute input paths.")] = None,
        directory: Annotated[str | None, Field(description="Absolute directory searched with pattern.")] = None,
        pattern: Annotated[
            str, Field(max_length=200, description="Glob relative to directory, e.g. '**/*.jpg'.")
        ] = "*",
        output: Annotated[
            str | None,
            Field(max_length=1000, description="Output naming pattern with {stem}, {name}, {ext}, {dir}, {index}."),
        ] = None,
        overwrite: bool = False,
        continue_on_error: bool = True,
        dry_run: bool = False,
        max_files: Annotated[int, Field(ge=1, le=10_000)] = 200,
    ) -> BatchReport:
        used = check_steps(recipe)
        if "output" in used and output is None:
            raise invalid("the recipe uses {output} but no output pattern is given")
        if output is not None and "output" not in used:
            raise invalid("an output pattern is given but no step writes to {output}")
        inputs = list_inputs(files, directory, pattern, max_files)
        outputs = plan_outputs(inputs, output, overwrite=overwrite)
        codec = await kit.codec()
        sample = {
            **file_values(inputs[0], 1),
            "image": codec.image(0),
            "layer": codec.item(0),
            "output": str(outputs[0]),
        }
        check_types(recipe, sample)

        if dry_run:
            results = [
                FileResult(file=str(path), status="planned", output=str(out) if out else None)
                for path, out in zip(inputs, outputs, strict=True)
            ]
            return report(True, results)

        before = {codec.image(image["id"]) for image in (await kit.call("session.images", codec=codec))["images"]}
        results: list[FileResult] = []
        stop = False
        for index, (path, out) in enumerate(zip(inputs, outputs, strict=True), start=1):
            if stop:
                results.append(FileResult(file=str(path), status="skipped", output=str(out) if out else None))
                continue
            result = await run_file(ctx, codec, recipe, used, path, index, out, overwrite, before)
            results.append(result)
            stop = result.status == "failed" and not continue_on_error
        return report(False, results)

    async def run_file(
        ctx: Context,
        codec: IdCodec,
        recipe: list[RecipeStep],
        used: set[str],
        path: Path,
        index: int,
        out: Path | None,
        overwrite: bool,
        before: set[str],
    ) -> FileResult:
        result = FileResult(file=str(path), status="ok", output=str(out) if out else None)
        image_pattern = re.compile(rf"^image:\d+@{re.escape(codec.session_id)}$")
        created: list[str] = []

        def track(value: Any) -> None:
            for text in _strings(value):
                if image_pattern.match(text) and text not in before and text not in created:
                    created.append(text)

        try:
            data, error = await call_tool(ctx, "gimp_open_image", {"path": str(path)}, None)
            if error is not None:
                result.status, result.error = "failed", error
                return result
            result.image = data["id"]
            track(data)
            values = {**file_values(path, index), "image": data["id"], "output": str(out) if out else ""}
            if "layer" in used:
                layers = (await kit.call("image.inspect", {"image": codec.parse_image(data["id"])}, codec=codec))[
                    "layers"
                ]
                values["layer"] = codec.item(layers[0]["id"]) if layers else ""
            for number, step in enumerate(recipe):
                data, error = await call_tool(ctx, step.tool, step_arguments(step, values, overwrite), number)
                if error is not None:
                    result.status, result.error = "failed", error
                    return result
                track(data)
            if out is not None and out.exists():
                result.outputs.append(str(out))
            return result
        finally:
            for image in created:
                try:
                    await kit.call(
                        "image.close",
                        {"image": codec.parse_image(image), "discard_changes": True},
                        codec=codec,
                        mutating=True,
                    )
                except GimpMcpError:
                    continue  # already closed
                result.closed.append(image)

    async def call_tool(
        ctx: Context, name: str, arguments: dict[str, Any], step: int | None
    ) -> tuple[Any, StepError | None]:
        try:
            called = await kit.mcp.call_tool(name, arguments, ctx)
        except Exception as error:  # argument validation: the SDK raises ToolError
            return None, StepError(step=step, tool=name, code="INVALID_ARGUMENT", message=str(error))
        structured = getattr(called, "structured_content", None) or {}
        if getattr(called, "is_error", False):
            details = structured.get("error") or {}
            text = " ".join(getattr(block, "text", "") for block in getattr(called, "content", []))
            return None, StepError(
                step=step,
                tool=name,
                code=details.get("code", "TOOL_ERROR"),
                message=details.get("message", text),
                hint=details.get("hint"),
            )
        return structured, None


def report(dry_run: bool, results: list[FileResult]) -> BatchReport:
    count = {status: sum(1 for r in results if r.status == status) for status in ("ok", "failed", "skipped")}
    return BatchReport(
        dry_run=dry_run,
        total=len(results),
        succeeded=count["ok"],
        failed=count["failed"],
        skipped=count["skipped"],
        files=results,
    )


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list | tuple):
        return [s for v in value for s in _strings(v)]
    return []


def _has_output(text: str) -> bool:
    return "{output}" in text


def _has_output_anywhere(arguments: dict[str, Any]) -> bool:
    return any(_has_output(text) for text in _strings(arguments))

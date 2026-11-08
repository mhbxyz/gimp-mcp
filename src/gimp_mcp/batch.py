"""Batch processing (#61): inputs, placeholders and outputs of a recipe run over many files.

GIMP-free and side-effect free: everything here is checked before the first file is opened.
See docs/adr/0006-batch-recipes.md.
"""

from __future__ import annotations

import os
import string
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import GimpMcpError
from .paths import check_input_file, check_output_file

# {image}, {layer} and {output} are only known while running; the others come from the input path.
FILE_PLACEHOLDERS = ("file", "name", "stem", "ext", "dir", "index")
RUN_PLACEHOLDERS = ("image", "layer", "output")
PLACEHOLDERS = FILE_PLACEHOLDERS + RUN_PLACEHOLDERS
OUTPUT_PLACEHOLDERS = ("name", "stem", "ext", "dir", "index")

_FORMATTER = string.Formatter()


def invalid(message: str, hint: str | None = None, **details: Any) -> GimpMcpError:
    return GimpMcpError("INVALID_ARGUMENT", message, hint=hint, details=details)


def placeholders(text: str, allowed: Sequence[str] = PLACEHOLDERS) -> set[str]:
    """The placeholders used in ``text`` ({{ and }} are literal braces)."""
    try:
        fields = [field for _, field, _, _ in _FORMATTER.parse(text) if field is not None]
    except ValueError as error:
        raise invalid(f"malformed placeholder in {text!r}: {error}") from error
    for field in fields:
        if field not in allowed:
            raise invalid(
                f"unknown placeholder {{{field}}} in {text!r}",
                allowed=[f"{{{name}}}" for name in allowed],
            )
    return set(fields)


def placeholders_in(value: Any) -> set[str]:
    """Placeholders used anywhere in a JSON-like argument value."""
    if isinstance(value, str):
        return placeholders(value)
    if isinstance(value, Mapping):
        return set().union(*(placeholders_in(v) for v in value.values())) if value else set()
    if isinstance(value, list | tuple):
        return set().union(*(placeholders_in(v) for v in value)) if value else set()
    return set()


def substitute(value: Any, values: Mapping[str, Any]) -> Any:
    """Replace placeholders in strings; ``"{index}"`` alone becomes the integer."""
    if isinstance(value, str):
        if value == "{index}":
            return values["index"]
        try:
            return _FORMATTER.vformat(value, (), dict(values))
        except (ValueError, KeyError) as error:
            raise invalid(f"cannot substitute placeholders in {value!r}: {error}") from error
    if isinstance(value, Mapping):
        return {key: substitute(v, values) for key, v in value.items()}
    if isinstance(value, list | tuple):
        return [substitute(v, values) for v in value]
    return value


def file_values(path: Path, index: int) -> dict[str, Any]:
    return {
        "file": str(path),
        "name": path.name,
        "stem": path.stem,
        "ext": path.suffix.lstrip("."),
        "dir": str(path.parent),
        "index": index,
    }


def list_inputs(files: Sequence[str] | None, directory: str | None, pattern: str, max_files: int) -> list[Path]:
    """Explicit files, or the regular files matching ``pattern`` inside ``directory`` (sorted)."""
    if (files is None) == (directory is None):
        raise invalid("give either files or directory (with a pattern), not both")
    if files is not None:
        found = [check_input_file(path) for path in files]
        if len(set(found)) != len(found):
            raise invalid("the same file is listed twice")
    else:
        found = _glob(directory or "", pattern)
    if not found:
        raise invalid("no input file", directory=directory, pattern=pattern)
    if len(found) > max_files:
        raise invalid(
            f"{len(found)} files match, more than max_files={max_files}",
            hint="Narrow the pattern or raise max_files.",
        )
    return found


def _glob(directory: str, pattern: str) -> list[Path]:
    root = Path(os.path.expanduser(directory))
    if not root.is_absolute():
        raise invalid(f"directory {directory!r} is relative: give an absolute path")
    if not root.is_dir():
        raise GimpMcpError("FILE_NOT_FOUND", f"{root} is not a directory", details={"directory": str(root)})
    if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise invalid(f"pattern {pattern!r} must be relative to the directory, without '..'")
    real_root = root.resolve()
    matches = []
    for path in root.glob(pattern):
        # symlinks are allowed only when they stay inside the directory
        if not path.is_file() or not path.resolve().is_relative_to(real_root):
            continue
        matches.append(path)
    return sorted(matches)


def plan_outputs(inputs: Sequence[Path], pattern: str | None, *, overwrite: bool) -> list[Path | None]:
    """The output path of each input: absolute, unique, never an input, existing only when overwrite."""
    if pattern is None:
        return [None] * len(inputs)
    placeholders(pattern, OUTPUT_PLACEHOLDERS)
    outputs = [
        check_output_file(substitute(pattern, file_values(path, index)), overwrite=overwrite)
        for index, path in enumerate(inputs, start=1)
    ]
    if len(set(outputs)) != len(outputs):
        raise invalid(
            f"output pattern {pattern!r} gives the same file for several inputs",
            hint="Use {stem}, {name} or {index} in the output pattern.",
        )
    resolved_inputs = {path.resolve() for path in inputs}
    for output in outputs:
        if output.resolve() in resolved_inputs:
            raise invalid(f"output {output} would replace an input file", output=str(output))
    return list(outputs)

"""Argument validation failures as gimp-mcp errors (#146).

The MCP SDK validates a tool's arguments against its input schema before the tool runs and reports a
failure as framework text (pydantic's message, model class names, documentation URLs). Agents get
instead an ``INVALID_ARGUMENT`` error naming each field at fault and a hint listing the tool's
parameters, so they can fix the call in one retry.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from pydantic import ValidationError

from .errors import GimpMcpError

_INSTANCE_OF = re.compile(r" or instance of \w+")


def _describe(schema: dict[str, Any], defs: dict[str, Any]) -> str:
    """A short type for the hint: 'rgb'|'gray', integer 1..100, string, object."""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        schema = defs.get(ref.rsplit("/", 1)[-1], {})
    variants = schema.get("anyOf")
    if variants:
        return " or ".join(_describe(v, defs) for v in variants if v.get("type") != "null")
    if "enum" in schema:
        return "|".join(repr(value) for value in schema["enum"])
    kind = str(schema.get("type", "value"))
    low, high = schema.get("minimum"), schema.get("maximum")
    if low is not None or high is not None:
        kind += f" {'' if low is None else low}..{'' if high is None else high}"
    return kind


def _expected_keys(schema: dict[str, Any], loc: tuple[Any, ...]) -> list[str]:
    """The property names allowed where an unknown key was found (``loc`` without the key itself)."""
    defs: dict[str, Any] = schema.get("$defs", {})
    node: dict[str, Any] = schema

    def resolve(item: dict[str, Any]) -> dict[str, Any]:
        ref = item.get("$ref")
        if isinstance(ref, str):
            return defs.get(ref.rsplit("/", 1)[-1], {})
        variants = [v for v in item.get("anyOf", []) if v.get("type") != "null"]
        return resolve(variants[0]) if len(variants) == 1 else item

    for part in loc:
        node = resolve(node)
        # a list index goes into the items, a name into the properties
        node = node.get("items", {}) if isinstance(part, int) else node.get("properties", {}).get(str(part), {})
    return list(resolve(node).get("properties", {}))


def _problem(error: Any, schema: dict[str, Any] | None = None) -> str:
    if error["type"] == "missing":
        return "missing"
    if error["type"] == "extra_forbidden" and schema is not None:
        expected = _expected_keys(schema, tuple(error["loc"][:-1]))
        return "unknown key" + (f"; expected: {', '.join(expected)}" if expected else "")
    message = _INSTANCE_OF.sub("", str(error["msg"]))
    message = re.sub(r"^Input should", "should", message)
    message = re.sub(r"^Value error, ", "", message)
    received = error.get("input")
    if received is not None and not isinstance(received, (dict, list)):
        message += f" (got {received!r})"[:80]
    return message


def invalid_arguments(
    tool: str, schema: dict[str, Any], arguments: dict[str, Any], error: ValidationError
) -> GimpMcpError:
    properties: dict[str, Any] = schema.get("properties", {})
    defs: dict[str, Any] = schema.get("$defs", {})
    required: list[str] = list(schema.get("required", []))
    problems = [
        {"field": ".".join(str(part) for part in e["loc"]) or "(arguments)", "problem": _problem(e, schema)}
        for e in error.errors(include_url=False)
    ]
    unknown = sorted(name for name in arguments if name not in properties)
    parts = [f"{p['field']}: {p['problem']}" for p in problems]
    missing = [p["field"] for p in problems if p["problem"] == "missing"]
    for name in unknown:
        # One unknown name and one missing parameter: almost always the same argument under another name.
        close = missing if len(unknown) == len(missing) == 1 else difflib.get_close_matches(name, properties, 1, 0.6)
        parts.append(f"{name}: unknown argument" + (f" (did you mean {close[0]}?)" if close else ""))
    needed = ", ".join(f"{name} ({_describe(properties.get(name, {}), defs)})" for name in required)
    optional = ", ".join(name for name in properties if name not in required)
    hint = f"{tool} requires {needed or 'no argument'}"
    hint += f"; optional: {optional}." if optional else "."
    details: dict[str, Any] = {"errors": problems, "required": required}
    if unknown:
        details["unknown"] = unknown
    return GimpMcpError(
        "INVALID_ARGUMENT", f"invalid arguments for {tool}: " + "; ".join(parts), hint=hint, details=details
    )


def signature(tool: str, schema: dict[str, Any]) -> str:
    """One line to call a tool: required parameters with their types, optional ones with '?'."""
    properties: dict[str, Any] = schema.get("properties", {})
    defs: dict[str, Any] = schema.get("$defs", {})
    required = list(schema.get("required", []))
    parts = [f"{name}: {_describe(properties.get(name, {}), defs)}" for name in required]
    parts += [f"{name}?" for name in properties if name not in required]
    return f"{tool}({', '.join(parts)})"


def toolset_disabled(tool: str, toolset: str) -> GimpMcpError:
    return GimpMcpError(
        "TOOLSET_DISABLED",
        f"{tool} belongs to the toolset {toolset!r}, which is not enabled",
        hint=f"Call gimp_enable_toolsets with toolsets=[{toolset!r}], then call {tool} again.",
        details={"tool": tool, "toolset": toolset},
    )

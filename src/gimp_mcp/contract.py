"""The public API contract (docs/compatibility.md) as data, and the breaking-change checker (#116).

``collect_contract()`` gathers what clients depend on: every tool (name, toolset, input and output
schemas, annotations), the error codes, prompts, resources and CLI commands with their options.
Descriptions and titles are left out: rewording is not a contract change. ``compare(old, new)`` lists
every difference as compatible or breaking; ``verdict`` decides whether a set of changes may merge.
``scripts/api_contract.py`` writes the snapshot (docs/api/contract.json) and runs the check in CI.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["compatible", "breaking"]
Direction = Literal["input", "output"]
JSON = dict[str, Any]

# Schema keywords that document rather than constrain.
_DOC_KEYWORDS = {"description", "title", "examples"}


@dataclass(frozen=True)
class Change:
    kind: Kind
    where: str
    what: str


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


# --- collecting -------------------------------------------------------------------------------------


def _strip_docs(schema: Any) -> Any:
    """The schema without documentation keywords (property *names* such as ``title`` are kept)."""
    if isinstance(schema, list):
        return [_strip_docs(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: JSON = {}
    for key, value in schema.items():
        if key in _DOC_KEYWORDS:
            continue
        if key in ("properties", "$defs"):
            out[key] = {name: _strip_docs(sub) for name, sub in value.items()}
        else:
            out[key] = _strip_docs(value)
    return out


def _cli_contract(parser: argparse.ArgumentParser) -> JSON:
    def options(command: argparse.ArgumentParser) -> JSON:
        result: JSON = {}
        for action in command._actions:  # pyright: ignore[reportPrivateUsage]
            if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):  # pyright: ignore[reportPrivateUsage]
                continue
            name = max(action.option_strings, key=len) if action.option_strings else action.dest
            entry: JSON = {"required": bool(action.required) or not action.option_strings}
            if action.choices is not None:
                entry["choices"] = sorted(str(choice) for choice in action.choices)
            result[name] = entry
        return result

    contract: JSON = {"": options(parser)}
    for action in parser._actions:  # pyright: ignore[reportPrivateUsage]
        if isinstance(action, argparse._SubParsersAction):  # pyright: ignore[reportPrivateUsage]
            for name, sub in action.choices.items():
                contract[name] = options(sub)
    return contract


async def _collect() -> JSON:
    from mcp import Client

    from .cli import build_parser
    from .errors import ERROR_CODES
    from .server import build_server

    server = build_server(toolsets="all", env={})
    catalog = server.gimp_toolkit.catalog  # type: ignore[attr-defined]
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
        prompts = (await client.list_prompts()).prompts
        resources = (await client.list_resources()).resources
        templates = (await client.list_resource_templates()).resource_templates
    contract_tools: JSON = {}
    for tool in tools:
        data = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        contract_tools[tool.name] = {
            "toolset": catalog[tool.name].toolset,
            "annotations": data.get("annotations", {}),
            "inputSchema": _strip_docs(data["inputSchema"]),
            **({"outputSchema": _strip_docs(data["outputSchema"])} if "outputSchema" in data else {}),
        }
    return {
        "tools": contract_tools,
        "error_codes": sorted(ERROR_CODES),
        "prompts": {
            prompt.name: {"arguments": {arg.name: bool(arg.required) for arg in prompt.arguments or []}}
            for prompt in prompts
        },
        # Static resources only: per-image resources (gimp://images/<id>/...) depend on GIMP's state.
        "resources": sorted(str(resource.uri) for resource in resources),
        "resource_templates": sorted(template.uri_template for template in templates),
        "cli": _cli_contract(build_parser()),
    }


def collect_contract() -> JSON:
    import anyio

    return anyio.run(_collect)


def render_contract(contract: JSON) -> str:
    return json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --- comparing --------------------------------------------------------------------------------------


class _Schemas:
    """Compare two JSON schemas of one direction, following ``$ref`` into each side's ``$defs``."""

    def __init__(self, old_root: JSON, new_root: JSON, where: str, direction: Direction):
        self.old_defs = old_root.get("$defs", {})
        self.new_defs = new_root.get("$defs", {})
        self.where = where
        self.direction = direction
        self.changes: list[Change] = []
        self._seen: set[tuple[str, str]] = set()

    def _add(self, path: str, what: str, *, narrows: bool) -> None:
        """``narrows``: the change accepts fewer inputs (input) or promises less (output)."""
        kind: Kind = "breaking" if narrows else "compatible"
        self.changes.append(Change(kind, f"{self.where}: {self.direction} {path}".rstrip(), what))

    def _resolve(self, schema: JSON, defs: JSON) -> tuple[JSON, str | None]:
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.removeprefix("#/$defs/")
            return defs.get(name, {}), name
        return schema, None

    @staticmethod
    def _split_nullable(schema: JSON) -> tuple[JSON, bool, list[JSON] | None]:
        """(the schema without ``null``, nullable, remaining variants when several)."""
        variants = schema.get("anyOf") or schema.get("oneOf")
        if variants is None:
            types = schema.get("type")
            if isinstance(types, list) and "null" in types:
                rest = [t for t in types if t != "null"]
                return {**schema, "type": rest[0] if len(rest) == 1 else rest}, True, None
            return schema, False, None
        others = [v for v in variants if v != {"type": "null"}]
        nullable = len(others) != len(variants)
        base = {k: v for k, v in schema.items() if k not in ("anyOf", "oneOf")}
        if len(others) == 1:
            return {**others[0], **base}, nullable, None
        return base, nullable, others

    def compare(self, old: JSON, new: JSON, path: str = "") -> None:
        old, old_ref = self._resolve(old, self.old_defs)
        new, new_ref = self._resolve(new, self.new_defs)
        if old_ref and new_ref:
            if (old_ref, new_ref) in self._seen:
                return  # recursive model: already compared
            self._seen.add((old_ref, new_ref))
        old, old_null, old_variants = self._split_nullable(old)
        new, new_null, new_variants = self._split_nullable(new)
        widen = self.direction == "input"  # accepting more is compatible for inputs, not for outputs
        if old_null != new_null:
            # Inputs: refusing null narrows. Outputs: returning null where a value was promised narrows.
            self._add(path, "null " + ("now allowed" if new_null else "no longer allowed"),
                      narrows=(not new_null) if widen else new_null)  # fmt: skip
        if old_variants is not None or new_variants is not None:
            self._compare_variants(old_variants or [old], new_variants or [new], path)
            return
        old, _ = self._resolve(old, self.old_defs)
        new, _ = self._resolve(new, self.new_defs)
        self._compare_type(old, new, path)
        self._compare_enum(old, new, path)
        self._compare_bounds(old, new, path)
        for key in ("const", "pattern", "format"):
            if old.get(key) != new.get(key):
                self._add(path, f"{key} changed from {old.get(key)!r} to {new.get(key)!r}", narrows=widen)
        if self.direction == "input" and "default" in old and "default" in new and old["default"] != new["default"]:
            self._add(path, f"default changed from {old['default']!r} to {new['default']!r}", narrows=True)
        if "properties" in old or "properties" in new:
            self._compare_properties(old, new, path)
        if "items" in old and "items" in new:
            self.compare(old["items"], new["items"], f"{path}[]")
        elif "prefixItems" in old and "prefixItems" in new:
            for index, (a, b) in enumerate(zip(old["prefixItems"], new["prefixItems"], strict=False)):
                self.compare(a, b, f"{path}[{index}]")

    def _compare_variants(self, old: list[JSON], new: list[JSON], path: str) -> None:
        def key(schema: JSON) -> str:
            return json.dumps(self._resolve(schema, {})[0], sort_keys=True)

        old_keys, new_keys = {key(v) for v in old}, {key(v) for v in new}
        widen = self.direction == "input"
        if old_keys - new_keys:
            self._add(path, f"type variants removed: {sorted(old_keys - new_keys)}", narrows=widen)
        if new_keys - old_keys:
            self._add(path, f"type variants added: {sorted(new_keys - old_keys)}", narrows=not widen)

    @staticmethod
    def _types(schema: JSON) -> set[str]:
        value = schema.get("type")
        if value is None:
            return set()
        types = {value} if isinstance(value, str) else set(value)
        return types | ({"integer"} if "number" in types else set())

    def _compare_type(self, old: JSON, new: JSON, path: str) -> None:
        old_types, new_types = self._types(old), self._types(new)
        if old_types == new_types or not old_types or not new_types:
            if bool(old_types) != bool(new_types):
                # A type appears (narrower) or disappears (anything goes).
                self._add(path, f"type changed from {old.get('type')} to {new.get('type')}",
                          narrows=bool(new_types) == (self.direction == "input"))  # fmt: skip
            return
        wider = old_types < new_types
        narrower = new_types < old_types
        if wider or narrower:
            narrows = narrower if self.direction == "input" else wider
            self._add(path, f"type changed from {old.get('type')} to {new.get('type')}", narrows=narrows)
        else:
            self._add(path, f"type changed from {old.get('type')} to {new.get('type')}", narrows=True)

    def _compare_enum(self, old: JSON, new: JSON, path: str) -> None:
        if "enum" not in old and "enum" not in new:
            return
        if "enum" not in old or "enum" not in new:
            restricted = "enum" in new
            self._add(path, "values " + ("restricted to a list" if restricted else "no longer restricted"),
                      narrows=restricted == (self.direction == "input"))  # fmt: skip
            return
        removed = [v for v in old["enum"] if v not in new["enum"]]
        added = [v for v in new["enum"] if v not in old["enum"]]
        widen = self.direction == "input"
        if removed:
            self._add(path, f"values removed: {removed}", narrows=widen)
        if added:
            self._add(path, f"values added: {added}", narrows=not widen)

    def _compare_bounds(self, old: JSON, new: JSON, path: str) -> None:
        lower = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
        upper = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")
        widen = self.direction == "input"
        for key in (*lower, *upper):
            a, b = old.get(key), new.get(key)
            if a == b:
                continue
            # A bound that appears tightens; one that disappears loosens.
            tighter = (b is not None) if a is None or b is None else (b > a if key in lower else b < a)
            self._add(path, f"{key} changed from {a} to {b}", narrows=tighter == widen)

    def _compare_properties(self, old: JSON, new: JSON, path: str) -> None:
        old_props, new_props = old.get("properties", {}), new.get("properties", {})
        old_req, new_req = set(old.get("required", [])), set(new.get("required", []))
        prefix = f"{path}." if path else ""
        output = self.direction == "output"
        for name in old_props:
            if name not in new_props:
                self._add(prefix + name, "output field removed" if output else "parameter removed", narrows=True)
        for name in new_props:
            if name in old_props:
                continue
            if output:
                self._add(prefix + name, "new output field", narrows=False)
            elif name in new_req:
                self._add(prefix + name, "new required parameter", narrows=True)
            else:
                self._add(prefix + name, "new optional parameter", narrows=False)
        for name in old_props:
            if name not in new_props:
                continue
            if (name in old_req) != (name in new_req):
                if output:
                    gone = name in old_req
                    self._add(prefix + name, "may be missing now" if gone else "always present now", narrows=gone)
                else:
                    now = name in new_req
                    self._add(prefix + name, "now required" if now else "now optional", narrows=now)
            self.compare(old_props[name], new_props[name], prefix + name)
        a, b = old.get("additionalProperties", True), new.get("additionalProperties", True)
        if (a is False) != (b is False):
            closed = b is False
            self._add(path or "(object)", "extra properties " + ("refused" if closed else "accepted"),
                      narrows=closed == (self.direction == "input"))  # fmt: skip


def _compare_tool(name: str, old: JSON, new: JSON) -> Iterator[Change]:
    where = f"tool {name}"
    if old.get("toolset") != new.get("toolset"):
        yield Change("breaking", where, f"moved from toolset {old.get('toolset')} to {new.get('toolset')}")
    old_ann, new_ann = old.get("annotations", {}), new.get("annotations", {})
    if old_ann.get("readOnlyHint") is True and new_ann.get("readOnlyHint") is not True:
        yield Change("breaking", where, "no longer read-only")
    elif old_ann.get("destructiveHint") is False and new_ann.get("destructiveHint") is True:
        yield Change("breaking", where, "now destructive")
    elif old_ann != new_ann:
        yield Change("compatible", where, f"annotations changed: {new_ann}")
    schemas = _Schemas(old["inputSchema"], new["inputSchema"], where, "input")
    schemas.compare(old["inputSchema"], new["inputSchema"])
    yield from schemas.changes
    if "outputSchema" in old and "outputSchema" not in new:
        yield Change("breaking", where, "output schema removed")
    elif "outputSchema" in new and "outputSchema" not in old:
        yield Change("compatible", where, "output schema added")
    elif "outputSchema" in old:
        schemas = _Schemas(old["outputSchema"], new["outputSchema"], where, "output")
        schemas.compare(old["outputSchema"], new["outputSchema"])
        yield from schemas.changes


def _compare_names(old: list[str], new: list[str], label: str) -> Iterator[Change]:
    for name in old:
        if name not in new:
            yield Change("breaking", f"{label} {name}", "removed")
    for name in new:
        if name not in old:
            yield Change("compatible", f"{label} {name}", "added")


def _compare_arguments(where: str, old: JSON, new: JSON, noun: str) -> Iterator[Change]:
    """Prompt arguments or CLI options: ``{name: required}`` or ``{name: {"required": ...}}``."""

    def required(value: Any) -> bool:
        return bool(value["required"] if isinstance(value, dict) else value)

    for name, value in old.items():
        if name not in new:
            yield Change("breaking", f"{where} {name}", f"{noun} removed")
        elif required(new[name]) and not required(value):
            yield Change("breaking", f"{where} {name}", "now required")
        elif required(value) and not required(new[name]):
            yield Change("compatible", f"{where} {name}", "now optional")
        if name in new and isinstance(value, dict) and "choices" in value:
            removed = [c for c in value["choices"] if c not in new[name].get("choices", value["choices"])]
            added = [c for c in new[name].get("choices", []) if c not in value["choices"]]
            if removed:
                yield Change("breaking", f"{where} {name}", f"choices removed: {removed}")
            if added:
                yield Change("compatible", f"{where} {name}", f"choices added: {added}")
    for name, value in new.items():
        if name not in old:
            yield Change("breaking" if required(value) else "compatible", f"{where} {name}",
                         f"new {'required' if required(value) else 'optional'} {noun}")  # fmt: skip


def compare(old: JSON, new: JSON) -> list[Change]:
    """Every difference between two contracts, classified."""
    changes: list[Change] = []
    old_tools, new_tools = old.get("tools", {}), new.get("tools", {})
    for name in old_tools:
        if name not in new_tools:
            changes.append(Change("breaking", f"tool {name}", "removed"))
    for name in new_tools:
        if name not in old_tools:
            changes.append(Change("compatible", f"tool {name}", "added"))
        else:
            changes.extend(_compare_tool(name, old_tools[name], new_tools[name]))
    changes.extend(_compare_names(old.get("error_codes", []), new.get("error_codes", []), "error code"))
    changes.extend(_compare_names(old.get("resources", []), new.get("resources", []), "resource"))
    changes.extend(
        _compare_names(old.get("resource_templates", []), new.get("resource_templates", []), "resource template")
    )
    old_prompts, new_prompts = old.get("prompts", {}), new.get("prompts", {})
    changes.extend(_compare_names(list(old_prompts), list(new_prompts), "prompt"))
    for name in old_prompts.keys() & new_prompts.keys():
        changes.extend(
            _compare_arguments(
                f"prompt {name}", old_prompts[name]["arguments"], new_prompts[name]["arguments"], "argument"
            )
        )
    old_cli, new_cli = old.get("cli", {}), new.get("cli", {})
    changes.extend(_compare_names(list(old_cli), list(new_cli), "CLI command"))
    for name in old_cli.keys() & new_cli.keys():
        changes.extend(_compare_arguments(f"CLI {name or 'gimp-mcp'}", old_cli[name], new_cli[name], "option"))
    return changes


# --- deciding ---------------------------------------------------------------------------------------


def _unreleased(changelog: str) -> str:
    match = re.search(r"^## \[Unreleased\]\s*$(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    return match.group(1) if match else ""


def _major(version: str) -> int:
    return int(version.split(".")[0])


def verdict(changes: list[Change], changelog: str, old_version: str, new_version: str) -> Verdict:
    """Breaking changes need a ``### Breaking`` entry under ``## [Unreleased]`` in the CHANGELOG and,
    from 1.0 on, a new major version."""
    breaking = [change for change in changes if change.kind == "breaking"]
    if not breaking:
        return Verdict(True)
    reasons = []
    section = re.search(r"^### Breaking\s*$(.*?)(?=^##|\Z)", _unreleased(changelog), re.M | re.S)
    if not section or not re.search(r"^\s*[-*] \S", section.group(1), re.M):
        reasons.append("breaking changes need an entry under '### Breaking' in CHANGELOG.md's Unreleased section")
    if _major(old_version) >= 1 and _major(new_version) <= _major(old_version):
        reasons.append(f"breaking changes after 1.0 need a new major version (base {old_version}, now {new_version})")
    return Verdict(not reasons, reasons)

"""Controlled access to compatible GIMP procedures (allowlist, typed arguments, no code execution)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from ..toolkit import DESTRUCTIVE, READ_ONLY, Toolkit
from .procedures import Argument


class CallableProcedure(BaseModel):
    name: str
    description: str | None
    arguments: list[Argument]
    return_values: list[Argument]


class CallableList(BaseModel):
    procedures: list[CallableProcedure]
    total: int = Field(description="Number of callable procedures matching the query.")


class CallResult(BaseModel):
    name: str
    results: dict[str, Any] = Field(
        description="Return values by name: numbers, booleans, strings, enum nicks, '#rrggbbaa' colors, "
        "image/item ids and lists of those."
    )


def register(kit: Toolkit) -> None:
    @kit.tool(
        name="gimp_list_callable_procedures",
        title="List callable GIMP procedures",
        description=(
            "PDB procedures that gimp_call_procedure accepts, with their signatures. Only image, item, layer, "
            "drawable, selection, channel, path and text procedures and plug-in filters whose arguments can be "
            "passed as JSON are listed; code evaluation, files, UI, context changes and quitting never are."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_list_callable_procedures(
        query: Annotated[str, Field(description="Substring of the procedure name.")] = "",
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
    ) -> CallableList:
        return CallableList(**await kit.call("pdb.callable", {"query": query, "limit": limit}))

    @kit.tool(
        name="gimp_call_procedure",
        title="Call a GIMP procedure",
        description=(
            "Run one allowed PDB procedure with arguments given by name (see gimp_list_callable_procedures): "
            "numbers/booleans/strings, enum nicks, '#rrggbb' colors, image/item ids, lists of item ids. "
            "Omitted arguments keep GIMP's defaults (images and items are required); the run mode is always "
            "non-interactive. Side effects are those of the procedure; one undo step when an image is involved. "
            "Refused: PROCEDURE_NOT_ALLOWED, INVALID_ARGUMENT, INVALID_ID, NOT_FOUND."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_call_procedure(
        name: str,
        arguments: Annotated[dict[str, Any], Field(description="Arguments by name.")] | None = None,
    ) -> CallResult:
        codec = await kit.codec()
        data = await kit.call("pdb.call", {"name": name, "arguments": arguments or {}}, codec=codec, mutating=True)
        return CallResult(name=name, results=data["results"])

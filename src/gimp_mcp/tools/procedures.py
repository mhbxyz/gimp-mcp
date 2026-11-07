"""Read-only discovery of GIMP's procedure database (nothing is executed)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from ..toolkit import READ_ONLY, Toolkit


class ProcedureSummary(BaseModel):
    name: str
    description: str | None


class SearchResult(BaseModel):
    procedures: list[ProcedureSummary]
    total: int = Field(description="Number of matching procedures (may exceed the returned list).")


class Argument(BaseModel):
    name: str
    type: str = Field(description="GType name, e.g. gint, gdouble, GimpImage, GimpDrawable, GFile.")
    description: str | None
    default: Any = None
    minimum: Any = None
    maximum: Any = None
    choices: list[str] | None = None


class ProcedureDetails(BaseModel):
    name: str
    type: str = Field(description="internal (GIMP core), plugin, persistent or temporary.")
    description: str | None
    help: str | None
    authors: str | None
    date: str | None
    menu_label: str | None
    menu_paths: list[str]
    image_types: str | None
    arguments: list[Argument]
    return_values: list[Argument]


def register(kit: Toolkit) -> None:
    @kit.tool(
        name="gimp_search_procedures",
        title="Search GIMP procedures",
        description=(
            "Search GIMP's procedure database (PDB) by name substring. Read-only: lists what exists in this "
            "GIMP installation; it does not mean an MCP tool exposes it."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_search_procedures(
        query: Annotated[str, Field(description="Substring of the procedure name, e.g. 'brightness'.")] = "",
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
    ) -> SearchResult:
        return SearchResult(**await kit.call("pdb.search", {"query": query, "limit": limit}))

    @kit.tool(
        name="gimp_describe_procedure",
        title="Describe a GIMP procedure",
        description=(
            "Metadata of one PDB procedure: type, documentation, menu, arguments (types, ranges, defaults, "
            "choices) and return values. Read-only: the procedure is not run."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_describe_procedure(name: str) -> ProcedureDetails:
        return ProcedureDetails(**await kit.call("pdb.describe", {"name": name}))

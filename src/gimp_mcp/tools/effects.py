"""The full GEGL filter catalog (#47): list operations, apply any of them, manage editable filters.

Parameters are introspected from GIMP and validated by the bridge before anything changes.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, Field

from ..models import ChangedObject
from ..toolkit import DESTRUCTIVE, MUTATING, READ_ONLY, Toolkit
from .filters import FilterInfo
from .inspect import ItemId

FilterId = Annotated[str, Field(description="Filter id from gimp_list_filters or gimp_apply_filter.")]
Operation = Annotated[str, Field(description="Operation name, e.g. 'gegl:unsharp-mask' (gimp_list_filter_operations).")]
Value = bool | int | float | str
Parameters = Annotated[
    dict[str, Value],
    Field(description="Operation parameters by name (gimp_describe_filter_operation); colors as '#rrggbb[aa]'."),
]
Opacity = Annotated[float, Field(ge=0, le=100, description="0-100.")]
Mode = Annotated[str, Field(description="Blend mode nick, e.g. 'normal', 'multiply', 'screen'.")]


class OperationSummary(BaseModel):
    name: str
    title: str
    categories: list[str]
    supported: bool = Field(description="False when it cannot be applied here (see reason).")
    reason: str | None = None


class OperationList(BaseModel):
    operations: list[OperationSummary]


class ParameterSpec(BaseModel):
    name: str
    kind: str = Field(description="number, integer, boolean, choice, enum, color, string or unsupported.")
    description: str | None = None
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None
    default: Value | None = None
    type: str | None = Field(default=None, description="GIMP type of an unsupported parameter.")


class OperationDetails(OperationSummary):
    description: str
    parameters: list[ParameterSpec]


class FilterState(BaseModel):
    id: str | None = Field(description="Editable filter id; null when the filter was merged into the pixels.")
    name: str
    operation: str
    visible: bool
    opacity: float = Field(description="0-100.")
    mode: str
    parameters: dict[str, Value | None]


class AppliedFilter(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    filter: FilterState
    destructive: bool = Field(description="True when the layer's pixels were changed.")
    restricted_to_selection: bool = Field(description="True when a selection limited the effect.")


class ReorderedFilters(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    filters: list[FilterInfo] = Field(description="Top of the filter stack first.")
    recreated: dict[str, str] = Field(description="Old filter id -> new id, for the filters GIMP had to re-create.")


class MergedFilters(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("item",)
    item: str
    merged: int = Field(description="Number of filters baked into the pixels.")
    filters: list[FilterInfo] = Field(description="Filters left on the layer (new ids), top first.")


def register(kit: Toolkit) -> None:
    def state(codec, data: dict[str, Any]) -> FilterState:
        return FilterState(**{**data, "id": None if data["id"] is None else codec.filter(data["id"])})

    def infos(codec, filters: list[dict[str, Any]]) -> list[FilterInfo]:
        return [FilterInfo(**{**f, "id": codec.filter(f["id"])}) for f in filters]

    @kit.tool(
        toolset="effects",
        name="gimp_list_filter_operations",
        title="List filter operations",
        description=(
            "List the ~200 GEGL operations GIMP offers as filters (blur, sharpen, noise, distort, light, artistic, "
            "edge-detect, color...), optionally filtered by text or category. supported=false ones are listed "
            "with the reason (scripts, auxiliary inputs, internal operations)."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_list_filter_operations(
        query: Annotated[str, Field(description="Substring of the name or title.")] = "",
        category: Annotated[str | None, Field(description="e.g. 'blur', 'distort', 'light', 'noise'.")] = None,
    ) -> OperationList:
        data = await kit.call("filter.operations", {"query": query, "category": category})
        return OperationList(**data)

    @kit.tool(
        toolset="effects",
        name="gimp_describe_filter_operation",
        title="Describe a filter operation",
        description="Parameters of a filter operation as GIMP declares them: kind, range, choices and default.",
        annotations=READ_ONLY,
    )
    async def gimp_describe_filter_operation(operation: Operation) -> OperationDetails:
        return OperationDetails(**await kit.call("filter.describe", {"operation": operation}))

    @kit.tool(
        toolset="effects",
        name="gimp_apply_filter",
        title="Apply a filter",
        description=(
            "Apply any supported operation to a layer: as an editable filter (default: pixels untouched, "
            "parameters editable later, saved in XCF) or destructively (destructive=true: plain layers only). "
            "Parameters not given keep GIMP's defaults; invalid ones are refused before anything changes. "
            "Respects the selection. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_apply_filter(
        item: ItemId,
        operation: Operation,
        parameters: Parameters = {},  # noqa: B006
        destructive: bool = False,
        name: Annotated[str | None, Field(description="Filter name shown in GIMP (default: its title).")] = None,
        opacity: Opacity | None = None,
        mode: Mode | None = None,
        visible: bool | None = None,
    ) -> AppliedFilter:
        codec = await kit.codec()
        data = await kit.call(
            "filter.apply_any",
            {"item": codec.parse_item(item), "operation": operation, "parameters": parameters,
             "destructive": destructive, "name": name, "opacity": opacity, "mode": mode, "visible": visible},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return AppliedFilter(
            item=item,
            filter=state(codec, data["filter"]),
            destructive=data["destructive"],
            restricted_to_selection=data["restricted_to_selection"],
        )

    @kit.tool(
        toolset="effects",
        name="gimp_inspect_filter",
        title="Inspect a filter",
        description="Operation, parameters, visibility, opacity and blend mode of an editable filter on a layer.",
        annotations=READ_ONLY,
    )
    async def gimp_inspect_filter(item: ItemId, filter: FilterId) -> FilterState:
        codec = await kit.codec()
        data = await kit.call(
            "filter.inspect", {"item": codec.parse_item(item), "filter": codec.parse_filter(filter)}, codec=codec
        )
        return state(codec, data)

    @kit.tool(
        toolset="effects",
        name="gimp_set_filter",
        title="Change a filter",
        description=(
            "Change an editable filter: some parameters, visibility, opacity and/or blend mode. Only the given "
            "values change. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_set_filter(
        item: ItemId,
        filter: FilterId,
        parameters: Parameters = {},  # noqa: B006
        visible: bool | None = None,
        opacity: Opacity | None = None,
        mode: Mode | None = None,
    ) -> FilterState:
        codec = await kit.codec()
        data = await kit.call(
            "filter.set",
            {"item": codec.parse_item(item), "filter": codec.parse_filter(filter), "parameters": parameters,
             "visible": visible, "opacity": opacity, "mode": mode},
            codec=codec,
            mutating=True,
        )  # fmt: skip
        return state(codec, data)

    @kit.tool(
        toolset="effects",
        name="gimp_move_filter",
        title="Reorder a filter",
        description=(
            "Move an editable filter to a position in the layer's filter stack (0 = top, applied last). GIMP 3.2 "
            "has no reorder function: the filters from the top down to the lowest moved slot are re-created "
            "with the same settings and get new ids (see 'recreated'). One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_move_filter(
        item: ItemId, filter: FilterId, position: Annotated[int, Field(ge=0)]
    ) -> ReorderedFilters:
        codec = await kit.codec()
        data = await kit.call(
            "filter.reorder",
            {"item": codec.parse_item(item), "filter": codec.parse_filter(filter), "position": position},
            codec=codec,
            mutating=True,
        )
        return ReorderedFilters(
            item=item,
            filters=infos(codec, data["filters"]),
            recreated={codec.filter(int(old)): codec.filter(new) for old, new in data["recreated"].items()},
        )

    @kit.tool(
        toolset="effects",
        name="gimp_merge_filters",
        title="Merge filters into the layer",
        description=(
            "Bake editable filters into the layer's pixels (destructive, plain layers only): the whole stack, or "
            "from the bottom up to and including up_to. Filters above up_to stay editable (re-created with new "
            "ids). One undo step."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_merge_filters(item: ItemId, up_to: FilterId | None = None) -> MergedFilters:
        codec = await kit.codec()
        data = await kit.call(
            "filter.merge",
            {"item": codec.parse_item(item), "up_to": None if up_to is None else codec.parse_filter(up_to)},
            codec=codec,
            mutating=True,
        )
        return MergedFilters(item=item, merged=data["merged"], filters=infos(codec, data["filters"]))

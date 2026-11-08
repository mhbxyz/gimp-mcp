"""GEGL filter catalog policy and parameter validation (#47): pure functions, no GIMP."""

from __future__ import annotations

import gmb_filters  # type: ignore[import-not-found]
import pytest

PIXELIZE = [
    {"name": "norm", "kind": "choice", "choices": ["diamond", "round", "square"], "default": "square"},
    {"name": "size-x", "kind": "integer", "min": 1, "max": 2147483647, "default": 16},
    {"name": "ratio-x", "kind": "number", "min": 0.0, "max": 1.0, "default": 1.0},
    {"name": "background", "kind": "color", "default": "#ffffff"},
    {"name": "clip", "kind": "boolean", "default": True},
    {"name": "mode", "kind": "enum", "choices": ["normal", "multiply"], "default": "normal"},
]


@pytest.mark.parametrize(
    ("name", "categories", "kinds", "supported", "reason"),
    [
        ("gegl:pixelize", ["blur", "scramble"], ["choice", "integer"], True, None),
        ("gegl:gluas", ["script"], ["string"], False, "denied"),
        ("gegl:ctx-script", ["render", "vector"], ["string"], False, "denied"),
        ("gegl:styles", ["Generic"], ["string"], False, "denied"),
        ("gegl:displace", ["map"], ["number"], False, "auxiliary input"),
        ("gimp:multiply-legacy", [], [], False, "internal"),
        ("gimp:flood", ["gimp"], [], False, "internal"),
        ("gimp:curves", ["color"], ["unsupported"], False, "parameter"),
        ("gimp:levels", ["color"], ["number", "enum"], True, None),
    ],
)
def test_operation_status(name, categories, kinds, supported, reason):
    ok, why = gmb_filters.operation_status(name, categories, kinds)
    assert ok is supported
    if reason is None:
        assert why is None
    else:
        assert reason in why


def test_values_are_validated_and_normalized():
    values = gmb_filters.validate(
        PIXELIZE,
        {"norm": "round", "size-x": 8, "ratio-x": 0.5, "background": "#ff000080", "clip": False, "mode": "multiply"},
    )
    assert values == {
        "norm": "round",
        "size-x": 8,
        "ratio-x": 0.5,
        "background": (1.0, 0.0, 0.0, 128 / 255),
        "clip": False,
        "mode": "multiply",
    }
    assert gmb_filters.validate(PIXELIZE, {"ratio-x": 1}) == {"ratio-x": 1.0}  # integers are numbers
    assert gmb_filters.validate(PIXELIZE, {"background": "#0f0"}) == {"background": (0.0, 1.0, 0.0, 1.0)}


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"size": 3}, "unknown parameter 'size'"),
        ({"size-x": 0}, "between 1 and 2147483647"),
        ({"size-x": 2.5}, "integer"),
        ({"size-x": True}, "integer"),
        ({"ratio-x": "big"}, "number"),
        ({"ratio-x": 1.5}, "between 0.0 and 1.0"),
        ({"norm": "hexagon"}, "one of diamond, round, square"),
        ({"background": "red"}, "#rrggbb"),
        ({"clip": "yes"}, "true or false"),
        ({"mode": "screen"}, "one of normal, multiply"),
    ],
)
def test_invalid_values_are_refused_with_a_useful_message(values, message):
    with pytest.raises(gmb_filters.InvalidParameter) as error:
        gmb_filters.validate(PIXELIZE, values)
    assert message in str(error.value)


def test_unsupported_parameters_cannot_be_set():
    spec = [{"name": "curve", "kind": "unsupported", "type": "GimpCurve"}]
    with pytest.raises(gmb_filters.InvalidParameter, match="GimpCurve"):
        gmb_filters.validate(spec, {"curve": [0, 1]})


def test_stack_reordering_plan():
    """GIMP 3.2 can only append a filter on top: filters down to the lowest moved slot are re-created.

    Stacks are listed top first, like gimp_list_filters. The plan is (filters to re-create in
    append order, i.e. bottom-up; final stack).
    """
    # move a (bottom) to the top: every slot changes
    assert gmb_filters.reorder_plan(["c", "b", "a"], "a", 0) == (["b", "c", "a"], ["a", "c", "b"])
    # move c (top) under b: only the two top slots change, a stays
    assert gmb_filters.reorder_plan(["c", "b", "a"], "c", 1) == (["c", "b"], ["b", "c", "a"])
    # no change
    assert gmb_filters.reorder_plan(["c", "b", "a"], "b", 1) == ([], ["c", "b", "a"])
    with pytest.raises(ValueError):
        gmb_filters.reorder_plan(["c", "b", "a"], "b", 3)

"""Allowlist policy for the generic PDB access (issue #16)."""

from __future__ import annotations

import json
from pathlib import Path

import gmb_policy  # type: ignore[import-not-found]
import pytest

INVENTORY = Path(__file__).resolve().parents[2] / "docs" / "coverage" / "pdb-inventory.json"
PROCS = {p["name"]: p for p in json.loads(INVENTORY.read_text())["procedures"]}
SESSION = "a1b2c3d4"


def allowed(name: str) -> tuple[bool, str | None]:
    return gmb_policy.evaluate(PROCS[name])


@pytest.mark.parametrize(
    "name",
    [
        "gimp-image-get-resolution",
        "gimp-drawable-invert",
        "gimp-layer-set-opacity",
        "plug-in-despeckle",
        "gimp-drawable-get-pixel",
        "gimp-drawable-levels",
    ],
)
def test_compatible_procedures_are_allowed(name):
    assert allowed(name) == (True, None)


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("python-fu-eval", "denied"),
        ("gimp-quit", "denied"),
        ("gimp-image-delete", "denied"),
        ("gimp-file-save", "outside"),
        ("file-png-export", "outside"),
        ("gimp-context-set-foreground", "denied"),
        ("extension-gimp-mcp-bridge", "denied"),
        ("gimp-image-get-file", "unsupported type GFile"),
        ("gimp-image-attach-parasite", "parasite"),
        ("plug-in-screenshot", "denied"),
        ("plug-in-mail-image", "denied"),
        ("plug-in-web-browser", "denied"),
        ("plug-in-dbbrowser", "denied"),
    ],
)
def test_dangerous_or_incompatible_procedures_are_refused(name, reason):
    ok, why = allowed(name)
    assert ok is False
    assert why is not None and reason in why


def test_arguments_are_converted_from_json_with_ids_bound_to_the_session():
    meta = PROCS["gimp-drawable-invert"]
    plan = gmb_policy.plan_call(meta, {"drawable": f"item:7@{SESSION}", "linear": True}, SESSION)
    assert plan == [("drawable", "item", 7), ("linear", "scalar", True)]


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"drawable": "item:7@deadbeef", "linear": True}, "SESSION_CHANGED"),
        ({"drawable": "image:7@a1b2c3d4", "linear": True}, "INVALID_ID"),
        ({"drawable": f"item:7@{SESSION}", "linear": "yes"}, "INVALID_ARGUMENT"),
        ({"drawable": f"item:7@{SESSION}", "nope": 1}, "INVALID_ARGUMENT"),
        ({"linear": True}, "INVALID_ARGUMENT"),  # required object argument missing
    ],
)
def test_bad_arguments_are_refused_before_running(arguments, code):
    with pytest.raises(gmb_policy.PolicyError) as excinfo:
        gmb_policy.plan_call(PROCS["gimp-drawable-invert"], arguments, SESSION)
    assert excinfo.value.code == code


def test_ranges_choices_and_enums_are_checked():
    opacity = PROCS["gimp-layer-set-opacity"]
    with pytest.raises(gmb_policy.PolicyError):
        gmb_policy.plan_call(opacity, {"layer": f"item:1@{SESSION}", "opacity": 250.0}, SESSION)
    despeckle = PROCS["plug-in-despeckle"]
    plan = gmb_policy.plan_call(
        despeckle,
        {"image": f"image:1@{SESSION}", "drawables": [f"item:2@{SESSION}"], "radius": 3},
        SESSION,
    )
    assert ("drawables", "items", [2]) in plan
    assert ("run-mode", "run-mode", "noninteractive") in plan
    fill = PROCS["gimp-drawable-edit-fill"]
    with pytest.raises(gmb_policy.PolicyError):
        gmb_policy.plan_call(fill, {"drawable": f"item:1@{SESSION}", "fill-type": "lava"}, SESSION)
    assert ("fill-type", "enum", "foreground") in gmb_policy.plan_call(
        fill, {"drawable": f"item:1@{SESSION}", "fill-type": "foreground"}, SESSION
    )


def test_a_meaningful_share_of_the_pdb_is_callable():
    callable_ = [name for name, meta in PROCS.items() if gmb_policy.evaluate(meta)[0]]
    assert len(callable_) > 300
    assert not any("eval" in name or "script-fu" in name for name in callable_)


def _third_party(name: str) -> dict:
    # G'MIC-Qt's procedure in GIMP 3: its `command` string can run shell commands (`exec`).
    return {"name": name, "type": "plugin", "arguments": [
        {"name": "run-mode", "type": "GimpRunMode"}, {"name": "image", "type": "GimpImage"},
        {"name": "command", "type": "gchararray"}], "return_values": []}  # fmt: skip


@pytest.mark.parametrize("name", ["plug-in-gmic-qt", "plug-in-my-filter", "plug-in-despeckle-pro"])
def test_only_the_plug_ins_shipped_with_gimp_are_callable(name):
    # Any installed plug-in named plug-in-* used to pass: a third-party one can do anything its author let it (#122).
    ok, reason = gmb_policy.evaluate(_third_party(name))
    assert not ok and reason is not None and ("not shipped with GIMP" in reason or "denied" in reason)


def test_the_list_of_gimp_plug_ins_is_the_inventory_of_gimp():
    assert {name for name in PROCS if name.startswith("plug-in-")} == gmb_policy.GIMP_PLUG_INS

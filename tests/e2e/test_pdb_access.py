from __future__ import annotations

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error, preview, rgba


async def test_discover_read_mutate_and_refuse(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        listed = await call(client, "gimp_list_callable_procedures", query="invert")
        names = [p["name"] for p in listed["procedures"]]
        assert "gimp-drawable-invert" in names
        signature = next(p for p in listed["procedures"] if p["name"] == "gimp-drawable-invert")
        assert [a["name"] for a in signature["arguments"]] == ["drawable", "linear"]
        evals = await call(client, "gimp_list_callable_procedures", query="eval")
        assert evals["procedures"] == []

        image = (await call(client, "gimp_create_image", width=10, height=10, fill="#ff0000", resolution=150))["id"]
        layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]

        resolution = await call(
            client, "gimp_call_procedure", name="gimp-image-get-resolution", arguments={"image": image}
        )
        assert resolution["results"] == {"xresolution": 150.0, "yresolution": 150.0}
        pixel = await call(
            client,
            "gimp_call_procedure",
            name="gimp-drawable-get-pixel",
            arguments={"drawable": layer, "x-coord": 2, "y-coord": 3},
        )
        assert pixel["results"]["color"].lower().startswith("#ff0000")

        inverted = await call(
            client, "gimp_call_procedure", name="gimp-drawable-invert", arguments={"drawable": layer, "linear": False}
        )
        assert inverted["results"] == {}
        assert rgba(await preview(client, image), 5, 5)[:3] == (0, 255, 255)

        session = image.split("@")[1]
        not_allowed = await error(client, "gimp_call_procedure", name="python-fu-eval", arguments={})
        file_access = await error(client, "gimp_call_procedure", name="gimp-file-save", arguments={})
        unknown = await error(client, "gimp_call_procedure", name="gimp-does-not-exist", arguments={})
        stale = await error(
            client,
            "gimp_call_procedure",
            name="gimp-drawable-invert",
            arguments={"drawable": f"item:99999@{session}", "linear": False},
        )
        bad_type = await error(
            client, "gimp_call_procedure", name="gimp-drawable-invert", arguments={"drawable": layer, "linear": "no"}
        )
        interactive = await error(
            client,
            "gimp_call_procedure",
            name="plug-in-despeckle",
            arguments={"run-mode": "interactive", "image": image, "drawables": [layer]},
        )
        wrong_object = await error(
            client, "gimp_call_procedure", name="gimp-layer-set-opacity", arguments={"layer": image, "opacity": 50.0}
        )
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert not_allowed["code"] == "PROCEDURE_NOT_ALLOWED" and "denied" in not_allowed["details"]["reason"]
    assert file_access["code"] == "PROCEDURE_NOT_ALLOWED"
    assert unknown["code"] == "NOT_FOUND"
    assert stale["code"] == "NOT_FOUND"
    assert bad_type["code"] == "INVALID_ARGUMENT"
    assert interactive["code"] == "INVALID_ARGUMENT"
    assert wrong_object["code"] == "INVALID_ID"
    for refusal in (not_allowed, file_access, stale, bad_type, interactive, wrong_object):
        assert refusal["outcome"] == "not_applied"


async def test_plug_in_filter_with_drawable_array(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=20, height=20, fill="white"))["id"]
        layer = (await call(client, "gimp_inspect_image", image=image))["layers"][0]["id"]
        result = await call(
            client,
            "gimp_call_procedure",
            name="plug-in-despeckle",
            arguments={"image": image, "drawables": [layer], "radius": 2},
        )
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert result["name"] == "plug-in-despeckle"

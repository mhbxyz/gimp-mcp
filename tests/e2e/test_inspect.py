from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .gimp_batch import run_batch


@pytest.fixture(scope="module")
def two_projects(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """poster.xcf: nested groups, a mask, a name GIMP must de-duplicate. flyer.xcf: same names."""
    directory = tmp_path_factory.mktemp("projects")
    poster, flyer = directory / "poster.xcf", directory / "flyer.xcf"
    run_batch(f"""
img = Gimp.Image.new(120, 80, Gimp.ImageBaseType.RGB)
layer(img, "Background", 120, 80, alpha=False)
outer = group(img, "Outer")
inner = group(img, "Inner", parent=outer)
deep = layer(img, "Title", 30, 10, parent=inner, opacity=50.0, mode=Gimp.LayerMode.MULTIPLY)
deep.set_offsets(5, 7)
deep.add_mask(deep.create_mask(Gimp.AddMaskType.WHITE))
layer(img, "Title", 10, 10, parent=outer, position=1)
hidden = layer(img, "Hidden", 4, 4)
hidden.set_visible(False)
save_xcf(img, {str(poster)!r})
img2 = Gimp.Image.new(64, 64, Gimp.ImageBaseType.RGB)
layer(img2, "Background", 64, 64, alpha=False)
layer(img2, "Title", 8, 8)
save_xcf(img2, {str(flyer)!r})
""")
    return poster, flyer


def flatten(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(flatten(node.get("children") or []))
    return result


async def test_inspect_nested_groups_masks_and_duplicate_names_across_images(
    gimp_factory: Callable[..., HeadlessGimp], two_projects: tuple[Path, Path]
):
    poster, flyer = two_projects
    gimp = gimp_factory(open_files=[poster, flyer])
    async with mcp_client(gimp) as client:
        status = (await client.call_tool("gimp_status", {})).structured_content
        assert status is not None
        by_file = {Path(image["file"]).name: image["id"] for image in status["images"]}
        result = await client.call_tool("gimp_inspect_image", {"image": by_file["poster.xcf"]})
        other = await client.call_tool("gimp_inspect_image", {"image": by_file["flyer.xcf"]})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data is not None and other.structured_content is not None
    assert (data["width"], data["height"], data["base_type"]) == (120, 80, "rgb")
    assert data["dirty"] is False
    tree = [(node["name"], node["kind"]) for node in data["layers"]]
    assert tree == [("Hidden", "layer"), ("Outer", "group"), ("Background", "layer")]
    outer = data["layers"][1]
    assert [(n["name"], n["kind"]) for n in outer["children"]] == [("Inner", "group"), ("Title #1", "layer")]
    title = outer["children"][0]["children"][0]
    assert title["name"] == "Title"
    assert (title["x"], title["y"], title["width"], title["height"]) == (5, 7, 30, 10)
    assert title["opacity"] == pytest.approx(50.0)
    assert title["mode"] == "multiply"
    assert title["mask"] is not None and title["mask"]["id"].startswith("item:")
    assert title["parent"] == outer["children"][0]["id"]
    assert data["layers"][0]["visible"] is False

    poster_ids = {node["id"] for node in flatten(data["layers"])}
    flyer_nodes = flatten(other.structured_content["layers"])
    assert len(poster_ids) == len(flatten(data["layers"]))  # unique within the image
    assert poster_ids.isdisjoint({node["id"] for node in flyer_nodes})  # and across images
    assert [n["name"] for n in flyer_nodes] == ["Title", "Background"]


async def test_inspect_item_by_id_and_stale_ids(
    gimp_factory: Callable[..., HeadlessGimp], two_projects: tuple[Path, Path]
):
    poster, _ = two_projects
    gimp = gimp_factory(open_files=[poster])
    async with mcp_client(gimp) as client:
        status = (await client.call_tool("gimp_status", {})).structured_content
        assert status is not None
        image_id = status["images"][0]["id"]
        tree = (await client.call_tool("gimp_inspect_image", {"image": image_id})).structured_content
        assert tree is not None
        inner = tree["layers"][1]["children"][0]
        item = await client.call_tool("gimp_inspect_item", {"item": inner["id"]})
        assert not item.is_error, item.content
        assert item.structured_content is not None
        assert item.structured_content["kind"] == "group"
        assert item.structured_content["image"] == image_id
        assert item.structured_content["parent"] == tree["layers"][1]["id"]
        assert item.structured_content["position"] == 0
        mask_id = inner["children"][0]["mask"]["id"]
        mask = (await client.call_tool("gimp_inspect_item", {"item": mask_id})).structured_content
        assert mask is not None and mask["kind"] == "mask"

        session = status["session_id"]
        missing = await client.call_tool("gimp_inspect_item", {"item": f"item:99999@{session}"})
        assert missing.is_error and missing.structured_content is not None
        assert missing.structured_content["error"]["code"] == "NOT_FOUND"

        gimp.restart()
        stale = await client.call_tool("gimp_inspect_image", {"image": image_id})
    assert stale.is_error and stale.structured_content is not None
    assert stale.structured_content["error"]["code"] == "SESSION_CHANGED"

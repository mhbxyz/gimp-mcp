"""Deprecated parameters on a real GIMP (#117, #119): the old form works and says what replaces it."""

from __future__ import annotations

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call

NOTICES = "io.github.mhbxyz/deprecations"


async def test_renamed_parameters_keep_working_with_a_notice(gimp: HeadlessGimp):
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_create_image", width=20, height=10))["id"]
        channel = await call(client, "gimp_create_channel", image=image, name="Saved")
        old = await client.call_tool("gimp_set_channel", {"channel_id": channel["id"], "name": "Renamed"})
        point = await call(client, "gimp_add_sample_point", image=image, x=3, y=4)
        removed = await client.call_tool(
            "gimp_remove_guide", {"image": image, "id": point["sample_point"], "kind": "sample_point"}
        )
        renamed = await call(client, "gimp_inspect_item", item=channel["id"])
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert not old.is_error and renamed["name"] == "Renamed"
    assert old.meta is not None and removed.meta is not None
    [notice] = old.meta[NOTICES]
    assert notice == {"name": "gimp_set_channel.channel_id", "since": "0.7.0", "removal": "1.0.0",
                      "replacement": "use channel"}  # fmt: skip
    assert any("Deprecation notice: gimp_set_channel.channel_id" in getattr(b, "text", "") for b in old.content)
    assert not removed.is_error and removed.structured_content["sample_points"] == []
    assert {n["name"] for n in removed.meta[NOTICES]} == {
        "gimp_remove_guide.id",
        "gimp_remove_guide.kind='sample_point'",
    }

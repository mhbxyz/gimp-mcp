from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client


async def test_real_client_sees_gimp_version_and_an_open_image(
    gimp_factory: Callable[..., HeadlessGimp], tmp_path: Path
):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (40, 30), (200, 10, 10)).save(photo)
    gimp = gimp_factory(open_files=[photo])

    async with mcp_client(gimp) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert "gimp_status" in names
        result = await client.call_tool("gimp_status", {})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data is not None
    assert data["gimp_version"].startswith("3.")
    assert [(image["file"], image["width"], image["height"]) for image in data["images"]] == [
        (str(photo), 40, 30)
    ]
    assert "photo" in data["images"][0]["name"]  # display name, localized by GIMP
    assert data["images"][0]["id"].startswith("image:")

from __future__ import annotations

from collections.abc import Callable

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client


async def test_server_survives_a_gimp_restart_and_sees_the_new_session(
    gimp_factory: Callable[..., HeadlessGimp],
):
    gimp = gimp_factory()
    async with mcp_client(gimp) as client:
        first = await client.call_tool("gimp_status", {})
        assert not first.is_error
        gimp.restart()
        second = await client.call_tool("gimp_status", {})
    assert not second.is_error, second.content
    assert first.structured_content is not None and second.structured_content is not None
    assert first.structured_content["session_id"] != second.structured_content["session_id"]

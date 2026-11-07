from __future__ import annotations

from gmb_server import BridgeError  # type: ignore[import-not-found]

from .tool_harness import error_code, tool_client


async def test_call_passes_arguments_through_and_returns_results():
    def call(params):
        return {"results": {"xresolution": 72.0}}

    async with tool_client({"pdb.call": call}) as (client, bridge):
        result = await client.call_tool(
            "gimp_call_procedure", {"name": "gimp-image-get-resolution", "arguments": {"image": "image:1@a1b2c3d4"}}
        )
    assert result.structured_content == {"name": "gimp-image-get-resolution", "results": {"xresolution": 72.0}}
    assert bridge.calls[0][1] == {"name": "gimp-image-get-resolution", "arguments": {"image": "image:1@a1b2c3d4"}}


async def test_policy_refusals_are_structured_and_not_applied():
    def refuse(params):
        raise BridgeError("PROCEDURE_NOT_ALLOWED", "python-fu-eval: denied", {"reason": "denied by policy ('eval')"})

    async with tool_client({"pdb.call": refuse}) as (client, _):
        result = await client.call_tool("gimp_call_procedure", {"name": "python-fu-eval"})
    assert error_code(result) == "PROCEDURE_NOT_ALLOWED"
    assert result.structured_content is not None
    assert result.structured_content["error"]["outcome"] == "not_applied"

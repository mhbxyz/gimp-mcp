"""Session-level tools: diagnostics."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .. import __version__
from ..toolkit import READ_ONLY, Toolkit


class ImageSummary(BaseModel):
    id: str = Field(description="Opaque image id, valid for this GIMP session only.")
    name: str = Field(description="GIMP's display name (may be localized, e.g. '[photo] (imported)').")
    file: str | None = Field(description="File the image was opened from or saved to, if any.")
    width: int
    height: int
    dirty: bool = Field(description="True when the image has unsaved changes.")


class StatusOutput(BaseModel):
    connected: bool
    gimp_version: str
    session_id: str = Field(description="Changes whenever GIMP restarts; ids from older sessions are rejected.")
    bridge_protocol: int
    server_version: str = Field(description="Version of this MCP server.")
    plugin_version: str = Field(description="Version of the GIMP plug-in.")
    plugin_compatibility: Literal["match", "compatible", "partial"] = Field(
        description="match: same version as the server. compatible: another version that serves every operation "
        "this server uses. partial: an older plug-in; tools it cannot serve fail with PLUGIN_VERSION_MISMATCH "
        "(fix: `gimp-mcp install-plugin`, then restart GIMP)."
    )
    socket: str
    images: list[ImageSummary]


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="core",
        name="gimp_status",
        title="GIMP status",
        description=(
            "Diagnose the connection to the running GIMP session: GIMP version, session id and the "
            "list of open images (with their ids). Call this first."
        ),
        annotations=READ_ONLY,
    )
    async def gimp_status() -> StatusOutput:
        codec = await kit.codec()
        result = await kit.call("session.images", codec=codec)
        session = kit.bridge.session
        assert session is not None
        return StatusOutput(
            connected=True,
            gimp_version=session.gimp_version,
            session_id=session.session_id,
            bridge_protocol=session.protocol,
            server_version=__version__,
            plugin_version=session.bridge_version or "unknown",
            plugin_compatibility=kit.bridge.plugin_check.verdict.value if kit.bridge.plugin_check else "partial",
            socket=str(kit.bridge.endpoint.socket_path),
            images=[ImageSummary(**{**image, "id": codec.image(image["id"])}) for image in result["images"]],
        )

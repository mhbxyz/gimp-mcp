"""MCP resources (#62): open images, their layer trees and previews, readable without tool calls.

* ``gimp://images``: the open images (JSON, like ``gimp_status``).
* ``gimp://images/{image}/layers``: an image's details and layer tree (JSON, like ``gimp_inspect_image``).
* ``gimp://images/{image}/preview``: a PNG preview (longest side ``RESOURCE_PREVIEW_SIZE``).

The concrete per-image resources are listed while the image is open; tools that open or close
images tell the client that the list changed (``Toolkit.tool(changes_images=True)``).
"""

from __future__ import annotations

import base64
import json
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError
from mcp_types import Resource as MCPResource

from .errors import GimpMcpError
from .models import encode_image
from .toolkit import Toolkit
from .tools.preview import max_bytes

IMAGES_URI = "gimp://images"
LAYERS_TEMPLATE = "gimp://images/{image}/layers"
PREVIEW_TEMPLATE = "gimp://images/{image}/preview"
RESOURCE_PREVIEW_SIZE = 512


def _failed(error: GimpMcpError) -> ResourceError:
    text = f"{error.code}: {error.message}"
    if error.hint:
        text += f" ({error.hint})"
    return ResourceError(text)


async def open_images(kit: Toolkit) -> list[dict[str, Any]]:
    codec = await kit.codec()
    data = await kit.call("session.images", codec=codec)
    return [{**image, "id": codec.image(image["id"])} for image in data["images"]]


async def image_resources(kit: Toolkit) -> list[MCPResource]:
    """The per-image resources of the open images; none when GIMP cannot be reached."""
    try:
        images = await open_images(kit)
    except GimpMcpError:
        return []
    listed = []
    for image in images:
        listed.append(
            MCPResource(
                uri=LAYERS_TEMPLATE.format(image=image["id"]),
                name=f"layers: {image['name']}",
                title=f"Layer tree of {image['name']}",
                description="Image details and the full layer tree, as gimp_inspect_image returns them.",
                mime_type="application/json",
            )
        )
        listed.append(
            MCPResource(
                uri=PREVIEW_TEMPLATE.format(image=image["id"]),
                name=f"preview: {image['name']}",
                title=f"Preview of {image['name']}",
                description=f"PNG preview of the visible image, longest side {RESOURCE_PREVIEW_SIZE} px.",
                mime_type="image/png",
            )
        )
    return listed


def register(kit: Toolkit) -> None:
    mcp = kit.mcp

    @mcp.resource(
        IMAGES_URI,
        name="images",
        title="Open images",
        description="The images open in GIMP: id, name, file, size, unsaved changes.",
        mime_type="application/json",
    )
    async def images() -> str:
        try:
            return json.dumps({"images": await open_images(kit)})
        except GimpMcpError as error:
            raise _failed(error) from error

    @mcp.resource(
        LAYERS_TEMPLATE,
        name="layers",
        title="Layer tree",
        description="An open image's details and full layer tree (ids as in the tools).",
        mime_type="application/json",
    )
    async def layers(image: str) -> str:
        try:
            codec = await kit.codec()
            number = codec.parse_image(image)
            data = await kit.call("image.inspect", {"image": number}, codec=codec)
        except GimpMcpError as error:
            raise _failed(error) from error
        return encode_image(codec, data).model_dump_json()

    @mcp.resource(
        PREVIEW_TEMPLATE,
        name="preview",
        title="Preview",
        description=f"PNG preview of an open image, longest side {RESOURCE_PREVIEW_SIZE} px.",
        mime_type="image/png",
    )
    async def preview(image: str) -> bytes:
        try:
            codec = await kit.codec()
            number = codec.parse_image(image)
            data = await kit.call(
                "image.preview",
                {"image": number, "max_size": RESOURCE_PREVIEW_SIZE, "max_bytes": max_bytes()},
                codec=codec,
            )
        except GimpMcpError as error:
            raise _failed(error) from error
        return base64.b64decode(data["png_base64"])

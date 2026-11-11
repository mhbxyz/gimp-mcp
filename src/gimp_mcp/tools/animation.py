"""Animations (#59): layers as frames, timing and disposal, previews, optimization, animated exports.

GIMP plays an animation from the bottom layer up; each frame's duration and disposal are written in
its layer name ("Frame 2 (100ms) (replace)"), the way GIMP's GIF and WebP exporters read them.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from mcp_types import ImageContent
from pydantic import BaseModel, Field

from ..colors import parse_color
from ..errors import GimpMcpError
from ..models import ChangedObject
from ..paths import check_output_file
from ..toolkit import MUTATING, READ_ONLY, Toolkit, ToolResult
from .formats import Exported
from .inspect import ImageId, ItemId

Duration = Annotated[int, Field(ge=1, le=600_000, description="Milliseconds.")]
Disposal = Annotated[
    Literal["combine", "replace"],
    Field(description="After this frame: combine (the next frame is drawn over it) or replace (it is removed)."),
]


class Frame(BaseModel):
    item: str
    index: int = Field(description="Playing order, 0 = first frame (the bottom layer).")
    name: str
    duration_ms: int
    disposal: str


class FrameList(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("added", "image")
    image: str
    frames: list[Frame]
    added: str | None = None


class FramePreview(BaseModel):
    image: str
    index: int
    width: int
    height: int
    frames_shown: list[int] = Field(description="Frames visible at that moment (disposal applied).")


class Optimized(ChangedObject):
    id_from: ClassVar[tuple[str, ...]] = ("image",)
    image: str = Field(description="The new, optimized (or unoptimized) image.")
    frames: list[Frame]


def register(kit: Toolkit) -> None:
    def frame_list(codec: Any, data: dict[str, Any], image: str, changed: str | None = None) -> FrameList:
        """``changed``: the frame a call changed, its ``id`` (else the added frame, else the image)."""
        frames = [Frame(**{**f, "item": codec.item(f["item"])}) for f in data["frames"]]
        added = codec.item(data["added"]) if data.get("added") is not None else None
        return FrameList(image=image, frames=frames, added=added, id=changed or "")

    @kit.tool(
        toolset="animation",
        name="gimp_list_frames",
        title="List animation frames",
        description="The image's frames in playing order (bottom layer first) with duration and disposal "
        "(default_delay for frames without one).",
        annotations=READ_ONLY,
    )
    async def gimp_list_frames(image: ImageId, default_delay: Duration = 100) -> FrameList:
        codec = await kit.codec()
        data = await kit.call("anim.frames", {"image": codec.parse_image(image), "default_delay": default_delay},
                              codec=codec)  # fmt: skip
        return frame_list(codec, data, image)

    @kit.tool(
        toolset="animation",
        name="gimp_add_frame",
        title="Add a frame",
        description=(
            "Add a frame at index (playing order; default: last): empty (optionally filled with a color) or a copy "
            "of another frame (duplicate_of), with its duration and disposal. Reorder frames with "
            "gimp_move_layer. One undo step."
        ),
        annotations=MUTATING,
    )
    async def gimp_add_frame(
        image: ImageId,
        index: Annotated[int | None, Field(ge=0)] = None,
        duplicate_of: ItemId | None = None,
        name: str | None = None,
        duration_ms: Duration | None = None,
        disposal: Disposal | None = None,
        fill: str | None = None,
    ) -> FrameList:
        codec = await kit.codec()
        params: dict[str, Any] = {
            "image": codec.parse_image(image), "name": name, "duration_ms": duration_ms, "disposal": disposal,
            "duplicate_of": codec.parse_item(duplicate_of) if duplicate_of else None,
            "fill": parse_color(fill).to_wire() if fill else None,
        }  # fmt: skip
        if index is not None:
            params["index"] = index
        data = await kit.call("anim.add_frame", params, codec=codec, mutating=True)
        return frame_list(codec, data, image)

    @kit.tool(
        toolset="animation",
        name="gimp_set_frame",
        title="Set frame timing",
        description="Change a frame's duration, disposal and/or name (written in its layer name). One undo step.",
        annotations=MUTATING,
    )
    async def gimp_set_frame(
        item: ItemId, duration_ms: Duration | None = None, disposal: Disposal | None = None, name: str | None = None
    ) -> FrameList:
        codec = await kit.codec()
        data = await kit.call(
            "anim.set_frame",
            {"item": codec.parse_item(item), "duration_ms": duration_ms, "disposal": disposal, "name": name},
            codec=codec,
            mutating=True,
        )
        return frame_list(codec, data, codec.image(data["image"]), changed=item)

    @kit.tool(
        toolset="animation",
        name="gimp_preview_frame",
        title="Preview a frame",
        description="Render the animation as it looks while frame index shows (earlier frames kept by 'combine').",
        annotations=READ_ONLY,
    )
    async def gimp_preview_frame(
        image: ImageId, index: Annotated[int, Field(ge=0)], max_size: Annotated[int, Field(ge=16, le=1024)] = 512
    ) -> FramePreview:
        codec = await kit.codec()
        data = await kit.call(
            "anim.preview", {"image": codec.parse_image(image), "index": index, "max_size": max_size}, codec=codec
        )
        info = FramePreview(image=image, index=index, width=data["width"], height=data["height"],
                            frames_shown=data["frames_shown"])  # fmt: skip
        return ToolResult(info, [ImageContent(type="image", data=data["png_base64"], mime_type="image/png")])  # type: ignore[return-value]

    @kit.tool(
        toolset="animation",
        name="gimp_optimize_animation",
        title="Optimize an animation",
        description=(
            "Make a new image from the animation: optimize (GIF-style: each frame keeps only what changes), "
            "optimize-difference, or unoptimize (every frame complete). The original is unchanged."
        ),
        annotations=MUTATING,
        changes_images=True,
    )
    async def gimp_optimize_animation(
        image: ImageId, mode: Literal["optimize", "optimize-difference", "unoptimize"] = "optimize"
    ) -> Optimized:
        codec = await kit.codec()
        data = await kit.call("anim.optimize", {"image": codec.parse_image(image), "mode": mode}, codec=codec,
                              mutating=True)  # fmt: skip
        return Optimized(image=codec.image(data["id"]),
                         frames=[Frame(**{**f, "item": codec.item(f["item"])}) for f in data["frames"]])  # fmt: skip

    @kit.tool(
        toolset="animation",
        name="gimp_export_animation",
        title="Export an animation",
        description=(
            "Export the frames as an animated GIF (.gif) or WebP (.webp): loop forever or play once, a default "
            "duration and disposal for frames without one, or force them on every frame. GIMP 3.2 has no APNG "
            "exporter. The image is unchanged."
        ),
        annotations=MUTATING,
    )
    async def gimp_export_animation(
        image: ImageId,
        path: str,
        loop: bool = True,
        default_delay: Duration = 100,
        default_disposal: Disposal = "combine",
        force: bool = False,
        overwrite: bool = False,
    ) -> Exported:
        target = check_output_file(path, overwrite=overwrite)
        suffix = target.suffix.lower()
        if suffix == ".gif":
            options: dict[str, Any] = {"as-animation": True, "loop": loop, "default-delay": default_delay,
                                       "default-dispose": default_disposal, "force-delay": force,
                                       "force-dispose": force}  # fmt: skip
        elif suffix == ".webp":
            options = {"animation": True, "animation-loop": loop, "default-delay": default_delay,
                       "force-delay": force, "lossless": True}  # fmt: skip
        else:
            raise GimpMcpError("UNSUPPORTED_FORMAT", f"{target.name}: animations export to .gif or .webp")
        codec = await kit.codec()
        data = await kit.call(
            "image.export_as",
            {"image": codec.parse_image(image), "path": str(target), "options": options, "metadata": []},
            codec=codec,
            mutating=True,
        )
        return Exported(**data)

"""History: undo groups (GIMP's own undo stack) and checkpoints (the agent's undo/redo).

GIMP 3.2 gives plug-ins no undo/redo procedure and no access to the undo
history, only undo *groups*. Agents therefore undo and redo with checkpoints:
full copies of an image kept by the bridge and restored on demand.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from ..ids import IdCodec
from ..toolkit import DESTRUCTIVE, MUTATING, READ_ONLY, Toolkit
from .files import ImageRef, image_ref
from .inspect import ImageId

CheckpointId = Annotated[str, Field(description="Checkpoint id from gimp_create_checkpoint.")]


class UndoGroupState(BaseModel):
    image: str
    depth: int = Field(description="Undo groups this client still has open on the image (0 = none).")


class Checkpoint(BaseModel):
    checkpoint: str
    label: str | None
    image: str = Field(description="Image the checkpoint belongs to (follows restorations).")
    width: int
    height: int
    created: float = Field(description="Unix time.")


class CheckpointList(BaseModel):
    image: str
    checkpoints: list[Checkpoint] = Field(description="Oldest first.")


class RestoreResult(ImageRef):
    image: str = Field(description="Id of the restored image (a new id: all item ids changed).")
    previous_image: str = Field(description="Id the image had before; it is no longer valid.")


class DeleteCheckpointResult(BaseModel):
    checkpoint: str
    deleted: bool


def register(kit: Toolkit) -> None:
    @kit.tool(
        toolset="undo",
        name="gimp_begin_undo_group",
        title="Begin undo group",
        description=(
            "Start grouping the following changes to an image into ONE step of GIMP's undo history (what Ctrl+Z "
            "undoes in GIMP's UI). Close it with gimp_end_undo_group. Groups nest. If this client disconnects, "
            "its open groups are closed automatically. Grouping is not a transaction: nothing is rolled back on "
            "error (use checkpoints for that)."
        ),
        annotations=MUTATING,
    )
    async def gimp_begin_undo_group(image: ImageId, label: str | None = None) -> UndoGroupState:
        codec = await kit.codec()
        data = await kit.call(
            "undo.begin", {"image": codec.parse_image(image), "label": label}, codec=codec, mutating=True
        )
        return UndoGroupState(image=image, depth=data["depth"])

    @kit.tool(
        toolset="undo",
        name="gimp_end_undo_group",
        title="End undo group",
        description="Close the innermost undo group this client opened on the image (NO_OPEN_GROUP otherwise).",
        annotations=MUTATING,
    )
    async def gimp_end_undo_group(image: ImageId) -> UndoGroupState:
        codec = await kit.codec()
        data = await kit.call("undo.end", {"image": codec.parse_image(image)}, codec=codec, mutating=True)
        return UndoGroupState(image=image, depth=data["depth"])

    def checkpoint_model(codec: IdCodec, data: dict[str, Any]) -> Checkpoint:
        return Checkpoint(
            checkpoint=codec.checkpoint(data["checkpoint"]),
            label=data["label"],
            image=codec.image(data["image"]),
            width=data["width"],
            height=data["height"],
            created=data["created"],
        )

    @kit.tool(
        toolset="history",
        name="gimp_create_checkpoint",
        title="Create checkpoint",
        description=(
            "Keep a full copy of the image's current state (layers, text, masks, filters, selection) so it can "
            "be restored later: this is how to undo/redo. Copies are hidden from image lists and use memory; "
            "at most 20 per image."
        ),
        annotations=MUTATING,
    )
    async def gimp_create_checkpoint(image: ImageId, label: str | None = None) -> Checkpoint:
        codec = await kit.codec()
        data = await kit.call(
            "checkpoint.create", {"image": codec.parse_image(image), "label": label}, codec=codec, mutating=True
        )
        return checkpoint_model(codec, data)

    @kit.tool(
        toolset="history",
        name="gimp_list_checkpoints",
        title="List checkpoints",
        description="Checkpoints of an image, oldest first.",
        annotations=READ_ONLY,
    )
    async def gimp_list_checkpoints(image: ImageId) -> CheckpointList:
        codec = await kit.codec()
        data = await kit.call("checkpoint.list", {"image": codec.parse_image(image)}, codec=codec)
        return CheckpointList(image=image, checkpoints=[checkpoint_model(codec, c) for c in data["checkpoints"]])

    @kit.tool(
        toolset="history",
        name="gimp_restore_checkpoint",
        title="Restore checkpoint (undo/redo)",
        description=(
            "Replace the image with the state saved in a checkpoint. The restored image gets a NEW image id and "
            "new item ids (the old ones become invalid); GIMP windows showing it are reconnected; its file "
            "association is kept and it is marked as having unsaved changes; its GIMP undo history starts "
            "empty. Checkpoints are kept, so restoring a later one redoes. Destructive for the current state "
            "unless it was checkpointed."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_restore_checkpoint(image: ImageId, checkpoint: CheckpointId) -> RestoreResult:
        codec = await kit.codec()
        data = await kit.call(
            "checkpoint.restore",
            {"image": codec.parse_image(image), "checkpoint": codec.parse_checkpoint(checkpoint)},
            codec=codec,
            mutating=True,
        )
        ref = image_ref(codec, data)
        return RestoreResult(**{**ref.model_dump(), "image": ref.id, "previous_image": image})

    @kit.tool(
        toolset="history",
        name="gimp_delete_checkpoint",
        title="Delete checkpoint",
        description=(
            "Free a checkpoint's memory. Closing an image deletes its checkpoints too. Checkpoints are not in "
            "GIMP's undo history."
        ),
        annotations=DESTRUCTIVE,
    )
    async def gimp_delete_checkpoint(checkpoint: CheckpointId) -> DeleteCheckpointResult:
        codec = await kit.codec()
        await kit.call(
            "checkpoint.delete", {"checkpoint": codec.parse_checkpoint(checkpoint)}, codec=codec, mutating=True
        )
        return DeleteCheckpointResult(checkpoint=checkpoint, deleted=True)

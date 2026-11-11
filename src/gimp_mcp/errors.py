"""Structured errors shared by the bridge client and the MCP tools.

Every failure surfaced to an MCP client carries a stable ``code`` so an agent
can react programmatically. ``outcome`` tells whether the requested change was
applied: ``"not_applied"`` (safe to retry), ``"unknown"`` (the request may or
may not have run inside GIMP: inspect before retrying) or ``None`` for reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Outcome = Literal["not_applied", "unknown"]


@dataclass
class GimpMcpError(Exception):
    code: str
    message: str
    hint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    outcome: Outcome | None = "not_applied"

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            data["hint"] = self.hint
        if self.details:
            data["details"] = self.details
        if self.outcome:
            data["outcome"] = self.outcome
        return data


# Every error code a client can receive, with its meaning. Part of the public API (docs/api/contract.json):
# a code is never removed or renamed. tests/unit/test_api_contract.py checks that every code raised in
# src/ is listed here and documented in docs/tools.md.
ERROR_CODES: dict[str, str] = {
    "BRIDGE_ALREADY_RUNNING": "Another GIMP instance already serves the bridge socket.",
    "BRIDGE_UNAVAILABLE": "The bridge socket or pipe exists but cannot be used.",
    "CHECKPOINT_LIMIT": "Too many checkpoints on this image; delete some first.",
    "DISCONNECTED": "The connection to GIMP closed during the call.",
    "EMPTY_SELECTION": "The operation needs a selection and the image has none.",
    "FILE_EXISTS": "The target file exists and overwrite is false.",
    "FILE_NOT_FOUND": "The file to read does not exist.",
    "FONT_NOT_FOUND": "No installed font has this name.",
    "GIMP_ERROR": "GIMP reported a failure while running the operation.",
    "GIMP_NOT_FOUND": "No GIMP 3.2 executable was found.",
    "GIMP_NOT_RUNNING": "No GIMP serves the bridge: start GIMP with the plug-in installed.",
    "GIMP_START_FAILED": "A headless GIMP could not be started.",
    "IMAGE_IN_USE": "The image is shown in a GIMP window the bridge did not open; close it in GIMP.",
    "IMAGE_MISMATCH": "The items given belong to different images.",
    "INVALID_ARGUMENT": "An argument is missing, of the wrong type, out of range or inconsistent.",
    "INVALID_ID": "A string is not an image, item or checkpoint id.",
    "LOCKED": "The item's pixels, position or visibility are locked.",
    "NOT_FOUND": "No object with this id or name exists (any more).",
    "NO_OPEN_GROUP": "No undo group is open on this image.",
    "PERMISSION_DENIED": "The file system refused access to the path.",
    "PLUGIN_VERSION_MISMATCH": "The GIMP plug-in and the server are not compatible.",
    "PROCEDURE_NOT_ALLOWED": "The GIMP procedure is outside the allowlist.",
    "PROTOCOL_ERROR": "A malformed message was exchanged with the plug-in.",
    "READ_ONLY": "The object cannot be changed (e.g. a system resource).",
    "REQUEST_TOO_LARGE": "The request exceeds the bridge's message size limit.",
    "SESSION_CHANGED": "The id comes from an earlier GIMP session.",
    "TIMEOUT": "GIMP did not answer in time; the change may have been applied.",
    "TOOL_ERROR": "A batch step failed with an error that carries no code.",
    "UNAUTHORIZED": "The bridge token is missing or wrong.",
    "UNKNOWN_METHOD": "The plug-in does not know this operation (it is older than the server).",
    "UNSAFE_SOCKET_DIR": "The socket directory is not private to the user.",
    "UNSAVED_CHANGES": "The image has unsaved changes and discard_changes is false.",
    "UNSUPPORTED": "GIMP cannot do this on this object or in this mode.",
    "UNSUPPORTED_FORMAT": "No file format matches the extension or the requested format.",
    "UNSUPPORTED_TYPE": "A procedure argument has a type the bridge cannot pass.",
    "VERSION_INCOMPATIBLE": "The running GIMP is older than 3.2.",
    "WRITE_FAILED": "GIMP could not write the file.",
    "WRONG_KIND": "The id names an object of another kind (e.g. a path where a layer is expected).",
}

INSTALL_HINT = (
    "Start GIMP 3.2+ with the bridge plug-in installed (`gimp-mcp install-plugin`), "
    "or run `gimp-mcp doctor` to diagnose."
)

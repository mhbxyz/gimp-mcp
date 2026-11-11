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
    "GIMP_NOT_RUNNING": "No bridge socket, or stale socket (GIMP exited).",
    "BRIDGE_UNAVAILABLE": (
        "Socket present but no answer in time (GIMP busy/frozen), token unreadable, or a pipe served by another user."
    ),
    "VERSION_INCOMPATIBLE": "GIMP older than 3.2.",
    "PLUGIN_VERSION_MISMATCH": (
        "The GIMP plug-in and the server are not compatible (see `docs/compatibility.md`); "
        "run `gimp-mcp install-plugin`, then restart GIMP."
    ),
    "UNAUTHORIZED": "Bad token (stale token file, wrong socket).",
    "TIMEOUT": "No answer within the request timeout; mutation outcome `unknown`.",
    "DISCONNECTED": "Connection lost during a request; mutation outcome `unknown`.",
    "PROTOCOL_ERROR": "Malformed or mismatched bridge message.",
    "REQUEST_TOO_LARGE": "A request larger than the bridge's limit (8 MiB); the connection is closed.",
    "UNKNOWN_METHOD": "The plug-in does not know the operation (it is older than the server).",
    "SESSION_CHANGED": "Id issued by a previous GIMP session.",
    "INVALID_ID": "Malformed id or wrong kind (item id where an image id is expected…).",
    "NOT_FOUND": "The image/item no longer exists (closed, deleted).",
    "WRONG_KIND": "The id exists but designates another kind of object (e.g. a mask where a layer is required).",
    "INVALID_ARGUMENT": (
        "An argument is missing, of the wrong type, out of range or inconsistent (`details.errors` names each field)."
    ),
    "TOOLSET_DISABLED": "The tool exists but its toolset is not enabled: call `gimp_enable_toolsets` first.",
    "FILE_NOT_FOUND": "Input file missing.",
    "FILE_EXISTS": "Output exists and `overwrite` is false.",
    "PERMISSION_DENIED": "Input file not readable.",
    "WRITE_FAILED": "Missing/unwritable directory or GIMP failed to write.",
    "UNSUPPORTED_FORMAT": "Extension or file content not supported by this operation.",
    "UNSAVED_CHANGES": "Closing a dirty image without `discard_changes`.",
    "IMAGE_IN_USE": "Image shown in a GIMP window the bridge did not create.",
    "NO_OPEN_GROUP": "`gimp_end_undo_group` without an open group from this client (closed on disconnect).",
    "CHECKPOINT_LIMIT": "20 checkpoints already kept for the image.",
    "PROCEDURE_NOT_ALLOWED": "The procedure is outside the generic-access allowlist (`details.reason`).",
    "UNSUPPORTED_TYPE": "A procedure argument has a type the generic access cannot pass.",
    "FONT_NOT_FOUND": "Unknown font name; `details.suggestions` lists close names.",
    "EMPTY_SELECTION": "The operation needs a selection and nothing is selected.",
    "IMAGE_MISMATCH": "Objects from different images combined in one operation.",
    "LOCKED": "The targeted property or content is locked in GIMP.",
    "UNSUPPORTED": "The operation exists but cannot be used through this tool (`message` says why).",
    "READ_ONLY": "A built-in resource cannot be changed: duplicate it first.",
    "GIMP_ERROR": "Unexpected failure inside GIMP; for a mutation the outcome is `unknown`.",
    "TOOL_ERROR": "A batch step failed with an error that carries no code.",
    "GIMP_NOT_FOUND": "`gimp-mcp` found no GIMP 3.2 executable (CLI and tests).",
    "GIMP_START_FAILED": "A headless GIMP could not be started (CLI and tests).",
    "BRIDGE_ALREADY_RUNNING": "Another GIMP already serves the bridge socket (plug-in log).",
    "UNSAFE_SOCKET_DIR": "The socket directory is not private to the user (plug-in log).",
}

INSTALL_HINT = (
    "Start GIMP 3.2+ with the bridge plug-in installed (`gimp-mcp install-plugin`), "
    "or run `gimp-mcp doctor` to diagnose."
)

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


INSTALL_HINT = (
    "Start GIMP 3.2+ with the bridge plug-in installed (`gimp-mcp install-plugin`), "
    "or run `gimp-mcp doctor` to diagnose."
)

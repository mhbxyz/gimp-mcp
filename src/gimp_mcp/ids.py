"""Opaque, session-bound identifiers for GIMP objects.

GIMP numbers images and items (layers, groups, masks, channels, paths) with
integers that are unique within one GIMP process and are reused after a
restart. Exposing them raw would let an identifier obtained before a restart
silently target a different object, so every identifier carries the session it
was issued in: ``image:3@a1b2c3d4`` / ``item:12@a1b2c3d4``.
"""

from __future__ import annotations

import re

from .errors import GimpMcpError

_ID_RE = re.compile(r"^(image|item):(\d+)@([0-9A-Za-z]+)$")


class IdCodec:
    def __init__(self, session_id: str):
        self.session_id = session_id

    def image(self, number: int) -> str:
        return f"image:{number}@{self.session_id}"

    def item(self, number: int) -> str:
        return f"item:{number}@{self.session_id}"

    def parse_image(self, value: str) -> int:
        return self._parse(value, "image")

    def parse_item(self, value: str) -> int:
        return self._parse(value, "item")

    def _parse(self, value: str, kind: str) -> int:
        match = _ID_RE.match(value or "")
        if match is None or match.group(1) != kind:
            raise GimpMcpError(
                "INVALID_ID",
                f"{value!r} is not a valid {kind} id",
                hint=(
                    f"Use the {kind} ids returned by gimp_status or gimp_inspect_image, "
                    f"e.g. '{kind}:1@<session>'."
                ),
            )
        if match.group(3) != self.session_id:
            raise GimpMcpError(
                "SESSION_CHANGED",
                f"{value!r} was issued by another GIMP session (current session: {self.session_id})",
                hint="GIMP was restarted: list images again with gimp_status to get fresh ids.",
            )
        return int(match.group(2))

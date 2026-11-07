"""Path rules shared by the file tools.

* Paths are interpreted on the machine running GIMP, as the user running it.
* They must be absolute (``~`` is expanded): the MCP server and GIMP have
  different working directories, so relative paths would be ambiguous.
* Writing never replaces an existing file unless ``overwrite`` is true.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from .errors import GimpMcpError

ExportFormat = Literal["png", "jpeg"]

EXPORT_FORMATS: dict[str, ExportFormat] = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}
XCF_SUFFIXES = (".xcf",)


def _absolute(path: str) -> Path:
    expanded = Path(os.path.expanduser(path))
    if not expanded.is_absolute():
        raise GimpMcpError(
            "INVALID_ARGUMENT",
            f"path {path!r} is relative",
            hint="Give an absolute path (or one starting with ~): GIMP and the MCP server do not share a "
            "working directory.",
        )
    return expanded


def check_input_file(path: str) -> Path:
    resolved = _absolute(path)
    if not resolved.exists():
        raise GimpMcpError("FILE_NOT_FOUND", f"{resolved} does not exist", details={"path": str(resolved)})
    if not resolved.is_file():
        raise GimpMcpError("INVALID_ARGUMENT", f"{resolved} is not a regular file", details={"path": str(resolved)})
    if not os.access(resolved, os.R_OK):
        raise GimpMcpError("PERMISSION_DENIED", f"{resolved} is not readable", details={"path": str(resolved)})
    return resolved


def check_output_file(path: str, *, overwrite: bool) -> Path:
    resolved = _absolute(path)
    parent = resolved.parent
    if not parent.is_dir():
        raise GimpMcpError(
            "WRITE_FAILED",
            f"directory {parent} does not exist",
            hint="Create the directory first; file tools never create directories.",
            details={"path": str(resolved)},
        )
    if not os.access(parent, os.W_OK | os.X_OK):
        raise GimpMcpError("WRITE_FAILED", f"directory {parent} is not writable", details={"path": str(resolved)})
    if resolved.exists():
        if resolved.is_dir():
            raise GimpMcpError("INVALID_ARGUMENT", f"{resolved} is a directory", details={"path": str(resolved)})
        if not overwrite:
            raise GimpMcpError(
                "FILE_EXISTS",
                f"{resolved} already exists",
                hint="Pass overwrite=true to replace it, or choose another path.",
                details={"path": str(resolved)},
            )
        if not os.access(resolved, os.W_OK):
            raise GimpMcpError("WRITE_FAILED", f"{resolved} is not writable", details={"path": str(resolved)})
    return resolved


def export_format(path: Path, requested: str | None) -> ExportFormat:
    inferred = EXPORT_FORMATS.get(path.suffix.lower())
    if inferred is None:
        hint = "Use gimp_save_image for .xcf projects." if path.suffix.lower() in XCF_SUFFIXES else None
        raise GimpMcpError(
            "UNSUPPORTED_FORMAT",
            f"cannot export to {path.suffix or 'a file without extension'}: supported extensions are .png, .jpg, .jpeg",
            hint=hint,
            details={"path": str(path)},
        )
    if requested is not None and requested != inferred:
        raise GimpMcpError(
            "INVALID_ARGUMENT",
            f"format {requested!r} contradicts the extension of {path.name}",
            details={"path": str(path), "format": requested},
        )
    return inferred

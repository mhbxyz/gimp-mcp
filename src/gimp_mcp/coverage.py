"""Coverage matrix: which GIMP capabilities the MCP tools expose, and how they are verified.

The matrix is versioned with the code (``CAPABILITIES``) and rendered against a
procedure inventory dumped from a real GIMP (``gimp-mcp inventory``) into
``docs/coverage.md`` (``gimp-mcp coverage``). Unit tests keep both consistent:
every MCP tool is listed, every listed tool exists, and every PDB procedure
referenced exists in the committed inventory.

Procedure references are PDB names (``gimp-image-scale``). Calls without a
public PDB procedure are written ``libgimp:<function>``.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["tested", "partial", "unsupported"]


@dataclass(frozen=True)
class Capability:
    area: str
    name: str
    status: Status
    tools: tuple[str, ...] = ()
    procedures: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    notes: str = ""
    min_gimp: str = "3.2"


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "Session",
        "Connection diagnostics, open images",
        "tested",
        tools=("gimp_status",),
        procedures=("gimp-get-images", "gimp-image-get-name", "gimp-image-is-dirty", "gimp-image-get-file"),
        tests=("tests/e2e/test_connection.py", "tests/e2e/test_lifecycle.py", "tests/e2e/test_restart.py"),
    ),
    Capability(
        "Inspection",
        "Image properties and ordered layer tree (groups, masks)",
        "tested",
        tools=("gimp_inspect_image", "gimp_inspect_item"),
        procedures=(
            "gimp-image-get-layers",
            "gimp-item-get-children",
            "gimp-image-get-base-type",
            "gimp-image-get-precision",
            "gimp-image-get-resolution",
            "gimp-image-get-xcf-file",
            "gimp-layer-get-mask",
            "gimp-layer-get-mode",
            "gimp-layer-get-opacity",
            "gimp-drawable-get-offsets",
            "gimp-item-id-is-valid",
            "gimp-image-id-is-valid",
            "gimp-layer-from-mask",
        ),
        tests=("tests/e2e/test_inspect.py",),
    ),
    Capability(
        "Preview",
        "Composite preview as PNG (max 1024 px)",
        "tested",
        tools=("gimp_preview",),
        procedures=("libgimp:gimp_image_get_thumbnail",),
        tests=("tests/e2e/test_preview.py",),
        notes="8-bit sRGB rendering of the visible layers; larger renders go through export.",
    ),
    Capability(
        "Files",
        "Create, open, save XCF, export PNG/JPEG, close",
        "tested",
        tools=(
            "gimp_create_image",
            "gimp_open_image",
            "gimp_save_image",
            "gimp_export_image",
            "gimp_close_image",
        ),
        procedures=(
            "gimp-image-new",
            "gimp-layer-new",
            "gimp-image-insert-layer",
            "gimp-drawable-fill",
            "gimp-image-clean-all",
            "gimp-file-load",
            "gimp-file-save",
            "file-png-export",
            "file-jpeg-export",
            "gimp-image-delete",
            "gimp-display-new",
        ),
        tests=("tests/e2e/test_files.py",),
        notes="Other export formats (WebP, TIFF, PSD...) are reachable in the PDB but not exposed.",
    ),
    Capability(
        "Layers",
        "Create, group, import, duplicate, rename, reorder, delete layers; visibility, opacity, mode, locks",
        "tested",
        tools=(
            "gimp_create_layer",
            "gimp_create_group",
            "gimp_import_layer",
            "gimp_duplicate_layer",
            "gimp_set_layer_properties",
            "gimp_move_layer",
            "gimp_delete_layer",
        ),
        procedures=(
            "gimp-layer-new",
            "gimp-group-layer-new",
            "gimp-file-load-layer",
            "gimp-layer-copy",
            "gimp-item-set-name",
            "gimp-item-set-visible",
            "gimp-layer-set-opacity",
            "gimp-layer-set-mode",
            "gimp-item-set-lock-position",
            "gimp-item-set-lock-content",
            "gimp-image-reorder-item",
            "gimp-image-remove-layer",
            "gimp-image-undo-group-start",
            "gimp-image-undo-group-end",
        ),
        tests=("tests/e2e/test_layers.py",),
    ),
    Capability(
        "Geometry",
        "Scale/resize canvas/crop images; move, scale, rotate, flip layers",
        "tested",
        tools=(
            "gimp_resize_image",
            "gimp_resize_canvas",
            "gimp_crop_image",
            "gimp_set_layer_offsets",
            "gimp_scale_layer",
            "gimp_rotate_layer",
            "gimp_flip_layer",
        ),
        procedures=(
            "gimp-image-scale",
            "gimp-image-resize",
            "gimp-image-crop",
            "gimp-layer-set-offsets",
            "gimp-layer-scale",
            "gimp-item-transform-rotate",
            "gimp-item-transform-flip-simple",
            "gimp-context-set-interpolation",
            "gimp-context-set-transform-resize",
        ),
        tests=("tests/e2e/test_transform.py",),
        notes="Perspective, shear and arbitrary matrices are not exposed.",
    ),
    Capability(
        "Discovery",
        "Search and describe PDB procedures (read-only)",
        "tested",
        tools=("gimp_search_procedures", "gimp_describe_procedure"),
        procedures=("gimp-drawable-filter-operation-get-available",),
        tests=("tests/e2e/test_procedures.py",),
        notes="Introspection only; nothing is executed.",
    ),
    Capability(
        "History",
        "Undo / redo from a client",
        "unsupported",
        notes="GIMP 3.2 offers no undo/redo procedure to plug-ins (only undo groups); see #9.",
    ),
    Capability(
        "Painting",
        "Fill (selection or whole layer), polylines, rectangles and ellipses with explicit color/width/opacity",
        "tested",
        tools=("gimp_fill", "gimp_draw_path", "gimp_draw_shape"),
        procedures=(
            "gimp-drawable-edit-fill",
            "gimp-drawable-edit-stroke-item",
            "gimp-drawable-edit-stroke-selection",
            "gimp-path-new",
            "gimp-path-stroke-new-from-points",
            "gimp-image-insert-path",
            "gimp-image-remove-path",
            "gimp-selection-save",
            "gimp-image-select-item",
            "gimp-image-remove-channel",
            "gimp-drawable-mask-intersect",
            "gimp-context-push",
            "gimp-context-pop",
            "gimp-context-set-defaults",
            "gimp-context-set-foreground",
            "gimp-context-set-opacity",
            "gimp-context-set-paint-mode",
            "gimp-context-set-stroke-method",
            "gimp-context-set-line-width",
            "gimp-context-set-line-cap-style",
            "gimp-context-set-line-join-style",
        ),
        tests=("tests/e2e/test_paint.py",),
        notes="Brush-based painting (paintbrush, airbrush, clone...) and gradients are not exposed.",
    ),
    Capability(
        "Selections",
        "Rectangle/ellipse selections (replace/add/subtract/intersect), all/none/invert, bounds; layer masks",
        "tested",
        tools=(
            "gimp_select_rectangle",
            "gimp_select_ellipse",
            "gimp_modify_selection",
            "gimp_get_selection",
            "gimp_add_layer_mask",
            "gimp_set_layer_mask",
            "gimp_remove_layer_mask",
        ),
        procedures=(
            "gimp-image-select-rectangle",
            "gimp-image-select-ellipse",
            "gimp-selection-all",
            "gimp-selection-none",
            "gimp-selection-invert",
            "gimp-selection-bounds",
            "gimp-selection-value",
            "gimp-selection-is-empty",
            "gimp-context-set-feather",
            "gimp-context-set-feather-radius",
            "gimp-context-set-antialias",
            "gimp-layer-create-mask",
            "gimp-layer-add-mask",
            "gimp-layer-remove-mask",
            "gimp-layer-set-apply-mask",
            "gimp-layer-set-show-mask",
            "gimp-layer-set-edit-mask",
            "gimp-drawable-invert",
        ),
        tests=("tests/e2e/test_selections.py",),
        notes="Free/fuzzy/by-color selections, paths and channels are not exposed.",
    ),
    Capability(
        "Filters",
        "Brightness/contrast, hue/saturation, Gaussian blur; destructive or editable (non-destructive) filters",
        "tested",
        tools=(
            "gimp_brightness_contrast",
            "gimp_hue_saturation",
            "gimp_gaussian_blur",
            "gimp_list_filters",
            "gimp_remove_filter",
        ),
        procedures=(
            "gimp-drawable-brightness-contrast",
            "gimp-drawable-hue-saturation",
            "gimp-drawable-filter-new",
            "libgimp:gimp_drawable_append_filter",
            "libgimp:gimp_drawable_merge_filter",
            "gimp-drawable-get-filters",
            "gimp-drawable-filter-delete",
            "gimp-drawable-filter-get-operation-name",
        ),
        tests=("tests/e2e/test_filters.py",),
        notes="Other GEGL operations are available in GIMP but not exposed (see gegl_operations in the inventory).",
    ),
    Capability("Text", "Editable text layers", "unsupported", notes="Planned: #14."),
    Capability("Generic PDB", "Calling allowed PDB procedures", "unsupported", notes="Planned: #16."),
    Capability(
        "Other",
        "Paths/vectors, channels, guides, color mode conversion, indexed images, animation",
        "unsupported",
        notes="Not planned yet.",
    ),
)


@dataclass
class Inventory:
    gimp_version: str
    procedures: dict[str, dict[str, object]]
    gegl_operations: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Inventory:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            gimp_version=data["gimp_version"],
            procedures={p["name"]: p for p in data["procedures"]},
            gegl_operations=list(data.get("gegl_operations", [])),
        )


def referenced_procedures() -> set[str]:
    return {p for cap in CAPABILITIES for p in cap.procedures if not p.startswith("libgimp:")}


def all_tools() -> set[str]:
    return {tool for cap in CAPABILITIES for tool in cap.tools}


def _family(name: str) -> str:
    parts = name.split("-")
    return "-".join(parts[:2]) if parts[0] in ("gimp", "file", "plug", "script", "python") else parts[0]


def render_matrix(inventory_path: Path) -> str:
    inventory = Inventory.load(inventory_path)
    names = set(inventory.procedures)
    used = referenced_procedures() & names
    missing = sorted(referenced_procedures() - names)
    types = Counter(str(p.get("type")) for p in inventory.procedures.values())
    families = Counter(_family(name) for name in names)
    used_families = Counter(_family(name) for name in used)
    lines = [
        "# Coverage matrix",
        "",
        "<!-- Generated by `gimp-mcp coverage --inventory docs/coverage/pdb-inventory.json"
        " --output docs/coverage.md`. Do not edit by hand: edit `src/gimp_mcp/coverage.py`. -->",
        "",
        f"Inventory: GIMP **{inventory.gimp_version}**, {len(names)} PDB procedures ("
        + ", ".join(f"{count} {kind}" for kind, count in sorted(types.items()))
        + f"), {len(inventory.gegl_operations)} GEGL operations available to filters.",
        "",
        f"MCP tools: **{len(all_tools())}**. PDB procedures relied upon by tools: **{len(used)}** "
        f"({len(used) * 100 / max(1, len(names)):.1f}% of the inventory). Most PDB procedures are low-level "
        "getters/setters, so this percentage measures breadth, not usefulness.",
        "",
        "## Capabilities",
        "",
        "| Area | Capability | Status | MCP tools | Verified by | Min. GIMP | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for cap in CAPABILITIES:
        tools = ", ".join(f"`{t}`" for t in cap.tools) or "—"
        tests = ", ".join(f"`{t}`" for t in cap.tests) or "—"
        lines.append(
            f"| {cap.area} | {cap.name} | {cap.status} | {tools} | {tests} | {cap.min_gimp} | {cap.notes or ''} |"
        )
    lines += [
        "",
        "## Procedure families",
        "",
        "| Family | Procedures in GIMP | Used by MCP tools |",
        "|---|---|---|",
    ]
    for family, count in sorted(families.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{family}-*` | {count} | {used_families.get(family, 0)} |")
    lines += ["", "## Version-dependent references", ""]
    if missing:
        lines += [
            "Procedures referenced by tools but absent from this inventory (tools using them will fail):",
            "",
        ]
        lines += [f"- `{name}`" for name in missing]
    else:
        lines.append("Every procedure referenced by the tools exists in this inventory.")
    lines += [
        "",
        "## Regenerating",
        "",
        "```sh",
        "uv run gimp-mcp inventory --output docs/coverage/pdb-inventory.json   # needs a running GIMP",
        "uv run gimp-mcp coverage --inventory docs/coverage/pdb-inventory.json --output docs/coverage.md",
        "```",
        "",
    ]
    return "\n".join(lines)

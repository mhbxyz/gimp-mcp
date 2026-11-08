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
from types import ModuleType
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
        "Session",
        "Toolsets: list the tool groups, enable more during a session",
        "tested",
        tools=("gimp_list_toolsets", "gimp_enable_toolsets"),
        tests=("tests/unit/test_toolsets.py", "tests/e2e/test_thumbnail_journey.py"),
        notes="MCP-side only, no GIMP procedure; see docs/toolsets.md",
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
        "Animation",
        "Frames with duration and disposal, frame previews, optimize/unoptimize, animated GIF and WebP export",
        "tested",
        tools=(
            "gimp_list_frames",
            "gimp_add_frame",
            "gimp_set_frame",
            "gimp_preview_frame",
            "gimp_optimize_animation",
            "gimp_export_animation",
        ),
        procedures=(
            "plug-in-animationoptimize",
            "plug-in-animationoptimize-diff",
            "plug-in-animationunoptimize",
            "file-gif-export",
            "file-webp-export",
        ),
        tests=("tests/e2e/test_animation.py", "tests/unit/test_animation_names.py"),
        notes="No APNG exporter in GIMP 3.2.",
    ),
    Capability(
        "Batch processing",
        "A recipe of tool calls run over explicit files or a confined glob, with naming patterns and per-file reports",
        "tested",
        tools=("gimp_run_batch",),
        tests=("tests/e2e/test_batch.py", "tests/unit/test_batch_tools.py"),
        notes="Server-side: each step is an ordinary call of a listed tool; images are closed without saving.",
    ),
    Capability(
        "Text",
        "Rich text markup, outline, kerning, hinting, indent, language, base direction, text box",
        "tested",
        tools=("gimp_set_text_style", "gimp_inspect_text_style"),
        procedures=(
            "gimp-text-layer-set-markup",
            "gimp-text-layer-get-markup",
            "gimp-text-layer-set-outline",
            "gimp-text-layer-set-outline-color",
            "gimp-text-layer-set-outline-width",
            "gimp-text-layer-set-kerning",
            "gimp-text-layer-set-hint-style",
            "gimp-text-layer-set-indent",
            "gimp-text-layer-set-language",
            "gimp-text-layer-set-base-direction",
            "gimp-text-layer-resize",
        ),
        tests=("tests/e2e/test_typography.py", "tests/unit/test_text_markup.py"),
        notes="Text along a path: no GIMP 3.2 API (#88).",
    ),
    Capability(
        "Vector layers",
        "Vector layers from paths with editable fill and stroke; link layers to external files",
        "tested",
        tools=(
            "gimp_create_vector_layer",
            "gimp_set_vector_layer",
            "gimp_inspect_vector_layer",
            "gimp_create_link_layer",
            "gimp_set_link_layer",
            "gimp_inspect_link_layer",
        ),
        procedures=(
            "gimp-vector-layer-new",
            "gimp-vector-layer-set-fill-color",
            "gimp-vector-layer-set-stroke-color",
            "gimp-vector-layer-set-stroke-width",
            "gimp-vector-layer-set-stroke-dash-pattern",
            "gimp-vector-layer-refresh",
            "gimp-link-layer-new",
            "gimp-link-layer-set-file",
            "gimp-link-layer-get-file",
        ),
        tests=("tests/e2e/test_vector_layers.py",),
    ),
    Capability(
        "Selections",
        "Select by color, fuzzy select, from alpha / text / path / channel",
        "tested",
        tools=("gimp_select_by_color", "gimp_select_item"),
        procedures=(
            "gimp-image-select-color",
            "gimp-image-select-contiguous-color",
            "gimp-image-select-item",
            "gimp-context-set-sample-criterion",
        ),
        tests=("tests/e2e/test_channels.py",),
    ),
    Capability(
        "Selections",
        "Grow, shrink, border, feather, sharpen, round, remove holes, translate",
        "tested",
        tools=("gimp_modify_selection_shape",),
        procedures=(
            "gimp-selection-grow",
            "gimp-selection-shrink",
            "gimp-selection-border",
            "gimp-selection-feather",
            "gimp-selection-sharpen",
            "gimp-selection-flood",
            "gimp-selection-translate",
            "script-fu-selection-round",
        ),
        tests=("tests/e2e/test_channels.py",),
    ),
    Capability(
        "Selections",
        "Channels: create (empty, selection, component), set, combine, delete; listed in inspection, kept in XCF",
        "tested",
        tools=("gimp_create_channel", "gimp_set_channel", "gimp_combine_channels", "gimp_delete_channel"),
        procedures=(
            "gimp-channel-new",
            "gimp-channel-new-from-component",
            "gimp-selection-save",
            "gimp-channel-combine-masks",
            "gimp-channel-set-color",
            "gimp-channel-set-opacity",
            "gimp-image-remove-channel",
            "gimp-image-get-channels",
        ),
        tests=("tests/e2e/test_channels.py",),
    ),
    Capability(
        "Geometry",
        "Perspective, shear, matrix and rotation around a point on layers, groups, paths, channels and selection",
        "tested",
        tools=("gimp_transform",),
        procedures=(
            "gimp-item-transform-perspective",
            "gimp-item-transform-shear",
            "gimp-item-transform-matrix",
            "gimp-item-transform-rotate",
            "gimp-context-set-transform-resize",
        ),
        tests=("tests/e2e/test_geometry.py",),
    ),
    Capability(
        "Geometry",
        "Image rotation by 90/180/270, image flip, canvas resize with layer resize and fill",
        "tested",
        tools=("gimp_rotate_image", "gimp_flip_image", "gimp_resize_canvas"),
        procedures=("gimp-image-rotate", "gimp-image-flip", "gimp-image-resize", "gimp-layer-resize-to-image-size"),
        tests=("tests/e2e/test_geometry.py",),
    ),
    Capability(
        "Painting",
        "Paint along strokes: paintbrush, pencil, airbrush, ink, eraser, smudge, dodge/burn, clone, heal",
        "tested",
        tools=("gimp_paint_stroke",),
        procedures=(
            "gimp-paintbrush",
            "gimp-pencil",
            "gimp-airbrush",
            "gimp-eraser",
            "gimp-smudge",
            "gimp-dodgeburn",
            "gimp-clone",
            "gimp-heal",
            "gimp-context-set-dynamics-name",
            "gimp-context-set-brush-size",
        ),
        tests=("tests/e2e/test_painting.py",),
    ),
    Capability(
        "Painting",
        "Gradient fill (named or inline, shapes, repeat, offset) and bucket fill (color, pattern, gradient)",
        "tested",
        tools=("gimp_gradient_fill", "gimp_bucket_fill"),
        procedures=(
            "gimp-drawable-edit-gradient-fill",
            "gimp-drawable-edit-bucket-fill",
            "gimp-context-set-sample-threshold",
            "gimp-context-set-sample-criterion",
            "gimp-image-select-contiguous-color",
        ),
        tests=("tests/e2e/test_painting.py",),
    ),
    Capability(
        "Formats",
        "Export to every GIMP format with introspected options (WebP, AVIF/HEIF, TIFF, BMP, GIF, ICO, PDF, PSD…)",
        "tested",
        tools=("gimp_list_file_formats", "gimp_describe_file_format", "gimp_export_as"),
        procedures=(
            "file-webp-export",
            "file-heif-av1-export",
            "file-heif-export",
            "file-tiff-export",
            "file-bmp-export",
            "file-gif-export",
            "file-ico-export",
            "file-pdf-export",
            "file-psd-export",
        ),
        tests=("tests/e2e/test_formats.py", "tests/unit/test_formats.py"),
    ),
    Capability(
        "Formats",
        "Open PDF (pages, size), SVG (size), PSD layers, multi-page TIFF, RAW through GIMP's detection",
        "partial",
        tools=("gimp_open_with_options",),
        procedures=("file-pdf-load", "file-svg-load", "file-psd-load", "file-tiff-load", "gimp-file-load"),
        tests=("tests/e2e/test_formats.py",),
        notes="PDF pages are filtered after loading (GimpInt32Array options cannot be set); RAW is not tested "
        "(needs darktable or RawTherapee).",
    ),
    Capability(
        "Formats",
        "Export layers or groups to separate files, and regions (slices)",
        "tested",
        tools=("gimp_export_layers", "gimp_export_region"),
        procedures=("gimp-layer-new-from-drawable", "gimp-image-crop", "gimp-image-duplicate"),
        tests=("tests/e2e/test_formats.py",),
    ),
    Capability(
        "Document",
        "Guides and sample points (add, list with values, remove)",
        "tested",
        tools=("gimp_list_guides", "gimp_add_guide", "gimp_add_sample_point", "gimp_remove_guide"),
        procedures=(
            "gimp-image-add-hguide",
            "gimp-image-add-vguide",
            "gimp-image-find-next-guide",
            "gimp-image-delete-guide",
            "gimp-image-add-sample-point",
            "gimp-image-find-next-sample-point",
            "gimp-image-get-sample-point-position",
            "gimp-image-delete-sample-point",
        ),
        tests=("tests/e2e/test_document.py",),
    ),
    Capability(
        "Document",
        "Exif/XMP/IPTC metadata and comment; exports keep only what is asked",
        "tested",
        tools=("gimp_get_metadata", "gimp_set_metadata"),
        procedures=(
            "libgimp:gimp_image_get_metadata",
            "libgimp:gimp_image_set_metadata",
            "gimp-image-attach-parasite",
            "gimp-image-get-parasite",
        ),
        tests=("tests/e2e/test_document.py",),
    ),
    Capability(
        "Document",
        "Resolution, unit and print size",
        "tested",
        tools=("gimp_set_print_size",),
        procedures=("gimp-image-set-resolution", "gimp-image-set-unit", "gimp-image-get-unit"),
        tests=("tests/e2e/test_document.py",),
    ),
    Capability(
        "Composition",
        "Copy/cut (layers, selection, visible) and paste into a layer, as a layer or a new image",
        "tested",
        tools=("gimp_copy", "gimp_paste"),
        procedures=(
            "gimp-edit-named-copy",
            "gimp-edit-named-cut",
            "gimp-edit-named-copy-visible",
            "gimp-edit-named-paste",
            "gimp-edit-named-paste-as-new-image",
            "gimp-edit-copy",
            "gimp-edit-paste",
            "gimp-floating-sel-anchor",
            "gimp-floating-sel-to-layer",
        ),
        tests=("tests/e2e/test_compose.py",),
    ),
    Capability(
        "Composition",
        "Merge down, merge group, merge visible, flatten, new layer from visible",
        "tested",
        tools=("gimp_merge_layers", "gimp_flatten_image", "gimp_new_layer_from_visible"),
        procedures=(
            "gimp-image-merge-down",
            "gimp-image-merge-visible-layers",
            "gimp-group-layer-merge",
            "gimp-image-flatten",
            "gimp-layer-new-from-visible",
        ),
        tests=("tests/e2e/test_compose.py",),
    ),
    Capability(
        "Composition",
        "Alpha channel, alpha to selection, layer boundary, crop to content, align and distribute",
        "tested",
        tools=(
            "gimp_set_alpha_channel",
            "gimp_alpha_to_selection",
            "gimp_fit_layer",
            "gimp_crop_to_content",
            "gimp_align_layers",
        ),
        procedures=(
            "gimp-layer-add-alpha",
            "gimp-layer-flatten",
            "gimp-layer-resize-to-image-size",
            "gimp-layer-resize",
            "gimp-image-autocrop",
            "gimp-image-autocrop-selected-layers",
            "gimp-layer-set-offsets",
        ),
        tests=("tests/e2e/test_compose.py", "tests/unit/test_align.py"),
    ),
    Capability(
        "Resources",
        "List and inspect brushes, gradients, patterns, palettes with previews",
        "tested",
        tools=("gimp_list_resources", "gimp_inspect_resource"),
        procedures=(
            "gimp-brushes-get-list",
            "gimp-gradients-get-list",
            "gimp-patterns-get-list",
            "gimp-palettes-get-list",
            "gimp-brush-get-info",
            "gimp-pattern-get-info",
            "gimp-gradient-get-uniform-samples",
            "gimp-palette-get-colors",
        ),
        tests=("tests/e2e/test_resources.py", "tests/unit/test_resource_helpers.py"),
    ),
    Capability(
        "Resources",
        "Create, edit (generated brushes, gradients, palettes), duplicate, rename, delete user resources",
        "tested",
        tools=(
            "gimp_create_resource",
            "gimp_duplicate_resource",
            "gimp_rename_resource",
            "gimp_delete_resource",
            "gimp_edit_brush",
            "gimp_edit_gradient",
            "gimp_edit_palette",
        ),
        procedures=(
            "gimp-brush-new",
            "gimp-gradient-new",
            "gimp-palette-new",
            "gimp-resource-duplicate",
            "gimp-resource-rename",
            "gimp-resource-delete",
            "gimp-brush-set-shape",
            "gimp-gradient-segment-range-split-uniform",
            "gimp-palette-add-entry",
        ),
        tests=("tests/e2e/test_resources.py",),
        notes="Patterns cannot be created from a plug-in in GIMP 3.2.",
    ),
    Capability(
        "Resources",
        "Palette import (.gpl, .act, .aco, .ase, .pal) and export (gpl, css, text, python, php, java, kpl)",
        "tested",
        tools=("gimp_import_palette", "gimp_export_palette"),
        procedures=(
            "gimp-palettes-refresh",
            "gimp-palette-export-css",
            "gimp-palette-export-text",
            "python-fu-palette-export-as-kpl",
        ),
        tests=("tests/e2e/test_resources.py", "tests/unit/test_palette_files.py"),
        notes="Formats other than .gpl are read by gimp-mcp (GIMP 3.2 reads them only in its dialog); "
        "CMYK and Lab swatches are refused.",
    ),
    Capability(
        "Paths",
        "Create paths (polylines, Bézier, ellipses, text outlines), inspect, rename, show, duplicate, delete",
        "tested",
        tools=(
            "gimp_create_path",
            "gimp_add_path_stroke",
            "gimp_path_from_text",
            "gimp_inspect_path",
            "gimp_set_path",
            "gimp_duplicate_path",
            "gimp_delete_path",
        ),
        procedures=(
            "gimp-path-new",
            "gimp-image-insert-path",
            "gimp-path-bezier-stroke-new-moveto",
            "gimp-path-bezier-stroke-lineto",
            "gimp-path-bezier-stroke-cubicto",
            "gimp-path-bezier-stroke-conicto",
            "gimp-path-bezier-stroke-new-ellipse",
            "gimp-path-stroke-close",
            "gimp-path-new-from-text-layer",
            "gimp-path-get-strokes",
            "gimp-path-stroke-get-points",
            "gimp-path-copy",
            "gimp-image-remove-path",
            "gimp-image-get-paths",
        ),
        tests=("tests/e2e/test_paths.py",),
    ),
    Capability(
        "Paths",
        "Edit strokes (translate, scale, rotate, flip, reverse, close, remove); length and point at distance",
        "tested",
        tools=("gimp_edit_path_stroke", "gimp_path_point_at"),
        procedures=(
            "gimp-path-stroke-translate",
            "gimp-path-stroke-scale",
            "gimp-path-stroke-rotate",
            "gimp-path-stroke-flip",
            "gimp-path-stroke-reverse",
            "gimp-path-remove-stroke",
            "gimp-path-stroke-get-length",
            "gimp-path-stroke-get-point-at-dist",
        ),
        tests=("tests/e2e/test_paths.py",),
    ),
    Capability(
        "Paths",
        "Path to selection, selection to path, stroke (line or brush), fill",
        "tested",
        tools=("gimp_path_to_selection", "gimp_selection_to_path", "gimp_stroke_path", "gimp_fill_path"),
        procedures=(
            "libgimp:gimp_image_select_item",
            "plug-in-sel2path",
            "gimp-drawable-edit-stroke-item",
            "gimp-context-set-stroke-method",
        ),
        tests=("tests/e2e/test_paths.py",),
    ),
    Capability(
        "Paths",
        "SVG import (file or string) and export; paths kept in XCF",
        "tested",
        tools=("gimp_import_svg_paths", "gimp_export_path_svg"),
        procedures=(
            "gimp-image-import-paths-from-string",
            "gimp-image-import-paths-from-file",
            "gimp-image-export-path-to-string",
        ),
        tests=("tests/e2e/test_paths.py",),
    ),
    Capability(
        "Modes",
        "Convert between RGB, grayscale and indexed (palette, colors, dithering)",
        "tested",
        tools=("gimp_convert_mode",),
        procedures=("gimp-image-convert-rgb", "gimp-image-convert-grayscale", "gimp-image-convert-indexed"),
        tests=("tests/e2e/test_modes.py",),
    ),
    Capability(
        "Modes",
        "Convert precision (8/16/32-bit integer, half/float/double, linear or not)",
        "tested",
        tools=("gimp_convert_precision",),
        procedures=("gimp-image-convert-precision", "gimp-image-get-precision"),
        tests=("tests/e2e/test_modes.py",),
    ),
    Capability(
        "Modes",
        "Color profiles: read, assign, convert (intent, BPC), remove, built-in or ICC file; embed on export",
        "tested",
        tools=("gimp_get_color_profile", "gimp_set_color_profile"),
        procedures=(
            "libgimp:gimp_image_get_color_profile",
            "libgimp:gimp_image_get_effective_color_profile",
            "libgimp:gimp_image_set_color_profile",
            "libgimp:gimp_image_convert_color_profile",
            "libgimp:gimp_color_profile_new_from_file",
        ),
        tests=("tests/e2e/test_modes.py",),
    ),
    Capability(
        "Color",
        "Levels, color balance, colorize, desaturate, invert, threshold, posterize (editable or destructive)",
        "tested",
        tools=(
            "gimp_levels",
            "gimp_color_balance",
            "gimp_colorize",
            "gimp_desaturate",
            "gimp_invert",
            "gimp_threshold",
            "gimp_posterize",
        ),
        procedures=(
            "gimp-drawable-filter-new",
            "gimp-drawable-levels",
            "gimp-drawable-color-balance",
            "gimp-drawable-colorize-hsl",
            "gimp-drawable-desaturate",
            "gimp-drawable-invert",
            "gimp-drawable-threshold",
            "gimp-drawable-posterize",
        ),
        tests=("tests/unit/test_color_plans.py", "tests/e2e/test_color.py"),
        notes="Through GIMP's own operations (gimp:levels…) as filters, merged for destructive mode.",
    ),
    Capability(
        "Color",
        "Curves (spline points or explicit samples)",
        "tested",
        tools=("gimp_curves",),
        procedures=("gimp-drawable-curves-spline", "gimp-drawable-curves-explicit"),
        tests=("tests/e2e/test_color.py",),
        notes="Destructive only: an editable curves filter needs a GimpCurve object.",
    ),
    Capability(
        "Color",
        "Exposure, shadows-highlights, white balance, equalize, stretch contrast",
        "tested",
        tools=("gimp_exposure", "gimp_shadows_highlights", "gimp_auto_adjust"),
        procedures=("gimp-drawable-levels-stretch", "gimp-drawable-equalize"),
        tests=("tests/e2e/test_color.py",),
    ),
    Capability(
        "Filters",
        "GEGL filter catalog: list and describe operations (introspected from GIMP)",
        "tested",
        tools=("gimp_list_filter_operations", "gimp_describe_filter_operation"),
        procedures=(
            "gimp-drawable-filter-operation-get-available",
            "gimp-drawable-filter-operation-get-details",
            "gimp-drawable-filter-new",
        ),
        tests=("tests/unit/test_filter_catalog.py", "tests/e2e/test_effects.py"),
        notes="Scripts, auxiliary-input and internal operations are listed as unsupported, with the reason.",
    ),
    Capability(
        "Filters",
        "Apply any supported GEGL operation, destructive or editable, respecting the selection",
        "tested",
        tools=("gimp_apply_filter",),
        procedures=("gimp-drawable-filter-new", "gimp-drawable-merge-filters", "libgimp:gimp_drawable_append_filter"),
        tests=("tests/e2e/test_effects.py",),
        notes="Curated pixel checks (unsharp mask, noise reduction, pixelize, drop shadow, vignette, lens "
        "distortion) and a smoke test of every supported operation with its defaults.",
    ),
    Capability(
        "Filters",
        "Editable filters: inspect, change parameters, visibility, opacity, blend mode, reorder, merge",
        "tested",
        tools=("gimp_inspect_filter", "gimp_set_filter", "gimp_move_filter", "gimp_merge_filters"),
        procedures=(
            "gimp-drawable-get-filters",
            "gimp-drawable-filter-get-blend-mode",
            "gimp-drawable-filter-get-opacity",
            "gimp-drawable-filter-get-visible",
            "gimp-drawable-filter-set-visible",
            "gimp-drawable-filter-delete",
            "gimp-drawable-merge-filters",
        ),
        tests=("tests/e2e/test_effects.py",),
        notes="No reorder or single-filter merge in GIMP 3.2: filters above are re-created (new ids).",
    ),
    Capability(
        "Analysis",
        "Histogram and statistics per channel (region, selection)",
        "tested",
        tools=("gimp_histogram",),
        procedures=("libgimp:gegl_buffer_get", "gimp-image-duplicate", "gimp-image-merge-visible-layers"),
        tests=("tests/unit/test_stats.py", "tests/e2e/test_analysis.py"),
        notes="8-bit sRGB values; pixels count unweighted by alpha (alpha is its own channel), selection >= 50%.",
    ),
    Capability(
        "Analysis",
        "Color sampling at points, with averaging radius",
        "tested",
        tools=("gimp_sample_colors",),
        procedures=("libgimp:gegl_buffer_get",),
        tests=("tests/e2e/test_analysis.py",),
    ),
    Capability(
        "Analysis",
        "Compare images, layers or checkpoints (changed pixels, bounds, difference preview)",
        "tested",
        tools=("gimp_compare",),
        procedures=("libgimp:gegl_buffer_get", "gimp-image-duplicate", "gimp-image-merge-visible-layers"),
        tests=("tests/unit/test_stats.py", "tests/e2e/test_analysis.py"),
    ),
    Capability(
        "Analysis",
        "Dominant colors; full-resolution crop preview",
        "tested",
        tools=("gimp_dominant_colors", "gimp_preview_region"),
        procedures=("gimp-image-crop", "libgimp:gimp_image_get_thumbnail"),
        tests=("tests/unit/test_stats.py", "tests/e2e/test_analysis.py"),
        notes="Crop previews are rendered from a temporary copy, up to 1024 px per side.",
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
        "Undo groups (one GIMP undo step, closed on disconnect); checkpoints for undo/redo by agents",
        "tested",
        tools=(
            "gimp_begin_undo_group",
            "gimp_end_undo_group",
            "gimp_create_checkpoint",
            "gimp_list_checkpoints",
            "gimp_restore_checkpoint",
            "gimp_delete_checkpoint",
        ),
        procedures=(
            "gimp-image-undo-group-start",
            "gimp-image-undo-group-end",
            "gimp-image-duplicate",
            "gimp-image-set-file",
            "gimp-displays-reconnect",
            "gimp-image-undo-disable",
            "gimp-image-undo-enable",
        ),
        tests=("tests/e2e/test_history.py", "tests/unit/test_undo_groups.py"),
        notes="GIMP 3.2 has no undo/redo procedure for plug-ins: restoring a checkpoint replaces the image "
        "(new ids). The effect of undo groups on GIMP's own history cannot be read back by plug-ins.",
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
    Capability(
        "Text",
        "Editable text layers: text, font, size (px/pt), color, justification, spacing, fixed box; font list",
        "tested",
        tools=("gimp_create_text_layer", "gimp_set_text", "gimp_inspect_text", "gimp_list_fonts"),
        procedures=(
            "gimp-text-layer-new",
            "gimp-text-layer-set-text",
            "gimp-text-layer-set-font",
            "gimp-text-layer-set-font-size",
            "gimp-text-layer-set-color",
            "gimp-text-layer-set-justification",
            "gimp-text-layer-set-letter-spacing",
            "gimp-text-layer-set-line-spacing",
            "gimp-text-layer-set-antialias",
            "gimp-text-layer-resize",
            "gimp-text-layer-get-text",
            "gimp-text-layer-get-font",
            "gimp-text-layer-get-font-size",
            "gimp-text-layer-get-color",
            "gimp-fonts-get-list",
            "gimp-font-get-by-name",
        ),
        tests=("tests/e2e/test_text.py",),
        notes="Rich markup, outlines, kerning, language and text along paths are not exposed; the fixed/dynamic "
        "box mode cannot be read back through libgimp.",
    ),
    Capability(
        "Generic PDB",
        "List and call allowlisted PDB procedures with typed JSON arguments (see section below)",
        "tested",
        tools=("gimp_list_callable_procedures", "gimp_call_procedure"),
        procedures=("libgimp:gimp_procedure_run_config",),
        tests=("tests/e2e/test_pdb_access.py", "tests/unit/test_pdb_policy.py"),
        notes="Allowlist policy in plugin/gimp-mcp-bridge/gmb_policy.py; run mode forced to non-interactive.",
    ),
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


def load_plugin_module(name: str) -> ModuleType:
    from .plugin_modules import load

    return load(name)


def _reason_category(reason: str | None) -> str:
    text = reason or ""
    if text.startswith("denied"):
        return "denied by name (code evaluation, UI, shared context, quitting, external effects...)"
    if text.startswith("outside"):
        return "outside the allowed families (files, exports, resources, ...)"
    if "unsupported type" in text:
        return "argument or return type not representable in JSON (" + text.rsplit(" ", 1)[-1] + ")"
    if text.startswith("procedure type"):
        return "temporary/persistent procedure"
    return text or "unknown"


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
    policy = load_plugin_module("gmb_policy")
    verdicts = {name: policy.evaluate(meta) for name, meta in inventory.procedures.items()}
    callable_names = sorted(name for name, (ok, _reason) in verdicts.items() if ok)
    reasons = Counter(_reason_category(reason) for ok, reason in verdicts.values() if not ok)
    lines += [
        "",
        "## Generic access (`gimp_call_procedure`)",
        "",
        f"**{len(callable_names)}** of {len(names)} procedures are callable through the allowlist "
        "(`gmb_policy.evaluate`). Refused procedures by reason:",
        "",
        "| Reason | Procedures |",
        "|---|---|",
    ]
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {reason} | {count} |")
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

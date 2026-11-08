"""MCP prompts (#62): common workflows spelled out with the tools to use.

Every ``gimp_*`` name a prompt mentions is checked against the server's tools by
``tests/unit/test_protocol.py``.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

CHECKPOINT = (
    "Before editing, call gimp_create_checkpoint (toolset history) so you can go back with "
    "gimp_restore_checkpoint if a step goes wrong."
)


def register(mcp: MCPServer) -> None:
    @mcp.prompt(
        name="thumbnail",
        title="Make a thumbnail",
        description="Open an image, scale it so its longest side fits, export it and close it.",
    )
    def thumbnail(path: str, size: str = "256", output: str = "") -> str:
        target = output or f"a PNG next to {path} named <name>-thumb.png"
        return f"""Make a thumbnail of {path} whose longest side is {size} px, with GIMP.

1. gimp_open_image with path {path}; keep the returned image id.
2. gimp_inspect_image to read its width and height; compute the new size so the longest side is
   {size} px and the aspect ratio is kept (never enlarge a smaller image).
3. gimp_resize_image with that width and height (interpolation cubic).
4. gimp_export_image to {target}. Do not replace an existing file unless the user asked for it
   (overwrite=true).
5. gimp_preview to check the result, then gimp_close_image with discard_changes=true so the
   original file is left untouched."""

    @mcp.prompt(
        name="remove-background",
        title="Remove a background",
        description="Make the background of a photo or logo transparent with a layer mask, then export a PNG.",
    )
    def remove_background(path: str, output: str = "") -> str:
        target = output or f"a PNG next to {path} named <name>-cutout.png"
        return f"""Remove the background of {path} with GIMP, keeping the subject.

1. gimp_open_image with path {path}, then gimp_preview to see where the background is.
2. gimp_enable_toolsets with ["channels", "compose", "history", "analysis"] if those tools are
   not listed yet. {CHECKPOINT}
3. gimp_inspect_image to get the layer id, and gimp_set_alpha_channel(action="add") on it.
4. Select the background: gimp_select_by_color with a point on the background (fuzzy select;
   raise threshold for noisy backgrounds) or a color for a uniform background, operation "add" to
   select several areas. gimp_sample_colors helps to pick the color.
5. gimp_modify_selection(action="invert") to select the subject, gimp_modify_selection_shape
   (feather, 1-2 px) to soften the edge.
6. gimp_add_layer_mask(fill="selection") on the layer: non-destructive, the pixels stay. Check
   with gimp_preview and refine the selection if needed.
7. gimp_export_image to {target} (PNG keeps the transparency), then gimp_close_image with
   discard_changes=true."""

    @mcp.prompt(
        name="photo-touch-up",
        title="Touch up a photo",
        description="Measure, then correct exposure, contrast and colors of a photo, and compare with the original.",
    )
    def photo_touch_up(path: str, output: str = "") -> str:
        target = output or f"a JPEG next to {path} named <name>-edited.jpg"
        return f"""Touch up the photo {path} with GIMP, measuring before and after each change.

1. gimp_open_image with path {path}, gimp_preview to look at it.
2. gimp_enable_toolsets with ["analysis", "color", "history"]. {CHECKPOINT}
3. gimp_histogram on the layer: clipped shadows or highlights, low contrast, color cast
   (unequal channel means on what should be neutral).
4. Corrections, as editable filters where possible (destructive=false):
   * exposure: gimp_exposure or gimp_levels (input_low/input_high from the histogram percentiles);
   * contrast: gimp_auto_adjust(method="stretch-contrast") or gimp_curves;
   * color cast: gimp_auto_adjust(method="white-balance") or gimp_color_balance;
   * dark areas: gimp_shadows_highlights.
5. gimp_histogram again and gimp_compare with the checkpoint to confirm what changed; keep the
   changes small and natural.
6. gimp_export_image to {target}, then gimp_close_image with discard_changes=true."""

    @mcp.prompt(
        name="batch-export",
        title="Convert a folder",
        description="Convert or resize every matching file of a folder with one batch recipe.",
    )
    def batch_export(directory: str, pattern: str = "*", format: str = "webp", output_directory: str = "") -> str:
        out = output_directory or f"{directory}/converted"
        return f"""Convert the files matching {pattern} in {directory} to {format} with GIMP.

1. gimp_enable_toolsets with ["batch", "formats"].
2. gimp_describe_file_format for {format} to see its export options (quality, lossless...).
3. Make sure the output directory {out} exists (the tools never create directories).
4. gimp_run_batch with directory={directory}, pattern={pattern}, output="{out}/{{stem}}.{format}",
   dry_run=true, and a recipe such as:
   [{{"tool": "gimp_export_as", "arguments": {{"image": "{{image}}", "path": "{{output}}"}}}}]
   Add steps before the export to resize (gimp_resize_image) or adjust each image.
   Check the planned files and outputs.
5. Run gimp_run_batch again with dry_run=false. Existing outputs are refused unless the user
   asked to replace them (overwrite=true). Report the files that failed and why."""

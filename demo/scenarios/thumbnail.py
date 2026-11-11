"""A 1280x720 video thumbnail from one photo: blurred backdrop, vignetted subject, editable title
re-typed after a change of mind, a badge added as one undo step then undone and redone with
checkpoints, saved as XCF, reopened and exported to PNG and JPEG."""

from __future__ import annotations

import json
from typing import Any

from demo.harness import Report, Scenario, Session, asset, find, image_size, pixel, tree

WIDTH, HEIGHT = 1280, 720
FIRST_TITLE = "Sunset over the Lake"
FINAL_TITLE = "Golden Hour at the Lake"


async def first_text(gimp: Session, image: str, text: str) -> dict[str, Any]:
    """Find a text layer by its text (layer names of new text layers are derived from the text)."""
    details = await gimp.call("gimp_inspect_image", image=image)
    stack = list(details["layers"])
    while stack:
        node = stack.pop(0)
        if node["kind"] == "text" and node["name"].startswith(text):
            return node
        stack.extend(node.get("children") or [])
    raise KeyError(text)


EXPECTED_TREE = [
    ["Title", "group", [
        ["Badge text", "text", []],
        ["Badge", "layer", []],
        ["Title text", "text", []],
        ["Title shadow", "text", []],
        ["Accent", "layer", []],
        ["Banner", "layer", []],
    ]],
    ["Subject", "group", [["Photo", "layer", []]]],
    ["Backdrop", "group", [["Backdrop photo", "layer", []]]],
    ["Background", "layer", []],
]  # fmt: skip


async def steps(gimp: Session, report: Report) -> None:
    out = gimp.out
    status = await gimp.call("gimp_status")
    report.check("connected to GIMP through MCP", status["connected"], f"GIMP {status['gimp_version']}")

    image = (await gimp.call("gimp_create_image", width=WIDTH, height=HEIGHT, fill="#0d0b1a"))["id"]
    backdrop = (await gimp.call("gimp_create_group", image=image, name="Backdrop"))["id"]
    subject = (await gimp.call("gimp_create_group", image=image, name="Subject"))["id"]
    title_group = (await gimp.call("gimp_create_group", image=image, name="Title"))["id"]

    # Backdrop: the source, scaled to cover the canvas, blurred and toned down.
    back = await gimp.call(
        "gimp_import_layer", image=image, path=str(asset("lake-sunset.png")), name="Backdrop photo", parent=backdrop
    )
    await gimp.call("gimp_scale_layer", item=back["id"], width=1280, height=800, anchor="top-left")
    await gimp.call("gimp_set_layer_offsets", item=back["id"], x=0, y=-40)
    await gimp.call("gimp_gaussian_blur", item=back["id"], radius=14)
    dim = await gimp.call("gimp_brightness_contrast", item=back["id"], brightness=-35, destructive=False)
    desat = await gimp.call("gimp_hue_saturation", item=back["id"], saturation=-30, destructive=False)
    report.check("backdrop corrections are editable filters", not dim["destructive"] and not desat["destructive"])
    filters_before = [f["operation"] for f in (await gimp.call("gimp_list_filters", item=back["id"]))["filters"]]
    await gimp.preview(image, "01-backdrop", "1. Blurred, darkened backdrop")

    # Subject: the sharp photo, framed by a feathered elliptical mask (vignette).
    photo = await gimp.call(
        "gimp_import_layer", image=image, path=str(asset("lake-sunset.png")), name="Photo", parent=subject
    )
    await gimp.call("gimp_scale_layer", item=photo["id"], width=880, height=550, anchor="top-left")
    await gimp.call("gimp_set_layer_offsets", item=photo["id"], x=200, y=20)
    await gimp.call("gimp_select_ellipse", image=image, x=210, y=30, width=860, height=530, feather=70)
    masked = await gimp.call("gimp_add_layer_mask", item=photo["id"], fill="selection")
    await gimp.call("gimp_modify_selection", image=image, action="none")
    report.check("vignette mask attached to the photo", masked["mask"] is not None)
    await gimp.preview(image, "02-subject", "2. Photo with a feathered vignette mask")

    # Title: banner, accent line, editable title and its blurred shadow.
    banner = await gimp.call("gimp_create_layer", image=image, name="Banner", parent=title_group)
    await gimp.call(
        "gimp_draw_shape",
        item=banner["id"],
        shape="rectangle",
        x=0,
        y=560,
        width=1280,
        height=160,
        fill_color="#000000",
        opacity=70,
    )
    accent = await gimp.call("gimp_create_layer", image=image, name="Accent", parent=title_group)
    await gimp.call("gimp_draw_path", item=accent["id"], points=[[440, 672], [840, 672]], width=5, color="#ffb347")
    shadow = await gimp.call(
        "gimp_create_text_layer",
        image=image,
        text=FIRST_TITLE,
        font="Sans-serif Bold",
        size=64,
        color="#000000",
        x=4,
        y=584,
        justify="center",
        box_width=1280,
        box_height=90,
        parent=title_group,
    )
    await gimp.call("gimp_set_layer_properties", item=shadow["id"], name="Title shadow", opacity=80)
    await gimp.call("gimp_gaussian_blur", item=shadow["id"], radius=4, destructive=False)
    title = await gimp.call(
        "gimp_create_text_layer",
        image=image,
        text=FIRST_TITLE,
        font="Sans-serif Bold",
        size=64,
        color="#ffffff",
        x=0,
        y=580,
        justify="center",
        box_width=1280,
        box_height=90,
        parent=title_group,
    )
    await gimp.call("gimp_set_layer_properties", item=title["id"], name="Title text")
    await gimp.preview(image, "03-title", f"3. Title '{FIRST_TITLE}'")

    # Change of mind: the title stays editable text, so it is simply re-typed.
    for item in (title["id"], shadow["id"]):
        await gimp.call("gimp_set_text", item=item, text=FINAL_TITLE)
    await gimp.call("gimp_set_text", item=title["id"], color="#fff3d6")
    props = await gimp.call("gimp_inspect_text", item=title["id"])
    report.check("title is still editable text after the edit", props["text"] == FINAL_TITLE, props["text"])
    await gimp.preview(image, "04-retitled", f"4. Title re-typed: '{FINAL_TITLE}'")

    # A badge, added as ONE undo step, then undone and redone with checkpoints
    # (GIMP gives plug-ins no undo/redo: checkpoints are the agent's undo).
    before = await gimp.call("gimp_create_checkpoint", image=image, label="before badge")
    await gimp.call("gimp_begin_undo_group", image=image, label="Add badge")
    badge = await gimp.call("gimp_create_layer", image=image, name="Badge", parent=title_group)
    await gimp.call(
        "gimp_draw_shape",
        item=badge["id"],
        shape="ellipse",
        x=1110,
        y=24,
        width=140,
        height=140,
        fill_color="#e63946",
        stroke_color="#ffffff",
        stroke_width=4,
    )
    await gimp.call(
        "gimp_create_text_layer",
        image=image,
        text="NEW",
        font="Sans-serif Bold",
        size=34,
        color="#ffffff",
        x=1110,
        y=72,
        justify="center",
        box_width=140,
        box_height=45,
        parent=title_group,
    )
    await gimp.call("gimp_set_layer_properties", item=(await first_text(gimp, image, "NEW"))["id"], name="Badge text")
    closed = await gimp.call("gimp_end_undo_group", image=image)
    report.check("badge changes grouped into one undo step", closed["depth"] == 0)
    after = await gimp.call("gimp_create_checkpoint", image=image, label="with badge")
    badge_png = await gimp.preview(image, "05-badge", "5. Badge added (one undo group)")

    undone = await gimp.call("gimp_restore_checkpoint", image=image, checkpoint=before["checkpoint"])
    image = undone["image"]
    undone_tree = tree(await gimp.call("gimp_inspect_image", image=image))
    report.check("undo (restore 'before badge') removes the badge", ["Badge", "layer", []] not in undone_tree[0][2])
    undone_png = await gimp.preview(image, "06-undo", "6. Undo: checkpoint 'before badge' restored")
    redone = await gimp.call("gimp_restore_checkpoint", image=image, checkpoint=after["checkpoint"])
    image = redone["image"]
    redo_png = await gimp.preview(image, "07-redo", "7. Redo: checkpoint 'with badge' restored")
    report.check(
        "undo/redo visibly change the badge area",
        pixel(badge_png, 590, 47) == pixel(redo_png, 590, 47) != pixel(undone_png, 590, 47),
        f"badge {pixel(badge_png, 590, 47)}, undone {pixel(undone_png, 590, 47)}",
    )
    for checkpoint in (before, after):
        await gimp.call("gimp_delete_checkpoint", checkpoint=checkpoint["checkpoint"])
    final_png = await gimp.preview(image, "08-final", "8. Final composition")

    details = await gimp.call("gimp_inspect_image", image=image)
    report.check("canvas is 1280x720", (details["width"], details["height"]) == (WIDTH, HEIGHT))
    report.check("layer tree matches the plan", tree(details) == EXPECTED_TREE, json.dumps(tree(details)))
    report.check("preview keeps the 16:9 proportions", image_size(final_png) == (640, 360))
    banner_pixel = pixel(final_png, 20, 330)
    report.check("banner darkens the bottom band", max(banner_pixel) < 80, str(banner_pixel))

    # Save the editable project, reopen it and compare.
    xcf = out / "thumbnail.xcf"
    await gimp.call("gimp_save_image", image=image, path=str(xcf), overwrite=True)
    await gimp.call("gimp_close_image", image=image)
    reopened = (await gimp.call("gimp_open_image", path=str(xcf)))["id"]
    again = await gimp.call("gimp_inspect_image", image=reopened)
    report.check("XCF reopens with the same layer tree", tree(again) == EXPECTED_TREE)
    title_again = await gimp.call("gimp_inspect_text", item=find(again, "Title text")["id"])
    report.check(
        "title is editable text in the reopened XCF",
        find(again, "Title text")["kind"] == "text" and title_again["text"] == FINAL_TITLE,
        f"{title_again['font']} {title_again['size']}{title_again['size_unit']} {title_again['color']}",
    )
    backdrop_filters = await gimp.call("gimp_list_filters", item=find(again, "Backdrop photo")["id"])
    filters_after = [f["operation"] for f in backdrop_filters["filters"]]
    report.check(
        "editable filters survive the XCF round trip",
        filters_after == filters_before
        and sorted(filters_after) == ["gimp:brightness-contrast", "gimp:hue-saturation"],
        json.dumps(filters_after),
    )

    # Final files.
    png, jpg = out / "thumbnail.png", out / "thumbnail.jpg"
    await gimp.call("gimp_export_image", image=reopened, path=str(png), overwrite=True)
    await gimp.call("gimp_export_image", image=reopened, path=str(jpg), overwrite=True, jpeg_options={"quality": 88})
    await gimp.call("gimp_close_image", image=reopened)
    for path in (png, jpg):
        size = image_size(path.read_bytes())
        report.check(
            f"{path.name} is a {WIDTH}x{HEIGHT} image", size == (WIDTH, HEIGHT), f"{path.stat().st_size} bytes"
        )


SCENARIO = Scenario(
    name="thumbnail",
    title="video thumbnail",
    toolsets=("files", "layers", "transform", "selection", "paint", "filters", "text", "history", "undo"),
    assets=("lake-sunset.png",),
    outputs=("thumbnail.xcf", "thumbnail.png", "thumbnail.jpg"),
    steps=steps,
    prompt=(
        "Open ~/inputs/lake-sunset.png in GIMP and turn it into a 1280x720 YouTube thumbnail: make the colors "
        'pop, darken the left third so text reads well, add a big bold title "GOLDEN HOUR" and a smaller '
        'subtitle "5 editing tricks", keep each edit on its own layer, then export ~/out/thumbnail.png.'
    ),
    agent_output="thumbnail.png",
)

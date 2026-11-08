# Demo: prepare a folder of photos for a website

Twenty photos (JPEG, some with an EXIF orientation, PNG and TIFF, of mixed sizes) and one corrupt file:
each is turned upright, fitted to 1600 px on its longest side, converted to sRGB, watermarked with the
logo at 60% in the bottom-right corner, stripped of its GPS position (the copyright stays) and exported
as `<name>-web.webp` and `<name>-web.jpg`, through MCP only.

```sh
uv run demo/run.py web-photo-batch      # scripted version, headless GIMP; report in demo/out/
CLAUDE_CODE_OAUTH_TOKEN=... demo/video/record.sh 0.6.0 web-photo-batch   # agent version, video
uv run evals/run.py web-photo-batch     # agent version, checked (evaluation suite)
```

| A stored photo (EXIF orientation 6) | Its web version |
|---|---|
| ![stored](web-photo-batch/previews/01-tower-stored.webp) | ![web](web-photo-batch/previews/02-tower-web.webp) |

## How

A batch recipe applies the same steps to every file, and today it cannot fit "the longest side" (both
dimensions are required, #150), nor turn a photo only when its EXIF says so. So each photo is first
read once (`gimp_open_image`, `gimp_inspect_image`, `gimp_get_metadata`: size and orientation), and
the photos are grouped by stored size and orientation: one `gimp_run_batch` per group, with
`gimp_rotate_image` (orientations 6 and 8), `gimp_resize_image`, `gimp_set_metadata` (GPS tags removed,
orientation reset), `gimp_set_color_profile` (convert to an sRGB ICC file: GIMP's built-in sRGB is not
embedded, #158), `gimp_import_layer` (the watermark, whose file carries the 60% opacity: a recipe
cannot change the layer it imported, #162), `gimp_export_as` (WebP, Exif kept) and `gimp_export_image`
(JPEG, Exif and profile kept). The corrupt file is in the first group: it is reported, the others go on.

## What is checked

The photos are drawn by code (CC0), each with a red marker in its top-left corner as it should be seen,
a copyright and a GPS position, so: every output exists with its longest side at 1600 px and the
marker top-left (upright); the watermark's pixel is a 60% mix of teal and the photo; the outputs have no
GPS position, the copyright, and an sRGB profile (read with Pillow); the corrupt file is the only
failure; the inputs' SHA-256 are unchanged. The [generated report](web-photo-batch/report.md) lists
every call and check.

# Demo: animated sticker

A looping sticker built from layers: a logo slides in from the left and fades in over 12 frames
(80 ms each, the last one held 1 s, each frame replacing the previous one), optimized, and exported as
GIF and animated WebP under a 500 KB budget, through MCP only.

```sh
uv run demo/run.py animated-sticker      # scripted version, headless GIMP; report in demo/out/
CLAUDE_CODE_OAUTH_TOKEN=... demo/video/record.sh 0.6.0 animated-sticker   # agent version, video
uv run evals/run.py animated-sticker     # agent version, checked (evaluation suite)
```

![last frame](animated-sticker/previews/sticker-last.webp)

## How

For each frame k: `gimp_add_frame` on top (filled with the background), `gimp_import_layer` (the logo
at x = 40 + 24k), `gimp_set_layer_properties` (opacity (k+1)/12), `gimp_merge_layers` down into the
frame, `gimp_set_frame` (name, duration, `replace`). Then `gimp_optimize_animation` (a new image) for
the GIF, and `gimp_export_animation` for both files.

## What is checked

The logo is drawn by code (CC0), so each frame's logo position and opacity are known. Read back with
Pillow (and the WebP's RIFF chunks for its durations): 12 frames, looping; 80 ms per frame and 1000 ms
for the last; in every frame the logo's pixel is the logo at that frame's opacity over the background
(mixed in linear light, as GIMP does) and the background is untouched before it; the left edge of the
logo moves by 24 px per frame; both files are under 500 KB. The
[generated report](animated-sticker/report.md) lists every call and check.

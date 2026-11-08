# Demo: print-ready A5 flyer

An A5 flyer laid out for print: 300 dpi, 3 mm bleed on each side (a 154×216 mm canvas, 1819×2551 px),
guides on the trim and on a 5 mm safe margin, a photo running into the bleed, the title and the text
inside the safe area; saved as XCF and exported as PDF and TIFF at print size, through MCP only.

```sh
uv run demo/run.py print-flyer      # scripted version, headless GIMP; report in demo/out/
CLAUDE_CODE_OAUTH_TOKEN=... demo/video/record.sh 0.6.0 print-flyer   # agent version, video
uv run evals/run.py print-flyer     # agent version, checked (evaluation suite)
```

![flyer](print-flyer/previews/flyer.webp)

| Measure | Millimetres | Pixels at 300 dpi |
|---|---|---|
| Canvas (A5 + bleed) | 154 × 216 | 1819 × 2551 |
| Bleed | 3 | 35 |
| Safe margin from the canvas edge | 3 + 5 | 94 |

## How

`gimp_create_image`, `gimp_set_print_size` (300 dpi), eight `gimp_add_guide`, the photo with
`gimp_import_layer`, `gimp_scale_layer` and `gimp_set_layer_offsets` (wider than the canvas, at the
top), two `gimp_create_text_layer` boxes inside the safe area, `gimp_save_image` (XCF), then
`gimp_flatten_image` (a TIFF export writes one page per layer: the printer needs the composite) and
`gimp_export_as` to PDF and TIFF.

## What is checked

Through MCP: the photo's layer reaches the left, top and right bleed edges, the title and body layers
lie inside the safe margins, the eight guides are where the specification puts them. In the files: the
PDF page is 154×216 mm (pypdf), the TIFF is 1819×2551 at 300 dpi with the photo up to its top and left
edges (Pillow), and the XCF keeps the eight guides (read from its guide property). The
[generated report](print-flyer/report.md) lists every call and check.

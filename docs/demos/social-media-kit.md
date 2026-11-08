# Demo: social media kit from one design

One design (a photo, a navy brand band with a red accent line, a logo and the headline "Golden Hour
Sale" in cream) adapted to four formats, each with guides on its safe area and the headline kept as
editable text, saved as XCF and exported as PNG, through MCP only.

```sh
uv run demo/run.py social-media-kit      # scripted version, headless GIMP; report in demo/out/
CLAUDE_CODE_OAUTH_TOKEN=... demo/video/record.sh 0.6.0 social-media-kit   # agent version, video
uv run evals/run.py social-media-kit     # agent version, checked (evaluation suite)
```

| Post 1080×1080 | Story 1080×1920 | Banner 1500×500 | Thumbnail 1280×720 |
|---|---|---|---|
| ![post](social-media-kit/previews/post.webp) | ![story](social-media-kit/previews/story.webp) | ![banner](social-media-kit/previews/banner.webp) | ![thumbnail](social-media-kit/previews/thumbnail.webp) |

| Format | Size | Safe margins (left, top, right, bottom) |
|---|---|---|
| Instagram post | 1080×1080 | 64 px |
| Story | 1080×1920 | 64, 250, 64, 250 |
| Banner | 1500×500 | 60 px |
| Video thumbnail | 1280×720 | 64 px |

## How

For each format: `gimp_create_image`, four `gimp_add_guide` on the safe area, the photo with
`gimp_import_layer`, `gimp_scale_layer` and `gimp_set_layer_offsets` to cover the canvas, the band and
its accent with `gimp_draw_shape`, the headline with `gimp_create_text_layer` (a text box inside the
safe area), the logo scaled into the top-right corner of the safe area, then `gimp_save_image` (XCF)
and `gimp_export_image` (PNG).

## What is checked

In each reopened XCF: the headline is a text layer with the expected text and font
(`gimp_inspect_text`), the four guides are at the safe-area positions, and the headline and logo
layers lie inside them. In each PNG, read with Pillow: the size, the brand colors (navy band, cream
text, red accent) and the logo's teal pixels inside the safe area; in each XCF file, the
`gimp-text-layer` parasite with the headline. The [generated report](social-media-kit/report.md) lists
every call and check.

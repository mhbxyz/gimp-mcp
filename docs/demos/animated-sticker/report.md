# gimp-mcp demo: animated sticker

Result: **PASS** — 10/10 checks, 74 MCP tool calls, 5.3 s.

Outputs: `logo.png`, `sticker.gif`, `sticker.webp`.

## Previews (from `gimp_preview`)

**The last frame (logo in place, fully opaque)**

![The last frame (logo in place, fully opaque)](previews/sticker-last.webp)

## Checks

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | 12 frames with their own timing and disposal | pass | [(80, 'replace'), (80, 'replace'), (80, 'replace')]... |
| 2 | sticker.gif has 12 frames and loops | pass | 12 frames, loop 0 |
| 3 | sticker.gif: 80 ms per frame, the last held 1 s | pass | [80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 1000] |
| 4 | sticker.gif: each frame shows the logo at its place and opacity | pass |  |
| 5 | sticker.gif is under 500 KB | pass | 6939 bytes |
| 6 | sticker.webp has 12 frames and loops | pass | 12 frames, loop 0 |
| 7 | sticker.webp: 80 ms per frame, the last held 1 s | pass | [80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 1000] |
| 8 | sticker.webp: each frame shows the logo at its place and opacity | pass |  |
| 9 | sticker.webp is under 500 KB | pass | 2992 bytes |
| 10 | the server listed only the scenario's toolsets (34 tools) | pass | files,layers,animation,compose |

## Tool calls

| # | Tool | Arguments | ms | Result |
|---|---|---|---|---|
| 1 | `gimp_enable_toolsets` | `{"toolsets": ["animation", "compose"]}` | 29 | ok |
| 2 | `gimp_create_image` | `{"width": 480, "height": 240, "fill": "#fdf6e3"}` | 69 | id=image:1@18dbcc30, name=[Untitled], width=480, height=240 |
| 3 | `gimp_inspect_image` | `{"image": "image:1@18dbcc30"}` | 15 | id=image:1@18dbcc30, name=[Untitled], width=480, height=240 |
| 4 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 1, "fill": "#fdf6e3"}` | 12 | ok |
| 5 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 133 | id=item:6@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=40, y=72 |
| 6 | `gimp_set_layer_properties` | `{"item": "item:6@18dbcc30", "opacity": 8}` | 14 | id=item:6@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=40, y=72 |
| 7 | `gimp_merge_layers` | `{"mode": "down", "item": "item:6@18dbcc30", "merge_type": "clip-to-bottom"}` | 34 | ok |
| 8 | `gimp_set_frame` | `{"item": "item:9@18dbcc30", "name": "Frame 1", "duration_ms": 80, "disposal": "replace"}` | 7 | ok |
| 9 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 2, "fill": "#fdf6e3"}` | 11 | ok |
| 10 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 127 | id=item:13@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=64, y=72 |
| 11 | `gimp_set_layer_properties` | `{"item": "item:13@18dbcc30", "opacity": 17}` | 11 | id=item:13@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=64, y=72 |
| 12 | `gimp_merge_layers` | `{"mode": "down", "item": "item:13@18dbcc30", "merge_type": "clip-to-bottom"}` | 21 | ok |
| 13 | `gimp_set_frame` | `{"item": "item:16@18dbcc30", "name": "Frame 2", "duration_ms": 80, "disposal": "replace"}` | 8 | ok |
| 14 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 3, "fill": "#fdf6e3"}` | 8 | ok |
| 15 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 139 | id=item:20@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=88, y=72 |
| 16 | `gimp_set_layer_properties` | `{"item": "item:20@18dbcc30", "opacity": 25}` | 4 | id=item:20@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=88, y=72 |
| 17 | `gimp_merge_layers` | `{"mode": "down", "item": "item:20@18dbcc30", "merge_type": "clip-to-bottom"}` | 14 | ok |
| 18 | `gimp_set_frame` | `{"item": "item:23@18dbcc30", "name": "Frame 3", "duration_ms": 80, "disposal": "replace"}` | 5 | ok |
| 19 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 4, "fill": "#fdf6e3"}` | 8 | ok |
| 20 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 131 | id=item:27@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=112, y=72 |
| 21 | `gimp_set_layer_properties` | `{"item": "item:27@18dbcc30", "opacity": 33}` | 7 | id=item:27@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=112, y=72 |
| 22 | `gimp_merge_layers` | `{"mode": "down", "item": "item:27@18dbcc30", "merge_type": "clip-to-bottom"}` | 11 | ok |
| 23 | `gimp_set_frame` | `{"item": "item:30@18dbcc30", "name": "Frame 4", "duration_ms": 80, "disposal": "replace"}` | 7 | ok |
| 24 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 5, "fill": "#fdf6e3"}` | 8 | ok |
| 25 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 117 | id=item:34@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=136, y=72 |
| 26 | `gimp_set_layer_properties` | `{"item": "item:34@18dbcc30", "opacity": 42}` | 4 | id=item:34@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=136, y=72 |
| 27 | `gimp_merge_layers` | `{"mode": "down", "item": "item:34@18dbcc30", "merge_type": "clip-to-bottom"}` | 5 | ok |
| 28 | `gimp_set_frame` | `{"item": "item:37@18dbcc30", "name": "Frame 5", "duration_ms": 80, "disposal": "replace"}` | 4 | ok |
| 29 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 6, "fill": "#fdf6e3"}` | 8 | ok |
| 30 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 118 | id=item:41@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=160, y=72 |
| 31 | `gimp_set_layer_properties` | `{"item": "item:41@18dbcc30", "opacity": 50}` | 3 | id=item:41@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=160, y=72 |
| 32 | `gimp_merge_layers` | `{"mode": "down", "item": "item:41@18dbcc30", "merge_type": "clip-to-bottom"}` | 5 | ok |
| 33 | `gimp_set_frame` | `{"item": "item:44@18dbcc30", "name": "Frame 6", "duration_ms": 80, "disposal": "replace"}` | 5 | ok |
| 34 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 7, "fill": "#fdf6e3"}` | 7 | ok |
| 35 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 119 | id=item:48@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=184, y=72 |
| 36 | `gimp_set_layer_properties` | `{"item": "item:48@18dbcc30", "opacity": 58}` | 5 | id=item:48@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=184, y=72 |
| 37 | `gimp_merge_layers` | `{"mode": "down", "item": "item:48@18dbcc30", "merge_type": "clip-to-bottom"}` | 5 | ok |
| 38 | `gimp_set_frame` | `{"item": "item:51@18dbcc30", "name": "Frame 7", "duration_ms": 80, "disposal": "replace"}` | 5 | ok |
| 39 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 8, "fill": "#fdf6e3"}` | 8 | ok |
| 40 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 111 | id=item:55@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=208, y=72 |
| 41 | `gimp_set_layer_properties` | `{"item": "item:55@18dbcc30", "opacity": 67}` | 6 | id=item:55@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=208, y=72 |
| 42 | `gimp_merge_layers` | `{"mode": "down", "item": "item:55@18dbcc30", "merge_type": "clip-to-bottom"}` | 8 | ok |
| 43 | `gimp_set_frame` | `{"item": "item:58@18dbcc30", "name": "Frame 8", "duration_ms": 80, "disposal": "replace"}` | 11 | ok |
| 44 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 9, "fill": "#fdf6e3"}` | 9 | ok |
| 45 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 101 | id=item:62@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=232, y=72 |
| 46 | `gimp_set_layer_properties` | `{"item": "item:62@18dbcc30", "opacity": 75}` | 5 | id=item:62@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=232, y=72 |
| 47 | `gimp_merge_layers` | `{"mode": "down", "item": "item:62@18dbcc30", "merge_type": "clip-to-bottom"}` | 5 | ok |
| 48 | `gimp_set_frame` | `{"item": "item:65@18dbcc30", "name": "Frame 9", "duration_ms": 80, "disposal": "replace"}` | 8 | ok |
| 49 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 10, "fill": "#fdf6e3"}` | 9 | ok |
| 50 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 110 | id=item:69@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=256, y=72 |
| 51 | `gimp_set_layer_properties` | `{"item": "item:69@18dbcc30", "opacity": 83}` | 8 | id=item:69@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=256, y=72 |
| 52 | `gimp_merge_layers` | `{"mode": "down", "item": "item:69@18dbcc30", "merge_type": "clip-to-bottom"}` | 6 | ok |
| 53 | `gimp_set_frame` | `{"item": "item:72@18dbcc30", "name": "Frame 10", "duration_ms": 80, "disposal": "replace"}` | 9 | ok |
| 54 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 11, "fill": "#fdf6e3"}` | 10 | ok |
| 55 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 164 | id=item:76@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=280, y=72 |
| 56 | `gimp_set_layer_properties` | `{"item": "item:76@18dbcc30", "opacity": 92}` | 8 | id=item:76@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=280, y=72 |
| 57 | `gimp_merge_layers` | `{"mode": "down", "item": "item:76@18dbcc30", "merge_type": "clip-to-bottom"}` | 7 | ok |
| 58 | `gimp_set_frame` | `{"item": "item:79@18dbcc30", "name": "Frame 11", "duration_ms": 80, "disposal": "replace"}` | 12 | ok |
| 59 | `gimp_add_frame` | `{"image": "image:1@18dbcc30", "index": 12, "fill": "#fdf6e3"}` | 9 | ok |
| 60 | `gimp_import_layer` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/logo.png", "name"...` | 131 | id=item:83@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=304, y=72 |
| 61 | `gimp_set_layer_properties` | `{"item": "item:83@18dbcc30", "opacity": 100}` | 5 | id=item:83@18dbcc30, name=Logo, kind=layer, width=96, height=96, x=304, y=72 |
| 62 | `gimp_merge_layers` | `{"mode": "down", "item": "item:83@18dbcc30", "merge_type": "clip-to-bottom"}` | 9 | ok |
| 63 | `gimp_set_frame` | `{"item": "item:86@18dbcc30", "name": "Frame 12", "duration_ms": 1000, "disposal": "replace"}` | 12 | ok |
| 64 | `gimp_delete_layer` | `{"item": "item:2@18dbcc30"}` | 5 | ok |
| 65 | `gimp_list_frames` | `{"image": "image:1@18dbcc30"}` | 12 | ok |
| 66 | `gimp_preview_frame` | `{"image": "image:1@18dbcc30", "index": 0, "max_size": 480}` | 67 | width=480, height=240 |
| 67 | `gimp_preview_frame` | `{"image": "image:1@18dbcc30", "index": 6, "max_size": 480}` | 29 | width=480, height=240 |
| 68 | `gimp_preview_frame` | `{"image": "image:1@18dbcc30", "index": 11, "max_size": 480}` | 30 | width=480, height=240 |
| 69 | `gimp_optimize_animation` | `{"image": "image:1@18dbcc30", "mode": "optimize"}` | 1521 | ok |
| 70 | `gimp_export_animation` | `{"image": "image:17@18dbcc30", "path": "demo/out/animated-sticker/sticker.gif", "l...` | 504 | path=demo/out/animated-sticker/sticker.gif, bytes=6939 |
| 71 | `gimp_export_animation` | `{"image": "image:1@18dbcc30", "path": "demo/out/animated-sticker/sticker.webp", "l...` | 140 | path=demo/out/animated-sticker/sticker.webp, bytes=2992 |
| 72 | `gimp_preview` | `{"image": "image:1@18dbcc30", "max_size": 480}` | 6 | 480x240 PNG, 1431 bytes |
| 73 | `gimp_close_image` | `{"image": "image:17@18dbcc30", "discard_changes": true}` | 4 | ok |
| 74 | `gimp_close_image` | `{"image": "image:1@18dbcc30", "discard_changes": true}` | 5 | ok |

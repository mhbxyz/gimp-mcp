# gimp-mcp demo: prepare a folder of photos for a website

Result: **PASS** — 10/10 checks, 104 MCP tool calls, 18.3 s.

Outputs: `logo.png`, `web/beach-web.webp`, `web/beach-web.jpg`.

## Previews (from `gimp_preview`)

**1. tower.jpg as stored (EXIF: turn it)**

![1. tower.jpg as stored (EXIF: turn it)](previews/01-tower-stored.webp)

**2. tower-web.webp: upright, 1600 px, watermarked**

![2. tower-web.webp: upright, 1600 px, watermarked](previews/02-tower-web.webp)

## Checks

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | every photo was read (size, orientation) | pass | 17 groups |
| 2 | the corrupt file is reported as failed, the others are done | pass | UNSUPPORTED_FORMAT; 20 ok |
| 3 | the input files are unchanged (SHA-256) | pass |  |
| 4 | every photo has a WebP and a JPEG, longest side 1600 px | pass | 40 files |
| 5 | each is upright as EXIF said (red marker top-left) | pass |  |
| 6 | the watermark is in the bottom-right corner at about 60% | pass |  |
| 7 | no GPS position in any export | pass |  |
| 8 | the copyright is kept in every export | pass |  |
| 9 | every export carries an sRGB profile | pass |  |
| 10 | the server listed only the scenario's toolsets (46 tools) | pass | files,layers,transform,batch,document,geometry,modes,formats |

## Tool calls

| # | Tool | Arguments | ms | Result |
|---|---|---|---|---|
| 1 | `gimp_enable_toolsets` | `{"toolsets": ["batch", "document", "geometry", "modes", "formats"]}` | 27 | ok |
| 2 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/beach.jpg"}` | 179 | id=image:1@fb5b4d13, name=[beach] (imported), width=3000, height=2000 |
| 3 | `gimp_inspect_image` | `{"image": "image:1@fb5b4d13"}` | 14 | id=image:1@fb5b4d13, name=[beach] (imported), width=3000, height=2000 |
| 4 | `gimp_get_metadata` | `{"image": "image:1@fb5b4d13"}` | 5 | ok |
| 5 | `gimp_close_image` | `{"image": "image:1@fb5b4d13"}` | 4 | ok |
| 6 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/boat.jpg"}` | 96 | id=image:2@fb5b4d13, name=[boat] (imported), width=1500, height=1000 |
| 7 | `gimp_inspect_image` | `{"image": "image:2@fb5b4d13"}` | 3 | id=image:2@fb5b4d13, name=[boat] (imported), width=1500, height=1000 |
| 8 | `gimp_get_metadata` | `{"image": "image:2@fb5b4d13"}` | 2 | ok |
| 9 | `gimp_close_image` | `{"image": "image:2@fb5b4d13"}` | 2 | ok |
| 10 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/bridge.png"}` | 115 | id=image:3@fb5b4d13, name=[bridge] (imported), width=2400, height=1600 |
| 11 | `gimp_inspect_image` | `{"image": "image:3@fb5b4d13"}` | 6 | id=image:3@fb5b4d13, name=[bridge] (imported), width=2400, height=1600 |
| 12 | `gimp_get_metadata` | `{"image": "image:3@fb5b4d13"}` | 3 | ok |
| 13 | `gimp_close_image` | `{"image": "image:3@fb5b4d13"}` | 3 | ok |
| 14 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/cafe.jpg"}` | 115 | id=image:4@fb5b4d13, name=[cafe] (imported), width=2000, height=2000 |
| 15 | `gimp_inspect_image` | `{"image": "image:4@fb5b4d13"}` | 6 | id=image:4@fb5b4d13, name=[cafe] (imported), width=2000, height=2000 |
| 16 | `gimp_get_metadata` | `{"image": "image:4@fb5b4d13"}` | 2 | ok |
| 17 | `gimp_close_image` | `{"image": "image:4@fb5b4d13"}` | 2 | ok |
| 18 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/church.jpg"}` | 115 | id=image:5@fb5b4d13, name=[church] (imported), width=2100, height=1400 |
| 19 | `gimp_inspect_image` | `{"image": "image:5@fb5b4d13"}` | 5 | id=image:5@fb5b4d13, name=[church] (imported), width=2100, height=1400 |
| 20 | `gimp_get_metadata` | `{"image": "image:5@fb5b4d13"}` | 2 | ok |
| 21 | `gimp_close_image` | `{"image": "image:5@fb5b4d13"}` | 3 | ok |
| 22 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/dog.jpg"}` | 111 | id=image:6@fb5b4d13, name=[dog] (imported), width=1800, height=1800 |
| 23 | `gimp_inspect_image` | `{"image": "image:6@fb5b4d13"}` | 5 | id=image:6@fb5b4d13, name=[dog] (imported), width=1800, height=1800 |
| 24 | `gimp_get_metadata` | `{"image": "image:6@fb5b4d13"}` | 2 | ok |
| 25 | `gimp_close_image` | `{"image": "image:6@fb5b4d13"}` | 2 | ok |
| 26 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/door.jpg"}` | 107 | id=image:7@fb5b4d13, name=[door] (imported), width=2400, height=1600 |
| 27 | `gimp_inspect_image` | `{"image": "image:7@fb5b4d13"}` | 7 | id=image:7@fb5b4d13, name=[door] (imported), width=2400, height=1600 |
| 28 | `gimp_get_metadata` | `{"image": "image:7@fb5b4d13"}` | 3 | ok |
| 29 | `gimp_close_image` | `{"image": "image:7@fb5b4d13"}` | 3 | ok |
| 30 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/fountain.tif"}` | 108 | id=image:8@fb5b4d13, name=[fountain] (imported), width=1000, height=1500 |
| 31 | `gimp_inspect_image` | `{"image": "image:8@fb5b4d13"}` | 5 | id=image:8@fb5b4d13, name=[fountain] (imported), width=1000, height=1500 |
| 32 | `gimp_get_metadata` | `{"image": "image:8@fb5b4d13"}` | 2 | ok |
| 33 | `gimp_close_image` | `{"image": "image:8@fb5b4d13"}` | 2 | ok |
| 34 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/garden.png"}` | 111 | id=image:9@fb5b4d13, name=[garden] (imported), width=1600, height=2400 |
| 35 | `gimp_inspect_image` | `{"image": "image:9@fb5b4d13"}` | 5 | id=image:9@fb5b4d13, name=[garden] (imported), width=1600, height=2400 |
| 36 | `gimp_get_metadata` | `{"image": "image:9@fb5b4d13"}` | 2 | ok |
| 37 | `gimp_close_image` | `{"image": "image:9@fb5b4d13"}` | 3 | ok |
| 38 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/harbor.jpg"}` | 122 | id=image:10@fb5b4d13, name=[harbor] (imported), width=2400, height=1600 |
| 39 | `gimp_inspect_image` | `{"image": "image:10@fb5b4d13"}` | 6 | id=image:10@fb5b4d13, name=[harbor] (imported), width=2400, height=1600 |
| 40 | `gimp_get_metadata` | `{"image": "image:10@fb5b4d13"}` | 2 | ok |
| 41 | `gimp_close_image` | `{"image": "image:10@fb5b4d13"}` | 2 | ok |
| 42 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/lamp.tif"}` | 128 | id=image:11@fb5b4d13, name=[lamp] (imported), width=1200, height=1800 |
| 43 | `gimp_inspect_image` | `{"image": "image:11@fb5b4d13"}` | 4 | id=image:11@fb5b4d13, name=[lamp] (imported), width=1200, height=1800 |
| 44 | `gimp_get_metadata` | `{"image": "image:11@fb5b4d13"}` | 3 | ok |
| 45 | `gimp_close_image` | `{"image": "image:11@fb5b4d13"}` | 3 | ok |
| 46 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/market.jpg"}` | 124 | id=image:12@fb5b4d13, name=[market] (imported), width=1800, height=1200 |
| 47 | `gimp_inspect_image` | `{"image": "image:12@fb5b4d13"}` | 5 | id=image:12@fb5b4d13, name=[market] (imported), width=1800, height=1200 |
| 48 | `gimp_get_metadata` | `{"image": "image:12@fb5b4d13"}` | 3 | ok |
| 49 | `gimp_close_image` | `{"image": "image:12@fb5b4d13"}` | 3 | ok |
| 50 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/plaza.jpg"}` | 141 | id=image:13@fb5b4d13, name=[plaza] (imported), width=2100, height=1400 |
| 51 | `gimp_inspect_image` | `{"image": "image:13@fb5b4d13"}` | 4 | id=image:13@fb5b4d13, name=[plaza] (imported), width=2100, height=1400 |
| 52 | `gimp_get_metadata` | `{"image": "image:13@fb5b4d13"}` | 3 | ok |
| 53 | `gimp_close_image` | `{"image": "image:13@fb5b4d13"}` | 3 | ok |
| 54 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/river.tif"}` | 149 | id=image:14@fb5b4d13, name=[river] (imported), width=3000, height=2000 |
| 55 | `gimp_inspect_image` | `{"image": "image:14@fb5b4d13"}` | 6 | id=image:14@fb5b4d13, name=[river] (imported), width=3000, height=2000 |
| 56 | `gimp_get_metadata` | `{"image": "image:14@fb5b4d13"}` | 2 | ok |
| 57 | `gimp_close_image` | `{"image": "image:14@fb5b4d13"}` | 2 | ok |
| 58 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/roof.png"}` | 110 | id=image:15@fb5b4d13, name=[roof] (imported), width=2700, height=1800 |
| 59 | `gimp_inspect_image` | `{"image": "image:15@fb5b4d13"}` | 11 | id=image:15@fb5b4d13, name=[roof] (imported), width=2700, height=1800 |
| 60 | `gimp_get_metadata` | `{"image": "image:15@fb5b4d13"}` | 3 | ok |
| 61 | `gimp_close_image` | `{"image": "image:15@fb5b4d13"}` | 4 | ok |
| 62 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/stairs.jpg"}` | 103 | id=image:16@fb5b4d13, name=[stairs] (imported), width=1800, height=1200 |
| 63 | `gimp_inspect_image` | `{"image": "image:16@fb5b4d13"}` | 4 | id=image:16@fb5b4d13, name=[stairs] (imported), width=1800, height=1200 |
| 64 | `gimp_get_metadata` | `{"image": "image:16@fb5b4d13"}` | 2 | ok |
| 65 | `gimp_close_image` | `{"image": "image:16@fb5b4d13"}` | 2 | ok |
| 66 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/street.tif"}` | 117 | id=image:17@fb5b4d13, name=[street] (imported), width=1800, height=1200 |
| 67 | `gimp_inspect_image` | `{"image": "image:17@fb5b4d13"}` | 5 | id=image:17@fb5b4d13, name=[street] (imported), width=1800, height=1200 |
| 68 | `gimp_get_metadata` | `{"image": "image:17@fb5b4d13"}` | 2 | ok |
| 69 | `gimp_close_image` | `{"image": "image:17@fb5b4d13"}` | 2 | ok |
| 70 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/tiles.png"}` | 109 | id=image:18@fb5b4d13, name=[tiles] (imported), width=1500, height=1500 |
| 71 | `gimp_inspect_image` | `{"image": "image:18@fb5b4d13"}` | 5 | id=image:18@fb5b4d13, name=[tiles] (imported), width=1500, height=1500 |
| 72 | `gimp_get_metadata` | `{"image": "image:18@fb5b4d13"}` | 2 | ok |
| 73 | `gimp_close_image` | `{"image": "image:18@fb5b4d13"}` | 3 | ok |
| 74 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/tower.jpg"}` | 127 | id=image:19@fb5b4d13, name=[tower] (imported), width=3000, height=2000 |
| 75 | `gimp_inspect_image` | `{"image": "image:19@fb5b4d13"}` | 6 | id=image:19@fb5b4d13, name=[tower] (imported), width=3000, height=2000 |
| 76 | `gimp_get_metadata` | `{"image": "image:19@fb5b4d13"}` | 2 | ok |
| 77 | `gimp_close_image` | `{"image": "image:19@fb5b4d13"}` | 2 | ok |
| 78 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/train.jpg"}` | 108 | id=image:20@fb5b4d13, name=[train] (imported), width=1200, height=800 |
| 79 | `gimp_inspect_image` | `{"image": "image:20@fb5b4d13"}` | 10 | id=image:20@fb5b4d13, name=[train] (imported), width=1200, height=800 |
| 80 | `gimp_get_metadata` | `{"image": "image:20@fb5b4d13"}` | 3 | ok |
| 81 | `gimp_close_image` | `{"image": "image:20@fb5b4d13"}` | 4 | ok |
| 82 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/fountain.tif", "/home/mhbxyz/Projects/...` | 861 | ok |
| 83 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/train.jpg"], "recipe": [{"tool": "gimp...` | 677 | ok |
| 84 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/lamp.tif"], "recipe": [{"tool": "gimp_...` | 659 | ok |
| 85 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/boat.jpg"], "recipe": [{"tool": "gimp_...` | 656 | ok |
| 86 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/tiles.png"], "recipe": [{"tool": "gimp...` | 820 | ok |
| 87 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/garden.png"], "recipe": [{"tool": "gim...` | 707 | ok |
| 88 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/market.jpg", "/home/mhbxyz/Projects/gi...` | 1321 | ok |
| 89 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/stairs.jpg"], "recipe": [{"tool": "gim...` | 641 | ok |
| 90 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/dog.jpg"], "recipe": [{"tool": "gimp_r...` | 725 | ok |
| 91 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/cafe.jpg"], "recipe": [{"tool": "gimp_...` | 725 | ok |
| 92 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/plaza.jpg"], "recipe": [{"tool": "gimp...` | 659 | ok |
| 93 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/church.jpg"], "recipe": [{"tool": "gim...` | 756 | ok |
| 94 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/bridge.png", "/home/mhbxyz/Projects/gi...` | 1306 | ok |
| 95 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/door.jpg"], "recipe": [{"tool": "gimp_...` | 644 | ok |
| 96 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/roof.png"], "recipe": [{"tool": "gimp_...` | 599 | ok |
| 97 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/beach.jpg", "/home/mhbxyz/Projects/gim...` | 1345 | ok |
| 98 | `gimp_run_batch` | `{"files": ["demo/out/web-photo-batch/photos/tower.jpg"], "recipe": [{"tool": "gimp...` | 663 | ok |
| 99 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/photos/tower.jpg"}` | 120 | id=image:101@fb5b4d13, name=[tower] (imported), width=3000, height=2000 |
| 100 | `gimp_preview` | `{"image": "image:101@fb5b4d13", "max_size": 480}` | 39 | 480x320 PNG, 1845 bytes |
| 101 | `gimp_close_image` | `{"image": "image:101@fb5b4d13"}` | 3 | ok |
| 102 | `gimp_open_image` | `{"path": "demo/out/web-photo-batch/web/tower-web.webp"}` | 104 | id=image:102@fb5b4d13, name=[tower-web] (imported), width=1067, height=1600 |
| 103 | `gimp_preview` | `{"image": "image:102@fb5b4d13", "max_size": 480}` | 13 | 320x480 PNG, 19401 bytes |
| 104 | `gimp_close_image` | `{"image": "image:102@fb5b4d13"}` | 2 | ok |

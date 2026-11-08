# gimp-mcp demo: photo montage with sky replacement

Result: **PASS** — 9/9 checks, 21 MCP tool calls, 2.3 s.

Outputs: `landscape.png`, `sky.png`, `montage.xcf`, `montage.png`.

## Previews (from `gimp_preview`)

**1. The dull sky**

![1. The dull sky](previews/01-before.webp)

**2. New sky masked in, foreground warmed**

![2. New sky masked in, foreground warmed](previews/02-after.webp)

## Checks

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | the color grade is an editable filter | pass |  |
| 2 | the landscape keeps its color balance as a filter in the image | pass | ['gimp:color-balance'] |
| 3 | the reopened XCF keeps the editable color balance | pass | ['gimp:color-balance'] |
| 4 | montage.png has the landscape's size | pass | (1200, 800) |
| 5 | sky pixels come from the new sky (within 8) | pass | worst 0 |
| 6 | foreground pixels change only by a bounded color grade (at most 40, not none) | pass | largest 37, mean 25.5 |
| 7 | the horizon transition is narrower than 6 px (no gray halo, no sky on the ground) | pass | gray above at x=[], sky below at x=[] |
| 8 | the XCF keeps the new sky as a masked layer over the landscape | pass | [('New sky', True), ('Landscape', False)] |
| 9 | the server listed only the scenario's toolsets (48 tools) | pass | files,layers,selection,filters,channels,color |

## Tool calls

| # | Tool | Arguments | ms | Result |
|---|---|---|---|---|
| 1 | `gimp_open_image` | `{"path": "demo/out/sky-replacement/landscape.png"}` | 199 | id=image:1@2affa010, name=[landscape] (imported), width=1200, height=800 |
| 2 | `gimp_inspect_image` | `{"image": "image:1@2affa010"}` | 16 | id=image:1@2affa010, name=[landscape] (imported), width=1200, height=800 |
| 3 | `gimp_set_layer_properties` | `{"item": "item:2@2affa010", "name": "Landscape"}` | 11 | id=item:2@2affa010, name=Landscape, kind=layer, width=1200, height=800, x=0, y=0 |
| 4 | `gimp_enable_toolsets` | `{"toolsets": ["channels", "color"]}` | 3 | ok |
| 5 | `gimp_preview` | `{"image": "image:1@2affa010", "max_size": 600}` | 75 | 600x400 PNG, 124728 bytes |
| 6 | `gimp_select_by_color` | `{"image": "image:1@2affa010", "point": [10, 10], "item": "item:2@2affa010", "threshold": 24}` | 67 | ok |
| 7 | `gimp_modify_selection_shape` | `{"image": "image:1@2affa010", "action": "grow", "amount": 1}` | 14 | ok |
| 8 | `gimp_modify_selection_shape` | `{"image": "image:1@2affa010", "action": "feather", "amount": 1.5}` | 16 | ok |
| 9 | `gimp_import_layer` | `{"image": "image:1@2affa010", "path": "demo/out/sky-replacement/sky.png", "name": ...` | 113 | id=item:5@2affa010, name=New sky, kind=layer, width=1200, height=800, x=0, y=0 |
| 10 | `gimp_add_layer_mask` | `{"item": "item:5@2affa010", "fill": "selection"}` | 17 | id=item:5@2affa010, name=New sky, kind=layer, width=1200, height=800, x=0, y=0 |
| 11 | `gimp_modify_selection` | `{"image": "image:1@2affa010", "action": "none"}` | 5 | ok |
| 12 | `gimp_color_balance` | `{"item": "item:2@2affa010", "range": "midtones", "cyan_red": 18, "yellow_blue": -12, "preserve_luminosity": true, "de...` | 8 | destructive=False, filter=filter:1@2affa010 |
| 13 | `gimp_preview` | `{"image": "image:1@2affa010", "max_size": 600}` | 64 | 600x400 PNG, 150387 bytes |
| 14 | `gimp_save_image` | `{"image": "image:1@2affa010", "path": "demo/out/sky-replacement/montage.xcf", "ove...` | 28 | bytes=1392562 |
| 15 | `gimp_export_image` | `{"image": "image:1@2affa010", "path": "demo/out/sky-replacement/montage.png", "ove...` | 302 | width=1200, height=800, path=demo/out/sky-replacement/montage.png, bytes=641816 |
| 16 | `gimp_list_filters` | `{"item": "item:2@2affa010"}` | 4 | ok |
| 17 | `gimp_close_image` | `{"image": "image:1@2affa010"}` | 4 | ok |
| 18 | `gimp_open_image` | `{"path": "demo/out/sky-replacement/montage.xcf"}` | 38 | id=image:4@2affa010, name=montage.xcf, width=1200, height=800 |
| 19 | `gimp_inspect_image` | `{"image": "image:4@2affa010"}` | 26 | id=image:4@2affa010, name=montage.xcf, width=1200, height=800 |
| 20 | `gimp_list_filters` | `{"item": "item:22@2affa010"}` | 2 | ok |
| 21 | `gimp_close_image` | `{"image": "image:4@2affa010"}` | 5 | ok |

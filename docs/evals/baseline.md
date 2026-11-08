# gimp-mcp agent evaluation

**19/24 tasks passed** — gimp-mcp 0.5.0 (checkout), model claude-sonnet-5-5, 2026-11-08. Default toolsets; the agent enables others itself.

Updated since: old-photo-restoration, product-cutout and social-media-kit on 2026-11-08; screenshot-annotation on 2026-11-08; web-photo-batch on 2026-11-08; animated-sticker on 2026-11-08 (each task's package and date are in the JSON).

| Task | Result | Tool calls | Errors returned | Duration | Tokens in / out (cache read) |
|---|---|---|---|---|---|
| `resize-export` | pass | 3 | 0 | 10.8 s | 10 / 748 (69709) |
| `crop-quadrant` | pass | 3 | 0 | 10.3 s | 10 / 658 (64946) |
| `text-title` | pass | 5 | 0 | 15.8 s | 12 / 951 (88843) |
| `logo-overlay` | pass | 5 | 0 | 16.7 s | 12 / 820 (85574) |
| `rotate` | pass | 7 | 0 | 26.1 s | 18 / 1302 (130496) |
| `red-rectangle` | pass | 5 | 0 | 22.2 s | 14 / 1059 (98353) |
| `blur` | pass | 4 | 0 | 12.7 s | 10 / 659 (65633) |
| `darken` | **FAIL** | 4 | 0 | 13.9 s | 12 / 658 (80047) |
| `white-border` | pass | 3 | 0 | 15.6 s | 10 / 863 (67665) |
| `undo` | pass | 7 | 0 | 20.8 s | 16 / 1091 (118566) |
| `grayscale` | pass | 4 | 0 | 20.4 s | 12 / 824 (79705) |
| `invert` | pass | 7 | 1 | 32.9 s | 18 / 1094 (143909) |
| `batch-thumbnails` | pass | 16 | 0 | 36.6 s | 22 / 2536 (193961) |
| `animated-gif` | pass | 8 | 0 | 35.8 s | 16 / 1767 (136380) |
| `lossless-webp` | **FAIL** | 0 | 0 | 16.3 s | 8 / 703 (47571) |
| `indexed-4-colors` | pass | 6 | 1 | 29.9 s | 16 / 1042 (123861) |
| `dominant-color` | pass | 9 | 1 | 21.6 s | 16 / 1147 (123024) |
| `print-resolution` | pass | 5 | 0 | 20.8 s | 14 / 926 (113082) |
| `old-photo-restoration` | pass | 31 | 0 | 76.0 s | 48 / 8101 (797084) |
| `product-cutout` | **FAIL** | 52 | 6 | 89.0 s | 60 / 9789 (890864) |
| `social-media-kit` | pass | 74 | 0 | 88.4 s | 40 / 12850 (663588) |
| `screenshot-annotation` | **FAIL** | 36 | 0 | 76.3 s | 38 / 8628 (492658) |
| `web-photo-batch` | **FAIL** | 80 | 2 | 145.8 s | 68 / 16407 (1214075) |
| `animated-sticker` | pass | 87 | 4 | 95.8 s | 52 / 12380 (769104) |

## Details

### `resize-export`

* pass: the session finished (success)
* pass: photo-600.jpg exists and is an image
* pass: photo-600.jpg is JPEG (JPEG)
* pass: photo-600.jpg is 600x400 (600x400)
* pass: the gradient is kept, not cropped
* gimp tools: gimp_open_image, gimp_resize_image, gimp_export_image
* other tools tried: ToolSearch

### `crop-quadrant`

* pass: the session finished (success)
* pass: green.png exists and is an image
* pass: green.png is PNG (PNG)
* pass: green.png is 200x200 (200x200)
* pass: only the green quadrant
* gimp tools: gimp_open_image, gimp_crop_image, gimp_export_image
* other tools tried: ToolSearch

### `text-title`

* pass: the session finished (success)
* pass: hello.xcf is a GIMP project
* pass: hello.png exists and is an image
* pass: hello.png is PNG (PNG)
* pass: hello.png is 800x200 (800x200)
* pass: dark text in the middle, white corners (11306 dark pixels, corners [255, 255, 255, 255])
* gimp tools: gimp_create_image, gimp_create_text_layer, gimp_set_layer_offsets, gimp_save_image, gimp_export_image
* other tools tried: ToolSearch

### `logo-overlay`

* pass: the session finished (success)
* pass: branded.png exists and is an image
* pass: branded.png is PNG (PNG)
* pass: branded.png is 1200x800 (1200x800)
* pass: logo at 50% in the bottom-right corner only
* gimp tools: gimp_open_image, gimp_import_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_export_image
* other tools tried: ToolSearch

### `rotate`

* pass: the session finished (success)
* pass: rotated.png exists and is an image
* pass: rotated.png is PNG (PNG)
* pass: rotated.png is 200x300 (200x300)
* pass: rotated clockwise (black half on top)
* gimp tools: gimp_open_image, gimp_inspect_image, gimp_rotate_layer, gimp_inspect_image, gimp_resize_canvas, gimp_set_layer_offsets, gimp_export_image
* other tools tried: Bash, ToolSearch, ToolSearch

### `red-rectangle`

* pass: the session finished (success)
* pass: rect.png exists and is an image
* pass: rect.png is PNG (PNG)
* pass: rect.png is 400x300 (400x300)
* pass: red rectangle at x 100-300, y 50-150 on white
* gimp tools: gimp_create_image, gimp_select_rectangle, gimp_inspect_image, gimp_fill, gimp_export_image
* other tools tried: Bash, ToolSearch

### `blur`

* pass: the session finished (success)
* pass: blurred.png exists and is an image
* pass: blurred.png is PNG (PNG)
* pass: blurred.png is 256x256 (256x256)
* pass: the checkerboard is blurred (contrast down, average kept) (mean 188, std dev 2 (input 128, 128; 188 is the linear-light average))
* gimp tools: gimp_open_image, gimp_inspect_image, gimp_gaussian_blur, gimp_export_image
* other tools tried: ToolSearch

### `darken`

* pass: the session finished (success)
* pass: darker.png exists and is an image
* pass: darker.png is PNG (PNG)
* pass: darker.png is 300x200 (300x200)
* **FAIL**: about 30% darker (mean between 60 and 110, input 128) (mean 119)
* gimp tools: gimp_open_image, gimp_inspect_image, gimp_brightness_contrast, gimp_export_image
* other tools tried: ToolSearch

### `white-border`

* pass: the session finished (success)
* pass: framed.png exists and is an image
* pass: framed.png is PNG (PNG)
* pass: framed.png is 240x140 (240x140)
* pass: a 20 px white border around the unchanged image
* gimp tools: gimp_open_image, gimp_resize_canvas, gimp_export_image
* other tools tried: ToolSearch

### `undo`

* pass: the session finished (success)
* pass: step1-blurred.png exists and is an image
* pass: step1-blurred.png is PNG (PNG)
* pass: step1-blurred.png is 256x256 (256x256)
* pass: step2-restored.png exists and is an image
* pass: step2-restored.png is PNG (PNG)
* pass: step2-restored.png is 256x256 (256x256)
* pass: blurred, then exactly restored (blurred std dev 2; restored (0, 0, 0), (255, 255, 255))
* gimp tools: gimp_open_image, gimp_inspect_image, gimp_create_checkpoint, gimp_gaussian_blur, gimp_export_image, gimp_remove_filter, gimp_export_image
* other tools tried: ToolSearch

### `grayscale`

* pass: the session finished (success)
* pass: gray.png exists and is an image
* pass: gray.png is PNG (PNG)
* pass: gray.png is 400x100 (400x100)
* pass: gray tones only, bars still distinct ([(125, 125, 125), (105, 105, 105), (120, 120, 120), (140, 140, 140)])
* gimp tools: gimp_open_image, gimp_inspect_image, gimp_hue_saturation, gimp_export_image
* other tools tried: Bash, ToolSearch

### `invert`

* pass: the session finished (success)
* pass: inverted.png exists and is an image
* pass: inverted.png is PNG (PNG)
* pass: inverted.png is 400x400 (400x400)
* pass: every color inverted
* error returned: `gimp_invert: Error executing tool gimp_invert: 1 validation error for gimp_invertArguments
item
  Field required [type=missing, input_value={'image': 'image:1@4ff4da95'}, input_type=dict]
    For further informati`
* gimp tools: gimp_open_image, gimp_list_toolsets, gimp_enable_toolsets, gimp_invert, gimp_inspect_image, gimp_invert, gimp_export_image
* other tools tried: Bash, ToolSearch

### `batch-thumbnails`

* pass: the session finished (success)
* pass: a.jpg exists and is an image
* pass: a.jpg is JPEG (JPEG)
* pass: a.jpg is 200x150 (200x150)
* pass: a.jpg keeps its color
* pass: b.jpg exists and is an image
* pass: b.jpg is JPEG (JPEG)
* pass: b.jpg is 200x150 (200x150)
* pass: b.jpg keeps its color
* pass: c.jpg exists and is an image
* pass: c.jpg is JPEG (JPEG)
* pass: c.jpg is 200x150 (200x150)
* pass: c.jpg keeps its color
* pass: only the three JPEGs in ~/out/batch (['a.jpg', 'b.jpg', 'c.jpg'])
* gimp tools: gimp_status, gimp_list_toolsets, gimp_enable_toolsets, gimp_run_batch, gimp_open_image, gimp_open_image, gimp_open_image, gimp_resize_image, gimp_resize_image, gimp_resize_image, gimp_export_image, gimp_export_image, gimp_export_image, gimp_close_image, gimp_close_image, gimp_close_image
* other tools tried: Bash, ToolSearch, ListMcpResourcesTool, ToolSearch

### `animated-gif`

* pass: the session finished (success)
* pass: blink.gif is an animated GIF of 100x100 (GIF (100, 100))
* pass: 3 frames: red, green, blue ([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
* pass: 500 ms per frame ([500, 500, 500])
* pass: loops forever (0)
* gimp tools: gimp_list_toolsets, gimp_enable_toolsets, gimp_create_image, gimp_add_frame, gimp_add_frame, gimp_list_frames, gimp_set_frame, gimp_export_animation
* other tools tried: Bash, ToolSearch, ToolSearch

### `lossless-webp`

* pass: the session finished (success)
* **FAIL**: photo.webp exists and is an image
* **FAIL**: lossless: pixels identical to the source (no image of the right size)
* gimp tools: none
* other tools tried: Bash, ToolSearch, ToolSearch

### `indexed-4-colors`

* pass: the session finished (success)
* pass: indexed.png exists and is an image
* pass: indexed.png is PNG (PNG)
* pass: indexed.png is 400x100 (400x100)
* pass: indexed, at most 4 colors (mode P, 4 colors)
* error returned: `gimp_convert_mode: Error executing tool gimp_convert_mode: 2 validation errors for gimp_convert_modeArguments
image
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit http`
* gimp tools: gimp_list_toolsets, gimp_open_image, gimp_enable_toolsets, gimp_convert_mode, gimp_convert_mode, gimp_export_image
* other tools tried: Bash, ToolSearch

### `dominant-color`

* pass: the session finished (success)
* pass: the answer gives the dominant color's hex code (#e63946) (#e63946, #ffffff)
* error returned: `gimp_sample_colors: Error executing tool gimp_sample_colors: 2 validation errors for gimp_sample_colorsArguments
target
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit h`
* gimp tools: gimp_open_image, gimp_list_toolsets, gimp_enable_toolsets, gimp_dominant_colors, gimp_inspect_image, gimp_dominant_colors, gimp_sample_colors, gimp_sample_colors, gimp_histogram
* other tools tried: ToolSearch, ToolSearch

### `print-resolution`

* pass: the session finished (success)
* pass: print.png exists and is an image
* pass: print.png is PNG (PNG)
* pass: print.png is 1200x800 (1200x800)
* pass: the PNG says 300 dpi ((299.9994, 299.9994))
* gimp tools: gimp_open_image, gimp_list_toolsets, gimp_enable_toolsets, gimp_set_print_size, gimp_export_image
* other tools tried: ToolSearch, ToolSearch

### `old-photo-restoration`

* pass: the session finished (success)
* pass: restored-print.tif is a 16-bit TIFF ((16, 16, 16))
* pass: the TIFF says 300 dpi ((300.0, 300.0))
* pass: restored-web.jpg is an image (1181x732)
* pass: the sky's color bands are level (under 0.5° measured) (-0.17°)
* pass: no scanner bed remains along the edges (0 white)
* pass: full contrast again (1%-99%: <=30 and >=225) (22-229)
* pass: the output is the print, straight (aligned within 12/255) (mean difference 3.7 at offset 8,8)
* pass: every dust spot has the clean print's color again (within 40) (worst 13/255 over 14)
* gimp tools: gimp_open_image, gimp_list_toolsets, gimp_enable_toolsets, gimp_preview, gimp_inspect_image, gimp_convert_precision, gimp_rotate_layer, gimp_preview, gimp_crop_image, gimp_preview, gimp_select_by_color, gimp_select_by_color, gimp_modify_selection_shape, gimp_describe_filter_operation, gimp_apply_filter, gimp_modify_selection, gimp_preview, gimp_apply_filter, gimp_histogram, gimp_levels, gimp_preview, gimp_preview_region, gimp_describe_filter_operation, gimp_apply_filter, gimp_preview_region, gimp_set_print_size, gimp_enable_toolsets, gimp_export_as, gimp_export_image, gimp_set_alpha_channel, gimp_export_as
* other tools tried: Bash, ToolSearch, ToolSearch, ToolSearch, ToolSearch, ToolSearch, ToolSearch

### `product-cutout`

* pass: the session finished (success)
* **FAIL**: product-2000.jpg is 2000x2000 with an sRGB profile ((2000, 2000), profile none)
* **FAIL**: product-2000.webp is 2000x2000 with an sRGB profile ((2000, 2000), profile none)
* **FAIL**: product-800.jpg is 800x800 with an sRGB profile ((800, 800), profile none)
* **FAIL**: product-800.webp is 800x800 with an sRGB profile ((800, 800), profile none)
* **FAIL**: product-400.jpg is 400x400 with an sRGB profile ((400, 400), profile none)
* **FAIL**: product-400.webp is 400x400 with an sRGB profile ((400, 400), profile none)
* pass: the product is centered with a 5% margin (box (641, 103, 1360, 1899), center 1000,1001, largest side 1796 (target 1800))
* pass: outside the product and its shadow, pixels are exactly white (0 other pixels)
* pass: a soft shadow lies below the product, none visible above it (darkest below 162, above 254)
* error returned: `gimp_modify_selection: Error executing tool gimp_modify_selection: 1 validation error for gimp_modify_selectionArguments
action
  Field required [type=missing, input_value={'image': 'image:1@f1087c..., 'operation': 'invert'`
* error returned: `gimp_add_layer_mask: Error executing tool gimp_add_layer_mask: 1 validation error for gimp_add_layer_maskArguments
item
  Field required [type=missing, input_value={'image': 'image:1@f1087cb2'}, input_type=dict]
    For f`
* error returned: `gimp_alpha_to_selection: WRONG_KIND: item 7 is a mask, not a layer`
* error returned: `gimp_move_layer: Error executing tool gimp_move_layer: 1 validation error for gimp_move_layerArguments
parent
  Field required [type=missing, input_value={'item': 'item:8@f1087cb2', 'position': 2}, input_type=dict]
  `
* error returned: `gimp_gaussian_blur: Error executing tool gimp_gaussian_blur: 1 validation error for gimp_gaussian_blurArguments
radius
  Field required [type=missing, input_value={'item': 'item:9@f1087cb2...'18', 'std_dev_y': '12'}, inp`
* error returned: `gimp_restore_checkpoint: Error executing tool gimp_restore_checkpoint: 1 validation error for gimp_restore_checkpointArguments
image
  Field required [type=missing, input_value={'checkpoint': 'checkpoint:1@f1087cb2'}, input_t`
* gimp tools: gimp_open_image, gimp_list_toolsets, gimp_enable_toolsets, gimp_preview, gimp_sample_colors, gimp_select_by_color, gimp_get_selection, gimp_modify_selection, gimp_modify_selection, gimp_inspect_image, gimp_add_layer_mask, gimp_add_layer_mask, gimp_modify_selection, gimp_scale_layer, gimp_resize_canvas, gimp_set_layer_offsets, gimp_alpha_to_selection, gimp_select_item, gimp_modify_selection, gimp_create_layer, gimp_create_layer, gimp_move_layer, gimp_select_ellipse, gimp_move_layer, gimp_fill, gimp_modify_selection, gimp_move_layer, gimp_gaussian_blur, gimp_set_layer_properties, gimp_gaussian_blur, gimp_inspect_image, gimp_preview, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_preview_region, gimp_set_color_profile, gimp_describe_file_format, gimp_describe_file_format, gimp_create_checkpoint, gimp_export_as, gimp_export_as, gimp_resize_image, gimp_export_as, gimp_export_as, gimp_restore_checkpoint, gimp_restore_checkpoint, gimp_resize_image, gimp_export_as, gimp_export_as, gimp_open_image, gimp_get_color_profile, gimp_sample_colors
* other tools tried: ToolSearch, ToolSearch

### `social-media-kit`

* pass: the session finished (success)
* pass: social-post.png is 1080x1080 (1080x1080)
* pass: post: the brand colors are there (navy band, cream text, red accent) (navy 13.0%, cream 1.96%, red 0.74%)
* pass: post: the logo lies inside the safe area (logo (64, 64, 244, 244), safe 64,64-1016,1016)
* pass: social-post.xcf keeps the headline as an editable text layer (419764 bytes)
* pass: social-story.png is 1080x1920 (1080x1920)
* pass: story: the brand colors are there (navy band, cream text, red accent) (navy 18.3%, cream 2.64%, red 0.52%)
* pass: story: the logo lies inside the safe area (logo (64, 250, 284, 470), safe 64,250-1016,1670)
* pass: social-story.xcf keeps the headline as an editable text layer (926186 bytes)
* pass: social-banner.png is 1500x500 (1500x500)
* pass: banner: the brand colors are there (navy band, cream text, red accent) (navy 30.3%, cream 3.57%, red 1.60%)
* pass: banner: the logo lies inside the safe area (logo (1300, 180, 1440, 320), safe 60,60-1440,440)
* pass: social-banner.xcf keeps the headline as an editable text layer (350391 bytes)
* pass: social-thumbnail.png is 1280x720 (1280x720)
* pass: thumbnail: the brand colors are there (navy band, cream text, red accent) (navy 19.2%, cream 2.82%, red 1.11%)
* pass: thumbnail: the logo lies inside the safe area (logo (64, 64, 184, 184), safe 64,64-1216,656)
* pass: social-thumbnail.xcf keeps the headline as an editable text layer (285650 bytes)
* gimp tools: gimp_status, gimp_list_toolsets, gimp_list_fonts, gimp_open_image, gimp_open_image, gimp_enable_toolsets, gimp_preview, gimp_preview, gimp_create_image, gimp_import_layer, gimp_scale_layer, gimp_create_layer, gimp_create_layer, gimp_import_layer, gimp_create_text_layer, gimp_scale_layer, gimp_set_layer_offsets, gimp_set_layer_offsets, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_preview, gimp_save_image, gimp_export_image, gimp_create_image, gimp_import_layer, gimp_scale_layer, gimp_create_layer, gimp_create_layer, gimp_import_layer, gimp_create_text_layer, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_set_layer_offsets, gimp_set_layer_offsets, gimp_scale_layer, gimp_preview, gimp_save_image, gimp_export_image, gimp_create_image, gimp_create_image, gimp_import_layer, gimp_import_layer, gimp_scale_layer, gimp_scale_layer, gimp_set_layer_offsets, gimp_set_layer_offsets, gimp_create_layer, gimp_create_layer, gimp_import_layer, gimp_create_text_layer, gimp_create_layer, gimp_create_layer, gimp_import_layer, gimp_create_text_layer, gimp_scale_layer, gimp_scale_layer, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_add_guide, gimp_preview, gimp_preview, gimp_save_image, gimp_export_image, gimp_save_image, gimp_export_image
* other tools tried: ToolSearch, ToolSearch

### `screenshot-annotation`

* pass: the session finished (success)
* pass: tutorial.png is a lossless PNG of the same size (PNG (1280, 800))
* pass: the e-mail keeps no detail (no glyph pixel left) (dark pixels 0 (were 229))
* pass: the avatar keeps no detail (flatter, eyes and mouth gone) (std dev 39.3 (was 71.4), features still visible at [])
* pass: outside the annotations and redactions, pixels are identical to the screenshot (0 other changed pixels)
* pass: red annotations at the Save button, the E-mail field, the Name and Phone fields (red pixels: save 2236, e-mail 608, name 636, phone 608)
* **FAIL**: the PNG carries no metadata (no text, Exif, time or profile chunk) (chunks ['IHDR', 'sRGB', 'gAMA', 'cHRM', 'pHYs', 'tIME', 'IDAT', 'IDAT', 'IDAT', 'IEND'])
* gimp tools: gimp_open_image, gimp_preview, gimp_list_toolsets, gimp_enable_toolsets, gimp_describe_filter_operation, gimp_inspect_image, gimp_select_rectangle, gimp_apply_filter, gimp_select_rectangle, gimp_apply_filter, gimp_select_rectangle, gimp_create_layer, gimp_draw_shape, gimp_draw_shape, gimp_draw_shape, gimp_draw_shape, gimp_draw_path, gimp_draw_path, gimp_create_text_layer, gimp_create_text_layer, gimp_create_text_layer, gimp_create_text_layer, gimp_set_layer_offsets, gimp_set_layer_offsets, gimp_set_layer_offsets, gimp_set_layer_offsets, gimp_preview, gimp_select_rectangle, gimp_draw_path, gimp_draw_path, gimp_draw_path, gimp_draw_path, gimp_draw_path, gimp_draw_path, gimp_preview, gimp_export_image
* other tools tried: ToolSearch, Bash, ToolSearch, ToolSearch

### `web-photo-batch`

* pass: the session finished (success)
* pass: every photo has a WebP and a JPEG, longest side 1600 px (40 files)
* pass: each is upright as EXIF said (red marker top-left)
* pass: the watermark is in the bottom-right corner at about 60%
* pass: no GPS position in any export
* pass: the copyright is kept in every export
* **FAIL**: every export carries an sRGB profile (beach-web.webp, beach-web.jpg, harbor-web.webp, harbor-web.jpg, market-web.webp, market-web.jpg)
* error returned: `gimp_enable_toolsets: Error executing tool gimp_enable_toolsets: 1 validation error for gimp_enable_toolsetsArguments
toolsets
  Field required [type=missing, input_value={'names': '["batch","docu...","formats","compose"]'`
* error returned: `gimp_export_as: WRITE_FAILED: directory /home/demo/work does not exist
Hint: Create the directory first; file tools never create directories.`
* gimp tools: gimp_list_toolsets, gimp_enable_toolsets, gimp_enable_toolsets, gimp_run_batch, gimp_open_image, gimp_get_metadata, gimp_get_color_profile, gimp_describe_file_format, gimp_run_batch, gimp_open_image, gimp_open_image, gimp_get_metadata, gimp_get_metadata, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_get_metadata, gimp_open_image, gimp_open_image, gimp_open_image, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_enable_toolsets, gimp_describe_file_format, gimp_resize_image, gimp_import_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_set_color_profile, gimp_set_metadata, gimp_export_as, gimp_export_as, gimp_open_image, gimp_open_image, gimp_get_color_profile, gimp_get_color_profile, gimp_get_metadata, gimp_get_metadata, gimp_open_image, gimp_inspect_image, gimp_set_layer_properties, gimp_export_as, gimp_export_as, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_open_image, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_get_metadata, gimp_get_color_profile, gimp_get_color_profile, gimp_get_color_profile, gimp_run_batch, gimp_open_image, gimp_preview, gimp_run_batch, gimp_run_batch, gimp_run_batch, gimp_run_batch, gimp_run_batch, gimp_run_batch, gimp_open_image, gimp_open_image, gimp_preview, gimp_preview
* other tools tried: Bash, ToolSearch, ToolSearch, ToolSearch, ToolSearch, ToolSearch

### `animated-sticker`

* pass: the session finished (success)
* pass: sticker.gif has 12 frames and loops (12 frames, loop 0)
* pass: sticker.gif: 80 ms per frame, the last held 1 s ([80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 1000])
* pass: sticker.gif: each frame shows the logo at its place and opacity
* pass: sticker.gif is under 500 KB (12651 bytes)
* pass: sticker.webp has 12 frames and loops (12 frames, loop 0)
* pass: sticker.webp: 80 ms per frame, the last held 1 s ([80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 1000])
* pass: sticker.webp: each frame shows the logo at its place and opacity
* pass: sticker.webp is under 500 KB (2992 bytes)
* error returned: `gimp_duplicate_layer: Error executing tool gimp_duplicate_layer: 1 validation error for gimp_duplicate_layerArguments
item
  Field required [type=missing, input_value={'layer': 'item:2@b0f8cd23'}, input_type=dict]
    For `
* error returned: `gimp_set_layer_properties: Error executing tool gimp_set_layer_properties: 1 validation error for gimp_set_layer_propertiesArguments
item
  Field required [type=missing, input_value={'layer': 'item:5@b0f8cd23', 'opacity': 8}, i`
* error returned: `gimp_set_layer_offsets: Error executing tool gimp_set_layer_offsets: 1 validation error for gimp_set_layer_offsetsArguments
item
  Field required [type=missing, input_value={'layer': 'item:5@b0f8cd23', 'x': 40, 'y': 24}, inp`
* error returned: `gimp_preview_frame: Error executing tool gimp_preview_frame: 1 validation error for gimp_preview_frameArguments
index
  Field required [type=missing, input_value={'image': 'image:1@b0f8cd...em': 'item:65@b0f8cd23'}, inpu`
* gimp tools: gimp_list_toolsets, gimp_enable_toolsets, gimp_create_image, gimp_status, gimp_inspect_image, gimp_import_layer, gimp_duplicate_layer, gimp_set_layer_properties, gimp_set_layer_offsets, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_set_layer_properties, gimp_merge_layers, gimp_duplicate_layer, gimp_duplicate_layer, gimp_set_layer_offsets, gimp_merge_layers, gimp_delete_layer, gimp_delete_layer, gimp_list_frames, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_set_frame, gimp_export_animation, gimp_export_animation, gimp_preview_frame, gimp_preview_frame
* other tools tried: Bash, ToolSearch, ToolSearch, ToolSearch

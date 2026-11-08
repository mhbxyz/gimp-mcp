# Runs inside GIMP (python-fu-eval): walks the filter catalog like the bridge does, several times, to see
# what makes DrawableFilter.new crash on macOS. Logs every step (fsync).
import os
import sys
import gi
gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, Gegl
Gegl.Buffer.__gtype__
sys.path.insert(0, os.environ["PLUGIN_DIR"])
import gmb_ops
import gmb_filters
log = open(os.environ["PROBE_OUT"], "w")
def say(text):
    log.write(text + "\n"); log.flush(); os.fsync(log.fileno())
mode = os.environ["MODE"]
if "init" in mode:
    Gegl.init(None)
image = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(image, "l", 8, 8, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
image.insert_layer(layer, None, 0)
skip = {"gegl:checkerboard"}
for walk in range(3 if "x3" in mode else 1):
    for name in Gimp.DrawableFilter.operation_get_available():
        if name in skip:
            continue
        if "prefilter" in mode:
            _ok, keys, values = Gimp.DrawableFilter.operation_get_details(name)
            details = {key: values.index(i) for i, key in enumerate(keys)}
            categories = [c for c in (details.get("categories") or "").split(":") if c]
            if not gmb_filters.operation_status(name, categories, [])[0]:
                continue
        say("walk %d op %s new" % (walk, name))
        drawable_filter = Gimp.DrawableFilter.new(layer, name, "probe")
        gmb_ops._describe_filter_params(drawable_filter.get_config())
        if "delete" in mode:
            drawable_filter.delete()
say("done")

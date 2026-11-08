# Runs inside GIMP (python-fu-eval): walks the filter catalog like gmb_ops.filter_catalog, logging each
# step (fsync) before doing it, so the last line names what crashes.
import os
import gi
gi.require_version("Gimp", "3.0")
from gi.repository import Gimp
log = open(os.environ["PROBE_OUT"], "w")
def say(text):
    log.write(text + "\n"); log.flush(); os.fsync(log.fileno())
image = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(image, "l", 8, 8, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
image.insert_layer(layer, None, 0)
for name in Gimp.DrawableFilter.operation_get_available():
    say("op %s new" % name)
    try:
        config = Gimp.DrawableFilter.new(layer, name, "probe").get_config()
    except Exception as error:
        say("op %s error %r" % (name, error)); continue
    for pspec in config.list_properties():
        say("op %s prop %s %s" % (name, pspec.name, pspec.value_type.name))
        try:
            config.get_property(pspec.name)
        except Exception as error:
            say("op %s prop %s error %r" % (name, pspec.name, error))
say("done")

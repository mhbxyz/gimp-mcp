# Runs inside GIMP (python-fu-eval): replays gmb_ops._describe_filter_params for every operation, logging
# each step (fsync) before doing it, so the last line names what crashes.
import os
import sys
import gi
gi.require_version("Gimp", "3.0")
from gi.repository import Gimp
sys.path.insert(0, os.environ["PLUGIN_DIR"])
import gmb_ops
log = open(os.environ["PROBE_OUT"], "w")
def say(text):
    log.write(text + "\n"); log.flush(); os.fsync(log.fileno())
image = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(image, "l", 8, 8, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
image.insert_layer(layer, None, 0)
for name in Gimp.DrawableFilter.operation_get_available():
    say("op %s details" % name)
    Gimp.DrawableFilter.operation_get_details(name)
    say("op %s new" % name)
    try:
        config = Gimp.DrawableFilter.new(layer, name, "probe").get_config()
    except Exception as error:
        say("op %s error %r" % (name, error)); continue
    for pspec in config.list_properties():
        kind = gmb_ops._param_kind(pspec)
        say("op %s prop %s kind %s blurb" % (name, pspec.name, kind))
        pspec.get_blurb()
        if kind in ("number", "integer"):
            say("op %s prop %s minmax" % (name, pspec.name)); pspec.minimum, pspec.maximum
        elif kind == "choice":
            say("op %s prop %s choice" % (name, pspec.name)); list(Gimp.param_spec_choice_get_choice(pspec).list_nicks())
        elif kind == "enum":
            say("op %s prop %s enum" % (name, pspec.name)); [v.value_nick for v in pspec.enum_class.__enum_values__.values()]
        if kind != "unsupported":
            say("op %s prop %s value" % (name, pspec.name)); gmb_ops._config_value(config.get_property(pspec.name))
say("done")

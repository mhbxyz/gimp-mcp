"""Animation frames (#59). Standard library only, no GIMP.

GIMP keeps an animation as layers, the bottom layer first. A frame's duration and disposal are
written in its layer name, the way GIMP's GIF and WebP exporters read them:
"Frame 3 (100ms) (replace)".
"""

import re

_TAG = re.compile(r"\s*\((?:(\d+)\s*ms|(combine|replace))\)\s*$", re.IGNORECASE)


def parse_frame_name(name):
    """-> (base name, duration in ms or None, disposal or None)."""
    duration = disposal = None
    base = name
    while True:
        match = _TAG.search(base)
        if match is None:
            break
        if match.group(1) is not None and duration is None:
            duration = int(match.group(1))
        elif match.group(2) is not None and disposal is None:
            disposal = match.group(2).lower()
        else:
            break
        base = base[: match.start()]
    return base.strip(), duration, disposal


def frame_name(base, duration, disposal):
    name = base
    if duration is not None:
        name += " (%dms)" % duration
    if disposal is not None:
        name += " (%s)" % disposal
    return name


def frames(layers, default_delay=100, default_disposal="combine"):
    """layers: (id, name) top first, as GIMP lists them -> frames in playing order."""
    result = []
    for index, (number, name) in enumerate(reversed(layers)):
        base, duration, disposal = parse_frame_name(name)
        result.append({
            "item": number,
            "index": index,
            "name": base,
            "duration_ms": duration if duration is not None else default_delay,
            "disposal": disposal or default_disposal,
        })  # fmt: skip
    return result


def visible_frames(frames, index):
    """Indexes of the frames on screen while frame ``index`` shows.

    A frame's disposal says what happens to it when the next frame comes: "combine" keeps it
    under the next one, "replace" removes it.
    """
    if not 0 <= index < len(frames):
        raise IndexError("frame %d does not exist (%d frames)" % (index, len(frames)))
    start = 0
    for previous in range(index):
        if frames[previous]["disposal"] == "replace":
            start = previous + 1
    return list(range(start, index + 1))

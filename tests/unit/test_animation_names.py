"""Animation frames (#59): timing and disposal live in layer names, as GIMP's GIF/WebP plug-ins read them."""

from __future__ import annotations

import gmb_anim  # type: ignore[import-not-found]
import pytest


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Frame 1", ("Frame 1", None, None)),
        ("Frame 1 (100ms)", ("Frame 1", 100, None)),
        ("Frame 1 (100ms) (replace)", ("Frame 1", 100, "replace")),
        ("Frame 1 (combine) (40 ms)", ("Frame 1", 40, "combine")),
        ("Background (1000ms)(replace)", ("Background", 1000, "replace")),
        ("Note (draft)", ("Note (draft)", None, None)),
    ],
)
def test_parse_frame_names(name, expected):
    assert gmb_anim.parse_frame_name(name) == expected


def test_frame_names_round_trip():
    assert gmb_anim.frame_name("Run", 80, "replace") == "Run (80ms) (replace)"
    assert gmb_anim.frame_name("Run", None, None) == "Run"
    assert gmb_anim.parse_frame_name(gmb_anim.frame_name("Walk (step)", 120, "combine")) == (
        "Walk (step)",
        120,
        "combine",
    )


def test_frames_are_listed_bottom_up_with_defaults():
    # GIMP lists layers top first; animations play from the bottom layer
    frames = gmb_anim.frames([(3, "C (50ms)"), (2, "B"), (1, "A (200ms) (replace)")], default_delay=100)
    assert frames == [
        {"item": 1, "index": 0, "name": "A", "duration_ms": 200, "disposal": "replace"},
        {"item": 2, "index": 1, "name": "B", "duration_ms": 100, "disposal": "combine"},
        {"item": 3, "index": 2, "name": "C", "duration_ms": 50, "disposal": "combine"},
    ]


def test_visible_frames_follow_the_disposal_of_previous_frames():
    def frame(index, disposal):
        return {"item": index, "index": index, "name": str(index), "duration_ms": 100, "disposal": disposal}

    frames = [frame(0, "combine"), frame(1, "replace"), frame(2, "combine"), frame(3, "combine")]
    assert gmb_anim.visible_frames(frames, 0) == [0]
    assert gmb_anim.visible_frames(frames, 1) == [0, 1]  # frame 0 combines: 1 is drawn over it
    assert gmb_anim.visible_frames(frames, 2) == [2]  # frame 1 is replaced
    assert gmb_anim.visible_frames(frames, 3) == [2, 3]
    with pytest.raises(IndexError):
        gmb_anim.visible_frames(frames, 4)

"""Text along a path (#88): warping control points along a path, without GIMP.

Expected positions come from geometry known in advance (a straight line, a circle of known radius),
not from the code under test. The algorithm is GIMP's (app/path/gimppath-warp.c): a point's x is a
distance along the path, its y an offset along the path's normal from the line y = y_offset.
"""

from __future__ import annotations

import math

import gmb_warp  # type: ignore[import-not-found]
import pytest

KAPPA = 0.5522847498  # cubic Bézier approximation of a quarter circle


def line(x0, y0, x1, y1):
    """A GIMP Bézier stroke (control-in, anchor, control-out per anchor) for a straight segment."""
    return ([x0, y0, x0, y0, x0, y0, x1, y1, x1, y1, x1, y1], False)


def circle(cx, cy, r):
    """Clockwise on screen (y down): right, bottom, left, top."""
    k = KAPPA * r
    anchors = [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r)]
    tangents = [(0, k), (-k, 0), (0, -k), (k, 0)]  # direction of travel at each anchor
    controls = []
    for (ax, ay), (tx, ty) in zip(anchors, tangents, strict=True):
        controls += [ax - tx, ay - ty, ax, ay, ax + tx, ay + ty]
    return (controls, True)


def test_a_straight_path_translates_the_text_onto_it():
    warp = gmb_warp.PathWarp([line(100, 200, 500, 200)])
    assert warp.length == pytest.approx(400, abs=0.01)
    # x along the line, y below it by (y - y_offset): the text's middle line sits on the path
    assert warp.point(0, 30, y_offset=30) == pytest.approx((100, 200), abs=0.01)
    assert warp.point(250, 10, y_offset=30) == pytest.approx((350, 180), abs=0.01)
    assert warp.point(399, 50, y_offset=30) == pytest.approx((499, 220), abs=0.01)


def test_beyond_the_end_the_text_continues_along_the_last_direction():
    warp = gmb_warp.PathWarp([line(100, 200, 500, 200)])
    assert warp.point(450, 30, y_offset=30) == pytest.approx((550, 200), abs=0.05)


def test_on_a_circle_points_keep_their_distance_from_the_path():
    r = 100.0
    warp = gmb_warp.PathWarp([circle(0, 0, r)])
    assert warp.length == pytest.approx(2 * math.pi * r, rel=0.002)
    for distance in (10, 80, 157, 300, 600):
        on = warp.point(distance, 20, y_offset=20)
        inside = warp.point(distance, 30, y_offset=20)  # 10 px along the normal, toward the center
        assert math.hypot(*on) == pytest.approx(r, abs=0.3), distance
        assert math.hypot(*inside) == pytest.approx(r - 10, abs=0.3), distance
    # a quarter of the circumference from the start (right) lands at the bottom
    assert warp.point(math.pi * r / 2, 0, y_offset=0) == pytest.approx((0, r), abs=0.5)


def test_text_longer_than_the_first_stroke_continues_on_the_next():
    warp = gmb_warp.PathWarp([line(0, 0, 100, 0), line(0, 50, 100, 50)])
    assert warp.point(130, 0, y_offset=0) == pytest.approx((30, 50), abs=0.01)


def test_warp_strokes_moves_every_control_point_and_keeps_closed_flags():
    warp = gmb_warp.PathWarp([line(100, 200, 500, 200)])
    square = ([0, 0, 0, 0, 0, 0, 10, 0, 10, 0, 10, 0, 10, 10, 10, 10, 10, 10], True)
    ((controls, closed),) = warp.warp_strokes([square], y_offset=5)
    assert closed is True and len(controls) == len(square[0])
    assert controls[:2] == pytest.approx([100, 195], abs=0.01)
    assert controls[12:14] == pytest.approx([110, 205], abs=0.01)


def test_paths_without_length_are_refused():
    with pytest.raises(ValueError):
        gmb_warp.PathWarp([line(5, 5, 5, 5)])
    with pytest.raises(ValueError):
        gmb_warp.PathWarp([])

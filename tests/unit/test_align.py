"""Layer alignment and distribution (#54): offsets computed without GIMP."""

from __future__ import annotations

import gmb_align  # type: ignore[import-not-found]
import pytest

# (x, y, width, height)
A = (10, 10, 20, 10)
B = (50, 40, 10, 30)
C = (0, 70, 40, 20)
BOX = (0, 0, 100, 100)


@pytest.mark.parametrize(
    ("horizontal", "vertical", "expected"),
    [
        ("left", None, [(0, 10), (0, 40)]),
        ("center", None, [(40, 10), (45, 40)]),
        ("right", None, [(80, 10), (90, 40)]),
        (None, "top", [(10, 0), (50, 0)]),
        (None, "middle", [(10, 45), (50, 35)]),
        (None, "bottom", [(10, 90), (50, 70)]),
        ("center", "middle", [(40, 45), (45, 35)]),
    ],
)
def test_align_to_a_box(horizontal, vertical, expected):
    assert gmb_align.align([A, B], BOX, horizontal, vertical) == expected


def test_distribute_centers_evenly_between_the_outer_layers():
    # centers x: A 20, B 55, C 20 -> sorted by center: A(20), C(20), B(55); outer stay, middle moves to 37.5
    moved = gmb_align.distribute([A, B, C], "horizontal")
    assert moved[0] == (10, 10) and moved[1] == (50, 40)
    assert moved[2] == (18, 70)  # center 37.5 -> x = 37.5 - 20 = 17.5, rounded half to even -> 18
    vertical = gmb_align.distribute([A, B, C], "vertical")
    # centers y: A 15, B 55, C 80 -> B moves to 47.5 -> y = 47.5 - 15 = 32.5 -> 32
    assert vertical == [(10, 10), (50, 32), (0, 70)]


def test_distribute_needs_three_layers():
    with pytest.raises(ValueError):
        gmb_align.distribute([A, B], "horizontal")

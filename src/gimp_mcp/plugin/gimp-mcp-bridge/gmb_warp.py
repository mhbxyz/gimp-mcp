"""Warp control points along a path, as GIMP's "Text along Path" does (#88). Stdlib only, no GIMP.

GIMP 3.2 has no PDB procedure for Text along Path, so the bridge reproduces its algorithm
(`app/path/gimppath-warp.c`): a point's x is a distance along the path (stroke after stroke) and its
y, measured from the line y = y_offset, an offset along the path's normal. Strokes are GIMP Bézier
strokes: a flat list of x, y for each anchor's (control-in, anchor, control-out) triple. Two
deliberate differences: points before the start (x < 0) continue backwards along the first tangent,
where GIMP puts them at (0, 0), and points within 2 px of the start keep their normal offset.
"""

import bisect
import itertools
import math

SAMPLES_PER_SEGMENT = 64
DX = 2.0  # half the span used to estimate the tangent, as GIMP


def _pairs(controls):
    return [(float(controls[i]), float(controls[i + 1])) for i in range(0, len(controls) - 1, 2)]


def _segments(controls, closed):
    points = _pairs(controls)
    anchors = [(points[3 * i], points[3 * i + 1], points[3 * i + 2]) for i in range(len(points) // 3)]
    segments = []
    for (_cin, anchor, cout), (cin, nxt, _cout) in itertools.pairwise(anchors):
        segments.append((anchor, cout, cin, nxt))
    if closed and len(anchors) > 1:
        segments.append((anchors[-1][1], anchors[-1][2], anchors[0][0], anchors[0][1]))
    return segments


def _cubic(p0, p1, p2, p3, t):
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


class _Stroke:
    """A stroke flattened into a polyline, with the distance from the start at each sample."""

    def __init__(self, controls, closed):
        samples = []
        for segment in _segments(controls, closed):
            start = 1 if samples else 0
            samples += [_cubic(*segment, t=i / SAMPLES_PER_SEGMENT) for i in range(start, SAMPLES_PER_SEGMENT + 1)]
        self.samples = samples
        self.distances = [0.0]
        for (x0, y0), (x1, y1) in itertools.pairwise(samples):
            self.distances.append(self.distances[-1] + math.hypot(x1 - x0, y1 - y0))
        self.length = self.distances[-1]

    def at(self, distance):
        distance = min(max(distance, 0.0), self.length)
        i = max(1, bisect.bisect_left(self.distances, distance))
        d0, d1 = self.distances[i - 1], self.distances[i]
        (x0, y0), (x1, y1) = self.samples[i - 1], self.samples[i]
        t = 0.0 if d1 == d0 else (distance - d0) / (d1 - d0)
        return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)

    def direction(self, start, end):
        (x0, y0), (x1, y1) = self.at(start), self.at(end)
        length = math.hypot(x1 - x0, y1 - y0)
        return None if length < 0.01 else ((x1 - x0) / length, (y1 - y0) / length)

    def warp(self, x, offset):
        """The point at distance x along the stroke, moved by offset along the normal."""
        if x >= self.length - DX or x < 0:
            end = x >= self.length - DX
            anchor = self.length if end else 0.0
            tangent = self.direction(self.length - DX, self.length) if end else self.direction(0.0, DX)
            px, py = self.at(anchor)
            if tangent is None:
                return (px, py)
            tx, ty = tangent
            along = x - anchor
            return (px + tx * along - ty * offset, py + ty * along + tx * offset)
        px, py = self.at(x)
        tangent = self.direction(max(0.0, x - DX), x + DX)
        if tangent is None:
            return (px, py)
        tx, ty = tangent
        return (px - ty * offset, py + tx * offset)


class PathWarp:
    """The strokes of a path, as a guide that other strokes are warped along."""

    def __init__(self, strokes):
        self.strokes = [s for s in (_Stroke(controls, closed) for controls, closed in strokes) if s.length > 0]
        if not self.strokes:
            raise ValueError("the path has no length")
        self.length = sum(s.length for s in self.strokes)

    def point(self, x, y, y_offset):
        offset = y - y_offset
        for stroke in self.strokes[:-1]:
            if x < stroke.length:
                return stroke.warp(x, offset)
            x -= stroke.length
        return self.strokes[-1].warp(x, offset)

    def warp_strokes(self, strokes, y_offset):
        """Every control point of every stroke warped; strokes keep their point count and closed flag."""
        warped = []
        for controls, closed in strokes:
            moved = []
            for x, y in _pairs(controls):
                moved.extend(self.point(x, y, y_offset))
            warped.append((moved, closed))
        return warped

"""Align and distribute layers (#54). Standard library only.

Boxes are (x, y, width, height) in image pixels; results are new (x, y) offsets, in input order.
"""


def _place(start, size, box_start, box_size, mode, near, mid, far):
    if mode is None:
        return start
    if mode == near:
        return box_start
    if mode == mid:
        return round(box_start + (box_size - size) / 2)
    if mode == far:
        return box_start + box_size - size
    raise ValueError("unknown alignment %r" % mode)


def align(boxes, reference, horizontal=None, vertical=None):
    rx, ry, rw, rh = reference
    return [
        (
            _place(x, w, rx, rw, horizontal, "left", "center", "right"),
            _place(y, h, ry, rh, vertical, "top", "middle", "bottom"),
        )
        for x, y, w, h in boxes
    ]


def distribute(boxes, direction):
    """Spread the centers evenly between the first and last centers (sorted along the direction)."""
    if len(boxes) < 3:
        raise ValueError("distributing needs at least 3 layers")
    axis = 0 if direction == "horizontal" else 1
    centers = [box[axis] + box[axis + 2] / 2 for box in boxes]
    order = sorted(range(len(boxes)), key=lambda i: (centers[i], i))
    first, last = centers[order[0]], centers[order[-1]]
    step = (last - first) / (len(boxes) - 1)
    result = [(box[0], box[1]) for box in boxes]
    for rank, index in enumerate(order[1:-1], start=1):
        x, y, w, h = boxes[index]
        center = first + rank * step
        if axis == 0:
            result[index] = (round(center - w / 2), y)
        else:
            result[index] = (x, round(center - h / 2))
    return result

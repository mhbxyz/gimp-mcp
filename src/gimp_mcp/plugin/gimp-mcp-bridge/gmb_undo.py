"""Track undo groups opened by bridge clients so they are always closed.

Standard library only. GIMP's undo groups are counted per image; a group left
open would swallow every later change (including the user's) into a single
undo step. Groups are therefore tracked per (connection, image) and closed
when the client ends them, or when its connection goes away (client exit,
timeout, crash).
"""

from __future__ import annotations


class NoOpenGroup(Exception):
    pass


class UndoGroups:
    def __init__(self, start, end, is_valid):
        self._start = start
        self._end = end
        self._is_valid = is_valid
        self._open = {}  # (connection, image) -> depth

    def open_count(self, connection, image):
        return self._open.get((connection, image), 0)

    def begin(self, connection, image):
        self._start(image)
        key = (connection, image)
        self._open[key] = self._open.get(key, 0) + 1
        return self._open[key]

    def end(self, connection, image):
        key = (connection, image)
        depth = self._open.get(key, 0)
        if depth == 0:
            raise NoOpenGroup("no undo group opened by this client on image %d" % image)
        self._end(image)
        if depth == 1:
            del self._open[key]
        else:
            self._open[key] = depth - 1
        return depth - 1

    def close_connection(self, connection):
        closed = 0
        for key in [key for key in self._open if key[0] == connection]:
            depth = self._open.pop(key)
            image = key[1]
            if self._is_valid(image):
                for _ in range(depth):
                    self._end(image)
                    closed += 1
        return closed

"""Undo groups opened through the bridge are always closed (issue #9)."""

from __future__ import annotations

import gmb_undo  # type: ignore[import-not-found]
import pytest

from gimp_mcp.bridge import BridgeClient

from .fake_bridge import running_fake_bridge


class FakeGimp:
    def __init__(self):
        self.events: list[tuple[str, int]] = []
        self.valid = {1, 2}

    def start(self, image: int) -> None:
        self.events.append(("start", image))

    def end(self, image: int) -> None:
        self.events.append(("end", image))

    def is_valid(self, image: int) -> bool:
        return image in self.valid


def groups(gimp: FakeGimp) -> gmb_undo.UndoGroups:
    return gmb_undo.UndoGroups(start=gimp.start, end=gimp.end, is_valid=gimp.is_valid)


def test_begin_and_end_are_paired_per_connection_and_image():
    gimp = FakeGimp()
    tracker = groups(gimp)
    assert tracker.begin("conn-a", 1) == 1
    assert tracker.begin("conn-a", 1) == 2  # nested
    assert tracker.end("conn-a", 1) == 1
    assert tracker.end("conn-a", 1) == 0
    assert gimp.events == [("start", 1), ("start", 1), ("end", 1), ("end", 1)]


def test_ending_a_group_that_is_not_open_is_an_explicit_error():
    tracker = groups(FakeGimp())
    tracker.begin("conn-a", 1)
    with pytest.raises(gmb_undo.NoOpenGroup):
        tracker.end("conn-b", 1)  # another client's group is not ours to close
    with pytest.raises(gmb_undo.NoOpenGroup):
        tracker.end("conn-a", 2)


def test_disconnect_closes_every_group_of_that_connection_only():
    gimp = FakeGimp()
    tracker = groups(gimp)
    tracker.begin("conn-a", 1)
    tracker.begin("conn-a", 1)
    tracker.begin("conn-a", 2)
    tracker.begin("conn-b", 1)
    gimp.events.clear()
    closed = tracker.close_connection("conn-a")
    assert sorted(gimp.events) == [("end", 1), ("end", 1), ("end", 2)]
    assert closed == 3
    assert tracker.open_count("conn-b", 1) == 1


def test_groups_of_images_closed_meanwhile_are_forgotten_without_calling_gimp():
    gimp = FakeGimp()
    tracker = groups(gimp)
    tracker.begin("conn-a", 2)
    gimp.valid.discard(2)
    gimp.events.clear()
    tracker.close_connection("conn-a")
    assert gimp.events == []


async def test_the_bridge_notifies_disconnections():
    seen: list[object] = []
    with running_fake_bridge({"x": lambda p: {}}) as bridge:
        bridge.server.on_disconnect.append(seen.append)
        client = BridgeClient(bridge.endpoint)
        await client.call("x")
        connection = bridge.server.last_connection_id
        await client.close()
        for _ in range(50):
            if seen:
                break
            import asyncio

            await asyncio.sleep(0.02)
    assert seen == [connection]

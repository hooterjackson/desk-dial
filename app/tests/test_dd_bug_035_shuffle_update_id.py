"""DD-BUG-035: the companion shuffle carries the expected queue UpdateID across its moves.

The lock is released between moves; another app's edit there used to be adopted (the next move
read the new UpdateID and passed it), so later moves took the wrong songs. Now each move compares
the UpdateID it reads with the version the previous step left, and stops with QueueChanged before
moving anything else.
Headless: the fake speaker of test_cc_sonos_v7.py on a fake clock; no network, no Sonos, no Tk.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.sonos import QueueChanged  # noqa: E402
from test_cc_music import FakeItem  # noqa: E402
from test_cc_sonos_v7 import Rig, ids, row_signature  # noqa: E402

QUEUE = tuple(range(90, 100))
REVERSE = [7, 6, 5, 4, 3, 2, 1, 0]   # every step moves a row


def rig():
    return Rig(queue=QUEUE, position=2, latency=0.0)


def on(r, **kwargs):
    rows = r.speaker.items[r.state["playlist_position"]:]
    return r.adapter.shuffle_reorder(True, r.state["group_revision"], r.state["track_id"], plan=REVERSE,
                                     expected_rows=[row_signature(x) for x in rows], **kwargs)


def foreign_add(r, number=555):
    r.speaker.items.append(FakeItem(number))
    r.speaker.revision += 1


class CarriedUpdateIdTests(unittest.TestCase):
    def test_companion_shuffle_stops_when_another_app_edits_between_moves(self):
        r = rig()
        steps = []

        def between():
            steps.append(len(r.speaker.reorders))
            if len(steps) == 1:
                foreign_add(r)            # the phone app adds a song while the lock is free
        with self.assertRaises(QueueChanged):
            on(r, between_steps=between)
        self.assertEqual(len(r.speaker.reorders), 1, "no move after the foreign edit")
        self.assertTrue(r.shuffle.saved["base_rows"], "the record is kept (failure after acceptance)")

    def test_an_edit_before_the_first_move_moves_nothing(self):
        r = rig()
        with self.assertRaises(QueueChanged):
            on(r, progress=lambda payload: foreign_add(r))
        self.assertEqual(r.speaker.reorders, [])

    def test_shuffle_off_stops_the_same_way(self):
        r = rig()
        on(r)
        r.refresh()
        steps = []

        def between():
            steps.append(1)
            if len(steps) == 1:
                r.speaker.items.insert(len(r.speaker.items) - 1, FakeItem(556))
                r.speaker.revision += 1
        moved_before = len(r.speaker.reorders)
        with self.assertRaises(QueueChanged):
            r.adapter.shuffle_reorder(False, r.state["group_revision"], r.state["track_id"],
                                      playnext_song_ids=[], between_steps=between)
        self.assertEqual(len(r.speaker.reorders) - moved_before, 1)

    def test_without_foreign_edits_the_plan_is_realised(self):
        r = rig()
        on(r)
        upcoming = list(QUEUE[2:])
        self.assertEqual(ids(r.speaker.items), [90, 91] + [upcoming[j] for j in REVERSE])


if __name__ == "__main__":
    unittest.main()

"""DD-BUG-034: a companion-shuffle record must not outlive its queue.

When another Sonos app replaces the queue, the next state read sees a queue UpdateID the record
was not checked at, reads the queue once, finds the record's base rows gone and drops the record:
``companion_shuffle`` turns False within one poll. A drop whose store write fails removes the file
or is retried, so the record never comes back at the next start.
Headless: the fake speaker of test_cc_sonos_v7.py on a fake clock; no network, no Sonos, no Tk.
"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_cc_music import FakeItem  # noqa: E402
from test_cc_sonos_v7 import Rig, row_signature, song  # noqa: E402


QUEUE = tuple(range(90, 100))


def shuffled():
    rig = Rig(queue=QUEUE, position=2, latency=0.0)
    rows = rig.speaker.items[2:]
    state = rig.adapter.shuffle_reorder(True, rig.state["group_revision"], rig.state["track_id"],
                                        plan=[7, 6, 5, 4, 3, 2, 1, 0],
                                        expected_rows=[row_signature(x) for x in rows])
    assert state["companion_shuffle"]
    rig.refresh()
    return rig


def replace_queue_elsewhere(rig, numbers=(300, 301, 302, 303)):
    rig.speaker.items = [FakeItem(n) for n in numbers]
    rig.speaker.revision += 1
    rig.play(1)


class FailingStore:
    def __init__(self, path=None):
        self.path, self.saved, self.fail = path, None, True

    def save(self, data):
        if self.fail:
            raise OSError("disk full")
        self.saved = data

    def load(self):
        return dict(self.saved or {})


class StaleRecordTests(unittest.TestCase):
    def test_foreign_queue_replacement_clears_companion_shuffle(self):
        rig = shuffled()
        replace_queue_elsewhere(rig)
        self.assertFalse(rig.refresh()["companion_shuffle"], "within one poll")
        self.assertEqual(rig.shuffle.saved, {}, "the record is deleted, not only hidden")
        rig.adapter.load_shuffle_record()   # the next start
        self.assertFalse(rig.refresh()["companion_shuffle"])

    def test_a_stale_record_loaded_at_start_is_dropped_by_the_first_poll(self):
        rig = shuffled()
        record = dict(rig.shuffle.saved)
        replace_queue_elsewhere(rig)
        restarted = Rig(queue=(300, 301, 302), position=1, latency=0.0)
        restarted.shuffle.saved = record
        restarted.adapter.load_shuffle_record()
        self.assertFalse(restarted.refresh()["companion_shuffle"])
        self.assertEqual(restarted.shuffle.saved, {})

    def test_our_own_play_next_and_playback_keep_the_record(self):
        rig = shuffled()
        rig.adapter.play_next([song(5), song(6)], rig.state["group_revision"], rig.state["track_id"])
        self.assertTrue(rig.refresh()["companion_shuffle"])
        rig.play(5)
        self.assertTrue(rig.refresh()["companion_shuffle"])
        self.assertTrue(rig.shuffle.saved["base_rows"])

    def test_an_unchanged_queue_costs_no_extra_read(self):
        rig = shuffled()
        rig.speaker.queue_reads.clear()
        for _ in range(3):
            self.assertTrue(rig.refresh()["companion_shuffle"])
        self.assertEqual(rig.speaker.queue_reads, [(0, 1)] * 3, "only the poll's own 1-row read")
        rig.adapter.play_next([song(5)], rig.state["group_revision"], rig.state["track_id"])
        rig.refresh()
        rig.speaker.queue_reads.clear()
        rig.refresh()
        self.assertEqual(rig.speaker.queue_reads, [(0, 1)], "a checked UpdateID is not read again")

    def test_a_failed_drop_removes_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shuffle-restore.bin"
            rig = shuffled()
            path.write_bytes(b"record")
            store = FailingStore(path)
            rig.adapter.shuffle_store = store
            replace_queue_elsewhere(rig)
            self.assertFalse(rig.refresh()["companion_shuffle"])
            self.assertFalse(path.exists())

    def test_a_failed_drop_without_a_file_is_retried_by_the_next_poll(self):
        rig = shuffled()
        store = FailingStore()
        store.saved = dict(rig.shuffle.saved)
        rig.adapter.shuffle_store = store
        replace_queue_elsewhere(rig)
        self.assertFalse(rig.refresh()["companion_shuffle"])
        self.assertTrue(store.saved, "the write failed")
        store.fail = False
        self.assertFalse(rig.refresh()["companion_shuffle"])
        self.assertEqual(store.saved, {}, "retried")

    def test_a_new_shuffle_after_a_failed_drop_keeps_its_record(self):
        """A drop left pending (store write failed, no file to unlink) must not delete the record
        a later companion shuffle saves: the new record supersedes the stale one."""
        rig = shuffled()
        store = FailingStore()
        store.saved = dict(rig.shuffle.saved)
        rig.adapter.shuffle_store = store
        rig.speaker.items = [FakeItem(n) for n in range(300, 310)]
        rig.speaker.revision += 1
        rig.play(1)
        self.assertFalse(rig.refresh()["companion_shuffle"])
        self.assertTrue(rig.adapter._shuffle_drop_pending, "the drop could not be written")
        store.fail = False                       # the store is writable again
        rows = rig.speaker.items[1:]
        state = rig.adapter.shuffle_reorder(True, rig.state["group_revision"], rig.state["track_id"],
                                            plan=[8, 7, 6, 5, 4, 3, 2, 1, 0],
                                            expected_rows=[row_signature(x) for x in rows])
        self.assertTrue(state["companion_shuffle"], "shuffle on's own state keeps the new record")
        self.assertTrue(store.saved.get("base_rows"), "the new record persists")
        self.assertFalse(rig.adapter._shuffle_drop_pending)
        self.assertTrue(rig.refresh()["companion_shuffle"])
        self.assertTrue(store.saved.get("base_rows"))


if __name__ == "__main__":
    unittest.main()

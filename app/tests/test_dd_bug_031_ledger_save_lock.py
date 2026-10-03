"""DD-BUG-031: the queue ledger never holds its lock across the file write / fsync, so a classify() on the Tk
thread is not stalled while the Sonos worker saves. Headless: a temp folder, no network."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from control_center import queue_context  # noqa: E402
from control_center.queue_context import QueueLedger, Segment  # noqa: E402

SLOW = 0.2


class LedgerSaveLockTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "queue-ledger.json"
        self.ledger = QueueLedger("room", path=self.path)
        self.ledger.record_start(Segment(kind="album", name="A"), ["1", "2", "3"])

    def test_classify_not_blocked_by_save_io(self):
        in_fsync, real_fsync = threading.Event(), queue_context.os.fsync

        def slow_fsync(fd):
            in_fsync.set()
            time.sleep(SLOW)
            real_fsync(fd)

        with mock.patch.object(queue_context.os, "fsync", slow_fsync):
            writer = threading.Thread(target=self.ledger.record_start,
                                      args=(Segment(kind="album", name="B"), ["4", "5"]))
            writer.start()
            self.assertTrue(in_fsync.wait(2.0))
            started = time.perf_counter()
            context = self.ledger.classify(["4", "5"])
            elapsed = time.perf_counter() - started
            writer.join(5.0)
        self.assertEqual(context.title, "B", "the in-memory ledger changed before the save")
        self.assertLess(elapsed, SLOW / 2, "classify waited for the fsync")

    def test_the_newest_state_is_the_one_on_disk(self):
        for n in range(5):
            self.ledger.append_playnext(2, [f"p{n}"])
        loaded = QueueLedger("room", path=self.path).load()
        self.assertEqual([s.song_ids for s in loaded.playnext], [["p4"], ["p3"], ["p2"], ["p1"], ["p0"]])
        self.assertEqual(loaded.base.song_ids, ["1", "2", "3"])

    def test_concurrent_writers_leave_the_last_state(self):
        threads = [threading.Thread(target=self.ledger.append_playnext, args=(2, [f"t{n}"])) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5.0)
        loaded = QueueLedger("room", path=self.path).load()
        self.assertEqual(sorted(s.song_ids[0] for s in loaded.playnext),
                         sorted(s.song_ids[0] for s in self.ledger.playnext))
        self.assertEqual(len(loaded.playnext), 8)


if __name__ == "__main__":
    unittest.main()

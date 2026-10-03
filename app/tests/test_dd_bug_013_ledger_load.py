"""DD-BUG-013: the Up next queue ledger is loaded at start (and when the pinned room changes), not only saved.

A ledger entry written by an earlier session for the pinned room is the runtime's ledger after a restart;
a room resolved later (none pinned) loads that room's entry instead of overwriting it unread. The ledger
file is a temporary one (queue_context.default_path patched); no Sonos, port, window or network.
"""
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import queue_context  # noqa: E402
from control_center.queue_context import QueueLedger, Segment  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.sonos import SonosAdapter  # noqa: E402


def adapter(room):
    live = SonosAdapter.__new__(SonosAdapter)      # no address, no network: only the pinned room is read
    live.room_uid = room
    return live


class DefaultLedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "queue-ledger.json"
        patcher = mock.patch.object(queue_context, "default_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        for room, name in (("ROOM_A", "Album A"), ("ROOM_B", "Album B")):
            QueueLedger(room).record_start(Segment(kind="album", name=name), ["1", "2", "3"])

    def test_default_ledger_loads_the_persisted_room_entry(self):
        ledger = Runtime._default_ledger(adapter("ROOM_A"))
        self.assertIsNotNone(ledger.base)
        self.assertEqual((ledger.base.name, ledger.base.song_ids), ("Album A", ["1", "2", "3"]))
        self.assertTrue(ledger.autosave)

    def test_a_missing_or_corrupt_file_is_an_empty_ledger(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.assertIsNone(Runtime._default_ledger(adapter("ROOM_A")).base)
        self.path.unlink()
        self.assertIsNone(Runtime._default_ledger(adapter("ROOM_A")).base)

    def test_fakes_keep_an_in_memory_ledger(self):
        ledger = Runtime._default_ledger(object())
        self.assertFalse(ledger.autosave)
        self.assertIsNone(ledger.base)

    def test_the_ledger_follows_a_room_resolved_later(self):
        live = adapter(None)
        controller = types.SimpleNamespace(ledger=None)
        runtime = types.SimpleNamespace(sonos=live, ledger=Runtime._default_ledger(live), _controller=controller,
                                        _ledger_follows_room=True, _ledger_room_lock=threading.Lock())
        self.assertIsNone(runtime.ledger.base)
        Runtime._follow_ledger_room(runtime)            # still no room: unchanged
        self.assertEqual(runtime.ledger.room_uid, "")
        live.room_uid = "ROOM_B"
        Runtime._follow_ledger_room(runtime)
        self.assertEqual(runtime.ledger.room_uid, "ROOM_B")
        self.assertEqual(runtime.ledger.base.name, "Album B")
        self.assertIs(controller.ledger, runtime.ledger)
        # the file still holds both rooms (nothing overwritten unread)
        self.assertEqual(QueueLedger("ROOM_A").load().base.name, "Album A")

    def test_an_injected_ledger_is_never_replaced(self):
        injected = QueueLedger(autosave=False)
        runtime = types.SimpleNamespace(sonos=adapter("ROOM_B"), ledger=injected, _controller=None,
                                        _ledger_follows_room=False, _ledger_room_lock=threading.Lock())
        Runtime._follow_ledger_room(runtime)
        self.assertIs(runtime.ledger, injected)


if __name__ == "__main__":
    unittest.main()

"""K3 section 9.7.3 provenance ledger (WP6): base + Play-next attribution by id multiset,
the context strings K4 draws as given, foreign detection, and per-room persistence."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.queue_context import (  # noqa: E402
    FOREIGN_TITLE, QueueLedger, Segment, format_duration,
)


def rows(*song_ids):
    return [{"row": i + 1, "song_id": None if s is None else str(s)} for i, s in enumerate(song_ids)]


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data" / "queue-ledger.json"

    def ledger(self, room="ROOM"):
        return QueueLedger(room, path=self.path, clock=lambda: 1000.0)

    def album(self, ledger, ids=(1, 2, 3, 4)):
        ledger.record_start(Segment("album", name="Midnight Cruisin'", artist="Kingo Hamada", year=1982,
                                    library_id="l.1", art_template="https://is1-ssl.mzstatic.com/x/{w}x{h}bb.jpg",
                                    accent=0x224466), [str(v) for v in ids])

    def test_a_base_album_with_its_rows(self):
        ledger = self.ledger()
        self.album(ledger)
        context = ledger.classify(rows(1, 2, 3, 4))
        self.assertEqual(context.presenter(), {"kind": "album", "title": "Midnight Cruisin'",
                                               "sub": "Kingo Hamada · 1982"})
        self.assertEqual(context.roles, ["base"] * 4)
        ledger.base.year = None
        self.assertEqual(ledger.classify(rows(1, 2, 3, 4)).sub, "Kingo Hamada", "year omitted when unknown")

    def test_play_next_rows_are_taken_before_base_rows_and_survive_a_shuffle(self):
        ledger = self.ledger()
        self.album(ledger)
        ledger.append_playnext(2, ["9", "3"])
        context = ledger.classify(rows(1, 9, 3, 2, 3, 4))
        self.assertEqual(context.kind, "album")
        self.assertEqual(context.roles, ["base", "playnext", "playnext", "base", "base", "base"])
        self.assertEqual(context.playnext_offsets(first_upcoming=1), [0, 1])
        shuffled = ledger.classify(rows(1, 9, 3, 4, 3, 2))
        self.assertEqual(shuffled.kind, "album", "a permutation of the same ids is still ours")
        self.assertEqual(ledger.playnext_song_ids(), ["9", "3"])

    def test_a_re_queued_played_song_keeps_its_play_next_row_first_for_the_shuffle(self):
        # move_next of the played row 2 re-inserts it at P+1 = 4 (C5-45: pn holds that row).
        ledger = self.ledger()
        self.album(ledger)
        ledger.append_playnext(4, ["2"])
        context = ledger.classify(rows(1, 2, 3, 2, 4))
        self.assertEqual(context.kind, "album")
        self.assertEqual(context.roles, ["base", "base", "base", "playnext", "base"])
        self.assertEqual(context.playnext_offsets(first_upcoming=3), [0])
        # An explorer Play next of a song the album already played (album 1..10, playing row 5).
        ledger = self.ledger()
        self.album(ledger, ids=range(1, 11))
        ledger.append_playnext(6, ["2"])
        context = ledger.classify(rows(1, 2, 3, 4, 5, 2, 6, 7, 8, 9, 10))
        self.assertEqual(context.roles[1], "base", "the played row 2")
        self.assertEqual(context.roles[5], "playnext")
        self.assertEqual(context.playnext_offsets(first_upcoming=5), [0])

    def test_a_played_play_next_row_keeps_its_role_ahead_of_its_upcoming_base_twin(self):
        # Album 1..4, playing row 1, Play next '3' at row 2; playback then reaches row 3.
        ledger = self.ledger()
        self.album(ledger)
        ledger.append_playnext(2, ["3"])
        context = ledger.classify(rows(1, 3, 2, 3, 4))
        self.assertEqual(context.roles, ["base", "playnext", "base", "base", "base"])
        self.assertEqual(context.playnext_offsets(first_upcoming=3), [], "the upcoming '3' is the album's")

    def test_playnext_units_carry_each_blocks_start_row_for_the_shuffle_off(self):
        # [WP6-r22] The shuffle-off effect's playnext_song_ids: [song_id, start_row] per unit,
        # newest block first, so the adapter can let played Play-next rows give back their units.
        ledger = self.ledger()
        self.album(ledger, ids=range(1, 11))
        ledger.append_playnext(4, ["7", "8"])
        ledger.append_playnext(6, ["2"])
        self.assertEqual(ledger.playnext_units(), [["2", 6], ["7", 4], ["8", 4]])
        self.assertEqual(ledger.playnext_song_ids(), ["2", "7", "8"])
        older = self.ledger()   # a segment without start_row (an older file): the bare id
        self.album(older)
        older.playnext.insert(0, Segment("playnext", song_ids=["2"]))
        self.assertEqual(older.playnext_units(), [["2", None]])
        json.dumps(ledger.playnext_units())   # plain JSON values for the effect payload
        ledger.record_start(Segment("album", name="A"), ["1"])
        self.assertEqual(ledger.playnext_units(), [])

    def test_row_numbers_come_from_the_rows_or_first_row(self):
        ledger = self.ledger()
        self.album(ledger, ids=range(1, 11))
        ledger.append_playnext(6, ["2"])
        window = [{"row": n, "song_id": s} for n, s in ((2, "2"), (3, "3"), (6, "2"), (7, "6"))]
        self.assertEqual(ledger.classify(window).roles, ["base", "base", "playnext", "base"])
        self.assertEqual(ledger.classify(["2", "3", "4", "5", "2"], first_row=2).roles,
                         ["base", "base", "base", "base", "playnext"])
        self.assertEqual(ledger.classify(["2", "2"], first_row=6).roles, ["playnext", "base"])

    def test_foreign_detection_stays_the_id_multiset(self):
        ledger = self.ledger()
        self.album(ledger, ids=range(1, 11))
        ledger.append_playnext(6, ["2"])
        # Another app removed row 3: the Play-next '2' is now above its insert row; still ours.
        context = ledger.classify(rows(1, 2, 4, 5, 2, 6, 7, 8, 9, 10))
        self.assertEqual(context.kind, "album")
        self.assertEqual(context.roles.count("playnext"), 1)
        self.assertEqual(ledger.classify(rows(1, 2, 3, 2, 2)).kind, "foreign", "a third '2'")
        older = self.ledger()   # a segment without start_row (an older file) matches any row
        self.album(older)
        older.playnext.insert(0, Segment("playnext", song_ids=["2"]))
        self.assertEqual(older.classify(rows(1, 2, 3, 2)).roles, ["base", "playnext", "base", "base"])

    def test_one_unattributable_row_makes_the_queue_foreign(self):
        ledger = self.ledger()
        self.album(ledger)
        for queue in (rows(1, 2, None, 4), rows(1, 2, 3, 4, 77), rows(1, 2, 3, 4, 4)):
            with self.subTest(queue=[r["song_id"] for r in queue]):
                context = ledger.classify(queue, total=len(queue))
                self.assertEqual(context.presenter(), {"kind": "foreign", "title": FOREIGN_TITLE,
                                                       "sub": f"Started in another app · {len(queue)} songs"})
                self.assertIn("foreign", context.roles)
        self.assertEqual(self.ledger().classify(rows(1, 2)).kind, "foreign", "no start of ours")

    def test_playlist_and_song_contexts(self):
        ledger = self.ledger()
        ledger.record_start(Segment("playlist", name="PAPER LANTERN Ep. 1", favourite=True, count=34,
                                    duration_ms=(2 * 60 + 5) * 60000), [str(v) for v in range(34)])
        context = ledger.classify(rows(*range(34)))
        self.assertEqual(context.presenter(), {"kind": "playlist", "title": "PAPER LANTERN Ep. 1",
                                               "sub": "Favourite playlist · 34 songs · 2 h 05 min"})
        ledger.record_start(Segment("playlist", name="Road", count=1, duration_ms=190000), ["5"])
        self.assertEqual(ledger.classify(rows(5)).sub, "Playlist · 1 song · 3 min")
        ledger.record_start(Segment("song", name="Plastic Love", album="Variety", count=1), ["8"])
        context = ledger.classify(rows(8))
        self.assertEqual((context.kind, context.title, context.base_kind), ("playlist", "Variety", "song"))
        self.assertEqual(format_duration(None), "")
        self.assertEqual(format_duration(59 * 60000), "59 min")

    def test_a_start_replaces_everything(self):
        ledger = self.ledger()
        self.album(ledger)
        ledger.append_playnext(2, ["9"])
        self.album(ledger, ids=(5, 6))
        self.assertEqual((ledger.playnext, ledger.base.song_ids), ([], ["5", "6"]))

    def test_persistence_per_room_ids_names_and_templates_only(self):
        a, b = self.ledger("ROOM-A"), self.ledger("ROOM-B")
        self.album(a)
        a.append_playnext(3, ["9"])
        b.record_start(Segment("playlist", name="Road"), ["7"])
        loaded = self.ledger("ROOM-A").load()
        self.assertEqual(loaded.classify(rows(1, 2, 9, 3, 4)).kind, "album")
        self.assertEqual(self.ledger("ROOM-B").load().base.name, "Road")
        self.assertIsNone(self.ledger("ROOM-C").load().base)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data["rooms"]), ["ROOM-A", "ROOM-B"])
        text = self.path.read_text(encoding="utf-8").lower()
        for secret in ("token", "authorization", "password", "x-sonos", "x-rincon"):
            self.assertNotIn(secret, text)

    def test_a_corrupt_or_foreign_file_is_an_empty_ledger(self):
        self.path.parent.mkdir(parents=True)
        for content in ("{not json", json.dumps({"version": 99, "rooms": {}}), json.dumps([1, 2])):
            with self.subTest(content=content[:12]):
                self.path.write_text(content, encoding="utf-8")
                ledger = self.ledger().load()
                self.assertIsNone(ledger.base)
                self.album(ledger)   # and it can write over it
                self.assertEqual(self.ledger().load().base.song_ids, ["1", "2", "3", "4"])

    def test_segment_kinds_are_checked(self):
        with self.assertRaises(ValueError):
            Segment("radio")


if __name__ == "__main__":
    unittest.main()

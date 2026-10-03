"""DD-BUG-035: CONTROL_CENTER_V5.md 9.5.2 step 5 states the UpdateID rule that sonos.py builds.

Each guarded move compares the UpdateID it reads with the version the model describes (step 2's
read, then the one read right after the previous move) and raises QueueChanged on a mismatch, so
another app's edit between steps stops the job before any move. 9.5.3 step 5 inherits it."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "CONTROL_CENTER_V5.md"
SONOS = ROOT / "control_center" / "sonos.py"


def _section(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


class SpecStep5UpdateIdTest(unittest.TestCase):
    def setUp(self):
        text = SPEC.read_text(encoding="utf-8")
        self.step5 = _section(text, "**9.5.2 `shuffle_reorder(on=True", " 6 verify:")
        self.restore = _section(text, "**9.5.3 `shuffle_reorder(on=False)`", " 6 verify as 9.5.2")
        self.text = text

    def test_expected_version_seeded_before_loop(self):
        seed = self.step5.index("U_exp = the UpdateID of step 2's read")
        self.assertLess(seed, self.step5.index("while remaining:"))

    def test_mismatch_raises_before_position_read_and_move(self):
        check = self.step5.index("if U_now != U_exp: raise QueueChanged")
        self.assertLess(self.step5.index("U_now = str(c.get_queue(0,1).update_id)"), check)
        self.assertLess(check, self.step5.index("pos = int(c.get_current_track_info()"))
        self.assertLess(check, self.step5.index("ReorderTracksInQueue"))

    def test_move_uses_expected_and_rereads_after_it(self):
        self.assertIn('("UpdateID",int(U_exp))', self.step5)
        self.assertNotIn('("UpdateID",int(U_now))', self.step5)
        apply = self.step5.index("apply the move to `model`")
        reread = self.step5.index("U_exp = str(c.get_queue(0,1).update_id)")
        self.assertLess(apply, reread)
        self.assertLess(reread, self.step5.index("between_steps()"))
        self.assertIn("4 calls when it moves", self.step5)

    def test_restore_inherits_step5(self):
        self.assertIn("exactly as 9.5.2 step 5", self.restore)

    def test_call_counts_consistent(self):
        self.assertNotIn("× 3 calls ≈ 177", self.text)
        self.assertNotIn("≈ 177 calls", self.text)
        self.assertIn("59 moves × 4 calls ≈ 236 SOAP calls", self.text)
        self.assertEqual(59 * 4, 236)

    def test_code_matches_spec(self):
        src = SONOS.read_text(encoding="utf-8")
        body = _section(src, "def _realise(", "\n    def ")
        read = body.index("update_id = str(coordinator.get_queue(start=0, max_items=1).update_id)")
        check = body.index("if update_id != expected:")
        self.assertLess(read, check)
        self.assertLess(check, body.index("self._position(coordinator.get_current_track_info())"))
        self.assertRegex(body, r"expected = str\(coordinator\.get_queue\(start=0, max_items=1\)\.update_id\)")
        self.assertGreaterEqual(src.count("step, snapshot.revision)"), 2)  # 9.5.2 and 9.5.3 both seed it


if __name__ == "__main__":
    unittest.main()

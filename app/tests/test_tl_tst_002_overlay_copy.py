"""TL-TST-002 follow-up: the hands-on copy that was cut with an ellipsis on the knob's glass now fits.

With the hold flow running to completion, test_every_instruction_fits_the_glass reached its synthetic part and
showed notes cut on the End stop test's Seek overlay (the Yes/No legend, the ask() retry, the first push of a
repeat) and on the deferred hold's notice ("Once more · attempt 10 of 10"). No window, port or network."""
import inspect
import unittest

from test_cc5_tooling import (FakeFirmware54, companion_device, copy_json, load_script, needs_tooling,
                              prompt_fit_problems, t)


@needs_tooling
class OverlayCopyFitsTests(unittest.TestCase):
    def setUp(self):
        self.module = load_script("check_nanod_cc5.py")
        self.device = companion_device()
        self.caps = {**FakeFirmware54().capabilities(), "glyphs": "latin-ext-a"}
        v4, _ = t.fixture_frames()
        self.seek = self.device._frame({**copy_json(v4["v4-tracks-no-previous"]), "layout": "seek",
                                        "ring": {"style": "lap", "value": 0, "index": 17, "count": 20}}, self.caps)

    def seek_problems(self, say, note):
        frame = t.overlay({**self.seek, "id": 5}, "STEP 10 OF 10", say, "", note, "error")
        return prompt_fit_problems(self.device._frame(frame, self.caps))

    def notice_problems(self, note):
        frame = t.prompt_frame("STEP 10 OF 10", "Hold Button 1", "Hold until it says Let go", note)
        return prompt_fit_problems(self.device._frame({**frame, "id": 5}, self.caps))

    def test_the_old_copy_was_cut(self):
        """The finding reproduces with the copy it replaced (so the fit check below can fail)."""
        for note in ("Yes: Button 4 · No: Button 1", "That was Button 4 · Yes 4 · No 1",
                     "Again · Push 1 of 5, then let go"):
            self.assertNotEqual(self.seek_problems("Did you push?", note), [], note)
        self.assertNotEqual(self.notice_problems("Once more · attempt 10 of 10"), [])

    def test_yes_no_legend_and_its_retry_fit_the_seek_overlay(self):
        for question in ("Did you push?", "Pushed past 0:00?"):
            self.assertEqual(self.seek_problems(question, t.PROMPT_YES_NO), [])
            for n in (2, 3):   # Buttons 1 and 4 are the answers
                note = t.PROMPT_YES_NO_RETRY.format(n=n)
                self.assertIn(f"Button {n}", note)
                self.assertTrue(note.endswith("Yes 4 · No 1"), note)
                self.assertEqual(self.seek_problems(question, note), [], note)
        self.assertIn("Button 4", t.PROMPT_YES_NO)
        self.assertIn("Button 1", t.PROMPT_YES_NO)
        self.assertEqual(self.notice_problems(t.PROMPT_YES_NO), [])

    def test_ask_retries_with_the_short_legend(self):
        source = inspect.getsource(t.KnobPrompter.ask)
        self.assertIn("PROMPT_YES_NO_RETRY.format(n=m['kd'] + 1)", source)
        self.assertNotIn("That was Button", source)

    def test_every_push_note_fits_and_names_its_push(self):
        pushes = self.module.PUSHES
        for n in range(1, pushes + 1):
            for again in ("", "Again · "):
                note = self.module.push_note(n, again)
                self.assertTrue(note.startswith(f"{again if n == 1 else ''}Push {n} of {pushes}"), note)
                self.assertTrue(note.endswith("let go"), note)
                self.assertEqual(self.seek_problems("Push past the end", note), [], note)
        self.assertEqual(self.module.push_note(2, "Again · "), f"Push 2 of {pushes}, then let go")
        self.assertIn("push_note(n, again)", inspect.getsource(self.module.push_test))

    def test_deferred_attempt_note_fits_up_to_ten(self):
        attempts = self.module.DEFERRED_ATTEMPTS
        for n in range(2, attempts + 1):
            note = self.module.DEFERRED_AGAIN.format(n=n, of=attempts)
            self.assertEqual(note, f"Again · attempt {n} of {attempts}")
            self.assertEqual(self.notice_problems(note), [], note)
        self.assertIn("DEFERRED_AGAIN.format(n=n + 1, of=attempts_max)",
                      inspect.getsource(self.module.deferred_hold))


if __name__ == "__main__":
    unittest.main()

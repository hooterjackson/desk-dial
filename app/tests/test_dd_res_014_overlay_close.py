"""DD-RES-014: MusicOverlay.close(timeout) keeps the stage and the art service inside ONE budget
(the art gets only what the stage close left of the shared deadline, never another timeout/2), and
a second close returns at once without touching the stage or the art again. Headless: fakes only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.music_overlay import MusicOverlay  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Presenter:
    def __init__(self, clock, spend, result=True, boom=False):
        self.clock, self.spend, self.result, self.boom = clock, spend, result, boom
        self.calls = []

    def close(self, timeout):
        self.calls.append(timeout)
        self.clock.t += self.spend
        if self.boom:
            raise RuntimeError("stuck")
        return self.result


class Art:
    def __init__(self):
        self.calls = []
        self.stats = {}

    def close(self, timeout):
        self.calls.append(timeout)


class OverlayCloseBudget(unittest.TestCase):
    def test_art_gets_only_the_time_left(self):
        clock = Clock()
        pres, art = Presenter(clock, spend=1.5), Art()
        ov = MusicOverlay(pres, art=art, clock=clock)
        self.assertTrue(ov.close(2.0))
        self.assertEqual(pres.calls, [2.0])
        self.assertEqual(len(art.calls), 1)
        self.assertAlmostEqual(art.calls[0], 0.5)

    def test_budget_spent_gives_art_zero_not_negative(self):
        clock = Clock()
        pres, art = Presenter(clock, spend=3.0), Art()
        ov = MusicOverlay(pres, art=art, clock=clock)
        ov.close(2.0)
        self.assertEqual(art.calls, [0.0])

    def test_quick_stage_close_leaves_art_the_rest(self):
        clock = Clock()
        pres, art = Presenter(clock, spend=0.0), Art()
        MusicOverlay(pres, art=art, clock=clock).close(2.0)
        self.assertAlmostEqual(art.calls[0], 2.0)

    def test_no_presenter_art_gets_whole_budget(self):
        art = Art()
        self.assertTrue(MusicOverlay(None, art=art, clock=Clock()).close(1.0))
        self.assertAlmostEqual(art.calls[0], 1.0)

    def test_second_close_returns_at_once(self):
        clock = Clock()
        pres, art = Presenter(clock, spend=1.0, result=False), Art()
        ov = MusicOverlay(pres, art=art, clock=clock)
        self.assertFalse(ov.close(2.0))
        self.assertFalse(ov.close(2.0), "the second close reports the first result")
        self.assertEqual(len(pres.calls), 1)
        self.assertEqual(len(art.calls), 1)

    def test_failing_stage_close_still_closes_art_once(self):
        clock = Clock()
        pres, art = Presenter(clock, spend=0.5, boom=True), Art()
        ov = MusicOverlay(pres, art=art, clock=clock)
        self.assertFalse(ov.close(2.0))
        self.assertAlmostEqual(art.calls[0], 1.5)
        self.assertFalse(ov.close(2.0))
        self.assertEqual((len(pres.calls), len(art.calls)), (1, 1))


if __name__ == "__main__":
    unittest.main()

"""DD-BUG-050: a Sonos Volume Limit clamps SetGroupVolume; the adapter must report the clamped
level instead of polling 2 s and raising "not confirmed" on every detent above the limit.

Headless: the FakeSpeaker of test_cc_music.py on a fake clock; no network, no Sonos, no Tk.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.sonos import READBACK_S, SonosAdapter, SonosError  # noqa: E402
from test_cc_music import FakeClock, FakeSpeaker, MemoryStore  # noqa: E402

DOC_HOST = "192.0.2.1"   # RFC 5737 documentation address; the fake factory never connects


class ClampedGroup:
    """A group whose speaker Volume Limit clamps writes; the new level shows after `lag` reads."""

    def __init__(self, group, limit, lag=2):
        self.uid, self.coordinator, self.members = group.uid, group.coordinator, group.members
        self.limit, self.lag = limit, lag
        self.current, self.pending, self.reads_left = group.volume, None, 0
        self.writes = []

    @property
    def volume(self):
        if self.pending is not None:
            if self.reads_left <= 0:
                self.current, self.pending = self.pending, None
            self.reads_left -= 1
        return self.current

    @volume.setter
    def volume(self, value):
        self.writes.append(value)
        self.pending = min(value, 100 if self.limit is None else self.limit)
        self.reads_left = self.lag


class StuckGroup(ClampedGroup):
    """A group that ignores every write (its level never moves)."""

    @property
    def volume(self):
        return self.current

    @volume.setter
    def volume(self, value):
        self.writes.append(value)


def rig(limit=60, start=50, lag=2):
    clock, speaker = FakeClock(), FakeSpeaker()
    speaker.group.volume = start
    adapter = SonosAdapter(DOC_HOST, soco_factory=lambda host: speaker,
                           share_link_factory=lambda value: value, recovery_store=MemoryStore(),
                           shuffle_store=MemoryStore(), clock=clock.now, sleep=clock.sleep)
    state = adapter.read_state()
    speaker.group = ClampedGroup(speaker.group, limit, lag)
    return adapter, speaker, clock, state


class VolumeLimitTests(unittest.TestCase):
    def test_set_volume_above_speaker_limit_reports_the_clamped_level(self):
        adapter, speaker, clock, state = rig(limit=60, start=50)
        began = clock.now()
        result = adapter.set_volume(80, state["group_revision"])
        self.assertEqual(result["volume"], 60)
        self.assertEqual(speaker.group.writes, [80], "the write is never replayed")
        self.assertLess(clock.now() - began, 1.0, "no 2 s wait holding the adapter lock")

    def test_later_steps_at_the_limit_are_accepted_quickly(self):
        adapter, speaker, clock, state = rig(limit=60, start=58)
        self.assertEqual(adapter.set_volume(61, state["group_revision"])["volume"], 60)
        for target in (61, 62, 63):
            began = clock.now()
            self.assertEqual(adapter.set_volume(target, state["group_revision"])["volume"], 60)
            self.assertLess(clock.now() - began, 1.0)

    def test_a_raised_limit_is_forgotten(self):
        adapter, speaker, clock, state = rig(limit=60, start=58)
        adapter.set_volume(70, state["group_revision"])
        speaker.group.limit = None
        self.assertEqual(adapter.set_volume(70, state["group_revision"])["volume"], 70)

    def test_unmoved_volume_without_a_known_limit_still_errors(self):
        adapter, speaker, clock, state = rig(limit=50, start=50)
        began = clock.now()
        with self.assertRaisesRegex(SonosError, "not confirmed"):
            adapter.set_volume(60, state["group_revision"])
        self.assertGreaterEqual(clock.now() - began, READBACK_S)

    def test_lowering_and_exact_targets_are_unchanged(self):
        adapter, speaker, clock, state = rig(limit=60, start=50)
        self.assertEqual(adapter.set_volume(40, state["group_revision"])["volume"], 40)
        self.assertEqual(adapter.set_volume(60, state["group_revision"])["volume"], 60)

    def test_one_detent_at_a_time_up_to_and_past_the_limit(self):
        """The reported case: 59 -> 60 lands exactly on the limit, then every later detent reads
        back unchanged at 60. Each returns 60 in under 1 s without raising."""
        adapter, speaker, clock, state = rig(limit=60, start=59)
        for target in (60, 61, 62, 63):
            with self.subTest(target=target):
                began = clock.now()
                self.assertEqual(adapter.set_volume(target, state["group_revision"])["volume"], 60)
                self.assertLess(clock.now() - began, 1.0, "no 2 s wait holding the adapter lock")
        self.assertEqual(speaker.group.writes, [60, 61, 62, 63], "each write sent once, never replayed")

    def test_lowering_that_does_not_move_still_errors(self):
        adapter, speaker, clock, state = rig(limit=60, start=59)
        adapter.set_volume(60, state["group_revision"])
        adapter.set_volume(61, state["group_revision"])          # learns the limit at 60
        speaker.group = StuckGroup(speaker.group, 60)
        began = clock.now()
        with self.assertRaisesRegex(SonosError, "not confirmed"):
            adapter.set_volume(55, state["group_revision"])
        self.assertGreaterEqual(clock.now() - began, READBACK_S)

    def test_after_a_downward_step_an_unmoved_upward_write_still_errors_once(self):
        """Only a start the previous UPWARD step confirmed counts: a level reached going down (or
        set by another app) is not evidence of a limit, so the first unmoved step still errors."""
        adapter, speaker, clock, state = rig(limit=None, start=70)
        adapter.set_volume(50, state["group_revision"])
        speaker.group.limit = 50
        with self.assertRaisesRegex(SonosError, "not confirmed"):
            adapter.set_volume(51, state["group_revision"])

    def test_after_a_restart_only_the_first_step_at_the_limit_errors(self):
        adapter, speaker, clock, state = rig(limit=60, start=60)
        with self.assertRaisesRegex(SonosError, "not confirmed"):
            adapter.set_volume(61, state["group_revision"])
        for target in (61, 62):
            began = clock.now()
            self.assertEqual(adapter.set_volume(target, state["group_revision"])["volume"], 60)
            self.assertLess(clock.now() - began, 1.0)

    def test_a_slow_coordinator_is_not_mistaken_for_the_limit(self):
        """No limit, but the coordinator takes 0.4 s to report the new level after an upward step
        from a confirmed level: the real level is confirmed, not the start."""
        adapter, speaker, clock, state = rig(limit=None, start=59, lag=2)
        adapter.set_volume(60, state["group_revision"])
        speaker.group.lag = 8          # 8 reads x 50 ms = 0.4 s, under VOLUME_UNMOVED_STABLE_S
        self.assertEqual(adapter.set_volume(61, state["group_revision"])["volume"], 61)


if __name__ == "__main__":
    unittest.main()

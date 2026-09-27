"""ALIVE.md section 10.2 and rulings R3/R4 on the host (desktop v7): companion state.

* sonos.py: ``_state`` adds the track's ``duration`` from the same read-only
  get_current_track_info() call as ``position``;
* runtime.sonos_time_ms: the Sonos "H:MM:SS" position/duration parser (unknown -> None);
* controller.py frame content: ``playing`` on Home frames from the confirmed transport
  only (R4, with the album-start hold; K2 M16: omitted while ``Starting…`` and on the
  ``started`` frame, K3 section 5.1.2) and ``feedback.skip`` on a Tracks skip's ``ok``
  (D9); an entry frame and the first post-ready frame stay equal with an ``alive`` knob;
* runtime.SongProgress / Runtime._poll_progress: the section 3 ``progress`` triggers
  (first opportunity, track change, play/pause change, R3 re-send on becoming PLAYING,
  a seek > 2 s, every 30 s while playing, dur 0 when nothing plays), posted only to a
  knob with ``alive`` and written with the frame of the same poll; end to end through a
  real DeviceBridge on an in-memory knob;
* runtime.led_tuning / Runtime.apply_led_tuning: settings.json ``led_drive`` / ``led_dither``
  (validated, never logged by value);
* ``limit`` events: a knob touch (the floating knob's summon path) and, desktop v7 (K3
  section 10.4), ``Controller.limit`` -- never a position or a button.

No Tk, no port, no network and no thread pool (stand-in executors, fake clocks).
"""
from pathlib import Path
from queue import Queue
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center import device, presentation as P  # noqa: E402
from control_center import runtime as runtime_module  # noqa: E402
from control_center.alive_lights import AliveLights  # noqa: E402
from control_center.controller import ALBUM_START_HOLD_SECONDS, Controller  # noqa: E402
from control_center.device import DeviceBridge  # noqa: E402
from control_center.runtime import (PROGRESS_REFRESH_SECONDS, PROGRESS_SEEK_MS, Runtime,  # noqa: E402
                                    SongProgress, led_tuning, sonos_time_ms)
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows  # noqa: E402
from control_center.sonos import SonosAdapter  # noqa: E402
from test_alive_wire import AL4, P4, WireSerial  # noqa: E402
from test_cc_controller import Clock, ControllerFixture, ManualExecutor, state  # noqa: E402
from test_cc_device import Clock as BridgeClock  # noqa: E402
from test_cc_enter_frames import Monotonic, RuntimeCase, SpyWindows  # noqa: E402
from test_cc_music import FakeSpeaker, MemoryStore  # noqa: E402

ABSENT = "absent"
HOME_LAYOUTS = P.ALIVE_PLAYING_LAYOUTS


def playing_of(frame):
    return frame.get("playing", ABSENT)


class AliveDevice:
    """DeviceBridge stand-in with the alive host API: records posts and tunings."""

    def __init__(self, alive=True):
        self.events = Queue()
        self.commands = []
        self.media_capability = None
        self.alive = alive
        self.progress = []
        self.tuning = []

    def submit(self, *command):
        self.commands.append(command)

    def post_progress(self, pos_ms, dur_ms):
        self.progress.append((pos_ms, dur_ms))

    def set_led_tuning(self, drive=None, dither=None):
        self.tuning.append((drive, dither))

    def frames(self):
        return [command[1] for command in self.commands if command[0] == "frame"]


# ------------------------------------------------------------------------------------ sonos
class SonosDurationTests(unittest.TestCase):
    def adapter(self, **track):
        speaker = FakeSpeaker()
        speaker.track.update(track)
        calls = []
        read = speaker.get_current_track_info

        def counted():
            calls.append(1)
            return read()

        speaker.get_current_track_info = counted
        adapter = SonosAdapter("192.168.1.50", soco_factory=lambda host: speaker,
                               share_link_factory=lambda value: value, recovery_store=MemoryStore())
        return adapter, speaker, calls

    def test_state_carries_the_duration_of_the_same_read_only_track_read(self):
        adapter, speaker, calls = self.adapter(position="0:01:23", duration="0:04:05")
        state = adapter.read_state()
        self.assertEqual((state["position"], state["duration"]), ("0:01:23", "0:04:05"))
        self.assertEqual(len(calls), 1, "one get_current_track_info() per read, as before")
        self.assertEqual((speaker.played, speaker.skips, speaker.removals, speaker.seeks), ([], [], [], []))
        self.assertEqual(speaker.group.volume, 25)
        self.assertEqual((sonos_time_ms(state["position"]), sonos_time_ms(state["duration"])), (83000, 245000))

    def test_a_missing_or_not_implemented_duration_is_unknown(self):
        adapter, _speaker, _calls = self.adapter()
        self.assertEqual(adapter.read_state()["duration"], "")
        adapter, _speaker, _calls = self.adapter(position="NOT_IMPLEMENTED", duration="NOT_IMPLEMENTED")
        state = adapter.read_state()
        self.assertEqual((state["position"], state["duration"]), ("NOT_IMPLEMENTED", "NOT_IMPLEMENTED"))
        self.assertEqual((sonos_time_ms(state["position"]), sonos_time_ms(state["duration"])), (None, None))

    def test_command_results_carry_it_too(self):
        adapter, speaker, _calls = self.adapter(duration="0:03:00")
        state = adapter.read_state()
        result = adapter.transport("next", state["group_revision"], state["track_id"])
        self.assertEqual(speaker.skips, ["next"])
        self.assertEqual(result["duration"], "0:03:00")


class SonosTimeTests(unittest.TestCase):
    def test_values(self):
        cases = {"0:00:00": 0, "0:03:25": 205000, "00:03:25": 205000, "1:02:03": 3723000,
                 "0:1:5": 65000, " 0:01:00 ": 60000, "0:03:25.5": 205500, "0:03:25.250": 205250,
                 "0:00:01.1/2": 1500, "0:00:01.0/3": 1000, "24:00:00": P.ALIVE_PROGRESS_MAX_MS,
                 "23:59:59.999": P.ALIVE_PROGRESS_MAX_MS - 1}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(sonos_time_ms(text), expected)

    def test_unknown(self):
        for value in ("NOT_IMPLEMENTED", "", "   ", None, 0, 205, 1.5, b"0:03:25", ["0:03:25"],
                      "0:60:00", "0:00:60", "24:00:01", "99999:00:00", "-0:01:00", "+0:01:00",
                      "0:03", "3:25", "0:03:25:00", "0:03:25.", "0:03:25.x", "0:00:01.2/2",
                      "0:00:01.1/0", "0:03:25/2", "abc", "0:0a:25", "١:00:00", "0：03：25"):
            with self.subTest(value=value):
                self.assertIsNone(sonos_time_ms(value))


# ---------------------------------------------------------------------- controller: playing
class PlayingFrameTests(ControllerFixture):
    def home(self):
        """`playing` of the Home frame; the entry (post-ready) projection must agree."""
        frame = self.c.frame()
        self.assertIn(frame["layout"], HOME_LAYOUTS)
        self.assertEqual(playing_of(frame), playing_of(self.c.control()["frame"]))
        return playing_of(frame)

    def test_only_the_confirmed_transport(self):
        for playback, expected in (("PLAYING", True), ("PAUSED_PLAYBACK", False), ("STOPPED", False),
                                   ("TRANSITIONING", ABSENT), ("UNKNOWN", ABSENT),
                                   ("NO_MEDIA_PRESENT", ABSENT), (None, ABSENT), ("PLAYING", True)):
            with self.subTest(playback=playback):
                self.publish(state(playback=playback))
                self.assertEqual(self.home(), expected)

    def test_before_the_first_read_and_while_sonos_is_offline_it_is_omitted(self):
        fresh = Controller(clock=self.clock)
        self.assertEqual(playing_of(fresh.frame()), ABSENT)            # "Looking for Sonos…"
        self.publish(state(playback="PLAYING"))
        self.assertIs(self.home(), True)
        self.publish(state(online=False, playback="PLAYING"))          # the last state, offline
        self.assertEqual((self.c.frame()["layout"], self.home()), ("notice", ABSENT))
        self.publish(state(playback="PAUSED_PLAYBACK"))
        self.assertIs(self.home(), False)
        self.c.complete(self.c.request("state"), error="Sonos is unavailable")
        self.assertEqual(self.home(), ABSENT)

    def test_only_home_frames_carry_it(self):
        self.publish(state(playback="PLAYING"))
        self.tracks(2)
        self.assertEqual(playing_of(self.c.frame()), ABSENT)
        self.c.button(0)                                   # Back: Home
        self.assertIs(self.home(), True)
        self.recent()
        self.assertEqual(playing_of(self.c.frame()), ABSENT)
        self.c.button(0)
        self.open_windows()
        self.assertEqual(playing_of(self.c.frame()), ABSENT)

    def test_every_home_layout_carries_it(self):
        self.publish(state(playback="PLAYING", can_pause=True))
        self.assertEqual((self.c.frame()["layout"], self.home()), ("nowPlaying", True))
        self.publish(state(playback="STOPPED", can_play=True))
        self.assertEqual((self.c.frame()["layout"], self.home()), ("idle", False))
        self.c.position(40)
        self.assertEqual((self.c.frame()["layout"], self.home()), ("volume", False))

    def test_a_pending_home_command_never_changes_it(self):
        self.publish(state(playback="PLAYING", can_pause=True))
        self.c.button(0)
        pause = self.one("transport")
        self.assertEqual(pause["direction"], "pause")
        self.assertIs(self.home(), True, "confirmed state only: the pause is still out")
        self.c.complete(pause["request"], state(playback="PAUSED_PLAYBACK", can_play=True))
        self.assertIs(self.home(), False)


class AlbumStartTests(ControllerFixture):
    """R4: `playing` stays omitted after an album start until PLAYING is confirmed; K2 M16 (K3
    section 5.1.2): also on every Home frame while `Starting…` and on the `started` frame."""

    def start_album(self, result, index=2):
        """Recent Play (hybrid, K3 section 8): Home at once with `Starting…`; returns the first
        frame after the result (the one carrying the `started` moment on success)."""
        self.publish(state(playback="PAUSED_PLAYBACK", can_play=True))
        self.assertIs(playing_of(self.c.frame()), False)
        self.recent()
        self.c.position(index)
        self.c.button(3)
        play = self.one("play_items")
        self.assertEqual(self.c.screen.mode, "home")
        self.assertEqual(playing_of(self.c.frame()), ABSENT, "omitted while Starting…")
        self.c.complete(play["request"], result)
        return self.c.frame()

    def test_the_ok_frame_omits_playing_until_playing_is_confirmed(self):
        frame = self.start_album(state(playback="STOPPED", can_play=True))
        self.assertEqual((frame["mode"], frame["layout"], frame["feedback"]["kind"], frame["feedback"]["moment"]),
                         ("VOLUME", "idle", "ok", "started"))
        self.assertNotIn("skip", frame["feedback"])
        self.assertEqual(playing_of(frame), ABSENT, "the album start's started frame")
        self.assertEqual(playing_of(self.c.frame()), ABSENT, "the R4 hold")
        for playback in ("PAUSED_PLAYBACK", "TRANSITIONING", "STOPPED"):
            self.publish(state(playback=playback, can_play=True))
            self.assertEqual(playing_of(self.c.frame()), ABSENT, playback)
        self.publish(state(playback="PLAYING", can_pause=True))
        self.assertIs(playing_of(self.c.frame()), True, "the first confirmed playing")
        self.publish(state(playback="PAUSED_PLAYBACK", can_play=True))
        self.assertIs(playing_of(self.c.frame()), False, "the hold ended with PLAYING")

    def test_a_start_confirmed_at_once_carries_true_after_the_started_frame(self):
        frame = self.start_album(state(playback="PLAYING", can_pause=True))
        self.assertEqual((frame["feedback"]["kind"], frame["feedback"]["moment"]), ("ok", "started"))
        self.assertEqual(playing_of(frame), ABSENT, "M16: never cuts the started wash with Fill")
        self.assertIs(playing_of(self.c.frame()), True, "returns on the next Home frame")

    def test_the_hold_ends_after_its_deadline(self):
        self.start_album(state(playback="STOPPED", can_play=True))
        self.clock.advance(ALBUM_START_HOLD_SECONDS - 0.01)
        self.assertEqual(playing_of(self.c.frame()), ABSENT)
        self.clock.advance(0.02)
        self.assertIs(playing_of(self.c.frame()), False, "a start that never played is not playing")

    def test_a_home_play_press_ends_the_hold(self):
        self.start_album(state(playback="STOPPED", can_play=True))
        self.c.drain()
        self.c.button(0)
        play = self.one("transport")
        self.assertEqual(play["direction"], "play")
        self.assertIs(playing_of(self.c.frame()), False, "the confirmed STOPPED again")
        self.c.complete(play["request"], state(playback="PLAYING", can_pause=True))
        self.assertIs(playing_of(self.c.frame()), True)

    def test_a_failed_album_start_holds_nothing(self):
        self.publish(state(playback="PAUSED_PLAYBACK", can_play=True))
        self.recent()
        self.c.button(3)
        play = self.one("play_items")
        self.c.complete(play["request"], error="The selected library item could not play")
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.c.screen.mode, "home")
        self.assertIs(playing_of(self.c.frame()), False)

    def test_home_1_is_ignored_while_starting(self):
        self.publish(state(playback="PAUSED_PLAYBACK", can_play=True))
        self.recent()
        self.c.button(3)
        play = self.one("play_items")
        self.c.button(0)                                   # Home 1 while Starting…: ignored (S01:86)
        self.assertFalse(self.effects("transport"))
        self.assertEqual(playing_of(self.c.frame()), ABSENT)
        self.c.complete(play["request"], state(playback="STOPPED", can_play=True))
        self.assertEqual(self.c.frame()["feedback"]["kind"], "ok")
        self.assertEqual(playing_of(self.c.frame()), ABSENT, "false -> absent -> true: never a fill")
        self.publish(state(playback="PLAYING", can_pause=True))
        self.assertIs(playing_of(self.c.frame()), True)


# ------------------------------------------------------------------ controller: feedback.skip
class SkipFeedbackTests(ControllerFixture):
    def skip(self, index, result=None, error=None):
        if self.c.screen.mode == "tracks":
            self.c.position(index)                         # a skip keeps Tracks (recentred)
        else:
            self.tracks(index)
        self.c.button(3)
        effect = self.one("transport")
        self.c.complete(effect["request"], result if error is None else None, error)
        return effect

    def test_a_tracks_skip_ok_names_its_direction(self):
        self.assertEqual(self.skip(2, state(track_id="t2"))["direction"], "next")
        self.assertEqual(self.c.frame()["feedback"], {"kind": "ok", "seq": 1, "skip": 1})
        self.assertEqual(self.skip(0, state(track_id="t1"))["direction"], "previous")
        self.assertEqual(self.c.frame()["feedback"], {"kind": "ok", "seq": 2, "skip": -1})

    def test_a_failed_skip_has_no_direction(self):
        self.skip(2, error="Sonos did not skip")
        self.assertEqual(self.c.frame()["feedback"], {"kind": "err", "seq": 1})

    def test_other_oks_have_no_direction(self):
        self.recent()
        self.c.button(3)
        play = self.one("play_items")
        self.c.complete(play["request"], state(title="Album 0", playback="PLAYING"))
        feedback = self.c.frame()["feedback"]
        self.assertEqual((feedback["kind"], feedback["seq"], feedback["moment"]), ("ok", 1, "started"))
        self.assertNotIn("skip", feedback)
        self.open_windows()
        self.c.position(2)
        self.c.button(3)
        activate = self.one("windows_activate")
        self.c.complete(activate["request"], True)
        self.assertEqual(self.c.frame()["feedback"], {"kind": "ok", "seq": 2})

    def test_a_skip_that_lands_after_leaving_tracks_keeps_its_direction(self):
        self.tracks(0)
        self.c.button(3)
        effect = self.one("transport")
        self.c.button(0)                                   # Back: Home before the skip finished
        self.c.complete(effect["request"], state(track_id="t0"))
        self.assertEqual(self.c.frame()["feedback"], {"kind": "ok", "seq": 1, "skip": -1})

    def test_the_bridge_sends_them_only_to_an_alive_knob(self):
        self.publish(state(playback="PLAYING"))
        self.skip(2, state(track_id="t2", playback="PLAYING"))
        self.c.button(0)                                   # Back: Home
        frame = self.c.frame()
        self.assertIs(frame["playing"], True)
        alive = device._frame(frame, AL4)
        self.assertEqual((alive["playing"], alive["feedback"]), (True, {"kind": "ok", "seq": 1, "skip": 1}))
        for caps in (P4, {"controlCenter": 1, "presentation": 2}):
            with self.subTest(caps=caps):
                plain = device._frame(frame, caps)
                self.assertNotIn("playing", plain)
                self.assertEqual(plain.get("feedback", {"kind": "ok", "seq": 1}), {"kind": "ok", "seq": 1})


# ------------------------------------------------------------------------ SongProgress (pure)
def sonos_state(playback="PLAYING", track="t1", position="0:01:00", duration="0:04:00", online=True):
    return {"online": online, "playback": playback, "track_id": track, "position": position, "duration": duration}


class SongProgressTests(unittest.TestCase):
    def setUp(self):
        self.p = SongProgress()

    def see(self, at, **reading):
        self.p.observe(sonos_state(**reading), at)

    def test_nothing_before_a_reading(self):
        self.assertIsNone(self.p.update(100.0))

    def test_the_first_update_posts_the_extrapolated_position(self):
        self.see(100.0)
        self.assertEqual(self.p.update(100.4), (60400, 240000))
        self.assertIsNone(self.p.update(100.5))

    def test_every_30_s_while_playing_only(self):
        self.see(100.0)
        self.p.update(100.0)
        self.see(101.0, position="0:01:01")                    # consistent with the extrapolation
        self.assertIsNone(self.p.update(101.0))
        self.assertIsNone(self.p.update(100.0 + PROGRESS_REFRESH_SECONDS - 0.01))
        self.assertEqual(self.p.update(100.0 + PROGRESS_REFRESH_SECONDS), (90000, 240000))
        self.assertIsNone(self.p.update(131.0))
        paused = SongProgress()
        paused.observe(sonos_state(playback="PAUSED_PLAYBACK"), 100.0)
        self.assertEqual(paused.update(100.0), (60000, 240000))
        self.assertIsNone(paused.update(1000.0), "never refreshed while paused")

    def test_a_track_change(self):
        self.see(100.0)
        self.p.update(100.0)
        self.see(110.0, track="t2", position="0:00:01", duration="0:03:00")
        self.assertEqual(self.p.update(110.5), (1500, 180000))
        self.see(111.0, track="t2", position="0:00:02", duration="0:03:01")   # the length became exact
        self.assertEqual(self.p.update(111.0), (2000, 181000))

    def test_a_play_pause_change(self):
        self.see(100.0)
        self.p.update(100.0)
        self.see(105.0, playback="PAUSED_PLAYBACK", position="0:01:05")
        self.assertEqual(self.p.update(105.3), (65000, 240000), "not extrapolated while paused")
        self.see(200.0, playback="PAUSED_PLAYBACK", position="0:01:05")        # unchanged: no post
        self.assertIsNone(self.p.update(200.0))
        self.see(300.0, position="0:01:05")
        self.assertEqual(self.p.update(300.2), (65200, 240000))

    def test_r3_resend_when_the_transport_becomes_playing_again(self):
        self.see(100.0)
        self.p.update(100.0)
        self.see(101.0, playback="TRANSITIONING", position="0:01:01")
        self.assertIsNone(self.p.update(101.0), "unknown: nothing posted, the knob keeps its latch")
        self.see(102.0, position="0:01:02")
        self.assertEqual(self.p.update(102.0), (62000, 240000), "unknown -> PLAYING re-sends")
        self.see(103.0, online=False, position="0:01:03")
        self.assertIsNone(self.p.update(103.0))
        self.see(104.0, position="0:01:04")
        self.assertEqual(self.p.update(104.0), (64000, 240000), "offline -> PLAYING re-sends")

    def test_a_seek_is_a_reading_more_than_2_s_off(self):
        self.see(100.0)
        self.p.update(100.0)                                         # 60000 at 100
        self.see(110.0, position="0:01:12")                         # expected 70000: 2000 off
        self.assertEqual(PROGRESS_SEEK_MS, 2000)
        self.assertIsNone(self.p.update(110.0), "within the tolerance")
        self.see(111.0, position="0:01:14")                         # expected 71000: 3000 off
        self.assertEqual(self.p.update(111.2), (74200, 240000))
        self.see(112.0, position="0:00:10")                         # backwards
        self.assertEqual(self.p.update(112.0), (10000, 240000))

    def test_a_seek_while_paused(self):
        self.see(100.0, playback="PAUSED_PLAYBACK")
        self.p.update(100.0)
        self.see(150.0, playback="PAUSED_PLAYBACK", position="0:01:01")
        self.assertIsNone(self.p.update(150.0))
        self.see(151.0, playback="PAUSED_PLAYBACK", position="0:02:00")
        self.assertEqual(self.p.update(151.0), (120000, 240000))

    def test_nothing_playing_posts_dur_0_once(self):
        self.see(100.0)
        self.p.update(100.0)
        self.see(101.0, playback="STOPPED", position="0:00:00")
        self.assertEqual(self.p.update(101.0), (0, 0))
        self.see(102.0, playback="STOPPED", track="t2", position="0:00:00")
        self.assertIsNone(self.p.update(102.0))
        self.see(103.0, track="radio", position="NOT_IMPLEMENTED", duration="NOT_IMPLEMENTED")
        self.assertIsNone(self.p.update(103.0), "a stream has no length: still nothing to show")
        self.see(104.0, track="t3", position="0:00:01")
        self.assertEqual(self.p.update(104.0), (1000, 240000))

    def test_a_stream_first(self):
        for reading in ({"position": "NOT_IMPLEMENTED", "duration": "NOT_IMPLEMENTED"},
                        {"position": "", "duration": ""}, {"duration": "0:00:00"},
                        {"position": "garbage"}):
            with self.subTest(reading=reading):
                progress = SongProgress()
                progress.observe(sonos_state(**reading), 100.0)
                self.assertEqual(progress.update(100.0), (0, 0))

    def test_an_unknown_transport_posts_nothing(self):
        for reading in ({"online": False}, {"playback": "TRANSITIONING"}, {"playback": "UNKNOWN"}):
            with self.subTest(reading=reading):
                progress = SongProgress()
                progress.observe(sonos_state(**reading), 100.0)
                self.assertIsNone(progress.update(100.0))

    def test_reset_posts_afresh(self):
        self.see(100.0)
        self.p.update(100.0)
        self.assertIsNone(self.p.update(101.0))
        self.p.reset()
        self.assertEqual(self.p.update(101.0), (61000, 240000))
        self.p.reset()
        self.see(102.0, playback="STOPPED")
        self.assertEqual(self.p.update(102.0), (0, 0))

    def test_extrapolation_is_clamped_to_the_duration(self):
        self.see(100.0, position="0:03:59")
        self.assertEqual(self.p.update(110.0), (240000, 240000))
        self.see(111.0, position="0:04:01")                          # Sonos past the end
        self.assertIsNone(self.p.update(111.0), "no seek: both at the end")

    def test_an_unchanged_reading_keeps_the_earlier_time_base(self):
        self.see(100.0)
        self.see(100.9)                                              # the same second read again
        self.assertEqual(self.p.update(101.0), (61000, 240000))

    def test_the_home_playing_rise_re_sends(self):
        """The knob extrapolates only from its Home resume edge (R3): when Home shows a resume
        that was first seen (and posted) on another screen, the position is posted again."""
        self.see(100.0, playback="PAUSED_PLAYBACK")
        self.p.home(False)
        self.assertEqual(self.p.update(100.0), (60000, 240000))
        # Tracks is shown (no home() calls); the Sonos app resumes: R3 posts on that frame.
        self.see(103.0)
        self.assertEqual(self.p.update(103.0), (60000, 240000))
        self.assertIsNone(self.p.update(110.0))
        # Back on Home 22 s later: its frame says playing:true after a Home frame that did not.
        self.p.home(True)
        self.assertEqual(self.p.update(125.0), (82000, 240000))
        self.p.home(True)
        self.assertIsNone(self.p.update(126.0), "only the rise")
        # An R4 hold (Home without `playing`) and then the confirmed start: a rise again.
        self.p.home(None)
        self.assertIsNone(self.p.update(127.0))
        self.p.home(True)
        self.assertEqual(self.p.update(128.0), (85000, 240000))
        # Anything but a bool is "absent".
        self.p.home(1)
        self.p.home(True)
        self.assertEqual(self.p.update(129.0), (86000, 240000))

    def test_a_home_rise_needs_a_playing_transport(self):
        self.see(100.0, playback="PAUSED_PLAYBACK")
        self.p.update(100.0)
        self.p.home(True)                                            # (never with a paused reading)
        self.assertIsNone(self.p.update(101.0))
        self.p.home(False)
        self.see(102.0, playback="STOPPED")
        self.assertEqual(self.p.update(102.0), (0, 0))
        self.p.home(True)
        self.assertIsNone(self.p.update(103.0), "nothing playing: dur 0 was sent once")

    def test_reset_forgets_the_home_playing(self):
        self.see(100.0)
        self.p.home(True)
        self.p.update(100.0)
        self.p.reset()
        self.p.update(100.5)                                         # the new connection's first post
        self.p.home(True)                                            # its first Home frame: a rise
        self.assertEqual(self.p.update(101.0), (61000, 240000))


# ------------------------------------------------------------------- Runtime progress posting
class PlayingSonos(SimulatedSonos):
    def __init__(self):
        super().__init__()
        self.state.update(position="0:01:00", duration="0:04:00")


class RuntimeProgressTests(unittest.TestCase):
    def setUp(self):
        executor = patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.monotonic = Monotonic()
        timer = patch.object(runtime_module.time, "monotonic", self.monotonic)
        timer.start()
        self.addCleanup(timer.stop)
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.sonos = PlayingSonos()
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()                  # the fake clock never advances: no polls
        self.device = AliveDevice()
        self.runtime = Runtime(self.c, self.sonos, SimulatedAppleMusic(), SpyWindows(), self.device)
        self.addCleanup(self.runtime.close)

    def connect(self):
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.runtime.poll()
        self.device.events.put({"kind": "ready", "id": self.c.control_id})
        self.runtime.poll()
        self.assertTrue(self.c.ready)

    def reading(self, **values):
        request = self.c.request("state")
        self.c.drain()
        self.runtime.results.put((request, {**self.sonos.read_state(), **values}, None))

    def test_posted_on_the_first_alive_poll(self):
        self.assertFalse(self.runtime.alive, "not connected")
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.monotonic.now += 0.25
        self.runtime.poll()
        self.assertTrue(self.runtime.alive)
        # The reading is timed at the poll that first saw it (here: this one).
        self.assertEqual(self.device.progress, [(60000, 240000)], "rides in the enter line")
        self.assertEqual(self.device.frames(), [], "the knob is not ready yet")

    def test_a_post_writes_the_frame_of_that_poll_at_once(self):
        self.connect()
        self.assertEqual(self.device.progress, [(60000, 240000)])
        self.device.commands.clear()
        self.monotonic.now += 0.1
        self.runtime.poll()
        self.assertEqual(self.device.frames(), [], "unchanged frame, heartbeat not due")
        self.reading(position="0:02:30")                             # a seek (90 s ahead)
        self.monotonic.now += 0.1
        self.runtime.poll()
        self.assertEqual(self.device.progress[-1], (150000, 240000))
        # The desktop engine gets exactly what the knob got.
        self.assertEqual((self.runtime.last_progress, self.runtime.progress_seq),
                         ((150000, 240000, self.monotonic.now), 2))
        frames = self.device.frames()
        self.assertEqual(len(frames), 1, "written at once with the post")
        self.assertIs(frames[0]["playing"], True)
        self.assertNotIn("progress", frames[0], "the bridge adds the latched fields, not the runtime")

    def test_every_30_s_while_playing_and_on_pause(self):
        self.connect()
        start = self.monotonic.now
        self.device.progress.clear()
        self.monotonic.now = start + PROGRESS_REFRESH_SECONDS
        self.runtime.poll()
        self.assertEqual(self.device.progress, [(60000 + 30000, 240000)])
        self.reading(playback="PAUSED_PLAYBACK", position="0:01:31", can_play=True, can_pause=False)
        self.monotonic.now += 1.0
        self.runtime.poll()
        self.assertEqual(self.device.progress[-1], (91000, 240000))
        self.assertIs(self.device.frames()[-1]["playing"], False)

    def test_nothing_to_post_without_alive(self):
        for device in (AliveDevice(alive=False), AliveDevice(alive=None)):
            with self.subTest(alive=device.alive):
                self.runtime.device = device
                self.device = device
                self.connect()
                self.monotonic.now += PROGRESS_REFRESH_SECONDS
                self.runtime.poll()
                self.assertFalse(self.runtime.alive)
                self.assertEqual(device.progress, [])
                self.assertEqual((self.runtime.last_progress, self.runtime.progress_seq), (None, 0))

    def test_a_device_without_the_alive_api(self):
        from test_cc_controller import FakeDevice
        self.runtime.device = self.device = FakeDevice()
        self.device.media_capability = None
        self.connect()
        self.runtime.poll()
        self.assertFalse(self.runtime.alive)

    def test_a_reconnect_posts_afresh(self):
        self.connect()
        self.assertEqual(len(self.device.progress), 1)
        self.device.events.put({"kind": "disconnected", "message": "Knob disconnected"})
        self.runtime.poll()
        self.assertFalse(self.runtime.alive)
        self.monotonic.now += 2.0
        self.connect()
        self.assertEqual(self.device.progress[-1], (62000, 240000))
        # Both events handled in one poll: still a new connection.
        self.device.events.put({"kind": "disconnected", "message": "Knob disconnected"})
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.device.events.put({"kind": "ready", "id": self.c.control_id + 1})
        self.monotonic.now += 1.0
        self.runtime.poll()
        self.assertEqual(self.device.progress[-1], (63000, 240000))

    def test_nothing_playing_posts_dur_0(self):
        self.sonos.state.update(position="NOT_IMPLEMENTED", duration="NOT_IMPLEMENTED")
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.connect()
        self.assertEqual(self.device.progress, [(0, 0)])

    def ready_current(self):
        """Dispatch the current entry and acknowledge it (the first post-ready frame follows)."""
        self.runtime.poll()
        self.device.events.put({"kind": "ready", "id": self.c.control_id})
        self.runtime.poll()
        self.assertTrue(self.c.ready)

    def paused_then_resumed_on_tracks(self):
        """Paused on Home; the user opens Tracks; the Sonos app resumes (R3 posts on Tracks)."""
        self.sonos.state.update(playback="PAUSED_PLAYBACK", can_play=True, can_pause=False)
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.connect()
        self.assertEqual(self.device.progress, [(60000, 240000)])
        self.assertIs(self.device.frames()[-1]["playing"], False)
        self.c.button(2)                                             # Home 3: Tracks
        self.ready_current()
        self.assertEqual(self.device.frames()[-1]["layout"], "tracks")
        self.reading(playback="PLAYING", position="0:01:00", can_play=False, can_pause=True)
        self.monotonic.now += 1.0
        self.runtime.poll()
        self.assertEqual(self.device.progress, [(60000, 240000)] * 2, "R3: posted on the Tracks frame")
        self.assertNotIn("playing", self.device.frames()[-1])
        return self.monotonic.now

    def test_home_showing_a_resume_seen_elsewhere_re_sends_with_its_first_frame(self):
        resumed = self.paused_then_resumed_on_tracks()
        self.monotonic.now += 20.0
        self.runtime.poll()
        self.assertEqual(len(self.device.progress), 2, "no refresh due yet")
        self.c.button(0)                                             # Back: Home
        self.monotonic.now += 0.1
        self.runtime.poll()                                          # dispatches the Home entry
        entries = [command[1] for command in self.device.commands if command[0] == "enter"]
        self.assertIs(entries[-1]["frame"]["playing"], True, "the knob's Home resume edge")
        self.assertEqual(self.device.progress[2:], [(60000 + round((self.monotonic.now - resumed) * 1000), 240000)],
                         "posted in the poll of the first playing:true Home frame")
        self.device.events.put({"kind": "ready", "id": self.c.control_id})
        self.monotonic.now += 0.1
        self.runtime.poll()
        self.assertIs(self.device.frames()[-1]["playing"], True)
        self.assertEqual(len(self.device.progress), 3, "once")

    def test_home_playing_all_along_needs_no_extra_post(self):
        self.connect()                                               # playing on Home
        self.c.button(2)                                             # Tracks
        self.ready_current()
        self.monotonic.now += 10.0
        self.runtime.poll()
        self.c.button(0)                                             # Back: Home
        self.ready_current()
        self.assertIs(self.device.frames()[-1]["playing"], True)
        self.assertEqual(self.device.progress, [(60000, 240000)], "the knob kept extrapolating")

    def test_the_knob_song_hand_follows_a_resume_seen_elsewhere(self):
        """End to end with the alive engine as the knob runs it: every written line latches the
        pending progress, then renders; on Home, asleep, the song hand shows the true position."""
        log = []
        device = self.device
        submit, post = device.submit, device.post_progress
        device.submit = lambda *command: (log.append(("line", self.monotonic.now, command)), submit(*command))
        device.post_progress = lambda pos, dur: (log.append(("post", self.monotonic.now, (pos, dur))), post(pos, dur))
        resumed = self.paused_then_resumed_on_tracks()
        self.monotonic.now += 20.0
        self.runtime.poll()
        self.c.button(0)                                             # Back: Home
        self.ready_current()
        check = self.monotonic.now + 2.0
        engine = AliveLights(0)
        pending = frame = None
        for kind, at, value in log:
            ms = int(round(at * 1000))
            if kind == "post":
                pending = value
                continue
            command, payload = value
            if command not in ("enter", "frame"):
                continue
            if not engine.claimed():
                engine.claim(ms)
            if pending is not None:
                engine.set_progress(ms, *pending)
                pending = None
            frame = payload["frame"] if command == "enter" else payload
            engine.render(ms, frame)
        self.assertIs(frame["playing"], True)
        for ms in range(int(round(self.monotonic.now * 1000)), int(round(check * 1000)) + 1, 16):
            engine.render(ms, frame)
        self.assertTrue(engine.asleep())
        expected = 60000 + (check - resumed) * 1000
        self.assertAlmostEqual(engine.song_prog * 240000, expected, delta=250,
                               msg="the song hand is where Sonos is, not 20 s behind")

    def test_a_failing_post_is_not_fatal(self):
        def broken(pos, dur):
            raise RuntimeError("bridge gone")
        self.device.post_progress = broken
        with self.assertLogs("control_center.runtime", level="WARNING") as logs:
            self.connect()
            self.reading(position="0:03:00")
            self.monotonic.now += 1.0
            self.runtime.poll()
        self.assertEqual(len([line for line in logs.output if "Song position" in line]), 1, "logged once")
        self.assertTrue(self.device.frames(), "frames still go out")


# ------------------------------------------------ entry frames with an alive knob (Stage 8 rule)
class UnconfirmedStartSonos(SimulatedSonos):
    """An album start whose readback still shows the previous pause (R4)."""

    def play_items(self, items, expected_group_revision):
        super().play_items(items, expected_group_revision)
        self.state.update(playback="PAUSED_PLAYBACK", can_play=True, can_pause=False)
        return self.read_state()


class AliveEnterFrameTests(RuntimeCase):
    """The entry frame is still the first post-ready frame with an `alive` knob (posts force frames)."""

    def setUp(self):
        with patch("test_cc_enter_frames.SimulatedSonos", UnconfirmedStartSonos):
            super().setUp()
        self.device = self.runtime.device = AliveDevice()

    def test_home_entries_carry_playing_and_equal_the_first_frame(self):
        self.c.button(2)                                   # Tracks
        self.assertEqual(playing_of(self.assert_enter("tracks")), ABSENT)
        self.c.button(0, self.c.control_id)                # Back: Home
        self.assertIs(playing_of(self.assert_enter("home")), True)
        self.assertEqual(self.device.progress[:1], [(0, 0)], "the simulator has no track length")

    def test_skip_success(self):
        self.c.button(2)                                   # Tracks
        self.settle()
        self.c.position(0, self.c.control_id)
        self.c.button(3, self.c.control_id)
        self.runtime.dispatch()
        self.runtime.audio.run_all()                       # the reconnect's state read (C5-2), then the skip
        self.runtime.poll()
        entry = self.assert_enter("skip success")
        self.assertEqual(entry["feedback"], {"kind": "ok", "seq": 1, "skip": -1})

    def test_album_start(self):
        self.c.button(1)
        self.settle()
        self.runtime.library.run_next()
        self.runtime.poll()
        self.assert_enter("page load")
        self.c.position(2, self.c.control_id)
        self.c.button(3, self.c.control_id)
        entry = self.assert_enter("album start: Home at once")
        self.assertEqual((entry["layout"], entry["status"]), ("nowPlaying", "Starting…"))
        self.assertEqual(playing_of(entry), ABSENT, "M16: omitted while Starting…")
        self.runtime.library.run_all()                     # resolve, then play on the audio lane
        self.runtime.audio.run_all()
        self.runtime.poll()
        frame = self.device.frames()[-1]
        self.assertEqual((frame["feedback"]["kind"], frame["feedback"].get("moment")), ("ok", "started"))
        self.assertEqual(playing_of(frame), ABSENT, "R4: not confirmed yet (and the started frame)")


# ---------------------------------------------------------------------------- limit events
class LimitEventTests(unittest.TestCase):
    def setUp(self):
        executor = patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.c = Controller()
        self.device = AliveDevice()
        self.runtime = Runtime(self.c, SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), self.device)
        self.addCleanup(self.runtime.shutdown)
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.device.events.put({"kind": "ready", "id": self.c.control_id})
        self.runtime._device_events()
        self.device.commands.clear()

    def limit(self, direction):
        self.device.events.put({"kind": "limit", "id": self.c.control_id, "dir": direction})
        self.runtime._device_events()

    def test_a_limit_is_a_touch_and_the_controller_limit_only(self):
        seq = self.runtime.touch_seq
        with patch.object(self.c, "position") as position, patch.object(self.c, "button") as button, \
                patch.object(self.c, "limit") as limit:
            self.limit(1)
            self.limit(-1)
        position.assert_not_called()
        button.assert_not_called()
        self.assertEqual([call.args for call in limit.call_args_list],
                         [(1, self.c.control_id), (-1, self.c.control_id)], "K3 section 10.4")
        self.assertEqual((self.runtime.touch_seq, self.runtime.last_touch_kind), (seq + 2, "limit"))
        self.assertEqual((self.runtime.limit_seq, self.runtime.last_limit_dir), (2, -1))
        self.assertEqual(self.device.commands, [], "a touch sends nothing")

    def test_a_malformed_direction_is_still_a_touch_but_no_limit(self):
        seq = self.runtime.touch_seq
        with patch.object(self.c, "limit") as limit:
            for direction in (0, 2, True, "1", None, 1.0):
                self.limit(direction)
        limit.assert_not_called()
        self.assertEqual(self.runtime.touch_seq, seq + 6)
        self.assertEqual((self.runtime.limit_seq, self.runtime.last_limit_dir), (0, 0))

    def test_a_limit_during_the_button_probe_is_a_touch(self):
        probed = []
        self.runtime.on_button_probe = probed.append
        seq = self.runtime.touch_seq
        self.limit(1)
        self.assertEqual((self.runtime.touch_seq, probed), (seq + 1, []))


# ----------------------------------------------------------------------------- LED tuning
class LedTuningTests(unittest.TestCase):
    def test_values(self):
        cases = [({}, (None, None)), ({"led_drive": 150}, (150, None)), ({"led_dither": False}, (None, False)),
                 ({"led_drive": 1, "led_dither": True}, (1, True)), ({"led_drive": 255}, (255, None)),
                 (None, (None, None)), ([("led_drive", 5)], (None, None)),
                 ({"led_drive": None, "led_dither": None}, (None, None))]
        for settings, expected in cases:
            with self.subTest(settings=settings):
                self.assertEqual(led_tuning(settings), expected)

    def test_invalid_values_are_ignored_and_logged_by_key_only(self):
        for key, value in (("led_drive", 0), ("led_drive", 256), ("led_drive", 150.0), ("led_drive", True),
                           ("led_drive", "secret-150"), ("led_dither", 1), ("led_dither", "secret-yes")):
            with self.subTest(key=key, value=value):
                with self.assertLogs("control_center.runtime", level="WARNING") as logs:
                    self.assertEqual(led_tuning({key: value, "led_dither" if key == "led_drive" else "led_drive": None}),
                                     (None, None))
                text = "\n".join(logs.output)
                self.assertIn(key, text)
                self.assertNotIn(repr(value), text)
                self.assertNotIn("secret", text)

    def test_apply_hands_them_to_the_bridge(self):
        with patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor):
            device = AliveDevice()
            runtime = Runtime(Controller(), SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), device)
            self.addCleanup(runtime.shutdown)
            self.assertEqual(runtime.apply_led_tuning({"led_drive": 90, "led_dither": False, "port": "COM8"}),
                             (90, False))
            self.assertEqual((device.tuning, runtime.led_tuning), ([(90, False)], (90, False)))
            runtime.apply_led_tuning({})
            self.assertEqual(device.tuning[-1], (None, None), "removed from settings: nothing sent")

            def broken(drive=None, dither=None):
                raise RuntimeError("bridge gone")
            device.set_led_tuning = broken
            with self.assertLogs("control_center.runtime", level="WARNING"):
                self.assertEqual(runtime.apply_led_tuning({"led_drive": 60}), (60, None))
            runtime.device = None
            self.assertEqual(runtime.apply_led_tuning({"led_dither": True}), (None, True))


# ------------------------------------------------ end to end: Runtime -> DeviceBridge -> knob
PROFILE_NAMES = ("BINARIS BEER", "MIDI SKIPPER", "MIDI CLACK JONES")


class EndToEndTests(unittest.TestCase):
    CAPS = AL4

    def setUp(self):
        executor = patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.monotonic = Monotonic()
        timer = patch.object(runtime_module.time, "monotonic", self.monotonic)
        timer.start()
        self.addCleanup(timer.stop)
        device._strip_logged.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge_clock = BridgeClock()
        self.serial = WireSerial(self.bridge_clock, self.CAPS)
        template = next(iter(self.serial.profiles.values()))
        self.serial.profiles = {name: {**template, "name": name} for name in PROFILE_NAMES}
        self.bridge = DeviceBridge(self.temp.name, lambda port: self.serial, request_timeout=0.1, autostart=False,
                                   clock=self.bridge_clock, local_minute=lambda: 1234)
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.sonos = PlayingSonos()
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()
        self.runtime = Runtime(self.c, self.sonos, SimulatedAppleMusic(), SimulatedWindows(), self.bridge)
        self.addCleanup(self.runtime.shutdown)

    def pump(self):
        bridge = self.bridge
        for _ in range(100):
            if bridge._deferred_command is None and bridge.commands.empty():
                break
            command, value = bridge._next_command()
            bridge._dispatch(command, value)
            bridge._service()

    def cycle(self):
        self.runtime.poll()
        self.pump()

    def connect(self):
        self.bridge.submit("connect", "COM-FAKE")
        self.pump()
        self.cycle()         # connected: enter (with the first progress)
        self.cycle()         # ready: the first post-ready frame
        self.assertTrue(self.c.ready)

    def test_the_knob_receives_playing_progress_and_skip(self):
        self.runtime.apply_led_tuning({"led_drive": 90, "led_dither": False})
        self.connect()
        (kind, entry), (kind2, first) = self.serial.frames()[:2]
        self.assertEqual((kind, kind2), ("control", "frame"))
        self.assertEqual(entry["clock"], 1234)
        self.assertEqual(entry["progress"], {"pos": 60000, "dur": 240000})
        self.assertEqual((entry["ledDrive"], entry["ledDither"]), (90, False))
        self.assertIs(entry["playing"], True)
        self.assertIs(first["playing"], True)
        self.assertNotIn("progress", first, "sent once")
        # 30 s later: a refresh, written at once with the frame of that poll.
        count = len(self.serial.frames())
        self.monotonic.now += PROGRESS_REFRESH_SECONDS
        self.cycle()
        progress = [frame["progress"] for _kind, frame in self.serial.frames()[count:] if "progress" in frame]
        self.assertEqual(progress, [{"pos": 90000, "dur": 240000}])
        # A Tracks skip: its ok names the direction.
        self.c.button(2)
        self.cycle()
        self.device_ready()
        self.c.position(2, self.c.control_id)
        self.c.button(3, self.c.control_id)
        self.runtime.dispatch()
        self.runtime.audio.run_all()     # the connect's fresh state read (C5-2), then the skip
        self.cycle()
        self.device_ready()
        skipped = [frame for _kind, frame in self.serial.frames() if frame.get("feedback", {}).get("kind") == "ok"]
        self.assertTrue(skipped)
        self.assertEqual(skipped[-1]["feedback"]["skip"], 1)
        self.assertNotIn("playing", skipped[-1], "a Tracks frame")

    def device_ready(self):
        self.cycle()
        self.cycle()

    def test_a_knob_limit_is_a_touch(self):
        self.connect()
        seq = self.runtime.touch_seq
        self.serial.inject({"id": self.bridge.ready_id, "lim": 1})
        self.bridge._read()
        self.runtime.poll()
        self.assertEqual((self.runtime.touch_seq, self.runtime.last_touch_kind), (seq + 1, "limit"))
        self.assertEqual((self.runtime.limit_seq, self.runtime.last_limit_dir), (1, 1))


class EndToEndWithoutAliveTests(EndToEndTests):
    """A cc5.2/cc5.3-style knob: no section 3 field ever reaches it."""
    CAPS = P4

    def test_the_knob_receives_playing_progress_and_skip(self):
        self.runtime.apply_led_tuning({"led_drive": 90, "led_dither": False})
        self.connect()
        self.monotonic.now += PROGRESS_REFRESH_SECONDS
        self.cycle()
        self.assertFalse(self.runtime.alive)
        for _kind, frame in self.serial.frames():
            for name in ("playing", "clock", "progress", "ledDrive", "ledDither"):
                self.assertNotIn(name, frame)

    # test_a_knob_limit_is_a_touch is inherited: the bridge does not gate `lim` on alive
    # (a pre-alive knob never sends one), and the runtime never filters a touch.


if __name__ == "__main__":
    unittest.main()

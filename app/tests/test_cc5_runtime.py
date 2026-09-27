"""K3 sections 1 and 10: lanes per op, the section 1.1 step scheduler, the progress channel,
invalidation, the sign-in state from every Apple op, art identity and accents per mode, ledger
writes, LED tuning and Motion hand-offs (C5-48, C5-65, M26)."""
from queue import Queue
import unittest
from unittest.mock import patch

from cc5_support import Clock, FakeDevice, Fixture, Harness, ManualExecutor, queue_state
from control_center.apple_music import AppleMusicError
from control_center.controller import Controller
from control_center.runtime import AUDIO_RAN_KEEP, AudioLane, Runtime, failure, led_tuning_v5
from control_center.simulation import SimControls, SimulatedAppleMusic, SimulatedSonos, SimulatedWindows


class StepSonos(SimulatedSonos):
    """A speaker at 50 ms per SOAP call on a fake clock (the section 17.2 FakeSpeaker's role)."""
    CALL = 0.05

    def __init__(self, clock):
        super().__init__(clock=clock, sleep=clock.sleep)
        self.clock = clock
        self.load_album()
        self.hook = None
        self.volume_at = []
        self.transport_at = []
        self.seek_at = []

    def set_volume(self, value, expected_group_revision):
        self.clock.advance(self.CALL)
        self.volume_at.append(self.clock())
        self.state["volume"] = value
        return self.read_state()

    def transport(self, direction, expected_group_revision, expected_track_id=None):
        self.clock.advance(self.CALL)
        self.transport_at.append(self.clock())
        return self.read_state()

    def read_state(self):
        self.clock.advance(self.CALL)
        return super().read_state()

    def play_next(self, items, expected_group_revision, expected_track_id, progress=None, between_steps=None):
        for index in range(100):
            self.clock.advance(2 * self.CALL)        # the insert and its tail read
            if progress:
                progress({"phase": "inserting", "k": index + 1, "n": 100})
            if index == 9 and self.hook:
                self.hook()
            if between_steps:
                between_steps()
        return {**self.read_state(), "_inserted": {"start_row": 6, "song_ids": []}}

    def seek(self, seconds, expected_group_revision, expected_track_id, between_steps=None):
        start = self.clock()
        self.seek_at.append(start)
        while self.clock() - start < 2.65:
            self.clock.advance(0.1)
            if self.hook and abs(self.clock() - start - 1.0) < 0.05:
                self.hook()
            if between_steps:
                between_steps()
        return {**self.read_state(), "_applied_seek": int(seconds)}


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = Clock(100.0)
        for name in ("monotonic",):
            timer = patch("control_center.runtime.time.monotonic", self.clock)
            timer.start()
            self.addCleanup(timer.stop)
        sleeper = patch("control_center.runtime.time.sleep", self.clock.advance)
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.sonos = StepSonos(self.clock)
        self.apple = SimulatedAppleMusic(clock=self.clock, sleep=self.clock.sleep)
        self.c = Controller(clock=self.clock)
        self.runtime = Runtime(self.c, self.sonos, self.apple, SimulatedWindows(), FakeDevice())
        self.addCleanup(self.runtime.close)
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()

    def run_audio(self):
        self.runtime.audio.run_all()

    def start_play_next(self):
        self.c.button(1)
        self.runtime.dispatch()
        self.runtime.library.run_all()
        self.runtime.poll()
        self.apple.resolve(self.c.recent.items[0])       # cached: the job inserts at once
        self.c.button(2, self.c.control_id)
        self.runtime.dispatch()

    def test_volume_mid_play_next_within_200_ms(self):
        submitted = []

        def hook():
            submitted.append(self.clock())
            self.c.desired_volume = 44
            self.c.volume_request = self.c.request("volume", value=44, expected_group_revision=self.c.state["group_revision"])
            self.runtime.dispatch()
        self.sonos.hook = hook
        self.start_play_next()
        self.run_audio()
        self.assertEqual(len(self.sonos.volume_at), 1)
        self.assertLessEqual(self.sonos.volume_at[0] - submitted[0], 0.2 + 1e-9)
        self.runtime.poll()
        self.assertEqual(self.c.feedback["moment"], "queued", "the job still ends ok")

    def test_play_pause_mid_job(self):
        submitted = []

        def hook():
            submitted.append(self.clock())
            self.c.command_request = self.c.request("transport", direction="pause",
                                                    expected_group_revision=self.c.state["group_revision"])
            self.runtime.dispatch()
        self.sonos.hook = hook
        self.start_play_next()
        self.run_audio()
        self.assertLessEqual(self.sonos.transport_at[0] - submitted[0], 0.2 + 1e-9)

    def test_state_poll_every_2000_ms_during_the_job(self):
        self.start_play_next()
        self.assertEqual(self.c._busy_code(), "queueing")
        requests = 0
        for _ in range(8):
            self.clock.advance(0.5)
            before = len([e for e in self.c.pending.values() if e["kind"] == "state"])
            self.c.tick()
            requests += len([e for e in self.c.drain() if e["kind"] == "state"])
        self.assertLessEqual(requests, 2)

    def test_queue_changing_presses_stay_dimmed(self):
        self.start_play_next()
        frame = self.c.frame()
        self.assertEqual([b["enabled"] for b in frame["buttons"]][2:], [False, False])

    def test_volume_during_a_seek_confirmation_and_a_second_seek_waits(self):
        submitted = []

        def hook():
            submitted.append(self.clock())
            self.c.desired_volume = 30
            self.c.volume_request = self.c.request("volume", value=30, expected_group_revision=self.c.state["group_revision"])
            second = self.c.request("seek", target_s=150, expected_group_revision=self.c.state["group_revision"],
                                    expected_track_id=self.c.state.get("track_id"))
            self.runtime.dispatch()
            self.sonos.hook = None
        self.sonos.hook = hook
        first = self.c.request("seek", target_s=100, expected_group_revision=self.c.state["group_revision"],
                               expected_track_id=self.c.state.get("track_id"))
        self.runtime.dispatch()
        self.run_audio()
        self.assertLessEqual(self.sonos.volume_at[0] - submitted[0], 0.2 + 1e-9)
        self.assertEqual(len(self.sonos.seek_at), 2)
        self.assertGreaterEqual(self.sonos.seek_at[1] - self.sonos.seek_at[0], 2.65, "the second waited")


class AudioLaneUnitTests(unittest.TestCase):
    def test_idle_order_is_arrival_and_seek_skips_seek(self):
        executor = ManualExecutor()
        lane = AudioLane(executor)
        order = []

        def seek_job(name):
            def run(steps):
                order.append(name + ":start")
                steps()
                order.append(name + ":end")
            return run
        lane.submit("seek", seek_job("s1"))
        lane.submit("seek", seek_job("s2"))
        lane.submit("volume", lambda steps: order.append("v"))
        executor.run_all()
        self.assertEqual(order, ["s1:start", "v", "s1:end", "s2:start", "s2:end"])

    def test_exclusive_runs_short_jobs_between_steps(self):
        executor = ManualExecutor()
        lane = AudioLane(executor)
        order = []

        def job(steps):
            order.append("step1")
            lane.submit("state", lambda s: order.append("state"))
            lane.submit("shuffle_reorder", lambda s: order.append("other-exclusive"))
            steps()
            order.append("step2")
        lane.submit("play_next", job)
        executor.run_all()
        self.assertEqual(order, ["step1", "state", "step2", "other-exclusive"])

    def test_the_ran_log_is_bounded(self):
        # WP5-R9: one entry per job for the life of the tray process was a slow leak.
        executor = ManualExecutor()
        lane = AudioLane(executor)
        for _ in range(AUDIO_RAN_KEEP * 4):
            lane.submit("state", lambda steps: None)
        executor.run_all(limit=AUDIO_RAN_KEEP * 8)
        self.assertEqual(len(lane.ran), AUDIO_RAN_KEEP)
        lane.submit("volume", lambda steps: None)
        executor.run_all()
        self.assertEqual((len(lane.ran), lane.ran[-1]), (AUDIO_RAN_KEEP, "volume"))


class DiagTests(unittest.TestCase):
    """WP5-R11 (K3 section 6.5): the knob's enterMsLast / enterMsMax, logged at debug level once a
    minute with the cause of the last re-entry; requested once a minute when the bridge can."""

    def setUp(self):
        self.clock = Clock(1000.0)
        timer = patch("control_center.runtime.time.monotonic", self.clock)
        timer.start()
        self.addCleanup(timer.stop)

    def boot(self, device=None):
        h = Harness(self)
        if device is not None:
            h.runtime.device = device
        h.runtime.device.events.put({"kind": "connected",
                                     "capabilities": {"controlCenter": True, "presentation": 5}})
        h.run(1)
        return h

    def lines(self, logs):
        return [record.getMessage() for record in logs.records if "enterMs" in record.getMessage()]

    def test_logged_once_a_minute_with_the_cause(self):
        h = self.boot()
        h.press(1)                                   # Browse: a re-entry
        cause = h.c.last_reentry_cause
        self.assertTrue(cause)
        with self.assertLogs("control_center.runtime", level="DEBUG") as logs:
            h.runtime.device.events.put({"kind": "diag", "diag": {"enterMsLast": 84, "enterMsMax": 131}})
            h.runtime.poll()
            self.clock.advance(30.0)
            h.runtime.device.events.put({"kind": "diag", "diag": {"enterMsLast": 90, "enterMsMax": 131}})
            h.runtime.poll()
            self.clock.advance(30.0)
            h.runtime.device.events.put({"kind": "diag", "enterMsLast": 77, "enterMsMax": 140})
            h.runtime.poll()
        lines = self.lines(logs)
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("enterMsLast 84 ms, enterMsMax 131 ms", lines[0])
        self.assertIn(cause, lines[0])
        self.assertIn("enterMsLast 77 ms, enterMsMax 140 ms", lines[1])
        self.assertEqual(h.runtime.last_diag, (77, 140, h.c.last_reentry_cause))
        self.assertTrue(all(record.levelname == "DEBUG" for record in logs.records if "enterMs" in record.getMessage()))

    def test_values_that_are_not_millisecond_ints_are_never_logged(self):
        h = self.boot()
        with self.assertLogs("control_center.runtime", level="DEBUG") as logs:
            h.runtime._diag_event({"kind": "diag", "diag": {"enterMsLast": "84; drop", "enterMsMax": None}})
            h.runtime._diag_event({"kind": "diag", "diag": {"enterMsLast": 12, "enterMsMax": True}})
        self.assertEqual(len(self.lines(logs)), 1)
        self.assertIn("enterMsMax ? ms", self.lines(logs)[0])

    def test_requested_once_a_minute_while_claimed(self):
        asked = []

        class Device(FakeDevice):
            def request_diag(self):
                asked.append(True)
        h = self.boot(Device())
        self.assertEqual(asked, [], "not at the claim: the knob is entering")
        self.clock.advance(59.0)
        h.runtime.poll()
        self.assertEqual(asked, [])
        self.clock.advance(1.5)
        h.runtime.poll()
        h.runtime.poll()
        self.assertEqual(asked, [True])
        self.clock.advance(60.0)
        h.runtime.poll()
        self.assertEqual(len(asked), 2)
        h.runtime.device.events.put({"kind": "disconnected"})
        h.runtime.poll()
        self.clock.advance(120.0)
        h.runtime.poll()
        self.assertEqual(len(asked), 2, "never while no knob is claimed")


class LaneRoutingTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(self)
        self.h.run(1)

    def test_lanes_per_op(self):
        runtime = self.h.runtime
        c = self.h.c
        cases = {"state": "audio", "queue_window": "audio", "set_shuffle": "audio", "recent": "library",
                 "like": "library", "ratings": "lookahead", "catalog_songs": "lookahead",
                 "playlist_meta": "lookahead", "recent_lookahead": "lookahead"}
        payloads = {"queue_window": {"start": 0, "count": 3}, "set_shuffle": {"on": True, "expected_group_revision": "x"},
                    "recent": {"offset": 0, "list_visit": c.recent.visit}, "like": {"song_id": "1"},
                    "ratings": {"ids": ["1"]}, "catalog_songs": {"ids": ["1"]},
                    "playlist_meta": {"playlist_id": "p"},
                    "recent_lookahead": {"offset": 0, "list_visit": c.recent.visit}}
        for kind, lane in cases.items():
            with self.subTest(kind=kind):
                before = {name: len(getattr(runtime, name).jobs) for name in ("audio", "library", "lookahead")}
                c.request(kind, **payloads.get(kind, {}))
                runtime.dispatch()
                after = {name: len(getattr(runtime, name).jobs) for name in ("audio", "library", "lookahead")}
                grew = [name for name in after if after[name] > before[name]]
                self.assertEqual(grew, [lane])
                for name in ("audio", "library", "lookahead"):
                    getattr(runtime, name).jobs.clear()

    def test_favourites_lane_follows_the_cache(self):
        runtime = self.h.runtime
        self.h.c.request("favourite_playlists", force=True, lane="library")
        runtime.dispatch()
        self.assertEqual(len(runtime.library.jobs), 1)
        self.h.c.request("favourite_playlists", force=False, lane="lookahead")
        runtime.dispatch()
        self.assertEqual(len(runtime.lookahead.jobs), 1)

    def test_progress_is_delivered_before_the_completion(self):
        self.h.press(1)
        self.h.run(2)
        seen = []
        original_progress, original_complete = self.h.c.progress, self.h.c.complete

        def progress(request, payload):
            seen.append("progress")
            original_progress(request, payload)

        def complete(request, result=None, error=None):
            if self.h.c.pending.get(request, {}).get("kind") == "play_next":
                seen.append("complete")
            original_complete(request, result, error)
        self.h.c.progress, self.h.c.complete = progress, complete
        self.h.press(2)
        self.h.run(3)
        self.assertEqual(seen[-1], "complete")
        self.assertIn("progress", seen[:-1])


class InvalidationTests(Fixture):
    def test_unsent_writes_are_dropped_and_forgotten(self):
        runtime = Runtime.__new__(Runtime)
        runtime._controller = self.c
        import threading
        runtime._action_lock = threading.Lock()
        runtime._action_epoch = 0
        runtime._latest_volume = None
        self.browse()
        self.press(2)                        # play_next
        self.turn_to(3)
        self.c.effects.append({"kind": "like", "request": 999, "song_id": "7"})
        self.c.like_inflight.add("7")
        runtime.invalidate_actions()
        self.assertIsNone(self.c.play_next_job)
        self.assertNotIn("7", self.c.like_inflight)
        self.assertFalse([e for e in self.c.effects if e["kind"] in ("play_next", "like")])


class SigninTests(unittest.TestCase):
    def test_every_apple_result_feeds_the_signin_state(self):
        h = Harness(self)
        h.run(1)
        h.apple.expired = True
        h.press(1)
        h.run(2)
        self.assertTrue(h.runtime.music_signin_expired)
        self.assertTrue(h.c.music_signin_expired)
        self.assertEqual(h.frame()["title"], "Apple Music sign-in expired")
        h.apple.expired = False
        h.c.button(0, h.c.control_id)
        h.press(1)
        h.run(2)
        self.assertFalse(h.runtime.music_signin_expired)

    def test_failure_maps_outcomes(self):
        self.assertEqual(failure(AppleMusicError("x", status=401), op="like").outcome, "signin_expired")
        self.assertEqual(failure(AppleMusicError("x", status=429), op="like").outcome, "rate_limited")
        from control_center.sonos import GroupChanged, SeekNotConfirmed
        self.assertEqual(failure(GroupChanged("g"), op="seek").outcome, "group_changed")
        self.assertEqual(failure(SeekNotConfirmed("s"), op="seek").outcome, "not_confirmed")
        self.assertEqual(failure(RuntimeError("Obsolete library request discarded"), op="recent").outcome, "discarded")


class ArtAndAccentTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(self)
        self.h.run(1)

    def test_art_identity_per_mode(self):
        c, runtime = self.h.c, self.h.runtime
        self.assertEqual(runtime._art_identity()[0], "playing")
        self.h.press(1)
        self.h.run(2)
        self.assertEqual(runtime._art_identity()[:2], ("recent", "a0"))
        self.h.press(1)
        self.h.run(2)
        self.assertEqual(runtime._art_identity()[:2], ("recent", "a0"))
        c.button(2, c.control_id)
        c.tick()
        self.h.clock.advance(0.2)
        self.h.run(2)
        self.assertEqual(runtime._art_identity()[0], "playlist")

    def test_no_art_items_get_the_gen_accent_and_index_7_is_warm(self):
        from control_center.artwork import gen_sleeve
        runtime = self.h.runtime
        item = {"id": "x", "title": "Night Drive", "artist": "Sample library", "art_template": ""}
        self.assertEqual(runtime.accent_of("recent", item), gen_sleeve("Night Drive", "Sample library")["ring_accent"])
        for n in range(200):
            title = f"T{n}"
            if gen_sleeve(title, "")["index"] == 7:
                self.assertEqual(runtime.accent_of("recent", {"id": "y", "title": title, "artist": ""}), 0)
                break
        self.assertEqual(runtime.accent_of("window", {"id": "w", "accent": None}), 0)

    def test_led_style_white_strips_colours(self):
        self.h.press(1)
        self.h.run(2)
        self.h.runtime.led_style = "white"
        self.assertNotIn("colors", self.h.frame()["ring"])


class LedgerTests(unittest.TestCase):
    def test_start_and_play_next_write_the_ledger(self):
        h = Harness(self)
        h.run(1)
        h.press(1)
        h.run(2)
        h.press(3)                           # start Promises
        h.run(3)
        base = h.runtime.ledger.base
        self.assertEqual((base.kind, base.name, len(base.song_ids)), ("album", "Promises", 9))
        h.press(1)
        h.run(2)
        h.c.position(1, h.c.control_id)
        h.press(2)                           # Play next Night Drive
        h.run(3)
        self.assertEqual(h.runtime.ledger.playnext[0].start_row, 2)


class TuningAndMotionTests(unittest.TestCase):
    def test_led_pink_and_vol_full(self):
        self.assertEqual(led_tuning_v5({"led_pink": "#FF285A", "led_vol_full": True}), (0xFF285A, True))
        self.assertEqual(led_tuning_v5({"led_pink": "pink", "led_vol_full": 1}), (None, None))
        calls = []

        class Device(FakeDevice):
            def set_led_tuning(self, drive=None, dither=None, pink=None, vol_full=None):
                calls.append((drive, dither, pink, vol_full))
        h = Harness(self)
        h.runtime.device = Device()
        h.runtime.apply_led_tuning({"led_drive": 200, "led_pink": 0x123456, "led_vol_full": False})
        self.assertEqual(calls, [(200, None, 0x123456, False)])

    def test_motion_setting_and_system_event(self):
        calls = []

        class Device(FakeDevice):
            def set_reduced_motion(self, on):
                calls.append(on)
        probe = {"off": True}
        h = Harness(self, motion_probe=lambda: probe["off"])
        h.runtime.device = Device()
        self.assertIs(h.frame()["reducedMotion"], False, "not configured: full motion")
        h.runtime.set_motion("system")
        self.assertIs(h.frame()["reducedMotion"], True)
        probe["off"] = False
        h.stage.emit("system", what="motion")
        h.run(1)
        self.assertIs(h.frame()["reducedMotion"], False)
        h.runtime.set_motion("reduced")
        self.assertIs(h.frame()["reducedMotion"], True)
        self.assertEqual(calls[-1], True)

    def test_the_picker_gets_the_registry_and_the_motion_setting(self):
        calls = []

        class Picker(SimulatedWindows):
            def set_overlay_registry(self, provider):
                calls.append(("registry", provider))

            def set_reduced_motion(self, on):
                calls.append(("motion", on))
        with patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor):
            runtime = Runtime(Controller(clock=Clock()), SimulatedSonos(), SimulatedAppleMusic(), Picker(),
                              motion_probe=lambda: True)
        self.addCleanup(runtime.close)
        self.assertEqual([kind for kind, _ in calls], ["registry", "motion"])
        self.assertIs(calls[1][1], False, "not configured yet: full motion (K3 14.3)")
        registry = calls[0][1]
        runtime.open_surfaces.add("upnext")
        self.assertEqual(registry(), {"upnext"})
        registry().add("explorer")
        self.assertEqual(runtime.open_surfaces, {"upnext"}, "the picker gets a copy")
        runtime.set_motion("system")
        self.assertEqual(calls[-1], ("motion", True))
        runtime.set_motion("full")
        self.assertEqual(calls[-1], ("motion", False))

    def test_a_picker_that_refuses_the_calls_does_not_stop_the_runtime(self):
        class Picker(SimulatedWindows):
            def set_overlay_registry(self, provider):
                raise RuntimeError("no")

            def set_reduced_motion(self, on):
                raise RuntimeError("no")
        with patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor):
            runtime = Runtime(Controller(clock=Clock()), SimulatedSonos(), SimulatedAppleMusic(), Picker())
        self.addCleanup(runtime.close)
        runtime.set_motion("reduced")
        self.assertTrue(runtime.reduced_motion)


class ShuffleRecordLoadTests(unittest.TestCase):
    """[P3] K3 9.5.3: the record the runtime loads at start reaches the controller as its base-row
    order (signature digests only), so the Shuffle-off preview survives a companion restart."""

    def test_the_loaded_record_reaches_the_controller(self):
        h = Harness(self)
        h.sonos.record = {"base_rows": [["sig-b", "2"], ["sig-a", "1"]]}
        self.assertEqual(h.runtime._read_shuffle_record(), h.sonos.record)
        h.runtime.poll()
        self.assertEqual(h.c.shuffle_record_order, ["sig-b", "sig-a"])

    def test_no_record_or_a_malformed_one_is_none(self):
        from control_center.runtime import shuffle_record_order
        for record in ({}, None, {"base_rows": []}, {"base_rows": "x"}, {"base_rows": [["sig-a", "1"], [None, "2"]]},
                       {"base_rows": [[]]}):
            self.assertIsNone(shuffle_record_order(record), record)
        self.assertEqual(shuffle_record_order({"base_rows": [("sig-a", "1")], "room_uid": "R"}), ["sig-a"])
        h = Harness(self)
        h.c.shuffle_record(["sig-old"])
        h.runtime._read_shuffle_record()                    # the simulator's record is empty
        h.runtime.poll()
        self.assertIsNone(h.c.shuffle_record_order)

    def test_only_the_live_adapter_is_read_at_start(self):
        h = Harness(self)
        h.runtime._shuffle_record_loaded = False
        before = h.runtime.audio_lane.queued()
        h.runtime._load_shuffle_record()                    # the simulator: no store I/O job
        self.assertTrue(h.runtime._shuffle_record_loaded)
        self.assertEqual(h.runtime.audio_lane.queued(), before)


class CancelReasonPassThroughTests(unittest.TestCase):
    """C5-78 (review item R8; K3 5.7.4, 9.9): the runtime hands `windows_cancel`'s `reason` to the picker;
    an adapter without the parameter gets the call it takes; a payload without one leaves the picker's
    own inference (WP7b-D6) in charge."""

    ORIGIN = {"hwnd": 1, "pid": 100}

    class Bare:
        """A picker with only what shutdown needs besides its cancel (no take_events)."""
        def close(self):
            pass

    def runtime_with(self, windows):
        h = Harness(self)
        h.runtime.windows = windows
        return h

    def test_the_reason_reaches_the_picker(self):
        calls = []

        class Picker(self.Bare):
            def cancel(self, origin, complete=None, reason=None):
                calls.append((origin, complete, reason))
                return True
        h = self.runtime_with(Picker())
        for reason in ("back", "hold", "lock", "sleep", "idle", None):
            effect = {"kind": "windows_cancel", "origin": self.ORIGIN, "home": True, "complete": "left"}
            if reason is not None:
                effect["reason"] = reason
            h.runtime._windows_effect(effect)
        self.assertEqual(calls, [(self.ORIGIN, "left", r) for r in ("back", "hold", "lock", "sleep", "idle", None)])

    def test_older_adapters_get_the_call_they_take(self):
        calls = []

        class NoReason(self.Bare):
            def cancel(self, origin, complete=None):
                calls.append(("v7-pre-R8", origin, complete))
                return True

        class V6(self.Bare):
            def cancel(self, origin):
                calls.append(("v6", origin))
                return False
        for windows in (NoReason(), V6()):
            h = self.runtime_with(windows)
            h.runtime._windows_effect({"kind": "windows_cancel", "origin": self.ORIGIN, "home": True,
                                       "complete": None, "reason": "back"})
            self.assertEqual(h.runtime._events[-1]["kind"], "cancel_result", "a v6 return becomes the event")
        self.assertEqual(calls, [("v7-pre-R8", self.ORIGIN, None), ("v6", self.ORIGIN)])

    def test_end_to_end_a_lock_close_reaches_the_simulated_picker(self):
        h = Harness(self)
        h.run(1)
        h.c.open_windows()
        h.runtime.dispatch()
        self.assertEqual(h.c.screen.mode, "windows")
        h.c.notice = ""
        h.c.presenter_event({"kind": "system", "what": "lock"})
        h.runtime.dispatch()
        self.assertEqual(h.windows.cancel_reasons, ["lock"])
        h.run(1)                                            # cancel_result(restored=False): expected, no notice
        self.assertEqual((h.c.screen.mode, h.c.notice), ("home", ""))
        h.c.open_windows()
        h.runtime.dispatch()
        h.c.button(0, h.c.control_id)
        h.runtime.dispatch()
        self.assertEqual(h.windows.cancel_reasons, ["lock", "back"])


if __name__ == "__main__":
    unittest.main()

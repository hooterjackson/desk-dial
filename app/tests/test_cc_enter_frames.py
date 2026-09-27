"""Decorated entry frames, feedback and runtime-owned presentation on desktop v7 (no device or
network I/O). An entry frame is the first post-ready frame, except its `artKey`: the entry
keeps the previous frame's cover and the new one goes out in the first frame after `ready`
(CONTROL_CENTER_V5.md section 6.3, C5-13)."""
from pathlib import Path
from queue import Queue
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.controller import Controller, Screen
from control_center.device import DeviceBridge
from control_center.runtime import Runtime, ART_RETRY_SECONDS
from control_center.simulation import SimulatedSonos, SimulatedAppleMusic, SimulatedWindows
from standalone import fresh_controller
from cc5_support import Clock, FakeDevice, ManualExecutor, page, recent_page, state
from test_cc_device import Clock as DeviceClock, FakeSerial, control as device_control, frame as device_frame


class SpyWindows(SimulatedWindows):
    def __init__(self):
        super().__init__()
        self.hotkey = []
        self.activate_result = None

    def set_hotkey_enabled(self, enabled):
        self.hotkey.append(enabled)

    def activate(self, item):
        return item["available"] if self.activate_result is None else self.activate_result


class Monotonic:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def art_result(token, key="cover_1"):
    return SimpleNamespace(token=token, key=key, error="", rgb565=bytes(120 * 120 * 2))


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        executor = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.monotonic = Monotonic()
        timer = patch("control_center.runtime.time.monotonic", self.monotonic)
        timer.start()
        self.addCleanup(timer.stop)
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.sonos, self.apple, self.windows = SimulatedSonos(), SimulatedAppleMusic(), SpyWindows()
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()  # the fake clock never advances: no background polls
        self.device = FakeDevice()
        self.runtime = Runtime(self.c, self.sonos, self.apple, self.windows, self.device)
        self.addCleanup(self.runtime.close)
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c.set_hardware(True)
        self.settle()

    def settle(self):
        """Dispatch the latest entry, acknowledge it; return (entry frame, first post-ready frame)."""
        for _ in range(5):  # Windows effects complete synchronously and queue their entry.
            self.runtime.dispatch()
            if not self.c.effects:
                break
        entries = [command[1] for command in self.device.commands if command[0] == "enter"]
        self.assertTrue(entries, "no device entry was dispatched")
        entry = entries[-1]
        self.assertEqual(entry["id"], self.c.control_id)
        self.assertFalse(self.c.ready)
        self.device.commands.clear()
        self.device.events.put({"kind": "ready", "id": entry["id"]})
        self.runtime.poll()
        frames = [command[1] for command in self.device.commands if command[0] == "frame"]
        self.assertTrue(frames, "no frame after ready")
        self.device.commands.clear()
        return entry["frame"], frames[0]

    def assert_enter(self, label):
        previous = self.runtime._knob_art_key
        entry, first = self.settle()
        with self.subTest(path=label):
            self.assertEqual(first["id"], self.c.control_id)
            strip = lambda frame: {k: v for k, v in frame.items() if k not in ("id", "artKey")}  # noqa: E731
            self.assertEqual(strip(first), strip(entry), "the entry frame is the first post-ready frame")
            if previous is not None:
                self.assertEqual(entry["artKey"], previous, "the entry keeps the previous cover")
            self.assertEqual(entry["ledStyle"], "color")
            self.assertIn("artKey", entry)
            self.assertNotEqual(entry["status"], "Connecting knob")
        return entry


class EnterFrameTests(RuntimeCase):
    def test_mode_changes(self):
        self.c.button(2)
        self.assertEqual(self.assert_enter("tracks")["layout"], "tracks")
        self.c.button(0, self.c.control_id)
        self.assertEqual(self.assert_enter("home")["layout"], "nowPlaying")
        self.c.button(1, self.c.control_id)
        entry = self.assert_enter("recent loading")
        self.assertEqual((entry["activity"], entry["ring"]["style"]), ("loading", "off"))

    def test_external_volume_change(self):
        request = self.c.request("state")
        self.runtime.results.put((request, {**self.sonos.read_state(), "volume": 61}, None))
        self.runtime.poll()
        entry = self.assert_enter("external volume")
        self.assertEqual((entry["layout"], entry["status"], entry["value"]), ("volume", "Changed on Sonos", "61%"))

    def test_skip_success(self):
        self.c.button(2)
        self.settle()
        self.c.position(2, self.c.control_id)
        self.c.button(3, self.c.control_id)
        self.runtime.dispatch()
        self.runtime.audio.run_all()     # the reconnect's fresh state read (C5-2), then the skip
        self.runtime.poll()
        entry = self.assert_enter("skip success")
        self.assertEqual(entry["ring"]["index"], 1)
        self.assertEqual(entry["feedback"], {"kind": "ok", "seq": 1, "skip": 1})

    def test_page_load_start_and_recent_back(self):
        self.c.button(1)
        self.settle()
        self.runtime.library.run_next()
        self.runtime.poll()
        self.assertEqual(self.assert_enter("page load")["activity"], "idle")
        self.c.position(2, self.c.control_id)
        self.c.button(3, self.c.control_id)
        entry = self.assert_enter("start: Home at once")
        self.assertEqual((entry["layout"], entry["status"], entry["activity"]), ("nowPlaying", "Starting…", "pending"))
        self.assertNotIn("playing", entry)
        self.runtime.library.run_all()   # resolve, then play on the audio lane
        self.runtime.audio.run_all()
        self.runtime.poll()
        frame = self.runtime.frame()
        self.assertEqual((frame["feedback"]["kind"], frame["feedback"].get("moment")), ("ok", "started"))

    def test_windows_open_switch(self):
        self.c.button(3)
        self.assertEqual(self.assert_enter("windows open")["layout"], "windows")
        self.c.position(3, self.c.control_id)
        self.c.button(3, self.c.control_id)
        entry = self.assert_enter("windows switch")
        self.assertEqual((entry["mode"], entry["feedback"]), ("VOLUME", {"kind": "ok", "seq": 1}))

    def test_windows_back_and_dismiss(self):
        self.c.button(3)
        self.settle()
        self.c.button(0, self.c.control_id)
        self.assertEqual(self.assert_enter("windows back")["layout"], "nowPlaying")
        self.c.button(3, self.c.control_id)
        self.settle()
        self.c.dismiss_windows()
        self.assertEqual(self.assert_enter("windows dismiss")["mode"], "VOLUME")

    def test_windows_back_while_a_start_is_pending(self):
        self.c.button(1)
        self.settle()
        self.runtime.library.run_next()
        self.runtime.poll()
        self.settle()
        self.c.button(3, self.c.control_id)
        self.settle()
        self.assertIsNotNone(self.c.start)
        self.c.button(3, self.c.control_id)
        self.settle()
        self.c.button(0, self.c.control_id)
        entry = self.assert_enter("windows back, start pending")
        self.assertEqual((entry["mode"], entry["activity"], entry["status"]), ("VOLUME", "pending", "Starting…"))

    def test_group_change_and_reconnect(self):
        request = self.c.request("state")
        self.runtime.results.put((request, {**self.sonos.read_state(), "group_revision": "sim:2", "volume": 12}, None))
        self.runtime.poll()
        self.assert_enter("group change")
        self.device.events.put({"kind": "disconnected"})
        self.runtime.poll()
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.runtime.poll()
        entry = self.assert_enter("reconnect")
        self.assertNotEqual(entry["activity"], "offline")

    def test_failed_switch_flashes_without_reentry(self):
        self.c.button(3)
        self.settle()
        self.windows.activate_result = False
        before = self.c.control_id
        self.c.button(3, self.c.control_id)
        self.runtime.poll()
        frames = [command[1] for command in self.device.commands if command[0] == "frame"]
        self.assertEqual(self.c.control_id, before)
        self.assertEqual(frames[-1]["feedback"], {"kind": "err", "seq": 1})
        self.assertFalse([command for command in self.device.commands if command[0] == "enter"])

    def test_art_key_follows_the_current_identity(self):
        self.runtime.artwork_result = art_result(("playing", "1", ""))
        self.runtime.poll()
        self.c.button(2, self.c.control_id)
        self.assertEqual(self.assert_enter("tracks with art")["artKey"], "cover_1")
        self.c.position(2, self.c.control_id)
        self.c.button(3, self.c.control_id)
        self.runtime.dispatch()
        self.runtime.audio.run_all()
        self.runtime.poll()
        entry, first = self.settle()
        self.assertEqual(entry["artKey"], "cover_1", "the entry keeps the previous cover")
        self.assertEqual(first["artKey"], "", "the old cover is never presented for the new track")


class DecoratorTests(unittest.TestCase):
    def test_raising_decorator_breaks_neither_frame_nor_enter(self):
        c = Controller()
        c.drain()
        plain = c.frame()

        def broken(frame):
            frame["title"] = "half-decorated"
            raise RuntimeError("boom")
        c.decorate = broken
        with self.assertLogs("control_center.controller", "ERROR") as logs:
            self.assertEqual(c.frame(), plain)
            self.assertEqual(c.frame(), plain)
            c._enter()
        self.assertEqual(len(logs.output), 1, "logged once")
        entry, = c.drain()
        self.assertEqual(entry["kind"], "device_enter")
        self.assertEqual(entry["control"]["frame"]["title"], plain["title"])
        self.assertNotIn("_entry", entry["control"]["frame"])
        c.decorate = lambda frame: None
        self.assertEqual(c.frame(), plain)

    def test_decorated_frame_is_returned_and_embedded(self):
        c = Controller()
        c.decorate = lambda frame: {**frame, "ledStyle": "white", "artKey": "k"}
        self.assertEqual((c.frame()["ledStyle"], c.frame()["artKey"]), ("white", "k"))
        self.assertEqual(c.control()["frame"]["artKey"], "k")
        self.assertNotIn("_entry", c.control()["frame"])

    def test_entry_frame_is_the_post_ready_projection(self):
        clock = Clock()
        c = Controller(clock=clock)
        c.complete(c.request("state"), state())
        c.set_hardware(True)
        self.assertEqual((c.frame()["status"], c.frame()["activity"]), ("Connecting knob", "loading"))
        embedded = c.control()["frame"]
        self.assertEqual((embedded["status"], embedded["activity"], embedded["layout"]), ("", "idle", "nowPlaying"))
        c.device_ready(c.control_id)
        self.assertEqual(c.frame(), embedded)

    def test_startup_entry_before_the_first_sonos_read_is_not_loading(self):
        c = Controller(clock=Clock())
        c.set_hardware(True)
        embedded = c.control()["frame"]
        self.assertNotEqual(embedded["activity"], "loading")
        self.assertFalse(c.screen.loading)
        c.device_ready(c.control_id)
        self.assertEqual(c.frame(), embedded)

    def test_reconnect_entry_does_not_show_the_disconnect_notice(self):
        c = Controller()
        c.complete(c.request("state"), state())
        c.disconnected()
        c.set_hardware(True)
        embedded = c.control()["frame"]
        self.assertNotEqual(embedded["activity"], "offline")
        c.device_ready(c.control_id)
        self.assertEqual(c.frame(), embedded)


class EntryOrderTests(unittest.TestCase):
    """A completion applies its own status before re-entering: the embedded entry frame is the
    first post-ready frame (pure controller, hardware attached)."""
    PLAYING = dict(playback="PLAYING", can_pause=True, can_play=False, queue_length=4)

    def setUp(self):
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.c.complete(self.c.request("state"), state(**self.PLAYING))
        self.c.last_poll = self.clock()
        self.c.set_hardware(True)
        self.c.device_ready(self.c.control_id)
        self.c.drain()

    def assert_entry_is_post_ready(self, label):
        entries = [e for e in self.c.drain() if e["kind"] == "device_enter"]
        self.assertEqual(len(entries), 1, label)
        control = entries[0]["control"]
        self.assertEqual(control["id"], self.c.control_id)
        self.c.device_ready(control["id"])
        self.assertEqual(self.c.frame(), control["frame"], label)
        return control["frame"]

    def test_confirmed_volume_after_the_reveal(self):
        self.c.position(29, self.c.control_id)
        self.c.tick()
        volume = next(e for e in self.c.drain() if e["kind"] == "volume")
        self.clock.advance(1.6)
        self.c.complete(volume["request"], state(30, **self.PLAYING))  # Sonos settled elsewhere
        frame = self.assert_entry_is_post_ready("volume confirmed")
        self.assertEqual((frame["layout"], frame["status"], frame["activity"]), ("nowPlaying", "", "idle"))

    def test_failed_volume_write(self):
        self.c.position(29, self.c.control_id)
        self.c.tick()
        volume = next(e for e in self.c.drain() if e["kind"] == "volume")
        self.c.complete(volume["request"], error="The requested volume was not confirmed.")
        frame = self.assert_entry_is_post_ready("volume failed")
        self.assertEqual(frame["feedback"]["kind"], "err")

    def test_sonos_recovery_with_a_new_volume(self):
        self.c.complete(self.c.request("state"), error="Speaker offline")
        self.c.complete(self.c.request("state"), state(28, online=False))
        self.c.drain()
        self.c.complete(self.c.request("state"), state(35, **self.PLAYING))
        frame = self.assert_entry_is_post_ready("Sonos recovered")
        self.assertEqual((frame["layout"], frame["status"], frame["activity"]), ("nowPlaying", "", "idle"))

    def test_group_change_reported_by_a_transport_completion(self):
        self.c.button(0, self.c.control_id)  # Pause
        pause = next(e for e in self.c.drain() if e["kind"] == "transport")
        self.c.complete(pause["request"], state(12, group="group-b", playback="PAUSED_PLAYBACK",
                                                can_pause=False, can_play=True, queue_length=4))
        frame = self.assert_entry_is_post_ready("group change with the pause")
        self.assertEqual(frame["confirmedVolume"], 12)

    def test_skip_ok_entry_carries_the_sweep(self):
        self.c.button(2, self.c.control_id)
        self.c.device_ready(self.c.control_id)
        self.c.position(2, self.c.control_id)
        self.c.button(3, self.c.control_id)
        skip = next(e for e in self.c.drain() if e["kind"] == "transport")
        self.c.complete(skip["request"], state(track_id="track-2", **self.PLAYING))
        frame = self.assert_entry_is_post_ready("skip ok")
        self.assertEqual(frame["feedback"]["skip"], 1)


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.c.complete(self.c.request("state"), state())
        self.c.drain()

    def entry_frame(self):
        entries = [e for e in self.c.drain() if e["kind"] == "device_enter"]
        return entries[-1]["control"]["frame"]

    def test_success_and_failure_sequence(self):
        self.assertIsNone(self.c.feedback)
        self.assertNotIn("feedback", self.c.frame())
        self.c.button(2)
        self.c.position(2)
        self.c.button(3)
        skip = next(e for e in self.c.drain() if e["kind"] == "transport")
        self.c.complete(skip["request"], error="Could not skip")
        self.assertEqual(self.c.frame()["feedback"], {"kind": "err", "seq": 1})
        self.c.button(3)
        skip = next(e for e in self.c.drain() if e["kind"] == "transport")
        self.c.complete(skip["request"], state(track_id="track-2"))
        self.assertEqual(self.entry_frame()["feedback"], {"kind": "ok", "seq": 2, "skip": 1})
        self.assertEqual(self.c.feedback_seq, 2)

    def test_start_success_failure_and_discarded(self):
        def start():
            self.c.button(1)
            request = next(e for e in self.c.drain() if e["kind"] == "recent")
            self.c.complete(request["request"], recent_page(0, 30))
            self.c.button(3)
            return next(e for e in self.c.drain() if e["kind"] == "play_items")
        play = start()
        self.c.complete(play["request"], error="Pending action discarded after connection changed")
        self.assertIsNone(self.c.feedback, "a discarded command is not a user-visible failure")
        play = start()
        self.c.complete(play["request"], error="The selected library item could not play")
        self.assertEqual(self.c.feedback, {"kind": "err", "seq": 1})
        play = start()
        self.c.complete(play["request"], state(title="Album 0"))
        self.assertEqual((self.c.feedback["seq"], self.c.feedback["moment"]), (2, "started"))

    def test_windows_activation_error_and_sequence_wrap(self):
        self.c.feedback_seq = 0x7FFFFFFF
        self.c.button(3)
        opened = next(e for e in self.c.drain() if e["kind"] == "windows_open")
        self.c.complete(opened["request"], {"items": [{"id": "1", "title": "A", "app": "B", "available": True}],
                                             "index": 0, "origin": {}})
        self.c.button(3)
        activate = next(e for e in self.c.drain() if e["kind"] == "windows_activate")
        self.c.complete(activate["request"], error="Windows control failed (OSError)")
        self.assertEqual(self.c.feedback, {"kind": "err", "seq": 1}, "seq wraps within 1..0x7FFFFFFF")

    def test_a_skip_failure_after_leaving_tracks_still_shakes(self):
        """K3 section 8: a failed skip is `err` + the desktop notice, wherever the knob is."""
        self.c.button(2)
        self.c.position(2)
        self.c.button(3)
        skip = next(e for e in self.c.drain() if e["kind"] == "transport")
        self.c.button(0)
        self.c.complete(skip["request"], error="Could not skip")
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.c.notice, "Could not skip")


class RecreationTests(unittest.TestCase):
    def setUp(self):
        self.c = Controller()
        self.runtime = Runtime(self.c, SimulatedSonos(), SimulatedAppleMusic(), SpyWindows(), FakeDevice())
        self.addCleanup(self.runtime.close)

    def test_runtime_decorates_the_queued_entry_and_drops_superseded_ones(self):
        self.assertEqual(self.runtime.led_style, "color")
        entries = [e for e in self.c.effects if e["kind"] == "device_enter"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["control"]["frame"]["ledStyle"], "color")
        other = Controller()
        other._enter()
        other._enter()
        self.runtime.attach(other)
        entries = [e for e in other.effects if e["kind"] == "device_enter"]
        self.assertEqual([e["control"]["id"] for e in entries], [other.control_id])
        self.assertEqual(entries[0]["control"]["frame"]["ledStyle"], "color")
        self.assertIs(self.runtime.controller, other)
        self.assertEqual(self.runtime.frame(), other.frame())
        self.assertEqual(self.runtime.frame()["ledStyle"], "color")

    def test_assigning_the_controller_attaches_it(self):
        other = Controller()
        self.runtime.controller = other
        self.assertEqual(other.decorate, self.runtime._decorate)
        self.assertEqual(other.accent_lookup, self.runtime.accent_of)
        self.assertIs(other.ledger, self.runtime.ledger)

    def test_fresh_controller_keeps_decorator_and_sequence(self):
        self.c.complete(self.c.request("state"), state())
        self.runtime.artwork_result = art_result(self.runtime._art_identity(), key="old_cover")
        self.assertEqual(self.c.frame()["artKey"], "old_cover")
        self.c._feedback("ok")
        self.c._feedback("err")
        self.runtime.led_style = "white"
        self.runtime.last_frame = {"stale": True}
        new = fresh_controller(self.c, self.runtime)
        self.assertIs(self.runtime.controller, new, "attached before its first entry")
        self.assertIsNone(self.runtime.last_frame)
        self.assertEqual(new.decorate, self.runtime._decorate)
        self.assertEqual(new.feedback_seq, 2)
        self.assertIsNone(new.feedback)
        self.assertGreater(new.control_id, self.c.control_id)
        entry, = [e for e in new.effects if e["kind"] == "device_enter"]
        self.assertEqual(entry["control"]["id"], new.control_id)
        self.assertEqual(entry["control"]["frame"]["ledStyle"], "white")
        self.assertEqual(entry["control"]["frame"]["artKey"], "")
        self.runtime.attach(new)  # what standalone does next: idempotent
        entry, = [e for e in new.effects if e["kind"] == "device_enter"]
        self.assertEqual((entry["control"]["frame"]["ledStyle"], entry["control"]["frame"]["artKey"]), ("white", ""))
        new._feedback("ok")
        self.assertEqual(new.feedback, {"kind": "ok", "seq": 3})

    def test_fresh_controller_without_runtime_is_fixed_by_attach(self):
        self.c.complete(self.c.request("state"), state())
        self.runtime.artwork_result = art_result(self.runtime._art_identity(), key="old_cover")
        new = fresh_controller(self.c)
        self.assertEqual(new.decorate, self.runtime._decorate)
        self.runtime.attach(new)
        entry, = [e for e in new.effects if e["kind"] == "device_enter"]
        self.assertEqual(entry["control"]["frame"]["artKey"], "")


class ArtRuleTests(unittest.TestCase):
    def setUp(self):
        self.c = Controller()
        self.c.complete(self.c.request("state"), state())
        self.runtime = Runtime(self.c, SimulatedSonos(), SimulatedAppleMusic(), SpyWindows(), FakeDevice())
        self.addCleanup(self.runtime.close)

    def test_art_requires_matching_identity_and_ignores_activity(self):
        self.runtime.artwork_result = art_result(("playing", "track-1", ""))
        self.assertEqual(self.c.frame()["artKey"], "cover_1")
        self.c.position(40)
        self.assertEqual(self.c.frame()["activity"], "pending")
        self.assertEqual(self.c.frame()["artKey"], "cover_1", "art never depends on activity")
        self.c.state["track_id"] = "track-2"
        self.assertEqual(self.c.frame()["artKey"], "", "a result for another identity is never shown")
        self.runtime.artwork_result = art_result(("playing", "track-2", ""))
        self.runtime.artwork_enabled = False
        self.assertEqual(self.c.frame()["artKey"], "")

    def test_art_hidden_on_windows_and_notice_but_kept_on_idle_and_seek(self):
        self.runtime.artwork_result = art_result(("playing", "track-1", ""))
        for layout in ("windows", "notice"):
            with self.subTest(layout=layout):
                self.assertFalse(self.runtime._art_allowed({"layout": layout}))
        for layout in ("nowPlaying", "volume", "idle", "tracks", "seek"):
            self.assertTrue(self.runtime._art_allowed({"layout": layout}))
        self.c.screen = Screen(mode="windows", status="", windows={"items": [
            {"id": "w", "title": "W", "app": "A", "available": True}]})
        self.runtime.artwork_result = art_result(self.runtime._art_identity())
        self.assertEqual(self.c.frame()["artKey"], "")

    def test_recent_items_follow_the_focused_item(self):
        self.c.button(1)
        request = next(e for e in self.c.drain() if e["kind"] == "recent")
        self.c.complete(request["request"], recent_page(0, 30))
        self.assertEqual(self.runtime._art_identity()[:2], ("recent", "album-0"))
        self.c.position(4)
        self.assertEqual(self.runtime._art_identity()[:2], ("recent", "album-4"))


class ArtworkEventTests(RuntimeCase):
    def arm(self):
        self.runtime.artwork_result = art_result(("playing", "1", ""))
        self.runtime.poll()
        sent = [command for command in self.device.commands if command[0] == "artwork"]
        self.assertEqual(len(sent), 1)
        self.device.commands.clear()
        return (self.c.control_id, "cover_1")

    def artwork_commands(self):
        commands = [command for command in self.device.commands if command[0] == "artwork"]
        self.device.commands.clear()
        return commands

    def test_mismatch_from_the_bridge_is_status_only(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = DeviceClock()
            bridge = DeviceBridge(temp, lambda port: FakeSerial(clock), request_timeout=0.1,
                                  autostart=False, clock=clock)
            bridge._connect("COM-FAKE")
            bridge.capabilities["artwork"] = {"version": 1, "width": 120, "height": 120,
                                              "format": "RGB565_LE", "chunkBytes": 384}
            bridge._enter({**device_control(), "frame": {**device_frame(), "artKey": "cover_1"}})
            while not bridge.events.empty():
                bridge.events.get_nowait()
            bridge._queue_artwork({"id": 1, "key": "cover_1", "data": b"short"})
            self.device.events = bridge.events
        hotkey, ready, supported = list(self.windows.hotkey), self.c.ready, self.runtime.device_supported
        self.runtime.poll()
        self.assertEqual((self.runtime.device_supported, self.c.ready, self.windows.hotkey),
                         (supported, ready, hotkey))
        self.assertEqual((self.runtime.artwork_status["state"], self.runtime.artwork_status["reason"]),
                         ("error", "size"))
        self.assertIsNone(self.runtime._art_retry)
        self.assertNotIn("short", repr(self.runtime.artwork_status))

    def test_transient_error_retries_once_after_a_second(self):
        identity = self.arm()
        event = {"kind": "artwork-error", "id": identity[0], "key": identity[1], "reason": "timeout",
                 "transient": True, "retrying": False, "message": "raw firmware text"}
        self.device.events.put(dict(event))
        self.runtime.poll()
        self.assertEqual(self.artwork_commands(), [])
        self.assertEqual(self.runtime.artwork_status["message"], "Album artwork transfer timed out.")
        self.monotonic.now += ART_RETRY_SECONDS - 0.01
        self.runtime.poll()
        self.assertEqual(self.artwork_commands(), [])
        self.monotonic.now += 0.02
        self.runtime.poll()
        self.assertEqual(len(self.artwork_commands()), 1, "one delayed retry")
        self.device.events.put(dict(event))
        self.runtime.poll()
        self.monotonic.now += 5
        for _ in range(5):
            self.runtime.poll()
        self.assertEqual(self.artwork_commands(), [], "never a second retry for the same control and key")
        self.assertTrue(self.runtime.device_supported)

    def test_no_runtime_retry_while_bridge_retries_or_for_final_or_stale_errors(self):
        identity = self.arm()
        for event in ({"reason": "parse", "retrying": True},
                      {"reason": "parse", "transient": False},
                      {"reason": "rejected"},
                      {"reason": "timeout", "id": identity[0] - 1}):
            self.device.events.put({"kind": "artwork-error", "id": identity[0], "key": identity[1], **event})
        self.runtime.poll()
        self.monotonic.now += 5
        self.runtime.poll()
        self.assertEqual(self.artwork_commands(), [])

    def test_ready_event_records_status(self):
        identity = self.arm()
        self.device.events.put({"kind": "artwork-ready", "id": identity[0], "key": identity[1]})
        self.runtime.poll()
        self.assertEqual(self.runtime.artwork_status["state"], "ready")

    def test_empty_art_key_lets_an_aborted_upload_resume(self):
        identity = self.arm()
        self.assertEqual(self.runtime._art_sent, identity)
        self.runtime.artwork_enabled = False  # frame now carries no art
        self.runtime.poll()
        self.assertIsNone(self.runtime._art_sent)
        self.runtime.artwork_enabled = True
        self.runtime.poll()
        self.assertEqual(len(self.artwork_commands()), 1)


if __name__ == "__main__":
    unittest.main()

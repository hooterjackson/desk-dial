"""Control-center behaviour and deterministic concurrency on the desktop v7 grammar
(CONTROL_CENTER_V5.md sections 3-5 and 10); no device or network I/O.

Also the shared fixtures other suites import (Clock, state, page, windows_snapshot,
ControllerFixture, ManualExecutor, FakeDevice, FakeWidget, FakeVariable, CountingSonos).
"""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center.controller import Controller
from control_center.runtime import Runtime, failure
from control_center.apple_music import MusicUnavailable
from control_center.simulation import SimulatedSonos, SimulatedAppleMusic, SimulatedWindows
from cc5_support import (Clock, FakeDevice, ManualExecutor, page, queue_state, recent_page, state,  # noqa: F401
                         windows_snapshot)


class ControllerFixture(unittest.TestCase):
    """A controller on a fake clock after one v6-shaped Sonos state (Home, playing)."""

    def setUp(self):
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.publish(state())
        self.c.last_poll = self.clock()

    def publish(self, value):
        request = self.c.request("state")
        self.c.complete(request, value)
        self.c.drain()

    def effects(self, kind=None):
        effects = self.c.drain()
        return [e for e in effects if kind is None or e["kind"] == kind]

    def one(self, kind):
        effects = self.effects(kind)
        self.assertEqual(len(effects), 1, effects)
        return effects[0]

    def recent(self, total=30):
        """Home 2 (Browse) and the first page."""
        self.c.button(1)
        effect = self.one("recent")
        self.c.complete(effect["request"], recent_page(0, total))
        self.c.drain()

    def tracks(self, index=1):
        """Home 3 (Tracks)."""
        self.c.button(2)
        self.c.position(index)
        self.c.drain()

    def open_windows(self):
        """Home 4 (Win) without a hotkey."""
        self.c.button(3)
        effect = self.one("windows_open")
        snapshot = windows_snapshot()
        self.c.complete(effect["request"], snapshot)
        self.c.drain()
        return snapshot


class NavigationTests(ControllerFixture):
    def test_home_buttons(self):
        self.c.button(2)
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 1))
        self.c.button(0)
        self.assertEqual(self.c.screen.mode, "home")
        self.c.button(1)
        self.assertEqual(self.c.screen.mode, "recent")
        request = self.one("recent")
        self.assertEqual((request["offset"], request["visit"]), (0, None))

    def test_transport_neutral_does_not_dispatch(self):
        self.tracks()
        self.c.button(3)
        self.assertFalse(self.effects("transport"))
        self.assertFalse(self.c.frame()["buttons"][3]["enabled"])

    def test_transport_success_stays_and_recenters(self):
        self.tracks(0)
        self.c.button(3)
        request = self.one("transport")
        self.assertEqual(request["direction"], "previous")
        self.c.complete(request["request"], state(track_id="track-0"))
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 1))

    def test_transport_is_not_issued_twice_while_pending(self):
        self.tracks(2)
        for _ in range(6):
            self.c.button(3)
        command = self.one("transport")
        self.c.complete(command["request"], state())
        self.c.button(3)
        self.assertFalse(self.effects("transport"))

    def test_offline_disabled_transport_really_cannot_execute(self):
        self.tracks(2)
        request = self.c.request("state")
        self.c.complete(request, error="Speaker offline")
        self.c.drain()
        self.assertFalse(self.c.frame()["buttons"][3]["enabled"])
        self.c.button(3)
        self.assertEqual(self.effects("transport"), [])

    def test_completed_skip_does_not_pull_the_user_back_from_another_mode(self):
        self.tracks(2)
        self.c.button(3)
        request = self.one("transport")
        self.c.button(0)
        self.c.complete(request["request"], state(track_id="track-2"))
        self.assertEqual(self.c.screen.mode, "home")

    def test_recent_play_goes_home_at_once(self):
        self.recent()
        self.c.position(3)
        self.c.button(3)
        start = self.one("play_items")
        self.assertEqual(start["item"]["id"], "album-3")
        self.assertEqual((self.c.screen.mode, self.c.frame()["status"]), ("home", "Starting…"))

    def test_unavailable_recent_item_has_no_action(self):
        self.c.button(1)
        self.c.complete(self.one("recent")["request"], recent_page(0, 30, overrides={2: {"available": False}}))
        self.c.position(2)
        self.c.button(3)
        self.c.button(2)
        self.assertFalse([e for e in self.effects() if e["kind"] in ("play_items", "play_next")])

    def test_stale_library_response_cannot_replace_a_new_visit(self):
        self.c.button(1)
        old = self.one("recent")
        self.c.button(0)
        self.c.button(1)
        new = self.one("recent")
        self.c.complete(old["request"], recent_page(0, 30))
        self.assertEqual(self.c.recent.items, [])
        self.c.complete(new["request"], recent_page(0, 30))
        self.assertEqual(len(self.c.recent.items), 25)

    def test_windows_back_returns_home(self):
        self.open_windows()
        self.c.button(0)
        self.assertEqual(self.one("windows_cancel")["home"], True)
        self.assertEqual(self.c.screen.mode, "home")

    def test_window_switch_returns_home(self):
        snapshot = self.open_windows()
        self.c.position(2)
        self.c.drain()
        self.c.button(3)
        command = self.one("windows_activate")
        self.assertEqual(command["item"]["id"], snapshot["items"][2]["id"])
        self.c.complete(command["request"], True)
        self.assertEqual(self.c.screen.mode, "home")

    def test_closed_windows_stay_selected_but_cannot_be_confirmed(self):
        self.open_windows()
        self.c.screen.windows.items[1]["available"] = False
        self.c.button(3)
        self.assertFalse(self.effects("windows_activate"))
        self.assertEqual(self.c.frame()["meta"], "Closed · can’t switch")

    def test_external_focus_loss_does_not_request_origin_focus_restore(self):
        self.open_windows()
        self.c.dismiss_windows()
        kinds = [e["kind"] for e in self.effects()]
        self.assertIn("windows_hide", kinds)
        self.assertNotIn("windows_cancel", kinds)
        self.assertEqual(self.c.screen.mode, "home")

    def test_skip_completing_under_the_picker_raises_no_toast(self):
        self.tracks(2)
        self.c.button(3)
        request = self.one("transport")
        self.c.button(0)
        self.open_windows()
        self.c.complete(request["request"], state(track_id="track-2"))
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertFalse(self.effects("toast"), "no toast over an open overlay")

    def test_late_play_failure_keeps_the_mode(self):
        self.recent()
        self.c.button(3)
        start = self.one("play_items")
        self.open_windows()
        self.c.complete(start["request"], error=failure(RuntimeError("Sonos refused"), op="play_items"))
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertEqual(self.c.feedback["kind"], "err")


class PositionAndResponseTests(ControllerFixture):
    def test_absolute_positions_are_not_capped_to_small_deltas(self):
        self.c.position(94)
        self.assertEqual(self.c.display_volume, 94)
        self.c.position(3)
        self.assertEqual(self.c.display_volume, 3)

    def test_input_positions_reject_invalid_types_and_bounds(self):
        for value in (True, 1.0, "20", None, -1, 101):
            self.c.position(value)
        self.assertEqual(self.c.display_volume, 28)

    def test_rapid_input_before_dispatch_coalesces_to_latest_absolute_value(self):
        for value in (40, 85, 77, 24, 39):
            self.c.position(value)
        self.c.tick()
        self.assertEqual(self.one("volume")["value"], 39)

    def test_reversal_while_write_inflight_preserves_latest_target(self):
        self.c.position(80)
        self.c.tick()
        request = self.one("volume")
        self.c.position(19)
        self.c.complete(request["request"], state(80))
        self.assertEqual(self.c.display_volume, 19)
        self.assertEqual(self.c.state["volume"], 80)
        self.clock.advance(0.11)
        self.c.tick()
        self.assertEqual(self.one("volume")["value"], 19)

    def test_confirming_current_dial_value_does_not_reenter_haptic_profile(self):
        self.c.position(50)
        self.c.tick()
        request = self.one("volume")
        control_id = self.c.control_id
        self.c.complete(request["request"], state(50))
        self.assertEqual(self.c.control_id, control_id)
        self.assertFalse(self.effects("device_enter"))
        self.assertEqual(self.c.display_volume, 50)

    def test_external_volume_change_rebases_the_absolute_control(self):
        before = self.c.control_id
        request = self.c.request("state")
        self.c.complete(request, state(68))
        self.assertGreater(self.c.control_id, before)
        self.assertEqual(self.c.control()["position"], 68)

    def test_group_change_drops_unissued_volume_intent(self):
        self.c.position(91)
        self.publish(state(12, group="group-b"))
        self.c.tick()
        self.assertEqual(self.c.display_volume, 12)
        self.assertIsNone(self.c.desired_volume)
        self.assertFalse(self.effects("volume"))

    def test_state_error_drops_volume_intent_and_prevents_offline_write(self):
        self.c.position(67)
        request = self.c.request("state")
        self.c.complete(request, error="Speaker offline")
        self.c.drain()
        self.c.tick()
        self.assertIsNone(self.c.desired_volume)
        self.assertFalse(self.effects("volume"))

    def test_old_group_write_failure_does_not_discard_new_group_intent(self):
        self.c.position(65)
        self.c.tick()
        old = self.one("volume")
        self.publish(state(12, group="group-b"))
        self.c.position(23)
        self.c.complete(old["request"], error="The Sonos group changed")
        self.assertEqual(self.c.display_volume, 23)
        self.clock.advance(0.11)
        self.c.tick()
        command = self.one("volume")
        self.assertEqual((command["value"], command["expected_group_revision"]), (23, "group-b"))

    def test_stale_device_id_cannot_turn_or_navigate(self):
        previous = self.c.control_id
        self.c.button(2)
        self.c.drain()
        self.c.position(2, previous)
        self.c.button(1, previous)
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 1))

    def test_hardware_requires_matching_ready_ack(self):
        self.c.set_hardware(True)
        current = self.c.control_id
        self.c.device_ready(current - 1)
        self.c.position(77, current)
        self.assertEqual(self.c.display_volume, 28)
        self.c.device_ready(current)
        self.c.position(77, current)
        self.assertEqual(self.c.display_volume, 77)

    def test_unknown_and_duplicate_completions_are_ignored(self):
        original = deepcopy(self.c.state)
        self.c.complete(123456, state(99))
        request = self.c.request("state")
        self.c.complete(request, original)
        self.c.complete(request, state(99))
        self.assertEqual(self.c.state, original)


class CountingSonos(SimulatedSonos):
    def __init__(self):
        super().__init__()
        self.volumes = []
        self.skips = []
        self.plays = []

    def set_volume(self, value, expected_group_revision):
        self.volumes.append(value)
        return super().set_volume(value, expected_group_revision)

    def transport(self, *args):
        self.skips.append(args)
        return super().transport(*args)

    def play_items(self, items, expected_group_revision):
        self.plays.append(deepcopy(items))
        return super().play_items(items, expected_group_revision)


class CountingWindows(SimulatedWindows):
    def __init__(self):
        super().__init__()
        self.opened_on = []

    def snapshot(self):
        self.opened_on.append(threading.get_ident())
        return super().snapshot()


class RuntimeConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.patch_executor = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        self.patch_executor.start()
        self.addCleanup(self.patch_executor.stop)
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.sonos, self.apple, self.windows = CountingSonos(), SimulatedAppleMusic(), CountingWindows()
        request = self.c.request("state")
        self.c.complete(request, self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()
        self.device = FakeDevice()
        self.runtime = Runtime(self.c, self.sonos, self.apple, self.windows, self.device)
        self.addCleanup(self.runtime.close)

    def tick_dispatch(self):
        self.c.tick()
        self.runtime.dispatch()

    def browse(self):
        self.c.button(1)
        self.runtime.dispatch()
        self.runtime.library.run_next()
        self.runtime.poll()

    def test_library_fetch_can_finish_while_audio_lane_is_busy(self):
        self.c.position(42)
        self.tick_dispatch()
        self.c.button(1)
        self.runtime.dispatch()
        self.assertEqual(len(self.runtime.audio.jobs), 1)
        self.assertEqual(len(self.runtime.library.jobs), 1)
        self.runtime.library.run_next()
        self.runtime.poll()
        self.assertEqual(self.c.screen.mode, "recent")
        self.assertEqual(len(self.c.recent.items), 25)
        self.assertEqual(self.sonos.volumes, [])

    def test_stale_queued_library_reads_do_not_delay_current_browse(self):
        calls = []
        original = self.apple.recent_page

        def counted(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)
        self.apple.recent_page = counted
        self.c.button(1)
        self.runtime.dispatch()
        self.c.button(0)
        self.c.button(1)
        self.runtime.dispatch()
        self.runtime.library.run_next()
        self.assertEqual(calls, [], "The obsolete queued visit should not make an Apple API request")
        self.runtime.library.run_next()
        self.runtime.poll()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.c.screen.mode, "recent")
        self.assertEqual(len(self.c.recent.items), 25)

    def test_windows_effects_execute_on_ui_thread_without_audio_executor(self):
        self.c.button(3)
        self.runtime.dispatch()
        self.assertEqual(self.windows.opened_on, [threading.get_ident()])
        self.assertEqual(self.runtime.audio.jobs, [])
        self.assertEqual(self.c.screen.mode, "windows")

    def test_pending_volume_is_coalesced_while_executor_is_busy(self):
        self.c.position(40)
        self.tick_dispatch()
        for value in (75, 21, 32):
            self.c.position(value)
        self.runtime.audio.run_next()
        self.assertNotIn(40, self.sonos.volumes,
                         "An obsolete queued target must not be applied before the latest absolute position")

    def test_physical_reversal_processed_this_poll_replaces_queued_target(self):
        self.c.position(40)
        self.tick_dispatch()
        for value in (60, 70, 23):
            self.device.events.put({"kind": "position", "position": value, "id": self.c.control_id})
        self.runtime.poll()
        self.runtime.audio.run_next()
        self.assertEqual(self.sonos.volumes, [23])

    def test_io_lane_throttle_reads_latest_intent_after_waiting(self):
        self.clock.now = 200.02
        self.c.last_poll = self.clock()
        self.runtime._last_volume_complete = 200.0
        self.c.position(40)
        self.tick_dispatch()
        waits = []

        def wait(seconds):
            waits.append(seconds)
            self.clock.advance(seconds)
            self.c.position(23)  # A reversal while the worker is throttled.
        with patch("control_center.runtime.time.monotonic", self.clock), \
             patch("control_center.runtime.time.sleep", wait):
            self.runtime.audio.run_next()
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], 0.08)
        self.assertEqual(self.sonos.volumes, [23])
        self.assertGreaterEqual(self.runtime._last_volume_complete, 200.1)

    def test_disconnect_during_throttle_wait_is_rechecked_before_write(self):
        self.clock.now = 200.02
        self.c.last_poll = self.clock()
        self.runtime._last_volume_complete = 200.0
        self.c.position(40)
        self.tick_dispatch()

        def wait(seconds):
            self.clock.advance(seconds)
            self.device.events.put({"kind": "disconnected"})
            self.runtime._device_events()
        with patch("control_center.runtime.time.monotonic", self.clock), \
             patch("control_center.runtime.time.sleep", wait):
            self.runtime.audio.run_next()
        self.assertEqual(self.sonos.volumes, [])

    def test_disconnect_drops_volume_effect_not_yet_dispatched(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c.position(65)
        self.c.tick()
        self.device.events.put({"kind": "disconnected"})
        self.runtime._device_events()
        self.runtime.dispatch()
        self.runtime.audio.run_all()
        self.assertEqual(self.sonos.volumes, [])

    def test_disconnect_drops_transport_effect_not_yet_dispatched(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c.button(2)
        self.c.position(2)
        self.c.button(3)
        self.device.events.put({"kind": "disconnected"})
        self.runtime._device_events()
        self.runtime.dispatch()
        self.runtime.audio.run_all()
        self.assertEqual(self.sonos.skips, [])

    def test_disconnect_drops_play_effect_not_yet_dispatched(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.browse()
        self.c.button(3)
        self.device.events.put({"kind": "disconnected"})
        self.runtime._device_events()
        self.runtime.dispatch()
        self.runtime.library.run_all()
        self.runtime.audio.run_all()
        self.assertEqual(self.sonos.plays, [])
        self.assertIsNone(self.c.start, "the dropped start releases the busy dims")

    def test_disconnect_drops_already_queued_but_unstarted_volume(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c.position(65)
        self.tick_dispatch()
        self.device.events.put({"kind": "disconnected"})
        self.runtime._device_events()
        self.runtime.audio.run_all()
        self.assertEqual(self.sonos.volumes, [])

    def test_group_change_drops_queued_volume_before_provider_invocation(self):
        self.c.position(65)
        self.tick_dispatch()
        changed = deepcopy(self.sonos.state)
        changed.update(group_revision="new-group", volume=12)
        self.sonos.state = changed
        request = self.c.request("state")
        self.c.complete(request, changed)
        self.runtime.audio.run_all()
        self.assertEqual(self.sonos.volumes, [])

    def test_group_response_processed_this_poll_invalidates_queued_volume(self):
        self.c.position(65)
        self.tick_dispatch()
        changed = deepcopy(self.sonos.state)
        changed.update(group_revision="new-group", volume=12)
        self.sonos.state = changed
        request = self.c.request("state")
        self.runtime.results.put((request, changed, None))
        self.runtime.poll()
        self.runtime.audio.run_next()
        self.assertEqual(self.sonos.volumes, [])

    def test_resolving_apple_item_does_not_occupy_audio_lane(self):
        self.browse()
        self.c.button(3)
        self.runtime.dispatch()
        self.assertEqual(len(self.runtime.library.jobs), 1)
        self.assertEqual(self.runtime.audio.jobs, [])
        self.c.position(43)
        self.tick_dispatch()
        self.runtime.audio.run_next()
        self.assertEqual(self.sonos.volumes, [43])
        self.assertEqual(self.sonos.plays, [])

    def test_disconnect_during_apple_resolution_cannot_start_playback(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.browse()
        self.c.button(3)
        self.runtime.dispatch()
        self.device.events.put({"kind": "disconnected"})
        self.runtime._device_events()
        self.runtime.library.run_next()
        self.runtime.audio.run_all()
        self.assertEqual(self.sonos.plays, [])

    def test_no_frame_until_matching_device_entry_is_acknowledged(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c.set_hardware(True)
        entry_id = self.c.control_id
        self.runtime.poll()
        self.assertEqual([c[0] for c in self.device.commands], ["enter"])
        self.device.events.put({"kind": "ready", "id": entry_id - 1})
        self.runtime.poll()
        self.assertFalse(any(command[0] == "frame" for command in self.device.commands))
        self.device.events.put({"kind": "ready", "id": entry_id})
        self.runtime.poll()
        frames = [command for command in self.device.commands if command[0] == "frame"]
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][1]["id"], entry_id)

    def test_only_latest_undispatched_device_entry_is_sent(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.c._enter()
        self.c._enter()
        self.runtime.dispatch()
        entries = [command for command in self.device.commands if command[0] == "enter"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1]["id"], self.c.control_id)

    def test_f24_requires_supported_connected_device(self):
        self.runtime.hotkey()
        self.assertEqual(self.windows.opened_on, [])
        self.runtime.device_connected = self.runtime.device_supported = True
        self.runtime.hotkey()
        self.assertEqual(len(self.windows.opened_on), 1)

    def test_f24_does_not_open_picker_during_button_calibration(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.runtime.on_button_probe = lambda raw: None
        self.runtime.hotkey()
        self.assertEqual(self.windows.opened_on, [])

    def test_hid_tagged_serial_edge_does_not_reopen_picker(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.runtime.hotkey()
        self.device.events.put({"kind": "button", "button": 3, "id": self.c.control_id, "hid": True})
        self.runtime._device_events()
        self.runtime.dispatch()
        self.assertEqual(len(self.windows.opened_on), 1)

    def test_physical_windows_button_uses_serial_fallback_in_simulator(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.assertFalse(self.windows.supports_hotkey)
        self.device.events.put({"kind": "button", "button": 3, "id": self.c.control_id})
        self.runtime.poll()
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertEqual(len(self.windows.opened_on), 1)

    def test_shutdown_cancels_unstarted_worker_commands(self):
        self.c.position(60)
        self.tick_dispatch()
        self.runtime.close()
        self.runtime.audio.run_all()
        self.assertEqual(self.sonos.volumes, [])


class FakeWidget:
    def __init__(self, *args, **kwargs):
        self.values = dict(kwargs)
        self.protocols = {}
        self.destroyed = False

    def pack(self, *args, **kwargs): pass
    def title(self, *args): pass
    def geometry(self, *args): pass
    def transient(self, *args): pass
    def lift(self): pass
    def configure(self, **kwargs): self.values.update(kwargs)
    def protocol(self, name, callback): self.protocols[name] = callback
    def winfo_exists(self): return not self.destroyed
    def destroy(self): self.destroyed = True


class UnavailablePlaybackTests(ControllerFixture):
    def start_play(self):
        self.recent()
        self.c.position(3)
        self.c.button(3)
        return self.one("play_items")

    def test_unresolvable_item_is_disabled_for_this_browsing_visit(self):
        command = self.start_play()
        self.c.complete(command["request"], error=failure(MusicUnavailable("Saved track has no catalog match"),
                                                          op="play_items", kind="album"))
        item = self.c.recent.items[3]
        self.assertFalse(item["available"])
        self.assertEqual(item["reason"], "Saved track has no catalog match")
        self.assertEqual(self.c.frame()["status"], "Album unavailable")

    def test_authorization_failure_keeps_item_retryable(self):
        command = self.start_play()
        self.c.complete(command["request"], error=failure(RuntimeError("Music authorization expired"),
                                                          op="play_items"))
        self.assertTrue(self.c.recent.items[3]["available"])
        self.assertEqual(self.c.frame()["status"], "Didn’t start")


class FakeVariable:
    def __init__(self, value=""):
        self.value = value

    def get(self): return self.value
    def set(self, value): self.value = value


class SetupConfigurationTests(unittest.TestCase):
    """Exercise real setup callbacks against fake widgets, without starting Tk."""
    def setUp(self):
        from control_center import ui
        self.ui = ui
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)
        self.patch_data = patch.object(ui, "DATA_DIR", self.data_dir)
        self.patch_data.start()
        self.addCleanup(self.patch_data.stop)
        self.buttons = {}
        self.variables = []

        def button(parent, text, command, **kwargs):
            self.buttons[text] = command
            return FakeWidget()

        def variable(*args, **kwargs):
            result = FakeVariable(*args, **kwargs)
            self.variables.append(result)
            return result
        for target, name, value in (
            (ui, "button", button), (ui, "label", lambda *a, **k: FakeWidget(**k)),
            (ui.tk, "Toplevel", FakeWidget), (ui.tk, "Frame", FakeWidget),
            (ui.tk, "Entry", FakeWidget), (ui.tk, "StringVar", variable),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = object.__new__(ui.ControlCenterApp)
        self.app.root = FakeWidget()
        self.app.setup_window = None
        self.app.auth = None
        self.app.device = FakeDevice()
        self.app.config = {"speaker_ip": "192.0.2.120", "port": "COM8",
                           "button_order": [0, 1, 2, 3], "button_order_verified": False}
        self.app.runtime = SimpleNamespace(device_connected=True, device_supported=True,
                                           button_order=[0, 1, 2, 3], on_button_probe=None)
        self.app.controller = SimpleNamespace(ready=True)

    def test_reconnect_applies_saved_mapping_as_a_copy(self):
        self.app.config["button_order"] = [3, 1, 0, 2]
        self.app.runtime.device_connected = False
        self.app.connect()
        self.assertEqual(self.app.runtime.button_order, [3, 1, 0, 2])
        self.assertIsNot(self.app.runtime.button_order, self.app.config["button_order"])
        self.assertEqual(self.app.device.commands, [("connect", "COM8")])

    def test_calibration_needs_four_distinct_buttons_in_recorded_order(self):
        self.app.setup()
        self.buttons["Verify physical button order"]()
        probe = self.app.runtime.on_button_probe
        for raw in (3, 3, 1, 0):
            probe(raw)
        self.assertIs(self.app.runtime.on_button_probe, probe)
        self.assertEqual(self.variables[2].get(), "0,1,2,3")
        probe(2)
        self.assertIsNone(self.app.runtime.on_button_probe)
        self.assertEqual(self.variables[2].get(), "3,1,0,2")

    def test_saving_mapping_does_not_change_active_firmware_mapping_mid_connection(self):
        self.app.setup()
        self.variables[2].set("3,1,0,2")
        self.buttons["Save settings"]()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["button_order"], [3, 1, 0, 2])
        self.assertEqual(self.app.runtime.button_order, [0, 1, 2, 3])

    def test_calibration_is_unavailable_until_device_is_ready(self):
        self.app.runtime.device_supported = False
        self.app.setup()
        self.buttons["Verify physical button order"]()
        self.assertIsNone(self.app.runtime.on_button_probe)

    def test_closing_setup_clears_calibration_interception(self):
        self.app.setup()
        self.buttons["Verify physical button order"]()
        self.app.setup_window.protocols["WM_DELETE_WINDOW"]()
        self.assertIsNone(self.app.runtime.on_button_probe)
        self.assertTrue(self.app.setup_window.destroyed)

    def test_invalid_saved_mapping_falls_back_without_crashing_startup(self):
        for invalid in (None, [0, "1", 2, 3], [0, 0, 2, 3]):
            with self.subTest(invalid=invalid):
                (self.data_dir / "settings.json").write_text(json.dumps({"button_order": invalid}), encoding="utf-8")
                config = self.ui.ControlCenterApp.load_config()
                self.assertEqual(config["button_order"], [0, 1, 2, 3])
                self.assertFalse(config["button_order_verified"])


if __name__ == "__main__":
    unittest.main()

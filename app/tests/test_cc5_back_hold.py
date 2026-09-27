"""K3 section 4: Back targets, the firmware hold (`kh`) and F24 / `hid` routing (C5-8 withdrawn, C5-12, C5-36)."""
import unittest

from cc5_support import Fixture, Harness, queue_state


class BackTargetTests(Fixture):
    def test_recent_back_goes_home_at_the_volume(self):
        self.browse()
        self.press(0)
        self.assertEqual((self.c.screen.mode, self.c.bounds()[2]), ("home", 28))

    def test_explorer_back_returns_to_the_recent_index(self):
        self.browse()
        self.turn_to(4)
        self.press(1)
        self.turn_to(7)
        self.c.drain()
        self.press(0)
        close = self.one("explorer_close", self.c.effects[:])
        self.assertEqual(close["reason"], "back")
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("recent", 7))

    def test_tracks_back_goes_home(self):
        self.tracks(2)
        self.press(0)
        self.assertEqual(self.c.screen.mode, "home")

    def test_seek_back_goes_to_tracks_neutral(self):
        self.seek()
        self.press(0)
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 1))

    def test_upnext_back_returns_to_the_saved_tracks_index(self):
        self.tracks(2)
        self.press(1)
        self.c.drain()
        self.turn_to(3)
        self.press(0)
        self.assertEqual(self.one("upnext_close")["reason"], "back")
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 2))

    def test_windows_back_goes_home_with_windows_cancel(self):
        self.open_windows()
        self.press(0)
        cancel = self.one("windows_cancel")
        self.assertEqual((cancel["home"], cancel["complete"]), (True, None))
        self.assertEqual(self.c.screen.mode, "home")


class HoldTests(Fixture):
    def test_hold_on_home_does_nothing(self):
        control = self.c.control_id
        self.hold()
        self.assertEqual((self.c.screen.mode, self.c.control_id), ("home", control))

    def test_hold_from_every_mode_goes_home(self):
        cases = {"recent": self.browse, "tracks": lambda: self.tracks(2), "seek": self.seek,
                 "upnext": self.upnext, "windows": self.open_windows}
        for mode, enter in cases.items():
            with self.subTest(mode=mode):
                enter()
                self.c.drain()
                self.assertEqual(self.c.screen.mode, mode)
                self.hold()
                effects = self.effects()
                self.assertEqual(self.c.screen.mode, "home")
                if mode == "upnext":
                    self.assertEqual([e["reason"] for e in effects if e["kind"] == "upnext_close"], ["hold"])
                if mode == "windows":
                    self.assertEqual(len([e for e in effects if e["kind"] == "windows_cancel"]), 1)

    def test_explorer_hold_closes_with_hold(self):
        self.browse()
        self.press(1)
        self.c.drain()
        self.hold()
        self.assertEqual(self.one("explorer_close")["reason"], "hold")
        self.assertEqual(self.c.screen.mode, "home")

    def test_one_action_per_hold_event(self):
        self.browse()
        self.hold()
        control = self.c.control_id
        self.hold()                       # the same event again on Home: nothing
        self.assertEqual(self.c.control_id, control)

    def test_hold_right_after_ready_without_a_kd_goes_home(self):
        """K1 section 11.2 step 5: a long press latched while entering is sent after `ready`."""
        self.c.hardware = True
        self.browse()
        self.c.device_ready(self.c.control_id)
        self.press(0)                     # Back: a re-entry, knob blind until ready
        self.assertFalse(self.c.ready)
        self.c.device_ready(self.c.control_id)
        self.c.hold(0, self.c.control_id)
        self.assertEqual(self.c.screen.mode, "home")

    def test_hold_of_an_old_control_or_another_button_is_ignored(self):
        self.browse()
        self.c.hold(0, self.c.control_id - 1)
        self.c.hold(1, self.c.control_id)
        self.assertEqual(self.c.screen.mode, "recent")

    def test_no_host_hold_timer(self):
        """A ready with logical 0 held and no `kh` does nothing, whatever time passes."""
        self.c.hardware = True
        self.browse()
        self.c.device_ready(self.c.control_id)
        self.tick(5.0)
        self.assertEqual(self.c.screen.mode, "recent")

    def test_seek_hold_flushes_the_debouncing_target(self):
        self.seek()
        self.turn_to(self.c.screen.index + 3)
        self.hold()
        seeks = self.effects("seek")
        self.assertEqual(len(seeks), 1)
        self.assertEqual(self.c.screen.mode, "home")

    def test_no_toast_after_any_hold_close(self):
        self.upnext()
        self.ratings()
        self.c.music_signin_expired = True
        self.press(2)                     # arms the sign-in exit toast
        self.hold()
        self.tick(1.0)
        self.assertFalse(self.effects("toast"))

    def test_hold_ignored_in_the_play_window(self):
        self.upnext()
        self.ratings()
        self.turn_to(6)
        self.press(3)
        self.tick(0.1)
        self.hold()
        self.assertEqual(self.c.screen.mode, "upnext")
        self.tick(0.3)
        self.assertEqual(self.c.screen.mode, "home")

    def test_latched_while_a_snap_is_in_flight(self):
        self.open_windows()
        self.press(1)                     # snap left
        self.hold()
        self.assertEqual(self.c.screen.mode, "windows")
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.assertEqual(self.c.screen.mode, "home")


class HidRoutingTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(self)
        self.h.runtime.device_connected = self.h.runtime.device_supported = True
        self.h.windows.supports_hotkey = True
        self.h.runtime.presentation_level = 5
        self.h.run(1)                     # the first Sonos state read

    def kd(self, logical, hid=False):
        self.h.device.events.put({"kind": "button", "id": self.h.c.control_id, "button": logical,
                                  "pressed": True, "hid": hid})
        self.h.runtime.poll()

    def test_hid_tagged_logical_3_is_dropped(self):
        self.kd(3, hid=True)
        self.assertFalse(any(e["kind"] == "windows_open" for e in self.h.c.pending.values()))
        self.assertEqual(self.h.c.screen.mode, "home")

    def test_f24_opens_the_picker_on_home_only(self):
        self.h.runtime.hotkey()
        self.assertEqual(self.h.c.screen.mode, "windows")
        self.h.c.button(0, self.h.c.control_id)
        self.h.runtime.dispatch()
        self.h.c.button(2, self.h.c.control_id)      # Tracks
        self.h.runtime.dispatch()
        self.h.runtime.hotkey()
        self.assertEqual(self.h.c.screen.mode, "tracks")

    def test_logical_3_without_hid_acts_outside_home(self):
        self.h.c.button(2, self.h.c.control_id)      # Tracks
        self.h.runtime.dispatch()
        self.h.c.position(2, self.h.c.control_id)
        self.kd(3)
        self.assertTrue(any(e["kind"] == "transport" for e in self.h.c.pending.values()))

    def test_presentation_4_drops_logical_3_on_home_with_the_hotkey(self):
        self.h.runtime.presentation_level = 4
        self.kd(3)
        self.assertEqual(self.h.c.screen.mode, "home")
        self.assertFalse(any(e["kind"] == "windows_open" for e in self.h.c.pending.values()))

    def test_without_a_hotkey_serial_logical_3_opens_the_picker(self):
        self.h.windows.supports_hotkey = False
        self.kd(3)
        self.assertEqual(self.h.c.screen.mode, "windows")

    def test_hold_event_goes_home(self):
        self.h.c.button(2, self.h.c.control_id)
        self.h.runtime.dispatch()
        self.h.device.events.put({"kind": "hold", "id": self.h.c.control_id, "button": 0, "raw": 0})
        self.h.runtime.poll()
        self.assertEqual(self.h.c.screen.mode, "home")

    def test_windows_button_is_button_order_3_and_hid_only_on_home(self):
        self.h.runtime.button_order = [3, 2, 1, 0]
        self.h.c.button_order = [3, 2, 1, 0]
        control = self.h.c.control()
        self.assertEqual((control["windowsButton"], control["windowsHidEnabled"]), (0, True))
        self.h.c.button(2, self.h.c.control_id)
        self.assertFalse(self.h.c.control()["windowsHidEnabled"])


if __name__ == "__main__":
    unittest.main()

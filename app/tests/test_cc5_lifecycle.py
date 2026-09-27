"""K3 section 13: every close reason, parent modes, the 60 s idle from knob input, refusals and
disconnect / reconnect (C5-2, C5-55)."""
import unittest

from cc5_support import Fixture, Harness, queue_state


class CloseReasonTests(Fixture):
    def enter(self, surface):
        while self.c.screen.mode != "home":
            self.hold()
        if surface == "explorer":
            self.browse()
            self.turn_to(3)
            self.press(1)
        elif surface == "upnext":
            self.tracks(2)
            self.press(1)
        else:
            self.open_windows()
        self.c.drain()

    def test_lock_sleep_idle_foreground_go_to_the_parent(self):
        parents = {"explorer": ("recent", 3), "upnext": ("tracks", 2)}
        for surface, (mode, index) in parents.items():
            for reason in ("lock", "sleep", "idle", "foreground"):
                with self.subTest(surface=surface, reason=reason):
                    self.enter(surface)
                    self.c.close_overlay(reason)
                    close = self.one(surface + "_close")
                    self.assertEqual(close["reason"], reason)
                    self.assertEqual((self.c.screen.mode, self.c.screen.index), (mode, index))
                    self.c.screen.mode = "home"

    def test_system_events_route_lock_and_sleep(self):
        self.enter("explorer")
        self.c.presenter_event({"kind": "system", "what": "lock"})
        self.assertEqual(self.one("explorer_close")["reason"], "lock")
        self.enter("upnext")
        self.c.presenter_event({"kind": "system", "what": "sleep"})
        self.assertEqual(self.one("upnext_close")["reason"], "sleep")

    def test_display_does_nothing_until_the_presenter_closes(self):
        self.enter("explorer")
        self.c.presenter_event({"kind": "system", "what": "display"})
        self.assertEqual(self.c.screen.mode, "explorer")
        self.c.presenter_event({"kind": "closed", "surface": "explorer", "reason": "display"})
        self.assertEqual(self.c.screen.mode, "recent")
        self.assertFalse(self.effects("explorer_close"), "presenter-initiated: no close effect")

    def test_device_close(self):
        self.enter("upnext")
        self.c.presenter_event({"kind": "closed", "surface": "upnext", "reason": "device"})
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 2))
        self.assertFalse(self.effects("upnext_close"))

    def test_a_closed_event_for_a_close_we_asked_for_is_registry_only(self):
        self.enter("explorer")
        self.press(0)
        control = self.c.control_id
        self.c.presenter_event({"kind": "closed", "surface": "explorer", "reason": "back"})
        self.assertEqual((self.c.screen.mode, self.c.control_id), ("recent", control))

    def test_events_for_a_surface_no_longer_current_are_dropped(self):
        self.enter("explorer")
        self.press(0)
        self.c.presenter_event({"kind": "refused", "surface": "explorer", "reason": "device"})
        self.assertEqual(self.c.screen.mode, "recent")
        self.assertIsNone(self.c.feedback)


class IdleTests(Fixture):
    def test_60_s_without_knob_input_including_lim(self):
        self.browse()
        self.press(1)
        self.tick(30)
        self.c.limit(1, self.c.control_id)  # a `lim` is knob input
        self.tick(59)
        self.assertEqual(self.c.screen.mode, "explorer")
        self.tick(1.1)
        self.assertEqual(self.c.screen.mode, "recent")

    def test_no_idle_close_outside_overlays(self):
        self.browse()
        self.tick(120)
        self.assertEqual(self.c.screen.mode, "recent")

    def test_the_idle_counts_from_the_overlay_entry_not_from_the_last_detent_before_it(self):
        # WP5-R1: a quiet knob, then F24 (the Win press is knob input; its `kd` never reaches
        # button()). The picker closes `idle` 60 s after it opened, never on the next tick.
        self.tick(120)
        self.c.open_windows()
        effect = self.one("windows_open")
        self.c.complete(effect["request"], {"items": [{"id": "0", "hwnd": 1, "title": "W", "app": "A",
                                                      "available": True}], "index": 0, "origin": {"hwnd": 1}})
        self.assertEqual(self.c.screen.mode, "windows")
        self.tick(0.025)
        self.assertEqual(self.c.screen.mode, "windows")
        self.tick(59.9)
        self.assertEqual(self.c.screen.mode, "windows")
        self.tick(0.2)
        self.assertEqual(self.c.screen.mode, "home")
        cancel = self.one("windows_cancel")
        self.assertEqual(self.c._cancel_pending["reason"], "idle")
        self.assertTrue(cancel["home"])

    def test_every_overlay_entry_re_arms_the_idle(self):
        for surface in ("explorer", "upnext"):
            with self.subTest(surface=surface):
                while self.c.screen.mode != "home":
                    self.hold()
                if surface == "explorer":
                    self.browse()
                else:
                    self.tracks()
                self.c.last_knob_input = self.clock() - 500.0   # as if the last input were long ago
                self.c._new_screen(surface, 0, surface + " open",
                                   **({"parent_index": 1} if surface == "upnext" else {}))
                self.assertEqual(self.c.last_knob_input, self.clock())
                self.tick(0.025)
                self.assertEqual(self.c.screen.mode, surface)


class HotkeyIdleRuntimeTests(unittest.TestCase):
    """WP5-R1 end to end: the real runtime's F24 path (runtime.hotkey()) after 120 s of quiet."""

    def boot(self, presentation):
        h = Harness(self)
        h.windows.supports_hotkey = True
        h.device.events.put({"kind": "connected", "capabilities": {"controlCenter": True,
                                                                   "presentation": presentation}})
        h.run(1)
        h.device.events.put({"kind": "ready", "id": h.c.control_id})
        h.run(1)
        return h

    def test_the_picker_stays_open_until_60_s_after_the_hotkey(self):
        for presentation in (5, 4):
            with self.subTest(presentation=presentation):
                h = self.boot(presentation)
                for _ in range(120):
                    h.clock.advance(1.0)
                    h.run(1)
                h.runtime.hotkey()
                opened = h.clock()
                if presentation >= 5:
                    # the knob's own kd for slot 3 carries hid:1 and is dropped by the runtime
                    h.device.events.put({"kind": "button", "button": h.runtime.button_order[3],
                                         "hid": True, "id": h.c.control_id})
                self.assertEqual(h.c.screen.mode, "windows")
                self.assertTrue(h.windows.visible)
                h.clock.advance(0.025)
                h.runtime.poll()
                self.assertEqual(h.c.screen.mode, "windows")
                self.assertEqual(h.windows.cancels, [])
                while h.clock() < opened + 59.5:
                    h.clock.advance(0.5)
                    h.runtime.poll()
                self.assertEqual(h.c.screen.mode, "windows")
                h.clock.advance(0.6)
                h.runtime.poll()
                self.assertEqual(h.c.screen.mode, "home")
                self.assertEqual(len(h.windows.cancels), 1)


class DisconnectTests(Fixture):
    def test_disconnect_closes_overlays_and_lands_home_on_reconnect(self):
        self.browse()
        self.press(1)
        self.c.drain()
        self.c.disconnected()
        self.assertEqual(self.one("explorer_close")["reason"], "disconnect")
        self.assertEqual(self.c.screen.mode, "home")
        self.c.set_hardware(True)
        entry = self.one("device_enter")
        self.assertEqual(entry["control"]["profile"], "BINARIS BEER")

    def test_picker_disconnect_hides_without_u12(self):
        self.open_windows()
        self.press(1)
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.c.drain()
        self.c.disconnected()
        effects = self.effects()
        self.assertEqual([e["kind"] for e in effects if e["kind"].startswith("windows_")], ["windows_hide"])

    def test_a_pending_start_finishes_honestly(self):
        self.browse()
        self.press(3)
        start = self.pending("play_items")
        self.c.disconnected()
        self.c.set_hardware(True)
        self.c.complete(start["request"], {**queue_state(), "_start": {"k": 9, "n": 9, "u": 0}})
        self.assertEqual(self.c.feedback["moment"], "started")

    def test_the_transient_is_cleared(self):
        self.publish(queue_state(online=False))
        self.press(0)
        self.c.disconnected()
        self.assertIsNone(self.c.transient)

    def test_reconnect_asks_for_fresh_state(self):
        self.c.set_hardware(True)
        self.c.drain()
        self.tick()
        self.assertEqual(len(self.effects("state")), 1)


if __name__ == "__main__":
    unittest.main()

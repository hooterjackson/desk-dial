"""K3 section 11: every presenter effect carries K4 section 2.3's fields plus `t0` from the injected
clock; one entry point for every event (VOC-R22); `system(motion)` (C5-53, C5-54)."""
import time
import unittest

from cc5_support import Fixture, Harness, queue_state
from control_center.controller import presenter_event_dict
from control_center.simulation import COMMON_FIELDS, REQUIRED_FIELDS, UPNEXT_REASONS, FakeStagePresenter
from control_center.stage.presenter import Mailbox, StagePresenter


class PayloadTests(Fixture):
    def collect(self):
        """Walk every presenter effect and return them (every drain is recorded)."""
        seen = []
        drain = self.c.drain

        def recording():
            effects = drain()
            seen.extend(effects)
            return effects
        self.c.drain = recording
        self.browse()
        self.press(1)
        self.press(2)
        self.tick(0.2)
        self.press(1)
        self.tick(0.2)
        self.c.limit(1, self.c.control_id)
        self.turn_to(2)
        self.press(3)
        self.tick(0.4)
        self.c.drain()
        self.upnext()
        self.ratings()
        self.press(1)
        self.c.limit(-1, self.c.control_id)
        self.hold()
        self.c.drain()
        self.open_windows()
        self.press(1)
        self.c.snap_result("left", "accepted")
        self.c.snap_result("left", "ok")
        self.press(0)
        self.c.drain()
        return seen

    def test_required_fields(self):
        for effect in self.collect():
            required = REQUIRED_FIELDS.get(effect["kind"])
            if required is None:
                continue
            with self.subTest(kind=effect["kind"]):
                missing = [name for name in COMMON_FIELDS + required if name not in effect]
                self.assertEqual(missing, [])

    def test_t0_is_the_injected_clock(self):
        self.browse()
        self.tick(1.25)
        self.press(1)
        opened = [e for e in self.c.drain() if e["kind"] == "explorer_open"][0]
        self.assertEqual(opened["t0"], self.clock())

    def test_control_min_is_0_in_list_modes(self):
        opens = [e for e in self.collect() if e["kind"] in ("explorer_open", "upnext_open")]
        self.assertTrue(opens)
        self.assertTrue(all(e["control_min"] == 0 for e in opens))

    def test_upnext_rows_reasons_are_the_enum(self):
        reasons = {e["reason"] for e in self.collect() if e["kind"] == "upnext_rows"}
        self.assertTrue(reasons)
        self.assertLessEqual(reasons, set(UPNEXT_REASONS))


class EventEntryPointTests(Fixture):
    def test_motion_updates_reduced_motion_in_the_next_frame(self):
        self.assertIs(self.frame()["reducedMotion"], False)
        self.c.presenter_event({"kind": "system", "what": "motion", "on": True})
        self.assertIs(self.frame()["reducedMotion"], True)
        self.browse()
        self.press(1)
        opened = [e for e in self.c.drain() if e["kind"] == "explorer_open"][0]
        self.assertIs(opened["reduced_motion"], True)

    def test_every_event_kind_is_accepted(self):
        self.open_windows()
        for event in ({"kind": "opened", "surface": "picker"}, {"kind": "closed", "surface": "picker", "reason": "back"},
                      {"kind": "system", "what": "display"}, {"kind": "cancel_result", "restored": True, "completed": False},
                      {"kind": "snap_result", "side": "left", "outcome": "ok"}, ("opened", {"surface": "picker"})):
            self.c.presenter_event(event)
        self.assertEqual(self.c.screen.mode, "windows")

    def test_no_display_off_kind(self):
        self.browse()
        self.press(1)
        self.c.presenter_event({"kind": "system", "what": "display_off"})
        self.assertEqual(self.c.screen.mode, "explorer")


class RuntimePresenterTests(unittest.TestCase):
    def test_the_runtime_pushes_payloads_to_the_stage_and_routes_events(self):
        h = Harness(self)
        h.run(1)
        h.press(1)
        h.run(2)
        h.press(1)                           # the explorer: the strict fake asserts every field
        h.run(1)
        self.assertEqual([e["kind"] for e in h.stage.of("explorer_open")], ["explorer_open"])
        self.assertEqual(h.runtime.open_surfaces, {"explorer"})
        h.stage.emit("click_action", surface="explorer")
        h.run(1)
        self.assertEqual(len(h.stage.of("explorer_close")), 1)

    def test_a_refusing_stage_returns_the_knob_to_the_parent(self):
        h = Harness(self)
        h.controls.stage = "refused"
        h.run(1)
        h.press(1)
        h.run(2)
        h.press(1)
        h.run(1)
        self.assertEqual(h.c.screen.mode, "recent")
        self.assertEqual(h.frame()["meta"], "Couldn’t open on screen")

    def test_a_display_close_from_the_stage(self):
        h = Harness(self)
        h.controls.stage = "display"
        h.run(1)
        h.press(2)
        h.press(1)
        h.run(1)
        self.assertEqual(h.c.screen.mode, "tracks")

    def test_a_raising_stage_counts_as_refused(self):
        h = Harness(self)
        h.run(1)

        class Broken:
            def post(self, effect):
                raise RuntimeError("no device")
        h.runtime.stage = Broken()
        h.press(1)
        h.run(2)
        h.press(1)
        h.run(1)
        self.assertEqual(h.c.screen.mode, "recent")

    def test_the_foreground_hwnd_is_filled_on_open(self):
        h = Harness(self)
        h.windows.foreground_hwnd = lambda: 4242
        h.run(1)
        h.press(1)
        h.run(2)
        h.press(1)
        h.run(1)
        self.assertEqual(h.stage.of("explorer_open")[0]["foreground_hwnd"], 4242)

    def test_without_a_stage_the_knob_runs_alone(self):
        h = Harness(self, stage=False)
        h.run(1)
        h.press(1)
        h.run(2)
        h.press(1)
        h.run(1)
        self.assertEqual(h.c.screen.mode, "explorer")


class EventShapeTests(unittest.TestCase):
    """WP5-R2: K4's `(kind, payload)` tuples, `system` naming its own kind in the payload."""

    def test_a_system_tuple_keeps_its_event_kind(self):
        self.assertEqual(presenter_event_dict(("system", {"kind": "lock", "t0": 1.5})),
                         {"kind": "system", "what": "lock", "t0": 1.5})
        self.assertEqual(presenter_event_dict(("closed", {"surface": "upnext", "reason": "display", "t0": 2.0})),
                         {"kind": "closed", "surface": "upnext", "reason": "display", "t0": 2.0})

    def test_a_payload_kind_never_replaces_the_event_kind(self):
        self.assertEqual(presenter_event_dict(("refused", {"kind": "x", "surface": "explorer", "reason": "busy"}))["kind"],
                         "refused")

    def test_dicts_pass_through_and_junk_is_dropped(self):
        event = {"kind": "system", "what": "sleep"}
        self.assertIs(presenter_event_dict(event), event)
        for junk in (None, 3, ("system",), (1, {})):
            self.assertIsNone(presenter_event_dict(junk))


class StageMailboxTests(unittest.TestCase):
    """WP5-R2 end to end: K4's real `StagePresenter` over a `Mailbox` as `runtime.stage`. Effects
    reach it through its K4 methods (it has no `post`), and the tuple events it posts come back
    through `runtime.poll()` to `controller.presenter_event`."""

    class Engine:
        def __init__(self):
            self.mailbox = Mailbox()

        def metrics(self):
            return {}

        def close(self, timeout=2.0):
            return True

    def boot(self):
        h = Harness(self, stage=False)
        self.engine = self.Engine()
        h.runtime.stage = StagePresenter(self.engine)
        h.run(1)
        return h

    def calls(self):
        items, _positions, _touch = self.engine.mailbox.take()
        return [call for call, _payload, _t in items]

    def push(self, event, **payload):
        self.engine.mailbox.push_event(event, {**payload, "t0": 1.0})

    def open_explorer(self, h):
        h.press(1)
        h.run(2)
        h.press(1)
        h.run(1)
        self.assertEqual(h.c.screen.mode, "explorer")
        self.assertIn("explorer_open", self.calls())

    def open_upnext(self, h):
        h.press(2)
        h.press(1)
        h.run(2)
        self.assertEqual(h.c.screen.mode, "upnext")
        self.assertIn("upnext_open", self.calls())

    def test_effects_go_through_the_k4_methods(self):
        h = self.boot()
        self.open_explorer(h)
        h.c.turn(1)
        h.runtime.dispatch()
        self.assertIn("explorer_highlight", self.calls())
        h.press(0)
        self.assertIn("explorer_close", self.calls())
        self.assertEqual(h.c.screen.mode, "recent")

    def test_opened_and_closed_tuples_update_the_registry(self):
        h = self.boot()
        self.open_explorer(h)
        self.push("opened", surface="explorer")
        h.runtime.poll()
        self.assertEqual(h.runtime.open_surfaces, {"explorer"})
        self.push("closed", surface="explorer", reason="display")
        h.runtime.poll()
        self.assertEqual(h.runtime.open_surfaces, set())
        self.assertEqual(h.c.screen.mode, "recent", "a display close from the stage returns to the parent")
        self.assertNotIn("explorer_close", self.calls(), "presenter-initiated: no close effect")

    def test_system_lock_and_sleep_close_the_overlay(self):
        for kind, opener, parent in (("lock", self.open_explorer, "recent"), ("sleep", self.open_upnext, "tracks")):
            with self.subTest(kind=kind):
                h = self.boot()
                opener(h)
                self.push("system", kind=kind)
                h.runtime.poll()
                self.assertEqual(h.c.screen.mode, parent)
                closes = [c for c in self.calls() if c.endswith("_close")]
                self.assertEqual(len(closes), 1)

    def test_system_display_does_nothing_by_itself(self):
        h = self.boot()
        self.open_explorer(h)
        self.push("system", kind="display")
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "explorer")

    def test_system_motion_re_evaluates_the_setting_at_once(self):
        h = self.boot()
        h.runtime.motion_probe = lambda: True
        h.runtime.motion_setting = "system"
        h.runtime._motion_checked = time.monotonic()   # the 5 s backstop is not due: only the event acts
        self.assertIs(h.c.reduced_motion, False)
        self.push("system", kind="motion")
        h.runtime.poll()
        self.assertIs(h.c.reduced_motion, True)
        self.assertIs(h.frame()["reducedMotion"], True)

    def test_refused_and_click_action_tuples(self):
        h = self.boot()
        self.open_explorer(h)
        self.push("refused", surface="explorer", reason="device")
        h.runtime.poll()
        self.assertEqual(h.c.screen.mode, "recent")
        self.assertEqual(h.frame()["meta"], "Couldn’t open on screen")
        h = self.boot()
        self.open_upnext(h)
        self.push("click_action", surface="upnext")
        h.runtime.poll()
        self.assertTrue(any(e["kind"] == "jump" for e in h.c.pending.values()), "click_action = Button 4 (Play)")
        self.assertIn("upnext_close", self.calls())

    def test_a_closed_mailbox_counts_as_refused(self):
        h = self.boot()
        self.engine.mailbox.closed = True
        h.press(1)
        h.run(2)
        h.press(1)
        h.run(1)
        self.assertEqual(h.c.screen.mode, "recent")


if __name__ == "__main__":
    unittest.main()

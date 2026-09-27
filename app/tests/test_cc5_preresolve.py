"""K3 sections 5.2.2 / 9.8.7: pre-resolution (C5-66): 400 ms of rest, focus then neighbours, the
lookahead lane at the lowest priority, one at a time, stale ones dropped."""
import unittest

from cc5_support import Fixture, Harness, recent_page


class ControllerTests(Fixture):
    def resolves(self):
        return [e for e in self.effects() if e["kind"] == "resolve"]

    def test_nothing_before_400_ms_of_rest(self):
        self.browse()
        self.turn_to(5)
        self.tick(0.39)
        self.assertFalse(self.resolves())
        self.tick(0.02)
        order = [e["item"]["id"] for e in self.resolves()]
        self.assertEqual(order, ["album-5", "album-6", "album-4"])

    def test_direction_of_travel(self):
        self.browse()
        self.turn_to(8)
        self.turn_to(7)
        self.tick(0.41)
        self.assertEqual([e["item"]["id"] for e in self.resolves()], ["album-7", "album-6", "album-8"])

    def test_unavailable_and_unloaded_items_are_skipped(self):
        self.browse(overrides={6: {"available": False}})
        self.turn_to(5)
        self.tick(0.41)
        self.assertEqual([e["item"]["id"] for e in self.resolves()], ["album-5", "album-4"])

    def test_a_spin_with_no_rest_resolves_nothing(self):
        self.browse(total=96, count=25)
        for position in range(1, 25):
            self.turn_to(position)
            self.tick(0.1)
        resolves = self.resolves()
        self.assertFalse(resolves)

    def test_a_new_focus_drops_the_stale_queued_ones_at_the_detent(self):
        # WP5-R8: at the detent, not at the next rest.
        self.browse()
        self.turn_to(5)
        self.tick(0.41)
        self.assertEqual(len(self.resolves()), 3)
        self.turn_to(6)
        drops = [e for e in self.c.drain() if e["kind"] == "resolve_drop"]
        self.assertEqual([d["keep"] for d in drops],
                         [[{"kind": "album", "id": "album-6"}, {"kind": "album", "id": "album-7"},
                           {"kind": "album", "id": "album-5"}]])
        self.turn_to(20)
        drops = [e for e in self.c.drain() if e["kind"] == "resolve_drop"]
        self.assertEqual(len(drops), 1)
        self.turn_to(21)
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "resolve_drop"],
                         "nothing asked for is left to drop")

    def test_no_drop_before_any_pre_resolution(self):
        self.browse()
        for position in range(1, 10):
            self.turn_to(position)
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "resolve_drop"])

    def test_the_explorer_recent_tab_triggers_it_too(self):
        self.browse()
        self.press(1)
        self.c.drain()
        self.turn_to(3)
        self.tick(0.41)
        self.assertEqual(self.resolves()[0]["item"]["id"], "album-3")


class LaneTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(self)
        self.h.run(1)
        self.h.press(1)
        self.h.run(2)

    def test_lowest_priority_one_at_a_time_and_stale_dropped(self):
        lane = self.h.runtime.lookahead_lane
        self.h.c.position(4, self.h.c.control_id)
        self.h.clock.advance(0.5)
        self.h.c.tick()
        self.h.runtime.dispatch()
        self.assertEqual(lane.queued_preresolve(), [("album", "a4"), ("album", "a5"), ("album", "a3")])
        self.h.c.position(10, self.h.c.control_id)      # a new focus before any ran
        self.h.clock.advance(0.5)
        self.h.c.tick()
        self.h.runtime.dispatch()
        self.assertEqual(lane.queued_preresolve(), [("album", "a10"), ("album", "a11")],
                         "a9 is unavailable in the simulator library; a4..a5 dropped")
        ran = self.h.runtime.lookahead.run_all()
        self.assertGreaterEqual(ran, 2)
        self.assertEqual(self.h.apple.resolve_calls, 2)
        self.assertIsNotNone(self.h.apple.resolve_cached(self.h.c.recent.items[10]))

    def test_a_spin_empties_the_stale_queue_before_the_next_rest(self):
        # WP5-R8: rest on 4, then spin 5..20 with no rest: the queued a4 / a5 / a3 go as the
        # focus leaves them, so draining the lane during the spin resolves nothing.
        lane = self.h.runtime.lookahead_lane
        cid = self.h.c.control_id
        self.h.c.position(4, cid)
        self.h.clock.advance(0.5)
        self.h.c.tick()
        self.h.runtime.dispatch()
        self.assertEqual(lane.queued_preresolve(), [("album", "a4"), ("album", "a5"), ("album", "a3")])
        for position in range(5, 21):
            self.h.clock.advance(0.05)
            self.h.c.position(position, cid)
            self.h.c.tick()
            self.h.runtime.dispatch()
            wanted = {("album", f"a{n}") for n in (position - 1, position, position + 1)}
            self.assertLessEqual(set(lane.queued_preresolve()), wanted)
        self.assertEqual(lane.queued_preresolve(), [])
        self.h.runtime.lookahead.run_all()
        self.assertEqual(self.h.apple.resolve_calls, 0, "a fast spin costs nothing")
        self.h.clock.advance(0.5)
        self.h.c.tick()
        self.h.runtime.dispatch()
        self.assertEqual(lane.queued_preresolve(), [("album", "a20"), ("album", "a21"), ("album", "a19")])

    def test_the_running_one_is_never_dropped(self):
        lane = self.h.runtime.lookahead_lane
        lane.running_preresolve = ("album", "a4")
        lane.keep_preresolve(set())
        self.assertEqual(lane.running_preresolve, ("album", "a4"))

    def test_a_queued_page_runs_before_pre_resolutions(self):
        lane = self.h.runtime.lookahead_lane
        order = []
        original = self.h.apple.recent_page
        self.h.apple.recent_page = lambda *a, **k: (order.append("page"), original(*a, **k))[1]
        original_pre = self.h.apple.preresolve
        self.h.apple.preresolve = lambda *a, **k: (order.append("pre"), original_pre(*a, **k))[1]
        self.h.c.position(9, self.h.c.control_id)
        self.h.clock.advance(0.5)
        self.h.c.tick()
        self.h.runtime.dispatch()
        self.h.runtime.lookahead.run_all()
        self.assertEqual(order[0], "page")


if __name__ == "__main__":
    unittest.main()

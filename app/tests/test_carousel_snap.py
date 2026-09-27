"""NanoD-snap: the real-window placement recipe (DESKTOP_STAGE.md 9.5-9.7; VOC 8.4 snap and
complete_one_side; VOC-D01; S5-13, S5-14, S5-32; CAROUSEL.md 12 item 4) against a fake native layer
on a fake clock. The fake applies posted calls a little later (as a target's thread would), can
stall like a busy app, and records every call made on a target window, so the tests assert:
- the recipe reaches a target only through ShowWindowAsync (SW_SHOWNOACTIVATE / SW_SHOWMINNOACTIVE)
  and SetWindowPos with SWP_ASYNCWINDOWPOS (never SetWindowPlacement, ShowWindow, a synchronous
  SetWindowPos, SW_RESTORE or SW_MAXIMIZE);
- DWMWA_EXTENDED_FRAME_BOUNDS compensation, the work-area halves, the verify windows;
- the hard deadlines (t0 + 800 ms; 600 ms for complete_one_side), with the put-back (step 7) that
  never re-maximizes; a stalled target resolves as move_rejected by the deadline;
- the carousel's backstop wins over a late worker, which then puts the window back.
Plus a static scan of the module (P9 timers, forbidden calls) and the Win32SnapNative guards."""
from pathlib import Path
import re
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import carousel as c  # noqa: E402
from control_center import carousel_render as R  # noqa: E402

MONITOR = (0, 0, 1920, 1080)
WORK = (0, 40, 1920, 1080)                      # a taskbar at the top: workspace != screen coordinates
LEFT, RIGHT = R.work_half(WORK, "left"), R.work_half(WORK, "right")
ALLOWED = {"is_window", "identity", "is_hung", "integrity_above_ours", "placement", "window_rect", "frame_bounds",
           "is_iconic", "is_zoomed", "monitor_of", "show_async", "set_pos_async"}
WPF_RESTORETOMAXIMIZED = 0x2


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class Win:
    def __init__(self, hwnd, rect=(300, 200, 1300, 900), inset=(7, 0, 7, 7), minimized=False, maximized=False,
                 normal=None, class_name="Chrome_WidgetWin_1", min_size=(0, 0), restore_to_max=False, hung=False,
                 above=False, toolwindow=False):
        self.hwnd = hwnd
        self.rect = tuple(rect)
        self.inset = tuple(inset)
        self.minimized, self.maximized = minimized, maximized
        # GetWindowPlacement.rcNormalPosition, in workspace coordinates (not for tool windows)
        self.normal = tuple(normal or rect)
        self.class_name = class_name
        self.min_size = min_size
        self.restore_to_max = restore_to_max
        self.hung, self.above = hung, above
        self.toolwindow = toolwindow
        self.stall = False                        # a busy target: posted calls are never handled
        self.dpi_after_move = None                # a new inset once the first move lands
        self.alive = True

    def frame(self):
        l, t, r, b = self.rect
        a, b_, c_, d = self.inset
        return (l + a, t + b_, r - c_, b - d)


class FakeNative:
    """The snap worker's native layer, on the test clock. Posted calls land ``lag`` seconds later
    (``tick``), unless the window stalls."""

    def __init__(self, clock, lag=0.03):
        self.clock = clock
        self.lag = lag
        self.windows = {}
        self.calls = []
        self.pending = []
        self.foreground_hwnd = 0x5001

    def add(self, win):
        self.windows[win.hwnd] = win
        return win

    def log(self, name, hwnd, *args):
        self.calls.append((name, hwnd) + args)

    def on(self, hwnd):
        return [call for call in self.calls if call[1] == hwnd]

    def tick(self):
        due = [p for p in self.pending if p[0] <= self.clock.t + 1e-12]
        self.pending = [p for p in self.pending if p[0] > self.clock.t + 1e-12]
        for _, win, action in due:
            if not win.stall:
                action()

    def _post(self, win, action):
        self.pending.append((self.clock.t + self.lag, win, action))

    # reads (never wait on the target)
    def is_window(self, hwnd):
        self.log("is_window", hwnd)
        win = self.windows.get(hwnd)
        return bool(win and win.alive)

    def identity(self, hwnd):
        self.log("identity", hwnd)
        return {"hwnd": hwnd, "pid": 20, "id": f"id{hwnd}"} if hwnd in self.windows else None

    def is_hung(self, hwnd):
        self.log("is_hung", hwnd)
        return self.windows[hwnd].hung

    def integrity_above_ours(self, hwnd):
        self.log("integrity_above_ours", hwnd)
        return self.windows[hwnd].above

    def placement(self, hwnd):
        self.log("placement", hwnd)
        win = self.windows[hwnd]
        flags = WPF_RESTORETOMAXIMIZED if win.restore_to_max else 0
        return flags, 2 if win.minimized else 3 if win.maximized else 1, win.normal

    def window_rect(self, hwnd):
        self.log("window_rect", hwnd)
        win = self.windows[hwnd]
        return (-32000, -32000, -31840, -31972) if win.minimized else win.rect

    def frame_bounds(self, hwnd):
        self.log("frame_bounds", hwnd)
        win = self.windows[hwnd]
        return None if win.minimized else win.frame()

    def is_iconic(self, hwnd):
        self.log("is_iconic", hwnd)
        return self.windows[hwnd].minimized

    def is_zoomed(self, hwnd):
        self.log("is_zoomed", hwnd)
        return self.windows[hwnd].maximized

    def monitor_of(self, hwnd):
        self.log("monitor_of", hwnd)
        return MONITOR, WORK

    def foreground(self):
        return self.foreground_hwnd

    # posted calls (the only ones that reach a target)
    def show_async(self, hwnd, command):
        self.log("show_async", hwnd, command)
        assert command in (c.SW_SHOWNOACTIVATE, c.SW_SHOWMINNOACTIVE), command
        win = self.windows[hwnd]

        def apply():
            if command == c.SW_SHOWMINNOACTIVE:
                win.minimized = True
                return
            if win.minimized and win.restore_to_max:
                win.minimized, win.maximized = False, True
                win.restore_to_max = False
                return
            if win.minimized or win.maximized:
                win.minimized = win.maximized = False
                l, t, r, b = win.normal
                dy = WORK[1] - MONITOR[1]
                win.rect = (l, t + dy, r, b + dy)
        self._post(win, apply)
        return True

    def set_pos_async(self, hwnd, insert_after, x, y, w, h, flags):
        self.log("set_pos_async", hwnd, insert_after, x, y, w, h, flags)
        assert flags & c.SWP_ASYNCWINDOWPOS and flags & 0x0010, hex(flags)
        win = self.windows[hwnd]

        def apply():
            if flags & 0x0003 == 0x0003:
                return                                   # a raise (NOSIZE | NOMOVE)
            width, height = max(w, win.min_size[0]), max(h, win.min_size[1])
            win.rect = (x, y, x + width, y + height)
            if win.dpi_after_move is not None:
                win.inset, win.dpi_after_move = win.dpi_after_move, None
                l, t, r, b = win.rect
                win.rect = (l, t, r + 6, b + 6)          # the app's WM_DPICHANGED resize
        self._post(win, apply)
        return True


class RecipeCase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.native = FakeNative(self.clock)
        self.results = []

        def wait(seconds):
            self.clock.t += seconds
            self.native.tick()
        self.worker = c.SnapWorker(self.native, clock=self.clock, wait=wait, threaded=False)
        self.addCleanup(self.worker.close)

    def job(self, win, side="left", t0=None, kind="snap", item=None):
        t0 = self.clock.t if t0 is None else t0
        item = item or {"hwnd": win.hwnd, "pid": 20, "id": f"id{win.hwnd}", "class_name": win.class_name,
                        "exstyle": 0x80 if win.toolwindow else 0}
        target = LEFT if side == "left" else RIGHT
        if kind == "complete":
            return c.SnapJob("complete", side=side, item=item, target=target, t0=t0, deadline=t0 + c.ONE_SIDE_DEADLINE_S)
        return c.SnapJob("snap", side=side, item=item, target=target, t0=t0, place_at=t0 + c.SNAP_PLACE_S,
                         deadline=t0 + c.SNAP_DEADLINE_S)

    def execute(self, job):
        self.worker.run_job(job)
        results = self.worker.take_results()
        return [(stage, outcome) for _job, stage, outcome, _info in results], self.clock.t

    def assertOnlyPostedCalls(self, hwnd):
        names = {call[0] for call in self.native.on(hwnd)}
        self.assertLessEqual(names, ALLOWED, names - ALLOWED)
        for call in self.native.on(hwnd):
            if call[0] == "set_pos_async":
                self.assertTrue(call[-1] & c.SWP_ASYNCWINDOWPOS and call[-1] & 0x10)
            if call[0] == "show_async":
                self.assertIn(call[2], (c.SW_SHOWNOACTIVATE, c.SW_SHOWMINNOACTIVE))

    def moves(self, hwnd):
        return [call for call in self.native.on(hwnd) if call[0] == "set_pos_async"]

    def shows(self, hwnd):
        return [call[2] for call in self.native.on(hwnd) if call[0] == "show_async"]


class PlacementTests(RecipeCase):
    def test_a_normal_window_moves_once_at_360_ms_with_frame_compensation(self):
        win = self.native.add(Win(0x10))
        t0 = self.clock.t
        outcomes, done = self.execute(self.job(win))
        self.assertEqual(outcomes, [("precheck", "accepted"), ("final", "ok")])
        self.assertEqual(win.frame(), LEFT, "the visible frame fills the half exactly")
        moves = self.moves(0x10)
        self.assertEqual(len(moves), 1, "moved once")
        _, _, after, x, y, w, h, flags = moves[0]
        self.assertEqual(flags, 0x4214)
        self.assertIsNone(after)
        self.assertEqual((x, y, x + w, y + h), (LEFT[0] - 7, LEFT[1], LEFT[2] + 7, LEFT[3] + 7))
        self.assertEqual(self.shows(0x10), [])
        first_move = self.native.calls.index(moves[0])
        self.assertTrue(all(call[0] != "set_pos_async" for call in self.native.calls[:first_move]))
        self.assertGreaterEqual(done - t0, c.SNAP_PLACE_S)
        self.assertLessEqual(done - t0, c.SNAP_PLACE_S + c.VERIFY_S)
        self.assertOnlyPostedCalls(0x10)

    def test_a_maximized_window_is_restored_without_activation_then_placed(self):
        win = self.native.add(Win(0x11, rect=(-8, 32, 1928, 1088), maximized=True, normal=(200, 100, 1200, 800)))
        outcomes, _ = self.execute(self.job(win, "right"))
        self.assertEqual(outcomes[-1], ("final", "ok"))
        self.assertEqual(self.shows(0x11), [c.SW_SHOWNOACTIVATE])     # never SW_RESTORE (9) or SW_MAXIMIZE (3)
        self.assertFalse(win.maximized)
        self.assertEqual(win.frame(), RIGHT)
        self.assertOnlyPostedCalls(0x11)

    def test_a_minimized_window_that_restores_to_maximized_is_asked_once_more(self):
        win = self.native.add(Win(0x12, minimized=True, restore_to_max=True, normal=(200, 100, 1200, 800)))
        outcomes, _ = self.execute(self.job(win))
        self.assertEqual(outcomes[-1], ("final", "ok"))
        self.assertEqual(self.shows(0x12), [c.SW_SHOWNOACTIVATE, c.SW_SHOWNOACTIVATE])
        self.assertEqual(win.frame(), LEFT)
        self.assertOnlyPostedCalls(0x12)

    def test_a_window_that_stays_iconic_is_rejected_and_minimized_again_at_its_normal_rect(self):
        win = self.native.add(Win(0x13, minimized=True, normal=(200, 100, 1200, 800)))
        win.stall = True
        t0 = self.clock.t
        outcomes, done = self.execute(self.job(win))
        self.assertEqual(outcomes, [("precheck", "accepted"), ("final", "move_rejected")])
        self.assertLessEqual(done - t0, c.SNAP_PLACE_S + c.RESTORE_LIMIT_S + 1e-6)
        back = self.moves(0x13)[-1]
        # the normal rect converted from workspace to screen (+ rcWork.top - rcMonitor.top), then minimized
        self.assertEqual(back[3:7], (200, 140, 1000, 700))
        self.assertEqual(self.shows(0x13), [c.SW_SHOWNOACTIVATE, c.SW_SHOWMINNOACTIVE])
        self.assertOnlyPostedCalls(0x13)

    def test_a_tool_windows_placement_is_already_in_screen_coordinates(self):
        win = self.native.add(Win(0x14, minimized=True, normal=(200, 100, 1200, 800), toolwindow=True))
        win.stall = True
        self.execute(self.job(win))
        self.assertEqual(self.moves(0x14)[-1][3:7], (200, 100, 1000, 700))

    def test_a_maximized_window_that_fails_is_left_restored_never_re_maximized(self):
        win = self.native.add(Win(0x15, rect=(-8, 32, 1928, 1088), maximized=True, normal=(200, 100, 1200, 800),
                                  min_size=(1500, 0)))
        outcomes, _ = self.execute(self.job(win))
        self.assertEqual(outcomes[-1], ("final", "cant_fit"))
        self.assertFalse(win.maximized, "S5-32: left restored at its normal rect")
        self.assertEqual(self.shows(0x15), [c.SW_SHOWNOACTIVATE])
        self.assertEqual(self.moves(0x15)[-1][3:7], (200, 140, 1000, 700))
        self.assertOnlyPostedCalls(0x15)

    def test_cant_fit_puts_a_normal_window_back_exactly(self):
        win = self.native.add(Win(0x16, rect=(300, 200, 1600, 900), min_size=(1200, 0)))
        before = win.rect
        outcomes, _ = self.execute(self.job(win))
        self.assertEqual(outcomes[-1], ("final", "cant_fit"))
        self.native.tick()
        self.clock.t += 0.1
        self.native.tick()
        self.assertEqual(win.rect, before, "S5-13: nothing moves")

    def test_a_busy_target_resolves_move_rejected_inside_the_deadline_and_nothing_blocks(self):
        win = self.native.add(Win(0x17))
        win.stall = True
        t0 = self.clock.t
        real = time.perf_counter()
        outcomes, done = self.execute(self.job(win))
        self.assertLess(time.perf_counter() - real, 0.5, "no real wait: every call returned at once")
        self.assertEqual(outcomes, [("precheck", "accepted"), ("final", "move_rejected")])
        self.assertLessEqual(done - t0, c.SNAP_DEADLINE_S + 1e-9)
        self.assertEqual(len(self.moves(0x17)), 2, "the placement and the put-back, both posted")
        self.assertOnlyPostedCalls(0x17)

    def test_a_uwp_frame_verifies_for_400_ms_cut_by_the_deadline(self):
        win = self.native.add(Win(0x18, class_name=c.UWP_FRAME_CLASS))
        win.stall = True
        t0 = self.clock.t
        outcomes, done = self.execute(self.job(win))
        self.assertEqual(outcomes[-1], ("final", "move_rejected"))
        self.assertGreater(done - t0, c.SNAP_PLACE_S + c.VERIFY_S)
        self.assertLessEqual(done - t0, c.SNAP_PLACE_S + c.VERIFY_UWP_S + 1e-9)
        win = self.native.add(Win(0x19, class_name=c.UWP_FRAME_CLASS, minimized=True, normal=(200, 100, 1200, 800)))
        self.native.lag = 0.14                                     # a slow restore: 140 ms
        t0 = self.clock.t
        outcomes, done = self.execute(self.job(win))
        self.assertLessEqual(done - t0, c.SNAP_DEADLINE_S + 1e-9, "never past the deadline")

    def test_a_late_t0_never_starts_a_wait_past_the_deadline(self):
        win = self.native.add(Win(0x1A))
        win.stall = True
        t0 = self.clock.t - 0.7                                    # the press was 700 ms ago
        outcomes, done = self.execute(self.job(win, t0=t0))
        self.assertEqual(outcomes[-1], ("final", "move_rejected"))
        self.assertLessEqual(done, t0 + c.SNAP_DEADLINE_S + 1e-9)

    def test_a_dpi_change_on_the_way_reapplies_the_placement_once(self):
        win = self.native.add(Win(0x1B))
        win.dpi_after_move = (10, 0, 10, 10)
        outcomes, _ = self.execute(self.job(win))
        self.assertEqual(outcomes[-1], ("final", "ok"))
        self.assertEqual(len(self.moves(0x1B)), 2)
        self.assertEqual(win.frame(), LEFT)


class PrecheckTests(RecipeCase):
    def test_hung_integrity_and_identity_failures_post_nothing(self):
        cases = (("hung", Win(0x20, hung=True), None), ("move_rejected", Win(0x21, above=True), None),
                 ("move_rejected", Win(0x22), {"hwnd": 0x22, "pid": 20, "id": "a-recycled-handle"}))
        for outcome, win, item in cases:
            with self.subTest(win=hex(win.hwnd)):
                self.native.add(win)
                outcomes, done = self.execute(self.job(win, item=item))
                self.assertEqual(outcomes, [("precheck", outcome)])
                self.assertEqual(self.moves(win.hwnd), [])
                self.assertEqual(self.shows(win.hwnd), [])
        gone = Win(0x23)
        gone.alive = False
        self.native.add(gone)
        self.assertEqual(self.execute(self.job(gone))[0], [("precheck", "move_rejected")])

    def test_an_integrity_query_that_fails_carries_on(self):
        win = self.native.add(Win(0x24))
        self.native.integrity_above_ours = lambda hwnd: (_ for _ in ()).throw(OSError("denied"))
        self.assertEqual(self.execute(self.job(win))[0][-1], ("final", "ok"))


class BackstopAndJobsTests(RecipeCase):
    def test_the_backstop_answered_first_so_a_late_ok_puts_the_window_back(self):
        win = self.native.add(Win(0x30))
        before = win.rect
        job = self.job(win)
        original = self.native.frame_bounds

        def late(hwnd):
            if job.accepted and not job.resolved and self.moves(0x30):
                job.resolve("move_rejected", "carousel")          # the carousel's backstop fired meanwhile
            return original(hwnd)
        self.native.frame_bounds = late
        outcomes, _ = self.execute(job)
        self.assertEqual(outcomes, [("precheck", "accepted")], "the worker's late result is dropped")
        self.assertEqual(job.resolved_by, "carousel")
        self.clock.t += 0.1
        self.native.tick()
        self.assertEqual(win.rect, before, "step 7 ran after all")

    def test_complete_one_side_moves_the_origin_within_600_ms(self):
        win = self.native.add(Win(0x31))
        t0 = self.clock.t
        outcomes, done = self.execute(self.job(win, "right", kind="complete"))
        self.assertEqual(outcomes, [("complete", "ok")])
        self.assertEqual(win.frame(), RIGHT)
        self.assertLessEqual(done - t0, c.ONE_SIDE_DEADLINE_S)
        busy = self.native.add(Win(0x32))
        busy.stall = True
        t0 = self.clock.t
        outcomes, done = self.execute(self.job(busy, "right", kind="complete"))
        self.assertEqual(outcomes, [("complete", "move_rejected")])
        self.assertLessEqual(done - t0, c.ONE_SIDE_DEADLINE_S + 1e-9)
        self.assertOnlyPostedCalls(0x32)

    def test_the_pair_raise_is_one_posted_setwindowpos(self):
        win = self.native.add(Win(0x33))
        self.worker.run_job(c.SnapJob("raise", hwnd=0x33))
        self.assertEqual(self.native.on(0x33), [("set_pos_async", 0x33, c.HWND_TOP_, 0, 0, 0, 0, 0x4013)])

    def test_the_threaded_worker_posts_its_wake(self):
        clock = Clock()
        native = FakeNative(clock)
        win = native.add(Win(0x34))
        woke = threading.Event()

        def wait(seconds):
            clock.t += seconds
            native.tick()
        worker = c.SnapWorker(native, clock=clock, wait=wait, post=lambda code: woke.set())
        try:
            job = c.SnapJob("snap", side="left", item={"hwnd": 0x34, "pid": 20, "id": "id52"}, target=LEFT, t0=clock.t,
                            place_at=clock.t + 0.36, deadline=clock.t + 0.8)
            worker.submit(job)
            self.assertTrue(woke.wait(2.0))
            deadline = time.monotonic() + 2.0
            outcomes = []
            while time.monotonic() < deadline and ("final", "ok") not in outcomes:
                outcomes += [(stage, outcome) for _j, stage, outcome, _i in worker.take_results()]
                time.sleep(0.01)
            self.assertIn(("final", "ok"), outcomes)
            self.assertTrue(any(t.name == "NanoD-snap" for t in threading.enumerate()))
        finally:
            self.assertTrue(worker.close(1.0))


class EngineIntegrationTests(unittest.TestCase):
    """The presenter's snap flow end to end with the real SnapWorker (run on the test thread)."""

    def test_accepted_then_ok_through_the_presenter(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_carousel_presenter import FakeBackend, FakeCapture, Clock as PClock, snapshot
        clock = PClock()
        backend = FakeBackend(monitor=MONITOR, work=WORK)
        backend.clock = clock
        native = FakeNative(clock)
        for i in range(5):
            native.add(Win(100 + i))

        def wait(seconds):
            clock.t += seconds
            native.tick()
        worker = c.SnapWorker(native, clock=clock, wait=wait, threaded=False, post=backend.post)
        presenter = c.CarouselPresenter(None, None, None, backend=backend, capture=FakeCapture(backend), snap=worker,
                                        clock=clock, inline=True)
        self.addCleanup(presenter.close)
        snap = snapshot(count=5, index=1)
        for item in snap["items"]:
            item["id"] = f"id{item['hwnd']}"
        presenter.show(snap)
        backend.activate()
        presenter._step_inline()
        presenter.snap({"t0": clock.t, "index": 1, "side": "left", "target_rect": presenter.half_rect("left"),
                        "item": {"hwnd": 101, "pid": 20, "id": "id101"}})
        presenter._step_inline()
        worker.run_pending()
        presenter._step_inline()
        self.assertEqual(presenter.take_events(), [("snap_result", ("left", "accepted")), ("snap_result", ("left", "ok"))])
        self.assertEqual(native.windows[101].frame(), LEFT)


class StaticTests(unittest.TestCase):
    """P9 / H2 for the picker module, and the forbidden calls (K4 9.6; CAROUSEL.md 12 item 4)."""
    SOURCE = (ROOT / "control_center" / "carousel.py").read_text(encoding="utf-8")

    @classmethod
    def code_lines(cls):
        in_doc = False
        for number, raw in enumerate(cls.SOURCE.splitlines(), 1):
            if raw.count('"""') % 2 == 1:
                in_doc = not in_doc
                continue
            if in_doc or raw.strip().startswith("#"):
                continue
            yield number, re.sub(r'"[^"]*"|\'[^\']*\'', '""', raw.split("  #")[0])

    def test_no_timers_or_sleeps_and_no_hard_coded_periods(self):
        hits = []
        for number, code in self.code_lines():
            for pattern in (r"\.after\(", r"\bSetTimer\(", r"\bsleep\(", r"\b16\.7\b", r"\b8\.3\b", r"\b4\.17\b"):
                if re.search(pattern, code):
                    hits.append((number, pattern, code.strip()))
        self.assertEqual(hits, [])

    def test_the_snap_code_never_names_a_blocking_or_activating_call(self):
        start = self.SOURCE.index("class SnapJob:")
        end = self.SOURCE.index("# ================================================================ Tk-side facade")
        snap_classes = self.SOURCE[start:self.SOURCE.index("# ========================================================================= engine")]
        native = self.SOURCE[self.SOURCE.index("class Win32SnapNative:"):end]
        for body in (snap_classes, native):
            for forbidden in ("SetWindowPlacement", "SW_RESTORE", "SW_MAXIMIZE", "SW_SHOWMAXIMIZED", "SetForegroundWindow",
                              "BringWindowToTop", "SetActiveWindow"):
                self.assertNotIn(forbidden, body)
            self.assertIsNone(re.search(r"\bShowWindow\(", body))
        declared = {entry[1] for entry in c.SNAP_DECLARATIONS}
        self.assertNotIn("SetWindowPlacement", declared)
        self.assertNotIn("ShowWindow", declared)

    def test_win32_snap_native_refuses_activating_or_synchronous_calls(self):
        native = c.Win32SnapNative()
        for command in (9, 3, 1, 5):                               # SW_RESTORE, SW_MAXIMIZE, SW_SHOWNORMAL, SW_SHOW
            with self.assertRaises(ValueError):
                native.show_async(0, command)
        for flags in (0x0214, 0x4204, 0x0013):                    # no ASYNC, or no NOACTIVATE
            with self.assertRaises(ValueError):
                native.set_pos_async(0, None, 0, 0, 1, 1, flags)
        self.assertIsNone(native.identity(0))                      # without the adapter's identity: none


if __name__ == "__main__":
    unittest.main()

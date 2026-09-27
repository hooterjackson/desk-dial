"""Floating knob overlay (control_center.overlay) against FLOATING_KNOB.md section 4.

Headless: no window, DC or GDI object is ever created here. The state machine
and scheduling run on a fake backend with a fake clock. The Win32 backend's
logic (creation order, DIB layout, UpdateLayeredWindow arguments, window
messages, pacing, strict cleanup order) runs against a recording fake API. The
real ctypes declarations are only resolved and inspected, never called.
The real hidden-window lifecycle lives in test_cc_overlay_live.py
(NANOD_OVERLAY_LIVE_TESTS=1 only).
"""
from pathlib import Path
import ast
import ctypes as C
import json
import queue
import random
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from control_center import overlay as ov  # noqa: E402
from control_center.overlay import (  # noqa: E402
    ANIMATING, BLANK_RING, DISABLED, HIDDEN, IN, OUT, SHOWN, KnobOverlay, OverlayScene, SlideMachine,
)

WINDOWS = sys.platform == "win32"
X64 = C.sizeof(C.c_void_p) == 8
SCALE_96 = 360 / 286
W96 = 2 * round(16 * SCALE_96)          # StubFace side at 96 DPI (40)
INSET96 = 24                            # the 24 logical px inset at 96 DPI (section 9.11)
BOX96 = W96 + INSET96                   # the window box: the face plus the inset


# ------------------------------------------------------------------ fakes
class FakeClock:
    def __init__(self, start=100.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds
        return self.t


class QuietLog:
    def __init__(self):
        self.lines = []

    def _add(self, level, message, **_):
        self.lines.append((level, message))

    def info(self, message, **kw):
        self._add("info", message)

    def warning(self, message, **kw):
        self._add("warning", message)

    def error(self, message, **kw):
        self._add("error", message)


def face_factory_recorder():
    """(factory, built faces). The stub face is tiny but keeps the KnobFace contract."""
    built = []

    class StubFace:
        def __init__(self, scale):
            self.scale = scale
            side = 2 * max(4, round(16 * scale))
            self.size = (side, side)
            self.center = (side // 2, side // 2)
            self.lcd_px = round(240 * scale)
            self.composed = []
            built.append(self)

        def compose(self, lcd, ring):
            self.composed.append((lcd, ring))
            image = Image.new("RGBA", self.size, (0, 0, 0, 0))
            image.putpixel((0, 0), (255, 128, 0, 128))     # straight alpha, premultiplied later
            if lcd is not None:
                image.putpixel((1, 0), lcd.getpixel((0, 0)))
            return image

    return StubFace, built


class FakeBackend:
    """The backend interface without Win32. Posted codes go through a queue and
    are dispatched to the engine in pump()/wait(), like the real message loop."""

    def __init__(self, *, clock=None, threaded=False, work=(0, 0, 1920, 1040), dpi=96, quns=5):
        self.clock = clock
        self.threaded = threaded
        self.work, self.dpi, self.quns = work, dpi, quns
        self.calls = []
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self.handler = None
        self.created = False
        self.window_gone = False
        self.visible = False
        self.post_ok = True
        self.post_quit_ok = True
        self.present_ok = True
        self.fail_create = None
        self.prepare_gate = None
        self.pump_error = None
        self.frames = []
        self.gdi, self.user = 11, 13
        self.wait_result = True
        self.thread_log = []          # (call, thread name): the thread rule is checked on it

    def record(self, *call):
        with self.lock:
            self.calls.append(call)
            self.thread_log.append((call[0], threading.current_thread().name))

    def threads_of(self):
        """{call name: set of thread names it ran on}."""
        with self.lock:
            result = {}
            for name, thread in self.thread_log:
                result.setdefault(name, set()).add(thread)
            return result

    def names(self):
        with self.lock:
            return [call[0] for call in self.calls]

    def last(self, name):
        with self.lock:
            matches = [call for call in self.calls if call[0] == name]
        return matches[-1] if matches else None

    def count(self, name, *args):
        with self.lock:
            return sum(1 for call in self.calls if call[0] == name and call[1:1 + len(args)] == args)

    # overlay thread
    def prepare_thread(self):
        self.record("prepare_thread")
        if self.prepare_gate is not None:
            self.prepare_gate.wait(5)
        return 2

    def create(self, handler, position, size):
        self.record("create", tuple(position), tuple(size))
        if self.fail_create is not None:
            raise self.fail_create
        self.handler = handler
        self.created = True
        self.size = tuple(size)

    def resize(self, size):
        self.record("resize", tuple(size))
        self.size = tuple(size)

    def present(self, frame, size, position, src_x, alpha):
        self.record("present", len(frame), tuple(size), tuple(position), src_x, alpha)
        self.frames.append(frame)
        return self.present_ok

    def show(self):
        self.record("show")
        self.visible = True
        return True

    def hide(self):
        self.record("hide")
        self.visible = False
        return True

    def geometry(self):
        self.record("geometry")
        return ov.Geometry(self.work, self.dpi)

    def notification_state(self):
        self.record("notification_state")
        return self.quns

    def gui_resources(self):
        with self.lock:               # not in ``calls``: metrics() may run at any point of a test
            self.thread_log.append(("gui_resources", threading.current_thread().name))
        return (self.gdi, self.user)

    def inject(self, event):
        self.queue.put(("event", event))

    def _dispatch(self, item):
        if item == "quit":
            return False
        if isinstance(item, tuple):
            self.handler(item[1])
        else:
            self.handler(ov.POSTED_EVENTS[item])
        return True

    def pump(self):
        if self.pump_error is not None:
            raise self.pump_error
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                return True
            if not self._dispatch(item):
                return False

    def wait(self, timeout):
        self.record("wait", timeout)
        if not self.wait_result:
            return False              # GetMessageW returned -1
        if not self.threaded:
            return True
        try:
            item = self.queue.get(timeout=0.02 if timeout is None else max(0.001, min(timeout, 0.02)))
        except queue.Empty:
            return True
        return self._dispatch(item)

    def pace(self):
        self.record("pace")
        if self.clock is not None:
            self.clock.advance(1 / 60)
        else:
            time.sleep(0.004)

    def destroy_window(self):
        self.record("destroy_window")
        if self.created and not self.window_gone:
            self.window_gone = True
            self.visible = False
            self.queue.put("quit")

    def unregister(self):
        self.record("unregister")

    def destroy(self):
        self.record("destroy")
        self.destroy_window()
        self.unregister()

    # any thread
    def post(self, code):
        self.record("post", code)
        if not self.post_ok or not self.created or self.window_gone:
            return False
        self.queue.put(code)
        return True

    def post_quit(self):
        self.record("post_quit")
        if not self.post_quit_ok:
            return False
        self.queue.put("quit")
        return True


def ring(seed=1):
    return tuple(((seed * 7 + i) % 256, (seed * 13) % 256, i * 4 % 256, 1.0 if i < 30 else 0.0)
                 for i in range(60))


def scene(key, lcd=None, seed=1):
    return OverlayScene(key, lcd, ring(seed))


def lcd_image(side, colour=(10, 20, 30, 255)):
    return Image.new("RGBA", (side, side), colour)


# ======================================================== pure state machine
class EaseTests(unittest.TestCase):
    def test_curves_endpoints_monotonic_and_clamped(self):
        self.assertEqual(ov.ease_out_cubic(0), 0.0)
        self.assertEqual(ov.ease_out_cubic(1), 1.0)
        self.assertEqual(ov.ease_in_cubic(0), 0.0)
        self.assertEqual(ov.ease_in_cubic(1), 1.0)
        self.assertEqual(ov.ease_out_cubic(-1), 0.0)
        self.assertEqual(ov.ease_in_cubic(2), 1.0)
        self.assertAlmostEqual(ov.ease_out_cubic(0.5), 0.875)
        self.assertAlmostEqual(ov.ease_in_cubic(0.5), 0.125)
        samples = [i / 100 for i in range(101)]
        for curve in (ov.ease_out_cubic, ov.ease_in_cubic):
            values = [curve(u) for u in samples]
            self.assertEqual(values, sorted(values))

    def test_reversal_identity_keeps_visibility(self):
        # out at progress u shows 1 - u^3; in at 1 - u shows the same.
        for i in range(101):
            u = i / 100
            self.assertAlmostEqual(1 - ov.ease_in_cubic(u), ov.ease_out_cubic(1 - u), places=12)

    def test_durations(self):
        self.assertEqual(ov.SLIDE_IN_SECONDS, 0.220)
        self.assertEqual(ov.SLIDE_OUT_SECONDS, 0.260)
        self.assertEqual(ov.HIDE_SECONDS, 2.5)


class SlideMachineTests(unittest.TestCase):
    def shown_machine(self, touch_at=0.0, seconds=2.5):
        m = SlideMachine()
        self.assertEqual(m.touch(touch_at, touch_at + seconds), ov.ARM)
        m.launch(touch_at)
        self.assertEqual(m.step(touch_at + 0.22), [SHOWN])
        return m

    def test_initial_state(self):
        m = SlideMachine()
        self.assertEqual(m.state, HIDDEN)
        self.assertIsNone(m.next_wait(0.0))
        self.assertEqual(m.visible(0.0), 0.0)
        self.assertEqual(m.step(10.0), [])

    def test_touch_from_hidden_arms_pending_until_launch(self):
        m = SlideMachine()
        self.assertEqual(m.touch(1.0, 3.5), ov.ARM)
        self.assertEqual(m.state, IN)
        self.assertTrue(m.pending)
        self.assertEqual(m.visible(5.0), 0.0)
        self.assertEqual(m.step(5.0), [])       # a pending slide-in does not progress
        self.assertIsNone(m.next_wait(5.0))
        self.assertTrue(m.launch(5.0))
        self.assertFalse(m.pending)
        self.assertFalse(m.launch(5.1))
        self.assertEqual(m.next_wait(5.0), ANIMATING)

    def test_slide_in_ease_out_over_220ms(self):
        m = SlideMachine()
        m.touch(0.0, 2.5)
        m.launch(0.0)
        self.assertAlmostEqual(m.visible(0.11), 0.875)
        self.assertEqual(m.step(0.2199), [])
        self.assertEqual(m.state, IN)
        self.assertEqual(m.step(0.22), [SHOWN])
        self.assertEqual(m.visible(0.22), 1.0)
        self.assertAlmostEqual(m.next_wait(0.22), 2.28)

    def test_deadline_then_slide_out_ease_in_over_260ms(self):
        m = self.shown_machine()
        self.assertEqual(m.step(2.4999), [])
        self.assertEqual(m.step(2.5), [OUT])
        self.assertEqual(m.next_wait(2.5), ANIMATING)
        self.assertAlmostEqual(m.visible(2.63), 0.875)
        self.assertEqual(m.step(2.7599), [])
        self.assertEqual(m.step(2.76), [HIDDEN])
        self.assertIsNone(m.deadline)
        self.assertIsNone(m.next_wait(2.76))

    def test_late_wakeup_starts_slide_out_without_a_jump(self):
        m = self.shown_machine()
        self.assertEqual(m.step(4.0), [OUT])     # woke 1.5 s late: still starts from fully shown
        self.assertEqual(m.visible(4.0), 1.0)

    def test_short_deadline_finishes_the_slide_in_first(self):
        m = SlideMachine()
        m.touch(0.0, 0.05)
        m.launch(0.0)
        self.assertEqual(m.step(0.1), [])
        self.assertEqual(m.step(0.22), [SHOWN, OUT])

    def test_every_touch_extends_the_deadline(self):
        m = self.shown_machine()
        self.assertEqual(m.touch(1.0, 3.5), ov.EXTEND)
        self.assertEqual(m.step(2.6), [])
        self.assertEqual(m.step(3.5), [OUT])

    def test_touch_while_sliding_in_only_extends(self):
        m = SlideMachine()
        m.touch(0.0, 2.5)
        m.launch(0.0)
        before = m.visible(0.1)
        self.assertEqual(m.touch(0.1, 2.6), ov.EXTEND)
        self.assertEqual(m.visible(0.1), before)
        self.assertEqual(m.deadline, 2.6)

    def test_every_touch_sets_the_deadline_even_when_shorter(self):
        # FLOATING_KNOB.md section 4: every touch() sets deadline = now + 2.5 s.
        m = self.shown_machine(seconds=10.0)
        self.assertEqual(m.touch(1.0, 3.5), ov.EXTEND)
        self.assertEqual(m.deadline, 3.5)
        self.assertEqual(m.step(3.4999), [])
        self.assertEqual(m.step(3.5), [OUT])

    def test_reversal_mid_slide_out_is_continuous(self):
        for fraction in (0.01, 0.25, 0.5, 0.75, 0.99):
            m = self.shown_machine()
            m.step(2.5)
            t = 2.5 + fraction * 0.26
            v = m.visible(t)
            self.assertEqual(m.touch(t, t + 2.5), ov.REVERSE)
            self.assertEqual(m.state, IN)
            self.assertAlmostEqual(m.visible(t), v, places=9)
            # the rest of the slide-in takes (1 - u_in) * 220 ms = fraction * 220 ms
            self.assertEqual(m.step(t + fraction * 0.22 - 1e-6), [])
            self.assertEqual(m.step(t + fraction * 0.22 + 1e-9), [SHOWN])

    def test_suppression_slides_out_at_once_and_blocks_touches(self):
        m = self.shown_machine()
        self.assertEqual(m.set_suppressed(True, 1.0), OUT)
        self.assertEqual(m.visible(1.0), 1.0)
        self.assertIsNone(m.touch(1.1, 3.6))
        self.assertEqual(m.state, OUT)
        self.assertEqual(m.step(1.26), [HIDDEN])
        self.assertIsNone(m.touch(2.0, 4.5))
        self.assertEqual(m.state, HIDDEN)
        self.assertIsNone(m.set_suppressed(False, 2.0))
        self.assertEqual(m.state, HIDDEN)          # a release never re-shows by itself
        self.assertEqual(m.touch(2.1, 4.6), ov.ARM)

    def test_suppression_during_slide_in_reverses_continuously(self):
        m = SlideMachine()
        m.touch(0.0, 2.5)
        m.launch(0.0)
        v = m.visible(0.11)
        self.assertEqual(m.set_suppressed(True, 0.11), OUT)
        self.assertAlmostEqual(m.visible(0.11), v, places=9)
        self.assertEqual(m.step(0.11 + 0.5 * 0.26 + 1e-9), [HIDDEN])

    def test_suppression_cancels_a_pending_slide_in(self):
        m = SlideMachine()
        m.touch(0.0, 2.5)
        self.assertEqual(m.set_suppressed(True, 0.01), HIDDEN)
        self.assertEqual(m.state, HIDDEN)

    def test_suppression_while_hidden_or_out_changes_nothing(self):
        m = SlideMachine()
        self.assertIsNone(m.set_suppressed(True, 0.0))
        m = self.shown_machine()
        m.step(2.5)
        self.assertIsNone(m.set_suppressed(True, 2.6))
        self.assertEqual(m.state, OUT)

    def test_hide_now(self):
        m = self.shown_machine()
        self.assertTrue(m.hide_now())
        self.assertEqual(m.state, HIDDEN)
        self.assertIsNone(m.deadline)
        self.assertFalse(m.hide_now())


# ============================================= engine via the Tk-side facade
class OverlayHarness(unittest.TestCase):
    """KnobOverlay + OverlayEngine driven inline: a fake clock, a fake backend, no thread."""

    work = (0, 0, 1920, 1040)
    dpi = 96

    def setUp(self):
        self.clock = FakeClock()
        self.backend = FakeBackend(clock=self.clock, work=self.work, dpi=self.dpi)
        self.factory, self.faces = face_factory_recorder()
        self.log = QuietLog()
        self.overlay = KnobOverlay(face_factory=self.factory, backend=self.backend, clock=self.clock,
                                   log=self.log)
        self.overlay._start_inline()

    def step(self):
        alive, wait = self.overlay._iterate()
        self.assertTrue(alive)
        return wait

    def advance(self, seconds):
        self.clock.advance(seconds)
        return self.step()

    def show_fully(self, key="A"):
        self.assertTrue(self.overlay.touch())
        self.overlay.submit(scene(key))
        self.assertEqual(self.step(), ANIMATING)
        self.advance(0.22)
        self.assertEqual(self.overlay.state, SHOWN)

    def presents(self):
        with self.backend.lock:
            return [call for call in self.backend.calls if call[0] == "present"]

    @property
    def face(self):
        return self.faces[-1]


class CreationTests(OverlayHarness):
    def test_created_hidden_at_the_left_edge_vertically_centred(self):
        names = self.backend.names()
        self.assertEqual(names[:3], ["prepare_thread", "geometry", "create"])
        # The box starts at the work area's left edge; the face is drawn 24 px into it (9.11).
        self.assertEqual(self.backend.calls[2], ("create", (0, (1040 - W96) // 2), (BOX96, W96)))
        self.assertEqual(self.overlay.state, HIDDEN)
        self.assertFalse(self.overlay.wants_frames)
        self.assertEqual(self.overlay.rect, (0, (1040 - W96) // 2, BOX96, W96))
        self.assertEqual(self.overlay.lcd_px, round(240 * SCALE_96))
        self.assertNotIn("show", names)
        self.assertNotIn("present", names)
        self.assertAlmostEqual(self.faces[0].scale, SCALE_96)

    def test_hwnd_names_the_backends_window_only_while_live(self):
        """KnobOverlay.hwnd (read-only, for the carousel's capture exclusion): the overlay
        thread's window handle, 0 before start, after close and for a bad value."""
        self.assertEqual(self.overlay.hwnd, 0, "the fake backend has no handle")
        self.backend.hwnd = 0x2A
        self.assertEqual(self.overlay.hwnd, 0x2A)
        self.backend.hwnd = "bogus"
        self.assertEqual(self.overlay.hwnd, 0)
        self.backend.hwnd = 0x2A
        self.assertEqual(KnobOverlay(face_factory=self.factory, backend=self.backend).hwnd, 0, "not started")
        self.overlay.close()
        self.assertEqual(self.overlay.hwnd, 0, "closed")
        self.assertNotIn("show", self.backend.names())

    def test_default_lcd_px_before_start(self):
        fresh = KnobOverlay(face_factory=self.factory, backend=FakeBackend())
        self.assertEqual(fresh.lcd_px, 302)
        self.assertIsNone(fresh.rect)
        self.assertEqual(fresh.state, HIDDEN)
        self.assertFalse(fresh.touch())             # nothing happens before start()
        self.assertFalse(fresh.submit(scene("A")))

    def test_scale_and_premultiplication_come_from_knob_face(self):
        from control_center import knob_face
        engine = self.overlay._engine
        self.assertIs(engine.scale_for, knob_face.scale_for)
        self.assertIs(engine.to_bgra, knob_face.premultiplied_bgra)
        self.assertFalse(hasattr(ov, "scale_for"))           # no local duplicate
        self.assertFalse(hasattr(ov, "premultiplied_bgra"))
        self.assertEqual(ov.DESIGN_RING_OUTER, knob_face.DESIGN_RING_OUTER)
        self.assertEqual(ov.DESIGN_RING_OUTER, 143)
        self.assertAlmostEqual(knob_face.scale_for(96), 360 / 286)
        self.assertAlmostEqual(knob_face.scale_for(192), 2 * 360 / 286)
        self.assertAlmostEqual(knob_face.scale_for(144, 286), 1.5)
        for ring_px in (286, 360, 420):              # the pre-start lcd_px is knob_face's at 96 DPI
            self.assertEqual(ov._initial_lcd_px(ring_px), round(240 * knob_face.scale_for(96, ring_px)))

    def test_default_face_factory_is_knob_face(self):
        from control_center import knob_face
        factory, to_bgra, scaler = ov._face_support(None)
        self.assertIs(factory, knob_face.KnobFace)
        self.assertIs(to_bgra, knob_face.premultiplied_bgra)
        self.assertIs(scaler, knob_face.scale_for)

    def test_knob_face_import_failure_reports_the_real_cause(self):
        import control_center
        name = "control_center.knob_face"
        saved_module = sys.modules.get(name)
        saved_attribute = getattr(control_center, "knob_face", None)
        sys.modules[name] = None                  # the import statement now fails
        if saved_attribute is not None:
            del control_center.knob_face
        try:
            for factory in (None, self.factory):
                overlay = KnobOverlay(face_factory=factory, backend=FakeBackend(), log=self.log)
                self.assertFalse(overlay.start())
                self.assertEqual(overlay.state, DISABLED)
                error = overlay.metrics()["last_error"]
                self.assertIn("knob_face is unavailable", error)
                self.assertIn("ModuleNotFoundError", error)   # the cause, not a generic message
                self.assertIsNone(overlay._thread)
                self.assertTrue(overlay.close())
        finally:
            if saved_module is not None:
                sys.modules[name] = saved_module
            else:
                sys.modules.pop(name, None)
            if saved_attribute is not None:
                control_center.knob_face = saved_attribute
        self.assertTrue(any(level == "error" and "ModuleNotFoundError" in line for level, line in self.log.lines))

    def test_scaled_inset_and_centre_at_200_percent(self):
        backend = FakeBackend(clock=self.clock, work=(0, 40, 2560, 1400), dpi=192)
        overlay = KnobOverlay(face_factory=self.factory, backend=backend, clock=self.clock, log=self.log)
        overlay._start_inline()
        side = 2 * round(16 * 2 * SCALE_96)
        self.assertEqual(overlay.rect, (0, 40 + (1360 - side) // 2, side + 48, side))
        metrics = overlay.metrics()
        self.assertEqual((metrics["face_px"], metrics["inset_px"]), ([side, side], 48))
        self.assertEqual(overlay.lcd_px, round(240 * 2 * SCALE_96))


class EdgeSlideTests(OverlayHarness):
    """FLOATING_KNOB.md section 9.11: the window box starts at the work area's left edge and
    the face is drawn 24 logical px into it, so a slide moves the face out from the screen
    edge itself (never from a cut line 24 px inside it); the shown position is unchanged."""

    def pixel(self, frame, x, y, width=BOX96):
        offset = (y * width + x) * 4
        return tuple(frame[offset:offset + 4])

    def test_window_rect(self):
        self.assertEqual(ov.window_rect((0, 0, 1920, 1040), 96, (434, 434)), (0, 303, 458, 434, 24))
        self.assertEqual(ov.window_rect((0, 40, 2560, 1400), 192, (868, 868)), (0, 286, 916, 868, 48))
        self.assertEqual(ov.window_rect((-1920, 0, 0, 1080), 144, (652, 652)), (-1920, 214, 688, 652, 36))
        self.assertEqual(ov.window_rect((0, 0, 1920, 1040), None, (434, 434)), (0, 303, 458, 434, 24))
        self.assertEqual(ov.window_rect((0, 0, 1920, 1040), 96, (434, 434), inset_logical_px=0),
                         (0, 303, 434, 434, 0))

    def test_the_face_is_drawn_inset_px_into_a_transparent_strip(self):
        self.show_fully()
        frame = self.backend.frames[-1]
        self.assertEqual(len(frame), BOX96 * W96 * 4)
        # StubFace paints its pixel (0, 0) (255, 128, 0) at alpha 128: premultiplied BGRA here.
        self.assertEqual(self.pixel(frame, INSET96, 0), (0, 64, 128, 128))
        for x in range(INSET96):
            for y in (0, W96 // 2, W96 - 1):
                self.assertEqual(self.pixel(frame, x, y), (0, 0, 0, 0), (x, y))

    def test_the_face_emerges_from_the_screen_edge(self):
        self.assertTrue(self.overlay.touch())
        self.overlay.submit(scene("A"))
        self.assertEqual(self.step(), ANIMATING)
        for seconds in (0.03, 0.05, 0.08, 0.06):         # 0.22 s of slide-in, in four steps
            self.advance(seconds)
        self.assertEqual(self.overlay.state, SHOWN)
        x, _y, width, _h = self.overlay.rect
        self.assertEqual((x, width), (0, BOX96))        # the window's clip line is the work area's edge
        lefts = [x + INSET96 - call[4] for call in self.presents()]   # the face's left edge on screen
        self.assertGreaterEqual(len(lefts), 5)
        self.assertEqual(lefts[0] + W96, x)             # first frame (hidden): the face ends at the edge
        self.assertEqual(lefts[-1], x + INSET96)        # shown: 24 px from the edge, as in section 4
        self.assertEqual(lefts, sorted(lefts))          # it only moves right while sliding in


class SlideTests(OverlayHarness):
    def test_first_touch_waits_for_a_fresh_scene_and_presents_hidden_before_show(self):
        self.assertTrue(self.overlay.touch())
        self.assertTrue(self.overlay.wants_frames)          # the Tk side renders from its next tick
        self.assertEqual(self.overlay.state, HIDDEN)         # not processed yet
        wait = self.step()
        self.assertEqual(self.overlay.state, IN)
        self.assertAlmostEqual(wait, ov.FIRST_FRAME_WAIT_SECONDS)
        self.assertNotIn("show", self.backend.names())
        self.assertNotIn("present", self.backend.names())
        self.clock.advance(0.025)                            # next UI tick
        self.overlay.submit(scene("A", lcd_image(self.overlay.lcd_px)))
        self.assertEqual(self.step(), ANIMATING)
        names = self.backend.names()
        first_present, show = names.index("present"), names.index("show")
        self.assertLess(first_present, show)                 # first frame presented while hidden
        self.assertEqual(self.presents()[0][4:], (BOX96, 0))   # src_x = W (the whole box), alpha 0
        self.assertEqual(self.face.composed[-1][1], scene("A").ring)
        self.advance(0.11)
        self.assertEqual(self.presents()[-1][4:], (round(BOX96 * 0.125), round(255 * 0.875)))
        wait = self.advance(0.11)
        self.assertEqual(self.overlay.state, SHOWN)
        self.assertEqual(self.presents()[-1][4:], (0, 255))
        self.assertAlmostEqual(wait, 2.5 - 0.025 - 0.22, places=6)

    def test_every_present_uses_the_fixed_window_rect(self):
        self.show_fully()
        x, y, w, h = self.overlay.rect
        for call in self.presents():
            self.assertEqual(call[2:4], ((w, h), (x, y)))
            self.assertEqual(call[1], w * h * 4)
            self.assertTrue(0 <= call[4] <= w)

    def test_scene_submitted_in_the_same_tick_counts_as_fresh(self):
        self.overlay.submit(scene("A"))
        self.overlay.touch()
        self.assertEqual(self.step(), ANIMATING)            # no arm wait
        self.assertIn("show", self.backend.names())

    def test_arm_times_out_and_launches_with_a_blank_face(self):
        self.overlay.touch()
        self.step()
        self.advance(0.05)
        self.assertNotIn("show", self.backend.names())
        self.assertEqual(self.advance(0.051), ANIMATING)
        self.assertIn("show", self.backend.names())
        lcd, ring_ = self.face.composed[-1]
        self.assertIsNone(lcd)
        self.assertEqual(ring_, BLANK_RING)

    def test_arm_timeout_reuses_the_last_scene_after_a_hide(self):
        self.show_fully("A")
        self.advance(2.5)
        self.advance(0.3)
        self.assertEqual(self.overlay.state, HIDDEN)
        composed = len(self.face.composed)
        self.overlay.touch()
        self.step()
        self.advance(0.11)
        self.assertEqual(self.overlay.state, IN)
        self.assertEqual(len(self.face.composed), composed)  # identical scene: not recomposed
        self.assertEqual(self.presents()[-1][4:], (BOX96, 0))

    def test_slide_out_after_the_deadline_then_sw_hide(self):
        self.show_fully()
        self.assertEqual(self.overlay.state, SHOWN)
        self.advance(2.5 - 0.22 - 0.001)
        self.assertEqual(self.overlay.state, SHOWN)
        self.assertEqual(self.advance(0.001), ANIMATING)
        self.assertEqual(self.overlay.state, OUT)
        self.assertTrue(self.overlay.wants_frames)
        self.advance(0.13)
        self.assertEqual(self.presents()[-1][4:], (round(BOX96 * 0.125), round(255 * 0.875)))
        wait = self.advance(0.13)
        self.assertEqual(self.overlay.state, HIDDEN)
        self.assertIsNone(wait)
        names = self.backend.names()
        self.assertEqual(names[-1], "hide")
        self.assertLess(len(names) - 1 - names[::-1].index("present"), names.index("hide"))
        self.assertFalse(self.overlay.wants_frames)
        self.assertFalse(self.backend.visible)

    def test_touch_extends_the_deadline(self):
        self.show_fully()
        self.advance(0.78)                     # t = +1.0
        self.overlay.touch()
        self.step()
        self.advance(1.6)                      # t = +2.6 > first deadline
        self.assertEqual(self.overlay.state, SHOWN)
        self.advance(0.899)
        self.assertEqual(self.overlay.state, SHOWN)
        self.advance(0.002)
        self.assertEqual(self.overlay.state, OUT)

    def test_touch_during_slide_out_reverses_from_the_current_progress(self):
        self.show_fully()
        self.advance(2.28)
        self.assertEqual(self.overlay.state, OUT)
        self.advance(0.13)
        before = self.presents()[-1]
        self.assertEqual(before[5], round(255 * 0.875))
        shows = self.backend.count("show")
        geometries = self.backend.count("geometry")
        self.overlay.touch()
        self.assertEqual(self.step(), ANIMATING)
        self.assertEqual(self.overlay.state, IN)
        self.assertEqual(self.presents()[-1], before)          # no jump
        self.assertEqual(self.backend.count("show"), shows + 1)        # HWND_TOPMOST re-asserted
        self.assertEqual(self.backend.count("geometry"), geometries + 1)  # geometry recomputed
        self.advance(0.055)
        self.assertEqual(self.presents()[-1][5], round(255 * ov.ease_out_cubic(0.75)))
        self.advance(0.056)
        self.assertEqual(self.overlay.state, SHOWN)
        self.assertNotIn("hide", self.backend.names())

    def test_peek_uses_its_own_duration(self):
        self.assertTrue(self.overlay.peek(5.0))
        self.overlay.submit(scene("A"))
        self.step()
        self.advance(4.9)
        self.assertEqual(self.overlay.state, SHOWN)
        self.advance(0.11)
        self.assertEqual(self.overlay.state, OUT)

    def test_touch_after_a_longer_peek_restarts_the_deadline_at_touch_time(self):
        self.overlay.peek(5.0)
        self.overlay.submit(scene("A"))
        self.step()
        self.advance(1.0)
        self.overlay.touch()                   # deadline = now + 2.5 s (spec), not the peek's 5 s
        self.step()
        self.advance(2.499)
        self.assertEqual(self.overlay.state, SHOWN)
        self.advance(0.002)
        self.assertEqual(self.overlay.state, OUT)

    def test_coalesced_peek_then_touch_keeps_the_newest(self):
        self.overlay.peek(5.0)
        self.clock.advance(0.01)
        self.overlay.touch()                   # coalesced into the pending post: newest wins
        self.assertEqual(self.backend.count("post", ov.WM_APP_TOUCH), 1)
        self.assertAlmostEqual(self.overlay._mail.touch_deadline, self.clock() + 2.5)
        self.overlay.submit(scene("A"))
        self.step()
        self.assertAlmostEqual(self.overlay._engine.machine.deadline, self.clock() + 2.5)

    def test_coalesced_touches_keep_the_latest_deadline(self):
        self.overlay.touch()
        self.clock.advance(1.0)
        self.overlay.touch()                   # coalesced into the pending post
        self.assertEqual(self.backend.count("post", ov.WM_APP_TOUCH), 1)
        self.overlay.submit(scene("A"))
        self.step()
        self.advance(2.4)
        self.assertEqual(self.overlay.state, SHOWN)
        self.advance(0.11)
        self.assertEqual(self.overlay.state, OUT)

    def test_wants_frames_follows_the_state(self):
        self.assertFalse(self.overlay.wants_frames)
        self.overlay.touch()
        self.assertTrue(self.overlay.wants_frames)
        self.step()
        self.assertTrue(self.overlay.wants_frames)
        self.overlay.submit(scene("A"))
        self.step()
        self.assertTrue(self.overlay.wants_frames)
        self.advance(2.5)
        self.assertEqual(self.overlay.state, OUT)
        self.assertTrue(self.overlay.wants_frames)
        self.advance(0.27)
        self.assertFalse(self.overlay.wants_frames)


class SuppressionTests(OverlayHarness):
    def test_suppression_slides_out_at_once_and_ignores_touches(self):
        self.show_fully()
        self.assertTrue(self.overlay.set_suppressed("picker", True))
        self.assertFalse(self.overlay.set_suppressed("picker", True))   # unchanged: no post
        self.assertEqual(self.step(), ANIMATING)
        self.assertEqual(self.overlay.state, OUT)
        self.assertFalse(self.overlay.touch())
        self.assertFalse(self.overlay.peek())
        self.advance(0.27)
        self.assertEqual(self.overlay.state, HIDDEN)
        self.assertEqual(self.backend.names()[-1], "hide")
        self.overlay.set_suppressed("disconnected", True)
        self.overlay.set_suppressed("picker", False)
        self.step()
        self.assertFalse(self.overlay.touch())                          # one reason still holds
        self.assertEqual(self.overlay.metrics()["suppressed"], ["disconnected"])
        self.overlay.set_suppressed("disconnected", False)
        self.step()
        self.assertEqual(self.overlay.state, HIDDEN)                      # a release does not re-show
        self.assertTrue(self.overlay.touch())
        self.step()
        self.assertEqual(self.overlay.state, IN)

    def test_touch_racing_a_suppression_is_ignored_on_the_overlay_thread(self):
        self.show_fully()
        self.advance(2.28)
        self.assertEqual(self.overlay.state, OUT)
        self.overlay.touch()                         # queued before the suppression
        self.overlay.set_suppressed("picker", True)
        self.step()
        self.assertEqual(self.overlay.state, OUT)

    def test_suppression_during_slide_in_reverses_without_a_jump(self):
        self.overlay.touch()
        self.overlay.submit(scene("A"))
        self.step()
        self.advance(0.11)
        before = self.presents()[-1]
        self.overlay.set_suppressed("picker", True)
        self.step()
        self.assertEqual(self.overlay.state, OUT)
        self.assertEqual(self.presents()[-1], before)
        self.advance(0.01)
        self.assertLess(self.presents()[-1][5], before[5])

    def test_suppression_cancels_a_pending_slide_in(self):
        self.overlay.touch()
        self.step()
        self.overlay.set_suppressed("disconnected", True)
        self.assertIsNone(self.step())
        self.assertEqual(self.overlay.state, HIDDEN)
        self.assertNotIn("show", self.backend.names())
        self.assertFalse(self.overlay.wants_frames)

    def test_suppression_set_before_start_applies(self):
        backend = FakeBackend(clock=self.clock)
        overlay = KnobOverlay(face_factory=self.factory, backend=backend, clock=self.clock, log=self.log)
        overlay.set_suppressed("disconnected", True)
        overlay._start_inline()
        self.assertFalse(overlay.touch())
        self.assertTrue(overlay._engine.machine.suppressed)
        self.assertEqual(backend.count("post", ov.WM_APP_SUPPRESS), 0)

    def test_fullscreen_and_presentation_block_the_slide_in(self):
        for state in (3, 4):
            self.backend.quns = state
            self.assertTrue(self.overlay.touch())
            self.assertIsNone(self.step())
            self.assertEqual(self.overlay.state, HIDDEN)
            self.assertFalse(self.overlay.wants_frames)
            metrics = self.overlay.metrics()
            self.assertTrue(metrics["fullscreen_blocked"])
            self.assertEqual(metrics["notification_state"], state)
        self.assertNotIn("show", self.backend.names())
        for state in (2, 5, None):                      # busy (borderless video) and unknown are allowed
            self.backend.quns = state
            self.overlay.touch()
            self.step()
            self.assertEqual(self.overlay.state, IN)
            self.assertFalse(self.overlay.metrics()["fullscreen_blocked"])
            self.overlay._engine.hide_now()

    def test_fullscreen_is_checked_at_each_slide_in_including_reversal(self):
        self.show_fully()
        checks = self.backend.count("notification_state")
        self.advance(2.3)
        self.assertEqual(self.overlay.state, OUT)
        self.advance(0.05)                            # partway out, so a reversal lands in IN
        self.backend.quns = 3
        self.overlay.touch()
        self.step()
        self.assertEqual(self.backend.count("notification_state"), checks + 1)
        self.assertEqual(self.overlay.state, OUT)
        self.backend.quns = 5
        self.overlay.touch()                          # the reversal is a slide-in: checked again
        self.step()
        self.assertEqual(self.overlay.state, IN)
        self.assertEqual(self.backend.count("notification_state"), checks + 2)
        self.advance(0.3)
        self.assertEqual(self.overlay.state, SHOWN)
        self.overlay.touch()                          # touches while shown only extend: no check
        self.step()
        self.assertEqual(self.backend.count("notification_state"), checks + 2)

    def test_lost_release_post_is_resynced_at_the_next_wakeup(self):
        self.overlay.set_suppressed("disconnected", True)
        self.step()
        self.assertTrue(self.overlay._engine.machine.suppressed)
        self.backend.post_ok = False
        self.assertTrue(self.overlay.set_suppressed("disconnected", False))   # its WM_APP+4 is lost
        self.assertFalse(self.overlay._mail.suppress_posted)
        self.assertEqual(self.overlay.metrics()["post_failures"], 1)
        self.backend.post_ok = True
        self.assertTrue(self.overlay.touch())         # the Tk side has no reason left
        self.assertEqual(self.backend.count("post", ov.WM_APP_SUPPRESS), 2)   # no re-post needed
        self.overlay.submit(scene("A"))
        self.assertEqual(self.step(), ANIMATING)      # the touch's wake-up re-reads the reasons first
        self.assertFalse(self.overlay._engine.machine.suppressed)
        self.assertEqual(self.overlay.state, IN)
        self.assertEqual(self.overlay.metrics()["suppressed"], [])
        self.advance(0.22)
        self.assertEqual(self.overlay.state, SHOWN)

    def test_lost_hold_post_is_resynced_at_the_next_wakeup(self):
        self.show_fully()
        self.backend.post_ok = False
        self.overlay.set_suppressed("picker", True)   # its WM_APP+4 is lost
        self.backend.post_ok = True
        self.overlay.submit(scene("B", seed=2))       # any wake-up (frame, timer, touch) re-syncs
        self.assertEqual(self.step(), ANIMATING)
        self.assertTrue(self.overlay._engine.machine.suppressed)
        self.assertEqual(self.overlay.state, OUT)
        self.advance(0.27)
        self.assertEqual(self.overlay.state, HIDDEN)

    def test_resync_applies_only_changes(self):
        engine = self.overlay._engine
        applied = []
        original = engine._apply_suppression
        engine._apply_suppression = lambda now: (applied.append(now), original(now))
        self.show_fully()
        self.assertEqual(applied, [])                 # unchanged reasons: nothing re-applied per frame
        self.overlay.set_suppressed("picker", True)
        self.step()
        self.assertEqual(len(applied), 1)             # the delivered WM_APP+4
        self.assertEqual(self.overlay.state, OUT)
        before = self.presents()[-1]
        self.advance(0.0)
        self.advance(0.13)
        self.assertEqual(len(applied), 1)
        self.assertLess(self.presents()[-1][5], before[5])   # the slide-out was never restarted

    def test_reversal_at_the_very_start_of_the_slide_out_is_fully_shown(self):
        self.show_fully()
        self.advance(2.28)
        self.assertEqual(self.overlay.state, OUT)
        self.overlay.touch()
        self.step()
        self.assertEqual(self.overlay.state, SHOWN)
        self.assertEqual(self.presents()[-1][4:], (0, 255))


class HandOffTests(OverlayHarness):
    def test_newest_wins_one_post_one_compose(self):
        self.show_fully("A")
        posts = self.backend.count("post", ov.WM_APP_FRAME)
        composed = len(self.face.composed)
        for key in ("B", "C", "D"):
            self.assertTrue(self.overlay.submit(scene(key, seed=ord(key))))
        self.assertEqual(self.backend.count("post", ov.WM_APP_FRAME), posts + 1)
        self.step()
        self.assertEqual(len(self.face.composed), composed + 1)
        self.assertEqual(self.face.composed[-1][1], ring(ord("D")))
        self.overlay.submit(scene("E", seed=5))
        self.assertEqual(self.backend.count("post", ov.WM_APP_FRAME), posts + 2)

    def test_failed_post_clears_the_pending_flag(self):
        self.show_fully("A")
        self.backend.post_ok = False
        self.assertFalse(self.overlay.submit(scene("B", seed=2)))
        self.assertFalse(self.overlay._mail.frame_posted)
        self.assertEqual(self.overlay.metrics()["post_failures"], 1)
        self.backend.post_ok = True
        self.assertTrue(self.overlay.submit(scene("C", seed=3)))
        self.assertTrue(self.overlay._mail.frame_posted)
        self.step()
        self.assertEqual(self.face.composed[-1][1], ring(3))

    def test_failed_touch_post_clears_its_flag(self):
        self.backend.post_ok = False
        self.assertFalse(self.overlay.touch())
        self.assertFalse(self.overlay._mail.touch_posted)
        self.backend.post_ok = True
        self.assertTrue(self.overlay.touch())
        self.assertTrue(self.overlay._mail.touch_posted)

    def test_failed_suppress_post_clears_its_flag(self):
        self.backend.post_ok = False
        self.overlay.set_suppressed("picker", True)
        self.assertFalse(self.overlay._mail.suppress_posted)
        self.backend.post_ok = True
        self.overlay.set_suppressed("disconnected", True)
        self.assertTrue(self.overlay._mail.suppress_posted)
        self.step()
        self.assertEqual(self.overlay.metrics()["suppressed"], ["disconnected", "picker"])

    def test_identical_scenes_are_skipped(self):
        self.show_fully("A")
        composed, presented = len(self.face.composed), len(self.presents())
        self.overlay.submit(scene("A"))                 # a new object with equal key and ring
        self.step()
        self.assertEqual(len(self.face.composed), composed)
        self.assertEqual(len(self.presents()), presented)

    def test_ring_or_lcd_key_change_recomposes(self):
        self.show_fully("A")
        composed = len(self.face.composed)
        self.overlay.submit(scene("A", seed=9))
        self.step()
        self.overlay.submit(scene("B", seed=9))
        self.step()
        self.assertEqual(len(self.face.composed), composed + 2)
        self.assertEqual(self.presents()[-1][4:], (0, 255))

    def test_keyless_scene_compares_the_lcd_object(self):
        self.show_fully("A")
        lcd = lcd_image(self.overlay.lcd_px)
        self.overlay.submit(OverlayScene(None, lcd, ring(1)))
        self.step()
        composed = len(self.face.composed)
        self.overlay.submit(OverlayScene(None, lcd, ring(1)))
        self.step()
        self.assertEqual(len(self.face.composed), composed)
        self.overlay.submit(OverlayScene(None, lcd.copy(), ring(1)))
        self.step()
        self.assertEqual(len(self.face.composed), composed + 1)

    def test_scenes_submitted_while_hidden_are_kept_not_presented(self):
        self.overlay.submit(scene("A"))
        self.step()
        self.assertNotIn("present", self.backend.names())
        self.assertEqual(self.face.composed, [])

    def test_submit_freezes_the_ring(self):
        self.show_fully("A")
        mutable = [list(colour) for colour in ring(4)]
        self.overlay.submit(("B", None, mutable))
        mutable[0][0] = 99
        self.step()
        self.assertEqual(self.face.composed[-1][1], ring(4))
        self.assertIsInstance(self.face.composed[-1][1][0], tuple)

    def test_frames_reaching_the_backend_are_premultiplied_bgra(self):
        self.show_fully("A")
        frame = self.backend.frames[-1]
        # (255,128,0,128) -> B,G,R premultiplied, at the face's pixel (0, 0): INSET96 px into the box.
        self.assertEqual(list(frame[4 * INSET96:4 * INSET96 + 4]), [0, 64, 128, 128])
        for i in range(0, len(frame), 4):
            self.assertLessEqual(max(frame[i:i + 3]), frame[i + 3])

    def test_stale_lcd_size_is_fitted_to_the_face(self):
        self.show_fully("A")
        self.assertEqual(self.overlay.metrics()["lcd_resizes"], 0)
        self.assertIsNone(self.overlay.metrics()["face_lcd_resizes"])   # the stub face has no counter
        self.overlay.submit(scene("B", lcd_image(100)))
        self.step()
        lcd = self.face.composed[-1][0]
        self.assertEqual(lcd.size, (self.face.lcd_px, self.face.lcd_px))
        self.assertEqual(self.overlay.metrics()["lcd_resizes"], 1)      # section 2: never silently upscaled
        self.overlay.submit(scene("C", lcd_image(self.overlay.lcd_px)))
        self.step()
        self.assertEqual(self.overlay.metrics()["lcd_resizes"], 1)      # the right size does not count

    def test_face_lcd_resizes_are_reported(self):
        self.show_fully("A")
        self.face.lcd_resizes = 3
        self.overlay.submit(scene("B", seed=2))
        self.step()
        self.assertEqual(self.overlay.metrics()["face_lcd_resizes"], 3)
        json.dumps(self.overlay.metrics())                             # status.json-safe

    def test_compose_failure_keeps_the_overlay_running(self):
        self.show_fully("A")
        self.face.compose = lambda lcd, ring_: (_ for _ in ()).throw(ValueError("bad ring"))
        self.overlay.submit(scene("B", seed=2))
        self.step()
        metrics = self.overlay.metrics()
        self.assertEqual(metrics["compose_failures"], 1)
        self.assertIn("bad ring", metrics["last_error"])
        self.assertEqual(self.overlay.state, SHOWN)


class GeometryTests(OverlayHarness):
    def hide_again(self):
        self.advance(2.5)
        self.advance(0.3)
        self.assertEqual(self.overlay.state, HIDDEN)

    def test_geometry_recomputed_on_every_slide_in_and_sprites_rebuilt_on_dpi_change(self):
        self.show_fully("A")
        self.hide_again()
        self.assertEqual(len(self.faces), 1)
        geometries = self.backend.count("geometry")
        self.show_fully("A")
        self.assertEqual(self.backend.count("geometry"), geometries + 1)
        self.assertEqual(len(self.faces), 1)             # same DPI: sprites reused
        self.hide_again()
        self.backend.dpi = 192
        self.backend.work = (0, 0, 2560, 1400)
        self.overlay.touch()
        self.overlay.submit(scene("A"))
        self.step()
        self.assertEqual(len(self.faces), 2)
        self.assertAlmostEqual(self.faces[-1].scale, 2 * SCALE_96)
        side = self.faces[-1].size[0]
        self.assertEqual(self.backend.last("resize"), ("resize", (side + 48, side)))
        self.assertEqual(self.overlay.rect, (0, (1400 - side) // 2, side + 48, side))
        self.assertEqual(self.overlay.lcd_px, round(240 * 2 * SCALE_96))
        self.assertEqual(self.presents()[-1][2], (side + 48, side))
        metrics = self.overlay.metrics()
        self.assertEqual((metrics["dpi"], metrics["window_px"]), (192, [side + 48, side]))
        self.assertEqual(metrics["face_builds"], 2)

    def test_dirty_geometry_while_visible_moves_the_window_now(self):
        self.show_fully("A")
        self.backend.work = (100, 0, 2020, 1040)
        self.backend.inject(ov.EV_DIRTY)
        self.step()
        self.assertEqual(self.overlay.rect[0], 100)                 # the new work area's left edge
        self.assertEqual(self.presents()[-1][3][0], 100)
        self.assertNotIn("resize", self.backend.names())     # same size: DIB kept

    def test_dirty_geometry_while_hidden_updates_the_rect_without_showing(self):
        # Section 9.17: Settings keeps clear of overlay.rect, so a DPI or work-area change while
        # the knob is hidden (its usual state) is laid out at once; nothing is shown.
        self.show_fully("A")
        self.hide_again()
        geometries = self.backend.count("geometry")
        presents, shows = len(self.presents()), self.backend.count("show")
        self.backend.dpi = 144
        self.backend.work = (0, 0, 1920, 1032)
        self.backend.inject(ov.EV_DIRTY)
        self.step()
        self.assertEqual(self.backend.count("geometry"), geometries + 1)
        side = self.faces[-1].size[0]
        self.assertAlmostEqual(self.faces[-1].scale, 1.5 * SCALE_96)
        self.assertEqual(self.overlay.rect, (0, (1032 - side) // 2, side + 36, side))
        self.assertEqual(self.overlay.lcd_px, round(240 * 1.5 * SCALE_96))
        self.assertEqual(self.backend.last("resize"), ("resize", (side + 36, side)))
        self.assertEqual(self.overlay.state, HIDDEN)
        self.assertEqual((len(self.presents()), self.backend.count("show")), (presents, shows))
        self.assertFalse(self.backend.visible)
        self.step()                                     # laid out once: not again while clean
        self.assertEqual(self.backend.count("geometry"), geometries + 1)
        self.overlay.touch()
        self.overlay.submit(scene("A"))
        self.step()
        self.assertEqual(self.backend.count("geometry"), geometries + 2, "every slide-in lays out again")
        self.assertEqual(len(self.faces), 2, "same DPI: the face built while hidden is reused")

    def test_dirty_geometry_while_hidden_before_the_first_slide_in(self):
        geometries = self.backend.count("geometry")
        self.backend.work = (0, 40, 1920, 1080)
        self.backend.inject(ov.EV_DIRTY)
        self.step()
        self.assertEqual(self.backend.count("geometry"), geometries + 1)
        self.assertEqual(self.overlay.rect[1], 40 + (1040 - self.overlay.rect[3]) // 2)
        self.assertEqual(self.overlay.state, HIDDEN)
        self.overlay.touch()
        self.overlay.submit(scene("A"))
        self.step()
        self.assertEqual(self.backend.count("geometry"), geometries + 2)

    def test_geometry_failure_while_visible_keeps_the_old_rect(self):
        self.show_fully("A")
        rect = self.overlay.rect
        self.backend.geometry = lambda: (_ for _ in ()).throw(OSError("no monitor"))
        self.backend.inject(ov.EV_DIRTY)
        self.step()
        self.assertEqual(self.overlay.rect, rect)
        self.assertEqual(self.overlay.state, SHOWN)


class EventTests(OverlayHarness):
    def test_hide_event_hides_immediately(self):
        self.show_fully("A")
        self.backend.inject(ov.EV_HIDE)
        self.step()
        self.assertEqual(self.overlay.state, HIDDEN)
        self.assertEqual(self.backend.last("hide"), ("hide",))
        self.assertFalse(self.overlay.wants_frames)
        self.assertFalse(self.backend.visible)

    def test_timer_event_is_only_a_wakeup(self):
        self.show_fully("A")
        presented = len(self.presents())
        self.backend.inject(ov.EV_TIMER)
        self.step()
        self.assertEqual(len(self.presents()), presented)
        self.assertEqual(self.overlay.state, SHOWN)

    def test_present_failure_is_counted_and_retried(self):
        self.backend.present_ok = False
        self.show_fully("A")
        failures = self.overlay.metrics()["ulw_failures"]
        self.assertGreater(failures, 0)
        wait = self.step()
        self.assertLessEqual(wait, ov.PRESENT_RETRY_SECONDS)
        self.backend.present_ok = True
        presented = self.overlay.metrics()["frames_presented"]
        self.advance(ov.PRESENT_RETRY_SECONDS)
        self.assertEqual(self.overlay.metrics()["frames_presented"], presented + 1)
        self.assertEqual(self.presents()[-1][4:], (0, 255))

    def test_stop_runs_cleanup_and_ends_the_loop(self):
        self.show_fully("A")
        self.backend.post(ov.WM_APP_STOP)
        alive, wait = self.overlay._iterate()
        self.assertTrue(alive)
        self.assertIsNone(wait)
        self.assertTrue(self.overlay._engine.stopped)
        self.assertEqual(self.backend.names()[-1], "destroy_window")
        self.assertEqual(self.overlay._iterate(), (False, None))   # WM_QUIT from WM_DESTROY

    def test_metrics_are_json_ready(self):
        self.show_fully("A")
        metrics = self.overlay.metrics()
        json.dumps(metrics)
        for key in ("state", "dpi", "window_px", "lcd_px", "frames_presented", "ulw_failures", "last_error",
                    "gdi_objects", "user_objects", "rect", "suppressed", "post_failures", "compose_ms"):
            self.assertIn(key, metrics)
        self.assertEqual(metrics["state"], SHOWN)
        self.assertEqual((metrics["gdi_objects"], metrics["user_objects"]), (11, 13))
        self.assertEqual(metrics["window_px"], [BOX96, W96])
        self.assertEqual((metrics["face_px"], metrics["inset_px"]), ([W96, W96], INSET96))
        self.assertGreaterEqual(metrics["frames_presented"], 2)    # the hidden first frame + fully shown
        self.assertEqual(metrics["ulw_failures"], 0)

    def test_close_inline_disables(self):
        self.assertTrue(self.overlay.close())
        self.assertEqual(self.overlay.state, DISABLED)
        self.assertFalse(self.overlay.touch())
        self.assertFalse(self.overlay.submit(scene("A")))
        self.assertFalse(self.overlay.wants_frames)
        self.assertTrue(self.overlay.close())


# ====================================================== threaded lifecycle
class ThreadedTests(unittest.TestCase):
    def setUp(self):
        self.factory, self.faces = face_factory_recorder()
        self.log = QuietLog()
        self.backend = FakeBackend(threaded=True)
        self.overlays = []

    # The thread rule: only these backend calls may run off the NanoD-overlay thread.
    ANY_THREAD = {"post", "post_quit", "gui_resources"}

    def tearDown(self):
        for overlay in self.overlays:
            overlay.close()
        self.assert_thread_rule()

    def assert_thread_rule(self):
        for name, threads in self.backend.threads_of().items():
            if name not in self.ANY_THREAD:
                self.assertEqual(threads, {ov.THREAD_NAME}, f"{name} ran on {sorted(threads)}")

    def make(self, **kw):
        overlay = KnobOverlay(face_factory=self.factory, backend=self.backend, log=self.log, **kw)
        self.overlays.append(overlay)
        return overlay

    def wait_for(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()

    def test_full_cycle_on_the_overlay_thread(self):
        overlay = self.make(hide_seconds=0.3)
        self.assertTrue(overlay.start())
        thread = overlay._thread
        self.assertEqual(thread.name, "NanoD-overlay")
        self.assertTrue(thread.daemon)
        self.assertNotEqual(thread.ident, threading.get_ident())
        self.assertEqual(overlay.state, HIDDEN)
        self.assertTrue(overlay.touch())
        self.assertTrue(overlay.wants_frames)
        overlay.submit(scene("A"))
        self.assertTrue(self.wait_for(lambda: overlay.state == SHOWN))
        self.assertEqual(overlay.metrics()["state"], SHOWN)   # gui_resources from the Tk thread
        self.assertTrue(self.wait_for(lambda: overlay.state == HIDDEN))
        names = self.backend.names()
        self.assertIn("pace", names)
        self.assertEqual(names[names.index("present"):].count("show"), 1)
        self.assertLess(len(names) - 1 - names[::-1].index("present"), len(names) - 1 - names[::-1].index("hide"))
        started = time.monotonic()
        self.assertTrue(overlay.close())
        self.assertLessEqual(time.monotonic() - started, ov.CLOSE_TIMEOUT_SECONDS + 0.2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(overlay.state, DISABLED)
        names = self.backend.names()
        self.assertIn(ov.WM_APP_STOP, [call[1] for call in self.backend.calls if call[0] == "post"])
        self.assertLess(names.index("destroy_window"), names.index("unregister"))
        self.assertEqual(names[-1], "unregister")
        threads = self.backend.threads_of()
        main = threading.current_thread().name
        self.assertEqual(threads["post"], {main})             # touch, submit and close only post
        self.assertEqual(threads["gui_resources"], {main})
        for name in ("prepare_thread", "geometry", "notification_state", "create", "present", "show",
                     "pace", "wait", "hide", "destroy_window", "unregister"):
            self.assertEqual(threads.get(name), {"NanoD-overlay"}, name)
        self.assert_thread_rule()

    def test_loop_ending_without_close_disables(self):
        """WM_QUIT or a GetMessageW failure without close(): 'disabled', never a stale 'shown'."""
        for how in ("quit", "getmessage"):
            with self.subTest(how=how):
                self.backend = FakeBackend(threaded=True)
                overlay = self.make()
                self.assertTrue(overlay.start())
                overlay.touch()
                overlay.submit(scene("A"))
                self.assertTrue(self.wait_for(lambda: overlay.state == SHOWN))
                if how == "quit":
                    self.backend.queue.put("quit")
                else:
                    self.backend.wait_result = False
                self.assertTrue(self.wait_for(lambda: not overlay._thread.is_alive()))
                self.assertEqual(overlay.state, DISABLED)
                self.assertFalse(overlay.wants_frames)
                self.assertEqual(overlay._status.machine_state, HIDDEN)
                metrics = overlay.metrics()
                self.assertEqual(metrics["state"], DISABLED)
                self.assertIn("ended unexpectedly", metrics["last_error"])
                self.assertFalse(overlay.touch())                     # no more posts to a dead window
                self.assertFalse(overlay.submit(scene("B")))
                self.assertEqual(metrics["post_failures"], 0)
                names = self.backend.names()
                self.assertIn("destroy_window", names)
                self.assertEqual(names[-1], "unregister")
                self.assertTrue(any(level == "error" and "ended unexpectedly" in line
                                    for level, line in self.log.lines))
                self.assertTrue(overlay.close())
                self.assert_thread_rule()

    def test_close_is_not_reported_as_an_unexpected_end(self):
        overlay = self.make()
        self.assertTrue(overlay.start())
        self.assertTrue(overlay.close())
        self.assertIsNone(overlay.metrics()["last_error"])
        self.assertFalse(any("unexpectedly" in line for _level, line in self.log.lines))

    def test_close_while_shown_joins_within_one_second(self):
        overlay = self.make()
        self.assertTrue(overlay.start())
        overlay.touch()
        overlay.submit(scene("A"))
        self.assertTrue(self.wait_for(lambda: overlay.state == SHOWN))
        started = time.monotonic()
        self.assertTrue(overlay.close())
        self.assertLess(time.monotonic() - started, ov.CLOSE_TIMEOUT_SECONDS)
        self.assertFalse(overlay._thread.is_alive())
        self.assertTrue(overlay.close())                 # idempotent

    def test_close_falls_back_to_wm_quit_when_the_stop_cannot_be_posted(self):
        overlay = self.make()
        self.assertTrue(overlay.start())
        self.backend.post_ok = False
        self.assertTrue(overlay.close())
        self.assertIn("post_quit", self.backend.names())
        self.assertFalse(overlay._thread.is_alive())
        names = self.backend.names()
        self.assertIn("destroy_window", names)
        self.assertEqual(names[-1], "unregister")

    def test_creation_failure_disables_and_the_app_keeps_running(self):
        self.backend.fail_create = OSError("CreateWindowExW failed (error 5)")
        overlay = self.make()
        self.assertFalse(overlay.start())
        self.assertEqual(overlay.state, DISABLED)
        self.assertFalse(overlay.wants_frames)
        self.assertFalse(overlay._thread.is_alive())
        self.assertIn("error 5", overlay.metrics()["last_error"])
        self.assertTrue(any(level == "error" and "creation failed" in line for level, line in self.log.lines))
        self.assertFalse(overlay.touch())
        self.assertFalse(overlay.peek())
        self.assertFalse(overlay.submit(scene("A")))
        overlay.set_suppressed("picker", True)
        self.assertIn("destroy", self.backend.names())       # partial resources cleaned
        self.assertTrue(overlay.close())
        self.assertFalse(overlay.start())

    def test_face_build_failure_disables(self):
        def broken(scale):
            raise MemoryError("sprites")
        overlay = KnobOverlay(face_factory=broken, backend=self.backend, log=self.log)
        self.overlays.append(overlay)
        self.assertFalse(overlay.start())
        self.assertEqual(overlay.state, DISABLED)
        self.assertNotIn("create", self.backend.names())

    def test_backend_construction_failure_disables(self):
        class Unavailable:
            def __init__(self, *a, **k):
                raise ov.OverlayError("the floating knob needs Windows")
        original = ov.Win32Backend
        ov.Win32Backend = Unavailable
        try:
            overlay = KnobOverlay(face_factory=self.factory, log=self.log)
            self.assertFalse(overlay.start())
        finally:
            ov.Win32Backend = original
        self.assertEqual(overlay.state, DISABLED)
        self.assertIsNone(overlay._thread)
        self.assertIn("needs Windows", overlay.metrics()["last_error"])
        self.assertTrue(overlay.close())

    def test_start_timeout_abandons_and_the_thread_cleans_up(self):
        self.backend.prepare_gate = threading.Event()
        overlay = self.make()
        overlay.START_TIMEOUT_SECONDS = 0.1
        started = time.monotonic()
        self.assertFalse(overlay.start())
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(overlay.state, DISABLED)
        self.assertIn("did not start", overlay.metrics()["last_error"])
        self.assertFalse(overlay.touch())
        self.backend.prepare_gate.set()
        self.assertTrue(self.wait_for(lambda: not overlay._thread.is_alive()))
        names = self.backend.names()
        self.assertIn("create", names)
        self.assertNotIn("show", names)
        self.assertEqual(names[-1], "unregister")

    def test_loop_failure_disables_and_cleans_up(self):
        overlay = self.make()
        self.assertTrue(overlay.start())
        self.backend.pump_error = RuntimeError("loop broke")
        overlay.touch()
        self.assertTrue(self.wait_for(lambda: overlay.state == DISABLED))
        self.assertTrue(self.wait_for(lambda: not overlay._thread.is_alive()))
        self.assertFalse(overlay.wants_frames)
        self.assertIn("loop broke", overlay.metrics()["last_error"])
        self.assertEqual(self.backend.names()[-1], "unregister")

    def test_start_is_idempotent(self):
        overlay = self.make()
        self.assertTrue(overlay.start())
        thread = overlay._thread
        self.assertTrue(overlay.start())
        self.assertIs(overlay._thread, thread)


# ================================================ Win32 backend on a fake API
class FakeFunction:
    def __init__(self, api, name):
        self.api, self.name = api, name

    def __call__(self, *args):
        self.api.calls.append((self.name, args))
        behaviour = self.api.behaviour.get(self.name, 1)
        return behaviour(*args) if callable(behaviour) else behaviour


class FakeDll:
    def __init__(self, api):
        self._api = api

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return FakeFunction(self._api, name)


class FakeApi:
    """Records every call; no Win32 function is ever invoked."""

    def __init__(self):
        self.calls = []
        self.error = 0
        self.dibs = []
        self.messages = []
        self.behaviour = {
            "SetThreadDpiAwarenessContext": 0x11, "GetThreadDpiAwarenessContext": 0x22,
            "GetAwarenessFromDpiAwarenessContext": 2, "GetCurrentThreadId": 4242, "PeekMessageW": self._peek,
            "GetModuleHandleW": 0x400000, "RegisterClassExW": 0xC0DE, "CreateWindowExW": 0x1234,
            "CreateCompatibleDC": 0x5678, "CreateDIBSection": self._dib, "SelectObject": 0x9999,
            "GetMessageW": 1, "DwmFlush": 0, "MsgWaitForMultipleObjectsEx": 0x102, "MonitorFromPoint": 0xAAAA,
            "GetMonitorInfoW": self._monitor, "GetDpiForMonitor": self._dpi, "PostQuitMessage": None,
            "SHQueryUserNotificationState": self._quns, "GetCurrentProcess": 0xFFFF, "GetGuiResources": 3,
            "ShowWindow": 0, "IsWindowVisible": 0,
        }
        self.dpi, self.quns = 144, 5
        for attribute in ("u", "g", "k", "d", "s", "sh"):
            setattr(self, attribute, FakeDll(self))

    def last_error(self):
        return self.error

    def names(self):
        return [name for name, _args in self.calls]

    def args(self, name):
        matches = [args for n, args in self.calls if n == name]
        return matches[-1] if matches else None

    def _dib(self, hdc, bmi, usage, bits, section, offset):
        header = bmi._obj.bmiHeader
        size = header.biWidth * -header.biHeight * 4
        buffer = (C.c_ubyte * size)()
        C.memset(buffer, 0xAB, size)                   # CreateDIBSection makes no zero promise
        self.dibs.append((buffer, header.biWidth, header.biHeight, header.biBitCount, header.biPlanes,
                          header.biCompression, header.biSize))
        bits._obj.value = C.addressof(buffer)
        return 0xD1B0 + len(self.dibs)

    def _monitor(self, monitor, info):
        work = info._obj.rcWork
        work.left, work.top, work.right, work.bottom = 0, 0, 2560, 1400
        return 1

    def _dpi(self, monitor, kind, x, y):
        x._obj.value = y._obj.value = self.dpi
        return 0

    def _quns(self, state):
        state._obj.value = self.quns
        return 0

    def _peek(self, msg, hwnd, low, high, flags):
        if flags == ov.PM_NOREMOVE or not self.messages:
            return 0
        msg._obj.message = self.messages.pop(0)
        return 1


class Win32BackendLogicTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.log = QuietLog()
        self.backend = ov.Win32Backend(api=self.api, log=ov._Log(self.log))
        self.events = []
        self.addCleanup(ov._WINDOW_HANDLERS.clear)

    def create(self, size=(3, 2), position=(10, 20)):
        self.backend.prepare_thread()
        self.backend.create(self.events.append, position, size)

    def test_prepare_thread_sets_verified_pmv2_and_creates_the_queue(self):
        self.assertEqual(self.backend.prepare_thread(), 2)
        self.assertEqual(self.api.calls[0], ("SetThreadDpiAwarenessContext", (-4,)))
        self.assertEqual(self.api.args("GetAwarenessFromDpiAwarenessContext"), (0x22,))
        peek = self.api.args("PeekMessageW")
        self.assertEqual(peek[1:], (None, ov.WM_USER, ov.WM_USER, ov.PM_NOREMOVE))
        self.assertEqual(self.backend.thread_id, 4242)
        self.assertEqual(self.log.lines, [])

    def test_unverified_dpi_awareness_is_logged(self):
        self.api.behaviour["GetAwarenessFromDpiAwarenessContext"] = 1
        self.backend.prepare_thread()
        self.assertTrue(any("DPI awareness" in line for _level, line in self.log.lines))

    def test_create_registers_the_class_and_a_hidden_popup_with_a_double_width_dib(self):
        self.create(size=(40, 30), position=(24, 505))
        names = self.api.names()
        order = [names.index(n) for n in ("GetModuleHandleW", "RegisterClassExW", "CreateWindowExW",
                                          "CreateCompatibleDC", "CreateDIBSection", "SelectObject")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.api.args("GetModuleHandleW"), (None,))
        wc = self.api.args("RegisterClassExW")[0]._obj
        self.assertEqual((wc.cbSize, wc.style, wc.lpszClassName, wc.hInstance), (80, 0, "NanoD.KnobOverlay", 0x400000))
        self.assertEqual(C.cast(wc.lpfnWndProc, C.c_void_p).value, C.cast(ov._WNDPROC_THUNK, C.c_void_p).value)
        self.assertEqual(self.api.args("CreateWindowExW"),
                         (0x080800A8, "NanoD.KnobOverlay", "Desk Dial knob", 0x80000000, 24, 505, 40, 30,
                          None, None, 0x400000, None))
        buffer, width, height, bits, planes, compression, header_size = self.api.dibs[0]
        self.assertEqual((width, height, bits, planes, compression, header_size), (80, -30, 32, 1, 0, 40))
        self.assertEqual(bytes(buffer), bytes(len(buffer)))   # both halves cleared: right half transparent
        self.assertEqual(self.api.args("SelectObject"), (0x5678, 0xD1B1))
        self.assertIn(0x1234, ov._WINDOW_HANDLERS)
        self.assertNotIn("ShowWindow", names)
        self.assertNotIn("SetWindowPos", names)

    def test_class_already_exists_is_tolerated(self):
        self.api.behaviour["RegisterClassExW"] = 0
        self.api.error = ov.ERROR_CLASS_ALREADY_EXISTS
        self.create()
        self.assertEqual(self.backend.hwnd, 0x1234)
        self.assertTrue(self.backend.registered)

    def test_other_registration_errors_fail_creation(self):
        self.api.behaviour["RegisterClassExW"] = 0
        self.api.error = 5
        with self.assertRaises(ov.OverlayError):
            self.create()
        self.assertNotIn("CreateWindowExW", self.api.names())

    def test_window_creation_failure_cleans_up_partially(self):
        self.api.behaviour["CreateWindowExW"] = 0
        with self.assertRaises(ov.OverlayError):
            self.create()
        self.backend.destroy()
        names = self.api.names()
        self.assertIn("UnregisterClassW", names)
        self.assertNotIn("DestroyWindow", names)
        self.assertNotIn("DeleteDC", names)

    def test_dib_failure_fails_creation_and_frees_the_dc(self):
        self.api.behaviour["CreateDIBSection"] = 0
        with self.assertRaises(ov.OverlayError):
            self.create()
        self.backend.destroy()
        tail = [n for n in self.api.names() if n in ("DeleteObject", "DeleteDC", "DestroyWindow",
                                                        "UnregisterClassW")]
        self.assertEqual(tail, ["DeleteDC", "DestroyWindow", "UnregisterClassW"])

    def test_cleanup_runs_in_the_strict_order(self):
        self.create()
        self.backend.wait(0.25)                       # arms the timer
        del self.api.calls[:]
        self.backend.destroy_window()
        self.assertEqual([n for n in self.api.names() if n != "GdiFlush"],
                         ["KillTimer", "SelectObject", "DeleteObject", "DeleteDC", "DestroyWindow"])
        self.assertEqual(self.api.args("KillTimer"), (0x1234, ov.TIMER_ID))
        self.assertEqual(self.api.args("SelectObject"), (0x5678, 0x9999))
        self.assertEqual(self.api.args("DeleteObject"), (0xD1B1,))
        self.assertEqual(self.api.args("DeleteDC"), (0x5678,))
        self.assertEqual(self.api.args("DestroyWindow"), (0x1234,))
        self.assertNotIn(0x1234, ov._WINDOW_HANDLERS)
        self.assertFalse(self.backend.post(ov.WM_APP_FRAME))
        self.backend.unregister()
        self.assertEqual(self.api.names()[-1], "UnregisterClassW")
        self.assertEqual(self.api.args("UnregisterClassW"), ("NanoD.KnobOverlay", 0x400000))
        count = len(self.api.calls)
        self.backend.destroy()                        # idempotent
        self.assertEqual(len(self.api.calls), count)

    def test_wm_destroy_posts_quit(self):
        self.create()
        self.assertEqual(self.backend._on_message(ov.WM_DESTROY, 0, 0), 0)
        self.assertEqual(self.api.args("PostQuitMessage"), (0,))

    def test_resize_frees_the_old_dib_before_creating_the_new_one(self):
        self.create(size=(3, 2))
        del self.api.calls[:]
        self.backend.resize((5, 4))
        names = [n for n in self.api.names() if n != "GdiFlush"]
        self.assertEqual(names[:3], ["SelectObject", "DeleteObject", "CreateDIBSection"])
        self.assertEqual(self.api.dibs[-1][1:3], (10, -4))
        self.assertEqual(self.backend.size, (5, 4))
        del self.api.calls[:]
        self.backend.resize((5, 4))
        self.assertEqual(self.api.calls, [])

    def test_present_copies_rows_into_the_left_half_and_calls_ulw(self):
        self.create(size=(3, 2), position=(10, 20))
        frame = bytes(range(1, 25))
        self.assertTrue(self.backend.present(frame, (3, 2), (10, 20), 1, 128))
        buffer = bytes(self.api.dibs[0][0])
        self.assertEqual(buffer[0:12], frame[0:12])
        self.assertEqual(buffer[12:24], bytes(12))
        self.assertEqual(buffer[24:36], frame[12:24])
        self.assertEqual(buffer[36:48], bytes(12))
        args = self.api.args("UpdateLayeredWindow")
        self.assertEqual(args[0], 0x1234)
        self.assertIsNone(args[1])
        self.assertEqual((args[2]._obj.x, args[2]._obj.y), (10, 20))
        self.assertEqual((args[3]._obj.cx, args[3]._obj.cy), (3, 2))
        self.assertEqual(args[4], 0x5678)
        self.assertEqual((args[5]._obj.x, args[5]._obj.y), (1, 0))
        self.assertEqual(args[6], 0)
        blend = args[7]._obj
        self.assertEqual((blend.BlendOp, blend.BlendFlags, blend.SourceConstantAlpha, blend.AlphaFormat),
                         (0, 0, 128, 1))
        self.assertEqual(args[8], ov.ULW_ALPHA)
        flushes = self.api.names().count("GdiFlush")
        self.assertTrue(self.backend.present(frame, (3, 2), (10, 20), 3, 0))   # same frame: no re-upload
        self.assertEqual(self.api.names().count("GdiFlush"), flushes)
        self.assertEqual(self.api.args("UpdateLayeredWindow")[5]._obj.x, 3)

    def test_present_refuses_mismatched_frames(self):
        self.create(size=(3, 2))
        self.assertFalse(self.backend.present(bytes(20), (3, 2), (0, 0), 0, 255))
        self.assertFalse(self.backend.present(bytes(24), (4, 2), (0, 0), 0, 255))
        self.assertFalse(self.backend.present(bytearray(24), (3, 2), (0, 0), 0, 255))
        self.assertNotIn("UpdateLayeredWindow", self.api.names())

    def test_present_failure_returns_false_and_logs(self):
        self.create()
        self.api.behaviour["UpdateLayeredWindow"] = 0
        self.api.error = 87
        self.assertFalse(self.backend.present(bytes(24), (3, 2), (0, 0), 0, 255))
        self.assertTrue(any("UpdateLayeredWindow failed (error 87)" in line for _l, line in self.log.lines))
        self.assertFalse(self.backend.present(bytes(24), (3, 2), (0, 0), 0, 255))
        self.assertEqual(sum("UpdateLayeredWindow" in line for _l, line in self.log.lines), 1)  # rate limited

    def test_present_before_create_is_refused(self):
        self.assertFalse(self.backend.present(bytes(24), (3, 2), (0, 0), 0, 255))

    def test_show_is_topmost_and_never_activates(self):
        self.create()
        self.assertTrue(self.backend.show())
        hwnd, insert_after, x, y, cx, cy, flags = self.api.args("SetWindowPos")
        self.assertEqual((hwnd, insert_after, x, y, cx, cy), (0x1234, ov.HWND_TOPMOST, 0, 0, 0, 0))
        for flag in (ov.SWP_NOACTIVATE, ov.SWP_NOOWNERZORDER, ov.SWP_SHOWWINDOW, ov.SWP_NOMOVE, ov.SWP_NOSIZE):
            self.assertTrue(flags & flag)
        self.backend.hide()
        self.assertEqual(self.api.args("ShowWindow"), (0x1234, ov.SW_HIDE))

    def test_show_falls_back_to_sw_showna(self):
        self.create()
        self.api.behaviour["SetWindowPos"] = 0
        self.assertFalse(self.backend.show())
        self.assertEqual(self.api.args("ShowWindow"), (0x1234, ov.SW_SHOWNA))

    def test_window_messages(self):
        self.create()
        m = self.backend._on_message
        self.assertEqual(m(ov.WM_MOUSEACTIVATE, 0, 0), ov.MA_NOACTIVATE)
        self.assertEqual(m(ov.WM_NCHITTEST, 0, 0), ov.HTTRANSPARENT)
        for code, event in ov.POSTED_EVENTS.items():
            self.assertEqual(m(code, 0, 0), 0)
            self.assertEqual(self.events.pop(), event)
        for code in (ov.WM_DISPLAYCHANGE, ov.WM_DPICHANGED, ov.WM_DWMCOMPOSITIONCHANGED):
            self.assertEqual(m(code, 0, 0), 0)
            self.assertEqual(self.events.pop(), ov.EV_DIRTY)
        self.assertIsNone(m(ov.WM_SETTINGCHANGE, ov.SPI_SETWORKAREA, 0))
        self.assertEqual(self.events.pop(), ov.EV_DIRTY)
        self.assertIsNone(m(ov.WM_SETTINGCHANGE, 0x0072, 0))
        self.assertEqual(self.events, [])
        self.assertEqual(m(ov.WM_POWERBROADCAST, ov.PBT_APMSUSPEND, 0), 1)
        self.assertEqual(self.events.pop(), ov.EV_HIDE)
        self.assertEqual(m(ov.WM_POWERBROADCAST, ov.PBT_APMRESUMEAUTOMATIC, 0), 1)
        self.assertEqual(self.events.pop(), ov.EV_DIRTY)
        self.assertEqual(m(ov.WM_ENDSESSION, 1, 0), 0)
        self.assertEqual(self.events.pop(), ov.EV_HIDE)
        self.assertEqual(m(ov.WM_ENDSESSION, 0, 0), 0)
        self.assertEqual(self.events, [])
        self.assertEqual(m(ov.WM_TIMER, ov.TIMER_ID, 0), 0)
        self.assertEqual(self.events.pop(), ov.EV_TIMER)
        self.assertIsNone(m(ov.WM_TIMER, 99, 0))
        self.assertEqual(m(ov.WM_CLOSE, 0, 0), 0)
        self.assertNotIn("DestroyWindow", self.api.names())
        self.assertIsNone(m(0x0005, 0, 0))                # anything else -> DefWindowProcW
        self.assertEqual(self.events, [])

    def test_wait_arms_the_timer_and_blocks_in_getmessage(self):
        self.create()
        self.assertTrue(self.backend.wait(0.25))
        self.assertEqual(self.api.args("SetTimer"), (0x1234, ov.TIMER_ID, 250, None))
        self.assertEqual(self.api.names()[-3:], ["GetMessageW", "TranslateMessage", "DispatchMessageW"])
        self.assertEqual(self.api.args("GetMessageW")[1:], (None, 0, 0))
        self.backend.wait(0.0001)
        self.assertEqual(self.api.args("SetTimer")[2], ov.USER_TIMER_MINIMUM_MS)
        del self.api.calls[:]
        self.backend.wait(None)
        self.assertEqual(self.api.names()[:2], ["KillTimer", "GetMessageW"])
        self.api.behaviour["GetMessageW"] = 0
        self.assertFalse(self.backend.wait(None))     # WM_QUIT
        self.api.behaviour["GetMessageW"] = -1
        self.assertFalse(self.backend.wait(None))     # error: leave the loop, never spin

    def test_wait_without_a_timer_falls_back_to_a_bounded_wait(self):
        self.create()
        self.api.behaviour["SetTimer"] = 0
        self.assertTrue(self.backend.wait(0.05))
        self.assertEqual(self.api.args("MsgWaitForMultipleObjectsEx"),
                         (0, None, 50, ov.QS_ALLINPUT, ov.MWMO_INPUTAVAILABLE))
        self.assertNotIn("GetMessageW", self.api.names())

    def test_pace_uses_dwmflush_and_falls_back_without_spinning(self):
        self.create()
        self.api.behaviour["DwmFlush"] = lambda: (time.sleep(0.002), 0)[1]
        self.backend.pace()
        self.backend.pace()
        self.assertNotIn("MsgWaitForMultipleObjectsEx", self.api.names())
        self.api.behaviour["DwmFlush"] = -2147024891                        # E_ACCESSDENIED
        self.backend.pace()
        self.assertEqual(self.api.args("MsgWaitForMultipleObjectsEx"),
                         (0, None, ov.PACE_FALLBACK_MS, ov.QS_ALLINPUT, ov.MWMO_INPUTAVAILABLE))
        del self.api.calls[:]
        self.api.behaviour["DwmFlush"] = 0                                  # instant success: not pacing
        self.backend.pace()
        self.assertNotIn("MsgWaitForMultipleObjectsEx", self.api.names())
        self.backend.pace()
        self.assertIn("MsgWaitForMultipleObjectsEx", self.api.names())

    def test_pace_kills_an_armed_timer(self):
        self.create()
        self.backend.wait(0.5)
        self.backend.pace()
        self.assertIn("KillTimer", self.api.names())

    def test_pump_dispatches_until_quit(self):
        self.create()
        self.api.messages = [ov.WM_APP_FRAME, ov.WM_TIMER]
        self.assertTrue(self.backend.pump())
        self.assertEqual(self.api.names().count("DispatchMessageW"), 2)
        self.api.messages = [ov.WM_APP_FRAME, ov.WM_QUIT, ov.WM_APP_TOUCH]
        self.assertFalse(self.backend.pump())
        peek = self.api.args("PeekMessageW")
        self.assertEqual(peek[1:], (None, 0, 0, ov.PM_REMOVE))

    def test_geometry_reads_the_primary_work_area_and_effective_dpi(self):
        geometry = self.backend.geometry()
        self.assertEqual(geometry, ov.Geometry((0, 0, 2560, 1400), 144))
        point, flags = self.api.args("MonitorFromPoint")
        self.assertEqual((point.x, point.y, flags), (0, 0, ov.MONITOR_DEFAULTTOPRIMARY))
        self.assertEqual(self.api.args("GetDpiForMonitor")[:2], (0xAAAA, ov.MDT_EFFECTIVE_DPI))
        self.api.behaviour["GetDpiForMonitor"] = 0x80070057
        self.assertEqual(self.backend.geometry().dpi, 96)
        self.api.behaviour["GetMonitorInfoW"] = 0
        with self.assertRaises(ov.OverlayError):
            self.backend.geometry()

    def test_notification_state_and_gui_resources(self):
        self.api.quns = 3
        self.assertEqual(self.backend.notification_state(), 3)
        self.api.behaviour["SHQueryUserNotificationState"] = 0x80004005
        self.assertIsNone(self.backend.notification_state())
        self.assertEqual(self.backend.gui_resources(), (3, 3))
        self.assertEqual([args[1] for name, args in self.api.calls if name == "GetGuiResources"],
                         [ov.GR_GDIOBJECTS, ov.GR_USEROBJECTS])

    def test_post_and_post_quit(self):
        self.assertFalse(self.backend.post(ov.WM_APP_FRAME))     # no window yet
        self.assertFalse(self.backend.post_quit())               # no thread yet
        self.create()
        self.assertTrue(self.backend.post(ov.WM_APP_TOUCH))
        self.assertEqual(self.api.args("PostMessageW"), (0x1234, ov.WM_APP_TOUCH, 0, 0))
        self.assertTrue(self.backend.post_quit())
        self.assertEqual(self.api.args("PostThreadMessageW"), (4242, ov.WM_QUIT, 0, 0))


class WindowProcedureTests(unittest.TestCase):
    def setUp(self):
        self.saved = ov._DEF_WINDOW_PROC
        self.defaults = []

        def default(hwnd, message, wparam, lparam):
            self.defaults.append((hwnd, message))
            return 77

        ov._DEF_WINDOW_PROC = default
        self.addCleanup(self.restore)

    def restore(self):
        ov._DEF_WINDOW_PROC = self.saved
        ov._WINDOW_HANDLERS.pop(0xBEEF, None)

    def test_handled_messages_return_the_handler_result(self):
        ov._WINDOW_HANDLERS[0xBEEF] = lambda message, wparam, lparam: 3
        self.assertEqual(ov._window_procedure(0xBEEF, ov.WM_MOUSEACTIVATE, 0, 0), 3)
        self.assertEqual(self.defaults, [])

    def test_unhandled_and_unknown_windows_fall_back_to_defwindowproc(self):
        ov._WINDOW_HANDLERS[0xBEEF] = lambda message, wparam, lparam: None
        self.assertEqual(ov._window_procedure(0xBEEF, 0x0005, 0, 0), 77)
        self.assertEqual(ov._window_procedure(0xF00D, 0x0081, 0, 0), 77)   # e.g. WM_NCCREATE before registration
        self.assertEqual(len(self.defaults), 2)

    def test_exceptions_never_escape(self):
        def broken(message, wparam, lparam):
            raise KeyboardInterrupt()
        ov._WINDOW_HANDLERS[0xBEEF] = broken
        self.assertEqual(ov._window_procedure(0xBEEF, 0x0005, 0, 0), 77)
        ov._DEF_WINDOW_PROC = lambda *a: (_ for _ in ()).throw(SystemExit())
        self.assertEqual(ov._window_procedure(0xBEEF, 0x0005, 0, 0), 0)

    # The real WINFUNCTYPE thunk, called through its C function pointer (no window):
    # the ctypes argument and LRESULT conversions and the hwnd-as-int lookup.
    def thunk_backend(self):
        api = FakeApi()
        backend = ov.Win32Backend(api=api, log=ov._Log(QuietLog()))
        events = []
        backend.prepare_thread()
        backend.create(events.append, (0, 0), (3, 2))
        self.addCleanup(ov._WINDOW_HANDLERS.pop, 0x1234, None)
        return backend, events

    def test_thunk_returns_the_backend_answers_as_lresult(self):
        backend, events = self.thunk_backend()
        thunk = ov._WNDPROC_THUNK
        self.assertEqual(thunk(0x1234, ov.WM_NCHITTEST, 0, 0), -1)          # HTTRANSPARENT, sign kept
        self.assertEqual(thunk(0x1234, ov.WM_MOUSEACTIVATE, 0, 0), ov.MA_NOACTIVATE)
        self.assertEqual(thunk(0x1234, ov.WM_APP_FRAME, 0, 0), 0)
        self.assertEqual(events, [ov.EV_FRAME])
        self.assertEqual(thunk(0x1234, ov.WM_POWERBROADCAST, ov.PBT_APMSUSPEND, 0), 1)
        self.assertEqual(events[-1], ov.EV_HIDE)
        self.assertEqual(self.defaults, [])
        self.assertEqual(thunk(0x1234, 0x0005, 0, 0), 77)                   # unhandled -> DefWindowProcW
        self.assertEqual(self.defaults, [(0x1234, 0x0005)])

    def test_thunk_falls_back_for_null_unknown_and_failing_windows(self):
        self.assertEqual(ov._WNDPROC_THUNK(None, ov.WM_NCHITTEST, 0, 0), 77)     # NULL hwnd arrives as None
        self.assertEqual(ov._WNDPROC_THUNK(0xF00D, ov.WM_NCHITTEST, 0, 0), 77)   # not registered
        self.assertEqual(self.defaults, [(None, ov.WM_NCHITTEST), (0xF00D, ov.WM_NCHITTEST)])

        def broken(message, wparam, lparam):
            raise RuntimeError("handler bug")
        ov._WINDOW_HANDLERS[0xBEEF] = broken
        self.assertEqual(ov._WNDPROC_THUNK(0xBEEF, ov.WM_NCHITTEST, 0, 0), 77)
        ov._DEF_WINDOW_PROC = lambda *a: (_ for _ in ()).throw(SystemExit())
        self.assertEqual(ov._WNDPROC_THUNK(0xBEEF, ov.WM_NCHITTEST, 0, 0), 0)

    @unittest.skipUnless(X64, "64-bit WPARAM/LPARAM")
    def test_thunk_preserves_full_width_wparam_and_signed_lparam(self):
        seen = []
        ov._WINDOW_HANDLERS[0xBEEF] = lambda message, wparam, lparam: seen.append((wparam, lparam)) or -2
        self.assertEqual(ov._WNDPROC_THUNK(0xBEEF, ov.WM_APP_TOUCH, 2 ** 64 - 1, -2), -2)
        self.assertEqual(seen, [(2 ** 64 - 1, -2)])
        big = 2 ** 40 + 5                                                    # an hwnd beyond 32 bits
        ov._WINDOW_HANDLERS[big] = lambda message, wparam, lparam: 9
        try:
            self.assertEqual(ov._WNDPROC_THUNK(big, ov.WM_APP_TOUCH, 0, 0), 9)
        finally:
            ov._WINDOW_HANDLERS.pop(big, None)

    def test_thunk_is_module_level_with_an_lresult_signature(self):
        self.assertIsInstance(ov._WNDPROC_THUNK, ov.WNDPROC)
        self.assertIn(ov._WNDPROC_THUNK, ov._KEPT_ALIVE)
        self.assertIs(ov.WNDPROC._restype_, C.c_ssize_t)
        self.assertEqual(ov.WNDPROC._argtypes_, (C.c_void_p, C.c_uint32, C.c_size_t, C.c_ssize_t))


# ================================================= declarations and source
class DeclarationTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(ov.OVERLAY_EX_STYLE, 0x080800A8)
        self.assertEqual(ov.OVERLAY_STYLE, 0x80000000)
        self.assertEqual(ov.OVERLAY_STYLE & ov.WS_VISIBLE, 0)
        self.assertEqual((ov.WM_APP_FRAME, ov.WM_APP_TOUCH, ov.WM_APP_STOP), (0x8001, 0x8002, 0x8003))
        self.assertEqual((ov.MA_NOACTIVATE, ov.HTTRANSPARENT, ov.SW_HIDE, ov.SW_SHOWNA), (3, -1, 0, 8))
        self.assertEqual((ov.SWP_NOSIZE, ov.SWP_NOMOVE, ov.SWP_NOACTIVATE, ov.SWP_SHOWWINDOW,
                          ov.SWP_NOOWNERZORDER), (0x1, 0x2, 0x10, 0x40, 0x200))
        self.assertEqual((ov.ULW_ALPHA, ov.AC_SRC_OVER, ov.AC_SRC_ALPHA), (2, 0, 1))
        self.assertEqual(ov.ERROR_CLASS_ALREADY_EXISTS, 1410)
        self.assertEqual(ov.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, -4)
        self.assertEqual((ov.WM_DISPLAYCHANGE, ov.WM_SETTINGCHANGE, ov.WM_DPICHANGED, ov.WM_DWMCOMPOSITIONCHANGED),
                         (0x7E, 0x1A, 0x2E0, 0x31E))
        self.assertEqual((ov.WM_POWERBROADCAST, ov.PBT_APMSUSPEND, ov.WM_ENDSESSION, ov.SPI_SETWORKAREA),
                         (0x218, 4, 0x16, 0x2F))
        self.assertEqual((ov.WM_MOUSEACTIVATE, ov.WM_NCHITTEST, ov.WM_DESTROY, ov.WM_QUIT, ov.WM_TIMER),
                         (0x21, 0x84, 0x2, 0x12, 0x113))
        self.assertEqual((ov.QS_ALLINPUT, ov.MWMO_INPUTAVAILABLE, ov.PACE_FALLBACK_MS), (0x4FF, 4, 8))
        self.assertEqual((ov.MONITOR_DEFAULTTOPRIMARY, ov.MDT_EFFECTIVE_DPI), (1, 0))
        self.assertEqual((ov.GR_GDIOBJECTS, ov.GR_USEROBJECTS), (0, 1))
        self.assertEqual(ov.FULLSCREEN_NOTIFICATION_STATES, {3, 4})
        self.assertEqual((ov.CLASS_NAME, ov.THREAD_NAME), ("NanoD.KnobOverlay", "NanoD-overlay"))
        self.assertEqual((ov.START_TIMEOUT_SECONDS, ov.CLOSE_TIMEOUT_SECONDS), (2.0, 1.0))

    @unittest.skipUnless(X64, "x64 layout")
    def test_structure_sizes_x64(self):
        for structure, size in ov.STRUCTURE_SIZES_X64.items():
            self.assertEqual(C.sizeof(structure), size, structure.__name__)

    @unittest.skipUnless(WINDOWS, "Win32 exports")
    def test_declarations_resolve_with_64_bit_types(self):
        api = ov.OverlayApi()            # resolves exports; calls nothing
        for attribute, name, result, args in ov.DECLARATIONS:
            function = getattr(getattr(api, attribute), name)
            self.assertIs(function.restype, result, name)
            self.assertEqual(tuple(function.argtypes), tuple(args), name)
        u, g = api.u, api.g
        handle = C.c_void_p
        self.assertIs(u.DefWindowProcW.restype, C.c_ssize_t)
        self.assertIs(u.DispatchMessageW.restype, C.c_ssize_t)
        self.assertEqual(tuple(u.DefWindowProcW.argtypes), (handle, C.c_uint32, C.c_size_t, C.c_ssize_t))
        self.assertEqual(tuple(u.PostMessageW.argtypes), (handle, C.c_uint32, C.c_size_t, C.c_ssize_t))
        self.assertIs(u.CreateWindowExW.restype, handle)
        self.assertEqual(len(u.CreateWindowExW.argtypes), 12)
        self.assertIs(u.MonitorFromPoint.argtypes[0], ov.POINT)            # by value
        self.assertIs(u.SetThreadDpiAwarenessContext.restype, handle)
        self.assertIs(u.SetTimer.restype, C.c_size_t)
        self.assertEqual(len(u.UpdateLayeredWindow.argtypes), 9)
        self.assertIs(g.CreateDIBSection.restype, handle)
        self.assertIs(g.SelectObject.restype, handle)
        self.assertIs(api.d.DwmFlush.restype, C.c_int32)
        self.assertIs(u.RegisterClassExW.restype, C.c_uint16)
        self.assertIs(u.GetMessageW.restype, C.c_int32)

    def test_no_forbidden_call_or_declaration(self):
        forbidden = {"SetForegroundWindow", "SetActiveWindow", "BringWindowToTop", "SetLayeredWindowAttributes",
                     "SendMessageW", "SendMessageA", "SendMessageTimeoutW", "SetWindowLongPtrW"}
        self.assertFalse(forbidden & {name for _attr, name, _r, _a in ov.DECLARATIONS})
        source = Path(ov.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called, show_arguments, imports = set(), [], set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                called.add(name)
                if name == "ShowWindow":
                    show_arguments.append(ast.unparse(node.args[1]))
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
        self.assertFalse(forbidden & called)
        self.assertEqual(sorted(set(show_arguments)), ["SW_HIDE", "SW_SHOWNA"])
        for token in ("SW_SHOWNORMAL", "SW_SHOWDEFAULT", "SW_SHOW ", "SW_SHOW)", "SW_SHOW,"):
            self.assertNotIn(token, source)
        self.assertFalse({name for name in imports if name and "tkinter" in name})
        self.assertIn("SWP_NOACTIVATE", ast.unparse(tree).split("SHOW_FLAGS =")[1].split("\n")[0])

    def test_premultiplied_bgra_matches_the_reference(self):
        rng = random.Random(7)
        image = Image.new("RGBA", (37, 23))
        image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.randrange(256))
                       for _ in range(37 * 23)])
        image.putpixel((0, 0), (255, 128, 0, 128))

        def muldiv(v, a):
            t = v * a + 128
            return (t + (t >> 8)) >> 8

        reference = bytearray()
        for r, g, b, a in image.getdata():
            reference += bytes((muldiv(b, a), muldiv(g, a), muldiv(r, a), a))
        _factory, to_bgra, _scaler = ov._face_support(None)     # what the overlay uploads
        self.assertEqual(to_bgra(image), bytes(reference))
        self.assertEqual(list(to_bgra(image)[:4]), [0, 64, 128, 128])
        self.assertEqual(to_bgra(image.convert("RGB"))[3], 255)

    def test_scene_shape(self):
        self.assertEqual(OverlayScene._fields, ("lcd_key", "lcd", "ring"))
        self.assertEqual(len(BLANK_RING), 60)
        self.assertEqual(BLANK_RING[0], (0x1F, 0x1F, 0x1F, 0.0))


if __name__ == "__main__":
    unittest.main()

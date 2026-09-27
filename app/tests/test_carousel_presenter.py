"""CarouselPresenter protocol tests (the v7 window picker: DESKTOP_STAGE.md sections 9, 10, 5; CAROUSEL.md
sections 1, 5, 11 and 12) with a fake backend, a fake NanoD-snap worker and a fake clock: no window, no
Win32, no Tk. The presenter runs inline (its engine is stepped on the test thread) except for the
threaded handshake tests, whose fake backend is a queue.

Ported invariants of the retired PickerOverlay tests:
- ThumbnailLifecycleTests: registration happens on a detent (far -> near), never per frame; a
  failed registration is never retried; closed, off-screen and hidden cards are released.
- OverlayDismissalTests: nothing registers or draws after hide (an exit animation, when one
  was requested, ends with the release <= 420 ms) or close; thumbnails go before the windows;
  close is idempotent and releases at once; show after close raises.
- PickerIconTests: no icon work in the WM_HOTKEY/focus path: set_icons only records, and the
  carousel thread's icon work starts after the show() handshake was published.
"""
from pathlib import Path
import queue
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from control_center import carousel as c  # noqa: E402
from control_center import carousel_render as R  # noqa: E402

MONITOR = (0, 0, 1280, 720)          # k = 1: pane (70, 92, 1140, 560); the host is rcMonitor
WORK = (0, 0, 1280, 672)
PANE = (70, 92, 1140, 560)
SHIFT = R.GROUP_SHIFT                # the cards group before the tray shows


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeBackend:
    """Records every call the engine makes; posted messages are queued and dispatched by pump()."""

    def __init__(self, monitor=MONITOR, work=WORK, host_mode=c.HOST_LAYERED, fail_register=(), sizes=None,
                 show_ok=True, fail_unregister=()):
        self.monitor = monitor
        self.work = work
        self.host_mode = host_mode
        self.fail_register = set(fail_register)
        self.fail_unregister = set(fail_unregister)
        self.sizes = dict(sizes or {})
        self.show_ok = show_ok
        self.calls = []
        self.queue = []
        self.visible = set()
        self.affinity = {}
        self.thumbs = {}                 # handle -> source hwnd
        self.props = {}                  # handle -> the last (dest, source, opacity, visible)
        self.next_handle = 1000
        self.chrome = None
        self.layers = {}
        self.layer_state = {}            # role -> (alpha, pos)
        self.toast = None
        self.dim = None
        self.glass_image = None
        self.glass_rect = None
        self.host_image = None
        self.hwnd_host = 0x5001
        self.on_event = self.on_input = None
        self.destroyed = False
        self.fail_layered = False
        self.clock = None                # the harness clock: unregister times
        self.release_times = []
        self.excluded = set()            # windows of this process kept out of the capture
        self.busy = False                # SHQueryUserNotificationState 3 or 4
        self.dirty = []                  # the chrome's B5 dirty rects
        self.reduced = False

    @property
    def host_hwnd(self):
        return self.hwnd_host

    def log(self, *entry):
        self.calls.append(entry)

    def names(self):
        return [entry[0] for entry in self.calls]

    # thread + loop
    def prepare_thread(self):
        return 2

    def create(self, on_event, on_input):
        self.on_event, self.on_input = on_event, on_input
        self.log("create")
        return self.hwnd_host

    def post(self, code):
        if self.destroyed:
            return False
        self.queue.append(code)
        return True

    def post_quit(self):
        return True

    def pump(self):
        while self.queue:
            code = self.queue.pop(0)
            if self.on_event is not None:
                self.on_event(c.POSTED_EVENTS[code])
        return True

    def wait(self, timeout):
        self.log("wait", timeout)
        return True

    def pace(self):
        self.log("pace")
        return "tick"

    # geometry + host
    def monitor_info(self, origin):
        self.log("monitor_rect", origin)
        return self.monitor, self.work

    def system_reduced_motion(self):
        return self.reduced

    def notification_busy(self):
        return self.busy

    def show_host(self, rect):
        self.log("show_host", tuple(rect))
        if self.show_ok:
            self.visible.add("host")
        return self.show_ok

    def set_host_passive(self, passive):
        self.log("passive", bool(passive))

    def refocus_host(self):
        self.log("refocus_host")
        return True

    def host_paint(self, image):
        self.log("host_paint", image.size)
        self.host_image = image

    def set_affinity(self, exclude):
        self.log("affinity", bool(exclude))
        for role in ("dim", "glass", "host", "chrome", "label", "dots"):
            self.affinity[role] = bool(exclude)
        return True

    def set_toast_affinity(self, exclude):
        self.log("toast_affinity", bool(exclude))
        self.affinity["toast"] = bool(exclude)
        return True

    def set_capture_exclusions(self, hwnds, exclude):
        self.log("exclusions", tuple(hwnds), bool(exclude))
        for hwnd in hwnds:
            (self.excluded.add if exclude else self.excluded.discard)(hwnd)
        return True

    # layers
    def chrome_alloc(self, rect):
        self.log("chrome_alloc", tuple(rect))
        self.chrome = R.Canvas.new(rect[2:])
        return self.chrome

    def chrome_canvas(self):
        return self.chrome

    def chrome_present(self, dirty=None):
        self.log("chrome_present")
        self.dirty.append(dirty)
        return True

    def chrome_show(self):
        self.log("show", "chrome")
        self.visible.add("chrome")

    def chrome_free(self):
        self.log("chrome_free")
        self.chrome = None

    def layer_alloc(self, role, rect):
        self.log("layer_alloc", role, tuple(rect))
        self.layers[role] = R.Canvas.new(rect[2:])
        return self.layers[role]

    def layer_canvas(self, role):
        return self.layers.get(role)

    def layer_present(self, role, alpha, pos=None):
        self.log("layer_present", role, alpha, pos)
        self.layer_state[role] = (alpha, pos)

    def layer_alpha(self, role, alpha, pos=None):
        self.log("layer_alpha", role, alpha, pos)
        self.layer_state[role] = (alpha, pos)

    def layer_show(self, role):
        self.log("show", role)
        self.visible.add(role)

    def layer_free(self, role):
        self.log("layer_free", role)
        self.layers.pop(role, None)

    def dim_upload(self, layout, background):
        self.log("dim_upload", background)
        self.dim = background

    def dim_show(self):
        self.log("show", "dim")
        self.visible.add("dim")

    def dim_alpha(self, alpha):
        self.log("dim_alpha", alpha)

    def glass_upload(self, rect, image):
        self.log("glass_upload", tuple(rect))
        self.glass_rect, self.glass_image = tuple(rect), image
        self.visible.add("glass")

    def glass_alpha(self, alpha):
        self.log("glass_alpha", alpha)

    def toast_alloc(self, rect):
        self.log("toast_alloc", tuple(rect))
        self.toast = R.Canvas.new(rect[2:])
        return self.toast

    def toast_canvas(self):
        return self.toast

    def toast_present(self, alpha):
        self.log("toast_present", alpha)

    def toast_show(self):
        self.log("show", "toast")
        self.visible.add("toast")

    def toast_hide(self):
        self.log("hide", "toast")
        self.visible.discard("toast")

    def toast_free(self):
        self.log("toast_free")
        self.toast = None

    def hide_layers(self):
        for role in ("chrome", "label", "dots", "host", "glass", "dim"):
            self.log("hide", role)
            self.visible.discard(role)

    def free_large(self):
        self.log("free_large")

    def use_plain_host(self):
        self.log("use_plain_host")
        self.host_mode = c.HOST_PLAIN
        self.hwnd_host = 0x5002

    def use_layered_host(self):
        self.log("use_layered_host")
        if self.fail_layered:
            self.host_mode = c.HOST_PLAIN
            self.hwnd_host = 0x5004
            return False
        self.host_mode = c.HOST_LAYERED
        self.hwnd_host = 0x5003
        return True

    def activate(self):
        """What the adapter's native.focus(host) causes: the host's WM_ACTIVATE posts
        WM_APP_ACTIVATED to the carousel thread's queue."""
        self.log("activated")
        return self.post(c.WM_APP_ACTIVATED)

    # thumbnails
    def register(self, hwnd):
        self.log("register", hwnd)
        if hwnd in self.fail_register:
            return None
        self.next_handle += 1
        self.thumbs[self.next_handle] = hwnd
        return self.next_handle

    def source_size(self, handle):
        self.log("source_size", self.thumbs.get(handle))
        return self.sizes.get(self.thumbs.get(handle), (1600, 1000))

    def update_thumbnail(self, handle, dest, source, opacity, visible):
        self.log("update", self.thumbs.get(handle), tuple(dest), tuple(source), opacity, visible)
        self.props[handle] = (tuple(dest), tuple(source), opacity, visible)
        return True

    def unregister(self, handle):
        self.log("unregister", self.thumbs.get(handle))
        if self.clock is not None:
            self.release_times.append(self.clock())
        hwnd = self.thumbs.pop(handle, None)
        self.props.pop(handle, None)
        if hwnd in self.fail_unregister:
            raise OSError("dwm")

    # capture + teardown
    def prepare_capture_thread(self):
        pass

    def flush(self):
        return 0

    def capture(self, rect):
        return Image.new("RGB", tuple(rect[2:]), (90, 110, 140))

    def destroy_windows(self):
        self.log("destroy_windows")
        self.destroyed = True
        self.visible.clear()

    def unregister_classes(self):
        self.log("unregister_classes")

    def destroy(self):
        self.destroy_windows()
        self.unregister_classes()

    def gui_resources(self):
        return (0, 0)


class FakeCapture:
    def __init__(self, backend=None):
        self.backend = backend
        self.jobs = []
        self.results = []
        self.closed = False

    def submit(self, job):
        self.jobs.append(job)
        return True

    def take_results(self):
        results, self.results = self.results, []
        return results

    def complete(self, image=None, error=None):
        job = self.jobs.pop(0)
        if image is None and error is None:
            size = tuple(job.rect[2:])
            image = R.frost_canvas(Image.new("RGB", size, (80, 90, 100)), job.k) if job.kind == "frost" else \
                Image.new("RGB", size, (80, 90, 100))
        self.results.append(c.CaptureResult(job.gen, job.kind, image, 1.0, 1.0, error))
        self.backend.post(c.WM_APP_CAPTURED)
        return job

    def close(self, timeout=None):
        self.closed = True
        return True


class FakeSnap:
    """A NanoD-snap stand-in: records the jobs; the test answers them (``answer``)."""

    def __init__(self):
        self.jobs = []
        self.results = []
        self.closed = False
        self.backend = None

    def submit(self, job):
        if self.closed:
            return False
        self.jobs.append(job)
        return True

    def take_results(self):
        results, self.results = self.results, []
        return results

    def answer(self, job, stage, outcome, info=None):
        if stage == "precheck" and outcome == "accepted":
            job.accepted = True
        elif not job.resolve(outcome, "worker"):
            return False
        self.results.append((job, stage, outcome, dict(info or {})))
        if self.backend is not None:
            self.backend.post(c.WM_APP_SNAP)
        return True

    def close(self, timeout=None):
        self.closed = True
        return True


def items(count=7, changes=None):
    out = []
    for i in range(count):
        item = {"id": f"w{i}", "hwnd": 100 + i, "pid": 20, "app": f"app{i}", "title": f"Window {i}",
                "available": True, "minimized": False}
        item.update((changes or {}).get(i, {}))
        out.append(item)
    return out


def snapshot(count=7, index=1, changes=None, origin=100):
    return {"items": items(count, changes), "index": index, "origin": {"hwnd": origin, "pid": 20}}


class Harness(unittest.TestCase):
    def make(self, **backend_args):
        self.clock = Clock()
        self.backend = FakeBackend(**backend_args)
        self.backend.clock = self.clock
        self.capture = FakeCapture(self.backend)
        self.snapper = FakeSnap()
        self.snapper.backend = self.backend
        self.presenter = c.CarouselPresenter(None, None, lambda: None, backend=self.backend, capture=self.capture,
                                             snap=self.snapper, clock=self.clock, inline=True)
        self.addCleanup(self.presenter.close)
        return self.presenter

    def step(self, seconds=0.0, dt=1 / 60):
        """Advance the fake clock by ``seconds`` in frames, stepping the engine each frame."""
        end = self.clock.t + seconds
        self.presenter._step_inline()
        while self.clock.t < end - 1e-9:
            self.clock.t = min(end, self.clock.t + dt)
            self.presenter._step_inline()

    def open(self, snap=None, glass=True):
        snap = snap or snapshot()
        self.presenter.show(snap)
        self.backend.activate()               # the adapter's native.focus(host) after the handshake
        self.step()
        if glass and self.capture.jobs:
            self.capture.complete()
            self.step()
        return snap

    def registered(self):
        return set(self.backend.thumbs.values())

    def calls_since(self, mark):
        return self.backend.calls[mark:]

    def events(self):
        return self.presenter.take_events()

    def layout(self):
        return R.layout_for(self.backend.monitor, self.backend.work)


class HandshakeTests(Harness):
    def test_show_returns_with_the_host_visible_activatable_on_rcmonitor_and_the_pane_rect(self):
        p = self.make()
        self.assertEqual(p.hwnd, 0x5001)
        self.assertIsNone(p.rect)
        p.show(snapshot())
        self.assertIn("host", self.backend.visible)
        self.assertEqual(p.rect, PANE, "rect still reports the stage's card area")
        self.assertTrue(p.visible)
        names = self.backend.names()
        self.assertEqual(self.backend.calls[names.index("monitor_rect")], ("monitor_rect", 100))
        self.assertEqual(self.backend.calls[names.index("show_host")], ("show_host", (0, 0, 1280, 720)))   # K4 9.2
        self.assertNotIn("chrome_alloc", names)            # the heavy setup waits for the activation
        self.backend.activate()
        self.step()
        names = self.backend.names()
        self.assertLess(names.index("show_host"), names.index("activated"))
        self.assertLess(names.index("activated"), names.index("chrome_alloc"))
        self.assertEqual(p.half_rect("left"), (0, 0, 640, 672))
        self.assertEqual(p.half_rect("right"), (640, 0, 1280, 672))

    def test_a_host_that_cannot_be_shown_raises_the_oserror_path(self):
        p = self.make(show_ok=False)
        with self.assertRaises(OSError):
            p.show(snapshot())
        self.assertFalse(p.visible)
        self.assertIsNone(p.rect)
        self.backend.show_ok = True
        p.show(snapshot())
        self.assertEqual(p.rect, PANE)

    def test_show_after_close_raises_and_close_is_idempotent(self):
        p = self.make()
        self.open()
        self.assertTrue(p.close())
        self.assertTrue(p.close())
        self.assertEqual(self.backend.names().count("destroy_windows"), 2)   # engine stop + backend.destroy
        with self.assertRaises(RuntimeError):
            p.show(snapshot())
        for call in (lambda: p.highlight(2), lambda: p.set_icons({"w1": None}), lambda: p.hide(),
                     lambda: p.play_switch_exit(), lambda: p.focus_local(), lambda: p.toast("x")):
            call()
        self.assertTrue(self.capture.closed)
        self.assertTrue(self.snapper.closed)

    def test_disabled_presenter_raises_on_show(self):
        class Broken(FakeBackend):
            def create(self, on_event, on_input):
                raise OSError("no windows")
        self.clock = Clock()
        p = c.CarouselPresenter(None, None, None, backend=Broken(), capture=FakeCapture(), clock=self.clock,
                                inline=True)
        self.assertTrue(p.disabled)
        self.assertIn("no windows", p.last_error)
        self.assertEqual(p.hwnd, 0)
        with self.assertRaises(OSError):
            p.show(snapshot())
        self.assertFalse(p.toast("x"))
        p.close()


class ActivationTests(Harness):
    """After the handshake the carousel thread must read its queue at once: the adapter's
    SetForegroundWindow(host) completes only then (CarouselEngine._open)."""

    def heavy(self):
        return [n for n in self.backend.names() if n in ("chrome_alloc", "layer_alloc", "dim_upload", "chrome_present",
                                                         "register")]

    def test_the_heavy_setup_waits_for_the_host_activation_while_the_loop_reads_the_queue(self):
        p = self.make()
        rendered = []
        real = R.render_label

        def spy(*args, **kwargs):
            rendered.append(1)
            return real(*args, **kwargs)

        with patch.object(R, "render_label", spy):
            p.show(snapshot(count=5, index=1))
            alive, wait = p._step_inline()
            self.assertTrue(alive)
            self.assertIsNotNone(wait)
            self.assertGreater(wait, 0.0)                          # blocks in the idle wait, never paces
            self.assertLessEqual(wait, c.ACTIVATION_WAIT_S + 1e-9)
            self.assertEqual(self.heavy(), [])
            self.assertEqual(rendered, [])                         # no label work meanwhile either
            self.assertEqual(self.capture.jobs[-1].kind, "frost")  # the capture runs meanwhile
            self.backend.on_input(c.IN_KEY, c.VK_RIGHT, 0)         # keys work at once
            self.assertEqual(p.take_events(), [("turn", 1)])
            self.clock.t += 0.004
            self.backend.activate()
            alive, wait = p._step_inline()
            self.assertEqual(wait, 0.0)
            p._step_inline()
        names = self.heavy()
        self.assertEqual(names[:3], ["chrome_alloc", "layer_alloc", "layer_alloc"])
        self.assertNotIn("dim_upload", names)                     # Frosted: no dim window
        self.assertIn("register", names)
        self.assertIn("chrome_present", names)
        self.assertTrue(rendered)                                  # the label worker (inline here)

    def test_without_an_activation_the_setup_starts_after_the_wait(self):
        self.make()
        self.presenter.show(snapshot())
        self.step(c.ACTIVATION_WAIT_S - 0.01)
        self.assertEqual(self.heavy(), [])
        self.step(0.02)
        self.assertIn("chrome_present", self.heavy())

    def test_an_exit_before_the_activation_sets_up_and_plays(self):
        self.make()
        self.presenter.show(snapshot())
        self.presenter.play_cancel_exit()
        self.presenter.hide()
        self.step()
        self.assertIn("chrome_alloc", self.backend.names())
        self.assertEqual(self.presenter._engine.session.exiting, "cancel")
        self.step(0.4)
        self.assertEqual(self.registered(), set())
        self.assertIsNone(self.presenter._engine.toast)            # v7: the picker raises no toast

    def test_a_late_or_repeated_activation_changes_nothing(self):
        self.make()
        self.open()
        self.step(0.5)
        mark = len(self.backend.calls)
        self.backend.activate()
        self.step()
        self.assertNotIn("chrome_alloc", [e[0] for e in self.calls_since(mark)])
        self.presenter.hide()
        self.step()
        self.backend.activate()
        self.step(0.1)
        self.assertEqual(self.backend.visible, set())


class ThumbnailLifecycleTests(Harness):
    def test_open_registers_to_the_visible_table_plus_one_far_to_near_once(self):
        self.make()
        self.open(snapshot(count=7, index=1))
        registers = [entry[1] for entry in self.backend.calls if entry[0] == "register"]
        self.assertEqual(sorted(registers), [100, 101, 102, 103, 104])            # |d| <= a_vis + 1 = 3 (16:9)
        distance = [abs(hwnd - 101) for hwnd in registers]
        self.assertEqual(distance, sorted(distance, reverse=True))                 # far -> near, centre last
        self.assertEqual(registers[-1], 101)
        mark = len(self.backend.calls)
        self.step(1.0)
        self.assertNotIn("register", [e[0] for e in self.calls_since(mark)])      # never per frame

    def test_the_32_9_table_registers_five_each_side(self):
        self.make(monitor=(0, 0, 5120, 1440), work=(0, 0, 5120, 1392))
        self.open(snapshot(count=13, index=6))
        self.assertTrue(self.layout().wide)
        self.assertEqual(self.registered(), set(range(101, 112)))                  # |d| <= a_vis + 1 = 5

    def test_every_update_sends_all_properties_with_cover_fit_and_table_opacity(self):
        self.make()
        self.open(snapshot(count=7, index=1))
        self.step(1.0)
        mark = len(self.backend.calls)
        self.presenter.highlight(1)       # same index: nothing moves
        self.backend.on_event(c.EV_DATA)
        self.step()
        updates = {e[1]: e for e in self.calls_since(mark) if e[0] == "update"}
        layout = self.layout()
        _, hwnd, dest, source, opacity, visible = updates[101]
        self.assertEqual(dest, R.card_rect(layout, 0, 1.0, SHIFT))                 # 400 x 250, 44 up before the tray
        self.assertEqual((dest[2] - dest[0], dest[3] - dest[1]), (400, 250))
        self.assertEqual(source, R.cover_source((1600, 1000), dest))
        self.assertEqual((opacity, visible), (255, True))
        _, _, dest, _, opacity, visible = updates[102]
        self.assertEqual(dest, R.card_rect(layout, 280, 0.56, SHIFT))
        self.assertEqual(opacity, round(255 * R.thumb_opacity(0.95, 0.22)))
        self.assertEqual(updates[104][4:], (0, False))                           # d = 3: registered, invisible

    def test_a_detent_reregisters_far_to_near_once(self):
        self.make()
        self.open(snapshot(count=9, index=1))
        self.step(1.0)
        mark = len(self.backend.calls)
        self.presenter.highlight(2)
        self.step(0.6)
        calls = self.calls_since(mark)
        registers = [e[1] for e in calls if e[0] == "register"]
        self.assertEqual(sorted(registers), [100, 101, 102, 103, 104, 105])
        self.assertEqual(registers[-1], 102)
        distance = [abs(hwnd - 102) for hwnd in registers]
        self.assertEqual(distance, sorted(distance, reverse=True))
        first_register = next(i for i, e in enumerate(calls) if e[0] == "register")
        self.assertTrue(all(e[0] == "unregister" for e in calls[first_register - 5:first_register]))
        self.assertEqual(self.registered(), {100, 101, 102, 103, 104, 105})

    def test_a_failed_registration_is_never_retried_and_draws_the_placeholder(self):
        self.make(fail_register={102})
        self.open(snapshot(count=8, index=1))
        for index in (2, 3, 2, 1):
            self.presenter.highlight(index)
            self.step(0.5)
        attempts = [e for e in self.backend.calls if e == ("register", 102)]
        self.assertEqual(len(attempts), 1)
        self.presenter.highlight(2)
        self.step(0.5)
        chrome = self.backend.chrome.image
        layout = self.layout()
        l, t, r, b = R.card_rect(layout, 0, 1.0, SHIFT)
        ox, oy = layout.band_origin
        pixel = chrome.getpixel((l - ox + 20, t - oy + 60))
        self.assertEqual((pixel[2], pixel[1], pixel[0], pixel[3]), R.PLACEHOLDER_RGB + (255,))
        self.presenter.hide()
        self.step()
        self.open(snapshot(count=3, index=1))
        self.assertNotIn("use_plain_host", self.backend.names())     # one protected window is not a broken host

    def test_a_closed_slot_is_released_and_keeps_its_card(self):
        self.make()
        snap = self.open(snapshot(count=7, index=1))
        self.assertIn(103, self.registered())
        snap["items"][3]["available"] = False
        mark = len(self.backend.calls)
        self.presenter.highlight(1)
        self.step(0.1)
        self.assertIn(("unregister", 103), self.calls_since(mark))
        self.assertNotIn(103, self.registered())
        self.presenter.highlight(2)
        self.step(0.6)
        self.assertNotIn(("register", 103), self.calls_since(mark))
        self.assertIn(3, self.presenter._engine.machine.closed)
        self.presenter.highlight(3)
        self.step(0.6)
        self.backend.on_input(c.IN_KEY, c.VK_RETURN, 0)                          # Switch is disabled
        self.assertEqual(self.presenter.take_events(), [])

    def test_off_screen_cards_are_released(self):
        self.make()
        self.open(snapshot(count=12, index=1))
        for index in range(2, 9):
            self.presenter.highlight(index)
            self.step(0.5)
        self.assertEqual(self.registered(), set(range(105, 112)))               # |d| <= 3 around index 8

    def test_minimized_caption_stubs_use_the_placeholder(self):
        self.make(sizes={102: (200, 54)})
        self.open(snapshot(count=6, index=1, changes={2: {"minimized": True}}))
        self.assertNotIn(102, self.registered())
        self.assertIn(2, self.presenter._engine.session.stubs)
        self.make(sizes={102: (1600, 1000)})
        self.open(snapshot(count=6, index=1, changes={2: {"minimized": True}}))
        self.assertIn(102, self.registered())                                    # DWM's last frame

    def fail_open(self):
        self.open(snapshot(count=5, index=1))
        self.presenter.hide()
        self.step()

    def test_every_registration_failing_in_two_opens_in_a_row_switches_to_the_plain_host(self):
        self.make(fail_register={100, 101, 102, 103, 104})
        self.fail_open()
        self.assertEqual(self.presenter.hwnd, 0x5001)
        self.fail_open()                                   # one bad open (a GPU reset) is not enough
        self.assertNotIn("use_plain_host", self.backend.names())
        self.assertEqual(self.presenter.hwnd, 0x5001)
        self.backend.fail_register = set()
        self.presenter.set_background("none")
        self.open(snapshot(count=5, index=1))
        self.assertIn("use_plain_host", self.backend.names())
        self.assertEqual(self.presenter.hwnd, 0x5002)
        self.assertEqual(self.presenter._engine.session.background, "glass")      # forced glass
        self.assertEqual(self.presenter.metrics()["host_mode"], c.HOST_PLAIN)
        self.assertIn("host_paint", self.backend.names())

    def test_the_plain_host_builds_no_frost_before_its_handshake(self):
        self.make(host_mode=c.HOST_PLAIN)
        mark = len(self.backend.calls)
        self.presenter.show(snapshot())
        names = [e[0] for e in self.calls_since(mark)]
        self.assertIn("show_host", names)
        self.assertNotIn("host_paint", names)
        self.backend.activate()
        self.step()
        self.assertNotIn("host_paint", self.backend.names())
        self.capture.complete()
        self.step()
        self.assertIn("host_paint", self.backend.names())                # the frost, once captured
        self.assertEqual(self.backend.host_image.size, MONITOR[2:])      # the host is rcMonitor in v7

    def test_a_successful_open_between_failing_ones_starts_the_count_over(self):
        self.make(fail_register={100, 101, 102, 103, 104})
        self.fail_open()
        self.backend.fail_register = set()
        self.fail_open()
        self.backend.fail_register = {100, 101, 102, 103, 104}
        self.fail_open()
        self.open(snapshot(count=5, index=1))
        self.assertNotIn("use_plain_host", self.backend.names())

    def test_a_display_change_brings_the_layered_host_back(self):
        self.make(fail_register={100, 101, 102, 103, 104})
        self.fail_open()
        self.fail_open()
        self.backend.fail_register = set()
        self.fail_open()
        self.assertEqual(self.presenter.metrics()["host_mode"], c.HOST_PLAIN)
        self.backend.on_event(c.EV_DISPLAY)                # WM_DISPLAYCHANGE / DWM / resume
        self.step()
        self.assertNotIn("use_layered_host", self.backend.names())      # at the next open only
        self.presenter.set_background("none")
        self.open(snapshot(count=5, index=1))
        self.assertIn("use_layered_host", self.backend.names())
        self.assertEqual(self.presenter.hwnd, 0x5003)
        self.assertEqual(self.presenter.metrics()["host_mode"], c.HOST_LAYERED)
        self.assertEqual(self.presenter._engine.session.background, "none")       # offered again
        self.assertEqual(self.registered(), {100, 101, 102, 103, 104})

    def test_the_plain_host_retries_the_layered_one_later_with_a_backoff(self):
        self.make(fail_register={100, 101, 102, 103, 104})
        engine = self.presenter._engine
        self.fail_open()
        self.fail_open()
        self.fail_open()                                   # now plain
        self.assertEqual(self.backend.host_mode, c.HOST_PLAIN)
        self.clock.t += c.PLAIN_RETRY_S - 5
        self.fail_open()
        self.assertNotIn("use_layered_host", self.backend.names())
        self.clock.t += 10
        self.fail_open()                                   # the timed retry: layered, and it fails again
        self.assertEqual(self.backend.names().count("use_layered_host"), 1)
        self.fail_open()
        self.fail_open()                                   # two failing opens: plain again, doubled wait
        self.assertEqual(self.backend.host_mode, c.HOST_PLAIN)
        self.assertEqual(engine._plain_retry_s, 2 * c.PLAIN_RETRY_S)
        self.backend.fail_layered = True                   # a retry that cannot even create the host
        self.clock.t += 2 * c.PLAIN_RETRY_S + 1
        self.fail_open()
        self.assertEqual(self.backend.names().count("use_layered_host"), 2)
        self.assertEqual(self.backend.host_mode, c.HOST_PLAIN)
        self.assertEqual(engine._plain_retry_s, 4 * c.PLAIN_RETRY_S)
        self.backend.fail_layered = False
        self.backend.fail_register = set()
        self.backend.on_event(c.EV_DISPLAY)
        self.step()
        self.fail_open()                                   # layered again, and it works: backoff reset
        self.assertEqual(self.backend.host_mode, c.HOST_LAYERED)
        self.assertEqual(engine._plain_retry_s, c.PLAIN_RETRY_S)

    def test_a_source_without_a_size_draws_the_placeholder_never_one_stretched_pixel(self):
        self.make(sizes={102: None})
        self.open(snapshot(count=6, index=1))
        self.assertNotIn(102, self.registered())
        self.assertIn(2, self.presenter._engine.session.failed)
        self.assertFalse([e for e in self.backend.calls if e[0] == "update" and e[1] == 102])
        self.presenter.highlight(2)
        self.step(0.6)
        self.assertEqual([e for e in self.backend.calls if e == ("register", 102)], [("register", 102)])
        chrome = self.backend.chrome.image
        layout = self.layout()
        l, t, r, b = R.card_rect(layout, 0, 1.0, SHIFT)
        ox, oy = layout.band_origin
        pixel = chrome.getpixel((l - ox + 20, t - oy + 60))
        self.assertEqual((pixel[2], pixel[1], pixel[0], pixel[3]), R.PLACEHOLDER_RGB + (255,))
        self.assertTrue(all(e[3] != (0, 0, 1, 1) for e in self.backend.calls if e[0] == "update" and e[5]))


class DismissalTests(Harness):
    def test_hide_releases_thumbnails_before_the_windows_go_then_frees_and_clears_affinity(self):
        self.make()
        self.open()
        mark = len(self.backend.calls)
        self.presenter.hide()
        self.assertIsNotNone(self.presenter.rect)           # the carousel thread has not run yet
        self.step()
        calls = [e[:2] for e in self.calls_since(mark)]
        unregisters = [i for i, e in enumerate(calls) if e[0] == "unregister"]
        hides = [calls.index(("hide", role)) for role in ("chrome", "label", "dots", "host", "glass", "dim")]
        self.assertEqual(len(unregisters), 5)
        self.assertLess(max(unregisters), min(hides))
        self.assertEqual(hides, sorted(hides))
        self.assertLess(hides[-1], calls.index(("chrome_free",)))
        self.assertEqual(self.registered(), set())
        self.assertIsNone(self.presenter.rect)
        self.assertFalse(any(self.backend.affinity.values()))
        self.assertEqual(self.backend.visible, set())
        self.assertEqual(self.backend.layers, {})

    def test_nothing_registers_or_draws_after_hide(self):
        self.make()
        self.open()
        self.presenter.hide()
        self.step()
        mark = len(self.backend.calls)
        self.presenter.highlight(3)
        self.presenter.set_icons({"w1": Image.new("RGBA", (32, 32), (200, 0, 0, 255))})
        self.presenter.set_labels({"w1": R.SimpleLabel("A", "B", "C")})
        self.presenter.focus_local()
        self.backend.on_event(c.EV_SELECT)
        self.step(1.0)
        names = [e[0] for e in self.calls_since(mark)]
        for name in ("register", "update", "chrome_present", "layer_present", "show", "show_host"):
            self.assertNotIn(name, names)

    def test_every_thumbnail_is_released_even_when_one_release_fails(self):
        self.make(fail_unregister={102})
        self.open()
        self.presenter.hide()
        self.step()
        self.assertEqual(self.registered(), set())
        self.assertEqual(self.backend.visible, set())

    def test_close_releases_at_once_even_during_an_exit(self):
        self.make()
        self.open()
        self.presenter.play_switch_exit()
        self.step(0.1)
        self.assertTrue(self.registered())
        self.presenter.close()
        self.assertEqual(self.registered(), set())
        self.assertEqual(self.backend.visible, set())
        self.assertEqual(self.backend.names()[-2:], ["destroy_windows", "unregister_classes"])

    def test_focus_local_after_hide_does_nothing(self):
        self.make()
        self.open()
        self.presenter.hide()
        self.presenter.focus_local()
        self.assertFalse(self.presenter._focused)

    def test_hide_drops_the_per_open_caches(self):
        self.make()
        self.open()
        self.step(0.5)
        engine = self.presenter._engine
        self.assertTrue(engine._label_cache)
        self.assertTrue(engine._shadows[1]._cache)
        self.assertTrue(engine._sprites)
        self.presenter.highlight(2)
        self.step(0.2)                                      # mid-flight: resized sprites
        self.assertTrue(len(engine._scaler))
        self.presenter.hide()
        self.step()
        self.assertEqual(len(engine._label_cache), 0)
        self.assertEqual(len(engine._shadows[1]._cache), 0)
        self.assertEqual(len(engine._sprites), 0)
        self.assertEqual(len(engine._scaler), 0)
        self.assertEqual(len(engine._scaler._faces), 0)
        self.assertIsNone(self.backend.chrome)

    def test_icon_sprites_never_accumulate_over_many_opens_or_a_long_walk(self):
        self.make()
        engine = self.presenter._engine
        icon = Image.new("RGBA", (128, 128), (20, 160, 90, 255))
        for cycle in range(12):                             # fresh item ids every open (new windows)
            snap = snapshot(count=6, index=1)
            for item in snap["items"]:
                item["id"] = f"c{cycle}-{item['id']}"
            self.presenter.set_icons({item["id"]: icon for item in snap["items"]})
            self.open(snap)
            self.step(0.3)
            self.assertLessEqual(len(engine._sprites), c.SPRITE_CACHE)
            self.presenter.hide()
            self.step()
            self.assertEqual((len(engine._sprites), len(engine._scaler)), (0, 0))
        self.open(snapshot(count=60, index=1, changes={i: {"available": i % 3 != 0} for i in range(60)}))
        for index in range(2, 60, 3):                       # a long walk: placeholders and badges
            self.presenter.highlight(index)
            self.step(0.1)
            self.assertLessEqual(len(engine._sprites), c.SPRITE_CACHE)
            self.assertLessEqual(len(engine._scaler), 64)
            self.assertLessEqual(len(engine._label_cache), c.LABEL_CACHE)


class ExitTests(Harness):
    def exit_release(self, kind, dt):
        """(ms from the exit call to the last thumbnail release, ms from the engine's exit start)."""
        self.make()
        self.open()
        self.step(0.5)
        self.backend.release_times.clear()
        called = self.clock.t
        {"switch": self.presenter.play_switch_exit, "cancel": self.presenter.play_cancel_exit,
         "pair": self.presenter.play_pair_exit}[kind]()
        self.presenter.hide()                                  # the adapter's order: exit, then hide
        machine = self.presenter._engine.machine
        started = None
        while self.clock.t - called < 0.6 and (started is None or self.registered()):
            self.presenter._step_inline()
            if started is None and machine.exit_t0 is not None:
                started = machine.exit_t0
            self.clock.t += dt
        self.assertEqual(self.registered(), set())
        released = max(self.backend.release_times)
        return (released - called) * 1000, (released - started) * 1000

    def test_thumbnails_are_released_once_everything_faded_at_any_frame_rate(self):
        for kind in ("switch", "cancel", "pair"):
            for hz in (30, 60, 144, 240):
                with self.subTest(kind=kind, hz=hz):
                    from_call, from_start = self.exit_release(kind, 1 / hz)
                    # the root 280 ms OUT and the cards group 220 ms EASE: the exit ends at 280 ms, at
                    # the first frame after it; never past 420 ms from the adapter's call
                    self.assertGreaterEqual(from_start, c.EXIT_S[kind] * 1000 - 1e-6)
                    self.assertLessEqual(from_start, c.EXIT_S[kind] * 1000 + 1000 / hz + 1e-6)
                    self.assertLessEqual(from_call, 420.0)
                    self.presenter.close()

    def test_switch_exit_fades_without_a_grow_and_raises_no_toast(self):
        self.make()
        self.open()
        self.step(0.5)
        machine = self.presenter._engine.machine
        self.presenter.play_switch_exit("app1 · Window 1")
        self.presenter.hide()
        self.step(0.1)
        self.assertIn(("passive", True), self.backend.calls)
        frame = machine.values(self.clock.t)
        centre = [cf for cf in frame.cards if cf.d == 0][0]
        self.assertEqual(centre.s, 1.0, "no 1.35 grow (S5-6)")
        self.assertLess(frame.root, 1.0)
        self.step(0.13)
        frame = machine.values(self.clock.t)
        self.assertEqual(frame.group, 0.0, "the cards group is gone at 220 ms (EASE) ...")
        self.assertGreater(frame.root, 0.0, "... the root at 280 ms (OUT)")
        self.step(0.12)
        self.assertEqual(self.registered(), set())
        self.assertNotIn("toast_alloc", self.backend.names())
        self.assertIsNone(self.presenter._engine.toast)

    def test_hide_then_switch_in_the_same_batch_still_plays_the_exit(self):
        self.make()
        self.open()
        self.presenter.hide()
        self.presenter.play_switch_exit()
        self.step(0.1)
        self.assertEqual(self.presenter._engine.session.exiting, "switch")

    def test_focus_loss_hide_is_instant(self):
        self.make()
        self.open()
        self.presenter.hide()
        self.step()
        self.assertIsNone(self.presenter._engine.session)
        self.assertEqual(self.registered(), set())

    def test_no_turning_registering_or_input_during_the_exit(self):
        self.make()
        self.open()
        self.presenter.play_switch_exit()
        self.step(0.05)
        mark = len(self.backend.calls)
        self.presenter.highlight(3)
        self.backend.on_event(c.EV_SELECT)
        self.backend.on_input(c.IN_KEY, c.VK_ESCAPE, 0)
        self.step(0.2)
        self.assertNotIn("register", [e[0] for e in self.calls_since(mark)])
        self.assertEqual(self.presenter.take_events(), [])

    def test_a_display_change_closes_an_open_picker_instantly_as_display(self):
        self.make()
        self.open()
        self.backend.on_event(c.EV_DISPLAY)
        self.step()
        self.assertIsNone(self.presenter._engine.session)
        self.assertEqual(self.registered(), set())
        self.assertIn(("closed", "display"), self.events())

    def test_a_suspend_closes_instantly_and_reports_sleep(self):
        self.make()
        self.open()
        self.backend.on_event(c.EV_SUSPEND)
        self.step()
        self.assertIsNone(self.presenter._engine.session)
        self.assertIn(("system", "sleep"), self.events())


class InputTests(Harness):
    def test_keys_wheel_and_centre_click_become_events(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(0.5)
        send = self.backend.on_input
        send(c.IN_KEY, c.VK_ESCAPE, 0)
        send(c.IN_KEY, c.VK_RETURN, 0)
        send(c.IN_KEY, c.VK_RETURN, 1)                          # auto-repeat: ignored
        send(c.IN_KEY, c.VK_LEFT, 0)
        send(c.IN_KEY, c.VK_RIGHT, 0)
        send(c.IN_KEY, c.VK_DOWN, 1)                            # arrows repeat
        send(c.IN_WHEEL, -120)
        send(c.IN_WHEEL, 60)
        send(c.IN_WHEEL, 60)
        send(c.IN_HWHEEL, 120)
        layout = self.layout()
        l, t, r, b = R.card_rect(layout, 0, 1.0, SHIFT)
        send(c.IN_CLICK, (l + r) // 2, (t + b) // 2)             # host-local = monitor-local
        l2, t2, r2, b2 = R.card_rect(layout, 280, 0.56, SHIFT)
        send(c.IN_CLICK, (l2 + r2) // 2 + 60, (t2 + b2) // 2)   # a side card: nothing
        send(c.IN_CLICK, 5, 5)                                  # the rest of the monitor: eaten, nothing
        send(c.IN_CLOSE)
        self.assertEqual(self.presenter.take_events(),
                         [("cancel", None), ("switch", 1), ("turn", -1), ("turn", 1), ("turn", 1), ("turn", 1),
                          ("turn", -1), ("turn", 1), ("switch", 1), ("cancel", None)])
        self.assertEqual(self.presenter.take_events(), [])

    def test_turning_past_an_end_bumps_locally_without_an_event(self):
        self.make()
        self.open(snapshot(count=3, index=0))
        self.step(0.5)
        self.backend.on_input(c.IN_KEY, c.VK_LEFT, 0)
        self.assertEqual(self.presenter.take_events(), [])
        machine = self.presenter._engine.machine
        self.assertEqual(machine.bump, -1)
        mark = len(self.backend.calls)
        self.step(0.16)
        self.assertIn("chrome_present", [e[0] for e in self.calls_since(mark)])
        self.assertAlmostEqual(machine.values(self.clock.t).bump, 12.0)
        self.step(0.2)
        self.assertEqual(machine.values(self.clock.t).bump, 0.0)

    def test_the_knobs_limit_bumps_through_highlight(self):
        self.make()
        self.open(snapshot(count=3, index=2))
        self.step(0.5)
        self.presenter.highlight(2, bump=1)                     # K3 windows_highlight{index, bump} at the end
        self.step(0.16)
        self.assertAlmostEqual(self.presenter._engine.machine.values(self.clock.t).bump, -12.0)

    def test_input_before_open_or_after_hide_is_ignored(self):
        self.make()
        self.backend.on_input(c.IN_KEY, c.VK_ESCAPE, 0)
        self.open()
        self.presenter.hide()
        self.step()
        self.backend.on_input(c.IN_KEY, c.VK_RETURN, 0)
        self.assertEqual(self.presenter.take_events(), [])


class GlassAndBackgroundTests(Harness):
    """K4 9.2: Frosted is the full-monitor blur.picker_frost (the glass window is rcMonitor, its
    capture reads rcMonitor under display affinity, it fades in from alpha 0; no dim window); No
    background is the flat 55 % dim."""

    WIDE = (-3440, 0, 0, 1440)          # a 3440 x 1440 monitor left of the primary: k = 2

    def test_the_frost_covers_rcmonitor_under_capture_affinity(self):
        self.make(monitor=self.WIDE, work=(-3440, 0, 0, 1400))
        self.presenter.show(snapshot())
        self.assertIn(("affinity", True), self.backend.calls)
        self.assertLess(self.backend.names().index("affinity"), self.backend.names().index("show_host"))
        layout = self.layout()
        self.assertEqual(self.presenter.rect, layout.pane, "rect still reports the stage's card area")
        self.assertEqual(self.backend.calls[self.backend.names().index("show_host")][1], layout.monitor_rect)
        self.step(0.1)
        job = self.capture.jobs[-1]
        self.assertEqual((job.kind, job.rect, job.k), ("frost", (-3440, 0, 3440, 1440), 2.0))
        self.assertTrue(all(self.backend.affinity.values()), "our windows are excluded until the capture")
        self.assertNotIn("glass_upload", self.backend.names())
        self.capture.complete()
        self.step()
        self.assertEqual(self.backend.glass_rect, (-3440, 0, 3440, 1440), "the glass geometry is rcMonitor")
        self.assertIsInstance(self.backend.glass_image, R.Canvas)
        self.assertEqual(self.backend.glass_image.size, (3440, 1440))
        self.assertEqual(self.backend.glass_image.image.getextrema()[3], (255, 255))
        self.assertFalse(any(self.backend.affinity.values()), "WDA_NONE once the capture is taken")
        self.assertEqual(self.presenter.half_rect("right"), (-1720, 0, 0, 1400))

    def test_frosted_never_shows_the_dim_and_the_frost_fades_in_from_zero(self):
        self.make()
        self.presenter.show(snapshot())
        self.backend.activate()
        self.step()
        self.assertIn("show", self.backend.names())               # chrome is up, the frost not yet
        self.assertEqual([e for e in self.backend.calls if e[0] == "glass_alpha"], [])
        mark = len(self.backend.calls)
        self.capture.complete()
        self.step()
        names = [e[0] for e in self.calls_since(mark)]
        alphas = [e[1] for e in self.backend.calls if e[0] == "glass_alpha"]
        self.assertEqual(alphas[0], 0, "the frost fade starts at alpha 0")
        self.assertLess(names.index("glass_upload"), names.index("glass_alpha"))
        self.step(0.4)
        alphas = [e[1] for e in self.backend.calls if e[0] == "glass_alpha"]
        self.assertEqual(alphas, sorted(alphas))
        self.assertEqual(alphas[-1], 255)
        self.assertGreater(len(alphas), 5, "a fade, not a jump")
        for name in ("dim_upload", "dim_alpha"):
            self.assertNotIn(name, self.backend.names())
        self.assertNotIn(("show", "dim"), self.backend.calls)
        self.assertIn("glass", self.backend.visible)
        start = len(self.backend.calls)
        self.presenter.play_cancel_exit()
        self.presenter.hide()
        self.step(0.5)
        exit_alphas = [e[1] for e in self.calls_since(start) if e[0] == "glass_alpha"]
        self.assertEqual(exit_alphas, sorted(exit_alphas, reverse=True))
        self.assertEqual(exit_alphas[-1], 0)

    def test_the_frost_upload_time_is_reported_for_the_supervised_check(self):
        import json
        self.make()
        real = self.backend.glass_upload

        def slow(rect, image):
            time.sleep(0.02)
            real(rect, image)
        self.backend.glass_upload = slow
        self.presenter.show(snapshot())
        self.backend.activate()
        self.step()
        metrics = self.presenter.metrics()
        self.assertIsNone(metrics["glass_upload_ms"])
        self.assertEqual(metrics["glass_upload_ms_max"], 0.0)
        self.capture.complete()
        self.step()
        metrics = self.presenter.metrics()
        self.assertGreaterEqual(metrics["glass_upload_ms"], 15.0)
        self.assertEqual(metrics["glass_upload_ms_max"], metrics["glass_upload_ms"])
        self.assertEqual((metrics["capture_ms"], metrics["glass_ms"]), (1.0, 1.0))
        json.dumps(metrics)
        self.presenter.hide()
        self.step(0.5)
        self.backend.glass_upload = real                          # a quick second open: max keeps the slow one
        self.open()
        metrics = self.presenter.metrics()
        self.assertLess(metrics["glass_upload_ms"], metrics["glass_upload_ms_max"])

    def test_capture_timeout_falls_back_to_the_tint_and_clears_affinity(self):
        self.make()
        self.presenter.show(snapshot())
        self.step(0.6)
        self.assertIn("glass_upload", self.backend.names())
        self.assertEqual(self.backend.glass_rect, (0, 0, 1280, 720))
        solid = self.backend.glass_image
        self.assertEqual(solid.size, (1280, 720))
        self.assertEqual(solid.image.getpixel((100, 300))[3], round(255 * 0.50))    # blur.picker_frost: no dim
        self.assertFalse(any(self.backend.affinity.values()))
        self.assertEqual(self.presenter._status.glass_fallbacks, 1)
        self.capture.complete()                                 # a late result is dropped
        self.step()
        self.assertEqual(self.presenter._status.glass_fallbacks, 1)

    def test_no_background_has_no_capture_no_affinity_and_the_55_percent_dim(self):
        self.make()
        self.presenter.set_background("none")
        self.assertEqual(self.presenter.background, "none")
        self.presenter.show(snapshot())
        self.step(0.5)
        self.assertEqual(self.capture.jobs, [])
        self.assertNotIn("affinity", self.backend.names())
        self.assertEqual(self.backend.dim, "none")
        self.assertIn("dim", self.backend.visible)
        self.assertEqual([e[1] for e in self.backend.calls if e[0] == "dim_alpha"][-1], 255)
        self.assertNotIn("glass_upload", self.backend.names())
        self.presenter.set_background("anything")
        self.assertEqual(self.presenter.background, "glass")

    def test_the_plain_host_paints_the_frost_over_the_whole_monitor(self):
        # The v7 host is rcMonitor (K4 9.2): the plain-host fallback paints the frost over the
        # whole monitor; there is no dim around a pane any more.
        self.make(host_mode=c.HOST_PLAIN, monitor=self.WIDE, work=self.WIDE)
        self.presenter.set_background("none")                     # forced to Frosted on the plain host
        self.open()
        self.step(0.4)
        shown = [e for e in self.backend.calls if e[0] == "show_host"][-1]
        self.assertEqual(shown[1], (-3440, 0, 3440, 1440))
        self.assertEqual(self.backend.host_image.size, (3440, 1440))
        self.assertIsInstance(self.backend.host_image, R.Canvas)
        self.assertNotIn("dim_upload", self.backend.names())
        for name in ("glass_upload", "glass_alpha"):
            self.assertNotIn(name, self.backend.names())

    def test_capture_exclusions_cover_the_frost_capture_only(self):
        self.make()
        self.presenter.set_capture_exclusions([0x7001, 0, "bad", None, 0x7001, 0x7002])
        mark = len(self.backend.calls)
        self.presenter.show(snapshot())
        calls = self.calls_since(mark)
        names = [e[0] for e in calls]
        self.assertIn(("exclusions", (0x7001, 0x7002), True), calls)
        self.assertLess(names.index("show_host"), names.index("exclusions"))
        self.assertEqual(self.capture.jobs[-1].kind, "frost")
        self.assertEqual(self.backend.excluded, {0x7001, 0x7002})
        self.backend.activate()
        self.step()
        self.assertEqual(self.backend.excluded, {0x7001, 0x7002})     # the capture is still running
        self.capture.complete()
        self.step()
        self.assertEqual(self.backend.excluded, set())
        self.presenter.hide()
        self.step()
        self.presenter.set_background("none")
        mark = len(self.backend.calls)
        self.presenter.show(snapshot())
        self.step(0.4)
        self.assertNotIn("exclusions", [e[0] for e in self.calls_since(mark)])

    def test_a_final_frame_at_rest_is_composed_after_every_animation(self):
        for hz in (60, 144, 240):
            with self.subTest(hz=hz):
                self.make()
                self.open(snapshot(count=7, index=1))
                self.step(1.0, 1 / hz)
                scenes = []
                real = R.compose_chrome

                def spy(canvas, scene, shadows, scaler=None):
                    scenes.append(scene)
                    return real(canvas, scene, shadows, scaler)
                with patch.object(R, "compose_chrome", spy):
                    self.presenter.highlight(2)
                    self.step(1.0, 1 / hz)
                self.assertGreater(len(scenes), 3)
                self.assertTrue(all(scene.animating for scene in scenes[:-1]))
                last = scenes[-1]
                self.assertFalse(last.animating)
                centre = [card for card in last.cards if card.index == 2]
                self.assertEqual(len(centre), 1)
                self.assertEqual((centre[0].s, centre[0].op, centre[0].selw), (1.0, 1.0, 1.0))
                self.assertEqual(centre[0].rect, R.card_rect(self.layout(), 0.0, 1.0, SHIFT))
                engine = self.presenter._engine
                resamples = {key[2] for key in engine._scaler._cache}
                self.assertIn(False, resamples)                      # LANCZOS copies for the rest frame
                self.assertTrue(engine._shadows[1]._cache)            # rest-frame shadows cached
                self.presenter.close()

    def test_first_frame_shows_chrome_and_layers_after_their_content(self):
        self.make()
        self.presenter.show(snapshot())
        self.backend.activate()
        self.step()
        names = self.backend.names()
        self.assertLess(names.index("chrome_present"), names.index("show"))
        self.assertEqual([e for e in self.backend.calls if e[0] == "show"],
                         [("show", "chrome"), ("show", "label"), ("show", "dots")])   # Frosted: no dim
        self.make()
        self.presenter.set_background("none")
        self.presenter.show(snapshot())
        self.backend.activate()
        self.step()
        names = self.backend.names()
        self.assertLess(names.index("dim_upload"), names.index("show"))
        self.assertIn(("show", "dim"), self.backend.calls)

    def test_frame_order_updates_then_chrome_then_the_pace(self):
        self.make()
        self.open()
        self.step(0.5)
        mark = len(self.backend.calls)
        self.presenter.highlight(2)
        self.step(0.3)
        calls = [e[0] for e in self.calls_since(mark)]
        frames = []
        current = []
        for name in calls:
            if name == "pace":
                frames.append(current)
                current = []
            else:
                current.append(name)
        self.assertGreater(len(frames), 5)
        for frame in frames:
            core = [n for n in frame if n in ("register", "unregister", "update", "chrome_present")]
            if core:
                self.assertEqual(core[-1], "chrome_present")        # updates and the chrome back to back
        self.assertTrue(all(d is not None for d in self.backend.dirty[1:]), "B5: dirty rects after the first frame")


class LayerTests(Harness):
    """B2 (K4 9.9): the label and the dots live in their own layered windows, uploaded only on a
    change; the group's fades are constant alphas and its shift a window move."""

    def presents(self, role, since=0):
        return [e for e in self.backend.calls[since:] if e[0] == "layer_present" and e[1] == role]

    def test_the_label_uploads_once_per_swap_and_fades_by_constant_alpha(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(0.6)
        label = self.presents("label")
        self.assertEqual(len(label), 1, "one upload for the first label")
        alphas = [e[2] for e in self.backend.calls if e[0] in ("layer_alpha", "layer_present") and e[1] == "label"]
        self.assertEqual(alphas[-1], 255)
        self.assertEqual(alphas, sorted(alphas), "the label fades in (root x label fade)")
        canvas = self.backend.layers["label"]
        self.assertGreater(canvas.image.getextrema()[3][1], 200, "the label is drawn in its layer")
        mark = len(self.backend.calls)
        self.presenter.highlight(2)
        self.step(0.5)
        self.assertEqual(len(self.presents("label", mark)), 1, "a detent swaps once")
        swap = [e for e in self.backend.calls[mark:] if e[0] in ("layer_alpha", "layer_present") and e[1] == "label"]
        self.assertEqual(swap[0][2], 0, "the new label starts at opacity 0 ...")
        self.assertEqual(swap[-1][2], 255, "... and fades in over 160 ms")

    def label_alphas(self, since):
        return [e[2] for e in self.backend.calls[since:] if e[0] in ("layer_alpha", "layer_present")
                and e[1] == "label"]

    def test_a_new_sprite_for_the_same_card_swaps_without_a_blink(self):
        """WP7b-R4 (K4 9.3 / 9.8; BS:1340's _labKey): the label fades in only when the selection
        moves. The snapped suffix appearing (acceptance) or going (a failed placement), and label
        or icon data arriving after open, replace the sprite at full opacity."""
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(0.6)
        self.assertEqual(self.backend.layer_state["label"][0], 255)
        engine = self.presenter._engine
        s = engine.session
        # the snapped suffix appears at acceptance ...
        mark = len(self.backend.calls)
        request = {"t0": self.clock.t, "index": 1, "side": "left", "target_rect": None, "place_at_ms": 360,
                   "item": {"id": "w1", "hwnd": 101, "pid": 20}}
        self.presenter.snap(request)
        self.step()
        job = self.snapper.jobs[-1]
        self.snapper.answer(job, "precheck", "accepted")
        self.step(0.3)
        self.assertEqual(s.label_key[4], R.SNAPPED_DESC["left"], "the suffix is shown")
        self.assertGreaterEqual(len(self.presents("label", mark)), 1, "the new sprite was uploaded")
        self.assertEqual(min(self.label_alphas(mark)), 255, "no blink at acceptance")
        # ... and goes when the placement fails
        mark = len(self.backend.calls)
        self.snapper.answer(job, "final", "move_rejected")
        self.step(0.3)
        self.assertEqual(s.label_key[4], "", "the suffix is gone")
        self.assertEqual(min(self.label_alphas(mark)), 255, "no blink when the suffix goes")
        # label data arriving after open
        mark = len(self.backend.calls)
        self.presenter.set_labels({"w1": R.SimpleLabel("app1", "A new title", "A description")})
        self.step(0.3)
        self.assertEqual(s.label_key[2], "A new title")
        self.assertEqual(min(self.label_alphas(mark)), 255, "no blink for new label data")
        # a detent still swaps, then fades in over 160 ms
        mark = len(self.backend.calls)
        self.presenter.highlight(2)
        self.step(0.5)
        swap = self.label_alphas(mark)
        self.assertEqual(swap[0], 0, "a new card's label starts at opacity 0 ...")
        self.assertEqual(swap[-1], 255, "... and fades in")

    def test_the_dots_row_and_marker(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(0.6)
        canvas = self.backend.layers["dots"]
        layout = self.layout()
        ox, oy = layout.dots[0] - layout.stage_x, layout.dots[1] - layout.stage_y
        left = R.CENTER_X - R.dots_width(5) / 2
        y = R.DOTS_TOP - oy + 2
        dim = canvas.image.getpixel((round(left) + 2 - round(ox), y))[3]
        marker = canvas.image.getpixel((round(left + R.DOT_PITCH) + 2 - round(ox), y))[3]
        self.assertEqual(dim, round(255 * R.DOT_OPACITY))
        self.assertEqual(marker, 255)
        mark = len(self.backend.calls)
        self.presenter.highlight(2)
        self.step(0.5)
        self.assertGreater(len(self.presents("dots", mark)), 3, "the marker translates over 420 ms")

    def test_the_group_shift_moves_the_layers(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(0.6)
        layout = self.layout()
        alpha, pos = self.backend.layer_state["label"]
        self.assertEqual(pos, (layout.labels[0], layout.labels[1] + round(SHIFT * layout.k)))


class SnapTests(Harness):
    """K4 9.4-9.7 on the carousel thread with a fake NanoD-snap: the job hand-over, the answers,
    the tray, the fly, the chip, the one-side preview, failures and the backstop."""

    def request(self, index=1, side="left", t0=None, target=None):
        return {"t0": self.clock.t if t0 is None else t0, "index": index, "side": side,
                "target_rect": target, "place_at_ms": 360, "item": {"id": f"w{index}", "hwnd": 100 + index, "pid": 20}}

    def snap(self, index=1, side="left", **kwargs):
        self.presenter.snap(self.request(index, side, **kwargs))
        self.step()
        return self.snapper.jobs[-1]

    def test_a_snap_hands_the_job_to_nanod_snap_with_t0_the_placement_and_the_deadline(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        t0 = self.clock.t - 0.01
        job = self.snap(1, "left", t0=t0)
        self.assertEqual(job.kind, "snap")
        self.assertEqual((job.side, job.hwnd, job.item["id"], job.item["pid"]), ("left", 101, "w1", 20))
        self.assertEqual(job.target, (0, 0, 640, 672))                  # the rcWork half (K3 target_rect)
        self.assertAlmostEqual(job.place_at, t0 + 0.360)
        self.assertAlmostEqual(job.deadline, t0 + 0.800)
        self.assertEqual(self.events(), [])                             # nothing before the pre-checks answer

    def test_acceptance_assigns_the_side_reveals_the_tray_and_flies(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(0.6)
        job = self.snap(1, "left")
        mark = len(self.backend.calls)
        self.snapper.answer(job, "precheck", "accepted")
        self.step()
        self.assertEqual(self.events(), [("snap_result", ("left", "accepted"))])
        engine = self.presenter._engine
        s = engine.session
        self.assertEqual(s.sides, {"left": 1, "right": None})
        self.assertTrue(engine.machine.tray_on)
        registers = [e[1] for e in self.calls_since(mark) if e[0] == "register"]
        self.assertEqual(registers[0], 101, "the slot's thumbnail first: below the cards")
        self.assertEqual(registers[-1], 101, "the fly last: on top of everything")
        self.assertEqual(registers.count(101), 3, "slot, card and fly")
        self.assertIsNotNone(s.fly)
        self.step(0.36)
        self.snapper.answer(job, "final", "ok")                    # placed and verified before the deadline
        self.step(0.1)
        fly = s.extra.get("fly")
        self.assertIsNotNone(fly)
        dest = self.backend.props[fly[0]][0]
        target = R.fly_target(self.layout(), "left")
        self.assertEqual(target, R.fly_target(self.layout(), (0, 0, 640, 672)))
        self.assertEqual(dest, R.fly_rect(s.fly["start"], target, 1.0))
        self.assertLessEqual(dest[2], 640, "a left snap flies into the left rcWork half (WP7b-R1)")
        self.assertLess(self.backend.props[fly[0]][2], 255, "fading since 380 ms")
        self.step(0.2)
        self.assertIsNone(s.fly, "unregistered at 600 ms")
        self.assertNotIn("fly", s.extra)
        self.step(0.5)
        frame = engine.machine.values(self.clock.t)
        self.assertEqual((frame.shift, frame.tray_op, frame.tray_y, frame.tray_sc), (0.0, 1.0, 0.0, 1.0))
        slot = s.extra["left"]
        dest, source, opacity, visible = self.backend.props[slot[0]]
        self.assertEqual(dest, R.slot_rect(self.layout(), "left"))
        self.assertEqual((opacity, visible), (255, True))
        centre = engine._label_job(s, 1)
        self.assertEqual(centre.suffix, R.SNAPPED_DESC["left"])

    def test_the_fly_ends_centred_in_the_half_being_snapped_to_on_the_g93sc(self):
        """WP7b-R1 / K4 9.5: kf = 2.784, a 2227 x 1392 px box at x 166 (left) or 2726 (right), y 0,
        whether the job's target came from the runtime (target_rect) or from the side."""
        for side, x, target in (("left", 166, None), ("right", 2726, None),
                                ("left", 166, (0, 0, 2560, 1392)), ("right", 2726, (2560, 0, 5120, 1392))):
            with self.subTest(side=side, target=target):
                self.make(monitor=(0, 0, 5120, 1440), work=(0, 0, 5120, 1392))
                self.open(snapshot(count=5, index=1))
                self.step(0.6)
                job = self.snap(1, side, target=target)
                self.snapper.answer(job, "precheck", "accepted")
                self.step()
                self.step(0.47)                                      # past the 460 ms move, before the release
                fly = self.presenter._engine.session.extra.get("fly")
                self.assertIsNotNone(fly)
                l, t, r, b = self.backend.props[fly[0]][0]
                self.assertLessEqual(abs(l - x), 1)
                self.assertLessEqual(abs(t - 0), 1)
                self.assertLessEqual(abs((r - l) - 2227), 2)
                half = (0, 2560) if side == "left" else (2560, 5120)
                self.assertTrue(half[0] - 1 <= l and r <= half[1] + 1, f"inside the {side} rcWork half")
                self.presenter.close()

    def test_placement_ok_requeries_the_source_and_keeps_the_host_in_front(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        job = self.snap(1, "right")
        self.snapper.answer(job, "precheck", "accepted")
        self.step()
        self.events()
        mark = len(self.backend.calls)
        self.snapper.answer(job, "final", "ok", {"posted": True, "foreground": 0x5001})
        self.step()
        self.assertEqual(self.events(), [("snap_result", ("right", "ok"))])
        names = [e[0] for e in self.calls_since(mark)]
        self.assertIn("source_size", names)
        self.assertIn("refocus_host", names)
        self.assertEqual(self.presenter._engine.session.sides["right"], 1)

    def test_a_precheck_failure_shows_the_slot_failure_and_reveals_the_tray_without_a_fly(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        job = self.snap(1, "left")
        self.snapper.answer(job, "precheck", "hung")
        self.step()
        self.assertEqual(self.events(), [("snap_result", ("left", "hung"))])
        engine = self.presenter._engine
        s = engine.session
        self.assertEqual(s.sides, {"left": None, "right": None})
        self.assertIsNone(s.fly)
        self.assertTrue(engine.machine.tray_on)
        self.assertEqual(s.failures["left"][0], "hung")
        self.step(0.3)
        self.assertGreater(engine.machine.values(self.clock.t).slots["left"].borders["failure"], 0.99)
        caption_keys = list(engine._captions)
        self.assertTrue(any(key[1] == "app1 isn’t responding" and key[2] == "failure" for key in caption_keys))
        self.step(c.FAILURE_S)
        self.assertNotIn("left", s.failures, "the failure state lasts 2.4 s")

    def test_a_placement_failure_unassigns_the_side(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        job = self.snap(1, "left")
        self.snapper.answer(job, "precheck", "accepted")
        self.step()
        self.snapper.answer(job, "final", "cant_fit")
        self.step()
        self.assertEqual(self.events(), [("snap_result", ("left", "accepted")), ("snap_result", ("left", "cant_fit"))])
        s = self.presenter._engine.session
        self.assertEqual(s.sides["left"], None)
        self.assertNotIn("left", s.extra)
        self.assertEqual(s.failures["left"][0], "cant_fit")

    def test_the_backstop_answers_move_rejected_at_the_deadline_once(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        t0 = self.clock.t
        job = self.snap(1, "left", t0=t0)
        self.snapper.answer(job, "precheck", "accepted")
        self.step(0.7)
        self.assertEqual(self.events(), [("snap_result", ("left", "accepted"))])
        self.step(0.11)
        self.assertEqual(self.events(), [("snap_result", ("left", "move_rejected"))])
        self.assertEqual(job.resolved_by, "carousel")
        self.assertFalse(self.snapper.answer(job, "final", "ok"), "a late worker result is dropped")
        self.step()
        self.assertEqual(self.events(), [])
        self.assertEqual(self.presenter.metrics()["snap_backstops"], 1)
        self.assertIsNone(self.presenter._engine.session.sides["left"])

    def test_the_idle_wait_ends_at_the_backstop_deadline(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(1.0)
        job = self.snap(1, "left", t0=self.clock.t)
        self.snapper.answer(job, "precheck", "hung")
        self.step(3.0)                                           # everything settled
        job = self.snap(2, "left", t0=self.clock.t)
        alive, wait = self.presenter._step_inline()
        self.assertIsNotNone(wait)
        self.assertLessEqual(wait, 0.8 + 1e-6, "the P9 idle wait wakes for the backstop")

    def test_snapping_the_same_window_to_the_other_side_moves_it(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        job = self.snap(1, "left")
        self.snapper.answer(job, "precheck", "accepted")
        self.snapper.answer(job, "final", "ok")
        self.step(0.9)
        job = self.snap(1, "right")
        self.snapper.answer(job, "precheck", "accepted")
        self.step()
        s = self.presenter._engine.session
        self.assertEqual(s.sides, {"left": None, "right": 1})
        self.assertNotIn("left", s.extra)

    def test_the_one_side_preview_shows_the_origin_in_the_empty_slot(self):
        self.make()
        self.open(snapshot(count=5, index=1, origin=100))       # the origin window is item 0
        job = self.snap(1, "left")
        self.snapper.answer(job, "precheck", "accepted")
        self.step(0.6)
        engine = self.presenter._engine
        s = engine.session
        self.assertEqual(engine._keep_side(s), "right")
        keep = s.extra.get("keep")
        self.assertIsNotNone(keep)
        self.assertEqual(keep[1], 100)
        self.assertEqual(self.backend.props[keep[0]][2], round(255 * R.KEEP_OPACITY))
        self.assertTrue(any(key[1] == "Right · keeps app0" and key[2] == "keep" for key in engine._captions))
        job = self.snap(0, "right")                              # the origin takes a side: no preview
        self.snapper.answer(job, "precheck", "accepted")
        self.step(0.3)
        self.assertIsNone(engine._keep_side(s))
        self.assertNotIn("keep", s.extra)

    def test_reduced_motion_has_no_fly_and_the_tray_fades_only(self):
        self.make()
        self.presenter.set_reduced_motion(True)
        self.open(snapshot(count=5, index=1))
        job = self.snap(1, "left")
        self.snapper.answer(job, "precheck", "accepted")
        self.step()
        engine = self.presenter._engine
        self.assertIsNone(engine.session.fly)
        frame = engine.machine.values(self.clock.t)
        self.assertEqual((frame.shift, frame.tray_y, frame.tray_sc), (0.0, 0.0, 1.0))
        self.assertLess(frame.tray_op, 1.0)

    def test_a_snap_without_an_open_picker_is_answered_at_once(self):
        self.make()
        self.presenter.snap(self.request(1, "left"))
        self.assertEqual(self.events(), [("snap_result", ("left", "move_rejected"))])
        self.open()
        self.presenter.snap({"side": "up", "index": 1})
        self.assertEqual(self.events(), [("snap_result", (None, "move_rejected"))])

    def test_a_teardown_resolves_a_pending_snap(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        job = self.snap(1, "left")
        self.presenter.hide()
        self.step()
        self.assertEqual(self.events(), [("snap_result", ("left", "move_rejected"))])
        self.assertTrue(job.resolved)

    def test_complete_one_side_and_raise_go_to_nanod_snap_with_their_deadline(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        start = self.clock.t
        job_id = self.presenter.complete_one_side({"hwnd": 100, "pid": 20, "id": "x"}, "right")
        self.presenter.raise_window(103)
        self.step()
        complete = [job for job in self.snapper.jobs if job.kind == "complete"][0]
        raised = [job for job in self.snapper.jobs if job.kind == "raise"][0]
        self.assertEqual(complete.id, job_id)
        self.assertEqual(complete.target, (640, 0, 1280, 672))
        self.assertAlmostEqual(complete.deadline, start + 0.600)
        self.assertEqual(raised.hwnd, 103)
        self.snapper.answer(complete, "complete", "ok")
        self.step()
        self.assertEqual(self.events(), [("complete_result", (job_id, True))])
        job_id = self.presenter.complete_one_side({"hwnd": 100, "pid": 20}, "left")
        self.step(0.61)
        self.assertEqual(self.events(), [("complete_result", (job_id, False))])     # the backstop
        self.presenter.close()
        job_id = self.presenter.complete_one_side({"hwnd": 100, "pid": 20}, "left")
        self.assertEqual(self.events(), [("complete_result", (job_id, False))])


class ToastServiceTests(Harness):
    """K4 10: the toast service on the carousel thread, no longer tied to a picker session."""

    def show(self, text="Playing Promises", exit=False, capture=True):
        self.presenter.toast(text, exit=exit)
        self.step()
        if capture and self.capture.jobs and self.capture.jobs[-1].kind == "toast":
            self.capture.complete()
            self.step()

    def test_a_toast_shows_at_top_588_holds_1800_ms_and_fades_out_in_200(self):
        self.make()
        self.show()
        toast = self.presenter._engine.toast
        self.assertIsNotNone(toast)
        layout = self.layout()
        self.assertEqual(toast.rect[1], round(layout.screen_point(0, R.TOAST_TOP)[1]))
        self.step(0.3)
        self.assertIn("toast", self.backend.visible)
        self.assertFalse(self.backend.affinity["toast"])
        self.step(1.4)
        self.assertIn("toast", self.backend.visible)
        self.step(0.35)
        self.assertNotIn("toast", self.backend.visible)
        self.assertIsNone(self.presenter._engine.toast)
        self.assertEqual(self.presenter.metrics()["toasts"], 1)

    def test_a_toast_is_dropped_over_the_open_picker(self):
        self.make()
        self.open()
        self.presenter.toast("Playing Promises")
        self.step()
        self.assertIsNone(self.presenter._engine.toast)
        self.assertEqual(self.presenter.metrics()["toasts_dropped"], 1)

    def test_the_pickers_own_exit_toast_waits_for_the_end_of_its_exit(self):
        self.make()
        self.open()
        self.step(0.5)
        self.presenter.play_cancel_exit()
        self.presenter.hide()
        self.step(0.05)
        self.presenter.toast("Slack left · Chrome right", exit=True)
        self.step(0.1)
        self.assertIsNone(self.presenter._engine.toast)
        self.step(0.2)
        self.assertIsNone(self.presenter._engine.session)
        self.assertEqual(self.presenter._engine.toast.text, "Slack left · Chrome right")

    def test_a_replacement_swaps_the_text_restarts_the_hold_without_entry_motion(self):
        self.make()
        self.show("First toast")
        self.step(1.0)
        machine = self.presenter._engine.toast.machine
        t0 = machine.t0
        self.presenter.toast("A second, longer toast text")
        self.step()
        toast = self.presenter._engine.toast
        self.assertEqual(toast.text, "A second, longer toast text")
        self.assertIs(toast.machine, machine)
        self.assertEqual(machine.t0, t0, "no new entry motion")
        self.assertEqual(self.capture.jobs[-1].kind, "toast", "a fresh glass capture for the new width")
        self.step(1.0)
        self.assertIn("toast", self.backend.visible, "the hold restarted")
        self.step(1.1)
        self.assertIsNone(self.presenter._engine.toast)

    def test_full_screen_and_presentation_mode_drop_toasts(self):
        self.make()
        self.backend.busy = True
        self.show()
        self.assertIsNone(self.presenter._engine.toast)
        self.assertEqual(self.presenter.metrics()["toasts_dropped"], 1)

    def test_an_open_or_end_toast_ends_a_running_toast(self):
        self.make()
        self.show()
        self.step(0.2)
        self.assertIn("toast", self.backend.visible)
        self.presenter.end_toast()
        self.step()
        self.assertNotIn("toast", self.backend.visible)
        self.show()
        self.step(0.2)
        mark = len(self.backend.calls)
        self.presenter.show(snapshot())
        calls = self.calls_since(mark)
        self.assertLess(calls.index(("toast_affinity", True)), calls.index(("hide", "toast")))
        self.assertLess(calls.index(("hide", "toast")), [e[0] for e in calls].index("show_host"))
        job = self.capture.jobs[-1]
        self.assertEqual((job.kind, job.flush), ("frost", True))

    def test_toast_capture_timeout_uses_the_plain_pill(self):
        self.make()
        self.presenter.toast("x")
        self.step(0.2)
        self.assertIn("toast", self.backend.visible)
        self.assertFalse(self.backend.affinity["toast"])

    def test_the_pill_is_rendered_by_the_label_worker_never_by_the_carousel_thread(self):
        """WP7b-R6: text fitting, the blur.toast glass and the drawing run on NanoD-label (here
        its inline form), for the first toast and for a replacement; the old pill stays up until
        the new one exists, and the carousel thread only pastes the premultiplied pill."""
        calls = []
        real = R.render_toast_canvas

        def spy(*args, **kwargs):
            calls.append(sys._getframe(1).f_code.co_name)
            return real(*args, **kwargs)

        class HeldToasts(c.LabelWorker):
            hold = False

            def take_toast_results(self):
                return [] if self.hold else super().take_toast_results()
        with patch.object(R, "render_toast_canvas", spy):
            self.make()
            engine = self.presenter._engine
            held = engine.labeler = HeldToasts(threaded=False)
            self.show("First toast")
            self.step(1.0)
            toast = engine.toast
            old = toast.sprite
            self.assertIsInstance(old, R.Canvas)
            held.hold = True
            self.presenter.toast("A second, longer toast text")
            self.step(0.05)
            self.assertIs(toast.sprite, old, "the old pill stays until NanoD-label has the new one")
            self.assertIn("toast", self.backend.visible)
            held.hold = False
            self.step()
            self.assertIsNot(toast.sprite, old)
            self.assertGreater(toast.sprite.size[0], old.size[0])
            self.assertEqual(self.capture.jobs[-1].kind, "toast", "then a fresh glass for the new width")
            self.capture.complete()
            self.step()
            self.assertFalse(self.backend.affinity["toast"])
        self.assertGreaterEqual(len(calls), 4, calls)                     # plain, glass, stretch, glass
        self.assertEqual(set(calls), {"_default_render_toast"}, "only ever on the label worker")

    def test_a_threaded_label_worker_renders_toast_pills_on_nanod_label(self):
        names = []
        real = R.render_toast_canvas

        def spy(*args, **kwargs):
            names.append(threading.current_thread().name)
            return real(*args, **kwargs)
        done = threading.Event()
        with patch.object(R, "render_toast_canvas", spy):
            worker = c.LabelWorker(post=lambda code: done.set(), threaded=True)
            self.addCleanup(worker.close, 2.0)
            self.assertTrue(worker.submit_toast(c.ToastJob((1, 1, "plain"), "Playing Promises", 2.0, None)))
            self.assertTrue(done.wait(20))
        results = worker.take_toast_results()
        self.assertEqual([key for key, _ in results], [(1, 1, "plain")])
        self.assertIsInstance(results[0][1], R.Canvas)
        self.assertEqual(names, ["NanoD-label"])

    def test_reduced_motion_toasts_have_no_rise_or_scale(self):
        self.make()
        self.presenter.set_reduced_motion(True)
        self.show()
        opacity, rise, scale = self.presenter._engine.toast.machine.values(self.clock.t)
        self.assertEqual((rise, scale), (0.0, 1.0))


class FrameStatsTests(Harness):
    def test_episodes_are_recorded_per_surface(self):
        self.make()
        self.open(snapshot(count=5, index=1))
        self.step(0.6, 1 / 240)
        self.presenter.highlight(2)
        self.step(0.6, 1 / 240)
        frames = self.presenter.metrics()["frames"]
        self.assertIn("picker", frames)
        last = frames["picker"]["last"]
        self.assertEqual(last["method"], "present_cadence")
        self.assertGreater(last["frames"], 20)
        self.assertGreater(last["fps"], 40)
        self.assertIn(last["kind"], ("turn", "open"))
        self.assertIn("interval_ms", last)
        for key in ("work_ms", "present_ms", "compose_present_ms", "cpu_pct_one_core", "boosted", "rm"):
            self.assertIn(key, last, key)                                 # WP7b-R2 (K4 6.2)
        self.assertGreaterEqual(last["compose_present_ms"]["p95"], last["work_ms"]["p95"])
        self.assertIs(last["rm"], False)

    def test_the_end_bump_is_a_turn_episode_and_present_time_is_measured(self):
        """WP7b-R2: K4 6.2 has no 'bump' kind; present_ms is the ULW span, not the compose."""
        self.make()
        clock = self.clock
        original = self.backend.chrome_present

        def slow_present(dirty=None):
            clock.t += 0.002                                              # a 2 ms chrome upload
            return original(dirty)
        self.backend.chrome_present = slow_present
        self.presenter._stats.cpu_clock = lambda: 0.0
        self.open(snapshot(count=3, index=2))
        self.step(0.8, 1 / 240)
        self.presenter.highlight(2, bump=1)                               # the knob's lim at the end
        self.step(0.6, 1 / 240)
        frames = self.presenter.metrics()["frames"]["picker"]
        last = frames["last"]
        self.assertEqual(last["kind"], "turn")
        self.assertNotIn("bump", frames["totals"])
        self.assertGreaterEqual(last["present_ms"]["p95"], 2.0 - 1e-6)
        self.assertGreaterEqual(last["compose_present_ms"]["p95"], last["present_ms"]["p95"])
        self.assertEqual(last["cpu_pct_one_core"], 0.0)


class DataTests(Harness):
    def test_icons_and_labels_are_recorded_on_the_tk_thread_and_drawn_by_the_engine(self):
        self.make()
        calls = []

        class Untouchable:
            """An icon the Tk side must never look into (no icon work in the focus path)."""
            def __getattr__(self, name):
                calls.append(name)
                raise AttributeError(name)

        self.presenter.set_icons({"w1": Untouchable()})
        self.assertEqual(calls, [])
        self.presenter.set_icons({"w1": Image.new("RGBA", (128, 128), (220, 30, 30, 255))})
        self.presenter.set_labels({"w1": R.SimpleLabel("Slack", "Danny Lewis", "Direct message")})
        published = []
        real = R.badge_sprite

        def spy(*args, **kwargs):
            published.append(self.presenter._status.opened_gen)
            return real(*args, **kwargs)

        with patch.object(R, "badge_sprite", spy):
            self.open(snapshot(count=4, index=1))
            self.step(0.5)
        self.assertTrue(published)
        self.assertTrue(all(gen >= 1 for gen in published))       # icon work only after the handshake
        chrome = self.backend.chrome.image
        layout = self.layout()
        ox, oy = layout.band_origin
        l, t, r, b = R.card_rect(layout, 0, 1.0, SHIFT)
        b_, g_, r_, a = chrome.getpixel((l - ox + R.BADGE_INSET + 15, b - oy - R.BADGE_INSET - 15))
        self.assertEqual((r_, g_, b_, a), (220, 30, 30, 255))     # the red icon's badge
        self.assertGreater(self.backend.layers["label"].image.getextrema()[3][1], 200)

    def test_the_hires_copy_attached_to_a_32_px_icon_is_used(self):
        icon = Image.new("RGBA", (32, 32), (0, 0, 255, 255))
        icon.info["nanod.iconHires"] = Image.new("RGBA", (128, 128), (0, 255, 0, 255))
        self.assertEqual(c._master_icon(icon).size, (128, 128))
        self.assertEqual(c._master_icon(Image.new("RGBA", (32, 32))).size, (32, 32))

    def test_closed_centre_label_says_closed(self):
        self.make()
        snap = self.open(snapshot(count=4, index=1))
        snap["items"][1]["available"] = False
        self.presenter.highlight(1)
        self.step(0.1)
        engine = self.presenter._engine
        job = engine._label_job(engine.session, 1)
        self.assertEqual(job.label.desc, R.CLOSED_DESC)
        self.assertEqual(job.label.title, "Window 1")


class ThreadedFakeBackend(FakeBackend):
    """A thread-safe fake: posts go through a queue.Queue; wait() blocks on it."""

    def __init__(self, delay_open=0.0, **kwargs):
        super().__init__(**kwargs)
        self.q = queue.Queue()
        self.delay_open = delay_open
        self.lock = threading.Lock()

    def log(self, *entry):
        with self.lock:
            self.calls.append(entry)

    def post(self, code):
        if self.destroyed:
            return False
        self.q.put(code)
        return True

    def post_quit(self):
        self.q.put("quit")
        return True

    def _dispatch(self, code):
        if code == "quit":
            return False
        if self.on_event is not None:
            self.on_event(c.POSTED_EVENTS[code])
        return True

    def pump(self):
        while True:
            try:
                code = self.q.get_nowait()
            except queue.Empty:
                return True
            if not self._dispatch(code):
                return False

    def wait(self, timeout):
        try:
            code = self.q.get(timeout=0.05 if timeout is None else max(0.001, timeout))
        except queue.Empty:
            return True
        return self._dispatch(code)

    def pace(self):
        time.sleep(0.004)
        return "tick"

    def monitor_info(self, origin):
        if self.delay_open:
            time.sleep(self.delay_open)
        return super().monitor_info(origin)

    def destroy_windows(self):
        super().destroy_windows()
        self.q.put("quit")


class ThreadedTests(unittest.TestCase):
    def make(self, **kwargs):
        backend = ThreadedFakeBackend(**kwargs)
        capture = FakeCapture(backend)
        snap = FakeSnap()
        snap.backend = backend
        presenter = c.CarouselPresenter(None, None, None, backend=backend, capture=capture, snap=snap)
        return presenter, backend

    def test_real_thread_open_turn_exit_close(self):
        presenter, backend = self.make()
        started = time.perf_counter()
        presenter.show(snapshot(count=5, index=1))
        self.assertLess(time.perf_counter() - started, 0.15)
        self.assertEqual(presenter.rect, PANE)
        self.assertEqual(threading.current_thread().name, "MainThread")
        self.assertTrue(any(t.name == "NanoD-carousel" for t in threading.enumerate()))
        self.assertTrue(any(t.name == "NanoD-label" for t in threading.enumerate()))
        presenter.highlight(2)
        time.sleep(0.5)
        self.assertEqual(presenter._engine.machine.sel, 2)
        presenter.play_switch_exit()
        presenter.hide()
        time.sleep(0.6)
        self.assertEqual(backend.thumbs, {})
        self.assertIsNone(presenter.rect)
        started = time.perf_counter()
        self.assertTrue(presenter.close())
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertFalse(presenter._thread.is_alive())
        self.assertIn("unregister_classes", backend.names())

    def test_handshake_timeout_raises_within_the_bound_and_the_late_open_never_stays_up(self):
        presenter, backend = self.make(delay_open=0.35)
        started = time.perf_counter()
        with self.assertRaises(OSError):
            presenter.show(snapshot())
        elapsed = time.perf_counter() - started
        self.assertGreaterEqual(elapsed, 0.14)
        self.assertLess(elapsed, 0.3)
        time.sleep(0.6)
        self.assertNotIn("host", backend.visible)
        self.assertIsNone(presenter.rect)
        backend.delay_open = 0.0
        presenter.show(snapshot())
        self.assertEqual(presenter.rect, PANE)
        presenter.close()


class _Namespace:
    pass


class FakeApi:
    """A ctypes-level stand-in for CarouselApi: every export records its call and returns a
    plausible value; DIB sections get real memory. It has no compositor-clock export (``optional``
    empty), so the pacer falls back to DwmFlush."""

    EXPORTS = (
        ("u", ("RegisterClassExW", "UnregisterClassW", "CreateWindowExW", "DestroyWindow", "DefWindowProcW",
               "IsWindow", "IsWindowVisible", "ShowWindow", "SetWindowPos", "UpdateLayeredWindow",
               "UpdateLayeredWindowIndirect", "GetMessageW", "PeekMessageW", "TranslateMessage", "DispatchMessageW",
               "PostMessageW", "PostThreadMessageW", "PostQuitMessage", "MsgWaitForMultipleObjectsEx", "BeginPaint",
               "EndPaint", "InvalidateRect", "LoadCursorW", "GetDC", "ReleaseDC", "GetForegroundWindow",
               "SetForegroundWindow", "MonitorFromWindow", "MonitorFromPoint", "GetMonitorInfoW",
               "SetThreadDpiAwarenessContext", "GetThreadDpiAwarenessContext", "GetAwarenessFromDpiAwarenessContext",
               "SetWindowDisplayAffinity", "GetWindowThreadProcessId", "GetGuiResources", "FillRect",
               "SystemParametersInfoW", "SetLayeredWindowAttributes")),
        ("g", ("CreateCompatibleDC", "DeleteDC", "CreateDIBSection", "SelectObject", "DeleteObject", "GdiFlush",
               "BitBlt", "SetDIBitsToDevice", "GetStockObject", "SetDCBrushColor")),
        ("k", ("GetModuleHandleW", "GetCurrentThreadId", "GetCurrentThread", "GetCurrentProcess",
               "GetCurrentProcessId", "SetThreadPriority", "CreateEventW", "SetEvent", "CloseHandle",
               "CreateWaitableTimerExW", "SetWaitableTimer")),
        ("d", ("DwmRegisterThumbnail", "DwmUnregisterThumbnail", "DwmQueryThumbnailSourceSize",
               "DwmUpdateThumbnailProperties", "DwmSetWindowAttribute", "DwmFlush", "DwmGetCompositionTimingInfo")),
        ("sh", ("SHQueryUserNotificationState",)),
    )

    def __init__(self, fail_noredirection=False, monitor=(0, 0, 5120, 1440), work=(0, 0, 5120, 1392)):
        import ctypes
        self.C = ctypes
        self.calls = []
        self.fail_noredirection = fail_noredirection
        self.monitor = monitor
        self.work = work
        self.next = 0x1000
        self.buffers = {}
        self.live_gdi = set()
        self.visible = set()
        self.foreign = set()             # windows of another process
        self.dead = set()                # destroyed windows
        self.notification_state = 5
        self.optional = {}
        for dll, names in self.EXPORTS:
            namespace = _Namespace()
            setattr(self, dll, namespace)
            for name in names:
                setattr(namespace, name, self._export(name))

    def last_error(self):
        return 0

    def _handle(self):
        self.next += 1
        return self.next

    def _export(self, name):
        def call(*args):
            self.calls.append((name,) + args)
            handler = getattr(self, "_" + name, None)
            return handler(*args) if handler is not None else 1
        return call

    def of(self, name):
        return [call for call in self.calls if call[0] == name]

    # user32
    def _CreateWindowExW(self, ex, cls, title, style, x, y, w, h, owner, menu, inst, param):
        if self.fail_noredirection and ex & c.WS_EX_NOREDIRECTIONBITMAP:
            return None
        return self._handle()

    def _DefWindowProcW(self, *args):
        return 0

    def _PeekMessageW(self, *args):
        return 0

    def _GetMessageW(self, *args):
        return 1

    def _SetWindowPos(self, hwnd, after, x, y, w, h, flags):
        if flags & c.SWP_SHOWWINDOW:
            self.visible.add(hwnd)
        return 1

    def _ShowWindow(self, hwnd, cmd):
        if cmd == c.SW_HIDE:
            self.visible.discard(hwnd)
        return 1

    def _IsWindowVisible(self, hwnd):
        return int(hwnd in self.visible)

    def _IsWindow(self, hwnd):
        return int(hwnd not in self.dead)

    def _GetCurrentProcessId(self):
        return 4242

    def _GetWindowThreadProcessId(self, hwnd, out):
        out._obj.value = 777 if hwnd in self.foreign else 4242
        return 0x99

    def _GetMonitorInfoW(self, monitor, info):
        target = info._obj
        rc = target.rcMonitor
        rc.left, rc.top, rc.right, rc.bottom = self.monitor
        rc = target.rcWork
        rc.left, rc.top, rc.right, rc.bottom = self.work
        return 1

    def _GetAwarenessFromDpiAwarenessContext(self, context):
        return 2

    def _GetDC(self, hwnd):
        return 0x88

    def _GetGuiResources(self, process, kind):
        return len(self.live_gdi) if kind == 0 else 0

    def _CreateEventW(self, *args):
        return self._handle()

    def _SHQueryUserNotificationState(self, out):
        out._obj.value = self.notification_state
        return 0

    def _DwmGetCompositionTimingInfo(self, hwnd, info):
        return 1                                    # "not available": the pacer samples now

    # gdi32
    def _CreateCompatibleDC(self, hdc):
        handle = self._handle()
        self.live_gdi.add(handle)
        return handle

    def _DeleteDC(self, hdc):
        self.live_gdi.discard(hdc)
        return 1

    def _CreateDIBSection(self, hdc, bmi, usage, bits, section, offset):
        header = bmi._obj.bmiHeader
        size = header.biWidth * abs(header.biHeight) * 4
        buffer = (self.C.c_ubyte * size)()
        handle = self._handle()
        self.buffers[handle] = buffer
        self.live_gdi.add(handle)
        bits._obj.value = self.C.addressof(buffer)
        return handle

    def _SelectObject(self, hdc, obj):
        return 0x77

    def _DeleteObject(self, obj):
        self.live_gdi.discard(obj)
        self.buffers.pop(obj, None)
        return 1

    def _BitBlt(self, mdc, x, y, w, h, src, sx, sy, rop):
        for buffer in self.buffers.values():
            self.C.memset(buffer, 0x40, len(buffer))
        return 1

    # dwmapi
    def _DwmRegisterThumbnail(self, dest, src, out):
        out._obj.value = self._handle()
        return 0

    def _DwmUnregisterThumbnail(self, handle):
        return 0

    def _DwmQueryThumbnailSourceSize(self, handle, size):
        size._obj.cx, size._obj.cy = 1600, 1000
        return 0

    def _DwmUpdateThumbnailProperties(self, handle, props):
        p = props._obj
        self.calls[-1] = ("DwmUpdateThumbnailProperties", handle, p.flags,
                          (p.destination.left, p.destination.top, p.destination.right, p.destination.bottom),
                          (p.source.left, p.source.top, p.source.right, p.source.bottom), p.opacity, p.visible)
        return 0

    def _DwmSetWindowAttribute(self, hwnd, attribute, value, size):
        return 0

    def _DwmFlush(self):
        return 0


class Win32BackendTests(unittest.TestCase):
    """Win32CarouselBackend against FakeApi: styles, ownership, DIB and ULW use, input mapping,
    teardown order. No Win32 call is made."""

    ROLES = ("dim", "glass", "host", "chrome", "label", "dots", "toast")

    def make(self, **kwargs):
        self.api = FakeApi(**kwargs)
        self.events, self.inputs = [], []
        backend = c.Win32CarouselBackend(api=self.api)
        backend.prepare_thread()
        backend.create(self.events.append, lambda *args: self.inputs.append(args))
        self.addCleanup(backend.destroy)
        return backend

    def created(self):
        return {call[2]: call for call in self.api.of("CreateWindowExW") if call[1] is not None}

    def test_windows_styles_ownership_and_dwm_attributes(self):
        backend = self.make()
        self.assertEqual(backend.host_mode, c.HOST_LAYERED)
        created = self.created()
        w = backend.windows
        for role in ("dim", "glass", "chrome", "label", "dots", "toast"):
            self.assertEqual(created[c.CLASS_NAMES[role]][1], 0x080800A8)
        host_ex = created[c.CLASS_NAMES["host"]][1]
        self.assertTrue(host_ex & c.WS_EX_NOREDIRECTIONBITMAP and host_ex & c.WS_EX_TOPMOST)
        self.assertFalse(host_ex & (c.WS_EX_NOACTIVATE | c.WS_EX_LAYERED | c.WS_EX_TRANSPARENT))
        owners = {name: call[9] for name, call in created.items()}
        self.assertEqual(owners[c.CLASS_NAMES["glass"]], w["dim"])
        self.assertEqual(owners[c.CLASS_NAMES["host"]], w["glass"])
        self.assertEqual(owners[c.CLASS_NAMES["chrome"]], w["host"])
        self.assertEqual(owners[c.CLASS_NAMES["label"]], w["chrome"])
        self.assertEqual(owners[c.CLASS_NAMES["dots"]], w["chrome"])
        self.assertIsNone(owners[c.CLASS_NAMES["toast"]])
        # step 3 (CAR 12.4): the GPU chrome's window is click-through, never activating, a
        # NOREDIRECTIONBITMAP DirectComposition target owned by the host, with its layered alpha set
        self.assertEqual(created[c.CLASS_NAMES["gpu"]][1], 0x082800A8)
        self.assertEqual(owners[c.CLASS_NAMES["gpu"]], w["host"])
        self.assertEqual(self.api.of("SetLayeredWindowAttributes")[-1][1:], (w["gpu"], 0, 255, c.LWA_ALPHA))
        self.assertEqual(c._WINDOW_HANDLERS[w["gpu"]](c.WM_NCHITTEST, 0, 0), c.HTTRANSPARENT)
        self.assertEqual(c._WINDOW_HANDLERS[w["gpu"]](c.WM_MOUSEACTIVATE, 0, 0), c.MA_NOACTIVATE)
        self.assertTrue(all(call[4] == c.WS_POPUP for call in created.values()))       # never WS_VISIBLE
        attributes = self.api.of("DwmSetWindowAttribute")
        forced = {call[1] for call in attributes if call[2] == c.DWMWA_TRANSITIONS_FORCEDISABLED}
        self.assertEqual(forced, set(w.values()))
        self.assertIn(w["host"], {call[1] for call in attributes if call[2] == c.DWMWA_WINDOW_CORNER_PREFERENCE})
        self.assertEqual(len(self.api.of("RegisterClassExW")), 8)
        self.assertEqual(self.api.of("SetThreadPriority")[-1][2], c.THREAD_PRIORITY_ABOVE_NORMAL)   # P13
        self.assertEqual(self.api.of("SetForegroundWindow"), [])

    def test_has_gpu_window_reports_the_window_not_the_method(self):
        """CAR 12.4 / WP7c-R7: the engine asks ``has_gpu_window``; when the chrome's window could not be
        made (its layered alpha refused here) it is False while the ``gpu_window`` method still exists
        and returns None."""
        backend = self.make()
        self.assertTrue(backend.has_gpu_window)
        api = FakeApi()
        api._SetLayeredWindowAttributes = lambda *args: 0
        broken = c.Win32CarouselBackend(api=api)
        broken.prepare_thread()
        broken.create(lambda *a: None, lambda *a: None)
        self.addCleanup(broken.destroy)
        self.assertNotIn("gpu", broken.windows)
        self.assertFalse(broken.has_gpu_window)
        self.assertTrue(callable(broken.gpu_window))
        self.assertIsNone(broken.gpu_window((0, 0, 64, 64)))

    def test_plain_host_fallback_when_noredirection_fails(self):
        backend = self.make(fail_noredirection=True)
        self.assertEqual(backend.host_mode, c.HOST_PLAIN)
        host = [call for call in self.api.of("CreateWindowExW") if call[2] == c.CLASS_NAMES["host"]][-1]
        self.assertEqual(host[1], c.PLAIN_HOST_EX_STYLE)
        self.assertEqual(host[9], backend.windows["dim"])
        handler = c._WINDOW_HANDLERS[backend.windows["host"]]
        self.assertEqual(handler(c.WM_PAINT, 0, 0), 0)
        self.assertEqual(self.api.of("SetDIBitsToDevice"), [])
        self.assertEqual(self.api.of("GetStockObject")[-1][1], c.DC_BRUSH)
        r, g, b = R.opaque_pane_rgb()
        self.assertEqual(self.api.of("SetDCBrushColor")[-1][2], r | (g << 8) | (b << 16))
        self.assertEqual(len(self.api.of("FillRect")), 1)
        frost = R.frost_canvas(Image.new("RGB", (64, 32), (90, 110, 140)), 1.0)
        backend.host_paint(frost)
        self.assertEqual(handler(c.WM_PAINT, 0, 0), 0)
        paint = self.api.of("SetDIBitsToDevice")[-1]
        self.assertEqual((paint[4], paint[5]), (64, 32))
        self.assertEqual(backend._host_paint[0], frost.image.tobytes())
        backend.free_large()
        handler(c.WM_PAINT, 0, 0)
        self.assertEqual(len(self.api.of("FillRect")), 2)

    def test_use_layered_host_leaves_the_fallback_or_stays_plain(self):
        backend = self.make(fail_noredirection=True)
        old = dict(backend.windows)
        self.assertFalse(backend.use_layered_host())             # still failing: a plain host again
        self.assertEqual(backend.host_mode, c.HOST_PLAIN)
        destroyed = [call[1] for call in self.api.of("DestroyWindow")]
        # the plain host (NOREDIRECTIONBITMAP failing) has no GPU chrome window either (CAR 12.4)
        self.assertNotIn("gpu", old)
        self.assertEqual(destroyed, [old["label"], old["dots"], old["chrome"], old["host"]])
        self.api.fail_noredirection = False
        plain = dict(backend.windows)
        self.assertTrue(backend.use_layered_host())
        self.assertEqual(backend.host_mode, c.HOST_LAYERED)
        host = [call for call in self.api.of("CreateWindowExW") if call[2] == c.CLASS_NAMES["host"]][-1]
        self.assertEqual((host[1], host[9]), (c.HOST_EX_STYLE, backend.windows["glass"]))
        chrome = [call for call in self.api.of("CreateWindowExW") if call[2] == c.CLASS_NAMES["chrome"]][-1]
        self.assertEqual(chrome[9], backend.windows["host"])
        self.assertNotEqual(backend.windows["host"], plain["host"])
        self.assertNotIn(plain["host"], c._WINDOW_HANDLERS)
        self.assertEqual((backend.windows["dim"], backend.windows["glass"]), (old["dim"], old["glass"]))

    def test_host_activation_wakes_the_loop_and_display_changes_are_events(self):
        backend = self.make()
        host = c._WINDOW_HANDLERS[backend.windows["host"]]
        dim = c._WINDOW_HANDLERS[backend.windows["dim"]]
        self.assertIsNone(host(c.WM_ACTIVATE, 1, 0))                    # WA_ACTIVE; DefWindowProc runs
        self.assertEqual(self.api.of("PostMessageW")[-1][1:], (backend.windows["dim"], c.WM_APP_ACTIVATED, 0, 0))
        self.assertEqual(self.api.of("SetEvent")[-1][1], backend.event, "the compositor-clock wait wakes too")
        posts = len(self.api.of("PostMessageW"))
        host(c.WM_ACTIVATE, c.WA_INACTIVE, 0)
        backend.set_host_passive(True)
        host(c.WM_ACTIVATE, 2, 0)                                        # WA_CLICKACTIVE while exiting
        self.assertEqual(len(self.api.of("PostMessageW")), posts)
        self.assertEqual(dim(c.WM_APP_ACTIVATED, 0, 0), 0)
        self.assertEqual(dim(c.WM_APP_SNAP, 0, 0), 0)
        self.assertIsNone(dim(c.WM_DISPLAYCHANGE, 32, 0))
        self.assertIsNone(dim(c.WM_DWMCOMPOSITIONCHANGED, 0, 0))
        self.assertEqual(dim(c.WM_POWERBROADCAST, c.PBT_APMRESUMEAUTOMATIC, 0), 1)
        self.assertEqual(dim(c.WM_POWERBROADCAST, c.PBT_APMSUSPEND, 0), 1)
        self.assertEqual(self.events, [c.EV_ACTIVATED, c.EV_SNAP, c.EV_DISPLAY, c.EV_DISPLAY, c.EV_DISPLAY,
                                       c.EV_SUSPEND])

    def test_show_host_places_on_rcmonitor_without_activating(self):
        backend = self.make()
        self.assertTrue(backend.show_host((0, 0, 5120, 1440)))
        call = self.api.of("SetWindowPos")[-1]
        self.assertEqual(call[1:7], (backend.windows["host"], c.HWND_TOPMOST, 0, 0, 5120, 1440))
        self.assertEqual(call[7], c.SWP_NOACTIVATE | c.SWP_SHOWWINDOW)
        self.assertEqual(backend.monitor_info(0x1234), ((0, 0, 5120, 1440), (0, 0, 5120, 1392)))
        self.assertEqual(self.api.of("MonitorFromWindow")[-1][1:], (0x1234, c.MONITOR_DEFAULTTONEAREST))

    def test_the_host_eats_clicks_everywhere_and_refocuses_only_when_it_lost_the_foreground(self):
        backend = self.make()
        host = c._WINDOW_HANDLERS[backend.windows["host"]]
        self.assertEqual(host(c.WM_NCHITTEST, 0, 0), c.HTCLIENT)            # K4 3: eats clicks anywhere
        backend.set_host_passive(True)
        self.assertEqual(host(c.WM_NCHITTEST, 0, 0), c.HTCLIENT)            # also during the exit
        self.assertEqual(host(c.WM_MOUSEACTIVATE, 0, 0), c.MA_NOACTIVATEANDEAT)
        backend.set_host_passive(False)
        self.api._GetForegroundWindow = lambda: 0x1234                     # ours
        self.assertTrue(backend.refocus_host())
        self.assertEqual(self.api.of("SetForegroundWindow"), [])
        self.api.foreign.add(0x9001)
        self.api._GetForegroundWindow = lambda: 0x9001
        backend.refocus_host()
        self.assertEqual(self.api.of("SetForegroundWindow")[-1][1], backend.windows["host"])

    def test_chrome_presents_a_dirty_rect_through_the_indirect_update(self):
        backend = self.make()
        canvas = backend.chrome_alloc((10, 20, 300, 400))
        canvas.fill((0, 0, 1, 1), (255, 0, 0), 1.0)
        surface = backend.surfaces["chrome"]
        buffer = self.api.buffers[surface.dib]
        self.assertEqual(bytes(buffer[:4]), bytes((0, 0, 255, 255)))       # B, G, R, A
        self.assertTrue(backend.chrome_present())
        ulw = self.api.of("UpdateLayeredWindow")[-1]
        self.assertEqual(ulw[1], backend.windows["chrome"])
        self.assertEqual((ulw[3]._obj.x, ulw[3]._obj.y, ulw[4]._obj.cx, ulw[4]._obj.cy), (10, 20, 300, 400))
        self.assertTrue(backend.chrome_present((5, 6, 50, 60)))           # B5
        indirect = self.api.of("UpdateLayeredWindowIndirect")[-1]
        info = indirect[2]._obj
        dirty = info.prcDirty.contents
        self.assertEqual((dirty.left, dirty.top, dirty.right, dirty.bottom), (5, 6, 50, 60))
        self.assertEqual(info.hdcSrc, surface.mdc)
        backend.chrome_free()
        self.assertIsNone(backend.chrome_canvas())

    def test_the_label_and_dots_layers_upload_and_move(self):
        backend = self.make()
        canvas = backend.layer_alloc("label", (0, 1008, 2560, 200))
        canvas.fill((0, 0, 2, 2), (255, 255, 255), 1.0)
        backend.layer_present("label", 128, (0, 920))
        ulw = self.api.of("UpdateLayeredWindow")[-1]
        self.assertEqual((ulw[1], ulw[3]._obj.x, ulw[3]._obj.y), (backend.windows["label"], 0, 920))
        self.assertEqual(ulw[8]._obj.SourceConstantAlpha, 128)
        backend.layer_alpha("label", 200, (0, 1000))
        ulw = self.api.of("UpdateLayeredWindow")[-1]
        self.assertEqual((ulw[3]._obj.x, ulw[3]._obj.y, ulw[4], ulw[5]), (0, 1000, None, None))
        self.assertEqual(ulw[8]._obj.SourceConstantAlpha, 200)
        backend.layer_free("label")
        self.assertIsNone(backend.layer_canvas("label"))

    def test_dim_and_glass_upload_once_free_their_dibs_and_fade_by_constant_alpha(self):
        backend = self.make(monitor=(0, 0, 1280, 720))
        layout = R.layout_for((0, 0, 1280, 720))
        baseline = set(self.api.live_gdi)
        backend.dim_upload(layout, "none")
        self.assertEqual(self.api.live_gdi, baseline)                        # freed right after the upload
        backend.dim_alpha(128)
        ulw = self.api.of("UpdateLayeredWindow")[-1]
        self.assertEqual(ulw[1], backend.windows["dim"])
        self.assertEqual(ulw[2:7], (None, None, None, None, None))           # no new content
        self.assertEqual(ulw[8]._obj.SourceConstantAlpha, 128)
        monitor = layout.monitor_rect
        frost = R.frost_canvas(Image.new("RGB", monitor[2:], (90, 110, 140)), 1.0)
        mark = len(self.api.calls)
        backend.glass_upload(monitor, frost)
        self.assertEqual(self.api.live_gdi, baseline)
        self.assertIn(backend.windows["glass"], self.api.visible)
        calls = self.api.calls[mark:]
        ulw = [call for call in calls if call[0] == "UpdateLayeredWindow"][-1]
        self.assertEqual(ulw[1], backend.windows["glass"])
        self.assertEqual((ulw[3]._obj.x, ulw[3]._obj.y, ulw[4]._obj.cx, ulw[4]._obj.cy), monitor)
        self.assertEqual(ulw[8]._obj.SourceConstantAlpha, 0, "uploaded at alpha 0, then faded in")
        with self.assertRaises(OSError):
            backend.glass_upload(monitor, R.solid_frost((10, 10)))
        self.assertEqual(self.api.live_gdi, baseline)

    def test_thumbnail_calls_send_all_five_flags(self):
        backend = self.make()
        handle = backend.register(0x999)
        self.assertEqual(self.api.of("DwmRegisterThumbnail")[-1][1:3], (backend.windows["host"], 0x999))
        self.assertEqual(backend.source_size(handle), (1600, 1000))
        self.assertTrue(backend.update_thumbnail(handle, (1, 2, 3, 4), (0, 0, 10, 20), 200, True))
        call = self.api.of("DwmUpdateThumbnailProperties")[-1]
        self.assertEqual(call[2:], (0x1F, (1, 2, 3, 4), (0, 0, 10, 20), 200, 1))
        backend.unregister(handle)
        self.assertEqual(self.api.of("DwmUnregisterThumbnail")[-1][1], handle)
        self.assertIsNone(backend.register(0))

    def test_window_procedures_map_input(self):
        backend = self.make()
        host = c._WINDOW_HANDLERS[backend.windows["host"]]
        dim = c._WINDOW_HANDLERS[backend.windows["dim"]]
        chrome = c._WINDOW_HANDLERS[backend.windows["chrome"]]
        label = c._WINDOW_HANDLERS[backend.windows["label"]]
        self.assertEqual(host(c.WM_KEYDOWN, c.VK_RETURN, 1 << 30), 0)
        self.assertEqual(host(c.WM_MOUSEWHEEL, (0xFF88 << 16), 0), 0)        # -120
        self.assertEqual(host(c.WM_LBUTTONUP, 0, (20 << 16) | 0xFFFE), 0)    # x = -2, y = 20
        self.assertEqual(host(c.WM_CLOSE, 0, 0), 0)
        self.assertIsNone(host(c.WM_MOUSEACTIVATE, 0, 0))
        self.assertEqual(self.inputs, [(c.IN_KEY, c.VK_RETURN, 1), (c.IN_WHEEL, -120), (c.IN_CLICK, -2, 20),
                                       (c.IN_CLOSE,)])
        backend.set_host_passive(True)
        host(c.WM_KEYDOWN, c.VK_ESCAPE, 0)
        self.assertEqual(len(self.inputs), 4)                                # no input while exiting
        for layer in (dim, chrome, label):
            self.assertEqual(layer(c.WM_NCHITTEST, 0, 0), c.HTTRANSPARENT)
            self.assertEqual(layer(c.WM_MOUSEACTIVATE, 0, 0), c.MA_NOACTIVATE)
        self.assertEqual(dim(c.WM_APP_OPEN, 0, 0), 0)
        self.assertEqual(self.events, [c.EV_OPEN])
        self.assertIsNone(chrome(c.WM_APP_OPEN, 0, 0))                       # only the dim is the target

    def test_a_click_never_takes_the_foreground_back_from_another_process(self):
        backend = self.make()
        host = c._WINDOW_HANDLERS[backend.windows["host"]]
        foreground = {"hwnd": 0x1234}
        self.api._GetForegroundWindow = lambda: foreground["hwnd"]
        self.assertIsNone(host(c.WM_MOUSEACTIVATE, 0, 0))              # our own window (the Control Center)
        self.api.foreign.add(0x9001)
        foreground["hwnd"] = 0x9001                                      # the Switch target has it
        self.assertEqual(host(c.WM_MOUSEACTIVATE, 0, 0), c.MA_NOACTIVATEANDEAT)
        foreground["hwnd"] = 0                                           # mid-activation: nobody
        self.assertEqual(host(c.WM_MOUSEACTIVATE, 0, 0), c.MA_NOACTIVATEANDEAT)
        self.assertEqual(self.inputs, [])

    def test_hidden_layers_give_back_their_retained_surfaces(self):
        backend = self.make(monitor=(0, 0, 1280, 720))
        layout = R.layout_for((0, 0, 1280, 720))
        baseline = set(self.api.live_gdi)
        backend.hide_layers()
        self.assertEqual(self.api.of("UpdateLayeredWindow"), [])        # nothing uploaded yet: nothing held
        backend.dim_upload(layout, "none")
        backend.chrome_alloc(layout.band)
        backend.chrome_present()
        backend.layer_alloc("label", layout.labels)
        backend.layer_present("label", 255, layout.labels[:2])
        backend.glass_upload(layout.monitor_rect, R.solid_frost(layout.monitor_rect[2:]))
        backend.chrome_free()
        backend.layer_free("label")
        mark = len(self.api.calls)
        backend.hide_layers()
        calls = self.api.calls[mark:]
        ulw = [call for call in calls if call[0] == "UpdateLayeredWindow"]
        self.assertEqual([call[1] for call in ulw], [backend.windows[r] for r in ("chrome", "label", "glass", "dim")])
        for call in ulw:
            self.assertEqual((call[4]._obj.cx, call[4]._obj.cy), (1, 1))
            self.assertEqual(call[8]._obj.SourceConstantAlpha, 0)
        hidden = [i for i, call in enumerate(calls) if call[0] == "ShowWindow"]
        self.assertEqual(len(hidden), 7)                                   # the GPU chrome's window too
        self.assertLess(max(hidden), calls.index(ulw[0]))                  # hidden first
        self.assertEqual(self.api.live_gdi, baseline)

    def test_the_thunk_never_unwinds_into_user32(self):
        backend = self.make()
        hwnd = backend.windows["toast"]
        saved = c._WINDOW_HANDLERS[hwnd]
        c._WINDOW_HANDLERS[hwnd] = lambda *args: 1 / 0
        try:
            self.assertEqual(c._window_procedure(hwnd, 0x1234, 0, 0), 0)
        finally:
            c._WINDOW_HANDLERS[hwnd] = saved

    def test_capture_releases_every_gdi_object(self):
        backend = self.make()
        baseline = set(self.api.live_gdi)
        buffers = set(self.api.buffers)
        image = backend.capture((5, 6, 8, 4))
        self.assertEqual((image.size, image.mode), ((8, 4), "RGB"))
        self.assertEqual(image.getpixel((0, 0)), (0x40, 0x40, 0x40))
        self.assertFalse(getattr(image, "readonly", 0))
        self.assertEqual(set(self.api.buffers), buffers, "the capture DIB is gone")
        self.assertEqual(self.api.live_gdi, baseline)
        self.assertEqual(self.api.of("BitBlt")[-1][9], c.SRCCOPY | c.CAPTUREBLT)
        self.assertIsNone(backend.capture((0, 0, 0, 5)))

    def test_affinity_toast_and_teardown_order(self):
        backend = self.make()
        backend.set_affinity(True)
        values = {call[1]: call[2] for call in self.api.of("SetWindowDisplayAffinity")}
        self.assertEqual(set(values.values()), {c.WDA_EXCLUDEFROMCAPTURE})
        self.assertEqual(set(values), {backend.windows[r] for r in ("dim", "glass", "host", "chrome", "label", "dots",
                                                                    "gpu")})
        backend.toast_alloc((100, 100, 40, 20))
        backend.toast_present(128)
        backend.toast_show()
        backend.chrome_alloc((0, 0, 1024, 512))                  # > 1 MB
        mark = len(self.api.calls)
        backend.hide_layers()
        hidden = [call[1] for call in self.api.calls[mark:] if call[0] == "ShowWindow"]
        self.assertEqual(hidden, [backend.windows[r] for r in ("gpu", "chrome", "label", "dots", "host", "glass",
                                                               "dim")])
        backend.free_large()
        self.assertIsNone(backend.chrome_canvas())
        self.assertIsNotNone(backend.toast_canvas())             # small: kept until the toast ends
        windows = dict(backend.windows)
        event = backend.event
        backend.destroy_windows()
        destroyed = [call[1] for call in self.api.of("DestroyWindow")]
        self.assertEqual(destroyed, [windows[r] for r in ("toast", "gpu", "label", "dots", "chrome", "host", "glass",
                                                          "dim")])
        self.assertEqual(self.api.live_gdi, set())
        self.assertIn(("CloseHandle", event), self.api.calls)
        self.assertFalse(any(hwnd in c._WINDOW_HANDLERS for hwnd in windows.values()))
        backend.unregister_classes()
        self.assertEqual(len(self.api.of("UnregisterClassW")), 8)

    def test_capture_exclusions_touch_only_live_windows_of_this_process(self):
        backend = self.make()
        self.api.foreign.add(0x9001)
        self.api.dead.add(0x9002)
        mark = len(self.api.calls)
        self.assertTrue(backend.set_capture_exclusions((0x7001, 0x9001, 0x9002, 0), True))
        affinity = [call[1:] for call in self.api.calls[mark:] if call[0] == "SetWindowDisplayAffinity"]
        self.assertEqual(affinity, [(0x7001, c.WDA_EXCLUDEFROMCAPTURE)])

    def test_pacing_falls_back_to_dwmflush_without_the_compositor_clock(self):
        backend = self.make()
        self.assertEqual(backend.pace(), "tick")
        self.assertEqual(len(self.api.of("DwmFlush")), 1)
        self.assertEqual(backend.frame_target(12.5), 12.5, "no timing info: sample now")

    def test_the_idle_wait_is_a_message_wait_on_the_mailbox_event_never_a_timer(self):
        backend = self.make()
        backend.wait(0.25)
        call = self.api.of("MsgWaitForMultipleObjectsEx")[-1]
        self.assertEqual((call[1], call[3], call[4]), (1, 250, c.QS_ALLINPUT))
        backend.wait(None)
        self.assertEqual(self.api.of("MsgWaitForMultipleObjectsEx")[-1][3], c.INFINITE)

    def test_notification_state_and_reduced_motion_queries(self):
        backend = self.make()
        self.assertFalse(backend.notification_busy())
        self.api.notification_state = 3
        self.assertTrue(backend.notification_busy())
        self.api.notification_state = 4
        self.assertTrue(backend.notification_busy())
        self.assertFalse(backend.system_reduced_motion())       # the fake leaves the BOOL at 1 (animations on)

    def test_structure_sizes_are_the_x64_layout(self):
        import ctypes
        for structure, size in c.STRUCTURE_SIZES_X64.items():
            self.assertEqual(ctypes.sizeof(structure), size, structure.__name__)
        self.assertEqual(c.LAYER_EX_STYLE, 0x080800A8)


if __name__ == "__main__":
    unittest.main()

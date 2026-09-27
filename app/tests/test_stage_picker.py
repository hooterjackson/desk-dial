"""The window picker's GPU chrome, step 3 (DESKTOP_STAGE §9.9, §22 Q2, §6.6 H1/H4/H6/H7; lead ruling R-h;
CAROUSEL.md §12.4).

The production ``CarouselPresenter`` runs inline on the presenter tests' fake backend (plus the GPU
chrome's window methods), a fake NanoD-snap and one fake clock that both the carousel (seconds) and
the stage's fake device (ticks) read. The chrome (``control_center.stage.picker_chrome``) records
every DirectComposition call on the fake device; the reference renderer evaluates the animations it
recorded, i.e. what DWM would run. Nothing is shown and no window is created; the native tests make
a device without a target (skipped where none can be made).

Covered: the GPU path replaces the CPU band and layers; every chrome property mirrors the machine's
tween at every frame (H7-style, within §4.6.2's fit bounds), so the chrome's card rect equals the
thumbnail's rect the engine sends (the headless half of AR-12); the clips follow the nearer card's
far edge; z-order far -> near; one Commit per event and none without a change; detents never upload;
labels swap only once their surface is ready; the fly's shadow (S5-4 returns); the exit and the
teardown; device loss mid-open falls back to the CPU chrome at once and the next open retries; the
CPU switch (setting, environment), the plain host and a missing chrome window keep the CPU chrome;
the device's idle release and the knob-touch warm-up; parity with compose_chrome at rest (H4);
the clip slots and the context flush on the native device (H6). ``ReviewFixTests``: the WP7c review's
findings R1-R7 (the device policy after a monitor change or a non-loss failure, a loss in a quiet
frame's upload, sprites that arrive at rest, the pool grown in quiet frames, the close unbinding the
label and the faces, the knob touch's device made off the carousel thread, a missing chrome window);
the native two-half device on two threads.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for path in (ROOT, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PIL import Image, ImageChops  # noqa: E402

from control_center import carousel as c  # noqa: E402
from control_center import carousel_render as R  # noqa: E402
from control_center.stage import com  # noqa: E402
from control_center.stage import picker_chrome as PC  # noqa: E402
from control_center.stage import picker_testing as PT  # noqa: E402
import test_carousel_presenter as T  # noqa: E402

M32 = ((0, 0, 5120, 1440), (0, 0, 5120, 1392))
M16 = ((0, 0, 2560, 1440), (0, 0, 2560, 1392))
DT = 1 / 240.0
OFFSET_TOL = 0.6               # px: the fit bound (0.45) plus float32 slack
OPACITY_TOL = 0.003
SCALE_TOL = 0.0015


class GpuBackend(T.FakeBackend):
    """The presenter tests' recording backend plus the GPU chrome's window. ``gpu_window=False``
    models Win32 when the window could not be made: ``has_gpu_window`` is False and the method
    still exists (it returns None)."""

    def __init__(self, *args, gpu_window=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.window_exists = bool(gpu_window)
        self.gpu_rects = []

    @property
    def has_gpu_window(self):
        return self.window_exists

    def gpu_window(self, rect):
        self.log("gpu_window", tuple(rect))
        if not self.window_exists:
            return None
        self.gpu_rects.append(tuple(rect))
        return 0x6001

    def gpu_show(self):
        self.log("show", "gpu")
        self.visible.add("gpu")

    def gpu_hide(self):
        self.log("hide", "gpu")
        self.visible.discard("gpu")

    def hide_layers(self):
        super().hide_layers()
        self.visible.discard("gpu")


class Rig:
    def __init__(self, test, monitor=M32, chrome="fake", backend_kw=None, environ=None, keep_pixels=False,
                 chrome_kw=None):
        self.clock = PT.SharedClock()
        self.backend = GpuBackend(monitor=monitor[0], work=monitor[1], **(backend_kw or {}))
        self.backend.clock = self.clock
        self.capture = T.FakeCapture(self.backend)
        self.snapper = T.FakeSnap()
        self.snapper.backend = self.backend
        if chrome == "fake":
            self.chrome = PT.fake_chrome(self.clock, keep_pixels=keep_pixels, **(chrome_kw or {}))
            self.chrome.prewarm_step(None)
        else:
            self.chrome = chrome
        self.presenter = c.CarouselPresenter(None, None, lambda: None, backend=self.backend, capture=self.capture,
                                             snap=self.snapper, clock=self.clock, inline=True,
                                             gpu_chrome=self.chrome, environ=environ or {})
        self.engine = self.presenter._engine
        test.addCleanup(self.presenter.close)
        self.samples = []

    @property
    def dev(self):
        return self.chrome.devices[-1]

    def step(self, seconds, dt=DT, check=None):
        end = self.clock.t + seconds
        self.presenter._step_inline()
        if check:
            check()
        while self.clock.t < end - 1e-9:
            self.clock.advance(min(dt, end - self.clock.t))
            self.presenter._step_inline()
            if check:
                check()

    def open(self, count=12, index=4, glass=True, settle=0.6, check=None, snap=None):
        self.presenter.show(snap or T.snapshot(count=count, index=index))
        self.backend.activate()
        self.step(0)
        if glass and self.capture.jobs:
            self.capture.complete()
        self.step(settle, check=check)

    def snap(self, index, side, place=True, check=None):
        p = self.presenter
        p.snap({"t0": self.clock.t, "index": index, "side": side, "target_rect": None, "place_at_ms": 360,
                "item": {"id": f"w{index}", "hwnd": 100 + index, "pid": 20}})
        self.step(DT, check=check)
        job = self.snapper.jobs[-1]
        self.snapper.answer(job, "precheck", "accepted")
        self.step(0.36, check=check)
        if place:
            self.snapper.answer(job, "final", "ok", {"rect": job.target})
        return job


def ref_value(rig, oid, prop, default):
    """The value DWM would sample now from what the fake device recorded (the reference renderer)."""
    cls = PT.reference_renderer()
    r = cls(rig.dev, rig.chrome.clock.freq)
    return float(r.value(oid, prop, rig.clock.dev(), default))


def machine_frame(rig):
    return rig.engine.machine.values(rig.clock.t)


class MirrorChecker:
    """Compares every slotted card's and the group's chrome properties (as recorded) with the machine
    at the current frame time; collects the worst errors."""

    def __init__(self, rig, test):
        self.rig, self.test = rig, test
        self.worst = {"offset": 0.0, "opacity": 0.0, "scale": 0.0, "rect": 0.0}
        self.checked = 0

    def note(self, kind, err):
        self.worst[kind] = max(self.worst[kind], abs(err))

    def __call__(self):
        rig = self.rig
        s = rig.engine.session
        ch = rig.chrome
        if s is None or not s.gpu or not s.gpu_synced or not ch.active:
            return
        m = rig.engine.machine
        t = rig.clock.t
        k = ch.k
        v = lambda oid, prop, d: ref_value(rig, oid, prop, d)
        self.note("opacity", v(ch.root.ref.v3, "opacity", 1.0) - m.root.value(t))
        self.note("opacity", v(ch.group.ref.v3, "opacity", 1.0) - m.group.value(t))
        self.note("offset", v(ch.group.ptr, "offset_y", 0.0) - m.shift.value(t) * k)
        bump = machine_frame(rig).bump
        self.note("offset", v(ch.cards.ptr, "offset_x", 0.0) - bump * k)
        ax = ch.hx0 + R.CENTER_X * k
        w0, h0 = R.card_box_px(k)
        for index, slot in ch.by_index.items():
            tw = m.cards.get(index)
            if tw is None:
                continue
            f = R.CLOSED_OPACITY if index in m.closed else 1.0
            self.note("offset", v(slot.pos.ptr, "offset_x", 0.0) - (ax + k * tw.x.value(t)))
            self.note("opacity", v(slot.pos.ref.v3, "opacity", 1.0) - f * tw.op.value(t))
            sv = v(slot.sc.transform, "scale_x", 1.0)
            ev = v(slot.es.transform, "scale_x", 1.0)
            self.note("scale", sv - tw.s.value(t))
            self.note("scale", ev - tw.escale.value(t))
            self.note("offset", v(slot.rise.ptr, "offset_y", 0.0) - tw.rise.value(t) * k)
            self.note("opacity", v(slot.side.ref.v3, "opacity", 1.0) - (1.0 - tw.selw.value(t)))
            self.note("opacity", v(slot.focus.ref.v3, "opacity", 1.0) - tw.selw.value(t))
            self.note("opacity", v(slot.frame.ref.v3, "opacity", 1.0) - R.OUTLINE_ALPHA * tw.selw.value(t))
            self.note("opacity", v(slot.shade.ref.v3, "opacity", 1.0) - tw.shade.value(t))
            # the chrome's card box against the rect the engine sends the card's thumbnail (AR-12's
            # headless half: both from the same curves at the same time)
            rect = s.rects.get(index)
            if rect is not None:
                cx = v(ch.cards.ptr, "offset_x", 0.0) + v(slot.pos.ptr, "offset_x", 0.0)
                cy = (v(ch.group.ptr, "offset_y", 0.0) + ch.hy0 + R.CENTER_Y * k
                      + v(slot.rise.ptr, "offset_y", 0.0) * sv)
                half_w, half_h = w0 / 2.0 * sv * ev, h0 / 2.0 * sv * ev
                box = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
                self.note("rect", max(abs(a - b) for a, b in zip(box, rect)))
        self.checked += 1


class GpuPathTests(unittest.TestCase):
    def tearDown(self):
        c.install_gpu_chrome(None)

    def test_an_open_uses_the_gpu_chrome_and_never_the_cpu_band_or_layers(self):
        rig = Rig(self)
        rig.open()
        p, b = rig.presenter, rig.backend
        self.assertEqual(p.chrome, "gpu")
        names = b.names()
        for heavy in ("chrome_alloc", "layer_alloc", "chrome_present", "layer_present"):
            self.assertNotIn(heavy, names, heavy)
        self.assertEqual(b.gpu_rects, [(0, 0, 5120, 1440)])                   # rcMonitor (K4 9.2)
        self.assertIn("gpu", b.visible)
        self.assertLess(names.index("activated"), names.index("gpu_window"))   # after the focus handshake
        self.assertTrue(rig.chrome.active)
        self.assertEqual(rig.dev.violations, [])
        modes = rig.chrome.tree.mode_calls
        self.assertIn(("interp", com.DCOMPOSITION_BITMAP_INTERPOLATION_MODE_LINEAR), modes)     # AR-8
        self.assertIn(("border", com.DCOMPOSITION_BORDER_MODE_SOFT), modes)
        self.assertNotIn(("interp", com.FORBIDDEN_INTERPOLATION), modes)
        self.assertNotIn(("border", com.FORBIDDEN_BORDER), modes)
        m = p.metrics()
        self.assertEqual((m["chrome"], m["gpu_sessions"], m["gpu_fallbacks"]), ("gpu", 1, 0))
        self.assertEqual(m["gpu"]["sessions"], 1)
        frames = m["frames"]
        self.assertIn("picker", frames)

    def test_every_chrome_property_mirrors_the_machine_and_the_card_box_tracks_the_thumbnail(self):
        """H7 / AR-12 (headless): at every frame of an open, fast and slow turns, an end bump, a snap
        (tray reveal) and the exit, what DWM would sample equals the machine's value within the fit
        bounds, and the chrome's card box equals the thumbnail rect within rounding."""
        rig = Rig(self)
        check = MirrorChecker(rig, self)
        rig.open(count=14, index=3, check=check)
        index = 3
        for i in range(8):                               # ~20 detents/s, retargets mid-flight
            index += 1
            rig.presenter.highlight(index)
            rig.step(0.05, check=check)
        for i in range(4):                               # slower, back
            index -= 1
            rig.presenter.highlight(index)
            rig.step(0.2, check=check)
        rig.presenter.highlight(0)                       # a long move
        rig.step(0.6, check=check)
        rig.presenter.highlight(0, bump=-1)              # the end bump (two legs)
        rig.step(0.5, check=check)
        rig.snap(2, "left", check=check)
        rig.step(0.6, check=check)
        rig.presenter.play_cancel_exit()
        rig.step(0.3, check=check)
        self.assertGreater(check.checked, 500)
        w = check.worst
        self.assertLessEqual(w["offset"], OFFSET_TOL, w)
        self.assertLessEqual(w["opacity"], OPACITY_TOL, w)
        self.assertLessEqual(w["scale"], SCALE_TOL, w)
        self.assertLessEqual(w["rect"], 1.5, w)          # integer thumbnail rects vs the continuous box
        self.assertEqual(rig.dev.violations, [])

    def test_the_mirror_holds_on_the_16_9_table_and_under_reduced_motion(self):
        rig = Rig(self, monitor=M16)
        rig.presenter.set_reduced_motion(True)
        check = MirrorChecker(rig, self)
        rig.open(count=9, index=4, check=check)
        for index in (5, 6, 5, 4, 3):
            rig.presenter.highlight(index)
            rig.step(0.12, check=check)
        rig.step(0.4, check=check)
        w = check.worst
        self.assertLessEqual(w["offset"], OFFSET_TOL, w)
        self.assertLessEqual(w["opacity"], OPACITY_TOL, w)
        self.assertLessEqual(w["rect"], 1.5, w)
        # reduced motion: positions and scales jump (float setters), never an animation
        slot = rig.chrome.by_index[3]
        self.assertIsInstance(rig.dev.value_now(slot.pos.ptr, "offset_x"), float)
        self.assertIsInstance(rig.dev.value_now(slot.sc.transform, "scale_x"), float)

    def test_clips_follow_the_nearer_cards_far_edge(self):
        """Each side card's chrome ends at its nearer neighbour's far edge (the neighbour's thumbnail
        hides it, as CSS does; WP7c-D3); the centre card is not clipped. Exact when the neighbour's X
        and scale retarget together; the mixed case (a far card whose scale target did not change) is
        one curve from the exact value and stays within 3 px."""
        rig = Rig(self)
        worst = {"exact": 0.0, "all": 0.0}

        def check():
            s, ch = rig.engine.session, rig.chrome
            if s is None or not s.gpu_synced or not ch.active:
                return
            m, t, k = rig.engine.machine, rig.clock.t, ch.k
            ax = ch.hx0 + R.CENTER_X * k
            for index, slot in ch.by_index.items():
                d = index - m.sel
                left = ref_value(rig, slot.clip, "clip_left", -PC.BIG)
                right = ref_value(rig, slot.clip, "clip_right", PC.BIG)
                if d == 0:
                    self.assertLessEqual(left, -PC.BIG + 1)
                    self.assertGreaterEqual(right, PC.BIG - 1)
                    continue
                near = m.cards.get(index - (1 if d > 0 else -1))
                if near is None:
                    continue
                edge = ax + k * near.x.value(t) + (1 if d > 0 else -1) * R.CARD_W * k / 2 * near.s.value(t) * \
                    near.escale.value(t)
                got = left if d > 0 else right
                err = abs(got - edge)
                worst["all"] = max(worst["all"], err)
                if not rig.chrome.counters["clip_approx"]:
                    worst["exact"] = max(worst["exact"], err)
        rig.open(count=14, index=3, check=check)
        index = 3
        for i in range(10):
            index += 1
            rig.presenter.highlight(index)
            rig.step(0.06, check=check)
        rig.step(0.6, check=check)
        self.assertLessEqual(worst["exact"], OFFSET_TOL, worst)
        self.assertLessEqual(worst["all"], 3.0, worst)
        self.assertEqual(rig.dev.violations, [])

    def test_z_order_is_far_to_near_and_changes_at_the_detent(self):
        rig = Rig(self)
        rig.open(count=12, index=4)
        for sel in (5, 6):
            rig.presenter.highlight(sel)
            rig.step(DT)
            ch = rig.chrome
            order = sorted(ch.by_index, key=lambda i: (-abs(i - sel), i))
            self.assertEqual(ch.cards.children, [ch.by_index[i].wrap for i in order])
            self.assertEqual(ch.cards.children[-1], ch.by_index[sel].wrap)          # the centre card on top

    def test_one_commit_per_event_none_without_change_and_detents_never_upload(self):
        rig = Rig(self)
        rig.open(count=12, index=4)
        rig.step(0.5)                                    # the prefetch uploads everything nearby first
        dev = rig.dev
        for sel in (5, 6, 7, 6):
            commits = dev.commits
            uploads = len(dev.calls_named("Upload"))
            rig.presenter.highlight(sel)
            rig.step(DT)
            self.assertEqual(dev.commits - commits, 1, "one Commit for the detent's batch")
            self.assertEqual(len(dev.calls_named("Upload")) - uploads, 0, "a detent's batch never uploads")
            rig.step(0.3)
        commits = dev.commits
        rig.presenter.set_labels({})                     # a data update with nothing new to draw
        rig.step(3 * DT)
        self.assertLessEqual(dev.commits - commits, 1)
        # every Commit is preceded by at least one call of its batch (no empty Commit)
        self.assertEqual(dev.violations, [])

    def test_a_label_swaps_only_once_its_surface_is_ready(self):
        rig = Rig(self)
        rig.open(count=10, index=4)
        rig.step(0.4)
        ch = rig.chrome
        before = rig.dev.value_now(ch.label_text.ptr, "content")
        rig.presenter.highlight(5)
        rig.step(DT)
        s = rig.engine.session
        label = s.label
        self.assertNotEqual(s.label_index, 5, "the new label waits for its surface (S5-24)")
        self.assertTrue(s.gpu_label_wait)
        self.assertEqual(rig.dev.value_now(ch.label_text.ptr, "content"), before)
        rig.step(0.05)
        self.assertEqual(s.label_index, 5)
        now = rig.dev.value_now(ch.label_text.ptr, "content")
        self.assertNotEqual(now, before)
        self.assertTrue(ch.surfaces.ready(s.label.sprite))
        self.assertIsNot(s.label, label)

    def test_the_fly_casts_its_shadow_along_the_fly(self):
        """S5-4 returns with the GPU chrome: the fly's shadow moves with the fly's translate + uniform
        scale (460 ms OUT) and fades from 380 ms over 220 ms, above every card."""
        rig = Rig(self)
        rig.open(count=10, index=4)
        rig.snap(4, "left", place=False)
        s, ch = rig.engine.session, rig.chrome
        self.assertIsNotNone(s.fly)
        fly = s.fly
        self.assertIs(ch.root.children[-1], ch.fly)
        worst = 0.0
        for _ in range(20):
            t = rig.clock.t
            e = c.EASE_OUT(min(1.0, max(0.0, (t - fly["t0"]) / c.FLY_S)))
            rect = R.fly_rect(fly["start"], fly["target"], e)
            x = ref_value(rig, ch.fly.ptr, "offset_x", 0.0)
            y = ref_value(rig, ch.fly.ptr, "offset_y", 0.0)
            sc = ref_value(rig, ch.fly_sc.transform, "scale_x", 1.0)
            w = (fly["start"][2] - fly["start"][0]) * sc
            worst = max(worst, abs(x - rect[0]), abs(y - rect[1]), abs(x + w - rect[2]))
            op = ref_value(rig, ch.fly.ref.v3, "opacity", 1.0)
            elapsed = t - fly["t0"]
            want = 1.0 if elapsed <= c.FLY_FADE_AT else 1.0 - c.EASE_OUT(min(1.0, (elapsed - c.FLY_FADE_AT)
                                                                               / c.FLY_FADE_S))
            self.assertAlmostEqual(op, want, delta=0.01)
            rig.step(0.012)
        self.assertLessEqual(worst, 1.5)

    def test_the_exit_fades_then_the_teardown_ends_the_chrome_and_hides_its_window(self):
        rig = Rig(self)
        rig.open(count=8, index=3)
        rig.presenter.play_switch_exit()
        rig.step(0.1)
        ch = rig.chrome
        self.assertLess(ref_value(rig, ch.root.ref.v3, "opacity", 1.0), 1.0)
        rig.step(0.3)
        self.assertIsNone(rig.engine.session)
        self.assertFalse(ch.active)
        self.assertNotIn("gpu", rig.backend.visible)
        self.assertEqual(rig.dev.value_now(ch.root.ref.v3, "opacity"), 0.0)
        self.assertEqual(ch.label_sprites, [])
        # the device stays warm for the next open (K4 4.2)
        self.assertIsNotNone(ch.dev)
        rig.presenter.show(T.snapshot(count=8, index=2))
        rig.backend.activate()
        rig.step(0.2)
        self.assertEqual(rig.presenter.chrome, "gpu")
        self.assertEqual(ch.counters["device_creates"], 1)
        self.assertEqual(ch.counters["sessions"], 2)

    def test_device_loss_mid_open_falls_back_to_the_cpu_chrome_at_once_and_the_next_open_retries(self):
        rig = Rig(self)
        rig.open(count=10, index=4)
        rig.dev.fail_next("Commit", com.DXGI_ERROR_DEVICE_REMOVED)
        mark = len(rig.backend.calls)
        rig.presenter.highlight(5)
        rig.step(0.1)
        names = [n[0] for n in rig.backend.calls[mark:]]
        self.assertIn("chrome_alloc", names, "the CPU chrome takes over this open")
        self.assertIn("chrome_present", names)
        self.assertEqual(rig.presenter.chrome, "cpu")
        m = rig.presenter.metrics()
        self.assertEqual(m["gpu_fallbacks"], 1)
        self.assertEqual(m["gpu"]["device_lost"], 1)
        self.assertIsNone(rig.chrome.dev, "every chrome object released (K4 4.3)")
        rig.presenter.hide()
        rig.step(0.05)
        rig.presenter.show(T.snapshot(count=10, index=4))
        rig.backend.activate()
        rig.step(0.2)
        self.assertEqual(rig.presenter.chrome, "gpu", "the next open tries the GPU again")
        self.assertEqual(rig.chrome.counters["device_creates"], 2)

    def test_a_device_that_cannot_be_made_leaves_the_cpu_chrome(self):
        def broken(hmon):
            raise OSError("no adapter")
        clock = PT.SharedClock()
        chrome = PC.PickerChrome(device_factory=broken, clock_factory=lambda d: None, monitor_for=lambda r: 1,
                                 monotonic=clock.car)
        rig = Rig(self, chrome=chrome)
        rig.clock = clock
        rig.open(count=6, index=2)
        self.assertEqual(rig.presenter.chrome, "cpu")
        self.assertIn("chrome_alloc", rig.backend.names())
        self.assertGreaterEqual(rig.presenter.metrics()["gpu_fallbacks"], 1)

    def test_the_cpu_switches_and_hosts_without_a_chrome_window_keep_the_cpu_chrome(self):
        rig = Rig(self)
        rig.presenter.set_chrome_mode("cpu")
        rig.open(count=6, index=2)
        self.assertEqual(rig.presenter.chrome, "cpu")
        self.assertNotIn("gpu_window", rig.backend.names())
        rig2 = Rig(self, environ={"NANOD_PICKER_CHROME": "cpu"})
        rig2.open(count=6, index=2)
        self.assertEqual(rig2.presenter.chrome, "cpu")
        rig3 = Rig(self, backend_kw={"gpu_window": False})             # as Win32 when the window failed
        rig3.open(count=6, index=2)
        self.assertEqual(rig3.presenter.chrome, "cpu")
        self.assertEqual(rig3.presenter.metrics()["gpu_fallbacks"], 0)
        rig4 = Rig(self, backend_kw={"host_mode": c.HOST_PLAIN})
        rig4.open(count=6, index=2)
        self.assertEqual(rig4.presenter.chrome, "cpu")
        self.assertEqual(rig.presenter.set_chrome_mode("auto"), "auto")

    def test_the_device_is_released_after_600_s_idle_and_a_knob_touch_warms_it(self):
        rig = Rig(self)
        rig.open(count=6, index=2)
        rig.presenter.hide()
        rig.step(0.05)
        self.assertIsNotNone(rig.chrome.dev)
        wait = rig.engine._next_wait(rig.clock.t)
        self.assertIsNotNone(wait)
        self.assertLessEqual(wait, 600.0)
        rig.clock.advance(601.0)
        rig.step(0)
        self.assertIsNone(rig.chrome.dev)
        self.assertEqual(rig.chrome.counters["device_releases"], 1)
        self.assertTrue(rig.presenter.note_touch())
        rig.step(0)
        self.assertIsNotNone(rig.chrome.dev, "warmed with nothing open")
        self.assertIsNone(rig.engine.session)

    def test_close_releases_every_chrome_object(self):
        rig = Rig(self)
        rig.open(count=8, index=3)
        dev = rig.dev
        self.assertGreater(dev.alive(), 100)
        rig.presenter.close()
        self.assertEqual(dev.alive(), 0)

    def test_thumbnails_are_not_resent_unchanged_on_the_gpu_chrome(self):
        rig = Rig(self)
        rig.open(count=8, index=3)
        rig.step(0.6)
        mark = len(rig.backend.calls)
        rig.snap(3, "right")                             # the tray springs; the cards stay at rest
        rig.step(0.2)
        updates = [call for call in rig.backend.calls[mark:] if call[0] == "update"]
        per_hwnd = {}
        for call in updates:
            per_hwnd.setdefault(call[1], []).append(call[2:])
        for hwnd, seq in per_hwnd.items():
            self.assertTrue(all(a != b for a, b in zip(seq, seq[1:])), f"{hwnd} re-sent unchanged")

    def test_install_hands_the_factory_to_the_carousel(self):
        self.assertIsNone(c.gpu_chrome_factory())
        self.assertTrue(PC.install())
        self.assertIs(c.gpu_chrome_factory(), PC.factory)
        c.install_gpu_chrome(None)
        self.assertIsNone(c.gpu_chrome_factory())

    def test_the_carousel_modules_never_name_the_stage_package(self):
        import re
        for name in ("carousel.py", "carousel_render.py", "windows.py"):
            text = (ROOT / "control_center" / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(control_center\.stage|from \.stage|from \. import stage)", text), name)

    def test_frame_stats_split_normal_and_detent_frames(self):
        stats = c.LoopStats(cpu_clock=lambda: 0.0)
        stats.begin("picker", "turn", 0.0)
        for i in range(10):
            stats.frame("picker", i / 240, 0.0004, 0.0002, detent=i in (3, 7), chrome="gpu",
                        sync_s=0.001 if i in (3, 7) else None)
        rec = stats.end("picker", 10 / 240, 1 / 240)
        self.assertEqual(rec["chrome"], "gpu")
        self.assertEqual(rec["detent_frames"], 2)
        self.assertAlmostEqual(rec["normal_ms"]["max"], 0.6, places=3)
        self.assertAlmostEqual(rec["sync_ms"]["max"], 1.0, places=3)
        pooled = stats.metrics()["picker"]["pooled"]
        self.assertEqual(sum(pooled["detent_ms"].values()), 2)
        self.assertEqual(sum(pooled["normal_ms"].values()), 8)


E_INVALIDARG = -2147024809      # 0x80070057: a COM failure that is not a device loss


def unbound(dev, visual):
    return dev.value_now(visual.ptr, "content") is None


class ThreadedGpuBackend(T.ThreadedFakeBackend):
    """The presenter tests' real-thread backend plus the GPU chrome's window (nothing is shown)."""

    has_gpu_window = True

    def gpu_window(self, rect):
        return 0x6001

    def gpu_show(self):
        pass

    def gpu_hide(self):
        pass


class ReviewFixTests(unittest.TestCase):
    """The WP7c review's findings, one test (or more) per fix: the policy in step with every release
    (R1), a loss in a quiet frame's upload (R2), sprites that arrive at rest (R3), the pool grown in
    quiet frames (R4), the teardown's unbinding (R5), the knob touch's device off the carousel
    thread (R6) and a missing chrome window (R7)."""

    def tearDown(self):
        c.install_gpu_chrome(None)

    # ---------------------------------------------------------------- R1
    def test_a_monitor_change_releases_the_device_and_the_next_warm_or_open_makes_one(self):
        clock = PT.SharedClock()
        chrome = PT.fake_chrome(clock, monitor_for=lambda rect: 1 if rect[0] < 2560 else 2)
        a, b = (0, 0, 2560, 1440), (2560, 0, 2560, 1440)
        self.assertTrue(chrome.warm(a))
        self.assertTrue(chrome.warm(b), "a device on the other monitor's adapter")
        self.assertEqual(len(chrome.devices), 2)
        self.assertEqual(chrome.counters["last_release"], "monitor")
        self.assertEqual(chrome.policy.state, "warm")
        clock.advance(1000.0)
        self.assertTrue(chrome.warm(a))
        self.assertEqual(len(chrome.devices), 3)
        # through the presenter: an open on another monitor (or HMONITORs renumbered by a reconnect),
        # then a knob touch with the foreground back on the first one
        rig = Rig(self, monitor=M16, chrome_kw={"monitor_for": lambda rect: 1 if rect[0] < 2560 else 2})
        rig.open(count=8, index=3)
        self.assertEqual(rig.presenter.chrome, "gpu")
        rig.presenter.hide()
        rig.step(0.05)
        rig.backend.monitor, rig.backend.work = (2560, 0, 5120, 1440), (2560, 0, 5120, 1392)
        rig.open(count=8, index=3)
        self.assertEqual(rig.presenter.chrome, "gpu")
        self.assertEqual(rig.chrome.counters["device_creates"], 2)
        self.assertEqual(rig.presenter.metrics()["gpu_fallbacks"], 0)
        rig.presenter.hide()
        rig.step(0.05)
        rig.backend.monitor, rig.backend.work = M16
        self.assertTrue(rig.presenter.note_touch())
        rig.step(0)
        self.assertIsNotNone(rig.chrome.dev)
        self.assertEqual(rig.chrome.counters["device_creates"], 3)

    def test_a_failure_that_is_not_a_loss_leaves_the_next_open_on_the_gpu(self):
        rig = Rig(self)
        rig.open(count=10, index=4)
        rig.dev.fail_next("Commit", E_INVALIDARG)                 # a sync's Commit
        rig.presenter.highlight(5)
        rig.step(0.1)
        self.assertEqual(rig.presenter.chrome, "cpu")
        m = rig.presenter.metrics()
        self.assertEqual((m["gpu_fallbacks"], m["gpu"]["device_lost"]), (1, 0))
        policy = rig.chrome.policy
        self.assertEqual((policy.state, policy.scene_open), ("cold", False))
        rig.presenter.hide()
        rig.step(0.05)
        rig.open(count=10, index=4)
        self.assertEqual(rig.presenter.chrome, "gpu", "the next open tries the GPU again (CAR 12.4)")
        self.assertEqual(rig.chrome.counters["device_creates"], 2)
        rig.presenter.hide()
        rig.step(0.05)
        rig.dev.fail_next("Commit", E_INVALIDARG)                 # begin()'s Commit
        rig.open(count=10, index=4)
        self.assertEqual(rig.presenter.chrome, "cpu")
        rig.presenter.hide()
        rig.step(0.05)
        rig.open(count=10, index=4)
        self.assertEqual(rig.presenter.chrome, "gpu")
        self.assertEqual(rig.chrome.counters["device_creates"], 3)
        self.assertEqual(rig.presenter.metrics()["gpu_fallbacks"], 2)

    # ---------------------------------------------------------------- R2
    def test_a_loss_in_a_quiet_frames_upload_hands_the_open_to_the_cpu_chrome_in_that_frame(self):
        for op in ("CreateSurface", "Upload"):
            rig = Rig(self)
            rig.open(count=12, index=4)
            rig.step(1.0)
            rig.presenter.highlight(5)
            rig.step(DT)                                         # the detent: the new label waits for its surface
            s, dev = rig.engine.session, rig.dev
            self.assertTrue(s.gpu_label_wait)
            dev.fail_next(op, com.DXGI_ERROR_DEVICE_REMOVED)
            hit = False
            for _ in range(8):
                mark = len(rig.backend.calls)
                rig.step(DT)
                if any(call[0] == op and call[2][:1] == ("FAILED",) for call in dev.calls):
                    hit = True
                    names = [n[0] for n in rig.backend.calls[mark:]]
                    self.assertFalse(s.gpu, op)
                    self.assertIn("chrome_alloc", names, f"{op}: the CPU chrome takes over in that frame")
                    self.assertIn("chrome_present", names, op)
                    break
            self.assertTrue(hit, op)
            self.assertFalse(s.gpu_label_wait or s.gpu_prebuild)
            self.assertEqual(rig.presenter.chrome, "cpu")
            m = rig.presenter.metrics()
            self.assertEqual((m["gpu_fallbacks"], m["gpu"]["device_lost"]), (1, 1), op)
            self.assertIsNone(rig.chrome.dev)
            rig.step(1.5)
            _alive, wait = rig.presenter._iterate()
            self.assertTrue(wait is None or wait > 0, f"{op}: the loop rests once the motion ends")

    # ---------------------------------------------------------------- R3
    def test_sprites_that_arrive_at_rest_are_synced_in_without_input(self):
        """set_icons and set_labels data and a card that closes, all at rest: the new badges and the
        placeholder face show within a few frames with no further input, and a badge never blanks
        while its new sprite uploads (the card keeps the previous one, as the tray keeps a caption)."""
        rig = Rig(self, monitor=M16)
        rig.open(count=8, index=3)
        rig.step(1.5)
        ch = rig.chrome

        def badges():
            return {i: sl.contents.get("badge", (None,))[0] for i, sl in ch.by_index.items()}
        before = badges()
        self.assertTrue(before and all(before.values()), before)
        rig.presenter.set_icons({f"w{i}": Image.new("RGBA", (128, 128), (200, 40 + 10 * i, 40, 255))
                                 for i in range(8)})
        blank = []
        rig.step(12 * DT, check=lambda: blank.extend(i for i, sid in badges().items() if not sid))
        self.assertEqual(blank, [], "a badge never blanks while its new sprite uploads")
        after = badges()
        self.assertTrue(all(after[i] != before[i] for i in after), (before, after))
        self.assertFalse(ch.want_sync)
        _alive, wait = rig.presenter._iterate()
        self.assertTrue(wait is None or wait > 0, "then the loop rests")
        # set_labels: a new app name re-renders the card's badge (its key holds label.app)
        old = badges()[3]
        rig.presenter.set_labels({"w3": R.SimpleLabel("Renamed", "Window 3", "")})
        rig.step(12 * DT, check=lambda: blank.extend(i for i, sid in badges().items() if not sid))
        self.assertNotEqual(badges()[3], old)
        self.assertEqual(blank, [])
        self.assertFalse(ch.want_sync)
        # a card that closes at rest shows its placeholder face
        self.assertFalse(ch.by_index[4].contents.get("face", (None,))[0])
        rig.presenter._items[4]["available"] = False
        rig.presenter.highlight(3)
        rig.step(12 * DT)
        self.assertTrue(ch.by_index[4].contents.get("face", (None,))[0], "the closed card's face")
        self.assertFalse(ch.want_sync)
        self.assertEqual(rig.dev.violations, [])

    def test_a_slot_given_to_another_card_never_shows_the_previous_cards_sprites(self):
        rig = Rig(self)
        rig.open(count=14, index=3)
        rig.step(0.5)
        ch = rig.chrome
        index = 3
        for _ in range(6):
            index += 1
            rig.presenter.highlight(index)
            rig.step(DT)
            for i, slot in ch.by_index.items():
                self.assertEqual(slot.owner, i)
            rig.step(0.05)

    # ---------------------------------------------------------------- R4
    def test_the_card_pool_grows_in_quiet_frames_never_inside_a_sync(self):
        """K4 4.7.1 / 9.10: 30 windows, turns at 20 and 40 detents/s on both tables: no visual,
        clip, transform or animation object is made inside a sync; the pool grows ahead."""
        for monitor in (M32, M16):
            for dt in (0.05, 0.025):
                rig = Rig(self, monitor=monitor)
                rig.open(count=30, index=0)
                ch = rig.chrome
                inside = []
                real_sync = ch.sync

                def spy(view, t_wake=None, real_sync=real_sync, ch=ch, inside=inside):
                    dev = ch.dev
                    before = PT.create_calls(dev)
                    try:
                        return real_sync(view, t_wake)
                    finally:
                        inside.append(PT.create_calls(dev) - before)
                ch.sync = spy
                for sel in range(1, 21):
                    rig.presenter.highlight(sel)
                    rig.step(dt)
                rig.step(0.6)
                key = (monitor[0], dt)
                self.assertGreater(len(inside), 20, key)
                self.assertEqual(sum(inside), 0, key)
                self.assertEqual(ch.counters["slots_grown_in_sync"], 0, key)
                self.assertGreater(len(ch.slots), PC.POOL, f"{key}: the pool grew ahead, in quiet frames")
                self.assertLessEqual(len(ch.slots), 30)
                self.assertEqual(rig.dev.violations, [])
        rig = Rig(self)
        rig.open(count=10, index=0)
        for sel in range(1, 10):
            rig.presenter.highlight(sel)
            rig.step(0.025)
        self.assertEqual(len(rig.chrome.slots), PC.POOL, "never more slots than the open's windows need")

    # ---------------------------------------------------------------- R5
    def test_the_teardown_unbinds_the_label_and_the_faces_in_its_commit(self):
        rig = Rig(self)
        rig.open(snap=T.snapshot(count=8, index=3, changes={4: {"available": False}}))
        ch, dev = rig.chrome, rig.dev
        face = ch.by_index[4].face
        self.assertTrue(dev.value_now(ch.label_text.ptr, "content"))
        self.assertTrue(dev.value_now(face.ptr, "content"), "the closed card's placeholder face")
        label_surfaces = {dev.value_now(v.ptr, "content") for v in (ch.label_text, ch.label_shadow)} - {None}
        rig.presenter.play_cancel_exit()
        rig.step(0.6)
        self.assertIsNone(rig.engine.session)
        self.assertIs(ch.dev, dev, "the device stays warm")
        for v in (ch.label_text, ch.label_shadow, face):
            self.assertTrue(unbound(dev, v), v)
        calls = dev.calls
        commit = max(i for i, call in enumerate(calls) if call[0] == "Device.Commit")
        unbind = [i for i, call in enumerate(calls) if call[0] == "Visual.SetContent" and call[1] == ch.label_text.ptr
                  and call[2] == (None,)]
        self.assertTrue(unbind and unbind[-1] < commit, "unbound in the batch of end()'s Commit")
        for sid in label_surfaces:
            self.assertTrue(dev.objects[sid]["released"], "the label's surfaces are released")
        self.assertEqual(dev.violations, [])
        # the next open binds a label again
        rig.open(count=8, index=2)
        self.assertEqual(rig.presenter.chrome, "gpu")
        self.assertTrue(dev.value_now(ch.label_text.ptr, "content"))

    # ---------------------------------------------------------------- R6
    def test_a_knob_touch_makes_no_device_on_the_carousel_thread_and_the_open_adopts_it(self):
        held = PT.HeldSpawn()
        rig = Rig(self, chrome_kw={"spawn": held})
        ch = rig.chrome
        self.assertTrue(rig.presenter.note_touch())
        rig.step(0)
        self.assertEqual(len(held.pending), 1, "the slow half runs on a worker")
        self.assertEqual((ch.devices, ch.halves), ([], []), "nothing of the device made on the carousel thread")
        self.assertTrue(ch.warming)
        self.assertTrue(rig.presenter.note_touch())                # a second touch: still the one worker
        rig.step(0)
        self.assertEqual(len(held.pending), 1)
        rig.presenter.show(T.snapshot(count=8, index=3))           # the handshake (raises when late)
        self.assertEqual(ch.devices, [], "the handshake never waits for the device")
        self.assertEqual(held.run_all(), 1)                        # the worker ends and posts WM_APP_WARM
        rig.backend.activate()
        rig.step(0.3)
        self.assertEqual(rig.presenter.chrome, "gpu")
        self.assertEqual((len(ch.devices), len(ch.halves)), (1, 1), "one device: the open adopted the half")
        self.assertEqual((ch.counters["warm_adopted"], ch.counters["device_creates"]), (1, 1))
        self.assertFalse(ch.warming)

    def test_a_half_for_another_monitor_or_after_close_is_released_never_adopted(self):
        clock = PT.SharedClock()
        held = PT.HeldSpawn()
        chrome = PT.fake_chrome(clock, spawn=held, monitor_for=lambda rect: 1 if rect[0] < 2560 else 2)
        self.assertEqual(chrome.warm_async((0, 0, 2560, 1440)), "started")
        self.assertEqual(chrome.warm_async((0, 0, 2560, 1440)), "pending")
        self.assertTrue(chrome.warm((2560, 0, 2560, 1440)), "an open on the other monitor makes its own device")
        held.run_all()
        self.assertEqual(len(chrome.halves), 1)
        self.assertTrue(chrome.halves[0].released, "the first monitor's half is released")
        self.assertEqual(chrome.counters["device_creates"], 1)
        chrome.close()
        self.assertEqual(chrome.warm_async((0, 0, 2560, 1440)), "started")
        chrome.close()
        held.run_all()
        self.assertTrue(chrome.halves[-1].released)
        self.assertIsNone(chrome.dev)
        # a worker that fails: the policy counts it, the next touch tries again
        def broken(hmon):
            raise OSError("no adapter")
        chrome = PT.fake_chrome(clock, prepare=broken)
        self.assertEqual(chrome.warm_async((0, 0, 2560, 1440)), "started")
        self.assertIsNone(chrome.dev)
        chrome.idle()
        self.assertEqual(chrome.counters["failures"], 1)
        self.assertFalse(chrome.warming)
        self.assertEqual(chrome.warm_async((0, 0, 2560, 1440)), "started")

    def test_a_show_right_after_a_touch_answers_its_handshake_while_the_device_is_made(self):
        """The finding's race on real threads (fakes; no window): the slow half takes 400 ms and the
        touch comes 2 ms before show(); show() answers well inside its 150 ms bound and the open
        adopts the half (one device)."""
        import time as _time
        clock = PT.SharedClock()

        def slow(hmon):
            _time.sleep(0.4)
            return PT.FakeHalf(hmon)
        chrome = PT.fake_chrome(clock, spawn=PC._spawn_thread, prepare=slow)
        chrome.prewarm_step(None)
        backend = ThreadedGpuBackend()
        capture = T.FakeCapture(backend)
        snapper = T.FakeSnap()
        snapper.backend = backend
        p = c.CarouselPresenter(None, None, None, backend=backend, capture=capture, snap=snapper,
                                gpu_chrome=chrome, environ={})
        self.addCleanup(p.close)
        self.assertTrue(p.note_touch())
        _time.sleep(0.002)
        started = _time.perf_counter()
        p.show(T.snapshot(count=6, index=2))
        self.assertLess(_time.perf_counter() - started, c.SHOW_TIMEOUT_S)
        deadline = _time.monotonic() + 3.0
        while p.chrome != "gpu" and _time.monotonic() < deadline:
            _time.sleep(0.01)
        self.assertEqual(p.chrome, "gpu")
        self.assertEqual((chrome.counters["device_creates"], chrome.counters["warm_adopted"]), (1, 1))
        self.assertEqual(chrome.halves[0].released, True)             # owned by the device now

    # ---------------------------------------------------------------- R7
    def test_a_missing_chrome_window_keeps_the_cpu_chrome_without_fallbacks_or_devices(self):
        rig = Rig(self, backend_kw={"gpu_window": False})
        self.assertTrue(callable(rig.backend.gpu_window), "the method exists, as on Win32")
        self.assertFalse(rig.engine._gpu_usable())
        for _ in range(2):
            rig.open(count=6, index=2)
            self.assertEqual(rig.presenter.chrome, "cpu")
            rig.presenter.hide()
            rig.step(0.05)
        self.assertEqual(rig.presenter.metrics()["gpu_fallbacks"], 0, "not a device failure (CAR 12.4)")
        self.assertNotIn("gpu_window", rig.backend.names())
        self.assertTrue(rig.presenter.note_touch())
        rig.step(0)
        self.assertEqual(rig.chrome.devices, [], "no device for a chrome that cannot draw")


class WiringTests(unittest.TestCase):
    """The lead's decision of 2026-09-26 (WP7c-D11 closed): the app installs the chrome before the
    WindowsAdapter exists, and the input fast path warms it at a knob touch through
    ``WindowsAdapter.note_touch`` wherever it warms the stage, never more often. The chain runs as in
    the app (``ui.FastPath`` on a reader thread -> the adapter -> the production presenter, inline on
    the fake backend with a fake chrome whose worker is held), so it shows where each part runs:
    the reader thread only posts, the carousel thread (here the test's) starts the worker, and the
    device is made on the worker alone."""

    def tearDown(self):
        c.install_gpu_chrome(None)

    def adapter(self, chrome_kw=None):
        import test_carousel_adapter as TA
        from unittest import mock
        from control_center import windows as w
        clock = PT.SharedClock()
        backend = GpuBackend(monitor=M32[0], work=M32[1])
        backend.clock = clock
        chrome = PT.fake_chrome(clock, **(chrome_kw or {}))
        chrome.prewarm_step(None)
        made = {}

        def picker(root, native, on_cancel):
            snapper = T.FakeSnap()
            snapper.backend = backend
            made["presenter"] = c.CarouselPresenter(root, native, on_cancel, backend=backend,
                                                    capture=T.FakeCapture(backend), snap=snapper, clock=clock,
                                                    inline=True, environ={})
            return made["presenter"]
        for patcher in (mock.patch.object(w, "NativeWindows", lambda: TA.FakeNative([])),
                        mock.patch.object(w, "PickerOverlay", picker),
                        mock.patch.object(w, "_window_labels", lambda: TA.LABELS)):
            patcher.start()
            self.addCleanup(patcher.stop)
        c.install_gpu_chrome(lambda log=None: chrome)               # what picker_chrome.install() registers
        adapter = w.WindowsAdapter(TA.FakeRoot(), lambda: None, lambda: None, lambda: None)
        self.addCleanup(adapter.close)
        presenter = made["presenter"]
        self.assertIs(presenter._gpu, chrome, "the adapter's presenter took the installed chrome")
        return adapter, presenter, backend, chrome

    def test_the_fast_paths_touch_reaches_the_adapter_at_most_as_often_as_the_stage(self):
        import threading
        from control_center import ui
        held = PT.HeldSpawn()
        adapter, presenter, backend, chrome = self.adapter({"spawn": held})
        warm_threads = []
        real_warm = chrome.warm_async

        def spy(*args, **kwargs):
            warm_threads.append(threading.current_thread().name)
            return real_warm(*args, **kwargs)
        chrome.warm_async = spy
        stage = type("Stage", (), {"touches": 0, "note_touch": lambda self: setattr(self, "touches", self.touches + 1)})()
        fast = ui.FastPath(overlay=None, stage=stage, windows=adapter)
        seen = {"never_more": True}

        def reader():
            for i in range(160):                                   # 40 s of turns at 4 per second
                fast.handle("position", {"id": 1, "p": i, "delta": 1}, 5.0 + i * 0.25)
                if backend.queue.count(c.WM_APP_WARM) > stage.touches:
                    seen["never_more"] = False
                if i == 0:
                    seen["first"] = (list(chrome.devices), list(chrome.halves), len(held.pending))
        t = threading.Thread(target=reader, name="NanoD-reader")
        t.start()
        t.join(10.0)
        self.assertFalse(t.is_alive())
        self.assertEqual(seen["first"], ([], [], 0), "the reader thread only posted: no device, no worker")
        self.assertTrue(seen["never_more"])
        warm_posts = backend.queue.count(c.WM_APP_WARM)
        self.assertEqual(stage.touches, 4, "t = 5, 15, 25, 35")
        self.assertEqual(warm_posts, stage.touches, "the adapter warmed with the stage, never more often")
        self.assertEqual(warm_threads, [], "the chrome is never called on the reader thread")
        presenter._step_inline()                                   # the carousel thread drains the posts
        self.assertEqual(set(warm_threads), {threading.current_thread().name})
        self.assertEqual(len(held.pending), 1, "one worker for the burst of touches; the device is made there")
        self.assertEqual((chrome.devices, chrome.halves), ([], []))
        held.run_all()
        presenter._step_inline()
        self.assertEqual((len(chrome.devices), chrome.counters["warm_adopted"]), (1, 1))
        self.assertIsNone(presenter._engine.session, "warmed with nothing open")

    def test_the_self_tests_wiring_check_holds_on_this_tree(self):
        """picker_selftest's static wiring check (WP7c-D11 closed) reads standalone.py and ui.py."""
        from control_center.stage import picker_selftest as PS
        ok, out = PS.wiring_checks()
        self.assertTrue(ok, out)
        self.assertEqual(set(out), {"main_installs_once", "right_before_the_app", "install_calls_picker_chrome_install",
                                    "fast_path_warms_the_stage_and_the_picker",
                                    "the_tick_hands_over_the_runtimes_picker"})

    def test_without_an_installed_chrome_a_touch_warms_nothing(self):
        import test_carousel_adapter as TA
        from unittest import mock
        from control_center import ui
        from control_center import windows as w
        backend = GpuBackend(monitor=M32[0], work=M32[1])

        def picker(root, native, on_cancel):
            return c.CarouselPresenter(root, native, on_cancel, backend=backend, capture=T.FakeCapture(backend),
                                       snap=T.FakeSnap(), inline=True, environ={})
        with mock.patch.object(w, "NativeWindows", lambda: TA.FakeNative([])), \
                mock.patch.object(w, "PickerOverlay", picker), mock.patch.object(w, "_window_labels", lambda: TA.LABELS):
            adapter = w.WindowsAdapter(TA.FakeRoot(), lambda: None, lambda: None, lambda: None)
        self.addCleanup(adapter.close)
        self.assertIsNone(adapter.overlay._gpu)
        fast = ui.FastPath(windows=adapter)
        self.assertTrue(fast.handle("limit", {"id": 1, "dir": 1}, 1.0))
        self.assertFalse(adapter.note_touch(), "no GPU chrome: the presenter answers False")
        self.assertEqual(backend.queue.count(c.WM_APP_WARM), 0)
        self.assertEqual(fast.failures, 0)


class ParityTests(unittest.TestCase):
    """H4 for step 3: the GPU chrome's reference render against compose_chrome (with the CPU label and
    dots layers) at rest, k = 1 on both tables. The difference that remains is WP7c-D3 (a farther
    card's chrome is clipped away under a translucent nearer card, where compose_chrome keeps
    1 - cover of it) and half-pixel card edges at this k (whole pixels at k = 2)."""

    def render_pair(self, monitor, highlight=None):
        out = []
        for gpu in (False, True):
            rig = Rig(self, monitor=monitor, chrome="fake" if gpu else False, keep_pixels=True)
            rig.open(count=9, index=4, settle=1.0)
            if highlight is not None:
                rig.presenter.highlight(highlight)
                rig.step(1.0)
            layout = R.layout_for(*monitor)
            x, y, w, h = layout.band
            if not gpu:
                cpu = R.straight_image(rig.backend.chrome.image)
                for role in ("label", "dots"):
                    alpha, pos = rig.backend.layer_state.get(role, (0, None))
                    canvas = rig.backend.layers.get(role)
                    if canvas is None or not alpha or pos is None:
                        continue
                    layer = R.straight_image(canvas.image)
                    layer.putalpha(layer.getchannel("A").point(lambda v, a=alpha: v * a // 255))
                    cpu.alpha_composite(layer, (pos[0] - x, pos[1] - y))
                out.append(cpu.getchannel("A"))
            else:
                rig.chrome.surfaces.age_all()
                size = (monitor[0][2], monitor[0][3])
                _pm, a = PT.render_chrome(rig.chrome, size, rig.clock.dev())
                out.append(a.crop((x, y, x + w, y + h)))
        return out

    def check(self, monitor, highlight=None):
        cpu_a, gpu_a = self.render_pair(monitor, highlight)
        diff = ImageChops.difference(cpu_a, gpu_a)
        hist = diff.histogram()
        total = sum(hist)
        mean = sum(i * n for i, n in enumerate(hist)) / total
        over24 = sum(hist[25:]) / total
        return mean, over24

    def test_16_9_at_rest_and_after_a_turn(self):
        for hl in (None, 5):
            mean, over24 = self.check(((0, 0, 1280, 720), (0, 0, 1280, 672)), hl)
            self.assertLess(mean, 1.0, (hl, mean))
            self.assertLess(over24, 0.002, (hl, over24))

    def test_32_9_at_rest_and_after_a_turn(self):
        for hl in (None, 5):
            mean, over24 = self.check(((0, 0, 2560, 720), (0, 0, 2560, 696)), hl)
            self.assertLess(mean, 1.2, (hl, mean))
            self.assertLess(over24, 0.003, (hl, over24))


class SpriteTests(unittest.TestCase):
    def test_a_gpu_shadow_is_cleared_under_its_box_and_placed_around_it(self):
        for kind in ("side", "focus", "fly"):
            sprite, (dx, dy) = R.gpu_shadow_sprite(kind, 2.0)
            w0, h0 = R.card_box_px(2.0)
            oy = round(R.GPU_SHADOWS[kind][0] * 2.0)
            # the card's own box (dx, dy relative to the card's top-left) is empty
            box = (-dx, -dy, -dx + w0, -dy + h0)
            self.assertEqual(sprite.mask.crop(box).getextrema(), (0, 0), kind)
            self.assertGreater(sprite.mask.getextrema()[1], 0)
            self.assertEqual(dy + (sprite.size[1] - h0) // 2, oy)          # the shadow sits oy lower

    def test_sprite_bytes_are_premultiplied_bgra(self):
        mask = Image.new("L", (2, 1), 128)
        s = R.Sprite.solid(mask, (200, 100, 50))
        w, h, data = R.sprite_bgra(s)
        self.assertEqual((w, h, len(data)), (2, 1, 8))
        b, g, r, a = data[:4]
        self.assertEqual(a, 128)
        self.assertAlmostEqual(r, 200 * 128 / 255, delta=1)
        self.assertAlmostEqual(b, 50 * 128 / 255, delta=1)

    def test_the_frame_ring_matches_compose_chromes_outline(self):
        ring, (dx, dy) = R.frame_ring_sprite(2.0)
        width = max(1, round(R.OUTLINE_WIDTH * 2.0))
        off = round(R.OUTLINE_OFFSET * 2.0)
        self.assertEqual((dx, dy), (-(off + width), -(off + width)))
        w0, h0 = R.card_box_px(2.0)
        self.assertEqual(ring.size, (w0 + 2 * (off + width), h0 + 2 * (off + width)))
        self.assertEqual(ring.mask.getpixel((0, 0)), 255)
        self.assertEqual(ring.mask.getpixel((width, width)), 0)

    def test_half_sprites_scale_back_to_the_full_footprint(self):
        s = R.Sprite.solid(Image.new("L", (61, 33), 255), (255, 255, 255))
        small, (sx, sy) = R.half_sprite(s)
        self.assertEqual(small.size, (31, 17))
        self.assertAlmostEqual(small.size[0] * sx, 61)
        self.assertAlmostEqual(small.size[1] * sy, 33)


_NATIVE = None
_NATIVE_ERR = None


def setUpModule():
    global _NATIVE, _NATIVE_ERR
    if sys.platform != "win32":
        _NATIVE_ERR = "Windows only"
        return
    try:
        from control_center.stage import win32 as W
        from control_center.stage.device import NativeDevice
        mon = W.primary_monitor()
        _NATIVE = NativeDevice(mon["hmonitor"] if mon else None)
    except Exception as exc:
        _NATIVE_ERR = repr(exc)


def tearDownModule():
    if _NATIVE is not None:
        _NATIVE.teardown()


class NativeSlotTests(unittest.TestCase):
    """H6 for the slots step 3 adds (a device without a target: nothing is shown)."""

    def setUp(self):
        if _NATIVE is None:
            self.skipTest(f"no stage device: {_NATIVE_ERR}")

    def test_rectangle_clip_slots_return_s_ok_and_the_anim_overloads_refuse_null(self):
        dev = _NATIVE
        clip = dev.create_rect_clip("t.clip")
        anim = dev.create_animation("t.anim")
        try:
            for name in ("Clip.SetLeft", "Clip.SetTop", "Clip.SetRight", "Clip.SetBottom"):
                self.assertEqual(PC.clip_fn(dev, name, clip)(clip, 12.5), 0, name)
                fa = PC.clip_fn(dev, name + ".anim", clip)
                self.assertEqual(fa(clip, None) & 0xFFFFFFFF, 0x80070057, name + ".anim(NULL)")
                fr, fb, fc, fe = dev.animation_fns()
                fr(anim)
                fc(anim, 0.0, 1.0, 0.0, 0.0, 0.0)
                fe(anim, 0.1, 1.0)
                self.assertEqual(fa(clip, anim), 0, name + ".anim")
                self.assertEqual(PC.clip_fn(dev, name, clip)(clip, 3.0), 0)        # the float setter unbinds it
            v = dev.create_visual("t.v")
            self.assertEqual(dev.fn("Visual.SetClip.object", v.ptr)(v.ptr, clip), 0)
            dev.commit()
        finally:
            dev.release(anim)
            dev.release(clip)

    def test_a_device_made_in_two_halves_on_two_threads_works_and_tears_down(self):
        """WP7c-R6's native path: D3D11CreateDevice on a worker thread, the DirectComposition half here
        (a device without a target: nothing is shown)."""
        import threading
        from control_center.stage import picker_device as PD
        from control_center.stage import win32 as W
        mon = W.primary_monitor()
        out = {}

        def worker():
            try:
                out["half"] = PD.prepare(mon["hmonitor"] if mon else None)
            except Exception as exc:                                  # pragma: no cover - reported below
                out["error"] = exc
        t = threading.Thread(target=worker, name="NanoD-chrome-warm")
        t.start()
        t.join(10.0)
        self.assertNotIn("error", out)
        half = out["half"]
        self.assertEqual(half.thread, "NanoD-chrome-warm")
        dev = PD.adopt(half)
        try:
            self.assertEqual(half.take(), (None, None), "the device owns the D3D11 half")
            self.assertTrue(dev.check_device_state())
            self.assertTrue(dev.info["timeFrequency_equals_qpf"])
            self.assertEqual(dev.info["prepared_on"], "NanoD-chrome-warm")
            v = dev.create_visual("t.v", v3=True)
            s = dev.create_surface(8, 8, False, "t.s")
            dev.upload(s, 8, 8, bytes(8 * 8 * 4), "t.s")
            self.assertEqual(dev.fn("Visual.SetContent", v.ptr)(v.ptr, s), 0)
            dev.commit()
        finally:
            self.assertGreater(dev.teardown(), 4)
        other = PD.prepare(mon["hmonitor"] if mon else None)
        self.assertEqual(PD.discard(other), 2, "a half never adopted is released (context, device)")
        self.assertEqual(PD.discard(other), 0)

    def test_an_upload_flushes_the_context_and_is_ready_a_frame_later(self):
        dev = _NATIVE
        now = [50.0]
        s = PC.Surfaces(dev, now=lambda: now[0], ready_s=PC.READY_S)
        self.assertIsNotNone(s._ctx_flush)                     # ID3D11DeviceContext::Flush (slot 111)
        sp = R.Sprite.solid(Image.new("L", (9, 7), 200), (10, 20, 30))
        surface, size = s.sprite(sp, "t")
        self.assertTrue(surface)
        self.assertEqual(size, (9, 7))
        self.assertFalse(s.ready(sp), "not in the frame of its upload")
        now[0] += PC.READY_S
        self.assertTrue(s.ready(sp))
        s.release()
        dev.commit()


if __name__ == "__main__":
    unittest.main()

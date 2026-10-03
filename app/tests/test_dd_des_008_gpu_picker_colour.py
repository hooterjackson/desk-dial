"""DD-DES-008: the installed app draws the picker with the GPU chrome, but the H4 picker goldens
(test_carousel_goldens) pin the CPU chrome only, and ParityTests (test_stage_picker) compares the GPU
chrome's ALPHA with compose_chrome at rest and after one turn. Here the five golden states (open,
turn, fly, filled, failure) run on both tables twice, once with the CPU chrome (compose_chrome plus the
CPU label and dots layers: what the goldens pin) and once with the fake GPU chrome (the reference
renderer evaluates what DWM would draw), and the GPU chrome's premultiplied RGB must match in colour.

The metric is the per-pixel largest channel difference: its mean, and the share of the band where it
exceeds 24 levels. At rest (open, filled, failure) the only differences are WP7c-D3's clip (a farther
card's chrome under a translucent nearer card) and half-pixel card edges, measured at a mean of about
0.15 and 0.05 % over 24, so the bound is mean < 0.3 and < 0.1 %. In motion (turn: 100 ms into a turn;
fly: 360 ms into a snap) the cards and the cards group are at fractional positions and scales that the
GPU samples bilinearly and compose_chrome rounds, which adds 1 px edge rings (measured up to mean 0.51
and 0.76 % over 24), so the bound there is the finding's mean < 1.2 with < 1.0 %. Both paths step at the
device's 240 Hz so the GPU label's upload-then-commit frame of latency stays one short frame.

A colour regression on the GPU path only (the failure slot's caption tinted green: same shape and
alpha, so the alpha-only ParityTests would pass) fails the rest bound. Headless: fake backend, fake
device, fake clock; no window, no screen read."""
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
from control_center.stage import picker_chrome as PC  # noqa: E402
from control_center.stage import picker_testing as PT  # noqa: E402
import test_carousel_goldens as G  # noqa: E402
import test_carousel_presenter as T  # noqa: E402
import test_stage_picker as SP  # noqa: E402

REST = (0.3, 0.001)                  # (mean levels, share over 24) for open, filled, failure
MOTION = (1.2, 0.010)                # for turn and fly
BOUNDS = {"open": REST, "turn": MOTION, "fly": MOTION, "filled": REST, "failure": REST}


class Scene:
    """One table's run of the production engine with the golden states' windows, on the shared fake
    clock, with the fake GPU chrome (``gpu``) or the CPU chrome."""

    def __init__(self, test, ratio, background, gpu):
        monitor, work = G.TABLES[ratio]
        self.monitor = (monitor, work)
        self.gpu = gpu
        self.clock = PT.SharedClock()
        self.backend = SP.GpuBackend(monitor=monitor, work=work, sizes={100 + G.STUB: (320, 40)})
        self.backend.clock = self.clock
        self.capture = T.FakeCapture(self.backend)
        self.snapper = T.FakeSnap()
        self.snapper.backend = self.backend
        if gpu:
            self.chrome = PT.fake_chrome(self.clock, keep_pixels=True)
            self.chrome.prewarm_step(None)
        else:
            self.chrome = False
        self.p = c.CarouselPresenter(None, None, lambda: None, backend=self.backend, capture=self.capture,
                                     snap=self.snapper, clock=self.clock, inline=True, gpu_chrome=self.chrome,
                                     environ={})
        test.addCleanup(self.p.close)
        self.p.set_background(background)
        items = [{"id": f"w{i}", "hwnd": 100 + i, "pid": 20, "app": G.APPS[i], "title": G.TITLES[i],
                  "available": i != G.CLOSED, "minimized": i == G.STUB} for i in range(len(G.APPS))]
        self.p.set_labels({f"w{i}": R.SimpleLabel(G.APPS[i], G.TITLES[i], G.DESCS[i]) for i in range(len(G.APPS))})
        self.p.show({"items": items, "index": 3, "origin": {"hwnd": 100, "pid": 20}})
        self.backend.activate()
        self.step()
        if self.capture.jobs:
            self.capture.complete()
        self.step(1.0)

    def step(self, seconds=0.0, dt=SP.DT):
        end = self.clock.t + seconds
        self.p._step_inline()
        while self.clock.t < end - 1e-9:
            self.clock.advance(min(dt, end - self.clock.t))
            self.p._step_inline()

    def snap(self, index, side, outcome="accepted"):
        self.p.snap({"t0": self.clock.t, "index": index, "side": side, "target_rect": None, "place_at_ms": 360,
                     "item": {"id": f"w{index}", "hwnd": 100 + index, "pid": 20}})
        self.step()
        job = self.snapper.jobs[-1]
        self.snapper.answer(job, "precheck", outcome)
        return job

    def chrome_rgb(self):
        """The band's chrome as premultiplied RGB (the GPU tree, or compose_chrome plus the CPU label and
        dots layers)."""
        layout = R.layout_for(*self.monitor)
        x, y, w, h = layout.band
        if self.gpu:
            if not self.p._engine.session.gpu:
                raise AssertionError("the GPU chrome is not driving the picker")
            self.chrome.surfaces.age_all()
            size = (self.monitor[0][2], self.monitor[0][3])
            pm, _a = PT.render_chrome(self.chrome, size, self.clock.dev())
            return pm.convert("RGB").crop((x, y, x + w, y + h))
        cpu = R.straight_image(self.backend.chrome.image)
        for role in ("label", "dots"):
            alpha, pos = self.backend.layer_state.get(role, (0, None))
            canvas = self.backend.layers.get(role)
            if canvas is None or not alpha or pos is None or role not in self.backend.visible:
                continue
            layer = R.straight_image(canvas.image)
            layer.putalpha(layer.getchannel("A").point(lambda v, a=G._alpha(alpha): v * a // 255))
            cpu.alpha_composite(layer, (pos[0] - x, pos[1] - y))
        return _premultiply(cpu)


def _premultiply(image):
    r, g, b, a = image.convert("RGBA").split()
    return Image.merge("RGB", [ImageChops.multiply(ch, a) for ch in (r, g, b)])


def states(test, ratio, gpu):
    """(name, premultiplied RGB band) for the five golden states of one table (test_carousel_goldens)."""
    out = []
    s = Scene(test, ratio, "glass", gpu)
    out.append(("open", s.chrome_rgb()))
    s.p.highlight(4)
    s.step(0.1)
    out.append(("turn", s.chrome_rgb()))
    s.step(0.6)
    job = s.snap(4, "left")
    s.step(G.FLY_AT)
    out.append(("fly", s.chrome_rgb()))
    s.snapper.answer(job, "final", "ok")
    s.step(1.0)
    out.append(("filled", s.chrome_rgb()))
    s.p.close()
    s = Scene(test, ratio, "none", gpu)
    s.snap(4, "right", outcome="move_rejected")
    s.step(0.6)
    out.append(("failure", s.chrome_rgb()))
    s.p.close()
    return out


def colour_difference(cpu, gpu):
    """(mean, share over 24) of the per-pixel largest channel difference."""
    r, g, b = ImageChops.difference(cpu, gpu).split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), b)
    hist = worst.histogram()
    total = sum(hist)
    return sum(i * n for i, n in enumerate(hist)) / total, sum(hist[25:]) / total


class GpuChromeColourTests(unittest.TestCase):
    def compare(self, ratio):
        cpu = dict(states(self, ratio, False))
        gpu = dict(states(self, ratio, True))
        out = {}
        for name in ("open", "turn", "fly", "filled", "failure"):
            self.assertEqual(cpu[name].size, gpu[name].size, name)
            self.assertGreater(cpu[name].getextrema()[0][1], 0, f"{name}: the CPU chrome drew nothing")
            out[name] = colour_difference(cpu[name], gpu[name])
        return out

    def test_gpu_chrome_matches_goldens_in_colour(self):
        for ratio in ("16x9", "32x9"):
            for name, (mean, over24) in self.compare(ratio).items():
                mean_max, over_max = BOUNDS[name]
                with self.subTest(ratio=ratio, state=name):
                    self.assertLess(mean, mean_max, (ratio, name, mean, over24))
                    self.assertLess(over24, over_max, (ratio, name, mean, over24))

    def test_a_recoloured_failure_caption_on_the_gpu_path_fails(self):
        """The check sees colour: the failure slot's caption tinted on the GPU path only (same shape,
        same alpha, so ParityTests' alpha comparison would pass) breaks the failure state's bound."""
        original = PC.PickerChrome._sprite_ready
        tinted = {}

        def recolour(chrome, sprite, name):
            if name == "slot.caption" and sprite is not None:
                key = id(sprite)
                if key not in tinted:
                    tinted[key] = (sprite, R.Sprite.solid(sprite.mask, (40, 255, 40)))
                sprite = tinted[key][1]
            return original(chrome, sprite, name)

        PC.PickerChrome._sprite_ready = recolour
        try:
            cpu = dict(states(self, "16x9", False))["failure"]
            gpu = dict(states(self, "16x9", True))["failure"]
        finally:
            PC.PickerChrome._sprite_ready = original
        self.assertTrue(tinted, "the failure state shows no slot caption on the GPU path")
        mean, over24 = colour_difference(cpu, gpu)
        mean_max, over_max = BOUNDS["failure"]
        self.assertTrue(mean >= mean_max or over24 >= over_max, (mean, over24))


if __name__ == "__main__":
    unittest.main()

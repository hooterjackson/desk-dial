"""K4 §6.6 H4 for the picker v2 (WP7b-R7): the production engine's frames against reviewed golden
images, on both tables (16:9 at 1280 x 720 and 32:9 at 2560 x 720, k = 1) and both backgrounds.

The real ``CarouselPresenter`` runs inline on the presenter tests' fake backend, fake NanoD-snap and
a fake clock (nothing is shown, no window is created, the screen is never read). Each golden is
the monitor as the windows would stack it (K4 §2.5): a synthetic desktop, the Frosted glass
(``frost_canvas`` of that desktop at the glass window's alpha) or No background's 55 % dim, the
host's DWM thumbnails as flat per-window colours at the engine's own rects, opacities and z-order
(the cards, the tray slots, the one-side preview and the snap fly), the chrome DIB
``compose_chrome`` drew into the band, and the label and dots layers at their positions and
constant alphas. So a golden pins the chrome (band, cards on both tables, the frame, both shadows,
badges, the chip, the tray and its slot states, closed and minimized cards) and the thumbnail
geometry (a fly into the wrong half, as WP7b-R1 had, changes thousands of pixels).

States per table: ``open`` (Frosted, at rest: a closed card and a minimized caption-stub card on
screen), ``turn`` (mid-turn), ``fly`` (a left snap 360 ms into its fly, opaque and nearly in the
left rcWork half, the tray springing in),
``filled`` (left filled, the chip, the one-side preview in the right slot) and ``failure`` (No
background: a refused right snap's red slot and caption).

Goldens live in ``tests/goldens/picker``. ``NANOD_WRITE_GOLDENS=1`` (re)writes them; they are
reviewed by eye before they are committed. A golden matches when at most 0.1 % of its channel
values differ by more than 3 levels (font rasterisation drift), as the music goldens do."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for path in (ROOT, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from control_center import carousel as c  # noqa: E402
from control_center import carousel_render as R  # noqa: E402
import test_carousel_presenter as T  # noqa: E402

GOLDENS = ROOT / "tests" / "goldens" / "picker"
TABLES = {"16x9": ((0, 0, 1280, 720), (0, 0, 1280, 672)), "32x9": ((0, 0, 2560, 720), (0, 0, 2560, 696))}
APPS = ("Chrome", "Slack", "Claude", "Explorer", "Steam", "Figma", "Spotify", "Notion", "Terminal")
TITLES = ("Calendar", "Danny Lewis", "Nano D Control Center", "Downloads", "Library", "Knob faceplate v3",
          "Discover Weekly", "Release checklist", "PowerShell")
DESCS = ("Week of Sep 22", "Direct message", "Conversation", "Folder", "Game launcher", "Design file",
         "Playlist", "Workspace page", "Administrator")
CLOSED, STUB = 5, 2                                  # a closed card and a minimized caption stub
FLY_AT = 0.36                                        # s after acceptance: the fly is ~95 % there, still opaque
PALETTE = ((66, 133, 244), (97, 31, 105), (204, 120, 92), (232, 182, 74), (0, 176, 190), (162, 89, 255),
           (30, 215, 96), (230, 230, 230), (12, 12, 12))


def desktop(size):
    """A deterministic desktop behind the picker: gradient, blocks and hard edges."""
    w, h = size
    image = Image.linear_gradient("L").rotate(90).resize((w, h)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((w // 10, h // 8, w // 3, h // 2), fill=(230, 80, 60))
    draw.rectangle((w // 2, h // 3, w - w // 7, h - h // 8), fill=(40, 120, 220))
    draw.rectangle((0, h - h // 20, w, h), fill=(20, 20, 24))
    return image


class GoldenBackend(T.FakeBackend):
    """The presenter tests' fake backend, also recording the glass and dim alphas and the
    thumbnails' registration order (DWM draws the later registered on top)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.glass_level = 0
        self.dim_level = 0
        self.order = []

    def glass_alpha(self, alpha):
        super().glass_alpha(alpha)
        self.glass_level = alpha

    def dim_alpha(self, alpha):
        super().dim_alpha(alpha)
        self.dim_level = alpha

    def register(self, hwnd):
        handle = super().register(hwnd)
        if handle is not None:
            self.order.append(handle)
        return handle

    def capture(self, rect):
        return desktop(tuple(rect[2:]))


class GoldenCapture(T.FakeCapture):
    def complete(self, image=None, error=None):
        job = self.jobs[0]
        if job.kind == "frost":
            image = R.frost_canvas(desktop(tuple(job.rect[2:])), job.k)
        return super().complete(image, error)


def _alpha(level):
    level = 0 if level is None else level
    return max(0, min(255, int(level if isinstance(level, int) else round(255 * level))))


def _over(base, canvas, xy, alpha=255):
    """A premultiplied layer (R.Canvas) over the straight RGB ``base`` at constant ``alpha``."""
    if canvas is None or alpha <= 0:
        return
    layer = canvas.straight()
    if alpha < 255:
        layer.putalpha(layer.getchannel("A").point(lambda v: v * alpha // 255))
    base.paste(layer.convert("RGB"), (int(xy[0]), int(xy[1])), layer.getchannel("A"))


def composite(backend, background):
    """The monitor as the windows stack (K4 §2.5): desktop, glass or dim, the host's thumbnails,
    the chrome band, the label and dots layers."""
    w, h = backend.monitor[2] - backend.monitor[0], backend.monitor[3] - backend.monitor[1]
    base = desktop((w, h))
    if background == "glass" and backend.glass_image is not None:
        _over(base, backend.glass_image, backend.glass_rect[:2], _alpha(backend.glass_level))
    elif background == "none":
        _over(base, R.Canvas(Image.new("RGBX", (w, h), R._pm((0, 0, 0), 0.55))), (0, 0), _alpha(backend.dim_level))
    for handle in backend.order:
        if handle not in backend.props:
            continue
        dest, _source, opacity, visible = backend.props[handle]
        if not visible or opacity <= 0:
            continue
        l, t, r, b = dest
        if r <= l or b <= t:
            continue
        hwnd = backend.thumbs.get(handle, 0)
        colour = PALETTE[(hwnd - 100) % len(PALETTE)]
        tile = Image.new("RGB", (r - l, b - t), colour)
        ImageDraw.Draw(tile).rectangle((0, 0, r - l, max(1, (b - t) // 8)), fill=tuple(v // 2 for v in colour))
        base.paste(tile, (l, t), Image.new("L", tile.size, opacity))
    layout = R.layout_for(backend.monitor, backend.work)
    if "chrome" in backend.visible:
        _over(base, backend.chrome, layout.band[:2])
    for role, rest in (("label", layout.labels), ("dots", layout.dots)):
        canvas = backend.layers.get(role)
        if canvas is None or role not in backend.visible:
            continue
        alpha, pos = backend.layer_state.get(role, (0, None))
        _over(base, canvas, pos if pos is not None else rest[:2], _alpha(alpha))
    return base


class Scene:
    """One table's run of the production engine, stepped on the fake clock."""

    def __init__(self, ratio, background="glass"):
        monitor, work = TABLES[ratio]
        self.background = background
        self.clock = T.Clock()
        self.backend = GoldenBackend(monitor=monitor, work=work,
                                     sizes={100 + STUB: (320, 40)})        # a minimized caption stub
        self.backend.clock = self.clock
        self.capture = GoldenCapture(self.backend)
        self.snapper = T.FakeSnap()
        self.snapper.backend = self.backend
        self.p = c.CarouselPresenter(None, None, lambda: None, backend=self.backend, capture=self.capture,
                                     snap=self.snapper, clock=self.clock, inline=True)
        self.p.set_background(background)
        items = [{"id": f"w{i}", "hwnd": 100 + i, "pid": 20, "app": APPS[i], "title": TITLES[i],
                  "available": i != CLOSED, "minimized": i == STUB} for i in range(len(APPS))]
        self.p.set_labels({f"w{i}": R.SimpleLabel(APPS[i], TITLES[i], DESCS[i]) for i in range(len(APPS))})
        self.p.show({"items": items, "index": 3, "origin": {"hwnd": 100, "pid": 20}})
        self.backend.activate()
        self.step()
        if self.capture.jobs:
            self.capture.complete()
        self.step(1.0)

    def step(self, seconds=0.0, dt=1 / 60):
        end = self.clock.t + seconds
        self.p._step_inline()
        while self.clock.t < end - 1e-9:
            self.clock.t = min(end, self.clock.t + dt)
            self.p._step_inline()

    def snap(self, index, side, outcome="accepted"):
        self.p.snap({"t0": self.clock.t, "index": index, "side": side, "target_rect": None, "place_at_ms": 360,
                     "item": {"id": f"w{index}", "hwnd": 100 + index, "pid": 20}})
        self.step()
        job = self.snapper.jobs[-1]
        self.snapper.answer(job, "precheck", outcome)
        return job

    def image(self):
        return composite(self.backend, self.background)

    def close(self):
        self.p.close()


def render_states(ratio):
    """(name, image) for every golden state of one table."""
    out = []
    s = Scene(ratio, "glass")
    try:
        out.append(("open", s.image()))
        s.p.highlight(4)
        s.step(0.1)
        out.append(("turn", s.image()))
        s.step(0.6)
        job = s.snap(4, "left")
        s.step(FLY_AT)                                 # the fly near the left half, before its fade
        out.append(("fly", s.image()))
        s.snapper.answer(job, "final", "ok")
        s.step(1.0)
        out.append(("filled", s.image()))
    finally:
        s.close()
    s = Scene(ratio, "none")
    try:
        s.snap(4, "right", outcome="move_rejected")
        s.step(0.6)
        out.append(("failure", s.image()))
    finally:
        s.close()
    return out


def differs(img, want, tolerance=3):
    """How many channel values differ by more than ``tolerance``."""
    diff = ImageChops.difference(img.convert("RGB"), want.convert("RGB"))
    total = 0
    for band in diff.split():
        hist = band.histogram()
        total += sum(hist[tolerance + 1:])
    return total


class PickerGoldenTests(unittest.TestCase):
    """H4: the picker chrome (and the thumbnail geometry) against the reviewed goldens."""

    maxDiff = None

    def test_goldens(self):
        write = os.environ.get("NANOD_WRITE_GOLDENS", "").strip() == "1"
        if write:
            GOLDENS.mkdir(parents=True, exist_ok=True)
        failures = []
        for ratio in ("16x9", "32x9"):
            for name, img in render_states(ratio):
                path = GOLDENS / f"picker_{name}_{ratio}.png"
                if write:
                    img.save(path, optimize=True)
                    continue
                if not path.exists():
                    failures.append(f"{path.name}: missing (NANOD_WRITE_GOLDENS=1 writes it)")
                    continue
                want = Image.open(path).convert("RGB")
                if want.size != img.size:
                    failures.append(f"{path.name}: size {img.size} != {want.size}")
                    continue
                over = differs(img, want)
                if over > (img.size[0] * img.size[1] * 3) // 1000:
                    failures.append(f"{path.name}: {over} channel values differ by more than 3")
        self.assertEqual(failures, [])

    def test_a_fly_in_the_wrong_half_fails_the_golden(self):
        """The golden is sensitive to the WP7b-R1 class of error: the fly composited into the
        other half differs from the reviewed image far beyond the tolerance."""
        path = GOLDENS / "picker_fly_32x9.png"
        if not path.exists():
            self.skipTest("the goldens are not written yet")
        s = Scene("32x9", "glass")
        try:
            s.p.highlight(4)
            s.step(0.7)
            s.snap(4, "left")
            s.step(FLY_AT)
            fly = s.p._engine.session.extra["fly"][0]
            dest, source, opacity, visible = s.backend.props[fly]
            w = dest[2] - dest[0]
            s.backend.props[fly] = ((dest[0] + 1280, dest[1], dest[0] + 1280 + w, dest[3]), source, opacity, visible)
            img = s.image()
        finally:
            s.close()
        want = Image.open(path).convert("RGB")
        self.assertGreater(differs(img, want), (img.size[0] * img.size[1] * 3) // 1000)


if __name__ == "__main__":
    unittest.main()

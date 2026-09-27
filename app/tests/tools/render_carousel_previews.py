"""Render preview PNGs of the desktop v6 window carousel (CAROUSEL.md sections 10 and 11).

Usage (cwd = app):
    .venv\\Scripts\\python.exe tests\\tools\\render_carousel_previews.py [output_dir] [--k 2.0]

No window is created and the screen is never read. The real CarouselPresenter runs inline on a
fake clock with a preview backend that records what the layered windows and DWM would show:
the dim (No background only), the Frosted background (section 11: carousel_render.frost_canvas
of the sample wallpaper over the whole monitor, in the glass window at its faded constant
alpha), the thumbnails (wireframe cards carrying the design's sample icons stand in for DWM
thumbnails, placed in the host's pane rect with the engine's own rects, cover-fit rcSource and
opacity, in registration order), the chrome DIB the engine composed, and the toast. Those are
composited into one PNG per scenario, plus a contact sheet and summary.json (scenario -> file,
compose timings, and for every glass_* scenario the check that the frost reaches all four
screen edges). Every string is the design handoff's sample content.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from control_center import carousel as c  # noqa: E402
from control_center import carousel_render as R  # noqa: E402

DEFAULT_OUT = Path(tempfile.gettempdir()) / "desk-dial-previews" / "v6-previews-fullscreen"
EDGE_PX = 4                 # the strip along each screen edge the frost check compares
ICON_DIR = ROOT / "design-reference" / "design_handoff_window_carousel" / "assets" / "apps"

# The handoff prototype's sample windows: (app, title, description, icon file or None, theme).
WINDOWS = [
    ("Google Chrome", "Calendar \u00b7 Week of Sep 22", "Riot Games \u00b7 Google Calendar", "chrome.png", "calendar"),
    ("Claude", "Nano D Control Center", "Conversation \u00b7 desktop app", "claude.png", "claude"),
    ("Slack", "Danny Lewis", "Direct message \u00b7 Riot Games", "slack.png", "slack"),
    ("ChatGPT", "PCB layout questions", "Conversation \u00b7 desktop app", "chatgpt.png", "chatgpt"),
    ("Google Chrome", "Understand the PCB", "Engineering docs \u00b7 9 tabs", "chrome.png", "doc"),
    ("Bambu Studio", "Rack_Base(2)", "Unsaved changes \u00b7 3D print project", None, "bambu"),
    ("File Explorer", "Downloads", "Folder \u00b7 Minimized", None, "files"),
    ("File Explorer", "Nano D Control Center App Icon", "Folder \u00b7 Minimized", None, "files"),
    ("Google Chrome", "Google Meet", "In a call \u00b7 Chrome", "chrome.png", "meet"),
    ("Steam", "Library", "Game launcher \u00b7 Minimized", None, "steam"),
]
MINIMIZED = {6, 7, 9}
THEMES = {   # (background, sidebar, bars, accent)
    "calendar": ((32, 33, 36), (40, 41, 44), (60, 64, 67), (79, 195, 247)),
    "claude": ((38, 38, 36), (31, 30, 28), (184, 181, 173), (58, 57, 53)),
    "slack": ((26, 29, 33), (74, 21, 75), (209, 210, 211), (63, 14, 64)),
    "chatgpt": ((33, 33, 33), (23, 23, 23), (142, 142, 142), (220, 220, 220)),
    "doc": ((233, 234, 237), (32, 33, 36), (200, 200, 200), (48, 48, 48)),
    "bambu": ((59, 63, 68), (247, 247, 247), (207, 207, 207), (0, 174, 66)),
    "files": ((25, 25, 25), (28, 28, 28), (189, 189, 189), (232, 182, 74)),
    "meet": ((32, 33, 36), (53, 54, 58), (142, 94, 162), (234, 67, 53)),
    "steam": ((27, 40, 56), (23, 26, 33), (61, 108, 141), (192, 86, 63)),
    "term": ((12, 12, 12), (30, 30, 30), (120, 200, 120), (200, 200, 200)),
}


# ---------------------------------------------------------------- sample art
def wallpaper(size, k, origin=(0, 0)):
    """The prototype's desktop behind the carousel (a calendar-like app) on the stage whose
    top-left is ``origin`` (monitor-local px), at stage scale k. A monitor larger than the stage
    (the user's 5120 x 1440) also gets a desktop backdrop with a terminal and a document window
    running off the screen's left and right edges and the taskbar across its full width, so the
    frost has real content to blur right up to every edge."""
    w, h = size
    ox, oy = (round(v) for v in origin)
    image = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(image)
    if (w, h) != (round(R.STAGE_W * k), round(R.STAGE_H * k)):
        ramp = Image.linear_gradient("L").rotate(90).resize(size)          # left -> right
        image = Image.merge("RGB", (ramp.point(lambda v: 30 + v // 3), ramp.point(lambda v: 70 - v // 5),
                                    ramp.point(lambda v: 120 + v // 2)))
        d = ImageDraw.Draw(image)
        u = k                                                               # one design px
        for x0, x1, theme in ((-round(60 * u), ox - round(40 * u), "term"),
                              (ox + round(R.STAGE_W * k) + round(40 * u), w + round(60 * u), "doc")):
            if x1 - x0 < round(80 * u):
                continue
            background, sidebar, bars, accent = THEMES[theme]
            y0, y1 = round(90 * u), h - round(110 * u)
            d.rectangle((x0, y0, x1, y1), fill=background)
            d.rectangle((x0, y0, x1, y0 + round(30 * u)), fill=sidebar)
            for i in range(max(0, (y1 - y0 - round(60 * u)) // round(22 * u))):
                y = y0 + round(50 * u) + i * round(22 * u)
                d.rectangle((x0 + round(80 * u), y, x0 + round(80 * u) + round((180 + (i * 67) % 420) * u),
                             y + round(7 * u)), fill=bars if i % 5 else accent)
        d.rectangle((0, h - round(48 * u), w, h), fill=(32, 32, 32))       # the taskbar, edge to edge

    def box(x, y, bw, bh, colour):
        d.rectangle((ox + round(x * k), oy + round(y * k), ox + round((x + bw) * k) - 1,
                     oy + round((y + bh) * k) - 1), fill=colour)

    box(0, 0, 1280, 672, (255, 255, 255))
    box(0, 56, 250, 616, (248, 249, 250))
    for i in range(7):
        box(250 + i * 147, 56, 1, 616, (227, 227, 227))
    for i in range(12):
        box(250, 100 + i * 48, 1030, 1, (238, 238, 238))
    for x, y, bw, bh, colour in ((262, 110, 130, 30, (255, 138, 61)), (556, 110, 130, 30, (240, 98, 146)),
                                 (850, 110, 130, 30, (240, 98, 146)), (1000, 110, 130, 30, (197, 179, 246)),
                                 (410, 200, 130, 70, (79, 195, 247)), (703, 250, 130, 90, (79, 195, 247)),
                                 (850, 300, 130, 50, (240, 98, 146)), (262, 390, 130, 60, (197, 179, 246)),
                                 (556, 430, 130, 80, (79, 195, 247)), (1000, 480, 130, 60, (79, 195, 247)),
                                 (703, 540, 130, 50, (255, 138, 61))):
        box(x, y, bw, bh, colour)
    box(0, 672, 1280, 48, (32, 32, 32))
    for x in (560, 600, 640, 680, 720):
        box(x, 684, 24, 24, (90, 90, 90))
    for i in range(10):
        box(20, 80 + i * 40, 160 - (i % 3) * 30, 8, (218, 220, 224))
    return image


def load_icon(name):
    if not name:
        return None
    path = ICON_DIR / name
    return Image.open(path).convert("RGBA") if path.exists() else None


def wireframe(theme, icon, app, k, engine):
    """A window stand-in for a DWM thumbnail: themed chrome and content bars, with the app's
    sample icon (or its letter tile) at 96 design px in the middle."""
    background, sidebar, bars, accent = THEMES[theme]
    w, h = round(R.CARD_W * k), round(R.CARD_H * k)
    image = Image.new("RGBA", (w, h), background + (255,))
    d = ImageDraw.Draw(image)
    d.rectangle((0, 0, w, round(30 * k)), fill=tuple(max(0, v - 12) for v in background) + (255,))
    d.rectangle((0, round(30 * k), round(96 * k), h), fill=sidebar + (255,))
    for i in range(9):
        y = round((52 + i * 24) * k)
        d.rectangle((round(12 * k), y, round((12 + 50 + (i * 17) % 24) * k), y + round(6 * k)), fill=bars + (255,))
        d.rectangle((round(120 * k), y, round((120 + 150 + (i * 53) % 190) * k), y + round(6 * k)), fill=bars + (255,))
    d.rectangle((round(120 * k), round(262 * k), round(440 * k), round(286 * k)), fill=accent + (255,))
    px = round(R.PLACEHOLDER_ICON * k)
    face = R._icon_square(icon, px) if icon is not None else R.letter_tile(app, px, engine)
    image.alpha_composite(face, ((w - px) // 2, (h - px) // 2))
    return image


# ---------------------------------------------------------------- preview backend
class PreviewBackend:
    """Records the engine's window, DWM and layer output instead of calling Win32."""

    host_mode = c.HOST_LAYERED

    def __init__(self, monitor, sources, stub_sizes=None):
        self.monitor = monitor
        self.sources = sources                  # hwnd -> wireframe image
        self.stub_sizes = dict(stub_sizes or {})
        self.queue = []
        self.on_event = self.on_input = None
        self.thumbs = {}                        # handle -> hwnd (registration order)
        self.props = {}                         # handle -> (dest, source, opacity, visible)
        self.next = 1000
        self.chrome = None
        self.chrome_rect = None
        self.toast = None
        self.toast_rect = None
        self.toast_alpha = 0
        self.dim = None
        self.dim_alpha_value = 0
        self.glass_image = None
        self.glass_rect = None
        self.glass_alpha_value = 0
        self.host_rect = None
        self.visible = set()

    host_hwnd = 0x5001

    def prepare_thread(self):
        return 2

    def create(self, on_event, on_input):
        self.on_event, self.on_input = on_event, on_input
        return self.host_hwnd

    def post(self, code):
        self.queue.append(code)
        return True

    def post_quit(self):
        return True

    def pump(self):
        while self.queue:
            self.on_event(c.POSTED_EVENTS[self.queue.pop(0)])
        return True

    def wait(self, timeout):
        return True

    def pace(self):
        return "flush"

    def monitor_rect(self, origin):
        return self.monitor

    def show_host(self, rect):
        self.host_rect = tuple(rect)            # the pane: where the DWM thumbnails go
        self.visible.add("host")
        return True

    def set_host_passive(self, passive):
        pass

    def host_paint(self, image):
        pass

    def set_affinity(self, exclude):
        return True

    def set_toast_affinity(self, exclude):
        return True

    def chrome_alloc(self, rect):
        self.chrome_rect = tuple(rect)
        self.chrome = R.Canvas.new(rect[2:])
        return self.chrome

    def chrome_canvas(self):
        return self.chrome

    def chrome_present(self):
        return True

    def chrome_show(self):
        self.visible.add("chrome")

    def chrome_free(self):
        self.chrome = None

    def dim_upload(self, layout, background):
        self.dim = (layout, background)

    def dim_show(self):
        self.visible.add("dim")

    def dim_alpha(self, alpha):
        self.dim_alpha_value = alpha

    def glass_upload(self, rect, image):
        self.glass_rect, self.glass_image = tuple(rect), image
        self.visible.add("glass")

    def glass_alpha(self, alpha):
        self.glass_alpha_value = alpha

    def toast_alloc(self, rect):
        self.toast_rect = tuple(rect)
        self.toast = R.Canvas.new(rect[2:])
        return self.toast

    def toast_canvas(self):
        return self.toast

    def toast_present(self, alpha):
        self.toast_alpha = alpha

    def toast_show(self):
        self.visible.add("toast")

    def toast_hide(self):
        self.visible.discard("toast")

    def toast_free(self):
        self.toast = None

    def hide_layers(self):
        for role in ("chrome", "host", "glass", "dim"):
            self.visible.discard(role)

    def free_large(self):
        pass

    def use_plain_host(self):
        pass

    def use_layered_host(self):
        return True

    def activate(self):
        """What the adapter's native.focus(host) causes: the host's WM_ACTIVATE posts
        WM_APP_ACTIVATED, and the engine starts the open's heavy setup (layers, first frame)."""
        return self.post(c.WM_APP_ACTIVATED)

    def register(self, hwnd):
        self.next += 1
        self.thumbs[self.next] = hwnd
        return self.next

    def source_size(self, handle):
        hwnd = self.thumbs.get(handle)
        if hwnd in self.stub_sizes:
            return self.stub_sizes[hwnd]
        return self.sources[hwnd].size

    def update_thumbnail(self, handle, dest, source, opacity, visible):
        self.props[handle] = (tuple(dest), tuple(source), opacity, visible)
        return True

    def unregister(self, handle):
        self.thumbs.pop(handle, None)
        self.props.pop(handle, None)

    def prepare_capture_thread(self):
        pass

    def flush(self):
        return 0

    def capture(self, rect):
        raise OSError("previews never read the screen")

    def destroy_windows(self):
        self.visible.clear()

    def unregister_classes(self):
        pass

    def destroy(self):
        self.destroy_windows()

    def gui_resources(self):
        return (0, 0)

    # ---------------------------------------------------------- composite
    def frost_layer(self):
        """The glass window's content as straight RGBA (a premultiplied Canvas from frost_canvas
        or solid_frost, or a straight image), or None."""
        image = self.glass_image
        if image is None:
            return None
        return image.straight() if isinstance(image, R.Canvas) else image.convert("RGBA")

    def render(self, background_image):
        """What the screen would show: wallpaper, dim, the frost, thumbnails, chrome, toast."""
        out = background_image.convert("RGBA")
        ml, mt = self.monitor[0], self.monitor[1]
        if "dim" in self.visible and self.dim is not None and self.dim_alpha_value:
            layout, background = self.dim
            dim = R.build_dim(R.Canvas.new(layout.monitor_rect[2:]), layout, background).straight()
            out.alpha_composite(_fade(dim, self.dim_alpha_value), (layout.monitor[0] - ml, layout.monitor[1] - mt))
        if "glass" in self.visible and self.glass_image is not None and self.glass_alpha_value:
            x, y = self.glass_rect[0] - ml, self.glass_rect[1] - mt
            out.alpha_composite(_fade(self.frost_layer(), self.glass_alpha_value), (x, y))
        if "host" in self.visible and self.host_rect is not None:
            pane = self.host_rect                               # the host's client area
            pane_x, pane_y = pane[0] - ml, pane[1] - mt
            for handle, hwnd in self.thumbs.items():            # z-order is registration order
                props = self.props.get(handle)
                if not props or not props[3]:
                    continue
                dest, source, opacity, _ = props
                w, h = dest[2] - dest[0], dest[3] - dest[1]
                if w <= 0 or h <= 0 or not opacity:
                    continue
                frame = self.sources[hwnd].crop(source).resize((w, h), Image.Resampling.BILINEAR)
                out.alpha_composite(_fade(frame, opacity), (pane_x + dest[0], pane_y + dest[1]))
        if "chrome" in self.visible and self.chrome is not None:
            out.alpha_composite(self.chrome.straight(), (self.chrome_rect[0] - ml, self.chrome_rect[1] - mt))
        if "toast" in self.visible and self.toast is not None and self.toast_alpha:
            out.alpha_composite(_fade(self.toast.straight(), self.toast_alpha),
                                (self.toast_rect[0] - ml, self.toast_rect[1] - mt))
        return out.convert("RGB")


def _fade(image, alpha255):
    image = image.convert("RGBA")
    if alpha255 >= 255:
        return image
    r, g, b, a = image.split()
    return Image.merge("RGBA", (r, g, b, a.point([round(v * alpha255 / 255) for v in range(256)])))


class PreviewCapture:
    """Completes capture jobs synchronously from the sample wallpaper (never the screen)."""

    def __init__(self, backend, wall):
        self.backend = backend
        self.wall = wall
        self.results = []

    def submit(self, job):
        x, y, w, h = job.rect
        ml, mt = self.backend.monitor[0], self.backend.monitor[1]
        crop = self.wall.crop((x - ml, y - mt, x - ml + w, y - mt + h))
        # "frost": the section 11 background over the job's rect (rcMonitor on the layered host),
        # exactly what CaptureWorker hands the carousel thread; the toast's capture stays raw.
        image = R.frost_canvas(crop, job.k) if job.kind == "frost" else crop
        self.results.append(c.CaptureResult(job.gen, job.kind, image, 0.0, 0.0, None))
        self.backend.post(c.WM_APP_CAPTURED)
        return True

    def take_results(self):
        results, self.results = self.results, []
        return results

    def close(self, timeout=None):
        return True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- scenarios
class Scene:
    def __init__(self, k, background="glass", labels=None, closed=(), stubs=None, windows=None, monitor=None):
        self.monitor = tuple(monitor) if monitor else (0, 0, round(R.STAGE_W * k), round(R.STAGE_H * k))
        layout = R.layout_for(self.monitor)
        self.k = k = layout.k
        self.windows = windows or WINDOWS
        self.engine = R.TextEngine()
        size = (self.monitor[2] - self.monitor[0], self.monitor[3] - self.monitor[1])
        self.wall = wallpaper(size, k, (layout.stage_x - self.monitor[0], layout.stage_y - self.monitor[1]))
        icons = {}
        sources = {}
        items = []
        for i, (app, title, desc, icon_name, theme) in enumerate(self.windows):
            icon = load_icon(icon_name)
            icons[f"w{i}"] = icon
            sources[100 + i] = wireframe(theme, icon, app, k, self.engine)
            items.append({"id": f"w{i}", "hwnd": 100 + i, "pid": 20, "app": app, "title": title,
                          "available": i not in closed, "minimized": i in MINIMIZED})
        self.items = items
        self.clock = Clock()
        self.backend = PreviewBackend(self.monitor, sources, {100 + i: size for i, size in (stubs or {}).items()})
        self.capture = PreviewCapture(self.backend, self.wall)
        self.presenter = c.CarouselPresenter(None, None, None, backend=self.backend, capture=self.capture,
                                             clock=self.clock, inline=True)
        self.presenter.set_background(background)
        self.presenter.set_icons(icons)
        base = {f"w{i}": R.SimpleLabel(app, title, desc) for i, (app, title, desc, _, _) in enumerate(self.windows)}
        base.update(labels or {})
        self.presenter.set_labels(base)
        self.compose_ms = []

    def step(self, seconds, fps=60):
        end = self.clock.t + seconds
        status = self.presenter._status
        while self.clock.t < end - 1e-9:
            self.clock.t = min(end, self.clock.t + 1 / fps)
            frames = status.frames
            self.presenter._step_inline(pace=False)
            if status.frames > frames and status.compose_ms is not None:
                self.compose_ms.append(status.compose_ms)      # frames the engine really composed

    def show(self, index):
        self.presenter.show({"items": self.items, "index": index, "origin": {"hwnd": 100, "pid": 20}})
        self.backend.activate()                # the adapter focuses the host right after show()

    def open(self, index):
        self.show(index)
        self.step(1.0)
        return self

    def image(self):
        return self.backend.render(self.wall)

    def frost_edges(self, image):
        """CAROUSEL.md section 11: the frost reaches all four screen edges. Nothing but the
        glass window covers the screen's edges (the pane, chrome and toast sit inside the
        stage), so every EDGE_PX strip must equal the wallpaper under the frost at the glass
        window's constant alpha, and the glass window must be exactly rcMonitor. At rest
        (alpha 255) each strip must also differ from the bare wallpaper almost everywhere
        (> 90 % of its pixels by more than 2 levels). None when no frost is up."""
        backend = self.backend
        if "glass" not in backend.visible or backend.glass_image is None or not backend.glass_alpha_value:
            return None
        ml, mt = self.monitor[0], self.monitor[1]
        monitor_rect = (ml, mt, self.monitor[2] - ml, self.monitor[3] - mt)
        expected = self.wall.convert("RGBA")
        expected.alpha_composite(_fade(backend.frost_layer(), backend.glass_alpha_value),
                                 (backend.glass_rect[0] - ml, backend.glass_rect[1] - mt))
        expected = expected.convert("RGB")
        w, h = image.size
        strips = {"top": (0, 0, w, EDGE_PX), "bottom": (0, h - EDGE_PX, w, h),
                  "left": (0, 0, EDGE_PX, h), "right": (w - EDGE_PX, 0, w, h)}
        edges = {}
        for edge, box in strips.items():
            got = image.crop(box)
            exact = max(high for _low, high in ImageChops.difference(got, expected.crop(box)).getextrema()) <= 2
            changed = ImageChops.difference(got, self.wall.crop(box)).convert("L").point(lambda v: 255 if v > 2 else 0)
            frosted = changed.histogram()[255] / (changed.size[0] * changed.size[1])
            edges[edge] = {"frost": bool(exact and (backend.glass_alpha_value < 255 or frosted > 0.9)),
                           "changed": round(frosted, 3)}
        ok = tuple(backend.glass_rect) == monitor_rect and all(e["frost"] for e in edges.values())
        return {"ok": ok, "glass_rect": list(backend.glass_rect), "monitor_rect": list(monitor_rect),
                "glass_alpha": backend.glass_alpha_value, "edges": edges}

    def close(self):
        self.presenter.close()


def letter_tile_sheet(k, engine):
    names = ["Bambu Studio", "File Explorer", "Steam", "Notepad", "Visual Studio Code", "\u4e2d\u6587\u5e94\u7528",
             "7-Zip", "Zoom"]
    sizes = [round(32 * k), round(18 * k), round(96 * k)]
    pad = round(12 * k)
    width = pad + len(names) * (max(sizes) + pad)
    height = pad + sum(s + pad for s in sizes)
    sheet = Image.new("RGBA", (width, height), (24, 24, 26, 255))
    y = pad
    for size in sizes:
        for i, name in enumerate(names):
            sheet.alpha_composite(R.letter_tile(name, size, engine), (pad + i * (max(sizes) + pad), y))
        y += size + pad
    return sheet.convert("RGB")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    k = 2.0
    if "--k" in argv:
        k = float(argv[argv.index("--k") + 1])
        args = [a for a in args if a != argv[argv.index("--k") + 1]]
    out = Path(args[0]) if args else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    long_title = ("Nano D Control Center: carousel layout, full-screen frost, thumbnails and the label column "
                  "with a title that is far too long for one line")
    cjk = "\u4f1a\u8bae\u8bb0\u5f55 \u00b7 \ud68c\uc758 \u00b7 \u0412\u0441\u0442\u0440\u0435\u0447\u0430 \u00b7 " \
          "\u039b\u03af\u03c3\u03c4\u03b1 \U0001F680 \u2705"
    ultrawide = (0, 0, round(2 * R.STAGE_W * k), round(R.STAGE_H * k))    # 32:9, the user's 5120 x 1440 at k = 2
    scenarios = [
        ("glass_sel0", dict(), 0, None),
        ("glass_sel1", dict(), 1, None),
        ("glass_sel_middle_letter_tile", dict(), 5, None),
        ("glass_sel_last_minimized", dict(), 9, None),
        ("glass_ultrawide_32x9_sel1", dict(monitor=ultrawide), 1, None),
        ("none_sel1", dict(background="none"), 1, None),
        ("none_sel_middle", dict(background="none"), 5, None),
        ("none_ultrawide_32x9_sel1", dict(background="none", monitor=ultrawide), 1, None),
        ("glass_closed_card", dict(closed={2}), 2, None),
        ("glass_minimized_last_frame", dict(), 6, None),
        ("glass_minimized_caption_stub", dict(stubs={6: (200, 54)}), 6, None),
        ("glass_long_title_ellipsis", dict(labels={"w1": R.SimpleLabel("Claude", long_title,
                                                                          "Conversation \u00b7 desktop app")}), 1, None),
        ("glass_cjk_emoji_fallback", dict(labels={"w3": R.SimpleLabel("ChatGPT", cjk, "Conversation \u00b7 desktop app")}),
         3, None),
        ("none_cjk_emoji_fallback", dict(background="none",
                                         labels={"w3": R.SimpleLabel("ChatGPT", cjk, "Conversation \u00b7 desktop app")}),
         3, None),
        ("glass_detent_mid_flight", dict(), 1, "detent"),
        ("glass_open_fade", dict(), 1, "open"),
        ("glass_switch_exit_mid", dict(), 1, "switch_mid"),
        ("toast_switch", dict(), 1, "switch"),
        ("toast_switch_long_title", dict(), 1, "switch_long"),
        ("toast_cancel", dict(), 1, "cancel"),
    ]
    summary = {"k": k, "scenarios": {}}
    thumbs = []
    frost_failures = []
    for name, options, index, action in scenarios:
        started = time.perf_counter()
        scene = Scene(k, **options)
        if action == "open":
            scene.show(index)
            scene.step(0.12)
        else:
            scene.open(index)
        if action == "detent":
            scene.presenter.highlight(index + 1)
            scene.step(0.12)
        elif action == "switch_mid":
            scene.presenter.play_switch_exit(f"{WINDOWS[index][0]}{R.SEP}{WINDOWS[index][1]}")
            scene.presenter.hide()
            scene.step(0.15)
        elif action == "switch":
            scene.presenter.play_switch_exit(f"{WINDOWS[index][0]}{R.SEP}{WINDOWS[index][1]}")
            scene.presenter.hide()
            scene.step(0.9)
        elif action == "switch_long":                    # the toast keeps the app and ellipsizes the title
            scene.presenter.play_switch_exit(f"{WINDOWS[index][0]}{R.SEP}{long_title} {long_title}")
            scene.presenter.hide()
            scene.step(0.9)
        elif action == "cancel":
            scene.presenter.play_cancel_exit()
            scene.presenter.hide()
            scene.step(0.8)
        image = scene.image()
        path = out / f"{name}.png"
        image.save(path)
        thumbs.append((name, image))
        timings = sorted(scene.compose_ms)
        frost = scene.frost_edges(image)
        if name.startswith("glass_") and not (frost and frost["ok"]):
            frost_failures.append(name)                 # section 11: every glass_* preview, edge to edge
        summary["scenarios"][name] = {
            "file": str(path), "index": index, "background": options.get("background", "glass"),
            "monitor": list(scene.monitor), "frost": frost,
            "compose_ms_median": timings[len(timings) // 2] if timings else None,
            "compose_ms_max": timings[-1] if timings else None,
            "frames": len(timings), "render_s": round(time.perf_counter() - started, 2),
        }
        scene.close()
        state = "" if frost is None else (" (frost to all four edges)" if frost["ok"] else " (FROST EDGE CHECK FAILED)")
        print(f"{name}: {path}{state}")
    tiles = letter_tile_sheet(k, R.TextEngine())
    tiles_path = out / "letter_tiles.png"
    tiles.save(tiles_path)
    summary["letter_tiles"] = str(tiles_path)
    cols = 4
    tw = 640
    th = round(tw * 720 / 1280)
    sheet = Image.new("RGB", (cols * tw, ((len(thumbs) + cols - 1) // cols) * (th + 28)), (12, 12, 12))
    draw = ImageDraw.Draw(sheet)
    for i, (name, image) in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * (th + 28)
        scale = min(tw / image.size[0], th / image.size[1])          # a 32:9 screen is letterboxed
        fitted = image.resize((max(1, round(image.size[0] * scale)), max(1, round(image.size[1] * scale))),
                              Image.Resampling.LANCZOS)
        sheet.paste(fitted, (x + (tw - fitted.size[0]) // 2, y + 28 + (th - fitted.size[1]) // 2))
        draw.text((x + 8, y + 8), name, fill=(230, 230, 230))
    sheet_path = out / "contact_sheet.png"
    sheet.save(sheet_path)
    summary["contact_sheet"] = str(sheet_path)
    summary["frost_edge_failures"] = frost_failures
    with open(out / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(f"contact sheet: {sheet_path}")
    if frost_failures:
        print(f"FROST EDGE CHECK FAILED: {', '.join(frost_failures)}")
        return 1
    print("every glass_* preview shows the frost reaching all four screen edges")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

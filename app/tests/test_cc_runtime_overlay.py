"""The floating knob's per-tick pipeline: ui.ControlCenterApp(chrome=False) driven by the
runtime (FLOATING_KNOB.md sections 1, 5 and 6), and Runtime.lcd_media's hi-res sources.

No Tk at all: a stand-in root (after/title/protocol/destroy only) and a stand-in
KnobOverlay. chrome=False must build no widget, so any widget construction here would
fail. Settings is exercised with stand-in widgets. No port, no window, no network.
"""
from concurrent.futures import Future
from io import BytesIO
import json
from pathlib import Path
from queue import Queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from control_center import runtime as runtime_module
from control_center import ui
from control_center import windows as w
from control_center.artwork import ArtworkResult
from control_center.overlay import OverlayScene
from control_center.presentation import RING_SEGMENTS
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows


class InlineExecutor:
    def __init__(self, **kwargs):
        self.jobs = []

    def submit(self, function, *args, **kwargs):
        self.jobs.append((function, args))
        return Future()

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class FakeRoot:
    """What ControlCenterApp(chrome=False) may use of the withdrawn root."""
    def __init__(self, log):
        self.log = log
        self.calls = []
        self.timers = {}
        self._next = 0

    def title(self, *args): self.calls.append(("title",) + args)
    def configure(self, **kwargs): self.calls.append(("configure", kwargs))
    def protocol(self, name, callback): self.calls.append(("protocol", name))
    def geometry(self, *args): self.calls.append(("geometry",) + args)
    def minsize(self, *args): self.calls.append(("minsize",) + args)
    def bind(self, *args): self.calls.append(("bind",) + args)
    def state(self): return "withdrawn"

    def after(self, ms, callback):
        self._next += 1
        self.timers[self._next] = (ms, callback)
        return self._next

    def after_cancel(self, ident):
        self.timers.pop(ident, None)

    def destroy(self):
        self.log.append("root.destroy")


class FakeBridge:
    def __init__(self, *args, **kwargs):
        self.events = Queue()
        self.commands = []
        self.closed = False
        self.serial = None
        self.media_capability = None

    def submit(self, command, value=None):
        self.commands.append((command, value))
        if command == "close":
            self.closed = True


class FakeKnobOverlay:
    """The KnobOverlay interface, recording every call (order in the shared log)."""
    def __init__(self, log, lcd_px=302, rect=(24, 479, 434, 434)):
        self.log = log
        self.wants_frames = False
        self.lcd_px = lcd_px
        self.rect = rect
        self.state = "hidden"
        self.scenes = []
        self.suppressed = []
        self.peeks = []

    def submit(self, scene):
        self.log.append("submit")
        self.scenes.append(scene)

    def touch(self):
        self.log.append("touch")

    def peek(self, seconds=2.5):
        self.peeks.append(seconds)

    def set_suppressed(self, reason, on):
        self.suppressed.append((reason, on))

    def metrics(self):
        return {"state": self.state}

    def close(self):
        self.log.append("overlay.close")


class FakePickerTop:
    def __init__(self, rect, mapped=True):
        self.rect, self.mapped = rect, mapped

    def winfo_ismapped(self): return self.mapped
    def winfo_rootx(self): return self.rect[0]
    def winfo_rooty(self): return self.rect[1]
    def winfo_width(self): return self.rect[2]
    def winfo_height(self): return self.rect[3]


class PickerWindows(SimulatedWindows):
    def __init__(self):
        super().__init__()
        self.overlay = SimpleNamespace(top=None)


class OverlayAppCase(unittest.TestCase):
    smoke = False

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.log = []
        self.windows = PickerWindows()
        for patcher in (patch.object(ui, "DATA_DIR", Path(temp.name)),
                        patch.object(ui, "BACKUP_DIR", Path(temp.name) / "backups"),
                        patch.object(ui, "ensure_ui_font", lambda root: ui.FALLBACK_FAMILY),
                        patch("control_center.device.DeviceBridge", FakeBridge),
                        patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor),
                        patch.object(ui.ControlCenterApp, "providers",
                                     lambda app, live: (SimulatedSonos(), SimulatedAppleMusic(), self.windows))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = FakeRoot(self.log)
        self.overlay = FakeKnobOverlay(self.log)
        self.app = ui.ControlCenterApp(self.root, smoke=self.smoke, live=False, chrome=False, overlay=self.overlay)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.app.closing = True
        try:
            self.app.runtime.shutdown(close_device=False)
        except Exception:
            pass

    def tick(self, count=1):
        for _ in range(count):
            self.app._poll_once()

    def connect(self):
        bridge = self.app.device
        bridge.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.tick()
        bridge.events.put({"kind": "ready", "id": self.app.controller.control_id})
        self.tick()
        self.assertTrue(self.app.runtime.device_connected and self.app.controller.ready)


class NoChromeTests(OverlayAppCase):
    def test_no_widget_no_window_sizing_no_key_bindings(self):
        self.assertFalse(self.app.chrome)
        names = [call[0] for call in self.root.calls]
        self.assertNotIn("geometry", names)
        self.assertNotIn("minsize", names)
        self.assertNotIn("bind", names)
        for widget in ("canvas", "connect_button", "device_label", "notice_label", "env_button",
                       "listbox", "turns", "hint", "lcd_photo", "ring_items", "button_items"):
            self.assertFalse(hasattr(self.app, widget), widget)
        self.assertIn(ui.POLL_MS, [ms for ms, _ in self.root.timers.values()], "the poll still runs")

    def test_panel_and_mirror_blanking_are_no_ops(self):
        frame = self.app.runtime.frame()
        self.app._render_panel(frame, True)
        self.app._blank_mirror()
        self.app.render(force=True)             # also what the picker's on_closed calls
        self.assertEqual(self.app.failure_counts, {})
        self.assertIsNone(self.app._dialog_parent())

    def test_the_gate_is_the_overlays_wants_frames(self):
        self.overlay.wants_frames = False
        self.assertFalse(self.app._mirror_visible())
        self.overlay.wants_frames = True
        self.assertTrue(self.app._mirror_visible())
        self.app.overlay = None
        self.assertFalse(self.app._mirror_visible())


class SceneTests(OverlayAppCase):
    def test_nothing_is_rendered_while_hidden(self):
        with patch.object(ui, "render_overlay_lcd", wraps=ui.render_overlay_lcd) as render:
            self.tick(3)
        render.assert_not_called()
        self.assertEqual(self.overlay.scenes, [])

    def test_scenes_follow_wants_frames_and_are_submitted_only_when_changed(self):
        self.connect()
        self.overlay.wants_frames = True
        self.tick()
        self.assertEqual(len(self.overlay.scenes), 1)
        scene = self.overlay.scenes[0]
        self.assertIsInstance(scene, OverlayScene)
        self.assertEqual((scene.lcd.mode, scene.lcd.size), ("RGBA", (302, 302)))
        self.assertEqual(len(scene.ring), RING_SEGMENTS)
        self.assertTrue(all(len(colour) == 4 for colour in scene.ring))
        self.tick(3)
        self.assertEqual(len(self.overlay.scenes), 1, "an unchanged scene is not submitted again")
        self.app.controller.button(1)            # Browse: the LCD changes
        self.tick()
        self.assertEqual(len(self.overlay.scenes), 2)
        self.assertNotEqual(self.overlay.scenes[1].lcd_key, scene.lcd_key)
        self.assertEqual(self.app.overlay_submits, 2)

    def test_the_lcd_is_drawn_at_the_overlays_size_with_hires_sources(self):
        self.connect()
        self.overlay.wants_frames = True
        with patch("control_center.lcd_preview.render_lcd", wraps=__import__(
                "control_center.lcd_preview", fromlist=["render_lcd"]).render_lcd) as render, \
                patch.object(self.app.runtime, "lcd_media", wraps=self.app.runtime.lcd_media) as media:
            self.tick()
        self.assertTrue(media.call_args.kwargs.get("hires"))
        self.assertAlmostEqual(render.call_args.kwargs["scale"], 302 / 240)
        self.assertIn("hires_cover", render.call_args.kwargs)
        self.overlay.lcd_px = 604                # a DPI change: the LCD is drawn again at the new size
        self.app.controller.turn(1)
        self.tick()
        self.assertEqual(self.overlay.scenes[-1].lcd.size, (604, 604))

    def test_at_240_px_the_knobs_own_lcd_is_drawn(self):
        self.overlay.lcd_px = 240
        self.connect()
        self.overlay.wants_frames = True
        with patch("control_center.lcd_preview.render_lcd", wraps=__import__(
                "control_center.lcd_preview", fromlist=["render_lcd"]).render_lcd) as render:
            self.tick()
        self.assertEqual(render.call_args.kwargs, {"scale": 1.0})
        frame = self.app.runtime.frame()
        self.assertEqual(self.overlay.scenes[-1].lcd.tobytes(), ui.render_lcd(frame).convert("RGBA").tobytes())

    def test_lcd_images_are_cached_and_never_replaced_in_place(self):
        self.connect()
        self.overlay.wants_frames = True
        self.tick()
        first = self.overlay.scenes[-1]
        self.app.controller.turn(1)
        self.tick()
        self.app.controller.turn(-1)
        self.tick()
        back = self.overlay.scenes[-1]
        self.assertEqual(back.lcd_key, first.lcd_key)
        self.assertIs(back.lcd, first.lcd, "the cached image is handed over again, not redrawn")


class HiresSourcesTests(OverlayAppCase):
    """The chrome=False pipeline hands render_overlay_lcd each hi-res source in its own slot:
    the decoded 480 px cover as hires_cover, the 128 px app icon as hires_icon."""

    def rendered(self, frame):
        self.overlay.wants_frames = True
        drawn = Image.new("RGBA", (302, 302), (1, 2, 3, 255))
        with patch.object(self.app.runtime, "frame", return_value=frame), \
                patch.object(ui, "render_overlay_lcd", return_value=drawn) as render:
            self.app.render(force=True)
        render.assert_called_once()
        self.assertIs(self.overlay.scenes[-1].lcd, drawn)
        self.assertEqual(render.call_args.kwargs["pixels"], 302)
        return render.call_args

    def test_the_hires_cover_is_passed_as_hires_cover(self):
        self.connect()
        preview = Image.new("RGB", (240, 240), (200, 10, 10))
        self.app.runtime.artwork_result = ArtworkResult(token=None, key="k1", preview=preview, rgb565=b"",
                                                        hires_jpeg=RuntimeHiresTests.jpeg((200, 10, 10)))
        args, kwargs = self.rendered(dict(self.app.runtime.frame(), artKey="k1"))
        self.assertIs(args[1], preview, "the 240 px cover stays the art argument")
        cover = kwargs["hires_cover"]
        self.assertEqual((cover.mode, cover.size), ("RGB", (480, 480)))
        self.assertEqual(cover.getpixel((240, 240))[0] // 10, 20)
        self.assertIsNone(kwargs["hires_icon"])

    def test_the_hires_icon_is_passed_as_hires_icon(self):
        self.connect()
        self.app.controller.button(3)                                  # Home 4: Win (simulated picker)
        self.tick()
        item = self.app._presented_window()
        self.assertIsNotNone(item)
        icon = Image.new("RGBA", (32, 32), (10, 200, 10, 255))
        big = Image.new("RGBA", (128, 128), (10, 200, 10, 255))
        self.app.runtime.window_icons[item["id"]] = icon
        self.app.runtime.window_hires[item["id"]] = (icon, big)          # a HiresIcon result, kept
        frame = self.app.runtime.frame()
        self.assertEqual(frame.get("layout"), "windows")
        args, kwargs = self.rendered(frame)
        self.assertIs(args[2], icon, "the 32 px icon stays the icon argument")
        self.assertIs(kwargs["hires_icon"], big)
        self.assertIsNone(kwargs["hires_cover"])


class TouchAndLightsTests(OverlayAppCase):
    def test_a_touch_submits_the_scene_first_then_touches_once(self):
        self.connect()
        self.log.clear()
        self.app.runtime.note_touch("turn")
        self.tick()
        self.assertEqual(self.log, ["submit", "touch"])
        self.tick(2)
        self.assertEqual(self.log.count("touch"), 1)
        self.app.runtime.note_touch("button")
        self.app.runtime.note_touch("hotkey")
        self.tick()
        self.assertEqual(self.log.count("touch"), 2, "one overlay.touch per tick with new touches")

    def test_physical_events_reach_the_overlay(self):
        self.connect()
        bridge = self.app.device
        bridge.events.put({"kind": "position", "id": self.app.controller.control_id, "p": 5})
        self.tick()
        self.assertIn("touch", self.log)

    def test_a_new_runtime_does_not_replay_touches(self):
        self.app.runtime.note_touch("turn")
        self.tick()
        self.log.clear()
        self.app._reset_mirror_state()
        self.tick()
        self.assertNotIn("touch", self.log)

    def test_lights_run_every_tick_while_connected_even_when_hidden(self):
        self.connect()
        with patch.object(self.app.preview_lights, "render", wraps=self.app.preview_lights.render) as lights:
            self.tick(3)
        self.assertEqual(lights.call_count, 3)
        self.assertEqual(self.overlay.scenes, [])

    def test_lights_pause_while_disconnected_and_reset_only_when_stale(self):
        with patch.object(self.app.preview_lights, "render", wraps=self.app.preview_lights.render) as lights, \
                patch.object(self.app.preview_lights, "reset", wraps=self.app.preview_lights.reset) as reset:
            self.tick(2)
            self.assertEqual(lights.call_count, 0)
            self.overlay.wants_frames = True        # (a peek) leaving hidden after skipped ticks
            self.tick()
            self.assertEqual(reset.call_count, 1)
            self.assertEqual(lights.call_count, 1)
        self.overlay.wants_frames = False
        self.connect()
        self.tick()
        with patch.object(self.app.preview_lights, "reset") as reset:
            self.app.runtime.note_touch("turn")     # continuous lights: the touch's flash is kept
            self.tick()
            reset.assert_not_called()

    def test_leaving_hidden_resubmits_the_same_scene(self):
        self.connect()
        self.overlay.wants_frames = True
        self.tick()
        self.overlay.wants_frames = False
        self.tick()
        self.overlay.wants_frames = True
        self.tick()
        self.assertEqual(len(self.overlay.scenes), 2)
        self.assertEqual(self.overlay.scenes[0].lcd_key, self.overlay.scenes[1].lcd_key)


class SuppressionTests(OverlayAppCase):
    def test_suppressed_while_disconnected_sent_only_on_change(self):
        self.tick(3)
        self.assertEqual(self.overlay.suppressed, [("disconnected", True), ("picker", False), ("carousel", False)])
        self.connect()
        self.tick(2)
        self.assertEqual(self.overlay.suppressed[-1], ("disconnected", False))
        self.assertEqual(self.overlay.suppressed.count(("disconnected", False)), 1)
        self.app.device.events.put({"kind": "disconnected", "message": "Knob disconnected"})
        self.tick()
        self.assertEqual(self.overlay.suppressed[-1], ("disconnected", True))

    def test_suppressed_while_the_picker_covers_the_knob(self):
        self.connect()
        self.windows.overlay.top = FakePickerTop((0, 100, 1200, 820))      # overlaps (24, 479, 434, 434)
        self.app.controller.button(3)                                        # Home 4: Win (simulated picker)
        self.tick()
        self.assertEqual(self.app.controller.screen.mode, "windows")
        self.assertEqual(self.overlay.suppressed[-1], ("picker", True))
        self.windows.overlay.top = FakePickerTop((1960, 286, 1200, 820))   # centred on 5120 px: clear
        self.tick()
        self.assertEqual(self.overlay.suppressed[-1], ("picker", False))
        self.windows.overlay.top = FakePickerTop((0, 100, 1200, 820), mapped=False)
        self.tick()
        self.assertEqual(self.overlay.suppressed.count(("picker", True)), 1)

    def test_the_carousel_holds_the_knob_hidden_while_open_wherever_it_is(self):
        # CAROUSEL.md section 11: reason 'carousel' for as long as the carousel publishes its rect
        # (open -> end of the exit), whatever the controller's mode and wherever the knob is; it is
        # sent before the tick's touch, so a touch meanwhile never slides the knob in.
        self.connect()
        self.tick()
        real = self.overlay.set_suppressed

        def spy(reason, on):
            self.log.append(("suppress", reason, on))
            real(reason, on)
        self.overlay.set_suppressed = spy
        picker = SimpleNamespace(rect=(1960, 160, 2280, 1120))            # clear of the knob (24, 479, 434, 434)
        self.windows.overlay = picker
        self.app.runtime.note_touch("turn")
        self.tick()
        self.assertEqual(self.overlay.suppressed[-1], ("carousel", True))
        self.assertNotIn(("picker", True), self.overlay.suppressed)
        self.assertLess(self.log.index(("suppress", "carousel", True)), len(self.log) - self.log[::-1].index("touch") - 1)
        self.assertNotEqual(self.app.controller.screen.mode, "windows")    # not keyed to the mode
        self.tick(3)
        self.assertEqual(self.overlay.suppressed.count(("carousel", True)), 1)
        picker.rect = None                                                  # the exit ended: torn down
        self.tick()
        self.assertEqual(self.overlay.suppressed[-1], ("carousel", False))

    def test_rects_overlap(self):
        self.assertTrue(ui.rects_overlap((0, 0, 10, 10), (9, 9, 5, 5)))
        self.assertFalse(ui.rects_overlap((0, 0, 10, 10), (10, 0, 5, 5)))
        self.assertFalse(ui.rects_overlap((0, 0, 10, 10), None))
        self.assertFalse(ui.rects_overlap((0, 0, 0, 10), (0, 0, 5, 5)))


class FailureAndCloseTests(OverlayAppCase):
    def test_a_failing_lcd_blanks_the_knob_once_and_recovers(self):
        self.connect()
        self.overlay.wants_frames = True
        with patch.object(ui, "render_overlay_lcd", side_effect=RuntimeError("renderer broke")), \
                self.assertLogs(ui._log.name, "ERROR"):
            self.tick(3)
        self.assertEqual(self.app.mirror_failures, 3)
        blanks = [scene for scene in self.overlay.scenes if scene.lcd is None]
        self.assertEqual(len(blanks), 1)
        self.assertEqual(blanks[0].ring, ((31, 31, 31, 0.0),) * RING_SEGMENTS)
        self.tick()
        self.assertIsNotNone(self.overlay.scenes[-1].lcd, "the next good tick draws in full")
        self.assertEqual(self.app.failure_counts.get("render", 0), 0)

    def test_peek(self):
        self.app.peek(2.5)
        self.assertEqual(self.overlay.peeks, [2.5])

    def test_close_closes_the_overlay_before_the_root(self):
        self.app.close()
        self.assertLess(self.log.index("overlay.close"), self.log.index("root.destroy"))


class SmokeModeTests(OverlayAppCase):
    smoke = True

    def test_the_smoke_ui_path_submits_scenes_without_a_device(self):
        self.overlay.wants_frames = True
        self.tick(2)
        self.assertIsNone(self.app.device)
        self.assertGreaterEqual(len(self.overlay.scenes), 1)
        self.assertGreaterEqual(self.app.lcd_renders, 1)

    def test_the_smoke_tests_overlay_composes_every_scene(self):
        import standalone
        smoke = standalone.SmokeOverlay(dpi=96)
        self.app.overlay = smoke
        self.app.controller.button(1)            # a few different frames
        self.tick(2)
        self.app.controller.button(0)
        self.tick(2)
        self.assertGreaterEqual(smoke.scenes, 2)
        self.assertEqual(smoke.errors, [])
        self.assertEqual(self.app.mirror_failures, 0)


class LiveServicesTests(OverlayAppCase):
    """Live mode's IconWorker: the HiresIcon 128 px copies only for the floating knob
    (chrome=False); the Windows carousel's facts channel and icon masters in both modes
    (CAROUSEL.md section 7), so the full window (app.py, --check-music) adds only facts=True."""

    def built_icon_worker(self):
        made = []

        class Service:
            def __init__(self, *args, **kwargs):
                made.append((type(self).__name__, kwargs))

            def close(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def request_many(self, *args, **kwargs): pass
            def clear(self): pass
            def poll(self): return []
        icons = type("IconWorker", (Service,), {})
        with patch("control_center.artwork.ArtworkService", type("ArtworkService", (Service,), {})), \
                patch("control_center.artwork.AccentService", type("AccentService", (Service,), {})), \
                patch("control_center.windows.IconWorker", icons):
            runtime = self.app._make_runtime(True, providers=(SimulatedSonos(), SimulatedAppleMusic(),
                                                              PickerWindows()))
        self.addCleanup(runtime.shutdown, close_device=False)
        self.assertIsInstance(runtime.icons, icons)
        return [kwargs for name, kwargs in made if name == "IconWorker"]

    def test_the_floating_knob_asks_for_hires_icons(self):
        self.assertEqual(self.built_icon_worker(), [{"hires": True, "facts": True}])

    def test_the_full_window_gets_the_pickers_facts_but_no_hires_copies(self):
        self.app.chrome = True
        self.assertEqual(self.built_icon_worker(), [{"facts": True}])


class DisabledOverlayTests(OverlayAppCase):
    def test_a_disabled_overlay_gets_no_scene_and_no_touch(self):
        self.overlay.state = "disabled"
        self.connect()
        self.app.runtime.note_touch("turn")
        with patch.object(ui, "render_overlay_lcd") as render:
            self.tick(2)
        render.assert_not_called()
        self.assertEqual(self.overlay.scenes, [])
        self.assertNotIn("touch", self.log)


class FakeWidget:
    def __init__(self, *args, **kwargs):
        self.values = dict(kwargs)
        self.calls = []
        self.geometries = []
        self.protocols = {}
        self.destroyed = False

    def pack(self, *args, **kwargs): pass
    def title(self, *args): pass
    def geometry(self, *args): self.geometries.extend(args)
    def transient(self, *args): self.calls.append("transient")
    def deiconify(self): self.calls.append("deiconify")
    def lift(self): self.calls.append("lift")
    def focus_force(self): self.calls.append("focus_force")
    def configure(self, **kwargs): self.values.update(kwargs)
    def bind(self, sequence, callback): self.protocols[sequence] = callback
    def protocol(self, name, callback): self.protocols[name] = callback
    def winfo_exists(self): return not self.destroyed
    def destroy(self): self.destroyed = True


class SettingsTests(OverlayAppCase):
    work_area = (0, 0, 1920, 1040)
    frame = (0, 0)                     # the title bar and borders (window_frame_extent)

    def open_settings(self):
        self.buttons = {}
        self.placements = []

        self.labels = []

        def show_fitted(window, width, height, place=None):
            # ui.show_fitted places a real Tk window while it is still withdrawn; the stand-in
            # window is not a tk.Wm, so this stand-in runs the placement the same way.
            self.placements.append(place)
            if place is not None:
                place(window, width, height)
            return None

        def button(parent, text, command, **kwargs):
            widget = FakeWidget(text=text)
            self.buttons[text] = (command, widget)
            return widget

        def label(parent, text="", size=11, color=None, **kwargs):
            widget = FakeWidget(text=text, color=color, **kwargs)
            self.labels.append(widget)
            return widget
        patches = [patch.object(ui, "button", button), patch.object(ui, "label", label),
                   patch.object(ui.tk, "Toplevel", FakeWidget), patch.object(ui.tk, "Frame", FakeWidget),
                   patch.object(ui.tk, "Entry", FakeWidget),
                   patch.object(ui.tk, "StringVar", lambda value="": SimpleNamespace(get=lambda: value,
                                                                                     set=lambda v: None)),
                   patch.object(ui, "show_fitted", show_fitted),
                   patch.object(ui, "primary_work_area", lambda window=None: self.work_area),
                   patch.object(ui, "window_frame_extent", lambda dpi=None: self.frame)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app.setup()
        return self.app.setup_window

    def test_settings_is_not_transient_and_is_brought_forward(self):
        win = self.open_settings()
        self.assertNotIn("transient", win.calls)
        self.assertEqual(win.calls[-3:], ["deiconify", "lift", "focus_force"])
        self.assertNotIn("Quit Desk Dial", self.buttons)
        win.calls.clear()
        self.app.setup()                         # tray Settings… again: the same window, forward
        self.assertIs(self.app.setup_window, win)
        self.assertEqual(win.calls, ["deiconify", "lift", "focus_force"])

    def test_tray_failure_adds_connect_and_quit(self):
        actions = []
        state = {"connected": False}
        self.app.setup_actions = {"connect": lambda: actions.append("connect"),
                                  "quit": lambda: actions.append("quit"),
                                  "label": lambda: "Disconnect knob" if state["connected"] else "Connect knob"}
        self.open_settings()
        self.buttons["Connect knob"][0]()
        self.buttons["Quit Desk Dial"][0]()
        self.assertEqual(actions, ["connect", "quit"])
        connect_widget = self.buttons["Connect knob"][1]
        state["connected"] = True
        self.tick()
        self.assertEqual(connect_widget.values["text"], "Disconnect knob")

    def test_tray_failure_settings_show_the_notice_until_dismissed(self):
        self.app.setup_actions = {"connect": lambda: None, "quit": lambda: None, "label": lambda: "Connect knob"}
        self.open_settings()
        notice = self.app.setup_notice_label
        self.assertIn(notice, self.labels)
        self.assertEqual(notice.values["text"], "")
        self.assertEqual(notice.values["color"], ui.NOTICE)
        self.app.controller.notice = "Skip failed"
        self.tick()
        self.assertEqual(notice.values["text"], "Skip failed  ·  Click to dismiss")
        notice.protocols["<Button-1>"](None)                   # a click dismisses it, as in v4
        self.assertEqual(self.app.controller.notice, "")
        self.tick()
        self.assertEqual(notice.values["text"], "")

    def test_plain_settings_have_no_notice_line(self):
        self.open_settings()
        self.assertIsNone(self.app.setup_notice_label)
        self.app.controller.notice = "Skip failed"
        self.tick()                                            # nothing to refresh, never an error
        self.assertEqual(self.app.failure_counts, {})

    def test_an_open_settings_window_gains_the_actions_after_a_tray_failure(self):
        first = self.open_settings()
        self.app.setup_actions = {"connect": lambda: None, "quit": lambda: None, "label": lambda: "Connect knob"}
        self.app.setup()
        self.assertTrue(first.destroyed)
        self.assertIsNot(self.app.setup_window, first)
        self.assertIn("Quit Desk Dial", self.buttons)

    # FLOATING_KNOB.md section 9.12: Settings has a position, clear of the always-on-top knob.
    def test_settings_open_centred_on_the_work_area(self):
        self.overlay.rect = (0, 303, 458, 434)          # the floating knob at 100 % on 1920 x 1040
        win = self.open_settings()
        self.assertEqual(len(self.placements), 1)
        self.assertIsNotNone(self.placements[0], "chrome=False places Settings")
        self.assertEqual(win.geometries[-1], "+660+95")  # (1920 - 600) / 2, (1040 - 850) / 2
        win.geometries.clear()
        self.app.setup()                                 # brought forward again: never moved
        self.assertEqual(win.geometries, [])

    def test_settings_move_right_of_the_knob_when_they_would_overlap(self):
        self.work_area = (0, 0, 1600, 1000)
        self.overlay.rect = (0, 175, 687, 651)           # the knob's box at 150 %
        win = self.open_settings()
        x, y = (int(part) for part in win.geometries[-1].lstrip("+").split("+"))
        self.assertEqual((x, y), (687 + ui.SETTINGS_GAP, 75))
        self.assertFalse(ui.rects_overlap((x, y) + ui.SETUP_SIZE, self.overlay.rect))

    def test_the_whole_window_stays_inside_a_small_work_area(self):
        # 1366 x 768 at 100 % (a 48 px taskbar): the 850 px Settings plus its title bar and
        # borders used to end about 170 px below the work area, Save and Authorize included.
        self.work_area = (0, 0, 1366, 720)
        self.frame = (16, 39)
        self.overlay.rect = (0, 143, 458, 434)
        win = self.open_settings()
        self.assertEqual(win.geometries, ["600x850", "600x681", "+482+0"])
        x, y = 482, 0
        self.assertLessEqual(y + 681 + 39, 720, "the outer bottom is inside the work area")
        self.assertLessEqual(x + 600 + 16, 1366)
        self.assertFalse(ui.rects_overlap((x, y, 616, 720), self.overlay.rect))
        self.assertEqual(win.calls[-3:], ["deiconify", "lift", "focus_force"])

    def test_the_frame_is_part_of_the_centred_box(self):
        self.frame = (16, 39)
        self.overlay.rect = (0, 303, 458, 434)
        win = self.open_settings()
        self.assertEqual(win.geometries, ["600x850", "+652+75"])  # (1920 - 616) / 2, (1040 - 889) / 2

    def test_a_disabled_overlay_or_unknown_work_area_still_opens_settings(self):
        self.overlay.rect = None
        win = self.open_settings()
        self.assertEqual(win.geometries[-1], "+660+95")
        self.app.setup_window = None
        self.work_area = None
        win = self.open_settings()
        self.assertFalse([spec for spec in win.geometries if spec.startswith("+")])
        self.assertEqual(win.calls[-3:], ["deiconify", "lift", "focus_force"])

    # FLOATING_KNOB.md section 9.13: the Apple Music authorization outcome reaches the desktop.
    def authorize(self, event):
        self.app.auth = SimpleNamespace(events=Queue(), stop=lambda: None)
        self.app.auth.events.put(event)
        self.tick()

    def test_the_authorization_outcome_shows_in_the_open_settings_note(self):
        self.open_settings()
        self.authorize({"event": "authorized"})
        self.assertEqual(self.app.setup_note.values["text"], "Apple Music connected · Home, then Browse")
        self.assertEqual(self.app.controller.screen.status, "Apple Music connected · Home, then Browse")
        self.assertEqual(self.app.take_tray_messages(), [], "a success shown in Settings needs no balloon")

    def test_a_failed_authorization_shows_in_settings_and_as_a_balloon(self):
        self.open_settings()
        self.authorize({"event": "error", "message": "Authorized, but credentials could not be saved."})
        self.assertEqual(self.app.setup_note.values["text"], "Authorized, but credentials could not be saved.")
        self.assertEqual(self.app.take_tray_messages(), ["Authorized, but credentials could not be saved."])
        self.assertEqual(self.app.take_tray_messages(), [], "taken once")

    def test_with_settings_closed_the_outcome_is_a_balloon(self):
        win = self.open_settings()
        win.protocols["WM_DELETE_WINDOW"]()              # the user closed Settings
        self.assertTrue(win.destroyed)
        self.assertIsNone(self.app._setup_set_note)
        self.authorize({"event": "authorized"})
        self.assertEqual(self.app.take_tray_messages(), ["Apple Music connected · Home, then Browse"])
        self.authorize({"event": "denied"})               # no message: the generic text
        self.assertEqual(self.app.take_tray_messages(), ["Authorization incomplete"])
        self.assertEqual(self.app.failure_counts.get("auth", 0), 0)

    def test_the_full_window_keeps_its_status_line_only(self):
        self.app.chrome = True
        self.authorize({"event": "error", "message": "Authorization failed"})
        self.assertEqual(self.app.controller.screen.status, "Authorization failed")
        self.assertEqual(self.app.take_tray_messages(), [])


class SettingsPlacementTests(unittest.TestCase):
    """ui.settings_origin and show_fitted's placement hook (FLOATING_KNOB.md section 9.12)."""

    def test_centred_when_clear(self):
        self.assertEqual(ui.settings_origin((0, 0, 2560, 1392), (600, 850), (0, 479, 458, 434)), (980, 271))
        self.assertEqual(ui.settings_origin((0, 0, 1920, 1040), (600, 850)), (660, 95))
        self.assertEqual(ui.settings_origin((-1920, 40, 0, 1080), (600, 850)), (-1260, 135))

    def test_right_of_the_knob_when_centring_would_overlap(self):
        self.assertEqual(ui.settings_origin((0, 0, 1600, 1000), (600, 850), (0, 175, 687, 651)), (711, 75))
        # A screen too narrow for both: as far right as the work area allows, never off it.
        self.assertEqual(ui.settings_origin((0, 0, 1280, 1000), (600, 850), (0, 175, 687, 651)), (680, 75))
        self.assertEqual(ui.settings_origin((0, 0, 500, 700), (600, 850), (0, 0, 458, 434)), (0, 0))

    def test_the_outer_window_stays_inside_the_work_area(self):
        # wm geometry +x+y places the outer rectangle: the frame counts for centring and clamping.
        self.assertEqual(ui.settings_origin((0, 0, 1366, 720), (600, 681), (0, 143, 458, 434), frame=(16, 39)),
                         (482, 0))
        self.assertEqual(ui.settings_origin((0, 0, 1600, 1000), (600, 850), (0, 175, 687, 651), frame=(16, 39)),
                         (711, 55))
        # Too narrow for both: the outer right edge stays on the work area.
        self.assertEqual(ui.settings_origin((0, 0, 1280, 1000), (600, 850), (0, 175, 687, 651), frame=(16, 39)),
                         (664, 55))
        for work, height, expected in (((0, 0, 1366, 720), 850, 681), ((0, 0, 1920, 1032), 850, 850),
                                       ((0, 0, 1280, 760), 993, 721), ((0, 0, 800, 300), 850, 400),
                                       ((0, 0, 800, 300), 380, 380), ((0, 40, 1536, 824), 850, 745)):
            with self.subTest(work=work, height=height):
                self.assertEqual(ui.settings_client_height(work, height, (16, 39)), expected)
                fitted = ui.settings_client_height(work, height, (16, 39))
                _x, y = ui.settings_origin(work, (600, fitted), frame=(16, 39))
                if fitted + 39 <= work[3] - work[1]:
                    self.assertLessEqual(y + fitted + 39, work[3])
                self.assertGreaterEqual(y, work[1])

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_window_frame_extent_is_the_title_bar_and_borders(self):
        width, height = ui.window_frame_extent(96)
        self.assertGreater(width, 0)
        self.assertGreater(height, width, "the title bar is taller than the side borders are wide")
        self.assertGreater(ui.window_frame_extent(192)[1], height)
        self.assertEqual(len(ui.window_frame_extent()), 2)

    def test_show_fitted_places_the_window_before_it_is_shown(self):
        events = []

        class Window(ui.tk.Wm):             # a tk.Wm stand-in: no Tk interpreter involved
            def withdraw(self): events.append("withdraw")
            def deiconify(self): events.append("deiconify")
            def update_idletasks(self): pass
            def winfo_reqheight(self): return 900
            def winfo_screenheight(self): return 1080
            def geometry(self, spec=None): events.append(("geometry", spec))

        grown = ui.show_fitted(Window(), 600, 850, place=lambda window, width, height: events.append(
            ("place", width, height)))
        self.assertEqual(grown, 900)
        self.assertEqual(events, ["withdraw", ("geometry", "600x900"), ("place", 600, 900), "deiconify"])
        events.clear()
        failing = Window()
        with self.assertLogs(ui._log.name, "ERROR"):
            ui.show_fitted(failing, 600, 950, place=lambda *args: 1 / 0)
        self.assertEqual(events[-1], "deiconify", "a failing placement never keeps Settings hidden")

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_primary_work_area_is_a_real_rectangle(self):
        left, top, right, bottom = ui.primary_work_area()
        self.assertGreater(right - left, 0)
        self.assertGreater(bottom - top, 0)


class AppIconTests(unittest.TestCase):
    """APP_ICON.md item 3: the root's iconphoto and the per-window .ico frames (a stand-in root
    and a stand-in Win32 API, no Tk, no window). The mapped-window check is in test_cc_ui.py."""

    class Root:
        def __init__(self, fail=None):
            self.calls, self.fail = [], fail

        def iconbitmap(self, *args, **kwargs):
            self.calls.append(("iconbitmap", args, kwargs))

        def iconphoto(self, default, *images):
            if self.fail == "photo":
                raise ui.tk.TclError("photo")
            self.calls.append(("iconphoto", default, images))

        def bind_class(self, tag, sequence, func, add=None):
            if self.fail == "bind":
                raise ui.tk.TclError("bind")
            self.calls.append(("bind_class", tag, sequence, func, add))

    class Api:
        """AppIconApi stand-in: DPI per window, loads and messages recorded."""
        METRICS = {96: (32, 16), 120: (40, 20), 144: (48, 24), 192: (64, 32)}

        def __init__(self, dpis, loads_fail=False):
            self.dpis, self.loads_fail = dpis, loads_fail
            self.loads, self.messages, self.classes = [], [], []

        def icon_sizes(self, hwnd):
            return self.METRICS[self.dpis[hwnd]]

        def load(self, path, size):
            self.loads.append((Path(path).name, size))
            return None if self.loads_fail else 0x7000 + size

        def set_window_icon(self, hwnd, which, handle):
            self.messages.append((hwnd, which, handle))

        def set_class_icon(self, hwnd, index, handle):
            self.classes.append((hwnd, index, handle))

    class Window(ui.tk.Wm):                  # a toplevel stand-in: no Tk interpreter involved
        def __init__(self, hwnd):
            self.hwnd = hwnd

        def wm_frame(self):
            return hex(self.hwnd)

    def test_the_root_gets_both_photos_and_every_toplevel_the_ico_frames(self):
        root = self.Root()
        icons = ui.AppWindowIcons(api=self.Api({}))
        applied = ui.apply_app_icon(root, photo_image=lambda path: ("photo", Path(path).name), window_icons=icons)
        self.assertEqual(applied, {"iconphoto": True, "windowIcons": True})
        self.assertEqual(root.calls, [
            ("iconphoto", True, (("photo", "nano-d-app-256.png"), ("photo", "nano-d-app-32.png"))),
            ("bind_class", "Toplevel", "<Map>", icons.on_map, "+"),
            ("bind_class", "Tk", "<Map>", icons.on_map, "+")])
        self.assertNotIn("iconbitmap", [call[0] for call in root.calls],
                         "Tk 8.6 cannot read the PNG-compressed frames of nano-d-app.ico")
        self.assertEqual(len(root._nanod_app_icons), 2, "the photos are kept alive")
        self.assertIs(root._nanod_window_icons, icons)
        self.assertEqual(icons.path, ui.APP_ICON_ICO)
        for path in (ui.APP_ICON_ICO,) + ui.APP_ICON_PHOTOS:
            self.assertTrue(path.is_file(), path)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_on_windows_the_window_icons_are_bound_by_default(self):
        root = self.Root()
        applied = ui.apply_app_icon(root, photo_image=lambda path: path)
        self.assertTrue(applied["windowIcons"])
        self.assertIsInstance(root._nanod_window_icons, ui.AppWindowIcons)
        self.assertIsInstance(root._nanod_window_icons.api, ui.AppIconApi)

    def test_a_failing_icon_never_stops_the_app(self):
        for fail, key in (("photo", "iconphoto"), ("bind", "windowIcons")):
            with self.subTest(fail=fail), self.assertLogs(ui._log.name, "WARNING"):
                applied = ui.apply_app_icon(self.Root(fail), photo_image=lambda path: path,
                                            window_icons=ui.AppWindowIcons(api=self.Api({})))
            self.assertFalse(applied[key])
            self.assertTrue(applied["windowIcons" if key == "iconphoto" else "iconphoto"])

    def test_each_mapped_window_gets_the_ico_frames_for_its_dpi(self):
        api = self.Api({0x10: 144, 0x20: 96})
        icons = ui.AppWindowIcons(api=api)
        icons.on_map(SimpleNamespace(widget=self.Window(0x10)))       # Settings at 150 %
        self.assertEqual(api.loads, [("nano-d-app.ico", 48), ("nano-d-app.ico", 24)])
        self.assertEqual(api.messages, [(0x10, ui.ICON_BIG, 0x7000 + 48), (0x10, ui.ICON_SMALL, 0x7000 + 24)])
        self.assertEqual(api.classes, [(0x10, ui.GCLP_HICON, 0x7000 + 48), (0x10, ui.GCLP_HICONSM, 0x7000 + 24)],
                         "the first mapped toplevel also sets the TkTopLevel class icons")
        icons.on_map(SimpleNamespace(widget=self.Window(0x20)))       # another window at 100 %
        self.assertEqual(api.loads[2:], [("nano-d-app.ico", 32), ("nano-d-app.ico", 16)])
        self.assertEqual(api.messages[2:], [(0x20, ui.ICON_BIG, 0x7000 + 32), (0x20, ui.ICON_SMALL, 0x7000 + 16)])
        self.assertEqual(len(api.classes), 2, "the class icons are set once")
        icons.on_map(SimpleNamespace(widget=self.Window(0x10)))       # mapped again: cached handles
        self.assertEqual(len(api.loads), 4)
        self.assertEqual(api.messages[-2:], [(0x10, ui.ICON_BIG, 0x7000 + 48), (0x10, ui.ICON_SMALL, 0x7000 + 24)])
        icons.on_map(SimpleNamespace(widget="not a toplevel"))
        icons.on_map(SimpleNamespace())
        self.assertEqual((len(api.messages), icons.windows, icons.failures), (6, 3, 0))

    def test_a_failed_load_is_logged_once_and_never_raises(self):
        api = self.Api({0x10: 96}, loads_fail=True)
        icons = ui.AppWindowIcons(api=api)
        with self.assertLogs(ui._log.name, "WARNING") as logs:
            icons.on_map(SimpleNamespace(widget=self.Window(0x10)))
            icons.on_map(SimpleNamespace(widget=self.Window(0x10)))
        self.assertEqual(len(logs.records), 1)
        self.assertEqual((api.messages, api.classes, icons.failures), ([], [], 2))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_loadimagew_gives_the_designers_frames_exactly(self):
        # No window: LoadImageW reads the PNG-compressed frames Tk 8.6 cannot, and each HICON
        # holds exactly that size's drawing (the hand-tuned small one at 16-24 px).
        api, reader = ui.AppIconApi(), w.IconApi()
        big, small = api.icon_sizes(None)                # no window: the system metrics
        self.assertGreater(big, small)
        self.assertGreaterEqual(small, 16)
        for size in (16, 20, 24, 32, 40, 48, 64):
            with self.subTest(size=size):
                handle = api.load(ui.APP_ICON_ICO, size)
                self.assertTrue(handle)
                try:
                    pixels = reader.icon_image(handle)
                finally:
                    reader.destroy_icon(handle)
                with Image.open(ui.APP_ICON_DIR / "png" / f"nano-d-app-{size}.png") as png:
                    expected = png.convert("RGBA")
                self.assertEqual(pixels.size, (size, size))
                self.assertEqual(pixels.tobytes(), expected.tobytes())


class RuntimeHiresTests(unittest.TestCase):
    """Runtime.lcd_media(hires=True): the decoded hi-res cover of the drawn result and the
    IconWorker's 128 px copy of the drawn icon; hires=False is unchanged."""

    def setUp(self):
        patcher = patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        from control_center.controller import Controller
        self.runtime = runtime_module.Runtime(Controller(), SimulatedSonos(), SimulatedAppleMusic(),
                                              SimulatedWindows(), None)
        self.addCleanup(self.runtime.shutdown)

    @staticmethod
    def jpeg(colour, size=480):
        data = BytesIO()
        Image.new("RGB", (size, size), colour).save(data, format="JPEG", quality=90)
        return data.getvalue()

    def test_the_hires_cover_comes_from_the_drawn_result_and_is_cached(self):
        preview = Image.new("RGB", (240, 240), (200, 10, 10))
        result = ArtworkResult(token=None, key="k1", preview=preview, rgb565=b"",
                               hires_jpeg=self.jpeg((200, 10, 10)))
        self.runtime.artwork_result = result
        frame = {"layout": "nowPlaying", "artKey": "k1"}
        base = self.runtime.lcd_media(frame)
        self.assertEqual(len(base), 4)
        art, icon, artwork2, identity, cover, big_icon = self.runtime.lcd_media(frame, hires=True)
        self.assertIs(art, preview)
        self.assertEqual((cover.mode, cover.size), ("RGB", (480, 480)))
        self.assertIsNone(big_icon)
        self.assertEqual(identity[:3], base[3])
        self.assertIs(self.runtime.lcd_media(frame, hires=True)[4], cover, "decoded once")
        # Another key: nothing drawn, so no hi-res cover either.
        self.assertIsNone(self.runtime.lcd_media({"layout": "nowPlaying", "artKey": "k2"}, hires=True)[4])

    def test_results_without_or_with_a_broken_hires_jpeg(self):
        preview = Image.new("RGB", (240, 240))
        frame = {"layout": "nowPlaying", "artKey": "k1"}
        self.runtime.artwork_result = ArtworkResult(token=None, key="k1", preview=preview, rgb565=b"")
        self.assertIsNone(self.runtime.lcd_media(frame, hires=True)[4])
        self.runtime.artwork_result = ArtworkResult(token=None, key="k1", preview=preview, rgb565=b"",
                                                    hires_jpeg=b"\xff\xd8 not a jpeg")
        self.assertIsNone(self.runtime.lcd_media(frame, hires=True)[4])
        self.assertIsNone(self.runtime.lcd_media(frame, hires=True)[4], "a failed decode is remembered")

    def test_artwork2_uses_the_same_results_hires_cover(self):
        self.runtime.artwork2 = True
        result = ArtworkResult(token=None, key="k1", preview=None, rgb565=b"",
                               jpeg=self.jpeg((5, 5, 5), 240), jpeg_key="j" * 24,
                               hires_jpeg=self.jpeg((5, 5, 5)))
        self.runtime.artwork_result = result
        art, _icon, artwork2, identity, cover, _big = self.runtime.lcd_media(
            {"layout": "nowPlaying", "artKey": "j" * 24}, hires=True)
        self.assertTrue(artwork2)
        self.assertEqual(art, result.jpeg)
        self.assertEqual(cover.size, (480, 480))
        self.assertEqual(identity[0], "j" * 24)

    class Icons:
        def __init__(self):
            self.results = []

        def request(self, items):
            pass

        def poll(self):
            results, self.results = self.results, []
            return results

        def close(self, timeout=None):
            pass

    def test_a_later_hires_result_is_kept_beside_the_same_32px_icon(self):
        self.runtime.icons = icons = self.Icons()
        icon = Image.new("RGBA", (32, 32), (10, 200, 10, 255))
        icons.results = [("w1", icon, 0x0AC80A)]
        self.runtime.poll()
        self.assertIs(self.runtime.window_icons["w1"], icon)
        revision = self.runtime._icons_revision
        self.assertIsNone(self.runtime.window_hires_icon("w1"))
        big = Image.new("RGBA", (128, 128), (10, 200, 10, 255))
        icons.results = [w.HiresIcon("w1", w.attach_hires_icon(icon.copy(), big), 0x0AC80A)]
        self.runtime.poll()
        self.assertIs(self.runtime.window_icons["w1"], icon, "the 32 px icon is not replaced")
        self.assertEqual(self.runtime._icons_revision, revision, "payloads and the picker are not redone")
        self.assertIs(self.runtime.window_hires_icon("w1"), big)
        media = self.runtime.lcd_media({"layout": "windows"}, {"id": "w1"}, hires=True)
        self.assertIs(media[1], icon)
        self.assertIs(media[5], big)
        # A new 32 px icon for the window: the old copy no longer applies.
        other = Image.new("RGBA", (32, 32), (200, 10, 10, 255))
        icons.results = [("w1", other, 0xC80A0A)]
        self.runtime.poll()
        self.assertIsNone(self.runtime.window_hires_icon("w1"))
        # A copy that no longer matches the current icon is stored like an ordinary result.
        icons.results = [w.HiresIcon("w1", w.attach_hires_icon(icon.copy(), big), 0x0AC80A)]
        self.runtime.poll()
        self.assertIsNot(self.runtime.window_icons["w1"], other)
        self.assertIs(self.runtime.window_hires_icon("w1"), big)
        self.assertEqual(self.runtime.accents[("window", "w1")], 0x0AC80A)

    def test_the_hires_icon_rides_with_the_drawn_32px_icon(self):
        icon = Image.new("RGBA", (32, 32), (10, 200, 10, 255))
        big = Image.new("RGBA", (128, 128), (10, 200, 10, 255))
        w.attach_hires_icon(icon, big)
        self.runtime.window_icons["w1"] = icon
        frame = {"layout": "windows"}
        media = self.runtime.lcd_media(frame, {"id": "w1"}, hires=True)
        self.assertIs(media[1], icon)
        self.assertIs(media[5], big)
        self.assertIsNone(self.runtime.lcd_media(frame, {"id": "other"}, hires=True)[5])
        self.assertIsNone(self.runtime.lcd_media({"layout": "volume"}, {"id": "w1"}, hires=True)[5])
        plain = Image.new("RGBA", (32, 32))
        self.runtime.window_icons["w2"] = plain
        self.assertIsNone(self.runtime.lcd_media(frame, {"id": "w2"}, hires=True)[5])
        self.assertNotEqual(media[3], self.runtime.lcd_media(frame, {"id": "w2"}, hires=True)[3])


class IconWorkerHiresTests(unittest.TestCase):
    """IconWorker keeps a 128 px copy only when the window's icon is the exe's icon, and sends
    it only after the snapshot's 32 px icons (a HiresIcon result), so the knob's payloads and
    ring accents never wait for the jumbo image list."""

    class Api:
        def __init__(self, source, reference, big, gate=None):
            self.source, self.reference, self.big = source, reference, big
            self.gate = gate
            self.hires_calls = []

        def co_initialize(self): return False
        def co_uninitialize(self): pass
        def window_icon(self, hwnd, kind): return 101 if kind == w.ICON_BIG else 0
        def icon_image(self, handle): return self.source.copy()
        def class_icon(self, hwnd, index): return 0
        def file_icon(self, path): return 0
        def destroy_icon(self, handle): pass

        def hires_icon(self, path):
            self.hires_calls.append(path)
            if self.gate is not None:
                self.gate.wait(3)
            return self.big, self.reference

    def collect(self, worker, count):
        found, until = [], time.monotonic() + 3
        while len(found) < count and time.monotonic() < until:
            found.extend(worker.poll())
            time.sleep(0.005)
        return found

    def nothing_more(self, worker):
        time.sleep(0.05)
        self.assertEqual(worker.poll(), [])

    def icons(self, colour):
        return (Image.new("RGBA", (48, 48), colour + (255,)), Image.new("RGBA", (32, 32), colour + (255,)),
                Image.new("RGBA", (256, 256), colour + (255,)))

    def test_a_matching_icon_carries_its_128px_copy_and_the_payload_and_accent_are_unchanged(self):
        from control_center.artwork import attached_icon_payload, dominant_rgb, icon_payload
        source, reference, big = self.icons((20, 120, 220))
        api = self.Api(source, reference, big)
        worker = w.IconWorker(api_factory=lambda: api, hires=True)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "a", "hwnd": 1, "path": r"C:\Apps\a.exe", "app": "a"},
                        {"id": "b", "hwnd": 2, "path": r"C:\APPS\A.EXE", "app": "a"}])
        found = self.collect(worker, 4)
        self.assertEqual([item for item, _, _ in found], ["a", "b", "a", "b"])
        self.assertEqual([getattr(result, "hires", False) for result in found], [False, False, True, True])
        for _, icon, accent in found[:2]:        # first: the 32 px icons, exactly as in cc5.3
            self.assertIsNone(w.attached_hires_icon(icon))
            self.assertEqual(icon.size, (32, 32))
            self.assertEqual(attached_icon_payload(icon), icon_payload(w.icon_thumbnail(source)))
            self.assertEqual(accent, dominant_rgb(source))
        for (_, first, accent), (_, icon, later_accent) in zip(found[:2], found[2:]):
            hires = w.attached_hires_icon(icon)
            self.assertEqual((hires.size, hires.mode), ((128, 128), "RGBA"))
            self.assertEqual(icon.tobytes(), first.tobytes(), "the same 32 px icon")
            self.assertEqual(attached_icon_payload(icon), attached_icon_payload(first))
            self.assertEqual(later_accent, accent)
        self.assertEqual(len(api.hires_calls), 1, "cached per exe path")
        self.nothing_more(worker)

    def test_the_32px_icons_never_wait_for_the_hires_extraction(self):
        source, reference, big = self.icons((20, 120, 220))
        gate = threading.Event()
        self.addCleanup(gate.set)
        api = self.Api(source, reference, big, gate)
        worker = w.IconWorker(api_factory=lambda: api, hires=True)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "a", "hwnd": 1, "path": r"C:\Apps\a.exe", "app": "a"},
                        {"id": "b", "hwnd": 2, "path": r"C:\Apps\b.exe", "app": "b"}])
        found = self.collect(worker, 2)          # the jumbo list is still blocked
        self.assertEqual([item for item, _, _ in found], ["a", "b"])
        self.assertFalse(any(getattr(result, "hires", False) for result in found))
        gate.set()
        later = self.collect(worker, 2)
        self.assertEqual([(item, getattr(result, "hires", False)) for result in later for item in result[:1]],
                         [("a", True), ("b", True)])

    def test_a_new_snapshot_drops_the_old_snapshots_hires_copies(self):
        source, reference, big = self.icons((20, 120, 220))
        gate = threading.Event()
        self.addCleanup(gate.set)
        api = self.Api(source, reference, big, gate)
        worker = w.IconWorker(api_factory=lambda: api, hires=True)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "old-1", "hwnd": 1, "path": r"C:\Apps\a.exe", "app": "a"},
                        {"id": "old-2", "hwnd": 2, "path": r"C:\Apps\b.exe", "app": "b"}])
        self.assertEqual([item for item, _, _ in self.collect(worker, 2)], ["old-1", "old-2"])
        until = time.monotonic() + 2
        while not api.hires_calls and time.monotonic() < until:
            time.sleep(0.005)                    # the worker is inside old-1's extraction
        worker.request([{"id": "new", "hwnd": 3, "path": r"C:\Apps\c.exe", "app": "c"}])
        gate.set()
        found = self.collect(worker, 2)
        self.assertEqual([(item, getattr(result, "hires", False)) for result in found for item in result[:1]],
                         [("new", False), ("new", True)])
        self.nothing_more(worker)
        self.assertEqual(api.hires_calls, [r"C:\Apps\a.exe", r"C:\Apps\c.exe"],
                         "old-2's copy was dropped unmade")

    def test_a_window_with_another_icon_gets_none(self):
        source, _reference, _big = self.icons((220, 20, 20))
        _s, reference, big = self.icons((20, 20, 220))
        worker = w.IconWorker(api_factory=lambda: self.Api(source, reference, big), hires=True)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "a", "hwnd": 1, "path": r"C:\Apps\a.exe", "app": "a"}])
        (_, icon, _), = self.collect(worker, 1)
        self.assertIsNotNone(icon)
        self.assertIsNone(w.attached_hires_icon(icon))
        self.nothing_more(worker)

    def test_failures_and_apis_without_hires_keep_the_32px_icon(self):
        source, reference, big = self.icons((20, 120, 220))
        api = self.Api(source, reference, big)
        api.hires_icon = lambda path: (_ for _ in ()).throw(OSError("shell"))
        worker = w.IconWorker(api_factory=lambda: api, hires=True)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "a", "hwnd": 1, "path": r"C:\Apps\a.exe", "app": "a"}])
        (_, icon, _), = self.collect(worker, 1)
        self.assertEqual(icon.size, (32, 32))
        self.assertIsNone(w.attached_hires_icon(icon))
        self.nothing_more(worker)

    def test_the_default_worker_is_cc53s_and_never_extracts_hires_copies(self):
        source, reference, big = self.icons((20, 120, 220))
        api = self.Api(source, reference, big)
        worker = w.IconWorker(api_factory=lambda: api)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "a", "hwnd": 1, "path": r"C:\Apps\a.exe", "app": "a"}])
        (_, icon, _), = self.collect(worker, 1)
        self.assertIsNone(w.attached_hires_icon(icon))
        self.nothing_more(worker)
        self.assertEqual(api.hires_calls, [])

    def test_helpers(self):
        corner = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        corner.paste(Image.new("RGBA", (48, 48), (9, 9, 9, 255)), (0, 0))
        self.assertTrue(w.small_jumbo(corner))
        self.assertTrue(w.small_jumbo(Image.new("RGBA", (256, 256), (0, 0, 0, 0))))
        self.assertFalse(w.small_jumbo(Image.new("RGBA", (256, 256), (9, 9, 9, 255))))
        self.assertTrue(w.icon_matches(Image.new("RGBA", (32, 32), (9, 9, 9, 255)),
                                       Image.new("RGBA", (256, 256), (9, 9, 9, 255))))
        self.assertFalse(w.icon_matches(None, Image.new("RGBA", (32, 32))))
        self.assertIsNone(w.attached_hires_icon(Image.new("RGBA", (32, 32))))
        wrong = Image.new("RGBA", (32, 32))
        wrong.info[w.ICON_HIRES_INFO] = Image.new("RGBA", (64, 64))
        self.assertIsNone(w.attached_hires_icon(wrong))
        self.assertIsNone(w.attached_hires_icon(None))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class IconApiHiresTests(unittest.TestCase):
    """Real shell image lists for this Python executable: no window, no other process."""

    def test_hires_icon_of_this_executable_and_no_handle_leak(self):
        import ctypes as C
        import gc
        user32 = C.WinDLL("user32", use_last_error=True)
        kernel32 = C.WinDLL("kernel32", use_last_error=True)
        user32.GetGuiResources.restype, user32.GetGuiResources.argtypes = C.c_uint32, (C.c_void_p, C.c_uint32)
        kernel32.GetCurrentProcess.restype = C.c_void_p

        def counts():
            process = kernel32.GetCurrentProcess()
            return user32.GetGuiResources(process, 0), user32.GetGuiResources(process, 1)
        api = w.IconApi()
        self.assertIs(api.get_image_list.restype, w.LONG)
        com = api.co_initialize()
        try:
            pair = api.hires_icon(sys.executable)
            self.assertIsNotNone(pair)
            big, reference = pair
            self.assertEqual((reference.size, reference.mode), ((32, 32), "RGBA"))
            self.assertGreaterEqual(big.width, 48)
            self.assertTrue(w.icon_matches(reference, w.fallback_icon_image(api, 0, sys.executable)))
            gc.collect()
            before = counts()
            for _ in range(20):
                api.hires_icon(sys.executable)
            gc.collect()
            after = counts()
            self.assertIsNone(api.hires_icon(""))
        finally:
            if com:
                api.co_uninitialize()
        self.assertLessEqual(after[0] - before[0], 2, f"GDI {before} -> {after}")
        self.assertLessEqual(after[1] - before[1], 2, f"USER {before} -> {after}")


if __name__ == "__main__":
    unittest.main()

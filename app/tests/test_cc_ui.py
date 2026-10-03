"""Desktop companion (control_center/ui.py): runtime builder, presentation settings,
knob mirror and robust poll. Real Tk (withdrawn), simulated providers, a fake
DeviceBridge and fake presentation services: no port, network or desktop action,
and every settings path points at a temporary DATA_DIR.
"""
import json
from pathlib import Path
from queue import Queue
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from PIL import Image

from control_center import ui
from control_center import windows as w
from control_center.artwork import ArtworkResult
from control_center.presentation import LEVELS, LED_GREEN, LED_WHITE, RING_SEGMENTS
from control_center.preview_lights import scale
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows


def _tk_available():
    try:
        probe = tk.Tk()
    except (tk.TclError, RuntimeError):  # no display, or a test guard that blocks Tk (it raises RuntimeError)
        return False
    probe.destroy()
    return True


TK = _tk_available()


class FakeBridge:
    """DeviceBridge stand-in: records commands, never opens a port."""
    instances = []

    def __init__(self, *args, **kwargs):
        self.events = Queue()
        self.commands = []
        self.closed = False
        self.serial = None
        self.capabilities = {}
        FakeBridge.instances.append(self)

    def submit(self, command, value=None):
        self.commands.append((command, value))
        if command == "close":
            self.closed = True

    def _emit(self, kind, **values):
        self.events.put({"kind": kind, **values})


class FakeService:
    """ArtworkService / AccentService / IconWorker stand-in (no threads, no I/O)."""
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.closed = False
        type(self).instances.append(self)

    def close(self, *args, **kwargs): self.closed = True
    def request(self, *args, **kwargs): pass
    def request_many(self, *args, **kwargs): pass
    def clear(self): pass
    def poll(self): return []


class FakeArtwork(FakeService):
    instances = []


class FakeAccents(FakeService):
    instances = []


class FakeIcons(FakeService):
    instances = []


class FakeOverlay:
    def __init__(self):
        self.icons = []

    def set_icons(self, icons):
        self.icons.append(icons)


class LiveWindows(SimulatedWindows):
    """What the live WindowsAdapter offers the runtime, without native calls."""
    def __init__(self):
        self.closed = False
        self.overlay = FakeOverlay()
        self.pumps = 0

    def close(self):
        self.closed = True

    def pump(self):
        self.pumps += 1


def fake_providers(app, live):
    return SimulatedSonos(), SimulatedAppleMusic(), LiveWindows() if live else SimulatedWindows()


class SettingsTests(unittest.TestCase):
    """load_config: defaults, tolerance of older files and validation (no Tk)."""
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        patcher = patch.object(ui, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, value):
        (self.data_dir / "settings.json").write_text(json.dumps(value), encoding="utf-8")

    def test_defaults_without_a_settings_file(self):
        config = ui.ControlCenterApp.load_config()
        self.assertEqual(config["led_style"], "color")
        self.assertIs(config["artwork"], True)

    def test_existing_settings_without_presentation_keys_get_the_defaults(self):
        self.write({"speaker_ip": "192.0.2.7", "port": "COM9", "button_order": [3, 1, 0, 2],
                    "button_order_verified": True})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["speaker_ip"], config["port"], config["button_order"]),
                         ("192.0.2.7", "COM9", [3, 1, 0, 2]))
        self.assertEqual((config["led_style"], config["artwork"]), ("color", True))

    def test_valid_presentation_settings_are_kept(self):
        self.write({"led_style": "white", "artwork": False})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["led_style"], config["artwork"]), ("white", False))

    def test_switcher_background_defaults_to_glass_and_keeps_valid_values(self):
        self.assertEqual(ui.ControlCenterApp.load_config()["picker_background"], "glass")
        self.write({"picker_background": "none"})
        self.assertEqual(ui.ControlCenterApp.load_config()["picker_background"], "none")
        for value in ("None", "blur", 0, None, ["none"]):
            with self.subTest(value=value):
                self.write({"picker_background": value})
                self.assertEqual(ui.ControlCenterApp.load_config()["picker_background"], "glass")

    def test_invalid_presentation_settings_fall_back(self):
        for led_style, artwork in (("rainbow", "yes"), (1, 1), (None, None), (["color"], 0), ("Color", "false")):
            with self.subTest(led_style=led_style, artwork=artwork):
                self.write({"led_style": led_style, "artwork": artwork, "port": "COM5"})
                config = ui.ControlCenterApp.load_config()
                self.assertEqual((config["led_style"], config["artwork"]), ("color", True))
                self.assertEqual(config["port"], "COM5")


class MirrorMathTests(unittest.TestCase):
    """Knob Face geometry and the optical mapping of PreviewLights drive values."""
    def test_segment_geometry_follows_knob_face(self):
        cx, cy = ui.MIRROR_CENTRE
        s = ui.MIRROR_SCALE

        def centre(i):
            points = ui.segment_polygon(i)
            return sum(points[::2]) / 4, sum(points[1::2]) / 4
        top, right, bottom = centre(0), centre(15), centre(30)
        self.assertAlmostEqual(top[0], cx)
        self.assertAlmostEqual(top[1], cy - 138 * s)
        self.assertAlmostEqual(right[0], cx + 138 * s)   # clockwise
        self.assertAlmostEqual(bottom[1], cy + 138 * s)
        xs, ys = ui.segment_polygon(0)[::2], ui.segment_polygon(0)[1::2]
        self.assertAlmostEqual(max(xs) - min(xs), 4 * s)
        self.assertAlmostEqual(max(ys) - min(ys), 10 * s)
        x0, y0, x1, y1 = ui.button_box(0)
        self.assertAlmostEqual(x1 - x0, 44 * s)
        self.assertAlmostEqual(ui.button_box(1)[0] - x0, 66 * s)
        width, height = ui.MIRROR_SIZE
        self.assertLessEqual(ui.button_box(3)[2], width)
        self.assertLessEqual(y1 + ui.STRIP_HEIGHT * s, height)

    def test_levels_map_to_knob_face_alphas(self):
        for level, alpha in zip(LEVELS, (0, .12, .34, .68, 1)):
            self.assertAlmostEqual(ui.optical_alpha(level), alpha)
        self.assertGreater(ui.optical_alpha(74), .34)   # odd-volume shoulder between L2 and L3
        self.assertLess(ui.optical_alpha(74), .68)

    def test_settled_cells_recover_colour_and_level(self):
        accent = 0x5865F2
        for colour in (LED_WHITE, LED_GREEN, accent):
            for level in LEVELS[1:]:
                with self.subTest(colour=hex(colour), level=level):
                    drive = scale(colour, level)
                    self.assertEqual(ui.led_source(drive, ui.LED_PALETTE + (accent,)), (colour, level))

    def test_display_colours_mix_from_the_unlit_floor(self):
        self.assertEqual(ui.ring_display(0), ui.SEGMENT_OFF)
        self.assertEqual(ui.ring_display(scale(LED_WHITE, LEVELS[4])), "#ffffff")
        # White at L2: 31 + (255 - 31) * .34 = 107.16 -> 0x6b
        self.assertEqual(ui.ring_display(scale(LED_WHITE, LEVELS[2])), "#6b6b6b")
        self.assertEqual(ui.strip_display(0), ui.STRIP_OFF)
        # A dim (L1) strip still shows at .18 over the #202020 face.
        self.assertEqual(ui.strip_display(scale(LED_WHITE, LEVELS[1])), "#484848")

    def test_lcd_cache_key_ignores_ring_noise_but_not_lcd_fields(self):
        frame = {"layout": "tracks", "title": "Next track",
                 "ring": {"style": "transport", "index": 2, "count": 3, "value": 1}}
        same = {**frame, "ring": {**frame["ring"], "value": 9, "external": True}}
        moved = {**frame, "ring": {**frame["ring"], "index": 0}}
        self.assertEqual(ui.lcd_cache_key(frame), ui.lcd_cache_key(same))
        self.assertNotEqual(ui.lcd_cache_key(frame), ui.lcd_cache_key(moved))


@unittest.skipUnless(TK, "Tk is unavailable")
class AppHarness(unittest.TestCase):
    live = False
    smoke = True
    settings = None
    chrome = True        # False: the installed app's floating knob (no window on the root)

    def make_overlay(self):
        """The KnobOverlay for chrome=False (a recording stand-in; no window)."""
        return None

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        if self.settings is not None:
            (self.data_dir / "settings.json").write_text(json.dumps(self.settings), encoding="utf-8")
        for cls in (FakeBridge, FakeArtwork, FakeAccents, FakeIcons):
            cls.instances = []
        for patcher in (patch.object(ui, "DATA_DIR", self.data_dir),
                        patch.object(ui, "BACKUP_DIR", self.data_dir / "backups"),
                        patch("control_center.device.DeviceBridge", FakeBridge),
                        patch("control_center.artwork.ArtworkService", FakeArtwork),
                        patch("control_center.artwork.AccentService", FakeAccents),
                        patch("control_center.windows.IconWorker", FakeIcons),
                        patch.object(ui.ControlCenterApp, "providers", fake_providers)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.overlay = self.make_overlay()
        # chrome=True: exactly the call the full-window tests always made.
        options = {} if self.chrome else {"chrome": False, "overlay": self.overlay}
        self.app = ui.ControlCenterApp(self.root, smoke=self.smoke, live=self.live, **options)
        self.addCleanup(self.close_app)

    def close_app(self):
        self.app.closing = True
        try:
            # A pending tick would fire into a later test's Tk event loop (the Tcl
            # notifier is per thread), also one a test lost by patching after().
            for after_id in self.root.tk.splitlist(self.root.tk.call("after", "info")):
                self.root.after_cancel(after_id)
        except Exception:
            pass
        try:
            self.app.runtime.shutdown(close_device=False)
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def pump(self, until=None, limit=2.0):
        """Poll without scheduling Tk timers (worker results arrive on threads)."""
        deadline = time.monotonic() + limit
        while True:
            self.app._poll_once()
            if until is None or until() or time.monotonic() > deadline:
                return
            time.sleep(0.005)


class SimulatorRuntimeTests(AppHarness):
    def test_simulator_has_no_network_services_and_applies_settings(self):
        runtime = self.app.runtime
        self.assertIsNone(runtime.artwork)
        self.assertIsNone(runtime.accent_service)
        self.assertIsNone(runtime.icons)
        self.assertEqual((runtime.led_style, runtime.artwork_enabled), ("color", True))
        self.assertEqual(runtime.button_order, self.app.config["button_order"])
        self.assertEqual(self.app.controller.windows_button, self.app.config["button_order"][3])   # K3 3.1: raw slot 3
        self.assertEqual((FakeArtwork.instances, FakeAccents.instances, FakeIcons.instances), ([], [], []))

    def test_simulator_controls_are_shown(self):
        for widget in (self.app.turns, self.app.listbox, self.app.env_button, self.app.hint):
            self.assertEqual(widget.winfo_manager(), "pack")

    def test_toggle_failure_keeps_the_current_runtime(self):
        runtime = self.app.runtime
        with patch.object(ui.ControlCenterApp, "providers", side_effect=RuntimeError("Setup required")), \
                patch.object(ui.messagebox, "showerror") as error:
            self.app.toggle_environment()
        error.assert_called_once()
        self.assertIs(self.app.runtime, runtime)
        self.assertFalse(self.app.live)
        self.assertFalse(runtime.closed)

    def test_toggle_failure_while_building_the_new_runtime_keeps_the_current_one(self):
        runtime, controller = self.app.runtime, self.app.controller
        built = []

        def providers(app, live):
            built.append(fake_providers(app, live))
            return built[-1]
        failures = (("artwork service", patch("control_center.artwork.ArtworkService",
                                               side_effect=RuntimeError("can't start new thread"))),
                    ("icon worker", patch("control_center.windows.IconWorker",
                                          side_effect=RuntimeError("can't start new thread"))),
                    ("runtime", patch.object(ui, "Runtime", side_effect=RuntimeError("no runtime"))))
        for name, failing in failures:
            with self.subTest(failing=name):
                for cls in (FakeArtwork, FakeAccents, FakeIcons):
                    cls.instances = []
                with patch.object(ui.ControlCenterApp, "providers", providers), failing, \
                        patch.object(ui.messagebox, "showerror") as error, \
                        self.assertLogs(ui._log.name, "ERROR"):
                    self.app.toggle_environment()   # never raises out of the Tk callback
                error.assert_called_once()
                self.assertEqual(error.call_args[0][0], "Setup required")
                self.assertIs(self.app.runtime, runtime)
                self.assertIs(self.app.controller, controller)
                self.assertIs(runtime.controller, controller)
                self.assertFalse(runtime.closed)
                self.assertFalse(self.app.live)
                self.assertEqual(self.app.env_button.cget("text"), "SIMULATOR")
                self.assertTrue(built[-1][2].closed, "the new live windows provider is closed")
                started = FakeArtwork.instances + FakeAccents.instances + FakeIcons.instances
                self.assertTrue(all(service.closed for service in started))
        self.assertEqual(len(built), len(failures))
        # The current runtime still polls: Sonos state arrives and the view responds.
        self.pump(lambda: self.app.controller.state.get("online"))
        self.assertTrue(self.app.controller.state.get("online"))
        self.app.controller.button(1)
        self.pump(lambda: self.app.controller.screen.mode == "recent")
        self.assertEqual(self.app.controller.screen.mode, "recent")


class LiveRuntimeTests(AppHarness):
    live = True

    def test_live_builds_artwork_accents_and_icons_for_the_speaker(self):
        runtime = self.app.runtime
        self.assertIs(runtime.artwork, FakeArtwork.instances[0])
        self.assertIs(runtime.accent_service, FakeAccents.instances[0])
        self.assertIs(runtime.icons, FakeIcons.instances[0])
        hosts = (self.app.config["speaker_ip"],)
        self.assertEqual(runtime.artwork.kwargs["speaker_hosts"], hosts)
        self.assertEqual(runtime.accent_service.kwargs["speaker_hosts"], hosts)

    def test_simulator_controls_are_hidden_in_live_mode(self):
        for widget in (self.app.turns, self.app.listbox, self.app.env_button, self.app.hint):
            self.assertEqual(widget.winfo_manager(), "")
        self.assertEqual(self.app.canvas.winfo_manager(), "pack")
        self.assertEqual(self.app.connect_button.winfo_manager(), "pack")

    def test_the_ui_tick_pumps_the_pickers_native_events(self):
        windows = self.app.runtime.windows
        self.pump()
        self.pump()
        self.assertGreaterEqual(windows.pumps, 2)

    def test_a_failing_pump_is_logged_once_and_the_tick_goes_on(self):
        runtime = self.app.runtime
        with patch.object(runtime.windows, "pump", side_effect=OSError("user32")), \
                patch.object(runtime.controller, "tick", wraps=runtime.controller.tick) as tick, \
                self.assertLogs("control_center.runtime", "WARNING") as logs:
            runtime.poll()
            runtime.poll()
        self.assertEqual(tick.call_count, 2)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(self.app.failure_counts.get("runtime", 0), 0)

    def test_picker_receives_icons_when_they_change(self):
        overlay = self.app.runtime.windows.overlay
        icon = Image.new("RGBA", (32, 32), (200, 40, 40, 255))
        self.pump()
        calls = len(overlay.icons)
        self.app.runtime.window_icons["1"] = icon
        self.pump()
        self.pump()
        self.assertEqual(len(overlay.icons), calls + 1)
        self.assertIs(overlay.icons[-1]["1"], icon)


class ToggleTests(AppHarness):
    smoke = False   # a (fake) DeviceBridge shared across the toggle
    settings = {"led_style": "white", "artwork": False, "button_order": [3, 1, 0, 2]}

    def test_toggle_keeps_settings_and_the_device_bridge(self):
        bridge = self.app.device
        self.assertIsInstance(bridge, FakeBridge)
        simulator = self.app.runtime
        self.app.toggle_environment()
        live = self.app.runtime
        self.assertTrue(self.app.live)
        self.assertTrue(simulator.closed)
        self.assertIsNot(live, simulator)
        self.assertIs(live.device, bridge)
        self.assertEqual((live.led_style, live.artwork_enabled), ("white", False))
        self.assertEqual(live.button_order, [3, 1, 0, 2])
        self.assertEqual(self.app.controller.windows_button, 2)            # button_order[3] (K3 3.1)
        self.assertIs(live.controller, self.app.controller)
        self.assertEqual(self.app.config["led_style"], "white")
        self.assertEqual(self.app.runtime.frame()["ledStyle"], "white")
        # Back to the simulator: the live runtime's own services stop, the bridge does not.
        windows = live.windows
        self.app.toggle_environment()
        self.assertFalse(self.app.live)
        self.assertTrue(live.closed and windows.closed)
        self.assertTrue(all(s.closed for s in FakeArtwork.instances + FakeAccents.instances + FakeIcons.instances))
        self.assertNotIn("close", [command for command, _ in bridge.commands])
        self.assertFalse(bridge.closed)
        self.assertIs(self.app.runtime.device, bridge)
        for widget in (self.app.turns, self.app.listbox, self.app.env_button, self.app.hint):
            self.assertEqual(widget.winfo_manager(), "pack")

    def test_toggle_resets_the_mirror_and_lights(self):
        self.app._lcd_key = "stale"
        with patch.object(self.app.preview_lights, "reset") as reset:
            self.app.toggle_environment()
        reset.assert_called()
        self.assertIsNone(self.app._lcd_key)

    def test_close_still_closes_the_device(self):
        bridge = self.app.device
        self.app.close()
        self.assertIn(("close", None), bridge.commands)


class SaveSettingsTests(AppHarness):
    def open_setup(self):
        commands = {}
        real = ui.button

        def spy(parent, text, command, **kwargs):
            commands[text] = command
            return real(parent, text, command, **kwargs)
        with patch.object(ui, "button", spy):
            self.app.setup()
        self.app.setup_window.withdraw()   # never shown during tests
        return commands

    def test_save_applies_presentation_live_without_reentering(self):
        self.pump(lambda: self.app.controller.state.get("online"))
        control_id = self.app.controller.control_id
        commands = self.open_setup()
        commands["Warm only"]()
        commands["Off"]()
        commands["Save settings"]()
        runtime = self.app.runtime
        self.assertEqual((runtime.led_style, runtime.artwork_enabled), ("white", False))
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["led_style"], saved["artwork"]), ("white", False))
        self.assertEqual(self.app.controller.control_id, control_id)
        self.assertFalse([e for e in self.app.controller.effects if e["kind"] == "device_enter"])
        self.assertEqual(runtime.frame()["ledStyle"], "white")
        # And back: Colour, artwork on.
        commands["Colour"]()
        commands["On"]()
        commands["Save settings"]()
        self.assertEqual((runtime.led_style, runtime.artwork_enabled), ("color", True))
        self.assertEqual(ui.ControlCenterApp.load_config()["led_style"], "color")

    def test_switcher_background_is_saved_and_applied_live(self):
        applied = []
        self.app.runtime.windows.set_picker_background = applied.append   # what WindowsAdapter offers
        commands = self.open_setup()
        commands["No background"]()
        commands["Save settings"]()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["picker_background"], "none")
        self.assertEqual(applied[-1], "none", "applied at once, like artwork and LEDs")
        self.assertEqual(ui.ControlCenterApp.load_config()["picker_background"], "none")
        commands["Frosted"]()
        commands["Save settings"]()
        self.assertEqual(applied[-1], "glass")
        self.assertEqual(ui.ControlCenterApp.load_config()["picker_background"], "glass")

    def test_no_background_is_disabled_on_the_plain_host_fallback(self):
        # CAROUSEL.md section 5: the carousel's plain host forces Frosted; a stored "none" is kept.
        self.app.config["picker_background"] = "none"
        self.app.runtime.windows.picker_backgrounds = ("glass",)   # what WindowsAdapter reports there
        widgets, texts = {}, []
        real_button, real_label = ui.button, ui.label

        def button_spy(parent, text, command, **kwargs):
            widgets[text] = real_button(parent, text, command, **kwargs)
            return widgets[text]

        def label_spy(parent, text="", *args, **kwargs):
            texts.append(text)
            return real_label(parent, text, *args, **kwargs)
        with patch.object(ui, "button", button_spy), patch.object(ui, "label", label_spy):
            self.app.setup()
        self.app.setup_window.withdraw()   # never shown during tests
        self.assertEqual(str(widgets["No background"].cget("state")), "disabled")
        self.assertEqual(str(widgets["Frosted"].cget("state")), "normal")
        self.assertIn(ui.PICKER_BACKGROUND_FALLBACK_NOTE, texts)
        widgets["No background"].invoke()                          # a disabled button does nothing
        widgets["Save settings"].invoke()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["picker_background"], "none", "kept for when it can be shown again")

    def test_credential_wording(self):
        texts = []
        real = ui.label

        def spy(parent, text="", *args, **kwargs):
            texts.append(text)
            return real(parent, text, *args, **kwargs)
        with patch.object(ui, "label", spy):
            self.app.setup()
        self.app.setup_window.withdraw()
        self.assertTrue(any("protected locally with Windows" in text for text in texts))
        self.assertIn("Album artwork", texts)
        self.assertIn("LEDs", texts)
        self.assertIn("Switcher background", texts)
        self.assertIn("Motion", texts)                              # K3 14.3 settings.motion
        # The choices only take effect on Save; the heading says so.
        self.assertTrue(any("Artwork, LEDs, Motion and the switcher background apply when saved" in text for text in texts))
        self.assertFalse(any("at once" in text for text in texts))
        self.assertFalse(any("next live connection" in text for text in texts))


class SetupNoteTests(SaveSettingsTests):
    """The Save confirmation fits the fitted Setup window and names what the live UI
    offers. The window stays unmapped (transient of the withdrawn test root):
    sizes are Tk's requested sizes and the size the dialog was fitted to."""
    test_save_applies_presentation_live_without_reentering = None
    test_switcher_background_is_saved_and_applied_live = None
    test_no_background_is_disabled_on_the_plain_host_fallback = None
    test_credential_wording = None

    def assert_fits(self, win):
        win.update_idletasks()
        cap = win.winfo_screenheight() - ui.SCREEN_MARGIN
        self.assertGreaterEqual(self.app.setup_size[1], min(win.winfo_reqheight(), cap),
                                "the content needs more than the window was given")

    def saved_note(self):
        commands = self.open_setup()
        win, note = self.app.setup_window, self.app.setup_note
        win.update_idletasks()
        reserved, fitted = note.winfo_reqheight(), list(self.app.setup_size)
        self.assert_fits(win)
        commands["Save settings"]()
        win.update_idletasks()
        return win, note, reserved, fitted

    def test_the_confirmation_fits_its_reserved_space(self):
        win, note, reserved, fitted = self.saved_note()
        self.assertEqual(note.cget("text"), ui.SETUP_SAVED_NOTES[self.app.live])
        self.assertLessEqual(note.winfo_reqheight(), reserved, "clipped at the fitted size")
        self.assertEqual(self.app.setup_size, fitted, "no jump: the space was already there")
        self.assert_fits(win)

    def test_the_wording_matches_what_the_ui_offers(self):
        _win, note, _reserved, _fitted = self.saved_note()
        text = note.cget("text")
        self.assertNotIn("restart live mode", text)
        self.assertIn("apply now", text)
        self.assertIn("Album artwork and LED style", text)
        self.assertIn("next time live mode starts", text)   # the simulator can switch to live

    def test_a_long_message_grows_the_window_instead_of_clipping(self):
        commands = self.open_setup()
        win = self.app.setup_window
        before = self.app.setup_size[1]
        message = "Apple Music could not be reached from this computer right now. " * 20

        class FailingStore:
            def __init__(self, *args, **kwargs):
                pass

            def load(self):
                raise RuntimeError(message)
        with patch("control_center.credentials.CredentialStore", FailingStore):
            commands["Authorize Apple Music"]()
        self.assertEqual(self.app.setup_note.cget("text"), message)
        cap = win.winfo_screenheight() - ui.SCREEN_MARGIN
        self.assertTrue(self.app.setup_size[1] > before or before >= cap, "the window grew")
        self.assert_fits(win)

    def test_refit_grows_to_content_and_never_shrinks(self):
        top = tk.Toplevel(self.root)
        top.withdraw()
        self.addCleanup(top.destroy)
        filler = tk.Frame(top, height=300, width=100)
        filler.pack()
        size = [600, 400]
        self.assertIsNone(ui.refit_height(top, size))
        filler.configure(height=520)
        self.assertEqual(ui.refit_height(top, size), 520)
        self.assertEqual(size, [600, 520])
        filler.configure(height=100)
        self.assertIsNone(ui.refit_height(top, size))
        self.assertEqual(size, [600, 520])
        self.assertIsNone(ui.refit_height(object(), size), "not a Tk window")

    def test_wrapped_lines_follow_the_wrap_width(self):
        text = ui.SETUP_SAVED_NOTES[True]
        wide = ui.wrapped_lines(self.root, text, 10, 100000)
        narrow = ui.wrapped_lines(self.root, text, 10, ui.SETUP_NOTE_WRAP)
        self.assertEqual(wide, 1)
        self.assertGreater(narrow, 1)
        self.assertGreater(ui.wrapped_lines(self.root, text, 10, 200), narrow)
        self.assertEqual(ui.wrapped_lines(self.root, "", 10, 10), 1)


class LiveSetupNoteTests(SetupNoteTests):
    live = True

    def test_the_wording_matches_what_the_ui_offers(self):
        _win, note, _reserved, _fitted = self.saved_note()
        text = note.cget("text")
        self.assertNotIn("restart live mode", text)
        self.assertNotIn("live mode", text, "the live window has no simulator/live switch")
        self.assertIn("Album artwork and LED style apply now", text)
        self.assertIn("quit Desk Dial from the tray and open it again", text)


OFFSCREEN = "+-4000+100"


def hide(window):
    """Alpha 0, off-screen, no taskbar button: mapped for measuring, never seen."""
    for option, value in (("-alpha", 0.0), ("-toolwindow", True)):
        try:
            window.attributes(option, value)
        except tk.TclError:
            pass
    window.wm_geometry(OFFSCREEN)


class InvisibleToplevel(tk.Toplevel):
    """The Setup Toplevel, hidden before its first map. Not transient for the
    withdrawn test root (Tk never maps a transient of an unmapped master), so
    the test can map it without showing the main window."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hide(self)

    def transient(self, master=None):
        return None

    wm_transient = transient


def widgets_with_text(widget, texts, found=None):
    found = {} if found is None else found
    for child in widget.winfo_children():
        try:
            text = child.cget("text")
        except tk.TclError:
            text = None
        if text in texts:
            found[text] = child
        widgets_with_text(child, texts, found)
    return found


class WindowFitTests(AppHarness):
    """Real layout at the default sizes (Archivo metrics): nothing is squeezed out."""
    def assert_fully_visible(self, widget, window):
        window.update()
        self.assertTrue(widget.winfo_ismapped(), widget)
        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight(), f"{widget} is squeezed")
        bottom = widget.winfo_rooty() - window.winfo_rooty() + widget.winfo_height()
        self.assertLessEqual(bottom, window.winfo_height(), f"{widget} is cut off")

    def open_setup(self):
        with patch.object(ui.tk, "Toplevel", InvisibleToplevel):
            self.app.setup()
        win = self.app.setup_window
        win.update()
        return win

    def test_setup_shows_save_and_authorize_at_its_default_size(self):
        win = self.open_setup()
        self.assertTrue(win.winfo_ismapped())
        self.assertEqual(win.winfo_width(), ui.SETUP_SIZE[0])
        self.assertGreaterEqual(win.winfo_height(), ui.SETUP_SIZE[1])
        self.assertGreaterEqual(win.winfo_height(), min(win.winfo_reqheight(),
                                                        win.winfo_screenheight() - ui.SCREEN_MARGIN))
        # r3.1: one page at a time (the page list under the strip); each page fits with Save.
        pages = {"General": {"Auto-hide", "Pinned", "Off"}, "Music": {"On", "Authorize Apple Music"},
                 "Windows": {"Frosted", "No background"}, "Knob": {"Warm only", "Colour"}}
        tabs = widgets_with_text(win, set(pages) | {"Home Assistant"})
        self.assertEqual(len(tabs), 5)
        for page, texts in pages.items():
            with self.subTest(page=page):
                tabs[page].invoke()
                win.update()
                found = widgets_with_text(win, texts | {"Save settings"})
                self.assertEqual(len(found), len(texts) + 1)
                for widget in found.values():
                    self.assert_fully_visible(widget, win)

    def test_a_short_setup_window_never_hides_the_actions(self):
        win = self.open_setup()
        win.geometry("600x420")
        win.update()
        self.assertEqual(win.winfo_height(), 420)
        widgets_with_text(win, {"Music"})["Music"].invoke()
        win.update()
        for widget in widgets_with_text(win, {"Save settings", "Authorize Apple Music"}).values():
            self.assert_fully_visible(widget, win)

    def test_simulator_window_fits_the_footer_and_notice(self):
        hide(self.root)
        self.root.deiconify()
        self.root.update()
        self.assertEqual(self.root.winfo_width(), ui.WINDOW_SIZE[0])
        self.assertGreaterEqual(self.root.winfo_height(), ui.WINDOW_SIZE[1])
        self.app.controller.notice = "Knob disconnected: check the USB cable"
        self.app.render(force=True)
        for widget in (self.app.connect_button, self.app.device_label, self.app.notice_label,
                       self.app.listbox, self.app.turns, self.app.hint):
            self.assert_fully_visible(widget, self.root)

    def test_fit_height_grows_to_content_and_never_shrinks(self):
        self.assertIsNone(ui.fit_height(object(), 600, 850), "not a Tk window")
        top = tk.Toplevel(self.root)
        top.withdraw()
        self.addCleanup(top.destroy)
        filler = tk.Frame(top, height=300, width=100)
        filler.pack()
        self.assertIsNone(ui.fit_height(top, 600, 850), "fits: unchanged")
        filler.configure(height=990)
        cap = top.winfo_screenheight() - ui.SCREEN_MARGIN
        self.assertEqual(ui.fit_height(top, 600, 850), min(990, cap))
        filler.configure(height=100000)
        self.assertEqual(ui.fit_height(top, 600, 850), cap, "capped to the screen")


class LiveWindowFitTests(AppHarness):
    live = True

    def test_live_window_keeps_its_default_size_and_shows_the_footer(self):
        hide(self.root)
        self.root.deiconify()
        self.root.update()
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), ui.WINDOW_SIZE)
        for widget in (self.app.connect_button, self.app.device_label, self.app.notice_label):
            self.assert_fully_visible(widget, self.root)

    assert_fully_visible = WindowFitTests.assert_fully_visible


class MirrorTests(AppHarness):
    def setUp(self):
        super().setUp()
        self.calls = []
        real = ui.render_lcd

        def counting(frame, artwork=None, window_icon=None):
            self.calls.append((frame, artwork, window_icon))
            return real(frame, artwork, window_icon)
        patcher = patch.object(ui, "render_lcd", counting)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pump(lambda: self.app.controller.state.get("online"))

    def test_mirror_items_and_accessibility_tags(self):
        canvas = self.app.canvas
        self.assertEqual(len(canvas.find_withtag("ring-led")), RING_SEGMENTS)
        self.pump()
        labels = [b["label"] for b in self.app.runtime.frame()["buttons"]]
        for slot, label in enumerate(labels):
            tags = canvas.gettags(self.app.button_items[slot])
            self.assertIn(f"button{slot}", tags)
            self.assertIn(f"action-label:{label}", tags)
            self.assertIn(self.app.button_items[slot], canvas.find_withtag(f"button{slot}"))

    def test_mirror_renders_several_frames_and_caches_the_lcd(self):
        self.pump()
        self.calls.clear()
        self.pump()
        self.pump()
        self.assertEqual(self.calls, [], "an unchanged frame is never re-rendered")
        self.app.controller.button(1)           # Browse: Recent
        self.pump(lambda: self.app.controller.screen.pages)
        self.assertEqual(self.app.controller.screen.mode, "recent")
        rendered = len(self.calls)
        self.assertGreater(rendered, 0)
        self.app.controller.turn(1)
        self.pump()
        self.assertEqual(len(self.calls), rendered + 1)
        self.app.controller.turn(-1)            # back to a cached LCD image
        self.pump()
        self.assertEqual(len(self.calls), rendered + 1)
        self.app.controller.button(0)           # Back to Home
        self.pump()
        self.app.controller.button(2)           # Windows
        self.pump()
        self.assertEqual(self.app.controller.screen.mode, "windows")
        self.assertEqual(self.app.mirror_failures, 0)
        self.assertTrue(all(frame is not None for frame, _, _ in self.calls))

    def test_art_is_passed_only_for_the_frames_art_key(self):
        runtime = self.app.runtime
        preview = Image.new("RGB", (240, 240), (90, 30, 30))
        runtime.artwork_result = ArtworkResult(runtime._art_identity(), "abc123", preview, b"", None)
        self.pump()
        frame, art, _ = self.calls[-1]
        self.assertEqual(frame["artKey"], "abc123")
        self.assertIs(art, preview)
        # A frame naming another cover never gets this one.
        self.app._draw_lcd({**frame, "artKey": "someOtherKey"}, True)
        self.assertEqual(self.calls[-1][0]["artKey"], "someOtherKey")
        self.assertIsNone(self.calls[-1][1])
        runtime.artwork_enabled = False          # Settings: Album artwork off
        self.pump()
        self.assertEqual(runtime.frame()["artKey"], "")
        self.assertEqual(self.app._lcd_key[1], "", "the art-less LCD is shown (from the cache)")

    def test_windows_layout_shows_the_real_app_icon(self):
        self.app.controller.button(2)
        self.pump()
        self.assertEqual(self.app.runtime.frame()["layout"], "windows")
        item = self.app.controller.presented()
        icon = Image.new("RGBA", (32, 32), (30, 90, 200, 255))
        self.app.runtime.window_icons[item["id"]] = icon
        self.pump()
        self.assertIs(self.calls[-1][2], icon)
        count = len(self.calls)
        replacement = Image.new("RGBA", (32, 32), (200, 90, 30, 255))
        self.app.runtime.window_icons[item["id"]] = replacement
        self.pump()
        self.assertEqual(len(self.calls), count + 1, "a new icon identity re-renders the LCD")
        self.assertIs(self.calls[-1][2], replacement)

    def test_mirror_is_skipped_while_withdrawn(self):
        self.app.smoke = False                  # the smoke test renders while withdrawn
        self.assertEqual(self.root.state(), "withdrawn")
        self.calls.clear()
        with patch.object(self.app.preview_lights, "render") as lights:
            self.app.controller.turn(1)
            self.pump()
        lights.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_poll_continues_after_a_raising_mirror(self):
        self.pump()
        with patch.object(ui, "render_lcd", side_effect=RuntimeError("renderer broke")), \
                patch.object(self.app.root, "after") as after, \
                patch.object(self.app.runtime, "poll", wraps=self.app.runtime.poll) as runtime_poll, \
                self.assertLogs(ui._log.name, "ERROR") as logs:
            self.app.controller.turn(1)
            self.app.poll()
            self.app.poll()
        after.assert_called_with(ui.POLL_MS, self.app.poll)
        self.assertEqual(after.call_count, 2)
        self.assertEqual(runtime_poll.call_count, 2)
        self.assertEqual(self.app.mirror_failures, 2)
        self.assertEqual(len(logs.output), 1, "rate-limited")
        self.assertEqual(set(self.app._ring_fill), {ui.SEGMENT_OFF})
        # Recovery: the next good tick redraws in full.
        self.pump()
        self.assertFalse(self.app._mirror_blank)
        self.assertEqual(self.app.mirror_failures, 2)

    def test_poll_continues_after_a_raising_runtime(self):
        with patch.object(self.app.runtime, "poll", side_effect=RuntimeError("runtime broke")), \
                patch.object(self.app.root, "after") as after, \
                self.assertLogs(ui._log.name, "ERROR"):
            self.app.poll()
        after.assert_called_once_with(ui.POLL_MS, self.app.poll)
        self.assertEqual(self.app.failure_counts.get("runtime"), 1, "counted for the smoke test")


class ClaimTests(AppHarness):
    smoke = False

    def test_preview_lights_reset_when_the_knob_claims(self):
        bridge = self.app.device
        with patch.object(self.app.preview_lights, "reset", wraps=self.app.preview_lights.reset) as reset:
            bridge.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
            self.pump()
            self.assertEqual(reset.call_count, 0, "not claimed until the entry is acknowledged")
            bridge.events.put({"kind": "ready", "id": self.app.controller.control_id})
            self.pump()
            self.assertEqual(reset.call_count, 1)
            self.pump()
            self.assertEqual(reset.call_count, 1)
            bridge.events.put({"kind": "disconnected", "message": "Knob disconnected"})
            self.pump()
            bridge.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
            self.pump()
            bridge.events.put({"kind": "ready", "id": self.app.controller.control_id})
            self.pump()
            self.assertEqual(reset.call_count, 2, "a reconnect claims again")

    def test_claim_is_latched_across_entry_acknowledgements(self):
        """Each entry drops c.ready until the knob acknowledges it; that is not an
        unclaim, so the lights keep their flash, decay and fade (firmware lastSeq)."""
        self.app.smoke = True                    # draw the mirror while withdrawn
        self.pump()                              # hidden -> shown reset happens here
        bridge, lights = self.app.device, self.app.preview_lights

        def acknowledge(c):
            """The knob acknowledges the current entry (as often as the host re-enters)."""
            for _ in range(50):
                bridge.events.put({"kind": "ready", "id": c.control_id})
                self.pump()
                if c.ready:
                    return
            self.fail("the entry was never acknowledged")
        with patch.object(lights, "reset", wraps=lights.reset) as reset:
            bridge.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
            self.pump()
            c = self.app.runtime.controller
            self.assertTrue(c.hardware)
            self.assertFalse(c.ready)
            acknowledge(c)
            self.assertEqual(reset.call_count, 1, "connect + ready claims once")
            self.pump(lambda: c.state.get("online"))
            acknowledge(c)
            # A button press enters a new screen (new control id, ready drops) ...
            entered = c.control_id
            c.button(1)                          # Browse
            self.assertGreater(c.control_id, entered)
            self.assertFalse(c.ready)
            self.pump()
            acknowledge(c)
            self.pump(lambda: c.screen.pages)    # the Recent page arrives (another entry)
            acknowledge(c)
            self.assertEqual(c.screen.mode, "recent")
            self.assertEqual(reset.call_count, 1, "an entry acknowledgement is not a claim")
            # ... and a flash armed with an entry survives the knob's acknowledgement.
            c._feedback("ok")
            c._enter()
            self.assertFalse(c.ready)
            self.pump()
            self.assertEqual(lights.flash, "ok")
            acknowledge(c)
            self.assertEqual(lights.flash, "ok", "the destination flash is not cut short")
            self.assertEqual(lights.last_seq, c.feedback_seq)
            self.assertEqual(reset.call_count, 1)
            # A release ends the claim; only a new connection claims again.
            bridge.events.put({"kind": "released"})
            self.pump()
            self.assertFalse(self.app._claimed)
            bridge.events.put({"kind": "disconnected", "message": "Knob disconnected"})
            self.pump()
            bridge.events.put({"kind": "connected", "capabilities": {"controlCenter": 1}})
            self.pump()
            self.assertEqual(reset.call_count, 1, "not claimed until the entry is acknowledged")
            acknowledge(c)
            self.assertEqual(reset.call_count, 2)


class RecordingOverlay:
    """The KnobOverlay interface (control_center/overlay.py) without a window: records
    what the app hands over. wants_frames is set by the test."""
    def __init__(self):
        self.wants_frames = False
        self.lcd_px = 302
        self.rect = (24, 479, 434, 434)
        self.state = "hidden"
        self.scenes, self.peeks, self.suppressed = [], [], []
        self.touches = 0
        self.closed = False

    def submit(self, scene):
        self.scenes.append(scene)

    def touch(self):
        self.touches += 1

    def peek(self, seconds=2.5):
        self.peeks.append(seconds)

    def set_suppressed(self, reason, on):
        self.suppressed.append((reason, on))

    def metrics(self):
        return {"state": self.state}

    def close(self):
        self.closed = True


class QuietToplevel(InvisibleToplevel):
    """Settings in chrome=False, hidden before its first map; records transient(),
    focus_force() and the Settings placement (a position-only geometry, FLOATING_KNOB.md
    section 9.12) instead of acting, so a test never takes the foreground and the hidden
    window stays off-screen."""
    def __init__(self, *args, **kwargs):
        self.transient_calls, self.forced, self.placements = [], 0, []
        self._quiet_ready = False
        super().__init__(*args, **kwargs)
        self._quiet_ready = True

    def transient(self, master=None):
        self.transient_calls.append(master)

    wm_transient = transient

    def wm_geometry(self, newGeometry=None):
        if self._quiet_ready and isinstance(newGeometry, str) and newGeometry.startswith("+"):
            self.placements.append(newGeometry)
            return ""
        return super().wm_geometry(newGeometry)

    geometry = wm_geometry

    def focus_force(self):
        self.forced += 1


class ChromelessHarness(AppHarness):
    """ControlCenterApp(chrome=False, overlay=...): the installed live app's mode."""
    chrome = False
    live = True

    def make_overlay(self):
        return RecordingOverlay()


class ChromelessBuildTests(ChromelessHarness):
    def test_no_widget_is_built_and_the_root_stays_withdrawn(self):
        self.pump()
        self.pump()
        self.assertFalse(self.app.chrome)
        self.assertIs(self.app.overlay, self.overlay)
        self.assertEqual(self.root.winfo_children(), [], "no header, panels, footer or canvas")
        self.assertEqual(self.root.state(), "withdrawn")
        self.assertEqual(self.root.bind(), (), "no root key bindings")
        for name in ("canvas", "connect_button", "device_label", "notice_label", "env_button", "listbox",
                     "turns", "hint", "lcd_photo"):
            self.assertFalse(hasattr(self.app, name), name)
        self.assertEqual(self.app.failure_counts, {})

    def test_the_gate_follows_wants_frames(self):
        self.pump(lambda: self.app.controller.state.get("online"))   # the frame settles first
        self.pump()
        calls = []
        real = ui.render_overlay_lcd

        def counting(*args, **kwargs):
            calls.append(kwargs)
            return real(*args, **kwargs)
        with patch.object(ui, "render_overlay_lcd", counting):
            self.pump()
            self.pump()
            self.assertEqual(calls, [], "hidden: nothing is rendered")
            self.assertEqual(self.overlay.scenes, [])
            self.overlay.wants_frames = True
            self.pump()
            self.pump()
        self.assertEqual(len(calls), 1, "rendered once, then cached")
        self.assertEqual(calls[0]["pixels"], 302)
        self.assertEqual(len(self.overlay.scenes), 1)
        scene = self.overlay.scenes[0]
        self.assertEqual((scene.lcd.mode, scene.lcd.size), ("RGBA", (302, 302)))
        self.assertEqual(len(scene.ring), RING_SEGMENTS)
        self.assertEqual(self.app.mirror_failures, 0)

    def test_touches_reach_the_overlay_and_peek_is_the_overlays(self):
        self.pump(lambda: self.app.controller.state.get("online"))
        self.app.runtime.note_touch("turn")
        self.pump()
        self.pump()
        self.assertEqual(self.overlay.touches, 1)
        self.assertGreaterEqual(len(self.overlay.scenes), 1, "the scene goes with the touch")
        self.app.peek(2.5)
        self.assertEqual(self.overlay.peeks, [2.5])

    def test_the_overlay_is_suppressed_while_disconnected(self):
        self.pump()
        self.assertIn(("disconnected", True), self.overlay.suppressed)

    def test_close_closes_the_overlay(self):
        self.app.close()
        self.assertTrue(self.overlay.closed)


class ChromelessSettingsTests(ChromelessHarness):
    def open_settings(self):
        with patch.object(ui.tk, "Toplevel", QuietToplevel):
            self.app.setup()
        win = self.app.setup_window
        win.update()
        return win

    def test_settings_opens_with_the_root_withdrawn(self):
        win = self.open_settings()
        self.assertEqual(self.root.state(), "withdrawn")
        self.assertTrue(win.winfo_ismapped(), "not a transient of the withdrawn root")
        self.assertEqual(win.transient_calls, [])
        self.assertEqual(win.forced, 1)
        found = widgets_with_text(win, {"Save settings", "Authorize Apple Music", "Connect knob", "Quit Desk Dial"})
        self.assertEqual(set(found), {"Save settings", "Authorize Apple Music"}, "the same Setup content")
        with patch.object(ui.tk, "Toplevel", QuietToplevel):
            self.app.setup()                     # tray Settings… again
        self.assertIs(self.app.setup_window, win)
        self.assertEqual(win.forced, 2)

    def test_settings_are_placed_clear_of_the_floating_knob(self):
        # FLOATING_KNOB.md section 9.12: placed once, while withdrawn, clear of overlay.rect.
        with patch.object(ui, "primary_work_area", lambda window=None: (0, 0, 1600, 1000)):
            win = self.open_settings()
        self.assertEqual(len(win.placements), 1)
        x, y = (int(part) for part in win.placements[0].lstrip("+").split("+"))
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(x + ui.SETUP_SIZE[0], 1600)
        self.assertGreaterEqual(y, 0)
        self.assertFalse(ui.rects_overlap((x, y, ui.SETUP_SIZE[0], self.app.setup_size[1]), self.overlay.rect))
        with patch.object(ui.tk, "Toplevel", QuietToplevel):
            self.app.setup()                     # brought forward again: never moved
        self.assertEqual(len(win.placements), 1)

    def test_the_saved_note_names_the_tray_and_the_floating_knob(self):
        self.assertIn("floating knob", ui.SETUP_SAVED_NOTES[True])
        self.assertIn("from the tray", ui.SETUP_SAVED_NOTES[True])
        self.assertNotIn("window", ui.SETUP_SAVED_NOTES[True])

    def test_tray_failure_settings_offer_connect_and_quit(self):
        connected = [False]
        actions = {"connect": Mock(), "quit": Mock(),
                   "label": lambda: "Disconnect knob" if connected[0] else "Connect knob"}
        self.app.setup_actions = actions
        win = self.open_settings()
        found = widgets_with_text(win, {"Connect knob", "Quit Desk Dial", "Save settings"})
        self.assertEqual(set(found), {"Connect knob", "Quit Desk Dial", "Save settings"})
        found["Connect knob"].invoke()
        actions["connect"].assert_called_once_with()
        connected[0] = True
        self.pump()
        self.assertEqual(self.app.setup_connect_button.cget("text"), "Disconnect knob")
        # No tray balloons either: controller.notice shows in Settings until dismissed.
        notice = self.app.setup_notice_label
        self.assertIs(notice.winfo_toplevel(), win)
        self.assertEqual(notice.cget("text"), "")
        self.app.controller.notice = "Skip failed"
        self.pump()
        self.assertEqual(notice.cget("text"), "Skip failed  ·  Click to dismiss")
        self.app.clear_notice()
        self.pump()
        self.assertEqual(notice.cget("text"), "")
        found["Quit Desk Dial"].invoke()
        actions["quit"].assert_called_once_with()


class ChromelessAppIconTests(ChromelessHarness):
    """APP_ICON.md item 3 on a real mapped window (hidden: alpha 0, off-screen). After
    ui.apply_app_icon on the root, Settings' frame and the TkTopLevel class carry the .ico's own
    frames for the window's DPI (the hand-tuned small drawing at 16-24 px), never Tk's 16 px
    frame stretched to 32 px (Tk 8.6 cannot read the PNG-compressed frames)."""

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_settings_carries_the_designers_frames(self):
        applied = ui.apply_app_icon(self.root)
        self.assertEqual(applied, {"iconphoto": True, "windowIcons": True})
        with patch.object(ui.tk, "Toplevel", QuietToplevel):
            self.app.setup()
        win = self.app.setup_window
        win.update()
        frame = int(win.wm_frame(), 16)
        self.assertNotEqual(frame, win.winfo_id(), "mapped: the frame is Tk's wrapper")
        reader = w.IconApi()
        big_size, small_size = ui.AppIconApi().icon_sizes(frame)
        checks = {"ICON_BIG": (reader.window_icon(frame, ui.ICON_BIG), big_size),
                  "ICON_SMALL": (reader.window_icon(frame, ui.ICON_SMALL), small_size),
                  "GCLP_HICON": (reader.class_icon(frame, ui.GCLP_HICON), big_size),
                  "GCLP_HICONSM": (reader.class_icon(frame, ui.GCLP_HICONSM), small_size)}
        for name, (handle, size) in checks.items():
            with self.subTest(icon=name):
                self.assertTrue(handle)
                image = reader.icon_image(handle)
                self.assertEqual(image.size, (size, size))
                png = ui.APP_ICON_DIR / "png" / f"nano-d-app-{size}.png"
                if png.is_file():     # 16-64 px; at other DPIs Windows picks the nearest frame
                    with Image.open(png) as source:
                        self.assertEqual(image.tobytes(), source.convert("RGBA").tobytes())
        self.assertEqual(self.root._nanod_window_icons.failures, 0)


# Desktop v6 (CAROUSEL.md section 1): PickerIconTests covered the Tk grid overlay, now
# replaced by the carousel presenter. Its invariant (no icon work in the WM_HOTKEY/focus
# path; icons only after focus) is ported to test_carousel_adapter.py (the adapter and the
# UI tick) and to the carousel's presenter tests (set_icons only posts to its mailbox).


# =========================================================================== desktop v7 (WP10)
# Headless (no Tk): a stand-in root drives ControlCenterApp(chrome=False) through _poll_once, as in
# test_cc_runtime_overlay; the runtime's lanes run inline. K4 2.4, 5.3, 11, 17.1; K2 10.3; K3 3.1, 16.
from types import SimpleNamespace                              # noqa: E402
from control_center import runtime as runtime_module           # noqa: E402
from control_center.controller import MODES                    # noqa: E402


class InlineExecutor:
    def __init__(self, *args, **kwargs):
        pass

    def submit(self, function, *args):
        from concurrent.futures import Future
        future = Future()
        try:
            future.set_result(function(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class StandInRoot:
    def __init__(self):
        self.timers, self._next = {}, 0

    def title(self, *args): pass
    def configure(self, **kwargs): pass
    def protocol(self, *args): pass
    def state(self): return "withdrawn"

    def after(self, ms, callback):
        self._next += 1
        self.timers[self._next] = (ms, callback)
        return self._next

    def after_cancel(self, ident): self.timers.pop(ident, None)
    def destroy(self): pass


class AliveOverlay:
    """The v7 KnobOverlay interface, recording every call; no window."""

    def __init__(self):
        self.calls = []
        self.frames, self.latched, self.scenes, self.suppressed = [], [], [], []
        self.alive_values = []
        self.wants_frames = False
        self.lcd_px, self.rect, self.state, self.hwnd = 302, (24, 479, 434, 434), "hidden", 0x5151
        self._alive = False

    def set_alive(self, on):
        if on != self._alive:
            self.alive_values.append(on)
        self._alive = on
        return True

    def post_frame(self, frame, *, claimed, local_max=None, t=None):
        self.frames.append((frame, claimed, local_max))
        return True

    def set_latched(self, *, t=None, **values):
        self.latched.append(values)
        return True

    def post_input(self, kind, value, control_id=None, t=None):
        self.calls.append(("input", kind, value, control_id))
        return True

    def submit(self, scene): self.scenes.append(scene)
    def touch(self): self.calls.append("touch")
    def peek(self, seconds=2.5): self.calls.append("peek")
    def set_suppressed(self, reason, on): self.suppressed.append((reason, on))
    def metrics(self): return {"state": self.state}
    def close(self): self.calls.append("close")


class RecordingStage:
    def __init__(self):
        self.positions, self.touches, self.exclusions, self.closed = [], 0, [], 0

    def position(self, control_id, p, t_read=None): self.positions.append((control_id, p, t_read))
    def note_touch(self): self.touches += 1
    def set_capture_exclusions(self, hwnds): self.exclusions.append(tuple(hwnds))
    def take_events(self): return []
    def close(self): self.closed += 1


class RecordingPicker:
    """The WindowsAdapter's knob-touch warm-up (CAROUSEL.md 12.4), counted."""

    def __init__(self):
        self.touches = 0

    def note_touch(self):
        self.touches += 1
        return True


class WarmableWindows(SimulatedWindows):
    """The simulator's picker plus the live adapter's ``note_touch`` (the GPU chrome's warm-up)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.touches = 0

    def note_touch(self):
        self.touches += 1
        return True


class ShellCase(unittest.TestCase):
    """ControlCenterApp(chrome=False) on a stand-in root with the simulated alive knob selected."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for patcher in (patch.object(ui, "DATA_DIR", Path(temp.name)),
                        patch.object(ui, "BACKUP_DIR", Path(temp.name) / "backups"),
                        patch.object(ui, "ensure_ui_font", lambda root: ui.FALLBACK_FAMILY),
                        patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.overlay = AliveOverlay()
        self.stage = RecordingStage()
        self.app = ui.ControlCenterApp(StandInRoot(), smoke=True, live=False, chrome=False, overlay=self.overlay,
                                       stage=self.stage)
        self.addCleanup(lambda: self.app.runtime.shutdown(close_device=False))

    def tick(self, count=1):
        for _ in range(count):
            self.app._poll_once()

    def connect(self):
        self.assertTrue(self.app.set_sim_connection("connected"))
        self.tick(4)
        self.assertTrue(self.app.runtime.alive, "the simulated knob reports alive")


class AliveShellTests(ShellCase):
    def test_the_engine_gets_the_knobs_frame_claim_bound_and_latched_values(self):
        self.connect()
        self.assertEqual(self.overlay.alive_values, [True])
        frame, claimed, local_max = self.overlay.frames[-1]
        self.assertIs(frame, self.app.runtime.last_frame, "the frame the knob was sent, with its id")
        self.assertEqual(frame["id"], self.app.controller.control_id)
        self.assertTrue(claimed)
        self.assertEqual(local_max, self.app.controller.bounds()[1])
        latched = {}
        for values in self.overlay.latched:
            latched.update(values)
        self.assertEqual(set(latched), {"clock", "reduced_motion", "tuning"} | ({"progress"} & set(latched)))
        self.assertTrue(0 <= latched["clock"] < 1440)
        self.assertIs(latched["reduced_motion"], False)
        posted = len(self.overlay.frames)
        self.tick(3)
        self.assertEqual(len(self.overlay.frames), posted, "an unchanged frame is not posted again")
        self.app.controller.button(1, self.app.controller.control_id)   # Browse: a new control and frame
        self.tick(4)
        self.assertEqual(self.app.controller.screen.mode, "recent")
        self.assertGreater(len(self.overlay.frames), posted)
        self.assertEqual(self.overlay.frames[-1][0]["id"], self.app.controller.control_id)
        self.assertEqual(self.overlay.scenes, [], "no LCD while the knob does not want frames")
        self.overlay.wants_frames = True
        self.tick()
        self.assertEqual(len(self.overlay.scenes), 1, "the LCD scene; the ring is the engine's")
        self.assertTrue(all(colour[3] == 0.0 for colour in self.overlay.scenes[0].ring))

    def test_a_knob_without_alive_keeps_the_preview_lights_scenes(self):
        self.connect()
        self.app.sim_device.alive = False                  # a cc5.3 knob
        self.overlay.wants_frames = True
        self.tick(2)
        self.assertEqual(self.overlay.alive_values, [True, False])
        self.assertTrue(any(colour[3] > 0 for colour in self.overlay.scenes[-1].ring), "PreviewLights ring")

    def test_disconnect_turns_the_engine_off(self):
        self.connect()
        self.app.sim_controls.connected = False
        self.tick(3)
        self.assertEqual(self.overlay.alive_values, [True, False])
        self.assertIn(("disconnected", True), self.overlay.suppressed)

    def test_explorer_and_upnext_suppress_the_knob_from_the_open_to_closed(self):
        self.connect()
        self.assertNotIn("explorer", [reason for reason, _on in self.overlay.suppressed], "quiet until held")
        self.app.runtime.open_surfaces.add("explorer")      # a scene still animating out after its close
        self.tick()
        self.assertEqual(self.overlay.suppressed[-1], ("explorer", True))
        self.app.runtime.open_surfaces.discard("explorer")
        self.tick()
        self.assertEqual(self.overlay.suppressed[-1], ("explorer", False))
        self.app.controller.screen.mode = "upnext"
        self.app._update_suppression(True)
        self.assertEqual(self.overlay.suppressed[-1], ("upnext", True))

    def test_the_stage_gets_the_knobs_window_as_a_capture_exclusion(self):
        self.tick(2)
        self.assertEqual(self.stage.exclusions, [(0x5151,)])

    def test_windows_button_is_button_order_3(self):
        self.app.config["button_order"] = [3, 1, 0, 2]
        runtime = self.app._make_runtime(False)
        self.addCleanup(lambda: runtime.shutdown(close_device=False))
        self.assertEqual(runtime.controller.windows_button, 2)

    def test_the_picker_reads_the_overlay_registry(self):
        providers = []

        class RegistryWindows(SimulatedWindows):
            def set_overlay_registry(self, provider):
                providers.append(provider)
        with patch.object(ui.ControlCenterApp, "providers",
                          lambda app, live: (SimulatedSonos(), SimulatedAppleMusic(), RegistryWindows())):
            runtime = self.app._make_runtime(False)
        self.addCleanup(lambda: runtime.shutdown(close_device=False))
        runtime.open_surfaces.add("upnext")
        self.assertEqual(providers[-1](), {"upnext"})

    def test_the_fast_path_warms_the_current_runtimes_picker(self):
        """CAROUSEL.md 12.4: the fast path gets the runtime's picker when it can warm (the live
        WindowsAdapter's note_touch), follows a runtime swap on the next tick, and a knob touch reaches
        it together with the stage, never more often."""
        fast = self.app.fast_path
        self.assertIsNone(fast.windows, "the simulator's picker has no GPU chrome to warm")
        with patch.object(ui.ControlCenterApp, "providers",
                          lambda app, live: (SimulatedSonos(), SimulatedAppleMusic(), WarmableWindows())):
            self.assertTrue(self.app.set_sim_connection("connected"))      # a new runtime
        self.tick()
        picker = self.app.runtime.windows
        self.assertIsInstance(picker, WarmableWindows)
        self.assertIs(fast.windows, picker)
        for step in range(40):                                        # 20 s of turns at 2 per second
            fast.handle("position", {"id": 1, "p": step, "delta": 1}, 100.0 + step * 0.5)
        self.assertEqual(picker.touches, self.stage.touches)
        self.assertEqual(picker.touches, 2)
        self.assertTrue(self.app.set_sim_connection("usb"))           # back to the plain simulator picker
        self.tick()
        self.assertIsNone(fast.windows)

    def test_a_new_app_hands_its_picker_to_the_fast_path_before_the_first_tick(self):
        with patch.object(ui.ControlCenterApp, "providers",
                          lambda app, live: (SimulatedSonos(), SimulatedAppleMusic(), WarmableWindows())), \
                patch.object(ui.ControlCenterApp, "poll", lambda app: None):
            app = ui.ControlCenterApp(StandInRoot(), smoke=True, live=False, chrome=False,
                                      overlay=AliveOverlay(), stage=RecordingStage())
        self.addCleanup(lambda: app.runtime.shutdown(close_device=False))
        self.assertIs(app.fast_path.windows, app.runtime.windows)

    def test_the_simulator_uses_the_state_pickers_fakes(self):
        runtime = self.app.runtime
        self.assertIsInstance(runtime.stage, ui.FakeStagePresenter)
        self.assertIsInstance(runtime.toasts, ui.SimulatedToasts)
        self.assertIs(runtime.stage.controls, self.app.sim_controls)
        self.assertGreater(runtime.sonos.P, 0, "an album is loaded in the queue (load_album)")
        self.assertTrue(self.app.set_sim_state("stage", "refused"))
        self.assertEqual(self.app.sim_controls.stage, "refused")
        self.assertFalse(self.app.set_sim_state("no_such_control", 1))
        self.connect()
        self.assertTrue(self.app.set_sim_connection("usb"))
        self.assertIsNone(self.app.runtime.device, "back to the (smoke-mode) bridge")

    def test_close_closes_the_stage(self):
        self.app.close()
        self.assertEqual(self.stage.closed, 1)


class FastPathTests(unittest.TestCase):
    """K4 5.3: the reader thread's position, limit and button events reach the floating knob's engine
    and (while a scene is up) the stage, stamped at the read, before the Tk tick."""

    def make(self):
        self.overlay, self.stage = AliveOverlay(), RecordingStage()
        fast = ui.FastPath(overlay=self.overlay, stage=self.stage, clock=lambda: 5.0)
        fast.button_order = [3, 1, 0, 2]
        return fast

    def test_inputs_are_posted_with_their_stamps(self):
        fast = self.make()
        fast.handle("position", {"id": 9, "p": 12, "position": 12, "delta": 1}, 1.25)
        fast.handle("limit", {"id": 9, "dir": -1}, 1.30)
        fast.handle("button", {"id": 9, "button": 0, "index": 0, "hid": False}, 1.35)
        self.assertEqual(self.overlay.calls, [("input", "position", (12, 1), 9), ("input", "limit", -1, 9),
                                              ("input", "press", 2, 9)], "raw 0 is the physical slot 2")
        self.assertEqual(self.stage.positions, [], "no scene is open")
        fast.stage_open = True
        fast.handle("position", {"id": 9, "p": 13, "delta": 1}, 1.40)
        self.assertEqual(self.stage.positions, [(9, 13, 1.40)])
        self.assertEqual(self.stage.touches, 1, "the device warm-up at most every 10 s")
        fast.handle("position", {"id": 9, "p": 14, "delta": 1}, 11.5)
        self.assertEqual(self.stage.touches, 2)
        self.assertFalse(fast.handle("ready", {"id": 9}, 12.0))

    def test_a_failure_never_reaches_the_reader_thread(self):
        fast = self.make()
        self.overlay.post_input = Mock(side_effect=RuntimeError("overlay gone"))
        self.assertFalse(fast.handle("limit", {"id": 1, "dir": 1}, 1.0))
        self.assertEqual(fast.failures, 1)

    def test_a_touch_warms_the_picker_with_the_stage_never_more_often(self):
        """CAROUSEL.md 12.4 (lead decision 2026-09-26): the picker's GPU chrome is warmed wherever the
        stage is, by the same limiter (at most once per FAST_TOUCH_SECONDS), so the adapter's
        note_touch never runs more often than the stage's."""
        fast = self.make()
        picker = RecordingPicker()
        fast.windows = picker
        t = 0.0
        while t < 61.0:
            kind, values = [("position", {"id": 9, "p": int(t), "delta": 1}), ("limit", {"id": 9, "dir": 1}),
                            ("button", {"id": 9, "button": 1})][int(t * 4) % 3]
            self.assertTrue(fast.handle(kind, values, t))
            self.assertLessEqual(picker.touches, self.stage.touches)
            t += 0.25
        self.assertEqual((self.stage.touches, picker.touches), (7, 7), "t = 0, 10, ..., 60")
        self.assertFalse(fast.handle("ready", {"id": 9}, 80.0))       # not input: no warm-up
        self.assertEqual(picker.touches, 7)
        fast.stage = None                                             # the picker alone: the same limiter
        fast.handle("limit", {"id": 9, "dir": 1}, 81.0)
        fast.handle("limit", {"id": 9, "dir": 1}, 85.0)
        self.assertEqual(picker.touches, 8)

    def test_a_failing_warm_up_never_stops_the_other_or_the_input(self):
        fast = self.make()
        picker = RecordingPicker()
        fast.windows = picker
        self.stage.note_touch = Mock(side_effect=RuntimeError("stage gone"))
        self.assertTrue(fast.handle("limit", {"id": 1, "dir": 1}, 1.0), "the input was posted")
        self.assertEqual((picker.touches, fast.failures), (1, 1))
        picker.note_touch = Mock(side_effect=OSError("picker gone"))
        del self.stage.note_touch
        self.assertTrue(fast.handle("limit", {"id": 1, "dir": 1}, 20.0))
        self.assertEqual((self.stage.touches, fast.failures), (1, 2))

    def test_the_bridges_emit_is_wrapped_once_and_still_queues(self):
        bridge = FakeBridge()
        fast = self.make()
        self.assertTrue(ui.install_fast_path(bridge, fast))
        self.assertFalse(ui.install_fast_path(bridge, fast), "idempotent")
        bridge._emit("position", id=4, p=7, position=7, delta=-1)
        bridge._emit("ready", id=4)
        self.assertEqual(self.overlay.calls, [("input", "position", (7, -1), 4)])
        self.assertEqual([bridge.events.get_nowait()["kind"] for _ in range(2)], ["position", "ready"])


class ShellSmallTests(unittest.TestCase):
    def test_escape_never_toggles_play_on_home(self):
        pressed = []
        app = SimpleNamespace(controller=SimpleNamespace(screen=SimpleNamespace(mode="home"), button=pressed.append))
        ui.ControlCenterApp.escape(app)
        self.assertEqual(pressed, [], "Esc on Home is not Play / Pause")
        app.controller.screen.mode = "recent"
        ui.ControlCenterApp.escape(app)
        self.assertEqual(pressed, [0])

    def test_every_mode_has_a_description(self):
        self.assertEqual(set(ui.MODE_DESCRIPTIONS), set(MODES))

    def test_the_state_picker_covers_every_sim_control(self):
        from control_center.simulation import SimControls
        names = {name for name, _label, _options in ui.SIM_PICKER}
        self.assertEqual(names, set(vars(SimControls())))
        for name, _label, options in ui.SIM_PICKER:
            self.assertIn(getattr(SimControls(), name), [value for value, _text in options], name)


if __name__ == "__main__":
    unittest.main()

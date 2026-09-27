"""ALIVE.md sections 2, 3 and 10.2 in the desktop v7 Settings (ui.py), without Tk.

* settings.json ``led_drive`` / ``led_dither`` (no UI): ``load_config`` keeps them only when
  present, Settings > Save writes them back unchanged, and ``_apply_presentation`` (runtime
  build and every Save) hands them to ``Runtime.apply_led_tuning`` -> ``DeviceBridge.
  set_led_tuning``, so a knob with ``alive`` gets ``ledDrive`` / ``ledDither`` in its enter
  frames;
* the Settings LED labels are "Colour" and "Warm only" [D16]; the stored values stay
  "color" and "white".

The Settings window runs its real callbacks on stand-in widgets (as test_cc_controller's
SetupConfigurationTests); no Tk, no port, no network, every path in a temporary DATA_DIR.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center import runtime as runtime_module  # noqa: E402
from control_center import ui  # noqa: E402
from control_center.controller import Controller  # noqa: E402
from control_center.device import DeviceBridge  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows  # noqa: E402
from test_alive_host import PROFILE_NAMES  # noqa: E402
from test_alive_wire import AL4, WireSerial  # noqa: E402
from test_cc_controller import FakeDevice, FakeVariable, FakeWidget, ManualExecutor  # noqa: E402
from test_cc_device import Clock as BridgeClock  # noqa: E402


class RecordingRuntime:
    """What _apply_presentation touches on a Runtime, recording the LED tuning it gets."""

    def __init__(self):
        self.windows = None
        self.tunings = []

    def apply_led_tuning(self, settings):
        self.tunings.append({key: settings[key] for key in ui.LED_TUNING_KEYS if key in settings})


class SettingsCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        patcher = patch.object(ui, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_settings(self, value):
        (self.data_dir / "settings.json").write_text(json.dumps(value), encoding="utf-8")

    def saved(self):
        return json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))


class LoadConfigTests(SettingsCase):
    def test_the_tuning_keys_are_kept_only_when_present(self):
        self.write_settings({"port": "COM9", "led_drive": 120, "led_dither": False})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["port"], config["led_drive"], config["led_dither"]), ("COM9", 120, False))
        self.write_settings({"port": "COM9"})
        config = ui.ControlCenterApp.load_config()
        self.assertNotIn("led_drive", config, "absent: never written back as null")
        self.assertNotIn("led_dither", config)
        (self.data_dir / "settings.json").unlink()
        self.assertFalse(set(ui.LED_TUNING_KEYS) & set(ui.ControlCenterApp.load_config()))

    def test_values_pass_through_raw_and_are_validated_where_applied(self):
        # Save writes back what the user put there; runtime.led_tuning drops an invalid one
        # (logged by key name only), so the knob keeps its default.
        self.write_settings({"led_drive": 900, "led_dither": "yes"})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["led_drive"], config["led_dither"]), (900, "yes"))
        with self.assertLogs("control_center.runtime", level="WARNING") as logs:
            self.assertEqual(runtime_module.led_tuning(config), (None, None))
        self.assertNotIn("900", "\n".join(logs.output))
        self.assertNotIn("yes", "\n".join(logs.output))

    def test_apply_presentation_hands_them_to_the_runtime(self):
        self.write_settings({"led_drive": 90, "led_dither": True, "led_style": "white"})
        app = object.__new__(ui.ControlCenterApp)
        app.config = ui.ControlCenterApp.load_config()
        runtime = RecordingRuntime()
        ui.ControlCenterApp._apply_presentation(app, runtime)
        self.assertEqual(runtime.tunings, [{"led_drive": 90, "led_dither": True}])
        self.assertEqual(runtime.led_style, "white")
        # A runtime without the alive API (an older stand-in) is left alone.
        plain = SimpleNamespace(windows=None)
        ui.ControlCenterApp._apply_presentation(app, plain)
        self.assertEqual(plain.led_style, "white")

    def test_a_real_runtime_reaches_the_bridge(self):
        self.write_settings({"led_drive": 120, "led_dither": False})
        app = object.__new__(ui.ControlCenterApp)
        app.config = ui.ControlCenterApp.load_config()
        tunings = []
        device = FakeDevice()
        device.set_led_tuning = lambda drive=None, dither=None: tunings.append((drive, dither))
        with patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor):
            runtime = Runtime(Controller(), SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), device)
            self.addCleanup(runtime.shutdown)
            ui.ControlCenterApp._apply_presentation(app, runtime)
        self.assertEqual((tunings, runtime.led_tuning), ([(120, False)], (120, False)))


class SettingsWindowTests(SettingsCase):
    """The real Settings callbacks on stand-in widgets (no Tk)."""

    def setUp(self):
        super().setUp()
        self.buttons = {}

        def button(parent, text, command, **kwargs):
            self.buttons[text] = command
            return FakeWidget()
        for target, name, value in (
            (ui, "button", button), (ui, "label", lambda *a, **k: FakeWidget(**k)),
            (ui.tk, "Toplevel", FakeWidget), (ui.tk, "Frame", FakeWidget),
            (ui.tk, "Entry", FakeWidget), (ui.tk, "StringVar", FakeVariable),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write_settings({"speaker_ip": "192.0.2.120", "port": "COM8", "led_style": "color",
                             "led_drive": 120, "led_dither": False})
        self.app = object.__new__(ui.ControlCenterApp)
        self.app.root = FakeWidget()
        self.app.setup_window = None
        self.app.auth = None
        self.app.device = FakeDevice()
        self.app.config = ui.ControlCenterApp.load_config()
        self.runtime = RecordingRuntime()
        self.runtime.device_connected = self.runtime.device_supported = True
        self.runtime.button_order, self.runtime.on_button_probe = [0, 1, 2, 3], None
        self.app.runtime = self.runtime
        self.app.controller = SimpleNamespace(ready=True)

    def test_the_led_labels_are_colour_and_warm_only(self):
        self.assertEqual(ui.LED_STYLE_CHOICES, (("Colour", "color"), ("Warm only", "white")))
        self.app.setup()
        self.assertIn("Colour", self.buttons)
        self.assertIn("Warm only", self.buttons)
        self.assertNotIn("Targeted colour", self.buttons)
        self.assertNotIn("White", self.buttons)
        self.buttons["Warm only"]()
        self.buttons["Save settings"]()
        self.assertEqual((self.saved()["led_style"], self.runtime.led_style), ("white", "white"))
        self.buttons["Colour"]()
        self.buttons["Save settings"]()
        self.assertEqual((self.saved()["led_style"], self.runtime.led_style), ("color", "color"))

    def test_save_keeps_the_tuning_keys_and_applies_them(self):
        self.app.setup()
        self.buttons["Warm only"]()
        self.buttons["Save settings"]()
        saved = self.saved()
        self.assertEqual((saved["led_drive"], saved["led_dither"], saved["led_style"]), (120, False, "white"))
        self.assertEqual(self.runtime.tunings, [{"led_drive": 120, "led_dither": False}])
        # load -> save -> load: unchanged.
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["led_drive"], config["led_dither"]), (120, False))

    def test_save_never_invents_the_tuning_keys(self):
        self.write_settings({"speaker_ip": "192.0.2.120", "port": "COM8"})
        self.app.config = ui.ControlCenterApp.load_config()
        self.app.setup()
        self.buttons["Save settings"]()
        self.assertFalse(set(ui.LED_TUNING_KEYS) & set(self.saved()))
        self.assertEqual(self.runtime.tunings, [{}])


class SettingsToKnobTests(SettingsCase):
    """settings.json -> load_config -> _apply_presentation -> Runtime -> DeviceBridge -> the
    enter line an `alive` knob receives."""

    def test_the_enter_frame_carries_led_drive_and_dither(self):
        self.write_settings({"led_drive": 90, "led_dither": False})
        app = object.__new__(ui.ControlCenterApp)
        app.config = ui.ControlCenterApp.load_config()
        executor = patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        clock = BridgeClock()
        serial = WireSerial(clock, AL4)
        template = next(iter(serial.profiles.values()))     # the profile inventory _enter checks
        serial.profiles = {name: {**template, "name": name} for name in PROFILE_NAMES}
        bridge = DeviceBridge(str(self.data_dir), lambda port: serial, request_timeout=0.1, autostart=False,
                              clock=clock, local_minute=lambda: 600)
        controller = Controller()
        runtime = Runtime(controller, SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), bridge)
        self.addCleanup(runtime.shutdown)
        ui.ControlCenterApp._apply_presentation(app, runtime)

        def pump():
            for _ in range(100):
                if bridge._deferred_command is None and bridge.commands.empty():
                    break
                command, value = bridge._next_command()
                bridge._dispatch(command, value)
                bridge._service()
        bridge.submit("connect", "COM-FAKE")
        pump()
        runtime.poll()
        pump()
        kind, entry = serial.frames()[0]
        self.assertEqual(kind, "control")
        self.assertEqual((entry["ledDrive"], entry["ledDither"]), (90, False))


if __name__ == "__main__":
    unittest.main()

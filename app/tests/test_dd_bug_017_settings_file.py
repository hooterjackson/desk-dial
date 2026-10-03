"""DD-BUG-017: settings.json is read BOM-tolerantly, a corrupt file is set aside (never silently
overwritten with defaults), and every writer goes through one atomic temp-file + os.replace helper.
No Tk, no network."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402


class SettingsFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        patcher = patch.object(ui, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.data_dir / "settings.json"

    def app(self):
        app = object.__new__(ui.ControlCenterApp)
        app.config = ui.ControlCenterApp.load_config()
        app.runtime = SimpleNamespace()
        return app

    def test_bom_file_loads(self):
        self.path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"led_style": "white", "ha_scenes": [],
                                                             "led_pink": 3}).encode("utf-8"))
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["led_style"], config["led_pink"]), ("white", 3))
        self.assertEqual(list(self.data_dir.iterdir()), [self.path], "a good file stays where it is")

    def test_corrupt_file_is_preserved_and_not_overwritten(self):
        torn = b'{"led_style": "white", "led_dri'
        for content in (torn, b"[1, 2]", b"\xff\xfe not utf-8"):
            with self.subTest(content=content):
                for leftover in self.data_dir.iterdir():
                    leftover.unlink()
                self.path.write_bytes(content)
                app = self.app()
                self.assertEqual(app.config["led_style"], ui.DEFAULT_LED_STYLE)
                app._apply_knob_sound(True, 40)                # writes at once
                aside = [p for p in self.data_dir.iterdir() if p.name.startswith("settings.json.bad-")]
                self.assertEqual(len(aside), 1)
                self.assertEqual(aside[0].read_bytes(), content, "the owner's file is kept as it was")
                self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["knob_sound_volume"], 40)

    def test_writes_use_os_replace_and_leave_no_temp_file(self):
        with patch.object(ui.os, "replace", wraps=os.replace) as replace:
            self.app()._apply_knob_sound(True, 30)
        replace.assert_called_once()
        self.assertEqual(replace.call_args[0][1], self.path)
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir()), ["settings.json"])

    def test_a_failed_write_keeps_the_old_file(self):
        self.path.write_text(json.dumps({"led_style": "white"}), encoding="utf-8")
        before = self.path.read_bytes()
        with patch.object(ui.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                ui.write_settings({"led_style": "colour"})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir()), ["settings.json"])

    def test_no_direct_settings_writes_remain(self):
        source = Path(ui.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"settings.json").write_text', source)


if __name__ == "__main__":
    unittest.main()

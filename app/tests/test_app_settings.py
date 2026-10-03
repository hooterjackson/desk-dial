"""Plan section 3c (S1 DD-C): Settings > Apps, the settings keys and their migration, the Rules dialog's checks,
Import, the 24 px icons, the daily profile check's wiring and the bundled profiles folder. Headless: a fake
runtime with lane DD-B's interface over the real profile Library, stand-in Tk widgets (no window), temporary
data folders, no network."""
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from control_center import app_profiles, paths, profile_updates, ui  # noqa: E402
from test_cc_controller import FakeVariable, FakeWidget  # noqa: E402

PROFILES = REPO / "profiles"


class FakeAppRuntime:
    """Lane DD-B's runtime interface (Runtime app_* methods) over a real Library."""

    def __init__(self, library, modes=None):
        self.library = library
        self.modes = dict(modes or {"onshape": "auto"})
        self.calls, self.reloads, self.toggles = [], 0, []

    def app_modes(self):
        return dict(self.modes)

    def set_app_mode(self, pid, mode):
        self.calls.append((pid, mode))
        self.modes[pid] = mode

    def app_rows(self):
        return [{"id": p.id, "name": p.name, "status": p.status, "source": p.source,
                 "mode": self.modes.get(p.id, "off"), "detect_summary": " · ".join(p.detect.exe + p.detect.host),
                 "active": False, "focused": False, "warnings": list(p.warnings), "icon24": p.raw_karl.get("icon24")}
                for p in self.library.profiles()]

    def reload_profiles(self):
        self.reloads += 1
        return self.library.reload()

    def toggle_app(self, pid):
        self.toggles.append(pid)
        return None

    def app_menu(self):
        return [(pid, pid.title(), mode == "manual") for pid, mode in self.modes.items() if mode != "off"]


class DataCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        patcher = patch.object(ui, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user, self.updates = self.root / "profiles" / "user", self.root / "profiles" / "updates"

    def write(self, settings):
        (self.data_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    def saved(self):
        return json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))

    def library(self, rules=None):
        return app_profiles.Library(PROFILES, self.updates, self.user, rules=rules)


# ============================================================================================ settings keys
class MigrationTests(DataCase):
    def test_defaults(self):
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["app_modes"], config["app_rules"], config["app_order"]),
                         ({"onshape": "off"}, {}, []))
        self.assertEqual((config["profile_updates"], config["profile_updates_last"]), ("off", 0),
                         "fetching updated profiles is off by default")

    def test_onshape_mode_migrates_and_stays_in_sync(self):
        self.write({"onshape_mode": "auto"})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["app_modes"], config["onshape_mode"]), ({"onshape": "auto"}, "auto"),
                         "Onshape keeps the owner's mode; every other app is Off until chosen")
        self.write({"onshape_mode": "auto", "app_modes": {"onshape": "manual", "figma": "auto"}})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["app_modes"], config["onshape_mode"]), ({"onshape": "manual", "figma": "auto"},
                                                                         "manual"))

    def test_types_and_values_are_validated(self):
        self.write({"app_modes": {"figma": "on", "Bad Id": "auto", "plasticity": "manual", "x" * 12: "auto"},
                    "app_rules": {"figma": {"exe": ["Figma.exe", "C:\\x\\Figma.exe", "figma.EXE", 3],
                                            "host": ["figma.com", "https://figma.com/file", "*.figma.com",
                                                     "figma.*.com", "figma.com:443", "FIGMA.COM"],
                                            "title": ["x"]},
                                  "blender": {"exe": "blender.exe"}, "Nope!": {"exe": ["a.exe"]}},
                    "app_order": ["figma", "figma", "BAD", 4, "onshape"],
                    "profile_updates": "hourly", "profile_updates_last": "yesterday"})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual(config["app_modes"], {"plasticity": "manual", "onshape": "off"})
        self.assertEqual(config["app_rules"], {"figma": {"exe": ["Figma.exe"], "host": ["figma.com", "*.figma.com"]}},
                         "program names and bare hosts only; a URL, a path or a misplaced wildcard is dropped")
        self.assertEqual(config["app_order"], ["figma", "onshape"])
        self.assertEqual((config["profile_updates"], config["profile_updates_last"]), ("off", 0))
        self.write({"profile_updates": "daily", "profile_updates_last": 1_800_000_000.5, "app_rules": [1],
                    "app_modes": "auto"})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["profile_updates"], config["profile_updates_last"], config["app_rules"]),
                         ("daily", 1_800_000_000.5, {}))
        self.assertEqual(config["app_modes"], {"onshape": "off"})

    def test_rule_lists_are_capped_as_the_validator_takes_them(self):
        self.write({"app_rules": {"figma": {"exe": [f"a{i}.exe" for i in range(40)]}}})
        rules = ui.ControlCenterApp.load_config()["app_rules"]
        self.assertEqual(len(rules["figma"]["exe"]), ui.APP_RULES_MAX)
        self.assertEqual(app_profiles._check_rules_arg(rules), [], "the Library takes every kept rule")

    def test_unknown_ids_are_dropped_only_once_the_library_has_loaded(self):
        self.write({"app_modes": {"figma": "auto", "gone": "manual"}, "app_rules": {"gone": {"exe": ["g.exe"]}},
                    "app_order": ["gone", "figma"]})
        config = ui.ControlCenterApp.load_config()
        self.assertIn("gone", config["app_modes"], "kept until the library says it doesn't exist")
        ui.prune_app_ids(config, [])
        self.assertIn("gone", config["app_modes"], "an empty library (it failed) drops nothing")
        ui.prune_app_ids(config, [p.id for p in self.library().profiles()])
        self.assertEqual((config["app_modes"], config["app_rules"], config["app_order"]),
                         ({"figma": "auto", "onshape": "off"}, {}, ["figma"]))

    def test_the_app_library_prunes_when_it_loads(self):
        self.write({"app_modes": {"figma": "auto", "gone": "manual"}})
        app = object.__new__(ui.ControlCenterApp)
        app.config = ui.ControlCenterApp.load_config()
        with patch.object(paths, "bundled_profiles_dir", lambda frozen=None: PROFILES), \
                patch.object(paths, "profiles_updates_dir", lambda frozen=None: self.updates), \
                patch.object(paths, "profiles_user_dir", lambda frozen=None: self.user):
            library = app._app_library()
        self.assertEqual([p.id for p in library.profiles()], ["onshape", "figma", "plasticity", "blender", "autocad"])
        self.assertIs(app._app_library(), library, "built once, shared by every runtime")
        self.assertEqual(app.config["app_modes"], {"figma": "auto", "onshape": "off"})

    def test_settings_save_keeps_the_app_keys(self):
        self.write({"onshape_mode": "auto", "app_rules": {"figma": {"host": ["figma.com"]}}})
        config = ui.ControlCenterApp.load_config()
        ui.write_settings(config)
        saved = self.saved()
        self.assertEqual((saved["app_modes"], saved["onshape_mode"], saved["app_rules"], saved["profile_updates"]),
                         ({"onshape": "auto"}, "auto", {"figma": {"host": ["figma.com"]}}, "off"))
        self.assertEqual(ui.ControlCenterApp.load_config(), config, "load -> save -> load is unchanged")


class RuleTests(unittest.TestCase):
    def test_program_names(self):
        self.assertEqual(ui.normal_rule("exe", "Figma.exe"), ("Figma.exe", ""))
        self.assertEqual(ui.normal_rule("exe", '  "C:\\Program Files\\Figma\\Figma.exe" '),
                         ("Figma.exe", "Kept the file name only: Figma.exe."))
        for bad in ("", "Figma", "*.exe", "figma.exe.lnk", "..\\"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "^Enter a program file name"):
                ui.normal_rule("exe", bad)

    def test_hosts_and_pasted_web_addresses(self):
        self.assertEqual(ui.normal_rule("host", "Figma.com"), ("figma.com", ""))
        self.assertEqual(ui.normal_rule("host", "*.figma.com"), ("*.figma.com", ""))
        for pasted in ("https://www.figma.com/file/abc?node=1#x", "www.figma.com/design/abc", "www.figma.com:443",
                       "http://user@www.figma.com/"):
            with self.subTest(pasted=pasted):
                value, note = ui.normal_rule("host", pasted)
                self.assertEqual(value, "www.figma.com")
                self.assertEqual(note, "Kept the host only: www.figma.com. Desk Dial never stores a web address.")
        for bad in ("", "figma", "figma.*.com", "*figma.com", "https://", "fig ma.com", "localhost"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "^Enter a website host"):
                ui.normal_rule("host", bad)


# ============================================================================================ the model
class ModelCase(DataCase):
    def setUp(self):
        super().setUp()
        self.write({"onshape_mode": "auto"})
        self.config = ui.ControlCenterApp.load_config()
        self.lib = self.library(self.config["app_rules"])
        self.runtime = FakeAppRuntime(self.lib, self.config["app_modes"])
        self.model = ui.AppsSettingsModel(self.config, self.runtime, self.lib, save=ui.write_settings)


class ModelTests(ModelCase):
    def test_one_row_per_profile_with_badge_source_mode_and_detection(self):
        rows = {row["id"]: row for row in self.model.rows()}
        self.assertEqual(list(rows), ["onshape", "figma", "plasticity", "blender", "autocad"])
        self.assertEqual({pid: row["badge"] for pid, row in rows.items()},
                         {"onshape": "Tested", "figma": "Not yet tested", "plasticity": "Not yet tested",
                          "blender": "Basic", "autocad": "Basic"})
        self.assertEqual({row["source"] for row in rows.values()}, {"Karl"})
        self.assertEqual({pid: row["mode"] for pid, row in rows.items()},
                         {"onshape": "auto", "figma": "off", "plasticity": "off", "blender": "off", "autocad": "off"})
        self.assertEqual(rows["figma"]["summary"], "Figma.exe · figma.com · www.figma.com")
        self.assertEqual(rows["blender"]["summary"], "blender.exe")
        self.assertEqual(ui.APP_SOURCE_LABELS, {"bundled": "Karl", "user": "Imported", "updates": "Updated"})

    def test_rows_word_missing_detection_and_warnings(self):
        self.runtime.app_rows = lambda: [{"id": "figma", "name": "FIGMA", "status": "community", "source": "user",
                                          "mode": "manual", "detect_summary": "",
                                          "warnings": ["ALIGN/TIDY UP: Not on this keyboard", "b", "c"]},
                                         {"id": "../x", "name": "bad"}]
        (row,) = self.model.rows()
        self.assertEqual((row["source"], row["summary"]), ("Imported", ui.APPS_NOT_DETECTED))
        self.assertEqual(row["warnings"], "ALIGN/TIDY UP: Not on this keyboard (and 2 more)")
        self.runtime.app_rows = lambda: 1 / 0
        with self.assertLogs(ui._log, "WARNING"):
            self.assertEqual(self.model.rows(), [])

    def test_a_mode_applies_at_once_and_is_saved(self):
        self.assertTrue(self.model.set_mode("figma", "auto"))
        self.assertEqual(self.runtime.calls, [("figma", "auto")])
        self.assertEqual(self.saved()["app_modes"], {"onshape": "auto", "figma": "auto"})
        self.assertEqual(self.saved()["onshape_mode"], "auto")
        self.model.set_mode("onshape", "manual")
        self.assertEqual((self.saved()["app_modes"]["onshape"], self.saved()["onshape_mode"]), ("manual", "manual"),
                         "onshape_mode follows for one release (a rollback reads it)")
        self.assertFalse(self.model.set_mode("figma", "on"))
        self.assertFalse(self.model.set_mode("Figma!", "auto"))
        self.assertEqual(len(self.runtime.calls), 2)

    def test_a_runtime_from_before_app_profiles_gets_onshape(self):
        seen = []
        model = ui.AppsSettingsModel(self.config, SimpleNamespace(set_onshape_mode=seen.append), self.lib)
        model.set_mode("onshape", "manual")
        self.assertEqual(seen, ["manual"])

    def test_a_failed_save_is_reported_not_raised(self):
        def fail(_config):
            raise OSError("locked")
        model = ui.AppsSettingsModel(self.config, self.runtime, self.lib, save=fail)
        with self.assertLogs(ui._log, "WARNING"):
            model.set_mode("figma", "manual")
        self.assertEqual((model.message, model.message_ok), (ui.APPS_SAVE_FAILED, False))
        self.assertEqual(self.runtime.modes["figma"], "manual", "the change still applies")


class RulesModelTests(ModelCase):
    def test_add_and_remove_rules_reach_the_library_and_detection(self):
        ok, text = self.model.add_rule("blender", "exe", "C:\\Blender 4.2\\blender-launcher.exe")
        self.assertEqual((ok, text), (True, "Kept the file name only: blender-launcher.exe."))
        ok, text = self.model.add_rule("blender", "host", "https://blender.example.org/editor?id=1")
        self.assertEqual((ok, text), (True, "Kept the host only: blender.example.org. Desk Dial never stores a web "
                                            "address."))
        self.assertEqual(self.saved()["app_rules"], {"blender": {"exe": ["blender-launcher.exe"],
                                                                 "host": ["blender.example.org"]}})
        self.assertNotIn("https", json.dumps(self.saved()), "the web address is never stored")
        self.assertEqual(self.runtime.reloads, 2)
        detect = self.lib.get("blender").detect
        self.assertTrue(detect.matches_exe("blender-launcher.exe"))
        self.assertTrue(detect.matches_host("blender.example.org"))
        self.assertEqual(self.model.rules("blender"), {"exe": ["blender-launcher.exe"], "host": ["blender.example.org"]})
        ok, text = self.model.remove_rule("blender", "exe", "blender-launcher.exe")
        self.assertEqual((ok, text), (True, "Removed blender-launcher.exe."))
        self.model.remove_rule("blender", "host", "blender.example.org")
        self.assertEqual(self.saved()["app_rules"], {})
        self.assertFalse(self.lib.get("blender").detect.matches_exe("blender-launcher.exe"))

    def test_refusals_in_plain_words(self):
        self.assertEqual(self.model.add_rule("figma", "exe", "figma.exe"), (False, ui.RULE_DUPLICATE),
                         "already built in (case-insensitive)")
        self.assertEqual(self.model.add_rule("figma", "host", "figma"), (False, ui.RULE_BAD_HOST))
        self.assertEqual(self.model.add_rule("figma", "exe", "figma"), (False, ui.RULE_BAD_EXE))
        for i in range(ui.APP_RULES_MAX):
            self.assertTrue(self.model.add_rule("figma", "exe", f"f{i}.exe")[0])
        self.assertEqual(self.model.add_rule("figma", "exe", "one-more.exe"), (False, ui.RULE_FULL))
        self.assertEqual(self.model.remove_rule("figma", "exe", "never.exe"), (False, ""))

    def test_built_in_rules_are_shown_apart(self):
        self.assertEqual(self.model.built_in_rules("figma"), {"exe": ["Figma.exe"], "host": ["figma.com", "www.figma.com"]})
        self.assertEqual(self.model.rules("figma"), {"exe": [], "host": []})


class ImportTests(ModelCase):
    def karl(self, folder, pid="myapp", name="MY APP"):
        doc = json.loads((PROFILES / "karl" / "blender.json").read_text(encoding="ascii"))
        doc.update(id=pid, name=name)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{pid}.json"
        path.write_text(json.dumps(doc), encoding="ascii")
        return path

    def test_import_copies_the_pair_reloads_and_says_so(self):
        source = self.karl(self.root / "downloads")
        (source.parent / "myapp.windows.json").write_text(json.dumps({"overlay": 1, "detect": {"exe": ["myapp.exe"]}}),
                                                          encoding="ascii")
        ok, text = self.model.import_profile(source)
        self.assertEqual((ok, text), (True, "Imported My app. Choose Manual or Auto to use it."))
        self.assertEqual(sorted(p.name for p in self.user.iterdir()), ["myapp.json", "myapp.windows.json"])
        self.assertEqual(self.runtime.reloads, 1)
        self.assertEqual(self.lib.get("myapp").source, "user")
        row = next(r for r in self.model.rows() if r["id"] == "myapp")
        self.assertEqual((row["source"], row["mode"], row["summary"]), ("Imported", "off", "myapp.exe"))

    def test_picking_the_sidecar_imports_its_karl_file(self):
        source = self.karl(self.root / "downloads")
        sidecar = source.parent / "myapp.windows.json"
        sidecar.write_text(json.dumps({"overlay": 1}), encoding="ascii")
        self.assertTrue(self.model.import_profile(sidecar)[0])

    def test_reimporting_onshape_resets_it_to_off(self):
        """S3 decision: a re-import (an id that already exists, from any source) turns that app Off, through the
        runtime (which releases held input when it is active) and before the reload, saved with onshape_mode."""
        order = []
        set_mode, reload = self.runtime.set_app_mode, self.runtime.reload_profiles
        self.runtime.set_app_mode = lambda pid, mode: (order.append(("mode", pid, mode)), set_mode(pid, mode))
        self.runtime.reload_profiles = lambda: (order.append(("reload",)), reload())[1]
        source = self.root / "downloads" / "onshape.json"
        source.parent.mkdir()
        source.write_bytes((PROFILES / "karl" / "onshape.json").read_bytes())
        self.assertEqual(self.model.import_profile(source),
                         (True, "Imported Onshape. It's Off: choose Manual or Auto to use it."))
        self.assertEqual(order, [("mode", "onshape", "off"), ("reload",)])
        self.assertEqual((self.saved()["app_modes"]["onshape"], self.saved()["onshape_mode"]), ("off", "off"))
        self.assertEqual(ui.APPS_IMPORTED_REPLACED, "Imported {name}. It's Off: choose Manual or Auto to use it.")

    def test_reimporting_an_imported_app_resets_it_to_off(self):
        source = self.karl(self.root / "downloads")
        self.assertEqual(self.model.import_profile(source), (True, "Imported My app. Choose Manual or Auto to use it."))
        self.model.set_mode("myapp", "manual")
        self.assertEqual(self.model.import_profile(source),
                         (True, "Imported My app. It's Off: choose Manual or Auto to use it."))
        self.assertEqual(self.runtime.calls[-1], ("myapp", "off"))
        self.assertEqual(self.saved()["app_modes"]["myapp"], "off")
        self.assertEqual(self.saved()["onshape_mode"], "auto", "only the re-imported app changes")

    def test_a_refused_reimport_keeps_the_mode(self):
        source = self.root / "downloads" / "onshape.json"
        source.parent.mkdir()
        source.write_text('{"format": 1, "id": "onshape"}', encoding="ascii")
        self.assertFalse(self.model.import_profile(source)[0])
        self.assertEqual(self.runtime.calls, [])
        self.assertEqual(self.runtime.modes["onshape"], "auto")

    def test_a_bad_file_lists_its_problems_and_copies_nothing(self):
        bad = self.root / "bad.json"
        bad.write_text('{"format": 1, "id": "bad"}', encoding="ascii")
        ok, text = self.model.import_profile(bad)
        self.assertFalse(ok)
        self.assertTrue(text.startswith("Couldn't import bad.json: bad.json: "), text)
        self.assertFalse(self.user.exists() and any(self.user.iterdir()))
        self.assertEqual(self.runtime.reloads, 0)
        many = app_profiles.ProfileError([f"p{i}" for i in range(5)])
        with patch.object(self.lib, "import_file", side_effect=many):
            self.assertEqual(self.model.import_profile(bad)[1], "Couldn't import bad.json: p0; p1; p2 (and 2 more)")

    def test_no_library_no_import(self):
        model = ui.AppsSettingsModel(self.config, self.runtime, None)
        self.assertEqual(model.import_profile(self.root / "x.json"), (False, ui.APPS_NO_LIBRARY))


class FetchSettingTests(ModelCase):
    def test_the_daily_box_is_saved(self):
        self.assertFalse(self.model.fetch_daily)
        self.model.set_fetch_daily(True)
        self.assertEqual(self.saved()["profile_updates"], "daily")
        self.model.set_fetch_daily(False)
        self.assertEqual(self.saved()["profile_updates"], "off")


# ============================================================================================ icons
class IconTests(unittest.TestCase):
    def decode(self, png):
        from PIL import Image
        import io
        with Image.open(io.BytesIO(png)) as image:
            image.load()
            return image.mode, image.size, image.copy()

    def test_rgb565_big_endian_to_rgba_with_black_transparent(self):
        raw = bytearray(24 * 24 * 2)
        struct.pack_into(">H", raw, 2 * 1, 0xF800)        # pure red at (1, 0)
        struct.pack_into(">H", raw, 2 * 24, 0x07E0)       # pure green at (0, 1)
        struct.pack_into(">H", raw, 2 * 25, 0x001F)       # pure blue at (1, 1)
        struct.pack_into(">H", raw, 2 * 26, 0x0001)       # nearly black: kept, opaque
        mode, size, image = self.decode(ui.icon24_png(bytes(raw)))
        self.assertEqual((mode, size), ("RGBA", (24, 24)))
        self.assertEqual(image.getpixel((0, 0))[3], 0, "black is transparent")
        self.assertEqual(image.getpixel((1, 0)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((0, 1)), (0, 255, 0, 255))
        self.assertEqual(image.getpixel((1, 1)), (0, 0, 255, 255))
        self.assertEqual(image.getpixel((2, 1)), (0, 0, 8, 255))

    def test_every_bundled_icon_converts(self):
        for profile in app_profiles.Library(PROFILES).profiles():
            with self.subTest(id=profile.id):
                png = ui.icon24_png(profile.raw_karl["icon24"])
                self.assertEqual(self.decode(png)[1], (24, 24))

    def test_no_icon(self):
        for value in (None, "", "not base64!", b"\0" * 10, 7):
            self.assertIsNone(ui.icon24_png(value))


# ============================================================================================ the page on stand-ins
class FakeCheck(FakeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class FakeBool(FakeVariable):
    def __init__(self, value=False):
        super().__init__(value)


class PageTests(ModelCase):
    def setUp(self):
        super().setUp()
        self.buttons, self.labels, self.checks, self.images = [], [], [], []

        def button(parent, text, command, **kwargs):
            widget = FakeWidget(text=text)
            self.buttons.append((text, command, widget))
            return widget

        def label(parent, text="", *args, **kwargs):
            widget = FakeWidget(text=text, **kwargs)
            self.labels.append(widget)
            return widget

        def check(*args, **kwargs):
            widget = FakeCheck(**kwargs)
            self.checks.append(widget)
            return widget

        def photo(**kwargs):
            self.images.append(kwargs)
            return FakeWidget(**kwargs)
        for target, name, value in ((ui, "button", button), (ui, "label", label), (ui.tk, "Frame", FakeWidget),
                                    (ui.tk, "Label", FakeWidget), (ui.tk, "Checkbutton", check),
                                    (ui.tk, "BooleanVar", FakeBool), (ui.tk, "PhotoImage", photo)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        FakeWidget.winfo_children = lambda self: []
        self.addCleanup(lambda: delattr(FakeWidget, "winfo_children"))
        self.app = object.__new__(ui.ControlCenterApp)
        self.app.config, self.app.runtime, self.app.app_library = self.config, self.runtime, self.lib
        self.app.setup_window, self.app.setup_size = None, None
        self.model = self.app._build_apps_page(FakeWidget(), FakeWidget())

    def press(self, text, index=0):
        matches = [command for name, command, _w in self.buttons if name == text]
        matches[index]()

    def texts(self):
        return [w.values.get("text") for w in self.labels]

    def test_the_page_shows_every_row_and_the_actions(self):
        texts = self.texts()
        self.assertIn(ui.APPS_INTRO, texts)
        for name in ("ONSHAPE", "FIGMA", "PLASTICITY", "BLENDER", "AUTOCAD"):
            self.assertIn(name, texts)
        for badge in ("TESTED", "NOT YET TESTED", "BASIC"):
            self.assertIn(badge, texts)
        self.assertNotIn("COMMUNITY TESTED", texts, "no shipped profile has been confirmed by an owner yet")
        self.assertIn("Karl · Figma.exe · figma.com · www.figma.com", texts)
        self.assertEqual(len(self.images), 5, "a 24 px icon per row")
        self.assertTrue(all(i["format"] == "png" for i in self.images))
        names = [name for name, _c, _w in self.buttons]
        self.assertEqual(names.count("Off"), 5)
        self.assertEqual(names.count(ui.APPS_RULES), 5)
        for action in (ui.APPS_IMPORT, ui.APPS_OPEN_FOLDER, ui.APPS_CHECK):
            self.assertIn(action, names)
        self.assertEqual(self.checks[0].values["text"], ui.APPS_FETCH_DAILY)
        chosen = [w.values.get("bg") for name, _c, w in self.buttons if name == "Auto"]
        self.assertEqual(chosen[0], ui.RULE, "Onshape's Auto is shown chosen")
        self.assertEqual(chosen[1], ui.SURFACE)

    def test_a_segment_applies_and_saves(self):
        self.press("Manual", 1)                     # Figma's row
        self.assertEqual(self.runtime.calls, [("figma", "manual")])
        self.assertEqual(self.saved()["app_modes"]["figma"], "manual")

    def test_check_for_updates_runs_off_the_tk_thread_and_reports(self):
        started = []
        self.app.check_profile_updates = lambda: started.append(True) or True
        self.press(ui.APPS_CHECK)
        self.assertEqual((started, self.model.message), ([True], profile_updates.TEXT_CHECKING))
        self.app.apps_model = self.model
        self.app._profile_update_finished(profile_updates.CheckResult(updated=["FIGMA"], finished=1_800_000_000.0))
        self.assertEqual(self.model.message, "Updated: FIGMA.")
        self.assertEqual(self.runtime.reloads, 1, "updated files reload the profiles")
        self.assertEqual(self.saved()["profile_updates_last"], 1_800_000_000.0)

    def test_the_daily_box(self):
        box = self.checks[0]
        box.values["variable"].set(True)
        box.values["command"]()
        self.assertEqual(self.saved()["profile_updates"], "daily")

    def test_open_profiles_folder_makes_it(self):
        opened = []
        with patch.object(paths, "profiles_user_dir", lambda frozen=None: self.user), \
                patch.object(ui.os, "startfile", opened.append, create=True):
            self.press(ui.APPS_OPEN_FOLDER)
        self.assertEqual(opened, [str(self.user)])
        self.assertTrue(self.user.is_dir())
        with patch.object(ui.os, "startfile", side_effect=OSError("no shell"), create=True), \
                self.assertLogs(ui._log, "WARNING"):
            self.press(ui.APPS_OPEN_FOLDER)
        self.assertEqual(self.model.message, ui.APPS_FOLDER_FAILED)


# ============================================================================================ app wiring
class WiringTests(DataCase):
    def test_apply_presentation_sends_only_changed_modes(self):
        app = object.__new__(ui.ControlCenterApp)
        app.config = {"app_modes": {"onshape": "auto", "figma": "manual"}}
        runtime = FakeAppRuntime(None, {"onshape": "auto"})
        for name in ("led_style", "artwork_enabled"):
            setattr(runtime, name, None)
        ui.ControlCenterApp._apply_presentation(app, runtime)
        self.assertEqual(runtime.calls, [("figma", "manual")])

    def test_runtime_kwargs_follow_runtimes_signature(self):
        app = object.__new__(ui.ControlCenterApp)
        app.config = {"app_modes": {"onshape": "auto"}, "app_rules": {}, "app_order": ["figma"]}
        app.app_library = library = object()

        class New:
            def __init__(self, controller, *a, app_library=None, app_modes=None, app_rules=None, app_order=None):
                pass

        class Old:
            def __init__(self, controller, *a, onshape=None):
                pass
        with patch.object(ui, "Runtime", New):
            self.assertEqual(app._app_runtime_kwargs(), {"app_library": library, "app_modes": {"onshape": "auto"},
                                                         "app_rules": {}, "app_order": ["figma"]})
        with patch.object(ui, "Runtime", Old):
            self.assertEqual(app._app_runtime_kwargs(), {})

    def test_daily_check_only_live_and_when_due(self):
        app = object.__new__(ui.ControlCenterApp)
        app.config = {"profile_updates": "daily", "profile_updates_last": 0}
        started = []
        app.check_profile_updates = lambda: started.append(1) or True
        app.live, app.smoke = False, False
        app._profile_updates_tick(now=1_800_000_000.0)
        self.assertEqual(started, [], "the simulator never fetches")
        app.live = True
        app._profile_updates_tick(now=1_800_000_000.0)
        self.assertEqual(started, [1])
        app._profile_updates_tick(now=1_800_000_010.0)
        self.assertEqual(started, [1], "a check that didn't finish waits an hour before the next try")
        app.config["profile_updates"] = "off"
        app._profile_updates_tick(now=1_800_100_000.0)
        self.assertEqual(started, [1], "Off never fetches")

    def test_a_failed_check_keeps_the_last_time(self):
        app = object.__new__(ui.ControlCenterApp)
        app.config = {"profile_updates_last": 5}
        app.runtime = SimpleNamespace()
        app._profile_update_finished(profile_updates.CheckResult(ok=False, offline=True, finished=99.0))
        self.assertEqual(app.config["profile_updates_last"], 5)
        self.assertFalse((self.data_dir / "settings.json").exists())

    def test_the_updater_targets_the_updates_folder_never_user(self):
        app = object.__new__(ui.ControlCenterApp)
        updater = app._profile_updater()
        self.assertEqual(updater.updates_dir, paths.profiles_updates_dir())
        self.assertEqual(updater.user_dir, paths.profiles_user_dir())
        self.assertNotEqual(updater.updates_dir, updater.user_dir)


class RealRuntimeTests(DataCase):
    """The model and the tray / status helpers over lane DD-B's real Runtime (simulated providers, no knob)."""

    def setUp(self):
        super().setUp()
        from control_center import runtime as runtime_module
        from control_center.controller import Controller
        from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows
        from test_cc_controller import FakeDevice, ManualExecutor
        self.write({"onshape_mode": "auto"})
        self.config = ui.ControlCenterApp.load_config()
        self.lib = self.library(self.config["app_rules"])
        app = object.__new__(ui.ControlCenterApp)
        app.config, app.app_library = self.config, self.lib
        with patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor):
            self.runtime = runtime_module.Runtime(Controller(), SimulatedSonos(), SimulatedAppleMusic(),
                                                  SimulatedWindows(), FakeDevice(), **app._app_runtime_kwargs())
        self.addCleanup(self.runtime.shutdown)
        self.model = ui.AppsSettingsModel(self.config, self.runtime, self.lib, save=ui.write_settings)

    def test_the_runtime_takes_the_library_and_the_modes(self):
        self.assertIs(self.runtime.app_library, self.lib)
        self.assertEqual(self.runtime.app_modes()["onshape"], "auto")
        rows = self.model.rows()
        self.assertEqual([r["id"] for r in rows], ["onshape", "figma", "plasticity", "blender", "autocad"])
        self.assertEqual([r["badge"] for r in rows], ["Tested", "Not yet tested", "Not yet tested", "Basic", "Basic"])
        self.assertTrue(all(ui.icon24_png(r["icon24"]) for r in rows), "the runtime's icons convert")

    def test_modes_and_rules_reach_the_runtime(self):
        self.model.set_mode("figma", "auto")
        self.assertEqual(self.runtime.app_modes()["figma"], "auto")
        self.assertTrue(self.model.add_rule("blender", "exe", "blender-launcher.exe")[0])
        row = next(r for r in self.model.rows() if r["id"] == "blender")
        self.assertIn("blender-launcher.exe", row["summary"])
        self.assertEqual(self.saved()["app_rules"], {"blender": {"exe": ["blender-launcher.exe"]}})

    def test_tray_and_status(self):
        import standalone
        entries = standalone.tray_app_entries(standalone.app_menu_entries(self.runtime))
        self.assertEqual(len(entries), 5)
        self.assertTrue(all(request.startswith("app:") for _t, request, _c in entries))
        block = standalone._app_status(self.runtime)
        self.assertEqual(block["mode_by_id"]["onshape"], "auto")
        self.assertNotIn("://", json.dumps(block))


class KnobPageTests(unittest.TestCase):
    SOURCE = (REPO / "control_center" / "ui.py").read_text(encoding="utf-8")

    def test_the_knob_page_points_to_apps(self):
        setup = self.SOURCE[self.SOURCE.index("    def setup(self, page=None):"):self.SOURCE.index("    def _place_settings")]
        self.assertNotIn('"Onshape mode"', setup)
        self.assertNotIn("onshape_choice", setup)
        self.assertIn("APPS_POINTER_NOTE", setup)
        self.assertEqual(ui.APPS_POINTER_NOTE, "Onshape and other apps: Settings › Apps.")
        self.assertIn(("apps", "Apps"), ui.SETTINGS_PAGES)
        self.assertEqual(ui.SETTINGS_OWN_SAVE_PAGES, ("home_assistant", "apps"))
        self.assertIn('if key in ("knob", "apps"):', setup, "Apps scrolls like Knob")

    def test_copy(self):
        self.assertEqual(ui.APP_STATUS_BADGES, {"tested": "Tested", "community": "Not yet tested", "basic": "Basic"})
        self.assertEqual(app_profiles.STATUS, ("tested", "community", "basic"), "only the shown label changed")
        self.assertEqual([t for t, _v in ui.APP_MODE_CHOICES], ["Off", "Manual", "Auto"])
        self.assertEqual(ui.APPS_FETCH_DAILY, "Fetch updated profiles from the Desk Dial repo (once a day)")


class BundledProfilesDirTests(unittest.TestCase):
    def test_checkout_and_frozen(self):
        self.assertEqual(paths.bundled_profiles_dir(frozen=False), REPO / "profiles")
        with patch.object(sys, "_MEIPASS", "C:\\bundle", create=True):
            self.assertEqual(paths.bundled_profiles_dir(frozen=True), Path("C:\\bundle") / "profiles")
        self.assertTrue((paths.bundled_profiles_dir(frozen=False) / "karl" / "onshape.json").is_file())


if __name__ == "__main__":
    unittest.main()

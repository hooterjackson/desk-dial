"""DD-BUG-047: no shipped Sonos room, speaker or port. A fresh settings.json pins nothing, a new
speaker IP un-pins the room, a room_uid without the speaker marker is dropped once on load (no
identifier is kept in code), the adapter pins the speaker's own room and the app remembers it once
together with the marker. No Tk, no network (TEST-NET-1 addresses only)."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402
from control_center.sonos import SonosAdapter, SonosUnavailable  # noqa: E402
from test_cc_music import FakeSpeaker, MemoryStore  # noqa: E402
import test_r3_settings  # noqa: E402  (its stand-in Settings window; not re-run here)

SPEAKER_A = "192.0.2.10"     # RFC 5737 documentation addresses
SPEAKER_B = "192.0.2.20"


class DataDirCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        patcher = patch.object(ui, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, value):
        (self.data_dir / "settings.json").write_text(json.dumps(value), encoding="utf-8")


class DefaultRoomTests(DataDirCase):
    def test_default_config_has_no_pinned_room_speaker_or_port(self):
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["speaker_ip"], config["room_uid"], config["port"]), ("", "", ""))

    def test_a_room_without_the_speaker_marker_is_dropped_once_on_load(self):
        self.write({"speaker_ip": SPEAKER_A, "room_uid": "RINCON_TEST_OLD"})          # older build
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["room_uid"], config[ui.ROOM_UID_SOURCE_KEY]), ("", ""))
        self.write({"speaker_ip": SPEAKER_A, "room_uid": "RINCON_TEST_OLD", "room_uid_source": "other"})
        self.assertEqual(ui.ControlCenterApp.load_config()["room_uid"], "")
        self.write({"speaker_ip": SPEAKER_A, "room_uid": "RINCON_TEST_OWN",
                    ui.ROOM_UID_SOURCE_KEY: ui.ROOM_UID_FROM_SPEAKER})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["room_uid"], config[ui.ROOM_UID_SOURCE_KEY]),
                         ("RINCON_TEST_OWN", ui.ROOM_UID_FROM_SPEAKER))
        self.write({"speaker_ip": 5, "room_uid": None})
        config = ui.ControlCenterApp.load_config()
        self.assertEqual((config["speaker_ip"], config["room_uid"]), ("", ""))

    def test_no_room_identifier_or_hash_of_one_is_kept_in_code(self):
        import re
        source = Path(ui.__file__).read_text(encoding="utf-8")
        self.assertNotIn("_RETIRED_ROOM_UID", source)
        self.assertIsNone(re.search(r"RINCON_[0-9A-Fa-f]{12}", source))
        self.assertIsNone(re.search(r"[0-9a-f]{64}", source))

    def test_ip_change_clears_room_uid(self):
        config = {"speaker_ip": SPEAKER_A, "room_uid": "RINCON_TEST_OWN"}
        ui.apply_speaker_ip(config, " " + SPEAKER_A + " ")
        self.assertEqual(config["room_uid"], "RINCON_TEST_OWN")
        ui.apply_speaker_ip(config, SPEAKER_B)
        self.assertEqual(config, {"speaker_ip": SPEAKER_B, "room_uid": ""})

    def test_adapter_without_room_pins_the_speakers_own_room(self):
        speaker = FakeSpeaker()
        speaker.uid = "RINCON_TEST_ANY"
        adapter = SonosAdapter(SPEAKER_A, room_uid=None, soco_factory=lambda host: speaker,
                               recovery_store=MemoryStore(), shuffle_store=MemoryStore())
        self.assertTrue(adapter.read_state()["online"])
        self.assertEqual(adapter.room_uid, "RINCON_TEST_ANY")

    def test_the_pinned_room_is_remembered_once(self):
        app = object.__new__(ui.ControlCenterApp)
        app.live = True
        app.config = {"speaker_ip": SPEAKER_A, "room_uid": ""}
        app.runtime = SimpleNamespace(sonos=SimpleNamespace(host=SPEAKER_A, room_uid="RINCON_TEST_ANY"))
        app._persist_pinned_room()
        self.assertEqual(app.config["room_uid"], "RINCON_TEST_ANY")
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["room_uid"], "RINCON_TEST_ANY")
        self.assertEqual(saved[ui.ROOM_UID_SOURCE_KEY], ui.ROOM_UID_FROM_SPEAKER)
        self.assertEqual(ui.ControlCenterApp.load_config()["room_uid"], "RINCON_TEST_ANY",
                         "a room the speaker reported survives the next start")
        app.config = {"speaker_ip": SPEAKER_B, "room_uid": ""}       # adapter still on the old speaker
        app._persist_pinned_room()
        self.assertEqual(app.config["room_uid"], "")

    def test_no_speaker_is_an_offline_stand_in_not_a_crash(self):
        sonos = ui.UnconfiguredSonos()
        state = sonos.read_state()
        self.assertFalse(state["online"])
        self.assertIn("IPv4", state["error"])
        with self.assertRaises(SonosUnavailable):
            sonos.set_volume(10, "rev")
        self.assertIsNone(getattr(sonos, "room_uid", None))


class SettingsSaveTests(unittest.TestCase):
    setUp = test_r3_settings.SettingsWindowPagesTests.setUp

    def test_saving_a_new_ip_drops_room_uid_and_an_empty_ip_saves(self):
        self.app.config.update(speaker_ip=SPEAKER_A, room_uid="RINCON_TEST_OWN")
        self.app.config[ui.ROOM_UID_SOURCE_KEY] = ui.ROOM_UID_FROM_SPEAKER
        self.app.setup()
        ip = self.vars[0]
        self.buttons["Save settings"]()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["room_uid"], "RINCON_TEST_OWN", "same speaker: the room stays pinned")
        self.assertEqual(saved[ui.ROOM_UID_SOURCE_KEY], ui.ROOM_UID_FROM_SPEAKER, "Save keeps the marker")
        ip.set(SPEAKER_B)
        self.buttons["Save settings"]()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["speaker_ip"], saved["room_uid"]), (SPEAKER_B, ""))
        ip.set("")
        self.buttons["Save settings"]()
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["speaker_ip"], "")


if __name__ == "__main__":
    unittest.main()

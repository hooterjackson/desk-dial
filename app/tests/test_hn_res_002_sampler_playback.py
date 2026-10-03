"""HN-RES-002: the soak sampler (work/audit/tools/deskdial_sampler.py) reads the real status.json shape and records a
scalar playback state and the active presentation per sample, so a soak record shows when music played.

No process, port, window or network: status_flags() reads a status.json written to a temporary folder."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLER = ROOT.parent / "tools" / "audit" / "tools" / "deskdial_sampler.py"


def load_sampler():
    spec = importlib.util.spec_from_file_location("deskdial_sampler_hn_res_002", SAMPLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status_doc(playback):
    """A status.json in the shape standalone.status_payload writes (synthetic values, no names)."""
    doc = {"pid": 1, "live": True, "connected": True, "ready": True, "mode": "VOLUME", "screenStatus": "",
           "loading": False, "sonosOnline": True, "volume": 20, "artwork2": True, "firmwarePresentation": 5,
           "dataDir": "X:/data", "executable": "X:/app.exe",
           "media": {"cover": {"wanted": 1, "present": 1, "uploads": 3, "hits": 2, "errors": 0, "failedKeys": [],
                               "lastError": "", "dropped": 0},
                     "icon": {"wanted": 1, "present": 1, "uploads": 1, "hits": 0, "errors": 0, "failedKeys": [],
                              "lastError": "", "dropped": 0}},
           "overlay": {"alive": True, "state": "shown"},
           "stage": {"posted": 0, "failed": 0, "stage": {"state": "idle"}},
           "lights": {"configured": True, "online": True, "on": True, "on_count": 2, "name": "Some Room",
                      "area_id": "some_area"},
           "knobFeel": {"sound": "normal", "volume": 50, "calibrating": False},
           "onshape": {"mode": "off", "active": False},
           "time": 0.0}
    if playback is not None:
        doc["playback"] = playback
    return doc


@unittest.skipUnless(SAMPLER.is_file(), "work/audit/tools/deskdial_sampler.py is not present")
class SamplerPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.sampler = load_sampler()
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def flags(self, doc):
        path = self.dir / "status.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return self.sampler.status_flags(str(path))

    def test_a_playing_capture_differs_from_an_idle_one(self):
        playing, idle = self.flags(status_doc("PLAYING")), self.flags(status_doc("PAUSED_PLAYBACK"))
        self.assertEqual((playing["playback"], playing["playing"]), ("PLAYING", True))
        self.assertEqual((idle["playback"], idle["playing"]), ("PAUSED_PLAYBACK", False))
        self.assertNotEqual(playing["playback"], idle["playback"])

    def test_the_active_presentation_and_the_real_sections_are_recorded(self):
        flags = self.flags(status_doc("PLAYING"))
        self.assertEqual(flags["presentation"], 5)
        self.assertEqual(flags["overlay.state"], "shown")
        self.assertEqual(flags["stage.stage.state"], "idle")
        self.assertEqual(flags["media.cover.uploads"], 3)
        self.assertEqual(flags["knobFeel.sound"], "normal")
        self.assertIs(flags["lights.on"], True)
        self.assertIs(flags["sonosOnline"], True)
        self.assertIn("status_age_s", flags)

    def test_no_name_path_or_free_text_is_recorded(self):
        flags = self.flags(status_doc("PLAYING"))
        for value in flags.values():
            self.assertNotIn(value, ("Some Room", "some_area", "X:/data", "X:/app.exe"))
        for key in flags:
            self.assertFalse(key.endswith(("name", "area_id", "dataDir", "executable", "lastError")), key)

    def test_without_a_playback_field_the_state_is_unknown_not_idle(self):
        flags = self.flags(status_doc(None))
        self.assertEqual((flags["playback"], flags["playing"]), (None, None))
        bogus = self.flags(status_doc("bogus"))
        self.assertEqual((bogus["playback"], bogus["playing"]), (None, None))

    def test_an_unreadable_status_is_flagged(self):
        path = self.dir / "status.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.sampler.status_flags(str(path)), {"status_read": "error"})


if __name__ == "__main__":
    unittest.main()

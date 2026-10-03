"""DD-BUG-001: an unreadable credential file or a non-IPv4 speaker address never aborts startup.
providers(live=True) falls back (Apple Music signed out with a strip notice, Sonos not set up),
load_config and Settings Save refuse IPv6, and the next save sets the unreadable file aside.
No Tk, no ports, no network."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402
from control_center.credentials import CredentialError, CredentialStore, musickit_saver  # noqa: E402
import test_r3_settings  # noqa: E402  (its stand-in Settings window; not re-run here)

IPV6 = "fe80::1"


class LockedStore:
    def __init__(self, *_args, **_kwargs):
        pass

    def load(self):
        raise CredentialError("Windows could not unlock these credentials.")


class LiveStartupResilienceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        for target, name, value in ((ui, "DATA_DIR", self.data_dir),
                                    ("control_center.windows.WindowsAdapter", None, MagicMock())):
            patcher = patch.object(target, name, value) if name else patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = object.__new__(ui.ControlCenterApp)
        self.app.root = MagicMock()
        self.app.config = ui.ControlCenterApp.load_config()

    def test_unreadable_credentials_and_ipv6_speaker_do_not_abort_startup(self):
        self.app.config["speaker_ip"] = IPV6                 # hand-edited after load
        with patch("control_center.credentials.CredentialStore", LockedStore):
            sonos, apple, _windows = self.app.providers(True)
            self.assertTrue(self.app.credentials_locked)
            self.assertFalse(sonos.read_state()["online"])
            self.assertFalse(apple.has_credentials())
            self.assertEqual(apple.credential_loader(), {}, "the loader never raises either")
        runtime = SimpleNamespace(device_connected=False, device_supported=True, apple=apple,
                                  controller=SimpleNamespace(state={}))
        strip = ui.strip_model(runtime, credentials_locked=self.app.credentials_locked)
        self.assertEqual((strip[2]["state"], strip[2]["detail"], strip[2]["key"]),
                         ("Sign in again", ui.CREDENTIALS_LOCKED_DETAIL, "sign_in"))

    def test_load_config_drops_a_non_ipv4_speaker(self):
        for bad in (IPV6, "speaker.local", "not an address"):
            with self.subTest(bad=bad):
                (self.data_dir / "settings.json").write_text(json.dumps({"speaker_ip": bad, "room_uid": "RINCON_TEST"}),
                                                             encoding="utf-8")
                config = ui.ControlCenterApp.load_config()
                self.assertEqual((config["speaker_ip"], config["room_uid"]), ("", ""))
        self.assertTrue(ui.valid_speaker_ip("192.0.2.10"))
        self.assertFalse(ui.valid_speaker_ip(IPV6))


class SaveRejectsIpv6Tests(unittest.TestCase):
    setUp = test_r3_settings.SettingsWindowPagesTests.setUp

    def test_save_rejects_ipv6(self):
        self.app.setup()
        self.vars[0].set(IPV6)
        self.buttons["Save settings"]()
        self.assertFalse((self.data_dir / "settings.json").exists())


@unittest.skipUnless(os.name == "nt", "Windows DPAPI")
class UnreadableFileTests(unittest.TestCase):
    def test_next_save_sets_the_unreadable_file_aside(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.bin"
            path.write_bytes(CredentialStore.MAGIC + b"another account's blob")
            store = CredentialStore(path)
            with self.assertRaises(CredentialError):
                store.load()
            musickit_saver(store)({"developer_token": "TEST-DEV", "music_user_token": "TEST-USER"})
            self.assertEqual(store.load()["music_user_token"], "TEST-USER")
            aside = [p for p in Path(directory).iterdir() if p.name.startswith("credentials.bin.unreadable-")]
            self.assertEqual(len(aside), 1, "kept, never deleted")
            self.assertFalse(store.set_aside_if_unreadable(), "a readable file stays")


if __name__ == "__main__":
    unittest.main()

"""DD-BUG-001 (Home Assistant side): save_token works on a credential file this account cannot
unlock. CredentialStore.update sets the unreadable file aside, then the token lands in a fresh
file; load_token never raises. DPAPI is replaced by a reversible stand-in. No Tk, no network."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import credentials  # noqa: E402
from control_center.credentials import CredentialError, CredentialStore  # noqa: E402
from control_center.home_assistant import load_token, save_token  # noqa: E402

KEY = b"\x5a"


def fake_dpapi(data, *, decrypt=False):
    if decrypt and not data.startswith(b"OK"):
        raise CredentialError("Windows could not unlock these credentials.")
    body = data[2:] if decrypt else data
    out = bytes(b ^ KEY[0] for b in body)
    return out if decrypt else b"OK" + out


class SaveTokenUnreadableFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        patcher = patch.object(credentials, "_dpapi", fake_dpapi)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = CredentialStore(self.dir / "credentials.bin")
        # Another account's blob: right header, but this account cannot decrypt it.
        self.store.path.write_bytes(CredentialStore.MAGIC + b"FOREIGN-BLOB")

    def test_save_token_sets_an_unreadable_file_aside_and_saves(self):
        with self.assertRaises(CredentialError):
            self.store.load()
        self.assertEqual(load_token(self.store), "", "load_token never raises")
        save_token(self.store, "test-token-value")          # no retry needed by the caller
        self.assertEqual(load_token(self.store), "test-token-value")
        aside = list(self.dir.glob("credentials.bin.unreadable-*"))
        self.assertEqual(len(aside), 1, "the unreadable file is kept, never deleted")
        self.assertEqual(aside[0].read_bytes(), CredentialStore.MAGIC + b"FOREIGN-BLOB")

    def test_readable_file_keeps_other_credentials(self):
        self.store.save({"team_id": "T"})
        save_token(self.store, "test-token-value")
        self.assertEqual(self.store.load(), {"team_id": "T", "ha_token": "test-token-value"})
        self.assertEqual(list(self.dir.glob("credentials.bin.unreadable-*")), [])


if __name__ == "__main__":
    unittest.main()

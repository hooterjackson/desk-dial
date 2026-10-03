"""DD-RES-001: a MusicKit authorization merges into the credential file and never deletes the
Home Assistant token (key file or a snapshot taken before the HA Save). No ports, no network."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.credentials import (AuthServer, CredentialStore, STORE_LOCK, musickit_saver)
from control_center.home_assistant import save_token


class MemoryStore(CredentialStore):
    def __init__(self, data=None):
        self.data = dict(data or {})

    def load(self):
        return dict(self.data)

    def save(self, credentials):
        self.data = dict(credentials)


KEY_FILE = {"team_id": "ABCDEFGHIJ", "key_id": "0123456789", "private_key": "TEST-KEY"}


class MusicKitMergeTests(unittest.TestCase):
    def test_musickit_authorization_keeps_ha_token_with_key_file(self):
        store = MemoryStore({"ha_token": "TEST-HA"})
        server = AuthServer(KEY_FILE, on_token=musickit_saver(store))
        self.assertEqual(server._accept_token("TEST-USER")[0], 200)
        self.assertEqual(store.load()["ha_token"], "TEST-HA")
        self.assertEqual(store.load()["music_user_token"], "TEST-USER")
        self.assertEqual(store.load()["private_key"], "TEST-KEY")

    def test_ha_save_between_click_and_consent_is_kept(self):
        store = MemoryStore({"developer_token": "TEST-DEV"})
        snapshot = store.load()                                # taken at the Authorize click
        server = AuthServer(snapshot, on_token=musickit_saver(store))
        with STORE_LOCK:
            save_token(store, "TEST-HA")                       # HA page saved meanwhile
        self.assertEqual(server._accept_token("TEST-USER")[0], 200)
        self.assertEqual(store.load(), {"developer_token": "TEST-DEV", "ha_token": "TEST-HA",
                                        "music_user_token": "TEST-USER"})
        self.assertEqual(server._accept_token("again")[0], 409)

    def test_update_is_serialised_by_the_process_lock(self):
        store = MemoryStore({})
        def bump(current):
            current["n"] = current.get("n", 0) + 1
            return current
        threads = [threading.Thread(target=lambda: [store.update(bump) for _ in range(200)]) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(store.load()["n"], 800)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_real_store_keeps_both(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CredentialStore(Path(directory) / "credentials.bin")
            save_token(store, "TEST-HA")
            server = AuthServer(KEY_FILE, on_token=musickit_saver(store))
            self.assertEqual(server._accept_token("TEST-USER")[0], 200)
            loaded = store.load()
            self.assertEqual(loaded["ha_token"], "TEST-HA")
            self.assertEqual(loaded["music_user_token"], "TEST-USER")


if __name__ == "__main__":
    unittest.main()

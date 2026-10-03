"""DD-RES-001 follow-up: home_assistant.save_token merges through the store's atomic update()
(one read-modify-write under STORE_LOCK) and keeps a load/save fallback for plain stores.
No ports, no network, no Tk."""
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.credentials import CredentialStore, STORE_LOCK
from control_center.home_assistant import CREDENTIAL_KEY, load_token, save_token


class UpdateStore(CredentialStore):
    """A real CredentialStore.update over an in-memory file; counts the paths taken."""
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.updates = 0

    def set_aside_if_unreadable(self):
        return False

    def load(self):
        return dict(self.data)

    def save(self, credentials):
        self.data = dict(credentials)

    def update(self, change):
        self.updates += 1
        return super().update(change)


class PlainStore:
    """A test stand-in without update(): save_token must still work."""
    def __init__(self, data=None):
        self.data = dict(data or {})

    def load(self):
        return dict(self.data)

    def save(self, credentials):
        self.data = dict(credentials)


class SaveTokenUpdateTests(unittest.TestCase):
    def test_uses_update_and_keeps_other_keys(self):
        store = UpdateStore({"music_user_token": "TEST-USER"})
        save_token(store, "TEST-HA")
        self.assertEqual(store.updates, 1)
        self.assertEqual(store.data, {"music_user_token": "TEST-USER", CREDENTIAL_KEY: "TEST-HA"})
        save_token(store, "")
        self.assertEqual(store.updates, 2)
        self.assertEqual(store.data, {"music_user_token": "TEST-USER"})

    def test_change_runs_under_store_lock(self):
        store = UpdateStore()
        seen = []
        original = store.load
        def load():
            # RLock: another thread cannot acquire it while update() holds it.
            result = []
            probe = threading.Thread(target=lambda: result.append(STORE_LOCK.acquire(blocking=False)))
            probe.start()
            probe.join()
            if result[0]:
                STORE_LOCK.release()
            seen.append(result[0])
            return original()
        store.load = load
        save_token(store, "TEST-HA")
        self.assertEqual(seen, [False], "the merge read happened while STORE_LOCK was held")

    def test_concurrent_writer_key_is_not_lost(self):
        store = UpdateStore({})
        def other_writer():
            for n in range(200):
                store.update(lambda current, n=n: {**current, "music_user_token": f"m{n}"})
        thread = threading.Thread(target=other_writer)
        thread.start()
        for _ in range(200):
            save_token(store, "TEST-HA")
        thread.join()
        self.assertEqual(store.data[CREDENTIAL_KEY], "TEST-HA")
        self.assertEqual(store.data["music_user_token"], "m199")

    def test_plain_store_fallback(self):
        store = PlainStore({"team_id": "t"})
        save_token(store, "TEST-HA")
        self.assertEqual(store.data, {"team_id": "t", CREDENTIAL_KEY: "TEST-HA"})
        self.assertEqual(load_token(store), "TEST-HA")
        save_token(store, "")
        self.assertEqual(store.data, {"team_id": "t"})

    def test_plain_store_with_empty_load(self):
        class NoneStore(PlainStore):
            def load(self):
                return None
        store = NoneStore()
        save_token(store, "TEST-HA")
        self.assertEqual(store.data, {CREDENTIAL_KEY: "TEST-HA"})


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.credentials import (AuthServer, CONSENT_TEXT, CredentialStore, CredentialError,
                                        MusicKitCredentials, developer_token)


class CredentialTests(unittest.TestCase):
    def test_the_consent_copy_is_the_approved_string(self):
        # settings.apple.consent (K3 sections 14.2, 15.3; [r2.2] the approval pass is closed,
        # C5-70). Like is add-only for good (C5-67): the page never promises an unlike.
        self.assertEqual(CONSENT_TEXT, "Allow Desk Dial to read your Apple Music library and to mark songs as "
                                       "Favorites when you press Like. A Favorite can add the song to your library.")
        for withdrawn in ("unfavourite", "unfavorite", "unlike", "remove", "modify your library"):
            self.assertNotIn(withdrawn, CONSENT_TEXT.lower())

    def test_developer_token_is_real_es256_with_bounded_expiry_and_origin(self):
        try:
            import jwt
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.skipTest("MusicKit signing dependencies are not installed")
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AuthKey_TEST.p8"
            path.write_bytes(pem)
            credentials = MusicKitCredentials.from_key_file("ABCDEFGHIJ", "0123456789", path)
            token = developer_token(credentials, origin="http://127.0.0.1:12345")
        decoded = jwt.decode(token, key.public_key(), algorithms=["ES256"], issuer="ABCDEFGHIJ")
        self.assertEqual(jwt.get_unverified_header(token)["kid"], "0123456789")
        self.assertEqual(decoded["origin"], ["http://127.0.0.1:12345"])
        self.assertLessEqual(decoded["exp"] - decoded["iat"], 3630)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_encrypted_atomic_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.bin"
            store = CredentialStore(path)
            self.assertEqual(store.load(), {})
            data = {"music_user_token": "TEST-SECRET-TOKEN", "private_key": "TEST-KEY"}
            store.save(data)
            self.assertEqual(store.load(), data)
            self.assertNotIn(b"TEST-SECRET", path.read_bytes())
            store.save({"music_user_token": "replacement"})
            self.assertEqual(store.load()["music_user_token"], "replacement")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            path.write_bytes(b"broken")
            with self.assertRaises(CredentialError):
                store.load()

    def test_loopback_authorization_requires_origin_nonce_and_single_use(self):
        saved = []
        server = AuthServer({"developer_token": "TEST-DEVELOPER"}, saved.append)
        url = server.start()
        try:
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            page = urlopen(url, timeout=2).read().decode()
            self.assertIn("Authorize Apple Music", page)
            self.assertNotIn("TEST-USER-TOKEN", page)
            # settings.apple.consent (K3 sections 14.2, 15.3): the app can now mark songs as Favorites.
            self.assertIn("<p>" + CONSENT_TEXT + "</p>", page)
            self.assertIn("mark songs as Favorites when you press Like", page)
            self.assertNotIn("modify your library", page)
            def post(origin=None, nonce=None):
                headers = {"Content-Type": "application/json"}
                if origin:
                    headers["Origin"] = origin
                if nonce:
                    headers["X-NanoD-Nonce"] = nonce
                return urlopen(Request(url + "token", data=json.dumps({"token": "TEST-USER-TOKEN"}).encode(), headers=headers), timeout=2)
            for origin, nonce in [(None, None), ("https://attacker.example", server._nonce), (server.origin, "wrong")]:
                with self.assertRaises(HTTPError) as error:
                    post(origin, nonce)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            with post(server.origin, server._nonce) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(saved[0]["music_user_token"], "TEST-USER-TOKEN")
            self.assertEqual(server.events.get_nowait(), {"event": "authorized"})
            with self.assertRaises(HTTPError) as error:
                post(server.origin, server._nonce)
            self.assertEqual(error.exception.code, 409)
            error.exception.close()
        finally:
            server.stop()

    def test_save_failure_does_not_report_authorized_or_leak_exception(self):
        def fail(value):
            raise RuntimeError("TEST-SECRET-TOKEN")
        server = AuthServer({"developer_token": "TEST-DEVELOPER"}, fail)
        url = server.start()
        try:
            request = Request(url + "token", data=b'{"token":"TEST-SECRET-TOKEN"}', headers={
                "Origin": server.origin, "X-NanoD-Nonce": server._nonce,
                "Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=2)
            self.assertNotIn("TEST-SECRET", error.exception.read().decode())
            error.exception.close()
            self.assertEqual(server.events.get_nowait()["event"], "error")
            self.assertFalse(server._complete)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()

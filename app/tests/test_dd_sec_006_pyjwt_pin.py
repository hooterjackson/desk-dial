"""DD-SEC-006: PyJWT 2.14.0 carries CVE-2026-101918 (GHSA-42vr-xj54-vc7v, a RecursionError on deeply nested
payloads in jwt.decode(verify_signature=False) and PyJWKClient). Desk Dial never reaches that path, but the pin
is raised to the fixed release so scanners stay clean. Reads requirements.txt only; no install, no network."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXED = (2, 15, 0)
KNOWN_VULNERABLE = {"pyjwt": [(2, 14, 0)]}


def pins():
    found = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(\[[^\]]*\])?==([0-9.]+)", line)
        if match:
            found[match.group(1).lower()] = (match.group(2) or "", tuple(int(x) for x in match.group(3).split(".")))
    return found


class PyJwtPinTests(unittest.TestCase):
    def test_pyjwt_is_pinned_at_or_above_the_fixed_release_with_crypto(self):
        extras, version = pins()["pyjwt"]
        self.assertEqual(extras, "[crypto]")          # ES256 (Apple Music developer token) needs cryptography
        self.assertGreaterEqual(version, FIXED)

    def test_no_known_vulnerable_pins(self):
        found = pins()
        for name, bad in KNOWN_VULNERABLE.items():
            with self.subTest(package=name):
                self.assertNotIn(found[name][1], bad)


if __name__ == "__main__":
    unittest.main()

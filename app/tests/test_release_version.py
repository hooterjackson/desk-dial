"""FW-PUB-004: one public version for the Desk Dial + knob pair.

Packaged manifests record the public version (platformio.ini NANO_FIRMWARE_PUBLIC) and the one string the image
reports ("<public>+<build id>.<binary letter>"); tools/release_nanod_cc5.py records each public release in
firmware/release.json. The rules (tooling.release_version_problems): Desk Dial's ProductVersion is the current release
version, the reported firmware string starts with it and ends with the binary letter, no public version carries an
internal cc id, and each version maps to one SHA-256. No port, no device, no build, no network.
"""
import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import test_cc5_tooling as base

t = base.t

INI = """[env:nanofoc_d]
platform = espressif32
build_flags =
\t-DNANO_FIRMWARE_VERSION=\\"1.0.0-cc5.7\\"
\t-DNANO_FIRMWARE_PUBLIC=\\"2.0.0\\"
"""
INI_NO_PUBLIC = INI.replace('\t-DNANO_FIRMWARE_PUBLIC=\\"2.0.0\\"\n', "")
SHA_F = "93ff0d50" + "0" * 56
SHA_OTHER = "0224d8ca" + "1" * 56
VERSION_TXT = "    StringStruct('FileVersion', '7.3.2.0'),\n    StringStruct('ProductVersion', '{}')])\n"


def manifest(binary="F", sha=SHA_F, ini=INI):
    p = t.PROFILES["cc5.7"].binary_profile(binary)
    record = {"firmwareVersion": p.version, "image": {"file": p.image.name, "sha256": sha},
              "binary": {"name": binary}}
    record.update(t.public_version_fields(p, binary, ini))
    return record


@base.needs_tooling
class ReleaseVersionTests(unittest.TestCase):
    def test_versions_are_public_and_unique(self):
        entry = t.release_entry(manifest(), "2.0.0")
        self.assertEqual(entry["version"], "2.0.0")
        self.assertEqual(entry["firmware"]["reportedVersion"], "2.0.0+cc5.7.F")
        self.assertEqual(entry["firmware"]["manifest"], "manifest-1.0.0-cc5.7-F.json")
        record = t.add_release({}, entry)
        self.assertEqual(t.release_version_problems(record, "2.0.0"), [])

        # ProductVersion must be the release version (today's 7.3.2.0 is not).
        self.assertTrue(t.release_version_problems(record, "7.3.2.0"))
        # The firmware string ends with the binary letter.
        wrong_letter = json.loads(json.dumps(record))
        wrong_letter["releases"][0]["firmware"]["binary"] = "D"
        self.assertTrue(any("binary letter" in x for x in t.release_version_problems(wrong_letter, "2.0.0")))
        # It starts with the public version.
        other_start = json.loads(json.dumps(record))
        other_start["releases"][0]["firmware"]["reportedVersion"] = "1.0.0+cc5.7.F"
        self.assertTrue(any("does not start" in x for x in t.release_version_problems(other_start, "2.0.0")))
        # No user-facing cc5.N string.
        internal = json.loads(json.dumps(record))
        internal["releases"][0]["version"] = internal["current"] = "1.0.0-cc5.7"
        internal["releases"][0]["desktop"]["productVersion"] = "1.0.0-cc5.7"
        self.assertTrue(any("not a public version" in x for x in t.release_version_problems(internal, "1.0.0-cc5.7")))
        # Each version maps to one SHA-256: a changed image under the same version stops; the same image is kept.
        with self.assertRaises(SystemExit):
            t.add_release(record, t.release_entry(manifest(sha=SHA_OTHER), "2.0.0"))
        self.assertEqual(t.add_release(record, entry), record)
        doubled = {"schema": 1, "current": "2.0.0", "releases": [entry, t.release_entry(manifest(sha=SHA_OTHER), "2.0.0")]}
        self.assertTrue(any("maps to 2 images" in x for x in t.release_version_problems(doubled, "2.0.0")))
        # A new public version for a new image is fine; the current one is the newest.
        newer = t.add_release(record, t.release_entry(manifest(sha=SHA_OTHER, ini=INI.replace("2.0.0", "2.0.1")),
                                                      "2.0.1"))
        self.assertEqual([r["version"] for r in newer["releases"]], ["2.0.0", "2.0.1"])
        self.assertEqual(t.release_version_problems(newer, "2.0.1"), [])

    def test_recorded_release_json_follows_the_rules(self):
        if not t.RELEASE_RECORD.is_file():
            self.skipTest("firmware/release.json is not recorded yet (the integration stage writes it)")
        self.assertEqual(t.release_version_problems(t.load_json(t.RELEASE_RECORD), t.desktop_product_version()), [])

    def test_manifest_fields(self):
        self.assertEqual(manifest()["publicVersion"], "2.0.0")
        self.assertEqual(manifest()["reportedVersion"], "2.0.0+cc5.7.F")
        self.assertEqual(manifest("D")["reportedVersion"], "2.0.0+cc5.7.D")
        none = manifest(ini=INI_NO_PUBLIC)
        self.assertEqual((none["publicVersion"], none["reportedVersion"]), (None, None))
        with self.assertRaises(SystemExit):
            t.release_entry(none, "2.0.0")
        # Another profile than the source's internal id reports its own id: no public fields.
        self.assertEqual(t.public_version_fields(t.PROFILES["cc5.6"].binary_profile("D"), "D", INI)["publicVersion"],
                         None)

    def test_packaging_records_the_fields(self):
        source = (t.WORK / "package_nanod_cc5.py").read_text(encoding="utf-8")
        self.assertIn("manifest.update(t.public_version_fields(p, p.binary))", source)

    def test_product_version_is_read_from_the_version_file(self):
        self.assertEqual(t.desktop_product_version(VERSION_TXT.format("2.0.0")), "2.0.0")
        self.assertIsNone(t.desktop_product_version("no version here"))
        self.assertIsNotNone(t.desktop_product_version())    # the real desktop-version.txt has one

    def test_release_script_writes_only_with_write(self):
        import release_nanod_cc5 as script
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            manifest_path = folder / "manifest-1.0.0-cc5.7-F.json"
            manifest_path.write_text(json.dumps(manifest()), encoding="utf-8")
            profile = types.SimpleNamespace(manifest=manifest_path)
            current = types.SimpleNamespace(binary_profile=lambda name: profile)
            record_path = folder / "release.json"
            with mock.patch.object(t, "CURRENT", current), \
                    mock.patch.object(t, "binary_choices", lambda p=None: ("D", "F")), \
                    mock.patch.object(t, "RELEASE_RECORD", record_path), \
                    mock.patch.object(t, "desktop_product_version", lambda text=None: "2.0.0"), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(script.main([]), 0)
                self.assertFalse(record_path.exists())
                self.assertEqual(script.main(["--write"]), 0)
                written = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertEqual(written["current"], "2.0.0")
                self.assertEqual(written["releases"][0]["firmware"]["sha256"], SHA_F)
                # ProductVersion still the old series: refused, nothing written.
                with mock.patch.object(t, "desktop_product_version", lambda text=None: "7.3.2.0"):
                    with self.assertRaises(SystemExit):
                        script.main(["--write"])
                self.assertEqual(json.loads(record_path.read_text(encoding="utf-8")), written)


if __name__ == "__main__":
    unittest.main()

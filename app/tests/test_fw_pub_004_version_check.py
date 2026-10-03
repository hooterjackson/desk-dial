"""FW-PUB-004: the knob reports settings "firmwareVersion" as "<NANO_FIRMWARE_PUBLIC>+<build id>.<binary letter>"
(src/cc_fw_version.h, e.g. 1.0.0+cc5.7.F). check_nanod_cc5.py's inventory check and finalize_nanod_cc5.py's settings
check compare against that string (tooling.reported_firmware_versions, the public version read from platformio.ini),
not against the internal id profile.version. No port, no device, no build."""
import contextlib
import inspect
import io
import unittest
from unittest import mock

import test_cc5_tooling as base

t = base.t

INI = """[env:nanofoc_d]
platform = espressif32
build_flags =
\t; a comment line
\t-DNANO_FIRMWARE_VERSION=\\"1.0.0-cc5.7\\"
\t-DNANO_FIRMWARE_PUBLIC=\\"1.0.0\\"
\t-DOTHER=1
"""
INI_NO_PUBLIC = INI.replace('\t-DNANO_FIRMWARE_PUBLIC=\\"1.0.0\\"\n', "")


@base.needs_tooling
class ReportedVersionTests(unittest.TestCase):
    def setUp(self):
        self.p = t.PROFILES["cc5.7"]

    def test_defines_are_read_without_quotes(self):
        self.assertEqual(t.firmware_version_defines(INI), ("1.0.0", "1.0.0-cc5.7"))
        self.assertEqual(t.firmware_version_defines(INI_NO_PUBLIC), (None, "1.0.0-cc5.7"))

    def test_binary_f_reports_public_build_id_and_letter(self):
        self.assertEqual(t.reported_firmware_versions(self.p, "F", INI), ("1.0.0+cc5.7.F",))
        self.assertEqual(t.reported_firmware_versions(self.p.binary_profile("D"), None, INI), ("1.0.0+cc5.7.D",))

    def test_unknown_binary_accepts_each_ladder_letter(self):
        got = t.reported_firmware_versions(self.p, None, INI)
        self.assertEqual(set(got), {f"1.0.0+cc5.7.{b}" for b in self.p.pipeline_binaries()})
        self.assertNotIn(self.p.version, got)

    def test_internal_id_is_no_longer_accepted(self):
        self.assertNotIn("1.0.0-cc5.7", t.reported_firmware_versions(self.p, "F", INI))

    def test_source_without_public_define_or_other_release_keeps_internal_id(self):
        self.assertEqual(t.reported_firmware_versions(self.p, "F", INI_NO_PUBLIC), ("1.0.0-cc5.7",))
        older = t.PROFILES["cc5.6"]
        self.assertEqual(t.reported_firmware_versions(older, "F", INI), (older.version,))

    def test_firmware_source_ini_matches_the_firmware_format(self):
        public, internal = t.firmware_version_defines()
        if public is None:
            self.skipTest("firmware source without NANO_FIRMWARE_PUBLIC")
        expected = f"{public}+{internal.split('-', 1)[1]}.F"
        profile = next((q for q in t.PROFILES.values() if q.version == internal), None)
        if profile is None:
            self.skipTest("no tooling profile for the source's internal id")
        self.assertEqual(t.reported_firmware_versions(profile, "F"), (expected,))


@base.needs_tooling
class CheckerUsesReportedVersionTests(unittest.TestCase):
    def setUp(self):
        self.module = base.load_script("check_nanod_cc5.py")

    def test_inventory_check_compares_the_reported_version(self):
        source = inspect.getsource(self.module.bridge_checks)
        self.assertIn("reported_firmware_versions(p, binary)", source)
        self.assertNotIn('settings.get("firmwareVersion") == p.version', source)
        self.assertIn('changed == ["firmwareVersion"]', source)          # only firmwareVersion changed still holds

    def test_main_passes_the_installed_binary_to_bridge_checks(self):
        seen = []
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(out))
            for target, name, value in (
                    (t, "require_companion_quit", lambda: False),
                    (t, "find_app_port", lambda *a, **k: "FAKEAPP"),
                    (t, "write_json_evidence", lambda path, data, **k: None),
                    (t, "step_down_coredump", lambda *a, **k: None),
                    (self.module, "RebootWatch", mock.MagicMock()),
                    (self.module.time, "sleep", lambda s: None),
                    (self.module, "bridge_checks", lambda *a, **k: seen.append(a) or {}),
                    (self.module, "raw_checks", lambda *a, **k: None)):
                stack.enter_context(mock.patch.object(target, name, value))
            try:
                self.module.main(["--binary", "F"])
            except SystemExit:
                pass
        self.assertTrue(seen)
        self.assertEqual(seen[0][4], "F")

    def test_finalize_compares_the_reported_version(self):
        source = base.WORK.joinpath("finalize_nanod_cc5.py").read_text(encoding="utf-8")
        self.assertIn('settings_version_ok(before_settings.get("firmwareVersion"), after_settings.get("firmwareVersion"), p)', source)
        self.assertNotIn('after_settings.get("firmwareVersion") == p.version', source)


if __name__ == "__main__":
    unittest.main()

"""TL-BUG-004 (review): when the knob's settings cannot be read, nanod_enter_bootloader_v2.py refuses with a message
that names --unverified-mac and the manual RECOVERY.md steps; with --unverified-mac and exactly one application
port it sends the one touch and records macMatched null and unverified true. A confirmed foreign MAC still refuses
with the flag. Ports, the knob and the touch are fakes: nothing is opened."""
import unittest

import test_cc5_tooling as base
from test_tl_bug_004_bootloader_mac import BootloaderMacTests, FakeSettingsKnob, efuse_hex, other_mac

t = base.t


@base.needs_tooling
class UnverifiedMacTests(BootloaderMacTests):
    def run_flag(self, knob, argv=("--unverified-mac",)):
        self.written, self.touches, self.lists = [], [], 0
        code = self.script.main(list(argv), knob_factory=lambda device: knob,
                                toucher=lambda device: self.touches.append(device) or "touched")
        [report] = self.written
        return code, report

    def test_unreadable_refusal_points_at_the_flag_and_recovery(self):
        for knob in (FakeSettingsKnob(fail=TimeoutError("No settings within 2.0 s")),
                     FakeSettingsKnob(fail=OSError("access denied")),
                     FakeSettingsKnob(None), FakeSettingsKnob("")):
            with self.subTest(knob=knob.serial_number, fail=knob.fail):
                code, report = self.run_flag(knob, argv=())
                self.assertEqual((code, self.touches, report["touchSent"]), (1, [], False))
                self.assertIsNone(report["macMatched"])
                self.assertNotIn("unverified", report)
                self.assertIn("No reset sent", report["error"])
                self.assertIn("--unverified-mac", report["error"])
                self.assertIn("RECOVERY.md section 2", report["error"])

    def test_unverified_flag_sends_one_touch_when_unreadable(self):
        for knob in (FakeSettingsKnob(fail=TimeoutError("No settings within 2.0 s")), FakeSettingsKnob(None)):
            with self.subTest(fail=knob.fail):
                code, report = self.run_flag(knob)
                self.assertEqual(self.touches, ["COMA"])
                self.assertTrue(report["touchSent"])
                self.assertIsNone(report["macMatched"])
                self.assertTrue(report["unverified"])
                self.assertIn("NOT verified", self.out.getvalue())

    def test_unverified_flag_never_overrides_a_confirmed_foreign_mac(self):
        code, report = self.run_flag(FakeSettingsKnob(efuse_hex(other_mac(t.CHIP_MAC))))
        self.assertEqual((code, self.touches, report["touchSent"]), (1, [], False))
        self.assertFalse(report["macMatched"])
        self.assertNotIn("unverified", report)

    def test_unverified_flag_needs_exactly_one_application_port(self):
        self.ports = [base.APP(), base.APP(device="COMB")]
        knob = FakeSettingsKnob(fail=TimeoutError("No settings within 2.0 s"))
        code, report = self.run_flag(knob)
        self.assertEqual((code, self.touches, report["touchSent"]), (1, [], False))
        self.assertEqual(knob.sent, [])

    def test_unverified_flag_still_refuses_a_placeholder_mac(self):
        from unittest import mock
        knob = FakeSettingsKnob(fail=TimeoutError("x"))
        with mock.patch.object(self.script.t, "CHIP_MAC", ""):
            code, report = self.run_flag(knob)
        self.assertEqual((code, self.touches), (1, []))
        self.assertIn("placeholder", report["error"])

    def test_matching_mac_with_flag_is_verified(self):
        code, report = self.run_flag(FakeSettingsKnob(efuse_hex(t.CHIP_MAC)))
        self.assertEqual(self.touches, ["COMA"])
        self.assertTrue(report["macMatched"])
        self.assertNotIn("unverified", report)


del BootloaderMacTests

if __name__ == "__main__":
    unittest.main()

"""TL-BUG-010: a refused nanod_enter_bootloader_v2.py run after the install (Desk Dial still running, both ports
present, no application port: touchSent false, no bootloader found) is not a rollback, so finalize_nanod_cc5.py is
not blocked by it forever. A record with touchSent true, one that found the knob already in the bootloader, one
without touchSent and an unreadable one still refuse. finalize runs on fake evidence in a temporary folder
(test_cc5_tooling.FinalizeFlowBase; no port, no device)."""
import unittest

import test_cc5_tooling as base

t = base.t

LATE = "20260923T073000Z"     # after the fixture's install (FLASH_STARTED 20260923T070000Z)
REFUSED = {"startedUtc": LATE, "touchSent": False, "companionRunning": True, "passed": False,
           "error": "DeskDial.exe is running; quit it first. No reset sent.", "changes": []}


@base.needs_tooling
class RefusedBootEntryTests(base.FinalizeFlowBase):
    def boot_entry(self, data, at_offset=400):
        return self.write(self.diag / f"{t.BOOT_ENTRY.stem}-{LATE}.json", data, self.BASE + at_offset)

    def test_refused_bootloader_entry_after_install_is_not_a_rollback(self):
        refused_runs = {
            "companion running": REFUSED,
            "both ports present": {"startedUtc": LATE, "touchSent": False, "passed": False,
                                   "error": "Application and ROM ports are both present; inspect manually."},
            "no application port": {"startedUtc": LATE, "touchSent": False, "alreadyInBootloader": False,
                                    "passed": False, "error": "no application port"},
        }
        for label, data in refused_runs.items():
            with self.subTest(label):
                self.build()
                path = self.boot_entry(data)
                flash = t.load_json(t.FLASH_CHECKS)
                self.assertEqual(self.module.rollbacks_since_install(t.FLASH_CHECKS, flash), [])
                self.assertEqual(self.module.main([]), 0)
                self.assertEqual(t.load_json(t.CC5_MANIFEST)["installationStatus"], "INSTALLED")
                self.assertIn(path.name, t.load_json(t.INSTALLATION)["bootEntryEvidence"])   # still listed

    def test_a_boot_entry_that_did_something_still_refuses(self):
        counted = {
            "touch sent": {"startedUtc": LATE, "touchSent": True, "passed": True, "romPort": "COMX"},
            "touch sent, no ROM port": {"startedUtc": LATE, "touchSent": True, "passed": False},
            "already in the bootloader": {"startedUtc": LATE, "touchSent": False, "alreadyInBootloader": True,
                                          "romPort": "COMX", "passed": True},
            "no touchSent field": {"startedUtc": LATE},
            "not an object": [1, 2],
            "unreadable": b"{not json",
        }
        for label, data in counted.items():
            with self.subTest(label):
                self.build()
                path = self.boot_entry(data)
                flash = t.load_json(t.FLASH_CHECKS)
                reasons = self.module.rollbacks_since_install(t.FLASH_CHECKS, flash)
                self.assertTrue(any(path.name in r and "ROM bootloader entry" in r for r in reasons), reasons)
                self.assert_refused("a rollback was made or started after the install")

    def test_refused_boot_entry_rule(self):
        refused = self.module.refused_boot_entry
        self.assertTrue(refused(REFUSED))
        self.assertTrue(refused({"touchSent": False, "alreadyInBootloader": False}))
        for record in (None, [], {}, {"touchSent": True}, {"touchSent": 0}, {"touchSent": False, "alreadyInBootloader": True},
                       {"touchSent": False, "romPort": "COMX"}):
            with self.subTest(record=record):
                self.assertFalse(refused(record))


if __name__ == "__main__":
    unittest.main()

"""TL-BUG-006: a rollback that stops after the write (exit 4) must hand the operator the manual commands for ITS
target (its own rollback app0 and backup, the region-by-region verify, the reset last, then --records-only), not
a runbook section written for older releases. Runs rollback_nanod_cc5.main() for every ROLLBACK_TARGETS key
against the fake esptool of test_cc5_tooling (no process, no port)."""
import unittest

import test_cc5_tooling as base

t = base.t


class RollbackExit4ManualBlockTests(base.RollbackFlowTests):
    active_binaries = None   # the real ladders, so every target's --binary is accepted

    def use_target(self, target):
        p = t.ROLLBACK_TARGETS[target]
        argv = ["--to", target]
        if p.pipeline_binaries():
            binary = p.pipeline_binaries()[0]
            argv += ["--binary", binary]
            p = p.binary_profile(binary)
        self.TARGET, self.ARGV, self.profile = target, tuple(argv), p
        p.before_full.write_bytes(self.before)
        return p

    def test_rollback_exit4_message_names_a_runbook_for_the_target(self):
        self.assertTrue(t.ROLLBACK_TARGETS)
        for target in sorted(t.ROLLBACK_TARGETS):
            for results in ({"write": False}, {"verify-app0": False},
                            {"verify-full": False, "verify-app1": False}):
                with self.subTest(target=target, results=list(results)):
                    p = self.use_target(target)
                    start = len(self.out.getvalue())
                    code, report, fake = self.run_rollback(**results)
                    out = self.out.getvalue()[start:]
                    self.assertEqual(code, 4)
                    self.assertEqual(fake.resets(), [])
                    self.assertIn("Do not reset or power-cycle", out)
                    self.assertNotIn("Follow firmware/RECOVERY.md (manual commands)", out)
                    self.assertIn(f"{p.tag} -> {p.from_tag}", out)
                    # Review: the stop rule must exempt step 3, or step 4 (the region verify) is unreachable.
                    header = out[out.index("Manual recovery"):out.index("1. Interpreter")]
                    header = " ".join(header.split())
                    self.assertIn("if step 3 fails, go on to step 4", header)
                    self.assertIn("stop at the first line of step 4 that does not exit 0", header)
                    self.assertNotRegex(header, r"stop at the first line that does not exit 0 and leave the chip "
                                                r"as it is:")
                    block = report["manualRecovery"]
                    write, app0 = block["write"]
                    self.assertIn("write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000", write)
                    for line in (write, app0):
                        self.assertIn(p.rollback_app.name, line)
                        self.assertIn(line, out)
                    self.assertIn("verify_flash 0x10000", app0)
                    self.assertIn("verify_flash 0x0", block["fullVerify"][0])
                    self.assertIn(p.before_full.name, block["fullVerify"][0])
                    # Region by region: every critical region, from pieces of this target's backup, never data.
                    regions = " ".join(block["regionVerify"])
                    for name in ("bootloader", "partition-table", "otadata", "app0", "app1"):
                        self.assertIn(f"region-{name}.bin", regions)
                    for name in ("nvs", "spiffs", "coredump"):
                        self.assertNotIn(f"region-{name}.bin", regions)
                    self.assertTrue(all("--after no_reset_stub" in line
                                        for line in block["write"] + block["fullVerify"] + block["regionVerify"]))
                    self.assertEqual(len(block["reset"]), 1)
                    self.assertIn("--after hard_reset read_mac", block["reset"][0])
                    self.assertLess(out.index(block["regionVerify"][-1]), out.index(block["reset"][0]))
                    records = block["records"][0]
                    self.assertIn(f"--to {target}", records)
                    self.assertTrue(records.endswith("--records-only"))
                    if p.binary:
                        self.assertIn(f"--binary {p.binary}", records)
                    self.assertIn("--port FAKEROM", write)
                    joined = "\n".join(line for lines in block.values() for line in lines)
                    self.assertNotIn("erase", joined)
                    self.assertEqual(self.records, [])

    def test_success_prints_no_manual_block(self):
        code, report, _ = self.run_rollback()
        self.assertEqual(code, 0)
        self.assertNotIn("manualRecovery", report)
        self.assertNotIn("Manual recovery", self.out.getvalue())


def load_tests(loader, tests, pattern):
    """Only this file's tests (the base class's own tests run in test_cc5_tooling.py)."""
    suite = unittest.TestSuite()
    cls = RollbackExit4ManualBlockTests
    suite.addTests(cls(name) for name in vars(cls) if name.startswith("test_"))
    return suite


if __name__ == "__main__":
    unittest.main()

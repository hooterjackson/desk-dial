"""TL-BUG-013: packaging refuses to replace the image of a binary the records show installed (a flash-checks record
with a write) and not rolled back since, unless --replace-installed is passed (then the manifest records it).
Runs build_nanod_cc5.main() and package_nanod_cc5.main() in the temporary tree of test_cc5_tooling's fixture
(fake PlatformIO and git; nothing is built, nothing touches a device)."""
import json
import unittest

import test_cc5_tooling as base

t = base.t


class PackageRefusesInstalledImage(base.BuildAndPackageFixture):
    def package_once(self):
        self.assertEqual(self.build.main([]), 0)
        self.assertEqual(self.module.main([]), 0)
        self.pb = t.CURRENT.binary_profile((t.binary_choices() or (None,))[0])
        return self.pb.image.read_bytes(), self.pb.manifest.read_bytes()

    def record(self, path, **fields):
        path.write_text(json.dumps(fields, indent=2) + "\n", encoding="utf-8")

    def rebuild_with_a_review_fix(self):
        self.image = self.image + b"review fix\0"
        self.assertEqual(self.build.main([]), 0)

    def test_package_refuses_to_replace_an_installed_unfinalized_binary(self):
        image, manifest = self.package_once()
        self.record(self.pb.flash_checks, startedUtc="20260930T120000Z", writeAttempted=True, flashWritten=True,
                    outcome="INSTALLED_VERIFIED_RESET")
        self.rebuild_with_a_review_fix()
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn("--replace-installed", str(caught.exception))
        self.assertIn(self.pb.flash_checks.name, str(caught.exception))
        self.assertEqual((self.pb.image.read_bytes(), self.pb.manifest.read_bytes()), (image, manifest))
        self.assertEqual(list(self.pb.image.parent.glob("*.superseded-*")), [])          # nothing archived either
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), self.active)

    def test_replace_installed_flag_packages_and_records_it(self):
        image, _ = self.package_once()
        self.record(self.pb.flash_checks, startedUtc="20260930T120000Z", writeAttempted=True,
                    outcome="INSTALLED_VERIFIED_RESET")
        self.rebuild_with_a_review_fix()
        self.assertEqual(self.module.main(["--replace-installed"]), 0)
        self.assertNotEqual(self.pb.image.read_bytes(), image)
        replaced = t.load_json(self.pb.manifest)["replacedInstalledImage"]
        self.assertEqual(replaced["previousImageSha256"], t.sha256_bytes(image))
        self.assertTrue(any(self.pb.flash_checks.name in r for r in replaced["reasons"]))

    def test_a_newer_rollback_frees_the_image(self):
        image, _ = self.package_once()
        self.record(self.pb.flash_checks, startedUtc="20260930T120000Z", writeAttempted=True,
                    outcome="INSTALLED_VERIFIED_RESET")
        self.record(self.pb.rollback_report, startedUtc="20260930T130000Z", outcome="ROLLED_BACK_VERIFIED_RESET")
        self.rebuild_with_a_review_fix()
        self.assertEqual(self.module.main([]), 0)
        self.assertNotIn("replacedInstalledImage", t.load_json(self.pb.manifest))

    def test_an_older_rollback_does_not(self):
        self.package_once()
        self.record(self.pb.rollback_report, startedUtc="20260930T110000Z", outcome="ROLLED_BACK_VERIFIED_RESET")
        self.record(self.pb.flash_checks, startedUtc="20260930T120000Z", writeAttempted=True,
                    outcome="INSTALLED_VERIFIED_RESET")
        self.rebuild_with_a_review_fix()
        with self.assertRaises(SystemExit):
            self.module.main([])

    def test_never_written_binary_repackages_freely(self):
        self.package_once()
        self.rebuild_with_a_review_fix()
        self.assertEqual(self.module.main([]), 0)


def load_tests(loader, tests, pattern):
    """Only this file's tests (the fixture's own tests run in test_cc5_tooling.py)."""
    cls = PackageRefusesInstalledImage
    return unittest.TestSuite(cls(name) for name in vars(cls) if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()

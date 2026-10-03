"""TL-BUG-005: build_nanod_cc5.py records the firmware tree it compiles (sourceSnapshot: the source listing's digests,
HEAD, dirty) and package_nanod_cc5.py refuses, writing nothing, when the tree changed since the accepted build or the
record has no snapshot; the manifest records the build's HEAD and dirty state. Runs both scripts in the temporary
tree of test_cc5_tooling's fixture (fake PlatformIO and git; nothing is built, nothing touches a device)."""
import json
import unittest

import test_cc5_tooling as base

t = base.t


class PackageTiedToBuildTests(base.BuildAndPackageFixture):
    def setUp(self):
        super().setUp()
        self.pb = t.CURRENT.binary_profile((t.binary_choices() or (None,))[0])

    def assert_nothing_written(self):
        self.assertFalse(self.pb.image.is_file())
        self.assertFalse(self.pb.source_zip.is_file())
        self.assertFalse(self.pb.manifest.is_file())
        self.assertEqual(t.ACTIVE_MANIFEST.read_bytes(), self.active)

    def test_build_records_the_source_snapshot(self):
        self.git_status = b" M src/main.cpp\n?? .vscode/launch.json\n"
        self.assertEqual(self.build.main([]), 0)
        snapshot = t.load_json(self.pb.build_report)["sourceSnapshot"]
        self.assertEqual(sorted(snapshot["sourceFiles"]), ["platformio.ini", "src/main.cpp"])
        self.assertEqual(snapshot["sourceFiles"]["src/main.cpp"],
                         t.digest_record(t.FIRMWARE_SOURCE / "src" / "main.cpp"))
        self.assertEqual(snapshot["checkoutHead"], "0123456789abcdef0123456789abcdef01234567")
        self.assertTrue(snapshot["dirty"])
        self.assertEqual(snapshot["status"], [" M src/main.cpp"])          # .vscode/ is not a source

    def test_package_refuses_tree_changed_since_build(self):
        self.assertEqual(self.build.main([]), 0)
        (t.FIRMWARE_SOURCE / "src" / "main.cpp").write_text("int main() { return 1; }\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        message = str(caught.exception)
        self.assertIn("src/main.cpp (modified)", message)
        self.assertIn("Nothing was written", message)
        self.assert_nothing_written()

    def test_an_added_or_removed_source_refuses_too(self):
        self.assertEqual(self.build.main([]), 0)
        original = self.fake_git

        def git(command, creationflags=0):
            if tuple(command[5:]) == self.LS_FILES:
                return b"src/main.cpp\0"                                   # platformio.ini gone from the listing
            return original(command, creationflags)
        self.patch(self.module, "subprocess", base.SimpleNamespace(check_output=git, CREATE_NO_WINDOW=0))
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn("platformio.ini (removed)", str(caught.exception))
        self.assert_nothing_written()

    def test_a_record_without_a_snapshot_refuses(self):
        self.assertEqual(self.build.main([]), 0)
        record = t.load_json(self.pb.build_report)
        del record["sourceSnapshot"]
        self.pb.build_report.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.module.main([])
        self.assertIn("sourceSnapshot", str(caught.exception))
        self.assert_nothing_written()

    def test_unchanged_tree_packages_with_the_build_head_and_dirty_state(self):
        self.git_status = b" M src/main.cpp\n"
        self.assertEqual(self.build.main([]), 0)
        self.git_status = b""
        self.assertEqual(self.module.main([]), 0)
        manifest = t.load_json(self.pb.manifest)
        self.assertEqual(manifest["checkoutHead"], "0123456789abcdef0123456789abcdef01234567")
        self.assertIs(manifest["dirty"], True)                              # as the build saw the tree
        self.assertEqual(manifest["sourceFiles"], t.load_json(self.pb.build_report)["sourceSnapshot"]["sourceFiles"])

    def test_a_git_failure_at_build_start_rejects_the_build(self):
        def broken(command, creationflags=0):
            raise OSError("git is not installed")
        self.patch(self.build, "subprocess", base.SimpleNamespace(run=self.fake_platformio, check_output=broken,
                                                                  CalledProcessError=OSError, STDOUT="STDOUT",
                                                                  CREATE_NO_WINDOW=0))
        self.assertEqual(self.build.main([]), 1)
        record = t.load_json(self.pb.build_report)
        self.assertFalse(record["accepted"])
        self.assertTrue(any("firmware sources could not be recorded" in p for p in record["problems"]))


if __name__ == "__main__":
    unittest.main()

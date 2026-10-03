"""TL-BUG-003: build_nanod_cc5.py drops every PLATFORMIO_* variable of the caller (PlatformIO 6 reads
PLATFORMIO_BUILD_SRC_FLAGS, _BUILD_SRC_FILTER, _EXTRA_SCRIPTS, _BUILD_CACHE_DIR and more), keeps only the pinned
PLATFORMIO_CORE_DIR plus its own BUILD_FLAGS/BUILD_DIR, and records the dropped names (never their values).
Runs build_nanod_cc5.main() against the fake PlatformIO of test_cc5_tooling (no process, no port)."""
import os
import unittest
from unittest import mock

import test_cc5_tooling as base

t = base.t

# Every PlatformIO 6 sysenvvar that shapes a build, plus the old names and a setting.
PIO_OVERRIDES = {name: "-DCC_LCD_PERIOD_MS=33" for name in (
    "PLATFORMIO_BUILD_FLAGS", "PLATFORMIO_SRC_BUILD_FLAGS", "PLATFORMIO_BUILD_UNFLAGS", "PLATFORMIO_BUILD_DIR",
    "PLATFORMIO_BUILD_SRC_FLAGS", "PLATFORMIO_BUILD_SRC_FILTER", "PLATFORMIO_EXTRA_SCRIPTS",
    "PLATFORMIO_BUILD_CACHE_DIR", "PLATFORMIO_LIB_EXTRA_DIRS", "PLATFORMIO_LIBDEPS_DIR", "PLATFORMIO_SRC_DIR",
    "PLATFORMIO_INCLUDE_DIR", "PLATFORMIO_LIB_DIR", "PLATFORMIO_BOARDS_DIR", "PLATFORMIO_WORKSPACE_DIR",
    "PLATFORMIO_PLATFORMS_DIR", "PLATFORMIO_PACKAGES_DIR", "PLATFORMIO_SETTING_ENABLE_TELEMETRY")}


@base.needs_tooling
class PioEnvironmentFilterTests(base.BuildAndPackageFixture):
    def caller_env(self):
        return {**PIO_OVERRIDES, "PLATFORMIO_CORE_DIR": "caller-core", "UNRELATED_VARIABLE": "kept"}

    def test_build_environment_drops_every_platformio_override(self):
        for name in sorted(t.CURRENT.pipeline_binaries() or [None]):
            p = t.CURRENT.binary_profile(name)
            with self.subTest(binary=name), mock.patch.dict(os.environ, self.caller_env()):
                env = self.build.build_environment(p)
                pio = {k for k in env if k.upper().startswith("PLATFORMIO_")}
                own = {"PLATFORMIO_CORE_DIR"} | ({"PLATFORMIO_BUILD_FLAGS"} if p.build_flags else set()) \
                    | ({"PLATFORMIO_BUILD_DIR"} if p.build_dir is not None else set())
                self.assertEqual(pio, own)
                self.assertEqual(env["PLATFORMIO_CORE_DIR"], str(t.PIO_CORE))
                if p.build_flags:
                    self.assertEqual(env["PLATFORMIO_BUILD_FLAGS"], " ".join(p.build_flags))
                if p.build_dir is not None:
                    self.assertEqual(env["PLATFORMIO_BUILD_DIR"], str(p.build_dir))
                self.assertEqual(env["UNRELATED_VARIABLE"], "kept")
                self.assertEqual(self.build.dropped_variables(),
                                 sorted(PIO_OVERRIDES))          # names only; the core dir is replaced, not dropped

    def test_the_build_record_and_log_name_the_dropped_variables(self):
        with mock.patch.dict(os.environ, self.caller_env()):
            self.assertEqual(self.build.main([]), 0)
        [env] = self.envs
        for name in PIO_OVERRIDES:
            if name not in ("PLATFORMIO_BUILD_FLAGS", "PLATFORMIO_BUILD_DIR"):
                self.assertNotIn(name, env)
        self.assertNotIn("-DCC_LCD_PERIOD_MS=33", env.get("PLATFORMIO_BUILD_FLAGS", ""))
        record = t.load_json(self.p.build_report)
        self.assertEqual(record["droppedEnvironment"], sorted(PIO_OVERRIDES))
        self.assertTrue(record["accepted"])
        log = self.p.build_log.read_text(encoding="utf-8")
        self.assertIn("PLATFORMIO_BUILD_SRC_FLAGS", log)
        self.assertNotIn("-DCC_LCD_PERIOD_MS=33", log)                          # values are never logged

    def test_a_clean_environment_records_an_empty_list(self):
        clean = {k: v for k, v in os.environ.items() if not k.upper().startswith("PLATFORMIO_")}
        with mock.patch.dict(os.environ, clean, clear=True):
            self.assertEqual(self.build.main([]), 0)
        self.assertEqual(t.load_json(self.p.build_report)["droppedEnvironment"], [])


if __name__ == "__main__":
    unittest.main()

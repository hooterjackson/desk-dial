"""HN-BUG-003: the harness evidence gate (tooling.harness_conf_problems, recorded by build_nanod_cc5.py) fails when
the harness renderer is older than a firmware unit the harness compiles (CMakeLists firmware_shared sources, their
headers, src/fonts), or when the build's CMakeCache NANOD_LV_CONF_DIR points at another lv_conf.h. Temporary files
only: no build, no port."""
import contextlib
import os
from pathlib import Path
import tempfile
import time
import unittest

import test_cc5_tooling as base

t = base.t

CONF = "#define LV_COLOR_DEPTH 16\n#define LV_USE_TFT_ESPI {}\n#define LV_OBJ_STYLE_CACHE 1\n"
CMAKELISTS = """add_library(firmware_shared OBJECT
  "${NANOD_FIRMWARE_SRC}/cc_display.cpp"
  "${NANOD_FIRMWARE_SRC}/cc_frame_parse.cpp")
file(GLOB CC_FONTS "${NANOD_FIRMWARE_SRC}/fonts/cc_font_*.c")
add_library(jpeg_glue OBJECT "${NANOD_FIRMWARE_SRC}/cc_jpeg.cpp" ${TJPGD_SHIM_SOURCES})
"""


def age(path, seconds):
    then = time.time() - seconds
    os.utime(path, (then, then))


@base.needs_tooling
class HarnessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.firmware = root / "fw"
        (self.firmware / "include").mkdir(parents=True)
        (self.firmware / "src" / "fonts").mkdir(parents=True)
        self.harness = root / "lcd-preview"
        (self.harness / "build" / "Release").mkdir(parents=True)
        self.fw_conf = self.firmware / "include" / "lv_conf.h"
        self.fw_conf.write_text(CONF.format(1), encoding="utf-8")
        self.host_conf = self.harness / "lv_conf.h"
        self.host_conf.write_text(CONF.format(0), encoding="utf-8")
        (self.harness / "CMakeLists.txt").write_text(CMAKELISTS, encoding="utf-8")
        self.sources = [self.firmware / "src" / name for name in
                        ("cc_display.cpp", "cc_display.h", "cc_frame_parse.cpp", "cc_jpeg.cpp", "fonts/cc_font_14.c",
                         "cc_haptic.cpp")]
        for path in self.sources:
            path.write_text("//\n", encoding="utf-8")
            age(path, 600)
        age(self.fw_conf, 600)
        age(self.host_conf, 300)
        self.exe = self.harness / "build" / "Release" / "lcd-preview.exe"
        self.exe.write_bytes(b"MZ")
        age(self.exe, 120)
        self.cache = self.harness / "build" / "CMakeCache.txt"
        self.write_cache(self.harness)

    def write_cache(self, conf_dir):
        self.cache.write_text(f"CMAKE_BUILD_TYPE:STRING=Release\nNANOD_LV_CONF_DIR:PATH={Path(conf_dir).as_posix()}\n",
                              encoding="utf-8")

    def check(self):
        return t.harness_conf_problems(self.fw_conf, self.host_conf, self.exe)

    def test_a_fresh_harness_passes(self):
        record, problems = self.check()
        self.assertEqual((problems, record["passed"]), ([], True))
        self.assertEqual(record["newerSources"], [])

    def test_harness_conf_fails_when_src_newer_or_cache_points_elsewhere(self):
        # (a) a firmware unit the harness compiles changed after the last build.py run
        for name in ("cc_display.cpp", "cc_display.h", "cc_jpeg.cpp", "fonts/cc_font_14.c"):
            with self.subTest(name=name):
                path = self.firmware / "src" / name
                age(path, 10)
                record, problems = self.check()
                self.assertFalse(record["passed"])
                self.assertEqual(record["newerSources"], [name])
                self.assertEqual(len(problems), 1)
                self.assertIn("older than firmware sources it compiles", problems[0])
                self.assertIn("run harness/build.py", problems[0])
                age(path, 600)
        # a unit the harness does not compile does not count
        age(self.firmware / "src" / "cc_haptic.cpp", 10)
        self.assertEqual(self.check()[1], [])
        # (b) the build's cache compiles a scratch lv_conf.h
        scratch = self.harness.parent / "scratch-conf"
        scratch.mkdir()
        self.write_cache(scratch)
        record, problems = self.check()
        self.assertFalse(record["passed"])
        self.assertEqual(len(problems), 1)
        self.assertIn("NANOD_LV_CONF_DIR", problems[0])
        self.assertEqual(Path(record["lvConfDir"]), scratch)
        self.write_cache(self.harness)
        self.assertEqual(self.check()[1], [])

    def test_no_cache_and_no_cmakelists_add_nothing(self):
        self.cache.unlink()
        (self.harness / "CMakeLists.txt").unlink()
        age(self.firmware / "src" / "cc_display.cpp", 10)
        self.assertEqual(self.check()[1], [])

    def test_the_real_cmakelists_lists_the_display_sources(self):
        names = {p.name for p in t.harness_firmware_units(t.WORK.parent / "harness" / "CMakeLists.txt",
                                                          t.FIRMWARE_SOURCE / "src")}
        if not names:
            self.skipTest("harness or the firmware tree is not present")
        for name in ("cc_display.cpp", "cc_frame_parse.cpp", "cc_icons.cpp", "cc_crumbs.cpp"):
            self.assertIn(name, names)
        self.assertTrue(any(name.startswith("cc_font_") for name in names))


if __name__ == "__main__":
    unittest.main()

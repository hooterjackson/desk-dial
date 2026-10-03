"""HN-BUG-003 (review): the harness evidence gate also watches the header-only code the compiled units reach
through #include "..." lines, followed transitively (cc_presentation.h, cc_lcd_logic.h, cc_sleep.h,
fonts/cc_fonts.h, cc_haptic_fx.h). Temporary files only: no build, no port."""
from pathlib import Path
import unittest

import test_cc5_tooling as base
from test_hn_bug_003_harness_evidence import HarnessEvidenceTests, age

t = base.t

HEADERS = {
    "cc_display.h": '#pragma once\n#include "cc_presentation.h"\n#include "cc_lcd_logic.h"\n#include <lvgl.h>\n',
    "cc_display.cpp": '#include "cc_display.h"\n#include "fonts/cc_fonts.h"\n#include "lvgl.h"\n',
    "cc_frame_parse.cpp": '#include "cc_frame_parse.h"\n  #  include "cc_haptic_fx.h"\n',
    "cc_frame_parse.h": '#pragma once\n#include "cc_presentation.h"\n',
    "cc_presentation.h": '#pragma once\n// #include "not_real.h" is not a line of its own\n',
    "cc_lcd_logic.h": '#pragma once\n#include "cc_sleep.h"\n',
    "cc_sleep.h": '#pragma once\n#include "cc_lcd_logic.h"\n',
    "fonts/cc_fonts.h": '#pragma once\n',
    "cc_haptic_fx.h": '#pragma once\n',
    "cc_unrelated.h": '#pragma once\n',
}


@base.needs_tooling
class TransitiveHeaderTests(HarnessEvidenceTests):
    def setUp(self):
        super().setUp()
        for name, text in HEADERS.items():
            path = self.firmware / "src" / name
            path.write_text(text, encoding="utf-8")
            age(path, 600)

    def test_units_follow_local_includes_transitively(self):
        units = t.harness_firmware_units(self.harness / "CMakeLists.txt", self.firmware / "src")
        names = [p.relative_to(self.firmware / "src").as_posix() for p in units]
        for name in ("cc_presentation.h", "cc_lcd_logic.h", "cc_sleep.h", "fonts/cc_fonts.h", "cc_haptic_fx.h"):
            self.assertIn(name, names)
        self.assertNotIn("cc_unrelated.h", names)
        self.assertEqual(len(names), len(set(names)))  # the cc_sleep.h <-> cc_lcd_logic.h cycle ends

    def test_gate_fails_when_only_an_included_header_is_newer(self):
        self.assertEqual(self.check()[1], [])
        for name in ("cc_presentation.h", "cc_lcd_logic.h", "cc_sleep.h", "fonts/cc_fonts.h", "cc_haptic_fx.h"):
            with self.subTest(name=name):
                path = self.firmware / "src" / name
                age(path, 10)
                record, problems = self.check()
                self.assertFalse(record["passed"])
                self.assertEqual(record["newerSources"], [name])
                self.assertIn("older than firmware sources it compiles", problems[0])
                age(path, 600)
        age(self.firmware / "src" / "cc_unrelated.h", 10)
        self.assertEqual(self.check()[1], [])

    def test_the_real_tree_reaches_the_header_only_code(self):
        names = {p.name for p in t.harness_firmware_units(t.WORK.parent / "harness" / "CMakeLists.txt",
                                                          t.FIRMWARE_SOURCE / "src")}
        if not names:
            self.skipTest("harness or the firmware tree is not present")
        for name in ("cc_presentation.h", "cc_lcd_logic.h", "cc_sleep.h", "cc_fonts.h", "cc_haptic_fx.h"):
            self.assertIn(name, names)


del HarnessEvidenceTests

if __name__ == "__main__":
    unittest.main()

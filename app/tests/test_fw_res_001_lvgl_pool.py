"""FW-RES-001: the tooling's LVGL pool size follows include/lv_conf.h (80 KB), the pre-cc5.4 diag gate keeps
the 64 KB those releases ran, and the build-only heap projection still clears its gate with the +16 KB .bss."""
from pathlib import Path
import re
import sys
import unittest

WORK = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(WORK))

import nanod_cc5_tooling as t  # noqa: E402

FIRMWARE_CONF = WORK.parent / "firmware" / "include" / "lv_conf.h"


class LvglPoolTests(unittest.TestCase):
    def test_pool_constant_is_80_kb(self):
        self.assertEqual(t.LVGL_HEAP_BYTES, 80 * 1024)
        self.assertEqual(t.PRE_V5_LVGL_HEAP_BYTES, 64 * 1024)

    @unittest.skipUnless(FIRMWARE_CONF.is_file(), "firmware checkout not present")
    def test_pool_constant_matches_firmware_lv_conf(self):
        code = FIRMWARE_CONF.read_text(encoding="utf-8", errors="replace")
        size = re.search(r"^\s*#define\s+LV_MEM_SIZE\s+\((\d+)\s*\*\s*1024U?\)", code, re.M)
        self.assertIsNotNone(size)
        self.assertEqual(int(size.group(1)) * 1024, t.LVGL_HEAP_BYTES)

    def test_pre_v5_fraction_gate_keeps_64_kb(self):
        good = {"lvglFree": 40000, "lvglMinFree": 16384, "heapMinFree": 90000, "stackLcd": 1025,
                "stackCom": 3000, "stackHmi": 2048, "stackFoc": 5000}
        self.assertTrue(t.diag_margins(good)["passed"])                         # 25 % of 64 KB
        self.assertFalse(t.diag_margins({**good, "lvglMinFree": 16383})["passed"])

    def test_v5_profile_gate_is_absolute(self):
        profiles = [x for x in t.PROFILES.values() if getattr(x, "lvgl_min_free", None)]
        self.assertTrue(profiles)
        p = profiles[-1]
        good = {"lvglFree": 60000, "lvglMinFree": 30 * 1024, "heapMinFree": 89396, "stackLcd": 2000,
                "stackCom": 3000, "stackHmi": 2048, "stackFoc": 5000, "artAsync": False}
        check = t.diag_margins(good, profile=p)["checks"]["lvglMinFree"]
        self.assertEqual(check["requiredBytes"], 30 * 1024)
        self.assertTrue(check["passed"])
        # The measured cc5.7 F heap minimum less the 16 KB of new .bss still clears the 40 KB heap gate.
        self.assertGreaterEqual(89396 - 16 * 1024, t.V5_HEAP_MIN_FREE_BYTES)

    def test_heap_projection_absorbs_the_extra_16_kb(self):
        # Largest ramUsedBytes recorded by the cc5.x builds (218,860 B) plus the pool growth.
        for dma in (True, False):
            projection = t.heap_projection(218860 + 16 * 1024, dma=dma)
            self.assertTrue(projection["passed"], projection)
            self.assertEqual(projection["ramDeltaVsCc53"], 218860 + 16384 - t.CC53_RAM_USED_BYTES)


if __name__ == "__main__":
    unittest.main()

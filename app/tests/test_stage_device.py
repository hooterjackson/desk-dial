"""The real D3D11 + DirectComposition device, headless (DESKTOP_STAGE §4.2, §4.5, §6.6 H6; G1-1,
G1-7, G1-8): a device **without a target**, so nothing is shown. Skipped where no device can be
created."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DEV = None
_ERR = None
if sys.platform == "win32":
    try:
        from control_center.stage import win32 as W  # noqa: E402
        from control_center.stage.device import NativeDevice  # noqa: E402
    except Exception as exc:  # pragma: no cover
        _ERR = repr(exc)
else:  # pragma: no cover
    _ERR = "Windows only"


def setUpModule():
    global _DEV, _ERR
    if _ERR is None:
        try:
            mon = W.primary_monitor()
            _DEV = NativeDevice(mon["hmonitor"] if mon else None)
        except Exception as exc:
            _ERR = repr(exc)


def tearDownModule():
    if _DEV is not None:
        _DEV.teardown()


class NativeDeviceTests(unittest.TestCase):
    def setUp(self):
        if _DEV is None:
            self.skipTest(f"no stage device: {_ERR}")
        self.dev = _DEV

    def test_time_frequency_is_qpf(self):
        """G1-8: begin times in timeFrequency ticks, which must equal QPF here."""
        self.assertTrue(self.dev.info["timeFrequency_equals_qpf"], self.dev.info)
        self.assertEqual(self.dev.freq, W.qpf())

    def test_h6_slot_matrix_and_setclip_discriminator(self):
        from control_center.stage import selftest
        ok, res, disc, disc_ok = selftest.slot_matrix(self.dev)
        self.assertTrue(disc_ok, res)
        self.assertTrue(ok, {k: v for k, v in res.items() if v not in ("0x00000000", "void")})
        from control_center.stage import com
        covered = {k.split("(")[0] for k in res}
        hot = {k for k, v in com.SLOTS.items() if v[1] == com.PY} - {"Unknown.AddRef"}
        self.assertEqual(hot - covered, set())                   # every GIL-keeping slot proven S_OK

    def test_upload_readback(self):
        import random
        rnd = random.Random(11)
        for w, h in ((1, 1), (37, 21), (300, 7)):
            data = bytes(rnd.randrange(256) for _ in range(w * h * 4))
            s = self.dev.create_surface(w, h, False, "t")
            try:
                self.assertIs(self.dev.upload(s, w, h, data, "t", verify=True), True)
            finally:
                self.dev.release(s)
        with self.assertRaises(ValueError):
            self.dev.upload(1, 2, 2, b"\0" * 3)

    def test_probe_scene_builds_turns_and_releases(self):
        from control_center.stage import clock as CK
        from control_center.stage.bench import _Holder
        from control_center.stage.engine import SceneContext, StageCore
        from control_center.stage.layout import StageLayout
        from control_center.stage.probe_scene import ProbeScene, probe_payload
        from control_center.stage.tree import Tree
        dev = self.dev
        dev.animation_fns()                                       # the one probe object per device
        alive0 = dev.alive()
        clock = CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc)
        core = StageCore(dev, clock)
        tree = Tree(dev)
        root = tree.root()
        container = tree.visual("scene")
        tree.add(root, container)
        payload = probe_payload(count=21, index=10)
        holder = _Holder(dev)
        ctx = SceneContext(holder, core, tree, StageLayout((0, 0, 2560, 1440)), "explorer", payload)
        scene = ProbeScene(ctx, payload)
        scene.build(payload, container)
        b = core.batch()
        scene.open(b, payload)
        b.commit()
        t1, _fc = core.t1()
        self.assertGreaterEqual(t1 - clock.now(), 0.0015 * clock.freq - 1)
        for step in (1, 1, -1, 1, -1, -1):
            b = core.batch()
            self.assertGreater(scene.turn(b, scene.focus + step), 0)
            b.commit()
        self.assertEqual(scene.turns, 6)
        tree.release_all()
        scene.release()
        holder.solids.release()
        self.assertEqual(dev.alive(), alive0)
        self.assertTrue(dev.check_device_state())

    def test_s1_s2_upload_counters_flush_and_prime(self):
        """The 2026-09-26 frame-drop fixes on the native device (no target, nothing shown): uploads
        are counted until a Commit carries them; that Commit's time is kept (the upload queue's
        pacing, the open's t1); ``flush`` is the context's Flush; ``prime`` is one upload Commit."""
        import time
        dev = self.dev
        dev.commit()
        self.assertEqual(dev.uploads_pending, 0)
        s = dev.create_surface(16, 16, True, "t")
        try:
            dev.upload(s, 16, 16, b"\x10" * (16 * 16 * 4), "t")
            self.assertEqual((dev.uploads_pending, dev.upload_bytes_pending), (1, 16 * 16 * 4))
            dev.flush()
            before = dev.upload_commits
            t = time.perf_counter()
            dev.commit()
            self.assertEqual((dev.uploads_pending, dev.upload_commits), (0, before + 1))
            self.assertGreaterEqual(dev.last_upload_commit, t)
            dev.commit()                                           # a Commit without uploads leaves it
            self.assertEqual(dev.upload_commits, before + 1)
        finally:
            dev.release(s)
        alive = dev.alive()
        dev.prime()
        self.assertEqual((dev.alive(), dev.upload_commits, dev.uploads_pending), (alive, before + 2, 0))

    def test_statistics_exports_keep_the_gil(self):
        """G1-1: the three statistics reads are PYFUNCTYPE (they hold the GIL, never wait)."""
        import ctypes as C
        for f in (W.DCompositionGetFrameId_py, W.DCompositionGetStatistics_py, W.DCompositionGetTargetStatistics_py):
            self.assertIsNotNone(f)
            self.assertTrue(f._flags_ & C._FUNCFLAG_PYTHONAPI)
        from control_center.stage import com
        self.assertEqual(com.SLOTS["Device.GetFrameStatistics"][1], com.PY)
        self.assertEqual(com.SLOTS["Device.Commit"][1], com.WF)


if __name__ == "__main__":
    unittest.main()

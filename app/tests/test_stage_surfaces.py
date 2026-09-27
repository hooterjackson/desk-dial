"""Prepared surfaces, blur recipes and the capture worker (DESKTOP_STAGE §0.7, §2.6, §4.5, §12;
G1-9). Headless: synthetic images only, the screen is never read."""
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from control_center import carousel_render as CR  # noqa: E402
from control_center.stage import blur as B  # noqa: E402
from control_center.stage import capture as CA  # noqa: E402
from control_center.stage import fake as F  # noqa: E402
from control_center.stage import surfaces as S  # noqa: E402


class BytesTests(unittest.TestCase):
    def test_sprite_bytes_are_premultiplied_bgra(self):
        img = Image.new("RGBA", (1, 1), (200, 100, 50, 128))
        w, h, data = S.sprite_bytes(img)
        self.assertEqual((w, h), (1, 1))
        b, g, r, a = data
        self.assertEqual(a, 128)
        self.assertEqual((r, g, b), (round(200 * 128 / 255), round(100 * 128 / 255), round(50 * 128 / 255)))

    def test_opaque_bytes_alpha_255(self):
        w, h, data = S.opaque_bytes(Image.new("RGB", (3, 2), (10, 20, 30)))
        self.assertEqual(len(data), 3 * 2 * 4)
        self.assertEqual(list(data[:4]), [30, 20, 10, 255])


class UploadQueueTests(unittest.TestCase):
    def test_budget_priority_and_newest_wins(self):
        dev = F.FakeDevice()
        t = [0.0]

        def clock():
            t[0] += 0.001            # every clock read = 1 ms later: ~one upload per ms
            return t[0]
        q = S.UploadQueue(dev, budget_s=0.004, clock=clock)
        done = []
        for i in range(8):
            q.put(("k", i), 2, 2, b"\0" * 16, priority=8 - i, done=lambda s, k: done.append(k))
        q.put(("k", 0), 2, 2, b"\1" * 16, priority=100, done=lambda s, k: done.append(("new", k)))
        n = q.run()
        self.assertGreaterEqual(n, 1)
        self.assertLess(n, 8)
        self.assertEqual(done, [])                                   # S1: handed over only once a frame old
        self.assertEqual(dev.upload_commits, 1)                      # the wake's own upload Commit
        t[0] += 0.010
        rest = q.run(budget_s=10.0)                                  # the first wake's surfaces ripen first
        self.assertEqual(done[0], ("k", 7))                          # lowest priority value first
        self.assertEqual(n + rest, 8)
        t[0] += 0.010
        self.assertEqual(q.ripen()[-1], ("k", 0))
        self.assertEqual(done[-1], ("new", ("k", 0)))
        self.assertEqual(len(q), 0)
        self.assertFalse(q.busy())

    def test_first_item_always_goes(self):
        dev = F.FakeDevice()
        q = S.UploadQueue(dev, budget_s=0.0)
        q.put("a", 1, 1, b"\0" * 4)
        q.put("b", 1, 1, b"\0" * 4)
        self.assertEqual(q.run(), 1)

    def test_s1_flush_commit_ripen_and_the_byte_budget(self):
        """S1 (2026-09-26): each upload is flushed, the wake commits its uploads at once (a Commit
        that carries content only), at most 2.5 MB per wake (the first item always goes), and a
        surface reaches ``done`` and ``landed`` only ``READY_S`` after that Commit."""
        clk = F.FakeClock()
        dev = F.FakeDevice(clk)
        q = S.UploadQueue(dev)
        got = []
        big = 680 * 680 * 4                                          # 1.85 MB each
        for i in range(3):
            q.put(("art", i), 680, 680, b"\0" * big, done=lambda s, k: got.append((k, s)))
        self.assertEqual(q.run(), 1)                                 # 2 x 1.85 MB > 2.5 MB: one this wake
        self.assertEqual((dev.flushes, dev.upload_commits, dev.uploads_pending), (1, 1, 0))
        self.assertEqual((got, q.landed), ([], []))
        self.assertEqual(q.next_wake_s(), 0.0)                       # content waits and nothing paces it here
        clk.advance(S.READY_S)
        self.assertEqual(q.run(), 1)
        self.assertEqual([k for k, _s in got], [("art", 0)])
        self.assertEqual(q.landed, [("art", 0)])
        self.assertTrue(dev.obj(got[0][1])["kind"] == "surface")

    def test_s1_pacing_after_the_devices_last_upload_commit(self):
        """Upload wakes are ``gap_s`` apart (an upload-carrying Commit sooner than two frames after
        the previous one blocks on the native device): none of the fake's Commits would wait."""
        clk = F.FakeClock()
        dev = F.FakeDevice(clk)
        q = S.UploadQueue(dev, gap_s=2 / 240 + 0.001)
        for i in range(4):
            q.put(("row", i), 1120, 176, b"\0" * (1120 * 176 * 4))  # 0.79 MB each: 3 per wake
        self.assertEqual(q.run(), 3)
        self.assertFalse(q.due())
        self.assertAlmostEqual(q.next_wake_s(), S.READY_S)          # the ripening comes first
        clk.advance(S.READY_S)
        self.assertEqual(q.run(), 0)                                 # ripened, but not paced yet
        self.assertEqual(len(q.landed), 3)
        self.assertAlmostEqual(q.next_wake_s(), 2 / 240 + 0.001 - S.READY_S, places=6)
        clk.advance(q.next_wake_s())
        self.assertEqual(q.run(), 1)
        self.assertEqual(dev.throttled, [])

    def test_s1_a_key_on_its_way_counts_as_resident_for_the_planners(self):
        """While an upload waits for its paced wake or ripens, the scenes' LRU view says it is there,
        so no art worker renders it again (``MusicLRU.__contains__``)."""
        from control_center.stage.scenes.common import MusicLRU
        clk = F.FakeClock()
        dev = F.FakeDevice(clk)
        q = S.UploadQueue(dev)
        lru = MusicLRU(S.SurfaceLRU(dev), dev, None, q)
        key = ("art", "k", "card", 340)
        self.assertNotIn(key, lru)
        q.put(key, 2, 2, b"\0" * 16, done=lambda s, k: lru.put(k, s, 16))
        self.assertTrue(q.in_flight(key))
        self.assertIn(key, lru)                                      # waiting for its upload
        q.run()
        self.assertIn(key, lru)                                      # ripening
        self.assertIsNone(lru.get(key))                              # ... but nothing can bind it yet
        clk.advance(S.READY_S)
        q.ripen()
        self.assertFalse(q.in_flight(key))
        self.assertIsNotNone(lru.get(key))
        self.assertIn(key, lru)

    def test_s1_a_key_stays_in_flight_while_its_upload_and_commit_run(self):
        """Review nit (S1, 2026-09-26): an item left ``items`` when its upload started but joined the
        ripening keys only after the wake's Commit, so for those few ms an art-worker planner
        (``MusicLRU.__contains__``) saw the key as neither waiting nor resident and could render and
        queue it again. Now it is counted as uploading before it leaves ``items``."""
        from control_center.stage.scenes.common import MusicLRU
        clk = F.FakeClock()
        dev = F.FakeDevice(clk)
        q = S.UploadQueue(dev)
        lru = MusicLRU(S.SurfaceLRU(dev), dev, None, q)
        keys = [("art", "k%d" % i, "card", 340) for i in range(3)]
        seen = []
        orig_upload, orig_flush, orig_commit = dev.upload, dev.flush, dev.commit

        def look(what):
            seen.append((what, [q.in_flight(k) for k in keys], [k in lru for k in keys]))

        def upload(surface, *a, **k):
            look("upload")
            return orig_upload(surface, *a, **k)

        def flush(*a, **k):
            look("flush")
            return orig_flush(*a, **k)

        def commit(*a, **k):
            look("commit")
            return orig_commit(*a, **k)
        dev.upload, dev.flush, dev.commit = upload, flush, commit
        for key in keys:
            q.put(key, 2, 2, b"\0" * 16, done=lambda s, k: lru.put(k, s, 16))
        self.assertEqual(q.run(), 3)
        self.assertEqual([w for w, _f, _c in seen], ["upload", "flush"] * 3 + ["commit"])
        for what, flight, contained in seen:
            self.assertEqual(flight, [True] * 3, what)
            self.assertEqual(contained, [True] * 3, what)
        self.assertEqual(q._uploading, {})                            # nothing left counted once committed
        self.assertTrue(all(q.in_flight(k) for k in keys))           # ripening
        clk.advance(S.READY_S)
        q.ripen()
        self.assertFalse(any(q.in_flight(k) for k in keys))
        self.assertTrue(all(k in lru for k in keys))

    def test_s1_a_failed_upload_leaves_nothing_counted(self):
        dev = F.FakeDevice()
        q = S.UploadQueue(dev)

        def broken(*a, **k):
            raise OSError("device lost")
        dev.upload = broken
        q.put("a", 2, 2, b"\0" * 16)
        with self.assertRaises(OSError):
            q.run()
        self.assertEqual((q._uploading, q._aging_keys), ({}, {}))
        self.assertFalse(q.in_flight("a"))

    def test_ticks_land_at_once_without_a_surface(self):
        dev = F.FakeDevice()
        q = S.UploadQueue(dev, gap_s=1.0)
        seen = []
        q.put(("tick", "o", 1), 1, 1, b"\0" * 4, tick=True, done=lambda s, k: seen.append((s, k)))
        self.assertEqual(q.next_wake_s(), 0.0)
        self.assertFalse(q.due())                                    # no content to upload
        self.assertEqual(q.ripen(), [("tick", "o", 1)])
        self.assertEqual(seen, [(None, ("tick", "o", 1))])
        self.assertEqual(dev.calls_named("Device.CreateSurface"), [])
        self.assertEqual(dev.commits, 0)


class CacheTests(unittest.TestCase):
    def test_shared_solid_per_colour_and_size(self):
        """G1-9: one shared opaque surface per colour and size class."""
        dev = F.FakeDevice()
        sc = S.SolidCache(dev)
        a = sc.get((11, 11, 12), 680, 680)
        self.assertIs(sc.get((11, 11, 12), 680, 680), a)
        self.assertNotEqual(sc.get((11, 11, 12), 408, 408), a)
        o = dev.obj(a)
        self.assertEqual((o["size"], o["opaque"], o["uploads"]), ((680, 680), True, 1))
        self.assertEqual(o["data"][:4], bytes((12, 11, 11, 255)))
        sc.release()
        self.assertTrue(dev.obj(a)["released"])

    def test_lru_pins_and_evicts(self):
        dev = F.FakeDevice()
        lru = S.SurfaceLRU(dev, capacity=3)
        ids = [dev.create_surface(1, 1, True) for _ in range(5)]
        for i in range(3):
            lru.put(i, ids[i])
        lru.pin({0})
        lru.get(1)
        lru.put(3, ids[3])                                           # evicts 2 (0 pinned, 1 recent)
        self.assertIsNone(lru.get(2))
        self.assertTrue(dev.obj(ids[2])["released"])
        self.assertEqual(lru.evictions, 1)
        lru.release()
        self.assertTrue(all(dev.obj(ids[i])["released"] for i in (0, 1, 3)))


class ShadowTests(unittest.TestCase):
    def test_box_shadow_geometry(self):
        sp = S.box_shadow(680, 680, 72, 0.40, offset_y_px=32)       # 0 16px 36px .40 at k = 2
        self.assertEqual(sp.sigma_px, 36)
        self.assertEqual(sp.reach_px, 108)
        self.assertEqual(sp.scale, 4)
        w, h = sp.image.size
        self.assertEqual(w, h)
        self.assertAlmostEqual(w * 4, 680 + 2 * 4 * (round(108 / 4) + 1), delta=4)
        self.assertAlmostEqual(sp.offset[0], -(round(108 / 4) + 1) * 4)
        self.assertAlmostEqual(sp.offset[1], 32 - (round(108 / 4) + 1) * 4)
        peak = sp.image.getchannel("A").getextrema()[1]
        self.assertAlmostEqual(peak, 0.40 * 255, delta=2)
        self.assertEqual(sp.image.getpixel((0, 0))[3], 0)


class RecipeTests(unittest.TestCase):
    def test_table_and_sigmas(self):
        """§12: σ = radius × k / reduce."""
        self.assertEqual(B.RECIPES["blur.explorer"].sigma(2), 9.0)
        self.assertEqual(B.RECIPES["blur.upnext"].sigma(2), 9.0)
        self.assertEqual(B.RECIPES["blur.picker_frost"].sigma(2), 10.0)
        self.assertEqual(B.RECIPES["blur.toast"].sigma(2), 12.0)
        self.assertEqual(B.RECIPES["blur.explorer"].tint_a, 0.50)
        self.assertEqual(B.RECIPES["blur.upnext"].tint_a, 0.55)
        self.assertEqual(B.RECIPES["blur.explorer"].ambient_opacity, 0.50)
        self.assertEqual(B.RECIPES["blur.upnext"].ambient_opacity, 0.45)
        self.assertEqual(B.RECIPES["blur.picker_frost"].saturate, 1.6)
        self.assertEqual(B.RECIPES["blur.toast"].fallback_a, 0.88)
        self.assertTrue(B.RECIPES["blur.picker_none"].flat)

    def test_matrices_match_the_v6_renderer(self):
        self.assertEqual(B.saturate_matrix(1.3), CR._saturate_matrix(1.3))
        self.assertEqual(B.tint_matrix((8, 8, 10), 0.5), CR._tint_matrix(1.0, (8, 8, 10), 0.5))

    def test_frost_pipeline_is_reduce_blur_saturate_then_tint(self):
        """The v6 order (carousel_render._frost_small): the saturated colour is clamped before
        the tint, as CSS composites the tint layer over the filtered backdrop."""
        from PIL import ImageFilter
        r = B.RECIPES["blur.explorer"]
        g = Image.linear_gradient("L").resize((640, 160))
        cap = Image.merge("RGB", (g, g.rotate(180), g.transpose(Image.FLIP_LEFT_RIGHT)))
        got, _ = B.frost(cap, r, 2.0, (640, 160), overdraw=0)
        want = cap.reduce(8).filter(ImageFilter.GaussianBlur(9.0))
        want = want.convert("RGB", CR._saturate_matrix(1.3)).convert("RGB", CR._tint_matrix(1.0, (8, 8, 10), 0.5))
        self.assertEqual(list(got.getdata()), list(want.getdata()))

    def test_frost_size_overdraw_and_sources(self):
        cap = Image.linear_gradient("L").resize((5120, 1440)).convert("RGB")
        frost, src = B.frost(cap, B.RECIPES["blur.explorer"], 2.0, (5120, 1440))
        self.assertEqual((frost.size, src), ((642, 182), "snapshot"))
        self.assertEqual(frost.getpixel((0, 5)), frost.getpixel((1, 5)))            # the overdraw replicates
        self.assertEqual(frost.getpixel((641, 5)), frost.getpixel((640, 5)))
        self.assertEqual(B.frost_placement(B.RECIPES["blur.explorer"]), (8.0, -8.0, -8.0))
        tint, src2 = B.frost(None, B.RECIPES["blur.explorer"], 2.0, (5120, 1440))
        self.assertEqual(src2, "tint_only")
        self.assertEqual(tint.getpixel((100, 100)), (11, 11, 13))      # S5-30: .50 of (8,8,10) over #0E0E10

    def test_ambient(self):
        self.assertEqual(B.ambient_size(2.0, (5120, 1440)), (720, 260))
        img = B.ambient(Image.new("RGB", (600, 600), (200, 40, 40)), 2.0, (5120, 1440))
        self.assertEqual(img.size, (720, 260))
        solid = B.ambient(0x102030, 2.0, (5120, 1440))
        self.assertEqual(solid.getpixel((5, 5)), (16, 32, 48))
        self.assertEqual(B.ambient_placement(2.0), (8.0, -320.0, -320.0))
        with self.assertRaises(ValueError):
            B.frost(None, B.RECIPES["blur.picker_none"], 2.0, (100, 100))


class CaptureWorkerTests(unittest.TestCase):
    def test_exclusions_wrap_the_grab_even_when_it_fails(self):
        calls = []

        def grab(rect):
            calls.append(("grab", rect))
            raise OSError("BitBlt failed")
        w = CA.StageCaptureWorker(lambda r: None, grab=grab, affinity=lambda h, on: calls.append(("aff", h, on)),
                                  start=False)
        job = CA.CaptureJob(3, (0, 0, 2560, 1440), B.RECIPES["blur.upnext"], 2.0, exclude=(0x10, 0x20))
        res = w.run_job(job)
        self.assertEqual(calls, [("aff", (0x10, 0x20), True), ("grab", (0, 0, 2560, 1440)),
                                 ("aff", (0x10, 0x20), False)])
        self.assertEqual(res.source, "tint_only")
        self.assertEqual(res.gen, 3)
        self.assertIn("BitBlt failed", res.error)

    def test_thread_posts_results_and_closes(self):
        got = []
        ev = threading.Event()

        def on_result(r):
            got.append(r)
            ev.set()
        w = CA.StageCaptureWorker(on_result, grab=lambda rect: Image.new("RGB", (rect[2], rect[3]), (50, 60, 70)),
                                  affinity=lambda h, on: True)
        try:
            self.assertTrue(w.submit(CA.CaptureJob(1, (0, 0, 1280, 720), B.RECIPES["blur.explorer"], 1.0,
                                                   ambient_source=0x334455)))
            self.assertTrue(ev.wait(10.0))
        finally:
            self.assertTrue(w.close(5.0))
        r = got[0]
        self.assertEqual((r.source, r.frost.size, r.ambient.size), ("snapshot", (162, 92), (200, 130)))
        self.assertIsNone(r.error)
        self.assertEqual(w._thread.name, "NanoD-stage-capture")


if __name__ == "__main__":
    unittest.main()

"""r3 Navigator: Recently Added covers from the explorer's art pipeline (navigator_covers.NavigatorCovers),
the Tk-side hand-over and the scene's fade-in over the accent tile. Headless: a synchronous ArtService
with the simulator's covers or a recording fake CoverStore; no network, no window."""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image  # noqa: E402

from control_center import navigator_model as NM  # noqa: E402
from control_center import scene_music as SM  # noqa: E402
from control_center.navigator import Navigator  # noqa: E402
from control_center.stage.scenes.navigator_covers import CAPACITY, NavigatorCovers, plan_for  # noqa: E402
from control_center.stage.scenes import navigator as NS  # noqa: E402
from control_center.stage.scenes import navigator_render as R  # noqa: E402
from control_center.stage.scenes.art import ArtService  # noqa: E402

APPLE = "https://is1-ssl.mzstatic.com/image/thumb/Music/v4/ab/cd/{w}x{h}bb.jpg"


def items(n=9, template=None):
    out = []
    for i in range(n):
        it = {"id": f"alb-{i}", "title": f"Album {i}", "artist": "Artist", "accent": 0x203040 + i, "kind": "album"}
        if template is not None:
            it.update(art_template=template.replace("ab/cd", f"ab/{i:02d}"), art_max=1400)
        out.append(it)
    return out


class Store:
    """A recording CoverStore: what ``ArtService.fetch_decoded`` asks of C1 (the allowlisted path)."""

    def __init__(self):
        self.calls = []

    def fetch(self, *args, **kw):
        self.calls.append((args, sorted(kw)))
        img = Image.new("RGB", (400, 400), (200, 40, 40))
        import io
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        return buf.getvalue()


class CoverSource(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.art = ArtService(sync=True, cover_store=self.store)
        self.covers = NavigatorCovers(self.art, k=2.0)

    def test_the_art_identity_is_the_explorers(self):
        it = items(1, APPLE)[0]
        key, plan = plan_for(it)
        self.assertEqual(key, SM.cover_plan(it).key)
        self.assertEqual(plan.kind, "cover")

    def test_window_is_focus_and_two_each_side_nearest_first(self):
        keys = self.covers.want(items(9, APPLE), 4)
        self.assertEqual(sorted(keys), [2, 3, 4, 5, 6])
        self.assertEqual(len(self.art._jobs), 5)
        prios = sorted((j.prio, j.key[1]) for j in self.art._jobs.values())
        self.assertEqual(prios[0][1], keys[4], "the focused cover first")
        self.assertIsNone(self.covers.get(keys[3]), "nothing until it lands (the accent tile shows)")
        self.art.run_pending()
        img = self.covers.get(keys[3])
        self.assertEqual(img.size, (240, 240), "decoded at the Navigator's 120-unit size, k 2")
        self.assertEqual(self.covers.stats["landed"], 5)

    def test_fetches_go_through_the_cover_store_only(self):
        self.covers.want(items(3, APPLE), 0)
        self.art.run_pending()
        self.assertTrue(self.store.calls)
        for args, kw in self.store.calls:
            self.assertTrue(args[0].startswith("https://is1-ssl.mzstatic.com/"), "the item's own template")
            self.assertEqual(kw, ["cancelled"], "no credentials, no extra headers: C1's rules")

    def test_leaving_the_window_cancels_what_has_not_started(self):
        src = items(20, APPLE)
        self.covers.want(src, 2)
        self.covers.want(src, 15)
        self.assertEqual(self.covers.stats["cancelled"], 5)
        self.assertEqual(len(self.art._jobs), 5)

    def test_already_landed_covers_are_not_asked_again(self):
        src = items(9, APPLE)
        self.covers.want(src, 4)
        self.art.run_pending()
        n = len(self.store.calls)
        self.covers.want(src, 4)
        self.art.run_pending()
        self.assertEqual(len(self.store.calls), n)

    def test_the_lru_is_bounded(self):
        src = items(60, APPLE)
        for focus in range(0, 60, 5):
            self.covers.want(src, focus)
            self.art.run_pending()
        self.assertLessEqual(len(self.covers._images), CAPACITY)
        self.assertGreater(self.covers.stats["evicted"], 0)

    def test_items_without_art_get_the_generated_sleeve(self):
        keys = self.covers.want(items(1), 0)
        self.art.run_pending()
        self.assertTrue(keys[0].startswith("g:"))
        self.assertIsNotNone(self.covers.get(keys[0]))
        self.assertEqual(self.store.calls, [], "no network for a generated sleeve")

    def test_a_failing_fetch_leaves_the_tile(self):
        def boom(*a, **k):
            raise OSError("offline")
        self.store.fetch = boom
        keys = self.covers.want(items(1, APPLE), 0)
        self.art.run_pending()
        self.assertIsNone(self.covers.get(keys[0]))
        self.assertEqual(self.covers.stats["failed"], 1)
        for _ in range(40):                          # the Tk tick asks again and again: backed off
            self.covers.want(items(1, APPLE), 0)
            self.art.run_pending()
        self.assertEqual(self.covers.stats["requests"], 1, "no retry within 30 s")

    def test_no_art_service_means_tiles(self):
        covers = NavigatorCovers(None)
        keys = covers.want(items(3, APPLE), 1)
        self.assertEqual(len(keys), 3)
        self.assertIsNone(covers.get(keys[1]))

    def test_the_simulators_covers_resolve(self):
        content, art = R.with_recent_covers(NM.build_content(R.design_states()[8][1]), R.design_states()[8][1])
        self.assertEqual(len(art), 5, "every visible cover landed as real art")
        self.assertTrue(all(cv.art_key in art for cv in content.covers))


class TkHandOver(unittest.TestCase):
    def test_landed_covers_are_posted_once(self):
        class Backend:
            disabled, hwnd = None, 0

            def __init__(self):
                self.posts = []

            def post(self, st):
                self.posts.append(st)

        class RT:
            presentation_level, touch_seq, device_connected, reduced_motion, open_surfaces = 6, 0, True, False, ()

            def __init__(self, c):
                self.controller = c

            def lcd_media(self, *a, **k):
                return None, None, False, ("",), None, None

        class Screen:
            mode, index = "recent", 4

        class Recent:
            items = items(9, APPLE)
            state = "ready"

        class C:
            screen, recent, state, spaces = Screen(), Recent(), {}, True
            display_volume = 0

        art = ArtService(sync=True, cover_store=Store())
        backend = Backend()
        nav = Navigator(backend, clock=lambda: 1.0, covers=NavigatorCovers(art))
        frame = {"title": "Album 4", "meta": "5 / 9", "buttons": []}
        nav.update(RT(C()), frame)
        first = backend.posts[-1]
        self.assertEqual(first["art"], {}, "nothing landed yet: tiles")
        self.assertTrue(all(cv.art_key for cv in first["content"].covers))
        art.run_pending()
        nav.update(RT(C()), frame)
        self.assertEqual(len(backend.posts[-1]["art"]), 5, "the landed covers, handed over")
        nav.update(RT(C()), frame)
        self.assertEqual(len(backend.posts), 2, "nothing new: nothing posted")


class FadeIn(unittest.TestCase):
    def setUp(self):
        self.snap = R.design_states()[8][1]
        self.source = R.recent_covers_source()

    def test_a_cover_landing_fades_in_over_its_tile(self):
        rig = R.HeadlessNavigator(R.desktop_image())
        content, art = R.with_recent_covers(NM.build_content(self.snap), self.snap, self.source, land=False)
        self.assertEqual(art, {})
        rig.post(content)
        rig.advance(900)
        focus = [it for it in rig.engine.scene.items.values() if it.offset == 0][0]
        self.assertEqual(focus.art_op.value(rig.clk.t), 0.0, "the accent tile shows")
        content, art = R.with_recent_covers(NM.build_content(self.snap), self.snap, self.source)
        rig.post(content, art=art)
        f = focus.art_op.func
        self.assertEqual((f.v0, f.v1), (0.0, 1.0))
        self.assertAlmostEqual(f.dur, NS.ART_FADE_MS / 1000.0)
        rig.advance(400)
        self.assertEqual(focus.art_op.value(rig.clk.t), 1.0)
        self.assertEqual(rig.dev.violations, [])

    def test_a_cover_already_in_shows_at_once(self):
        rig = R.HeadlessNavigator(R.desktop_image())
        content, art = R.with_recent_covers(NM.build_content(self.snap), self.snap, self.source)
        rig.post(content, art=art)
        focus = [it for it in rig.engine.scene.items.values() if it.offset == 0][0]
        self.assertEqual(focus.art_op.value(rig.clk.t), 1.0)

    def test_scene_keeps_a_bounded_set_of_images(self):
        rig = R.HeadlessNavigator(R.desktop_image())
        content, _ = R.with_recent_covers(NM.build_content(self.snap), self.snap, self.source)
        many = {f"k{i}": Image.new("RGB", (8, 8)) for i in range(60)}
        rig.post(content, art=many)
        self.assertLessEqual(len(rig.engine.scene.art), NS.ART_KEEP)
        cv = dataclasses.replace(content)
        self.assertTrue(cv.covers)


if __name__ == "__main__":
    unittest.main()

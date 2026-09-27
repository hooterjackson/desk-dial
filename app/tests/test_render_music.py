"""The PIL side of the music scenes (WP8): glyphs, premultiplied sprites, the art states (K4 §13.5,
§13.6), the scene sprites (§7.4, §8.2, §8.3 [r2.2]), text layout, the PIL reference renderer
(§4.8: LINEAR sampling, SOFT edges, LAYER vs MULTIPLY group opacity, recorded animations) and the
H4 golden images of every BS state-picker state at 16:9 and 32:9.

Golden images live in ``tests/goldens/music``. ``NANOD_WRITE_GOLDENS=1`` (re)writes them; they
are reviewed by eye (``write_review`` in the scenes' testing module renders the same cases at
k = 1 for that) before they are committed. Headless; nothing is shown or fetched."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from control_center import render_music as RM  # noqa: E402
from control_center import scene_music as SM  # noqa: E402

GOLDENS = ROOT / "tests" / "goldens" / "music"


def _near(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class GlyphTests(unittest.TestCase):
    def test_path_parser(self):
        clock = RM.parse_path(SM.GLYPHS["clock"])
        self.assertEqual(len(clock), 2)                                  # the hands, the circle
        heart = RM.parse_path(SM.GLYPHS["heart"])
        self.assertEqual(len(heart), 1)
        self.assertTrue(heart[0][1])                                     # closed
        xs = [p[0] for p in heart[0][0]]
        ys = [p[1] for p in heart[0][0]]
        self.assertAlmostEqual(min(ys), 3.99, delta=0.1)                   # the lobes' tops (r 5.5 arcs)
        self.assertAlmostEqual(max(ys), 22.0, delta=0.05)
        self.assertAlmostEqual(min(xs) + max(xs), 24.0, delta=0.2)       # symmetric about x = 12
        note = RM.parse_path(SM.GLYPHS["note"])
        self.assertEqual(len(note), 3)

    def test_masks(self):
        solid = RM.glyph_mask("heart", 40, stroke=1.8, caps="butt")
        dashed = RM.glyph_mask("heart", 40, stroke=1.8, dash=RM.HEART_DASH, caps="butt")
        filled = RM.glyph_mask("heart", 40, fill=True)
        cover = lambda m: sum(m.getdata()) / 255.0                       # noqa: E731
        self.assertLess(cover(dashed), 0.75 * cover(solid))              # 2.2 on / 2.4 off
        self.assertGreater(cover(dashed), 0.30 * cover(solid))
        self.assertGreater(cover(filled), 2 * cover(solid))
        self.assertEqual(solid.size, (40, 40))
        l, t, r, b = filled.getbbox()
        self.assertAlmostEqual((l + r) / 2.0, 20, delta=1.0)

    def test_dash_segments_cover_the_path(self):
        pts = [(0.0, 0.0), (10.0, 0.0)]
        dashes = RM._dash_segments(pts, 2.2, 2.4)
        self.assertEqual(len(dashes), 3)                                 # 0-2.2, 4.6-6.8, 9.2-10
        self.assertAlmostEqual(dashes[1][0][0], 4.6)
        self.assertAlmostEqual(dashes[2][-1][0], 10.0)


class SpriteTests(unittest.TestCase):
    def test_premultiplied_over_and_bytes(self):
        s = RM.Sprite.new(4, 2)
        s.fill((0, 0, 4, 2), (255, 255, 255), 0.5)
        b = s.bgra()
        self.assertEqual(len(b), 4 * 2 * 4)
        self.assertEqual(tuple(b[:4]), (128, 128, 128, 128))             # B G R A premultiplied
        s.fill((0, 0, 2, 2), (255, 0, 0), 0.5)
        px = s.straight().getpixel((0, 0))
        self.assertAlmostEqual(px[3], 191, delta=1)                      # 0.5 + 0.5·0.5
        self.assertTrue(_near(px[:3], (255, 85, 85), 2))                  # straight over, rounded
        self.assertEqual(tuple(s.bgra()[4 * 3:4 * 4]), (128, 128, 128, 128))

    def test_opaque_bytes(self):
        img = Image.new("RGB", (2, 1), (10, 20, 30))
        self.assertEqual(RM.opaque_bgra(img)[:4], bytes((30, 20, 10, 255)))

    def test_text_on_both_targets(self):
        spr = RM.Sprite.new(200, 40)
        w = RM.draw_text(spr, "Hounds of Love", 0, 0, 20, 26, wght=600)
        self.assertGreater(w, 100)
        self.assertIsNotNone(spr.a.getbbox())
        img = Image.new("RGB", (200, 40), (0, 0, 0))
        RM.draw_text(img, "Hounds of Love", 0, 0, 20, 26, rgb=(255, 0, 0))
        self.assertGreater(max(p[0] for p in img.getdata()), 200)


class GradientAndArtTests(unittest.TestCase):
    def test_linear_160(self):
        g = RM.linear_gradient_160(200, 0x2B3A55, 0x131A28)
        self.assertTrue(_near(g.getpixel((0, 0)), (0x2B, 0x3A, 0x55), 3))
        self.assertTrue(_near(g.getpixel((199, 199)), (0x13, 0x1A, 0x28), 3))
        top_right, bottom_left = g.getpixel((199, 0)), g.getpixel((0, 199))
        self.assertGreater(sum(top_right), sum(bottom_left))            # 160°: mostly top to bottom

    def test_radial_extended_ground(self):
        c = (200, 100, 50)
        g = RM.radial_ground(300, c)
        self.assertTrue(_near(g.getpixel((150, 114)), (190, 95, 48), 3))     # shade .95 at 50 % / 38 %
        corner = g.getpixel((0, 299))
        self.assertLess(sum(corner), sum(g.getpixel((150, 114))) / 2)

    def test_extended_geometry(self):
        src = RM.linear_gradient_160(400, 0xFF0000, 0x00FF00)
        img = RM.art_extended(src, 680, (255, 120, 30), SM.extended_fraction(680, 400), 2.0)
        self.assertEqual(img.size, (680, 680))
        fitted = RM.fit_square(src, 600)
        self.assertTrue(_near(img.getpixel((340, 340)), fitted.getpixel((300, 300)), 2))   # sharp, centred
        below = img.getpixel((340, 660))
        ground = RM.radial_ground(680, (255, 120, 30))
        self.assertLess(sum(below), sum(ground.getpixel((340, 660))))            # the shadow falls below

    def test_generated_and_loading(self):
        gen = RM.art_generated("Hounds of Love", "Kate Bush", 340)
        g0, g1, ink = RM.GEN_PALETTE[SM.gen_index("Hounds of Love", "Kate Bush")]
        self.assertTrue(_near(gen.getpixel((1, 1)), RM.rgb_of(g0), 4))
        inks = [p for p in gen.getdata() if _near(p, RM.rgb_of(ink), 12)]
        self.assertGreater(len(inks), 200)                                         # the title in ink
        again = RM.art_generated("Hounds of Love", "Kate Bush", 340)
        self.assertEqual(gen.tobytes(), again.tobytes())
        cover = RM.art_generated("Moon Safari", "Air", 380, variant="cover")
        self.assertEqual(cover.size, (380, 380))
        load = RM.art_loading("Heligoland", "Massive Attack", 340, 0xFF781E, 0xF2F2F2)
        self.assertEqual(load.getpixel((10, 10)), (0xFF, 0x78, 0x1E))
        self.assertTrue(any(_near(p, (0xF2, 0xF2, 0xF2), 20) for p in load.crop((22, 280, 200, 330)).getdata()))
        self.assertEqual(RM.art_loading("", "", 16, 0x232325, 0xF2F2F2).getpixel((3, 3)), (0x23, 0x23, 0x25))

    def test_mosaic(self):
        tiles = [Image.new("RGB", (100, 100), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))]
        m = RM.art_mosaic(tiles, 200)
        self.assertEqual([m.getpixel(p) for p in ((50, 50), (150, 50), (50, 150), (150, 150))],
                         [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)])


class SceneSpriteTests(unittest.TestCase):
    def test_sizes_at_k2(self):
        self.assertEqual(RM.label_sprite("A", "B", "C", 2.0).size, (1800, 176))
        self.assertEqual(RM.row_sprite(2.0, lead="art", title="t", sub="s").size, (1120, 176))
        spr, w, lh = RM.tab_sprite("recent", 2.0)
        self.assertGreater(w, 52 * 2)
        self.assertAlmostEqual(lh, max(36, RM.line_normal(34)))
        d = SM.dots_window(120, 60)
        self.assertEqual(RM.dots_sprite(d, 2.0).size, (82 * 28 - 16, 12))
        ho, hd, hf = RM.heart_sprites(2.0)
        self.assertEqual((ho.size, hd.size, hf.size), ((40, 40), (40, 40), (60, 60)))
        self.assertTrue(_near(hf.straight().getpixel((30, 30))[:3], SM.U_HEART_RGB, 2))

    def test_dots_end_fades(self):
        d = SM.dots_window(120, 60)
        spr = RM.dots_sprite(d, 1.0)
        a = spr.a
        self.assertEqual([a.getpixel((j * 14 + 2, 2)) for j in (0, 1, 2, 3)], [26, 51, 76, 102])

    def test_row_sprite_draws_the_tag_in_green_on_now(self):
        spr = RM.row_sprite(2.0, lead="number", number="04", title="Running Up That Hill", sub="Kate Bush",
                            tag=SM.row_tag(3, 3))
        st = spr.straight()
        greens = [p for p in st.crop((800, 60, 1070, 120)).getdata() if p[3] > 200 and p[1] > p[0] + 60]
        self.assertGreater(len(greens), 20)

    def test_placeholder_row(self):
        spr = RM.row_sprite(2.0, lead="placeholder", placeholder_k=1)
        self.assertEqual(spr.a.getpixel((60, 80)), round(0.10 * 255))              # the 56 px block at 10 %
        self.assertEqual(spr.a.getpixel((200, 60)), round(0.14 * 255))             # the first bar at 14 %

    def test_state_block_wraps_pretty(self):
        lines = RM.wrap_pretty("Add an album or a playlist to your library in the Music app.", 16, 400, 300)
        self.assertGreater(len(lines[-1].split()), 1)


class TextLayoutTests(unittest.TestCase):
    def test_balance_and_clamp(self):
        text = "Tropicália ou Panis et Circencis"
        greedy = RM.wrap(text, 34, 800, 288)
        balanced = RM.wrap_balanced(text, 34, 800, 288)
        self.assertEqual(len(greedy), len(balanced))
        eng = RM.text_engine()
        widths = [eng.width(l, 34, 800) for l in balanced]
        self.assertLessEqual(max(widths) - min(widths), max(eng.width(l, 34, 800) for l in greedy))
        long = " ".join(["Word"] * 40)
        clamped = RM.clamp_lines(RM.wrap(long, 34, 800, 288), 4, 34, 800, 288)
        self.assertEqual(len(clamped), 4)
        self.assertTrue(clamped[-1].endswith("…"))

    def test_exact_weights(self):
        eng = RM.text_engine()
        self.assertNotEqual(eng.width("Hounds of Love", 30, 800), eng.width("Hounds of Love", 30, 700))
        self.assertNotEqual(eng.width("Hounds of Love", 30, 500), eng.width("Hounds of Love", 30, 600))


class ReferenceRendererTests(unittest.TestCase):
    """§4.8: the renderer draws what DirectComposition composes from the recorded tree."""

    def setUp(self):
        from control_center.stage import fake as F
        from control_center.stage.scenes.testing import KeepingDevice
        from control_center.stage.tree import Tree
        self.clk = F.FakeClock()
        self.dev = KeepingDevice(self.clk)
        self.tree = Tree(self.dev)

    def square(self, rgb, size=40):
        s = self.dev.create_surface(size, size, True, "sq")
        self.dev.upload(s, size, size, RM.opaque_bgra(Image.new("RGB", (size, size), rgb)))
        return s

    def scene(self, overlap_mode):
        t = self.tree
        root = t.root()
        box = t.container("box", overlap=overlap_mode)
        t.add(root, box)
        op = t.opacity(box, 0.5)
        a = t.visual("a", content=self.square((255, 0, 0)))
        b = t.visual("b", content=self.square((0, 0, 255)))
        t.offset(a, 0, 0)
        t.offset(b, 20, 0)
        t.add(box, a)
        t.add(box, b)
        return root

    def test_layer_opacity_composes_the_group_first(self):
        root = self.scene(True)
        img = RM.ReferenceRenderer(self.dev, self.clk.freq).render(root.ptr, (80, 40), self.clk.t)
        self.assertTrue(_near(img.getpixel((30, 20)), (0, 0, 128), 2))         # blue only: no red through it
        self.assertTrue(_near(img.getpixel((5, 20)), (128, 0, 0), 2))

    def test_multiply_opacity_blends_each_child(self):
        root = self.scene(False)
        img = RM.ReferenceRenderer(self.dev, self.clk.freq).render(root.ptr, (80, 40), self.clk.t)
        self.assertTrue(_near(img.getpixel((30, 20)), (64, 0, 128), 2))        # red shows through the blue

    def test_transforms_and_animations(self):
        from control_center.stage import clock as CK
        from control_center.stage.engine import StageCore
        t = self.tree
        root = t.root()
        v = t.visual("v", content=self.square((255, 255, 255), 20))
        st = t.scale_transform(v, 10, 10)
        sc = t.scale(st, 20, 1.0)
        t.add(root, v)
        x = t.offset_x(v, 0.0)
        core = StageCore(self.dev, CK.StageClock(self.dev.time_frequency, self.dev.time_frequency, qpc=self.clk,
                                                 perf=self.clk.perf))
        b = core.batch()
        b.to(x, 40.0, 100, "OUT")
        b.to(sc, 2.0, 100, "OUT")
        b.commit()
        r = RM.ReferenceRenderer(self.dev, self.clk.freq)
        end = r.render(root.ptr, (100, 40), b.t1 + int(0.2 * self.clk.freq))
        self.assertEqual(end.getpixel((50, 10)), (255, 255, 255))               # x 40, scaled 2 about (10, 10)
        self.assertEqual(end.getpixel((31, 10)), (255, 255, 255))
        self.assertEqual(end.getpixel((28, 10)), (0, 0, 0))
        start = r.render(root.ptr, (100, 40), b.t1 - 1000)
        self.assertEqual(start.getpixel((5, 10)), (255, 255, 255))
        self.assertEqual(start.getpixel((45, 10)), (0, 0, 0))

    def test_forbidden_modes_are_refused(self):
        root = self.tree.root()
        self.dev.objects[root.ptr]["props"]["interp"] = 0
        with self.assertRaises(AssertionError):
            RM.ReferenceRenderer(self.dev, self.clk.freq).render(root.ptr, (10, 10), self.clk.t)


class GoldenTests(unittest.TestCase):
    """H4: the reference renderer against every BS state-picker state at 16:9 and 32:9."""

    maxDiff = None

    def test_goldens(self):
        from control_center.stage.scenes import testing as T
        write = os.environ.get("NANOD_WRITE_GOLDENS", "").strip() == "1"
        if write:
            GOLDENS.mkdir(parents=True, exist_ok=True)
        failures = []
        jobs = [(f"{name}_{ratio}", (lambda n=name, s=surface, b=build, r=ratio: T.render_golden(n, s, b, r)))
                for name, surface, build in T.golden_cases() for ratio in ("32x9", "16x9")]
        jobs += [(name, (lambda n=name, s=surface, b=build, bx=box: T.render_crop_golden(n, s, b, bx)))
                 for name, surface, build, box in T.CROP_CASES]
        for stem, render in jobs:
            if True:
                img = render()
                path = GOLDENS / f"{stem}.png"
                if write:
                    img.save(path, optimize=True)
                    continue
                if not path.exists():
                    failures.append(f"{path.name}: missing (NANOD_WRITE_GOLDENS=1 writes it)")
                    continue
                want = Image.open(path).convert("RGB")
                if want.size != img.size:
                    failures.append(f"{path.name}: size {img.size} != {want.size}")
                    continue
                diff = [abs(a - b) for pa, pb in zip(img.getdata(), want.getdata()) for a, b in zip(pa, pb)]
                over = sum(1 for d in diff if d > 3)
                if over > len(diff) // 1000:
                    failures.append(f"{path.name}: {over} channel values differ by more than 3")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()

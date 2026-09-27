"""Picker v2 rendering (DESKTOP_STAGE.md 9.2-9.4, 10.1, 12; CAROUSEL.md 6-8 and 12): the full-screen
blur.picker_frost on synthetic images, No background's dim, premultiplied canvas arithmetic,
chrome composition (the two crossfading shadows, the frame, the chip, the badge, the tray, B3a,
B4, B5), the label built with masked pastes, text fitting and per-glyph font fallback, the letter
tile, the toast (blur.toast, top 588) and the dots with their marker. Pure PIL: no windows, no Tk.
Font-fallback cases need the Windows fonts and skip without them."""
from pathlib import Path
import math
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from control_center import carousel_render as R  # noqa: E402

FONTS = R.SYSTEM_FONT_DIR
HAVE_FALLBACKS = all((FONTS / name).exists() for name in ("segoeui.ttf", "seguisb.ttf", "seguiemj.ttf", "msyh.ttc",
                                                          "malgun.ttf"))
ENGINE = R.TextEngine()


def synthetic_desktop(size):
    """A wallpaper-like test image: gradient, blocks, sharp edges."""
    w, h = size
    image = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((w // 8, h // 8, w // 3, h // 2), fill=(230, 80, 60))
    draw.rectangle((w // 2, h // 3, w - w // 6, h - h // 8), fill=(40, 120, 220))
    draw.rectangle((0, 0, w, h // 16), fill=(250, 250, 250))
    return image


class GlassTests(unittest.TestCase):
    """blur.picker_frost (K4 9.2, S5-21): the whole monitor, blurred on the reduced image,
    saturated 1.6, tinted rgba(10,10,12,.50); no dim, no sheen, no border, no inset lines."""

    def test_sigma_is_the_css_blur_standard_deviation(self):
        self.assertEqual(R.glass_sigma(2.0), 10.0)
        self.assertEqual(R.glass_sigma(2.0, R.TOAST_BLUR, R.TOAST_REDUCE), 12.0)    # blur.toast's blur(24px)
        self.assertEqual(R.frost_sigma(2.0), 10.0)    # sigma 40 k / 8
        self.assertEqual(R.frost_sigma(1.0), 5.0)
        # box-shadow blur radii are 2 sigma: the side shadow's 30 px blur is sigma 30 at k = 2,
        # padded to where 8 bits round to 0 (about 2.5 sigma at alpha .3), not 3 sigma
        pad = R.ShadowCache(2.0)._base("side")[2]
        self.assertEqual(pad, math.ceil(R.shadow_reach(0.30) * 30))
        self.assertTrue(2.3 * 30 < pad < 3 * 30, pad)

    def test_the_frost_is_the_recipe_step_by_step(self):
        from PIL import ImageFilter
        size, k = (2560, 1440), 2.0
        source = synthetic_desktop(size)
        small = source.reduce(8).filter(ImageFilter.GaussianBlur(40 * k / 8))
        small = small.convert("RGB", R._saturate_matrix(1.6)).convert("RGB", R._tint_matrix(1.0, (10, 10, 12), 0.50))
        want = small.resize(size, Image.Resampling.BILINEAR).convert("RGBA").tobytes()
        frost = R.frost(source, k).tobytes()
        self.assertEqual(frost, want)
        self.assertEqual(R.frost_canvas(source, k).straight().tobytes(), frost)
        self.assertEqual((R.GLASS_SATURATE, R.GLASS_TINT, R.GLASS_TINT_A, R.GLASS_DIM), (1.6, (10, 10, 12), 0.50, 1.0))

    def test_pipeline_is_opaque_same_size_and_deterministic(self):
        for k, size in ((1.0, (1280, 720)), (2.0, (2560, 1440)), (2.0, (5120, 1440))):
            with self.subTest(k=k, size=size):
                source = synthetic_desktop(size)
                first, second = R.frost(source, k), R.frost(source, k)
                self.assertEqual((first.size, first.mode), (size, "RGBA"))
                self.assertEqual(first.getchannel("A").getextrema(), (255, 255))
                self.assertEqual(first.tobytes(), second.tobytes())
                self.assertIs(R.glass, R.frost, "the historical name the smoke test calls")

    def test_the_dib_canvas_is_the_same_frost_premultiplied_and_opaque(self):
        source = synthetic_desktop((1280, 720))
        canvas = R.frost_canvas(source, 1.0)
        self.assertIsInstance(canvas, R.Canvas)
        self.assertEqual(canvas.size, (1280, 720))
        self.assertEqual(canvas.image.getextrema()[3], (255, 255), "opaque: premultiplied == straight")
        self.assertEqual(canvas.straight().tobytes(), R.frost(source, 1.0).tobytes())

    def test_the_rgb_capture_is_not_copied_before_it_is_reduced(self):
        source = synthetic_desktop((1280, 720))
        calls = []
        real = Image.Image.copy

        def spy(image):
            calls.append(image.size)
            return real(image)
        Image.Image.copy = spy
        try:
            R.frost_canvas(source, 1.0)
        finally:
            Image.Image.copy = real
        self.assertNotIn((1280, 720), calls)

    def test_blur_smooths_sharp_edges(self):
        source = Image.new("RGB", (1280, 720), (0, 0, 0))
        ImageDraw.Draw(source).rectangle((400, 100, 700, 450), fill=(255, 255, 255))
        glass = R.frost(source, 1.0).convert("RGB")
        row = 300
        diffs = [abs(sum(glass.getpixel((x + 1, row))) - sum(glass.getpixel((x, row)))) for x in range(20, 1260)]
        self.assertLess(max(diffs), 60)

    def test_tint_and_saturation_with_no_dim_border_sheen_or_inset_lines(self):
        black = R.frost(Image.new("RGB", (1280, 720), (0, 0, 0)), 1.0)
        self.assertEqual(black.getextrema()[:3], ((5, 5), (5, 5), (6, 6)), "0.50 x (10, 10, 12) everywhere")
        grey = R.frost(Image.new("RGB", (1280, 720), (128, 128, 128)), 1.0)
        pixel = grey.getpixel((640, 360))
        self.assertAlmostEqual(pixel[0], round(128 * 0.5 + 10 * 0.5), delta=1)       # no dim in the recipe
        red = R.frost(Image.new("RGB", (1280, 720), (200, 100, 100)), 1.0).getpixel((640, 360))
        self.assertGreater(red[0] - red[1], (200 - 100) * 0.5)                         # saturate(1.6) adds chroma
        for name in ("GLASS_SHEEN", "GLASS_BORDER_A", "PANE_SHADOW", "solid_glass", "opaque_pane", "_sheen", "_edges"):
            self.assertFalse(hasattr(R, name), f"no {name}")

    def test_the_frost_without_a_capture_is_the_tint_alone(self):
        solid = R.solid_frost((64, 32))
        self.assertIsInstance(solid, R.Canvas)
        self.assertEqual(solid.image.getextrema()[3], (128, 128))                     # 0.50
        b, g, r, a = solid.image.getpixel((5, 5))
        self.assertEqual((r, g, b), (5, 5, 6))
        for desktop in (0, 128, 255):
            self.assertAlmostEqual(r + desktop * (1 - a / 255), 10 * 0.5 + desktop * 0.5, delta=1.5)
        self.assertEqual(R.opaque_pane_rgb(), (9, 9, 10))     # the plain host's flat colour


class DimTests(unittest.TestCase):
    def test_no_background_dim_is_a_flat_55_percent(self):
        layout = R.layout_for((0, 0, 1280, 720))
        image = R.build_dim(R.Canvas.new((1280, 720)), layout, "none").image
        self.assertEqual(image.getextrema(), ((0, 0), (0, 0), (0, 0), (140, 140)))
        self.assertEqual(R.build_dim(R.Canvas.new((4, 4)), layout, "glass").image.getextrema()[3], (0, 0))


class CanvasTests(unittest.TestCase):
    def test_ink_views_paste_the_same_bytes_as_a_colour_fill_and_share_one_buffer(self):
        noise = Image.effect_noise((300, 200), 90)
        base = Image.merge("RGBX", [noise.point(lambda v: v // 2)] * 3 + [noise])
        mask = Image.effect_noise((211, 97), 120)
        for ink in (R.SHADOW_INK, (255, 255, 255, 255), (12, 200, 7, 255)):
            want, got = base.copy(), base.copy()
            want.paste(ink, (40, 30, 251, 127), mask)
            R._paste_ink(got, ink, (40, 30, 251, 127), mask)
            self.assertEqual(got.tobytes(), want.tobytes(), ink)
        first = R._INKS[R.SHADOW_INK]
        R._ink_view(R.SHADOW_INK, 10, 10)
        self.assertIs(R._INKS[R.SHADOW_INK], first, "a smaller view reuses the buffer")
        self.assertIsNone(R._ink_view(R.SHADOW_INK, 0, 5))
        self.assertIsNone(R._ink_view((1, 2, 3, 255), 5000, 5000))           # past INK_VIEW_MAX
        big = Image.new("RGBX", (8, 8))
        R._paste_ink(big, (1, 2, 3, 255), (0, 0, 8, 8), Image.new("L", (8, 8), 255))
        self.assertEqual(big.getpixel((3, 3)), (1, 2, 3, 255))

    def test_canvas_is_rgbx_and_over_is_premultiplied_source_over(self):
        with self.assertRaises(ValueError):
            R.Canvas(Image.new("RGBA", (2, 2)))
        canvas = R.Canvas.new((4, 1))
        canvas.over((0, 0, 1, 1), (0x11, 0x22, 0x33), 0.5)
        for got, want in zip(canvas.image.getpixel((0, 0)), (0x33 * 128 / 255, 0x22 * 128 / 255, 0x11 * 128 / 255, 128)):
            self.assertAlmostEqual(got, want, delta=0.51)
        canvas.fill((1, 0, 2, 1), (100, 50, 200), 0.5)
        canvas.over((1, 0, 2, 1), (0, 0, 0), 0.5)
        b, g, r, a = canvas.image.getpixel((1, 0))
        self.assertEqual((r, g, b), (round(50 * 0.5), round(25 * 0.5), round(100 * 0.5)))
        self.assertEqual(a, round(128 + 255 * 0.5 * (1 - 128 / 255)))

    def test_over_mask_skips_the_excluded_rect_and_clips(self):
        canvas = R.Canvas.new((20, 20))
        mask = Image.new("L", (30, 30), 200)
        canvas.over_mask((0, 0, 0), mask, (-5, -5), exclude=(5, 5, 15, 15))
        self.assertEqual(canvas.image.getpixel((10, 10))[3], 0)
        self.assertEqual(canvas.image.getpixel((2, 2))[3], 200)
        self.assertEqual(canvas.image.getpixel((17, 10))[3], 200)

    def test_sprites_keep_straight_colour_and_global_alpha(self):
        image = Image.new("RGBA", (2, 2), (200, 100, 50, 128))
        sprite = R.Sprite.from_image(image)
        canvas = R.Canvas.new((2, 2))
        canvas.over_sprite(sprite, (0, 0), 0.5)
        b, g, r, a = canvas.image.getpixel((0, 0))
        self.assertEqual(a, 64)
        self.assertEqual((r, g, b), (round(200 * 64 / 255), round(100 * 64 / 255), round(50 * 64 / 255)))
        straight = canvas.straight().getpixel((0, 0))
        self.assertAlmostEqual(straight[0], 200, delta=4)
        self.assertEqual(sprite.straight().getpixel((1, 1)), (200, 100, 50, 128))

    def test_resized_sprites_are_resampled_premultiplied(self):
        # An opaque white square on transparent black: the edge pixels a resize blends must stay
        # white (straight colour), not turn grey from the transparent pixels' black.
        image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((10, 10, 29, 29), fill=(255, 255, 255, 255))
        sprite = R.Sprite.from_image(image)
        for resample in (Image.Resampling.BILINEAR, Image.Resampling.LANCZOS):
            with self.subTest(resample=resample):
                small = sprite.resized((27, 27), resample).straight()
                edges = [small.getpixel((x, y)) for x in range(27) for y in range(27)
                         if 16 <= small.getpixel((x, y))[3] <= 240]
                self.assertTrue(edges)
                self.assertTrue(all(min(p[:3]) >= 245 for p in edges), edges[:4])
                self.assertEqual(small.getpixel((13, 13)), (255, 255, 255, 255))
        solid = R.Sprite.solid(Image.new("L", (8, 8), 255), (10, 20, 30))
        resized = solid.resized((4, 4))
        self.assertIsNone(resized.colour_image)
        self.assertEqual((resized.colour, resized.size), (solid.colour, (4, 4)))
        self.assertIs(sprite.resized(sprite.size), sprite)

    def test_sprite_scaler_is_bounded_and_trims(self):
        scaler = R._SpriteScaler(limit=4)
        sprite = R.Sprite.from_image(Image.new("RGBA", (64, 64), (1, 2, 3, 255)))
        for i in range(10):
            scaler.get(sprite, (20 + i, 20 + i), True)
        self.assertEqual(len(scaler), 4)
        self.assertIs(scaler.get(sprite, (29, 29), True), scaler.get(sprite, (29, 29), True))
        scaler.trim()
        self.assertEqual(len(scaler), 0)

    def test_premultiplied_bgra_bytes(self):
        self.assertEqual(R.premultiplied_bgra(Image.new("RGBA", (1, 1), (200, 100, 50, 128))),
                         bytes((25, 50, 100, 128)))
        self.assertEqual(R.premultiplied_bgra(Image.new("RGB", (1, 1), (1, 2, 3))), bytes((3, 2, 1, 255)))
        opaque = Image.new("RGBA", (2, 1), (10, 20, 30, 255))
        self.assertEqual(R.premultiplied_bgra(opaque), bytes((30, 20, 10, 255)) * 2)   # the fast path


class ComposeTests(unittest.TestCase):
    """compose_chrome with origin (0, 0) on a monitor-sized canvas (canvas px = host-local px)."""

    def scene(self, closed=None, placeholder_index=None, chip_index=None, background="glass", animating=False):
        layout = R.layout_for((0, 0, 1280, 720))
        badge = R.badge_sprite(None, "Slack", layout.k, ENGINE)
        chip = R.chip_sprite("left", layout.k, ENGINE)
        cards = []
        for d in (-2, 2, -1, 1, 0):
            x, s, op, shade = R.table_state(d)
            if closed == d:
                op *= R.CLOSED_OPACITY
            holder = R.placeholder_sprite(None, "Bambu Studio", layout.k, ENGINE) if placeholder_index == d else None
            cards.append(R.ChromeCard(R.card_rect(layout, x, s), s, op, shade, 1.0 if d == 0 else 0.0, badge, holder, d,
                                      None, chip if chip_index == d else None))
        scene = R.ChromeScene(layout.k, (0, 0), background, cards, [], animating)
        canvas = R.Canvas.new((1280, 720))
        drawn = R.compose_chrome(canvas, scene, R.ShadowCache(layout.k, background))
        return layout, scene, canvas.image, drawn

    def test_centre_card_is_clear_for_its_thumbnail_and_framed(self):
        layout, scene, image, drawn = self.scene()
        l, t, r, b = R.card_rect(layout, 0, 1.0)
        self.assertEqual((r - l, b - t), (400, 250))
        self.assertEqual(image.getpixel(((l + r) // 2, (t + b) // 2))[3], 0)
        frame_y = t - R.OUTLINE_OFFSET - 1          # k = 1: the frame's inner edge 6 out, 2 px wide (outer edge 8)
        self.assertAlmostEqual(image.getpixel(((l + r) // 2, frame_y))[3], round(255 * 0.9), delta=4)
        self.assertLess(image.getpixel(((l + r) // 2, t - 3))[3], 60)
        below, above = image.getpixel(((l + r) // 2, b + 30))[3], image.getpixel(((l + r) // 2, t - 25))[3]
        self.assertGreater(below, above)                  # the focus shadow falls down (offset 24)
        self.assertIsNotNone(drawn)
        self.assertTrue(drawn[0] <= l and drawn[2] >= r)

    def test_side_cards_carry_the_shade_and_no_frame(self):
        layout, scene, image, _ = self.scene()
        l, t, r, b = R.card_rect(layout, *R.table_state(1)[:2])
        b_, g_, r_, a = image.getpixel(((l + r) // 2, t + 10))
        self.assertAlmostEqual(a, round(255 * R.shade_alpha(0.95, 0.22)), delta=1)
        self.assertAlmostEqual(r_, round(0x11 * a / 255), delta=1)
        self.assertLess(image.getpixel(((l + r) // 2, t - 7))[3], 120)

    def test_badge_sits_at_the_bottom_left_inset_at_30_units(self):
        layout, scene, image, _ = self.scene()
        l, t, r, b = R.card_rect(layout, 0, 1.0)
        self.assertEqual((R.BADGE_SIZE, R.BADGE_INSET), (30, 12))
        self.assertEqual(image.getpixel((l + R.BADGE_INSET + 15, b - R.BADGE_INSET - 15))[3], 255)
        self.assertEqual(image.getpixel((l + R.BADGE_INSET + 15, b - R.BADGE_INSET - 60))[3], 0)

    def test_the_snap_chip_sits_top_left_under_the_shade(self):
        layout, scene, image, _ = self.scene(chip_index=0)
        l, t, r, b = R.card_rect(layout, 0, 1.0)
        chip = image.getpixel((l + R.CHIP_INSET + 2, t + R.CHIP_INSET + 2))
        self.assertAlmostEqual(chip[3], round(255 * R.CHIP_A), delta=2)            # rgba(18,18,20,.72)
        self.assertAlmostEqual(chip[2], round(18 * R.CHIP_A), delta=2)
        sprite = R.chip_sprite("right", 1.0, ENGINE)
        self.assertEqual(sprite.size[1], R.CHIP_PAD_Y * 2 + R.CHIP_ICON)
        self.assertGreater(sprite.size[0], R.CHIP_PAD_X * 2 + R.CHIP_ICON + R.CHIP_GAP)
        layout, scene, shaded, _ = self.scene(chip_index=-1)
        l, t, r, b = R.card_rect(layout, *R.table_state(-1)[:2])
        spot = (l + round((R.CHIP_INSET + 2) * 0.56), t + round((R.CHIP_INSET + 2) * 0.56))
        self.assertGreater(shaded.getpixel(spot)[3], round(255 * R.shade_alpha(0.95, 0.22)))

    def test_placeholder_and_closed_cards(self):
        layout, scene, image, _ = self.scene(placeholder_index=0)
        l, t, r, b = R.card_rect(layout, 0, 1.0)
        pixel = image.getpixel((l + 30, t + 30))
        self.assertEqual(pixel[3], 255)
        self.assertEqual((pixel[2], pixel[1], pixel[0]), R.PLACEHOLDER_RGB)
        self.assertEqual(R.PLACEHOLDER_RGB, (0x1B, 0x1B, 0x1D))
        layout, scene, image, _ = self.scene(closed=1)
        l, t, r, b = R.card_rect(layout, *R.table_state(1)[:2])
        a = image.getpixel(((l + r) // 2, t + 10))[3]
        self.assertAlmostEqual(a, round(255 * R.shade_alpha(0.95 * 0.35, 0.22)), delta=1)

    def test_both_backgrounds_draw_the_same_card_shadows(self):
        _, _, glass, _ = self.scene(background="glass")
        _, _, none, _ = self.scene(background="none")
        self.assertIsNone(ImageChops.difference(glass, none).getbbox(), "S5-20")

    def test_b5_only_the_dirty_rect_is_cleared(self):
        layout = R.layout_for((0, 0, 1280, 720))
        canvas = R.Canvas.new((1280, 720))
        canvas.fill((0, 0, 4, 4), (255, 0, 0), 1.0)                                  # stale content outside
        x, s, op, shade = R.table_state(0)
        card = R.ChromeCard(R.card_rect(layout, x, s), s, op, shade, 1.0)
        scene = R.ChromeScene(layout.k, (0, 0), "glass", [card], [], False, clear=(100, 100, 1200, 700))
        drawn = R.compose_chrome(canvas, scene, R.ShadowCache(layout.k))
        self.assertEqual(canvas.image.getpixel((1, 1))[3], 255, "outside the dirty rect: kept")
        footprint = R.scene_footprint(scene, R.ShadowCache(layout.k))
        self.assertEqual(drawn, footprint)

    def test_shadow_cache_crossfades_two_fixed_layers(self):
        cache = R.ShadowCache(1.0)
        self.assertEqual(cache.shadow_params("side"), (12, 30, 0.30))
        self.assertEqual(cache.shadow_params("focus"), (24, 60, 0.45))
        rect = (400, 200, 800, 450)
        for selw in (0.0, 0.5, 1.0):
            with self.subTest(selw=selw):
                canvas = R.Canvas.new((1280, 720))
                cache.paint(canvas, rect, 1.0, 1.0, selw, animating=False)
                side = R.Canvas.new((1280, 720))
                if selw < 1.0:
                    cache.paint(side, rect, 1.0, 1.0 - selw, 0.0, animating=False)
                if selw > 0.0:
                    cache.paint(side, rect, 1.0, selw, 1.0, animating=False)
                diff = ImageChops.difference(canvas.image.getchannel(3), side.image.getchannel(3))
                self.assertLessEqual(diff.getextrema()[1], 1, "side at 1 - selw, then focus at selw")
                self.assertEqual(canvas.image.getpixel((600, 300))[3], 0)             # never under its card

    def test_each_layer_is_the_analytic_blurred_box(self):
        k = 2.0
        for kind, selw in (("side", 0.0), ("focus", 1.0)):
            with self.subTest(kind=kind):
                cache = R.ShadowCache(k)
                oy, blur, alpha = cache.shadow_params(kind)
                sigma = blur / 2 * k
                canvas = R.Canvas.new((2400, 1600))
                l, t = 700, 300
                r, b = l + round(R.CARD_W * k), t + round(R.CARD_H * k)
                cache.paint(canvas, (l, t, r, b), 1.0, 1.0, selw, animating=False)
                cx = (l + r) // 2
                for dy in (1, 20, 60, 100):
                    y = b + dy
                    u = y + 0.5 - t - oy * k
                    expected = 255 * alpha * (R._phi(u / sigma) - R._phi((u - R.CARD_H * k) / sigma))
                    self.assertAlmostEqual(canvas.image.getpixel((cx, y))[3], expected, delta=2.5)
                pad = cache._base(kind)[2]
                self.assertLessEqual(255 * alpha * R._phi(-pad / sigma), 0.5)          # nothing visible cut

    def test_b3a_bands_are_nearest_while_animating_and_bilinear_at_rest(self):
        cache = R.ShadowCache(1.5)
        cache._base("side")                                   # the base's own resizes are not bands
        seen = []
        real = R._core_resize

        def spy(image, size, resample, box):
            seen.append(resample)
            return real(image, size, resample, box)
        with patch.object(R, "_core_resize", spy):
            cache.paint(R.Canvas.new((1200, 700)), (400, 300, 1000, 675), 1.0, 1.0, 0.0, animating=True)
            moving = set(seen)
            seen.clear()
            cache.paint(R.Canvas.new((1200, 700)), (400, 300, 1000, 675), 1.0, 1.0, 0.0, animating=False)
        self.assertEqual(moving, {Image.Resampling.NEAREST})
        self.assertEqual(set(seen), {Image.Resampling.BILINEAR})

    def test_shadow_bands_equal_a_cropped_full_mask_and_clip_to_the_canvas(self):
        cache = R.ShadowCache(1.5)
        for rect, s, op, kind in (((400, 300, 1000, 675), 1.0, 1.0, "focus"), ((-80, 40, 250, 246), 0.55, 0.6, "side"),
                                  ((900, 500, 1180, 675), 0.4, 0.95, "side")):
            with self.subTest(rect=rect):
                canvas = R.Canvas.new((1200, 700))
                cache.paint(canvas, rect, s, op, 1.0 if kind == "focus" else 0.0, animating=False)
                small, full, pad, oy = cache._base(kind)
                mx, my, mw, mh = cache.placement(rect, s, kind)
                level = round(op * cache.LEVELS)
                source = small if level == cache.LEVELS else small.point(R._lut(level / cache.LEVELS))
                reference = R.Canvas.new((1200, 700))
                reference.over_mask((0, 0, 0), source.resize((mw, mh), Image.Resampling.BILINEAR), (mx, my),
                                    exclude=rect)
                diff = ImageChops.difference(canvas.image.getchannel(3), reference.image.getchannel(3))
                self.assertLessEqual(diff.getextrema()[1], 1)

    def test_shadow_cache_caches_rest_frames_only_and_trims(self):
        cache = R.ShadowCache(1.0)
        canvas = R.Canvas.new((1400, 800))
        for i in range(40):
            cache.paint(canvas, (300, 200, 700, 450), 0.3 + i / 100, 1.0, i / 40, animating=True)
        self.assertEqual(len(cache._cache), 0)          # animating frames never repeat: not cached
        for i in range(30):
            cache.paint(canvas, (300, 200, 700 + i, 450), 1.0, 1.0, 1.0, animating=False)
        self.assertLessEqual(len(cache._cache), 24)
        before = len(cache._cache)
        cache.paint(canvas, (300, 200, 729, 450), 1.0, 1.0, 1.0, animating=False)
        self.assertEqual(len(cache._cache), before)     # a repeated rest frame hits
        cache.trim()
        self.assertEqual(len(cache._cache), 0)
        self.assertEqual(set(cache._bases), {"side", "focus"})

    def test_b4_badge_scales_are_quantised_to_one_64th(self):
        self.assertEqual(R.quantised(0.5601), 36 / 64)
        self.assertEqual(R.quantised(0.0001), 1 / 64)
        scaler = R._SpriteScaler()
        layout = R.layout_for((0, 0, 1280, 720))
        badge = R.badge_sprite(None, "Slack", layout.k, ENGINE)
        for s in (0.560, 0.561, 0.562, 0.5625):
            x, _, op, shade = R.table_state(1)
            card = R.ChromeCard(R.card_rect(layout, x, s), s, op, shade, 0.0, badge)
            R.compose_chrome(R.Canvas.new((1280, 720)), R.ChromeScene(1.0, (0, 0), "glass", [card], [], True),
                             R.ShadowCache(1.0), scaler)
        self.assertEqual(len(scaler), 1, "one copy for every scale inside the same 1/64 step")

    def test_placeholder_cards_apply_their_group_opacity_once(self):
        layout = R.layout_for((0, 0, 1280, 720))
        k = layout.k
        white = Image.new("RGBA", (128, 128), (250, 250, 250, 255))
        holder = R.placeholder_sprite(white, "App", k)
        badge = R.badge_sprite(white, "App", k)
        for name, d, factor in (("closed centre", 0, R.CLOSED_OPACITY), ("side a=1", 1, 1.0), ("side a=2", 2, 1.0)):
            for animating in (True, False):
                with self.subTest(card=name, animating=animating):
                    x, s, op, shade = R.table_state(d)
                    op *= factor
                    rect = R.card_rect(layout, x, s)
                    card = R.ChromeCard(rect, s, op, shade, 1.0 if d == 0 else 0.0, (badge[0], badge[1]), holder, 0)
                    canvas = R.Canvas.new((1280, 720))
                    R.compose_chrome(canvas, R.ChromeScene(k, (0, 0), "glass", [card], [], animating), R.ShadowCache(k))
                    l, t, r, b = rect
                    want_a = round(255 * op)
                    icon = canvas.image.getpixel(((l + r) // 2, (t + b) // 2))
                    fill = canvas.image.getpixel((l + 3, t + 3))
                    for pixel in (icon, fill):
                        self.assertAlmostEqual(pixel[3], want_a, delta=1)
                    self.assertAlmostEqual(icon[2], op * ((1 - shade) * 250 + shade * 0x11), delta=1.5)
                    self.assertAlmostEqual(fill[2], op * ((1 - shade) * 0x1B + shade * 0x11), delta=1.5)


class TrayTests(unittest.TestCase):
    """The snap tray's chrome (K4 9.4): the 4 % slot background (only where no thumbnail shows),
    the three border looks, the empty glyph, the slot badge and the caption."""

    def compose(self, **slot):
        layout = R.layout_for((0, 0, 1280, 720))
        rect = R.slot_rect(layout, "left")
        defaults = dict(side="left", rect=rect, scale=1.0, opacity=1.0, fill=0.0, borders={"empty": 1.0}, glyph=1.0,
                        badge=None, badge_alpha=0.0,
                        caption=R.caption_sprite("2", "Snap left", R.CAPTION_INKS["normal"], 1.0, ENGINE),
                        glyph_sprite=R.slot_glyph_sprite("left", 1.0))
        defaults.update(slot)
        canvas = R.Canvas.new((1280, 720))
        drawn = R.compose_chrome(canvas, R.ChromeScene(1.0, (0, 0), "glass", [], [R.TraySlot(**defaults)]),
                                 R.ShadowCache(1.0))
        return rect, canvas.image, drawn

    def test_the_empty_slot(self):
        rect, image, drawn = self.compose()
        l, t, r, b = rect
        self.assertEqual((r - l, b - t), (176, 110))
        self.assertEqual(image.getpixel((l + 20, t + 20))[3], round(255 * R.SLOT_BG_A))    # rgba(255,255,255,.04)
        dashes = [image.getpixel((x, t - 1))[3] for x in range(l, l + 40)]
        self.assertIn(0, dashes, "a dashed border")
        self.assertIn(round(255 * 0.40), dashes)
        centre = image.getpixel(((l + r) // 2 - 1, (t + b) // 2))
        self.assertGreater(centre[3], 150, "the half glyph at 0.80")
        caption = image.crop((l, b + 1 + R.CAPTION_GAP, l + 120, b + 1 + R.CAPTION_GAP + R.CAPTION_H))
        self.assertGreater(caption.getchannel(3).getextrema()[1], 150)
        self.assertGreaterEqual(drawn[3], b + R.CAPTION_GAP + R.CAPTION_H)

    def test_a_filled_slot_shows_no_background_a_solid_border_and_the_badge(self):
        badge = R.slot_badge_sprite(Image.new("RGBA", (64, 64), (0, 200, 0, 255)), "App", 1.0, ENGINE)
        rect, image, _ = self.compose(fill=1.0, borders={"filled": 1.0}, glyph=0.0, badge=badge, badge_alpha=1.0)
        l, t, r, b = rect
        self.assertEqual(image.getpixel((l + 60, t + 20))[3], 0, "the thumbnail shows through: no 4 % over it")
        self.assertEqual({image.getpixel((x, t - 1))[3] for x in range(l, l + 40)}, {round(255 * 0.5)})
        pixel = image.getpixel((l + R.SLOT_BADGE_INSET + 5, b - R.SLOT_BADGE_INSET - 5))
        self.assertEqual((pixel[1], pixel[3]), (200, 255))

    def test_the_failure_border_and_caption_ink(self):
        caption = R.caption_sprite("2", "Couldn’t move Slack", R.CAPTION_INKS["failure"], 1.0, ENGINE)
        rect, image, _ = self.compose(borders={"failure": 1.0}, caption=caption)
        l, t, r, b = rect
        b_, g_, r_, a = image.getpixel((l + 10, t - 1))
        self.assertEqual(a, round(255 * 0.9))
        self.assertAlmostEqual(r_, round(255 * 0.9), delta=1)
        colours = caption.straight().convert("RGB").getcolors(1 << 16)
        self.assertTrue(any(rgb == (255, 132, 116) for _, rgb in colours), "#FF8474")

    def test_the_border_crossfade_and_the_tray_opacity(self):
        rect, image, _ = self.compose(borders={"empty": 0.5, "filled": 0.5}, opacity=0.5)
        l, t, r, b = rect
        self.assertLess(max(image.getpixel((x, t - 1))[3] for x in range(l, l + 40)), round(255 * 0.5 * 0.9))


class LabelTests(unittest.TestCase):
    """render_label: masked pastes only (K4 4.7.3), the r2.1 geometry (K4 9.3)."""

    def test_no_alpha_composite_over_64k_pixels(self):
        seen = []
        real = Image.alpha_composite

        def spy(a, b):
            seen.append(a.size[0] * a.size[1])
            return real(a, b)
        with patch.object(Image, "alpha_composite", spy):
            for background in ("glass", "none"):
                R.render_label(R.SimpleLabel("Slack", "Danny Lewis " * 5, "Direct message"),
                               Image.new("RGBA", (128, 128), (200, 0, 0, 255)), 2.0, background, ENGINE, R.SNAPPED_DESC["left"])
        self.assertTrue(all(n <= 64 * 1024 for n in seen), seen)

    def test_rows_colours_and_the_icon(self):
        label = R.render_label(R.SimpleLabel("Slack", "Danny Lewis", "Direct message"),
                               Image.new("RGBA", (128, 128), (200, 0, 0, 255)), 2.0, "glass", ENGINE)
        image = label.sprite.straight()
        alphas = sorted({a for *_, a in image.getdata() if a > 0})
        self.assertIn(255, alphas)
        self.assertTrue(any(round(255 * 0.92) - 2 <= a <= round(255 * 0.92) for a in alphas), "the app row at .92")
        self.assertTrue(any(round(255 * 0.86) - 2 <= a <= round(255 * 0.86) for a in alphas), "the description at .86")
        colours = image.convert("RGB").getcolors(1 << 20)
        self.assertTrue(any(r > 190 and g < 20 for _, (r, g, b) in colours), "the red icon, full opacity")
        self.assertIsNone(label.shadow)

    def test_no_background_adds_one_text_shadow_sprite_under_the_text(self):
        label = R.render_label(R.SimpleLabel("A", "Title", "Desc"), None, 2.0, "none", ENGINE)
        self.assertIsNotNone(label.shadow)
        self.assertEqual(label.shadow.size, label.sprite.size)
        self.assertEqual(label.shadow.colour[:3], (0, 0, 0))
        self.assertLessEqual(label.shadow.mask.getextrema()[1], round(255 * 0.6) + 1)

    def test_the_snapped_suffix(self):
        plain = R.render_label(R.SimpleLabel("A", "Title", "Desc"), None, 1.0, "glass", ENGINE)
        snapped = R.render_label(R.SimpleLabel("A", "Title", "Desc"), None, 1.0, "glass", ENGINE, R.SNAPPED_DESC["right"])
        self.assertGreater(snapped.sprite.size[0], plain.sprite.size[0])
        self.assertEqual(R.SNAPPED_DESC, {"left": " · Snapped left", "right": " · Snapped right"})
        self.assertEqual(R.SNAP_BADGE, {"left": "Left", "right": "Right"})

    def test_label_stays_in_its_900_unit_column_at_top_512(self):
        for k in (1.0, 2.0):
            long = R.SimpleLabel("A very long application name " * 4, "Title " * 60, "Description " * 20)
            sprite = R.render_label(long, None, k, "glass", ENGINE)
            left = R.LABEL_LEFT * k
            self.assertGreaterEqual(sprite.x, left - 3)
            self.assertLessEqual(sprite.x + sprite.sprite.size[0], left + R.LABEL_WIDTH * k + 3)
            self.assertGreaterEqual(sprite.y, R.LABEL_TOP * k - 3)
            self.assertLessEqual(sprite.y + sprite.sprite.size[1], (R.LABEL_TOP + R.LABEL_HEIGHT) * k + 3)

    def test_empty_label(self):
        sprite = R.render_label(R.SimpleLabel("", "", ""), None, 1.0, "glass", ENGINE)
        self.assertIsNotNone(sprite.sprite)          # the row-1 letter tile still shows


class ShowThroughTests(unittest.TestCase):
    """What farther cards drew inside a nearer card's rect (their shade, badge and shadow) shows
    through the nearer card as CSS opacity shows it: at 1 - op for a placeholder face, at 1 - o
    under a thumbnail card, and not at all under a card that is opaque inside a fading group
    (ChromeCard.cover). Canvas px = host-local px here (origin (0, 0))."""
    FACE = (R.PLACEHOLDER_RGB[2], R.PLACEHOLDER_RGB[1], R.PLACEHOLDER_RGB[0], 255)   # B, G, R, A

    def setUp(self):
        self.layout = R.layout_for((0, 0, 1280, 720))
        self.k = self.layout.k
        self.badge = R.badge_sprite(Image.new("RGBA", (128, 128), (250, 250, 250, 255)), "App", self.k, ENGINE)
        self.holder = R.placeholder_sprite(None, "Bambu Studio", self.k, ENGINE)

    def card(self, d, op=None, cover=None, placeholder=False):
        x, s, table_op, shade = R.table_state(d)
        return R.ChromeCard(R.card_rect(self.layout, x, s), s, table_op if op is None else op, shade,
                            1.0 if d == 0 else 0.0, self.badge, self.holder if placeholder else None, d, cover)

    def compose(self, cards):
        canvas = R.Canvas.new((1280, 720))
        R.compose_chrome(canvas, R.ChromeScene(self.k, (0, 0), "glass", list(cards)), R.ShadowCache(self.k))
        return canvas.image

    @staticmethod
    def inside(spot, card):
        l, t, r, b = card.rect
        return l <= spot[0] < r and t <= spot[1] < b

    def badge_spot(self, card):
        l, t, r, b = card.rect
        q = R.quantised(card.s)
        inset = round(R.BADGE_INSET * self.k * card.s + 15 * self.k * q)
        return (l + inset, b - inset)

    @staticmethod
    def shade_spot(card):
        l, t, r, b = card.rect
        return (l + 5, t + 20)

    def assertOver(self, got, top, alpha, below, keep, delta=1.6):
        for band in range(4):
            self.assertAlmostEqual(got[band], alpha * top[band] + keep * below[band], delta=delta,
                                   msg=f"band {band}: {got} vs {top} at {alpha} over {below} at {keep}")

    def test_a_closed_centre_card_keeps_the_side_card_under_it_at_65_percent(self):
        sides = [self.card(d) for d in (-2, 2, -1, 1)]
        right = sides[3]
        centre = self.card(0, op=R.CLOSED_OPACITY, placeholder=True)
        below, image = self.compose(sides), self.compose(sides + [centre])
        spot = self.shade_spot(right)
        self.assertTrue(self.inside(spot, centre) and self.inside(spot, right))
        under = below.getpixel(spot)
        self.assertGreater(under[3], 40)
        self.assertOver(image.getpixel(spot), self.FACE, R.CLOSED_OPACITY, under, 1 - R.CLOSED_OPACITY)

    def test_a_side_card_shows_the_farther_card_at_one_minus_o_under_its_shade(self):
        far, near = self.card(2), self.card(1)
        spot = (far.rect[0] + 20, far.rect[1] + 10) if far.rect[0] > near.rect[0] else (far.rect[2] - 20, far.rect[1] + 10)
        spot = next((x, far.rect[1] + 10) for x in range(far.rect[0], far.rect[2])
                    if self.inside((x, far.rect[1] + 10), near))
        under = self.compose([far]).getpixel(spot)
        self.assertGreater(under[3], 40)                        # the farther card's #111 shade
        got = self.compose([far, near]).getpixel(spot)
        o, alpha = R.thumb_opacity(0.95, 0.22), R.shade_alpha(0.95, 0.22)
        lut = R.fade_lut(1 - o, R.SHADE_RGB, alpha)
        self.assertEqual(got, tuple(lut[band * 256 + under[band]] for band in range(4)))
        self.assertAlmostEqual(got[3], 255 * alpha + (1 - 0.95) * under[3], delta=1.0)

    def test_an_opaque_card_in_a_fading_group_still_hides_what_is_under_it(self):
        g = 0.5
        side = self.card(1, op=0.95 * g, cover=0.95)
        spot = self.shade_spot(side)
        under = self.compose([side]).getpixel(spot)
        self.assertGreater(under[3], 20)
        centre = self.card(0, op=g, cover=1.0)                      # the root's fade
        self.assertTrue(self.inside(spot, centre))
        self.assertEqual(self.compose([side, centre]).getpixel(spot), (0, 0, 0, 0))
        alone = self.card(0, op=g)                                   # a card fading by itself (cover = op)
        self.assertAlmostEqual(self.compose([side, alone]).getpixel(spot)[3], (1 - g) * under[3], delta=1.0)
        closed = self.card(0, op=R.CLOSED_OPACITY * g, cover=R.CLOSED_OPACITY, placeholder=True)
        self.assertOver(self.compose([side, closed]).getpixel(spot), self.FACE, R.CLOSED_OPACITY * g, under,
                        1 - R.CLOSED_OPACITY)

    def test_canvas_content_fade_and_the_table(self):
        canvas = R.Canvas.new((8, 8))
        self.assertIsNone(canvas.content((0, 0, 8, 8)))
        canvas.fill((2, 3, 5, 4), (200, 100, 50), 0.5)
        box, pixels = canvas.content((-4, -4, 20, 20))
        self.assertEqual((box, pixels.size), ((2, 3, 5, 4), (3, 1)))
        before = canvas.image.getpixel((2, 3))
        canvas.fade((0, 0, 8, 8), 1.0)
        self.assertEqual(canvas.image.getpixel((2, 3)), before)
        canvas.fade((0, 0, 3, 8), 0.5)
        for got, was in zip(canvas.image.getpixel((2, 3)), before):
            self.assertAlmostEqual(got, was * 0.5, delta=1)
        self.assertEqual(canvas.image.getpixel((3, 3)), before)
        canvas.fade((0, 0, 8, 8), 0.0)
        self.assertIsNone(canvas.content((0, 0, 8, 8)))
        lut = R.fade_lut(0.3, R.SHADE_RGB, 0.2)
        self.assertEqual(len(lut), 1024)
        self.assertEqual(tuple(lut[band * 256] for band in range(4)), R._pm(R.SHADE_RGB, 0.2))
        self.assertIs(R.fade_lut(0.3, R.SHADE_RGB, 0.2), lut)
        image = Image.new("L", (3, 1), 200)
        self.assertEqual(list(R._point(image, R._lut(0.5)).getdata()), [100] * 3)     # the fast point


class TextTests(unittest.TestCase):
    def test_fit_uses_the_same_width_function_and_binary_search(self):
        title = "An extremely long window title that goes on and on well past the label column width " * 3
        limit = 900 * 2.0
        fitted = ENGINE.fit(title, 56, 600, -0.01, limit)
        self.assertTrue(fitted.endswith("…"))
        self.assertLessEqual(ENGINE.width(fitted, 56, 600, -0.01), limit)
        text = " ".join(title.split())
        low = max(n for n in range(len(text) + 1)
                  if ENGINE.width(text[:n].rstrip() + "…", 56, 600, -0.01) <= limit)
        self.assertEqual(fitted, text[:low].rstrip() + "…")       # the longest prefix that fits
        self.assertEqual(ENGINE.fit("Short", 56, 600, -0.01, limit), "Short")
        self.assertEqual(ENGINE.fit("Anything", 56, 600, 0.0, 5), "")
        self.assertEqual(ENGINE.fit("  two\n lines  ", 30, 400, 0.0, 1000), "two lines")

    def test_tracking_and_fractional_advances(self):
        plain = ENGINE.width("Window", 56, 600, 0.0)
        tracked = ENGINE.width("Window", 56, 600, -0.01)
        self.assertAlmostEqual(plain - tracked, 6 * 0.56, places=6)
        self.assertNotEqual(plain, round(plain))

    def test_archivo_cmap(self):
        cover = R.coverage(R.ARCHIVO_PATH)
        for ch in "AZaz09 …·’":
            self.assertIn(ord(ch), cover, ch)
        for ch in "中П\U0001F600":
            self.assertNotIn(ord(ch), cover)
        self.assertEqual(ENGINE.font_for("A", 600).name, "Archivo")

    @unittest.skipUnless(HAVE_FALLBACKS, "Windows fallback fonts are not installed")
    def test_per_glyph_fallback_has_no_tofu(self):
        samples = {"Привет": ("segoeui", "seguisb"),
                   "Αθήνα": ("segoeui", "seguisb"),
                   "中文标题": ("msyh",), "한국어": ("malgun",),
                   "😀🚀": ("seguiemj",), "❤️": ("seguiemj",)}
        for text, family in samples.items():
            for wght in (400, 600):
                glyphs = ENGINE.glyphs(text, wght)
                self.assertTrue(glyphs)
                for ch, spec in glyphs:
                    with self.subTest(ch=ascii(ch), wght=wght):
                        self.assertIn(ord(ch), R.coverage(spec.path, spec.index))
                        self.assertNotEqual(spec.name, "Archivo")
                self.assertTrue(glyphs[0][1].name.lower().startswith(family), (ascii(text), glyphs[0][1].name))
                self.assertEqual(len(glyphs), len([ch for ch in text if ch != "️"]))
        self.assertEqual(ENGINE.font_for("П", 600).name, "seguisb.ttf")
        self.assertTrue(ENGINE.font_for("\U0001F600", 400, emoji=True).colour)

    def test_emoji_presentation_covers_bmp_emoji_and_the_variation_selectors(self):
        emoji = R.emoji_presentation
        for text in ("✅", "⭐", "⚡", "❌", "☕", "⌛", "⏳", "❓",
                     "\U0001F680", "❤️", "#️"):
            with self.subTest(text=ascii(text)):
                self.assertTrue(emoji(text, 0))
        for text in ("A", "❤", "✅︎", "\U0001F680︎", "·", "✓", "☀", "中"):
            with self.subTest(text=ascii(text)):
                self.assertFalse(emoji(text, 0))
        self.assertTrue(emoji("ok ✅ done", 3))
        self.assertEqual([start for start, _ in R.EMOJI_PRESENTATION_BMP],
                         sorted(start for start, _ in R.EMOJI_PRESENTATION_BMP))

    @unittest.skipUnless(HAVE_FALLBACKS, "Windows fallback fonts are not installed")
    def test_bmp_emoji_draw_in_colour_without_vs16(self):
        for text in ("✅", "⭐", "⚡", "❌", "☕", "⌛"):
            with self.subTest(text=ascii(text)):
                (ch, spec), = ENGINE.glyphs(text, 400)
                self.assertEqual(spec.name, "seguiemj.ttf")
                self.assertTrue(spec.colour)
        (ch, spec), = ENGINE.glyphs("✅︎", 400)                  # VS15: text presentation
        self.assertFalse(spec.colour)
        (ch, spec), = ENGINE.glyphs("❤", 400)                        # text by default
        self.assertFalse(spec.colour)
        label = R.render_label(R.SimpleLabel("App", "Done ✅", ""), None, 1.0, "glass", ENGINE)
        colours = label.sprite.straight().convert("RGB").getcolors(1 << 20)
        self.assertTrue(any(g > 120 and g > r + 40 for _, (r, g, b) in colours))   # the green check mark

    @unittest.skipUnless(HAVE_FALLBACKS, "Windows fallback fonts are not installed")
    def test_mixed_script_label_renders_every_row(self):
        label = R.SimpleLabel("Slack", "Привет 中文 한국어 \U0001F600",
                              "Direct message")
        sprite = R.render_label(label, None, 2.0, "glass", ENGINE)
        image = sprite.sprite.straight()
        self.assertGreater(image.size[0], 500)
        colours = image.convert("RGB").getcolors(1 << 20)
        self.assertTrue(any(r > 200 and b < 120 for _, (r, g, b) in colours))   # the colour emoji


class LetterTileTests(unittest.TestCase):
    def test_stub_tile_letter_colour_and_contrast(self):
        tile = R.stub_letter_tile("bambu studio", 64, ENGINE)
        self.assertEqual((tile.size, tile.mode), ((64, 64), "RGBA"))
        corner = tile.getpixel((1, 1))
        self.assertEqual(corner[:3], R.tile_colour("Bambu Studio"))
        self.assertTrue(any(p[:3] == (255, 255, 255) for p in tile.getdata()))
        for name in ("Bambu Studio", "File Explorer", "Steam", "Notepad", "Some Tool", "x", "中文"):
            self.assertGreaterEqual(R.white_contrast(R.tile_colour(name)), 3.0, name)
        self.assertEqual(R.tile_colour("Notepad"), R.tile_colour("  notepad "))
        self.assertLess(R.white_contrast((0xE8, 0xB6, 0x4A)), 3.0)          # the design's colour fails ...
        self.assertGreaterEqual(R.white_contrast(R.tile_colour("File Explorer")), 3.0)   # ... so it is darkened

    def test_letter_tile_prefers_window_facts_and_keeps_the_size(self):
        tile = R.letter_tile("Claude", 36, ENGINE)
        self.assertEqual((tile.size, tile.mode), ((36, 36), "RGBA"))


class SelfTestTests(unittest.TestCase):
    def test_window_free_self_test_passes_and_reports_no_text(self):
        from control_center import carousel
        report = carousel.self_test(hidden_windows=False, k=1.0)
        self.assertTrue(report["ok"], report)
        self.assertNotIn("windows", report)
        self.assertTrue({"glass_ok", "label_ok", "tile_ok", "glass_ms", "label_ms"} <= set(report))
        self.assertTrue(all(isinstance(name, str) and name.endswith((".ttf", ".ttc")) or name == "Archivo"
                            for name in report["label_fonts"]))


class ToastAndDotsTests(unittest.TestCase):
    def test_toast_padding_border_glass_and_fallback(self):
        text = "Slack · Danny Lewis"
        for k in (1.0, 2.0):
            w, h = R.toast_size(text, k, ENGINE)
            text_w = ENGINE.width(text, 15 * k, 400)
            self.assertAlmostEqual(w, text_w + 36 * k + 2 * max(1, round(k)), delta=1.01)
            self.assertAlmostEqual(h, (15 * R.LINE_NORMAL + 24) * k + 2 * max(1, round(k)), delta=1.01)
        plain = R.render_toast(text, 2.0, None, ENGINE)
        self.assertEqual(plain.getpixel((plain.width // 2, 6))[3], round(255 * R.TOAST_FALLBACK_A))
        # the pill is premultiplied (WP7b-R6): its bytes are exactly the tint at 88 %; the
        # straight view is Pillow's truncating unpremultiply of them (within one level)
        pill = R.render_toast_canvas(text, 2.0, None, ENGINE)
        self.assertEqual(pill.image.getpixel((plain.width // 2, 6)), R._pm(R.TOAST_TINT, R.TOAST_FALLBACK_A))
        for got, want in zip(plain.getpixel((plain.width // 2, 6))[:3], (24, 24, 26)):   # blur.toast's tint
            self.assertLessEqual(abs(got - want), 1)
        self.assertEqual((R.TOAST_TINT, R.TOAST_TINT_A), ((24, 24, 26), 0.62))
        backdrop = synthetic_desktop(plain.size)
        glass = R.render_toast(text, 2.0, backdrop, ENGINE)
        self.assertEqual(glass.size, plain.size)
        self.assertEqual(glass.getchannel("A").getextrema(), (255, 255))
        layout = R.layout_for((0, 0, 5120, 1440))
        x, y, w, h = R.toast_rect(layout, (400, 80))
        self.assertEqual((x + w / 2, y), (2560, 1176))                                  # top 588 at k = 2

    MAX_TOAST = "Google Chrome" + R.SEP + "🎵 " + "Synthetic tab title words " * 40

    def test_the_toast_pill_never_alpha_composites(self):
        """WP7b-R6 (K4 4.7.3): a fitted pill at k = 2 is over 64 K px, and it is rendered while
        a toast (and possibly the floating knob) animates: fills and masked pastes only."""
        seen = []
        real = Image.alpha_composite

        def spy(a, b, *args):
            seen.append(a.size[0] * a.size[1])
            return real(a, b, *args)
        with patch.object(Image, "alpha_composite", spy), patch.object(Image.Image, "alpha_composite",
                                                                        lambda *a, **k: seen.append(-1)):
            for backdrop in (None, synthetic_desktop((600, 90))):
                pill = R.render_toast_canvas(self.MAX_TOAST, 2.0, backdrop, ENGINE)
                self.assertGreater(pill.size[0] * pill.size[1], 64 * 1024, "the case the rule is about")
                R.render_toast(self.MAX_TOAST, 2.0, backdrop, ENGINE)
        self.assertEqual(seen, [])

    @staticmethod
    def reference_pill(text, k, backdrop):
        """The v7 pill as WP7b first built it (straight RGBA with alpha_composite): the look to keep."""
        text = R.fit_toast_text(text, k, ENGINE)
        w, h = R.toast_size(text, k, ENGINE)
        if backdrop is not None:
            base = R.toast_backdrop(backdrop.resize((w, h)) if backdrop.size != (w, h) else backdrop, k)
        else:
            base = Image.new("RGBA", (w, h), R.TOAST_TINT + (round(255 * R.TOAST_FALLBACK_A),))
        border = max(1, round(k))
        edges = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(edges).rectangle((0, 0, w - 1, h - 1), outline=(255, 255, 255, round(255 * R.TOAST_BORDER_A)),
                                        width=border)
        image = Image.alpha_composite(base, edges)
        px = R.TOAST_PX * k
        mask = Image.new("L", (w, h), 0)
        colour = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ENGINE.draw(text, border + R.TOAST_PAD_X * k, R.baseline_in(border + R.TOAST_PAD_Y * k, R.LINE_NORMAL * px, px),
                    px, 400, 0.0, mask, colour)
        white = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        white.putalpha(mask)
        image = Image.alpha_composite(image, white)
        colour = Image.frombuffer("RGBa", (w, h), colour.tobytes(), "raw", "RGBa", 0, 1).convert("RGBA")
        if colour.getbbox():
            image = Image.alpha_composite(image, colour)
        return image

    def test_the_masked_paste_pill_looks_like_the_alpha_composite_one(self):
        """WP7b-R6: premultiplied masked pastes are an exact "over"; against the straight
        alpha_composite pill every channel stays within 2 levels (rounding) on both bases."""
        for text, backdrop in (("Slack · Danny Lewis", None), ("Slack · Danny Lewis", synthetic_desktop((500, 90))),
                               (self.MAX_TOAST, synthetic_desktop((1900, 90)))):
            with self.subTest(text=text[:20], glass=backdrop is not None):
                want = R.premultiplied_bgra(self.reference_pill(text, 2.0, backdrop))
                got = R.render_toast_canvas(text, 2.0, backdrop, ENGINE)
                ref = Image.frombuffer("RGBX", got.size, want, "raw", "RGBX", 0, 1)
                for band in range(4):
                    diff = ImageChops.difference(got.image.getchannel(band), ref.getchannel(band))
                    self.assertLessEqual(diff.getextrema()[1], 2, f"band {band}")

    def test_long_toast_text_is_fitted_keeping_the_app_and_stays_on_the_monitor(self):
        for n in (80, 200, 400):
            title = ("Synthetic tab title words " * 40)[:n]
            text = "Google Chrome" + R.SEP + title
            for monitor in ((0, 0, 1920, 1080), (0, 0, 5120, 1440), (-1280, 0, 0, 720)):
                with self.subTest(chars=n, monitor=monitor):
                    layout = R.layout_for(monitor)
                    k = layout.k
                    fitted = R.fit_toast_text(text, k, ENGINE)
                    self.assertLessEqual(ENGINE.width(fitted, R.TOAST_PX * k, 400), R.TOAST_TEXT_MAX * k + 1e-6)
                    self.assertTrue(fitted.startswith("Google Chrome" + R.SEP), fitted[:20])
                    self.assertEqual(R.fit_toast_text(fitted, k, ENGINE), fitted)          # idempotent
                    size = R.toast_size(text, k, ENGINE)
                    x, y, w, h = R.toast_rect(layout, size)
                    self.assertGreaterEqual(x, monitor[0])
                    self.assertLessEqual(x + w, monitor[2])
                    self.assertLessEqual(y + h, monitor[3])
        huge_app = "Application " * 40 + R.SEP + "Title"
        fitted = R.fit_toast_text(huge_app, 1.0, ENGINE)
        self.assertTrue(fitted.endswith("…"))

    def test_the_dots_row_is_fixed_squares_centred_with_a_separate_marker(self):
        first, shown, opacities = R.dots_window(3, 1)
        self.assertEqual((first, shown, opacities), (0, 3, (0.4, 0.4, 0.4)))
        self.assertEqual(R.dots_width(3), 34)
        sprite, x, y = R.render_dots(opacities, 2.0)
        self.assertEqual(sprite.size, (68, 12))
        self.assertAlmostEqual(x + 34, R.CENTER_X * 2, delta=1)
        self.assertEqual(y, R.DOTS_TOP * 2)
        row = [sprite.mask.getpixel((i, 6)) for i in range(68)]
        self.assertEqual(max(row), round(255 * 0.4))
        self.assertEqual(row[12:28], [0] * 16)                                         # the 8-unit gap
        self.assertIsNone(R.render_dots((), 2.0))
        self.assertEqual(R.marker_sprite(2.0).size, (12, 12))
        self.assertEqual(R.marker_x(3, 1), R.CENTER_X - 17 + 14)

    def test_long_lists_show_an_82_dot_window_with_fading_ends(self):
        self.assertEqual(R.DOTS_CAP, 82)
        first, shown, opacities = R.dots_window(200, 100)
        self.assertEqual((first, shown), (59, 82))
        self.assertEqual(opacities[:3], (0.10, 0.20, 0.30))
        self.assertEqual(opacities[-3:], (0.30, 0.20, 0.10))
        first, shown, opacities = R.dots_window(200, 5)
        self.assertEqual((first, opacities[:3], opacities[-3:]), (0, (0.4, 0.4, 0.4), (0.30, 0.20, 0.10)))
        first, _, opacities = R.dots_window(200, 199)
        self.assertEqual((first, opacities[-3:]), (118, (0.4, 0.4, 0.4)))
        self.assertLessEqual(R.dots_width(82), 1280 - 128)


if __name__ == "__main__":
    unittest.main()

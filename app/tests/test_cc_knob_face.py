"""knob_face: the desktop v5 floating knob compositor and ring colour model (FLOATING_KNOB.md 2 and 7).

Headless (Pillow only, no Tk, no window). The benchmark logs KnobFace.compose
at 100 % and 200 % DPI on this PC, for a steady ring (warm sprite caches) and
for churning rings (every segment's colour and level new each frame; a
PreviewLights decay/pulse/flash sequence), and asserts loose bounds (the budget
is 8 ms).
"""
import json
import logging
import math
from pathlib import Path
import random
import statistics
import sys
import time
import unittest

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import knob_face as kf
from control_center import lcd_preview as lp
from control_center.presentation import (
    LED_AMBER, LED_GREEN, LED_RED, LED_VOLUME_RED, LED_WHITE, LEVELS, RING_SEGMENTS,
)
from control_center.preview_lights import PreviewLights, ease, peak, scale, toward

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / 'tests' / 'fixtures' / 'cc5_frames.json').read_text(encoding='utf-8'))
CASES = {case['id']: case for case in FIXTURES['cases']}
DPI_100, DPI_200 = 96, 192
DPIS = (96, 120, 144, 168, 192)          # 100 .. 200 %; 150 % and 175 % give an odd lcd_px
BUDGET_MS = 8.0
LOOSE_MS = 25.0          # the assertion; the log line shows the real figure


def lit(rgb=(255, 255, 255), level=1.0):
    return [tuple(rgb) + (level,)] * RING_SEGMENTS


def at_design(face, radius, degrees):
    """Pixel (x, y) at ``radius`` design px, ``degrees`` clockwise from twelve o'clock."""
    cx, cy = face.origin
    theta = math.radians(degrees)
    return (int(math.floor(cx + math.sin(theta) * radius * face.scale)),
            int(math.floor(cy - math.cos(theta) * radius * face.scale)))


def centroid(channel):
    """Value-weighted centroid (x, y) of an L image, in continuous px (pixel i spans [i, i + 1))."""
    values = channel.convert('F')
    width, height = values.size
    cols = values.resize((width, 1), Image.Resampling.BOX).get_flattened_data()
    rows = values.resize((1, height), Image.Resampling.BOX).get_flattened_data()
    return (sum((x + .5) * v for x, v in enumerate(cols)) / sum(cols),
            sum((y + .5) * v for y, v in enumerate(rows)) / sum(rows))


class _FrozenUiColourModel:
    """The ring colour model exactly as control_center/ui.py had it before the v5 move.

    Copied from ui.py in backups/source-snapshots/desktop-v5-start-20260924T205045Z.zip
    (constants at lines 95-105, functions at lines 250-347; only docstrings dropped
    and module names scoped to the class as ``cls.``), so the move to knob_face is
    checked against the old code, not against ui.py's re-export of knob_face.
    Do not "fix" or refactor this copy.
    """
    SEGMENT_OFF = "#1f1f1f"
    STRIP_OFF = "#262626"
    OPTICAL_ALPHA = (0.0, 0.12, 0.34, 0.68, 1.0)
    LED_FLOOR = 31                  # rgb(31,31,31), an unlit segment
    BUTTON_FACE = 0x20              # strips are rgba(colour, max(a, .18)) over #202020
    STRIP_MIN_ALPHA = 0.18
    LED_PALETTE = (LED_WHITE, LED_GREEN, LED_RED, LED_AMBER, LED_VOLUME_RED)
    LED_MATCH_TOLERANCE = 2         # per channel, drive rounding and decay truncation

    @staticmethod
    def _channels(color):
        return (color >> 16) & 255, (color >> 8) & 255, color & 255

    @staticmethod
    def _pack(r, g, b):
        return (r << 16) | (g << 8) | b

    @classmethod
    def optical_alpha(cls, level):
        if level <= 0:
            return 0.0
        for k in range(1, len(LEVELS)):
            if level <= LEVELS[k]:
                low, high = LEVELS[k - 1], LEVELS[k]
                return cls.OPTICAL_ALPHA[k - 1] + (cls.OPTICAL_ALPHA[k] - cls.OPTICAL_ALPHA[k - 1]) * (level - low) / (high - low)
        return 1.0

    @classmethod
    def led_source(cls, drive, palette=LED_PALETTE):
        if not drive:
            return 0, 0
        drive_peak = peak(drive)
        wanted = cls._channels(drive)
        best = None
        for colour in palette:
            colour_peak = peak(colour) if colour else 0
            if not colour_peak:
                continue
            level = min(255, round(drive_peak * 255 / colour_peak))
            error = max(abs(a - b) for a, b in zip(cls._channels(scale(colour, level)), wanted))
            if error <= cls.LED_MATCH_TOLERANCE and (best is None or error < best[0]):
                best = (error, colour, level)
                if not error:
                    break
        if best is not None:
            return best[1], best[2]
        return cls._pack(*(min(255, round(ch * 255 / drive_peak)) for ch in wanted)), drive_peak

    @classmethod
    def _mix_hex(cls, colour, alpha, base):
        return "#" + "".join(f"{round(base + (ch - base) * alpha):02x}" for ch in cls._channels(colour))

    @classmethod
    def ring_display(cls, drive, palette=LED_PALETTE):
        if not drive:
            return cls.SEGMENT_OFF
        colour, level = cls.led_source(drive, palette)
        return cls._mix_hex(colour, cls.optical_alpha(level), cls.LED_FLOOR)

    @classmethod
    def strip_display(cls, drive, palette=LED_PALETTE):
        if not drive:
            return cls.STRIP_OFF
        colour, level = cls.led_source(drive, palette)
        return cls._mix_hex(colour, max(cls.optical_alpha(level), cls.STRIP_MIN_ALPHA), cls.BUTTON_FACE)

    @classmethod
    def ring_palette(cls, frame):
        ring = frame.get("ring") if isinstance(frame.get("ring"), dict) else {}
        colors = ring.get("colors") if isinstance(ring.get("colors"), list) else []
        return cls.LED_PALETTE + tuple(c for c in colors if type(c) is int and 0 < c <= 0xFFFFFF)


OLD = _FrozenUiColourModel


def model_drives():
    """Settled palette drives, decays toward dark, off-palette colours and fixture accents."""
    rng = random.Random(7)
    drives = [0] + [scale(c, level) for c in OLD.LED_PALETTE for level in range(0, 256, 3)]
    drives += [toward(scale(c, level), 0, ease(t, 260)) for c in OLD.LED_PALETTE
               for level in (40, 90, 200, 255) for t in (20, 60, 140, 230)]          # decays to dark
    drives += [toward(scale(a, 255), scale(b, 90), ease(t, 260)) for a in OLD.LED_PALETTE
               for b in OLD.LED_PALETTE if a != b for t in (30, 150)]                  # colour to colour
    drives += [rng.randrange(1, 0x1000000) for _ in range(300)]
    return drives


class ColourModelTests(unittest.TestCase):
    def test_optical_mapping_and_display_colours(self):
        for level, alpha in zip(LEVELS, kf.OPTICAL_ALPHA):
            self.assertAlmostEqual(kf.optical_alpha(level), alpha)
        self.assertEqual(kf.ring_display(0), kf.SEGMENT_OFF)
        self.assertEqual(kf.ring_display(scale(LED_WHITE, LEVELS[4])), '#ffffff')
        self.assertEqual(kf.ring_display(scale(LED_WHITE, LEVELS[2])), '#6b6b6b')
        self.assertEqual(kf.strip_display(scale(LED_WHITE, LEVELS[1])), '#484848')
        self.assertEqual(kf.led_source(scale(LED_AMBER, LEVELS[3])), (LED_AMBER, LEVELS[3]))

    def test_same_behaviour_as_the_pre_move_ui_colour_model(self):
        """knob_face against a frozen copy of the old ui.py functions (not ui's re-export)."""
        self.assertEqual(kf.OPTICAL_ALPHA, OLD.OPTICAL_ALPHA)
        self.assertEqual(kf.LED_PALETTE, OLD.LED_PALETTE)
        self.assertEqual((kf.SEGMENT_OFF, kf.STRIP_OFF), (OLD.SEGMENT_OFF, OLD.STRIP_OFF))
        drives = model_drives()
        frames = [{}, {'ring': {'colors': [0x3366FF, 0x00FF88, 'bad', 0, True, 0x1000000]}},
                  {'ring': 'bad'}] + [case['frame'] for case in FIXTURES['cases'] if case['frame']]
        palettes = set()
        for frame in frames:
            palette = kf.ring_palette(frame)
            self.assertEqual(palette, OLD.ring_palette(frame))
            palettes.add(palette)
        self.assertGreater(len(palettes), 3)                    # fixture accents are covered
        compared = 0
        for palette in palettes:
            for drive in drives:
                self.assertEqual(kf.ring_display(drive, palette), OLD.ring_display(drive, palette), hex(drive))
                self.assertEqual(kf.led_source(drive, palette), OLD.led_source(drive, palette), hex(drive))
                self.assertEqual(kf.strip_display(drive, palette), OLD.strip_display(drive, palette), hex(drive))
                compared += 1
        for drive in drives:                                     # the default palette argument
            self.assertEqual(kf.ring_display(drive), OLD.ring_display(drive), hex(drive))
            self.assertEqual(kf.strip_display(drive), OLD.strip_display(drive), hex(drive))
        for level in range(-1, 257):
            self.assertEqual(kf.optical_alpha(level), OLD.optical_alpha(level), level)
        self.assertGreater(compared, 5000)

    def test_ui_re_exports_the_knob_face_model(self):
        try:
            from control_center import ui
        except Exception as error:  # pragma: no cover - ui needs tkinter importable
            self.skipTest(f'ui not importable: {error}')
        for name in ('optical_alpha', 'led_source', 'ring_display', 'ring_palette', 'strip_display'):
            self.assertIs(getattr(ui, name), getattr(kf, name), name)

    def test_colour_model_and_ui_import_without_pil(self):
        # Pre-v5 ui.py imported PIL only inside functions ("a broken renderer only
        # blanks the mirror"); knob_face keeps that: Pillow loads on first KnobFace.
        import subprocess
        code = (
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from control_center import knob_face as kf\n"
            "assert 'PIL' not in sys.modules, 'knob_face imported PIL'\n"
            "assert kf.ring_colors({}, [0xFF0000])[0] == (255, 0, 0, 1.0)\n"
            "assert kf.ring_display(0x00FF00) and kf.optical_alpha(255) == 1.0\n"
            "from control_center import ui\n"
            "assert 'PIL' not in sys.modules, 'ui imported PIL'\n"
            "assert ui.ring_display is kf.ring_display\n"
            "sys.modules['PIL'] = None\n"            # a broken Pillow: only the face fails
            "try:\n"
            "    kf.KnobFace(1.0)\n"
            "except ImportError:\n"
            "    print('OK')\n"
        )
        done = subprocess.run([sys.executable, '-I', '-c', code, str(ROOT)], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, 'OK'), done.stderr[-2000:])

    def test_ring_colors_are_the_display_colours_with_their_level(self):
        for case_id in ('led-vol-86', 'led-vol-96', 'led-recent', 'led-win-claude', 'home', 'ra-item'):
            frame = CASES[case_id]['frame']
            drives, _ = PreviewLights().render(frame, 0, 0)
            colours = kf.ring_colors(frame, drives)
            self.assertEqual(len(colours), RING_SEGMENTS)
            palette = OLD.ring_palette(frame)
            for drive, (r, g, b, level) in zip(drives, colours):
                with self.subTest(case=case_id, drive=hex(drive)):
                    self.assertEqual('#%02x%02x%02x' % (r, g, b), OLD.ring_display(drive, palette))
                    expected = OLD.optical_alpha(OLD.led_source(drive, palette)[1]) if drive else 0.0
                    self.assertAlmostEqual(level, expected)
        led = kf.ring_colors(CASES['led-vol-86']['frame'],
                             PreviewLights().render(CASES['led-vol-86']['frame'], 0, 0)[0])
        self.assertIn(kf.UNLIT, led)
        self.assertTrue(any(level > 0 for *_, level in led))

    def test_ring_colors_use_frame_accents_and_tolerate_odd_input(self):
        accent = 0x3366FF
        frame = {'ring': {'colors': [accent]}}
        drive = scale(accent, LEVELS[4])
        self.assertEqual(kf.ring_colors(frame, [drive])[0], (0x33, 0x66, 0xFF, 1.0))
        self.assertEqual(kf.ring_colors(None, [])[5], kf.UNLIT)
        self.assertEqual(len(kf.ring_colors({}, [LED_WHITE] * 70)), RING_SEGMENTS)


class GeometryTests(unittest.TestCase):
    def test_scale_maps_the_ring_diameter_to_360_logical_px(self):
        self.assertAlmostEqual(kf.scale_for(96), 360 / 286)
        self.assertAlmostEqual(kf.scale_for(192), 720 / 286)
        self.assertAlmostEqual(kf.scale_for(144, ring_logical_px=400), 400 / 286 * 1.5)
        for bad in (0, -96, True, None, '96'):
            with self.subTest(dpi=bad), self.assertRaises(ValueError):
                kf.scale_for(bad)
        for bad in (0, -1.0, float('nan'), float('inf'), False):
            with self.subTest(scale=bad), self.assertRaises(ValueError):
                kf.KnobFace(bad)

    def test_box_centre_and_lcd_size(self):
        odd = 0
        for dpi in DPIS:
            s = kf.scale_for(dpi)
            face = kf.KnobFace(s)
            with self.subTest(dpi=dpi):
                width, height = face.size
                self.assertEqual((width % 2, height % 2, width), (0, 0, height))
                self.assertEqual(face.center, (width // 2, height // 2))
                self.assertEqual(face.lcd_px, round(240 * s))
                self.assertEqual(face.lcd_px, lp.lcd_pixels(s))
                offset = 0.5 * (face.lcd_px % 2)
                self.assertEqual(face.origin, (face.center[0] + offset, face.center[1] + offset))
                odd += face.lcd_px % 2
                margin = kf.FACE_EXTENT * s                          # plate + shadow on every side
                self.assertGreaterEqual(min(face.origin[0], width - face.origin[0]), margin)
                self.assertGreaterEqual(width, 2 * (kf.PLATE_RADIUS + kf.SHADOW_OFFSET[1]) * s)
        self.assertEqual(odd, 2)                                      # 150 % (453) and 175 % (529)

    def test_lcd_disc_ring_and_plate_share_one_centre(self):
        """The whole-pixel LCD is centred on the knob at every DPI, odd lcd_px included.

        Before the fix an odd LCD (150 %: 453 px, 175 %: 529 px) sat 0.5 px right and down
        of the disc and ring, and the Pillow ellipse truncation put the plate 1/8 px up-left.
        """
        red = (200, 30, 60)
        for dpi in DPIS:
            face = kf.KnobFace(kf.scale_for(dpi))
            px = face.lcd_px
            frame = face.compose(Image.new('RGBA', (px, px), red + (255,)), lit(level=0.0))
            with self.subTest(dpi=dpi, lcd_px=px):
                # The LCD square: its exact pixel box, centred on origin.
                diff = ImageChops.difference(frame.convert('RGB'), Image.new('RGB', face.size, red))
                exact = Image.eval(ImageChops.add(ImageChops.add(*diff.split()[:2]), diff.split()[2]),
                                   lambda v: 255 if v == 0 else 0)
                left, top, right, bottom = exact.getbbox()
                self.assertEqual((right - left, bottom - top), (px, px))
                self.assertEqual(((left + right) / 2, (top + bottom) / 2), face.origin)
                # The 60 white segment bodies (and the disc edge they surround) around the same point.
                ring = centroid(Image.eval(frame.getchannel('G'), lambda v: v if v > 40 else 0))
                for got, want in zip(ring, face.origin):
                    self.assertAlmostEqual(got, want, delta=0.15)
                # The plate + shadow alpha: symmetric left-right about origin (the shadow drops 3 px).
                self.assertAlmostEqual(centroid(frame.getchannel('A'))[0], face.origin[0], delta=0.02)
                # The disc: its #0a0a0a band is as wide left of the LCD as right of it.
                row = frame.crop((0, int(face.origin[1]), face.size[0], int(face.origin[1]) + 1)).convert('RGB')
                disc = [x for x, pixel in enumerate(row.get_flattened_data()) if pixel == kf.DISC_RGB]
                self.assertEqual(left - min(disc), max(disc) + 1 - right)

    def test_outer_segment_ends_span_360_logical_px(self):
        for dpi in (96, 144, 192):
            face = kf.KnobFace(kf.scale_for(dpi))
            frame = face.compose(None, lit(level=0.0))          # white bodies, no glow
            white = frame.convert('RGB').point(lambda v: 255 if v > 200 else 0).convert('L')
            left, top, right, bottom = white.getbbox()
            with self.subTest(dpi=dpi):
                self.assertAlmostEqual(bottom - top, 360 * dpi / 96, delta=2)    # 12 and 6 o'clock
                self.assertAlmostEqual(right - left, 360 * dpi / 96, delta=2)    # 9 and 3 o'clock


class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.face = kf.KnobFace(kf.scale_for(DPI_100))
        cls.dark = cls.face.compose(None, [])                    # every segment unlit
        cls.white = cls.face.compose(None, lit())

    def test_outside_is_transparent(self):
        width, height = self.face.size
        for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            self.assertEqual(self.white.getpixel(corner)[3], 0)
        cx, cy = self.face.center
        limit = kf.FACE_EXTENT * self.face.scale
        alpha = self.white.getchannel('A').load()
        for y in range(0, height, 3):
            for x in range(0, width, 3):
                if math.hypot(x + .5 - cx, y + .5 - cy) > limit + 1:
                    self.assertEqual(alpha[x, y], 0, (x, y))

    def test_plate_and_shadow(self):
        plate = self.dark.getpixel(at_design(self.face, 149, 45))
        for channel, expected in zip(plate[:3], kf.PLATE_RGB):   # straight alpha over the shadow
            self.assertAlmostEqual(channel, expected, delta=1)
        self.assertGreaterEqual(plate[3], kf.PLATE_ALPHA)
        below = self.dark.getpixel(at_design(self.face, 160, 180))
        above = self.dark.getpixel(at_design(self.face, 160, 0))
        self.assertGreater(below[3], above[3])                   # offset 0,3: stronger below
        self.assertGreater(above[3], 0)
        self.assertLessEqual(max(below[3], above[3]), kf.SHADOW_ALPHA)
        self.assertEqual(below[:3], (0, 0, 0))                    # black shadow, straight alpha

    def test_segments_are_anti_aliased(self):
        for index, (_, body, _) in enumerate(self.face._segments):
            values = set(body.tobytes())
            self.assertIn(255, values, index)
            self.assertTrue(any(0 < v < 255 for v in values), index)
        # Diagonal segment 7 (42 deg): its box shows many levels between the plate and white.
        (x, y), body, _ = self.face._segments[7]
        region = self.white.crop((x, y, x + body.width, y + body.height)).getchannel('R')
        self.assertGreater(len({v for v in region.tobytes() if 30 < v < 240}), 10)
        # The body colour is the given one in the segment's middle: exact at 200 % (the LANCZOS
        # kernel of the 4x masks does not reach it), within a few levels of ringing on the 5 px
        # wide segments at 100 %.
        for face, tolerance in ((self.face, 3), (kf.KnobFace(kf.scale_for(DPI_200)), 0)):
            centre = at_design(face, kf.RING_RADIUS, 0)
            for colour in ((255, 255, 255), (255, 150, 30)):
                with self.subTest(scale=face.scale, colour=colour):
                    pixel = face.compose(None, lit(colour, 0.68)).getpixel(centre)
                    self.assertEqual(pixel[3], 255)
                    for got, want in zip(pixel[:3], colour):
                        self.assertAlmostEqual(got, want, delta=tolerance)

    def test_glow_is_clipped_by_the_disc(self):
        disc_inside = [at_design(self.face, r, d) for r in (121.5, 123, 124) for d in range(0, 360, 5)]
        for point in disc_inside:
            self.assertEqual(self.white.getpixel(point), self.dark.getpixel(point), point)
        gap = [at_design(self.face, 130, d) for d in range(3, 360, 6)]   # between two segments' ends
        brighter = sum(self.white.getpixel(p)[0] > self.dark.getpixel(p)[0] + 4 for p in gap)
        self.assertEqual(brighter, len(gap))
        edge = self.dark.getpixel(at_design(self.face, kf.DISC_RADIUS - .5, 90))
        self.assertGreater(edge[0], kf.DISC_RGB[0] + 8)            # the lighter 1 px inner edge
        self.assertEqual(self.dark.getpixel(at_design(self.face, 123, 90))[:3], kf.DISC_RGB)

    def test_glow_follows_the_level(self):
        point = at_design(self.face, 138, 3)       # between segments 0 and 1, at the ring radius
        glows = [self.face.compose(None, lit((255, 150, 30), a)).getpixel(point)[0] for a in (0.12, 0.34, 0.68, 1.0)]
        self.assertEqual(glows, sorted(glows))
        self.assertGreater(glows[-1], glows[0])

    def test_lcd_is_centred_and_never_resampled_at_lcd_px(self):
        px = self.face.lcd_px
        lcd = Image.new('RGBA', (px, px), (0, 0, 0, 0))
        solid = Image.new('RGBA', (px, px), (200, 30, 60, 255))
        lcd.paste(solid, (0, 0), lp._glass_mask(px))
        frame = self.face.compose(lcd, lit())
        cx, cy = self.face.center
        self.assertEqual(frame.getpixel((cx, cy)), (200, 30, 60, 255))
        for dx, dy in ((px // 2 - 2, 0), (-px // 2 + 1, 0), (0, px // 2 - 2), (0, -px // 2 + 1)):
            self.assertEqual(frame.getpixel((cx + dx, cy + dy)), (200, 30, 60, 255), (dx, dy))
        outside = frame.getpixel((cx + px // 2 + 2, cy))
        self.assertEqual(outside[:3], kf.DISC_RGB)
        blank = self.face.compose(None, lit())
        self.assertEqual(blank.getpixel((cx, cy)), (0, 0, 0, 255))   # the glass without an LCD
        self.assertEqual(self.face.lcd_resizes, 0)                   # lcd_px images are never resampled

    def test_a_wrong_size_lcd_is_fitted_but_counted_and_logged_once(self):
        face = kf.KnobFace(kf.scale_for(DPI_100))
        self.assertEqual(face.lcd_resizes, 0)
        with self.assertLogs('control_center.knob_face', level='WARNING') as logs:
            small = face.compose(Image.new('RGBA', (240, 240), (9, 9, 9, 255)), lit())
            face.compose(Image.new('RGBA', (240, 240), (9, 9, 9, 255)), lit())
            logging.getLogger('control_center.knob_face').warning('sentinel')
        self.assertEqual(small.size, face.size)                      # fitted, not fatal
        self.assertEqual(small.getpixel(face.center), (9, 9, 9, 255))
        self.assertEqual(face.lcd_resizes, 2)                        # one per LCD image that needed it
        self.assertEqual(len(logs.records), 2)                       # the first warning + the sentinel
        self.assertIn('240x240', logs.output[0])
        self.assertIn(str(face.lcd_px), logs.output[0])
        good = Image.new('RGBA', (face.lcd_px,) * 2, (9, 9, 9, 255))
        face.compose(good, lit())
        face.compose(good, lit())
        self.assertEqual(face.lcd_resizes, 2)                        # the right size does not count

    def test_premultiplied_bgra(self):
        data = kf.premultiplied_bgra(self.white)
        width, height = self.face.size
        self.assertEqual(len(data), width * height * 4)
        view = memoryview(data)
        self.assertTrue(all(max(view[i:i + 3]) <= view[i + 3] for i in range(0, len(data), 4)))
        sample = Image.new('RGBA', (2, 1))
        sample.putdata([(255, 128, 0, 128), (10, 20, 30, 255)])
        self.assertEqual(kf.premultiplied_bgra(sample), bytes([0, 64, 128, 128, 30, 20, 10, 255]))
        self.assertEqual(kf.premultiplied_bgra(sample.convert('RGB'))[4:], bytes([30, 20, 10, 255]))

    def test_sprites_are_built_once_and_frames_are_repeatable(self):
        face = kf.KnobFace(kf.scale_for(DPI_100))
        segments, base = face._segments, face._base
        lcd = lp.render_lcd(CASES['home']['frame'], scale=face.scale)
        ring = kf.ring_colors(CASES['home']['frame'], PreviewLights().render(CASES['home']['frame'], 0, 0)[0])
        first = face.compose(lcd, ring).tobytes()
        self.assertEqual(face.compose(lcd, ring).tobytes(), first)
        self.assertIs(face._segments, segments)
        self.assertIs(face._base, base)
        self.assertEqual(len(face._lcd_bases), 1)                    # the LCD layer is reused
        self.assertGreater(face.build_ms, 0)
        self.assertEqual(face.frames, 2)

    def test_ring_input_forms(self):
        face = self.face
        colours = lit((255, 150, 30), 0.68)
        packed = [(0xFF961E, 0.68)] * RING_SEGMENTS
        self.assertEqual(face.compose(None, packed).tobytes(), face.compose(None, colours).tobytes())
        short = face.compose(None, colours[:10]).tobytes()
        padded = face.compose(None, colours[:10] + [kf.UNLIT] * 50).tobytes()
        self.assertEqual(short, padded)
        self.assertEqual(face.compose(None, []).tobytes(), self.dark.tobytes())


# PreviewLights at 60 fps over (case, ms): volume up/down decays, accents, the loading and
# pending pulses and an ok flash, so ring colours and levels change on most frames.
LIGHT_SEQUENCE = (('led-vol-96', 100), ('led-vol-54', 300), ('led-vol-96', 100), ('led-recent', 100),
                  ('ra-load', 600), ('pend-tr-next', 600), ('flash-ok-home', 400), ('led-vol-54', 300))
FRAME_MS = 16


def timed(fn, *args):
    started = time.perf_counter()
    result = fn(*args)
    return result, (time.perf_counter() - started) * 1000


def light_sequence():
    """The ring_colors of LIGHT_SEQUENCE, one per 16 ms frame (what the overlay composes)."""
    lights, now, rings = PreviewLights(), 0, []
    for case_id, duration in LIGHT_SEQUENCE:
        frame = CASES[case_id]['frame']
        for _ in range(duration // FRAME_MS):
            rings.append(kf.ring_colors(frame, lights.render(frame, None, now)[0]))
            now += FRAME_MS
    return rings


class BenchmarkTests(unittest.TestCase):
    def measure(self, dpi, runs=25, churn_runs=40):
        """Median / max compose ms for a steady ring (warm caches) and for churning rings.

        The max includes interpreter noise (cyclic GC after the earlier tests' allocations):
        churn at 200 % runs ~4.4 ms max in a fresh process and ~6-7 ms here.
        """
        frame = CASES['led-vol-86']['frame']
        face = kf.KnobFace(kf.scale_for(dpi))
        lcd = lp.render_lcd(frame, scale=face.scale)
        ring = kf.ring_colors(frame, PreviewLights().render(frame, 0, 0)[0])
        face.compose(lcd, ring)
        steady, bgra, new_lcd = [], [], []
        for _ in range(runs):
            image, ms = timed(face.compose, lcd, ring)
            steady.append(ms)
            bgra.append(timed(kf.premultiplied_bgra, image)[1])
        for _ in range(max(5, runs // 3)):
            new_lcd.append(timed(face.compose, lcd.copy(), ring)[1])
        # Churn: all 60 lit, every colour and level new each frame (body sprites and glow
        # masks miss their caches every time: the worst case).
        rng = random.Random(dpi)
        churn = [timed(face.compose, lcd, [(rng.randrange(256), rng.randrange(256), rng.randrange(256),
                                            rng.uniform(0.05, 1.0)) for _ in range(RING_SEGMENTS)])[1]
                 for _ in range(churn_runs)]
        sequence = [timed(face.compose, lcd, colours)[1] for colours in light_sequence()]
        stats = lambda values: (statistics.median(values), max(values))
        return face, {'steady': stats(steady), 'churn': stats(churn), 'lights': stats(sequence),
                      'new LCD': stats(new_lcd), 'BGRA': stats(bgra)}, len(sequence)

    def test_compose_time_at_100_and_200_percent(self):
        for dpi in (DPI_100, DPI_200):
            face, times, frames = self.measure(dpi)
            figures = ', '.join(f'{name} {median:.2f}/{worst:.2f}' for name, (median, worst) in times.items())
            print(f'\n[knob_face benchmark] {dpi * 100 // 96}% DPI: box {face.size[0]} px, lcd {face.lcd_px} px, '
                  f'sprites {face.build_ms:.1f} ms once; compose median/max ms: {figures} '
                  f'(steady = one ring, warm caches; churn = 60 lit, new colour + level every frame; '
                  f'lights = {frames} PreviewLights frames of decays, pulses and a flash); '
                  f'budget {BUDGET_MS:.0f} ms', file=sys.stderr)
            with self.subTest(dpi=dpi):
                for name in ('steady', 'churn', 'lights'):
                    self.assertLess(times[name][0], LOOSE_MS, name)
                    self.assertLess(times[name][1], 4 * LOOSE_MS, name)      # no pathological frame
                self.assertLess(times['new LCD'][0] + times['BGRA'][0], 2 * LOOSE_MS)


# =========================================================================== desktop v7 (alive)
# ALIVE.md (K2 r2) 10.3 item 3 and 11 item 5; DESKTOP_STAGE (K4) 11.2-11.4, 6.6 H1 / H9.
import unittest.mock                                         # noqa: E402
from control_center import overlay as ov                     # noqa: E402
from control_center.alive_lights import AliveLights          # noqa: E402

HOME = {'id': 7, 'layout': 'nowPlaying', 'ledStyle': 'color', 'title': 'Song', 'playing': True,
        'ring': {'style': 'level', 'value': 54, 'index': 0, 'count': 101},
        'buttons': [{'label': 'Pause', 'enabled': True, 'icon': 'pause'},
                    {'label': 'Browse', 'enabled': True, 'icon': 'list'},
                    {'label': 'Tracks', 'enabled': True, 'icon': 'tracks'},
                    {'label': 'Win', 'enabled': True, 'icon': 'win'}]}


def with_feedback(frame, seq, **fields):
    return dict(frame, feedback=dict({'kind': 'ok', 'seq': seq}, **fields))


def max_diff(a, b):
    return max(abs(x - y) for ea, eb in zip(a, b) for x, y in zip(ea, eb))


class AliveLookTests(unittest.TestCase):
    """K2 10.3 item 3 / K4 11.3: fill 36 + 219 e, six looks (GLL, ties to the lower look), alpha
    0.95 GLL, sigma GLB / 2 x S_glow, ring only, nothing blurred per frame."""

    @classmethod
    def setUpClass(cls):
        cls.face = kf.AliveFace(kf.scale_for(DPI_100), kf.glow_scale_for(DPI_100))

    def test_look_index_is_the_nearest_level_and_ties_go_to_the_lower_look(self):
        def bs(mx):                                   # BS:479-481: g = 0; for j: if |GLL[j]-mx| < |GLL[g]-mx| g = j
            best = 0
            for j in range(1, len(kf.GLL)):
                if abs(kf.GLL[j] - mx) < abs(kf.GLL[best] - mx):
                    best = j
            return best
        for j, level in enumerate(kf.GLL):
            self.assertEqual(kf.look_index(level), j)
        for step in range(1001):
            self.assertEqual(kf.look_index(step / 1000), bs(step / 1000))
        # An exact tie (distances equal in binary) keeps the lower look: 0.5 is 0.25 from 0.25 and 0.75.
        with unittest.mock.patch.object(kf, 'GLL', (0.25, 0.75)), unittest.mock.patch.object(kf, 'LOOKS', 2):
            self.assertEqual(kf.look_index(0.5), 0)
        for j in range(len(kf.GLL) - 1):
            middle = (kf.GLL[j] + kf.GLL[j + 1]) / 2
            self.assertEqual(kf.look_index(middle + 1e-6), j + 1)
            self.assertEqual(kf.look_index(middle - 1e-6), j)
        self.assertEqual((kf.look_index(0.02), kf.look_index(1.0)), (0, 5))

    def test_segment_look_fill_tint_and_threshold(self):
        self.assertEqual(kf.segment_look((0, 0, 0)), ((36, 36, 36), -1, (0, 0, 0)))
        self.assertEqual(kf.segment_look((0.01, 0.0, 0.0))[1], -1, 'mx <= 0.01: no glow')
        fill, look, tint = kf.segment_look((1.0, 0.5, 0.0))
        self.assertEqual(fill, (255, 146, 36))              # round(36 + 219 e), half up
        self.assertEqual((look, tint), (5, (255, 128, 0)))  # tint round(e / mx * 255)
        fill, look, tint = kf.segment_look((0.3, 0.15, 0.0))
        self.assertEqual((look, tint), (1, (255, 128, 0)), 'the look comes from the rendered level')
        self.assertEqual(kf.alive_fill_hex((0, 0, 0)), '#242424')

    def test_glow_scale_and_sigmas_follow_the_ring_diameter_over_318(self):
        self.assertAlmostEqual(kf.glow_scale_for(96), 360 / 318, places=6)
        self.assertEqual([round(s, 2) for s in kf.look_sigmas(kf.glow_scale_for(96))],
                         [3.40, 4.53, 5.66, 6.79, 8.49, 10.19])
        self.assertEqual([round(s, 2) for s in kf.look_sigmas(kf.glow_scale_for(192))],
                         [6.79, 9.06, 11.32, 13.58, 16.98, 20.38])
        self.assertEqual(self.face.sigmas, kf.look_sigmas(kf.glow_scale_for(96)))

    def test_the_face_keeps_knob_faces_geometry_and_every_look_fits_the_box(self):
        for dpi in (96, 144, 192):
            with self.subTest(dpi=dpi):
                alive = self.face if dpi == 96 else kf.AliveFace(kf.scale_for(dpi), kf.glow_scale_for(dpi))
                v5 = kf.KnobFace(kf.scale_for(dpi))
                self.assertEqual((alive.size, alive.center, alive.lcd_px), (v5.size, v5.center, v5.lcd_px))
                for _at, _body, looks in alive._segments:
                    self.assertEqual(len(looks), 6)
                    for (x, y), mask in looks:
                        self.assertGreaterEqual(min(x, y), 0)
                        self.assertLessEqual(x + mask.width, alive.size[0])
                        self.assertLessEqual(y + mask.height, alive.size[1])

    def test_look_masks_bake_their_alpha_and_widen_with_the_look(self):
        _at, body, looks = self.face._segments[0]
        body_mass = sum(i * n for i, n in enumerate(body.histogram()))
        for g, ((_x, _y), mask) in enumerate(looks):
            peak = mask.getextrema()[1]
            self.assertGreater(peak, 0)
            self.assertLessEqual(peak, round(255 * kf.LOOK_ALPHA * kf.GLL[g]) + 1, g)
            # A blur keeps the mass; the look's alpha scales it (a little is clipped by the disc).
            mass = sum(i * n for i, n in enumerate(mask.histogram()))
            self.assertLess(abs(mass / body_mass - kf.LOOK_ALPHA * kf.GLL[g]) / (kf.LOOK_ALPHA * kf.GLL[g]), 0.25, g)
        widths = [mask.width for _xy, mask in looks]
        self.assertEqual(widths, sorted(widths), 'larger sigma for higher looks')
        self.assertGreater(widths[-1], widths[0])

    def test_glows_are_clipped_by_the_disc(self):
        (x, y), mask = self.face._segments[0][2][5]              # the widest look of the top segment
        full = Image.new('L', self.face.size, 0)
        full.paste(mask, (x, y))
        self.assertEqual(full.getpixel(at_design(self.face, 120, 0)), 0, 'inside the disc (r 126)')
        self.assertGreater(full.getpixel(at_design(self.face, 130, 0)), 0, 'outside it')

    def test_unlit_bodies_are_242424_and_no_button_strip_is_drawn(self):
        dark = self.face.compose(None, ov.BLANK_E)
        bright = self.face.compose(None, [(1.0, 0.75, 0.41)] * RING_SEGMENTS)
        body = at_design(self.face, 138, 0)
        self.assertEqual(dark.getpixel(body)[:3], (36, 36, 36))
        for got, want in zip(bright.getpixel(body)[:3], (255, 200, 126)):    # round(36 + 219 e); edge AA
            self.assertLessEqual(abs(got - want), 3)
        for point in (at_design(self.face, 166, 150), at_design(self.face, 166, 180), at_design(self.face, 166, 210)):
            self.assertEqual(dark.getpixel(point), bright.getpixel(point), 'M30: ring only, no strips')

    def test_compose_is_an_exact_premultiplied_over(self):
        face = self.face
        ring = [(0.0, 0.0, 0.0)] * RING_SEGMENTS
        ring[0], ring[15] = (1.0, 0.2, 0.1), (0.3, 0.6, 1.0)
        looks = kf.ring_key(ring)
        canvas = Image.new('RGBX', face.size, (0, 0, 0, 0))
        face.compose_into(canvas, (0, 0), None, looks)
        reference = face._base.copy()                             # straight RGBA, alpha_composite reference
        for index, (fill, look, tint) in enumerate(looks):
            if look >= 0:
                at, mask = face._segments[index][2][look]
                reference.alpha_composite(face._solid(tint, mask), at)
        for index, (fill, _look, _tint) in enumerate(looks):
            at, mask, _ = face._segments[index]
            reference.alpha_composite(face._solid(fill, mask), at)
        glass = face._disc_sprite(None)
        red, green, blue = glass.split()[2], glass.split()[1], glass.split()[0]
        disc = Image.merge('RGBA', (red, green, blue, face._disc_mask))
        reference.alpha_composite(disc, face._inner_box[:2])
        expected = kf.premultiplied_bgra(reference)
        drawn = canvas.tobytes()
        worst = max(abs(a - b) for a, b in zip(drawn, expected))
        self.assertLessEqual(worst, 2, 'masked pastes into the premultiplied canvas are an exact over')

    def test_nothing_is_blurred_per_frame_and_the_look_cache_never_misses(self):
        from unittest.mock import patch
        lights = AliveLights(0)
        lights.claim(0)
        canvas = Image.new('RGBX', self.face.size, (0, 0, 0, 0))
        with patch.object(kf.ImageFilter, 'GaussianBlur', side_effect=AssertionError('blur per frame')), \
                patch.object(kf.Image, 'alpha_composite', side_effect=AssertionError('alpha_composite per frame')):
            for step in range(120):
                ring, _buttons = lights.render(step * 8, with_feedback(HOME, 1 + step // 40), None, None)
                self.face.compose_into(canvas, (0, 0), None, kf.ring_key(ring))

    def test_the_ring_key_changes_only_with_the_quantised_face(self):
        ring = [(0.5, 0.2, 0.1)] * RING_SEGMENTS
        key = kf.ring_key(ring)
        self.assertEqual(kf.ring_key([(0.5 + 1e-4, 0.2, 0.1)] * RING_SEGMENTS), key)
        self.assertNotEqual(kf.ring_key([(0.52, 0.2, 0.1)] * RING_SEGMENTS), key)
        self.assertEqual(len(kf.ring_key(ring[:10])), RING_SEGMENTS, 'missing segments are unlit')


class CountingLights(AliveLights):
    renders = 0

    def render(self, now, frame=None, local_pos=None, local_max=None):
        type(self).renders += 1
        self.stamps = getattr(self, 'stamps', []) + [now]
        return super().render(now, frame, local_pos, local_max)


class AliveMirrorTests(unittest.TestCase):
    """K2 M27 catch-up and H1 frame-rate independence on the pure mirror."""

    def test_catch_up_steps_of_50_ms_at_most_60(self):
        for gap, steps in ((0.040, 0), (0.050, 0), (0.120, 2), (1.0, 19), (3.0, 59), (10.0, 60)):
            with self.subTest(gap=gap):
                mirror = ov.AliveMirror(AliveLights, start=100.0)
                self.assertEqual(mirror.catch_up(100.0 + gap), steps)
        mirror = ov.AliveMirror(CountingLights, start=100.0)
        mirror.catch_up(110.0)
        self.assertEqual(mirror.lights.stamps[0], ov.qpc_ms(107.0), 'a gap over 3 s first renders at now - 3 s')
        self.assertEqual(mirror.lights.stamps[1] - mirror.lights.stamps[0], 50)

    def test_a_message_never_moves_time_back(self):
        mirror = ov.AliveMirror(CountingLights, start=50.0)
        mirror.message(50.5)
        mirror.message(50.2)                       # an input read before the last render
        self.assertEqual(mirror.lights.stamps[-1], ov.qpc_ms(50.5))

    # The mirror's half of H1 (the engine's is test_alive_lights.FrameRateTests, same method): script
    # events fall on instants every rate samples (multiples of 250 ms, integer ms), so effects start
    # at the same render in every run; the 300 ms after an event are skipped (a target change is
    # applied over the render's whole dt, so a 60 Hz run starts a cursor move up to one frame's
    # damping ahead; with tau <= 70 ms that offset is 1.1 % at 250 ms and under 1 % from 300 ms).
    EVENTS = {0: 'claim', 1000: 'detent', 1250: 'detent', 1500: 'detent', 2000: 'like', 2500: 'limit'}
    END_MS, SETTLE_MS = 6000, 300          # the last input at 2.5 s: no sleep before 7.5 s

    def run_ms(self, times):
        mirror = ov.AliveMirror(AliveLights, start=0.00025)
        out, done = {}, set()
        for ms in times:
            t = (ms + 0.25) / 1000                               # int(t * 1000) == ms exactly (P12)
            for at in sorted(k for k in self.EVENTS if k <= ms and k not in done):
                done.add(at)
                stamp, kind = (at + 0.25) / 1000, self.EVENTS[at]
                if kind == 'claim':
                    mirror.apply_frame(HOME, True, 100, stamp)
                elif kind == 'detent':
                    mirror.apply_input('position', (54 + len(done), 1), 7, stamp)
                elif kind == 'like':
                    mirror.apply_frame(with_feedback(HOME, 5, moment='like'), True, 100, stamp)
                else:
                    mirror.apply_input('limit', 1, 7, stamp)
            out[ms] = mirror.render(t)
        return out

    def quiet(self, ms):
        return not any(0 <= ms - at < self.SETTLE_MS for at in self.EVENTS)

    def test_the_same_script_gives_the_same_ring_at_every_refresh_rate(self):
        runs = {rate: self.run_ms(sorted({math.floor(k * 1000 / rate + 0.5)
                                          for k in range(self.END_MS * rate // 1000 + 1)}))
                for rate in (60, 120, 144, 240, 360)}
        common = sorted(set.intersection(*(set(out) for out in runs.values())))
        compared = [ms for ms in common if self.quiet(ms)]
        self.assertGreater(len(compared), 30)
        for rate in (60, 120, 144, 240):
            with self.subTest(rate=rate):
                worst = max(max_diff(runs[rate][ms], runs[360][ms]) for ms in compared)
                self.assertLess(worst, 0.01)

    def test_skipped_vblanks_resume_on_the_curve(self):
        base = sorted({math.floor(k * 1000 / 240 + 0.5) for k in range(self.END_MS * 240 // 1000 + 1)})
        skipped = [ms for k, ms in enumerate(base) if k % 7 not in (3, 4, 5) or ms % 250 == 0]   # 1-3 in a row
        full, gaps = self.run_ms(base), self.run_ms(skipped)
        compared = [ms for ms in skipped if self.quiet(ms)]
        worst = max(max_diff(full[ms], gaps[ms]) for ms in compared)
        self.assertLess(worst, 0.01, 'no catch-up burst after a skip')


class InlineBackend:
    """A Win32Backend stand-in for the inline overlay: records presents; posts are delivered at pump."""
    hwnd = 0

    def __init__(self):
        self.handler = None
        self.size = None
        self.pending = []
        self.presents = []
        self.shown = False
        self.timing = (0.0, 1 / 240, 240.0)
        self.waits = []

    def prepare_thread(self): return 2
    def create(self, handler, position, size): self.handler, self.size = handler, tuple(size)
    def resize(self, size): self.size = tuple(size)
    def geometry(self): return (0, 0, 1920, 1040), 96
    def post(self, code): self.pending.append(code); return True
    def post_quit(self): return True

    def pump(self):
        pending, self.pending = self.pending, []
        for code in pending:
            self.handler(ov.POSTED_EVENTS[code])
        return True

    def wait(self, timeout): self.waits.append(timeout); return True
    def pace(self): pass
    def vblank_timing(self): return self.timing

    def present(self, frame, size, position, src_x, alpha):
        assert isinstance(frame, bytes) and len(frame) == size[0] * size[1] * 4
        self.presents.append((src_x, alpha))
        return True

    def show(self): self.shown = True; return True
    def hide(self): self.shown = False; return True
    def is_visible(self): return self.shown
    def notification_state(self): return 5
    def gui_resources(self): return 0, 0
    def destroy_window(self): self.handler = None
    def unregister(self): pass
    def destroy(self): pass


class FakeClock:
    def __init__(self, now=10.0):
        self.now = now

    def __call__(self):
        return self.now


class FloatingKnobAliveTests(unittest.TestCase):
    """The floating knob's engine on the overlay (K4 11.2, 11.4; K2 M27; H9), inline with a fake
    backend and a fake clock: nothing is created on screen."""

    def setUp(self):
        CountingLights.renders = 0
        self.clock = FakeClock(10.0)
        self.backend = InlineBackend()
        self.knob = ov.KnobOverlay(backend=self.backend, clock=self.clock, lights_factory=CountingLights)
        self.knob._start_inline()
        self.addCleanup(self.knob.close)
        self.knob.set_alive(True)
        self.step()

    def step(self, count=1):
        results = []
        for _ in range(count):
            results.append(self.knob._iterate())
        return results[-1]

    def at(self, t):
        self.clock.now = t

    def post(self, frame, t, claimed=True):
        self.at(t)
        self.knob.post_frame(frame, claimed=claimed, local_max=100)
        return self.step()

    def slide_in(self, t):
        self.at(t)
        self.knob.touch()
        self.knob.submit(ov.OverlayScene('lcd', None, ov.BLANK_RING))
        self.step()
        return self.knob._engine.mirror

    def twin(self, schedule, until):
        """AliveLights rendered continuously at 60 Hz, each message of ``schedule`` (sorted (t,
        message)) applied and rendered when it arrives, as the physical ring does; the ring at
        ``until``. A message is a frame (dict; the first one claims) or a fast-path input
        ``('input', kind, value, control id)`` with AliveMirror.apply_input's rules (the frame's
        local_max is 100, as ``post`` sends)."""
        lights = AliveLights(ov.qpc_ms(10.0))
        claimed, frame, local = False, None, None
        ticks = [10.0 + k / 60 for k in range(int((until - 10.0) * 60) + 1)]
        timeline = sorted([(t, 1, i, None) for i, t in enumerate(ticks)]
                          + [(t, 0, i, m) for i, (t, m) in enumerate(schedule)] + [(until, 2, 0, None)],
                          key=lambda event: event[:3])
        ring = None
        for t, kind, _index, message in timeline:
            if t > until + 1e-12:
                break
            now = ov.qpc_ms(t)
            if kind == 0 and isinstance(message, dict):
                if not claimed:
                    lights.claim(now)
                    claimed = True
                frame = message
            elif kind == 0:
                _input, what, value, control_id = message
                same = frame is not None and control_id == frame.get('id')
                if what == 'position':
                    local = (control_id, value[0])
                    if claimed and same and value[1]:
                        lights.detent(now, value[1])
                elif what == 'limit' and claimed and same:
                    lights.limit(now, value)
                elif what == 'press' and claimed:
                    lights.press(now, value)
            position = local[1] if local is not None and frame is not None and local[0] == frame.get('id') else None
            ring, _ = lights.render(now, frame, position, 100 if position is not None else None)
        return ring

    def test_while_hidden_one_render_per_message_and_no_loop_timer_compose_or_present(self):
        mirror = self.knob._engine.mirror
        self.assertIsNotNone(mirror)
        before = CountingLights.renders
        alive, wait = self.post(HOME, 10.02)
        self.assertEqual((alive, wait), (True, None), 'hidden: block, no timer')
        self.assertEqual(CountingLights.renders - before, 1)
        self.at(10.04)
        self.knob._mail.inputs.append(('position', (55, 1), 7, 10.04))
        self.knob._mail.input_posted = True
        self.backend.post(ov.WM_APP_INPUT)
        self.assertEqual(self.step(), (True, None))
        self.assertEqual(CountingLights.renders - before, 2)
        self.post(HOME, 12.04)                                    # 2 s later: 39 catch-up steps + 1
        self.assertEqual(CountingLights.renders - before, 2 + 39 + 1)
        metrics = self.knob.metrics()
        self.assertEqual((metrics['frames_composed'], metrics['frames_presented']), (0, 0))
        self.assertEqual(self.backend.presents, [])
        self.assertEqual(metrics['hidden_renders'], 3)
        self.assertEqual(self.backend.waits, [], 'no timer while hidden')
        self.assertTrue(metrics['alive'])

    def compare_with_twin(self, schedule, slide_at):
        for stamp, frame in schedule:
            self.post(frame, stamp)
        mirror = self.slide_in(slide_at)
        self.assertEqual(self.knob.state, 'in')
        shown_at = mirror.last
        self.assertAlmostEqual(shown_at, slide_at, delta=1 / 240)
        twin = self.twin(schedule, shown_at)
        self.assertLess(max_diff(mirror.ring, twin), 0.02)
        return mirror.ring, twin

    def test_a_like_posted_while_hidden_does_not_bloom_at_the_slide_in(self):
        like = with_feedback(HOME, 3, moment='like')
        ring, twin = self.compare_with_twin([(10.10, HOME), (10.50, like)], 12.50)
        # The bloom ended at 10.5 + 0.9 s; an engine that met the like only at the slide-in would be
        # 400 ms into it 400 ms later, where ours (and the twin) show none.
        late = self.twin([(10.10, HOME), (12.50, like)], 12.90)
        now = self.twin([(10.10, HOME), (10.50, like)], 12.90)
        self.assertGreater(max_diff(late, now), 0.02, 'the comparison would see a replayed bloom')

    def test_a_started_wash_300_ms_before_the_slide_in_shows_mid_way(self):
        started = with_feedback(dict(HOME, ring=dict(HOME['ring'])), 4, moment='started', color=0x3060F0)
        self.compare_with_twin([(10.10, HOME), (12.20, started)], 12.50)

    def test_a_ten_second_hidden_spell_across_the_fall_asleep(self):
        self.compare_with_twin([(10.10, HOME)], 20.10)

    # WP10-1: a summon carries its own message. post_input posts the input and then its touch, so
    # one pump holds both and the touch ARMs first; the Tk tick posts its frame before its touch;
    # a feedback frame can land in the 100 ms arm wait. Each must render at its own stamp (K4 11.2 /
    # K2 M27: "the new frame and inputs go only into the final render at now"), not be handed to
    # the launch's catch-up, which started their effects up to 3 s in the past.
    #
    # The first visible frame is checked against K2 M27's own procedure (exactly), not against the
    # 60 Hz twin: M27's catch-up steps are 50 ms, so the render at a message's stamp damps over up to
    # 50 ms where the twin damps over one 16.7 ms tick (0.27 for a waking detent, 0.11 for a press,
    # measured). That lead fades like H1's (AliveMirrorTests): 300 ms of visible frames later the
    # ring matches the twin within 0.02 (measured 0.001 / 0.002; the stale starts differ by 0.13 /
    # 0.91 there).
    def reference(self, schedule, t_end):
        """K2 M27 outside the overlay: one AliveMirror.message per message at its stamp, then the
        launch's catch-up and the render at the first visible frame's time."""
        mirror = ov.AliveMirror(AliveLights, start=10.0)
        for t, message in schedule:
            if isinstance(message, dict):
                def apply(message=message, t=t):
                    mirror.apply_frame(message, True, 100, t)
            else:
                def apply(message=message, t=t):
                    mirror.apply_input(message[1], message[2], message[3], t)
            mirror.message(t, apply)
        mirror.catch_up(t_end)
        mirror.render(t_end)
        return mirror.ring

    def summoned(self, schedule, stale, shown_near):
        """After a summon: the first visible frame is M27's; 300 ms of 240 Hz frames later the ring
        is the twin's. ``stale`` is the same schedule with the summon's messages met 3 s early by
        the launch's catch-up (the WP10-1 defect); both checks would see it."""
        engine = self.knob._engine
        mirror = engine.mirror
        self.assertEqual(self.knob.state, 'in')
        self.assertFalse(engine.machine.pending, 'launched')
        shown_at = mirror.last
        self.assertAlmostEqual(shown_at, shown_near, delta=1 / 240)
        self.assertEqual(max_diff(mirror.ring, self.reference(schedule, shown_at)), 0.0)
        self.assertGreater(max_diff(self.reference(stale, shown_at), mirror.ring), 0.02)
        for i in range(1, 73):                                      # 300 ms of vblanks at 240 Hz
            self.at(shown_at + i / 240)
            self.step()
        later = mirror.last
        self.assertGreaterEqual(later - shown_at, 0.3 - 1e-6)
        twin = self.twin(schedule, later)
        self.assertLess(max_diff(mirror.ring, twin), 0.02)
        self.assertGreater(max_diff(self.twin(stale, later), twin), 0.02, 'the comparison would see it')

    def test_a_detent_that_summons_the_knob_after_ten_seconds_hidden(self):
        self.post(HOME, 10.10)
        detent = ('input', 'position', (55, 1), 7)
        self.at(20.10)
        self.assertTrue(self.knob.post_input('position', (55, 1), 7, t=20.10))   # the input + its touch
        self.knob.submit(ov.OverlayScene('lcd', None, ov.BLANK_RING))
        before = self.knob.metrics()['hidden_renders']
        self.step()                                                   # one pump: touch, input, launch
        self.assertEqual(self.knob.metrics()['hidden_renders'] - before, 1, 'the input renders at its stamp')
        self.assertIn(ov.qpc_ms(20.10), self.knob._engine.mirror.lights.stamps)
        self.summoned([(10.10, HOME), (20.10, detent)], [(10.10, HOME), (17.10, detent)], 20.10)

    def test_a_press_that_summons_the_knob_and_its_feedback_frame_in_the_arm_wait(self):
        self.post(HOME, 10.10)
        press = ('input', 'press', 0, 7)
        ok = dict(with_feedback(HOME, 5), playing=False)
        self.at(18.10)
        self.assertTrue(self.knob.post_input('press', 0, 7, t=18.10))
        self.step()
        self.assertTrue(self.knob._engine.machine.pending, 'armed: waiting for a fresh scene')
        self.at(18.12)                                                # the Tk tick, 20 ms later
        self.knob.post_frame(ok, claimed=True, local_max=100)
        self.knob.submit(ov.OverlayScene('lcd2', None, ov.BLANK_RING))
        before = self.knob.metrics()['hidden_renders']
        self.step()
        self.assertEqual(self.knob.metrics()['hidden_renders'] - before, 1, 'the frame renders at its stamp')
        stamps = self.knob._engine.mirror.lights.stamps
        self.assertIn(ov.qpc_ms(18.10), stamps)
        self.assertIn(ov.qpc_ms(18.12), stamps)
        self.summoned([(10.10, HOME), (18.10, press), (18.12, ok)],
                      [(10.10, HOME), (15.12, press), (15.12, ok)], 18.12)

    def test_a_tk_frame_posted_in_the_same_tick_as_its_touch(self):
        self.post(HOME, 10.10)
        started = with_feedback(dict(HOME, ring=dict(HOME['ring'])), 4, moment='started', color=0x3060F0)
        self.at(15.10)
        self.knob.post_frame(started, claimed=True, local_max=100)   # _post_alive runs before touch()
        self.knob.touch()
        self.knob.submit(ov.OverlayScene('lcd', None, ov.BLANK_RING))
        self.step()
        self.assertIn(ov.qpc_ms(15.10), self.knob._engine.mirror.lights.stamps)
        self.summoned([(10.10, HOME), (15.10, started)], [(10.10, HOME), (12.10, started)], 15.10)

    def test_visible_frames_compose_only_when_the_face_changes(self):
        self.post(HOME, 10.10)
        self.slide_in(10.20)
        for i in range(1, 200):
            self.at(10.20 + i / 240)
            self.step()
        metrics = self.knob.metrics()
        self.assertEqual(self.knob.state, 'shown')
        self.assertGreater(metrics['frames_composed'], 0)
        self.assertGreater(metrics['frames_skipped'], 0, 'unchanged faces are skipped (AR-22)')
        self.assertLessEqual(metrics['frames_composed'], metrics['engine_renders'])
        self.assertEqual(self.backend.presents[0], (self.backend.size[0], 0), 'first frame presented hidden')
        self.assertEqual(self.backend.presents[-1], (0, 255))
        self.assertGreaterEqual(metrics['looks_build_ms'], 0.0)
        knob = metrics['frames']['knob']
        self.assertEqual(knob['slide']['last']['kind'], 'slide')

    def test_reduced_motion_fades_in_place(self):
        self.at(10.05)
        self.knob.set_latched(reduced_motion=True)
        self.step()
        self.post(HOME, 10.10)
        self.slide_in(10.20)
        for i in range(1, 60):
            self.at(10.20 + i / 240)
            self.step()
        self.assertTrue(all(src_x == 0 for src_x, _alpha in self.backend.presents), 'no slide')
        alphas = [alpha for _src, alpha in self.backend.presents]
        self.assertEqual(alphas[-1], 255)
        self.assertTrue(any(0 < alpha < 255 for alpha in alphas), 'a fade')
        self.assertAlmostEqual(self.knob._engine.machine.in_seconds, ov.REDUCED_FADE_SECONDS)

    def test_fast_path_inputs_touch_and_are_dropped_without_the_engine(self):
        self.post(HOME, 10.10)
        self.at(10.30)
        self.assertTrue(self.knob.post_input('limit', 1, 7))
        self.assertTrue(self.knob.wants_frames, 'a lim summons the knob like a turn (K4 11.6)')
        self.assertFalse(self.knob.post_input('volume', 1, 7), 'unknown kinds are refused')
        self.knob.set_alive(False)
        self.step()
        self.assertFalse(self.knob.alive)
        self.assertFalse(self.knob.post_input('position', (3, 1), 7), 'no engine: the v5 path')
        self.assertIsNone(self.knob._engine.mirror)


if __name__ == '__main__':
    unittest.main()

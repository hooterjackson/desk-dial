"""artwork2 icon payload (firmware/ARTWORK2.md section 5).

icon_payload() turns IconWorker's 32x32 RGBA into the 2048-byte RGB565 LE tile
image: alpha composited onto black as round(c*a/255), then r5 = (r*31+127)//255,
g6 = (g*63+127)//255, b5 = (b*31+127)//255, key sha256(raw)[:16]. The fast path
uses Pillow's premultiply; these tests hold it to the formula for every input.
IconWorker builds the payload on its own thread and hands it over in the icon's
``info`` (attach_icon_payload / attached_icon_payload), so the Tk poll encodes nothing.
"""
import hashlib
from pathlib import Path
import random
import sys
import time
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.artwork import (ICON_PAYLOAD_INFO, ArtworkError, attach_icon_payload, attached_icon_payload,
                                   icon_key, icon_payload, rgb565_over_black, rgb565le_rounded)
from control_center.presentation import ICON_BYTES, ICON_KEY_CHARS, ICON_SIZE

DESIGN_APPS = (Path(__file__).resolve().parents[1] / "design-reference" / "design_handoff_nano_d_artwork_color"
               / "assets" / "apps")


def reference_pixel(r, g, b, a):
    """The spec, one pixel: composite onto black with Python's round, then round to RGB565."""
    r, g, b = (round(c * a / 255) for c in (r, g, b))
    value = ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)
    return value.to_bytes(2, "little")


def reference(image):
    data = image.convert("RGBA").tobytes()
    return b"".join(reference_pixel(*data[i:i + 4]) for i in range(0, len(data), 4))


def random_icon(seed, size=ICON_SIZE):
    rng = random.Random(seed)
    return Image.frombytes("RGBA", (size, size), bytes(rng.randrange(256) for _ in range(size * size * 4)))


class IconPayloadTests(unittest.TestCase):
    def test_every_colour_alpha_pair_matches_the_formula(self):
        # All 65,536 (c, a) pairs, each channel a different c: Pillow's premultiply
        # (MULDIV255) and the rounding tables against the spec's arithmetic.
        data = bytearray()
        for a in range(256):
            for c in range(256):
                data += bytes((c, 255 - c, (c * 7) % 256, a))
        image = Image.frombytes("RGBA", (256, 256), bytes(data))
        self.assertEqual(rgb565_over_black(image), reference(image))

    def test_payload_key_and_size(self):
        for seed in range(8):
            with self.subTest(seed=seed):
                icon = random_icon(seed)
                key, raw = icon_payload(icon)
                self.assertEqual(len(raw), ICON_BYTES)
                self.assertEqual(raw, reference(icon))
                self.assertEqual(key, hashlib.sha256(raw).hexdigest()[:ICON_KEY_CHARS])
                self.assertEqual(key, icon_key(raw))
                self.assertRegex(key, r"^[0-9a-f]{16}$")

    def test_rounding_and_little_endian_byte_order(self):
        cases = {
            (255, 255, 255, 255): b"\xff\xff",
            (0, 0, 0, 255): b"\x00\x00",
            (255, 255, 255, 0): b"\x00\x00",                # fully transparent: the black tile
            (255, 0, 0, 255): (0xF800).to_bytes(2, "little"),
            (0, 255, 0, 255): (0x07E0).to_bytes(2, "little"),
            (0, 0, 255, 255): (0x001F).to_bytes(2, "little"),
            (128, 128, 128, 255): (16 << 11 | 32 << 5 | 16).to_bytes(2, "little"),
            (4, 2, 4, 255): (0).to_bytes(2, "little"),     # rounds down below half a step
            (5, 3, 5, 255): (1 << 11 | 1 << 5 | 1).to_bytes(2, "little"),  # rounds up from half a step
            (255, 0, 0, 128): (16 << 11).to_bytes(2, "little"),  # 255*128/255 = 128 -> r5 16
            (200, 100, 50, 64): reference_pixel(200, 100, 50, 64),
        }
        for pixel, expected in cases.items():
            with self.subTest(pixel=pixel):
                _, raw = icon_payload(Image.new("RGBA", (ICON_SIZE, ICON_SIZE), pixel))
                self.assertEqual(raw[:2], expected)
                self.assertEqual(raw, expected * (ICON_SIZE * ICON_SIZE))

    def test_rgb565le_rounded_is_the_spec_rounding(self):
        rgb = bytes(v for c in range(256) for v in (c, 255 - c, c))
        expected = b"".join(reference_pixel(c, 255 - c, c, 255) for c in range(256))
        self.assertEqual(rgb565le_rounded(rgb), expected)

    def test_other_modes_and_sizes_are_fitted_like_icon_thumbnail(self):
        from control_center.windows import icon_thumbnail
        wide = random_icon(3, 64).resize((64, 40))
        self.assertEqual(icon_payload(wide), icon_payload(icon_thumbnail(wide)))
        rgb = Image.new("RGB", (32, 32), (10, 20, 30))
        self.assertEqual(icon_payload(rgb)[1], reference_pixel(10, 20, 30, 255) * 1024, "RGB is opaque")
        for path in sorted(DESIGN_APPS.glob("*.png")):
            with self.subTest(app=path.name), Image.open(path) as source:
                thumb = icon_thumbnail(source)
                self.assertEqual(icon_payload(thumb)[1], reference(thumb))

    def test_anything_but_an_image_is_refused(self):
        for value in (None, object(), b"\x00" * ICON_BYTES, "icon"):
            with self.subTest(value=type(value).__name__), self.assertRaises(ArtworkError):
                icon_payload(value)

    def test_payloads_are_cheap_enough_for_the_ui_thread(self):
        icons = [random_icon(seed) for seed in range(20)]
        started = time.perf_counter()
        for _ in range(10):
            for icon in icons:
                icon_payload(icon)
        per_icon = (time.perf_counter() - started) / 200
        self.assertLess(per_icon, 0.002, f"{per_icon * 1e6:.0f} us per icon")



class WorkerPayloadTests(unittest.TestCase):
    def test_attached_payload_travels_with_copies(self):
        icon = random_icon(11)
        self.assertIsNone(attached_icon_payload(icon))
        self.assertIs(attach_icon_payload(icon), icon)
        self.assertEqual(attached_icon_payload(icon), icon_payload(icon))
        delivered = icon.copy()          # what IconWorker.poll() hands the runtime
        self.assertEqual(attached_icon_payload(delivered), icon_payload(icon))

    def test_only_a_well_formed_payload_on_a_32px_icon_is_trusted(self):
        good = icon_payload(random_icon(12))
        for size, value in (((32, 32), None), ((32, 32), good[0]), ((32, 32), (good[0], good[1][:-1])),
                            ((32, 32), (good[0][:-1], good[1])), ((32, 32), [good[0], good[1]]),
                            ((64, 64), good)):
            with self.subTest(size=size, value=type(value).__name__):
                image = Image.new("RGBA", size)
                image.info[ICON_PAYLOAD_INFO] = value
                self.assertIsNone(attached_icon_payload(image))
        for value in (None, object(), "icon"):
            self.assertIs(attach_icon_payload(value), value, "never raises")
            self.assertIsNone(attached_icon_payload(value))

    def test_icon_worker_entries_carry_the_payload(self):
        from control_center.windows import IconWorker, icon_thumbnail

        def no_api():
            raise OSError("no Win32 in this test")
        worker = IconWorker(api_factory=no_api)
        self.addCleanup(worker.close, 2)
        source = random_icon(13, 48)
        thumb, accent = worker._entry(source)
        self.assertEqual(thumb.tobytes(), icon_thumbnail(source).tobytes())
        self.assertEqual(attached_icon_payload(thumb), icon_payload(icon_thumbnail(source)))
        self.assertEqual(attached_icon_payload(thumb.copy()), attached_icon_payload(thumb))
        self.assertEqual(worker._entry(None), (None, None))

    def test_icon_worker_delivers_icons_with_their_payload(self):
        from control_center import windows as w
        source = random_icon(14, 48)

        class Api:  # the IconApi surface IconWorker uses; no Win32 call is made
            def co_initialize(self):
                return False

            def co_uninitialize(self):
                pass

            def window_icon(self, hwnd, kind):
                return 101 if hwnd == 1 and kind == w.ICON_BIG else 0

            def icon_image(self, handle):
                return source.copy()

            def class_icon(self, hwnd, index):
                return 0

            def file_icon(self, path):
                return 0

            def destroy_icon(self, handle):
                pass

        worker = w.IconWorker(api_factory=Api)
        self.addCleanup(worker.close, 2)
        worker.request([{"id": "a", "hwnd": 1, "path": "", "app": "example"},
                        {"id": "u", "hwnd": 2, "path": "", "app": "ApplicationFrameHost"}])
        found, deadline = [], time.monotonic() + 3
        while len(found) < 2 and time.monotonic() < deadline:
            found.extend(worker.poll())
            time.sleep(0.005)
        self.assertEqual([item for item, _, _ in found], ["a", "u"])
        self.assertEqual(attached_icon_payload(found[0][1]), icon_payload(w.icon_thumbnail(source)))
        self.assertEqual(found[1][1:], (None, None), "UWP: no icon, so no payload")


if __name__ == "__main__":
    unittest.main()

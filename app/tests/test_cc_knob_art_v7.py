"""K3 section 10.5 knob art (WP6; K1 section 8.4; C5-58): the r2.1 scrim, the four knob art
states at 240 px, content-hash keys; plus the desktop request ladder, the unscrimmed
cover store, the sleeve inputs and the Generated-sleeve hash (K4 sections 13.1-13.6)."""
from io import BytesIO
import hashlib
from pathlib import Path
import sys
import threading
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import artwork  # noqa: E402
from control_center.artwork import (  # noqa: E402
    ArtworkError, CoverStore, GEN_PALETTE, art_request_size, art_rung, cover_key, gen_index, gen_sleeve,
    knob_generated_cover, knob_loading_cover, prepare_artwork, prepare_artwork2, sleeve_inputs,
)
from control_center.presentation import COVER_MAX_BYTES  # noqa: E402


def k1_factor(y):
    """K1 section 8.4, written out independently: s at the pixel centre y + 0.5."""
    c = y + 0.5
    stops = [(0, 0.60), (108, 0.72), (148.8, 0.92), (168, 1.0)]
    if c >= 168:
        s = 1.0
    else:
        for (c0, s0), (c1, s1) in zip(stops, stops[1:]):
            if c0 <= c <= c1:
                s = s0 + (s1 - s0) * (c - c0) / (c1 - c0)
                break
    return 0.8 * (1 - s)


def encode(image, fmt="PNG"):
    output = BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def jpeg_markers(data):
    markers, index = [], 2
    while index < len(data) - 1:
        marker = data[index + 1]
        if marker == 0xDA:
            break
        length = int.from_bytes(data[index + 2:index + 4], "big")
        markers.append(marker)
        index += 2 + length
    return markers


class ScrimTests(unittest.TestCase):
    def test_the_scrim_rows_match_k1s_formula(self):
        tables = artwork._scrim_rows()
        for y in (0, 107, 108, 148, 167, 168, 239):
            with self.subTest(row=y):
                self.assertEqual(tables[y][255], round(255 * k1_factor(y)))
                self.assertEqual(tables[y][100], round(100 * k1_factor(y)))
        self.assertEqual([tables[y][255] for y in (0, 108, 148, 168, 239)], [81, 57, 17, 0, 0])

    def test_a_white_cover_through_the_whole_pipeline(self):
        preview, raw, _ = prepare_artwork(encode(Image.new("RGB", (600, 600), "white")))
        for y in (0, 107, 108, 148, 168, 239):
            with self.subTest(row=y):
                self.assertEqual(preview.getpixel((120, y)), (round(255 * k1_factor(y)),) * 3)
        self.assertEqual(raw[-240:], bytes(240), "the v1 120 px cover is black below the scrim")

    def test_the_hires_cover_uses_the_same_scrim_at_its_row_centres(self):
        tables = artwork._hires_scrim_rows(480)
        for y in (0, 1, 216, 297, 335, 336, 479):
            with self.subTest(row=y):
                c = (y + 0.5) / 2
                self.assertAlmostEqual(tables[y][255] / 255, 0.8 * (1 - artwork._scrim_s(c)), delta=0.5 / 255 + 1e-9)
        self.assertEqual(tables[336][255], 0)


class KnobArtStateTests(unittest.TestCase):
    def test_full_from_a_large_source(self):
        cover = Image.new("RGB", (600, 600), (200, 40, 40))
        prepared = prepare_artwork2(encode(cover))
        self.assertEqual(prepared.preview.getpixel((120, 0)), tuple(round(v * k1_factor(0)) for v in (200, 40, 40)))
        self.assertEqual(prepared.jpeg_key, cover_key(prepared.jpeg))

    def test_extended_from_a_source_under_160_px(self):
        cover = Image.new("RGB", (100, 100), (30, 90, 250))   # u = 2.4 > 1.5
        preview, _, dominant = prepare_artwork(encode(cover))
        self.assertIsNotNone(dominant)
        # The cover sits sharp at 1.5 × (150 px) in the middle: rows 45..194, columns 45..194.
        self.assertEqual(preview.getpixel((120, 60)), tuple(round(v * k1_factor(60)) for v in (30, 90, 250)))
        corner = preview.getpixel((5, 5))
        self.assertNotEqual(corner, tuple(round(v * k1_factor(5)) for v in (30, 90, 250)),
                            "outside the cover: the radial gradient of its colour")
        self.assertGreater(corner[2], corner[0])
        full = prepare_artwork(encode(Image.new("RGB", (160, 160), (30, 90, 250))))[0]
        self.assertEqual(full.getpixel((5, 5)), tuple(round(v * k1_factor(5)) for v in (30, 90, 250)),
                         "u = 1.5 is still art.full")

    def test_loading_is_a_flat_art_bg_without_text(self):
        prepared = knob_loading_cover(0x123456)
        for x, y in ((0, 0), (120, 60), (239, 100)):
            self.assertEqual(prepared.preview.getpixel((x, y)),
                             tuple(round(v * k1_factor(y)) for v in (0x12, 0x34, 0x56)))
        empty = knob_loading_cover(0)
        self.assertEqual(empty.preview.getpixel((10, 0)), tuple(round(v * k1_factor(0)) for v in (0x23, 0x23, 0x25)))
        self.assertEqual(len(set(empty.preview.crop((0, 0, 240, 1)).getdata())), 1, "no text")

    def test_generated_is_the_gen_gradient_without_text(self):
        prepared = knob_generated_cover("Night Channel", "Sample library")
        g0, g1 = GEN_PALETTE[gen_index("Night Channel", "Sample library")][:2]
        top_left = prepared.preview.getpixel((0, 0))
        bottom = prepared.preview.getpixel((239, 120))
        start = [(g0 >> s) & 255 for s in (16, 8, 0)]
        self.assertTrue(all(abs(a - round(b * k1_factor(0))) <= 3 for a, b in zip(top_left, start)))
        self.assertNotEqual(top_left, prepared.preview.getpixel((239, 0)), "a gradient, not a fill")
        self.assertIsNotNone(bottom)
        self.assertIs(knob_generated_cover("Night Channel", "Sample library").jpeg,
                      knob_generated_cover("Night Channel", "Sample library").jpeg, "cached")

    def test_every_state_is_a_baseline_jpeg_keyed_by_its_content(self):
        detail = Image.new("RGB", (600, 600), (0x12, 0x34, 0x56))
        detail.paste((250, 250, 250), (0, 0, 300, 300))   # a real cover has detail its bgColor lacks
        real = prepare_artwork2(encode(detail))
        loading = knob_loading_cover(0x123456)
        generated = knob_generated_cover("A", "B")
        keys = {real.jpeg_key, loading.jpeg_key, generated.jpeg_key, knob_loading_cover(0x654321).jpeg_key}
        self.assertEqual(len(keys), 4, "a loading cover never shares the real cover's key")
        for prepared in (loading, generated, real):
            with self.subTest(key=prepared.jpeg_key):
                self.assertEqual(prepared.jpeg_key, hashlib.sha256(prepared.jpeg).hexdigest()[:24])
                self.assertLessEqual(len(prepared.jpeg), COVER_MAX_BYTES)
                self.assertIn(0xC0, jpeg_markers(prepared.jpeg))
                self.assertNotIn(0xC2, jpeg_markers(prepared.jpeg))
                self.assertEqual(len(prepared.raw), 120 * 120 * 2)
                with Image.open(BytesIO(prepared.hires_jpeg)) as hires:
                    self.assertEqual(hires.size, (480, 480))


class GeneratedSleeveTests(unittest.TestCase):
    # BS genOf (Browse and Snap.dc.html:537) evaluated with node 24 on 2026-09-25.
    GOLDEN = [("Night Channel", "Sample library", 5), ("PAPER LANTERN Ep. 1", "", 5), ("Tidal Glass", "Oskar Lind Trio", 6),
              ("Linnéa Holm – Début", "Linnéa Holm", 2), ("🎵 Emoji 🎶", "Ārtist", 4), ("", "", 5),
              ("Untitled playlist", "", 7), ("Favorite Songs", "Apple Music", 4), ("東京", "宇多田ヒカル", 2)]

    def test_the_hash_matches_bs(self):
        for title, artist, expected in self.GOLDEN:
            with self.subTest(title=title):
                self.assertEqual(gen_index(title, artist), expected)

    def test_the_sleeve_and_its_ring_accent(self):
        sleeve = gen_sleeve("Untitled playlist", "")
        self.assertEqual((sleeve["index"], sleeve["ring_accent"], sleeve["accent"]), (7, 0, 0xFFBE69))
        sleeve = gen_sleeve("Night Channel", "Sample library")
        self.assertEqual((sleeve["g0"], sleeve["g1"], sleeve["ink"], sleeve["ring_accent"]),
                         (0x2A4F57, 0x112326, 0xE9F4F5, (40 << 16) | (210 << 8) | 230))

    def test_sleeve_inputs(self):
        self.assertEqual({k: v for k, v in sleeve_inputs({"art_bg": 0, "art_ink": 0}).items() if k != "gen"},
                         {"bg": 0x232325, "ink": 0xF2F2F2, "dominant": None})
        inputs = sleeve_inputs({"art_bg": 0x1D1D1F, "art_ink": 0xF2E9E1, "title": "T", "artist": "A"}, dominant=0xFF0000)
        self.assertEqual((inputs["bg"], inputs["ink"], inputs["dominant"], inputs["gen"]["index"]),
                         (0x1D1D1F, 0xF2E9E1, 0xFF0000, gen_index("T", "A")))


class LadderTests(unittest.TestCase):
    def test_the_smallest_rung_over_need_over_1_1_capped_at_art_max(self):
        for need, expected in ((112, 240), (264, 240), (265, 600), (340, 600), (612, 600), (680, 1200),
                               (760, 1200), (1360, 1200)):
            with self.subTest(need=need):
                self.assertEqual(art_rung(need), expected)
        self.assertEqual(art_rung(680, art_max=600), 600)
        self.assertEqual(art_rung(1360, k=4), 2000)
        self.assertEqual(art_rung(1360, k=3.5), 1200, "2000 only above k = 3.5")

    def test_request_sizes_by_use(self):
        self.assertEqual([art_request_size(use) for use in ("explorer_center", "explorer_side", "mosaic_tile",
                                                            "upnext_cover", "upnext_row", "knob")],
                         [1200, 600, 600, 1200, 240, 240])
        self.assertEqual(art_request_size("upnext_cover", k=4), 2000)
        self.assertEqual(art_request_size("mosaic_tile", k=4), 600)
        self.assertEqual(art_request_size("explorer_center", art_max=1080), 1080)


class Response:
    def __init__(self, data):
        self.data, self.status_code, self.headers = data, 200, {"Content-Type": "image/jpeg"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        yield self.data


class Session:
    def __init__(self, data, gate=None):
        self.data, self.calls, self.gate = data, [], gate

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.gate is not None:
            self.gate.wait(5)
        return Response(self.data)


class CoverStoreTests(unittest.TestCase):
    TEMPLATE = "https://is1-ssl.mzstatic.com/image/thumb/a/{w}x{h}bb.jpg"

    def test_covers_are_stored_unscrimmed_by_template_and_rung(self):
        data = encode(Image.new("RGB", (60, 60), "white"), "JPEG")
        session = Session(data)
        store = CoverStore(session=session)
        self.assertIsNone(store.cached(self.TEMPLATE, 600))
        self.assertEqual(store.fetch(self.TEMPLATE, 600), data, "the encoded bytes, no scrim")
        self.assertEqual(session.calls[0][0], "https://is1-ssl.mzstatic.com/image/thumb/a/600x600bb.jpg")
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertEqual(store.fetch(self.TEMPLATE, 600), data)
        self.assertEqual(len(session.calls), 1)
        store.fetch(self.TEMPLATE, 1200)
        self.assertEqual(len(session.calls), 2, "another rung is another key")
        self.assertNotEqual(CoverStore.key_for(self.TEMPLATE, 600), CoverStore.key_for(self.TEMPLATE, 1200))
        self.assertNotIn("mzstatic", CoverStore.key_for(self.TEMPLATE, 600), "URLs never enter a key")

    def test_the_allowlist_and_the_byte_budget(self):
        store = CoverStore(session=Session(b""))
        with self.assertRaises(ArtworkError):
            store.fetch("https://evil.example/{w}x{h}.jpg", 600)
        with self.assertRaises(ArtworkError):
            store.fetch(sonos_url="http://192.168.1.99:1400/getaa?x=1")
        data = encode(Image.new("RGB", (60, 60), "white"), "JPEG")
        store = CoverStore(session=Session(data), budget_bytes=int(len(data) * 2.5))
        for rung in (240, 600, 1200):
            store.fetch(self.TEMPLATE, rung)
        self.assertIsNone(store.cached(self.TEMPLATE, 240), "least recently used dropped")
        self.assertLessEqual(store.size_bytes, int(len(data) * 2.5))
        sonos = CoverStore(("192.168.1.50",), session=Session(data))
        self.assertEqual(sonos.fetch(sonos_url="http://192.168.1.50:1400/getaa?s=1&u=x"), data)

    def test_one_download_per_key_across_threads(self):
        data = encode(Image.new("RGB", (60, 60), "white"), "JPEG")
        gate = threading.Event()
        session = Session(data, gate)
        store = CoverStore(session=session)
        results = []
        threads = [threading.Thread(target=lambda: results.append(store.fetch(self.TEMPLATE, 600)))
                   for _ in range(3)]
        for thread in threads:
            thread.start()
        gate.set()
        for thread in threads:
            thread.join(5)
        self.assertEqual((len(results), len(session.calls)), (3, 1))


if __name__ == "__main__":
    unittest.main()

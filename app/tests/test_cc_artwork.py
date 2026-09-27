from io import BytesIO
import hashlib
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import artwork
from control_center.artwork import (
    ArtworkError, ArtworkService, apple_artwork_url, artwork_url, cover_jpeg, cover_key,
    prepare_artwork, prepare_artwork2, sonos_artwork_url, dominant_color, MAX_DOWNLOAD,
)
from control_center.presentation import COVER_JPEG_QUALITIES, COVER_KEY_CHARS, COVER_MAX_BYTES, COVER_SIZE

ROOT = Path(__file__).resolve().parents[1]
DESIGN_COVERS = ROOT / "design-reference" / "design_handoff_nano_d_artwork_color" / "assets" / "covers"


def png(color=(255, 255, 255), size=(40, 20)):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


class Response:
    status_code = 200
    def __init__(self, data, *, status=200, headers=None):
        self.data = data
        self.status_code = status
        self.headers = headers if headers is not None else {"Content-Type": "image/png"}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, chunk_size): yield self.data


class Session:
    def __init__(self, responses): self.responses, self.calls = responses, []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses[url]
        return result() if callable(result) else result


class ArtworkTests(unittest.TestCase):
    def test_sources_allow_only_apple_cdn_or_configured_sonos_art(self):
        self.assertEqual(artwork_url("https://is1-ssl.mzstatic.com/image/cover.jpg"), "https://is1-ssl.mzstatic.com/image/cover.jpg")
        self.assertEqual(sonos_artwork_url("/getaa?s=1&u=abc", "192.168.1.50"), "http://192.168.1.50:1400/getaa?s=1&u=abc")
        for url in ("http://is1-ssl.mzstatic.com/cover", "https://mzstatic.com.evil.test/a", "file:///x",
                    "http://127.0.0.1:1400/getaa", "http://169.254.169.254:1400/getaa",
                    "http://192.168.1.88:1400/getaa", "http://192.168.1.50:80/getaa",
                    "http://192.168.1.50:1400/status", "https://user:secret@is1-ssl.mzstatic.com/a",
                    "https://is1-ssl.mzstatic.com:444/a", "https://is1-ssl.mzstatic.com/a#fragment"):
            with self.subTest(url=url), self.assertRaises(ArtworkError):
                artwork_url(url, ("192.168.1.50", "127.0.0.1", "169.254.169.254"))

    def test_apple_template_metadata_falls_back_without_breaking_library(self):
        self.assertEqual(apple_artwork_url({"url": "https://is1-ssl.mzstatic.com/a/{w}x{h}.{f}"}),
                         "https://is1-ssl.mzstatic.com/a/480x480.jpg")
        for invalid in (None, [], {"url": None}, {"url": "https://evil.test/a"}, {"url": "https://is1-ssl.mzstatic.com/{unknown}"}):
            self.assertEqual(apple_artwork_url(invalid), "")

    def test_native_preview_uses_handoff_scrim_and_transport_is_little_endian(self):
        # The r2.1 scrim at pixel centres (K1 section 8.4): .60 / .72 / .92 / 1.0 under 0.8 opacity.
        preview, raw, color = prepare_artwork(png(size=(400, 300)))
        self.assertEqual(preview.size, (240, 240))
        self.assertEqual(len(raw), 120 * 120 * 2)
        self.assertEqual(preview.getpixel((120, 0)), (81, 81, 81))
        self.assertEqual(preview.getpixel((120, 108)), (57, 57, 57))
        self.assertEqual(preview.getpixel((120, 168)), (0, 0, 0))
        self.assertEqual(raw[-240:], bytes(240))
        red, raw, _ = prepare_artwork(png((255, 0, 0), (400, 300)))
        self.assertEqual(int.from_bytes(raw[:2], "little") & 0x7FF, 0)
        self.assertGreater(int.from_bytes(raw[:2], "little") >> 11, 0)

    def test_invalid_and_oversize_encoded_art_fails_cleanly(self):
        for data in (b"", b"not an image", bytes(MAX_DOWNLOAD + 1)):
            with self.assertRaises(ArtworkError): prepare_artwork(data)

    def wait_result(self, service):
        until = time.monotonic() + 2
        while time.monotonic() < until:
            found = service.poll()
            if found: return found[0]
            time.sleep(.005)
        self.fail("Artwork result not produced")

    def test_debounce_fetches_only_last_selection_and_cache_is_reused(self):
        a, b = "https://is1-ssl.mzstatic.com/a", "https://is1-ssl.mzstatic.com/b"
        session = Session({a: Response(png()), b: Response(png((255, 0, 0)))})
        service = ArtworkService(session=session, debounce=.025)
        try:
            service.request(a, token="old")
            service.request(b, token="new")
            result = self.wait_result(service)
            self.assertEqual(result.token, "new")
            self.assertFalse(result.error)
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(session.calls[0][0], b)
            self.assertFalse(session.calls[0][1]["allow_redirects"])
            self.assertEqual(session.calls[0][1]["headers"], {"Accept": "image/*"})
            service.request(b, token="another-control")
            again = self.wait_result(service)
            self.assertEqual(again.key, result.key)
            self.assertEqual(len(session.calls), 1)
        finally: service.close()

    def test_result_from_superseded_inflight_request_never_surfaces(self):
        a, b = "https://is1-ssl.mzstatic.com/a", "https://is1-ssl.mzstatic.com/b"
        started, proceed = threading.Event(), threading.Event()
        def blocked():
            started.set()
            proceed.wait(1)
            return Response(png())
        session = Session({a: blocked, b: Response(png((0, 0, 255)))})
        service = ArtworkService(session=session, debounce=0)
        try:
            service.request(a, "old")
            self.assertTrue(started.wait(1))
            service.request(b, "current")
            proceed.set()
            result = self.wait_result(service)
            self.assertEqual(result.token, "current")
            self.assertFalse(result.error)
        finally:
            proceed.set()
            service.close()

    def test_redirect_content_length_and_nonimage_fallbacks(self):
        url = "https://is1-ssl.mzstatic.com/a"
        for response in (Response(png(), status=302), Response(png(), headers={"Content-Length": str(MAX_DOWNLOAD + 1)}),
                         Response(png(), headers={"Content-Type": "text/html"})):
            service = ArtworkService(session=Session({url: response}), debounce=0)
            try:
                service.request(url, "t")
                result = self.wait_result(service)
                self.assertTrue(result.error)
                self.assertFalse(result.key)
            finally: service.close()

    def test_cached_answers_synchronously_and_is_keyed_like_the_worker(self):
        sonos = "http://192.168.1.50:1400/getaa?s=1&u=abc"
        session = Session({sonos: Response(png((0, 128, 255)))})
        service = ArtworkService(session=session, debounce=0)
        try:
            self.assertIsNone(service.cached(sonos, "t", speaker_host="192.168.1.50"), "a miss before any load")
            service.request(sonos, "t", speaker_host="192.168.1.50")
            loaded = self.wait_result(service)
            self.assertFalse(loaded.error)
            hit = service.cached(sonos, "other-token", speaker_host="192.168.1.50")
            self.assertEqual((hit.token, hit.key, hit.rgb565, hit.dominant, hit.error),
                             ("other-token", loaded.key, loaded.rgb565, loaded.dominant, ""))
            self.assertEqual(hit.preview.size, (240, 240))
            self.assertEqual(hit.preview.tobytes(), loaded.preview.tobytes())
            self.assertIsNot(hit.preview, service.cached(sonos, speaker_host="192.168.1.50").preview,
                             "each hit is its own copy of the cached preview")
            # The worker would refuse this URL without its speaker: never a hit either.
            self.assertIsNone(service.cached(sonos, "t"))
            for invalid in ("", None, "https://evil.test/a", "file:///x"):
                self.assertIsNone(service.cached(invalid, "t", speaker_host="192.168.1.50"))
            self.assertEqual(len(session.calls), 1, "cached() never downloads")
            self.assertEqual(service.poll(), [], "cached() never queues a result")
        finally: service.close()
        self.assertIsNone(service.cached(sonos, "t", speaker_host="192.168.1.50"), "nothing after close")

    def test_only_a_miss_waits_for_the_debounce(self):
        a, b = "https://is1-ssl.mzstatic.com/a", "https://is1-ssl.mzstatic.com/b"
        session = Session({a: Response(png()), b: Response(png((255, 0, 0)))})
        service = ArtworkService(session=session, debounce=0)
        try:
            service.request(a, "a")
            cover = self.wait_result(service)
            service.debounce = 5.0
            started = time.monotonic()
            service.request(a, "a-again")  # cached: no debounce, no download
            again = self.wait_result(service)
            self.assertLess(time.monotonic() - started, 2.0)
            self.assertEqual((again.token, again.key), ("a-again", cover.key))
            self.assertEqual(len(session.calls), 1)
            service.debounce = 1.0
            service.request(b, "b")  # a miss is debounced before its download starts
            time.sleep(0.05)
            self.assertEqual((len(session.calls), service.poll()), (1, []))
            result = self.wait_result(service)
            self.assertEqual((result.token, len(session.calls), session.calls[-1][0]), ("b", 2, b))
        finally: service.close()

    def test_clear_discards_ready_result(self):
        url = "https://is1-ssl.mzstatic.com/a"
        service = ArtworkService(session=Session({url: Response(png())}), debounce=0)
        try:
            service.request(url, "t")
            self.wait_result(service)
            service.clear()
            self.assertEqual(service.poll(), [])
        finally: service.close()


def jpeg_segments(data):
    """(marker, payload) of every segment before the scan, then ('SOS', header); checks SOI/EOI."""
    assert data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9", "SOI ... EOI"
    segments, i = [], 2
    while True:
        assert data[i] == 0xFF, f"marker expected at {i}"
        marker = data[i + 1]
        length = int.from_bytes(data[i + 2:i + 4], "big")
        payload = data[i + 4:i + 2 + length]
        if marker == 0xDA:
            segments.append(("SOS", payload))
            return segments
        segments.append((marker, payload))
        i += 2 + length


def psnr(a, b):
    x, y = a.convert("RGB").tobytes(), b.convert("RGB").tobytes()
    mse = sum((p - q) ** 2 for p, q in zip(x, y)) / len(x)
    return float("inf") if mse == 0 else 10 * math.log10(255 ** 2 / mse)


def noisy_preview(seed=7):
    """A 240 px preview hard enough to push the encoder down its quality ladder."""
    import random
    rng = random.Random(seed)
    return Image.frombytes("RGB", (COVER_SIZE, COVER_SIZE), bytes(rng.randrange(256) for _ in range(COVER_SIZE ** 2 * 3)))


class CoverJpegTests(unittest.TestCase):
    """ARTWORK2.md section 5: the host's artwork2 cover encoder."""

    def encode(self, image, quality):
        out = BytesIO()
        image.save(out, format="JPEG", quality=quality, subsampling=2, optimize=True, progressive=False)
        return out.getvalue()

    def test_design_covers_are_baseline_420_jfif_without_metadata(self):
        covers = sorted(DESIGN_COVERS.iterdir())
        self.assertGreaterEqual(len(covers), 9)
        for path in covers:
            with self.subTest(cover=path.name):
                prepared = prepare_artwork2(path.read_bytes())
                jpeg = prepared.jpeg
                self.assertLessEqual(len(jpeg), COVER_MAX_BYTES)
                self.assertEqual(prepared.jpeg_key, hashlib.sha256(jpeg).hexdigest()[:COVER_KEY_CHARS])
                segments = jpeg_segments(jpeg)
                markers = [m for m, _ in segments]
                self.assertEqual(markers[0], 0xE0, "JFIF APP0 first")
                self.assertTrue(segments[0][1].startswith(b"JFIF\x00"))
                self.assertEqual(set(markers) - {0xE0, 0xDB, 0xC4, 0xC0, "SOS"}, set(),
                                 "no EXIF/ICC/comment/progressive or other segment")
                self.assertEqual(markers.count(0xC0), 1, "one baseline SOF0")
                sof = dict(segments)[0xC0]
                self.assertEqual((sof[0], int.from_bytes(sof[1:3], "big"), int.from_bytes(sof[3:5], "big"), sof[5]),
                                 (8, COVER_SIZE, COVER_SIZE, 3), "8-bit 240 x 240 YCbCr")
                self.assertEqual([sof[6 + 3 * c:9 + 3 * c][:2] for c in range(3)],
                                 [bytes((1, 0x22)), bytes((2, 0x11)), bytes((3, 0x11))], "4:2:0")
                with Image.open(BytesIO(jpeg)) as decoded:
                    self.assertEqual((decoded.format, decoded.mode, decoded.size), ("JPEG", "RGB", (240, 240)))
                    self.assertNotIn("progressive", decoded.info)
                    # The pixels are the 240 px composited preview itself (no RGB565 step).
                    self.assertGreater(psnr(decoded, prepared.preview), 30)

    def test_the_same_pass_keeps_the_v1_payload(self):
        data = (DESIGN_COVERS / "kind-of-blue.jpg").read_bytes()
        preview, raw, dominant = prepare_artwork(data)
        prepared = prepare_artwork2(data)
        self.assertEqual((prepared.raw, prepared.dominant), (raw, dominant))
        self.assertEqual(prepared.preview.tobytes(), preview.tobytes())
        self.assertEqual(len(prepared.raw), 120 * 120 * 2)
        self.assertEqual(cover_jpeg(prepared.preview), (prepared.jpeg_key, prepared.jpeg), "deterministic")

    def test_the_first_ladder_quality_that_fits_is_used(self):
        preview = noisy_preview()
        sizes = {q: len(self.encode(preview, q)) for q in COVER_JPEG_QUALITIES}
        self.assertEqual(COVER_JPEG_QUALITIES, (85, 80, 75, 70, 65, 60))
        self.assertGreater(sizes[85], COVER_MAX_BYTES, "noise does not fit at 85")
        key, jpeg = cover_jpeg(preview)
        expected = next(q for q in COVER_JPEG_QUALITIES if sizes[q] <= COVER_MAX_BYTES)
        self.assertEqual(jpeg, self.encode(preview, expected))
        self.assertEqual(key, cover_key(jpeg))
        for limit_quality in COVER_JPEG_QUALITIES:
            with self.subTest(limit=limit_quality), patch.object(artwork, "COVER_MAX_BYTES", sizes[limit_quality]):
                chosen = next(q for q in COVER_JPEG_QUALITIES if sizes[q] <= sizes[limit_quality])
                self.assertEqual(cover_jpeg(preview)[1], self.encode(preview, chosen))

    def test_no_fitting_quality_means_no_artwork2_cover(self):
        data = (DESIGN_COVERS / "moon-safari.png").read_bytes()
        with patch.object(artwork, "COVER_MAX_BYTES", 200):
            self.assertEqual(cover_jpeg(prepare_artwork(data)[0]), (None, None))
            prepared = prepare_artwork2(data)
        self.assertIsNone(prepared.jpeg)
        self.assertIsNone(prepared.jpeg_key)
        self.assertEqual(len(prepared.raw), 120 * 120 * 2, "a cc5.2 knob still gets v1 art")

    def test_source_metadata_never_reaches_the_file(self):
        preview = prepare_artwork(png((10, 200, 90), (300, 260)))[0]
        preview.info.update(icc_profile=b"ICC" * 50, exif=b"Exif\x00\x00" + bytes(20), comment=b"private")
        _, jpeg = cover_jpeg(preview)
        markers = [m for m, _ in jpeg_segments(jpeg)]
        for marker in (0xE1, 0xE2, 0xFE, 0xC2):
            self.assertNotIn(marker, markers)
        self.assertNotIn(b"private", jpeg)

    def test_only_a_240_px_image_is_encoded(self):
        for image in (Image.new("RGB", (120, 120)), Image.new("RGB", (240, 239)), b"not an image", None):
            with self.subTest(image=image), self.assertRaises(ArtworkError):
                cover_jpeg(image)
        key, jpeg = cover_jpeg(Image.new("RGBA", (240, 240), (1, 2, 3, 4)))
        self.assertEqual(len(key), COVER_KEY_CHARS)



class HiresCoverTests(unittest.TestCase):
    """Desktop v5 (FLOATING_KNOB.md section 2): ArtworkResult.hires_jpeg, built in the same prepare pass."""

    def test_design_covers_get_a_480_px_baseline_quality_90_jpeg_of_the_same_crop_and_scrim(self):
        reference = BytesIO()
        Image.new("RGB", (16, 16), (90, 40, 200)).save(reference, format="JPEG", quality=90, subsampling=2)
        with Image.open(BytesIO(reference.getvalue())) as encoded:
            q90 = encoded.quantization
        for path in sorted(DESIGN_COVERS.iterdir()):
            with self.subTest(cover=path.name):
                prepared = prepare_artwork2(path.read_bytes())
                data = prepared.hires_jpeg
                self.assertIsInstance(data, bytes)
                self.assertLess(len(data), 64 * 1024)
                markers = [m for m, _ in jpeg_segments(data)]
                self.assertEqual(markers.count(0xC0), 1, "one baseline SOF0")
                self.assertEqual(set(markers) - {0xE0, 0xDB, 0xC4, 0xC0, "SOS"}, set(), "no metadata")
                with Image.open(BytesIO(data)) as decoded:
                    self.assertEqual((decoded.format, decoded.size), ("JPEG", (artwork.HIRES_SIZE,) * 2))
                    self.assertEqual(decoded.quantization, q90)
                    hires = decoded.convert("RGB")
                # Downsampled to 240 it is the knob's preview: the same crop, scrim and opacity.
                self.assertGreater(psnr(hires.reduce(2), prepared.preview), 28)

    def test_the_scrim_is_the_previews_made_continuous(self):
        size = artwork.HIRES_SIZE
        tables = artwork._hires_scrim_rows(size)
        self.assertEqual(len(tables), size)
        for y in (0, 1, 215, 216, 297, 335, 336, 479):
            centre = (y + .5) * 240 / size   # the knob coordinate of this row's centre
            with self.subTest(y=y):
                self.assertEqual(tables[y][255], round(255 * artwork._scrim_factor(centre)))
        # Each knob row's two hi-res rows straddle the 240 px preview's own factor.
        for row in range(1, 239):
            low, high = sorted((tables[2 * row][255], tables[2 * row + 1][255]))
            self.assertLessEqual(low - 1, artwork._scrim_rows()[row][255])
            self.assertLessEqual(artwork._scrim_rows()[row][255], high + 1)
        white = prepare_artwork2(png((255, 255, 255), (600, 600)))
        with Image.open(BytesIO(white.hires_jpeg)) as decoded:
            column = [decoded.convert("L").getpixel((240, y)) for y in range(size)]
        self.assertAlmostEqual(column[0], 82, delta=3)                   # 0.8 * 0.40 at the top
        self.assertLessEqual(max(column[340:]), 3)                       # solid black from knob row 168
        self.assertTrue(all(b <= a + 3 for a, b in zip(column, column[1:])), "never brighter lower down")

    def test_the_v1_and_artwork2_payloads_are_unchanged(self):
        data = (DESIGN_COVERS / "kind-of-blue.jpg").read_bytes()
        preview, raw, dominant = prepare_artwork(data)
        prepared = prepare_artwork2(data)
        self.assertEqual((prepared.preview.tobytes(), prepared.raw, prepared.dominant),
                         (preview.tobytes(), raw, dominant))
        self.assertEqual(cover_jpeg(prepared.preview), (prepared.jpeg_key, prepared.jpeg))
        self.assertEqual(prepared[:5], (prepared.preview, raw, dominant, prepared.jpeg, prepared.jpeg_key))
        self.assertEqual(prepare_artwork2(data).hires_jpeg, prepared.hires_jpeg, "deterministic")
        with patch.object(artwork, "hires_cover_jpeg", return_value=None):
            without = prepare_artwork2(data)
        self.assertIsNone(without.hires_jpeg)
        self.assertEqual((without.jpeg, without.raw), (prepared.jpeg, prepared.raw), "the knob's covers never depend on it")

    def test_encoder_failures_only_lose_the_hires_cover(self):
        self.assertIsNone(artwork.hires_cover_jpeg(object()))
        tiny = artwork.hires_cover_jpeg(Image.new("RGB", (8, 6), (200, 0, 0)))
        with Image.open(BytesIO(tiny)) as decoded:
            self.assertEqual(decoded.size, (artwork.HIRES_SIZE,) * 2)

    def test_result_and_prepared_fields(self):
        import dataclasses
        names = [f.name for f in dataclasses.fields(artwork.ArtworkResult)]
        self.assertEqual(names, ["token", "key", "preview", "rgb565", "dominant", "error", "jpeg", "jpeg_key",
                                 "hires_jpeg"])
        self.assertIsNone(artwork.ArtworkResult("t").hires_jpeg)
        self.assertEqual(artwork.PreparedArtwork._fields[-1], "hires_jpeg")
        self.assertEqual(artwork.PreparedArtwork._fields[:5], ("preview", "raw", "dominant", "jpeg", "jpeg_key"))

    def wait(self, predicate, what):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            value = predicate()
            if value:
                return value
            time.sleep(.005)
        self.fail(f"{what} not produced")

    def test_service_results_and_cache_carry_the_hires_cover(self):
        """No network: the fake session serves the bytes."""
        a, b = "https://is1-ssl.mzstatic.com/a", "https://is1-ssl.mzstatic.com/b"
        data_a, data_b = png((200, 60, 20), (500, 500)), png((20, 60, 200), (500, 500))
        session = Session({a: Response(data_a), b: Response(data_b)})
        service = ArtworkService(session=session, debounce=0)
        try:
            service.request(a, "t")
            result = self.wait(service.poll, "result")[0]
            expected = prepare_artwork2(data_a)
            self.assertEqual((result.token, result.hires_jpeg), ("t", expected.hires_jpeg))
            self.assertEqual(result.jpeg_key, expected.jpeg_key)
            self.assertEqual(service.cached(a, "u").hires_jpeg, expected.hires_jpeg)
            self.assertEqual(service.cached_hires(a), (expected.jpeg_key, expected.hires_jpeg))
            self.assertIsNone(service.cached_hires(b))
            self.assertIsNone(service.cached_hires("https://evil.test/a"))
            service.prefetch([b], page=("recent", 1))
            hit = self.wait(lambda: service.cached_hires(b), "prefetched hi-res cover")
            self.assertEqual(hit, (prepare_artwork2(data_b).jpeg_key, prepare_artwork2(data_b).hires_jpeg))
            self.assertEqual(len(session.calls), 2)
        finally:
            service.close()


if __name__ == "__main__": unittest.main()

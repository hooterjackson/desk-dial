"""Targeted-colour sources: dominant_rgb (knob-model.js port), AccentService,
Apple accent URLs, simulator accents and the design reference table.

No network: every HTTP session is a fake. The JS cross-check runs the design's
knob-model.js under node (skipped when node is not installed).

Regenerate the reference table (needs node) after a deliberate change with:
    .venv\\Scripts\\python.exe tests\\test_cc_accents.py --write-reference
"""
from io import BytesIO
from pathlib import Path
import base64
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageOps

from control_center import artwork
from control_center.artwork import (
    ACCENT_SIZE, AccentService, ArtworkResult, apple_artwork_url, dominant_color,
    dominant_from_sample, dominant_rgb, dominant_sample, prepare_artwork,
)
from control_center.apple_music import AppleMusicClient
from control_center.simulation import SimulatedAppleMusic, SimulatedWindows

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "design-reference" / "design_handoff_nano_d_artwork_color"
MODEL_JS = DESIGN / "knob-model.js"
CHECK_JS = Path(__file__).resolve().parent / "js" / "dominant_check.cjs"
REFERENCE = Path(__file__).resolve().parent / "fixtures" / "dominant_reference.json"
RED, BLUE, CLEAR = (255, 0, 0, 255), (0, 0, 255, 255), (0, 0, 0, 0)


def tile(pixels):
    """24x24 RGBA image: ``pixels`` in row-major order, the rest transparent."""
    pixels = list(pixels)
    assert len(pixels) <= 576
    image = Image.new("RGBA", (24, 24), CLEAR)
    image.putdata(pixels + [CLEAR] * (576 - len(pixels)))
    return image


def encode(image, fmt="PNG"):
    output = BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def rgb_text(value):
    """NanoModel.COLORS string form ("r,g,b") of an int accent, or None."""
    return None if value is None else f"{value >> 16},{(value >> 8) & 255},{value & 255}"


def design_assets():
    """{"covers/x.jpg": path} for every design sample cover and app icon."""
    found = {}
    for group in ("covers", "apps"):
        for path in sorted((DESIGN / "assets" / group).glob("*")):
            if path.is_file():
                found[f"{group}/{path.name}"] = path
    return found


def asset_sample(path):
    with Image.open(path) as image:
        return dominant_sample(ImageOps.exif_transpose(image))


# Synthetic 24x24 samples shared by the unit tests and the JS cross-check.
SAMPLES = {
    "solid-orange": [(200, 80, 40, 255)] * 576,
    "grey": [(128, 128, 128, 255)] * 576,
    "black": [(0, 0, 0, 255)] * 576,
    "white": [(255, 255, 255, 255)] * 576,
    "low-saturation": [(200, 180, 170, 255)] * 576,
    "dark-red": [(49, 0, 0, 255)] * 576,
    "value-50-edge": [(50, 0, 0, 255)] * 30,
    "saturation-0.3-edge": [(100, 70, 70, 255)] * 60,
    "saturation-below-0.3": [(100, 71, 71, 255)] * 576,
    "transparent-red": [(255, 0, 0, 127)] * 200 + [BLUE] * 10,
    "alpha-128-red": [(255, 0, 0, 128)] * 10 + [BLUE] * 5,
    "weight-beats-count": [(100, 60, 60, 255)] * 60 + [(0, 255, 0, 255)] * 20,
    "tie-red-first": [RED] * 10 + [BLUE] * 10,
    "tie-blue-first": [BLUE] * 10 + [RED] * 10,
    "weight-exactly-4": [RED] * 4,
    "weight-3": [RED] * 3,
    "weight-just-under-4": [RED] * 3 + [(254, 0, 0, 255)],
    "weight-just-over-4": [RED] * 4 + [(254, 0, 0, 255)],
    "mixed-bin-mean": [(255, 40, 10, 255)] * 7 + [(230, 50, 20, 255)] * 5 + [(0, 0, 0, 255)] * 20,
}


class DominantRgbTests(unittest.TestCase):
    def test_solid_saturated_colour_normalises_max_channel_to_255(self):
        self.assertEqual(dominant_rgb(Image.new("RGB", (100, 60), (200, 80, 40))), 0xFF6633)
        self.assertEqual(dominant_rgb(Image.new("RGB", (7, 300), (0, 0, 180))), 0x0000FF)
        self.assertEqual(dominant_rgb(tile(SAMPLES["solid-orange"])), 0xFF6633)

    def test_greys_black_white_and_dim_or_pale_pixels_are_none(self):
        for name in ("grey", "black", "white", "low-saturation", "dark-red", "saturation-below-0.3"):
            with self.subTest(name=name):
                self.assertIsNone(dominant_rgb(tile(SAMPLES[name])))
        self.assertIsNone(dominant_rgb(Image.new("RGBA", (40, 40), (255, 0, 0, 0))))

    def test_value_and_saturation_edges_are_inclusive(self):
        self.assertEqual(dominant_rgb(tile(SAMPLES["value-50-edge"])), 0xFF0000)
        edge = dominant_rgb(tile(SAMPLES["saturation-0.3-edge"]))
        self.assertIsNotNone(edge)
        self.assertEqual(edge >> 16, 255)

    def test_transparent_pixels_are_ignored_from_alpha_128(self):
        self.assertEqual(dominant_rgb(tile(SAMPLES["transparent-red"])), 0x0000FF)
        self.assertEqual(dominant_rgb(tile(SAMPLES["alpha-128-red"])), 0xFF0000)

    def test_heavier_saturation_value_bin_wins_over_pixel_count(self):
        self.assertEqual(dominant_rgb(tile(SAMPLES["weight-beats-count"])), 0x00FF00)
        two = tile([(0, 128, 0, 255)] * 30 + [RED] * 10)  # 30 x 0.502 beats 10 x 1.0
        self.assertEqual(dominant_rgb(two), 0x00FF00)

    def test_exact_tie_keeps_lowest_key_regardless_of_pixel_order(self):
        # Blue is key 7, red key 448; both bins weigh exactly 10.0.
        self.assertEqual(dominant_rgb(tile(SAMPLES["tie-red-first"])), 0x0000FF)
        self.assertEqual(dominant_rgb(tile(SAMPLES["tie-blue-first"])), 0x0000FF)

    def test_minimum_weight_is_four(self):
        self.assertEqual(dominant_rgb(tile(SAMPLES["weight-exactly-4"])), 0xFF0000)
        self.assertEqual(dominant_rgb(tile(SAMPLES["weight-just-over-4"])), 0xFF0000)
        self.assertIsNone(dominant_rgb(tile(SAMPLES["weight-3"])))
        self.assertIsNone(dominant_rgb(tile(SAMPLES["weight-just-under-4"])))  # 3 + 254/255

    def test_weighted_mean_uses_js_rounding(self):
        # Mean of one bin, normalised; values computed by hand with JS semantics.
        data = tile(SAMPLES["mixed-bin-mean"]).tobytes()
        bins = [0.0, 0.0, 0.0, 0.0]
        for i in range(0, len(data), 4):
            r, g, b, a = data[i:i + 4]
            mx, mn = max(r, g, b), min(r, g, b)
            if a < 128 or mx < 50 or (mx - mn) / mx < 0.3:
                continue
            w = (mx - mn) / mx * (mx / 255)
            bins = [bins[0] + w, bins[1] + r * w, bins[2] + g * w, bins[3] + b * w]
        mean = [bins[1] / bins[0], bins[2] / bins[0], bins[3] / bins[0]]
        expected = [int(v / max(mean) * 255 + 0.5) for v in mean]
        self.assertEqual(dominant_from_sample(data), (expected[0] << 16) | (expected[1] << 8) | expected[2])
        self.assertEqual(artwork._js_round(2.5), 3)
        self.assertEqual(artwork._js_round(0.49999999999999994), 0)

    def test_whole_image_is_sampled_without_crop(self):
        # A centre crop would see only blue; the whole image is mostly red.
        image = Image.new("RGB", (100, 20), (255, 0, 0))
        image.paste((0, 0, 255), (40, 0, 60, 20))
        self.assertEqual(dominant_rgb(image), 0xFF0000)
        self.assertEqual(len(dominant_sample(image)), 24 * 24 * 4)

    def test_palette_and_la_images_convert_through_rgba(self):
        palette = Image.new("P", (30, 30), 1)
        palette.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        self.assertEqual(dominant_rgb(palette), 0xFF0000)
        self.assertIsNone(dominant_rgb(Image.new("LA", (30, 30), (200, 255))))

    def test_compatibility_wrapper_maps_none_to_white(self):
        self.assertEqual(dominant_color(Image.new("RGB", (8, 8), (90, 90, 90))), 0xFFFFFF)
        self.assertEqual(dominant_color(Image.new("RGB", (8, 8), (200, 80, 40))), 0xFF6633)


def legacy_prepare(encoded):
    """The pre-Stage-4 per-pixel scrim and RGB565 loops, kept verbatim for comparison."""
    with Image.open(BytesIO(encoded)) as source:
        source.seek(0)
        source = ImageOps.exif_transpose(source)
        cropped = ImageOps.fit(source.convert("RGB"), (240, 240), method=Image.Resampling.LANCZOS)
    # K1 section 8.4 (r2.1 scrim): s at the pixel centre y + 0.5, 1 from 168 down.
    stops = ((0, .60), (108, .72), (148.8, .92), (168, 1.0), (240, 1.0))
    pixels = bytearray(cropped.tobytes())
    for y in range(240):
        c = y + .5
        for (y0, a0), (y1, a1) in zip(stops, stops[1:]):
            if y0 <= c <= y1:
                factor = .8 * (1 - (a0 + (a1 - a0) * (c - y0) / (y1 - y0)))
                break
        start = y * 240 * 3
        for i in range(start, start + 240 * 3):
            pixels[i] = round(pixels[i] * factor)
    preview = Image.frombytes("RGB", (240, 240), bytes(pixels))
    pixels = preview.resize((120, 120), Image.Resampling.LANCZOS).tobytes()
    raw = bytearray(120 * 120 * 2)
    for source_offset, target_offset in zip(range(0, len(pixels), 3), range(0, len(raw), 2)):
        r, g, b = pixels[source_offset:source_offset + 3]
        packed = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        raw[target_offset] = packed & 255
        raw[target_offset + 1] = packed >> 8
    return preview.tobytes(), bytes(raw)


class PrepareArtworkTests(unittest.TestCase):
    def fixtures(self):
        rng = random.Random(20260922)
        noise = Image.frombytes("RGB", (317, 211), bytes(rng.randrange(256) for _ in range(317 * 211 * 3)))
        gradient = Image.new("RGB", (256, 256))
        gradient.putdata([(x, y, (x * y) % 256) for y in range(256) for x in range(256)])
        rgba = Image.new("RGBA", (180, 260), (30, 200, 90, 120))
        found = {"noise.png": encode(noise), "gradient.jpg": encode(gradient, "JPEG"), "rgba.png": encode(rgba)}
        assets = design_assets()
        for name in ("covers/blue-lines.jpg", "covers/hounds-of-love.png", "apps/chatgpt.png", "apps/chrome.png"):
            if name in assets:
                found[name] = assets[name].read_bytes()
        return found

    def test_vectorised_scrim_and_rgb565_are_byte_identical_to_legacy_loops(self):
        for name, data in self.fixtures().items():
            with self.subTest(name=name):
                preview, raw, _ = prepare_artwork(data)
                old_preview, old_raw = legacy_prepare(data)
                self.assertEqual(preview.tobytes(), old_preview)
                self.assertEqual(raw, old_raw)

    def test_dominant_comes_from_uncropped_source_before_scrim(self):
        wide = Image.new("RGB", (900, 300), (255, 0, 0))
        wide.paste((0, 0, 255), (300, 0, 600, 300))  # the centre crop is all blue (300 px: art.full)
        preview, _, dominant = prepare_artwork(encode(wide))
        self.assertEqual(dominant, 0xFF0000)
        r, g, b = preview.getpixel((120, 20))
        self.assertGreater(b, r)
        self.assertIsNone(prepare_artwork(encode(Image.new("RGB", (40, 40), (120, 120, 120))))[2])

    def test_exif_orientation_is_applied_before_sampling(self):
        image = Image.new("RGB", (60, 30), (255, 0, 0))
        image.paste((0, 0, 255), (0, 0, 30, 30))
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 degrees clockwise when displayed
        output = BytesIO()
        image.save(output, format="JPEG", exif=exif.tobytes(), quality=95)
        encoded = output.getvalue()
        with Image.open(BytesIO(encoded)) as source:
            expected = dominant_rgb(ImageOps.exif_transpose(source))
        self.assertEqual(prepare_artwork(encoded)[2], expected)
        self.assertEqual(artwork.accent_from_bytes(encoded), expected)

    def test_result_dominant_defaults_to_none(self):
        self.assertIsNone(ArtworkResult("t").dominant)


class ReferenceTableTests(unittest.TestCase):
    def setUp(self):
        if not DESIGN.is_dir():
            self.skipTest("design reference export is not present")
        self.reference = json.loads(REFERENCE.read_text(encoding="utf-8"))

    def test_reference_table_matches_dominant_rgb_for_every_design_asset(self):
        assets = design_assets()
        self.assertEqual(set(self.reference["files"]), set(assets))
        for name, path in assets.items():
            with self.subTest(asset=name):
                value = dominant_from_sample(asset_sample(path))
                entry = self.reference["files"][name]
                self.assertEqual(entry["value"], value)
                self.assertEqual(entry["rgb"], rgb_text(value))
                self.assertEqual(entry["hex"], None if value is None else f"#{value:06X}")

    def test_colors_map_is_consistent_with_files(self):
        colors, sources = self.reference["colors"], self.reference["sources"]
        self.assertEqual(set(colors), set(sources))
        self.assertTrue(any(k.startswith("al:") and v for k, v in colors.items()))
        self.assertTrue(any(k.startswith("app:") and v for k, v in colors.items()))
        for key, source in sources.items():
            self.assertEqual(colors[key], self.reference["files"][source.removeprefix("assets/")]["rgb"])


def run_node(assets, samples):
    with tempfile.TemporaryDirectory() as folder:
        request = Path(folder) / "input.json"
        request.write_text(json.dumps({
            "assets": {name: base64.b64encode(data).decode("ascii") for name, data in assets.items()},
            "samples": {name: base64.b64encode(data).decode("ascii") for name, data in samples.items()},
        }), encoding="utf-8")
        done = subprocess.run([shutil.which("node"), str(CHECK_JS), str(MODEL_JS), str(request)],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
    if done.returncode:
        raise AssertionError("dominant_check.cjs failed: " + done.stderr[-2000:])
    return json.loads(done.stdout)


def node_assets():
    return {"assets/" + name: asset_sample(path) for name, path in design_assets().items()}


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class JsCrossCheckTests(unittest.TestCase):
    """dominant_rgb must equal knob-model.js dominant() on identical 24x24 bytes."""

    @classmethod
    def setUpClass(cls):
        if not MODEL_JS.is_file():
            raise unittest.SkipTest("design reference knob-model.js is not present")
        cls.assets = node_assets()
        cls.samples = {name: tile(pixels).tobytes() for name, pixels in SAMPLES.items()}
        cls.result = run_node(cls.assets, cls.samples)

    def test_every_design_asset_matches_js_through_real_load_colors(self):
        colors, sources = self.result["colors"], self.result["sources"]
        self.assertEqual(set(sources.values()), set(self.assets))  # every asset was loaded
        self.assertEqual(set(colors), set(sources))
        for key, source in sources.items():
            with self.subTest(key=key):
                self.assertEqual(colors[key], rgb_text(dominant_from_sample(self.assets[source])))

    def test_synthetic_edge_cases_match_js(self):
        for name, data in self.samples.items():
            with self.subTest(sample=name):
                self.assertEqual(self.result["samples"][name], rgb_text(dominant_from_sample(data)))

    def test_reference_fixture_equals_js_colors(self):
        reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
        self.assertEqual(reference["colors"], self.result["colors"])
        self.assertEqual(reference["sources"], self.result["sources"])


class AppleAccentUrlTests(unittest.TestCase):
    TEMPLATE = "https://is1-ssl.mzstatic.com/image/thumb/Music126/v4/aa/bb/source/{w}x{h}bb.jpg"

    def test_size_parameter_expands_width_and_height(self):
        artwork_ = {"url": self.TEMPLATE, "width": 3000, "height": 3000}
        self.assertTrue(apple_artwork_url(artwork_).endswith("/480x480bb.jpg"))
        self.assertTrue(apple_artwork_url(artwork_, ACCENT_SIZE).endswith("/96x96bb.jpg"))
        self.assertTrue(apple_artwork_url({"url": "https://is1-ssl.mzstatic.com/a/{w}x{h}.{f}"}, 96)
                        .endswith("/a/96x96.jpg"))
        for size in (0, 15, 3001, "96", 96.0, True, None):
            with self.subTest(size=size):
                self.assertEqual(apple_artwork_url(artwork_, size), "")

    def test_crop_code_and_unknown_placeholders_stay_rejected(self):
        for url in ("https://is1-ssl.mzstatic.com/a/{w}x{h}{c}.{f}", "https://is1-ssl.mzstatic.com/a/{w}x{h}bb.{q}",
                    "https://is1-ssl.mzstatic.com/a/{w}x{h}}.jpg"):
            for size in (480, ACCENT_SIZE):
                with self.subTest(url=url, size=size):
                    self.assertEqual(apple_artwork_url({"url": url}, size), "")

    def test_recently_added_items_expose_accent_url_next_to_artwork_url(self):
        class Response:
            status_code = 200
            def __init__(self, data): self.data = data
            def json(self): return self.data

        class Session:
            def __init__(self, data): self.data, self.calls = data, []
            def get(self, url, **kwargs):
                self.calls.append(url)
                return Response(self.data)

        resources = [
            {"id": "l.1", "type": "library-albums",
             "attributes": {"name": "Synthetic", "artistName": "Artist",
                            "artwork": {"url": self.TEMPLATE, "width": 1400, "height": 1400}}},
            {"id": "l.2", "type": "library-albums",
             "attributes": {"name": "Crop coded", "artwork": {"url": "https://is1-ssl.mzstatic.com/x/{w}x{h}{c}.{f}"}}},
            {"id": "l.3", "type": "library-playlists", "attributes": {"name": "No art"}},
            {"id": "l.4", "type": "library-albums",
             "attributes": {"name": "Elsewhere", "artwork": {"url": "https://example.com/{w}x{h}.jpg"}}},
        ]
        session = Session({"data": resources})
        client = AppleMusicClient({"developer_token": "dev", "music_user_token": "user"}, session=session)
        items = client.recent()["items"]
        self.assertEqual(len(session.calls), 1)  # accent URLs are never fetched by the client
        self.assertTrue(items[0]["artwork_url"].endswith("/480x480bb.jpg"))
        self.assertTrue(items[0]["accent_url"].endswith("/96x96bb.jpg"))
        for item in items[1:]:
            self.assertEqual((item["artwork_url"], item["accent_url"]), ("", ""))
            self.assertTrue(item["available"])


class FakeResponse:
    def __init__(self, data, *, status=200, headers=None, gate=None, started=None):
        self.data, self.status_code, self.gate, self.started = data, status, gate, started
        self.headers = headers if headers is not None else {"Content-Type": "image/png"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        if self.started:
            self.started.set()
        if self.gate:
            self.gate.wait(2)
        yield self.data


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = dict(responses), []
        self.lock = threading.Lock()

    def get(self, url, **kwargs):
        with self.lock:
            self.calls.append((url, kwargs))
        value = self.responses[url]
        return value() if callable(value) else value


def solid(color, size=(40, 40)):
    return encode(Image.new("RGB", size, color))


class AccentServiceTests(unittest.TestCase):
    A, B, C, D = (f"https://is{i}-ssl.mzstatic.com/image/{i}/96x96bb.jpg" for i in range(1, 5))

    def service(self, responses, **kwargs):
        session = FakeSession(responses)
        service = AccentService(session=session, **kwargs)
        self.addCleanup(service.close)
        return service, session

    def collect(self, service, count, timeout=3):
        found, until = [], time.monotonic() + timeout
        while len(found) < count and time.monotonic() < until:
            found.extend(service.poll())
            time.sleep(.005)
        return found

    def test_batch_is_deduplicated_and_cached_urls_answer_without_io(self):
        service, session = self.service({self.A: FakeResponse(solid((200, 80, 40))),
                                         self.B: FakeResponse(solid((90, 90, 90)))})
        service.request_many([self.A, self.B, self.A, "", None], "page-1")
        results = self.collect(service, 2)
        self.assertCountEqual(results, [("page-1", self.A, 0xFF6633), ("page-1", self.B, None)])
        self.assertEqual([url for url, _ in session.calls], [self.A, self.B])
        for _, kwargs in session.calls:
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["headers"], {"Accept": "image/*"})
        service.request_many([self.B, self.A], "page-1-again")
        self.assertEqual(service.poll(), [("page-1-again", self.B, None), ("page-1-again", self.A, 0xFF6633)])
        self.assertEqual(len(session.calls), 2)

    def test_new_batch_supersedes_unstarted_and_unwanted_inflight_work(self):
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        service, session = self.service({
            self.A: FakeResponse(solid((255, 0, 0)), gate=gate, started=started),
            self.B: FakeResponse(solid((0, 255, 0))), self.C: FakeResponse(solid((0, 0, 255))),
            self.D: FakeResponse(solid((255, 0, 255)))})
        service.request_many([self.A, self.B, self.C], "old")
        self.assertTrue(started.wait(2))
        service.request_many([self.D], "new")
        gate.set()
        self.assertEqual(self.collect(service, 1), [("new", self.D, 0xFF00FF)])
        time.sleep(.05)
        self.assertEqual(service.poll(), [])
        self.assertEqual([url for url, _ in session.calls], [self.A, self.D])

    def test_inflight_url_still_wanted_reports_once_with_newest_token(self):
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        service, session = self.service({
            self.A: FakeResponse(solid((255, 0, 0)), gate=gate, started=started),
            self.B: FakeResponse(solid((0, 255, 0)))})
        service.request_many([self.A], "first")
        self.assertTrue(started.wait(2))
        service.request_many([self.A, self.B], "second")
        gate.set()
        results = self.collect(service, 2)
        self.assertCountEqual(results, [("second", self.A, 0xFF0000), ("second", self.B, 0x00FF00)])
        time.sleep(.05)
        self.assertEqual(service.poll(), [])
        self.assertEqual([url for url, _ in session.calls], [self.A, self.B])

    def test_failures_report_white_and_are_retried_later(self):
        service, session = self.service({self.A: FakeResponse(b"", status=404),
                                         self.B: FakeResponse(b"not an image")})
        service.request_many([self.A, self.B], "t")
        self.assertCountEqual(self.collect(service, 2), [("t", self.A, None), ("t", self.B, None)])
        service.request_many([self.A], "t2")
        self.assertEqual(self.collect(service, 1), [("t2", self.A, None)])
        self.assertEqual([url for url, _ in session.calls], [self.A, self.B, self.A])

    def test_sources_outside_the_allowlist_are_never_requested(self):
        blocked = ["http://is1-ssl.mzstatic.com/a.jpg", "https://evil.test/a.jpg",
                   "https://user:secret@is1-ssl.mzstatic.com/a.jpg", "http://192.168.1.9:1400/getaa?s=1"]
        service, session = self.service({})
        service.request_many(blocked, "t")
        self.assertCountEqual(self.collect(service, 4), [("t", url, None) for url in blocked])
        self.assertEqual(session.calls, [])

    def test_known_sonos_speaker_is_allowed_only_when_supplied(self):
        url = "http://192.168.1.9:1400/getaa?s=1&u=x"
        service, session = self.service({url: FakeResponse(solid((0, 0, 200)))})
        service.request_many([url], "sonos", speaker_host="192.168.1.9")
        self.assertEqual(self.collect(service, 1), [("sonos", url, 0x0000FF)])

    def test_oversize_and_non_image_responses_fail_closed(self):
        service, _ = self.service({
            self.A: FakeResponse(solid((255, 0, 0)), headers={"Content-Length": str(artwork.MAX_DOWNLOAD + 1)}),
            self.B: FakeResponse(solid((255, 0, 0)), headers={"Content-Type": "text/html"}),
            self.C: FakeResponse(solid((255, 0, 0)), status=302)})
        service.request_many([self.A, self.B, self.C], "t")
        self.assertCountEqual(self.collect(service, 3), [("t", u, None) for u in (self.A, self.B, self.C)])

    def test_lru_is_bounded(self):
        service, session = self.service({url: FakeResponse(solid((255, 0, 0))) for url in (self.A, self.B, self.C)},
                                        cache_size=2)
        for url in (self.A, self.B, self.C):
            service.request_many([url], url)
            self.collect(service, 1)
        service.request_many([self.C, self.B], "cached")
        self.assertEqual(len(service.poll()), 2)
        service.request_many([self.A], "evicted")
        self.assertEqual(self.collect(service, 1), [("evicted", self.A, 0xFF0000)])
        self.assertEqual([url for url, _ in session.calls], [self.A, self.B, self.C, self.A])

    def test_clear_drops_pending_results_and_close_is_final(self):
        service, session = self.service({self.A: FakeResponse(solid((255, 0, 0)))})
        service.request_many([self.A], "t")
        self.collect(service, 1)
        service.request_many([self.A], "cached")
        service.clear()
        self.assertEqual(service.poll(), [])
        service.close()
        service.request_many([self.B], "late")
        time.sleep(.05)
        self.assertEqual(service.poll(), [])
        self.assertEqual(len(session.calls), 1)


PROTOTYPE = (ROOT / "design-reference" / "design_handoff_nano_d_master_r2.2" / "prototypes"
             / "Browse and Snap.dc.html")


def prototype_table(name):
    """One `const NAME = [ … ];` table of the r2.2 prototype (BS), or the lazily built
    `(NAME = [ … ])` window set, as its raw row lines."""
    text = PROTOTYPE.read_text(encoding="utf-8")
    match = re.search(r"(?:const |\()" + re.escape(name) + r" = \[\n(.*?)\n\s*\]", text, re.S)
    if match is None:
        raise AssertionError(f"{name} not found in the prototype")
    return [line for line in match.group(1).splitlines() if line.strip().startswith("{")]


def rgb(values):
    r, g, b = (int(v) for v in values)
    return (r << 16) | (g << 8) | b


def _js_field(line, key, pattern):
    """The value of `key: <pattern>` in one prototype row (an AssertionError when it is missing)."""
    match = re.search(r"(?<![\w.])" + re.escape(key) + r": " + pattern, line)
    if match is None:
        raise AssertionError(f"{key} not found in the prototype row {line.strip()[:60]}")
    return match.group(1)


def _js_string(line, key):
    return re.sub(r"\\(.)", r"\1", _js_field(line, key, r"'((?:[^'\\]|\\.)*)'"))


def _prototype_colour(line):
    """A row's `c` as a (r, g, b) triple, or None for the warm marker (`WARM`, BS:496 isW)."""
    text = _js_field(line, "c", r"(\[[^\]]*\]|[A-Z]+)")
    warm = tuple(int(v) for v in re.search(r"\bWARM = \[([^\]]*)\]", PROTOTYPE.read_text(encoding="utf-8"))
                 .group(1).split(","))
    if text == "WARM":
        return None
    colour = tuple(int(v) for v in text.strip("[]").split(","))
    return None if colour == warm else colour


def prototype_albums():
    """The r2.2 prototype's sample library (BS `ALB`, BS:499-509): (title, artist, year, (r, g, b))."""
    return [(_js_string(line, "t"), _js_string(line, "a"), int(_js_field(line, "y", r"(\d+)")),
             _prototype_colour(line)) for line in prototype_table("ALB")]


def prototype_windows():
    """The r2.2 prototype's window set (BS `this._W`, BS:727-735): (app, title, (r, g, b) or None)."""
    return [(_js_string(line, "app"), _js_string(line, "title"), _prototype_colour(line))
            for line in prototype_table("this._W")]


class SimulationAccentTests(unittest.TestCase):
    """The section 16 simulator (CONTROL_CENTER_V5.md): the BS sample library and window set, read
    from the r2.2 prototype (Browse and Snap.dc.html) itself."""

    def test_the_prototype_tables_are_read(self):
        albums, windows = prototype_albums(), prototype_windows()
        self.assertEqual(len(albums), 9)
        self.assertEqual(albums[0], ("Promises", "Floating Points, Pharoah Sanders & LSO", 2021, (120, 150, 190)))
        self.assertEqual(len(windows), 7)
        self.assertEqual(windows[3], ("ChatGPT", "PCB layout questions", None), "c: WARM, the warm marker")
        self.assertEqual(windows[2], ("Slack", "Danny Lewis", (230, 50, 200)))

    def test_the_simulator_library_is_the_prototype_library(self):
        """K3 section 16: the BS library (BS:499-535), title, artist, year and accent of every album."""
        from control_center.simulation import ALBUMS
        self.assertEqual([(t, a, y, tuple(c)) for t, a, y, c in ALBUMS], prototype_albums())

    def test_the_simulator_window_set_is_the_prototype_window_set(self):
        """K3 section 16: "the BS window set (BS:727-735) with accents"; `WARM` is the warm marker (None)."""
        from control_center.simulation import WINDOWS
        self.assertEqual([(app, title, None if c is None else tuple(c)) for app, title, c in WINDOWS],
                         prototype_windows())

    def test_recent_items_carry_deterministic_accents_and_no_artwork(self):
        first = SimulatedAppleMusic().recent_page(0, limit=100)["items"]
        second = SimulatedAppleMusic().recent_page(0, limit=100)["items"]
        self.assertEqual(len(first), 26)
        self.assertEqual([item["accent"] for item in first], [item["accent"] for item in second])
        for item in first:
            with self.subTest(item=item["id"]):
                self.assertNotIn("artwork_url", item)
                self.assertNotIn("accent_url", item)
                if item["art_template"]:
                    self.assertTrue(0 < item["accent"] <= 0xFFFFFF)
                else:
                    self.assertIsNone(item["accent"], "no art: the runtime's Generated-sleeve accent (K3 10.4)")
        albums = {title: rgb(colour) for title, _artist, _year, colour in prototype_albums()}
        checked = set()
        for item in first:
            if item["kind"] == "album" and item["title"] in albums and item["art_template"]:
                self.assertEqual(item["accent"], albums[item["title"]], item["title"])
                checked.add(item["title"])
        self.assertTrue(checked, "the list's albums carry the prototype's accents")
        pages = SimulatedAppleMusic().recent()["items"] + SimulatedAppleMusic().recent("10")["items"]
        self.assertEqual([item["id"] for item in pages], [item["id"] for item in first[:20]])

    def test_window_items_use_the_design_window_accents(self):
        items = SimulatedWindows().snapshot()["items"]
        expected = prototype_windows()
        self.assertEqual([(item["app"], item["title"]) for item in items], [(app, title) for app, title, _ in expected])
        for item, (_app, _title, colour) in zip(items, expected):
            self.assertEqual(item["accent"], None if colour is None else rgb(colour), item["title"])
        by_app = {item["app"]: item["accent"] for item in items}
        self.assertIsNone(by_app["ChatGPT"], "the warm marker: sent as 0 by the runtime (K2 M26)")
        self.assertEqual(by_app["Slack"], 0xE632C8)


def write_reference():
    """Regenerate tests/fixtures/dominant_reference.json (requires node)."""
    import PIL
    if not shutil.which("node"):
        raise SystemExit("node is required to map knob-model.js COLORS keys to assets")
    files = {}
    for name, path in design_assets().items():
        value = dominant_from_sample(asset_sample(path))
        files[name] = {"value": value, "rgb": rgb_text(value), "hex": None if value is None else f"#{value:06X}"}
    result = run_node(node_assets(), {})
    for key, source in result["sources"].items():
        if result["colors"][key] != files[source.removeprefix("assets/")]["rgb"]:
            raise SystemExit(f"JS and Python disagree for {key}")
    reference = {
        "description": "dominant_rgb() of the design handoff sample covers and app icons. 'colors' is the "
                       "NanoModel.COLORS map (knob-model.js loadColors keys, 'r,g,b' or null) to pre-populate "
                       "golden fixtures; 'sources' maps each key to its asset.",
        "algorithm": "control_center.artwork.dominant_rgb: EXIF transpose, RGBA, Pillow BOX 24x24 of the whole "
                     "image, exact port of knob-model.js dominant()",
        "pillow": PIL.__version__,
        "files": files,
        "colors": {key: result["colors"][key] for key in sorted(result["colors"])},
        "sources": {key: result["sources"][key] for key in sorted(result["sources"])},
    }
    REFERENCE.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {REFERENCE.name}: {len(files)} assets, {len(reference['colors'])} COLORS keys")


if __name__ == "__main__":
    if "--write-reference" in sys.argv:
        write_reference()
    else:
        unittest.main()

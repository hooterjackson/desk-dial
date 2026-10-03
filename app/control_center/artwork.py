"""Bounded, latest-selection artwork loading independent of input and network lanes.

No credentials are sent to artwork servers. URLs may only address Apple artwork
CDNs or the explicitly supplied Sonos speaker on its artwork endpoint. Failures
leave the text controls usable; neither a URL nor HTTP response enters logs.

Two services share one download path (allowlist, no credentials, no redirects,
size/time/pixel bounds):

* ArtworkService: the cover behind the LCD text (latest only; cached covers
  answer synchronously, only misses are debounced and downloaded) plus the
  artwork2 page prefetch (firmware/ARTWORK2.md section 9).
* AccentService: ring accents for list entries, one dominant colour per URL.

artwork2 payloads (ARTWORK2.md section 5): cover_jpeg() encodes the 240 px
composited cover as a baseline JPEG, icon_payload() turns a 32x32 RGBA app icon
into the 2048-byte RGB565 LE tile image.

Desktop v5 floating knob (FLOATING_KNOB.md section 2): the same prepare pass also
keeps ``hires_jpeg``, the source fitted to 480 px with the scrim80 composite
applied continuously (quality-90 JPEG), for the overlay's LCD above 240 px. It
is desktop-only: nothing about it reaches the knob.

v7 (CONTROL_CENTER_V5.md section 10.5, C5-58; PRESENTATION_V5.md section 8.4):

* every knob cover is composited with the r2.1 scrim: ``pixel = cover × 0.8 × (1 − s)``,
  ``s`` at pixel centres ``y + 0.5``, linear between (0, .60), (108, .72), (148.8, .92),
  (168, 1.0), ``s = 1`` below 168 (``_SCRIM_STOPS``);
* the knob's four art states at 240 px: ``art.full`` (LANCZOS, centre crop) when
  ``240 / source ≤ 1.5``, ``art.extended`` above (the cover sharp at 1.5× on a radial
  gradient of its own colour), ``art.loading`` (flat ``art_bg``, ``#232325`` when 0) and
  ``art.generated`` (the GEN palette's 160° gradient), both **without text**
  (``knob_loading_cover`` / ``knob_generated_cover``); every one is keyed by the content
  hash of its composited JPEG, so a loading cover and the real one never share a key;
* the desktop's request ladder (240 / 600 / 1200, 2000 only for k > 3.5; ``art_rung``) and
  the **unscrimmed** cover store (``CoverStore``, K4 section 13.3 C1: encoded bytes keyed
  by (template, rung) or the Sonos ``/getaa`` URL, 24 MB LRU, the same allowlist and bounds);
* the sleeve inputs (``sleeve_inputs``: ``bgColor`` / ``textColor1`` / dominant) and the
  Generated-sleeve palette and hash (``GEN_PALETTE``, ``gen_index``; K4 section 13.6).
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import hashlib
import ipaddress
import math
import threading
import time
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit, urljoin
import warnings

from PIL import Image, ImageOps

from .presentation import (
    ARTWORK_CACHE_ENTRIES, ARTWORK_PREFETCH_WORKERS, COVER_JPEG_QUALITIES, COVER_KEY_CHARS,
    COVER_MAX_BYTES, COVER_SIZE, ICON_BYTES, ICON_KEY_CHARS, ICON_SIZE,
)


SIZE = 240
TRANSFER_SIZE = 120
MAX_DOWNLOAD = 2 * 1024 * 1024
MAX_PIXELS = 16_000_000
# Apple template size for the knob cover. Kept at 480 (K4 section 13.1 "sizes unchanged"): the
# same download feeds the 480 px floating-knob hi-res cover; the knob cover itself is 240 px.
ARTWORK_SIZE = 480
ACCENT_SIZE = 96    # Apple template size for ring accents (24x24 is all dominant_rgb reads)
DOMINANT_SAMPLE = 24
DOMINANT_MIN_WEIGHT = 4
# The r2.1 scrim (K1 section 8.4; R:84; S01:121): (knob row coordinate, darkness s).
_SCRIM_STOPS = ((0.0, .60), (108.0, .72), (148.8, .92), (168.0, 1.0))
KNOB_OPACITY = 0.8
HIRES_SIZE = 2 * SIZE      # desktop v5: the hi-res cover edge (the Apple template is fetched at 480)
HIRES_JPEG_QUALITY = 90
EXTENDED_UPSCALE = 1.5     # K4 section 13.5: u > 1.5 → art.extended
LOADING_EMPTY_BG = 0x232325  # art.loading when art_bg is 0 (S5-11)
LOADING_EMPTY_INK = 0xF2F2F2
# Desktop request ladder (K4 section 13.1; RA section 4.1): the smallest rung ≥ need ÷ 1.1,
# capped at art_max; 2000 only when k > 3.5; never 3000.
ART_LADDER = (240, 600, 1200)
ART_RUNG_XL = 2000
ART_SIZE_BY_USE = {"explorer_center": 1200, "explorer_side": 600, "mosaic_tile": 600,
                   "upnext_cover": 1200, "upnext_row": 240, "knob": 240}
COVER_STORE_BYTES = 24 * 1024 * 1024  # K4 section 13.3 C1
# The Generated-sleeve palette GEN (BS:536; K4 section 13.6): (g0, g1, ink, accent).
GEN_PALETTE = ((0x2B3A55, 0x131A28, 0xF3F2F2, (70, 120, 255)),
               (0x5A2E24, 0x26130F, 0xF6EBE4, (255, 100, 60)),
               (0x2F4A3A, 0x15231B, 0xECF4EE, (60, 220, 120)),
               (0x4B3B63, 0x1F182C, 0xF1EEF6, (150, 100, 255)),
               (0x6B5A2A, 0x2C2410, 0xF7F1DF, (255, 190, 40)),
               (0x2A4F57, 0x112326, 0xE9F4F5, (40, 210, 230)),
               (0x5C2A3F, 0x28111B, 0xF6E9EF, (255, 60, 140)),
               (0x3D3D3D, 0x171717, 0xF3F2F2, (255, 190, 105)))
GEN_WARM_INDEX = 7  # its accent is sent as 0 (warm), K2 M26


class ArtworkError(ValueError):
    pass


class ArtworkCancelled(ArtworkError):
    """The request that started a download no longer wants its result."""


def artwork_url(value, speaker_hosts=()) -> str:
    """Validate the narrow source allowlist before starting any request."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ArtworkError("Artwork is unavailable.")
    if any(ord(c) < 33 for c in value) or "\\" in value:
        raise ArtworkError("Artwork address is unavailable.")
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise ArtworkError("Artwork address is unavailable.") from None
    if parsed.username or parsed.password or parsed.fragment or not host:
        raise ArtworkError("Artwork address is unavailable.")
    apple = host.endswith(".mzstatic.com") and host != ".mzstatic.com"
    if apple and parsed.scheme == "https" and port in (None, 443):
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
    # Match literal configured IPv4 addresses. Do not follow DNS names into the
    # local network, arbitrary local ports, loopback, link-local or metadata IPs.
    try:
        address = ipaddress.IPv4Address(host)
        known = {str(ipaddress.IPv4Address(h)) for h in speaker_hosts}
    except (ipaddress.AddressValueError, TypeError):
        known, address = set(), None
    if (address is not None and str(address) in known and address.is_private
            and not (address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified)
            and parsed.scheme == "http" and port == 1400 and parsed.path == "/getaa"):
        return value
    raise ArtworkError("Artwork source is unavailable.")


def sonos_artwork_url(value, host) -> str:
    """SoCo normally returns an absolute URL, but older sources use /getaa."""
    if not isinstance(value, str) or not value:
        return ""
    try:
        url = urljoin(f"http://{ipaddress.IPv4Address(host)}:1400/", value)
        return artwork_url(url, (host,))
    except (ArtworkError, ipaddress.AddressValueError, TypeError):
        return ""


def apple_artwork_url(artwork, size=ARTWORK_SIZE) -> str:
    """Expand Apple's documented artwork size template without guessing art.

    Apple's ``Artwork.url`` is a template: ``{w}`` and ``{h}`` (always together,
    e.g. ``.../{w}x{h}bb.jpg``) become ``size`` and an optional ``{f}`` becomes
    ``jpg``. Those are the only placeholders substituted. Any other token --
    including the crop code ``{c}`` seen in some Apple web templates
    (``{w}x{h}{c}.{f}``) -- is rejected: no library response available to this
    project has been verified to use it, and guessing a crop code could fetch a
    different image. A rejected template yields ``""``: no cover and a white
    (no-accent) ring entry, while the library item itself stays usable.

    ``size`` is the square edge in pixels: ARTWORK_SIZE for the LCD cover and
    ACCENT_SIZE for the ring accent (``item["accent_url"]``).
    """
    if not isinstance(artwork, dict) or not isinstance(artwork.get("url"), str):
        return ""
    if isinstance(size, bool) or not isinstance(size, int) or not 16 <= size <= 3000:
        return ""
    value = artwork["url"].replace("{w}", str(size)).replace("{h}", str(size)).replace("{f}", "jpg")
    if "{" in value or "}" in value:
        return ""
    try:
        return artwork_url(value)
    except ArtworkError:
        return ""


def _js_round(value: float) -> int:
    """JavaScript Math.round for non-negative values: half rounds up (toward +inf)."""
    whole = math.floor(value)
    return whole + 1 if value - whole >= 0.5 else whole


def dominant_sample(image) -> bytes:
    """The 24x24 RGBA bytes that dominant_rgb() bins: the whole image, BOX, no crop.

    These are the bytes a canvas ``getImageData(0, 0, 24, 24)`` returns in
    knob-model.js; the JS cross-check feeds exactly these bytes to dominant().
    """
    small = image.convert("RGBA").resize((DOMINANT_SAMPLE, DOMINANT_SAMPLE), Image.Resampling.BOX)
    return small.tobytes()


def dominant_from_sample(data) -> int | None:
    """Exact port of ``dominant()`` in knob-model.js over RGBA bytes (row-major).

    Same float operations in the same order as the JS (IEEE doubles in both),
    bins visited in ascending key order with a strict ``>`` (ties keep the lowest
    key, like JS integer-key iteration), JS ``Math.round`` for normalisation.
    Returns 0xRRGGBB, or None (= white) when nothing saturated enough remains.
    """
    bins = {}
    for i in range(0, len(data) - len(data) % 4, 4):
        a = data[i + 3]
        if a < 128:
            continue
        r, g, b = data[i], data[i + 1], data[i + 2]
        mx, mn = max(r, g, b), min(r, g, b)
        s = (mx - mn) / mx if mx else 0
        if mx < 50 or s < 0.3:
            continue
        key = ((r >> 5) << 6) | ((g >> 5) << 3) | (b >> 5)
        w = s * (mx / 255)
        entry = bins.get(key)
        if entry is None:
            entry = bins[key] = [0.0, 0.0, 0.0, 0.0]
        entry[0] += w
        entry[1] += r * w
        entry[2] += g * w
        entry[3] += b * w
    best = None
    for key in sorted(bins):
        if best is None or bins[key][0] > best[0]:
            best = bins[key]
    if best is None or best[0] < DOMINANT_MIN_WEIGHT:
        return None
    r, g, b = best[1] / best[0], best[2] / best[0], best[3] / best[0]
    mx = max(r, g, b)
    r, g, b = (_js_round(v / mx * 255) for v in (r, g, b))
    return (r << 16) | (g << 8) | b


def dominant_rgb(image) -> int | None:
    """Dominant accent colour of a PIL image as 0xRRGGBB, or None for white.

    knob-model.js dominant(): whole image to 24x24; skip alpha<128, max<50 and
    saturation<0.3; 3-3-3 bins weighted by saturation x value; heaviest bin's
    weighted mean normalised so its max channel is 255; None below weight 4.
    """
    return dominant_from_sample(dominant_sample(image))


def dominant_color(image) -> int:
    """Compatibility wrapper: dominant_rgb() with white for "no accent"."""
    value = dominant_rgb(image)
    return 0xFFFFFF if value is None else value


def _open_image(encoded: bytes):
    """Decode bounded encoded bytes into a loaded, EXIF-transposed image."""
    if not isinstance(encoded, bytes) or not 0 < len(encoded) <= MAX_DOWNLOAD:
        raise ArtworkError("Artwork could not be decoded.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(encoded)) as source:
                if source.width * source.height > MAX_PIXELS or source.width <= 0 or source.height <= 0:
                    raise ArtworkError("Artwork is too large.")
                source.seek(0)
                # exif_transpose returns a loaded copy, detached from the stream.
                return ImageOps.exif_transpose(source)
    except ArtworkError:
        raise
    except Exception:
        raise ArtworkError("Artwork could not be decoded.") from None


def accent_from_bytes(encoded: bytes) -> int | None:
    """Dominant colour of encoded artwork (same decode bounds as the cover)."""
    source = _open_image(encoded)
    try:
        return dominant_rgb(source)
    except Exception:
        raise ArtworkError("Artwork could not be decoded.") from None


def _scrim_s(c: float) -> float:
    """Scrim darkness ``s`` at knob coordinate ``c`` (a pixel centre, 0..240): linear between
    ``_SCRIM_STOPS``, 1 from 168 down (K1 section 8.4)."""
    if c <= _SCRIM_STOPS[0][0]:
        return _SCRIM_STOPS[0][1]
    for (c0, s0), (c1, s1) in zip(_SCRIM_STOPS, _SCRIM_STOPS[1:]):
        if c <= c1:
            return s0 + (s1 - s0) * (c - c0) / (c1 - c0)
    return 1.0


def _scrim_factor(c: float) -> float:
    """``0.8 × (1 − s(c))``: what a cover pixel is multiplied by at knob coordinate ``c``."""
    return KNOB_OPACITY * (1 - _scrim_s(c))


def _knob_centre(y: int, size: int) -> float:
    """Knob coordinate (0..240) of the centre of row ``y`` of a ``size`` px cover."""
    return (y + .5) * SIZE / size


@lru_cache(maxsize=2)
def _hires_scrim_rows(size: int = HIRES_SIZE):
    """Per-row tables of the scrim at ``size`` px: round(value * factor(the row centre's knob coordinate))."""
    return tuple(bytes(round(v * _scrim_factor(_knob_centre(y, size))) for v in range(256)) for y in range(size))


def hires_cover_jpeg(rgb_source, size: int = HIRES_SIZE, *, fitted=None) -> bytes | None:
    """The desktop-only hi-res cover: ``rgb_source`` fitted (centre crop, LANCZOS) to ``size``
    px (or the already composed ``fitted`` image of that size), the scrim composite applied
    at each pixel row centre's knob coordinate (the 240 px preview's scrim, made continuous),
    as a quality-90 baseline JPEG. None on failure."""
    try:
        if fitted is None:
            fitted = ImageOps.fit(rgb_source.convert("RGB"), (size, size), method=Image.Resampling.LANCZOS)
        fitted = fitted.convert("RGB")
        rgb, row, tables = fitted.tobytes(), size * 3, _hires_scrim_rows(size)
        scrimmed = Image.frombytes("RGB", (size, size),
                                   b"".join(rgb[y * row:(y + 1) * row].translate(tables[y]) for y in range(size)))
        output = BytesIO()
        scrimmed.save(output, format="JPEG", quality=HIRES_JPEG_QUALITY, subsampling=2, optimize=True,
                      progressive=False)
        return output.getvalue()
    except Exception:
        return None  # the 240 px cover still serves the overlay


def clean_cover_jpeg(rgb_source, size: int = HIRES_SIZE, *, fitted=None) -> bytes | None:
    """r3.1 Navigator: the hi-res cover of ``hires_cover_jpeg`` without the knob's scrim or its 0.8
    opacity (the desktop card draws its own text on glass, not over the art). None on failure."""
    try:
        if fitted is None:
            fitted = ImageOps.fit(rgb_source.convert("RGB"), (size, size), method=Image.Resampling.LANCZOS)
        output = BytesIO()
        fitted.convert("RGB").save(output, format="JPEG", quality=HIRES_JPEG_QUALITY, subsampling=2, optimize=True,
                                   progressive=False)
        return output.getvalue()
    except Exception:
        return None


@lru_cache(maxsize=1)
def _scrim_rows():
    """One 256-entry table per knob row: round(value * factor(y + 0.5)) per byte, applied
    with bytes.translate (byte-identical to the per-pixel formula)."""
    return tuple(bytes(round(v * _scrim_factor(y + .5)) for v in range(256)) for y in range(SIZE))


_R_HIGH = bytes(v & 0xF8 for v in range(256))           # (r >> 3) << 3
_G_HIGH = bytes(v >> 5 for v in range(256))             # (g >> 2) >> 3
_G_LOW = bytes(((v >> 2) & 0x07) << 5 for v in range(256))
_B_LOW = bytes(v >> 3 for v in range(256))


def _or_bytes(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "big") | int.from_bytes(b, "big")).to_bytes(len(a), "big")


def _rgb565le(rgb: bytes) -> bytes:
    """Little-endian RGB565 of packed RGB bytes (disjoint bit fields, OR == sum)."""
    r, g, b = rgb[0::3], rgb[1::3], rgb[2::3]
    out = bytearray(2 * len(r))
    out[0::2] = _or_bytes(g.translate(_G_LOW), b.translate(_B_LOW))
    out[1::2] = _or_bytes(r.translate(_R_HIGH), g.translate(_G_HIGH))
    return bytes(out)


# artwork2 rounding (ARTWORK2.md sections 5 and 7): r5 = (r*31+127)//255,
# g6 = (g*63+127)//255, b5 = (b*31+127)//255, packed little-endian.
_R5 = bytes((v * 31 + 127) // 255 for v in range(256))
_G6 = bytes((v * 63 + 127) // 255 for v in range(256))
_ROUND_R_HIGH = bytes(r5 << 3 for r5 in _R5)            # high byte: rrrrr ggg
_ROUND_G_HIGH = bytes(g6 >> 3 for g6 in _G6)
_ROUND_G_LOW = bytes((g6 & 0x07) << 5 for g6 in _G6)    # low byte: ggg bbbbb
_ROUND_B_LOW = _R5


def rgb565le_rounded(rgb: bytes) -> bytes:
    """Little-endian RGB565 of packed RGB bytes with artwork2's rounding (not v1's truncation)."""
    r, g, b = rgb[0::3], rgb[1::3], rgb[2::3]
    out = bytearray(2 * len(r))
    out[0::2] = _or_bytes(g.translate(_ROUND_G_LOW), b.translate(_ROUND_B_LOW))
    out[1::2] = _or_bytes(r.translate(_ROUND_R_HIGH), g.translate(_ROUND_G_HIGH))
    return bytes(out)


def cover_key(jpeg: bytes) -> str:
    """The artwork2 cover key: what the frame's `artKey` names."""
    return hashlib.sha256(jpeg).hexdigest()[:COVER_KEY_CHARS]


def icon_key(raw: bytes) -> str:
    """The artwork2 icon key: what the frame's `iconKey` names."""
    return hashlib.sha256(raw).hexdigest()[:ICON_KEY_CHARS]


def cover_jpeg(preview):
    """ARTWORK2.md section 5: (key, jpeg) of the 240 px composited cover, or (None, None).

    Baseline (never progressive) JFIF, 4:2:0, optimised Huffman tables, no EXIF,
    ICC or comment segment. The first quality of the ladder 85..60 whose file
    is at most COVER_MAX_BYTES is used; when none fits there is no artwork2
    cover for the item (the frame's artKey is then empty).
    """
    if not isinstance(preview, Image.Image) or preview.size != (COVER_SIZE, COVER_SIZE):
        raise ArtworkError("Artwork could not be encoded.")
    # A fresh image carries no info dict, so no EXIF, ICC or comment can reach the file.
    clean = Image.frombytes("RGB", preview.size, preview.convert("RGB").tobytes())
    for quality in COVER_JPEG_QUALITIES:
        output = BytesIO()
        clean.save(output, format="JPEG", quality=quality, subsampling=2, optimize=True, progressive=False)
        data = output.getvalue()
        if len(data) <= COVER_MAX_BYTES:
            return cover_key(data), data
    return None, None


def _fit_icon(image):
    """windows.icon_thumbnail's fit: aspect kept, centred on transparent padding."""
    fitted = ImageOps.contain(image, (ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
    if fitted.size == (ICON_SIZE, ICON_SIZE):
        return fitted
    tile = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    tile.paste(fitted, ((ICON_SIZE - fitted.width) // 2, (ICON_SIZE - fitted.height) // 2))
    return tile


def rgb565_over_black(rgba) -> bytes:
    """RGBA composited onto black (c' = round(c*a/255) per channel), then RGB565 LE with rounding.

    Pillow's RGBA -> RGBa conversion is exactly round(c*a/255) for every (c, a)
    (tests/test_cc_icon_payload.py checks all 65,536 pairs), so no Python pixel loop runs.
    """
    premultiplied = rgba.convert("RGBA").convert("RGBa").tobytes()
    rgb = bytearray(3 * (len(premultiplied) // 4))
    rgb[0::3], rgb[1::3], rgb[2::3] = premultiplied[0::4], premultiplied[1::4], premultiplied[2::4]
    return rgb565le_rounded(bytes(rgb))


def icon_payload(rgba) -> tuple[str, bytes]:
    """ARTWORK2.md section 5: (key, 2048-byte RGB565 LE) of a 32x32 RGBA app icon.

    The source is IconWorker's LANCZOS icon_thumbnail (another size is fitted the
    same way). Alpha is composited onto black, which is the tile the knob draws
    it on. Raises ArtworkError for anything that is not an image.
    """
    if not isinstance(rgba, Image.Image):
        raise ArtworkError("Icon is unavailable.")
    try:
        image = rgba.convert("RGBA")
        if image.size != (ICON_SIZE, ICON_SIZE):
            image = _fit_icon(image)
        raw = rgb565_over_black(image)
    except Exception:
        raise ArtworkError("Icon is unavailable.") from None
    if len(raw) != ICON_BYTES:
        raise ArtworkError("Icon is unavailable.")
    return icon_key(raw), raw


# IconWorker builds the payload on its own thread and keeps it in the icon's
# ``info`` (Image.copy() carries it), so the Tk poll never encodes an icon.
ICON_PAYLOAD_INFO = "nanod.iconPayload"


def attach_icon_payload(icon):
    """Store icon_payload(icon) in ``icon.info`` (worker thread); never raises. Returns ``icon``."""
    try:
        icon.info[ICON_PAYLOAD_INFO] = icon_payload(icon)
    except Exception:
        pass  # the runtime then builds it lazily, or shows the letter tile
    return icon


def attached_icon_payload(icon):
    """The (key, 2048 bytes) attach_icon_payload() stored on this 32x32 icon, or None."""
    info = getattr(icon, "info", None)
    value = info.get(ICON_PAYLOAD_INFO) if isinstance(info, dict) else None
    if (getattr(icon, "size", None) == (ICON_SIZE, ICON_SIZE) and isinstance(value, tuple) and len(value) == 2
            and isinstance(value[0], str) and len(value[0]) == ICON_KEY_CHARS
            and isinstance(value[1], bytes) and len(value[1]) == ICON_BYTES):
        return value
    return None


class PreparedArtwork(NamedTuple):
    """One prepare pass: the v1 payloads and, when the ladder fits, the artwork2 cover."""
    preview: object       # 240 px composited RGB image (0.8 opacity + scrim)
    raw: bytes            # v1: 120 px RGB565 LE (28,800 bytes)
    dominant: int | None  # ring accent 0xRRGGBB, None = white
    jpeg: bytes | None    # artwork2: baseline 240 px JPEG <= COVER_MAX_BYTES
    jpeg_key: str | None  # artwork2: sha256(jpeg)[:24]
    hires_jpeg: bytes | None = None  # desktop v5: 480 px continuous-scrim cover, quality 90
    clean_jpeg: bytes | None = None  # r3.1 Navigator: the same 480 px cover without the knob's scrim


def _knob_composite(cover):
    """(preview, raw) of a 240 px RGB cover: the scrim composite and the v1 120 px RGB565 transfer."""
    rgb, row, tables = cover.convert("RGB").tobytes(), SIZE * 3, _scrim_rows()
    scrimmed = b"".join(rgb[y * row:(y + 1) * row].translate(tables[y]) for y in range(SIZE))
    preview = Image.frombytes("RGB", (SIZE, SIZE), scrimmed)
    # Artwork is softer than foreground UI text. A 120px source displayed at
    # 240px cuts paced USB transfer time by 75%; text remains native resolution.
    raw = _rgb565le(preview.resize((TRANSFER_SIZE, TRANSFER_SIZE), Image.Resampling.LANCZOS).tobytes())
    return preview, raw


def _rgb(value) -> tuple:
    if isinstance(value, tuple):
        return tuple(int(v) & 0xFF for v in value[:3])
    value = int(value) & 0xFFFFFF
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def sleeve_colour(image, dominant=None) -> tuple:
    """The Extended sleeve's colour c (K4 section 13.6): the cover's dominant colour; for a
    cover without a saturated bin (dominant None) the mean of its 24 × 24 sample."""
    if dominant is not None:
        return _rgb(dominant)
    sample = image.convert("RGB").resize((DOMINANT_SAMPLE, DOMINANT_SAMPLE), Image.Resampling.BOX).tobytes()
    count = len(sample) // 3
    return tuple(round(sum(sample[i::3]) / count) for i in range(3))


def _shade(c, k) -> tuple:
    return tuple(_js_round(v * k) for v in c)


@lru_cache(maxsize=4)
def _extended_ground(colour: tuple, size: int) -> bytes:
    """``radial-gradient(120% 120% at 50% 38%, shade(c,.95) 0%, shade(c,.5) 52%, shade(c,.2) 100%)``
    (BS:540), evaluated at pixel centres, as packed RGB bytes."""
    stops = ((0.0, _shade(colour, .95)), (.52, _shade(colour, .5)), (1.0, _shade(colour, .2)))
    cx, cy, radius = .5 * size, .38 * size, 1.2 * size
    rows = []
    for y in range(size):
        dy2 = ((y + .5 - cy) / radius) ** 2
        line = bytearray(3 * size)
        for x in range(size):
            t = min(1.0, math.sqrt(((x + .5 - cx) / radius) ** 2 + dy2))
            (t0, c0), (t1, c1) = (stops[0], stops[1]) if t <= .52 else (stops[1], stops[2])
            f = (t - t0) / (t1 - t0)
            line[3 * x:3 * x + 3] = bytes(round(a + (b - a) * f) for a, b in zip(c0, c1))
        rows.append(bytes(line))
    return b"".join(rows)


def compose_extended(rgb_source, size: int, colour) -> Image.Image:
    """``art.extended`` at ``size`` px (K4 section 13.6 recipe, as K3 section 10.5 asks for the
    knob): the radial gradient of ``colour`` with the cover (centre-cropped square) drawn sharp
    at 1.5 × its native size, centred. No text, no shadow (the knob draws neither)."""
    colour = _rgb(colour)
    ground = Image.frombytes("RGB", (size, size), _extended_ground(colour, size))
    edge = min(rgb_source.size)
    drawn = max(1, min(size, round(EXTENDED_UPSCALE * edge)))
    square = ImageOps.fit(rgb_source.convert("RGB"), (edge, edge), method=Image.Resampling.LANCZOS)
    cover = square.resize((drawn, drawn), Image.Resampling.LANCZOS)
    offset = (size - drawn) // 2
    ground.paste(cover, (offset, offset))
    return ground


def _prepare(encoded: bytes, hires: bool = False):
    source = _open_image(encoded)
    try:
        dominant = dominant_rgb(source)
    except Exception:
        dominant = None  # The cover is still usable without a ring accent.
    extended = None
    try:
        rgb_source = source.convert("RGB")
        if SIZE / min(rgb_source.size) > EXTENDED_UPSCALE:
            # art.extended (K3 section 10.5 step 2): u = 240 / source > 1.5.
            extended = compose_extended(rgb_source, SIZE, sleeve_colour(rgb_source, dominant))
            cropped = extended
        else:
            cropped = ImageOps.fit(rgb_source, (SIZE, SIZE), method=Image.Resampling.LANCZOS)
    except Exception:
        raise ArtworkError("Artwork could not be decoded.") from None
    preview, raw = _knob_composite(cropped)
    if hires:
        fitted = extended.resize((HIRES_SIZE, HIRES_SIZE), Image.Resampling.LANCZOS) if extended else None
        if fitted is None:
            try:
                fitted = ImageOps.fit(rgb_source, (HIRES_SIZE, HIRES_SIZE), method=Image.Resampling.LANCZOS)
            except Exception:
                fitted = None
        return (preview, raw, dominant, hires_cover_jpeg(rgb_source, fitted=fitted),
                clean_cover_jpeg(rgb_source, fitted=fitted))
    return preview, raw, dominant


def prepare_artwork(encoded: bytes):
    """Return scrimmed 240px preview, 120px RGB565 transfer, and dominant colour.

    The r2.1 handoff uses 80% art opacity plus the darker readability scrim
    (K1 section 8.4): 60% at the top, 72% at y108, 92% at y148.8 and solid black
    from y168, evaluated at pixel centres. A source whose short edge is under
    160 px is drawn as ``art.extended``. The dominant colour (int 0xRRGGBB or
    None = white) is taken from the whole EXIF-transposed source, before any crop
    or scrim, as knob-model.js does.
    """
    return _prepare(encoded)


def prepare_artwork2(encoded: bytes) -> PreparedArtwork:
    """prepare_artwork plus the artwork2 JPEG of the same 240 px preview, in one pass.

    The JPEG is the preview before its 120 px reduction and without any RGB565
    quantisation (ARTWORK2.md section 5). An encoder failure only loses the
    artwork2 cover; the v1 payload stays usable for a cc5.2 knob.

    The same pass keeps ``hires_jpeg`` (desktop v5: hires_cover_jpeg of the same
    EXIF-transposed source; None when it cannot be encoded).
    """
    preview, raw, dominant, hires_jpeg, clean_jpeg = _prepare(encoded, hires=True)
    try:
        jpeg_key, jpeg = cover_jpeg(preview)
    except Exception:
        jpeg_key = jpeg = None
    return PreparedArtwork(preview, raw, dominant, jpeg, jpeg_key, hires_jpeg, clean_jpeg)


# ---------------------------------------------------------------------- knob art states (section 10.5)
def gen_index(title, artist) -> int:
    """BS ``genOf`` (BS:537; K4 section 13.6), ported exactly: ``x = 7``; for each code point of
    ``title + "|" + artist`` its first UTF-16 code unit, ``x = (x·31 + unit) mod 9973``; ``x mod 8``."""
    x = 7
    for character in f"{title or ''}|{artist or ''}":
        point = ord(character)
        unit = point if point < 0x10000 else 0xD800 + ((point - 0x10000) >> 10)
        x = (x * 31 + unit) % 9973
    return x % len(GEN_PALETTE)


def gen_sleeve(title, artist) -> dict:
    """The Generated sleeve of an item without art: palette index, gradient ends, ink and accent.
    ``ring_accent`` is what the knob gets (0 = warm for index 7, K2 M26)."""
    index = gen_index(title, artist)
    g0, g1, ink, accent = GEN_PALETTE[index]
    value = (accent[0] << 16) | (accent[1] << 8) | accent[2]
    return {"index": index, "g0": g0, "g1": g1, "ink": ink, "accent": value,
            "ring_accent": 0 if index == GEN_WARM_INDEX else value}


def sleeve_inputs(item: dict, dominant=None) -> dict:
    """What the sleeves need from an item (K4 sections 13.2 and 13.6): the ``art.loading`` fill and
    ink (``art_bg`` / ``art_ink``; ``#232325`` / ``#F2F2F2`` when Apple gave none, S5-11), the
    cover's dominant colour for ``art.extended`` (passed in by the worker that decoded it) and
    the Generated sleeve."""
    item = item if isinstance(item, dict) else {}
    bg = item.get("art_bg") if isinstance(item.get("art_bg"), int) else 0
    ink = item.get("art_ink") if isinstance(item.get("art_ink"), int) else 0
    return {"bg": bg or LOADING_EMPTY_BG, "ink": ink if (bg and ink) else LOADING_EMPTY_INK,
            "dominant": dominant, "gen": gen_sleeve(item.get("title", ""), item.get("artist", ""))}


def _linear_ground(g0: int, g1: int, size: int) -> bytes:
    """``linear-gradient(160deg, g0 0%, g1 100%)`` at pixel centres (CSS angle: 0 = to top, clockwise)."""
    angle = math.radians(160)
    dx, dy = math.sin(angle), -math.cos(angle)
    length = size * (abs(dx) + abs(dy))
    a, b = _rgb(g0), _rgb(g1)
    columns = [(x + .5 - size / 2) * dx / length for x in range(size)]
    rows = []
    for y in range(size):
        base = .5 + (y + .5 - size / 2) * dy / length
        line = bytearray(3 * size)
        for x, part in enumerate(columns):
            t = min(1.0, max(0.0, base + part))
            line[3 * x:3 * x + 3] = bytes(round(p + (q - p) * t) for p, q in zip(a, b))
        rows.append(bytes(line))
    return b"".join(rows)


def _prepared_from_cover(cover) -> PreparedArtwork:
    """PreparedArtwork of a composed 240 px cover (no dominant: the accent comes from the item)."""
    preview, raw = _knob_composite(cover)
    try:
        jpeg_key, jpeg = cover_jpeg(preview)
    except Exception:
        jpeg_key = jpeg = None
    hires = hires_cover_jpeg(cover, fitted=cover.resize((HIRES_SIZE, HIRES_SIZE), Image.Resampling.BICUBIC))
    return PreparedArtwork(preview, raw, None, jpeg, jpeg_key, hires)


@lru_cache(maxsize=8)   # ≈ 0.22 MB per entry (preview, v1, JPEG, hi-res)
def _loading_bytes(colour: int):
    prepared = _prepared_from_cover(Image.new("RGB", (SIZE, SIZE), _rgb(colour)))
    return prepared.preview.tobytes(), prepared[1:]


@lru_cache(maxsize=len(GEN_PALETTE))
def _generated_bytes(index: int):
    g0, g1, _ink, _accent = GEN_PALETTE[index]
    prepared = _prepared_from_cover(Image.frombytes("RGB", (SIZE, SIZE), _linear_ground(g0, g1, SIZE)))
    return prepared.preview.tobytes(), prepared[1:]


def _from_cache(entry) -> PreparedArtwork:
    preview_bytes, rest = entry
    return PreparedArtwork(Image.frombytes("RGB", (SIZE, SIZE), preview_bytes), *rest)


def knob_loading_cover(art_bg=0) -> PreparedArtwork:
    """``art.loading`` for the knob: a flat 240 px ``art_bg`` (``#232325`` when 0), no text (the knob
    LCD draws the title and artist itself, K1 section 8.6), scrimmed, JPEG-keyed. Cached per colour."""
    colour = int(art_bg) & 0xFFFFFF if isinstance(art_bg, int) and not isinstance(art_bg, bool) else 0
    return _from_cache(_loading_bytes(colour or LOADING_EMPTY_BG))


def knob_generated_cover(title, artist) -> PreparedArtwork:
    """``art.generated`` for the knob: the 160° ``GEN[h mod 8]`` gradient, no text, scrimmed,
    JPEG-keyed (8 covers in all, cached)."""
    return _from_cache(_generated_bytes(gen_index(title, artist)))


# ---------------------------------------------------------------------- desktop request ladder
def art_rung(need, art_max: int = 0, k: float = 2.0) -> int:
    """The smallest ladder rung ≥ ``need ÷ 1.1`` (240, 600, 1200; 2000 only when ``k`` > 3.5),
    capped at ``art_max`` when known (Apple returns the original anyway; RA section 4.1)."""
    ladder = ART_LADDER + ((ART_RUNG_XL,) if k > 3.5 else ())
    target = max(1.0, float(need)) / 1.1
    rung = next((value for value in ladder if value >= target), ladder[-1])
    if isinstance(art_max, int) and not isinstance(art_max, bool) and art_max > 0:
        rung = min(rung, art_max)
    return rung


def art_request_size(use: str, art_max: int = 0, k: float = 2.0) -> int:
    """The request size per use (K4 section 13.1): 1200 for the explorer centre card and the Up next
    cover (2000 when k > 3.5), 600 for side cards and mosaic tiles, 240 for Up next rows and the
    knob; capped at ``art_max``."""
    size = ART_SIZE_BY_USE[use]
    if size == 1200 and k > 3.5:
        size = ART_RUNG_XL
    if isinstance(art_max, int) and not isinstance(art_max, bool) and art_max > 0:
        size = min(size, art_max)
    return size


def template_url(template: str, size: int) -> str:
    """The Apple template expanded at ``size`` px through the allowlist (``apple_artwork_url``), or ""."""
    return apple_artwork_url({"url": template}, size) if isinstance(template, str) else ""


class CoverStore:
    """The desktop's **unscrimmed** encoded covers (K4 section 13.3 C1; RA section 4.5 item 2).

    Encoded bytes only (no decoded bitmaps), keyed by sha1(template) + rung, or sha1 of the Sonos
    ``/getaa`` URL, in one LRU of ``budget_bytes`` (24 MB). ``fetch`` is blocking and runs on the
    caller's worker (K4's ``NanoD-art-*``); a second fetch of a key another thread is loading waits
    for that download. Every download goes through ``_fetch``: the same allowlist, no credentials,
    no redirects, size, time and pixel bounds as the knob's covers. URLs never enter a key, a log
    or an error text.
    """

    def __init__(self, speaker_hosts=(), *, session=None, budget_bytes: int = COVER_STORE_BYTES):
        self.speaker_hosts = tuple(speaker_hosts)
        self.session = session
        self.budget_bytes = max(1, int(budget_bytes))
        self._condition = threading.Condition()
        self._cache = OrderedDict()   # key -> bytes
        self._bytes = 0
        self._inflight = set()
        self._local = threading.local()

    @staticmethod
    def key_for(template: str | None = None, rung: int | None = None, *, sonos_url: str | None = None) -> str:
        if template:
            return hashlib.sha1(template.encode("utf-8")).hexdigest()[:20] + f"@{int(rung)}"
        if sonos_url:
            return "sonos-" + hashlib.sha1(sonos_url.encode("utf-8")).hexdigest()[:20]
        raise ArtworkError("Artwork is unavailable.")

    def _source(self, template, rung, sonos_url, speaker_host):
        hosts = self.speaker_hosts + ((speaker_host,) if speaker_host else ())
        if template:
            url = template_url(template, int(rung))
            if not url:
                raise ArtworkError("Artwork is unavailable.")
            return url, hosts
        return artwork_url(sonos_url, hosts), hosts

    def cached(self, template: str | None = None, rung: int | None = None, *, sonos_url: str | None = None):
        """The stored bytes (LRU refreshed), or None. No I/O."""
        try:
            key = self.key_for(template, rung, sonos_url=sonos_url)
        except ArtworkError:
            return None
        with self._condition:
            data = self._cache.get(key)
            if data is not None:
                self._cache.move_to_end(key)
            return data

    def _session(self):
        if self.session is not None:
            return self.session
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = _new_session()
        return session

    def fetch(self, template: str | None = None, rung: int | None = None, *, sonos_url: str | None = None,
              speaker_host: str | None = None, cancelled=None) -> bytes:
        """The encoded, unscrimmed cover: from the store, awaited from another thread, or downloaded
        here. Raises ArtworkError (``ArtworkCancelled`` when ``cancelled()`` turns true)."""
        key = self.key_for(template, rung, sonos_url=sonos_url)
        url, hosts = self._source(template, rung, sonos_url, speaker_host)
        cancelled = cancelled or (lambda: False)
        with self._condition:
            while True:
                data = self._cache.get(key)
                if data is not None:
                    self._cache.move_to_end(key)
                    return data
                if key not in self._inflight:
                    self._inflight.add(key)
                    break
                if cancelled():
                    raise ArtworkCancelled("Artwork selection changed.")
                self._condition.wait(0.05)
        try:
            data = _fetch(self._session(), url, hosts, cancelled)
            _open_image(data)  # decodable within the pixel bound, or ArtworkError
            with self._condition:
                self._cache[key] = data
                self._cache.move_to_end(key)
                self._bytes += len(data)
                while self._bytes > self.budget_bytes and len(self._cache) > 1:
                    _, dropped = self._cache.popitem(last=False)
                    self._bytes -= len(dropped)
            return data
        finally:
            with self._condition:
                self._inflight.discard(key)
                self._condition.notify_all()

    def clear(self) -> None:
        with self._condition:
            self._cache.clear()
            self._bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes


def _new_session():
    import requests
    session = requests.Session()
    session.trust_env = False
    return session


def _fetch(session, url, hosts, cancelled) -> bytes:
    """One bounded artwork download. ``cancelled()`` and the 8 s deadline are polled per read.

    Redirects are deliberately rejected. Never turn a trusted art URL into a
    request for an arbitrary local address or send Apple auth headers. Errors
    carry fixed text only; the URL never enters a message.
    """
    url = artwork_url(url, hosts)
    start = time.monotonic()
    with session.get(url, stream=True, timeout=(2, 3), allow_redirects=False,
                     headers={"Accept": "image/*"}) as response:
        if response.status_code != 200:
            raise ArtworkError("Artwork is unavailable.")
        length = response.headers.get("Content-Length")
        if length and (not length.isdecimal() or int(length) > MAX_DOWNLOAD):
            raise ArtworkError("Artwork is too large.")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type and not content_type.startswith("image/"):
            raise ArtworkError("Artwork is unavailable.")
        data = bytearray()
        deadline = start + _FETCH_DEADLINE_S
        try:
            for part in _body_parts(response, deadline):
                if time.monotonic() > deadline:
                    raise ArtworkError("Artwork took too long to load.")
                if cancelled():
                    raise ArtworkCancelled("Artwork selection changed.")
                data.extend(part)
                if len(data) > MAX_DOWNLOAD:
                    raise ArtworkError("Artwork is too large.")
        except ArtworkError:
            raise
        except Exception:
            # A read cut short by the deadline-capped socket timeout is the deadline, not a fault.
            if time.monotonic() >= deadline - 0.05:
                raise ArtworkError("Artwork took too long to load.") from None
            raise
        return bytes(data)


_FETCH_DEADLINE_S = 8.0   # whole-download budget for one cover
_READ_TIMEOUT_S = 3.0     # per-read stall budget (the session.get read timeout)
_FALLBACK_CHUNK = 2_048   # iter_content chunk when the raw stream has no read1()


def _body_parts(response, deadline):
    """Yield the body as it arrives so the total deadline is checked after every socket read.

    ``iter_content(16384)`` blocks until 16 KB arrive, so a trickling source slipped the 8 s
    deadline by seconds (DD-RES-007). ``raw.read1`` returns whatever one read delivers, and the
    socket's read timeout is capped at the time left, so no single read outlasts the deadline.
    """
    raw = getattr(response, "raw", None)
    read1 = getattr(raw, "read1", None)
    if not callable(read1):
        yield from response.iter_content(chunk_size=_FALLBACK_CHUNK)
        return
    sock = getattr(getattr(raw, "connection", None), "sock", None)
    original = None
    if sock is not None:
        try:
            original = sock.gettimeout()
        except Exception:
            sock = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ArtworkError("Artwork took too long to load.")
            if sock is not None:
                try:
                    sock.settimeout(max(0.01, min(_READ_TIMEOUT_S, remaining)))
                except Exception:
                    sock = None
            part = read1(16_384, decode_content=True)
            if not part:
                return
            yield part
    finally:
        if sock is not None:
            try:
                sock.settimeout(original)
            except Exception:
                pass


@dataclass(frozen=True)
class ArtworkResult:
    token: object
    key: str = ""
    preview: object = None
    rgb565: bytes = b""
    dominant: int | None = None  # 0xRRGGBB; None = no accent (white)
    error: str = ""
    # artwork2 (ARTWORK2.md section 9): the 240 px baseline JPEG of the same
    # preview and its key. None when no quality of the ladder fits.
    jpeg: bytes | None = None
    jpeg_key: str | None = None
    # Desktop v5 floating knob: the 480 px continuous-scrim cover of the same source
    # (quality-90 JPEG), matched through the same key / jpeg_key. Never sent to the knob.
    hires_jpeg: bytes | None = None
    # r3.1 Navigator: the same 480 px cover without the knob's scrim. Never sent to the knob.
    clean_jpeg: bytes | None = None


def _art_key(raw: bytes) -> str:
    """The content key of a transfer: what the frame's `artKey` names."""
    return hashlib.sha256(raw).hexdigest()[:24]


ARTWORK_CACHE_LIMIT = 128  # ArtworkService cache_size clamp


class _Entry(NamedTuple):
    preview: object
    raw: bytes
    dominant: int | None
    key: str
    jpeg: bytes | None
    jpeg_key: str | None
    hires_jpeg: bytes | None = None
    clean_jpeg: bytes | None = None


class ArtworkService:
    """Debounced latest-selection covers, page prefetch on a small worker pool, one LRU.

    request(url, token, speaker_host=None) is nonblocking. poll() returns at most
    one result for the newest request. clear() invalidates in-flight work. A
    result's token belongs to the caller and must still match its current screen.

    cached(url, token, speaker_host=None) answers from the memory cache alone,
    synchronously (no I/O, no debounce), so a cover seen before swaps in on the
    same detent. Only a miss goes through request()'s debounce and download;
    request() for a URL already cached skips the debounce.

    prefetch(urls, page=..., speaker_host=None) queues the covers of a presented
    Recent page (priority order: the runtime passes them by distance from the
    selection). Every download, foreground or prefetch, has the same allowlist,
    no-credential, no-redirect, size, time and pixel bounds, and fills the same
    LRU (ARTWORK_CACHE_ENTRIES, clamp ARTWORK_CACHE_LIMIT). Scheduling
    (ARTWORK2.md section 9):

    * ``workers`` (ARTWORK_PREFETCH_WORKERS) threads serve both queues;
    * the foreground request keeps its debounce and always starts before any
      queued prefetch job; prefetch jobs never take the last idle worker (at
      most ``workers - 1`` run together), so a foreground miss never waits
      behind a running prefetch download;
    * the same page again (a selection change) never cancels queued jobs, it
      only reorders them; a new page, or ``prefetch([], page=None)`` when the
      Recent view is left, drops the jobs that have not started (a started
      download finishes and is cached);
    * a URL is downloaded once: a request for a URL another worker is loading
      waits for that download instead of starting a second one (and gives its
      worker back as soon as a newer request supersedes it: the download goes
      on and fills the cache), and a superseded foreground download of its own
      keeps running while the newest request (or the page) still wants its URL.

    cached_cover(url) is the artwork2 lookup the runtime's wanted lists use:
    (jpeg_key, jpeg) of a cached cover, or None; ``version`` grows whenever the
    cache gains a cover, so callers can tell when to look again.
    """
    def __init__(self, speaker_hosts=(), *, session=None, debounce=.12, cache_size=ARTWORK_CACHE_ENTRIES,
                 workers=ARTWORK_PREFETCH_WORKERS):
        self.speaker_hosts = tuple(speaker_hosts)
        self.session = session  # shared when injected; otherwise one requests.Session per worker
        self.debounce = debounce
        self.cache_size = max(1, min(int(cache_size), ARTWORK_CACHE_LIMIT))
        self.workers = max(1, int(workers))
        self._condition = threading.Condition()
        self._generation = 0
        self._pending = None
        self._result = None
        self._identity = None
        self._wanted_url = None        # safe URL of the newest foreground request
        self._closed = False
        # safe URL -> _Entry; guarded by _condition.
        self._cache = OrderedDict()
        self._version = 0
        self._prefetch = deque()       # unstarted prefetch jobs: (safe URL, hosts), priority order
        self._prefetch_page = None
        self._prefetch_wanted = set()  # safe URLs of the current prefetch page
        self._inflight = set()         # safe URLs a worker is downloading
        self._busy = 0                 # workers running a job
        self._local = threading.local()
        self._threads = [threading.Thread(target=self._run, name=f"NanoD-artwork-{index}", daemon=True)
                         for index in range(self.workers)]
        for thread in self._threads:
            thread.start()

    @property
    def version(self):
        """Grows whenever a cover enters the cache (no lock: an int read)."""
        return self._version

    def _hosts(self, speaker_host):
        return self.speaker_hosts + ((speaker_host,) if speaker_host else ())

    @staticmethod
    def _cache_key(url, hosts):
        """The worker's cache key: the validated URL for these hosts (raises ArtworkError)."""
        return artwork_url(url, hosts)

    def _cache_key_or_none(self, url, hosts):
        try:
            return self._cache_key(url, hosts)
        except ArtworkError:
            return None

    def _lookup(self, url, speaker_host):
        """The cache entry for ``url`` (LRU refreshed), or None; keyed exactly like the workers."""
        safe_url = self._cache_key_or_none(url, self._hosts(speaker_host))
        if safe_url is None:
            return None
        with self._condition:
            if self._closed:
                return None
            entry = self._cache.get(safe_url)
            if entry is not None:
                self._cache.move_to_end(safe_url)
            return entry

    def cached(self, url, token=None, *, speaker_host=None):
        """The ready cover for ``url`` from the memory cache, or None.

        Synchronous and I/O free. Keyed exactly like the worker's cache (the
        validated URL for the configured hosts plus ``speaker_host``), so a URL
        that request() would refuse is never a hit. A hit refreshes its LRU slot
        and carries ``token``; the caller still matches it to its own screen.
        """
        entry = self._lookup(url, speaker_host)
        return None if entry is None else self._result_for(token, entry)

    def cached_cover(self, url, *, speaker_host=None):
        """(jpeg_key, jpeg) of the cached artwork2 cover for ``url``, or None (no copy, no I/O)."""
        entry = self._lookup(url, speaker_host)
        if entry is None or not entry.jpeg or not entry.jpeg_key:
            return None
        return entry.jpeg_key, entry.jpeg

    def cached_hires(self, url, *, speaker_host=None):
        """(jpeg_key, hires_jpeg) of the cached cover for ``url`` (desktop v5), or None (no I/O)."""
        entry = self._lookup(url, speaker_host)
        if entry is None or not entry.hires_jpeg or not entry.jpeg_key:
            return None
        return entry.jpeg_key, entry.hires_jpeg

    @staticmethod
    def _result_for(token, entry):
        return ArtworkResult(token, entry.key, entry.preview.copy(), entry.raw, entry.dominant, "",
                             entry.jpeg, entry.jpeg_key, entry.hires_jpeg, entry.clean_jpeg)

    def request(self, url, token=None, *, speaker_host=None):
        with self._condition:
            if self._closed:
                return self._generation
            identity = (url, token, speaker_host)
            if identity == self._identity:
                return self._generation
            self._identity = identity
            self._generation += 1
            self._result = None
            hosts = self._hosts(speaker_host)
            safe_url = self._cache_key_or_none(url, hosts)
            self._wanted_url = safe_url
            # Only a miss waits for the debounce: a cached cover is answered at once.
            delay = 0 if safe_url is not None and safe_url in self._cache else self.debounce
            self._pending = (self._generation, time.monotonic() + delay, url, token, hosts)
            self._condition.notify_all()
            return self._generation

    def prefetch(self, urls, *, page=None, speaker_host=None):
        """Queue the covers of the presented page, in priority order (nonblocking).

        ``page`` identifies the page (the runtime passes (view id, page)). The
        same page again reorders its queued jobs and never drops one; another
        page, or ``page=None``, drops every job that has not started. Invalid,
        cached, duplicate and already-loading URLs are skipped.
        """
        with self._condition:
            if self._closed:
                return
            hosts = self._hosts(speaker_host)
            ordered, seen = [], set()
            for url in urls or ():
                safe_url = self._cache_key_or_none(url, hosts) if isinstance(url, str) and url else None
                if safe_url is None or safe_url in seen:
                    continue
                seen.add(safe_url)
                ordered.append((safe_url, hosts))
            if page is not None and page == self._prefetch_page:
                ordered += [job for job in self._prefetch if job[0] not in seen]
                wanted = self._prefetch_wanted | seen
            else:
                wanted = seen
            self._prefetch_page = page
            self._prefetch_wanted = wanted
            self._prefetch = deque(job for job in ordered
                                   if job[0] not in self._cache and job[0] not in self._inflight)
            self._condition.notify_all()

    def clear(self):
        with self._condition:
            self._generation += 1
            self._pending = self._result = self._identity = self._wanted_url = None
            self._condition.notify_all()

    def poll(self):
        with self._condition:
            result, self._result = self._result, None
            return [result] if result is not None else []

    def close(self):
        with self._condition:
            self._closed = True
            self._pending = self._result = self._wanted_url = None
            self._prefetch = deque()
            self._prefetch_wanted = set()
            self._generation += 1
            self._condition.notify_all()

    def _session(self):
        if self.session is not None:
            return self.session
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = _new_session()
        return session

    def _load(self, safe_url, hosts, cancelled):
        """Download and prepare one claimed URL, then cache it. Raises on failure."""
        prepared = prepare_artwork2(_fetch(self._session(), safe_url, hosts, cancelled))
        entry = _Entry(prepared.preview, prepared.raw, prepared.dominant, _art_key(prepared.raw),
                       prepared.jpeg, prepared.jpeg_key, prepared.hires_jpeg, prepared.clean_jpeg)
        with self._condition:
            self._cache[safe_url] = entry
            self._cache.move_to_end(safe_url)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            self._version += 1
        return entry

    def _obtain(self, safe_url, hosts, cancelled, abandon=None):
        """The cache entry for ``safe_url``: cached, awaited from another worker, or loaded here.

        ``cancelled`` stops a download of our own; ``abandon`` (default: ``cancelled``)
        ends a wait for another worker's download, which holds this worker idle.
        """
        abandon = abandon or cancelled
        with self._condition:
            while True:
                entry = self._cache.get(safe_url)
                if entry is not None:
                    self._cache.move_to_end(safe_url)
                    return entry
                if safe_url not in self._inflight:
                    self._inflight.add(safe_url)
                    break
                if abandon():
                    raise ArtworkCancelled("Artwork selection changed.")
                self._condition.wait()
        try:
            return self._load(safe_url, hosts, cancelled)
        finally:
            with self._condition:
                self._inflight.discard(safe_url)
                self._condition.notify_all()

    def _next_job(self):
        """Wait for the next job (called with the condition held); None once closed."""
        while True:
            if self._closed:
                return None
            timeout = None
            if self._pending is not None:
                remaining = self._pending[1] - time.monotonic()
                if remaining <= 0:
                    job, self._pending = ("foreground",) + self._pending, None
                    return job
                timeout = remaining
            # Prefetch never takes the last idle worker, so a foreground miss starts
            # as soon as its debounce ends. A single-worker pool (tests, fallback)
            # prefetches only while no foreground is pending.
            reserve = 1 if self.workers > 1 else 0
            if self._busy + reserve < self.workers and (reserve or self._pending is None):
                while self._prefetch:
                    safe_url, hosts = self._prefetch.popleft()
                    if safe_url in self._cache or safe_url in self._inflight:
                        continue
                    self._inflight.add(safe_url)
                    return ("prefetch", safe_url, hosts)
            self._condition.wait(timeout)

    def _foreground(self, generation, url, token, hosts):
        safe_url = None

        def cancelled():
            # A superseded download continues only while its page or the newest
            # request (A -> B -> A, which then waits for this download) wants it.
            with self._condition:
                return self._closed or (generation != self._generation and safe_url != self._wanted_url
                                        and safe_url not in self._prefetch_wanted)

        def superseded():
            # Waiting for another worker's download holds this worker: give it back as soon
            # as a newer request exists, so that request never waits behind page downloads.
            # The download goes on and fills the cache; the newest request finds the entry,
            # or waits for it on its own worker.
            with self._condition:
                return self._closed or generation != self._generation

        try:
            safe_url = self._cache_key(url, hosts)
            result = self._result_for(token, self._obtain(safe_url, hosts, cancelled, superseded))
        except ArtworkError as error:
            result = ArtworkResult(token, error=str(error))
        except Exception:
            result = ArtworkResult(token, error="Artwork could not be loaded.")
        with self._condition:
            if generation == self._generation and not self._closed:
                self._result = result

    def _prefetch_job(self, safe_url, hosts):
        """Load one claimed prefetch URL into the cache; failures are silent (never cached)."""
        try:
            self._load(safe_url, hosts, lambda: self._closed)
        except Exception:
            pass
        finally:
            with self._condition:
                self._inflight.discard(safe_url)
                self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                job = self._next_job()
                if job is None:
                    return
                self._busy += 1
            try:
                if job[0] == "foreground":
                    _, generation, _when, url, token, hosts = job
                    self._foreground(generation, url, token, hosts)
                else:
                    self._prefetch_job(job[1], job[2])
            except Exception:
                pass  # a worker never dies; the next job still runs
            finally:
                with self._condition:
                    self._busy -= 1
                    self._condition.notify_all()


class AccentService:
    """Ring accents for list entries: artwork URL -> dominant colour.

    One daemon worker with its own generation counter, its own HTTP session and
    a bounded LRU of url -> int|None (None = no accent, rendered white).

    * request_many(urls, token, speaker_host=None) is nonblocking. A new batch
      supersedes every unstarted job of older batches; a download already
      running continues only while its URL is still wanted by the newest batch.
      URLs are de-duplicated; cached URLs are answered from the LRU without I/O.
    * poll() drains (token, url, color) tuples; ``token`` is the one passed with
      the newest batch that asked for ``url``. Failed downloads report None too
      (not cached), so a caller never waits for a colour that will not come.
    * clear() drops unstarted work and undelivered results (the LRU is kept,
      a URL's colour does not change); close() stops the worker.

    Sources are limited exactly like ArtworkService (HTTPS Apple CDN or known
    Sonos speakers, no credentials, no redirects, size/time/pixel bounds).
    Nothing is logged, and URLs never enter error text.
    """
    def __init__(self, speaker_hosts=(), *, session=None, cache_size=256):
        self.speaker_hosts = tuple(speaker_hosts)
        self.session = session
        self.cache_size = max(1, min(int(cache_size), 1024))
        self._condition = threading.Condition()
        self._generation = 0
        self._queue = deque()  # unstarted (url, hosts) of the newest batch, in order
        self._wanted = {}      # url -> token for URLs the newest batch still awaits
        self._results = []
        self._cache = OrderedDict()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="NanoD-accents", daemon=True)
        self._thread.start()

    def request_many(self, urls, token=None, *, speaker_host=None):
        with self._condition:
            if self._closed:
                return self._generation
            self._generation += 1
            self._queue, self._wanted = deque(), {}
            hosts = self.speaker_hosts + ((speaker_host,) if speaker_host else ())
            seen = set()
            for url in urls or ():
                if not isinstance(url, str) or not url or url in seen:
                    continue
                seen.add(url)
                if url in self._cache:
                    self._cache.move_to_end(url)
                    self._results.append((token, url, self._cache[url]))
                    continue
                self._wanted[url] = token
                self._queue.append((url, hosts))
            self._condition.notify()
            return self._generation

    def poll(self):
        with self._condition:
            results, self._results = self._results, []
            return results

    def clear(self):
        with self._condition:
            self._generation += 1
            self._queue, self._wanted, self._results = deque(), {}, []
            self._condition.notify()

    def close(self):
        with self._condition:
            self._closed = True
            self._generation += 1
            self._queue, self._wanted, self._results = deque(), {}, []
            self._condition.notify()

    def _cancelled(self, url):
        with self._condition:
            return self._closed or url not in self._wanted

    def _compute(self, url, hosts):
        """(color, cacheable). Raises ArtworkCancelled when no longer wanted."""
        if self.session is None:
            self.session = _new_session()
        try:
            encoded = _fetch(self.session, url, hosts, lambda: self._cancelled(url))
        except ArtworkCancelled:
            raise
        except Exception:
            return None, False
        try:
            return accent_from_bytes(encoded), True
        except Exception:
            return None, False

    def _run(self):
        while True:
            with self._condition:
                while not self._closed and not self._queue:
                    self._condition.wait()
                if self._closed:
                    return
                url, hosts = self._queue.popleft()
                if url not in self._wanted:
                    continue
                if url in self._cache:
                    self._cache.move_to_end(url)
                    self._results.append((self._wanted.pop(url), url, self._cache[url]))
                    continue
            try:
                color, cacheable = self._compute(url, hosts)
            except ArtworkCancelled:
                continue
            except Exception:
                color, cacheable = None, False
            with self._condition:
                if self._closed:
                    return
                if cacheable:
                    self._cache[url] = color
                    self._cache.move_to_end(url)
                    while len(self._cache) > self.cache_size:
                        self._cache.popitem(last=False)
                if url in self._wanted:
                    self._results.append((self._wanted.pop(url), url, color))

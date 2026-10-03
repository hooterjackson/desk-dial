"""Presentation contract constants and pure helpers (no I/O, no Pillow).

Frozen with firmware/PRESENTATION_V4.md (presentation 4, cc5.3 and older) and
PRESENTATION_V5.md (presentation 5, 1.0.0-cc5.4 + desktop v7); the firmware mirrors these
values in src/cc_presentation.h and src/cc_frame_parse.cpp. Change both sides and their
tests together.
"""
from __future__ import annotations

import re

# PRESENTATION_V5.md section 1: gate every feature on the level that introduced it, never on
# PRESENTATION_VERSION (the newest level this host speaks). The artwork2, alive, glyph and v4
# frame gates use PRESENTATION_V4, so a cc5.3 knob (presentation 4) keeps all of them; only the
# v5 fields use PRESENTATION_V5.
PRESENTATION_V4 = 4
PRESENTATION_V5 = 5
PRESENTATION_VERSION = PRESENTATION_V5

# LED palette (never the LCD inks) and drive levels L0..L4 on a 0..255 scale,
# applied per channel before the firmware's global FastLED brightness cap.
LED_WHITE = 0xFFFFFF
LED_GREEN = 0x46E178
LED_RED = 0xFF4834
LED_AMBER = 0xFF961E
LED_VOLUME_RED = 0xFF3723
LEVELS = (0, 15, 46, 102, 204)
L0, L1, L2, L3, L4 = LEVELS
LEVEL_SHOULDER = 74  # odd-percent volume shoulder (deviation 1)

# Timing (milliseconds unless noted).
PULSE_MS = 260
PENDING_HOLD_MS = 3000
DECAY_MS = 260
BUTTON_FADE_MS = 220
FLASH_OK_MS = 650
FLASH_ERR_MS = 900
EXTERNAL_SECONDS = 6.0
# cubic-bezier(0.22,1,0.36,1) sampled at t = 0..1 in 1/16 steps, x255.
EASE_LUT = (0, 67, 123, 165, 195, 216, 230, 239, 245, 249, 252, 253, 254, 255, 255, 255, 255)

# Ring geometry.
RING_SEGMENTS = 60
VOLUME_START = 35
VOLUME_STEPS = 50
VOLUME_END = (VOLUME_START + VOLUME_STEPS) % RING_SEGMENTS  # 25
TRACKS_PREV = (52, 53)
TRACKS_NEUTRAL = 0
TRACKS_NEXT = (7, 8)
RING_WINDOW = 20
LIST_PITCH = 3

# LCD inks (tones) and footer inks. PRESENTATION_V5.md section 3.6: error #FF8474 (VOC-R10; was
# #FF8A7A), dim #5A5A5A (was #4A4A4A), the v5 tones on #FFFFFF / off #7A7A7A (section 5.2) and,
# [r2.2], the derived tone `liked` #A3244A (section 5.2 row 4: the filled heart, P5-R29). #FF285A
# is only the desktop Up next row heart (K4), never an LCD ink (OQ-5).
INK = 0xF2F2F2
INK_SECONDARY = 0xA6A6A6
INK_META = 0x7C7C7C
INK_ERROR = 0xFF8474
INK_SUCCESS = 0x7EE0A2
INK_DISABLED_GLYPH = 0x555555
TILE = 0x444444
TILE_INITIAL = 0xF2F2F2          # V4 letter tile initial (AW2 section 7)
INK_ON = 0xFFFFFF                # accent_ink's fallback (section 5.3)
# r3 (README section 2.2 "act", L-9): a lit-on button without an app colour, the active mode or tab.
INK_ACT = 0xFFBE69
# r3 (README section 9 "warm"): the amber line tone (`Knob: temperature`, the Seek status, Shuffle on/off).
INK_WARM = 0xFFBE69
FOOTER_INK = {"nav": 0xE6E6E6, "go": 0x6ED996, "stop": 0xFF8474, "dim": 0x5A5A5A,
              "on": INK_ON, "off": 0x7A7A7A, "liked": 0xA3244A}
TONE_INK = {"ink": INK, "muted": INK_META, "meta": INK_META, "secondary": INK_SECONDARY,
            "error": INK_ERROR, "success": INK_SUCCESS, "warm": INK_WARM}

# Wire tokens. The *_V4 tuples are what a presentation-4 parser (cc5.3 and older) accepts; the
# full tuples add the presentation-5 tokens (VOC section 1.2, append-only enum order).
LAYOUTS_V4 = ("nowPlaying", "volume", "idle", "recent", "tracks", "windows", "notice")
LAYOUTS = LAYOUTS_V4 + ("seek", "explorer", "upnext")
HOME_LAYOUTS = ("nowPlaying", "volume", "idle", "notice")
REST_LAYOUTS = ("nowPlaying", "idle")
TITLE_TONES = ("ink", "muted")
LINE_TONES = ("meta", "secondary", "error", "success")
ACTIVITIES = ("idle", "loading", "pending", "error", "unavailable", "offline")
RING_STYLES_V4 = ("off", "level", "selection", "transport")
RING_STYLES = RING_STYLES_V4 + ("lap",)
ICONS_V4 = ("play", "pause", "list", "win", "tracks", "back", "home", "more",
            "prev", "next", "switch", "cancel", "")
ICONS_V5 = ("expand", "clock", "playlists", "playnext", "seek", "shuffle", "heart", "snapleft", "snapright")
ICONS = ICONS_V4 + ICONS_V5
# Firmware enum order (CCIcon, VOC section 1.2): index = enum value.
ICON_ENUM = ("", "play", "pause", "list", "win", "tracks", "back", "home", "more", "prev", "next", "switch",
             "cancel") + ICONS_V5
LED_STYLES = ("white", "color")
LEGACY_LAYOUT = {"VOLUME": "nowPlaying", "RECENTLY ADDED": "recent", "TRACKS": "tracks", "WINDOWS": "windows"}

# Presentation 5 (PRESENTATION_V5.md sections 4-7).
BUTTON_LIT = ("on", "off")                                   # buttons[j].lit (section 5.1)
FEEDBACK_MOMENTS = ("queued", "shuffle", "like", "unlike", "snap", "started")   # feedback.moment (6.1)
FEEDBACK_SIDES = (-1, 1)                                     # feedback.side, with moment "snap" only
FEEDBACK_COLOR_MOMENTS = ("snap", "started")                 # feedback.color is kept only with these
LAP_COUNT_MAX = 59999                                        # lap ring: 1 <= count <= 59999, index < count
LED_PINK_MAX = 0xFFFFFF                                      # ledPink 0..0xFFFFFF (0 = the built-in PINK)
FRAME_BUDGET_BYTES_V5 = 1400                                 # section 14.1 (presentation >= 5)
# Latched presentation-5 field the bridge adds at send time (section 7.1): in every control frame
# and in the first frame line after the effective setting changes. Reset to false at every claim.
V5_LATCHED_FIELDS = ("reducedMotion",)
V5_LATCHED_WORST = {"reducedMotion": False}
# LED tuning fields (section 7.3, VOC section 6.2): presentation >= 5 AND `alive` only, added by the
# bridge at send time in every control frame when settings.json sets them; kept until reboot.
ALIVE_TUNING_FIELDS = ("ledPink", "ledVolFull")
ALIVE_TUNING_WORST = {"ledPink": LED_PINK_MAX, "ledVolFull": False}

# Section 2.2: the presentation-4 downgrade of a v5 frame (v7 host -> cc5.3 or older).
ICON_DOWNGRADE = {"expand": "more", "clock": "list", "playlists": "list", "playnext": "more", "seek": "tracks",
                  "shuffle": "switch", "heart": "more", "snapleft": "prev", "snapright": "next"}
SEEK_DOWNGRADE_RING = {"style": "off", "value": 0, "index": 1, "count": 3}   # the position row's centre dot
LAP_DOWNGRADE_RING = {"style": "off", "value": 0, "index": 0, "count": 0}

# Presentation 6 (Desk Dial r3 release 1: spaces navigation + Home Assistant Lights). Append-only
# additions to the v5 vocabulary; the host sends them only to a knob reporting presentation >= 6
# (and only then uses the r3 navigation at all). The v5 tuples above stay exactly as cc5.4 has them.
PRESENTATION_V6 = 6
LIGHTS_LAYOUTS = ("lights", "lightsbig", "scenes")
LAYOUTS_V6 = LAYOUTS + LIGHTS_LAYOUTS
LIGHTS_RING_STYLES = ("bri", "ctemp", "clusters")
RING_STYLES_V6 = RING_STYLES + LIGHTS_RING_STYLES + ("marker", "queue")
# r3.1 (section 19.10): the whole-queue ring of Tracks and Up next, {style "queue", index = the focus, count = T,
# now = the playing row (-1 none), first / colors as a selection ring}; `now` is kept on this style.
ICONS_V6_ADDED = ("bulb", "thermo", "power", "wand", "house", "album")
ICONS_V6 = ICONS + ICONS_V6_ADDED
ICON_ENUM_V6 = ICON_ENUM + ICONS_V6_ADDED        # firmware CCIcon, appended after the v5 tokens
VALUE_UNITS = ("%", "K")                         # `valueUnit` (lightsbig): default "%"
RING_KELVIN_MIN, RING_KELVIN_MAX = 2200, 6500     # ring.kelvin (bri / ctemp): the arc's colour temperature
RING_KELVIN_DEFAULT = 2700                       # the host fills a missing / invalid one (the knob requires it)
CLUSTERS_MAX = 20                                # clusters: 1 <= count <= 20, index < count
V6_TEXT_CAPACITY = {"prevTitle": 64, "nextTitle": 64}
# r3 navigation (README sections 1-3; PRESENTATION_V5.md section 19.9), append-only:
# `crumb` selects the pre-rendered arc breadcrumb (absent = none: the launcher, older screens);
CRUMBS = ("music", "recent", "onScreenRecent", "onScreenPlaylists", "tracks", "upnext", "windows", "lights",
          "scenes", "playlists")   # r3.1: `playlists` = MUSIC › PLAYLISTS (the knob list on Favourite playlists)
# the `warm` line tone (metaTone / statusTone) #FFBE69;
LINE_TONES_V6 = ("meta", "secondary", "error", "success", "warm")
# feedback.moment `refused` (kind "err" only): the unavailable-press flash (bottom 26-34 red, 320 ms);
FEEDBACK_MOMENTS_V6 = ("queued", "shuffle", "like", "unlike", "snap", "started", "refused")
# the `marker` ring (index < count, 1 <= count): a white marker at index on the r3 arc, the rest warm 0.1.
V6_FIELDS = ("valueUnit", "prevTitle", "nextTitle", "crumb", "holdMarker")
# r3.1 (section 19.10): `holdMarker` true = button 4 has a hold action on this screen (the knob draws the
# hold tick under its icon and the 1.0 s hold ring); absent = none.
# A v6 frame for an older knob (never produced by the controller, which uses r3 only at >= 6).
LAYOUT_DOWNGRADE_V6 = {"lights": "recent", "lightsbig": "recent", "scenes": "recent"}
ICON_DOWNGRADE_V6 = {"bulb": "more", "thermo": "more", "power": "more", "wand": "more", "house": "home",
                     "album": "list"}
LIGHTS_DOWNGRADE_RING = {"style": "off", "value": 0, "index": 0, "count": 0}


def kelvin_rgb(kelvin: int) -> int:
    """README section 3's Kelvin -> RGB (Tanner Helland; white-only bulbs, 2200-6500 K) as 0xRRGGBB.
    2200 K ~ (255,146,39), 3200 K ~ (255,183,112), 6500 K ~ (255,254,250). The firmware calibrates
    against the ring's white point; this is the reference curve (desktop mirror, tests)."""
    import math
    t = max(RING_KELVIN_MIN, min(RING_KELVIN_MAX, int(kelvin))) / 100.0
    r = 255.0 if t <= 66 else 329.7 * (t - 60) ** -0.1332
    g = 99.47 * math.log(t) - 161.12 if t <= 66 else 288.12 * (t - 60) ** -0.0755
    b = 255.0 if t >= 66 else 138.52 * math.log(t - 10) - 305.04
    out = 0
    for channel in (r, g, b):
        out = (out << 8) | int(max(0.0, min(255.0, math.floor(channel + 0.5))))   # rounded half up
    return out

# UTF-8 byte capacities (CCFrame buffer size minus NUL).
TEXT_CAPACITY = {"mode": 24, "target": 64, "value": 64, "detail": 96, "status": 64,
                 "title": 96, "subtitle": 96, "counter": 24, "volumeCaption": 96,
                 "heading": 32, "meta": 96}
BUTTON_LABEL_CAPACITY = 16
ART_KEY_PATTERN = r"[A-Za-z0-9_-]{0,64}"
FRAME_BUDGET_BYTES = 1100

# artwork2 (1.0.0-cc5.3, firmware/ARTWORK2.md): 240 px JPEG covers,
# 32x32 app icons, knob-side prefetch and unpaced whole-line writes.
ARTWORK2_CAPABILITY = {
    "version": 1, "available": True, "composited": "scrim80", "paced": False, "rxBytes": 8192,
    "chunkBytes": 2048, "haveKeys": 24,
    "cover": {"width": 240, "height": 240, "format": "JPEG", "maxBytes": 32768, "entries": 24},
    "icon": {"width": 32, "height": 32, "format": "RGB565_LE", "bytes": 2048, "entries": 48,
             "background": "black"},
}
MEDIA_KINDS = ("cover", "icon")
MEDIA_KEY_PATTERN = r"[A-Za-z0-9_-]{1,24}"
ICON_KEY_PATTERN = r"[A-Za-z0-9_-]{0,24}"
MEDIA_CHUNK_BYTES = 2048
MEDIA_HAVE_KEYS = 24
MEDIA_ACK_TIMEOUT_SECONDS = 1.5
MEDIA_RETRY_SECONDS = 1.0
MEDIA_WANTED_RESERVE = 4          # wanted list capped at entries - 4 per kind
COVER_SIZE = 240
COVER_MAX_BYTES = 32768
COVER_KEY_CHARS = 24
COVER_JPEG_QUALITIES = (85, 80, 75, 70, 65, 60)
ICON_SIZE = 32
ICON_BYTES = ICON_SIZE * ICON_SIZE * 2
ICON_KEY_CHARS = 16
ARTWORK_PREFETCH_WORKERS = 3
ARTWORK_CACHE_ENTRIES = 64

# "Warm · alive" LEDs (1.0.0-cc5.4, firmware/ALIVE.md). The host sends the section 3
# fields only when capabilities[ALIVE_CAPABILITY]["version"] == ALIVE_VERSION (an int), and never
# to cc5.3 or older firmware. The firmware parser (src/cc_frame_parse.cpp) mirrors these ranges.
ALIVE_CAPABILITY = "alive"
ALIVE_VERSION = 1
ALIVE_CLOCK_MAX = 1439                     # clock: local minutes since midnight, 0..1439
ALIVE_PROGRESS_MAX_MS = 86400000           # progress.pos / progress.dur: 0..24 h in ms; pos <= dur unless dur == 0
ALIVE_LED_DRIVE_MIN, ALIVE_LED_DRIVE_MAX = 1, 255   # ledDrive
ALIVE_SKIP_VALUES = (-1, 1)                # feedback.skip, only with feedback.kind "ok"
ALIVE_LIMIT_VALUES = (-1, 1)               # knob -> host {"id": <control id>, "lim": -1|1}
ALIVE_PLAYING_LAYOUTS = ("nowPlaying", "volume", "idle", "notice")   # playing: Home layouts only
# Frame content (the controller's) and the latched fields the bridge adds at send time (10.2).
ALIVE_CONTENT_FIELDS = ("playing",)        # plus feedback.skip
ALIVE_LATCHED_FIELDS = ("clock", "progress", "ledDrive", "ledDither")
ALIVE_CLOCK_RESEND_SECONDS = 600.0         # clock again in the next frame once 10 min have passed
# The longest value of every latched field: the section 8 budget reserves them on an alive knob,
# so a frame line with all of them added at send time still fits FRAME_BUDGET_BYTES.
ALIVE_LATCHED_WORST = {"clock": ALIVE_CLOCK_MAX,
                       "progress": {"pos": ALIVE_PROGRESS_MAX_MS, "dur": ALIVE_PROGRESS_MAX_MS},
                       "ledDrive": ALIVE_LED_DRIVE_MAX, "ledDither": False}

# Glyphs the cc5 fonts carry (capability glyphs == "latin-ext-a").
EXTRA_GLYPHS = "·–—‘’“”•…"


_CONTROL_RUN = re.compile("[\x00-\x1f\x7f]+")


def clean_text(text: str) -> str:
    """Replace each run of C0 controls or DEL with one space.

    Outside metadata (track and window titles) may carry newlines or tabs; a
    parser rejects them in required fields (section 3), so the host removes
    them where the frame text is created.
    """
    return _CONTROL_RUN.sub(" ", text) if isinstance(text, str) else text


def utf8_truncate(text: str, capacity: int) -> str:
    """Longest prefix whose UTF-8 encoding fits in capacity bytes (never splits a code point)."""
    data = text.encode("utf-8")
    if len(data) <= capacity:
        return text
    # Valid input: the only undecodable bytes are a code point cut at the end.
    return data[:capacity].decode("utf-8", errors="ignore")


def supported_glyph(ch: str) -> bool:
    code = ord(ch)
    return 0x20 <= code <= 0x7E or 0xA0 <= code <= 0x17F or ch in EXTRA_GLYPHS


def window_first(index: int, count: int) -> int:
    """First transmitted entry of the bounded ring window: V4's rule clamp(index-9, 0, count-20).

    Also every parser's derivation for an ABSENT `first` (PRESENTATION_V5.md section 4.2)."""
    if count <= RING_WINDOW:
        return 0
    return max(0, min(index - 9, count - RING_WINDOW))


def window_first_v5(index: int, count: int) -> int:
    """PRESENTATION_V5.md section 4.2 (VOC-R03): a v5 host's window, clamp(index-10, 0, count-20).

    A v5 host always sends it when count > 20 (P5-R9), so the parser never derives it."""
    if count <= RING_WINDOW:
        return 0
    return max(0, min(index - 10, count - RING_WINDOW))


def mmss(seconds: int) -> str:
    """Section 4.3: the Seek time, minutes unpadded and seconds two digits (C: "%u:%02u")."""
    return f"{seconds // 60}:{seconds % 60:02d}"


def sat_rgb(color: int):
    """ALIVE.md section 2 `sat()` of 0xRRGGBB in exact integers, as cc_alive_sat(): each channel
    round(max(0, x - 0.75 mn) / (mx - 0.75 mn) * 255), half away from zero. None when
    max - min < 30 (the WARM fallback)."""
    channels = ((color >> 16) & 255, (color >> 8) & 255, color & 255)
    mx, mn = max(channels), min(channels)
    if mx - mn < 30:
        return None
    den = 4 * mx - 3 * mn
    out = 0
    for x in channels:
        num = 255 * max(0, 4 * x - 3 * mn)
        out = (out << 8) | min(255, (2 * num + den) // (2 * den))
    return out


def _linear(channel: int) -> float:
    e = channel / 255.0
    return e / 12.92 if e <= 0.04045 else ((e + 0.055) / 1.055) ** 2.4


def relative_luminance(color: int) -> float:
    """sRGB relative luminance 0.2126 R + 0.7152 G + 0.0722 B of linearised channels."""
    return (0.2126 * _linear((color >> 16) & 255) + 0.7152 * _linear((color >> 8) & 255)
            + 0.0722 * _linear(color & 255))


ACCENT_INK_MIN_LUMINANCE = 0.10   # >= 3:1 against black


def accent_ink(color: int) -> int:
    """Section 5.3: the LCD ink of an assigned snap side (`lit:"on"` + `color`), integer in/out.

    0, or a colour whose sat() falls back to WARM -> #FFFFFF (the plain `on` ink). Otherwise
    s = sat(color), lifted towards white in eighths, m_j = s + ((255 - s) * j + 4) / 8 per channel
    (integer), j = 0..8: the first m_j with relative luminance >= 0.10 (j = 8 is white).
    Example (the contract's): navy 0x000080 -> sat 0x0000FF -> j = 2 -> 0x4040FF."""
    s = sat_rgb(color) if color else None
    if s is None:
        return INK_ON
    base = ((s >> 16) & 255, (s >> 8) & 255, s & 255)
    for j in range(9):
        lifted = 0
        for c in base:
            lifted = (lifted << 8) | (c + ((255 - c) * j + 4) // 8)
        if relative_luminance(lifted) >= ACCENT_INK_MIN_LUMINANCE:
            return lifted
    return INK_ON  # not reached: j = 8 is white


def button_tone_v5(slot: int, icon: str, enabled: bool, lit=None, layout: str = "") -> str:
    """PRESENTATION_V5.md section 5.2 (VOC section 2.3): the tone of one button, first match wins.

    `icon` is the effective icon (the wire token, or cc_legacy_icon(label) for a legacy frame
    without icons), `lit` is "on" / "off" / None (absent), `layout` the frame's layout. [r2.2] Row
    4, `heart` + `lit:"on"`, is the derived tone `liked` (CCButtonTone 7, P5-R29); the tone `on`
    covers rows 5-6 (accent and white inks: button_ink_v5)."""
    if not icon:
        return "none"
    if not enabled:
        return "dim"
    if slot == 0 and icon == "cancel":
        return "stop"
    if lit == "on" and icon == "heart":
        return "liked"   # row 4 [r2.2]: the filled heart in #A3244A (was `on` + PINK)
    if lit == "on":
        return "on"
    if lit == "off":
        return "off"
    if slot == 3 and icon in ("play", "prev", "next", "switch"):
        return "go"
    if slot == 0 and icon == "play" and layout in HOME_LAYOUTS:
        return "go"   # paused Home Play (the breath is LED-only)
    return "nav"


def button_ink_v5(slot: int, icon: str, enabled: bool, lit=None, color: int = 0, layout: str = "",
                  crumb: str = "") -> int:
    """Section 5.2's footer / idle-row ink of one button (0 = hidden, tone none)."""
    tone = button_tone_v5(slot, icon, enabled, lit, layout)
    if tone == "none":
        return 0
    if tone == "on":
        if color:
            return accent_ink(color)                     # row 5
        return INK_ACT if crumb else INK_ON              # row 6; presentation 6: act #FFBE69 on r3 screens
    return FOOTER_INK[tone]   # includes row 4, `liked` #A3244A (never sat(), whatever ledPink is)


def button_tone(slot: int, icon: str, enabled: bool) -> str:
    """PRESENTATION_V4.md section 5.9: the V4 tone (what cc_button_tone() derives today).

    button_tone_v5() is the presentation-5 table (section 5.2); the firmware header switches
    to it together with the LCD and LED packages (handoff)."""
    if not icon:
        return "none"
    if not enabled:
        return "dim"
    if slot == 0 and icon == "cancel":
        return "stop"
    if slot == 3 and icon in ("play", "prev", "next", "switch"):
        return "go"
    return "nav"

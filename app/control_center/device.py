"""Single-owner, leased Nano_D++ control-center connection.

Importing this module never opens a port. Inventory only queries returned names;
runtime controls cannot create or persist device profiles.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import base64
import bisect
import json
import logging
from pathlib import Path
import queue
import re
import threading
import time
import uuid
import unicodedata
import zlib

from protocol import LineDecoder

from . import presentation


class PacedSerial:
    """Bound native-USB bursts for the installed firmware's small CDC buffer.

    With artwork2 negotiated (ARTWORK2.md section 3) the bridge writes whole lines
    straight to ``port`` instead; this wrapper itself never changes.
    """
    CHUNK_BYTES = 64
    GAP_SECONDS = 0.005

    def __init__(self, port, sleep=time.sleep):
        self.port, self.sleep = port, sleep

    def __getattr__(self, name):
        return getattr(self.port, name)

    def write(self, data):
        written = 0
        for start in range(0, len(data), self.CHUNK_BYTES):
            part = data[start:start + self.CHUNK_BYTES]
            count = self.port.write(part)
            written += count
            if count != len(part):
                return written
            if written < len(data):
                self.sleep(self.GAP_SECONDS)
        return written


def _open_serial(port):
    try:
        import serial
    except ImportError:
        import sys
        vendor = Path(__file__).resolve().parents[1] / "vendor"
        if vendor.is_dir():
            sys.path.insert(0, str(vendor))
        import serial
    # Normal native-USB connection: DTR/RTS asserted, as verified with this kit.
    return PacedSerial(serial.Serial(port, 115200, timeout=0.05, write_timeout=1.0))


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


_LCD_PUNCTUATION = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", "·": "/", "•": "/", "×": "x", "⁄": "/",
    "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "ß": "ss"})
_LCD_MARKS = frozenset(("Mn", "Mc", "Me", "Cf"))
_ZWJ = "‍"


def _ascii_glyph(c):
    """The installed ASCII Montserrat set: printable ASCII (U+0020-007E) only."""
    return " " <= c <= "~"


def _lcd_dropped(c):
    """Invisible parts of a character: combining marks, format characters (joiners, tags), variation
    selectors and emoji skin-tone modifiers."""
    code = ord(c)
    return (unicodedata.category(c) in _LCD_MARKS or 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF
            or 0x1F3FB <= code <= 0x1F3FF)


def _lcd_text(text, glyph=_ascii_glyph):
    """Readable fallback for the knob's glyph set (``glyph``: ASCII by default).

    Only the copied device presentation is adapted; item identity, playback
    resolution and the companion's full Unicode strings remain untouched.
    DD-DES-002: each source character is adapted on its own: kept when it is a glyph, its
    punctuation or compatibility (NFKD) form when every part of that is a glyph, otherwise ONE
    "?" (a Hangul syllable, an Arabic ligature, an emoji with its modifiers, joiners and flag pair
    each count once), never a run of "?" for one character.
    """
    out = []
    joined = regional = False
    for c in text:
        if glyph(c):
            out.append(c)
            joined = regional = False
            continue
        if c == _ZWJ:
            joined = bool(out) and out[-1] == "?"     # an emoji ZWJ sequence stays one character
            continue
        if _lcd_dropped(c):
            continue
        code = ord(c)
        if joined:
            joined = False
            continue
        if 0x1F1E6 <= code <= 0x1F1FF:                  # regional indicators: a flag is a pair
            regional = not regional
            if not regional:
                continue
        else:
            regional = False
        mapped = c.translate(_LCD_PUNCTUATION)
        if mapped == c:
            mapped = "".join(p for p in unicodedata.normalize("NFKD", c)
                             if unicodedata.category(p) not in _LCD_MARKS).translate(_LCD_PUNCTUATION)
        out.append(mapped if mapped and all(glyph(p) for p in mapped) else "?")
    return "".join(out)


# ---------------------------------------------------------------------------
# Presentation contract v4 (firmware/PRESENTATION_V4.md, sections 2-4, 7-8).
# Malformed REQUIRED fields reject the frame (ValueError). Invalid or unsupported
# OPTIONAL fields are stripped and logged (rate-limited); they never raise.

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())  # the application configures the real handlers
_STRIP_LOG_SECONDS = 60.0
_strip_logged = {}
_ART_KEY = re.compile(presentation.ART_KEY_PATTERN)
_ICON_KEY = re.compile(presentation.ICON_KEY_PATTERN)
_MEDIA_KEY = re.compile(presentation.MEDIA_KEY_PATTERN)
_REQUIRED_TEXT = ("mode", "target", "value", "detail", "status")
_OPTIONAL_TEXT = ("title", "subtitle", "counter", "volumeCaption", "heading", "meta")
_V4_FIELDS = frozenset(("restLayout", "heading", "meta", "titleTone", "metaTone", "statusTone",
                        "page", "artDim", "feedback"))
_V4_RING_FIELDS = ("first", "colors", "unavailable", "moreIndex", "external")
_HOME_LAYOUTS = ("nowPlaying", "volume", "idle", "notice")
_TONE_DEFAULTS = {"titleTone": "ink", "metaTone": "meta", "statusTone": "meta"}
_LEGACY_BUTTON_COLORS = {"go": 0x66C991, "stop": 0xCE7474}
_LEGACY_WHITE = 0xF0EEE7
# ALIVE.md section 3 (1.0.0-cc5.4): top-level fields sent only with `alive` negotiated.
_ALIVE_FIELDS = frozenset((*presentation.ALIVE_CONTENT_FIELDS, *presentation.ALIVE_LATCHED_FIELDS))
# PRESENTATION_V5.md: `reducedMotion` (presentation >= 5; section 7.1) and the LED tuning fields
# (presentation >= 5 and `alive`; section 7.3). Both are latched fields the bridge adds at send time.
_V5_FIELDS = frozenset(presentation.V5_LATCHED_FIELDS)
_TUNING_FIELDS = frozenset(presentation.ALIVE_TUNING_FIELDS)
_V5_RING_FIELDS = ("now", "card")
# Presentation 6 (Desk Dial r3): `valueUnit`, `prevTitle`, `nextTitle` and `ring.kelvin`.
_V6_FIELDS = frozenset(presentation.V6_FIELDS)
_V6_RING_FIELDS = ("kelvin",)
_KNOWN_FIELDS = frozenset(("id", "buttons", "ring", "activity", "layout", "ledStyle", "artKey",
                           "volumeVisible", "confirmedVolume", "iconKey", *_REQUIRED_TEXT, *_OPTIONAL_TEXT,
                           *_V4_FIELDS, *_ALIVE_FIELDS, *_V5_FIELDS, *_TUNING_FIELDS, *_V6_FIELDS, "app"))


_KNOWN_SUBFIELDS = frozenset(["frame", "button.icon", "button.color", "button.lit", "ring.index", "feedback.skip",
                              "feedback.moment", "feedback.side", "feedback.color"] + [
    "ring." + name for name in _V4_RING_FIELDS + _V5_RING_FIELDS + _V6_RING_FIELDS + ("available",)])
# Legacy text that v4 renderers never draw; emptied (in this order) only when a
# v4 frame would otherwise exceed presentation.FRAME_BUDGET_BYTES. `value` is drawn
# only as the Home volume digits, so it is kept on Home layouts; elsewhere it is a
# legacy copy of the Recent/Windows title.
_BUDGET_TRIM = ("detail", "value", "target")
_BUDGET_HOME_KEPT = frozenset(("value",))
# Drawn outside text, shortened (longest first, whole code points from the end) only
# when JSON escapes (quotes, backslashes) still keep a frame over budget after the
# legacy trim. On equal sizes the Home volume caption goes first, then the subtitle.
_BUDGET_SHRINK = ("volumeCaption", "subtitle", "title")
# Artwork failures are events (artwork-error), never `error` or a disconnect.
ARTWORK_TRANSIENT = ("timeout", "parse")
ARTWORK_LINE_ERRORS = ("parse", "too large", "oversize")
ARTWORK_MESSAGES = {
    "unsupported": "This firmware cannot display album artwork.",
    "size": "Album artwork does not match the knob's negotiated format.",
    "invalid": "Album artwork request was invalid.",
    "timeout": "Album artwork transfer timed out.",
    "parse": "The knob could not read an album artwork packet.",
    "rejected": "The knob could not receive this album artwork.",
}


def _strip(field, reason, action="stripped"):
    """Record a stripped optional field without echoing its (possibly private) value."""
    if field not in _KNOWN_FIELDS and field not in _KNOWN_SUBFIELDS:
        field = "button.unknown" if field.startswith("button.") else (
            "ring.unknown" if field.startswith("ring.") else "unknown")
    now = time.monotonic()
    last = _strip_logged.get((field, reason))
    if last is None or now - last >= _STRIP_LOG_SECONDS:
        _strip_logged[(field, reason)] = now
        _log.warning("Presentation field %s %s: %s", field, action, reason)


def presentation_level(capabilities):
    """The knob's `presentation` capability (an int; anything else is 0).

    PRESENTATION_V5.md section 1: `level >= PRESENTATION_V5` negotiates the v5 frame fields,
    `kh`, `ks` in `ready`, `hid` and `reducedMotion`; every older feature (artwork2, alive, the
    latin-ext-a glyphs, the v4 frame fields) is gated on `level >= PRESENTATION_V4`, so a cc5.3
    knob (presentation 4) keeps it."""
    level = (capabilities or {}).get("presentation", 0)
    return level if type(level) is int else 0


def _artwork_capability(capabilities):
    """The negotiated artwork format, or None when art cannot be sent."""
    cap = (capabilities or {}).get("artwork")
    if (not isinstance(cap, dict) or cap.get("version") != 1 or cap.get("available", True) is False
            or (cap.get("width"), cap.get("height")) not in ((120, 120), (240, 240))
            or cap.get("format") != "RGB565_LE" or not _integer(cap.get("chunkBytes"), 2, 2048)):
        return None
    return cap


def _exact(value, expected):
    """`value` has every field of `expected` with exactly its type and value (extras ignored)."""
    if isinstance(expected, dict):
        return isinstance(value, dict) and all(name in value and _exact(value[name], sub)
                                               for name, sub in expected.items())
    return type(value) is type(expected) and value == expected


def artwork2_capability(capabilities):
    """The negotiated artwork2 capability (ARTWORK2.md section 1), or None.

    Only presentation >= 4 firmware whose `artwork2` object carries exactly the
    frozen fields (types included: 1 is not True) negotiates it; anything else
    keeps the v4 behaviour of today (v1 art paced on cc5.x, text on cc4).
    """
    if presentation_level(capabilities) < presentation.PRESENTATION_V4:
        return None
    if not _exact((capabilities or {}).get("artwork2"), presentation.ARTWORK2_CAPABILITY):
        return None
    return deepcopy(presentation.ARTWORK2_CAPABILITY)


# A2 app canvas (1.0.0-cc5.6; ONSHAPE.md section 10, CONTROL_CENTER.md "App canvas"): the frame's `app` object,
# sent only to a presentation-6 knob whose capabilities carry appCanvas 1. The knob then draws the app's own UI
# (Karl Malota's Onshape screens) instead of the text frame; an older knob never sees `app` (dropped silently)
# and shows A0's text screens.
# App profiles (APP_PROFILES.md sections 7-8; plan section 1c, S1 DD-B): `id` is any profile id (1..11 of
# [a-z0-9_-]), an optional `crc` (u32) names the uploaded copy (0 / absent = the built-in Onshape), the slot tokens
# knob / f1..f4 follow the legacy four, `index` goes to 32 and `param` carries the live constraint (`axis` 0..3,
# `plane`). A knob without `appProfiles` gets the legacy object only (_legacy_app): its parser never sees new fields.
APP_CAPABILITY = "appCanvas"
APP_PROFILES_CAPABILITY = "appProfiles"
WIRE_VERSION_APP = 1                                       # the DDAP wire version (APP_PROFILES.md)
APP_IDS = {"onshape": 1}                                   # the cc5.6 built-in (index 1); kept for older readers
APP_SLOTS = {"zoom": 0, "orbit": 1, "pan": 2, "tilt": 3,  # append-only (CCAppSlot); tilt: Desk Dial 7.2.2.0
             "knob": 4, "f1": 5, "f2": 6, "f3": 7, "f4": 8}
APP_LEGACY_SLOTS = ("zoom", "orbit", "pan", "tilt")
APP_MODES = {"A": False, "B": True}
APP_RING_MAX = 7
APP_INDEX_MAX = 32
APP_LEGACY_INDEX_MAX = 15
APP_VALUE_MAX = 99_999_999
APP_CRC_MAX = 0xFFFFFFFF
APP_AXIS_MAX = 3
_APP_SEQ_MAX = 0x7FFFFFFF
_APP_ID = re.compile(r"[a-z0-9_-]{1,11}")


def app_capability(capabilities):
    """True when the knob draws the frame's `app` object: presentation >= 6 and capabilities.appCanvas == 1."""
    caps = capabilities if isinstance(capabilities, dict) else {}
    value = caps.get(APP_CAPABILITY)
    return presentation_level(caps) >= presentation.PRESENTATION_V6 and type(value) is int and value == 1


def app_profiles_capability(capabilities):
    """{"slots", "maxBytes", "features"} when the knob takes uploaded app profiles (APP_PROFILES.md section 7:
    appProfiles 1 on an appCanvas knob, the three sizes as ints), else None."""
    caps = capabilities if isinstance(capabilities, dict) else {}
    if not app_capability(caps) or not _integer(caps.get(APP_PROFILES_CAPABILITY), 1, 1):
        return None
    slots, size, features = caps.get("appProfileSlots"), caps.get("appProfileMaxBytes"), caps.get("appProfileFeatures")
    if not (_integer(slots, 1, 64) and _integer(size, 1, 1 << 24) and _integer(features, 0, APP_CRC_MAX)):
        return None
    return {"slots": slots, "maxBytes": size, "features": features}


def app_parse(value):
    """The firmware's reading of a frame's `app` object (cc_frame_parse.cpp parse_app): (stored, ok).

    `stored` mirrors CCAppState as the harness prints it (the id as text, the crc, the slot as its number, defaults
    for what is absent); `ok` False means the firmware rejects the whole frame (the strict rule), and `stored` is
    None. Unknown keys are ignored; a well-formed id that is not loaded is accepted (the knob draws "Loading").
    `param.axis` (0..3, never a bool) and `param.plane` (a bool) are checked, not stored (the harness doesn't print
    them). harness/app_canvas_tests.py holds both readings to one table."""
    if not isinstance(value, dict):
        return None, False
    ident, slot = value.get("id"), value.get("slot")
    if not isinstance(ident, str) or _APP_ID.fullmatch(ident) is None or not isinstance(slot, str) \
            or slot not in APP_SLOTS:
        return None, False
    stored = {"id": ident, "crc": 0, "slot": APP_SLOTS[slot], "refused": False, "flash": 0, "wheel": False,
              "wheelRing": 0, "wheelIndex": 0, "param": False, "paramRing": 0, "paramIndex": 1, "paramTyped": False,
              "paramStep": 1, "paramValue": 0, "paramBump": 0, "echoSeq": 0, "echoRing": 0, "echoIndex": 1}
    if "crc" in value:
        if not _integer(value["crc"], 0, APP_CRC_MAX):
            return None, False
        stored["crc"] = value["crc"]
    if "refused" in value:
        if type(value["refused"]) is not bool:
            return None, False
        stored["refused"] = value["refused"]
    if "flash" in value:
        if not _integer(value["flash"], 0, _APP_SEQ_MAX):
            return None, False
        stored["flash"] = value["flash"]
    if "wheel" in value:
        wheel = value["wheel"]
        if not isinstance(wheel, dict) or not _integer(wheel.get("ring"), 0, APP_RING_MAX) \
                or not _integer(wheel.get("index"), 0, APP_INDEX_MAX):
            return None, False
        stored.update(wheel=True, wheelRing=wheel["ring"], wheelIndex=wheel["index"])
    if "param" in value:
        param = value["param"]
        if not isinstance(param, dict) or not _integer(param.get("ring"), 0, APP_RING_MAX) \
                or not _integer(param.get("index"), 1, APP_INDEX_MAX) or param.get("mode") not in APP_MODES \
                or not isinstance(param.get("mode"), str) or not _integer(param.get("step"), 0, 2) \
                or not _integer(param.get("value"), -APP_VALUE_MAX, APP_VALUE_MAX):
            return None, False
        if "bump" in param and not _integer(param["bump"], 0, _APP_SEQ_MAX):
            return None, False
        if "axis" in param and not _integer(param["axis"], 0, APP_AXIS_MAX):
            return None, False
        if "plane" in param and type(param["plane"]) is not bool:
            return None, False
        stored.update(param=True, paramRing=param["ring"], paramIndex=param["index"],
                      paramTyped=APP_MODES[param["mode"]], paramStep=param["step"], paramValue=param["value"],
                      paramBump=param.get("bump", 0))
    if "echo" in value:
        echo = value["echo"]
        if not isinstance(echo, dict) or not _integer(echo.get("ring"), 0, APP_RING_MAX) \
                or not _integer(echo.get("index"), 1, APP_INDEX_MAX) or not _integer(echo.get("seq"), 1, _APP_SEQ_MAX):
            return None, False
        stored.update(echoSeq=echo["seq"], echoRing=echo["ring"], echoIndex=echo["index"])
    return stored, True


# App profiles upload (APP_PROFILES.md section 7): stop-and-wait, one data line per bridge pass, each acked.
APP_PROFILE_CHUNK_B64 = 3000                     # b64 characters a data line carries at most (2,250 bytes)
APP_PROFILE_CHUNK_BYTES = APP_PROFILE_CHUNK_B64 // 4 * 3
APP_PROFILE_REPLY_SECONDS = 1.0                  # per line: list, each data ack, end
APP_PROFILE_ERRORS = re.compile(r"(crc|size|order|busy|wire|decode:\d{1,3}@\d{1,6})")


def legacy_app_parse(value):
    """The cc5.6 / cc5.7 reading (before app profiles): id "onshape" only, the legacy slots, no crc, index <= 15,
    no axis / plane. (stored, ok)."""
    stored, ok = app_parse(value)
    if not ok or value.get("id") != "onshape" or value.get("slot") not in APP_LEGACY_SLOTS or "crc" in value:
        return None, False
    for name in ("wheel", "param", "echo"):
        part = value.get(name)
        if isinstance(part, dict) and (part.get("index", 0) > APP_LEGACY_INDEX_MAX or "axis" in part
                                       or "plane" in part):
            return None, False
    return stored, True


def _legacy_app(raw):
    """The `app` object as a knob without appProfiles may see it, or None: the built-in Onshape's crc 0 is dropped
    (the default), a param's axis / plane removed; anything else new (a profile id or slot, an index past 15, an
    upload's crc) strips the whole object."""
    if not isinstance(raw, dict):
        return None
    value = deepcopy(raw)
    if type(value.get("crc")) is int and value["crc"] == 0:
        value.pop("crc")
    if isinstance(value.get("param"), dict):
        value["param"].pop("axis", None)
        value["param"].pop("plane", None)
    return value if legacy_app_parse(value)[1] else None


# r4 FEEL + SOUND (firmware 1.0.0-cc5.7, plan F2 / F3; firmware HAPTICS.md, CONTROL_CENTER.md "Feel and sound"). Each
# is its own capability (an int 1): `feel` (control `feel` and `reducedHaptics`), `hapticFx` (the frame's `haptic`
# event), `knobSound` (control `sound` 0..3), `offlineVolume` (informational: the knob is the PC's volume while no
# host has the port) and `recalibration` (the calibrating / calibrated protocol). A knob without one never sees the
# fields it names (dropped silently): cc5.6 and older keep today's feel and stay silent.
# `knobVolume` (Desk Dial 7.3.1): control `soundVolume` 0..100, the speaker's master volume in percent (0 silent,
# 100 the loudest sound at the speaker's full range); the knob then ignores `sound`, which still goes with it.
FEEL_CAPABILITY, HAPTIC_CAPABILITY, SOUND_CAPABILITY = "feel", "hapticFx", "knobSound"
KNOB_VOLUME_CAPABILITY = "knobVolume"
OFFLINE_VOLUME_CAPABILITY, RECALIBRATION_CAPABILITY = "offlineVolume", "recalibration"
FEEL_TOKENS = ("detent.value", "detent.dimmer", "detent.list", "detent.coarse", "detent.fine", "fluid.scrub",
               "fluid.light", "free.spin")
# The firmware's CCFx order (cc_haptic_fx.h): the stored `fx` number of each wire token.
HAPTIC_TOKENS = {"confirm.tick": 1, "confirm.thump": 2, "nudge.left": 3, "nudge.right": 4, "refuse.buzz": 5,
                 "error.buzz": 6, "confirm.off": 7}
SOUND_LEVELS = ("off", "low", "medium", "high")         # control `sound` 0..3 (settings.json `knob_sound`)
KNOB_VOLUME_MAX = 100                                    # control `soundVolume` 0..100 (percent)
SOUND_LEVEL_VOLUMES = (0, 40, 70, 100)                   # the top volume of each `sound` level (Low 1..40, …)
_HAPTIC_SEQ_MAX = 0x7FFFFFFF


def _capability_one(capabilities, name):
    caps = capabilities if isinstance(capabilities, dict) else {}
    value = caps.get(name)
    return type(value) is int and value == 1


def feel_capability(capabilities):
    """True when the knob runs the r4 feel tokens (capabilities.feel == 1)."""
    return _capability_one(capabilities, FEEL_CAPABILITY)


def haptic_capability(capabilities):
    """True when the knob plays the frame's `haptic` events (capabilities.hapticFx == 1)."""
    return _capability_one(capabilities, HAPTIC_CAPABILITY)


def sound_capability(capabilities):
    """True when the knob makes the r4 click sounds (capabilities.knobSound == 1)."""
    return _capability_one(capabilities, SOUND_CAPABILITY)


def knob_volume_capability(capabilities):
    """True when the knob takes the speaker volume in percent (capabilities.knobVolume == 1)."""
    return _capability_one(capabilities, KNOB_VOLUME_CAPABILITY)


def sound_level_for_volume(volume):
    """The `sound` level (0..3) a knob without knobVolume gets for a volume: 0 off, 1..40 Low, 41..70 Medium,
    71..100 High."""
    return next(level for level, top in enumerate(SOUND_LEVEL_VOLUMES) if volume <= top)


def recalibration_capability(capabilities):
    """True when {"recalibrate":...} answers calibrating / calibrated lines (capabilities.recalibration == 1)."""
    return _capability_one(capabilities, RECALIBRATION_CAPABILITY)


def haptic_parse(value):
    """The firmware's reading of a frame's `haptic` object (cc_frame_parse.cpp parse_haptic): (stored, ok).

    `stored` is {"fx": CCFx number, "seq": int}; `ok` False means the firmware rejects the whole frame (the strict
    rule): the token must be one of HAPTIC_TOKENS, the seq a JSON integer 1..0x7FFFFFFF (never a bool or a float).
    Unknown keys are ignored. harness/haptic_fx_tests.py holds both readings to one table."""
    if not isinstance(value, dict):
        return None, False
    token, seq = value.get("token"), value.get("seq")
    if not isinstance(token, str) or token not in HAPTIC_TOKENS or not _integer(seq, 1, _HAPTIC_SEQ_MAX):
        return None, False
    return {"fx": HAPTIC_TOKENS[token], "seq": seq}, True


def alive_capability(capabilities):
    """The negotiated `alive` capability (ALIVE.md section 1), or None.

    Only presentation >= 4 firmware whose `alive` object has "version": 1 (an int: True is
    not 1) negotiates it. Anything else (cc5.3 and older, or a malformed object) gets no
    section 3 field at all: its frame lines are byte-identical to what desktop v6 sent.
    """
    if presentation_level(capabilities) < presentation.PRESENTATION_V4:
        return None
    cap = (capabilities or {}).get(presentation.ALIVE_CAPABILITY)
    if not isinstance(cap, dict) or type(cap.get("version")) is not int or cap["version"] != presentation.ALIVE_VERSION:
        return None
    return deepcopy(cap)


def _alive_value(name, raw):
    """(valid, normalized) of one top-level ALIVE.md section 3 field, validated exactly as the
    1.0.0-cc5.4 parser (src/cc_frame_parse.cpp) validates it: ints are JSON integers (never a
    bool or a float) in range, bools are JSON booleans. There an invalid value rejects the
    frame; the host strips it (logged) and never sends it."""
    if name == "clock":
        return _integer(raw, 0, presentation.ALIVE_CLOCK_MAX), raw
    if name in ("playing", "ledDither"):
        return type(raw) is bool, raw
    if name == "ledDrive":
        return _integer(raw, presentation.ALIVE_LED_DRIVE_MIN, presentation.ALIVE_LED_DRIVE_MAX), raw
    if name == "progress":
        top = presentation.ALIVE_PROGRESS_MAX_MS
        valid = (isinstance(raw, dict) and _integer(raw.get("pos"), 0, top) and _integer(raw.get("dur"), 0, top)
                 and (raw["dur"] == 0 or raw["pos"] <= raw["dur"]))
        return valid, ({"pos": raw["pos"], "dur": raw["dur"]} if valid else None)  # extra keys dropped
    return False, None


def _alive_skip(raw):
    """feedback.skip: the JSON integer -1 or 1."""
    return type(raw) is int and raw in presentation.ALIVE_SKIP_VALUES


_HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")


def led_pink_value(raw):
    """settings.json `led_pink` as the wire `ledPink` (PRESENTATION_V5.md 7.3): an int
    0..0xFFFFFF, or a "#RRGGBB" string converted to that int. None when invalid (a bool, a
    float, another string, out of range)."""
    if isinstance(raw, str):
        return int(raw[1:], 16) if _HEX_COLOUR.fullmatch(raw) else None
    return raw if _integer(raw, 0, presentation.LED_PINK_MAX) else None


def alive_parse(frame):
    """ALIVE.md section 3 exactly as the 1.0.0-cc5.4 parser (src/cc_frame_parse.cpp) reads `frame`.

    Returns (stored, invalid). `stored` is what CCFrame holds for the section 3 fields:
    {"playing": -1|0|1, "feedbackSkip": -1|0|1, "clock": int|None, "progress": {"pos", "dur"}|None,
    "ledDrive": int|None, "ledDither": bool|None} (None: absent; the knob then uses its default,
    dither off with the F-T floor since the 2026-09-26 ruling, ALIVE.md 9 / 12.7).
    `invalid` names every present field ("feedback.skip" for the nested one) whose value makes
    the parser reject the frame. Values are validated first, on every layout and feedback kind;
    a valid `playing` outside the Home layouts (nowPlaying/volume/idle/notice, derived from
    `mode` when `layout` is absent) or a valid `feedback.skip` with a kind other than "ok" is
    then stripped, never a rejection. _frame() applies the same checks but strips (and logs)
    an invalid value instead of rejecting. The v4 fields are not examined here.
    The shared fixtures (tests/fixtures/frames_alive.json) hold both parsers to this.
    """
    stored = {"playing": -1, "feedbackSkip": 0, "clock": None, "progress": None, "ledDrive": None,
              "ledDither": None}
    invalid = []
    if not isinstance(frame, dict):
        return stored, invalid
    for name in (*presentation.ALIVE_CONTENT_FIELDS, *presentation.ALIVE_LATCHED_FIELDS):
        if name not in frame:
            continue
        valid, value = _alive_value(name, frame[name])
        if not valid:
            invalid.append(name)
        elif name == "playing":
            if _home(frame):
                stored["playing"] = int(value)
        else:
            stored[name] = value
    feedback = frame.get("feedback")
    if isinstance(feedback, dict) and "skip" in feedback:
        if not _alive_skip(feedback["skip"]):
            invalid.append("feedback.skip")
        elif feedback.get("kind") == "ok":
            stored["feedbackSkip"] = feedback["skip"]
    return stored, invalid


# ---------------------------------------------------------------------------
# {"diag":"?"} (P4 section 1; the `diag` capability stays 1). The fields the host reads: the
# twenty-four of PRESENTATION_V5.md 12.3 (VOC-K1c; 1.0.0-cc5.4), ALIVE.md 10.1's six LED fields
# (VOC section 6.1), and the memory figures of the 12.2 / 12.6 gates that older knobs report too.
# Every other diag field (reset attribution, task steps, the LED strips, ...) is not read.
DIAG_REQUEST = {"diag": "?"}
DIAG_LCD_FIELDS = ("lcdFps", "lcdFpsAnimMin", "lcdRefrUsMax", "lcdRefrUsAvg", "lcdRenderUsMax", "lcdFlushUs",
                   "lcdPxPerRefr", "lcdFullRefrs", "lcdLateRefrs", "lcdMaxGapMs", "lcdBusyPct", "core0IdlePct",
                   "lcdSpiHz", "enterMsLast", "enterMsMax", "holdEvents", "holdDeferred", "lcdDma", "lcdPeriodMs",
                   "artAsync", "artDecodeRequests", "artDecodeAborts", "artDecodeStale", "stackArtDec")
DIAG_LED_FIELDS = ("ledFps", "ledRenderUsMax", "ledRenderUsAvg", "ledMode", "ledShowGapMsMax", "ledLateShows")
DIAG_MEMORY_FIELDS = ("heapMinFree", "heapFree", "lvglFree", "lvglMinFree", "lcdAgeMs", "jpegDecodeMsMax",
                      "jpegDecodeMsLast")
# The fix binaries' fields (1.0.0-cc5.4 D and E, and 1.0.0-cc5.5): the LCD data line's output signal and the
# binary's letter ("build", a string "A".."F"; absent on an image without a ladder id). The same pair as the
# tooling's nanod_cc5_tooling.LCD_FIX_DIAG_FIELDS.
DIAG_BUILD_FIELDS = ("lcdMosiSig", "build")
# 1.0.0-cc5.5 (F1, safety and measurement; cc_diag.h): the FOC loop rate and its longest gap (µs, reset on
# read), the largest |Uq| (mV, reset on read), the time at the 2.2 V motor cap (ms since boot) and that cap
# (mV), the PD contract read once at boot (pdRead; pdPdo, the requested source PDO's position, 0 = none or
# unknown; pdVolts, that PDO's voltage from the knob's sink PDO table, 5 / 9, 0 = unknown; pdRdo, the raw
# RDO, only when the read worked), the USB interfaces TinyUSB accepted and the HID reports retried. The
# tooling's nanod_cc5_tooling.F1_DIAG_FIELDS.
DIAG_F1_FIELDS = ("focLoopHz", "focLoopUsMax", "uqAbsMax", "uqCapMs", "uqCapMv", "pdRead", "pdPdo", "pdVolts",
                  "pdRdo", "usbMidiOk", "usbHidOk", "hidRetries")
# 1.0.0-cc5.7 (r4 FEEL + SOUND; firmware cc_diag.h): the supply the driver scales with (5 / 9 V), the claim's feel,
# reduced haptics and sound level, the effect player's counters, the wall hits and their direction, the wall's
# fold-back (percent of force, events), the self-spin trip, the offline volume mode, recalibration and audio.
DIAG_R4_FIELDS = ("supplyVolts", "feel", "reducedHaptics", "soundLevel", "fxPlayed", "fxPulses", "fxDropped",
                  "wallHits", "wallDir", "foldbackPct", "foldbackEvents", "tripLatched", "spinTrips", "offlineVolume",
                  "calState", "calOutcome", "audioReady", "audioPlayed", "audioUnderruns", "audioDropped")
# knobVolume (Desk Dial 7.3.1): the speaker volume the claim sent (percent).
DIAG_VOLUME_FIELDS = ("soundVolume",)
DIAG_FIELDS = (DIAG_LCD_FIELDS + DIAG_LED_FIELDS + DIAG_MEMORY_FIELDS + DIAG_BUILD_FIELDS + DIAG_F1_FIELDS +
               DIAG_R4_FIELDS + DIAG_VOLUME_FIELDS)
DIAG_LED_MODES = ("offline", "alive", "native")          # cc_diag.cpp kLedModes (ALIVE.md 10.1)
_DIAG_BOOLS = frozenset(("lcdDma", "artAsync", "pdRead", "usbMidiOk", "usbHidOk",   # JSON booleans (cc_diag)
                         "reducedHaptics", "tripLatched", "offlineVolume", "audioReady"))
DIAG_CAL_STATES = ("idle", "running", "saving")
DIAG_CAL_OUTCOMES = ("", "ok", "init-failed", "pole-check-failed", "direction-changed", "save-timeout", "claimed")
_DIAG_PERCENT = frozenset(("lcdBusyPct", "core0IdlePct"))
_DIAG_UINT32 = 0xFFFFFFFF
# PRESENTATION_V5.md 12.6: the pipeline flags that identify the binary (the same table as the
# hardware-window tooling's nanod_cc5_tooling.LCD_BINARIES). A, B and C carry no "build" field and are
# told by their flags alone; D, E (1.0.0-cc5.4) and F (1.0.0-cc5.5: D's pipeline at a 12 ms period) name
# themselves in "build" and are accepted only with their own pipeline (D and F, like A, at any period).
DIAG_BINARIES = {"A": {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True},
                 "B": {"lcdDma": True, "lcdPeriodMs": 33, "artAsync": False},
                 "C": {"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False},
                 "D": {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True},
                 "E": {"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False},
                 "F": {"lcdDma": True, "lcdPeriodMs": 12, "artAsync": True}}
DIAG_LEGACY_BINARIES = ("A", "B", "C")                   # images without a "build" field


def _diag_value_ok(name, raw):
    if name in _DIAG_BOOLS:
        return type(raw) is bool
    if name == "ledMode":
        return isinstance(raw, str) and raw in DIAG_LED_MODES
    if name == "build":
        return isinstance(raw, str) and raw in DIAG_BINARIES
    if name in _DIAG_PERCENT:
        return _integer(raw, 0, 100)
    if name == "pdPdo":
        return _integer(raw, 0, 7)
    if name == "pdVolts":
        return _integer(raw, 0, 48)
    if name == "supplyVolts":
        return _integer(raw, 0, 48)
    if name == "feel":
        return isinstance(raw, str) and (raw == "" or raw in FEEL_TOKENS)
    if name == "soundLevel":
        return _integer(raw, 0, len(SOUND_LEVELS) - 1)
    if name == "soundVolume":
        return _integer(raw, 0, KNOB_VOLUME_MAX)
    if name == "wallDir":
        return type(raw) is int and raw in (-1, 0, 1)
    if name == "foldbackPct":
        return _integer(raw, 0, 100)
    if name == "calState":
        return isinstance(raw, str) and raw in DIAG_CAL_STATES
    if name == "calOutcome":
        return isinstance(raw, str) and raw in DIAG_CAL_OUTCOMES
    return _integer(raw, 0, _DIAG_UINT32)


def diag_parse(diag):
    """The typed read of a knob's `{"diag":{…}}` object (the value of the `diag` key).

    Returns (fields, invalid): `fields` maps each DIAG_FIELDS name present with a valid value to
    it (uint32 JSON integers, never bools or floats; the two percentages 0..100; `pdPdo` 0..7 and
    `pdVolts` 0..48; `lcdDma`, `artAsync`, `pdRead`, `usbMidiOk` and `usbHidOk` JSON booleans;
    `ledMode` one of DIAG_LED_MODES; `build` a DIAG_BINARIES letter); `invalid` names, in DIAG_FIELDS
    order, the present fields whose value is malformed (dropped, never raised, never echoed).
    Fields outside DIAG_FIELDS are ignored. A cc5.3 or older knob simply has none of the v5 ones, a
    cc5.4 knob none of the 1.0.0-cc5.5 DIAG_F1_FIELDS."""
    fields, invalid = {}, []
    if not isinstance(diag, dict):
        return fields, invalid
    for name in DIAG_FIELDS:
        if name not in diag:
            continue
        raw = diag[name]
        if _diag_value_ok(name, raw):
            fields[name] = raw
        else:
            invalid.append(name)
    return fields, invalid


def _diag_pipeline_matches(fields, name):
    """`fields` report binary `name`'s pipeline; a DMA + R5 pipeline (A, D, F) at any integer period (P5-R12)."""
    flags = DIAG_BINARIES[name]
    if all(fields.get(key) == value and type(fields.get(key)) is type(value) for key, value in flags.items()):
        return True
    return (flags["lcdDma"] and flags["artAsync"] and fields.get("lcdDma") is True and fields.get("artAsync") is True
            and type(fields.get("lcdPeriodMs")) is int)


def diag_binary(fields):
    """The PRESENTATION_V5.md 12.6 binary ("A".."F") a diag read identifies, else None (the same reading as the
    tooling's nanod_cc5_tooling.lcd_binary). A numbered image (D, E, F) names itself in `build`: that letter,
    accepted only with its own pipeline (`lcdDma` / `lcdPeriodMs` / `artAsync`), else None. An image without
    the field is A, B or C by its flags alone; binary A may run R4 at the measured scan period instead of
    16 ms (P5-R12): DMA and R5 at any integer period is A."""
    if not isinstance(fields, dict):
        return None
    if "build" in fields:
        build = fields.get("build")
        return build if build in DIAG_BINARIES and _diag_pipeline_matches(fields, build) else None
    for name in DIAG_LEGACY_BINARIES:
        if all(fields.get(key) == value and type(fields.get(key)) is type(value)
               for key, value in DIAG_BINARIES[name].items()):
            return name
    return next((name for name in DIAG_LEGACY_BINARIES if _diag_pipeline_matches(fields, name)), None)


def _local_minute():
    """Local minutes since midnight (ALIVE.md section 3 `clock`)."""
    now = time.localtime()
    return now.tm_hour * 60 + now.tm_min


def _valid_text(text):
    return isinstance(text, str) and not any(ord(c) < 0x20 for c in text)


def _device_text(text, capabilities, capacity):
    """Adapt text to the advertised glyphs, then truncate to the UTF-8 byte capacity.

    Below presentation 4 (or without a known glyph set) everything is ASCII,
    as the cc4 fonts require. With glyphs "latin-ext-a" only characters
    outside that set are transliterated.
    """
    if presentation_level(capabilities) >= presentation.PRESENTATION_V4 and (
            capabilities.get("glyphs") == "latin-ext-a"):
        text = unicodedata.normalize("NFC", text)
        text = _lcd_text(text, presentation.supported_glyph)
    else:
        text = _lcd_text(text)
    return presentation.utf8_truncate(text, capacity)


def _lights_big(frame):
    return frame.get("layout") == "lightsbig"


def _home(frame):
    mode = frame.get("mode")
    layout = frame.get("layout") or (presentation.LEGACY_LAYOUT.get(mode, "nowPlaying")
                                     if isinstance(mode, str) else "nowPlaying")
    return isinstance(layout, str) and layout in _HOME_LAYOUTS


def _layout_of(frame):
    """The layout a parser gives `frame`: a valid `layout` token, else the legacy one derived
    from `mode` (an invalid `layout` is stripped by the host, so the parser derives it too)."""
    layout = frame.get("layout")
    if isinstance(layout, str) and layout in presentation.LAYOUTS_V6:
        return layout
    mode = frame.get("mode")
    return presentation.LEGACY_LAYOUT.get(mode, "nowPlaying") if isinstance(mode, str) else "nowPlaying"


def _buttons(value, capabilities, v4):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("The device frame requires four button legends")
    result = []
    for slot, button in enumerate(value):
        if (not isinstance(button, dict) or not _valid_text(button.get("label"))
                or type(button.get("enabled")) is not bool):
            raise ValueError("Invalid button legend")
        out = {"label": _device_text(button["label"], capabilities, presentation.BUTTON_LABEL_CAPACITY),
               "enabled": button["enabled"]}
        for name, raw in button.items():
            if name in ("label", "enabled"):
                continue
            if name == "icon":
                if isinstance(raw, str) and raw in presentation.ICONS_V6:
                    out["icon"] = raw
                else:
                    _strip("button.icon", "invalid", "replaced by no icon" if v4 else "stripped")
            elif name == "color":
                if _integer(raw, 0, 0xFFFFFF):
                    out["color"] = raw
                else:
                    _strip("button.color", "invalid")
            elif name == "lit":
                # PRESENTATION_V5.md section 5.1: "on" | "off"; the presentation-4 downgrade drops it.
                if isinstance(raw, str) and raw in presentation.BUTTON_LIT:
                    out["lit"] = raw
                else:
                    _strip("button.lit", "invalid")
            else:
                _strip("button." + str(name), "unsupported")
        if v4:
            # Contract section 3: every v4 button carries an icon; "" means none
            # (tone none: LED off, footer hidden), exactly what a bad token implies.
            out.setdefault("icon", "")
        else:
            out.pop("lit", None)  # cc4: not a field of presentation 2/3
            if "color" not in out:
                # cc4 parsers require a colour; derive it from the tone rule.
                tone = presentation.button_tone(slot, out.get("icon", ""), out["enabled"])
                out["color"] = _LEGACY_BUTTON_COLORS.get(tone, _LEGACY_WHITE)
        result.append(out)
    return result


def _ring(value, v4, layout="nowPlaying", v5=False):
    """Validate the ring (required) and its optional fields.

    PRESENTATION_V5.md section 4: `lap` needs 1 <= count <= LAP_COUNT_MAX and index < count
    (else the frame is invalid, like a selection index past its count). `now` (an int in
    -1..count-1) and `card` (a bool; `true` needs count >= 2 and now == count - 2) are validated
    on every layout and kept only on a `selection` ring of layout `upnext`; a valid `unavailable`
    is dropped on layout `upnext` (P5-R24). An invalid value is stripped and logged, a valid one
    outside its scope is dropped silently (section 3.3). `v5` picks the window rule: the v5 host's
    clamp(index-10, 0, count-20), always sent when count > 20 (4.2, P5-R9); V4's clamp(index-9, ...)
    otherwise.
    """
    if (not isinstance(value, dict) or value.get("style") not in presentation.RING_STYLES_V6
            or not _integer(value.get("value"), 0, 100) or not _integer(value.get("index"), 0, 65535)
            or not _integer(value.get("count"), 0, 65535)):
        raise ValueError("Invalid ring frame")
    style, index, count = value["style"], value["index"], value["count"]
    if style in ("selection", "transport") and not index < count:
        raise ValueError("Selection ring index is outside its candidates")
    if style == "lap" and not (1 <= count <= presentation.LAP_COUNT_MAX and index < count):
        raise ValueError("Seek lap ring needs a duration of 1..59999 s and a target before its end")
    if style == "clusters" and not (1 <= count <= presentation.CLUSTERS_MAX and index < count):
        raise ValueError("Scene clusters need 1..20 scenes and a selection among them")
    if style == "marker" and not (1 <= count and index < count):
        raise ValueError("A marker ring needs 1.. entries and an index among them")
    if style == "queue" and not (1 <= count and index < count):
        raise ValueError("A queue ring needs 1.. rows and a focus among them")   # r3.1 (19.10)
    out = {"style": style, "value": value["value"], "index": index, "count": count}
    if "kelvin" in value:
        # Presentation 6: the colour temperature of a bri / ctemp arc; dropped silently elsewhere.
        if _integer(value["kelvin"], presentation.RING_KELVIN_MIN, presentation.RING_KELVIN_MAX):
            if style in ("bri", "ctemp"):
                out["kelvin"] = value["kelvin"]
        else:
            _strip("ring.kelvin", "invalid", "replaced by the default" if style in ("bri", "ctemp") else "stripped")
    if style in ("bri", "ctemp") and "kelvin" not in out:
        # The knob requires ring.kelvin on bri / ctemp (it rejects the frame without one).
        if "kelvin" not in value:
            _strip("ring.kelvin", "missing", "replaced by the default")
        out["kelvin"] = presentation.RING_KELVIN_DEFAULT
    for name in value:
        if (name not in out and name not in _V4_RING_FIELDS and name not in _V5_RING_FIELDS
                and name not in _V6_RING_FIELDS):
            _strip("ring." + str(name), "unsupported")  # includes the removed v2 `available` list
    if not v4:
        return out

    def in_window(first):
        # Section 4: 0 <= first <= index < first+20, and first is 0 when count <= 20.
        return (_integer(first, 0, 65535) and first <= index < first + presentation.RING_WINDOW
                and (count > presentation.RING_WINDOW or first == 0))

    # The host always sends a window that satisfies the rule: an absent or
    # invalid `first` is replaced by the host rule (V4: clamp(index-9, 0, count-20);
    # presentation 5: clamp(index-10, 0, count-20)).
    derived = presentation.window_first_v5(index, count) if v5 else presentation.window_first(index, count)
    if "first" in value and in_window(value["first"]):
        first, relative_valid = value["first"], True
    else:
        if "first" in value:
            _strip("ring.first", "outside the window rule", "replaced by the host window")
            relative_valid = False  # colors/unavailable were relative to the invalid first
        else:
            relative_valid = derived == 0  # they were relative to the implicit first 0
        first = derived
    if not in_window(first):
        # Only an off/level ring (index unused there) whose index lies past its
        # count; selection/transport/lap already require index < count.
        _strip("ring.index", "outside the window rule", "reset to 0")
        out["index"] = index = first = 0
    out["first"] = first
    window = max(0, min(presentation.RING_WINDOW, count - first))
    if "colors" in value:
        colors = value["colors"]
        if (relative_valid and isinstance(colors, list) and len(colors) <= window
                and all(_integer(c, 0, 0xFFFFFF) for c in colors)):
            out["colors"] = list(colors)
        else:
            _strip("ring.colors", "invalid" if relative_valid else "relative to another window")
    if "unavailable" in value:
        if relative_valid and _integer(value["unavailable"], 0, (1 << window) - 1):
            if layout != "upnext":  # Up next rows have no unavailable state (P5-R24): dropped silently
                out["unavailable"] = value["unavailable"]
        else:
            _strip("ring.unavailable", "invalid" if relative_valid else "relative to another window")
    if "moreIndex" in value:
        if _integer(value["moreIndex"], -1, count - 1):
            out["moreIndex"] = value["moreIndex"]
        else:
            _strip("ring.moreIndex", "invalid")
    if "external" in value:
        if type(value["external"]) is bool:
            out["external"] = value["external"]
        else:
            _strip("ring.external", "invalid")
    # Section 4.4: now / card, only on the Up next mirror's selection ring.
    upnext = style == "selection" and layout == "upnext"
    now = -1
    if "now" in value:
        if _integer(value["now"], -1, count - 1):
            now = value["now"]
            if upnext or style == "queue":   # r3.1: the queue ring's playing row
                out["now"] = now
        else:
            _strip("ring.now", "invalid")
    if "card" in value:
        card = value["card"]
        if type(card) is not bool:
            _strip("ring.card", "invalid")
        elif upnext:
            if card and not (count >= 2 and now == count - 2):
                _strip("ring.card", "not the entry after the now-playing row")  # the firmware rejects it
            else:
                out["card"] = card
    return out


def _optional(name, raw, capabilities):
    """Return (keep, normalized) for one optional top-level field."""
    if name in _OPTIONAL_TEXT:
        capacity = presentation.TEXT_CAPACITY[name]
        return (True, _device_text(raw, capabilities, capacity)) if _valid_text(raw) else (False, None)
    if name == "activity":
        return raw in presentation.ACTIVITIES, raw
    if name == "layout":
        return raw in presentation.LAYOUTS_V6, raw
    if name == "restLayout":
        return raw in presentation.REST_LAYOUTS, raw
    if name == "titleTone":
        return raw in presentation.TITLE_TONES, raw
    if name in ("metaTone", "statusTone"):
        return raw in presentation.LINE_TONES_V6, raw   # `warm`: presentation 6 (downgraded below)
    if name == "crumb":
        return isinstance(raw, str) and raw in presentation.CRUMBS, raw
    if name == "holdMarker":
        return type(raw) is bool, raw   # r3.1 (PRESENTATION_V5.md 19.10): button 4 has a hold action here
    if name == "valueUnit":
        return raw in presentation.VALUE_UNITS, raw
    if name in presentation.V6_TEXT_CAPACITY:
        capacity = presentation.V6_TEXT_CAPACITY[name]
        return (True, _device_text(raw, capabilities, capacity)) if _valid_text(raw) else (False, None)
    if name == "ledStyle":
        return raw in presentation.LED_STYLES, raw
    if name == "artKey":
        return isinstance(raw, str) and _ART_KEY.fullmatch(raw) is not None, raw
    if name == "iconKey":  # ARTWORK2.md section 6: validated exactly like artKey
        return isinstance(raw, str) and _ICON_KEY.fullmatch(raw) is not None, raw
    if name == "page":
        return _integer(raw, 0, 255), raw
    if name == "confirmedVolume":
        return _integer(raw, 0, 100), raw
    if name in ("artDim", "volumeVisible"):
        return type(raw) is bool, raw
    if name == "feedback":
        valid = (isinstance(raw, dict) and raw.get("kind") in ("ok", "err")
                 and _integer(raw.get("seq"), 1, 0x7FFFFFFF))
        return valid, ({"kind": raw["kind"], "seq": raw["seq"]} if valid else None)
    return False, None


def _v5_latched_value(name, raw):
    """(valid, value) of a presentation-5 latched field, validated as the cc5.4 parser does:
    reducedMotion and ledVolFull are JSON bools, ledPink a JSON int 0..0xFFFFFF (never a bool,
    float or string; PRESENTATION_V5.md sections 7.1 and 7.3)."""
    if name == "ledPink":
        return _integer(raw, 0, presentation.LED_PINK_MAX), raw
    if name in ("reducedMotion", "ledVolFull"):
        return type(raw) is bool, raw
    return False, None


def _feedback_v5(feedback, raw):
    """PRESENTATION_V5.md section 6.2 on the host: `moment`, `side`, `color` of the validated
    `feedback` ({kind, seq[, skip]}) from the submitted object `raw`, in place.

    An invalid token or value is stripped and logged (the firmware rejects the frame). With kind
    "ok": a kept `skip` next to a `moment` strips the moment (and its side and colour) and logs, a
    `snap` without a valid `side` strips the moment and logs. Then, silently: `moment` only with
    "ok", `side` only with a kept `snap`, `color` only with a kept `snap` or `started`."""
    moment = side = color = None
    if "moment" in raw:
        if isinstance(raw["moment"], str) and raw["moment"] in presentation.FEEDBACK_MOMENTS_V6:
            moment = raw["moment"]
        else:
            _strip("feedback.moment", "invalid")
    if "side" in raw:
        if type(raw["side"]) is int and raw["side"] in presentation.FEEDBACK_SIDES:
            side = raw["side"]
        else:
            _strip("feedback.side", "invalid")
    if "color" in raw:
        if _integer(raw["color"], 0, 0xFFFFFF):
            color = raw["color"]
        else:
            _strip("feedback.color", "invalid")
    if moment == "refused":
        # Presentation 6: the unavailable-press flash, with kind "err" only (dropped silently otherwise;
        # a presentation-5 knob never gets it: _downgrade_v6).
        if feedback["kind"] == "err":
            feedback["moment"] = moment
        return
    if feedback["kind"] != "ok" or moment is None:
        return
    if "skip" in feedback:
        _strip("feedback.moment", "sent with feedback.skip")
        return
    if moment == "snap" and side is None:
        _strip("feedback.moment", "snap without a side")
        return
    feedback["moment"] = moment
    if moment == "snap":
        feedback["side"] = side
    if color is not None and moment in presentation.FEEDBACK_COLOR_MOMENTS:
        feedback["color"] = color


def _downgrade(frame, v4=True):
    """PRESENTATION_V5.md section 2.2: a validated v5 frame as a presentation-4 (or older) knob
    must receive it, in place. Every row is mandatory: a V4 parser rejects unknown layout, style
    and icon tokens, and a rejected frame is fatal on the host.

    seek -> tracks (title = the m:ss of a lap ring's target, subtitle = the song, ring = the
    position row's centre dot); explorer -> recent page 1 + tab; upnext -> recent page 1; a lap
    ring elsewhere -> off; ring now/card and button lit dropped; the nine v5 icons mapped; an
    `unlike` feedback omitted, any other moment (with its side and colour) dropped. The latched
    v5 and tuning fields never reach this point for such a knob (_frame skips them)."""
    layout, ring = frame.get("layout"), frame["ring"]
    if layout == "seek":
        frame["layout"] = "tracks"
        song = frame.get("title", "")
        # The knob draws the time only from a lap ring (section 4.3); otherwise it shows none.
        frame["title"] = presentation.mmss(ring["index"]) if ring["style"] == "lap" else ""
        frame["subtitle"] = song
        frame["ring"] = ring = dict(presentation.SEEK_DOWNGRADE_RING)
    elif layout == "explorer":
        frame["layout"] = "recent"
        if v4:  # below presentation 4 `page` is not a field (V4 section 2)
            frame["page"] = min(255, 1 + frame.get("page", 0))
    elif layout == "upnext":
        frame["layout"] = "recent"
        if v4:
            frame["page"] = 1
    if ring["style"] == "lap":
        frame["ring"] = ring = dict(presentation.LAP_DOWNGRADE_RING)
    for name in _V5_RING_FIELDS:
        ring.pop(name, None)
    for button in frame["buttons"]:
        button.pop("lit", None)
        if button.get("icon") in presentation.ICON_DOWNGRADE:
            button["icon"] = presentation.ICON_DOWNGRADE[button["icon"]]
    feedback = frame.get("feedback")
    if feedback is not None:
        if feedback.get("moment") == "unlike":
            del frame["feedback"]  # r2.1 plays nothing for an unlike (P5-R16)
        else:
            for name in ("moment", "side", "color"):
                feedback.pop(name, None)
    return frame


def _downgrade_v6(frame):
    """A validated presentation-6 frame for a presentation-5 (or older) knob, in place: the r3 Lights
    layouts become `recent`, their rings `off`, the six r3 icons their nearest v5 token;
    `valueUnit`, `prevTitle`, `nextTitle` and `ring.kelvin` are dropped. The
    controller never builds these for such a knob (r3 needs presentation >= 6); this keeps a stray one
    from being rejected (a rejected frame is fatal on the host)."""
    if frame.get("layout") in presentation.LAYOUT_DOWNGRADE_V6:
        frame["layout"] = presentation.LAYOUT_DOWNGRADE_V6[frame["layout"]]
    ring = frame.get("ring")
    if isinstance(ring, dict):
        if ring.get("style") in presentation.LIGHTS_RING_STYLES:
            frame["ring"] = ring = dict(presentation.LIGHTS_DOWNGRADE_RING)
        elif ring.get("style") == "marker":
            ring["style"] = "selection"   # the same index / count, warm (no colours)
        elif ring.get("style") == "queue":
            ring["style"] = "selection"   # r3.1: the same focus / count / window
            ring.pop("now", None)
        ring.pop("kelvin", None)
    for name in ("metaTone", "statusTone"):
        if frame.get(name) == "warm":
            frame[name] = "secondary"
    feedback = frame.get("feedback")
    if isinstance(feedback, dict) and feedback.get("moment") == "refused":
        del feedback["moment"]
    for button in frame.get("buttons") or ():
        if button.get("icon") in presentation.ICON_DOWNGRADE_V6:
            button["icon"] = presentation.ICON_DOWNGRADE_V6[button["icon"]]
    for name in presentation.V6_FIELDS:
        frame.pop(name, None)
    return frame


def _slim(frame, v5=False):
    """Section 8 (V4) / PRESENTATION_V5.md section 14.2: omit defaults and legacy fields for
    presentation >= 4."""
    for name, default in _TONE_DEFAULTS.items():
        if frame.get(name) == default:
            del frame[name]
    for name, default in (("artDim", False), ("page", 0), ("heading", ""), ("meta", ""), ("artKey", ""),
                          ("iconKey", "")):
        if name in frame and frame[name] == default and type(frame[name]) is type(default):
            del frame[name]
    frame.pop("counter", None)
    if not _home(frame):
        for name in ("volumeCaption", "confirmedVolume", "restLayout", "volumeVisible"):
            if name == "volumeCaption" and _lights_big(frame):
                continue   # presentation 6: the lightsbig caption (`Brightness` / `Colour temperature`)
            frame.pop(name, None)
    for button in frame["buttons"]:
        # V4 strips every button colour; presentation 5 keeps the one that means something: an
        # assigned snap side's raw colour (lit "on", colour != 0, not the heart: PINK is the knob's).
        if not (v5 and button.get("lit") == "on" and button.get("icon") != "heart" and button.get("color", 0)):
            button.pop("color", None)
    ring = frame["ring"]
    # P4 section 8 slims only a `first` of 0, and only where every parser derives the same 0 for
    # an absent `first` (V4's clamp(index-9, 0, count-20), rules.absentFirst). A v5-rule window
    # sent to a presentation-4 knob can start at 0 where V4 derives 1 (index 10, count > 20): it
    # keeps its explicit 0, or the colours and mask (relative to 0) would be dropped (section 4.2).
    # Presentation 5 always sends `first` when count > 20 (P5-R9).
    if (ring.get("first") == 0 and presentation.window_first(ring["index"], ring["count"]) == 0
            and (not v5 or ring["count"] <= presentation.RING_WINDOW)):
        del ring["first"]
    for name, default in (("unavailable", 0), ("moreIndex", -1), ("external", False), ("now", -1),
                          ("card", False)):
        if name in ring and ring[name] == default and type(ring[name]) is type(default):
            del ring[name]
    if "colors" in ring and (frame.get("ledStyle") != "color" or ring["style"] != "selection"):
        del ring["colors"]
    feedback = frame.get("feedback")
    if feedback is not None and feedback.get("color") == 0:
        del feedback["color"]  # 0 = warm, the default
    return frame


def frame_line_bytes(frame):
    """Encoded size of the `{"frame":…}` line, counting a maximal id when absent."""
    message = {"frame": {**frame, "id": frame.get("id", 0x7FFFFFFF)}}
    return len(json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
               .encode("utf-8")) + 1


def _escaped_bytes(text):
    """Bytes `text` occupies inside the JSON line: escapes counted, quotes not."""
    return len(json.dumps(text, ensure_ascii=False, allow_nan=False)[1:-1].encode("utf-8"))


def _shrink(frame, excess):
    """Drop trailing code points from the longest drawn outside text until `excess`
    line bytes are gone (or nothing is left to shorten). Returns what remains over.

    JSON escaping is per character, so removing one code point shortens the line by
    exactly that character's escaped size.
    """
    sizes = {name: _escaped_bytes(frame[name]) for name in _BUDGET_SHRINK
             if isinstance(frame.get(name), str) and frame[name]}
    shortened = []
    while excess > 0 and sizes:
        name = max(sizes, key=sizes.get)  # first in _BUDGET_SHRINK order on a tie
        text = frame[name]
        removed = _escaped_bytes(text[-1])
        frame[name] = text[:-1]
        sizes[name] -= removed
        excess -= removed
        if not frame[name]:
            del sizes[name]
        if name not in shortened:
            shortened.append(name)
    for name in shortened:
        _strip(name, "frame size budget", "shortened")
    return excess


def frame_budget(capabilities):
    """(budget bytes, latched reserve) for a frame line to this knob.

    Presentation 4: V4's 1,100 B, reserving ALIVE's worst latched values on an alive knob.
    Presentation 5 (PRESENTATION_V5.md section 14.1): 1,400 B, reserving `reducedMotion` and, with
    `alive`, ALIVE's worst latched values plus the two tuning fields (the 148 B latched reserve)."""
    alive = alive_capability(capabilities) is not None
    if presentation_level(capabilities) >= presentation.PRESENTATION_V5:
        reserve = dict(presentation.V5_LATCHED_WORST)
        if alive:
            reserve.update(presentation.ALIVE_LATCHED_WORST)
            reserve.update(presentation.ALIVE_TUNING_WORST)
        return presentation.FRAME_BUDGET_BYTES_V5, reserve
    return presentation.FRAME_BUDGET_BYTES, (dict(presentation.ALIVE_LATCHED_WORST) if alive else None)


def _budget(frame, reserve=None, limit=None):
    """Section 8 budget: empty legacy text v4 renderers ignore, only when needed.

    The budget counts the encoded line, JSON escapes included: a title or app name
    made of quotes or backslashes takes twice its UTF-8 bytes on the wire. When the
    legacy trim is not enough, drawn outside text is shortened as a last resort.
    `reserve` (fields merged in for the size only) holds room for what the bridge adds
    at send time: on an alive knob the longest value of every latched field (ALIVE.md
    section 3), so the line still fits with all of them present. `limit` is the budget
    (presentation.FRAME_BUDGET_BYTES by default; FRAME_BUDGET_BYTES_V5 for presentation 5).
    """
    limit = presentation.FRAME_BUDGET_BYTES if limit is None else limit

    def size():
        return frame_line_bytes({**frame, **reserve} if reserve else frame)
    home = _home(frame) or _lights_big(frame)   # both draw `value` as the big digits
    for name in _BUDGET_TRIM:
        if size() <= limit:
            return frame
        if home and name in _BUDGET_HOME_KEPT:
            continue  # the Home volume digits are drawn
        if frame.get(name):
            frame[name] = ""
            _strip(name, "frame size budget", "emptied")
    excess = size() - limit
    if excess > 0 and _shrink(frame, excess) > 0:
        _strip("frame", "over the size budget", "sent")  # soft: the line limit is 4096 B
    return frame


def _frame(value, capabilities=None):
    """Validate and adapt one frame for the connected firmware's capabilities.

    Output key order follows the input. Text is transliterated for the
    advertised glyph set and truncated at a code point within the contract's
    UTF-8 byte capacity. Below presentation 4 every v4-only field is stripped,
    `notice` becomes `nowPlaying` and each button keeps a colour.

    ALIVE.md section 3 (`playing`, `feedback.skip`, `clock`, `progress`, `ledDrive`,
    `ledDither`) is kept only with `alive` negotiated (alive_capability); otherwise those
    fields are dropped silently and the result is exactly what desktop v6 produced. With
    `alive` an invalid value is stripped and logged (the firmware would reject the frame),
    a valid `playing` outside the Home layouts and a valid `feedback.skip` with a kind
    other than "ok" are dropped silently (alive_parse() is the parser's reading), and the
    section 8 budget reserves room for the latched fields the bridge adds at send time.

    PRESENTATION_V5.md (desktop v7): the controller builds v5 frames. Every value is validated
    as v5 content first (section 3.3: invalid -> stripped and logged, a valid value outside its
    scope -> dropped silently; v5_parse() is the cc5.4 parser's reading). A presentation-5 knob
    then gets the v5 fields, `reducedMotion` and, with `alive`, `ledPink` / `ledVolFull`, the
    section 14.2 slimming and the 1,400 B budget (frame_budget). Any older knob gets the
    mandatory section 2.2 downgrade (_downgrade) and, for presentation 4, V4's slimming and
    budget: for an input without v5 content its output is exactly desktop v6's.
    """
    if not isinstance(value, dict):
        raise ValueError("A complete device frame is required")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    level = presentation_level(capabilities)
    v4 = level >= presentation.PRESENTATION_V4
    v5 = level >= presentation.PRESENTATION_V5
    v6 = level >= presentation.PRESENTATION_V6
    alive = alive_capability(capabilities) is not None  # implies v4
    layout = _layout_of(value)  # scope of the ring's now / card / unavailable (section 4.4)
    result = {}
    for name, raw in value.items():
        if name == "id":
            if not _integer(raw, 1, 0x7FFFFFFF):
                raise ValueError("Invalid frame id")
            result[name] = raw
        elif name in _REQUIRED_TEXT:
            if not _valid_text(raw):
                raise ValueError(f"Invalid frame {name}")
            result[name] = _device_text(raw, capabilities, presentation.TEXT_CAPACITY[name])
        elif name == "buttons":
            result[name] = _buttons(raw, capabilities, v4)
        elif name == "ring":
            result[name] = _ring(raw, v4, layout, v5)
        elif name in _ALIVE_FIELDS:
            if not alive:
                continue  # cc5.3 and older: never sent, and not an error
            valid, normalized = _alive_value(name, raw)
            if valid:
                result[name] = normalized
            else:
                _strip(name, "invalid")
        elif name in _V5_FIELDS or name in _TUNING_FIELDS:
            # reducedMotion: presentation 5; ledPink / ledVolFull: presentation 5 and alive.
            if not v5 or (name in _TUNING_FIELDS and not alive):
                continue  # never sent to such a knob, and not an error
            valid, normalized = _v5_latched_value(name, raw)
            if valid:
                result[name] = normalized
            else:
                _strip(name, "invalid")
        elif name == "haptic":
            # r4: only for a knob that plays it (hapticFx); older firmware never sees it, silently.
            if not haptic_capability(capabilities):
                continue
            if haptic_parse(raw)[1]:
                result[name] = {"token": raw["token"], "seq": raw["seq"]}
            else:
                _strip(name, "invalid")
        elif name == "app":
            # A2: only for a knob that draws it (appCanvas); older firmware keeps A0's text frame, silently.
            if not app_capability(capabilities):
                continue
            if not app_parse(raw)[1]:
                _strip(name, "invalid")
            elif app_profiles_capability(capabilities) is not None:
                result[name] = deepcopy(raw)
            else:
                # App profiles: a knob without appProfiles never receives the new fields (a profile id, crc, slot,
                # index past 15, axis / plane); a legacy Onshape object passes as before.
                legacy = _legacy_app(raw)
                if legacy is not None:
                    result[name] = legacy
                else:
                    _strip(name, "needs appProfiles")
        elif name in _V4_FIELDS and not v4:
            continue  # Legacy firmware: v4-only presentation is not an error.
        elif name in _V6_FIELDS and not v6:
            continue  # presentation 5 and older: the r3 fields are never sent, and not an error
        elif name in _KNOWN_FIELDS:
            keep, normalized = _optional(name, raw, capabilities)
            if keep:
                result[name] = normalized
            else:
                _strip(name, "invalid")
        else:
            _strip(str(name), "unsupported")
    for name in (*_REQUIRED_TEXT, "buttons", "ring"):
        if name not in result:
            if name == "buttons":
                raise ValueError("The device frame requires four button legends")
            if name == "ring":
                raise ValueError("Invalid ring frame")
            raise ValueError(f"Invalid frame {name}")
    feedback = value.get("feedback")
    if alive:
        if "playing" in result and not _home(result):
            del result["playing"]  # Home layouts only (ALIVE.md section 3): dropped silently
        if "feedback" in result and isinstance(feedback, dict) and "skip" in feedback:
            if not _alive_skip(feedback["skip"]):
                _strip("feedback.skip", "invalid")
            elif result["feedback"]["kind"] == "ok":
                result["feedback"]["skip"] = feedback["skip"]
            # A valid skip with another kind is dropped silently (section 3).
    if "feedback" in result and isinstance(feedback, dict):
        _feedback_v5(result["feedback"], feedback)
    if "iconKey" in result:
        # ARTWORK2.md section 6: only with artwork2 negotiated and only on the Windows
        # layout (derived from mode when absent). Not an error otherwise: dropped silently.
        layout = result.get("layout") or presentation.LEGACY_LAYOUT.get(result.get("mode"), "nowPlaying")
        if layout != "windows" or artwork2_capability(capabilities) is None:
            del result["iconKey"]
    if not v6:
        _downgrade_v6(result)
    if not v5:
        _downgrade(result, v4)
    if not v4:
        if result.get("layout") == "notice":
            result["layout"] = "nowPlaying"
        if result.get("artKey") and _artwork_capability(capabilities) is None:
            result["artKey"] = ""  # What a v2 companion always sent to firmware without art.
        return result
    limit, reserve = frame_budget(capabilities)
    return _budget(_slim(result, v5), reserve, limit)


def _v5_token(raw, tokens):
    return isinstance(raw, str) and raw in tokens


def v5_parse(frame):
    """PRESENTATION_V5.md exactly as the 1.0.0-cc5.4 parser (src/cc_frame_parse.cpp) reads `frame`.

    Returns (stored, invalid). `invalid` names every present value that makes the parser reject
    the frame (every field is examined, required ones included: "mode", "buttons", "button.lit",
    "ring", "ring.now", "ring.card", "feedback.moment", "reducedMotion", "ledPink", ...); the frame
    is accepted exactly when it is empty. `stored` is what CCFrame then holds (section 15.1):
    {layout, page, ringStyle, ringIndex, ringCount, ringFirst, ringNow, ringCard, ringUnavailable,
    lit[4] ("on" | "off" | None), color[4], icon[4], feedbackKind (None: no feedback),
    feedbackMoment (None: none), feedbackSide, feedbackColor, feedbackSkip, reducedMotion,
    ledPink, ledVolFull (None: absent)}. Values are validated first on every layout and feedback
    kind (section 3.3 rule 5); a valid value outside its scope is then stripped: `now` / `card`
    outside a selection ring on `upnext`, `unavailable` on `upnext`, `moment` without kind "ok",
    `side` without a stored `snap`, `color` without a stored `snap` / `started`. With kind "ok",
    `skip` and `moment` together, or `snap` without `side`, reject; so does `card:true` on the Up
    next mirror unless count >= 2 and now == count - 2. _frame() applies the same checks but
    strips (and logs) instead of rejecting. tests/fixtures/frames_v5.json holds both parsers to it.
    """
    stored = {"layout": "nowPlaying", "page": 0, "ringStyle": None, "ringIndex": 0, "ringCount": 0,
              "ringFirst": 0, "ringNow": -1, "ringCard": False, "ringUnavailable": 0,
              "lit": [None] * 4, "color": [0] * 4, "icon": [""] * 4,
              "feedbackKind": None, "feedbackMoment": None, "feedbackSide": 0, "feedbackColor": 0,
              "feedbackSkip": 0, "reducedMotion": None, "ledPink": None, "ledVolFull": None}
    if not isinstance(frame, dict):
        return stored, ["frame"]
    invalid = []
    if "id" in frame and not _integer(frame["id"], 1, 0x7FFFFFFF):
        invalid.append("id")
    for name in _REQUIRED_TEXT:
        if not _valid_text(frame.get(name)):
            invalid.append(name)
    for name in _OPTIONAL_TEXT:
        if name in frame and not _valid_text(frame[name]):
            invalid.append(name)
    if "artKey" in frame and not (isinstance(frame["artKey"], str) and _ART_KEY.fullmatch(frame["artKey"])):
        invalid.append("artKey")
    for name, tokens in (("activity", presentation.ACTIVITIES), ("restLayout", presentation.REST_LAYOUTS),
                         ("titleTone", presentation.TITLE_TONES), ("metaTone", presentation.LINE_TONES),
                         ("statusTone", presentation.LINE_TONES), ("ledStyle", presentation.LED_STYLES)):
        if name in frame and not _v5_token(frame[name], tokens):
            invalid.append(name)
    if "layout" in frame:
        if _v5_token(frame["layout"], presentation.LAYOUTS):
            stored["layout"] = frame["layout"]
        else:
            invalid.append("layout")
    elif isinstance(frame.get("mode"), str):
        stored["layout"] = presentation.LEGACY_LAYOUT.get(frame["mode"], "nowPlaying")
    layout = stored["layout"]
    # iconKey never rejects (ARTWORK2.md section 6). ALIVE.md section 3 (alive_parse's reading).
    for name in (*presentation.ALIVE_CONTENT_FIELDS, *presentation.ALIVE_LATCHED_FIELDS):
        if name in frame and not _alive_value(name, frame[name])[0]:
            invalid.append(name)
    for name in (*presentation.V5_LATCHED_FIELDS, *presentation.ALIVE_TUNING_FIELDS):
        if name in frame:
            valid, raw = _v5_latched_value(name, frame[name])
            if valid:
                stored[name] = raw
            else:
                invalid.append(name)
    if "page" in frame:
        if _integer(frame["page"], 0, 255):
            stored["page"] = frame["page"]
        else:
            invalid.append("page")
    for name in ("artDim", "volumeVisible"):
        if name in frame and type(frame[name]) is not bool:
            invalid.append(name)
    if "feedback" in frame:
        feedback = frame["feedback"]
        if (not isinstance(feedback, dict) or feedback.get("kind") not in ("ok", "err")
                or not _integer(feedback.get("seq"), 1, 0x7FFFFFFF)):
            invalid.append("feedback")
        else:
            ok = feedback["kind"] == "ok"
            stored["feedbackKind"] = feedback["kind"]
            if "skip" in feedback:
                if not _alive_skip(feedback["skip"]):
                    invalid.append("feedback.skip")
                elif ok:
                    stored["feedbackSkip"] = feedback["skip"]
            moment = feedback.get("moment")
            if "moment" in feedback and not _v5_token(moment, presentation.FEEDBACK_MOMENTS):
                invalid.append("feedback.moment")
            if "side" in feedback and not (type(feedback["side"]) is int
                                           and feedback["side"] in presentation.FEEDBACK_SIDES):
                invalid.append("feedback.side")
            if "color" in feedback and not _integer(feedback["color"], 0, 0xFFFFFF):
                invalid.append("feedback.color")
            if ok and "skip" in feedback and "moment" in feedback:
                invalid.append("feedback.moment")      # section 6.2 rule 2
            if ok and moment == "snap" and "side" not in feedback:
                invalid.append("feedback.side")        # section 6.2 rule 2
            if ok and _v5_token(moment, presentation.FEEDBACK_MOMENTS):
                stored["feedbackMoment"] = moment
                if moment == "snap" and "side" in feedback:
                    stored["feedbackSide"] = feedback["side"]
                if moment in presentation.FEEDBACK_COLOR_MOMENTS and "color" in feedback:
                    stored["feedbackColor"] = feedback["color"]
    buttons = frame.get("buttons")
    if not isinstance(buttons, list) or len(buttons) != 4:
        invalid.append("buttons")
    else:
        for slot, button in enumerate(buttons):
            if (not isinstance(button, dict) or not _valid_text(button.get("label"))
                    or type(button.get("enabled")) is not bool):
                invalid.append("buttons")
                continue
            if "icon" in button:
                if _v5_token(button["icon"], presentation.ICONS):
                    stored["icon"][slot] = button["icon"]
                else:
                    invalid.append("button.icon")
            if "color" in button:
                if _integer(button["color"], 0, 0xFFFFFF):
                    stored["color"][slot] = button["color"]
                else:
                    invalid.append("button.color")
            if "lit" in button:
                if _v5_token(button["lit"], presentation.BUTTON_LIT):
                    stored["lit"][slot] = button["lit"]
                else:
                    invalid.append("button.lit")
    _v5_parse_ring(frame.get("ring"), layout, stored, invalid)
    if "confirmedVolume" in frame and not _integer(frame["confirmedVolume"], 0, 100):
        invalid.append("confirmedVolume")
    return stored, invalid


def _v5_parse_ring(ring, layout, stored, invalid):
    """v5_parse's ring: P4 section 4 plus PRESENTATION_V5.md sections 4.3-4.5."""
    if (not isinstance(ring, dict) or not _v5_token(ring.get("style"), presentation.RING_STYLES)
            or not _integer(ring.get("value"), 0, 100) or not _integer(ring.get("index"), 0, 65535)
            or not _integer(ring.get("count"), 0, 65535)):
        invalid.append("ring")
        return
    style, index, count = ring["style"], ring["index"], ring["count"]
    if style in ("selection", "transport") and index >= count:
        invalid.append("ring")
        return
    if style == "lap" and not (1 <= count <= presentation.LAP_COUNT_MAX and index < count):
        invalid.append("ring")
        return
    stored.update(ringStyle=style, ringIndex=index, ringCount=count)
    relative = True
    if "first" in ring:
        first = ring["first"]
        if (not _integer(first, 0, 65535) or first > index or index >= first + presentation.RING_WINDOW
                or (count <= presentation.RING_WINDOW and first != 0)):
            invalid.append("ring.first")
            return
    else:
        first = presentation.window_first(index, count)   # the parser's derivation (rules.absentFirst)
        relative = first == 0
    stored["ringFirst"] = first
    window = max(0, min(presentation.RING_WINDOW, count - first))
    if relative and "colors" in ring:
        colors = ring["colors"]
        if (not isinstance(colors, list) or len(colors) > window
                or not all(_integer(c, 0, 0xFFFFFF) for c in colors)):
            invalid.append("ring.colors")
    if relative and "unavailable" in ring:
        if _integer(ring["unavailable"], 0, (1 << window) - 1):
            stored["ringUnavailable"] = 0 if layout == "upnext" else ring["unavailable"]
        else:
            invalid.append("ring.unavailable")
    if "moreIndex" in ring and not _integer(ring["moreIndex"], -1, count - 1):
        invalid.append("ring.moreIndex")
    if "external" in ring and type(ring["external"]) is not bool:
        invalid.append("ring.external")
    upnext = style == "selection" and layout == "upnext"
    now = -1
    if "now" in ring:
        if _integer(ring["now"], -1, count - 1):
            now = ring["now"]
            if upnext:
                stored["ringNow"] = now
        else:
            invalid.append("ring.now")
            return
    if "card" in ring:
        if type(ring["card"]) is not bool:
            invalid.append("ring.card")
        elif upnext:
            if ring["card"] and not (count >= 2 and now == count - 2):
                invalid.append("ring.card")
            else:
                stored["ringCard"] = ring["card"]


_NO_MEDIA_STATUS = {"wanted": 0, "present": 0, "uploads": 0, "hits": 0, "errors": 0, "failedKeys": [],
                    "lastError": "", "dropped": 0}


class _MediaKind:
    """Push-engine state of one media kind (ARTWORK2.md section 9), bridge thread only.

    The mirror follows the knob's LRU store (section 4.4). The knob evicts a slot only
    at a miss `begin`, when all S = entries + 1 slots are valid and it is the least
    recently touched unpinned one (at most 2 pins): so at least entries - 2 other keys
    were touched after it. The engine records every touch the knob may have made
    (`touched`: have true, begin hit, commit, frame adoption, and timed-out or
    bare-error-mapped lines that may have been handled) and, per mirror key, the tick
    when the line that confirmed it was written (the earliest the knob can have touched
    it); touches after the oldest line still outstanding are kept for its reply. A key
    leaves the mirror once `capacity` = entries - 3 other keys may have been touched since (one key of
    margin for the LCD adopting a frame's key after the host recorded it), so the
    mirror never lists a key the knob has evicted. A forgotten key that is still wanted
    is re-checked by the next `have`, and a `have` that finds a listed key missing
    re-checks the whole list. The wanted list (entries - 4) always fits.
    """
    PINS = 2        # displayed and the frame key's slot
    ADOPT_LAG = 1   # frame adoption the LCD makes later than the host recorded it

    def __init__(self, kind, capability):
        entries = capability[kind]["entries"]
        self.kind = kind
        self.limit = max(0, entries - presentation.MEDIA_WANTED_RESERVE)
        self.capacity = max(1, entries - self.PINS - self.ADOPT_LAG)
        self.wanted = []        # [(key, payload)] in priority order; index 0 is what the knob shows
        self.payloads = {}      # key -> payload of the wanted list
        self.mirror = {}        # key believed present -> tick it was confirmed since, in confirmation order
        self.touched = {}       # key -> tick of its latest (possible) touch on the knob
        self.known = set()      # keys whose presence this connection has learned, either way
        self.failures = {}      # key -> 1 while its single retry is pending
        self.retry_at = {}      # key -> clock time of that retry
        self.failed = set()     # failed twice: not retried until reconnect or it re-enters the list
        self.probe = False      # a `have` query is due
        self.probe_head = None  # index-0 key of the last `have` sent
        self.dropped = 0        # items over the entries-4 cap in the latest list
        self.uploads = self.hits = self.errors = 0
        self.last_error = ""

    def position(self, key):
        for index, (wanted, _payload) in enumerate(self.wanted):
            if wanted == key:
                return index
        return None

    def touch(self, key, tick, since=None):
        """The knob touched, or may have touched, `key` by `tick`. With `since` (the tick
        its line was written) the knob is known to hold it."""
        self.touched[key] = tick
        if since is not None:
            self.mirror.pop(key, None)
            self.mirror[key] = since
            self.known.add(key)

    def forget(self, key):
        self.mirror.pop(key, None)
        self.known.discard(key)

    def trim(self, floor=None):
        """Forget every key that `capacity` other keys may have been touched after.

        `floor` is the oldest tick of a media line still outstanding (None when there is
        none): its reply confirms keys since that tick, so touches after it still count.
        """
        ticks = sorted(self.touched.values())
        for key, since in list(self.mirror.items()):
            newer = len(ticks) - bisect.bisect_right(ticks, since) - (self.touched.get(key, since) > since)
            if newer >= self.capacity:
                self.forget(key)
                if key in self.payloads:
                    self.probe = True  # still wanted: the next `have` re-checks it
        # A touch no newer than every confirmation, present or still to come, never counts again.
        sinces = list(self.mirror.values())
        if floor is not None:
            sinces.append(floor)
        oldest = min(sinces, default=None)
        self.touched = {} if oldest is None else {k: t for k, t in self.touched.items() if t > oldest}

    def status(self):
        return {"wanted": len(self.wanted), "present": len(self.mirror), "uploads": self.uploads,
                "hits": self.hits, "errors": self.errors, "failedKeys": sorted(self.failed),
                "lastError": self.last_error, "dropped": self.dropped}


class ControlRefused(ValueError):
    """DD-BUG-004: _enter refused the control payload itself (a profile missing from this knob's inventory, or
    malformed fields). Sending the same control again, or reconnecting, cannot fix it, so the bridge marks the
    `error` event retry=False (with the missing profile's name when that is the cause). The event keeps
    error="ValueError" so existing consumers see the same name."""

    error_name = "ValueError"

    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


class DeviceBridge:
    """Daemon worker API: submit(connect/enter/frame/disconnect/close, value).

    Events contain kind plus data. Inputs are accepted only after matching ready;
    absolute positions and deltas are never capped or replayed across controls.

    artwork2 (ARTWORK2.md, 1.0.0-cc5.3): after `capabilities` the bridge parses
    `artwork2`. When it is negotiated, `media_capability` is that capability (a
    dict), every line is written whole (no 64 B / 5 ms pacing), v1 `art` lines are
    never sent, and set_media_wanted() feeds a stop-and-wait `media` push engine
    that emits {"kind": "media-ready", "media": kind, "key": key, "hit": bool} and
    {"kind": "media-error", "media": kind, "key": key, "op": op, "error": text,
    "retrying": bool, "failed": bool} events (`media` carries the media kind because
    `kind` is the event name; `failed` means given up for this connection).
    After a media line times out, or a bare parse/oversize error is mapped to it
    (the error may answer an earlier non-media line), no other media line is written
    until a reply retires it or MEDIA_LINE_GRACE has passed, so every reply is
    credited to the line it answers. media_status() is the status.json view. Otherwise
    `media_capability` is None and everything is as before.

    alive (ALIVE.md, 1.0.0-cc5.4): `alive` is True while the connected knob advertises
    capabilities.alive.version == 1. Only then does the bridge send the section 3 fields:
    the frame content (`playing`, `feedback.skip`) passes _frame(), and the latched fields
    are added to the frame line at the moment it is written (section 10.2), never kept in
    `latest_frame`: `clock` (local minutes since midnight from `local_minute`) in every
    control (enter) frame and in the next frame line once ALIVE_CLOCK_RESEND_SECONDS have
    passed on `clock` since it was last sent; `progress` once, in the next frame line after
    post_progress(); `ledDrive`/`ledDither` from set_led_tuning() in every control frame
    (and once in the next frame line after they change). A heartbeat carries only what is
    due, so it never repeats a progress already sent. Latched fields in a submitted frame
    are ignored (logged): only the bridge adds them. A `{"id": <ready control>, "lim": -1|1}`
    message emits {"kind": "limit", "id": id, "dir": -1|1}; any other `lim` is ignored.
    Without `alive` every line is byte-identical to desktop v6's.

    presentation 5 (PRESENTATION_V5.md, 1.0.0-cc5.4 + desktop v7): frames get the v5 fields and
    the 1,400 B budget (_frame); every older knob gets the section 2.2 downgrade. `reducedMotion`
    is a latched field the bridge adds at send time (sections 7.1, 14.2): its value comes from
    set_reduced_motion() or from a submitted frame that carries it (taken out of the content), and
    it goes in every control frame and in the next frame line after it changes. With `alive` too,
    set_led_tuning(pink=, vol_full=) adds `ledPink` / `ledVolFull` to every control frame and to
    no other line (7.3, 14.2).
    Knob events (section 11): `ready` carries `held`, the logical mask of the `ks` it reports (the
    raw mask re-seeds the pressed state; absent = 0); `button` carries `hid` (True when that `kd`
    also sent F24); `{"id","ks","kh":raw}` of the ready control emits {"kind": "hold", "id": id,
    "button": <logical>, "raw": raw} (the firmware times it, once per press; the host never does;
    r3.1 firmware sends it for every button: slot 0 at 600 ms, the others at 1000 ms, and the host
    uses slot 0 and slot 3). A `kh` outside 0..3 or a `ks` outside 0..15 is ignored.

    diag (PRESENTATION_V5.md 12.3, VOC-K1c; K3 section 6.5): request_diag() asks a connected knob
    that advertises `diag: 1` for one `{"diag":"?"}` (thread-safe; written by the bridge thread on
    its next pass, at most one unanswered at a time). The request is read-only: it never renews
    the lease and never moves the heartbeat. Each `{"diag":{…}}` reply emits {"kind": "diag",
    "diag": <diag_parse fields>, "binary": "A"|"B"|"C"|None, "invalid": [names]}; a malformed reply
    is never an `error`.
    """
    HEARTBEAT_SECONDS = 0.5
    RECALIBRATE_SECONDS = 30.0      # r4: a recalibration (alignment, pole check, save) answers within this
    READ_LIMIT = 4096
    # An art line's single reply may arrive after its transfer was dropped or
    # timed out; it stays attributable for this many request timeouts.
    ART_LINE_GRACE = 2.0
    # artwork2 flow control. Frame and media lines are written only while the bytes
    # written but not yet known to be read by the knob stay within its CDC receive
    # queue (capability rxBytes) minus this reserve; a line that does not fit waits
    # (latest frame wins). Requests (a control with its embedded frame, a release) are
    # written at once: the reserve holds them (two frame budgets, more than the largest
    # control line), so the queue cannot overflow by construction (8192 - 2200 + a
    # request line < 8192). A media reply proves the knob read everything up to that
    # line; any other line is presumed read TX_READ_SECONDS after it was written (COM
    # stalls last 30-100 ms).
    TX_RESERVE_BYTES = 2 * presentation.FRAME_BUDGET_BYTES
    TX_READ_SECONDS = 0.15
    # A media line's reply stays attributable for this many ack timeouts. Replies come
    # in line order and carry no sequence number, so after a timeout (or a bare error
    # mapped to it) no other media line is written until the line is answered or this
    # grace has passed.
    MEDIA_LINE_GRACE = 2.0

    def __init__(self, backup_dir, serial_factory=None, request_timeout=1.5, *, autostart=True, clock=time.monotonic,
                 local_minute=_local_minute):
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self._deferred_command = None
        self.backup_dir = Path(backup_dir)
        self.serial_factory = serial_factory or _open_serial
        self.request_timeout = request_timeout
        self.clock = clock
        # alive (ALIVE.md section 3): the latched fields added at send time. `local_minute`
        # returns the local minutes since midnight (injectable, like `clock`, for tests).
        self.local_minute = local_minute
        self._alive_lock = threading.Lock()  # post_progress / set_led_tuning come from other threads
        self._clock_sent_at = None           # `clock` time of the last line that carried clock
        self._progress = None                # {"pos", "dur"} posted and not yet sent
        self._led_drive = self._led_dither = None
        self._led_pink = self._led_vol_full = None  # PRESENTATION_V5.md 7.3 (presentation 5 + alive)
        self._led_generation = self._led_sent = 0   # set_led_tuning changes / the last one sent
        # PRESENTATION_V5.md 7.1: the effective reducedMotion, and the value the last line that
        # carried it sent (None: none since connect; every control frame sends it anyway).
        self._motion = False
        self._motion_sent = None
        # r4 (firmware 1.0.0-cc5.7): the Knob sounds volume (0 off .. 100 %) and Reduced haptics, sent in every
        # control of a knob with knobVolume / knobSound / feel (never stored on the knob: a claim without them is
        # silent). A knobSound knob without knobVolume gets the volume's level (sound_level_for_volume).
        self._knob_volume = 0
        self._reduced_haptics = False
        self.calibrating = False                    # a recalibration runs on the knob (calibrating line seen)
        self._button_order = [0, 1, 2, 3]           # the ready control's buttonOrder (raw -> logical)
        # diag (PRESENTATION_V5.md 12.3): request_diag() calls (only the caller's thread writes it),
        # the count of them the bridge thread has written or dropped (only the bridge writes it), so
        # a request is never lost to a race, and the clock time of the one unanswered line.
        self._diag_asked = 0
        self._diag_served = 0
        self._diag_sent_at = None
        self.serial = None
        self.decoder = LineDecoder()
        self.profiles = {}
        self.capabilities = {}
        self.current = None
        self.port = None
        self.backup_path = None
        self.control_id = None
        self.ready_id = None
        self.position = None
        self._expected_position = None
        self.latest_frame = None
        self._artwork = None
        self._artwork_loaded = None
        # Art lines written and not yet answered, oldest first. They belong to
        # the serial stream, not to a transfer or a control: the firmware
        # answers every line once, in order, even after the host moved on.
        self._art_lines = deque(maxlen=32)
        self._art_line_seq = 0
        # artwork2 media engine (bridge thread only; see _media_* below).
        self.media_capability = None
        self._media_kinds = {}
        self._media_upload = None     # the upload in progress, or None
        self._media_wait = None       # the one outstanding media line (stop-and-wait), or None
        self._media_lines = deque(maxlen=32)  # media lines written and not yet answered
        self._media_seq = 0
        self._media_hold = 0.0        # no media line before this clock time
        self._media_line_max = 0      # bytes of the largest media line
        self._media_tick = 0          # orders every (possible) touch on the knob's stores
        self._media_frame_keys = {}   # kind -> the key the last written frame named (adoption)
        self._tx_log = deque()        # (time, bytes, media seq or None) of unconfirmed lines
        self._frame_pending = False   # artwork2: latest_frame still has to be written
        self._media_snapshot = {kind: dict(_NO_MEDIA_STATUS, failedKeys=[]) for kind in presentation.MEDIA_KINDS}
        self._media_fault_logged = set()
        self._media_list_noted = {}   # kind -> (invalid, dropped) of the last set_media_wanted call
        self._bare_error_logged = None  # clock time of the last "bare error during a grace" log line
        self.last_heartbeat = 0.0
        self.closed = False
        self._pressed = 0
        self._ready_held = 0
        # App profiles (APP_PROFILES.md section 7): the upload in progress and the ones waiting (bridge thread only).
        self._app_upload = None
        self._app_uploads = deque()
        self._closing = False
        self._thread = threading.Thread(target=self._run, name="NanoD-control-center", daemon=True)
        if autostart:
            self._thread.start()

    def submit(self, command, value=None):
        if self.closed:
            raise RuntimeError("Device bridge is closed")
        if command not in ("connect", "inventory", "enter", "frame", "artwork", "disconnect", "close", "recalibrate",
                           "app_profile"):
            raise ValueError("Unknown device command")
        self.commands.put((command, deepcopy(value)))

    def set_media_wanted(self, kind, items):
        """Replace the wanted list of media `kind` ("cover"/"icon"); thread-safe (ARTWORK2.md section 9).

        `items` is a priority-ordered list of (key, payload) tuples: index 0 is what
        the knob shows now. A no-op unless artwork2 is negotiated. Invalid items are
        skipped (logged), a repeated key keeps its first position, and at most
        entries - 4 items are kept; the rest are dropped and counted (logged once per
        change of that count, not per call: a Windows detent reorders the icon list
        without changing how many items it holds; status.json media.<kind>.dropped
        always has the latest count). Call it only when a list changes. Payloads are not copied when they
        are already bytes. Applied on the bridge thread in order with submit(): submit
        the frame naming a new key first, then call this, so the frame is written
        before any media line that selection change causes.
        """
        if kind not in presentation.MEDIA_KINDS:
            raise ValueError("Unknown media kind")
        cap = self.media_capability
        if cap is None or self.closed:
            return
        spec = cap[kind]
        limit = max(0, spec["entries"] - presentation.MEDIA_WANTED_RESERVE)
        clean, seen, dropped, invalid = [], set(), 0, 0
        for item in items or ():
            try:
                key, payload = item
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not isinstance(payload, (bytes, bytearray)):
                invalid += 1
                continue
            size_ok = (1 <= len(payload) <= spec["maxBytes"]) if kind == "cover" else len(payload) == spec["bytes"]
            if not isinstance(key, str) or _MEDIA_KEY.fullmatch(key) is None or not size_ok:
                invalid += 1
                continue
            if key in seen:
                continue
            seen.add(key)
            if len(clean) >= limit:
                dropped += 1
                continue
            clean.append((key, payload if type(payload) is bytes else bytes(payload)))
        # One log line per change of a count (the contract's "log once per change"), not per
        # call: in Windows mode each detent reorders the icon list, and the same cap would
        # otherwise be written to app.log on every detent from the UI thread.
        last_invalid, last_dropped = self._media_list_noted.get(kind, (0, 0))
        self._media_list_noted[kind] = (invalid, dropped)
        if invalid and invalid != last_invalid:
            _log.warning("Media %s list: %d invalid item(s) ignored", kind, invalid)
        if dropped and dropped != last_dropped:
            _log.info("Media %s list capped at %d item(s); %d dropped", kind, limit, dropped)
        self.commands.put(("media", (kind, clean, dropped)))

    def media_status(self):
        """status.json "media" view, safe from any thread: {"cover": {...}, "icon": {...}}.

        Per kind: wanted (kept list length), present (mirror size: keys the knob is
        known to hold, at most entries - 3 because the mirror follows the knob's
        LRU), uploads (commits), hits (keys found on the knob without a transfer:
        have true or begin hit), errors (media-error events), failedKeys (sorted keys given up
        for this connection), lastError ("" or the latest error text) and dropped
        (items over the entries-4 cap in the latest list). Everything restarts with
        each connection; `media_capability is not None` is the "artwork2" flag.
        """
        return deepcopy(self._media_snapshot)  # published by the bridge thread after each pass

    # ------------------------------------------------------------------
    # alive (ALIVE.md sections 3 and 10.2): capability, latched fields, `lim`.

    @property
    def alive(self):
        """True while a connected knob has negotiated `alive` (capabilities.alive.version == 1)."""
        return self.serial is not None and alive_capability(self.capabilities) is not None

    def post_progress(self, pos_ms, dur_ms):
        """Queue one `progress` for the next frame line (thread-safe; ALIVE.md section 3).

        `pos_ms`/`dur_ms` are ints in 0..86400000, `pos_ms` extrapolated by the caller to
        now; `dur_ms` 0 clears the knob's song position (sent as pos 0). A `pos_ms` past
        `dur_ms` (extrapolation overshoot) is sent as `dur_ms`. A newer post replaces one
        not yet sent, and a sent one is never repeated. Anything else is ignored and
        logged (never raised). Sent only to a knob with `alive`; forgotten on (re)connect.
        """
        top = presentation.ALIVE_PROGRESS_MAX_MS
        if not (_integer(dur_ms, 0, top) and type(pos_ms) is int and pos_ms >= 0):
            _strip("progress", "invalid", "not sent")
            return
        progress = {"pos": min(pos_ms, dur_ms) if dur_ms else 0, "dur": dur_ms}
        with self._alive_lock:
            self._progress = progress

    def set_led_tuning(self, drive=None, dither=None, pink=None, vol_full=None):
        """settings.json `led_drive` / `led_dither` for a knob with `alive`, and `led_pink` /
        `led_vol_full` for a knob with `alive` and presentation 5 (thread-safe).

        `drive` is an int 1..255 or None, `dither` a bool or None (None: not configured,
        not sent). `pink` (PRESENTATION_V5.md 7.3, VOC section 6.2) is an int 0..0xFFFFFF or a
        "#RRGGBB" string (converted; 0 = the built-in PINK), `vol_full` a bool. `ledDrive` /
        `ledDither` go in every control (enter) frame and once in the next frame line after a
        change (ALIVE.md 10.2); `ledPink` / `ledVolFull` only in control frames (PRESENTATION_V5.md
        7.3, 14.2), so a change reaches the knob at the next claim. An invalid value is ignored
        and logged by name only (treated as None). The knob keeps what it latched until it
        reboots.
        """
        if drive is not None and not _integer(drive, presentation.ALIVE_LED_DRIVE_MIN,
                                              presentation.ALIVE_LED_DRIVE_MAX):
            _strip("ledDrive", "invalid", "not sent")
            drive = None
        if dither is not None and type(dither) is not bool:
            _strip("ledDither", "invalid", "not sent")
            dither = None
        if pink is not None:
            pink = led_pink_value(pink)
            if pink is None:
                _strip("ledPink", "invalid", "not sent")
        if vol_full is not None and type(vol_full) is not bool:
            _strip("ledVolFull", "invalid", "not sent")
            vol_full = None
        with self._alive_lock:
            tuning = (drive, dither, pink, vol_full)
            if tuning != (self._led_drive, self._led_dither, self._led_pink, self._led_vol_full):
                self._led_drive, self._led_dither, self._led_pink, self._led_vol_full = tuning
                self._led_generation += 1

    def set_reduced_motion(self, on):
        """The effective Motion setting (VOC-R09) for a presentation-5 knob (thread-safe).

        PRESENTATION_V5.md 7.1 / 14.2: `reducedMotion` goes in every control frame and in the
        next frame line after it changes; the knob resets it to false at every claim. A frame
        submitted with a `reducedMotion` bool sets it too. Anything but a bool is ignored (logged)."""
        if type(on) is not bool:
            _strip("reducedMotion", "invalid", "not sent")
            return
        with self._alive_lock:
            self._motion = on

    def set_knob_feel(self, sound=None, reduced_haptics=None, volume=None):
        """Settings > Knob (thread-safe): the Knob sounds volume (int 0..100 %; or an older host's level: 0 off,
        1 Low, 2 Medium, 3 High, or one of SOUND_LEVELS, taken as that level's top volume; a volume wins) and
        Reduced haptics (bool). They ride in the next control (the runtime re-enters after a change); anything
        invalid is ignored (logged)."""
        if sound is not None:
            level = SOUND_LEVELS.index(sound) if isinstance(sound, str) and sound in SOUND_LEVELS else sound
            if _integer(level, 0, len(SOUND_LEVELS) - 1):
                self._knob_volume = SOUND_LEVEL_VOLUMES[level]
            else:
                _strip("sound", "invalid", "not sent")
        if volume is not None:
            if _integer(volume, 0, KNOB_VOLUME_MAX):
                self._knob_volume = volume
            else:
                _strip("soundVolume", "invalid", "not sent")
        if reduced_haptics is not None:
            if type(reduced_haptics) is bool:
                self._reduced_haptics = reduced_haptics
            else:
                _strip("reducedHaptics", "invalid", "not sent")

    def _feel_fields(self, value):
        """A control's r4 fields for this knob, in place: `feel` kept (a valid token) only with the feel capability,
        `reducedHaptics` added with it; with knobVolume `soundVolume` (the volume) and `sound` (0 when silent, else
        High), with knobSound alone `sound` (the volume's level); everything dropped for an older knob (its control
        line stays byte-identical to Desk Dial 7.2's)."""
        feel = value.pop("feel", None)
        value.pop("reducedHaptics", None)
        value.pop("sound", None)
        value.pop("soundVolume", None)
        if feel_capability(self.capabilities):
            if isinstance(feel, str) and feel in FEEL_TOKENS:
                value["feel"] = feel
            elif feel is not None:
                _strip("feel", "invalid", "not sent")
            value["reducedHaptics"] = bool(self._reduced_haptics)
        volume = int(self._knob_volume)
        if knob_volume_capability(self.capabilities):
            value["sound"] = 0 if volume == 0 else len(SOUND_LEVELS) - 1
            value["soundVolume"] = volume
        elif sound_capability(self.capabilities):
            value["sound"] = sound_level_for_volume(volume)

    def _recalibrate(self, value):
        """Settings > Knob > Recalibrate motor (bridge thread; firmware HAPTICS.md "Recalibration"). A knob with the
        recalibration capability: any control is released first (the knob refuses while claimed), then
        {"recalibrate":true} (or {"acceptDirection":true} once the user confirmed a direction change) and the wait
        for its `calibrated` line (up to RECALIBRATE_SECONDS: aligning takes seconds and is not a timeout of the
        link). The events `calibrating` / `calibrated` tell the runtime; the runtime enters again afterwards."""
        if self.serial is None:
            raise RuntimeError("Connect the knob first")
        if not recalibration_capability(self.capabilities):
            raise RuntimeError("This knob's firmware cannot recalibrate from Desk Dial")
        accept = isinstance(value, dict) and value.get("acceptDirection") is True
        if self.control_id is not None:
            # Released quietly: the control is forgotten first, so the knob's `released` line is no `released` event
            # (the runtime would take the knob for lost); the runtime enters again after `calibrated`.
            self._reset_control()
            self._request({"release": True}, lambda m: m.get("released") is True)
        self.calibrating = True
        self._emit("calibrating")
        self._write({"recalibrate": {"acceptDirection": True} if accept else True})
        deadline = self.clock() + self.RECALIBRATE_SECONDS
        while self.clock() < deadline:
            for reply in self._read():
                if isinstance(reply.get("calibrated"), dict):
                    return
        self.calibrating = False
        self._emit("calibrated", ok=False, reason="")

    def request_diag(self):
        """Ask the connected knob for its diagnostics once (thread-safe; PRESENTATION_V5.md 12.3).

        Read-only: the bridge thread writes `{"diag":"?"}` on its next pass (never from the
        caller's thread), only to a knob whose capabilities carry `diag: 1`, with at most one
        request unanswered (a newer call waits for the reply, or for `request_timeout`). Calls
        before that pass coalesce. The line never renews the lease and never counts as the
        heartbeat; with artwork2 it waits for receive-queue room like a frame line. The reply is
        the `diag` event (class docstring). Returns False when nothing will be asked (no knob
        connected, or the bridge is closing); a request is forgotten at a disconnect."""
        if self.closed or self._closing or self.serial is None:
            return False
        self._diag_asked += 1
        return True

    def _diag_due(self):
        """Bridge thread: a request_diag() is waiting to be written (or dropped)."""
        return self._diag_asked != self._diag_served

    def _diag_reset(self):
        self._diag_served = self._diag_asked     # (re)connect / disconnect: pending requests are dropped
        self._diag_sent_at = None

    def _diag_step(self):
        """Bridge thread: write a wanted `{"diag":"?"}` when it may go (request_diag)."""
        asked = self._diag_asked
        if asked == self._diag_served:
            return
        if self.serial is None or type(self.capabilities.get("diag")) is not int or self.capabilities["diag"] != 1:
            self._diag_served = asked            # nothing to ask: dropped, not kept for later
            return
        if self._diag_sent_at is not None and self.clock() - self._diag_sent_at < self.request_timeout:
            return                               # one unanswered request at a time
        data = self._encode(DIAG_REQUEST)
        if not self._tx_room(len(data)):
            return                               # artwork2 flow control: wait like a frame line
        self._diag_served = asked                # a call made meanwhile stays due: never lost
        self._diag_sent_at = self.clock()
        self._write_line(data)                   # never touches last_heartbeat: not a lease renewal

    def _diag_reply(self, diag):
        """A `{"diag":{…}}` reply: the typed fields as one `diag` event (never an error)."""
        self._diag_sent_at = None
        fields, invalid = diag_parse(diag)
        if invalid:
            _log.debug("Knob diag: malformed %s dropped", ", ".join(invalid))   # names only (DIAG_FIELDS)
        self._emit("diag", diag=fields, binary=diag_binary(fields), invalid=invalid)

    # ------------------------------------------------------------------
    # App profiles (APP_PROFILES.md section 7; plan 1c, S1 DD-B): the upload, stop-and-wait, interleaved with the
    # heartbeat (one line per pass, so input and frames never stall). `list` first (an id + crc already loaded is
    # not sent again), then begin (no reply), data lines of <= 3000 b64 characters each waiting for its ack (1 s),
    # end waiting for ok. A failure retries the whole upload once, then the `app-profile` event says failed (the
    # runtime keeps the text screen). The retry drains first (S3 review DD-6): a `list` line, and every reply ignored
    # until the list's answer. The knob answers its lines in order, so a stale reply (the "order" to the data line
    # written after a failed begin, a late ack or ok) is behind us then; with no answer in a second it begins anyway. Events: {"kind": "app-profile", "id", "crc", "state": "present" | "loaded" |
    # "failed", "bytes", "ms", "error"}. The knob's store is RAM only: the runtime uploads again after a reconnect.

    def _app_profile_reset(self):
        self._app_upload = None
        self._app_uploads.clear()

    def _app_profile_queue(self, value):
        """An upload request {"id", "crc", "wire": bytes} (the runtime's, once per (id, crc) and connection)."""
        if not isinstance(value, dict):
            return
        pid, crc, wire = value.get("id"), value.get("crc"), value.get("wire")
        if (not isinstance(pid, str) or _APP_ID.fullmatch(pid) is None or not _integer(crc, 0, APP_CRC_MAX)
                or not isinstance(wire, (bytes, bytearray)) or not wire):
            return
        busy = [u for u in ([self._app_upload] if self._app_upload else []) + list(self._app_uploads)]
        if any(u["id"] == pid and u["crc"] == crc for u in busy):
            return
        cap = app_profiles_capability(self.capabilities)
        if self.serial is None or cap is None or len(wire) > cap["maxBytes"]:
            self._emit("app-profile", id=pid, crc=crc, state="failed", bytes=len(wire), ms=0,
                       error="unsupported" if cap is None else "size")
            return
        self._app_uploads.append({"id": pid, "crc": crc, "wire": bytes(wire)})

    def _app_profile_start(self, item, retried=False, stage="list"):
        self._app_upload = {**item, "stage": stage, "offset": 0, "waiting": None, "deadline": 0.0,
                            "retried": retried, "started": item.get("started", self.clock())}

    def _app_profile_done(self, state, error=None):
        upload, self._app_upload = self._app_upload, None
        ms = int(round((self.clock() - upload["started"]) * 1000))
        self._emit("app-profile", id=upload["id"], crc=upload["crc"], state=state, bytes=len(upload["wire"]),
                   ms=max(0, ms), error=error)

    def _app_profile_fail(self, reason):
        """Retry the whole upload once (from begin), then report it failed."""
        upload = self._app_upload
        if upload is None:
            return
        if not upload["retried"]:
            self._app_profile_start(upload, retried=True, stage="drain")
            return
        self._app_profile_done("failed", reason)

    def _app_profile_step(self):
        """Bridge thread: at most one upload line per pass."""
        if self._app_upload is None:
            if not self._app_uploads or self.serial is None:
                return
            self._app_profile_start(self._app_uploads.popleft())
        upload = self._app_upload
        if upload["waiting"] is not None:
            if self.clock() >= upload["deadline"]:
                if upload["waiting"] in ("list", "drain"):
                    upload["waiting"], upload["stage"] = None, "begin"     # no list answer: upload anyway
                else:
                    self._app_profile_fail("timeout")
            return
        stage, wire = upload["stage"], upload["wire"]
        if stage in ("list", "drain"):
            message, waiting = {"op": "list"}, stage
        elif stage == "begin":
            message, waiting = {"op": "begin", "id": upload["id"], "bytes": len(wire), "crc": upload["crc"],
                                "wire": WIRE_VERSION_APP}, None
        elif stage == "data":
            part = wire[upload["offset"]:upload["offset"] + APP_PROFILE_CHUNK_BYTES]
            message = {"op": "data", "off": upload["offset"], "b64": base64.b64encode(part).decode("ascii")}
            waiting = ("ack", upload["offset"] + len(part))
        else:
            message, waiting = {"op": "end"}, "end"
        data = self._encode({"appProfile": message})
        if not self._tx_room(len(data)):
            return                                   # artwork2 flow control: wait like a frame line
        self._write_line(data)
        if stage == "begin":
            upload["stage"] = "data"                 # a successful begin gets no reply (the first ack follows)
            upload["offset"] = 0
        upload["waiting"] = waiting
        upload["deadline"] = self.clock() + APP_PROFILE_REPLY_SECONDS

    def _app_profile_reply(self, reply):
        """A `{"appProfile": {...}}` line: list / ack / ok / error for the upload in progress (never an `error`)."""
        upload = self._app_upload
        if upload is None:
            return
        waiting = upload["waiting"]
        if upload["stage"] == "drain" and not (waiting == "drain" and isinstance(reply.get("loaded"), list)):
            return                                   # DD-6: a stale reply to a line sent before the retry
        if "error" in reply:
            error = reply.get("error")
            error = error if isinstance(error, str) and APP_PROFILE_ERRORS.fullmatch(error) else "error"
            self._app_profile_fail(error)
            return
        if waiting in ("list", "drain") and isinstance(reply.get("loaded"), list):
            present = any(isinstance(e, dict) and e.get("id") == upload["id"] and e.get("crc") == upload["crc"]
                          for e in reply["loaded"])
            if present:
                self._app_profile_done("present")
            else:
                upload["waiting"], upload["stage"] = None, "begin"
            return
        if isinstance(waiting, tuple) and "ack" in reply:
            if not _integer(reply["ack"], 0, APP_CRC_MAX) or reply["ack"] != waiting[1]:
                self._app_profile_fail("order")
                return
            upload["offset"] = reply["ack"]
            upload["waiting"] = None
            upload["stage"] = "end" if upload["offset"] >= len(upload["wire"]) else "data"
            return
        if waiting == "end" and reply.get("ok") is True:
            if reply.get("id") == upload["id"] and reply.get("crc") == upload["crc"]:
                self._app_profile_done("loaded")
            else:
                self._app_profile_fail("order")

    def app_profile_status(self):
        """The upload in progress (id, bytes, offset), or None. Any thread (a snapshot)."""
        upload = self._app_upload
        if upload is None:
            return None
        return {"id": upload["id"], "bytes": len(upload["wire"]), "offset": upload["offset"]}

    def _alive_reset(self):
        """(Re)connect or disconnect: the next control frame carries everything anew."""
        self._clock_sent_at = None
        with self._alive_lock:
            self._progress = None
            self._led_sent = self._led_generation
            self._motion_sent = None

    def _alive_extras(self, enter=False):
        """(fields, token): the latched fields due in the frame line about to be written, ({}, None)
        when none is: ALIVE.md 10.2's with `alive`; `reducedMotion` for presentation 5 (in every
        control frame and after a change, PRESENTATION_V5.md 7.1); `ledPink` / `ledVolFull` with
        both, in control frames only (7.3, 14.2). Call _alive_sent(token) once the line is written."""
        alive = alive_capability(self.capabilities) is not None
        v5 = presentation_level(self.capabilities) >= presentation.PRESENTATION_V5
        if not alive and not v5:
            return {}, None
        fields = {}
        now = self.clock()
        if alive and (enter or self._clock_sent_at is None
                      or now - self._clock_sent_at >= presentation.ALIVE_CLOCK_RESEND_SECONDS):
            try:
                minute = self.local_minute()
            except Exception:
                minute = None
            if _integer(minute, 0, presentation.ALIVE_CLOCK_MAX):
                fields["clock"] = minute
            else:
                _strip("clock", "local time unavailable", "not sent")
        with self._alive_lock:
            progress = self._progress if alive else None
            drive, dither, generation = self._led_drive, self._led_dither, self._led_generation
            pink, vol_full = self._led_pink, self._led_vol_full
            tuning = alive and (enter or generation != self._led_sent)
            motion = self._motion
            motion_due = v5 and (enter or motion != self._motion_sent)
        if progress is not None:
            fields["progress"] = dict(progress)
        if tuning:
            if drive is not None:
                fields["ledDrive"] = drive
            if dither is not None:
                fields["ledDither"] = dither
            if v5 and enter:   # control frames only (14.2); never a plain frame line after a change
                if pink is not None:
                    fields["ledPink"] = pink
                if vol_full is not None:
                    fields["ledVolFull"] = vol_full
        if motion_due:
            fields["reducedMotion"] = motion
        return fields, (now if "clock" in fields else None, progress, generation if tuning else None,
                        motion if motion_due else None)

    def _alive_sent(self, token):
        """The line from _alive_extras() was written: nothing it carried is due again."""
        if token is None:
            return
        clock_at, progress, generation, motion = token
        if clock_at is not None:
            self._clock_sent_at = clock_at
        with self._alive_lock:
            if progress is not None and self._progress is progress:
                self._progress = None  # a newer post stays pending
            if generation is not None:
                self._led_sent = max(self._led_sent, generation)
            if motion is not None:
                self._motion_sent = motion

    def _alive_line(self, frame, enter=False):
        """(frame with the due latched fields appended, token); `frame` itself is not changed."""
        fields, token = self._alive_extras(enter)
        return ({**frame, **fields} if fields else frame), token

    _BRIDGE_FIELDS = (*presentation.ALIVE_LATCHED_FIELDS, *presentation.ALIVE_TUNING_FIELDS)

    def _content(self, frame):
        """A submitted frame without the latched fields: only the bridge adds them.

        ALIVE's latched fields and the tuning fields are ignored (logged). A `reducedMotion` bool
        is the Motion setting (set_reduced_motion); it is taken out of the content either way."""
        if not isinstance(frame, dict):
            return frame
        if "reducedMotion" in frame:
            self.set_reduced_motion(frame["reducedMotion"])
        elif not any(name in frame for name in self._BRIDGE_FIELDS):
            return frame
        for name in self._BRIDGE_FIELDS:
            if name in frame:
                _strip(name, "added by the bridge at send time", "ignored")
        return {name: raw for name, raw in frame.items()
                if name not in self._BRIDGE_FIELDS and name not in presentation.V5_LATCHED_FIELDS}

    def _media_publish(self):
        kinds = self._media_kinds
        self._media_snapshot = {kind: (kinds[kind].status() if kind in kinds else dict(_NO_MEDIA_STATUS,
                                                                                         failedKeys=[]))
                                for kind in presentation.MEDIA_KINDS}

    def _emit(self, kind, **values):
        self.events.put({"kind": kind, **values})

    def _encode(self, message):
        data = (json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(data) > 4096:
            raise ValueError("Device command exceeds the frame size limit")
        return data

    def _write(self, message, media_seq=None):
        if self.serial is None:
            raise OSError("The knob is disconnected")
        data = self._encode(message)
        if self.media_capability is not None and media_seq is None:
            # A request (control, release) uses the reserve; only a line that would not
            # fit the whole receive queue waits (never in practice: requests are < 1.3 KB).
            deadline = self.clock() + self.TX_READ_SECONDS
            while not self._tx_room(len(data), reserve=0) and self.clock() < deadline:
                self._read()
        self._write_line(data, media_seq)

    def _write_line(self, data, media_seq=None):
        if self.media_capability is None:
            written = self.serial.write(data)
        else:
            # ARTWORK2.md section 3: each complete line in one write(), never paced.
            port = self.serial.port if isinstance(self.serial, PacedSerial) else self.serial
            written = port.write(data)
            self._tx_log.append((self.clock(), len(data), media_seq))
        if written != len(data):
            raise OSError("Incomplete device write")

    def _tx_room(self, size, reserve=None):
        """artwork2: True when `size` more bytes keep the knob's unread bytes in budget."""
        cap = self.media_capability
        if cap is None:
            return True
        log = self._tx_log
        horizon = self.clock() - self.TX_READ_SECONDS
        while log and log[0][0] <= horizon:
            log.popleft()
        reserve = self.TX_RESERVE_BYTES if reserve is None else reserve
        return sum(entry[1] for entry in log) + size <= cap["rxBytes"] - reserve

    def _tx_read_through(self, seq):
        """The reply to media line `seq` came: the knob read every byte up to that line."""
        log = self._tx_log
        if any(entry[2] == seq for entry in log):
            while log and log.popleft()[2] != seq:
                pass

    def _consume(self, message):
        if isinstance(message.get("appProfile"), dict):
            self._app_profile_reply(message["appProfile"])
            return
        if isinstance(message.get("mediaAck"), dict):
            try:
                self._media_ack(message["mediaAck"])
            except OSError:
                raise
            except Exception as exc:  # presentation-only: never an `error` event or a disconnect
                self._media_fault(exc)
            return
        if isinstance(message.get("artAck"), dict):
            self._artwork_ack(message["artAck"])
            return
        if isinstance(message.get("diag"), dict):
            self._diag_reply(message["diag"])
            return
        if "error" in message:
            if self._media_line_error(message) or self._artwork_line_error(message):
                return
            # Do not echo arbitrary serial payloads, which may contain settings.
            raise OSError("The knob rejected the command; check capability, profile and control ID")
        if message.get("calibrating") is True:
            # r4 (recalibration 1): the knob's motor is aligning (seconds, not a timeout; no control meanwhile).
            self.calibrating = True
            self._emit("calibrating")
            return
        if isinstance(message.get("calibrated"), dict):
            result = message["calibrated"]
            self.calibrating = False
            ok = result.get("ok") is True
            reason = result.get("reason") if isinstance(result.get("reason"), str) else ""
            self._emit("calibrated", ok=ok, reason=reason if reason in DIAG_CAL_OUTCOMES else "")
            return
        if message.get("released") is True:
            was_active = self.control_id is not None
            self._reset_control()
            if was_active:
                self._emit("released", reason="lease-expired" if message.get("reason") == "lease-expired" else "released")
            return
        if "ready" in message:
            if (self.ready_id is None and type(message["ready"]) is int and message["ready"] == self.control_id
                    and message.get("p") == self._expected_position and _integer(message.get("p"), 0, 65535)):
                self.ready_id = self.control_id
                self.position = message["p"]
                # PRESENTATION_V5.md 11.3: `ks` (presentation 5) re-seeds the pressed mask, so an
                # edge lost while entering never leaves a stale bit; absent or invalid = 0.
                held = message.get("ks")
                self._pressed = held if _integer(held, 0, 15) else 0
                # DD-BUG-006: a button down as `ready` was built may still send its kd with this id (the HMI
                # publishes the press, then queues the kd): that first key line is not a second press.
                self._ready_held = self._pressed
                self._emit("ready", id=self.ready_id, p=self.position, position=self.position,
                           held=self._logical_mask(self._pressed))
            return
        if self.ready_id is None or message.get("id") != self.ready_id:
            return
        state = message.get("ks")
        state = state if _integer(state, 0, 15) else None
        up, down, hold = message.get("ku"), message.get("kd"), message.get("kh")
        key_line = _integer(up, 0, 3) or _integer(down, 0, 3) or _integer(hold, 0, 3)
        if state is not None and not key_line:
            # 1.0.0-cc5.5 (F1): a position line's `ks` is the mask the knob last reported AND its live mask,
            # so it can only clear bits: a key-up lost to a full key queue. Clear-only here too, before the
            # turn it carries (the release came first): each cleared bit is that button's release; a bit
            # is never set from it (a press always arrives as its own kd, even when this line came first).
            cleared = self._pressed & ~state
            self._pressed &= state
            for raw in range(4):
                if cleared & (1 << raw):
                    self._emit("release", id=self.ready_id, index=raw, button=raw)
        elif state is not None:
            # DD-BUG-006: a key line's `ks` is the knob's mask as that edge was queued, so a bit set here and
            # missing there is a key-up lost to a full key queue: release it before the edge (and before the
            # re-seed below drops it silently). The line's own `ku` bit is left to the `ku` path.
            stale = self._pressed & ~state
            if _integer(up, 0, 3):
                stale &= ~(1 << up)
            self._pressed &= ~stale
            for raw in range(4):
                if stale & (1 << raw):
                    self._emit("release", id=self.ready_id, index=raw, button=raw)
        limit = message.get("lim")
        if type(limit) is int and limit in presentation.ALIVE_LIMIT_VALUES:
            # ALIVE.md section 3: an end-stop push of the ready control (a touch, like a turn).
            self._emit("limit", id=self.ready_id, dir=limit)
        if _integer(message.get("p"), 0, 65535):
            previous = self.position
            self.position = message["p"]
            if previous is not None and previous != self.position:
                self._emit("position", id=self.ready_id, p=self.position, position=self.position, delta=self.position - previous)
        if _integer(up, 0, 3):
            was_down = self._pressed & (1 << up)
            self._pressed &= ~(1 << up)
            if was_down:
                # The release of a press this control saw (r3: button 1 acts on release, README 1).
                # Its own kind, so input fast paths that count `button` as a press never see it.
                self._emit("release", id=self.ready_id, index=up, button=up)
        if _integer(down, 0, 3):
            mask = 1 << down
            if self._ready_held & mask:
                pass        # the kd of a press `ready` already reported as held: no second press
            elif state is None or state & mask:
                if self._pressed & mask:
                    # DD-BUG-006: a new press of a button still marked down (its ku was lost): the missing
                    # release first, then this press, instead of swallowing it.
                    self._emit("release", id=self.ready_id, index=down, button=down)
                self._pressed |= mask
                # PRESENTATION_V5.md 11.1: `hid:1` when that press also sent F24 (the host drops it).
                hid = type(message.get("hid")) is int and message["hid"] == 1
                self._emit("button", id=self.ready_id, index=down, button=down, pressed=True, hid=hid)
        if _integer(hold, 0, 3):
            # PRESENTATION_V5.md 11.2: the firmware's 600 ms long press of the raw button at slot 0,
            # at most one per physical press (a deferred one arrives right after `ready`, with no
            # `kd` in that control). The host never times a hold (VOC-D06). r3.1: every button's
            # hold arrives here (the others at 1000 ms); the runtime acts on slots 0 and 3 only.
            self._emit("hold", id=self.ready_id, button=self._button_order.index(hold), raw=hold)
        if key_line:
            self._ready_held = 0    # only the first key line after `ready` can be that press's kd
        if state is not None and key_line:
            # A key line's `ks` is the knob's mask as that edge was queued: it re-seeds the pressed state.
            self._pressed = state

    def _logical_mask(self, raw_mask):
        """A raw button bitmask (`ks`) as logical slots of the ready control's buttonOrder."""
        return sum(1 << slot for slot, raw in enumerate(self._button_order) if raw_mask & (1 << raw))

    def _read(self):
        # Take what is already buffered without waiting; when idle, block for one
        # byte up to the port's own timeout (50 ms). Never a zero-timeout read.
        waiting = getattr(self.serial, "in_waiting", 0) or 0
        data = self.serial.read(max(1, min(waiting, self.READ_LIMIT)))
        messages = self.decoder.feed(data)
        for message in messages:
            self._consume(message)
        return messages

    def _request(self, message, predicate, *, optional=False):
        self._write(message)
        deadline = self.clock() + self.request_timeout
        while self.clock() < deadline:
            for reply in self._read():
                if predicate(reply):
                    return reply
        if optional:
            return None
        raise TimeoutError("The knob did not acknowledge the request")

    def _reset_control(self):
        self.control_id = self.ready_id = self.position = None
        self._expected_position = None
        self.latest_frame = None
        self._artwork = None
        self._artwork_loaded = None
        self._pressed = 0
        self._ready_held = 0
        self._frame_pending = False
        self._media_control_changed()

    def _connect(self, port):
        if self.serial is not None:
            raise RuntimeError("Disconnect before opening another port")
        self.decoder.reset()
        self._art_lines.clear()
        self._media_reset()
        self._reset_control()
        self._alive_reset()
        self._diag_reset()
        self._app_profile_reset()
        self.profiles = {}
        self.capabilities = {}
        self.backup_path = None
        self.port = str(port)
        try:
            self.serial = self.serial_factory(self.port)
            inventory = self._request({"profiles": "#all"}, lambda m: isinstance(m.get("profiles"), list) and isinstance(m.get("current"), str))
            names = inventory["profiles"]
            if (not names or len(names) != len(set(names)) or any(not isinstance(n, str) or not 1 <= len(n.encode("utf-8")) <= 20 for n in names)
                    or inventory["current"] not in names):
                raise ValueError("Invalid installed profile inventory")
            for name in names:
                result = self._request({"profile": name}, lambda m, n=name: isinstance(m.get("profile"), dict) and m["profile"].get("name") == n)
                self.profiles[name] = deepcopy(result["profile"])
            self.current = inventory["current"]
            settings = self._request({"settings": "?"}, lambda m: isinstance(m.get("settings"), dict))["settings"]
            filtered = {key: settings[key] for key in ("serialNumber", "firmwareVersion", "deviceName", "deviceOrientation", "ledMaxBrightness") if key in settings}
            capabilities = self._request({"capabilities": "?"}, lambda m: isinstance(m.get("capabilities"), dict), optional=True)
            self.capabilities = deepcopy(capabilities["capabilities"]) if capabilities else {}
            self._media_negotiate()
            path = self._inventory_backup({"current": self.current, "settings": filtered, "profiles": self.profiles,
                                           "capabilities": self.capabilities})
            self.backup_path = path
            self._emit("connected", profiles=deepcopy(self.profiles), current=self.current,
                       capabilities=deepcopy(self.capabilities), port=self.port, backup=str(path))
        except Exception:
            if self.serial is not None:
                self.serial.close()
                self.serial = None
            self._reset_control()
            self._media_reset()
            raise

    INVENTORY_DEDUPE_SCAN = 8   # DD-BUG-005: how many of the newest backups an unchanged inventory is matched against

    def _inventory_backup(self, content):
        """The inventory backup of this connect: a new control-center-inventory-*.json, or (DD-BUG-005) the
        newest existing one with the same content (current, settings, profiles, capabilities; not the time or
        the port), touched so it is the newest again. A replug or a reconnect loop then adds no file; a
        changed inventory (firmware, settings, profiles) always gets its own. Existing backups are never
        deleted."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        wanted = json.loads(json.dumps(content, ensure_ascii=False, allow_nan=False))
        try:
            existing = sorted(((entry.stat().st_mtime, entry.name, entry)
                               for entry in self.backup_dir.glob("control-center-inventory-*.json")
                               if entry.is_file()), reverse=True)[:self.INVENTORY_DEDUPE_SCAN]
        except OSError:
            existing = []
        for _, _, entry in existing:
            try:
                saved = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(saved, dict) and {key: saved.get(key) for key in wanted} == wanted:
                try:
                    entry.touch()       # the newest again (tooling orders inventories by time)
                except OSError:
                    continue
                return entry
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.backup_dir / f"control-center-inventory-{timestamp}-{uuid.uuid4().hex[:8]}.json"
        with path.open("x", encoding="utf-8") as output:
            json.dump({"createdUtc": timestamp, "port": self.port, **content}, output, indent=2,
                      ensure_ascii=False, allow_nan=False)
        return path

    def _enter(self, payload):
        if self.serial is None:
            raise RuntimeError("Connect the knob first")
        if self.capabilities.get("controlCenter") != 1:
            raise RuntimeError("Installed firmware lacks control-center support; inventory is read-only until the targeted firmware extension is installed")
        if self.backup_path is None or not self.backup_path.is_file():
            raise RuntimeError("A complete device inventory backup is required before control")
        if not isinstance(payload, dict) or payload.get("profile") not in self.profiles:
            raise ControlRefused("Choose an inventoried existing profile",
                                  profile=payload.get("profile") if isinstance(payload, dict) else None)
        value = deepcopy(payload)
        if type(value.get("windowsHidEnabled", True)) is not bool:
            raise ControlRefused("Windows HID enable must be a boolean")
        value.setdefault("windowsHidEnabled", True)
        order = value.get("buttonOrder", [0, 1, 2, 3])
        if not isinstance(order, list) or len(order) != 4 or any(type(i) is not int for i in order) or set(order) != {0, 1, 2, 3}:
            raise ControlRefused("Button order must be a physical-to-raw permutation")
        if (not _integer(value.get("id"), 1, 0x7FFFFFFF) or not _integer(value.get("min"), 0, 0)
                or not _integer(value.get("max"), 0, 65535) or not _integer(value.get("position"), 0, value["max"])
                or not _integer(value.get("windowsButton"), 0, 3)):
            raise ControlRefused("Invalid control bounds, index or button mapping")
        if self.control_id is not None and value["id"] <= self.control_id:
            raise ValueError("Control IDs must increase within a connection")
        self._feel_fields(value)
        value["frame"] = _frame(self._content(value.get("frame")), self.capabilities)
        self.control_id = value["id"]
        self._artwork = None
        self._artwork_loaded = None
        self._frame_pending = False
        self._media_control_changed()
        self._expected_position = value["position"]
        self.ready_id = self.position = None
        self._pressed = 0
        self._ready_held = 0
        self._button_order = list(order)  # raw -> logical for this control's events (VOC-N11)
        self.latest_frame = {**value["frame"], "id": self.control_id}
        try:
            self._media_frame_written(value["frame"])
            # alive: clock (and any due progress, LED tuning) ride in the control's frame only.
            sent, token = self._alive_line(value["frame"], enter=True)
            message = {"control": value if sent is value["frame"] else {**value, "frame": sent}}
            self._request(message, lambda m: m.get("ready") == value["id"] and m.get("p") == value["position"])
            self._alive_sent(token)
            self.last_heartbeat = self.clock()
        except Exception:
            try:
                self._write({"release": True})
            finally:
                self._reset_control()
            raise

    def _frame(self, payload):
        if not isinstance(payload, dict) or self.ready_id is None or payload.get("id") != self.ready_id:
            raise ValueError("Frame must match the ready control")
        normalized = _frame(self._content(payload), self.capabilities)
        normalized["id"] = self.ready_id
        if self.media_capability is not None:
            # Written whole as soon as the knob's receive queue has room; a newer
            # frame replaces one still waiting (frames stay coalesced).
            self.latest_frame = normalized
            self._frame_pending = True
            self._flush_frame()
            return
        sent, token = self._alive_line(normalized)
        self._write({"frame": sent})
        self._alive_sent(token)
        self.latest_frame = normalized
        if self._artwork and normalized.get("artKey", "") != self._artwork["key"]:
            self._artwork = None
        self.last_heartbeat = self.clock()

    def _flush_frame(self):
        """artwork2: write the pending latest frame when the flow-control budget allows."""
        if not self._frame_pending:
            return
        if self.serial is None or self.ready_id is None or self.latest_frame is None:
            self._frame_pending = False
            return
        sent, token = self._alive_line(self.latest_frame)  # latched fields due now (ALIVE.md 10.2)
        data = self._encode({"frame": sent})
        if not self._tx_room(len(data)):
            return
        self._write_line(data)
        self._alive_sent(token)
        self._frame_pending = False
        self.last_heartbeat = self.clock()
        self._media_frame_written(self.latest_frame)

    def _heartbeat(self):
        if self.media_capability is not None:
            # The lease heartbeat continues during media transfers (ARTWORK2.md section 3).
            if (not self._frame_pending and self.ready_id is not None and self.latest_frame is not None
                    and self.clock() - self.last_heartbeat >= self.HEARTBEAT_SECONDS):
                self._frame_pending = True
            self._flush_frame()
            return
        if self.ready_id is not None and self.latest_frame is not None and self.clock() - self.last_heartbeat >= self.HEARTBEAT_SECONDS:
            # Only latched fields that are due (never a progress already sent).
            sent, token = self._alive_line(self.latest_frame)
            self._write({"frame": sent})
            self._alive_sent(token)
            self.last_heartbeat = self.clock()

    def _artwork_error(self, ident, key, reason, *, retrying=False, transient=None):
        """Presentation-only failure: never an `error` event or a disconnect."""
        if transient is None:
            transient = reason in ARTWORK_TRANSIENT
        self._emit("artwork-error", id=ident, key=key if isinstance(key, str) else "", reason=reason,
                   transient=transient, retrying=retrying, message=ARTWORK_MESSAGES[reason])

    def _queue_artwork(self, payload):
        """Start a cooperative transfer. Each iteration writes at most one chunk.

        Art failures are presentation-only events, never a control disconnect.
        The matching frame must precede this command to prevent stale art from
        replacing the visible selection, even when the control ID is unchanged.
        With artwork2 negotiated v1 `art` lines are never sent (ARTWORK2.md section 3).
        """
        if self.media_capability is not None:
            return
        if not isinstance(payload, dict):
            self._artwork_error(None, "", "invalid")
            return
        ident, key, raw = payload.get("id"), payload.get("key"), payload.get("data")
        if (ident != self.ready_id or self.ready_id is None or not self.latest_frame
                or key != self.latest_frame.get("artKey")):
            return
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
            return  # An empty key means "no art"; there is nothing to upload.
        cap = _artwork_capability(self.capabilities)
        if cap is None:
            self._artwork_error(ident, key, "unsupported")
            return
        if not isinstance(raw, bytes) or len(raw) != cap["width"] * cap["height"] * 2:
            self._artwork_error(ident, key, "size")
            return
        if self._artwork_loaded == (ident, key) or (self._artwork and (ident, key) == (self._artwork["id"], self._artwork["key"])):
            return
        self._artwork = {"id": ident, "key": key, "data": raw, "chunk": min(384, cap["chunkBytes"]),
                         "offset": 0, "stage": "begin", "waiting": None, "deadline": 0,
                         "crc32": zlib.crc32(raw) & 0xFFFFFFFF, "retried": False}

    def _artwork_abort(self, reason, *, retry=False):
        """Abort the active transfer; optionally restart it once from `begin`."""
        art = self._artwork
        again = retry and not art["retried"]
        # After its own retry failed, the bridge reports the failure as final.
        self._artwork_error(art["id"], art["key"], reason, retrying=again,
                            transient=reason in ARTWORK_TRANSIENT and not art["retried"])
        if again:
            self._artwork = {**art, "offset": 0, "stage": "begin", "waiting": None,
                             "deadline": 0, "retried": True}
        else:
            self._artwork = None

    def _artwork_step(self):
        art = self._artwork
        if art is None:
            return
        if (art["id"] != self.ready_id or self.latest_frame is None
                or art["key"] != self.latest_frame.get("artKey")):
            self._artwork = None
            return
        if art["waiting"] is not None:
            if self.clock() >= art["deadline"]:
                self._artwork_abort("timeout")
            return
        message = {"id": art["id"], "key": art["key"], "op": art["stage"]}
        expected = art["offset"]
        if art["stage"] == "begin":
            message.update(bytes=len(art["data"]), crc32=art["crc32"])
        elif art["stage"] == "data":
            part = art["data"][art["offset"]:art["offset"] + art["chunk"]]
            message.update(offset=art["offset"], data=base64.b64encode(part).decode("ascii"))
            expected += len(part)
        now = self.clock()
        self._art_line_seq += 1
        art["waiting"] = (art["stage"], expected)
        art["deadline"] = now + self.request_timeout
        art["line"] = self._art_line_seq
        self._art_lines.append({"seq": self._art_line_seq, "id": art["id"], "key": art["key"],
                                "op": art["stage"],
                                "deadline": now + self.ART_LINE_GRACE * self.request_timeout})
        self._write({"art": message})

    def _pop_art_line(self, match=None):
        """Retire the art line a reply answers: the oldest one, or the oldest matching one.

        Replies arrive in line order, so older lines before a match were answered
        (or lost) already and are retired with it. Expired lines are forgotten.
        """
        now = self.clock()
        while self._art_lines and self._art_lines[0]["deadline"] <= now:
            self._art_lines.popleft()
        for position, line in enumerate(self._art_lines):
            if match is None or match(line):
                for _ in range(position + 1):
                    self._art_lines.popleft()
                return line
        return None

    def _art_line_owner(self, line):
        """True when `line` is the outstanding line of the active transfer."""
        art = self._artwork
        return (line is not None and art is not None and art["waiting"] is not None
                and art.get("line") == line["seq"])

    def _artwork_line_error(self, message):
        """A bare parse/oversize error answering an outstanding art line is art-only.

        It aborts the active transfer (one automatic retry) only when it answers
        that transfer's line; a reply to a line whose transfer was dropped, timed
        out or superseded by a new control is reported and otherwise ignored.
        """
        text = message.get("error")
        if not isinstance(text, str) or not any(word in text.lower() for word in ARTWORK_LINE_ERRORS):
            return False
        line = self._pop_art_line()
        if line is None:
            return False
        if self._art_line_owner(line):
            self._artwork_abort("parse", retry=True)
        else:
            self._artwork_error(line["id"], line["key"], "parse")
        return True

    def _artwork_ack(self, ack):
        art = self._artwork
        # A firmware parse failure carries id/key only if its bounded prefix scan found them.
        parse = ack.get("op") == "parse"

        def answers(line):  # every artAck answers the oldest outstanding line it names
            return ("id" not in ack or ack["id"] == line["id"]) and ("key" not in ack or ack["key"] == line["key"])
        line = self._pop_art_line(answers)
        if parse:
            if self._art_line_owner(line) or (line is None and art and art["waiting"] is not None
                                              and answers({"id": art["id"], "key": art["key"]})):
                self._artwork_abort("parse")
            elif line is not None:
                self._artwork_error(line["id"], line["key"], "parse")
            return
        if not art or art["waiting"] is None:
            return
        failed = "error" in ack
        if ack.get("id") != art["id"] or ack.get("key") != art["key"]:
            return
        if failed:
            self._artwork_abort("rejected")
            return
        if ack.get("op") != art["waiting"][0]:
            return
        cached = art["stage"] == "begin" and ack.get("offset") == len(art["data"])
        if ack.get("offset") != art["waiting"][1] and not cached:
            self._artwork_abort("rejected")
            return
        art["offset"] = ack["offset"]
        if art["stage"] == "commit":
            self._artwork_loaded = (art["id"], art["key"])
            self._emit("artwork-ready", id=art["id"], key=art["key"])
            self._artwork = None
            return
        art["stage"] = "commit" if art["offset"] == len(art["data"]) else "data"
        art["waiting"] = None

    # ------------------------------------------------------------------
    # artwork2 media push engine (ARTWORK2.md sections 3, 4 and 9). Bridge thread only.

    def _media_reset(self):
        """(Re)connect, disconnect or a new capabilities reply: forget everything."""
        self.media_capability = None
        self._media_kinds = {}
        self._media_upload = self._media_wait = None
        self._media_lines.clear()
        self._media_hold = 0.0
        self._media_frame_keys = {}
        self._tx_log.clear()
        self._frame_pending = False
        self._media_publish()

    def _media_fault(self, exc):
        """An unexpected media-engine exception: logged once per type, the upload dropped, a pause."""
        name = type(exc).__name__
        if name not in self._media_fault_logged:
            self._media_fault_logged.add(name)
            _log.warning("Media engine fault (%s); artwork uploads pause", name)
        self._media_upload = self._media_wait = None
        self._media_hold = self.clock() + presentation.MEDIA_RETRY_SECONDS

    def _media_negotiate(self):
        """Parse `artwork2` after `capabilities`: the mirror starts empty."""
        self._media_reset()
        cap = artwork2_capability(self.capabilities)
        if cap is None:
            return
        self._media_kinds = {kind: _MediaKind(kind, cap) for kind in presentation.MEDIA_KINDS}
        chunk = cap["chunkBytes"]
        widest = {"media": {"id": 0x7FFFFFFF, "op": "data", "kind": "cover", "key": "k" * 24,
                            "offset": cap["cover"]["maxBytes"], "data": "A" * (4 * -(-chunk // 3))}}
        self._media_line_max = len(self._encode(widest))
        self.media_capability = cap
        self._media_publish()

    def _media_next_tick(self):
        self._media_tick += 1
        return self._media_tick

    def _media_trim(self, state):
        """state.trim() keeping the touches that a reply still on its way may count against."""
        ticks = [line["tick"] for line in self._media_lines]
        if self._media_wait is not None:
            ticks.append(self._media_wait["tick"])
        state.trim(min(ticks, default=None))

    def _media_frame_written(self, frame):
        """A frame (or a control's frame) naming another key: the knob adopts it (a touch)."""
        if self.media_capability is None or not isinstance(frame, dict):
            return
        for kind, field in (("cover", "artKey"), ("icon", "iconKey")):
            key = frame.get(field) or ""
            if key == self._media_frame_keys.get(kind):
                continue  # displayed does not change: no touch
            self._media_frame_keys[kind] = key
            state = self._media_kinds.get(kind)
            if key and state is not None:
                state.touch(key, self._media_next_tick())
                self._media_trim(state)

    def _media_control_changed(self):
        """A new control or a release: the knob cancels its upload context, so does the host.

        A line still outstanding keeps being awaited (stop-and-wait) but is no longer
        an upload's line: its reply only updates the mirror.
        """
        self._media_upload = None
        if self._media_wait is not None:
            self._media_wait["upload"] = None
        self._media_hold = 0.0

    def _media_wanted(self, kind, items, dropped):
        state = self._media_kinds.get(kind)
        if self.media_capability is None or state is None:
            return  # set_media_wanted is a no-op without artwork2
        keys = [key for key, _payload in items]
        keep = set(keys)
        state.wanted, state.payloads, state.dropped = list(items), dict(items), dropped
        # A key that dropped out of the list may be tried again when it re-enters.
        state.failures = {key: count for key, count in state.failures.items() if key in keep}
        state.retry_at = {key: when for key, when in state.retry_at.items() if key in keep}
        state.failed &= keep
        state.known &= keep | set(state.mirror)  # a key known absent is forgotten once unwanted
        state.probe = bool(keys) and (keys[0] != state.probe_head or any(key not in state.known for key in keys))

    def _media_candidate(self, now):
        """(position, kind order, kind, key) of the next key to upload, or None.

        Each kind's first key not in the mirror, not failed and not waiting for its
        retry; the lower list position wins, covers first on a tie (both index 0).
        """
        best = None
        for order, kind in enumerate(presentation.MEDIA_KINDS):
            state = self._media_kinds.get(kind)
            if state is None:
                continue
            for position, (key, _payload) in enumerate(state.wanted):
                if key in state.mirror or key in state.failed or state.retry_at.get(key, now) > now:
                    continue
                if best is None or (position, order) < best[:2]:
                    best = (position, order, kind, key)
                break
        return best

    def _media_busy(self):
        if self.media_capability is None or self.serial is None:
            return False
        if self._frame_pending or self._media_wait is not None:
            return True
        now = self.clock()
        if self.ready_id is None or now < self._media_hold or self._media_unanswered(now):
            return False
        return (self._media_upload is not None or any(state.probe for state in self._media_kinds.values())
                or self._media_candidate(now) is not None)

    def _media_unanswered(self, now):
        """True while a media line may still be answered (live, timed out or bare-error mapped).

        Replies come in line order but carry no sequence number, a `have` reply names
        no key and a retry repeats its line's id/op/kind/key, so no other media line may
        compete with a reported one: it is retired by a matching reply, or counted lost
        after MEDIA_LINE_GRACE.
        """
        lines = self._media_lines
        while lines and lines[0]["expires"] <= now:
            lines.popleft()
        return bool(lines)

    def _busy(self):
        """Work that must not wait behind the 20 ms command-queue poll."""
        return bool(self._artwork) or self._media_busy()

    def _media_step(self):
        """Write at most one media line: stop-and-wait, frames and commands first."""
        if self.media_capability is None or self.serial is None:
            return
        self._flush_frame()
        now = self.clock()
        wait = self._media_wait
        if wait is not None:
            if now < wait["deadline"]:
                return
            self._media_wait = None
            self._media_failed(wait, "timeout", maybe_handled=True)
        if self._media_unanswered(now):
            return  # its reply could otherwise be credited to the next line (a retry repeats it)
        if (self.ready_id is None or self._frame_pending or now < self._media_hold
                or self._deferred_command is not None or not self.commands.empty()):
            return
        if not self._tx_room(self._media_line_max):
            return
        # A due `have` goes first; it never cancels an upload on the knob.
        for kind in presentation.MEDIA_KINDS:
            state = self._media_kinds[kind]
            if state.probe:
                state.probe = False
                keys = self._media_probe_keys(state)
                if keys:
                    state.probe_head = keys[0]
                    self._media_send({"op": "have", "kind": kind, "keys": keys}, kind=kind, op="have", keys=keys)
                    return
        best = self._media_candidate(now)
        upload = self._media_upload
        if upload is not None:
            state = self._media_kinds[upload["kind"]]
            position = state.position(upload["key"])
            rank = (position, presentation.MEDIA_KINDS.index(upload["kind"]))
            preempted = (best is not None and best[0] == 0 and (best[2], best[3]) != (upload["kind"], upload["key"])
                         and position is not None and best[:2] < rank)
            if position is None or upload["key"] in state.mirror or upload["id"] != self.ready_id or preempted:
                # Out of the list, found present, or a new missing index 0 outranks it: the
                # knob cancels the old context at the next begin.
                self._media_upload = upload = None
        if upload is None:
            if best is None:
                return
            _position, _order, kind, key = best
            payload = self._media_kinds[kind].payloads[key]
            upload = self._media_upload = {"kind": kind, "key": key, "data": payload, "id": self.ready_id,
                                           "crc32": zlib.crc32(payload) & 0xFFFFFFFF, "offset": 0, "stage": "begin"}
        stage, offset = upload["stage"], upload["offset"]
        fields = {"op": stage, "kind": upload["kind"], "key": upload["key"]}
        expected = offset
        if stage == "begin":
            fields.update(bytes=len(upload["data"]), crc32=upload["crc32"])
        elif stage == "data":
            part = upload["data"][offset:offset + self.media_capability["chunkBytes"]]
            fields.update(offset=offset, data=base64.b64encode(part).decode("ascii"))
            expected = offset + len(part)
        self._media_send(fields, kind=upload["kind"], op=stage, key=upload["key"], expected=expected, upload=upload)

    def _media_probe_keys(self, state):
        """Index 0 first, then every wanted key not confirmed in this connection."""
        keys = []
        for index, (key, _payload) in enumerate(state.wanted):
            if (index == 0 or key not in state.known) and key not in keys:
                keys.append(key)
                if len(keys) >= self.media_capability["haveKeys"]:
                    break
        return keys

    def _media_send(self, fields, *, kind, op, key=None, keys=None, expected=None, upload=None):
        ident = self.ready_id
        self._media_seq += 1
        seq = self._media_seq
        now = self.clock()
        line = {"seq": seq, "id": ident, "op": op, "kind": kind, "key": key, "keys": keys,
                "expected": expected, "bytes": len(upload["data"]) if upload else None, "upload": upload,
                "tick": self._media_next_tick(),
                "deadline": now + presentation.MEDIA_ACK_TIMEOUT_SECONDS,
                "expires": now + self.MEDIA_LINE_GRACE * presentation.MEDIA_ACK_TIMEOUT_SECONDS}
        self._write({"media": {"id": ident, **fields}}, media_seq=seq)
        self._media_lines.append(line)
        self._media_wait = line

    def _pop_media_line(self, match=None):
        """Retire the media line a reply answers (the oldest matching one, with older lost ones)."""
        now = self.clock()
        lines = self._media_lines
        while lines and lines[0]["expires"] <= now:
            lines.popleft()
        for position, line in enumerate(lines):
            if match is None or match(line):
                for _ in range(position + 1):
                    lines.popleft()
                return line
        return None

    def _media_line_error(self, message):
        """A bare parse/oversize error while a media line may still be answered is media-only.

        It answers that line (damaged before its `{"media"` prefix) or an earlier non-media
        line (a damaged frame), and replies carry no sequence number: so it never retires
        the line. The live line is reported as a parse failure (its retry scheduled as for
        any error) and then stays outstanding like a timed-out line: until a reply matches
        it or MEDIA_LINE_GRACE has passed no other media line is written, so a late reply
        of it is never credited to the next line (a `have` reply names no key). A line
        already reported (timed out, or mapped before) is left as it is; the error is then
        only logged (at most once a minute), so a damaged frame or request answered during
        a grace is never invisible.
        """
        text = message.get("error")
        if (self.media_capability is None or not isinstance(text, str)
                or not any(word in text.lower() for word in ARTWORK_LINE_ERRORS)):
            return False
        if not self._media_unanswered(self.clock()):
            return False  # no media line to map it to: as fatal as before
        wait = self._media_wait
        if wait is not None and any(line is wait for line in self._media_lines):
            self._media_wait = None
            self._media_failed(wait, "parse", maybe_handled=True)
        else:
            now = self.clock()
            if self._bare_error_logged is None or now - self._bare_error_logged >= _STRIP_LOG_SECONDS:
                self._bare_error_logged = now
                _log.info("Bare %s reply consumed while an already reported media line awaits its reply", text)
        return True

    def _media_ack(self, ack):
        if self.media_capability is None:
            return
        if ack.get("op") == "parse":  # id/key only when the knob's prefix scan found them
            def answers(line):
                return all(name not in ack or ack[name] == line[name] for name in ("id", "key"))
        else:
            def answers(line):
                return all(name not in ack or ack[name] == line[name] for name in ("id", "op", "kind", "key"))
        line = self._pop_media_line(answers)
        if line is not None:
            self._media_answered(line, ack, parse=ack.get("op") == "parse")

    def _media_answered(self, line, ack, *, parse=False):
        self._tx_read_through(line["seq"])
        current = self._media_wait is not None and self._media_wait["seq"] == line["seq"]
        if current:
            self._media_wait = None
        if parse:
            if current:
                self._media_failed(line, "parse")
            return  # a late reply to a line already reported as timed out
        error = ack.get("error")
        if error is not None:
            if not current:
                return
            if error == "Stale media control":
                self._media_stale(line)
            else:
                self._media_failed(line, error if isinstance(error, str) and error else "rejected")
            return
        self._media_success(line, ack, current)

    def _media_success(self, line, ack, current):
        state = self._media_kinds.get(line["kind"])
        if state is None:
            return
        op = line["op"]
        if op == "have":
            answers = ack.get("have")
            if not (isinstance(answers, list) and len(answers) == len(line["keys"])
                    and all(type(answer) is bool for answer in answers)):
                if current:
                    self._media_failed(line, "Invalid media reply")
                return
            contradicted = False
            for key, present in zip(line["keys"], answers):  # the knob touches hits in this order
                if present:
                    if key not in state.mirror:
                        state.hits += 1
                    state.touch(key, self._media_next_tick(), since=line["tick"])
                else:
                    contradicted |= key in state.mirror
                    state.forget(key)
                    state.known.add(key)  # known absent
            if contradicted:
                # The knob evicted a key the mirror listed: re-check every other wanted key.
                asked = set(line["keys"])
                state.known = {key for key in state.known if key in asked or key not in state.payloads}
            if (current or contradicted) and any(key not in state.known for key, _payload in state.wanted):
                state.probe = True  # more unconfirmed keys than one `have` holds
            self._media_trim(state)
            return
        offset = ack.get("offset")
        upload = line["upload"]
        live = current and upload is not None and upload is self._media_upload
        if not _integer(offset, 0, 0xFFFFFFFF):
            if live:
                self._media_failed(line, "Invalid media reply")
            return
        key = line["key"]
        if op in ("begin", "commit") and offset == line["bytes"]:
            if live:
                self._media_upload = None
            if live or key not in state.mirror:
                self._media_ready(state, key, hit=op == "begin", since=line["tick"])
            else:  # a late reply for a key already reported ready: no second event
                state.touch(key, self._media_next_tick(), since=line["tick"])
                self._media_trim(state)
            return
        if not live:
            return
        if op != "commit" and offset == line["expected"]:
            upload["offset"] = offset
            upload["stage"] = "commit" if offset == len(upload["data"]) else "data"
            return
        self._media_failed(line, "Invalid media reply")

    def _media_ready(self, state, key, *, hit, since):
        state.touch(key, self._media_next_tick(), since=since)
        self._media_trim(state)
        state.failures.pop(key, None)
        state.retry_at.pop(key, None)
        state.failed.discard(key)
        if hit:
            state.hits += 1
        else:
            state.uploads += 1
        self._emit("media-ready", media=state.kind, key=key, hit=hit)

    def _media_failed(self, line, reason, *, maybe_handled=False):
        """Timeout, error reply or parse mapping: presentation-only, never a disconnect.

        `maybe_handled`: a timeout or a bare error, after which the knob may still have
        handled the line (its reply lost or yet to come)."""
        state = self._media_kinds.get(line["kind"])
        if state is None:
            return
        if maybe_handled and line["op"] != "data":
            # Handled with its reply lost or late, or lost itself: the knob may have touched its keys.
            for key in line["keys"] or (line["key"],):
                state.touch(key, self._media_next_tick())
            self._media_trim(state)
        if line["op"] == "have":
            state.errors += 1
            state.last_error = reason
            self._emit("media-error", media=state.kind, key="", op="have", error=reason,
                       retrying=False, failed=False)
            return
        upload = line["upload"]
        if upload is None:
            return  # cancelled by a control change: not a failure of its key
        if upload is self._media_upload:
            self._media_upload = None
        key = line["key"]
        state.forget(key)
        state.errors += 1
        state.last_error = reason
        retrying = False
        if key in state.payloads and key not in state.failed:
            if state.failures.get(key, 0) >= 1:
                state.failed.add(key)  # second failure: not retried in this connection
                state.failures.pop(key, None)
                state.retry_at.pop(key, None)
            else:
                state.failures[key] = 1
                state.retry_at[key] = self.clock() + presentation.MEDIA_RETRY_SECONDS
                retrying = True
        self._emit("media-error", media=state.kind, key=key, op=line["op"], error=reason,
                   retrying=retrying, failed=key in state.failed)

    def _media_stale(self, line):
        """A "Stale media control" reply is never a failure: re-evaluate with the current ID."""
        upload = line["upload"]
        if upload is not None and upload is self._media_upload:
            self._media_upload = None
        if line["op"] == "have":
            self._media_kinds[line["kind"]].probe = True
        if line["id"] == self.ready_id:
            # The knob no longer holds this control (a release is on its way): pause.
            self._media_hold = self.clock() + presentation.MEDIA_RETRY_SECONDS

    # ------------------------------------------------------------------

    def _disconnect(self):
        error = None
        try:
            if self.serial is not None and self.control_id is not None:
                self._request({"release": True}, lambda m: m.get("released") is True)
        except Exception as exc:
            error = exc
        finally:
            if self.serial is not None:
                self.serial.close()
            self.serial = None
            self.decoder.reset()
            self._art_lines.clear()
            self._reset_control()
            self._media_reset()
            self._alive_reset()
            self._diag_reset()
            self._app_profile_reset()
            self._emit("disconnected")
        if error:
            raise error

    def _dispatch(self, command, value):
        """Run one command (None: nothing) on the bridge thread."""
        if command in ("connect", "inventory"):
            if command == "inventory" and self.serial is not None:
                self._emit("connected", profiles=deepcopy(self.profiles), current=self.current, capabilities=deepcopy(self.capabilities), port=self.port, backup=str(self.backup_path))
            else:
                self._connect(value)
        elif command == "enter":
            self._enter(value)
        elif command == "frame":
            self._frame(value)
        elif command == "artwork":
            self._queue_artwork(value)
        elif command == "recalibrate":
            self._recalibrate(value)
        elif command == "app_profile":
            self._app_profile_queue(value)
        elif command == "media":
            self._media_wanted(*value)
            self._media_publish()
        elif command == "disconnect":
            self._disconnect()
        elif command == "close":
            self._closing = True
            self._disconnect()

    def _service(self):
        """One pass of the port: heartbeat, replies, then at most one art or media line."""
        if self.serial is not None:
            self._heartbeat()
            self._read()
            self._diag_step()
            self._artwork_step()
            self._app_profile_step()
            if self.media_capability is not None:
                try:
                    self._media_step()
                except OSError:
                    raise
                except Exception as exc:  # presentation-only: never an `error` event or a disconnect
                    self._media_fault(exc)
                self._media_publish()

    def _run(self):
        while not self._closing:
            try:
                try:
                    command, value = self._next_command()
                except queue.Empty:
                    command, value = None, None
                self._dispatch(command, value)
                self._service()
            except Exception as exc:
                # DD-BUG-004: a refused control is not a link failure; say so, so no consumer retries it.
                details = {"retry": False, **exc.details} if isinstance(exc, ControlRefused) else {}
                self._emit("error", message=str(exc), error=getattr(exc, "error_name", type(exc).__name__), **details)
                if isinstance(exc, (OSError, TimeoutError)) and self.serial is not None:
                    try:
                        self._disconnect()
                    except Exception:
                        pass
                elif command in ("enter", "frame") and self.control_id is not None:
                    # A rejected new binding must not leave an older binding armed
                    # while the desktop displays an error/new target.
                    try:
                        self._request({"release": True}, lambda m: m.get("released") is True)
                    except Exception:
                        try:
                            self._disconnect()
                        except Exception:
                            pass
                    finally:
                        self._reset_control()
        self.closed = True
        self._emit("closed")

    def _next_command(self):
        """Keep the latest adjacent presentation; never cross a control boundary."""
        if self._deferred_command is not None:
            command, value = self._deferred_command
            self._deferred_command = None
        else:
            command, value = self.commands.get(timeout=0 if self._busy() else 0.02)
        if command == "frame" and isinstance(value, dict):
            while True:
                try:
                    following = self.commands.get_nowait()
                except queue.Empty:
                    break
                if (following[0] != "frame" or not isinstance(following[1], dict)
                        or following[1].get("id") != value.get("id")):
                    self._deferred_command = following
                    break
                value = following[1]
        return command, value

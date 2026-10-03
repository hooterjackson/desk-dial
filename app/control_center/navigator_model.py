"""The r3 Navigator's content and visibility (r3 README section 5, 1.2, 2.2, 4; DESKTOP_STAGE section 24).

Pure Python: no Tk, no PIL, no Win32. Two steps, so the controller is only ever *read*:

1. ``read_snapshot(controller, frame)`` - the read-only adapter. It copies what the Navigator
   shows out of the controller's public state (``screen``, ``state``, ``lights``, ``recent``,
   ``display_volume`` / ``display_bri`` / ``display_kelvin``, ``lights_mode``) and out of the
   decorated frame the Tk tick already renders for the floating knob (title, meta, buttons, the
   reveal layouts), into a plain dict of primitives. It never calls a method that changes state
   and never raises (a missing field reads as empty). The Tracks rows' titles come from the
   controller's read-only ``queue_titles(rows)``.
2. ``build_content(snapshot, pressed=None)`` - the Navigator's content for that snapshot
   (``NavContent``): the kind of card, the path row, the per-kind fields and the 2 x 2 keys grid.

r3.1 (2026-09-29 feedback round; Claude Design r3.1, ``Knob IA Prototype r3.1.dc.html``): the
launcher in its lights domain (hold 4) shows the Lights card under ``Home › <area>``; the Lights card
adds the area line (``3 lights · 2 on · 1 unavailable``), one row per light and the blocked states;
Recently Added on its Favourite playlists source is ``Music › Playlists`` (``Favourite playlist``,
covers from ``scene_music.explorer_plan(item, "favourites")``: the 2 x 2 mosaic); whole-queue Tracks
centres its rows on the focus; Scenes rows carry their kind; the HOLD row replaces ``Hold 1 for
Home`` with key chips (``1 Home``, ``4 Knob to lights`` / ``4 Knob to music`` / ``4 Queue`` /
``4 Play next``) that fill with the hold's progress, and key 4 no longer fills on a press.

``Visibility`` holds the section 5 rules: appears on any turn or press; auto-hides 4 s after the
last input at Home and the space roots; stays while in Recently Added, Tracks (Seek), Scenes or
the temperature knob mode; hidden while a full-screen overlay is open, while the knob is away and
with the setting Off; always shown (with content) when Pinned.

``applies(runtime)``: the Navigator replaces the floating knob only for an r3 knob
(``presentation >= 6``); older knobs keep the floating knob.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

NAVIGATOR_PRESENTATION = 6
MODES = ("auto", "pinned", "off")
DEFAULT_MODE = "auto"
AUTO_HIDE_S = 4.0                 # section 5: after the last input at Home and the space roots
STICKY_HIDE_S = 20.0              # user 2026-09-29: the list screens stay up while browsing, but never forever
PRESS_FLASH_S = 0.22              # a pressed key's white fill (the knob's buttons send presses only)
ROW_OFFSETS = (-2, -1, 0, 1, 2)   # the five visible rows (38 u each) around the focus
COVER_OFFSETS = (-2, -1, 0, 1, 2)

KELVIN_MIN, KELVIN_MAX = 2200, 6500
WHITE = (255, 255, 255)
GREEN_TAG = (0x6E, 0xD9, 0x96)    # `Skip to` / `Back to`
RUNNING_TAG = (0x7E, 0xE0, 0xA2)  # `Running`
PLAYING_TITLE = (0x9C, 0xF0, 0xBC)
WARM = (0xFF, 0xBE, 0x69)
ERROR = (0xFF, 0x84, 0x74)
META_A = 0.70                     # meta 11/15 white 70 %
TAG_A = 0.60                      # the `Now` tag

# The depth of each controller mode (the prototype's DEP; `seek` is Tracks' knob mode).
DEPTH = {"launcher": 0, "home": 1, "windows": 1, "lights": 1, "recent": 2, "tracks": 2, "seek": 2,
         "scenes": 2, "explorer": 3, "upnext": 3, "onshape": 1}
PATHS = {"launcher": "Home", "home": "Music", "recent": "Music › Recently Added",
         "tracks": "Music › Tracks", "seek": "Music › Tracks › Seek", "lights": "Lights",
         "scenes": "Lights › Scenes", "onshape": "Onshape"}
KINDS = {"launcher": "now", "home": "now", "lights": "lights", "recent": "covers", "tracks": "rows",
         "seek": "seek", "scenes": "scenes"}
# A0 (ONSHAPE.md): Onshape mode has no Navigator card yet (no KINDS entry: build_content -> None, hidden);
# its fast path gives the Navigator no input while the mode is on. The card is A1 (the Navigator mirror).
# Modes with a full-screen overlay (or the picker) of their own: the Navigator is hidden there.
OVERLAY_MODES = ("explorer", "upnext", "windows")
STICKY_MODES = ("recent", "tracks", "seek", "scenes")
# The knob's short button labels -> the Navigator's words (section 5 "what 1-4 do now").
LABELS = {"Win": "Windows", "Temp": "Temperature", "Browse": "Music", "Recent": "Recent"}
# The prototype's key words per mode (P L808-836); None = the frame's label (it changes with state).
# r3.1: Recently Added 3 is the list's source toggle (the frame's `Playlists` / `Recent`), Tracks 4 the
# frame's `Skip` (transport) or `Play` (whole queue).
KEY_WORDS = {"launcher": ("Music", "Windows", "Lights", None), "home": ("Home", "Recent", "Tracks", None),
             "recent": ("Back", "Full screen", None, "Play"), "tracks": ("Back", "Up next", "Seek", None),
             "seek": ("Cancel", "Up next", "Set", "Play"), "lights": ("Home", "Scenes", "Temperature", None),
             "scenes": ("Back", "—", "—", "Run"), "onshape": ("Tilt", "Orbit", "Undo", "Pan")}
ART_FIELDS = ("kind", "art_template", "art_max", "art_bg", "art_ink", "sonos_art", "album")
# A favourite playlist's art identity (scene_music.playlist_plan): its mosaic once playlist_meta landed.
PLAYLIST_FIELDS = ("mosaic", "art_state", "first_art", "count", "empty")
HOLD_1 = "Hold 1 for Home"
HOLD_SECONDS = {"1": 0.6, "4": 1.0}   # the firmware's holds: button 1 600 ms, button 4 1000 ms
LIGHT_ON = (255, 255, 255)
LIGHT_OFF_A = 0.55
SCENE_KINDS = {"scene": "Scene", "script": "Script", "automation": "Automation"}


@dataclass(frozen=True)
class NavLight:
    """One light of the area (r3.1 Lights card): name, `80% · 3000 K` / `Off` / `Unavailable`."""
    name: str
    value: str
    value_rgb: tuple = WHITE
    value_a: float = 0.9
    dot_rgb: tuple = WHITE
    dot_a: float = 1.0


def applies(runtime) -> bool:
    """True for a knob that runs the r3 navigation (presentation >= 6): the Navigator replaces the
    floating knob. Never raises."""
    try:
        level = getattr(runtime, "presentation_level", None)
        if type(level) is int:
            return level >= NAVIGATOR_PRESENTATION
        # A runtime without the capability (a stand-in): the controller's r3 switch decides.
        return bool(getattr(getattr(runtime, "controller", None), "spaces", False))
    except Exception:
        return False


def normal_mode(value) -> str:
    return value if value in MODES else DEFAULT_MODE


def kelvin_rgb(kelvin) -> tuple:
    """README section 3's Kelvin -> RGB (Tanner Helland), clamped 0-255."""
    t = max(1000.0, float(kelvin)) / 100.0

    def cl(x):
        return int(round(max(0.0, min(255.0, x))))
    r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return cl(r), cl(g), cl(b)


def kelvin_frac(kelvin) -> float:
    return max(0.0, min(1.0, (float(kelvin) - KELVIN_MIN) / (KELVIN_MAX - KELVIN_MIN)))


def mmss(seconds) -> str:
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        s = 0
    return f"{s // 60}:{s % 60:02d}"


# --------------------------------------------------------------------------- content
@dataclass(frozen=True)
class NavKey:
    digit: str
    label: str
    enabled: bool = True
    pressed: bool = False


@dataclass(frozen=True)
class NavRow:
    key: str                      # stable identity (a row visual follows it across turns)
    offset: int                   # rows from the list's centre (the playing song / the focused scene)
    number: str
    title: str
    title_rgb: tuple = WHITE
    tag: str = ""
    tag_rgb: tuple = WHITE
    tag_a: float = TAG_A


@dataclass(frozen=True)
class NavCover:
    key: str
    offset: int                   # items from the focused one
    accent: int = 0x2A2A30
    art_key: str = ""


@dataclass(frozen=True)
class NavContent:
    kind: str                     # now | lights | covers | rows | seek | scenes
    mode: str                     # the controller mode it came from
    path: str
    depth: int
    sticky: bool
    keys: tuple = ()
    hold_hint: bool = False
    hold_text: str = ""               # r3.1: the HOLD row as text (``1 Home · 4 Queue``)
    holds: tuple = ()                 # r3.1: the HOLD chips ((digit, label, progress 0..1), ...)
    # now / seek / covers text
    title: str = ""
    artist: str = ""
    status: str = ""
    status_rgb: tuple = WHITE
    status_a: float = META_A
    art_key: str = ""
    accent: int = 0x2A2A30
    # now
    volume: int = 0
    volume_active: bool = False
    # lights
    caption: str = ""
    big: str = ""
    unit: str = ""
    bri: int = 0
    bri_frac: float = 0.0
    kelvin: int = 2700
    kelvin_rgb: tuple = (255, 169, 87)
    temp_frac: float = 0.0
    bri_a: float = 1.0
    temp_a: float = 1.0
    scene: str = ""
    lights_on: bool = True
    area_line: str = ""               # r3.1: `3 lights · 2 on · 1 unavailable`
    area_rgb: tuple = WHITE
    area_a: float = 0.75
    lights_rows: tuple = ()           # r3.1: NavLight per light of the area (r3.1.1: mixed / unavailable only)
    # r3.1.1 compact Lights card: the two value rows and the summary line
    bri_caption: str = "Brightness"   # `Brightness` / `Brightness · avg`
    bri_text: str = ""                # `62%` / `Off` / `—`
    temp_text: str = ""               # `3200 K` / `—`
    summary_bold: str = ""            # the running scene, else the area name (`Home Assistant` when not connected)
    summary_rest: str = ""            # `3 lights · 3 on` (+ ` · 1 unavailable`) or the blocked text
    summary_rgb: tuple = WHITE        # #FF8474 when a light is unavailable / not connected
    summary_rest_a: float = 0.75
    # covers / rows / scenes
    covers: tuple = ()
    rows: tuple = ()
    plate: int = 0                # plate position in rows (-1, 0, 1)
    # seek
    seek_frac: float = 0.0

    def geometry(self) -> str:
        """The kind as the card's geometry sees it: r3.1's Lights card with its area block is
        ``lights+N`` (N light rows)."""
        if self.kind == "lights":
            return f"lights+{len(self.lights_rows)}"       # r3.1.1: the rows only when mixed / unavailable
        return self.kind

    def layout_key(self):
        """What decides the card's geometry (its height): the kind (with the Lights area block) and
        the hold row."""
        return (self.geometry(), self.hold_hint)


def _text(value) -> str:
    return " ".join(str(value).split()) if isinstance(value, str) else ""


def _int(value, default=0) -> int:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else default
    except (TypeError, ValueError):
        return default


_log = logging.getLogger(__name__)
_SNAPSHOT_FAILURES_LOGGED = set()  # exception type names read_snapshot has logged (once each)


def read_snapshot(controller, frame) -> dict:
    """The read-only adapter (see the module docstring). ``frame`` is the decorated frame the Tk
    tick renders (``runtime.frame()``). Never raises; unknown fields read as empty."""
    snap = {"mode": "", "frame": {}, "state": {}, "index": 0, "spaces": False}
    try:
        c = controller
        frame = frame if isinstance(frame, dict) else {}
        screen = getattr(c, "screen", None)
        mode = getattr(screen, "mode", "") or ""
        snap["mode"] = mode
        snap["index"] = _int(getattr(screen, "index", 0))
        snap["spaces"] = bool(getattr(c, "spaces", False))
        snap["home_domain"] = getattr(c, "home_domain", "volume") if snap["spaces"] else "volume"
        hold_action = getattr(c, "hold_action", None)
        snap["hold4"] = _text(hold_action()) if callable(hold_action) else ""
        snap["loaded"] = _loaded(dict(getattr(c, "state", {}) or {}))
        keep = ("title", "subtitle", "status", "statusTone", "meta", "metaTone", "layout", "value", "valueUnit",
                "volumeCaption", "playing", "artKey", "heading")
        snap["frame"] = {k: frame.get(k) for k in keep if k in frame}
        snap["buttons"] = [dict(label=_text(b.get("label")), enabled=bool(b.get("enabled", True)),
                                lit=b.get("lit"), icon=b.get("icon"))
                           for b in (frame.get("buttons") or ()) if isinstance(b, dict)][:4]
        state = dict(getattr(c, "state", {}) or {})
        snap["state"] = {k: state.get(k) for k in ("title", "artist", "album", "playback", "position_s",
                                                   "duration_s", "volume", "online", "playlist_position",
                                                   "queue_length", "repeat", "queue_revision")}
        try:
            snap["volume"] = _int(c.display_volume)
        except Exception:
            snap["volume"] = _int(state.get("volume"))
        if mode in ("recent",):
            source = getattr(c, "list_source", "recent") if snap["spaces"] else "recent"
            source = source if source in ("recent", "favourites") else "recent"
            snap["list_source"] = source
            if source == "favourites":
                # r3.1: Favourite playlists (their playlist_meta merged in: count, mosaic, art state).
                fav = getattr(c, "favourites", None)
                items = list(getattr(fav, "items", None) or ())
                metas = dict(getattr(fav, "meta", None) or {})
                snap["recent"] = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    meta = metas.get(str(it.get("id", ""))) or {}
                    entry = {"id": _text(str(it.get("id", ""))), "title": _text(it.get("title")), "artist": "",
                             "accent": _int(meta.get("accent", it.get("accent")), 0x2A2A30), "year": "",
                             "kind": "playlist", **{f: it.get(f) for f in ART_FIELDS if f in it and f != "kind"}}
                    entry.update({f: meta[f] for f in PLAYLIST_FIELDS if f in meta})
                    snap["recent"].append(entry)
                snap["recent_state"] = getattr(fav, "state", "")
            else:
                lst = getattr(c, "recent", None)
                items = list(getattr(lst, "items", None) or ())
                snap["recent"] = [{"id": _text(str(it.get("id", ""))), "title": _text(it.get("title")),
                                   "artist": _text(it.get("artist")), "accent": _int(it.get("accent"), 0x2A2A30),
                                   "year": it.get("year") or it.get("release_year") or "",
                                   # the art identity the explorer uses (scene_music.cover_plan), read only
                                   **{f: it.get(f) for f in ART_FIELDS if f in it}}
                                  for it in items if isinstance(it, dict)]
                snap["recent_state"] = getattr(lst, "state", "")
        if mode == "seek":
            seek = getattr(screen, "seek", None)
            snap["seek"] = {"target": _int(getattr(seek, "target_s", 0)), "D": _int(getattr(seek, "D", 0))}
        if mode in ("tracks", "seek"):
            queue = False
            tracks_queue = getattr(c, "_tracks_queue", None)
            if mode == "tracks" and callable(tracks_queue):
                try:
                    queue = bool(tracks_queue())
                except Exception:
                    queue = False
            snap["tracks_queue"] = queue
            snap["neighbours"] = _queue_titles(c, state, centre=snap["index"] + 1 if queue else None)
        if mode in ("lights", "scenes", "launcher"):
            lights = getattr(c, "lights", None)
            if lights is not None:
                try:
                    bri, kelvin, on = c.display_bri, c.display_kelvin, c.lights_display_on()
                except Exception:
                    bri, kelvin, on = _int(getattr(lights, "bri", 0)), getattr(lights, "kelvin", None), \
                        bool(getattr(lights, "on", False))
                snap["lights"] = {
                    "online": bool(getattr(lights, "online", False)), "on": bool(on), "bri": _int(bri),
                    "kelvin": _int(kelvin, 2700) if kelvin is not None else 2700,
                    "supports_ct": bool(getattr(lights, "supports_ct", True)),
                    "scene_label": _text(getattr(lights, "scene_label", "")),
                    "scene_id": getattr(lights, "scene_id", None),
                    "adjusted": bool(getattr(lights, "adjusted", False)), "name": _text(getattr(lights, "name", "")),
                    "count": getattr(lights, "count", None),
                    "scenes": [{"id": s.get("entity_id", ""), "label": _text(s.get("label"))
                                or _text(str(s.get("entity_id", "")).split(".")[-1].replace("_", " ").capitalize()),
                                "running": bool(s.get("running")), "type": s.get("type") or "",
                                "bri": s.get("bri"), "kelvin": s.get("kelvin")}
                               for s in (getattr(lights, "scenes", None) or ()) if isinstance(s, dict)][:20],
                    "mode": getattr(c, "lights_mode", "bri")}
                block, area = None, None
                try:
                    block = c.lights_block()
                    area = c.lights_area()
                except Exception:
                    pass
                snap["lights"]["block"] = block
                if isinstance(area, dict):
                    snap["lights"]["area"] = {
                        "count": area.get("count"), "ok": area.get("ok"), "on": area.get("on"),
                        "bad": [_text(n) for n in area.get("bad") or ()], "mixed": bool(area.get("mixed")),
                        "members": [{"name": _text(m.get("name") or m.get("entity_id") or ""), "on": bool(m.get("on")),
                                     "bri": _int(m.get("bri")), "kelvin": _int(m.get("kelvin"), 0),
                                     "available": m.get("available", True) is not False}
                                    for m in area.get("members") or () if isinstance(m, dict)][:12]}
    except Exception as exc:
        # Never raises (the Tk tick); a partial snapshot is returned, marked, and the first failure
        # of each kind goes to app.log so an empty card is never silent (DD-RES-011).
        name = type(exc).__name__
        snap["error"] = name
        if name not in _SNAPSHOT_FAILURES_LOGGED:
            _SNAPSHOT_FAILURES_LOGGED.add(name)
            try:
                _log.warning("Navigator snapshot failed partway (%s); the card shows what was read",
                             name, exc_info=True)
            except Exception:
                pass
    return snap


def _loaded(state) -> bool:
    """Something is loaded on Sonos (the r3.1 design's `S.loaded`)."""
    return bool(state.get("playback") in ("PLAYING", "PAUSED_PLAYBACK") or state.get("title")
                or state.get("queue_length"))


def _queue_titles(c, state, centre=None) -> dict:
    """Queue titles for the rows P-2 .. P+2 (wrapping), read-only: the controller's accessor
    ``queue_titles(rows)`` (a dict row -> title, or a list in ``rows`` order). A row it does not
    know yet, or a controller without it, reads as absent ("—"). r3.1 whole-queue Tracks: the rows
    ``centre``-2 .. ``centre``+2 around the focus (1-based, no wrap)."""
    P, T = _int(state.get("playlist_position")), _int(state.get("queue_length"))
    if P <= 0 or T <= 0:
        return {}
    if centre is not None:
        rows = sorted({centre + d for d in ROW_OFFSETS if 1 <= centre + d <= T} - {P})
    else:
        rows = sorted({(P - 1 + d) % T + 1 for d in ROW_OFFSETS} - {P})
    fn = getattr(c, "queue_titles", None)
    if callable(fn):
        try:
            got = fn(rows)
            if isinstance(got, dict):
                return {int(k): _text(v) for k, v in got.items() if isinstance(v, str) and v.strip()}
            if isinstance(got, (list, tuple)):
                return {r: _text(v) for r, v in zip(rows, got) if isinstance(v, str) and v.strip()}
        except Exception:
            pass
    return {}


def _status_tone(tone):
    if tone == "error":
        return ERROR, 1.0
    if tone == "warm":
        return WARM, 1.0
    if tone == "secondary":
        return WHITE, 0.85
    return WHITE, META_A


def _keys(snap, pressed, kind):
    """The 2 x 2 grid: what buttons 1-4 do now (section 5; the prototype's words per mode, NV-17 ...
    NV-22), unavailable at 40 %, the pressed one filled. A ``None`` word takes the frame's own label
    (Play / Pause, All off / Turn on); availability always comes from the frame's buttons."""
    buttons = snap.get("buttons") or []
    words = KEY_WORDS.get(snap.get("mode", ""), (None, None, None, None))
    out = []
    for i in range(4):
        b = buttons[i] if i < len(buttons) else {"label": "", "enabled": False}
        label = words[i] if words[i] is not None else LABELS.get(b.get("label", ""), b.get("label", ""))
        if label == "Temperature" and b.get("lit") == "on":
            label = "Brightness"               # the lit Temp key returns the knob to brightness
        if snap.get("mode") == "launcher" and snap.get("home_domain") == "lights" and i == 3:
            lights = snap.get("lights") or {}
            label = "Lights off" if lights.get("on") else "Lights on"     # r3.1 design (Home's lights domain)
        enabled = bool(b.get("enabled", True)) and bool(label) and label != "—"
        if snap.get("mode") == "seek" and i == 3:
            enabled = False                    # Play is unavailable in Seek (NV-19)
        # r3.1 design: key 4 no longer fills on a press (its HOLD chip shows the hold).
        out.append(NavKey(str(i + 1), label or "—", enabled, pressed == i and i != 3))
    return tuple(out)


def _holds(snap, depth) -> tuple:
    """The r3.1 HOLD row: (digit, label, progress) chips; `1 Home` below the space roots and hold
    4's action where it exists. The progress is the pending press's time over the firmware's hold."""
    held = snap.get("held") or {}
    out = []
    if depth >= 2:
        out.append(("1", "Home", _progress(held.get(0), HOLD_SECONDS["1"])))
    word = _text(snap.get("hold4"))
    if word:
        out.append(("4", word, _progress(held.get(3), HOLD_SECONDS["4"])))
    return tuple(out)


def _progress(seconds, total) -> float:
    try:
        value = max(0.0, min(1.0, float(seconds) / total))
    except (TypeError, ValueError):
        return 0.0
    return round(value * 20) / 20.0                  # 5 % steps: a new chip sprite at most 20 times a hold


def _hold_text(holds) -> str:
    return " · ".join(f"{digit} {label}" for digit, label, _p in holds)


def _words(n) -> str:
    return "1 light" if n == 1 else f"{n} lights"


def _lights_block_card(lights, frame):
    """The Lights card's area block (r3.1 design): (area line, rgb, alpha, rows)."""
    block = lights.get("block")
    area = lights.get("area") or {}
    name = _text(lights.get("name")) or "the area"
    if block in ("nc", "area", "connecting"):
        line = {"nc": "Not connected · open Settings", "area": "Area not found",
                "connecting": "Connecting to Home Assistant"}[block]
        return line, (ERROR if block != "connecting" else WHITE), (1.0 if block != "connecting" else 0.75), ()
    members = area.get("members") or []
    rows = []
    for m in members:
        if not m.get("available", True):
            rows.append(NavLight(m.get("name", ""), "Unavailable", ERROR, 1.0, ERROR, 1.0))
        elif m.get("on"):
            k = m.get("kelvin") or 0
            value = f"{m.get('bri', 0)}% · {k} K" if k else f"{m.get('bri', 0)}%"
            rows.append(NavLight(m.get("name", ""), value, WHITE, 0.9, kelvin_rgb(k or 2700), 1.0))
        else:
            rows.append(NavLight(m.get("name", ""), "Off", WHITE, LIGHT_OFF_A, WHITE, 0.25))
    if block == "empty":
        return f"No lights in {name}", WHITE, 0.75, ()
    if block == "unav":
        return "All lights unavailable", ERROR, 1.0, tuple(rows)
    count = area.get("count")
    if count is None:
        return "", WHITE, 0.75, ()
    on = area.get("on")
    line = _words(count) + (f" · {on} on" if isinstance(on, int) else "")
    bad = area.get("bad") or []
    if bad:
        line += f" · {len(bad)} unavailable"
    return line, (ERROR if bad else WHITE), (1.0 if bad else 0.75), tuple(rows)


def build_content(snap: dict, pressed=None):
    """The Navigator content for a snapshot, or None where the Navigator has nothing to show
    (Windows, the explorer, Up next, an unknown mode). ``pressed``: the logical slot 0-3 whose key
    is filled now, or None."""
    mode = snap.get("mode", "")
    kind = KINDS.get(mode)
    if kind is None:
        return None
    if mode == "launcher" and snap.get("home_domain") == "lights":
        kind = "lights"                                  # r3.1: Home's knob sets the lights (hold 4)
    frame = snap.get("frame") or {}
    state = snap.get("state") or {}
    depth = DEPTH.get(mode, 1)
    lights = snap.get("lights") or {}
    # User 2026-09-29: the Lights card (brightness or temperature) hides AUTO_HIDE_S after the last touch;
    # the list screens hide STICKY_HIDE_S after it.
    temp_mode = mode == "lights" and lights.get("mode") == "temp"
    sticky = mode in STICKY_MODES
    path = PATHS.get(mode, "")
    area_name = _text(lights.get("name")) if lights.get("area", {}).get("count") is not None else ""
    if mode == "recent" and snap.get("list_source") == "favourites":
        path = "Music › Playlists"
    elif kind == "lights" and area_name:
        path = ("Home › " if mode == "launcher" else "Lights › ") + area_name     # r3.1 design
    elif mode == "scenes" and area_name:
        path = f"Lights › {area_name} › Scenes"
    holds = _holds(snap, depth)
    base = dict(mode=mode, path=path, depth=depth, sticky=sticky, keys=_keys(snap, pressed, kind),
                hold_hint=bool(holds), hold_text=_hold_text(holds), holds=holds)
    art_key = _text(frame.get("artKey"))
    tone_rgb, tone_a = _status_tone(frame.get("metaTone") or frame.get("statusTone"))

    if kind == "now":
        title = _text(state.get("title"))
        playback = state.get("playback")
        status = _text(frame.get("status"))
        status_rgb, status_a = _status_tone(frame.get("statusTone"))
        if snap.get("spaces") and not snap.get("loaded", True):
            # r3.1 design: nothing loaded (grey art, no status line).
            return NavContent(kind="now", title="Nothing playing", artist="Pick an album in Recent", status=status,
                              status_rgb=status_rgb, status_a=status_a, art_key="",
                              volume=max(0, min(100, _int(snap.get("volume")))),
                              volume_active=frame.get("layout") == "volume", **base)
        if not status:
            status_rgb, status_a = WHITE, META_A
            if playback == "PLAYING":
                pos, dur = _int(state.get("position_s")), _int(state.get("duration_s"))
                status = f"Playing · {mmss(pos)} of {mmss(dur)}" if dur > 0 else "Playing"
            elif playback in ("PAUSED_PLAYBACK", "STOPPED"):
                status = "Paused"
            elif not state.get("online"):
                status = "Sonos unavailable"
        return NavContent(kind="now", title=title or "Nothing playing", artist=_text(state.get("artist")) if title
                          else "", status=status, status_rgb=status_rgb, status_a=status_a, art_key=art_key,
                          volume=max(0, min(100, _int(snap.get("volume")))),
                          volume_active=frame.get("layout") == "volume", **base)

    if kind == "lights":
        on, online = bool(lights.get("on")), bool(lights.get("online"))
        bri, kelvin = max(0, min(100, _int(lights.get("bri")))), _int(lights.get("kelvin"), 2700)
        kelvin = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
        scene = lights.get("scene_label") or ""
        if scene and lights.get("adjusted"):
            scene += " · adjusted"
        caption, big, unit, bri_a, temp_a = "Brightness", str(bri), "%", 1.0, 0.5
        block = lights.get("block")
        mixed = bool((lights.get("area") or {}).get("mixed"))
        if block is not None or not online:
            # r3.1 design: blocked (Not connected / No lights / all unavailable), bars at 30 %.
            caption = "Home Assistant" if block in ("nc", None) else (_text(lights.get("name")) or "Lights")
            big, unit, bri_a, temp_a = "—", "", 0.3, 0.3
            scene = ""
        elif not on:
            caption, big, unit = "Lights", "Off", ""
        elif temp_mode:
            caption, big, unit, bri_a, temp_a = "Colour temperature", str(kelvin), "K", 0.5, 1.0
        if on and mixed and block is None and online:
            caption += " · average"
        line, line_rgb, line_a, rows = _lights_block_card(lights, frame)
        # r3.1.1 compact card: the value lives on its bar row; scene + area merge into one summary line;
        # the per-light rows only when the area is mixed or a light is unavailable.
        blocked = block is not None or not online
        area = lights.get("area") or {}
        name = _text(lights.get("name")) or "Lights"
        bri_caption = "Brightness · avg" if on and mixed and not blocked else "Brightness"
        bri_text = "—" if blocked else (f"{bri}%" if on else "Off")
        temp_text = "—" if blocked else f"{kelvin} K"
        if not blocked and not on:
            bri_a, temp_a = 1.0, 0.5
        if blocked:
            bold = "Home Assistant" if block in ("nc", "connecting", None) else name
            rest = line
        else:
            label = _text(lights.get("scene_label"))
            bold = label if label and not lights.get("adjusted") else name
            rest = line
        bad = bool(area.get("bad")) or block == "unav"
        red = line_rgb == ERROR
        if not (mixed or bad):
            rows = ()
        return NavContent(kind="lights", caption=caption, big=big, unit=unit, bri=bri,
                          bri_frac=(bri / 100.0) if on and block is None else 0.0, kelvin=kelvin,
                          kelvin_rgb=kelvin_rgb(kelvin), temp_frac=kelvin_frac(kelvin), bri_a=bri_a, temp_a=temp_a,
                          scene=scene or "—", lights_on=on, area_line=line, area_rgb=line_rgb, area_a=line_a,
                          lights_rows=rows, bri_caption=bri_caption, bri_text=bri_text, temp_text=temp_text,
                          summary_bold=bold, summary_rest=rest, summary_rgb=ERROR if red else WHITE,
                          summary_rest_a=1.0 if red else 0.75, **base)

    if kind == "covers":
        items = snap.get("recent") or []
        index = max(0, min(len(items) - 1, _int(snap.get("index")))) if items else 0
        covers = []
        for d in COVER_OFFSETS:
            j = index + d
            if 0 <= j < len(items):
                it = items[j]
                covers.append(NavCover(key=it.get("id") or f"item-{j}", offset=d, accent=_int(it.get("accent"),
                                                                                            0x2A2A30),
                                       art_key=art_key if d == 0 else ""))
        cur = items[index] if items else {}
        status = _text(frame.get("meta"))
        favourites = snap.get("list_source") == "favourites"
        if not favourites and frame.get("metaTone", "meta") == "meta" and status:
            # r3.1 design: `{i} / {n} · {year}` (the knob's line carries the artist instead).
            position = status.split(" · ")[0]
            year = cur.get("year")
            status = f"{position} · {year}" if year and "/" in position else position
        return NavContent(kind="covers", title=_text(frame.get("title")) or _text(cur.get("title")),
                          artist=("Favourite playlist" if favourites else "") or _text(frame.get("subtitle"))
                          or _text(cur.get("artist")), status=status,
                          status_rgb=tone_rgb, status_a=tone_a, covers=tuple(covers), art_key=art_key,
                          accent=_int(cur.get("accent"), 0x2A2A30), **base)

    if kind == "rows" and snap.get("tracks_queue"):
        return _queue_rows(snap, frame, state, base, tone_rgb, tone_a)

    if kind == "rows":
        P, T = _int(state.get("playlist_position")), _int(state.get("queue_length"))
        index = max(0, min(2, _int(snap.get("index"), 1)))
        pos = index - 1                                  # -1 previous, 0 now, +1 next
        neighbours = snap.get("neighbours") or {}
        rows = []
        if T > 0 and P > 0:
            used = set()
            for d in sorted(ROW_OFFSETS, key=lambda v: (abs(v), -v)):   # 0, +1, -1, +2, -2
                n = (P - 1 + d) % T + 1                  # wrap-around at the queue's ends (the prototype)
                if n in used:                            # a queue shorter than five rows shows each once
                    continue
                used.add(n)
                playing = d == 0
                title = _text(state.get("title")) if playing else neighbours.get(n, "")
                target = pos != 0 and d == pos
                tag, tag_rgb, tag_a = "", WHITE, TAG_A
                if target:
                    tag, tag_rgb, tag_a = ("Skip to" if pos > 0 else "Back to"), GREEN_TAG, 1.0
                elif playing:
                    tag = "Now"
                rows.append(NavRow(key=f"row-{n}", offset=d, number="♪" if playing else str(n),
                                   title=title or "—", title_rgb=PLAYING_TITLE if playing else WHITE,
                                   tag=tag, tag_rgb=tag_rgb, tag_a=tag_a))
            rows.sort(key=lambda r: r.offset)
        else:
            rows.append(NavRow(key="row-now", offset=0, number="♪",
                               title=_text(state.get("title")) or "Nothing playing", title_rgb=PLAYING_TITLE,
                               tag="Now"))
        meta, tone = _text(frame.get("meta")), frame.get("metaTone") or "meta"
        if tone in ("error", "warm", "secondary") or meta in ("Skipping…",):
            status = meta                              # a message replaces the status line (NV-24)
        else:
            status, tone_rgb, tone_a = ("Press 4 to skip" if pos else "Turn for previous or next"), WHITE, META_A
        return NavContent(kind="rows", rows=tuple(rows), plate=pos, status=status, status_rgb=tone_rgb,
                          status_a=tone_a, title=_text(state.get("title")), **base)

    if kind == "seek":
        seek = snap.get("seek") or {}
        target, D = _int(seek.get("target")), max(1, _int(seek.get("D"), 1))
        return NavContent(kind="seek", title=_text(frame.get("title")) or _text(state.get("title")),
                          big=mmss(target), unit=f"of {mmss(D)}", seek_frac=max(0.0, min(1.0, target / D)),
                          art_key=art_key, status=_text(frame.get("meta")), status_rgb=tone_rgb, status_a=tone_a,
                          **base)

    # scenes
    scenes = lights.get("scenes") or []
    index = max(0, min(len(scenes) - 1, _int(snap.get("index")))) if scenes else 0
    rows = []
    for j, s in enumerate(scenes):
        d = j - index
        if abs(d) > 2:
            continue
        running = s.get("running") or (s.get("id") and s.get("id") == lights.get("scene_id")
                                       and not lights.get("adjusted") and lights.get("on"))
        kind_tag = SCENE_KINDS.get(str(s.get("type") or "").lower(), "")    # r3.1 design: the row's kind
        rows.append(NavRow(key=f"scene-{s.get('id') or j}", offset=d, number=str(j + 1), title=s.get("label") or "",
                           tag="Running" if running else kind_tag, tag_rgb=RUNNING_TAG if running else WHITE,
                           tag_a=1.0 if running else 0.55))
    status = _text(frame.get("meta")) if frame.get("metaTone") in ("error", "warm") else ""
    status_rgb, status_a = (tone_rgb, tone_a) if status else (WHITE, META_A)
    if not scenes:
        status = "No scenes set up"
    if not status:
        focus = scenes[index] if scenes else {}
        status = "Press 4 to run"
        if type(focus.get("bri")) is int and type(focus.get("kelvin")) is int:
            status += f" · {focus['bri']}% · {focus['kelvin']} K"
        elif type(focus.get("bri")) is int:
            status += f" · {focus['bri']}%"
    return NavContent(kind="scenes", rows=tuple(rows), plate=0, status=status,
                      status_rgb=status_rgb, status_a=status_a, **base)


def _queue_rows(snap, frame, state, base, tone_rgb, tone_a):
    """r3.1 whole-queue Tracks: five rows centred on the focus (no wrap), the playing row ``♪`` /
    ``Now``, the focus on the plate tagged ``Skip to`` / ``Back to`` when it is another row."""
    P, T = _int(state.get("playlist_position")), _int(state.get("queue_length"))
    focus = max(1, min(T, _int(snap.get("index")) + 1)) if T > 0 else 1
    neighbours = snap.get("neighbours") or {}
    rows = []
    for d in ROW_OFFSETS:
        n = focus + d
        if not 1 <= n <= T:
            continue
        playing = n == P
        title = _text(state.get("title")) if playing else neighbours.get(n, "")
        tag, tag_rgb, tag_a = "", WHITE, TAG_A
        if d == 0 and not playing:
            tag, tag_rgb, tag_a = ("Skip to" if n > P else "Back to"), GREEN_TAG, 1.0
        elif playing:
            tag = "Now"
        rows.append(NavRow(key=f"row-{n}", offset=d, number="♪" if playing else str(n), title=title or "—",
                           title_rgb=PLAYING_TITLE if playing else WHITE, tag=tag, tag_rgb=tag_rgb, tag_a=tag_a))
    meta, tone = _text(frame.get("meta")), frame.get("metaTone") or "meta"
    if tone in ("error", "warm", "secondary") or meta in ("Skipping…",) or meta.startswith("Playing "):
        status = meta                                  # a message replaces the status line (NV-24)
    else:
        status = "Turn to browse the queue" if focus == P else f"{focus} / {T} · Press 4 to play"   # r3.1 design
        tone_rgb, tone_a = WHITE, META_A
    return NavContent(kind="rows", rows=tuple(rows), plate=0, status=status, status_rgb=tone_rgb, status_a=tone_a,
                      title=_text(state.get("title")), **base)


# --------------------------------------------------------------------------- visibility
@dataclass
class Visibility:
    """Section 5's show / hide rules on a monotonic clock (seconds)."""
    mode: str = DEFAULT_MODE
    last_input: float | None = None
    history: list = field(default_factory=list)

    def note_input(self, now: float):
        self.last_input = float(now)

    def set_mode(self, mode):
        self.mode = normal_mode(mode)

    def visible(self, now: float, content, *, overlay_open=False, connected=True) -> bool:
        if content is None or self.mode == "off" or overlay_open or not connected:
            return False
        if self.mode == "pinned":
            return True
        return self.last_input is not None and now - self.last_input < self._hide_after(content)

    @staticmethod
    def _hide_after(content) -> float:
        return STICKY_HIDE_S if content.sticky else AUTO_HIDE_S

    def next_change(self, now: float, content, *, overlay_open=False, connected=True):
        """Seconds until ``visible`` can turn False by itself (the auto-hide), or None."""
        if not self.visible(now, content, overlay_open=overlay_open, connected=connected):
            return None
        if self.mode == "pinned" or self.last_input is None:
            return None
        return max(0.0, self.last_input + self._hide_after(content) - now)

"""The Music explorer and Up next: the pure scene model (DESKTOP_STAGE K4 §7, §8, §13, §16, §18;
CONTROL_CENTER_V5 K3 §5.3, §5.6, §9.7.3, §11; VOC §7.1, §9).

Pure Python: no stage import, no PIL, no Tk, no I/O. The stage scenes (the ``scenes`` package
inside the stage) bind these tables and rules to DirectComposition visuals; the PIL renderer
(``render_music``) draws the sprites they name; the tests check the maths (H8).

Units are px of the 1280 x 720 reference stage; physical px = units x k (``layout`` is any object
with ``k``, ``sx0``, ``sy0``, ``W``, ``H`` and ``wide``, e.g. ``stage.layout.StageLayout``).
Every rest position is rounded to whole physical px (§0.3).

Contents:
- the explorer tables (16:9 and 32:9, §7.2), card slots, z-order, the hit rect, the dots window
  (DOTS_CAP 82 with fading ends, S5-9), the preload window (±12 / ±6 + 4 ahead, §7.7), the L0 set,
  build priority, loading placeholders (S5-11), the label, tab, hints and state-block copy;
- the Up next table (§8.2), rows (tag, lead, sub, the four [r2.2] heart states with their
  precedence), the plate and column geometry, the hints and the shuffle line;
- the art plan of an item (§13.1, §13.5, §13.6; S5-12, K4 §22 Q1): which art state, which rung;
- every motion duration of §7.6 / §8.5 / §16 as named constants.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

# --------------------------------------------------------------------------- copy (VOC §9)
COPY = {
    "overlay.explorer.tab_recent": "Recently Added",
    "overlay.explorer.tab_favourites": "Favourite playlists",
    "overlay.explorer.sub_favourite": "Favourite playlist",
    "overlay.explorer.sub_favourite_auto": "Favourite playlist · made by Apple Music",
    "overlay.explorer.untitled": "Untitled playlist",
    "overlay.explorer.empty_title": "No favourite playlists yet",
    "overlay.explorer.empty_help": "Star a playlist in the Music app. It appears here within a few minutes.",
    "overlay.explorer.recent_empty_title": "Nothing recently added",
    "overlay.explorer.recent_empty_help": "Add an album or a playlist to your library in the Music app.",
    "overlay.explorer.error_title": "Library not loaded",
    "overlay.explorer.error_help": "Go Home, then Browse to retry.",
    "overlay.explorer.signin_title": "Apple Music sign-in expired",
    "overlay.explorer.signin_help": "Open Settings on your PC to sign in again.",
    "overlay.upnext.header": "Up next",
    "overlay.upnext.tag_now": "Now playing",
    "overlay.upnext.tag_played": "Played",
    "overlay.upnext.tag_next": "Up next",
    "overlay.upnext.shuffle_on": "Shuffle on",
    "overlay.upnext.shuffle_off": "In order",
    "overlay.upnext.shuffle_sonos": "Shuffle on · Sonos picks the order",
    "overlay.upnext.card_title": "Sonos is shuffling the rest",
    "overlay.upnext.card_sub": "{n} songs · order isn’t shown",
    "overlay.upnext.row_not_catalog": " · not in Apple Music",
}
# overlay.explorer.hints / overlay.upnext.hints (VOC §9.3; [r2.2] `Liked` on a liked row)
EXPLORER_HINTS = (("1", "Back"), ("2", "Recently Added"), ("3", "Playlists"), ("4", "Play"))


def upnext_hints(shuffle_on: bool, liked: bool):
    return (("1", "Back"), ("2", "Shuffle off" if shuffle_on else "Shuffle"),
            ("3", "Liked" if liked else "Like"), ("4", "Play"))


# BS `I` glyphs (24-unit viewBox, stroke 2, round caps and joins)
GLYPHS = {
    "clock": "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    "queue": "M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3",
    "shuffle": ("M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22M18 2l4 4-4 4M2 6h1.9c1.5 0 2.9.9 "
                "3.6 2.2M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8M18 14l4 4-4 4"),
    "heart": "M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z",
    "note": "M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
}
TAB_GLYPH = {"recent": "clock", "favourites": "queue"}      # BS:489, :491 (`I.queue` = playlists)
TAB_KEY = {"recent": "2", "favourites": "3"}
TAB_LABEL = {"recent": COPY["overlay.explorer.tab_recent"], "favourites": COPY["overlay.explorer.tab_favourites"]}
SOURCES = ("recent", "favourites")

# --------------------------------------------------------------------------- motion (App A; §7.6, §8.5, §16)
ROOT_FADE_MS = 340
ENTER_MS, ENTER_OPACITY_MS, STAGGER_MS = 440, 320, 45
TURN_MS, TURN_OPACITY_MS, SHADE_MS, SHADOW_MS = 420, 300, 320, 320
L0_MS = 420                                   # S5-28: the level crossfade on the turn curve
MARKER_MS = 420
LABEL_FADE_MS = 160
AMBIENT_MS, AMBIENT_DEBOUNCE_MS = 600, 200
BUMP_LEG_MS, BUMP_UNITS = 160, 14
EXIT_MS = 170                                 # source switch / state change: IN
SWITCH_ENTRY_MS = 190                         # the new source's entry, anchored to t0
TAB_LABEL_MS, TAB_UNDERLINE_MS = 240, 320
PLAY_GROW_MS, PLAY_GROW = 380, 1.12
PLAY_OTHERS_MS = 300
ART_READY_MS = 240
BLOCK_FADE_MS = 160
REDUCED_OPACITY_MS = 200                      # §16: every card and row opacity change
# Up next
U_LEFT_RISE_MS, U_LEFT_OPACITY_MS, U_LEFT_RISE_UNITS = 460, 320, 20
U_ENTER_MS, U_ENTER_OPACITY_MS, U_STAGGER_MS, U_ENTER_UNITS = 420, 300, 40, 40
U_PLATE_MS = 320
U_TURN_MS, U_TURN_OPACITY_MS = 420, 300
U_COVER_MS, U_COVER_DEBOUNCE_MS = 420, 120
U_SHUFFLE_EXIT_MS, U_SHUFFLE_ENTRY_MS = 160, 200
U_SHUFFLE_LINE_MS = 240                       # EASE (S5-8)
U_PLAY_GROW_MS, U_PLAY_GROW = 420, 1.06       # S5-7
U_PLAY_PLATE_MS = 320
U_ROW_DATA_MS = 160
HEART_OPACITY_MS = 200
HEART_POP = ((0, 1.5, 380, "SPR"), (420, 1.0, 380, "SPR"))   # 0.4 -> 1.5 -> 1, per leg (S5-31)
HEART_FROM = 0.4
SHARPEN_DELAY_MS, SHARPEN_FADE_MS = 150, 120  # §8.6 (AR-17)
AMBIENT_OPACITY = {"explorer": 0.50, "upnext": 0.45}

# --------------------------------------------------------------------------- explorer geometry (§7.2)
CARD_UNITS = 340
CARD_CX, CARD_CY = 640, 318
L1_UNITS, L0_UNITS = 170, 340                 # S5-28 cover levels
RISE_UNITS, ENTER_SCALE = 30, 0.9
SHADOW_SIDE = (16, 36, 0.40)                  # y, blur, alpha (units)
SHADOW_FOCUS = (40, 80, 0.55)
SHADE_RGB = (0x0B, 0x0B, 0x0C)
LIST_LOADING_RGB = (0x23, 0x23, 0x25)         # art.list_loading, S5-11
INSET_ALPHA = 0.12
LABEL_LEFT, LABEL_TOP, LABEL_W, LABEL_H = 190, 514, 900, 88
DOTS_TOP, DOT_UNITS, DOT_PITCH, DOT_OPACITY = 622, 6, 14, 0.40
DOTS_CAP = (1280 - 128 + 8) // DOT_PITCH      # 82 (S5-9)
DOTS_HALF = DOTS_CAP // 2                     # 41
DOT_END_FADES = (0.10, 0.20, 0.30)            # outermost first
HINTS_TOP = 664
TABS_TOP = 44
BLOCK_LEFT, BLOCK_TOP, BLOCK_W = 340, 250, 600
PRELOAD = {True: 12, False: 6}                # §7.7 / §18: wide ±12, 16:9 ±6
PRELOAD_AHEAD = 4


@dataclass(frozen=True)
class Table:
    x: tuple
    s: tuple
    o: tuple
    sh: tuple

    @property
    def a_max(self) -> int:
        return len(self.x) - 1


TABLE_16x9 = Table(x=(0, 300, 470, 590, 660), s=(1.00, 0.60, 0.42, 0.30, 0.22), o=(1.0, 0.92, 0.55, 0.0, 0.0),
                   sh=(0.0, 0.24, 0.48, 0.60, 0.60))
TABLE_32x9 = Table(x=(0, 300, 500, 680, 850, 1010, 1170, 1330, 1490),
                   s=(1.00, 0.60, 0.46, 0.42, 0.40, 0.40, 0.40, 0.40, 0.40),
                   o=(1.0, 0.92, 0.84, 0.76, 0.68, 0.60, 0.54, 0.50, 0.0),
                   sh=(0.0, 0.24, 0.34, 0.42, 0.48, 0.52, 0.55, 0.58, 0.60))


def explorer_table(wide: bool) -> Table:
    return TABLE_32x9 if wide else TABLE_16x9


def sign(v) -> int:
    return (v > 0) - (v < 0)


def upx(layout, units) -> int:
    """Whole physical px of a size in units."""
    return int(round(units * layout.k))


def stage_x(layout, x_units) -> float:
    return layout.sx0 + x_units * layout.k


def stage_y(layout, y_units) -> float:
    return layout.sy0 + y_units * layout.k


@dataclass(frozen=True)
class CardSlot:
    a: int
    x: int          # container left, physical px (the card's scale is about its centre)
    s: float
    o: float
    sh: float


def card_size(layout) -> int:
    return upx(layout, CARD_UNITS)


def card_rest_y(layout) -> int:
    return int(round(stage_y(layout, CARD_CY) - card_size(layout) / 2.0))


def card_slot(layout, table: Table, d: int) -> CardSlot:
    """§7.2: a = min(|d|, a_max), the slot's left in px (centre + sg·X·k − size/2), S, O, shade."""
    a = min(abs(d), table.a_max)
    cs = card_size(layout)
    x = int(round(stage_x(layout, CARD_CX) + sign(d) * table.x[a] * layout.k - cs / 2.0))
    return CardSlot(a, x, table.s[a], table.o[a], table.sh[a])


def card_rise_px(layout, s: float) -> float:
    """The enter rise, 30 units in the scaled space: 30·S·k px (§0.5 item 1)."""
    return RISE_UNITS * s * layout.k


def card_z_order(indices, focus: int, a_max: int):
    """Bottom to top: z = 20 − a (BS:1183); equal z keeps DOM order (the higher index on top)."""
    return sorted(indices, key=lambda i: (-min(abs(i - focus), a_max), i))


def card_hit_rect(layout):
    """The centre card's rest rect in host client px (§3, §7.2)."""
    cs = card_size(layout)
    x = int(round(stage_x(layout, CARD_CX) - cs / 2.0))
    y = card_rest_y(layout)
    return (x, y, x + cs, y + cs)


def in_range(i: int, focus: int, table: Table) -> bool:
    return abs(i - focus) <= table.a_max


def placeholder_indices(focus: int, count, a_max: int):
    """S5-11: the loading list fills the slots [focus − a_max, focus + a_max], clamped to
    [0, count − 1] when the count is known, else to >= 0."""
    lo = max(0, focus - a_max)
    hi = focus + a_max
    if isinstance(count, int):
        hi = min(hi, count - 1)
    return list(range(lo, hi + 1))


# --------------------------------------------------------------------------- dots (§7.4; S5-9, S5-10)
@dataclass(frozen=True)
class Dots:
    first: int
    count: int              # dots drawn
    left_fade: bool         # more items exist before the first dot
    right_fade: bool
    marker: int             # the focused dot, 0-based within the drawn row

    @property
    def key(self):
        return (self.count, self.left_fade, self.right_fade)


def dots_window(n, i) -> Dots:
    n = int(n or 0)
    if n <= 0:
        return Dots(0, 0, False, False, 0)
    i = max(0, min(n - 1, int(i)))
    if n <= DOTS_CAP:
        return Dots(0, n, False, False, i)
    first = max(0, min(i - DOTS_HALF, n - DOTS_CAP))
    return Dots(first, DOTS_CAP, first > 0, first + DOTS_CAP < n, i - first)


def dot_opacities(dots: Dots):
    """Per drawn dot: 0.40, with the 3 end dots at 0.30 / 0.20 / 0.10 where more items exist."""
    ops = [DOT_OPACITY] * dots.count
    if dots.left_fade:
        for j, op in enumerate(DOT_END_FADES):
            if j < dots.count:
                ops[j] = op
    if dots.right_fade:
        for j, op in enumerate(DOT_END_FADES):
            if j < dots.count:
                ops[dots.count - 1 - j] = op
    return ops


def dots_left_units(count: int) -> float:
    """BS `dots()`: the row starts at 640 − (n·14 − 8) / 2."""
    return 640 - (count * DOT_PITCH - 8) / 2.0


def marker_x(layout, dots: Dots) -> int:
    return int(round(stage_x(layout, dots_left_units(dots.count) + dots.marker * DOT_PITCH)))


# --------------------------------------------------------------------------- preload (§7.7, §13.4)
def preload_window(index: int, count, wide: bool, direction: int = 0):
    """(lo, hi) inclusive: ±12 (wide) / ±6 around the focus, plus 4 in the direction of travel,
    clamped to the list (``count`` None: open-ended at the top, clamped at 0)."""
    r = PRELOAD[bool(wide)]
    lo = index - r - (PRELOAD_AHEAD if direction < 0 else 0)
    hi = index + r + (PRELOAD_AHEAD if direction > 0 else 0)
    lo = max(0, lo)
    if isinstance(count, int):
        hi = min(hi, count - 1)
    return lo, hi


def l0_indices(index: int, count, direction: int = 0):
    """L0 (the 1200 rung) for |d| <= 2 plus the next item in the direction of travel (§7.7)."""
    out = [index + d for d in (-2, -1, 0, 1, 2)]
    if direction:
        out.append(index + 3 * sign(direction))
    n = count if isinstance(count, int) else None
    return [i for i in out if i >= 0 and (n is None or i < n)]


def build_order(index: int, lo: int, hi: int, direction: int = 0):
    """|d| ascending, the direction of travel first (§7.7, §13.4 item 1)."""
    dirn = sign(direction) or 1
    return sorted(range(lo, hi + 1), key=lambda i: (abs(i - index), 0 if sign(i - index) in (0, dirn) else 1, i))


# --------------------------------------------------------------------------- label and state block (§7.4)
def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def format_duration(duration_ms) -> str:
    """``{h} h {mm} min`` or ``{m} min``; "" when unknown (the K3 queue_context rule)."""
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms <= 0:
        return ""
    minutes = round(duration_ms / 60000)
    if minutes >= 60:
        return f"{minutes // 60} h {minutes % 60:02d} min"
    return f"{max(1, minutes)} min"


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def item_title(item: dict) -> str:
    title = str(item.get("title") or "").strip()
    if not title and item.get("kind") == "playlist":
        return COPY["overlay.explorer.untitled"]
    return title


def explorer_label(item: dict | None, source: str):
    """(title, sub, meta) of the label (§7.4; BS:1195): album sub ``{artist}``, meta ``{year} ·
    {n tracks}``; playlist sub ``Favourite playlist`` (``· made by Apple Music`` for the auto
    one), meta ``{n} songs · {h} h {mm} min``."""
    if not isinstance(item, dict):
        return "", "", ""
    title = item_title(item)
    if source == "favourites":
        sub = COPY["overlay.explorer.sub_favourite_auto" if item.get("auto") else "overlay.explorer.sub_favourite"]
        n = _int(item.get("count"))
        if n is None:
            n = _int(item.get("track_count"))
        parts = [_plural(n, "song", "songs")] if n is not None else []
        dur = format_duration(item.get("duration_ms"))
        if dur and parts:
            parts.append(dur)
        return title, sub, " · ".join(parts)
    sub = str(item.get("artist") or "")
    n = _int(item.get("track_count"))
    year = _int(item.get("year"))
    parts = []
    if year is not None:
        parts.append(str(year))
    if n is not None:
        parts.append(_plural(n, "song", "songs") if item.get("kind") == "playlist" else _plural(n, "track", "tracks"))
    return title, sub, " · ".join(parts)


def state_block(state: str, source: str):
    """(glyph, title, help) of the state block, or None when the state draws cards (§7.4, S5-33)."""
    glyph = TAB_GLYPH.get(source, "queue")
    if state == "empty":
        if source == "favourites":
            return glyph, COPY["overlay.explorer.empty_title"], COPY["overlay.explorer.empty_help"]
        return glyph, COPY["overlay.explorer.recent_empty_title"], COPY["overlay.explorer.recent_empty_help"]
    if state == "signin":
        return glyph, COPY["overlay.explorer.signin_title"], COPY["overlay.explorer.signin_help"]
    if state == "error":
        return glyph, COPY["overlay.explorer.error_title"], COPY["overlay.explorer.error_help"]
    return None


BLOCK_STATES = ("empty", "signin", "error")


# --------------------------------------------------------------------------- art plan (§13.1, §13.5, §13.6)
ART_LADDER = (240, 600, 1200)
EXTENDED_U = 1.5


def art_rung(need_px, art_max: int = 0, k: float = 2.0) -> int:
    """The smallest rung >= need ÷ 1.1 (2000 only when k > 3.5), capped at ``art_max`` (§13.1)."""
    ladder = ART_LADDER + ((2000,) if k > 3.5 else ())
    target = max(1.0, float(need_px)) / 1.1
    rung = next((v for v in ladder if v >= target), ladder[-1])
    am = _int(art_max)
    if am and am > 0:
        rung = min(rung, am)
    return rung


def is_extended(need_px, source_edge) -> bool:
    """§13.5: u = need ÷ source edge; u > 1.5 draws ``art.extended``."""
    edge = max(1, int(source_edge or 0))
    return float(need_px) / edge > EXTENDED_U


def extended_fraction(need_px, source_edge) -> float:
    """The cover's drawn edge as a fraction of the element: 1.5 × native, capped at 1 (the inset
    is (1 − f) / 2: 400 px on a 680 card 6 %, 300 px 17 %, Sonos 400 on the 760 cover 10.5 %)."""
    return min(1.0, EXTENDED_U * max(1, int(source_edge or 0)) / float(need_px))


def _h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class ArtPlan:
    """What an element shows (VOC §7.1 art state ids), from the item's §13.2 keys.

    ``kind``: ``cover`` (fetch ``source``, drawn ``art.full`` or ``art.extended`` by §13.5),
    ``mosaic`` (2 × 2 of ``sources``), ``single`` (one tile, full bleed), ``generated``
    (``title`` / ``artist``), ``pending`` (playlist meta not loaded yet: loading tile only),
    ``never`` (a source that never arrives: loading tile only, the simulator's ``loading``).
    ``key`` is the art identity (the same for every element that shows the same art)."""
    kind: str
    key: str
    sources: tuple = ()          # (template, art_max) or ("sonos", url)
    title: str = ""
    artist: str = ""
    bg: int = 0
    ink: int = 0


LOADING_EMPTY_BG, LOADING_EMPTY_INK = 0x232325, 0xF2F2F2


def loading_colours(item: dict):
    """``art.loading`` fill and ink: Apple ``bgColor`` / ``textColor1``; ``#232325`` / ``#F2F2F2``
    when Apple gave none (S5-11)."""
    bg = _int(item.get("art_bg")) or 0
    ink = _int(item.get("art_ink")) or 0
    if not bg:
        return LOADING_EMPTY_BG, LOADING_EMPTY_INK
    return bg, ink or LOADING_EMPTY_INK


def _template_source(desc: dict):
    t = desc.get("art_template") if isinstance(desc, dict) else None
    if isinstance(t, str) and t:
        return (t, _int(desc.get("art_max")) or 0)
    return None


def source_key(src) -> str:
    return "s:" + _h(src[1]) if src and src[0] == "sonos" else "t:" + _h(src[0])


def cover_plan(item: dict, *, title=None, artist=None, allow_sonos=True) -> ArtPlan:
    """An album, a song row or a Recently Added item: its template, else the row's Sonos
    ``/getaa`` URL, else the Generated sleeve (hash of title and artist, BS ``genOf``)."""
    title = item_title(item) if title is None else title
    artist = str(item.get("artist") or "") if artist is None else artist
    bg, ink = loading_colours(item)
    src = _template_source(item)
    if src is None and allow_sonos:
        s = item.get("sonos_art")
        if isinstance(s, str) and s:
            src = ("sonos", s)
    if src is None:
        return ArtPlan("generated", "g:" + _h(f"{title}|{artist}"), (), title, artist, bg, ink)
    if src[0].startswith("simulation://loading/"):
        return ArtPlan("never", source_key(src), (src,), title, artist, bg, ink)
    return ArtPlan("cover", source_key(src), (src,), title, artist, bg, ink)


def playlist_plan(item: dict) -> ArtPlan:
    """A favourite playlist (S01:302-304; S5-12; K4 §22 Q1 "always tracks-derived"): the 2 × 2
    mosaic of the first 4 distinct albums with art, else the first one full bleed, else the
    playlist's own art, else a Generated sleeve from the playlist title. Until ``playlist_meta``
    lands (no ``mosaic`` / ``art_state`` key) the loading tile shows."""
    title = item_title(item)
    bg, ink = loading_colours(item)
    mosaic = item.get("mosaic")
    if mosaic is None and "art_state" not in item:
        return ArtPlan("pending", "p:" + _h(str(item.get("id") or title)), (), title, "", bg, ink)
    tiles = [s for s in (_template_source(m) for m in (mosaic or ())) if s is not None]
    if len(tiles) >= 4:
        tiles = tiles[:4]
        return ArtPlan("mosaic", "m:" + _h("|".join(t[0] for t in tiles)), tuple(tiles), title, "", bg, ink)
    if tiles:
        return ArtPlan("single", "t:" + _h(tiles[0][0]), (tiles[0],), title, "", bg, ink)
    own = _template_source(item)
    if own is not None:
        return ArtPlan("cover", source_key(own), (own,), title, "", bg, ink)
    return ArtPlan("generated", "g:" + _h(f"{title}|"), (), title, "", bg, ink)


def explorer_plan(item: dict | None, source: str) -> ArtPlan | None:
    if not isinstance(item, dict):
        return None
    if source == "favourites" or (item.get("kind") == "playlist" and "mosaic" in item):
        return playlist_plan(item)
    return cover_plan(item)


def gen_index(title, artist) -> int:
    """BS ``genOf`` (BS:537; K4 §13.6), ported exactly (the same as ``artwork.gen_index``)."""
    x = 7
    for ch in f"{title or ''}|{artist or ''}":
        cp = ord(ch)
        unit = cp if cp < 0x10000 else 0xD800 + ((cp - 0x10000) >> 10)
        x = (x * 31 + unit) % 9973
    return x % 8


# --------------------------------------------------------------------------- Up next (§8)
U_ROW_LEFT, U_ROW_CY, U_ROW_W, U_ROW_H = 600, 320, 560, 88
U_QY = (0, 100, 176, 236, 284)
U_QS = (1.00, 0.78, 0.66, 0.58, 0.52)
U_QO = (1.0, 0.72, 0.46, 0.24, 0.0)
U_A_MAX = 4
U_PLAYED = 0.6
U_PLATE = (600, 276, 560, 88)
U_LEFT_X, U_LEFT_Y, U_COVER = 120, 120, 380
U_TEXT_TOP = U_LEFT_Y + U_COVER + 18          # 518
U_ROW_PAD, U_ROW_GAP, U_RIGHT_GAP = 20, 18, 12
U_LEAD_ART, U_LEAD_NUM, U_HEART = 56, 40, 20
U_TAG_NOW_RGB = (0x6E, 0xD9, 0x96)
U_HEART_RGB = (0xFF, 0x28, 0x5A)
U_COVER_BASE_RGB = (0x1B, 0x1B, 0x1D)
U_ROW_ART_NEED = 56                          # units (112 px at k = 2)
HEART_LOOKS = {"liked": (0.0, 0.0, 1.0), "not_liked": (0.45, 0.0, 0.0), "unknown": (0.0, 0.30, 0.0),
               "not_catalog": (0.15, 0.0, 0.0), "none": (0.0, 0.0, 0.0)}   # outline, dashed, filled


@dataclass(frozen=True)
class RowSlot:
    a: int
    y: int          # the row's top in px at rest (its centre line − 44 units), before the scale
    s: float
    o: float


def row_slot(layout, d: int, played: bool = False) -> RowSlot:
    a = min(abs(d), U_A_MAX)
    y = int(round(stage_y(layout, U_ROW_CY + sign(d) * U_QY[a]) - upx(layout, U_ROW_H) / 2.0))
    o = U_QO[a] * (U_PLAYED if played else 1.0)
    return RowSlot(a, y, U_QS[a], o)


def row_left(layout) -> int:
    return int(round(stage_x(layout, U_ROW_LEFT)))


def plate_rect(layout):
    x, y, w, h = U_PLATE
    left, top = int(round(stage_x(layout, x))), int(round(stage_y(layout, y)))
    return (left, top, left + upx(layout, w), top + upx(layout, h))


def row_tag(k: int, now: int):
    """(copy id, rgb, alpha) of the row tag (BS:1214-1215), or None."""
    if k == now:
        return "overlay.upnext.tag_now", U_TAG_NOW_RGB, 1.0
    if k < now:
        return "overlay.upnext.tag_played", (255, 255, 255), 0.70
    if k == now + 1:
        return "overlay.upnext.tag_next", (255, 255, 255), 0.70
    return None


def heart_state(row: dict | None, likes_known: bool, *, placeholder=False, card=False) -> str:
    """[r2.2] precedence (R22 BS:1222-1223): placeholder / card → not in Apple Music → not known
    yet → liked / not liked."""
    if placeholder or card or not isinstance(row, dict):
        return "none"
    if row.get("catalog") is False:
        return "not_catalog"
    liked = row.get("liked")
    if not likes_known or liked is None:
        return "unknown"
    return "liked" if liked else "not_liked"


def context_album_row(row: dict, context: dict | None) -> bool:
    """A row of the context album (album context, base segment): it shows its number and its
    sub is ``{artist}`` (BS:1210; K3 §9.7.3)."""
    if not isinstance(context, dict) or context.get("kind") != "album":
        return False
    seg = row.get("segment")
    if seg is not None:
        return seg == "base"
    return bool(row.get("album")) and row.get("album") == context.get("title")


def row_lead(row: dict | None, context: dict | None, *, placeholder=False, card=False) -> str:
    if card:
        return "none"
    if placeholder or not isinstance(row, dict):
        return "placeholder"
    return "number" if context_album_row(row, context) else "art"


def row_number(row: dict) -> str:
    n = _int(row.get("track_number"))
    return f"{n:02d}" if n is not None else ""


def row_texts(row: dict, context: dict | None):
    """(title, sub): ``{artist}`` on context-album rows, else ``{artist} · {album}``; a row that
    is not in Apple Music adds `` · not in Apple Music`` (S01:339)."""
    title = str(row.get("title") or "")
    artist = str(row.get("artist") or "")
    album = str(row.get("album") or "")
    if context_album_row(row, context) or not album:
        sub = artist
    else:
        sub = f"{artist} · {album}" if artist else album
    if row.get("catalog") is False:
        sub += COPY["overlay.upnext.row_not_catalog"]
    return title, sub


def card_texts(n):
    return COPY["overlay.upnext.card_title"], COPY["overlay.upnext.card_sub"].format(n=n if n is not None else 0)


def placeholder_bar_width(k: int) -> float:
    """BS:1215: the first bar is (40 + (k·37) mod 40) % of the text column."""
    return (40 + (k * 37) % 40) / 100.0


def shuffle_line(shuffle: str):
    """(text, on) of the shuffle line (BS:1411): white when on (companion or Sonos), 0.60 off."""
    if shuffle == "sonos":
        return COPY["overlay.upnext.shuffle_sonos"], True
    if shuffle == "companion":
        return COPY["overlay.upnext.shuffle_on"], True
    return COPY["overlay.upnext.shuffle_off"], False


def big_cover_row(rows: dict, focus: int, now: int, context: dict | None):
    """The row whose album the big cover (and the ambient) shows (§8.4): the context album's
    (album context, the cover stays still) or the focused row's."""
    if isinstance(context, dict) and context.get("kind") == "album":
        cand = rows.get(now)
        if cand is not None and context_album_row(cand, context):
            return cand
        for k in sorted(rows):
            if context_album_row(rows[k], context):
                return rows[k]
        return cand if cand is not None else rows.get(focus)
    return rows.get(focus)


def big_cover_plan(row: dict | None) -> ArtPlan | None:
    if not isinstance(row, dict):
        return None
    return cover_plan(row, title=str(row.get("album") or row.get("title") or ""), artist=str(row.get("artist") or ""))


def row_art_plan(row: dict | None) -> ArtPlan | None:
    if not isinstance(row, dict):
        return None
    return cover_plan(row, title=str(row.get("album") or row.get("title") or ""), artist=str(row.get("artist") or ""))


def rows_by_index(rows) -> dict:
    """K3 rows (1-based ``row``) keyed by 0-based queue index."""
    out = {}
    for r in rows or ():
        if isinstance(r, dict) and isinstance(r.get("row"), int) and not isinstance(r.get("row"), bool):
            out[r["row"] - 1] = r
    return out

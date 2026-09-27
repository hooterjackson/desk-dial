"""Map knob-model.js states/views (tests/fixtures/knob_golden.json) to v4 frames.

The golden fixture is produced by tests/js/knob_golden.cjs from the design's
knob-model.js with NanoModel.COLORS pre-populated from
tests/fixtures/dominant_reference.json. This adapter turns each model state and
view into the presentation-v4 frame the host would send (PRESENTATION_V4.md
section 3 field map; renderers draw text verbatim) and turns the model's ring
and button lights into (rgb, level) cells on the contract's LEVELS scale.

Pure helpers only: no I/O except ``load_golden``.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import presentation  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "knob_golden.json"
MODEL_JS = ROOT / "design-reference" / "design_handoff_nano_d_artwork_color" / "knob-model.js"
REFERENCE = ROOT / "tests" / "fixtures" / "dominant_reference.json"
GOLDEN_JS = ROOT / "tests" / "js" / "knob_golden.cjs"

MODE = {"home": "VOLUME", "recent": "RECENTLY ADDED", "tracks": "TRACKS", "windows": "WINDOWS"}
TITLE_TONE = {"#F2F2F2": "ink", "#7C7C7C": "muted"}
LINE_TONE = {"#7C7C7C": "meta", "#A6A6A6": "secondary", "#FF8A7A": "error", "#7EE0A2": "success"}
# Stage 6 art fixtures (app/assets/fixtures/*.rgb565).
ART_DEN, ART_BRIGHT = "art-den-120", "art-bright-120"
ART_BRIGHT_CASE = "stress-long-accented-title-browsing"
PULSE_MS = presentation.PULSE_MS
OFF = (0, 0)


def load_golden(path=GOLDEN):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def color_int(text):
    """NanoModel colour string "r,g,b" -> 0xRRGGBB; None (no accent) -> 0."""
    if not text:
        return 0
    r, g, b = (int(part) for part in text.split(","))
    return (r << 16) | (g << 8) | b


def model_cells(model_ring):
    """Model ring ([["r,g,b", l] | null] x 60) -> contract cells (rgb, LEVELS[l]); off -> (0, 0)."""
    cells = []
    for entry in model_ring:
        if entry is None or not entry[1]:
            cells.append(OFF)
        else:
            cells.append((color_int(entry[0]), presentation.LEVELS[entry[1]]))
    return cells


def model_buttons(model_buttons_):
    """Model buttons ({c, l} x 4) -> (rgb, LEVELS[l]); dark -> (0, 0)."""
    return [OFF if not b["l"] else (color_int(b["c"]), presentation.LEVELS[b["l"]]) for b in model_buttons_]


class Adapter:
    """Model state + white view -> v4 frame, using the golden's injected colours."""

    def __init__(self, golden):
        constants = golden["constants"]
        self.tints = {key: color_int(value) for key, value in constants["tints"].items()}
        self.pages = constants["pages"]
        self.wins = constants["WINS"]

    # ------------------------------------------------------------ helpers
    def tint(self, key):
        return self.tints.get(key, 0)

    def entries(self, st):
        return self.pages[st["recent"]["page"]] if st["recent"]["page"] < len(self.pages) else []

    @staticmethod
    def activity(st):
        mode = st["mode"]
        if mode == "home":
            if st["sonos"] != "ok":
                return "offline"
            return "pending" if st["vol"] != st["volConf"] or st["playReq"] != st["playing"] else "idle"
        if mode == "recent":
            return {"loading": "loading", "pending": "pending", "partial": "error",
                    "auth": "error"}.get(st["recent"]["status"], "idle")
        if mode == "tracks":
            return "pending" if st["tracks"]["status"] == "pending" else "idle"
        if mode == "windows":
            return {"pending": "pending", "failed": "error"}.get(st["win"]["status"], "idle")
        return "idle"

    @staticmethod
    def layout(st, lcd):
        mode = st["mode"]
        if mode == "home":
            if lcd["layout"] == "list":
                return "notice"
            if lcd.get("volVis"):
                return "volume"
            return "idle" if lcd["layout"] == "idle" else "nowPlaying"
        return {"recent": "recent", "tracks": "tracks", "windows": "windows"}[mode]

    def ring(self, st, led_style):
        mode, color = st["mode"], led_style == "color"
        if mode == "home":
            return {"style": "level", "value": st["vol"], "index": 0, "count": 101,
                    "first": 0, "unavailable": 0, "moreIndex": -1, "external": bool(st.get("ext"))}
        if mode == "tracks":
            return {"style": "transport", "value": 0, "index": st["tracks"]["pos"] + 1, "count": 3,
                    "unavailable": 1 if st["opt"].get("noPrev") else 0}
        if mode == "recent":
            r = st["recent"]
            if r["status"] in ("empty", "auth"):
                return {"style": "off", "value": 0, "index": 0, "count": 0}
            es = self.entries(st)
            count, index = len(es), r["idx"]
            first = presentation.window_first(index, count)
            window = es[first:first + presentation.RING_WINDOW]
            ring = {"style": "selection", "value": 0, "index": index, "count": count, "first": first,
                    "unavailable": sum(1 << k for k, e in enumerate(window) if e.get("na")),
                    "moreIndex": next((j for j, e in enumerate(es) if e.get("more")), -1)}
            if color:
                ring["colors"] = [0 if e.get("more") else self.tint("al:" + e["t"]) for e in window]
            return ring
        w = st["win"]
        order, index = w["order"], w["idx"]
        count = len(order)
        first = presentation.window_first(index, count)
        width = min(presentation.RING_WINDOW, count - first)
        ring = {"style": "selection", "value": 0, "index": index, "count": count, "first": first,
                "unavailable": sum(1 << k for k in range(width) if first + k in w["closed"]),
                "moreIndex": -1}
        if color:
            ring["colors"] = [self.tint("app:" + self.wins[order[first + k]]["app"]) for k in range(width)]
        return ring

    def art(self, case_id, st, lcd):
        """Stage 6 art fixture name, or None where the model shows no cover."""
        if not lcd.get("art") or st["mode"] == "windows":
            return None
        return ART_BRIGHT if case_id == ART_BRIGHT_CASE else ART_DEN

    # -------------------------------------------------------------- frame
    def frame(self, st, view, led_style, control_id=1, case_id=""):
        """The v4 frame for one model state (full, before device slimming).

        Returns None when the knob is disconnected (deviation 8: firmware hands
        control back to the native UI; the host sends no frame).
        """
        if st["conn"] != "ok":
            return None
        lcd, foot, mode = view["lcd"], view["foot"], st["mode"]
        layout = self.layout(st, lcd)
        title, meta, title_tone = lcd.get("title", ""), lcd.get("meta", ""), TITLE_TONE[lcd["tc"]]
        if mode == "tracks" and st["tracks"]["pos"] == -1 and st["opt"].get("noPrev"):
            # Deviation 6: 'Previous unavailable' (229 px) does not fit the 180 px title.
            title, title_tone, meta = "Previous track", "muted", "Previous unavailable"
        home = mode == "home"
        art = self.art(case_id, st, lcd)
        dim = bool(mode == "recent" and art and self._selected_unavailable(st))
        frame = {
            "id": control_id,
            "mode": MODE[mode],
            "target": "DESKTOP" if mode == "windows" else "Den",
            "value": f"{lcd['big']}%" if home and lcd.get("big") != "" else lcd.get("big", ""),
            "detail": "",
            "status": lcd.get("st", ""),
            "title": title,
            "subtitle": lcd.get("sub", ""),
            "activity": self.activity(st),
            "layout": layout,
            "heading": lcd.get("label", ""),
            "meta": meta,
            "titleTone": title_tone,
            "metaTone": LINE_TONE[lcd["mc"]],
            "statusTone": LINE_TONE[lcd["sc"]],
            "page": st["recent"]["page"] if mode == "recent" else 0,
            "ledStyle": led_style,
            "artKey": art or "",
            "artDim": dim,
            "buttons": [{"label": f["w"], "enabled": f["tone"] not in ("dim", "none"), "icon": f["icon"]}
                        for f in foot],
            "ring": self.ring(st, led_style),
        }
        if home:
            frame.update({
                "restLayout": "idle" if lcd["layout"] == "idle" else "nowPlaying",
                "volumeVisible": layout == "volume",
                "volumeCaption": lcd.get("volCap", ""),
                "confirmedVolume": st["volConf"],
            })
        if st.get("flash"):
            frame["feedback"] = {"kind": st["flash"]["kind"], "seq": st["flash"]["id"]}
        return frame

    def _selected_unavailable(self, st):
        es = self.entries(st)
        idx = st["recent"]["idx"]
        return 0 <= idx < len(es) and bool(es[idx].get("na"))

    def case_frame(self, case, led_style, control_id=1):
        return self.frame(case["st"], case["views"]["white"], led_style, control_id, case["id"])

    @staticmethod
    def pulse_ms(tick):
        """Elapsed onset time whose pulse phase equals the model's tick parity."""
        return (tick & 1) * PULSE_MS

    @staticmethod
    def flash_kind(frame):
        feedback = frame.get("feedback") if frame else None
        return feedback["kind"] if feedback else None


# ------------------------------------------------------------------ alive (ALIVE.md 11.2)
# Target golden: tests/fixtures/alive_golden.json, produced by tests/js/alive_golden.cjs from
# the led-choreography design's knob-model.js view(st, {led:"alive"}) (finishAlive). Its
# "constants" block has the same tints / pages / WINS shape as the v4 golden, so ``Adapter``
# maps its states to frames unchanged; ``alive_frame`` adds the ALIVE.md section 3 fields.
ALIVE_GOLDEN = ROOT / "tests" / "fixtures" / "alive_golden.json"
ALIVE_DESIGN = ROOT / "design-reference" / "design_handoff_led_choreography"
ALIVE_GOLDEN_JS = ROOT / "tests" / "js" / "alive_golden.cjs"
ALIVE_HOME_LAYOUTS = ("nowPlaying", "volume", "idle", "notice")


def load_alive_golden(path=ALIVE_GOLDEN):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def merge_state(st, patch):
    """knob-model.js ``merge(clone(st), patch)``: dicts merge recursively, anything else assigns."""
    out = json.loads(json.dumps(st))

    def merge(target, source):
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = json.loads(json.dumps(value))
    merge(out, patch or {})
    return out


def alive_playing(st):
    """ALIVE.md 3 ``playing`` of a Home frame: the CONFIRMED transport is PLAYING.

    None (the host omits the field) while Sonos is unreachable, since the transport is unknown;
    False when nothing is playing (the model's ``nothing``: queue empty, transport STOPPED);
    else the model's confirmed ``playing`` (``playReq`` is only the request).
    """
    if st.get("sonos") != "ok":
        return None
    if st.get("nothing"):
        return False
    return bool(st.get("playing"))


def alive_frame(adapter, st, view, led_style, control_id=1, case_id=""):
    """The v4 frame of ``Adapter.frame`` plus the ALIVE.md section 3 frame content.

    ``playing`` is added on Home layouts only (``alive_playing``). ``feedback.skip`` is not
    derived: a model state does not record the skip direction, and targets never read it.
    Latched fields (clock, progress, ledDrive, ledDither) are not frame content (10.2).
    """
    frame = adapter.frame(st, view, led_style, control_id, case_id)
    if frame is None:
        return None
    if frame["layout"] in ALIVE_HOME_LAYOUTS:
        playing = alive_playing(st)
        if playing is not None:
            frame["playing"] = playing
    return frame


def alive_remap(design_palette):
    """ALIVE.md 11.2 palette remap, keyed by finishAlive's own colour strings.

    finishAlive has already remapped the model colours (W -> WARM, G -> AG, R and
    '255,55,35' -> AR, '255,150,30' -> AAMB, anything else -> sat(x)); this maps its output
    to the engine roles (control_center.alive_lights ROLE_*). Any other string is an ACCENT
    whose rgb is the design's sat(x).
    """
    from control_center import alive_lights as al
    return {design_palette["WARM"]: al.ROLE_WARM, design_palette["AG"]: al.ROLE_GREEN,
            design_palette["AR"]: al.ROLE_RED, design_palette["AAMB"]: al.ROLE_AMBER,
            design_palette["ABLUE"]: al.ROLE_BLUE}


def alive_design_cell(color, level, alpha, remap):
    """One finishAlive cell -> (role, class, alpha, accent rgb or None); unlit -> None."""
    from control_center import alive_lights as al
    if not level:
        return None
    role = remap.get(color, al.ROLE_ACCENT)
    rgb = tuple(int(part) for part in color.split(",")) if role == al.ROLE_ACCENT else None
    return (role, level, alpha, rgb)


def alive_design_ring(ring, remap):
    """finishAlive ring ([c, l, a] | null) x 60 -> design cells."""
    return [None if entry is None else alive_design_cell(entry[0], entry[1], entry[2], remap) for entry in ring]


def alive_design_buttons(buttons, remap):
    """finishAlive buttons ({tone, c, l, a}) x 4 -> design cells (l 0 = off)."""
    return [alive_design_cell(b["c"], b["l"], b["a"], remap) for b in buttons]


def alive_cell(cell):
    """control_center.alive_lights.Cell -> (role, class, alpha, accent rgb or None); None stays None."""
    from control_center import alive_lights as al
    if cell is None:
        return None
    return (cell.role, cell.cls, cell.alpha, tuple(cell.rgb) if cell.role == al.ROLE_ACCENT else None)

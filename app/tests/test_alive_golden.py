"""alive targets (control_center.alive_lights.alive_targets) against the RC design's finishAlive().

ALIVE.md revision 2, 11.3 target golden. tests/fixtures/alive_golden.json is produced by
tests/js/alive_golden.cjs from the led-choreography design's knob-model.js
view(st, {led:"alive"}) with NanoModel.COLORS pre-populated from
tests/fixtures/dominant_reference.json; the animator flags come from the design's own
draw()/detect() expressions. tests/tools/knob_adapter.py maps every model state to the v4
frame the host would send (plus ALIVE.md 3 ``playing``: these are the v6 host's frames, which a cc5.4
knob draws with the revision 2 targets, ALIVE.md 1) and remaps finishAlive's colours (11.3):
design WARM -> WARM, AG -> GREEN, AR -> RED, AAMB -> AMBER, ABLUE -> BLUE, sat(x) -> ACCENT sat(x).

Compared for every case x variant (base, asleep, ok/err flash, err flash asleep, external,
external asleep), both ``ledStyle`` values and both pulse phases where the design pulses:
ring and buttons exactly on role and class (plus the accent rgb), alpha within 1e-6;
effectiveAsleep, cursor, family; the 5.4 flags pending, heat, pausedPlay, the RED set
(``volRed``), tint and the song-hand eligibility; the 6.4 selected-entry accent. sat() is
compared with finishAlive's own sat() over its whole domain (the fixture's "sat" table digest).

Revision 2 departs from finishAlive's v4 geometry (ALIVE.md 5): the expected targets are the contract's
(``contract_ring``, written out here from ALIVE.md 5.1-5.2, independently of the module), and every
segment, cursor, tint or accent where the contract differs from the design must be explained by a
listed deviation or ruling (DEVIATIONS / RULINGS), each tagged and counted; a difference no tag
explains fails. Revision 2's new tags (11.3): M1 (the semantic body 0.62 / half-step 0.81), M2 (the
value gate), M3 (lists carry only their items' colours), M9 (the re-centred window), M13 (the
half-step after the endpoint), M31 (a loading list is the comet only). M18 (the resting buttons) is
the design's rule on every tone a v4 frame has, so it never differs here (the BS golden exercises it).
[user 2026-09-26] Tag UR-12.8 (ALIVE.md 12.8): at rest every lit segment is 0.34 and the buttons 0.34 / 0.26
(the design: 0.05 / 0.10 / 0.16 and 0.12 / 0.04); only the alpha differs, role and class are the design's.

Regenerate after a deliberate change (node is needed only for the golden):
    node tests\\js\\alive_golden.cjs design-reference\\design_handoff_led_choreography tests\\fixtures\\dominant_reference.json tests\\fixtures\\alive_golden.json
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tests" / "tools"
for _path in (str(ROOT), str(TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import alive_lights as al  # noqa: E402
import knob_adapter as ka  # noqa: E402

GOLDEN = ka.load_alive_golden()
ADAPTER = ka.Adapter(GOLDEN)
REMAP = ka.alive_remap(GOLDEN["designConstants"]["palette"])
CASES = {case["id"]: case for case in GOLDEN["cases"]}
LEDS = ("color", "white")
ALPHA_TOL = 1e-6
WARM, GREEN, RED = al.ROLE_WARM, al.ROLE_GREEN, al.ROLE_RED
AMBER, BLUE, ACCENT = al.ROLE_AMBER, al.ROLE_BLUE, al.ROLE_ACCENT
S = al.CLASS_S
HOLD_PROBE_MS = 12 * 260          # 3120: an even (HIGH) pulse phase, past the 3 s hold

DEVIATIONS = {
    "D5": "ALIVE D5 / 5.2 Offline: no reconnecting pulse (marks stay 0.12) and no Working comet "
          "over them; expected = the design's own 'missing' view",
    "D7": "ALIVE D7 / 6.4: SWITCHED uses the selected entry's accent; the design reads the drawn "
          "cursor colour, which rest or a flash draw otherwise",
    "D10": "ALIVE D10: the half-step (class S) also exists at rest (the design draws class 2 there); its "
           "resting level is 12.8's 0.34",
    "D15": "ALIVE D15 + lead ruling R1: 6.1 pending excludes activity offline, so a stale displayed != "
           "confirmed request on the Home Sonos-off notice is not pending (no Working comet) and rests; "
           "expected = the design's view at the confirmed volume (the fixture's 'D15' alt)",
    "D16": "ALIVE D16 / section 2: ledStyle 'white' is warm only (list accents and the 80/90 % "
           "colours become WARM; GREEN, flash RED, BLUE and buttons are kept)",
    "V4-9.2": "PRESENTATION_V4 9.2 (ALIVE 5.1.2 step 3): the pending-decrease span k = n+1..nc is drawn "
              "class 1; the design leaves it dark",
    "V4-9.4": "PRESENTATION_V4 9.4 (ALIVE 5.1.8): the pending pulse holds class 1 after 3 s",
    "M1": "ALIVE M1 / 5.2: the amber / red volume body is 0.62 and the half-step 0.81 in every role "
          "(the design draws semantic class 2 at 1.0)",
    "M2": "ALIVE M2 / 5.1.2: the volume colours are gated on the value AND the position (the design "
          "colours by position only)",
    "M3": "ALIVE M3 / 5.1.3: lists carry only their items' colours: a legacy More is one warm item "
          "(no second cell), an unavailable cursor keeps its colour at 0.45 (class Q), a pending "
          "cursor pulses in its colour (the design draws warm / white there)",
    "M9": "ALIVE M9 / 5.1.1: the 20-entry window is re-centred on the transmitted window "
          "(c0 = first + 9; the design draws the whole list on absolute slots)",
    "M13": "ALIVE M13 / 5.1.2: for an odd volume the endpoint is 35 + floor(v/2) and the half-step "
           "(class S, 0.81) lights the NEXT segment (the design: endpoint 35 + round(v/2), no half-step); "
           "the flash / external overrides follow the endpoint",
    "M31": "ALIVE M31 / 5.1.3 case 1: a loading list draws no cells, only the Working comet (the design "
           "pulses segment 0)",
}
RULINGS = {
    "R2": "ALIVE R2 (review Q1) / 5.4: the tint needs the cursor role ACCENT (a sat() that fell back "
          "to WARM gives none); the design's draw() line 308 tints with ANY non-warm cursor, so a "
          "Recent / Windows ok/err flash tints green/red there",
    "R3": "ALIVE R3 (review Q2, F3) / 8.4: the song hand needs the last Home frame's playing == true "
          "(the CONFIRMED transport; a missing playing counts as not playing)",
    "UR-12.8": "ALIVE 12.8 (user ruling 2026-09-26): resting is one steady dim warm white, every lit segment "
               "at 0.34 and the buttons at 0.34 (awake >= 0.5) / 0.26 (the design rests at 0.05 / 0.10 / 0.16 "
               "and 0.12 / 0.04); role and class unchanged",
}
# [user 2026-09-26] 12.8: the design's resting button levels -> the ruled ones.
RULED_BUTTON_REST = {0.12: 0.34, 0.04: 0.26}
# Tags a case may carry that a comparison cannot always exercise alone (M2 is always co-located with
# M13 or V4-9.2 in the design's cases: 79 and 89 are odd).
OPTIONAL = {"V4-9.4", "M2"}


# ------------------------------------------------------------------ the contract (ALIVE.md 5)
AWAKE_WARM = {"P": 0.14, 1: 0.30, "Q": 0.45, 2: 0.62, "N": 0.70, S: 0.81, 3: 1.0, 4: 1.0}
AWAKE_SEMANTIC = {"P": 0.14, 1: 0.45, "Q": 0.45, 2: 0.62, "N": 0.70, S: 0.81, 3: 1.0, 4: 1.0}
RESTING = {"P": 0.34, 1: 0.34, "Q": 0.34, 2: 0.34, "N": 0.34, S: 0.34, 3: 0.34, 4: 0.34}   # [user 2026-09-26] 12.8


def _alpha(role, cls, asleep):
    if asleep:
        return RESTING[cls]
    return (AWAKE_WARM if role == WARM else AWAKE_SEMANTIC)[cls]


def _cell(role, cls, asleep, rgb=None):
    if asleep:
        return (WARM, cls, RESTING[cls], None)
    return (role, cls, _alpha(role, cls, False), rgb if role == ACCENT else None)


def contract_ring(frame, asleep, flash, pending_ms=0):
    """ALIVE.md revision 2, 5.1-5.2 written out: (60 cells (role, class, alpha, rgb) | None, cursor,
    selected accent). ``frame`` is a v4 frame of the adapter (first present when count > 20)."""
    ring = frame["ring"]
    style, activity = ring["style"], frame["activity"]
    colour = frame.get("ledStyle") == "color"
    cells = {}
    cursor, accent = 0, None
    if style == "level":
        v = ring["value"]
        c = frame.get("confirmedVolume", v)

        def col(k, x):
            if not colour:
                return WARM
            return RED if x >= 90 and k >= 45 else AMBER if x >= 80 and k >= 40 else WARM
        if activity == "offline":
            cells[(35 + c // 2) % 60] = (WARM, 1)
            cursor = (35 + c // 2) % 60
        else:
            e, n, nc = v // 2, (v + 1) // 2, (c + 1) // 2
            put = lambda k, role, cls: cells.__setitem__((35 + k) % 60, (role, cls))  # noqa: E731
            put(0, WARM, 1)
            put(50, WARM, 1)
            for k in range(n + 1):
                put(k, col(k, v), 2 if k <= nc else 1)
            for k in range(n + 1, nc + 1):
                put(k, col(k, c), 1)
            if v % 2:
                put(e + 1, col(e + 1, v), S)
            put(e, col(e, v), 4 if ring.get("external") else 3)
            cursor = (35 + e) % 60
        out = [None] * 60
        for i, (role, cls) in cells.items():
            out[i] = _cell(role, cls, asleep)
    elif style == "selection":
        out = [None] * 60
        count, index = ring["count"], ring["index"]
        if activity != "loading" and count:
            first = ring.get("first", 0)
            width = min(20, count - first)
            colors = ring.get("colors", []) if colour else []
            mask = ring.get("unavailable", 0)
            more = ring.get("moreIndex", -1)
            c0 = first + (width - 1) // 2

            def acc(j):
                k = j - first
                if j == more or not 0 <= k < len(colors) or not colors[k]:
                    return None
                return al.sat(al.rgb_tuple(colors[k]))
            for j in range(first, first + width):
                if (mask >> (j - first)) & 1:
                    continue
                s = acc(j)
                out[((j - c0) * 3) % 60] = _cell(ACCENT if s else WARM, 1, asleep, s)
            cursor = ((index - c0) * 3) % 60
            s = acc(index)
            cls = 3 if index == more or not (mask >> (index - first)) & 1 else "Q"
            if activity == "pending":
                cls = 1 if pending_ms >= 3000 or (pending_ms // 260) % 2 else 3
            out[cursor] = _cell(ACCENT if s else WARM, cls, asleep, s)
            accent = s
    elif style == "transport":
        out = [None] * 60
        index, no_prev = ring["index"], bool(ring.get("unavailable", 0) & 1)
        if not no_prev:
            out[52] = out[53] = _cell(WARM, 1, asleep)
        out[0] = _cell(WARM, 1, asleep)
        out[7] = out[8] = _cell(WARM, 1, asleep)
        pair = (52, 53) if index == 0 else (7, 8) if index == 2 else (0,)
        cursor = {0: 52, 1: 0, 2: 8}[index]
        if index != 0 or not no_prev:
            for i in pair:
                out[i] = _cell(WARM, 2 if index == 1 else 3, asleep)
        if activity == "pending":
            cls = 1 if pending_ms >= 3000 or (pending_ms // 260) % 2 else 3
            for i in pair:
                out[i] = _cell(WARM, cls, asleep)
    else:
        out = [None] * 60
    home = frame["layout"] in ka.ALIVE_HOME_LAYOUTS
    if not asleep and home and ring.get("external") is True:
        for k in (-1, 0, 1):
            out[(cursor + k) % 60] = (BLUE, 4, 1.0, None)
    if flash:
        role = GREEN if flash == "ok" else RED
        for k in (-2, -1, 0, 1, 2):
            out[(cursor + k) % 60] = (role, 4, 1.0 if abs(k) <= 1 else 0.5, None)
    return out, cursor, accent


def ours_targets(frame, st, tick=0, pending_ms=None):
    """alive_targets for one golden state: stateAsleep = st.asleep, the frame's flash, pulse phase."""
    phase = ka.Adapter.pulse_ms(tick) if pending_ms is None else pending_ms
    return al.alive_targets(frame, state_asleep=bool(st.get("asleep")), flash=ka.Adapter.flash_kind(frame),
                            pending_ms=phase)


def rgb(text):
    return tuple(int(part) for part in text.split(",")) if text else None


def cells_equal(a, b):
    if a is None or b is None:
        return a is b
    return a[0] == b[0] and a[1] == b[1] and abs(a[2] - b[2]) <= ALPHA_TOL and a[3] == b[3]


def rings_equal(a, b):
    return all(cells_equal(x, y) for x, y in zip(a, b))


class Expected:
    """The contract's targets for one (case, variant, led, tick), every difference from the design's
    finishAlive() explained by a tag."""

    def __init__(self, case, variant, led, tick, frame):
        self.tags = Counter()
        self.untagged = []
        st = ka.merge_state(case["st"], variant["patch"])
        self.st, self.led, self.frame = st, led, frame
        alive, flags = variant["alive"], variant["flags"]
        ring = variant["tick1"] if tick and "tick1" in variant else alive["ring"]
        alt = case.get("alt", {}).get("tag")
        if "altAlive" in variant and alt in ("D5", "D15"):
            # The design's own drawing of the deviation (D5 missing, D15/R1 confirmed).
            alt_ring = variant["altTick1"] if tick and "altTick1" in variant else variant["altAlive"]["ring"]
            own = {k: v for k, v in flags.items() if k in variant["altFlags"]}
            if (alt_ring, variant["altAlive"]["buttons"], variant["altAlive"]["ledSleep"], variant["altFlags"]) \
                    != (ring, alive["buttons"], alive["ledSleep"], own):
                self.tags[alt] += 1
            ring, alive, flags = alt_ring, variant["altAlive"], variant["altFlags"]
        self.design_ring = ka.alive_design_ring(ring, REMAP)
        self.buttons = ka.alive_design_buttons(alive["buttons"], REMAP)
        self.asleep, self.design_cursor, self.mode = alive["ledSleep"], alive["cursor"], alive["mode"]
        if self.asleep:                                     # [user 2026-09-26] 12.8 resting buttons
            for j, b in enumerate(self.buttons):
                if b is None:
                    continue
                if b[2] in RULED_BUTTON_REST:
                    self.buttons[j] = (b[0], b[1], RULED_BUTTON_REST[b[2]], b[3])
                    self.tags["UR-12.8"] += 1
                else:
                    self.untagged.append(("resting button", j, b))
        self.pending, self.heat, self.paused_play = flags["pending"], flags["heat"], flags["pausedPlay"]
        self.song_hand = flags["songHand"]
        self.design_tint = rgb(flags["tint"])
        self.embers = set(flags["embers"])
        self._self_check()
        self._ring(tick)
        self._accent(variant["flags"])
        self._flags()

    def _self_check(self):
        derived = {i for i, c in enumerate(self.design_ring) if self.heat and c and c[0] == RED}
        assert derived == self.embers, ("embers derivation", derived, self.embers)
        assert self._design_tint(self.design_ring, self.design_cursor) == self.design_tint, ("tint", self.design_tint)

    def _design_tint(self, ring, cursor):
        """draw() line 308-309 on role cells: any non-warm lit cursor in Recent / Windows, awake."""
        cell = ring[cursor]
        if self.mode not in ("windows", "recent") or self.asleep or cell is None or cell[0] == WARM:
            return None
        return cell[3] if cell[0] == ACCENT else rgb(GOLDEN["designConstants"]["palette"][
            {GREEN: "AG", RED: "AR", AMBER: "AAMB", BLUE: "ABLUE"}[cell[0]]])

    # -- the ring: the contract's, every difference from the design explained
    def _ring(self, tick):
        frame = self.frame
        if frame is None:                                   # disconnected: the offline targets (D5 alt)
            self.ring, self.cursor, self.accent_contract = self.design_ring, self.design_cursor, None
            return
        flash = ka.Adapter.flash_kind(frame)
        pending_ms = ka.Adapter.pulse_ms(tick)
        self.ring, self.cursor, self.accent_contract = contract_ring(frame, self.asleep, flash, pending_ms)
        ring = frame["ring"]
        style, activity = ring["style"], frame["activity"]
        for i in range(60):
            d, c = self.design_ring[i], self.ring[i]
            if cells_equal(d, c):
                continue
            tags = self._explain(i, d, c, style, activity, ring)
            if self.asleep and d is not None and c is not None and (d[0], d[1], d[3]) == (c[0], c[1], c[3]):
                tags = set(tags) | {"UR-12.8"}              # [user 2026-09-26] only the resting alpha
            if not tags:
                self.untagged.append((i, d, c))
            for tag in tags:
                self.tags[tag] += 1
        if self.cursor != self.design_cursor:
            tag = "M13" if style == "level" else "M9" if style == "selection" else None
            if tag is None:
                self.untagged.append(("cursor", self.design_cursor, self.cursor))
            else:
                self.tags[tag] += 1

    def _explain(self, i, d, c, style, activity, ring):
        tags = set()
        if style == "level":
            v = ring["value"]
            conf = self.frame.get("confirmedVolume", v)
            e, n, nc = v // 2, (v + 1) // 2, (conf + 1) // 2
            k = (i - 35) % 60
            near = min(abs(al.cd(i, self.cursor)), abs(al.cd(i, self.design_cursor))) <= 3
            if activity == "offline":                       # [D15] the confirmed endpoint, M13 placement
                return {"M13"} if conf % 2 and near else set()
            if v % 2 and near:
                tags.add("M13")
                if self.asleep and c is not None and c[1] == S:
                    tags.add("D10")
            if n < k <= nc:
                tags.add("V4-9.2")
            if d is not None and c is not None and d[0] != c[0]:
                if self.led != "color" and d[0] in (AMBER, RED) and c[0] == WARM:
                    tags.add("D16")
                elif d[0] in (AMBER, RED, WARM) and c[0] in (AMBER, RED, WARM):
                    tags.add("M2")
            if d is not None and c is not None and d[:2] == c[:2] and d[0] != WARM and c[1] in (2, S):
                tags.add("M1")
            return tags
        if style == "selection":
            count, index = ring["count"], ring["index"]
            more, mask, first = ring.get("moreIndex", -1), ring.get("unavailable", 0), ring.get("first", 0)
            if activity == "loading":
                return {"M31"}
            if count > 20:
                tags.add("M9")
            if more >= 0 and i in (self.cursor, (self.cursor + 1) % 60) and index == more:
                tags.add("M3")
            if more >= 0 and i == ((more - (first + (min(20, count - first) - 1) // 2)) * 3 + 1) % 60:
                tags.add("M3")                              # the design's second More cell
            if i == self.cursor and (activity == "pending" or (mask >> (index - first)) & 1):
                tags.add("M3")
            if self.led != "color" and d is not None and d[0] == ACCENT:
                tags.add("D16")
            return tags
        return tags

    def _accent(self, own_flags):
        """6.4 memory: the selected entry's accent (the contract's acc(index)); the design's SWITCHED
        colour on the reference view differs on a pending / flashed cursor (D7), under Warm only (D16)
        and on an unavailable Recent cursor (M3: the design draws it warm)."""
        design = rgb(own_flags["washRef"])
        self.accent = self.accent_contract
        if rgb(own_flags["wash"]) != design:
            self.tags["D7"] += 1
        if self.accent != design:
            ring = self.frame["ring"] if self.frame else {}
            index, first = ring.get("index", 0), ring.get("first", 0)
            if self.led != "color":
                self.tags["D16"] += 1
            elif (ring.get("unavailable", 0) >> (index - first)) & 1:
                self.tags["M3"] += 1
            elif ring.get("count", 0) > 20:
                self.tags["M9"] += 1
            else:
                self.untagged.append(("accent", design, self.accent))

    def _flags(self):
        self.vol_red = {i for i, c in enumerate(self.ring) if c and c[0] == RED}
        design = self._design_tint(self.design_ring, self.design_cursor)
        cell = self.ring[self.cursor]
        family_tints = self.mode in ("windows", "recent") and not self.asleep
        self.tint = cell[3] if family_tints and cell is not None and cell[0] == ACCENT else None
        if design != self.tint:
            ring = self.frame["ring"] if self.frame else {}
            index, first = ring.get("index", 0), ring.get("first", 0)
            if design is not None and self.tint is None and cell is not None and cell[0] != ACCENT:
                self.tags["R2"] += 1
            elif ring.get("count", 0) > 20:
                self.tags["M9"] += 1
            elif self.frame and (self.frame["activity"] == "pending" or (ring.get("unavailable", 0) >> (index - first)) & 1):
                self.tags["M3"] += 1
            else:
                self.untagged.append(("tint", design, self.tint))
        playing = self.frame.get("playing") if self.frame else None
        contract = bool(self.asleep and self.mode == "home" and playing is True)
        if contract != self.song_hand:
            assert self.song_hand and (self.st.get("nothing") or self.st.get("sonos") != "ok"), \
                "song hand differs outside the R3 states"
            self.tags["R3"] += 1
        self.song_hand = contract


def ours_song_hand(targets):
    return bool(targets.asleep and targets.family == "home" and targets.playing is True)


def compare(test, ours, exp):
    """Assert every compared field; returns the number of values compared."""
    test.assertEqual(exp.untagged, [], "a difference from the design no listed deviation explains")
    ring = [ka.alive_cell(c) for c in ours.ring]
    buttons = [ka.alive_cell(c) for c in ours.buttons]
    for i in range(60):
        test.assertTrue(cells_equal(ring[i], exp.ring[i]), f"segment {i}: ours {ring[i]} expected {exp.ring[i]}")
    for j in range(4):
        test.assertTrue(cells_equal(buttons[j], exp.buttons[j]), f"button {j}: ours {buttons[j]} expected {exp.buttons[j]}")
    test.assertEqual(ours.asleep, exp.asleep, "effectiveAsleep")
    test.assertEqual(ours.cursor, exp.cursor, "cursor")
    test.assertEqual(ours.family, exp.mode, "family")
    test.assertEqual(ours.pending, exp.pending, "pending")
    test.assertEqual(ours.heat, exp.heat, "heat")
    test.assertEqual(ours.paused_play, exp.paused_play, "pausedPlay")
    test.assertEqual({i for i, c in enumerate(ours.ring) if c is not None and c.vol_red}, exp.vol_red, "volRed")
    ours_tint = tuple(round(x * 255) for x in ours.tint) if ours.tint is not None else None
    test.assertEqual(ours_tint, exp.tint, "tint")
    test.assertEqual(ours_song_hand(ours), exp.song_hand, "song hand")
    test.assertEqual(ours.accent, exp.accent, "selected accent (6.4)")
    return 60 + 4 + 11


def combos():
    """Every (case, variant, led, tick) the golden compares."""
    for case in GOLDEN["cases"]:
        for variant in case["variants"]:
            ticks = (0, 1) if "tick1" in variant or "altTick1" in variant else (0,)
            for led in LEDS:
                for tick in ticks:
                    yield case, variant, led, tick


def frame_of(case, variant, led):
    st = ka.merge_state(case["st"], variant["patch"])
    return st, ka.alive_frame(ADAPTER, st, {"lcd": variant["lcd"], "foot": variant["foot"]}, led, case_id=case["id"])


# ======================================================================= golden
class AliveGoldenTests(unittest.TestCase):
    def test_every_case_matches_finish_alive_except_tagged_deviations(self):
        used, compared, values = Counter(), 0, 0
        per_tag_cases = {}
        for case, variant, led, tick in combos():
            st, frame = frame_of(case, variant, led)
            exp = Expected(case, variant, led, tick, frame)
            used.update(exp.tags)
            for tag in exp.tags:
                per_tag_cases.setdefault(tag, set()).add(case["id"])
            with self.subTest(case=case["id"], variant=variant["key"], led=led, tick=tick):
                values += compare(self, ours_targets(frame, st, tick), exp)
            compared += 1
        self.assertGreaterEqual(compared, 2400)
        for tag in set(used) - set(DEVIATIONS) - set(RULINGS):
            self.fail(f"untagged deviation {tag}")
        for tag in list(DEVIATIONS) + list(RULINGS):
            if tag not in OPTIONAL:
                with self.subTest(tag=tag):
                    self.assertGreater(used[tag], 0, f"{tag} is never exercised")
        report = ", ".join(f"{tag} {used[tag]} ({len(per_tag_cases[tag])} case(s))" for tag in sorted(used))
        print(f"\n[alive golden] {len(GOLDEN['cases'])} cases, {compared} comparisons, {values} values; "
              f"tagged: {report}")

    def test_pending_hold_deviation(self):
        """V4-9.4: at 3120 ms the design (even tick) is HIGH; the contract holds class 1 like tick 1."""
        probed = 0
        for case, variant, led, tick in combos():
            if tick or "tick1" not in variant:
                continue
            st, frame = frame_of(case, variant, led)
            if frame is None or frame["activity"] != "pending" or frame["ring"]["style"] not in ("selection", "transport"):
                continue
            high = ka.alive_design_ring(variant["alive"]["ring"], REMAP)
            low = ka.alive_design_ring(variant["tick1"], REMAP)
            with self.subTest(case=case["id"], variant=variant["key"], led=led):
                self.assertFalse(rings_equal(high, low))                     # the design pulses
                cursor = ours_targets(frame, st).cursor
                last_high = ours_targets(frame, st, pending_ms=10 * 260).ring[cursor]
                held = ours_targets(frame, st, pending_ms=HOLD_PROBE_MS).ring[cursor]
                self.assertEqual((last_high.cls, held.cls), (3, 1) if not st.get("asleep") else (last_high.cls, 1))
            probed += 1
        self.assertGreaterEqual(probed, 20)

    def test_deviation_expected_values(self):
        """Hand-checked values, one or more per tag (literal, not derived from the contract function)."""
        def run(case_id, key="base", led="color", tick=0):
            case = CASES[case_id]
            variant = next(v for v in case["variants"] if v["key"] == key)
            st, frame = frame_of(case, variant, led)
            return ours_targets(frame, st, tick), ka.alive_design_ring(variant["alive"]["ring"], REMAP), variant

        # M13: home-turn (v 55): endpoint 35 + 27 = 2 at 1.0, the half-step 3 at 0.81; the design
        # draws the endpoint at 3 and 2 as body. Resting: the half-step at 12.8's 0.34 [D10].
        ours, design, _ = run("home-turn")
        self.assertEqual((ours.cursor, ka.alive_cell(ours.ring[2]), ka.alive_cell(ours.ring[3])),
                         (2, (WARM, 3, 1.0, None), (WARM, S, 0.81, None)))
        self.assertEqual((design[2], design[3]), ((WARM, 2, 0.62, None), (WARM, 3, 1, None)))
        ours, design, _ = run("home-turn", "asleep")
        self.assertEqual(ka.alive_cell(ours.ring[3]), (WARM, S, 0.34, None))
        # UR-12.8: at rest the body (k 10) is 0.34 where the design rests it at 0.10.
        body = (35 + 10) % 60
        self.assertEqual((ka.alive_cell(ours.ring[body]), design[body]), ((WARM, 2, 0.34, None), (WARM, 2, 0.1, None)))
        # M1: led-vol-86 (e 43, k 40..42 amber body): 0.62 where the design draws amber class 2 at 1.0.
        ours, design, _ = run("led-vol-86")
        self.assertEqual(ka.alive_cell(ours.ring[(35 + 41) % 60]), (AMBER, 2, 0.62, None))
        self.assertEqual(design[(35 + 41) % 60], (AMBER, 2, 1, None))
        # M2 + M13: vol-89 (e 44): AMBER endpoint and half-step (the design: a RED endpoint at 35 + 45).
        ours, design, variant = run("vol-89-ext")
        st, frame = frame_of(CASES["vol-89-ext"], variant, "color")
        plain = al.alive_targets(dict(frame, ring=dict(frame["ring"], external=False)))
        self.assertEqual(ka.alive_cell(plain.ring[(35 + 45) % 60])[:2], (AMBER, S))
        self.assertEqual(ka.alive_cell(plain.ring[(35 + 44) % 60])[:2], (AMBER, 3))
        self.assertEqual(design[(35 + 43) % 60][:2], (AMBER, 2))   # the design colours by position only
        # V4-9.2: vol-1-down-50 (v 1, confirmed 50): the span k 2..25 is class 1 (WARM 0.30 below 80 %);
        # the design leaves it dark.
        ours, design, _ = run("vol-1-down-50")
        self.assertEqual(ka.alive_cell(ours.ring[(35 + 10) % 60]), (WARM, 1, 0.30, None))
        self.assertIsNone(design[(35 + 10) % 60])
        # D16: led-vol-96 white: the red endpoint is WARM class 3; the flash stays RED.
        ours, design, _ = run("led-vol-96", led="white")
        cursor = (35 + 48) % 60
        self.assertEqual(design[cursor], (RED, 3, 1, None))
        self.assertEqual(ka.alive_cell(ours.ring[cursor]), (WARM, 3, 1.0, None))
        ours, _, _ = run("led-vol-96", "err", led="white")
        self.assertEqual(ka.alive_cell(ours.ring[cursor]), (RED, 4, 1.0, None))
        # M3: ra-more (the More entry at slot 15): one warm cell, the design's second cell (16) is gone.
        ours, design, _ = run("ra-more")
        self.assertEqual((design[15][:2], design[16][:2]), ((WARM, 3), (WARM, 3)))
        self.assertEqual((ka.alive_cell(ours.ring[15])[:2], ours.ring[16]), ((WARM, 3), None))
        # M3: pend-wi-claude keeps the Claude accent (D13, the design too); pend-ra-p2 now keeps its accent.
        ours, design, _ = run("pend-wi-claude")
        self.assertEqual(ka.alive_cell(ours.ring[51]), design[51])
        ours, design, variant = run("pend-ra-p2")
        self.assertIsNone(variant["flags"]["wash"])
        self.assertEqual(ours.accent, rgb(variant["flags"]["washRef"]))
        self.assertEqual(ka.alive_cell(ours.ring[ours.cursor])[0], ACCENT)
        # M31: ra-load: the design pulses segment 0; the contract draws nothing (the comet only).
        ours, design, _ = run("ra-load")
        self.assertEqual(design[0][:2], (WARM, 2))
        self.assertEqual(({i for i, c in enumerate(ours.ring) if c}, ours.pending), (set(), True))
        # M9: wi-n45-i30 (first 21): the window re-centred, c0 = 30, cursor at 0.
        ours, _, _ = run("wi-n45-i30")
        self.assertEqual(ours.cursor, 0)
        self.assertEqual({i for i, c in enumerate(ours.ring) if c}, {((j - 30) * 3) % 60 for j in range(21, 41)})
        # D5: reconnecting marks: design 0.5 / 0.15 pulse, ours 0.12; no Working comet.
        ours, design, variant = run("disc-reconnecting")
        self.assertEqual({design[i][2] for i in range(0, 60, 5)}, {0.5})
        self.assertEqual({ka.alive_cell(ours.ring[i]) for i in range(0, 60, 5)}, {(AMBER, 1, 0.12, None)})
        self.assertTrue(variant["flags"]["pending"])
        self.assertFalse(ours.pending)
        # D15 / R1: home-off-pend (61 over confirmed 54, Sonos off): the endpoint at 35 + 27 [M13].
        ours, design, variant = run("home-off-pend", "asleep")
        self.assertTrue(variant["flags"]["pending"])
        self.assertEqual((ours.pending, ours.asleep), (False, True))
        self.assertEqual({i: ka.alive_cell(c) for i, c in enumerate(ours.ring) if c}, {2: (WARM, 1, 0.34, None)})
        # R2: flash-ok-wi-first: the design tints green, ALIVE 5.4 does not tint (ACCENT only).
        ours, _, variant = run("flash-ok-wi-first")
        self.assertEqual(variant["flags"]["tint"], GOLDEN["designConstants"]["palette"]["AG"])
        self.assertIsNone(ours.tint)
        # R3: home-none asleep: the design shows the song hand; the frame says playing:false.
        ours, _, variant = run("home-none", "asleep")
        self.assertTrue(variant["flags"]["songHand"])
        self.assertIs(ours.playing, False)

    def test_buttons_and_paused_play(self):
        """Paused Play is GREEN class 3 at 1.0 awake, WARM 0.34 resting (12.8; the design 0.12); Cancel RED;
        dim 0.14 / 0.26 at rest."""
        def buttons(case_id, key="base"):
            case = CASES[case_id]
            variant = next(v for v in case["variants"] if v["key"] == key)
            st, frame = frame_of(case, variant, "color")
            ours = ours_targets(frame, st)
            return [ka.alive_cell(b) for b in ours.buttons], ka.alive_design_buttons(variant["alive"]["buttons"], REMAP), ours
        ours, design, targets = buttons("home-paused")
        self.assertEqual(ours[0], (GREEN, 3, 1.0, None))
        self.assertEqual(ours, design)
        self.assertTrue(targets.paused_play)
        ours, design, targets = buttons("home-paused", "asleep")
        self.assertEqual(ours[0], (WARM, 3, 0.34, None))
        self.assertEqual(design[0], (WARM, 3, 0.12, None))                 # UR-12.8
        self.assertFalse(targets.paused_play)
        ours, _, _ = buttons("wi-brw")
        self.assertEqual([b[:2] for b in ours], [(RED, 2), (WARM, 2), (WARM, 2), (GREEN, 3)])
        ours, _, _ = buttons("home-pausing")
        self.assertEqual(ours[0], (WARM, 1, 0.14, None))
        ours, _, _ = buttons("home-pausing", "asleep")
        self.assertEqual(ours[0], (WARM, 1, 0.14, None))           # pending: never rests

    def test_local_cursor_at_the_frame_position_changes_nothing(self):
        """6.3: a local position equal to the frame's value/index gives the same targets (a selection
        ring re-centres on the local index [M15], which is the host window only where the host follows
        the v5 rule, so lists longer than 20 are compared only where clamp(index - 10) == first)."""
        checked = 0
        for case, variant, led, tick in combos():
            st, frame = frame_of(case, variant, led)
            if frame is None or tick:
                continue
            ring = frame["ring"]
            local = {"level": (ring.get("value"), 100), "selection": (ring.get("index"), ring.get("count", 0) - 1),
                     "transport": (ring.get("index"), 2)}.get(ring["style"])
            if local is None:
                continue
            if ring["style"] == "selection" and ring["count"] > 20 and \
                    max(0, min(ring["index"] - 10, ring["count"] - 20)) != ring.get("first"):
                continue
            flash = ka.Adapter.flash_kind(frame)
            a = al.alive_targets(frame, state_asleep=bool(st.get("asleep")), flash=flash)
            b = al.alive_targets(frame, local[0], local[1], state_asleep=bool(st.get("asleep")), flash=flash)
            with self.subTest(case=case["id"], variant=variant["key"], led=led):
                self.assertEqual([ka.alive_cell(c) for c in a.ring], [ka.alive_cell(c) for c in b.ring])
                self.assertEqual((a.cursor, a.pending, a.asleep, a.accent), (b.cursor, b.pending, b.asleep, b.accent))
            checked += 1
        self.assertGreater(checked, 2000)

    def test_design_constants_are_the_contract_remap(self):
        constants = GOLDEN["designConstants"]
        # ALIVE.md 11.2 names the design WARM and the model's volume colours literally.
        self.assertEqual(constants["palette"]["WARM"], "255,164,84")
        self.assertEqual(constants["MODEL_WARM"], constants["palette"]["WARM"])
        self.assertEqual(sorted(REMAP.values()), sorted((WARM, GREEN, RED, AMBER, BLUE)))
        self.assertEqual(len(REMAP), 5)
        # finishAlive's alpha tables are the contract's 5.2 table (classes 1..4; S is D10); the
        # semantic class 2 is 0.62 [M1] where finishAlive draws 1.0. [user 2026-09-26] 12.8: the resting
        # column is one level, 0.34, where finishAlive rests at 0.05 / 0.10 / 0.16.
        aw, rest = constants["AW"], constants["AS"]
        self.assertEqual([rest[cls] for cls in (1, 2, 3, 4)], [0.05, 0.1, 0.16, 0.16])
        for cls in (1, 2, 3, 4):
            self.assertEqual(al.ALPHA_AWAKE_WARM[cls], aw[cls])
            self.assertEqual(al.ALPHA_REST[cls], 0.34)
            self.assertEqual(al.ALPHA_AWAKE_SEMANTIC[cls], {1: 0.45, 2: 0.62, 3: 1.0, 4: 1.0}[cls])
        # The injected accents are the dominant reference (as the v4 golden).
        reference = json.loads(ka.REFERENCE.read_text(encoding="utf-8"))["colors"]
        for key, value in reference.items():
            self.assertEqual(GOLDEN["constants"]["tints"][key], value, key)
        self.assertEqual(GOLDEN["constants"]["tints"]["app:Discord"], "88,101,242")   # COLOR_FALLBACK

    def test_sat_is_the_design_sat_over_its_whole_domain(self):
        """11.2 "sat(x) -> sat(x)": al.sat equals finishAlive's own sat() (lifted verbatim by
        alive_golden.cjs) on every (min, x, max) with max - min >= 30. Each channel is mapped on
        its own given the min and max, so this is the whole domain, including the 14k exact .5
        roundings (JS Math.round: half up); a spread of 29 falls back to WARM (None), 30 does not."""
        ref = GOLDEN["sat"]
        self.assertIn("Math.round(Math.max(0, x - mn * 0.75) / (mx - mn * 0.75) * 255)", ref["source"])
        self.assertIn("if (mx - mn < 30) return WARM", ref["source"])
        table = bytearray()
        sat = al.sat
        for mn in range(256):
            for mx in range(mn + 30, 256):
                for x in range(mn, mx + 1):
                    table.append(sat((mn, x, mx))[1])
        self.assertEqual(len(table), ref["triples"])
        self.assertEqual(hashlib.sha256(bytes(table)).hexdigest(), ref["sha256"],
                         "al.sat differs from the design's sat() (regenerate the golden and diff the table)")
        self.assertGreater(ref["exactHalves"], 10000)
        for mn, x, mx, want in ref["halfSamples"]:
            self.assertEqual(al.sat((mn, x, mx)), tuple(want), (mn, x, mx))
        threshold = ref["threshold"]
        self.assertEqual((threshold["spread29Warm"], threshold["spread30Warm"]), (threshold["colours"], 0))
        self.assertTrue(all(al.sat((mn, mn, mn + 29)) is None for mn in range(threshold["colours"])))
        self.assertTrue(all(al.sat((mn, mn, mn + 30)) is not None for mn in range(threshold["colours"])))

    def test_coverage(self):
        groups = Counter(case["group"] for case in GOLDEN["cases"])
        for group in ("scenario", "stress", "ledRows", "sweep", "volume", "pending", "flash", "lists",
                      "tracks", "windows", "disconnected", "alive"):
            self.assertGreater(groups[group], 0, group)
        ids = {case["id"] for case in GOLDEN["cases"]}
        for case_id in ("home", "home-pidle", "home-none", "home-turn", "home-pend", "home-paused", "home-ext",
                        "home-off", "ra-load", "ra-item", "ra-more", "ra-na", "ra-pend", "ra-part", "ra-auth",
                        "ra-empty", "tr-neu", "tr-next", "tr-done", "tr-noprev", "wi-brw", "wi-closed", "wi-fail",
                        "disc"):
            self.assertIn(case_id, ids)                  # every scenarios() state
        self.assertEqual(groups["stress"], 14)           # every stress() state
        keys = Counter(v["key"] for case in GOLDEN["cases"] for v in case["variants"])
        for key in ("base", "asleep", "ok", "err", "err-asleep", "ext", "ext-asleep"):
            self.assertGreater(keys[key], 0, key)
        flags = Counter()
        for case in GOLDEN["cases"]:
            for v in case["variants"]:
                f = v["flags"]
                flags.update(k for k in ("pending", "heat", "pausedPlay", "songHand") if f[k])
                flags.update(k for k in ("tint", "wash", "washRef") if f[k])
                if f["embers"]:
                    flags["embers"] += 1
                if v["alive"]["ledSleep"]:
                    flags["ledSleep"] += 1
        for key in ("pending", "heat", "pausedPlay", "songHand", "tint", "wash", "washRef", "embers", "ledSleep"):
            self.assertGreater(flags[key], 0, key)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_golden_fixture_is_current(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "alive_golden.json"
            done = subprocess.run([shutil.which("node"), str(ka.ALIVE_GOLDEN_JS), str(ka.ALIVE_DESIGN),
                                   str(ka.REFERENCE), str(out)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=180)
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            self.assertEqual(out.read_text(encoding="utf-8"), ka.ALIVE_GOLDEN.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

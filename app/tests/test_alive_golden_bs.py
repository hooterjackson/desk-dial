"""alive targets (control_center.alive_lights.alive_targets) against the Browse and Snap renderVals().

ALIVE.md revision 2, 11.3 "BS golden". tests/fixtures/alive_golden_bs.json is produced by
tests/js/alive_golden_bs.cjs from the [r2.2] master's "Browse and Snap.dc.html" (the logic block run
unmodified; 11.3 [r2.2]: the liked heart is compared against r2.2's renderVals() footer
{c: PINK, a: 0.3} (R22 BS:1268), PINK 0.30 awake and WARM 0.26 at rest (M32, 12.8); r2.1's PINK 1.0 is no
longer the expected value; every other state is identical in r2.1 and r2.2): per state, the design's
own ring / button targets (this._ring, this._btns), its cursor (this._cursor) and Working flag
(this._working), and the v7 host frame of that state (the mapping of
11.3, done in the generator next to the state it reads). Each frame goes through the host validator
(``device._frame`` for a presentation-5 knob with ``alive``) and ``alive_targets``, awake and at rest.

Compared exactly on role and class, alpha within 1e-6, after the BS remap (11.3): [255,190,105] (BS's
warm marker, isW) -> WARM, [0,255,98] -> GREEN, [255,131,56] -> AMBER, [255,0,0] -> RED, [255,40,90]
on a button -> PINK, any other colour x -> sat(x) (WARM when sat() falls back). BS's targets carry
awake alphas; at rest they go through BS draw()'s own mapping (BS:609 ring thresholds, BS:620
buttons) as the user ruled it on 2026-09-26 (ALIVE.md 12.8, the BS oracle's RULING_PATCH: every lit
segment 0.34, buttons 0.34 / 0.26 on BS:620's split), which is what the knob's resting column must equal. The class of a BS alpha: 0.14 P,
0.30 1, 0.45 Q in Up next (1 elsewhere), 0.62 2, 0.70 N, 0.81 S, 1.0 3. Also compared: the cursor, the
Working comet (pending), heat, the tint (BS:634 with the remap) and the paused-Play breath (BS:617).

Every difference is a listed tag (11.3): M4 (the Tracks Prev cursor 52, BS 53), M14 (the Up next card:
counted in the window geometry, no cell, moments at its slot; BS windows over the rows without it and
falls to cursor 0); D10 (the half-step rested at 0.13, BS 0.10) no longer differs since 12.8 rests every
level at 0.34. One more difference follows the
contract's own rule but is not yet a listed deviation (PENDING_12_4, WP2-F5): during Starting... the
disabled Play gets no paused-Play breath (5.3 row 2 wins over row 9), where BS:617/621 breathes
Button 1 whenever Home is paused; the engine departs from BS draw() there. VOC-D02 (the snap colour in
sat()) and M26 (the warm marker sent as 0) are absorbed by the remap and the host mapping; they are
counted, never differences. The states BS
does not model (the pending span, external, the pending pulse) are compared against ALIVE.md only
(test_alive_lights.py).

Regenerate after a deliberate change (node is needed only for the golden):
    node tests\\js\\alive_golden_bs.cjs design-reference\\design_handoff_nano_d_master_r2.2\\prototypes tests\\fixtures\\alive_golden_bs.json
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import alive_lights as al  # noqa: E402
from control_center import device  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "alive_golden_bs.json"
GENERATOR = ROOT / "tests" / "js" / "alive_golden_bs.cjs"
DESIGN = ROOT / "design-reference" / "design_handoff_nano_d_master_r2.2" / "prototypes"      # 11.3 [r2.2]
ALIVE_MD = ROOT.parent / "firmware" / "ALIVE.md"
CAPS_V5 = {"presentation": 5, "glyphs": "latin-ext-a", "alive": {"version": 1, "fps": 60, "drive": 150}}
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))
K = GOLDEN["constants"]
WARM8, GREEN8, AMBER8, RED8, PINK8 = (tuple(K[k]) for k in ("WARM", "GREEN", "AMBER", "RED", "PINK"))
TAGS = {
    "M4": "ALIVE M4: the Tracks Prev cursor is 52 (BS's cursor is the last cell at 1.0: 53)",
    "M14": "ALIVE M14: the Up next card counts in the window geometry and draws no cell; moments start at its "
           "slot (BS windows over the rows without it and falls to cursor 0, BS:1332)",
    "5.3-row2": "ALIVE 5.3 row 2 before row 9 (row 9: 'enabled: row 2 already took disabled'): a disabled Play during "
                "Starting... gets no paused-Play breath; BS:617/621 breathes Button 1 whenever Home is paused. The "
                "engine departs from BS draw() here; not yet listed in 12.4 (PENDING_12_4)",
}
# 11.3: every mismatch must be a listed deviation. A tag here follows the contract's text but still needs its
# 12.4 entry (and a 12.3 id if the ALIVE.md owner gives it one); requested with WP2-F5. When the owner lists
# it, retag with that id and remove it from this set.
PENDING_12_4 = {"5.3-row2"}
ABSORBED = {
    "VOC-D02": "the snap button in sat(app colour) (BS: the raw colour, BS:1282); the remap applies sat() to BS",
    "M26": "the warm-marker colour [255,190,105] is sent as 0 (BS draws it WARM, isW)",
}
CLASS_OF = {0.14: "P", 0.3: 1, 0.62: 2, 0.7: "N", 0.81: "S", 1: 3}


def role_of(c, button=False):
    """The BS remap (11.3): (role, accent rgb or None)."""
    c = tuple(c)
    if c == WARM8:
        return al.ROLE_WARM, None
    if c == GREEN8:
        return al.ROLE_GREEN, None
    if c == AMBER8:
        return al.ROLE_AMBER, None
    if c == RED8:
        return al.ROLE_RED, None
    if button and c == PINK8:
        return al.ROLE_PINK, None
    s = al.sat(c)
    return (al.ROLE_ACCENT, s) if s is not None else (al.ROLE_WARM, None)


def bs_class(alpha, upnext):
    if alpha == 0.45:
        return "Q" if upnext else 1
    return CLASS_OF[alpha]


def rest_ring(alpha):
    return 0.34             # BS:609 (0.16 / 0.10 / 0.05) as ruled [user 2026-09-26] 12.8: one resting level


def rest_button(alpha):
    return 0.34 if alpha >= 0.5 else 0.26          # BS:620 split (was 0.12 / 0.04) as ruled [user 2026-09-26] 12.8


def expected(case, asleep):
    """BS's targets as the knob's cells (role, class, alpha, rgb) after the remap and BS's resting map."""
    upnext = case["mode"] == "queue"
    ring = []
    for cell in case["ring"]:
        if cell is None:
            ring.append(None)
            continue
        c, a = cell
        role, rgb = role_of(c)
        cls = 1 if case["mode"] == "offline" else bs_class(a, upnext)
        ring.append((al.ROLE_WARM, cls, rest_ring(a), None) if asleep else (role, cls, a, rgb))
    buttons = []
    for c, a in case["buttons"]:
        if not a:
            buttons.append(None)
            continue
        role, rgb = role_of(c, button=True)
        buttons.append((al.ROLE_WARM, None, rest_button(a), None) if asleep else (role, None, a, rgb))
    return ring, buttons


def ours(cell, button=False):
    if cell is None:
        return None
    return (cell.role, None if button else cell.cls, cell.alpha, tuple(cell.rgb) if cell.role == al.ROLE_ACCENT else None)


def same(a, b):
    if a is None or b is None:
        return a is b
    return a[0] == b[0] and a[1] == b[1] and abs(a[2] - b[2]) <= 1e-6 and a[3] == b[3]


def targets_of(case, asleep):
    frame = case["frame"]
    if frame is None:
        return al.alive_targets(None), None
    wired = device._frame(frame, CAPS_V5)
    return al.alive_targets(wired, state_asleep=asleep, pending_ms=0), wired


class AliveGoldenBSTests(unittest.TestCase):
    def test_every_state_matches_browse_and_snap_except_tagged_deviations(self):
        used, absorbed, compared = Counter(), Counter(), 0
        for case in GOLDEN["cases"]:
            for asleep in (False, True):
                if asleep and (case["frame"] is None or case["frame"]["activity"] in ("pending", "loading")):
                    continue            # unclaimed never rests; pending never rests (6.1; BS does not model it)
                t, wired = targets_of(case, asleep)
                ring, buttons = expected(case, asleep)
                tags = Counter()
                with self.subTest(case=case["id"], asleep=asleep):
                    long = case["id"].startswith("upnext-longshuffle")
                    for i in range(60):
                        got, want = ours(t.ring[i]), ring[i]
                        if same(got, want):
                            continue
                        if long:
                            tags["M14"] += 1
                        else:
                            self.fail(f"segment {i}: ours {got}, BS {want}")
                    for j in range(4):
                        got, want = ours(t.buttons[j], True), buttons[j]
                        self.assertTrue(same(got, want), f"button {j}: ours {got}, BS {want}")
                    if not asleep:                                          # BS's cursor is an awake notion
                        if t.cursor != case["cursor"]:
                            if case["id"] == "tracks--1" and (t.cursor, case["cursor"]) == (52, 53):
                                tags["M4"] += 1
                            elif long:
                                tags["M14"] += 1
                            else:
                                self.fail(f"cursor: ours {t.cursor}, BS {case['cursor']}")
                    self.assertEqual(t.pending, case["working"], "the Working comet")
                    mode = case["mode"]
                    self.assertEqual(t.heat, mode == "home" and not asleep and (wired or {}).get("ring", {}).get("value", 0) >= 90)
                    bs_paused = mode == "home" and not case["playing"] and not asleep
                    if t.paused_play != bs_paused:
                        self.assertEqual(case["id"], "home-starting")
                        self.assertFalse(t.paused_play)                     # the engine never breathes a dim Play
                        tags["5.3-row2"] += 1
                    cr = case["ring"][case["cursor"]]
                    bs_tint = None
                    if mode in ("recent", "explore", "queue", "windows") and not asleep and cr and tuple(cr[0]) != WARM8:
                        role, rgb = role_of(cr[0])
                        bs_tint = rgb
                    tint = tuple(round(x * 255) for x in t.tint) if t.tint is not None else None
                    if tint != bs_tint:
                        self.assertTrue(long, f"tint: ours {tint}, BS {bs_tint}")
                        tags["M14"] += 1
                used.update(tags)
                compared += 1
                for b in (wired or {}).get("buttons", ()):
                    if b.get("lit") == "on" and "color" in b and al.sat(al.rgb_tuple(b["color"])) != al.rgb_tuple(b["color"]):
                        absorbed["VOC-D02"] += 1
                if wired and wired["ring"].get("style") == "selection" and 0 in wired["ring"].get("colors", ()):
                    absorbed["M26"] += 1
        self.assertGreaterEqual(compared, 100)
        self.assertEqual(set(used) - set(TAGS), set())
        for tag in TAGS:
            self.assertGreater(used[tag], 0, f"{tag} is never exercised")
        for tag in ABSORBED:
            self.assertGreater(absorbed[tag], 0, f"{tag} never occurs")
        print(f"\n[alive BS golden] {len(GOLDEN['cases'])} states, {compared} comparisons; tagged: "
              + ", ".join(f"{k} {used[k]}" for k in sorted(used)) + "; absorbed: "
              + ", ".join(f"{k} {absorbed[k]}" for k in sorted(absorbed)))

    def test_host_frames_are_wire_valid(self):
        for case in GOLDEN["cases"]:
            frame = case["frame"]
            if frame is None:
                continue
            with self.subTest(case=case["id"]):
                wired = device._frame(frame, CAPS_V5)
                for key in ("layout", "activity", "buttons"):
                    self.assertEqual(wired.get(key), frame.get(key), key)
                for key in ("style", "index", "count", "colors", "now", "card"):
                    self.assertEqual(wired["ring"].get(key), frame["ring"].get(key), key)

    def test_hand_checked_states(self):
        by = {case["id"]: case for case in GOLDEN["cases"]}
        # Home 55: endpoint 2, half-step 3 at 0.81 (M13 is BS's own placement); 89: AMBER (the M2 gate).
        t, _ = targets_of(by["home-55"], False)
        self.assertEqual((t.cursor, ours(t.ring[3])), (2, (al.ROLE_WARM, "S", 0.81, None)))
        t, _ = targets_of(by["home-89"], False)
        self.assertEqual(ours(t.ring[(35 + 45) % 60])[:2], (al.ROLE_AMBER, "S"))
        # [r2.2][M32] The liked heart is PINK 0.30 (r2.1: 1.0) and rests WARM 0.26 (12.8); Seek lit on; the explorer's
        # off tab 0.30.
        t, _ = targets_of(by["upnext-liked"], False)
        self.assertEqual(ours(t.buttons[2], True), (al.ROLE_PINK, None, 0.3, None))
        t, _ = targets_of(by["upnext-liked"], True)
        self.assertEqual(ours(t.buttons[2], True), (al.ROLE_WARM, None, 0.26, None))
        t, _ = targets_of(by["seek-q4-74"], False)
        self.assertEqual((ours(t.buttons[2], True), ours(t.buttons[3], True)),
                         ((al.ROLE_WARM, None, 1.0, None), (al.ROLE_WARM, None, 0.14, None)))
        t, _ = targets_of(by["explore-recent-10"], False)
        self.assertEqual((ours(t.buttons[1], True)[2], ours(t.buttons[2], True)[2]), (1.0, 0.30))
        # The card: no cell at its slot, the cursor at it (M14); BS falls to 0.
        case = by["upnext-longshuffle-card"]
        t, wired = targets_of(case, False)
        self.assertEqual((wired["ring"]["card"], wired["ring"]["count"], wired["ring"]["now"]), (True, 6, 4))
        self.assertIsNone(t.ring[t.cursor])
        self.assertEqual(case["cursor"], 0)

    def test_r22_golden_reads_the_r22_design(self):
        """11.3 [r2.2] (WP2-F2): the golden is generated from the r2.2 BS, whose renderVals() gives the liked heart
        {c: PINK, a: 0.3, ink: '#A3244A'}; the fixture carries that value, not r2.1's PINK 1.0."""
        self.assertIn("design_handoff_nano_d_master_r2.2", GOLDEN["design"])
        self.assertIn("design_handoff_nano_d_master_r2.2", str(DESIGN))
        html = (DESIGN / "Browse and Snap.dc.html").read_text(encoding="utf-8")
        self.assertIn("F(I.heart, 'on', 'Already liked · unfavourite in the Music app', "
                      "{ fill: I.heart, c: PINK, a: 0.3, ink: '#A3244A' })", html)      # R22 BS:1268
        case = next(c for c in GOLDEN["cases"] if c["id"] == "upnext-liked")
        self.assertEqual(case["buttons"][2], [list(PINK8), 0.3])
        self.assertEqual(case["foot"][2], {"icon": "heart", "tone": "liked", "c": None})
        self.assertEqual(case["frame"]["buttons"][2], {"label": "b2", "enabled": True, "icon": "heart", "lit": "on"})
        self.assertEqual(expected(case, False)[1][2], (al.ROLE_PINK, None, 0.3, None))
        self.assertEqual(expected(case, True)[1][2], (al.ROLE_WARM, None, 0.26, None))

    @unittest.skipUnless(ALIVE_MD.is_file(), "ALIVE.md is not next to the companion")
    def test_every_tag_is_a_listed_deviation(self):
        """11.3 (WP2-F5): every tag is an id listed in ALIVE.md section 12, except the ones in PENDING_12_4, which
        must cite the contract rule the engine follows and wait for their 12.4 entry."""
        text = ALIVE_MD.read_text(encoding="utf-8")
        section = text[text.index("\n## 12. "):text.index("\n## 13. ")]
        listed = set()
        for line in section.splitlines():
            if line.startswith("| "):
                head = line.split("|")[1]
            elif line.startswith("- **"):
                head = line.split("**")[1]
            else:
                continue
            listed.update(re.findall(r"\b(?:VOC-)?[A-Z]\d+\b", head))
        self.assertLessEqual({"M4", "M14", "D10", "D3", "M32", "M33", "VOC-D02"}, listed)   # the parser reads 12
        self.assertEqual({t for t in TAGS if t not in listed}, PENDING_12_4)
        self.assertLessEqual(set(ABSORBED), listed)
        self.assertNotIn("BS617", listed)
        # The pending tag's rule is the contract's own text (5.3 row 9: row 2 already took a disabled Play).
        self.assertIn("(enabled: row 2 already took disabled)", text)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_golden_fixture_is_current(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "alive_golden_bs.json"
            done = subprocess.run([shutil.which("node"), str(GENERATOR), str(DESIGN), str(out)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=180)
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            self.assertEqual(out.read_text(encoding="utf-8"), FIXTURE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

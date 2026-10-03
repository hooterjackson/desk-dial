"""The evidence of the 2026-09-26 LED ruling (ALIVE.md 12.7): dither off by default + the F-T floor.

On the hardware, cc5.4 binary A's temporal dither (ALIVE.md 9 step 4, then on by default) toggled most
resting and offline LEDs by one count every frame: they sit at 0-3 counts, where a one-count toggle is
a visible flicker. The user ruled (2026-09-26): dither OFF by default, plus a minimum brightness floor
so that the dimmest designed marks stay visible (with plain rounding, a mark below half a count goes
dark). This tool measures the floor candidates on both design oracles, which carry the designs' own
tone-mapped ``e`` for every step (tests/fixtures/alive_oracle.json, RC; alive_oracle_bs.json, BS), and on
the engine's own breathing marks over time:

* section 9 at drive 150 with dither off (``alive_lights.reference_output``: sRGB EOTF, drive, the
  [D17] power limit, round half up) on each step's rounded ``e``;
* an LED is **target-lit** when its entry in the step's persistent view is non-null with ``a > 0``
  (``alive_lights.lit_masks(oracle_targets(view))``, firmware ``cc_alive_lit``);
* a target-lit LED-step whose plain rounding is dark while m = max_c v_c > 0 is a **mark to floor**.

Rule F-T floors exactly the marks to floor (the mask is the target, not ``e``). Its channel candidates
(each applied only to the marks to floor, every other LED keeps plain rounding):

* ``dominant-only`` (chosen): one count on every channel equal to m (the dominant one; a tie lights
  each tied channel), the rest 0: the byte plain rounding shows just above m = 0.5.
* ``proportional``: q_c = round(v_c / m), the dominant channel 1 and a channel >= m / 2 also 1. The
  first reading of F-T, superseded the same day: plain rounding leaves such a channel dark just above
  m = 0.5, so a breathing mark lit it at its dim point and dropped it on both sides (``continuity``).
* ``per-channel``: every channel with v_c > 0 at 1.
* ``e-threshold`` (a mask-free alternative): any LED, lit target or not, whose max e >= 1/256 and
  whose plain rounding is dark is floored; counted for what it would light that has no target.

The hue error of a floored LED is the angle between its output bytes and (a) the ideal linear value
v (what the design's e asks the LED for through the section 9 transfer; in the EOTF's linear toe, where
every floored mark sits, that ratio is the design-space one, so AMBER asks for 0.51 green per red
instead of its full-level 0.23) and (b) the cell's full-level colour (eotf of its design colour: the
hue the same cell has when bright). Both are in linear light, which is what the LED's PWM emits.

``continuity`` runs the Python engine frame by frame (16/17/17 ms) through the breaths the floor
serves: offline (the 12 amber marks) and asleep on Home at several clock times (the resting ring and
buttons at night), and counts, per candidate, over consecutive frames of a target-lit LED: a floored
byte with more counts than the plain byte next to it in time, and a channel that moves against its
value (every v_c rising while some q_c falls, or the reverse). [user 2026-09-26, later the same day,
ALIVE.md 12.8] Resting is now one steady warm white at 0.34 (no breath, time of day >= 0.80), so the
asleep runs no longer reach the floor (they stay in the report as evidence that nothing there flickers)
and the BS oracle's resting marks are visible; the oracles still carry the floor on their offline marks,
their dim design targets (RC) and their fades.

Writes diagnostics/cc5.4-alive-floor-report.json (deterministic: no run time in it). An existing
report with other content is kept as ``cc5.4-alive-floor-report.superseded-<UTC>.json`` first.
``--check`` only compares. Usage:
    .venv\\Scripts\\python.exe tests\\tools\\alive_floor_report.py [--check]
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import alive_lights as al  # noqa: E402

REPORT = ROOT / "diagnostics" / "cc5.4-alive-floor-report.json"
ORACLES = (ROOT / "tests" / "fixtures" / "alive_oracle.json", ROOT / "tests" / "fixtures" / "alive_oracle_bs.json")
DRIVE = al.DEFAULT_DRIVE
E_THRESHOLD = 1 / 256
KNIFE = 0.005          # counts around the 0.5 plain-rounding threshold (float32 knob vs float64 twin)


def _round(x):
    return min(255, max(0, math.floor(x + 0.5)))


def _pack(q):
    return (q[0] << 16) | (q[1] << 8) | q[2]


def _angle(q, v):
    nq, nv = math.sqrt(sum(x * x for x in q)), math.sqrt(sum(x * x for x in v))
    if nq == 0 or nv == 0:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(q, v)) / (nq * nv)))))


def _stats(values):
    values = sorted(x for x in values if x is not None)
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(sum(values) / len(values), 1),
            "p95": round(values[int(0.95 * (len(values) - 1))], 1), "max": round(values[-1], 1)}


def _values(expect):
    """Per LED (60 ring, 4 buttons) the drive- and power-limited channel values v (float64)."""
    lin = [[al.srgb_eotf(x) * DRIVE for x in c] for c in expect["ring"] + expect["buttons"]]
    total = 0.0
    for k, c in enumerate(lin):
        total += (1 if k < 60 else al.BUTTON_LEDS_PER_SLOT) * (c[0] + c[1] + c[2])
    scale = al.POWER_BUDGET / total if total > al.POWER_BUDGET else 1.0
    return [[x * scale for x in c] for c in lin]


CHOSEN = "dominant-only"
CANDIDATES = {
    "dominant-only": lambda v, m: [1 if x >= m else 0 for x in v],
    "proportional": lambda v, m: [math.floor(x / m + 0.5) for x in v],
    "per-channel": lambda v, m: [1 if x > 0 else 0 for x in v],
}
# The engine runs of ``continuity``: (label, clock minute or None, claimed) -- offline, then asleep on Home.
CONTINUITY_RUNS = (("offline", None, False), ("asleep, clock unset", None, True), ("asleep 00:00", 0, True),
                   ("asleep 06:00", 6 * 60, True), ("asleep 21:00", 21 * 60, True),
                   ("asleep 22:30", 22 * 60 + 30, True), ("asleep 23:00", 23 * 60, True))
CONTINUITY_MS = 20000          # measured per run, after the settle (the reveal offline; asleep and damped on Home)
HOME_FRAME = {"id": 1, "mode": "VOLUME", "target": "Hall", "value": "54%", "detail": "", "status": "",
              "activity": "idle", "layout": "nowPlaying", "ledStyle": "color", "confirmedVolume": 54,
              "buttons": [{"label": label, "enabled": True, "icon": icon} for label, icon in
                          (("Pause", "pause"), ("Browse", "list"), ("Win", "win"), ("Tracks", "tracks"))],
              "ring": {"style": "level", "value": 54, "index": 0, "count": 101, "external": False}}


def _output(v, lit, rule):
    """(section 9 bytes (r, g, b) of one LED with dither off and `rule` as the F-T channel rule, floored?)."""
    plain = [_round(x) for x in v]
    m = max(v)
    if lit and not any(plain) and m > 0:
        return tuple(rule(v, m)), True
    return tuple(plain), False


def continuity():
    """Per candidate, over the engine runs, frame by frame on every target-lit LED: floored bytes with more
    counts than the plain byte next to them in time, channels that move against their value, byte changes."""
    result = {name: {"flooredBrighterThanAdjacentPlain": 0, "channelAgainstValue": 0, "byteChanges": 0,
                     "flooredLedFrames": 0} for name in CANDIDATES}
    runs = []
    steps = (16, 17, 17)
    for label, minute, claimed in CONTINUITY_RUNS:
        eng = al.AliveLights(0)
        start, frame = 0, None
        if claimed:
            start, frame = 1000, HOME_FRAME
            eng.claim(start)
            if minute is not None:
                eng.set_clock(start, minute)
        settle = start + (al.SLEEP_MS + 6000 if claimed else 2000)
        prev = {name: None for name in CANDIDATES}
        now, k, frames = start, 0, 0
        while now < settle + CONTINUITY_MS:
            ring_e, button_e = eng.render(now, frame)
            ring_lit, button_lit = eng.lit_masks()
            if now >= settle:
                lit = ring_lit + button_lit
                values = _values({"ring": ring_e, "buttons": button_e})
                visible = [any(_round(x) for x in v) for v in values]
                frames += 1
                for name, rule in CANDIDATES.items():
                    cur = [(lit[i], values[i]) + _output(values[i], lit[i], rule) + (visible[i],) for i in range(64)]
                    r = result[name]
                    r["flooredLedFrames"] += sum(1 for c in cur if c[3])
                    if prev[name] is not None:
                        for (l0, v0, q0, f0, p0), (l1, v1, q1, f1, p1) in zip(prev[name], cur):
                            r["byteChanges"] += q0 != q1
                            if not (l0 and l1):
                                continue
                            if (f0 and p1 and sum(q0) > sum(q1)) or (f1 and p0 and sum(q1) > sum(q0)):
                                r["flooredBrighterThanAdjacentPlain"] += 1
                            up = all(b >= a for a, b in zip(v0, v1))
                            down = all(b <= a for a, b in zip(v0, v1))
                            if (up and any(b < a for a, b in zip(q0, q1))) or \
                                    (down and any(b > a for a, b in zip(q0, q1))):
                                r["channelAgainstValue"] += 1
                    prev[name] = cur
            now += steps[k % 3]
            k += 1
        runs.append({"run": label, "framesMeasured": frames})
    return {"runs": runs, "measuredMsPerRun": CONTINUITY_MS, "candidates": result,
            "note": "per target-lit LED over consecutive frames: a floored byte with more counts than the plain byte "
                    "next to it in time (the dim point brighter, or another hue, than its sides), and a channel that "
                    "moves against its value (every v_c rising while some q_c falls, or the reverse)"}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build():
    lit_steps = visible = to_floor = zero_m = 0
    visible_changed = floor_mismatch = unlit_changed = 0
    unlit_e_floor = e_floor = 0
    knife = knife_same = 0
    steps_total = 0
    worst_added = 0
    levels = Counter()
    angles_v = {name: [] for name in CANDIDATES}
    angles_full = {name: [] for name in CANDIDATES}
    patterns = {name: Counter() for name in CANDIDATES}
    per_oracle = {}
    for path in ORACLES:
        data = json.loads(path.read_text(encoding="utf-8"))
        warm_default = data.get("designConstants", {}).get("WARM")
        oracle_floor = 0
        for case in data["cases"]:
            warm = case.get("warm") or warm_default
            view = None
            for step in case["steps"]:
                steps_total += 1
                view = step.get("view", view)
                cells = view["ring"] + view["buttons"]
                ring_lit, button_lit = al.lit_masks(al.oracle_targets(view))
                lit = ring_lit + button_lit
                e = step["expect"]["ring"] + step["expect"]["buttons"]
                recorded = step["expect"]["bytes"]                  # the oracle's own section 9 bytes
                added = 0
                for k, v in enumerate(_values(step["expect"])):
                    plain = [_round(x) for x in v]
                    m = max(v)
                    if not any(plain) and max(e[k]) >= E_THRESHOLD:
                        e_floor += 1
                        unlit_e_floor += not lit[k]
                    if not lit[k]:
                        unlit_changed += recorded[k] != _pack(plain)
                        continue
                    lit_steps += 1
                    if abs(m - 0.5) < KNIFE:
                        knife += 1
                        # Just below 0.5: the floor; just above: plain rounding at m = 0.5 (the dominant only).
                        below = CANDIDATES[CHOSEN](v, m)
                        above = [_round(x * 0.5 / m) for x in v]
                        knife_same += below == above
                    if any(plain):
                        visible += 1
                        visible_changed += recorded[k] != _pack(plain)
                        continue
                    if not m > 0:
                        zero_m += 1
                        continue
                    to_floor += 1
                    oracle_floor += 1
                    floor_mismatch += recorded[k] != _pack(CANDIDATES[CHOSEN](v, m))
                    levels[round(m, 2)] += 1
                    colour = warm if cells[k].get("warm") else [x / 255 for x in cells[k]["c"]]
                    full = [al.srgb_eotf(x) for x in colour]
                    for name, rule in CANDIDATES.items():
                        q = rule(v, m)
                        angles_v[name].append(_angle(q, v))
                        angles_full[name].append(_angle(q, full))
                        patterns[name]["#%02X%02X%02X" % tuple(q)] += 1
                    added += (1 if k < 60 else al.BUTTON_LEDS_PER_SLOT) * sum(CANDIDATES[CHOSEN](v, m))
                worst_added = max(worst_added, added)
        per_oracle[path.name] = {"sha256": _sha256(path), "cases": len(data["cases"]),
                                 "steps": sum(len(c["steps"]) for c in data["cases"]), "marksToFloor": oracle_floor}
    # A mark fading asleep (tau 700 ms) from the 0.5-count level at drive 150 to e = 1/256.
    e_half = al.srgb_oetf(0.5 / DRIVE)
    hold_ms = round(al.TAU_RING_REST_DOWN * math.log(e_half / E_THRESHOLD))
    return {
        "report": "cc5.4-alive-floor-report",
        "generator": "app/tests/tools/alive_floor_report.py",
        "ruling": {
            "id": "ALIVE.md 12.7", "by": "user", "date": "2026-09-26",
            "text": "Temporal dither OFF by default (ledDither:true re-enables it); a minimum brightness floor keeps "
                    "the dimmest designed marks visible. Rule F-T: a target-lit LED whose plain rounding is dark "
                    "while m = max v > 0 shows one count on its dominant channel (every channel equal to m; a tie "
                    "lights each), the rest 0.",
            "amended": "2026-09-26, after the fix build's review: the first channel rule, round(v / m), also lit a "
                       "channel >= m/2, which plain rounding leaves dark just above m = 0.5; a breathing mark then "
                       "lit that channel at its dim point and dropped it on both sides (the offline amber marks went "
                       "#010100 -> #010000 -> #010100 at the dim point -> #010000). The dominant-only rule is the byte "
                       "plain rounding shows just above 0.5, so the breath passes through the floor without a jump "
                       "(continuity).",
            "why": "binary A on the hardware (2026-09-26): the dither toggled most resting/offline LEDs by one "
                   "count every frame at their 0-3 count levels (a visible flicker); with dither off and plain "
                   "rounding, marks below half a count go dark.",
        },
        "method": {"drive": DRIVE, "dither": False, "powerBudget": al.POWER_BUDGET,
                   "targetLit": "view entry non-null with a > 0 (alive_lights.lit_masks / firmware cc_alive_lit)",
                   "hueError": "degrees between the output bytes and (a) the ideal linear v, (b) the cell's "
                               "full-level colour eotf(c), both in linear light",
                   "eThreshold": E_THRESHOLD, "knifeBand": KNIFE},
        "oracles": per_oracle,
        "counts": {"steps": steps_total, "targetLitLedSteps": lit_steps, "alreadyVisible": visible,
                   "marksToFloor": to_floor, "targetLitWithZeroE": zero_m,
                   "oracleBytes": {"visibleChangedFromPlain": visible_changed, "unlitChangedFromPlain": unlit_changed,
                                   "marksNotFT": floor_mismatch},
                   "markLevels": {f"{m:.2f}": n for m, n in sorted(levels.items(), key=lambda kv: -kv[1])[:12]}},
        "candidates": {
            name: {"hueErrorVsIdealV": _stats(angles_v[name]), "hueErrorVsFullLevelColour": _stats(angles_full[name]),
                   "bytes": dict(patterns[name].most_common())}
            for name in CANDIDATES},
        "eThresholdAlternative": {
            "floorsLedSteps": e_floor, "withoutTarget": unlit_e_floor,
            "withoutTargetShare": round(unlit_e_floor / e_floor, 2) if e_floor else 0,
            "holdOfAFadingMarkMs": hold_ms,
            "note": "effect tails, halos and gaussian skirts have no target; a mark fading asleep (tau 700 ms) "
                    "from 0.5 count to e = 1/256 would stay at one count for about this long"},
        "knifeEdge": {"ledStepsWithinBand": knife, "identicalBytesEitherSide": knife_same,
                      "note": "target-lit LED-steps whose largest channel is within the band of 0.5 count, where the "
                              "float32 knob and the float64 twin may round differently; under the dominant-only "
                              "floor both sides give the same bytes (the floor is plain rounding at m = 0.5)"},
        "continuity": continuity(),
        "power": {"maxCountsAddedPerStep": worst_added, "bound": 68 * 3, "budget": al.POWER_BUDGET},
        "choice": {
            "rule": "F-T", "channels": CHOSEN, "superseded": "proportional (round(v / m), 2026-09-26)",
            "why": ["F-T leaves every already-visible byte identical and lights exactly the target-lit marks "
                    "that plain rounding darkens (no unlit tail, halo or fading mark);",
                    "dominant-only is the only candidate continuous with plain rounding: a mark breathing through "
                    "half a count never shows a floored byte brighter than, or of another hue from, the plain "
                    "bytes on either side, and no channel moves against its value (continuity: zero events, where "
                    "the proportional rule toggles a second channel twice per breath);",
                    "lowest mean hue error against the cell's full-level colour (the hue the mark has when "
                    "bright: an amber mark dims as red, its dominant channel, not yellow); against the ideal v "
                    "it is the worst, because in the EOTF's linear toe v's ratios are the design-space ones "
                    "(AMBER 0.51 green per red instead of 0.23);",
                    "both sides of the 0.5-count knife edge give the same bytes, so the float32 knob and the "
                    "float64 twin agree there;",
                    "it is one pure per-LED rule on the dither-off path, identical in C++ (float32), Python and "
                    "the JS oracles (float64), with at most 68 x 3 counts added to a 16920 budget."]},
    }


def dumps(report):
    return json.dumps(report, indent=2, sort_keys=False) + "\n"


def main(argv):
    text = dumps(build())
    current = REPORT.read_text(encoding="utf-8") if REPORT.is_file() else None
    if "--check" in argv:
        if current != text:
            print(f"{REPORT} is out of date; run tests/tools/alive_floor_report.py")
            return 1
        print(f"{REPORT} is up to date")
        return 0
    if current == text:
        print(f"{REPORT} unchanged")
        return 0
    if current is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        kept = REPORT.with_name(f"{REPORT.stem}.superseded-{stamp}.json")
        REPORT.rename(kept)
        print(f"kept the previous report as {kept.name}")
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

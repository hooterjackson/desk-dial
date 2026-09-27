"""ALIVE.md 11.3 twin replay fixture: harness/alive_sequences.json.

tests/tools/make_alive_sequences.py runs engine-level timelines (frames, local position, detents,
limits, presses, clock, progress, claim, release, reset, native-handover reveal, drive/dither)
through control_center.alive_lights.AliveLights and records e, the section 9 output bytes
(dither off, on a subset; [user 2026-09-26] with the F-T floor and its mask "lit", ALIVE.md 12.7),
asleep/cursor/flash, the effect queue and animating per render.
harness/alive_tests.py (MSVC) replays the same file through the firmware's CCAlive with
every frame parsed by cc_parse_frame; that comparison is the C++ half of 11.3.

These tests check the Python half: the committed fixture is what the engine produces now (like
``make_light_sequences --check``), its frames are wire-valid (the v6 host's v4 frames plus the ALIVE.md
section 3 fields; [r2] the v7 host's PRESENTATION_V5 frames through ``device._frame`` for a
presentation-5 knob with ``alive``) within the byte budgets, and the timelines cover every section 6
event, the 6.3 local-cursor rules, offline/release/reset/native handover [M29], time of day, the song
hand, both LED styles, the pending accent, the clock and millis wraps and the output stage, plus the
revision 2 additions of 11.4: every moment (rows c-h) with the PRNG sequence, MODE on transport <-> lap
and not on a tab switch, the explorer / upnext families, reduced motion, the M15 re-centring, the M16
guard, the M22 hold, set_tuning, the Up next card (raw frames included), loading vs an unloaded entry
and the Q1 End stop per push; [r2.2] the liked button at PINK 0.30 -> WARM 0.26 at rest (M32, 12.8) and a Seek
span that keeps activity pending across two jumps with no comet gap (M33; ``expect.pending``).

Regenerate after a deliberate engine or sequence change:
    .venv\\Scripts\\python.exe tests\\tools\\make_alive_sequences.py
"""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tests" / "tools"
for _path in (str(ROOT), str(TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import alive_lights as al  # noqa: E402
from control_center import device, presentation as P  # noqa: E402
import make_alive_sequences as mas  # noqa: E402

CAPS_V4 = {"presentation": 4, "glyphs": "latin-ext-a"}
U32 = 2 ** 32
HOME_LAYOUTS = ("nowPlaying", "volume", "idle", "notice")
EFFECTS = ("boot", "down", "wake", "tick", "bound", "bloom", "fail", "sweep", "fill", "drain", "shimmer",
           "wash", "reveal", "press", "half", "scatter")


def v4_part(frame):
    """The frame without the ALIVE.md section 3 frame content (``playing``, ``feedback.skip``)."""
    out = {k: v for k, v in frame.items() if k != "playing"}
    if isinstance(out.get("feedback"), dict):
        out["feedback"] = {k: v for k, v in out["feedback"].items() if k != "skip"}
    return out


class AliveSequenceFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = mas.build()
        cls.text = mas.dumps(cls.data)
        cls.frames = cls.data["frames"]
        cls.cases = cls.data["cases"]

    def steps(self, name=None):
        for case_name, case in self.cases.items():
            if name is None or case_name == name:
                yield from ((case_name, i, s) for i, s in enumerate(case["steps"]))

    def frame(self, step):
        return self.frames[step["frame"]] if "frame" in step else None

    def rows(self, name=None):
        for case_name, i, step in self.steps(name):
            for row in step["expect"]["fx"]:
                yield case_name, i, step, row

    # ------------------------------------------------------------- the file
    def test_fixture_is_current(self):
        self.assertTrue(mas.OUTPUT.is_file(), f"{mas.OUTPUT} is missing; run tests/tools/make_alive_sequences.py")
        self.assertEqual(mas.OUTPUT.read_text(encoding="utf-8"), self.text,
                         "alive_sequences.json is out of date; run tests/tools/make_alive_sequences.py "
                         "(and harness/alive_tests.py for the C++ half)")

    def test_format(self):
        d = self.data
        self.assertEqual((d["version"], d["tolerance"], d["byteTolerance"], d["eScale"]), (2, 0.002, 1, 100000))
        self.assertGreaterEqual(len(self.cases), 24)
        total = 0
        for name, i, step in self.steps():
            total += 1
            expect = step["expect"]
            self.assertEqual(len(expect["e"]), 192, (name, i))
            self.assertTrue(all(type(x) is int and 0 <= x <= d["eScale"] for x in expect["e"]), (name, i))
            if "bytes" in expect:
                self.assertEqual(len(expect["bytes"]), 64)
                self.assertFalse(step.get("dither", False), "bytes are recorded with dither off only")
                self.assertRegex(expect["lit"], r"^[0-9a-f]{16}$")          # [user 2026-09-26] the F-T mask
            else:
                self.assertNotIn("lit", expect)
            self.assertIn(expect["flash"], (0, 1, 2))
            self.assertTrue(0 <= expect["cursor"] < 60)
            self.assertEqual(set(step) - {"now", "ops", "frame", "local", "drive", "dither", "expect", "raw"}, set())
            if "lim" in expect:
                self.assertTrue(expect["lim"] and set(expect["lim"]) <= {-1, 1})
            self.assertTrue(0 <= step["now"] < U32)
        self.assertGreater(total, 8000)
        with_bytes = sum(1 for _, _, s in self.steps() if "bytes" in s["expect"])
        with_animating = sum(1 for _, _, s in self.steps() if "animating" in s["expect"])
        self.assertGreater(with_bytes, 2000)
        self.assertGreater(with_animating, 0.95 * total)     # only knife edges are left out

    def test_frames_are_wire_valid_within_the_budget(self):
        latched = {"clock": 1439, "progress": {"pos": 86400000, "dur": 86400000}, "ledDrive": 255,
                   "ledDither": True}
        latched_v5 = {**latched, "reducedMotion": False, "ledPink": 16777215, "ledVolFull": False}
        raw = {s["frame"] for *_, s in self.steps() if s.get("raw")}
        worst, worst_v5, counts = 0, 0, Counter()
        for index, frame in enumerate(self.frames):
            with self.subTest(frame=index):
                if "playing" in frame:
                    self.assertIs(type(frame["playing"]), bool)
                    self.assertIn(frame["layout"], HOME_LAYOUTS)          # Home frames only
                feedback = frame.get("feedback") or {}
                if "skip" in feedback:
                    self.assertEqual(feedback["kind"], "ok")              # stripped with any other kind
                    self.assertIn(feedback["skip"], (-1, 1))
                if index in raw:                                          # [r2] unparsed on purpose
                    counts["raw"] += 1
                    self.assertEqual(frame["layout"], "upnext")
                    self.assertNotEqual(device._frame(frame, mas.CAPS_V5), frame)   # the host strips the bit
                    continue
                if mas.has_v5(frame):                                     # the v7 host (PRESENTATION_V5)
                    counts["v5"] += 1
                    self.assertEqual(device._frame(frame, mas.CAPS_V5), frame)
                    size = device.frame_line_bytes({**frame, **latched_v5})
                    worst_v5 = max(worst_v5, size)
                    self.assertLessEqual(size, P.FRAME_BUDGET_BYTES_V5)
                    continue
                counts["v4"] += 1
                plain = v4_part(frame)
                self.assertEqual(device._frame(plain, CAPS_V4), plain)
                size = device.frame_line_bytes({**frame, **latched})
                worst = max(worst, size)
                self.assertLessEqual(size, P.FRAME_BUDGET_BYTES)
        self.assertGreater(counts["v5"], 100)
        self.assertGreater(counts["raw"], 0)
        print(f"\n[alive twin] {len(self.frames)} frames ({counts['v4']} v4, {counts['v5']} v5, {counts['raw']} raw); "
              f"worst frame line with every latched field: v4 {worst} B, v5 {worst_v5} B")

    # ---------------------------------------------------------- coverage
    def test_every_section_6_event_occurs(self):
        types = Counter(row[0] for *_, row in self.rows())
        for kind in EFFECTS:
            self.assertGreater(types[kind], 0, kind)
        boots = {row[4] for *_, row in self.rows() if row[0] == "boot"}
        self.assertEqual(boots, {0, 1})                               # home and non-home boot
        ticks = [row for *_, row in self.rows() if row[0] == "tick"]
        self.assertEqual({r[4] for r in ticks}, {-1, 1})
        self.assertLessEqual({0, 7}, {r[5] for r in ticks})           # tick lengths at both ends
        bounds = [row for *_, row in self.rows() if row[0] == "bound"]
        self.assertEqual({r[4] for r in bounds}, {-1, 1})
        colours = {tuple(r[5:8]) for r in bounds}
        self.assertIn((1, 0, 0), colours)                             # RED at >= 90 %
        self.assertIn(tuple(round(x, 6) for x in al.ENGINE_PALETTE.warm), colours)
        self.assertEqual({row[4] for *_, row in self.rows() if row[0] == "sweep"}, {-1, 1})   # [D9]
        self.assertLessEqual({0, 27, 28, 35, 50}, {row[4] for *_, row in self.rows() if row[0] in ("fill", "drain")})
        self.assertEqual({row[3] for *_, row in self.rows() if row[0] == "press"}, {0, 1, 2, 3})
        flashes = {s["expect"]["flash"] for *_, s in self.steps()}
        self.assertEqual(flashes, {0, 1, 2})
        # Evictions at the [D12] cap: the queue is full and a killed effect disappears early.
        self.assertTrue(any(len(s["expect"]["fx"]) == al.QUEUE_CAP for *_, s in self.steps("queue-pressure")))
        # [r2] the new effects with their parameters.
        halves = [row for *_, row in self.rows() if row[0] == "half"]
        self.assertEqual({r[4] for r in halves}, {-1, 1})
        self.assertIn(tuple(round(x, 6) for x in al.ENGINE_PALETTE.warm), {tuple(r[5:8]) for r in halves})
        blooms = {tuple(r[4:7]) for *_, r in self.rows() if r[0] == "bloom"}
        self.assertIn(tuple(round(x, 6) for x in al.PINK), blooms)
        self.assertIn(tuple(round(x, 6) for x in al.GREEN), blooms)

    def test_claim_seeds_and_boots(self):
        steps = list(self.steps("claim-seed-boot-home"))
        first = next((i, s) for _, i, s in steps if any(op["op"] == "claim" for op in s.get("ops", ())))
        frame = self.frame(first[1])
        self.assertEqual(frame["feedback"]["seq"], 5)
        self.assertTrue(frame["ring"]["external"] and frame["playing"])
        seeded = [row[0] for row in first[1]["expect"]["fx"]]
        self.assertEqual(sorted(seeded), ["boot", "reveal"])            # no bloom / shimmer / fill / reveal event
        self.assertEqual(first[1]["expect"]["flash"], 0)
        kinds = {row[0] for *_, row in self.rows("claim-seed-boot-home")}
        self.assertIn("bloom", kinds)                                  # the next seq blooms
        self.assertNotIn("shimmer", kinds)

    def test_sleep_timing(self):
        by_now = {s["now"]: s["expect"]["asleep"] for *_, s in self.steps("sleep-wake-inputs")}
        self.assertEqual((by_now[4999], by_now[5000]), (False, True))          # 5000 ms after the claim
        shimmer = next(row[1] for *_, row in self.rows("ext-shimmer") if row[0] == "shimmer")
        ext = {s["now"]: s["expect"]["asleep"] for *_, s in self.steps("ext-shimmer")}
        self.assertEqual((ext[shimmer + 3199], ext[shimmer + 3200]), (False, True))   # EXT: 3200 ms
        # The deadline meets a pending volume: awake past 5000 ms, asleep at a later re-check.
        recheck = [s for *_, s in self.steps("sleep-recheck-pending-flash")]
        awake = [s["now"] for s in recheck if 5000 <= s["now"] <= 6600]
        self.assertTrue(awake and not any(s["expect"]["asleep"] for s in recheck if 5000 <= s["now"] <= 6600))
        self.assertTrue(any(s["expect"]["asleep"] for s in recheck if 6600 < s["now"] < 9400))
        # Wakes: from inputs, a flash, pending and EXT.
        wakes = [row[1] for *_, row in self.rows("sleep-wake-inputs") if row[0] == "wake"]
        self.assertGreaterEqual(len(set(wakes)), 5)

    def test_tick_direction_and_velocity_edges(self):
        steps = {s["now"]: s for *_, s in self.steps("tick-direction-velocity-edges")}
        against = 0
        for now, step in steps.items():
            deltas = [op["delta"] for op in step.get("ops", ()) if op["op"] == "detent"]
            ticks = [row for row in step["expect"]["fx"] if row[0] == "tick" and row[1] == now]
            if deltas and ticks and ticks[-1][4] != (1 if deltas[-1] > 0 else -1):
                against += 1                                           # dir = sign(cd(new, old))
        self.assertGreaterEqual(against, 3)
        lens = [row[5] for *_, row in self.rows("tick-direction-velocity-edges") if row[0] == "tick"]
        self.assertIn(0, lens)
        self.assertIn(7, lens)

    def test_local_cursor_rules(self):
        seen = Counter()
        for _, _, step in self.steps("local-cursor-rules"):
            frame = self.frame(step)
            if frame is None or "local" not in step:
                continue
            pos, top = step["local"]
            ring = frame["ring"]
            applied = al.apply_local(frame, pos, top)[1]
            style, activity, layout = ring["style"], frame["activity"], frame["layout"]
            if style == "level":
                reason = ("notice" if layout == "notice" else "offline" if activity == "offline"
                          else "max" if top != 100 else "ok")
            elif style == "selection":
                reason = (activity if activity in ("pending", "loading") else "max" if top != ring["count"] - 1
                          else "window" if not ring.get("first", 0) <= pos < ring.get("first", 0) + 20 else "ok")
            else:
                reason = "pending" if activity == "pending" else "max" if top != 2 else "ok"
            self.assertEqual(applied, reason in ("ok", "window"), (style, reason))
            seen[(style, reason)] += 1
        expected = {("level", r) for r in ("ok", "max", "notice", "offline")}
        expected |= {("selection", r) for r in ("ok", "max", "pending", "loading", "window")}
        expected |= {("transport", r) for r in ("ok", "max", "pending")}
        self.assertEqual(set(seen), expected)

    def test_offline_release_reset_and_native_handover(self):
        ops = Counter(op["op"] for *_, s in self.steps() for op in s.get("ops", ()))
        for name in ("reset", "claim", "release", "detent", "limit", "press", "clock", "progress", "rm", "tuning",
                     "knob", "knobReset"):
            self.assertGreater(ops[name], 0, name)
        self.assertEqual(ops["reveal"], 0)                            # [M29]: no 5 s return any more
        steps = [s for *_, s in self.steps("release-down-native")]
        downs = {row[1] for s in steps for row in s["expect"]["fx"] if row[0] == "down"}
        self.assertGreaterEqual(len(downs), 2)
        # [M29] the native path keeps the LEDs until the next claim: a gap of more than 60 s without a
        # render (no reveal, no marks), then a claim that boots.
        gap = next((a, b) for a, b in zip(steps, steps[1:]) if (b["now"] - a["now"]) % U32 >= 60000)
        self.assertTrue(any(op["op"] == "claim" for op in gap[1].get("ops", ())))
        self.assertIn("boot", [row[0] for row in gap[1]["expect"]["fx"] if row[1] == gap[1]["now"]])
        resets = [s for *_, s in self.steps("offline-reset-reveal") if any(o["op"] == "reset" for o in s.get("ops", ()))]
        self.assertTrue(all(any(r[0] == "reveal" and r[1] == op.get("t", s["now"]) for r in s["expect"]["fx"])
                            for s in resets for op in s["ops"] if op["op"] == "reset"))

    def test_album_start_confirmation(self):
        """6.4.3 as written (review F2): after an album start from Recent, the wash is cut by fill
        when the ok frame carried playing:false and the next frame says true (the engine rule), and
        runs its 1100 ms when the ok frame omitted playing, which is what the [R4] host sends."""
        kills, fills = {}, set()
        for *_, s in self.steps("album-start-confirmation"):
            for row in s["expect"]["fx"]:
                if row[0] == "wash":
                    kills[row[1]] = row[2]
                elif row[0] == "fill":
                    fills.add(row[1])
        self.assertEqual(len(kills), 2)
        first, second = sorted(kills)
        self.assertIn(kills[first], fills)                              # cut by the fill
        self.assertEqual(kills[first] - first, 300)
        self.assertIsNone(kills[second])                                # ran out
        self.assertFalse(any(t > second for t in fills))

    def test_rulings_r1_and_r3(self):
        """[R1] a stale request on the Home Sonos-off notice is not pending: it rests at the input
        deadline (a pending volume would keep the knob awake); [R3] a Home frame without playing
        hides the song hand and freezes it like playing:false. [user 2026-09-26] 12.8: no song hand is drawn
        at rest, so the ring shows none in any of those stretches (the R3 latch itself is test_alive_lights')."""
        stale = [s for *_, s in self.steps("sleep-recheck-pending-flash")
                 if "frame" in s and self.frame(s)["layout"] == "notice"
                 and self.frame(s)["ring"]["value"] != self.frame(s)["confirmedVolume"]]
        self.assertTrue(stale and not stale[0]["expect"]["asleep"])     # the press woke it
        self.assertTrue(stale[-1]["expect"]["asleep"])                  # rests: not pending
        after = [s for *_, s in self.steps("sleep-recheck-pending-flash")][-1]
        self.assertFalse(after["expect"]["asleep"])                     # Sonos up: the same request is pending
        # R3: the song-hand case goes true -> absent -> true while asleep; no fill/drain fires across it.
        # [user 2026-09-26] 12.8: the hand (it was a HOT splat on the dark segments 3..24 of volume 54) is
        # not drawn at rest, before, during or after the absent stretch.
        steps = [s for *_, s in self.steps("song-hand")]

        def framed(i):
            return self.frame(steps[i]) if "frame" in steps[i] else {}
        absent = [i for i in range(1, len(steps)) if framed(i).get("layout") == "volume"
                  and "playing" not in framed(i) and framed(i - 1).get("playing") is True]
        self.assertTrue(absent)
        start = absent[0]
        stop = next(i for i in range(start, len(steps)) if "playing" in framed(i))

        def hand(i):                                                 # max e over the dark segments 5..22
            e = steps[i]["expect"]["e"]
            return max(e[3 * k + q] for k in range(5, 23) for q in range(3)) / mas.E_SCALE
        self.assertTrue(all(steps[i]["expect"]["asleep"] for i in range(start - 1, stop + 1)))
        self.assertLess(max(hand(i) for i in range(start - 1, stop + 2)), 1e-3)   # no hand at rest
        fills = {row[1] for s in steps[start:stop + 20] for row in s["expect"]["fx"] if row[0] in ("fill", "drain")}
        self.assertFalse({t for t in fills if t >= steps[start]["now"]})

    def test_lease_flap_keeps_five_downs_live(self):
        """Section 7: releases inside one 120 ms kill fade leave several downs drawing at once, each
        from the snapshot of its own release (the C++ half compares their e with this engine's)."""
        steps = [s for *_, s in self.steps("lease-flap-downs")]
        releases = [op for s in steps for op in s.get("ops", ()) if op["op"] == "release"]
        live = [{row[1] for row in s["expect"]["fx"] if row[0] == "down"} for s in steps]
        self.assertEqual(len(releases), 5)
        self.assertEqual(max(map(len, live)), 5)
        pairs = [s for s in steps if [o["op"] for o in s.get("ops", ())] == ["claim", "release"]]
        self.assertTrue(pairs and all("frame" not in s for s in pairs))   # claim + release between renders

    def test_clock_song_styles_wraps_and_output(self):
        clock = [s for *_, s in self.steps("time-of-day-clock-wrap")]
        span = sum((b["now"] - a["now"]) % U32 for a, b in zip(clock, clock[1:]))
        self.assertGreater(span, 48 * 3600 * 1000)                    # midnight crossed twice
        self.assertTrue(any(op["op"] == "progress" and op["dur"] == 0 for *_, s in self.steps()
                            for op in s.get("ops", ())))
        styles = {self.frames[s["frame"]]["ledStyle"] for *_, s in self.steps() if "frame" in s}
        self.assertEqual(styles, {"white", "color"})
        self.assertTrue(any(f["layout"] == "windows" and f["activity"] == "pending" for f in self.frames))   # [D13]
        wrap = [s["now"] for *_, s in self.steps("millis-wrap")]
        self.assertTrue(any(t > U32 - 3000 for t in wrap) and any(t < 10000 for t in wrap))
        drives = {s.get("drive", 150) for *_, s in self.steps()}
        self.assertLessEqual({1, 60, 150, 255}, drives)
        self.assertTrue(any(s.get("dither") for *_, s in self.steps()))
        # The [D17] power limit engages on recorded output steps.
        limited = 0
        for *_, s in self.steps():
            if "bytes" in s["expect"]:
                e = [x / mas.E_SCALE for x in s["expect"]["e"]]
                load = (sum(map(mas.eotf, e[:180])) + 2 * sum(map(mas.eotf, e[180:]))) * s.get("drive", 150)
                limited += load > mas.POWER_BUDGET
        self.assertGreater(limited, 5)

    # ------------------------------------------------------------ the tool
    def test_reference_output(self):
        full = [[1.0, 1.0, 1.0]] * 60
        ring, buttons = mas.reference_output(full, [[1.0, 1.0, 1.0]] * 4, 150)
        q = math.floor(150 * 16920 / (204 * 150) + 0.5)                # S = 204 * 150 > B: scaled to B
        self.assertEqual((ring[0], buttons[3]), (q * 0x010101, q * 0x010101))
        warm = [list(al.WARM)] * 60                                     # the section 2 float WARM [R5]
        ring, buttons = mas.reference_output(warm, [list(al.WARM)] * 4, 150)
        self.assertEqual(set(ring) | set(buttons), {(150 << 16) | (78 << 8) | 21})   # 68 LEDs = B: unscaled
        ring, _ = mas.reference_output([list(al.WARM)] + [[0.0] * 3] * 59, [[0.0] * 3] * 4, 255)
        self.assertEqual(ring[0], 0xFF8424)                             # the user's pick, exactly
        ring, _ = mas.reference_output([list(al.AMBER)] + [[0.0] * 3] * 59, [[0.0] * 3] * 4, 255)
        self.assertEqual(ring[0], 0xFF3A0A)
        self.assertEqual(mas.POWER_BUDGET, 16920.0)
        self.assertEqual(mas.POWER_BUDGET, al.POWER_BUDGET)
        self.assertAlmostEqual(mas.eotf(0.5), 0.21404114, places=7)
        self.assertEqual((mas.eotf(-1), mas.eotf(2)), (0.0, 1.0))

    def test_reference_output_floor(self):
        """[user 2026-09-26] 9 step 4, rule F-T: the tool's independent reference floors a dark lit LED
        to one count on its dominant channel(s) (the 12.7 amendment; not round(v / max v)), leaves unlit
        and visible LEDs alone, and agrees with the engine module's reference_output (alive_lights) on
        random dim frames."""
        def at(v, lit, drive=255):
            e = [al.srgb_oetf(x / drive) if x > 0 else 0.0 for x in v]
            ring, buttons = mas.reference_output([e] + [[0.0] * 3] * 59, [[0.0] * 3, e, [0.0] * 3, [0.0] * 3], drive,
                                                 [lit] + [False] * 59, [False, lit, False, False])
            self.assertEqual(ring[0], buttons[1])
            return ring[0]
        self.assertEqual(at((0.498, 0.238, 0.208), True), 0x010000)
        self.assertEqual(at((0.0, 0.314, 0.124), True), 0x000100)
        self.assertEqual(at((0.3, 0.154, 0.066), True), 0x010000)         # a dim AMBER: its red only
        self.assertEqual(at((0.2, 0.2, 0.05), True), 0x010100)            # a tie lights both
        self.assertEqual(at((0.498, 0.238, 0.208), False), 0)          # unlit tail
        self.assertEqual(at((0.0, 0.0, 0.0), True), 0)
        self.assertEqual(at((0.8, 0.45, 0.0), True), 0x010000)          # visible: plain
        self.assertEqual(mas.reference_output([[0.01] * 3] * 60, [[0.0] * 3] * 4)[0][0], 0)   # no flags: plain
        self.assertEqual(mas.lit_hex([True] + [False] * 58 + [True], [False, False, False, True]),
                         f"{(1 << 0) | (1 << 59) | (1 << 63):016x}")
        state = 12345
        for _ in range(200):
            e, lit = [], []
            for _ in range(64):
                state = (state * 1103515245 + 12345) % 2 ** 31
                e.append([(state >> k & 1023) / 1023 * 0.06 for k in (0, 10, 20)])
                lit.append(bool(state >> 30 & 1))
            a = mas.reference_output(e[:60], e[60:], 150, lit[:60], lit[60:])
            b = al.reference_output(e[:60], e[60:], 150, lit[:60], lit[60:])
            self.assertEqual(a, b)

    def test_bytes_carry_the_floor(self):
        """[user 2026-09-26] The recorded bytes (dither off, the default) floor the dark lit LEDs: only
        LEDs whose bit is set in "lit" differ from plain rounding, by one count at most per channel (on
        the dominant channel of the recorded e, 12.7), and the floor fires on many steps (resting and
        offline marks, fades toward a lit level)."""
        floored = 0
        for name, i, step in self.steps():
            expect = step["expect"]
            if "bytes" not in expect:
                continue
            mask = int(expect["lit"], 16)
            e = [[x / mas.E_SCALE for x in expect["e"][3 * k:3 * k + 3]] for k in range(64)]
            ring, buttons = mas.reference_output(e[:60], e[60:], step.get("drive", 150))
            for k, (got, plain) in enumerate(zip(expect["bytes"], ring + buttons)):
                channels = (got >> 16, got >> 8 & 255, got & 255)
                if mask >> k & 1 and plain == 0 and got and max(channels) == 1:
                    floored += plain != got
                    top = max(e[k])
                    for c in range(3):                             # the dominant channel lit, a clearly lower one not
                        if e[k][c] < top - 2e-3:
                            self.assertEqual(channels[c], 0, (name, i, k))
                    continue
                for shift in (16, 8, 0):                           # plain rounding (e rounded to 1e-5)
                    self.assertLessEqual(abs((got >> shift & 255) - (plain >> shift & 255)), 1, (name, i, k))
        self.assertGreater(floored, 500)

    # --------------------------------------------------------- [r2] 11.4
    def test_every_moment_and_the_prng(self):
        rows = [row for *_, row in self.rows("moments-rows")]
        kinds = {row[0] for row in rows}
        self.assertLessEqual({"sweep", "scatter", "bloom", "half", "wash"}, kinds)
        sweeps = {(row[3], row[4]) for row in rows if row[0] == "sweep"}
        self.assertIn((0, 1), sweeps)                                  # queued: from 12 o'clock
        seeds = []
        for *_, row in self.rows("moments-rows"):
            if row[0] == "scatter" and row[4] not in seeds:
                seeds.append(row[4])
        state, want = al.RNG_SEED, []
        for _ in seeds:
            state = al.xorshift32(state)
            want.append(round(al.scatter_seed(state), 9))
        self.assertEqual(seeds, want)                                  # shuffle on and off: the sequence
        self.assertEqual(len(seeds), 2)
        # No flash with a moment [M7]; the flash rows keep it.
        steps = {s["now"]: s for *_, s in self.steps("moments-rows")}
        for now, step in steps.items():
            frame = self.frame(step) or {}
            feedback = frame.get("feedback") or {}
            if "moment" in feedback and any(r[1] == now for r in step["expect"]["fx"]):
                self.assertEqual(step["expect"]["flash"], 0, now)
        # M16: no fill or drain in the moments case (every start omits or changes playing with its moment).
        self.assertFalse({"fill", "drain"} & kinds)

    def test_reduced_motion_sequence(self):
        steps = [s for *_, s in self.steps("reduced-motion")]
        on = True
        dropped_window = []
        for s in steps:
            for op in s.get("ops", ()):
                if op["op"] == "rm":
                    on = op["on"]
            if on:
                dropped_window.append(s)
        # (step 0 also shows the power-up reveal of the engine's reset(0), queued before the latch)
        new = {row[0] for s in dropped_window[1:] for row in s["expect"]["fx"] if row[1] == s["now"]}
        self.assertFalse(new & {"wake", "tick", "sweep", "scatter", "reveal"})
        self.assertLessEqual({"boot", "bloom", "fail", "bound", "half", "press", "down"}, new)
        later = {row[0] for s in steps if s not in dropped_window for row in s["expect"]["fx"]}
        self.assertLessEqual({"scatter", "tick", "reveal"}, later)     # restored when off

    def test_mode_seek_and_tabs(self):
        steps = [s for *_, s in self.steps("mode-seek-explorer-upnext")]
        reveals = []
        for a, b in zip(steps, steps[1:]):
            if "frame" in b and any(r[0] == "reveal" and r[1] == b["now"] for r in b["expect"]["fx"]):
                reveals.append((self.frames[a.get("frame", b["frame"])]["layout"] if "frame" in a else None,
                                self.frames[b["frame"]]["layout"]))
        self.assertIn(("tracks", "seek"), reveals)
        self.assertIn(("seek", "tracks"), reveals)
        self.assertNotIn(("explorer", "explorer"), reveals)            # the tab switch
        pages = {self.frames[s["frame"]].get("page", 0) for s in steps if "frame" in s
                 and self.frames[s["frame"]]["layout"] == "explorer"}
        self.assertEqual(pages, {0, 1})
        bounds = [r for s in steps for r in s["expect"]["fx"] if r[0] == "bound"]
        self.assertEqual({r[4] for r in bounds}, {-1, 1})              # 0:00 and T_end

    def test_upnext_card_and_raw_frames(self):
        steps = [s for *_, s in self.steps("upnext-card")]
        raw = [s for s in steps if s.get("raw")]
        self.assertTrue(raw)
        for s in raw:
            frame = self.frames[s["frame"]]
            self.assertEqual(frame["ring"]["unavailable"], 1 << 5)
            self.assertNotEqual(frame["ring"]["colors"][5], 0)
        # The same frames through the host validator give identical e (the bit and the colour are ignored).
        for s in raw:
            parsed = device._frame(self.frames[s["frame"]], mas.CAPS_V5)
            a, b = al.alive_targets(self.frames[s["frame"]]), al.alive_targets(parsed)
            self.assertEqual((a.ring, a.cursor, a.buttons), (b.ring, b.cursor, b.buttons))
        fails = [r for s in steps for r in s["expect"]["fx"] if r[0] == "fail"]
        self.assertEqual({r[3] for r in fails}, {((5 - 2) * 3) % 60})  # the Head shake at slot(5)

    def test_loading_and_recentre(self):
        steps = [s for *_, s in self.steps("loading-vs-unloaded")]
        loading = [s for s in steps if "frame" in s and self.frames[s["frame"]]["activity"] == "loading"]
        self.assertTrue(loading and all(s["expect"]["cursor"] == 0 for s in loading))
        unloaded = [s for s in steps if "frame" in s and self.frames[s["frame"]]["ring"].get("count") == 96]
        self.assertTrue(any(s["expect"]["cursor"] != 0 for s in unloaded))
        spin = [s for *_, s in self.steps("recentre-96") if "local" in s]
        self.assertEqual({s["local"][0] for s in spin} >= {0, 95}, True)
        self.assertTrue(any(abs(s["local"][0] - self.frames[s["frame"]]["ring"]["index"]) > 10 for s in spin))

    def test_q1_end_stop_per_push(self):
        lims = [(s["now"], s["expect"]["lim"]) for *_, s in self.steps("end-stop-per-push") if "lim" in s["expect"]]
        self.assertEqual([l for _, l in lims], [[1], [1], [1], [1], [-1], [-1], [1], [-1]])
        for now, _ in lims:                                            # each lim plays its bound now
            step = next(s for *_, s in self.steps("end-stop-per-push") if s["now"] == now)
            self.assertTrue(any(r[0] == "bound" and r[1] == now for r in step["expect"]["fx"]))

    # --------------------------------------------------------- [r2.2] 11.4
    @staticmethod
    def _buttons_e(step):
        e = step["expect"]["e"]
        return [e[180 + 3 * j:183 + 3 * j] for j in range(4)]

    def _near(self, got, want, units=2):
        return all(abs(a - b) <= units for a, b in zip(got, want))

    def test_r22_liked_heart_pink_030_rests_like_off(self):
        """[M32] 11.4: the liked Button 3 settles at PINK 0.30 (r2.1: 1.0) next to off 0.30 and a dim 0.14,
        rests at WARM 0.26 exactly like off (12.8), and a tuned ledPink draws it at 0.30 too."""
        def scaled(colour, alpha):
            return [round(x * alpha * mas.E_SCALE) for x in colour]
        steps = [s for *_, s in self.steps("liked-heart-rest")]
        liked = [s for s in steps if self.frame(s) and self.frame(s)["buttons"][2].get("lit") == "on"]
        pink, tuned = scaled(al.PINK, 0.30), scaled(al.pink_from_led(0xFF0C30), 0.30)
        settled = [s for s in liked if not s["expect"]["asleep"] and self._near(self._buttons_e(s)[2], pink)]
        self.assertGreater(len(settled), 20)
        beside_dim = [s for s in settled if not self.frame(s)["buttons"][3]["enabled"]]
        self.assertTrue(beside_dim, "the liked heart is never shown next to a dim button")
        for s in beside_dim[-3:]:
            b = self._buttons_e(s)
            self.assertTrue(self._near(b[1], scaled(al.WARM, 0.30)), b[1])       # off
            self.assertTrue(self._near(b[3], scaled(al.WARM, 0.14)), b[3])       # dim: not the liked level
        self.assertTrue(any(self._near(self._buttons_e(s)[2], tuned) for s in liked if not s["expect"]["asleep"]))
        resting = [s for s in liked if s["expect"]["asleep"]]
        self.assertTrue(resting)
        for s in (resting[-1], [r for r in resting if r["now"] < settled[-1]["now"]][-1]):
            b = self._buttons_e(s)
            self.assertTrue(self._near(b[2], b[1], 1), (s["now"], b[2], b[1]))  # WARM 0.26 like off [M18, 12.8]
            self.assertGreater(b[2][0], 0)

    def test_r22_seek_pending_across_two_jumps(self):
        """[M33] 11.4: one Seek span of activity pending across jump 1, a retargeting turn and the follow-up
        jump; the Working comet (6.1 pending, compared with C++ too) never drops and holds sleep off."""
        steps = [s for *_, s in self.steps("seek-pending-two-jumps")]
        self.assertTrue(all("pending" in s["expect"] for s in steps))
        seek = [s for s in steps if self.frame(s) and self.frame(s)["layout"] == "seek"]
        pending = [i for i, s in enumerate(seek) if self.frame(s)["activity"] == "pending"]
        first, last = pending[0], pending[-1]
        self.assertEqual(pending, list(range(first, last + 1)), "an idle frame between the two jumps")
        span = seek[first:last + 1]
        self.assertEqual(sorted({self.frame(s)["ring"]["index"] for s in span}), [84, 89])   # target moved
        turns = [s["now"] for s in span if any(op["op"] == "detent" for op in s.get("ops", ()))]
        self.assertEqual(len(turns), 1)
        self.assertTrue(all(s["expect"]["pending"] and not s["expect"]["asleep"] for s in span))
        self.assertGreater(span[-1]["now"] - turns[0], al.SLEEP_MS)            # past the sleep deadline
        after = seek[last + 1:]
        self.assertTrue(after and not any(s["expect"]["pending"] for s in after))
        self.assertTrue(after[-1]["expect"]["asleep"])
        self.assertFalse(any(s["expect"]["pending"] for s in steps if s["now"] < span[0]["now"]))

    def test_tick_ties_round_up_and_the_guard_is_live(self):
        def timeline():
            s = mas.Seq("probe", "")
            s.op("claim").step(0, mas.home(40), (40, 100))
            s.op("detent", at=10, delta=1).step(13, mas.home(41), (41, 100))     # t 10: vel 0
            s.op("detent", at=87, delta=1).step(90, mas.home(42), (42, 100))     # 90 ms later: vel 5
            return s
        tick = [row for row in timeline().steps[-1]["expect"]["fx"] if row[0] == "tick"][-1]
        self.assertEqual(tick[5], 1)                                   # round(0.5) = 1, as exact arithmetic
        self.assertEqual(al.TICK_TIE_BIAS, 1e-4)
        margin = mas.TICK_TIE_MARGIN
        try:
            mas.TICK_TIE_MARGIN = 0.2                                  # widened: the tie is refused
            with self.assertRaises(AssertionError):
                timeline()
        finally:
            mas.TICK_TIE_MARGIN = margin
        ties = [row for *_, row in self.rows("tick-direction-velocity-edges") if row[0] == "tick"]
        self.assertTrue({1, 6} <= {row[5] for row in ties})           # the replayed exact ties

if __name__ == "__main__":
    unittest.main()

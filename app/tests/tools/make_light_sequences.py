"""Write harness/light_pixels.json: LED sequence fixtures for the firmware parity test.

Every case is a timeline of wire-valid v4 frames (control id, ``now_ms``,
pressed-button mask, optional renderer reset) replayed through ONE
``control_center.preview_lights.PreviewLights`` per case. Each step records what
the Python reference model produced:

* ``ring`` - the 60 logical drive colours after damping (pre-cap);
* ``buttons`` - the 4 slot drive colours after the fade and press highlight;
* ``cursor``, ``flash`` (0 none / 1 ok / 2 err), ``last_seq``;
* ``pending_ms`` / ``loading_ms`` (time since the pulse onsets) and ``cells``,
  the pure target (``ring_target``) as sparse ``[segment, rgb, level]`` rows;
* ``button_pixels`` - the stateless ``button_pixels(frame, pressed)``.

harness/light_tests.cpp parses each frame with the firmware's own
``cc_parse_frame`` and feeds the same timeline through ``CCLightRenderer``,
comparing every field above bit-exactly (and the physical ring for the four
mounting orientations). Frames are stored once in ``frames`` and referenced by
index (``"f"``) from the steps.

Layout: ``{"version", "frames": [...], "cases": {name: {"note", "steps": [...]}}}``.

Usage (the parity harness calls ``build()``/``dumps()`` itself):
    .venv\\Scripts\\python.exe tests\\tools\\make_light_sequences.py [--check]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _path in (str(ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import device, presentation as P  # noqa: E402
from control_center.preview_lights import (  # noqa: E402
    PreviewLights, button_pixels, ring_target,
)

OUTPUT = ROOT.parent / "harness" / "light_pixels.json"
VERSION = 2
U32 = 2 ** 32
CAPS_V4 = {"presentation": 4, "glyphs": "latin-ext-a"}
FLASH_CODE = {None: 0, "ok": 1, "err": 2}


# ----------------------------------------------------------------- frames
def _buttons(*spec):
    return [{"label": label, "enabled": enabled, "icon": icon} for label, enabled, icon in spec]


HOME_BUTTONS = _buttons(("Pause", True, "pause"), ("Browse", True, "list"), ("Win", True, "win"),
                        ("Tracks", True, "tracks"))
RECENT_BUTTONS = _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"),
                          ("Play", True, "play"))
WINDOWS_BUTTONS = _buttons(("Cancel", True, "cancel"), ("Home", True, "home"), ("Win", True, "win"),
                           ("Switch", True, "switch"))
TRACKS_BUTTONS = _buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"),
                          ("Next", True, "next"))


def _base(control_id, mode, layout, activity, led, buttons, ring, feedback=None, **extra):
    frame = {"id": control_id, "mode": mode, "target": "Hall", "value": "", "detail": "", "status": "",
             "activity": activity, "layout": layout, "ledStyle": led, "buttons": buttons, "ring": ring}
    frame.update(extra)
    if feedback:
        frame["feedback"] = {"kind": feedback[0], "seq": feedback[1]}
    return frame


def volume_frame(v, c=None, led="color", external=False, activity="idle", feedback=None, control_id=1,
                 buttons=HOME_BUTTONS):
    return _base(control_id, "VOLUME", "volume", activity, led, buttons,
                 {"style": "level", "value": v, "index": 0, "count": 101, "external": external},
                 feedback, value=f"{v}%", restLayout="nowPlaying",
                 confirmedVolume=v if c is None else c)


def accent(j):
    """Distinct non-white accents; every 7th entry has no accent (0 -> white)."""
    if j % 7 == 3:
        return 0
    return (0x30 + (j * 37) % 200) << 16 | (0x20 + (j * 53) % 210) << 8 | (0x40 + (j * 29) % 190)


def recent_closed(j):
    return j % 5 == 2


def windows_closed(j):
    return j % 4 == 1


def list_frame(count, index, led="color", windows=False, activity="idle", more=-1, first="auto",
               unavailable=None, colors="auto", feedback=None, control_id=1, page=0):
    """Recent (default) or Windows list; colours/mask relative to the transmitted first."""
    closed = unavailable or (windows_closed if windows else recent_closed)
    start = P.window_first(index, count) if first in ("auto", None) else first
    width = min(P.RING_WINDOW, count - start)
    ring = {"style": "selection", "value": 0, "index": index, "count": count}
    if first is not None:
        ring["first"] = start
    if first is None and start != 0:
        # An absent first: the colours/mask a legacy sender would send relative to
        # an implicit 0 (both sides ignore them once the derived first is not 0).
        start, width = 0, min(P.RING_WINDOW, count)
    mask = sum(1 << k for k in range(width) if closed(start + k) and start + k != more)
    if mask:
        ring["unavailable"] = mask
    if more >= 0:
        ring["moreIndex"] = more
    if colors == "auto" and led == "color":
        ring["colors"] = [accent(start + k) for k in range(width)]
    elif isinstance(colors, list):
        ring["colors"] = colors
    return _base(control_id, "WINDOWS" if windows else "RECENTLY ADDED", "windows" if windows else "recent",
                 activity, led, WINDOWS_BUTTONS if windows else RECENT_BUTTONS, ring, feedback,
                 title=f"Entry {index + 1}", page=page)


def transport_frame(index, no_prev=False, activity="idle", mask=None, feedback=None, control_id=1, count=3):
    ring = {"style": "transport", "value": 0, "index": index, "count": count}
    bits = (1 if no_prev else 0) if mask is None else mask
    if bits:
        ring["unavailable"] = bits
    buttons = [dict(b) for b in TRACKS_BUTTONS]
    buttons[3] = {"label": ("Prev", "Skip", "Next")[index] if index < 3 else "Skip",
                  "enabled": index != 1 and not (index == 0 and no_prev),
                  "icon": ("prev", "next", "next")[index] if index < 3 else "next"}
    return _base(control_id, "TRACKS", "tracks", activity, "color", buttons, ring, feedback)


def off_frame(feedback=None, control_id=1, buttons=RECENT_BUTTONS, activity="idle"):
    return _base(control_id, "NOTICE", "notice", activity, "color", buttons,
                 {"style": "off", "value": 0, "index": 0, "count": 0}, feedback)


# ------------------------------------------------------------- sequences
class Sequence:
    """A timeline of steps; ``t`` advances by ``dt`` before each step."""

    def __init__(self, name, note, start=1000):
        self.name, self.note, self.t, self.steps = name, note, start % U32, []

    def at(self, t):
        self.t = t % U32
        return self

    def step(self, frame, dt=0, control_id=None, pressed=0, reset=False):
        self.t = (self.t + dt) % U32
        cid = frame.get("id", 1) if control_id is None else control_id
        self.steps.append({"control_id": cid, "now_ms": self.t, "pressed": pressed, "reset": reset,
                           "frame": frame})
        return self

    def hold(self, frame, duration, every, **kw):
        """Repeat ``frame`` every ``every`` ms for ``duration`` ms (the first step after ``every``)."""
        for _ in range(duration // every):
            self.step(frame, every, **kw)
        return self

    def probe(self, frame, offsets, **kw):
        """Steps at absolute offsets (ms) from the current time, e.g. LUT probe points."""
        base = self.t
        for offset in offsets:
            self.at(base + offset).step(frame, 0, **kw)
        return self


FINE = (1, 2, 5, 10, 16, 17, 33, 50, 65, 97, 130, 163, 195, 229, 259, 260, 261, 300)
FADE = (1, 13, 14, 55, 110, 137, 165, 219, 220, 221, 260)


def volume_sequences():
    out = []
    s = Sequence("volume-white-sweep", "white arc 0..100..0 at 40 ms, confirmed = requested")
    for v in list(range(0, 101)) + list(range(99, -1, -1)):
        s.step(volume_frame(v, led="white"), 40)
    s.hold(volume_frame(0, led="white"), 400, 50)
    out.append(s)

    s = Sequence("volume-color-fast-turns", "colour arc: fast turns leave decay tails; amber/red thresholds")
    for v in range(0, 101):
        s.step(volume_frame(v), 15)
    s.hold(volume_frame(100), 300, 60)
    for v in range(100, 39, -1):
        s.step(volume_frame(v), 9)
    s.probe(volume_frame(40), FINE)
    for v in range(40, 96, 1):
        s.step(volume_frame(v), 23)
    for v in range(95, 70, -5):
        s.step(volume_frame(v), 31)
    s.probe(volume_frame(70), FINE)
    out.append(s)

    s = Sequence("volume-pending-up-down", "pending increase and decrease spans at L1, odd/even steps")
    for v in range(30, 71):
        s.step(volume_frame(v, 30), 30)
    for c in range(30, 71, 8):
        s.step(volume_frame(70, c), 45)
    s.step(volume_frame(70, 70), 45)
    for v in range(70, 9, -1):
        s.step(volume_frame(v, 70), 20)
    s.probe(volume_frame(10, 70), FINE)
    for c in range(70, 9, -12):
        s.step(volume_frame(10, c), 70)
    s.step(volume_frame(10, 10), 70)
    for v, c in ((81, 97), (88, 97), (89, 97), (97, 81), (100, 80), (0, 9), (1, 0), (0, 100), (100, 0)):
        s.step(volume_frame(v, c), 90)
        s.step(volume_frame(v, c, led="white"), 90)
    out.append(s)

    s = Sequence("volume-thresholds-styles", "k 40 amber / 45 red in colour, white purity, style toggles")
    for v in list(range(74, 101)) + list(range(100, 73, -1)):
        s.step(volume_frame(v, led="color"), 35)
        s.step(volume_frame(v, led="white"), 35)
    s.hold(volume_frame(79), 300, 100)
    s.step(volume_frame(79, led="white"), 20)
    s.probe(volume_frame(79, led="white"), FINE)
    out.append(s)

    s = Sequence("volume-external", "external endpoint at L4, cleared by a local turn")
    for v in (54, 55, 99, 100, 0, 1):
        s.step(volume_frame(v, external=True), 100)
        s.step(volume_frame(v, external=False), 100)
        s.probe(volume_frame(v, external=False), (13, 65, 130, 259, 260))
        s.step(volume_frame(v, external=True), 100)
    for v in range(60, 50, -1):
        s.step(volume_frame(v, 60, external=v % 2 == 0), 25)
    out.append(s)

    s = Sequence("volume-home-offline", "Home offline: only the confirmed endpoint, white L1, no marks")
    s.step(volume_frame(61, 41), 50)
    s.step(volume_frame(61, 41, activity="offline"), 50)
    s.probe(volume_frame(61, 41, activity="offline"), FINE)
    for c in (41, 42, 0, 1, 100, 99, 50):
        s.step(volume_frame(61, c, activity="offline", led="white"), 60)
        s.step(volume_frame(c, c, activity="offline"), 60)
    s.step(volume_frame(50, 50), 50)
    s.probe(volume_frame(50, 50), (1, 50, 100, 300))
    s.step(volume_frame(50, 50, activity="offline"), 50)
    s.probe(volume_frame(50, 50, activity="offline"), FINE)
    out.append(s)
    return out


LIST_COUNTS = (1, 2, 9, 11, 16, 20, 21, 45, 80)


def list_sequences():
    out = []
    for n in LIST_COUNTS:
        more = n - 1 if n >= 2 else -1
        s = Sequence(f"recent-n{n}", f"Recent {n} entries: window rule, More double landmark, closed gaps, "
                                     "white unavailable cursor, sweep up slow and down fast")
        for i in range(n):
            s.step(list_frame(n, i, more=more), 35)
        s.probe(list_frame(n, n - 1, more=more), (13, 130, 300))
        for i in range(n - 1, -1, -1):
            s.step(list_frame(n, i, more=more), 12)
        s.probe(list_frame(n, 0, more=more), FINE)
        s.step(list_frame(n, n // 2, more=more, led="white"), 40)
        s.step(list_frame(n, n // 2, more=more), 40)
        out.append(s)
    for n in (9, 20, 21, 45):
        s = Sequence(f"windows-n{n}", f"Windows {n}: closed windows keep an app-colour L2 cursor")
        for i in range(n):
            s.step(list_frame(n, i, windows=True), 30)
        for i in range(n - 1, -1, -3):
            s.step(list_frame(n, i, windows=True, led="white"), 14)
        s.probe(list_frame(n, 0, windows=True, led="white"), (5, 65, 130, 261))
        out.append(s)

    s = Sequence("list-first-absent-present", "absent first (derived window, relative data kept only at 0) "
                                               "vs present first")
    for n in (11, 21, 45, 80):
        for i in (0, 5, 9, 10, 11, n // 2, n - 10, n - 1):
            if 0 <= i < n:
                s.step(list_frame(n, i, first=None, more=n - 1), 40)
                s.step(list_frame(n, i, first="auto", more=n - 1), 40)
                s.step(list_frame(n, i, first=None, windows=True), 40)
    out.append(s)

    s = Sequence("list-more-and-unavailable", "More cursor pair, unavailable cursor Recent white vs Windows accent")
    for more in (0, 4, 8):
        for i in range(9):
            s.step(list_frame(9, i, more=more, unavailable=lambda j: j in (2, 3, 6)), 45)
            s.step(list_frame(9, i, more=more, unavailable=lambda j: j in (2, 3, 6), windows=True), 45)
    s.step(list_frame(9, 3, colors=[0] * 9, unavailable=lambda j: j == 3, windows=True), 45)
    s.step(list_frame(9, 3, colors=[], unavailable=lambda j: j == 3, windows=True), 45)
    s.step(list_frame(20, 19, colors=[0xFFFFFF] * 20, more=19), 45)
    out.append(s)

    s = Sequence("list-windows-detection", "unavailable cursor colour: mode WINDOWS or layout windows; "
                                           "an absent layout is derived from mode by the parser")
    closed = lambda j: j == 2  # noqa: E731  (entry 2 has a real accent; accent(3) is the 0 sentinel)

    def variant(mode, layout):
        frame = list_frame(9, 2, unavailable=closed, windows=True)
        frame["mode"] = mode
        if layout is None:
            del frame["layout"]
        else:
            frame["layout"] = layout
        return frame

    for mode, layout in (("WINDOWS", None), ("RECENTLY ADDED", None), ("WINDOWS", "recent"),
                         ("Windows", "windows"), ("Windows", "recent"), ("TRACKS", None), ("WINDOWS", "windows")):
        s.step(variant(mode, layout), 60)
        s.step(list_frame(9, 4), 60)
    out.append(s)
    return out


def pulse_sequences():
    out = []
    s = Sequence("recent-loading-page1", "Recent page-1 placeholder (count 1, loading): segment 0 L2/L1, "
                                         "onset reset")
    placeholder = list_frame(1, 0, activity="loading", colors=None)
    s.step(placeholder, 0)
    s.hold(placeholder, 1600, 20)
    s.step(list_frame(11, 0, more=10), 30)
    s.probe(list_frame(11, 0, more=10), FINE)
    s.step(placeholder, 100)
    s.hold(placeholder, 600, 13)
    s.step(list_frame(11, 10, more=10, activity="loading", page=1), 20)   # page 2 load: segment 0 only
    s.hold(list_frame(11, 10, more=10, activity="loading", page=1), 900, 20)
    s.step(list_frame(11, 10, more=10, page=1), 20)
    s.probe(list_frame(11, 10, more=10, page=1), FINE)
    out.append(s)

    s = Sequence("pending-onset-hold", "pending pulse: onset-anchored, starts HIGH, 260 ms phases, "
                                       "holds L1 after 3 s, onset resets")
    pending = list_frame(9, 3, activity="pending")
    s.step(list_frame(9, 3), 0)
    s.step(pending, 37)
    s.hold(pending, 3600, 10)
    s.step(list_frame(9, 3), 20)
    s.probe(list_frame(9, 3), (1, 65, 130, 200))
    s.step(pending, 111)
    s.hold(pending, 1200, 17)
    s.step(list_frame(9, 5, activity="pending"), 5)          # index moves while pending: no new onset
    s.hold(list_frame(9, 5, activity="pending"), 700, 23)
    s.step(list_frame(21, 20, activity="pending", windows=True), 10)
    s.hold(list_frame(21, 20, activity="pending", windows=True), 3300, 50)
    s.step(volume_frame(54, activity="pending"), 10)         # level + pending: no pulse, no onset
    s.hold(volume_frame(54, activity="pending"), 600, 40)
    s.step(pending, 10)
    s.hold(pending, 900, 30)
    out.append(s)
    return out


def transport_sequences():
    out = []
    s = Sequence("transport", "Tracks: Prev/Neutral/Next landmarks, no Prev, no Next, pending pairs, "
                              "invalid count dark")
    for no_prev in (False, True):
        for index in (1, 2, 1, 0, 1, 0, 2):
            s.step(transport_frame(index, no_prev), 70)
            s.probe(transport_frame(index, no_prev), (5, 130))
    s.step(transport_frame(2, mask=4), 70)
    s.step(transport_frame(1, mask=5), 70)
    s.step(transport_frame(0, mask=7), 70)
    for index, no_prev in ((0, False), (0, True), (2, False), (1, False), (1, True)):
        s.step(transport_frame(index, no_prev), 100)
        s.step(transport_frame(index, no_prev, activity="pending"), 10)
        s.hold(transport_frame(index, no_prev, activity="pending"), 3300, 40)
        s.step(transport_frame(index, no_prev), 10)
        s.probe(transport_frame(index, no_prev), (1, 97, 260))
    s.step(transport_frame(1, count=5), 60)                  # parser-valid, renderer draws nothing
    s.step(transport_frame(1), 60)
    s.step(off_frame(), 60)
    s.probe(off_frame(), FINE)
    out.append(s)
    return out


def flash_sequences():
    out = []
    s = Sequence("flash-seq-and-control-id", "ok 650 ms / err 900 ms on cursor+-1, triggered by a new seq "
                                              "regardless of control id; seeded by the first frame", start=0)
    s.step(list_frame(9, 1, feedback=("ok", 5), control_id=1), 0)            # seeds 5, no flash
    s.step(volume_frame(54, feedback=("ok", 5), control_id=2), 10)           # same seq, new id: none
    s.step(volume_frame(54, control_id=2), 10)                               # no feedback: unchanged
    s.step(volume_frame(54, feedback=("ok", 6), control_id=3), 10)           # flash ok
    s.probe(volume_frame(54, feedback=("ok", 6), control_id=3), (1, 100, 649, 650, 651, 700, 909, 910))
    s.step(list_frame(9, 4, feedback=("err", 7), control_id=4), 50)          # flash err (new id)
    s.probe(list_frame(9, 4, control_id=4), (1, 300, 649, 650, 899, 900, 901, 1159, 1160))
    s.step(list_frame(9, 4, feedback=("err", 7), control_id=4), 20)          # repeated seq: none
    s.step(transport_frame(0, True, feedback=("err", 8), control_id=5), 20)   # 51..53, no Prev landmarks
    s.probe(transport_frame(0, True, control_id=5), (100, 450))
    s.step(transport_frame(0, True, feedback=("ok", 9), control_id=5), 0)    # restart as ok mid-flash
    s.probe(transport_frame(0, True, control_id=5), (1, 649, 650, 910))
    s.step(off_frame(feedback=("ok", 10), control_id=6), 50)                 # off: cursor 0 -> 59, 0, 1
    s.probe(off_frame(control_id=6), (10, 649, 650, 700))
    s.step(volume_frame(100, feedback=("err", 11), control_id=7), 50)        # cursor 25 -> 24..26
    s.probe(volume_frame(100, control_id=7), (10, 899, 900, 1200))
    s.step(list_frame(9, 3, activity="pending", feedback=("ok", 12), control_id=8), 50)  # drawn over pending
    s.hold(list_frame(9, 3, activity="pending", control_id=8), 1000, 25)
    s.step(list_frame(11, 10, more=10, activity="loading", feedback=("err", 13), control_id=9), 50)
    s.hold(list_frame(11, 10, more=10, activity="loading", control_id=9), 1000, 25)
    s.step(volume_frame(20, led="white", feedback=("ok", 0x7FFFFFFF), control_id=0x7FFFFFFF), 60)
    s.hold(volume_frame(20, led="white", control_id=0x7FFFFFFF), 700, 50)
    out.append(s)

    s = Sequence("flash-reset-seeding", "a renderer reset seeds lastSeq without flashing", start=5000)
    s.step(list_frame(9, 4, feedback=("err", 9)), 0)                         # construction seeding
    s.step(list_frame(9, 4, feedback=("err", 9)), 50)
    s.step(list_frame(9, 4, feedback=("err", 10)), 50)                       # flashes
    s.hold(list_frame(9, 4), 300, 50)
    s.step(list_frame(9, 4, feedback=("err", 11)), 50, reset=True)           # reset: seeds 11, snaps
    s.step(list_frame(9, 4, feedback=("err", 11)), 50)
    s.step(list_frame(9, 5, feedback=("ok", 12)), 50)
    s.probe(list_frame(9, 5), (1, 260, 649, 650, 900))
    s.step(list_frame(9, 5), 100, reset=True)                                # reset without feedback
    s.step(list_frame(9, 5, feedback=("ok", 1)), 50)                         # first feedback flashes
    s.probe(list_frame(9, 5, feedback=("ok", 1)), (1, 649, 650, 700))
    s.step(volume_frame(54, feedback=("ok", 2)), 20, reset=True)            # reset mid-scene: snap, no flash
    s.step(volume_frame(55, feedback=("ok", 2)), 20)
    out.append(s)
    return out


def damping_sequences():
    out = []
    s = Sequence("decay-tails", "fast turns: overlapping 260 ms decays, retargets mid-decay, LUT probes")
    for i in list(range(0, 20)) + list(range(19, -1, -1)):
        s.step(list_frame(20, i, more=19), 7)
    s.probe(list_frame(20, 0, more=19), FINE)
    for v in range(100, -1, -4):
        s.step(volume_frame(v), 5)
    s.probe(volume_frame(0), FINE)
    for v in (100, 60, 100, 20, 21, 22, 100, 0):
        s.step(volume_frame(v), 3)
    s.probe(volume_frame(0), (1, 2, 3, 8, 16, 32, 64, 128, 256, 257, 258, 259, 260, 520))
    # Equal-peak hue change snaps (instant rise): W L2 -> AMBER L2 body segments.
    s.step(volume_frame(84, led="white"), 300)
    s.step(volume_frame(84, led="color"), 5)
    s.step(volume_frame(84, led="white"), 5)
    s.probe(volume_frame(84, led="white"), (1, 130, 260))
    out.append(s)

    s = Sequence("millis-wrap", "pulses, decay, flash and fades across the 2^32 ms wrap; a finished fade "
                                "never replays", start=U32 - 700)
    pending = list_frame(9, 3, activity="pending")
    s.step(list_frame(9, 3), 0)
    s.step(pending, 10)
    s.hold(pending, 3400, 20)                                 # crosses 0 near +700
    s.step(list_frame(9, 3), 10)
    s.at(U32 - 300)
    s.step(list_frame(9, 4, feedback=("ok", 3)), 0)
    s.step(list_frame(9, 5, feedback=("ok", 4)), 50)          # flash + decay straddle the wrap
    s.probe(list_frame(9, 5), (1, 100, 249, 250, 251, 649, 650, 700))
    s.at(U32 - 120)
    s.step(list_frame(1, 0, activity="loading", colors=None), 0)
    s.hold(list_frame(1, 0, activity="loading", colors=None), 1100, 20)
    # Button fade across the wrap, then time "comes back" 2^32 ms later: no replay.
    enabled = list_frame(9, 5)
    disabled = list_frame(9, 5)
    disabled["buttons"] = [dict(b) for b in disabled["buttons"]]
    disabled["buttons"][3]["enabled"] = False
    s.at(U32 - 100)
    s.step(enabled, 0)
    s.step(disabled, 10)                                      # fade starts at U32-90
    s.probe(disabled, (1, 55, 89, 90, 91, 110, 219, 220, 221, 300))
    s.at(U32 - 100 + 10 + 50)                                 # == start + 50 + 2^32 ms
    s.step(disabled, 0)
    s.step(disabled, 100)
    s.step(volume_frame(80), 0)                               # ring decay replay guard as well
    s.step(volume_frame(20), 10)
    s.probe(volume_frame(20), (1, 130, 259, 260, 400))
    s.at(s.t - 330)                                           # == decay start + 70 + 2^32 ms
    s.step(volume_frame(20), 0)
    out.append(s)
    return out


def button_sequences():
    out = []
    s = Sequence("buttons-tones-fade-press", "section 5.9 tones, 220 ms fades both ways, retarget mid-fade, "
                                             "press highlight only on nav/go/stop")
    frame = list_frame(9, 4)

    def with_buttons(*spec):
        f = dict(frame)
        f["buttons"] = _buttons(*spec)
        return f

    nav = with_buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("More", True, "more"))
    go = with_buttons(("Back", True, "back"), ("Home", True, "home"), ("Win", True, "win"), ("Play", True, "play"))
    dim = with_buttons(("Back", False, "back"), ("Home", False, "home"), ("Win", False, "win"), ("Play", False, "play"))
    stop = with_buttons(("Cancel", True, "cancel"), ("Home", True, "home"), ("", True, ""), ("Switch", True, "switch"))
    none = with_buttons(("", True, ""), ("", False, ""), ("", True, ""), ("", True, ""))
    odd = with_buttons(("Play", True, "play"), ("Cancel", True, "cancel"), ("Prev", True, "prev"), ("Next", False, "next"))
    s.step(nav, 0)
    for a, b in ((nav, go), (go, dim), (dim, stop), (stop, none), (none, nav), (nav, odd), (odd, go)):
        s.step(b, 300)
        s.probe(b, FADE)
    s.step(dim, 300)
    s.step(go, 60)                                            # retarget mid-fade (from the shown colour)
    s.step(stop, 60)
    s.step(nav, 60)
    s.probe(nav, FADE)
    for mask in (0b0001, 0b0010, 0b0100, 0b1000, 0b1111, 0):
        for f in (nav, go, dim, stop, none, odd):
            s.step(f, 20, pressed=mask)
    s.step(go, 300, pressed=0b1000)
    s.step(dim, 10, pressed=0b1000)                          # press while fading to dim: no highlight
    s.probe(dim, (50, 250), pressed=0b1000)
    s.step(stop, 10, pressed=0b1001)                         # press while fading to stop/switch
    s.probe(stop, (50, 250), pressed=0b1001)
    out.append(s)
    return out


def golden_sequences():
    """Every knob-model golden frame (both LED styles) through the host adapter, slow and fast."""
    import knob_adapter as ka   # tests/tools; needs tests/fixtures/knob_golden.json
    golden = ka.load_golden()
    adapter = ka.Adapter(golden)
    frames = []
    for number, case in enumerate(golden["cases"], 1):
        for led in ("white", "color"):
            frame = adapter.case_frame(case, led, number)
            if frame is not None:
                frames.append(device._frame(frame, CAPS_V4))
    slow = Sequence("golden-scenarios", "all knob-model golden frames as wire frames, 97 ms apart")
    for frame in frames:
        slow.step(frame, 97)
    fast = Sequence("golden-fast", "the golden colour frames in reverse, 11 ms apart (decay overlap)")
    for frame in reversed([f for f in frames if f.get("ledStyle") == "color"]):
        fast.step(frame, 11)
    return [slow, fast]


def sequences():
    return (volume_sequences() + list_sequences() + pulse_sequences() + transport_sequences()
            + flash_sequences() + damping_sequences() + button_sequences() + golden_sequences())


# ---------------------------------------------------------------- replay
class _Recording(PreviewLights):
    """PreviewLights that also exposes the onset times the target was drawn with."""

    def _onsets(self, frame, now):
        self.onset_ms = super()._onsets(frame, now)
        return self.onset_ms


def replay(sequence):
    """Run one sequence through one PreviewLights; returns the recorded steps (frame by value)."""
    lights = _Recording()
    out = []
    for step in sequence.steps:
        if step["reset"]:
            lights.reset()
        frame = step["frame"]
        ring, buttons = lights.render(frame, step["control_id"], step["now_ms"], step["pressed"])
        pending_ms, loading_ms = lights.onset_ms
        cells, cursor = ring_target(frame, pending_ms, loading_ms, lights.flash)
        assert cursor == lights.cursor
        out.append({
            "control_id": step["control_id"], "now_ms": step["now_ms"], "pressed": step["pressed"],
            "reset": step["reset"], "frame": frame,
            "ring": ring, "buttons": buttons, "cursor": cursor, "flash": FLASH_CODE[lights.flash],
            "last_seq": lights.last_seq, "pending_ms": pending_ms, "loading_ms": loading_ms,
            "cells": [[i, c, l] for i, (c, l) in enumerate(cells) if c or l],
            "button_pixels": button_pixels(frame, step["pressed"]),
        })
    return out


def build():
    """{"version", "frames", "cases"}: frames deduplicated and referenced by index."""
    frames, index = [], {}
    cases = {}
    for sequence in sequences():
        assert sequence.name not in cases, sequence.name
        steps = []
        for step in replay(sequence):
            key = json.dumps(step["frame"], sort_keys=True, separators=(",", ":"))
            if key not in index:
                index[key] = len(frames)
                frames.append(step.pop("frame"))
            else:
                step.pop("frame")
            steps.append({"f": index[key], **step})
        cases[sequence.name] = {"note": sequence.note, "steps": steps}
    return {"version": VERSION, "generator": "app/tests/tools/make_light_sequences.py",
            "global_brightness_cap": 51, "frames": frames, "cases": cases}


def dumps(data):
    """Deterministic, line-oriented JSON: one frame / one step per line."""
    def one(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    lines = ["{" + ",".join(f"{one(k)}:{one(data[k])}" for k in ("version", "generator", "global_brightness_cap"))
             + ',"frames":[']
    lines.append(",\n".join(one(frame) for frame in data["frames"]) + "],")
    lines.append('"cases":{')
    blocks = []
    for name, case in data["cases"].items():
        body = ",\n".join(one(step) for step in case["steps"])
        blocks.append(f'{one(name)}:{{"note":{one(case["note"])},"steps":[\n{body}]}}')
    lines.append(",\n".join(blocks))
    lines.append("}}")
    return "\n".join(lines) + "\n"


def summary(data):
    steps = sum(len(case["steps"]) for case in data["cases"].values())
    return f"{len(data['cases'])} sequence(s), {steps} step(s), {len(data['frames'])} distinct frame(s)"


def main(argv):
    data = build()
    text = dumps(data)
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != text:
            print(f"{OUTPUT} is out of date; run tests/tools/make_light_sequences.py")
            return 1
        print(f"{OUTPUT} is up to date ({summary(data)})")
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT} ({summary(data)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

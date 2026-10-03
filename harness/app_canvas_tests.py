"""A2 app canvas harness (1.0.0-cc5.6; CONTROL_CENTER.md "App canvas"). Python + MSVC (+ Pillow for the sheet).

1. cpp11_gate.py (the app canvas units are shared units there too) unless --no-gate.
2. Builds app_canvas_tests.exe with MSVC /W4 /WX from the unchanged firmware units (cc_frame_parse.cpp,
   cc_app_canvas.cpp, cc_app_gfx.cpp, cc_app_fonts.cpp, cc_app_shape.cpp, cc_app_cards.cpp, cc_app_screens.cpp)
   and the C data (cc_app_onshape.c, cc_app_icons.c, compiled as C).
3. Parse cases: every `app` object below goes through the real cc_parse_frame() inside a valid A0 Onshape frame
   line; accept / reject and the stored CCAppState must equal the expectation AND the Desk Dial's reading of the
   same object (control_center.device.app_parse), so both parsers are held to one table.
4. Render cases: every app screen (idle plasma, zoom, orbit at four angles, tilt at four pitches and its settle, pan,
   the Undo flash, the refusal, the Home chord (three and all four buttons held) and the zoom held at its bound, the
   wheel on each ring, a card mid-animation, a slide, the cancel entry, parameter mode A / B and its hold-to-cancel
   bar, the echo) is driven through CCAppCanvas exactly as the LCD thread drives it (a pass per millisecond) and
   saved as PNG; each case also checks the view the canvas chose and that it drew.
5. The contact sheet (round-masked, 2x) goes to app/design-reference/
   onshape-ui-contact-sheet.png, with Karl's own ui_preview renders beside it when --karl <png> is given.
6. A frame-rate estimate for the knob from the pixel work each screen does (see estimate_fps()).

Usage: app_canvas_tests.py [--no-gate] [--out DIR] [--sheet PATH] [--karl PNG]
No device, no USB. Exit status non-zero on any failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
work = root.parent
firmware = work / 'firmware'
src = firmware / 'src'
companion = work / 'app'
arduinojson = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'ArduinoJson' / 'src'
sys.path.insert(0, str(companion))
from control_center import device  # noqa: E402  (the host reading of the same object)
from control_center import onshape_app  # noqa: E402

UNITS_CPP = ('cc_frame_parse.cpp', 'cc_app_canvas.cpp', 'cc_app_gfx.cpp', 'cc_app_fonts.cpp', 'cc_app_shape.cpp',
             'cc_app_cards.cpp', 'cc_app_screens.cpp')
UNITS_C = ('cc_app_onshape.c', 'cc_app_icons.c')
# Harness-only C: the app-profile fixtures (app_canvas_fixtures.c, not firmware data).
FIXTURES_C = root / 'app_canvas_fixtures.c'
SHEET = companion / 'design-reference' / 'onshape-ui-contact-sheet.png'
# App profiles (plan §6, S1 FW-B): the built-in Onshape's pixel goldens, captured from the renderer before the
# generic-renderer refactor (base 7e1a806). manifest.json maps each render case (and each mid-animation snap,
# "<case>@<ms>") to the sha256 of its raw 240 x 240 RGB565 buffer (little-endian); the PNG beside it is the same
# frame for the eye. Every Onshape render must match byte for byte; --update-goldens rewrites them (only ever
# from a commit whose Onshape output is known good).
GOLDENS = root / 'goldens' / 'app_canvas'


def msvc_env():
    msvc = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207')
    sdk = Path('C:/Program Files (x86)/Windows Kits/10')
    sdk_include = sorted((sdk / 'Include').iterdir(), key=lambda p: p.name)[-1]
    sdk_lib = sdk / 'Lib' / sdk_include.name
    env = {key.upper(): value for key, value in os.environ.items()}
    env['INCLUDE'] = ';'.join(str(path) for path in (
        msvc / 'include', sdk_include / 'ucrt', sdk_include / 'shared', sdk_include / 'um'))
    env['LIB'] = ';'.join(str(path) for path in (msvc / 'lib/x64', sdk_lib / 'ucrt/x64', sdk_lib / 'um/x64'))
    return msvc / 'bin/Hostx64/x64/cl.exe', env


def build(out: Path) -> Path:
    cl, env = msvc_env()
    obj = out / 'obj'
    obj.mkdir(parents=True, exist_ok=True)
    # The C data: C99 compound literals and designated initialisers, compiled as C (/TC), as the device does.
    for unit in (*(src / u for u in UNITS_C), FIXTURES_C):
        subprocess.run([str(cl), '/nologo', '/TC', '/std:c11', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS', '/c',
                        f'/I{src}', str(unit), f'/Fo{obj}\\'], cwd=out, env=env, check=True)
    exe = out / 'app_canvas_tests.exe'
    subprocess.run([str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
                    f'/I{src}', f'/external:I{arduinojson}', '/external:W0', str(root / 'app_canvas_tests.cpp'),
                    *(str(src / unit) for unit in UNITS_CPP), *(str(obj / (Path(u).stem + '.obj')) for u in (*UNITS_C, FIXTURES_C.name)),
                    f'/Fo{obj}\\', f'/Fe{exe}'], cwd=out, env=env, check=True)
    return exe


# ---------------------------------------------------------------------------------------------------- frames
BASE = {"mode": "ONSHAPE", "target": "Onshape", "value": "ZOOM", "detail": "Hold 1 tilt", "status": "",
        "layout": "nowPlaying", "heading": "ONSHAPE", "title": "ZOOM",
        "buttons": [{"label": "Tilt", "enabled": True, "icon": "expand"},
                    {"label": "Orbit", "enabled": True, "icon": "shuffle"},
                    {"label": "Undo", "enabled": True, "icon": "back"},
                    {"label": "Pan", "enabled": True, "icon": "expand"}],
        "ring": {"style": "off", "value": 0, "index": 0, "count": 0}}


def line(app=None, raw_app=None):
    frame = dict(BASE, id=7)
    text = json.dumps({"frame": frame}, separators=(',', ':'))
    if raw_app is not None:
        return text[:-2] + ',"app":' + raw_app + '}}'
    if app is not None:
        return json.dumps({"frame": dict(frame, app=app)}, separators=(',', ':'))
    return text


def app(slot="zoom", **extra):
    out = {"id": "onshape", "slot": slot}
    out.update(extra)
    return out


def fx(profile_id, slot="knob", crc=0x1A2B3C4D, **extra):
    """An app object for a harness fixture profile (app_canvas_fixtures.c; their wire crc is 0x1A2B3C4D)."""
    out = {"id": profile_id, "crc": crc, "slot": slot}
    out.update(extra)
    return out


# (name, app object or raw JSON text, accept). The expectation of an accepted case is device.app_parse()'s.
PARSE_CASES = [
    ("minimal", app(), True),
    ("orbit", app("orbit"), True),
    ("tilt", app("tilt"), True),                  # the 1.0.0-cc5.6 rebuild (Desk Dial 7.2.2.0): slot 3
    ("tilt-refused", app("tilt", refused=True), True),
    ("pan-refused-flash", app("pan", refused=True, flash=12), True),
    ("wheel", app(wheel={"ring": 2, "index": 0}), True),
    ("wheel-max", app(wheel={"ring": 7, "index": 15}), True),
    ("param-a", app(param={"ring": 0, "index": 2, "mode": "A", "value": 300, "step": 1}), True),
    ("param-b-negative", app(param={"ring": 1, "index": 6, "mode": "B", "value": -12500, "step": 2, "bump": 3}), True),
    ("echo", app(echo={"ring": 3, "index": 4, "seq": 9}), True),
    ("unknown-key-ignored", app(future=1), True),
    ("everything", app("orbit", flash=1, wheel={"ring": 1, "index": 3},
                       param={"ring": 0, "index": 4, "mode": "B", "value": 99999999, "step": 0, "bump": 1},
                       echo={"ring": 0, "index": 1, "seq": 1}), True),
    ("no-app", None, True),
    # App profiles (APP_PROFILES.md section 8): any profile id (1..11 of [a-z0-9_-]) with an optional crc, the slots
    # knob / f1..f4, index up to 32. An id that is not loaded is drawn as Loading, never rejected.
    ("profile-id", {"id": "figma", "slot": "zoom"}, True),
    ("profile-id-crc", fx("figma", "f4", crc=4294967295), True),
    ("slot-knob", app("knob"), True),
    ("slot-f1", app("f1"), True),
    ("wheel-index-32", app(wheel={"ring": 7, "index": 32}), True),
    ("bad-id", {"id": "Figma", "slot": "zoom"}, False),
    ("bad-id-empty", {"id": "", "slot": "zoom"}, False),
    ("bad-id-long", {"id": "abcdefghijkl", "slot": "zoom"}, False),
    ("bad-id-number", {"id": 1, "slot": "zoom"}, False),
    ("crc-negative", app(crc=-1), False),
    ("crc-high", app(crc=4294967296), False),
    ("crc-string", app(crc="1"), False),
    ("no-id", {"slot": "zoom"}, False),
    ("bad-slot", app("idle"), False),
    ("bad-slot-case", app("TILT"), False),
    ("no-slot", {"id": "onshape"}, False),
    ("not-object", '"onshape"', False),
    ("refused-not-bool", app(refused=1), False),
    ("flash-negative", app(flash=-1), False),
    ("flash-float", app(flash=1.5), False),
    ("wheel-ring-high", app(wheel={"ring": 8, "index": 0}), False),
    ("wheel-index-high", app(wheel={"ring": 0, "index": 33}), False),
    ("wheel-missing-index", app(wheel={"ring": 0}), False),
    ("wheel-not-object", app(wheel=True), False),
    ("param-index-zero", app(param={"ring": 0, "index": 0, "mode": "A", "value": 0, "step": 1}), False),
    ("param-bad-mode", app(param={"ring": 0, "index": 1, "mode": "C", "value": 0, "step": 1}), False),
    ("param-step-high", app(param={"ring": 0, "index": 1, "mode": "A", "value": 0, "step": 3}), False),
    ("param-value-float", app(param={"ring": 0, "index": 1, "mode": "A", "value": 0.5, "step": 1}), False),
    ("param-value-bool", app(param={"ring": 0, "index": 1, "mode": "A", "value": True, "step": 1}), False),
    ("param-value-high", app(param={"ring": 0, "index": 1, "mode": "A", "value": 100000000, "step": 1}), False),
    ("param-no-value", app(param={"ring": 0, "index": 1, "mode": "A", "step": 1}), False),
    ("echo-seq-zero", app(echo={"ring": 0, "index": 1, "seq": 0}), False),
    ("echo-index-zero", app(echo={"ring": 0, "index": 0, "seq": 1}), False),
    # DD-SEC-001: the keyboard-focus refusal flag (optional, default false, kept only with refused; read leniently
    # because device.app_parse and older firmware ignore the key, so acceptance never changes).
    ("refused-focus", app(refused=True, refusedFocus=True), True),
    ("refused-focus-false", app(refused=True, refusedFocus=False), True),
    ("focus-without-refused", app(refusedFocus=True), True),
    ("focus-not-bool", app(refused=True, refusedFocus=1), True),
]
# DD-SEC-001: the cases whose stored refusedFocus is true (every other accepted case stores false).
REFUSED_FOCUS_TRUE = frozenset({"refused-focus"})
# The app-profile cases: device.app_parse is held to them once Desk Dial reads profile ids (a NOTE until then).
PROFILE_PARSE = frozenset({"profile-id", "profile-id-crc", "slot-knob", "slot-f1", "wheel-index-32", "bad-id",
                           "bad-id-empty", "bad-id-long", "bad-id-number", "crc-negative", "crc-high", "crc-string",
                           "wheel-index-high"})


def host_reads_profiles() -> bool:
    return device.app_parse({"id": "figma", "slot": "knob"})[1]


def parse_entries():
    entries = []
    for name, value, _ in PARSE_CASES:
        entries.append({"name": name, "line": line(raw_app=value) if isinstance(value, str) else line(value)})
    return entries


# ---------------------------------------------------------------------------------------------------- renders
def step(t, a=None, angle=None, buttons=None, skip=False, snap=False, profile=None):
    s = {"t": t}
    if profile is not None:
        s["profile"] = profile   # the harness store serves this fixture from now on
    if skip:
        s["skip"] = True
    if snap:
        s["snap"] = True   # also dump the buffer after this step's pass (a mid-animation golden)
    if a is not None:
        s["line"] = line(a)
    if angle is not None:
        s["angle"] = angle
    if buttons is not None:
        s["buttons"] = buttons
    return s


QUARTER = 15708   # pi / 2 in 1e-4 rad


def render_cases():
    orbit = app("orbit")
    tilt = app("tilt")
    cases = [
        # (name, expected view, steps, label)
        ("zoom", "main", [step(0, app()), step(400, angle=int(QUARTER * 0.4))], "ZOOM (knob alone)"),
        ("orbit-45", "main", [step(0, orbit), step(50)], "ORBIT at rest (45 deg)"),
        ("orbit-68", "main", [step(0, orbit), step(300, angle=3927)], "ORBIT +22.5 deg"),
        ("orbit-101", "main", [step(0, orbit), step(400, angle=9817)], "ORBIT +56 deg"),
        ("orbit-135", "main", [step(0, orbit), step(500, angle=QUARTER)], "ORBIT +90 deg"),
        ("orbit-settle", "main", [step(0, orbit), step(300, angle=5000), step(320, app("zoom")), step(370, snap=True),
                                  step(420)],
         "ORBIT ended: settling (100 of 220 ms)"),
        ("tilt-30", "main", [step(0, tilt, buttons=0b0001), step(50)], "TILT at rest (30 deg, F1 held)"),
        ("tilt-52", "main", [step(0, tilt), step(300, angle=3927)], "TILT +22.5 deg (52.5)"),
        ("tilt-86", "main", [step(0, tilt), step(400, angle=9817)], "TILT +56 deg (86)"),
        ("tilt-neg", "main", [step(0, tilt), step(400, angle=-5890)], "TILT -34 deg (-4)"),
        ("tilt-settle", "main", [step(0, tilt), step(300, angle=7854), step(320, app("zoom")), step(360, snap=True),
                                 step(420)],
         "TILT ended: settling (100 of 220 ms)"),
        ("tilt-rested", "main", [step(0, tilt), step(300, angle=7854), step(320, app("zoom")), step(600)],
         "TILT ended: back at rest (zoom)"),
        ("pan", "main", [step(0, app("pan")), step(400, angle=4000)], "PAN"),
        ("undo-flash", "main", [step(0, app()), step(100, app(flash=1)), step(140, snap=True), step(180)],
         "Tap 3: UNDO flash"),
        ("refused", "main", [step(0, app(refused=True)), step(50)], "Refused: POINT AT MODEL"),
        ("refused-focus", "main", [step(0, app(refused=True, refusedFocus=True)), step(50)],
         "Refused (focus): CLICK MODEL FIRST"),
        ("refused-then-focus", "main", [step(0, app(refused=True)), step(30, app(refused=True, refusedFocus=True)),
                                        step(80)], "Refused, then the focus refusal"),
        ("held-orbit", "main", [step(0, orbit, buttons=0b0010), step(60)], "Button 2 held (keycap lit)"),
        # HN-DES-001: the Onshape Home chord (all four buttons held 1 s is the only way out) on its way there, and
        # the zoom held at its 0 / 60000 bound (the knob pushed into the end stop and springing back).
        ("home-chord-3", "main", [step(0, app(), buttons=0b0111), step(600)], "Home chord: 3 of 4 held"),
        ("home-chord-4", "main", [step(0, app(), buttons=0b1111), step(600)], "Home chord: all 4 held 0.6 s"),
        ("zoom-at-bound", "main", [step(0, app()), step(400, angle=2 * QUARTER), step(450, angle=2 * QUARTER + 300),
                                   step(550, angle=2 * QUARTER), step(800)], "ZOOM held at its bound (end stop)"),
        ("wheel-model", "wheel", [step(0, app(wheel={"ring": 0, "index": 2}), buttons=0b0100), step(1000)],
         "Wheel MODEL: EXTRUDE"),
        ("wheel-modify", "wheel", [step(0, app(wheel={"ring": 1, "index": 3}), buttons=0b0100), step(1100)],
         "Wheel MODIFY: TRANSFORM (search)"),
        ("wheel-sketch", "wheel", [step(0, app(wheel={"ring": 2, "index": 2}), buttons=0b0100), step(1100)],
         "Wheel SKETCH: RECTANGLE"),
        ("wheel-view", "wheel", [step(0, app(wheel={"ring": 3, "index": 4}), buttons=0b0100), step(1100)],
         "Wheel VIEW: ISOMETRIC"),
        ("wheel-cancel", "wheel", [step(0, app(wheel={"ring": 0, "index": 0}), buttons=0b0100), step(300)],
         "Wheel entry 0: cancel"),
        ("card-mid", "wheel", [step(0, app(wheel={"ring": 0, "index": 1}), buttons=0b0100), step(700)],
         "Card mid-animation (SKETCH, 700 ms)"),
        ("wheel-slide", "wheel", [step(0, app(wheel={"ring": 0, "index": 3}), buttons=0b0100),
                                  step(600, app(wheel={"ring": 0, "index": 4})), step(620, snap=True), step(650)],
         "Slide 3 -> 4 (50 ms)"),
        ("param-a", "param", [step(0, app(param={"ring": 0, "index": 4, "mode": "A", "value": 300, "step": 1})),
                              step(200)], "Param A (scroll): FILLET +0.30"),
        ("param-b", "param", [step(0, app(param={"ring": 0, "index": 2, "mode": "B", "value": 27500, "step": 2})),
                              step(200)], "Param B (type): EXTRUDE 27.50"),
        ("param-hold", "param", [step(0, app(param={"ring": 1, "index": 6, "mode": "B", "value": -4200, "step": 0})),
                                 step(100, buttons=0b0100), step(400, snap=True), step(800)],
         "Param: 3 held 700 ms (cancel)"),
        ("echo", "echo", [step(0, app()), step(100, app(echo={"ring": 0, "index": 2, "seq": 1})), step(300, snap=True),
                          step(700)],
         "Echo: EXTRUDE ran"),
        ("idle", "idle", [step(0, app()), step(5800, snap=True), step(6500)], "Idle plasma (1.5 s in)"),
        ("idle-later", "idle", [step(0, app()), step(8000)], "Idle plasma (3 s in, as Karl's #131)"),
        # FW-BUG-023: past 2^31 ms of uptime (24.86 days) the screens match their early-uptime twins (the twins
        # start at 1 s: the first 90 ms of uptime fall in the parameter nudge window, which adds frames).
        ("refused-ref", "main", [step(1000, app(refused=True)), step(1050)], "Refused at 1 s uptime"),
        ("refused-after-2^31ms", "main", [step(WRAP + 1000, app(refused=True)), step(WRAP + 1050)],
         "Refused at 24.86 days uptime"),
        ("undo-flash-ended-ref", "main", [step(0, app()), step(100, app(flash=1)), step(700),
                                          step(1000, app("orbit"), skip=True), step(1050)], "UNDO flash 0.9 s ago"),
        ("undo-flash-ended-2^31ms", "main", [step(0, app()), step(100, app(flash=1)), step(700),
                                             step(WRAP + 1000, app("orbit"), skip=True), step(WRAP + 1050)],
         "UNDO flash 24.86 days ago"),
        ("wheel-entry-ref", "wheel", [step(1000, app()), step(1100, app(wheel={"ring": 0, "index": 2}),
                                                           buttons=0b0100), step(2100)], "Wheel entered 100 ms in"),
        ("wheel-entry-2^31ms", "wheel", [step(1000, app()), step(WRAP + 1100, app(wheel={"ring": 0, "index": 2}),
                                                                buttons=0b0100, skip=True), step(WRAP + 2100)],
         "Wheel entered at 24.86 days uptime"),
        # FW-BUG-032: the angle word wraps modulo 2^32 (CCAngleWord); the cube follows a turn across the int32 wrap
        # (0x7FFFFF00 -> 0x7FFFFFF0 -> 0x80000010, then on by +22.5 deg) exactly as the same turn near zero, and a
        # still knob draws differently (the turn moved the cube).
        ("track_angle_across_int32_wrap", "main", [step(0, orbit, angle=s32(0x7FFFFF00)),
                                                    step(300, angle=s32(0x7FFFFFF0)), step(400, angle=s32(0x80000010)),
                                                    step(700, angle=s32(0x80000010 + 3927))],
         "ORBIT across the int32 angle wrap"),
        ("track_angle_near_zero-ref", "main", [step(0, orbit, angle=0), step(300, angle=0xF0), step(400, angle=0x110),
                                               step(700, angle=0x110 + 3927)], "ORBIT by the same turn near zero"),
        ("track_angle_still-ref", "main", [step(0, orbit, angle=s32(0x7FFFFF00)), step(700)], "ORBIT, knob still"),
    ]
    return cases


# App profiles (plan section 6, S1 FW-B): the generic renderer on harness fixtures (app_canvas_fixtures.c), served
# by this harness's store. (name, expected view, steps, label, fixture served: None = the built-in only, "none" =
# nothing loaded.)
def profile_cases():
    lab = "fx-label"
    sh = lambda m, st: f"fx-s{m}{st}"   # noqa: E731
    meshes, styles = ("CUBE", "PYRAMID", "OCTA"), ("FACE", "GRIPS", "THICK")
    mv = {"ring": 1, "index": 3, "mode": "B", "value": 6000, "step": 1}      # MOVE (axes, default Z)
    rot = {"ring": 1, "index": 2, "mode": "B", "value": 30000, "step": 1}    # ROTATE (axes + planes, default Y)
    cases = [
        ("fx-label-knob", "main", [step(0, fx(lab)), step(60)], "Label visual: knob ZOOM", "label"),
        ("fx-label-f1", "main", [step(0, fx(lab, "f1"), buttons=0b0001), step(60)], "Label: F1 + KNOB PAN (held)",
         "label"),
        ("fx-label-flash", "main", [step(0, fx(lab)), step(100, fx(lab, flash=1)), step(160)],
         "Label: tap flash F3 UNDO", "label"),
        ("fx-label-refused", "main", [step(0, fx(lab, refused=True)), step(60)], "Label: POINT AT THE APP", "label"),
        ("fx-label-refused-focus", "main", [step(0, fx(lab, refused=True, refusedFocus=True)), step(60)],
         "Label: CLICK THE APP FIRST", "label"),
        ("fx-label-legacy-slot", "main", [step(0, fx(lab, "orbit")), step(60)], "Label: legacy orbit -> F4 ROTATE",
         "label"),
        ("fx-label-noaction", "main", [step(0, fx("fx-lbl-idle")), step(60)], "Label, nothing live: icon + name",
         "label-idle"),
    ]
    for m in range(3):
        for st in range(3):
            cases.append((f"fx-{meshes[m].lower()}-{styles[st].lower()}", "main",
                          [step(0, fx(sh(m, st), "f4")), step(300, angle=2400), step(400)],
                          f"{meshes[m]} {styles[st]} (orbit)", f"shape-{m}{st}"))
    cases += [
        ("fx-pyramid-zoom", "main", [step(0, fx(sh(1, 2))), step(400, angle=6000)], "PYRAMID zoom", "shape-12"),
        ("fx-octa-pan", "main", [step(0, fx(sh(2, 0), "f1")), step(400, angle=4000)], "OCTA pan", "shape-20"),
        ("fx-pyramid-flash", "main", [step(0, fx(sh(1, 2))), step(100, fx(sh(1, 2), flash=1)), step(160)],
         "PYRAMID tap flash", "shape-12"),
        ("fx-stepped", "main", [step(0, fx(sh(1, 2), "f4")), step(300, angle=1300), step(400)],
         "Stepped pose (+7.4 deg)", "shape-12"),
        ("fx-unstepped", "main", [step(0, fx("fx-unstep", "f4")), step(300, angle=1300), step(400)],
         "Unstepped pose (+7.4 deg)", "unstepped"),
        ("fx-wheel-frame", "wheel", [step(0, fx(lab, wheel={"ring": 0, "index": 1}), buttons=0b0100), step(1000)],
         "Wheel: SEL / LABEL elements", "label"),
        ("fx-wheel-paste", "wheel", [step(0, fx(lab, wheel={"ring": 0, "index": 2}), buttons=0b0100), step(400)],
         "Wheel: CTRL SHIFT V, clipboard", "label"),
        ("fx-wheel-win", "wheel", [step(0, fx(lab, wheel={"ring": 0, "index": 3}), buttons=0b0100), step(400)],
         "Wheel: WIN keycap, play", "label"),
        ("fx-wheel-disabled", "wheel", [step(0, fx(lab, wheel={"ring": 0, "index": 4}), buttons=0b0100), step(400)],
         "Wheel: not on Windows (grey)", "label"),
        ("fx-wheel-enabled-twin", "wheel", [step(0, fx(lab, wheel={"ring": 0, "index": 3}), buttons=0b0100),
                                            step(400)], "(twin of the disabled case)", "label"),
        ("fx-wheel-macro", "wheel", [step(0, fx(lab, wheel={"ring": 0, "index": 5}), buttons=0b0100), step(400)],
         "Wheel: macro (no chord)", "label"),
        ("fx-wheel-search", "wheel", [step(0, fx(lab, wheel={"ring": 0, "index": 6}), buttons=0b0100), step(400)],
         "Wheel: search, no card", "label"),
        ("fx-wheel-32", "wheel", [step(0, fx("fx-rings8", wheel={"ring": 7, "index": 32}), buttons=0b0100),
                                  step(400)], "Wheel: entry 32 of 32, ring 8 of 8", "rings8"),
        ("fx-wheel-rings8-first", "wheel", [step(0, fx("fx-rings8", wheel={"ring": 0, "index": 2}),
                                                     buttons=0b0100), step(400)], "8 rings: tabs at ring 1", "rings8"),
        ("fx-wheel-rings8-mid", "wheel", [step(0, fx("fx-rings8", wheel={"ring": 4, "index": 0}), buttons=0b0100),
                                          step(400)], "8 rings: tabs at ring 5 (cancel)", "rings8"),
        ("fx-param-scale", "param", [step(0, fx(lab, param={"ring": 1, "index": 1, "mode": "B", "value": 1500,
                                                              "step": 1})), step(200)],
         "Param: SCALE uniform (X Y Z lit)", "label"),
        ("fx-param-rotate", "param", [step(0, fx(lab, param={"ring": 1, "index": 2, "mode": "B", "value": 45000,
                                                               "step": 2})), step(200)],
         "Param: ROTATE 45 deg about Y", "label"),
        ("fx-param-neg", "param", [step(0, fx(lab, param={"ring": 1, "index": 3, "mode": "B", "value": -3500,
                                                            "step": 0})), step(200)],
         "Param: below zero reads PULL", "label"),
        ("fx-param-clamped", "param", [step(0, fx(lab, param={"ring": 1, "index": 4, "mode": "B", "value": 9000,
                                                                "step": 1})), step(200)],
         "Param: 9.0 clamped to max 5.0", "label"),
        ("fx-param-at-max", "param", [step(0, fx(lab, param={"ring": 1, "index": 4, "mode": "B", "value": 5000,
                                                               "step": 1})), step(200)],
         "Param: 5.0 (its max)", "label"),
        ("fx-param-hold", "param", [step(0, fx(lab, param={"ring": 1, "index": 1, "mode": "B", "value": 1000,
                                                             "step": 1})), step(100, buttons=0b0100), step(500)],
         "Param: 3 held (cancel bar)", "label"),
        ("fx-echo", "echo", [step(0, fx(lab)), step(100, fx(lab, echo={"ring": 0, "index": 2, "seq": 1})),
                             step(500)], "Echo: PASTE OVER ran", "label"),
        ("fx-idle-sampled", "idle", [step(0, fx(lab)), step(6500)], "Idle plasma, colours from the icon", "label"),
        ("fx-loading", "loading", [step(0, fx("nothere")), step(60)], "Loading: id not in the store", "none"),
        ("fx-loading-crc", "loading", [step(0, app(crc=7)), step(60)], "Loading: onshape crc mismatch", None),
        ("fx-loading-then-loaded", "main", [step(0, fx(lab)), step(100, profile="label"), step(160)],
         "Loading, then the upload lands", "none"),
        # S3 review FW-2: the frame's live constraint (param.axis / param.plane, APP_PROFILES.md section 8) lights
        # the chips and moves the handle; a frame that changes only the axis redraws.
        ("fx-param-move", "param", [step(0, fx(lab, param=mv)), step(200)], "Param: MOVE, default axis (Z)", "label"),
        ("fx-param-move-x", "param", [step(0, fx(lab, param=dict(mv, axis=0))), step(200)], "Param: MOVE on X",
         "label"),
        ("fx-param-move-then-x", "param", [step(0, fx(lab, param=mv)), step(100, fx(lab, param=dict(mv, axis=0))),
                                           step(300)], "(MOVE, then the axis key X)", "label"),
        ("fx-param-move-uniform", "param", [step(0, fx(lab, param=dict(mv, axis=3))), step(200)],
         "Param: MOVE uniform (axis 3)", "label"),
        ("fx-param-rotate-x", "param", [step(0, fx(lab, param=dict(rot, axis=0))), step(200)],
         "Param: ROTATE about X", "label"),
        ("fx-param-rotate-x-plane", "param", [step(0, fx(lab, param=dict(rot, axis=0, plane=True))), step(200)],
         "Param: ROTATE, Shift+X: the YZ plane", "label"),
        # S3 review FW-1: a card the decoder accepts whose elements reach far past the card pane, mid-slide (two
        # cards in one frame): its draw stays bounded by the pane.
        ("fx-hostile-card", "wheel", [step(0, fx("fx-hostile", wheel={"ring": 0, "index": 1}), buttons=0b0100),
                                      step(300, fx("fx-hostile", wheel={"ring": 0, "index": 2})), step(340)],
         "Hostile card, mid-slide", "hostile"),
    ]
    return cases


# S3 review FW-1: the knob draw estimate (estimate_fps) of the hostile card frame must stay below this. The task
# watchdog is 10 s; a normal card frame is ~2 ms.
HOSTILE_DRAW_MS_MAX = 250.0


def check_profiles(out: Path, pcases, rendered, sheet_path: Path) -> int:
    """The fixture renders: view, pixels, guard bands, leases (done with the Onshape ones), plus what each
    feature must show, then their own contact sheet."""
    from PIL import Image, ImageChops
    failures = 0

    def img(name):
        return Image.open(out / f'{name}.png').convert('RGB')

    def differ(a, b, box=None):
        d = ImageChops.difference(img(a), img(b))
        return (d.crop(box) if box else d).getbbox() is not None

    def expect(ok, what):
        nonlocal failures
        failures += not ok
        print(f'{"PASS" if ok else "FAIL"} profiles: {what}')

    ui = {(255, 255, 255), (0, 0, 0), (0x6B, 0x6D, 0x6B), (0x39, 0x39, 0x39), (0xFF, 0xCB, 0x4A)}

    def colours(name, box):
        return {c for _n, c in img(name).crop(box).getcolors(1 << 16)}

    expect(differ('fx-label-knob', 'fx-label-f1'), 'the label visual names the live slot (knob vs F1 + KNOB)')
    expect(differ('fx-label-knob', 'fx-label-flash', (0, 70, 240, 125)), 'a tap flash renames the action (F3 UNDO)')
    expect(differ('fx-label-refused', 'fx-label-refused-focus', (0, 125, 240, 145)) and
           not differ('fx-label-refused', 'fx-label-refused-focus', (0, 0, 240, 125)),
           'the generic refusals differ on the refusal line only')
    expect(not differ('fx-label-legacy-slot', 'fx-label-knob', (0, 140, 240, 240)) and
           differ('fx-label-legacy-slot', 'fx-label-knob', (0, 70, 240, 125)),
           'a legacy slot token on a data profile picks the slot with that fx')
    expect(differ('fx-label-noaction', 'fx-label-knob', (60, 55, 180, 130)), 'nothing live: the icon and the name')
    shapes = [n for n, *_ in pcases if n.startswith(('fx-cube-', 'fx-pyramid-', 'fx-octa-'))
              and n.count('-') == 2 and n.split('-')[2] in ('face', 'grips', 'thick')]
    distinct = len({img(n).crop((0, 55, 240, 128)).tobytes() for n in shapes})
    expect(distinct == len(shapes), f'{len(shapes)} mesh x style renders all differ in the shape band')
    expect(differ('fx-stepped', 'fx-unstepped', (0, 55, 240, 128)), 'stepped poses snap, unstepped do not')
    expect(differ('fx-wheel-disabled', 'fx-wheel-enabled-twin', (0, 118, 240, 160)),
           'a command not on Windows draws its name and chord differently (grey)')
    name_box = (20, 118, 220, 140)
    expect((255, 255, 255) not in colours('fx-wheel-disabled', name_box)
           and (255, 255, 255) in colours('fx-wheel-enabled-twin', name_box), 'the disabled name is grey, not white')
    chord_box = (20, 144, 220, 160)
    expect(colours('fx-wheel-macro', chord_box) == {(0, 0, 0)}, 'a macro draws no chord')
    expect(colours('fx-wheel-win', chord_box) != {(0, 0, 0)}, 'the WIN chord draws keycaps')
    expect(differ('fx-wheel-rings8-first', 'fx-wheel-rings8-mid', (0, 182, 240, 200)),
           '8 rings: the tab strip follows the open ring')
    expect(not differ('fx-param-clamped', 'fx-param-at-max'), 'a value past max draws as max')
    expect(differ('fx-param-neg', 'fx-param-clamped', (0, 110, 240, 122)), 'below zero reads label_neg')
    sampled = colours('fx-idle-sampled', (0, 0, 240, 240)) - ui
    expect(len(sampled) >= 2, f'the idle plasma uses colours sampled from the icon ({len(sampled)} beyond the UI)')
    expect(not differ('fx-loading', 'fx-loading-crc'), 'Loading is neutral: an unknown id and a crc mismatch match')
    expect(differ('fx-loading-then-loaded', 'fx-loading'), 'Loading gives way when the profile lands')
    chips = (125, 62, 195, 80)   # the X / Y / Z chips (card x0 60: x0 + 68 + i * 16, y0 46 + 20)
    expect(differ('fx-param-move', 'fx-param-move-x', chips), 'param.axis 0 lights X instead of the default Z')
    expect(not differ('fx-param-move-x', 'fx-param-move-then-x'), 'a frame that changes only the axis redraws to it')
    expect(differ('fx-param-move-x', 'fx-param-move-uniform', chips), 'param.axis 3 (uniform) lights all three')
    expect(differ('fx-param-rotate-x', 'fx-param-rotate-x-plane', chips), 'param.plane lights the plane (Y and Z)')
    hostile = rendered['fx-hostile-card']
    _fps, hostile_ms, _frame = estimate_fps(hostile['lastFills'], hostile['lastCalls'], 16)
    expect(hostile_ms <= HOSTILE_DRAW_MS_MAX,
           f'a hostile card (elements far past the pane, two cards mid-slide) draws in ~{hostile_ms} ms on the knob '
           f'({hostile["lastCalls"]} fills, budget {HOSTILE_DRAW_MS_MAX} ms)')
    make_profiles_sheet(out, pcases, sheet_path)
    print(f'Profiles contact sheet: {sheet_path}')
    return failures


def make_profiles_sheet(out: Path, pcases, sheet_path: Path):
    from PIL import Image, ImageDraw, ImageFont
    scale, gap, label_h, cols = 2, 20, 30, 6
    tile = 240 * scale
    shown = [c for c in pcases if c[0] not in ('fx-wheel-enabled-twin', 'fx-param-at-max', 'fx-loading-crc',
                                               'fx-hostile-card', 'fx-param-move-then-x')]
    rows = (len(shown) + cols - 1) // cols
    width = cols * tile + (cols + 1) * gap
    height = rows * (tile + label_h) + (rows + 1) * gap + 70
    sheet = Image.new('RGB', (width, height), (28, 30, 32))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('segoeui.ttf', 20)
        title = ImageFont.truetype('segoeuib.ttf', 26)
    except OSError:
        font = title = ImageFont.load_default()
    draw.text((gap, 20), 'App profiles: the generic app canvas on harness fixtures (app_canvas_fixtures.c) - '
              'harness/app_canvas_tests.py (UI adapted from Karl Malota, with permission)',
              fill=(230, 230, 230), font=title)
    mask = Image.new('L', (tile, tile), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, tile - 1, tile - 1), fill=255)
    for i, (name, _view, _steps, label, _profile) in enumerate(shown):
        im = Image.open(out / f'{name}.png').convert('RGB').resize((tile, tile), Image.NEAREST)
        x = gap + (i % cols) * (tile + gap)
        y = 70 + gap + (i // cols) * (tile + label_h + gap)
        sheet.paste(im, (x, y), mask)
        draw.ellipse((x, y, x + tile - 1, y + tile - 1), outline=(70, 72, 76))
        draw.text((x, y + tile + 4), label, fill=(210, 210, 210), font=font)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path, optimize=True)


def s32(word):
    """The int32 the knob publishes for a 32-bit angle word (FW-BUG-032)."""
    return word - (1 << 32) if word >= 1 << 31 else word


WRAP = 1 << 31   # ms: the uptime at which a signed before(now, deadline) flips (24.86 days)
# FW-BUG-023: (wrapped case, its early-uptime twin, what must match). "pixels": the PNGs are identical;
# "frames": the same number of frames drawn (an unwrapped clock).
WRAP_TWINS = [
    ("refused-after-2^31ms", "refused-ref", ("pixels", "frames")),
    ("undo-flash-ended-2^31ms", "undo-flash-ended-ref", ("pixels", "frames")),
    ("wheel-entry-2^31ms", "wheel-entry-ref", ("pixels", "frames")),
    ("track_angle_across_int32_wrap", "track_angle_near_zero-ref", ("pixels", "frames")),
]
# FW-BUG-032: (case, case it must NOT match): the turn across the wrap moved the cube.
MOVED_PAIRS = [("track_angle_across_int32_wrap", "track_angle_still-ref")]
WRAP_TWIN_NAMES = frozenset([name for wrapped, twin, _what in WRAP_TWINS for name in (wrapped, twin)] +
                            [name for pair in MOVED_PAIRS for name in pair])


def estimate_fps(pixels, calls, period_ms):
    """Knob frame-rate estimate for one screen (a model, not a measurement; diag lcdFps measures it on the knob).
    ESP32-S3 at 240 MHz, octal PSRAM, SPI at 80 MHz. Drawing: 15 ns per pixel written into the PSRAM canvas
    (16-bit stores through the cache, write-back bound at ~66 MB/s: the full clear alone is ~0.9 ms) plus
    0.35 us per fill() call (clip and loop set-up; Silkscreen text is one call per lit font pixel). Pushing:
    115,200 B in ten 24-row chunks; each chunk's PSRAM -> internal copy (~0.25 ms) overlaps the previous chunk's
    DMA except the first, and the wire takes 921,600 bits / 80 MHz = 11.52 ms. A frame is draw + 0.25 + 11.52 ms;
    the binary's period (D 16 ms, F 12 ms) is the floor between two frames of a moving screen. For scale: Karl
    measured ~1 ms draw and ~11.8 ms push for his screens in an internal-RAM sprite."""
    draw_ms = pixels * 15e-6 + calls * 0.35e-3
    frame_ms = draw_ms + 11.52 + 0.25
    return round(1000.0 / max(frame_ms, period_ms), 1), round(draw_ms, 2), round(frame_ms, 2)


def make_sheet(out: Path, results, cases, sheet_path: Path, karl: Path | None):
    from PIL import Image, ImageDraw, ImageFont
    scale, gap, label_h, cols = 2, 20, 30, 6
    tile = 240 * scale
    rows = (len(cases) + cols - 1) // cols
    width = cols * tile + (cols + 1) * gap
    height = rows * (tile + label_h) + (rows + 1) * gap + 70
    karl_img = None
    if karl is not None and karl.is_file():
        karl_img = Image.open(karl).convert('RGB')
        kw = width - 2 * gap
        karl_img = karl_img.resize((kw, int(karl_img.height * kw / karl_img.width)), Image.NEAREST)
        height += karl_img.height + 60
    sheet = Image.new('RGB', (width, height), (28, 30, 32))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('segoeui.ttf', 20)
        title = ImageFont.truetype('segoeuib.ttf', 26)
    except OSError:
        font = title = ImageFont.load_default()
    draw.text((gap, 20), 'Onshape app canvas (A2, 1.0.0-cc5.6) - firmware drawing code, rendered by '
              'harness/app_canvas_tests.py (UI adapted from Karl Malota, with permission)',
              fill=(230, 230, 230), font=title)
    mask = Image.new('L', (tile, tile), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, tile - 1, tile - 1), fill=255)
    for i, (name, _view, _steps, label) in enumerate(cases):
        img = Image.open(out / f'{name}.png').convert('RGB').resize((tile, tile), Image.NEAREST)
        x = gap + (i % cols) * (tile + gap)
        y = 70 + gap + (i // cols) * (tile + label_h + gap)
        sheet.paste(img, (x, y), mask)
        draw.ellipse((x, y, x + tile - 1, y + tile - 1), outline=(70, 72, 76))
        draw.text((x, y + tile + 4), label, fill=(210, 210, 210), font=font)
    if karl_img is not None:
        y = height - karl_img.height - gap
        draw.text((gap, y - 40), "Karl's own tools/ui_preview renders (katbinaris/NanoD_RatchetH1 "
                  "feat/firmware-esp-idf-quadra), for comparison", fill=(230, 230, 230), font=title)
        sheet.paste(karl_img, (gap, y))
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path, optimize=True)
    return sheet_path


def host_app(stored):
    """device.app_parse()'s stored object as the harness prints the firmware's: the id as text ("onshape" for the
    cc5.6 index 1) and the crc (0 when the host reading has none)."""
    if stored is None:
        return None
    out = dict(stored)
    if not isinstance(out.get('id'), str):
        out['id'] = {v: k for k, v in device.APP_IDS.items()}.get(out.get('id'), '')
    out.setdefault('crc', 0)
    return out


def frame_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_goldens(out: Path, cases, rendered, update: bool) -> int:
    """The built-in Onshape renders (every case of render_cases() and its snaps) against goldens/app_canvas."""
    frames = [frame for name, _v, _s, _l in cases for frame in (name, *rendered[name]['snaps'])]
    hashes = {frame: frame_hash(out / f'{frame}.rgb565') for frame in frames}
    manifest_path = GOLDENS / 'manifest.json'
    if update:
        GOLDENS.mkdir(parents=True, exist_ok=True)
        for old in GOLDENS.glob('*.png'):
            old.unlink()
        for frame in frames:
            shutil.copyfile(out / f'{frame}.png', GOLDENS / f'{golden_file(frame)}.png')
        manifest = {"what": "app canvas pixel goldens: sha256 of the raw 240x240 RGB565 buffer (little-endian) of "
                            "each built-in Onshape render case (and <case>@<ms> mid-animation snaps)",
                    "generator": "harness/app_canvas_tests.py --update-goldens",
                    "firmware": subprocess.run(['git', '-C', str(firmware), 'describe', '--always', '--dirty'],
                                               capture_output=True, text=True).stdout.strip(),
                    "frames": {frame: hashes[frame] for frame in frames}}
        manifest_path.write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
        print(f'UPDATED goldens: {len(frames)} frames -> {manifest_path}')
        return 0
    if not manifest_path.is_file():
        print(f'FAIL goldens: {manifest_path} missing')
        return 1
    want = json.loads(manifest_path.read_text(encoding='utf-8'))['frames']
    bad = [frame for frame in frames if want.get(frame) != hashes[frame]]
    stale = sorted(set(want) - set(frames))
    for frame in bad:
        print(f'FAIL golden {frame}: {"not in the manifest" if frame not in want else "pixels differ"} '
              f'(see {out / (frame + ".png")} vs {GOLDENS / (golden_file(frame) + ".png")})')
    for frame in stale:
        print(f'FAIL golden {frame}: in the manifest but not rendered')
    ok = not bad and not stale
    print(f'{"PASS" if ok else "FAIL"} Onshape pixel goldens: {len(frames) - len(bad)}/{len(frames)} frames byte for '
          f'byte ({manifest_path.relative_to(work)})')
    return len(bad) + len(stale)


def golden_file(frame: str) -> str:
    """A file name for a frame name ("^" and "@" are kept; nothing else needs escaping on Windows)."""
    return frame


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--no-gate', action='store_true')
    parser.add_argument('--out', type=Path, default=root / 'build' / 'app-canvas')
    parser.add_argument('--sheet', type=Path, default=SHEET)
    parser.add_argument('--karl', type=Path, default=None)
    parser.add_argument('--update-goldens', action='store_true', help='rewrite goldens/app_canvas from this run')
    parser.add_argument('--profiles-sheet', type=Path, default=None,
                        help='the app-profile fixtures contact sheet (default: <out>/app-profiles-contact-sheet.png)')
    args = parser.parse_args(argv)
    if not args.no_gate:
        subprocess.run([sys.executable, str(root / 'cpp11_gate.py')], check=True)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    exe = build(out)
    cases = render_cases()
    pcases = profile_cases()
    payload = {"parse": parse_entries(),
               "render": [{"name": name, "steps": steps} for name, _v, steps, _l in cases] +
                         [dict({"name": name, "steps": steps}, **({"profile": prof} if prof else {}))
                          for name, _v, steps, _l, prof in pcases]}
    cases_path = out / 'cases.json'
    cases_path.write_text(json.dumps(payload), encoding='utf-8')
    run = subprocess.run([str(exe), str(cases_path), str(out)], capture_output=True, text=True)
    if run.returncode:
        print(run.stdout, run.stderr)
        return 1
    results = [json.loads(text) for text in run.stdout.splitlines() if text.strip()]
    failures = 0

    # Parse parity: firmware vs expectation vs device.app_parse.
    parsed = {r['name']: r for r in results if r['kind'] == 'parse'}
    host_profiles = host_reads_profiles()
    for name, value, accept in PARSE_CASES:
        got = parsed[name]
        obj = json.loads(value) if isinstance(value, str) else value
        host_stored, host_ok = device.app_parse(obj) if obj is not None else (None, True)
        host_stored = host_app(host_stored)
        problem = None
        if got['accept'] != accept:
            problem = f'firmware accept {got["accept"]}, expected {accept}'
        elif name in PROFILE_PARSE and not host_profiles:
            pass   # the firmware side only (below: refusedFocus)
        elif host_ok != accept:
            problem = f'device.app_parse accept {host_ok}, expected {accept}'
        elif accept and obj is not None and got['app'] != host_stored:
            problem = f'stored differs: firmware {got["app"]} host {host_stored}'
        elif accept and obj is None and got['app']['id'] != '':
            problem = 'a frame without app stored an app'
        elif got.get('refusedFocus') != (name in REFUSED_FOCUS_TRUE):
            problem = f'refusedFocus {got.get("refusedFocus")}, expected {name in REFUSED_FOCUS_TRUE}'
        if problem:
            failures += 1
            print(f'FAIL parse {name}: {problem}')
    print(f'{"PASS" if not failures else "FAIL"} app object parse: {len(PARSE_CASES)} cases, firmware == '
          'expectation == device.app_parse')
    if not host_profiles:
        print(f'NOTE app object parse: device.app_parse does not read app-profile ids yet; {len(PROFILE_PARSE)} '
              'profile cases checked against the firmware only')

    # The wheel table: the firmware's rings, names and chords are Desk Dial's (onshape_app.COMMANDS).
    table = (src / 'cc_app_onshape.c').read_text(encoding='utf-8')
    for ring in onshape_app.RINGS:
        for command in ring.commands:
            chord = command.display_chord()
            needle = f'{{"{command.name}", {"true" if command.search else "false"}, {chord}'
            if needle not in table:
                failures += 1
                print(f'FAIL wheel table: {ring.name} {command.name}: {needle!r} not in cc_app_onshape.c')
    print('PASS wheel table parity (cc_app_onshape.c == onshape_app.RINGS)' if not failures else '')

    # Renders.
    from ppm_to_png import convert
    rendered = {r['name']: r for r in results if r['kind'] == 'render'}
    report = []
    for name, view, _steps, label in [c[:4] for c in cases] + [c[:4] for c in pcases]:
        r = rendered[name]
        for frame in (name, *r['snaps']):
            convert(out / f'{frame}.ppm')
            (out / f'{frame}.ppm').unlink()
        # Every pass releases what it acquired (no profile pointer outlives a pass); a profile was drawn from.
        leases_ok = not r['leaked'] and (r['leases'] > 0 or view == 'loading')
        if r['view'] != view or r['frames'] < 1 or r['lastFills'] < 57600 or not r['guard'] or not leases_ok:
            failures += 1
            print(f'FAIL render {name}: view {r["view"]} (expected {view}), frames {r["frames"]}, '
                  f'last frame {r["lastFills"]} px, guard bands {"intact" if r["guard"] else "WRITTEN"}, '
                  f'leases {r["leases"]} {"LEAKED" if r["leaked"] else "released"}')
        if any(name == c[0] for c in pcases):
            print(f'{"PASS" if r["view"] == view else "FAIL"} render {name:14s} view {r["view"]:7s} '
                  f'{r["lastFills"]:6d} px {r["lastCalls"]:5d} fills, {r["leases"]} leases')
            continue
        fps_d, draw_ms, frame_ms = estimate_fps(r['lastFills'], r['lastCalls'], 16)
        fps_f, _, _ = estimate_fps(r['lastFills'], r['lastCalls'], 12)
        report.append({"name": name, "label": label, "view": r['view'], "framesDrawn": r['frames'],
                       "pixelsWritten": r['lastFills'], "fillCalls": r['lastCalls'], "drawMsEstimate": draw_ms, "frameMsEstimate": frame_ms,
                       "fpsD": fps_d, "fpsF": fps_f, "hostDrawUsMax": r['drawUsMax']})
        print(f'{"PASS" if r["view"] == view else "FAIL"} render {name:14s} view {r["view"]:5s} '
              f'{r["lastFills"]:6d} px {r["lastCalls"]:5d} fills -> draw ~{draw_ms:5.2f} ms, frame ~{frame_ms:5.2f} ms: D {fps_d} fps, F {fps_f} fps')
    failures += check_goldens(out, cases, rendered, args.update_goldens)
    failures += check_profiles(out, pcases, rendered, args.profiles_sheet or out / 'app-profiles-contact-sheet.png')
    from PIL import Image, ImageChops
    for wrapped, twin, what in WRAP_TWINS:
        problems = []
        if 'pixels' in what:
            a = Image.open(out / f'{wrapped}.png').convert('RGB')
            b = Image.open(out / f'{twin}.png').convert('RGB')
            if ImageChops.difference(a, b).getbbox() is not None:
                problems.append('pixels differ')
        if 'frames' in what and rendered[wrapped]['frames'] != rendered[twin]['frames']:
            problems.append(f'frames {rendered[wrapped]["frames"]} vs {rendered[twin]["frames"]}')
        failures += bool(problems)
        print(f'{"FAIL" if problems else "PASS"} uptime wrap {wrapped} == {twin} ({", ".join(what)})'
              + (f': {"; ".join(problems)}' if problems else ''))
    for moved, still in MOVED_PAIRS:
        a = Image.open(out / f'{moved}.png').convert('RGB')
        b = Image.open(out / f'{still}.png').convert('RGB')
        ok = ImageChops.difference(a, b).getbbox() is not None
        failures += not ok
        print(f'{"PASS" if ok else "FAIL"} angle wrap: {moved} differs from {still} (the turn moved the cube)')
    # HN-DES-001: the chord shows (the fourth keycap lights: home-chord-4 differs from home-chord-3) within the
    # draw budget of the screens already on the sheet, and the zoom at its bound draws its main screen.
    budget = max(e['drawMsEstimate'] for e in report if not e['name'].startswith(('home-chord', 'zoom-at-bound')))
    for name in ('home-chord-3', 'home-chord-4', 'zoom-at-bound'):
        entry = next(e for e in report if e['name'] == name)
        ok = entry['drawMsEstimate'] <= budget
        failures += not ok
        print(f'{"PASS" if ok else "FAIL"} {name}: draw ~{entry["drawMsEstimate"]} ms within the sheet budget '
              f'({budget} ms)')
    chord3 = Image.open(out / 'home-chord-3.png').convert('RGB')
    chord4 = Image.open(out / 'home-chord-4.png').convert('RGB')
    shown = ImageChops.difference(chord3, chord4).getbbox() is not None
    failures += not shown
    print(f'{"PASS" if shown else "FAIL"} home chord: all four held draws differently from three (fourth keycap lit)')
    # DD-SEC-001: the focus refusal reads CLICK MODEL FIRST: it differs from POINT AT MODEL on the action line only
    # (y 131), and a refusal that turns into a focus refusal redraws to that same screen.
    refused_img = Image.open(out / 'refused.png').convert('RGB')
    focus_img = Image.open(out / 'refused-focus.png').convert('RGB')
    later_img = Image.open(out / 'refused-then-focus.png').convert('RGB')
    box = ImageChops.difference(refused_img, focus_img).getbbox()
    ok = box is not None and box[1] >= 125 and box[3] <= 145
    failures += not ok
    print(f'{"PASS" if ok else "FAIL"} refused focus: CLICK MODEL FIRST differs from POINT AT MODEL on the action '
          f'line only (diff box {box})')
    ok = ImageChops.difference(focus_img, later_img).getbbox() is None
    failures += not ok
    print(f'{"PASS" if ok else "FAIL"} refused focus: a refusal turning into a focus refusal redraws to it')
    (out / 'app-canvas-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    # The wrap twins are test-only screens: they are checked above but never drawn on the contact sheet (the
    # default --sheet is the committed design reference).
    sheet_cases = [case for case in cases if case[0] not in WRAP_TWIN_NAMES]
    if len(sheet_cases) != len(cases) - len(WRAP_TWIN_NAMES):
        failures += 1
        print('FAIL contact sheet: a WRAP_TWINS name is not a render case')
    sheet = make_sheet(out, results, sheet_cases, args.sheet, args.karl)
    print(f'Contact sheet: {sheet}')
    print(f'{"PASS" if not failures else "FAIL"} app canvas harness ({failures} failure(s))')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

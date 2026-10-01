"""Onshape app-canvas animations for the README: the knob's own Onshape UI (Karl Malota's design, adapted
with permission; cube, command wheel, parameter mode, echo, idle plasma) rendered by the firmware's own
drawing code through lcd/app_canvas_anim.cpp (app-canvas-anim.exe, built by build_lcd.py).

A scene is a script for app-canvas-anim: timed steps carrying the knob's shaft angle (1e-4 rad, as the
firmware's cc_app_angle_read()), the physical button mask, and the frame lines Desk Dial would send. The
frames are hand-built after control_center/controller.py _frame_onshape (the A0 text frame around the A2
`app` object) and every `app` object is checked against control_center.device.app_parse (the host's
reading of the firmware parser) before it goes into a script. Nothing here talks to a knob or to Onshape.

What the knob does with a script (cc_app_canvas.cpp, cc_app_canvas.h): the cube follows the angle in the
`zoom` / `tilt` / `orbit` / `pan` slot (32 stepped poses per turn; zoom one doubling per quarter turn, pan
60 px per radian), eases over kCCAppSettleMs = 220 ms when orbit or tilt ends; a `flash` change is the
260 ms amber UNDO; `wheel` shows the command wheel (Desk Dial reveals it 250 ms into a button-3 hold,
onshape_app.WHEEL_SHOW_S), an entry change slides the cards over 120 ms and the card's own keyframes loop
(SKETCH's first keyframe is 650 ms, EXTRUDE's 600 + 80 + 80 ms then 1300 ms rest: cc_app_onshape.c:33-42);
`param` draws parameter mode (A: the value is the change); an `echo` seq change replays the card for 1.1 s;
5 s without input starts the plasma.

Usage (a test render):
  DESK_DIAL_APP=<app dir> python onshape_scenes.py --exe <build>/Release/app-canvas-anim.exe --work <dir> [scene]
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from PIL import Image

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion import dev  # noqa: E402
import knob_scenes as K  # noqa: E402

# A knob that draws the app canvas: presentation 6 and appCanvas 1 (device.app_capability).
CAPS = dict(K.CAPS, presentation=6, appCanvas=1)

TURN = 62832                    # 2 pi in 1e-4 rad
QUARTER = TURN // 4
B1, B2, B3, B4 = 1, 2, 4, 8     # physical button bits (CCAppInputs.buttons: bit n = button n)
FPS = 30
MIN_FRAME_MS = 12               # CC_LCD_PERIOD_MS of the F binary (the release knob)

# controller.py COPY (lines 436-448): the text frame around the app object (an older knob shows it).
TITLE = {"zoom": "ZOOM", "orbit": "ORBIT", "pan": "PAN", "tilt": "TILT", "refused": "Point at the model"}
SUB = {"zoom": "1 tilt · 2 orbit · 4 pan", "orbit": "Turn to orbit", "tilt": "Turn to tilt", "pan": "Turn to pan",
       "refused": "Put the cursor on it"}
MODEL, MODIFY, SKETCH, VIEW = 0, 1, 2, 3          # cc_app_onshape.c RINGS / onshape_app.RINGS
SKETCH_CMD, EXTRUDE, REVOLVE = 1, 2, 3            # MODEL ring entries (0 = cancel)


def _btn(icon, label, lit=None):
    return {"icon": icon, "label": label, "enabled": True, "lit": lit, "color": 0}


def onshape_frame(fid, slot="zoom", refused=False, held=None, **app_extra):
    """The frame Desk Dial sends in Onshape mode (controller._frame_onshape / _buttons_onshape), with the
    A2 `app` object: slot = the cube scene, plus flash / wheel / param / echo from the injector."""
    action = "refused" if refused else slot
    lit = {0: "on"} if held == 0 else {1: "on"} if held == 1 else {3: "on"} if held == 3 else {}
    frame = {"id": fid, "mode": "ONSHAPE", "target": "Onshape", "value": TITLE[action], "detail": SUB[action],
             "status": "", "title": TITLE[action], "subtitle": SUB[action], "counter": "", "activity": "idle",
             "buttons": [_btn("expand", "Tilt", lit.get(0)), _btn("shuffle", "Orbit", lit.get(1)),
                         _btn("back", "Undo"), _btn("expand", "Pan", lit.get(3))],
             "ring": {"style": "off", "value": 0, "index": 0, "count": 0}, "layout": "nowPlaying",
             "heading": "ONSHAPE", "meta": "", "titleTone": "ink", "metaTone": "meta", "statusTone": "meta",
             "reducedMotion": False}
    app = {"id": "onshape", "slot": slot}
    if refused:
        app["refused"] = True
    app.update(deepcopy(app_extra))
    stored, ok = dev.app_parse(app)
    if not ok:
        raise ValueError(f"app object the firmware would reject: {app}")
    frame["app"] = app
    wire = dev._frame(frame, CAPS)
    if "app" not in wire or wire["app"] != app:
        raise ValueError(f"device._frame dropped or changed the app object: {app}")
    return wire, stored


class Script:
    """Steps for app-canvas-anim, built in time order."""

    def __init__(self, name, duration_ms, fps=FPS, start_ms=0):
        self.name = name
        self.script = {"fps": fps, "duration_ms": duration_ms, "start_ms": start_ms, "min_frame_ms": MIN_FRAME_MS,
                       "steps": []}
        self.fid = 0
        self.flash_seq = 0
        self.echo_seq = 0
        self.last = {}            # the last app object sent (for incremental changes)
        self.held = None          # logical modifier slot lit on the text frame

    def step(self, t, angle=None, buttons=None):
        s = {"t": int(t)}
        if angle is not None:
            s["angle"] = int(angle)
        if buttons is not None:
            s["buttons"] = int(buttons)
        if self.script["steps"] and self.script["steps"][-1]["t"] > s["t"]:
            raise ValueError(f"{self.name}: step at {t} out of order")
        self.script["steps"].append(s)
        return s

    def frame(self, t, slot="zoom", angle=None, buttons=None, refused=False, **app):
        self.fid += 1
        wire, _ = onshape_frame(self.fid, slot, refused, self.held, **app)
        s = self.step(t, angle, buttons)
        s["line"] = json.dumps({"frame": wire}, ensure_ascii=False, separators=(",", ":"))
        self.last = {k: v for k, v in app.items()}
        self.last["slot"] = slot
        return s

    def again(self, t, angle=None, buttons=None, **changes):
        """Resend the last app object with changes (None removes a key)."""
        app = {k: v for k, v in self.last.items() if k != "slot"}
        for k, v in changes.items():
            if v is None:
                app.pop(k, None)
            else:
                app[k] = v
        return self.frame(t, self.last.get("slot", "zoom"), angle, buttons, **app)

    def flash(self, t, angle=None, buttons=None):
        self.flash_seq += 1
        return self.again(t, angle, buttons, flash=self.flash_seq)

    def echo(self, t, ring, index, angle=None, buttons=None):
        self.echo_seq += 1
        return self.again(t, angle, buttons, echo={"ring": ring, "index": index, "seq": self.echo_seq})

    def sweep(self, t0, t1, a0, a1, every=40):
        """A continuous knob movement: angle keyframes every `every` ms (the renderer interpolates per ms)."""
        n = max(1, int((t1 - t0) / every))
        for k in range(1, n + 1):
            f = k / n
            e = f * f * (3 - 2 * f)          # ease in and out, as a hand turns
            self.step(t0 + (t1 - t0) * f, angle=round(a0 + (a1 - a0) * e))


# ------------------------------------------------------------------ the scenes
def _zoom(S, t0, angle0=0):
    """Knob alone: a turn in over 2 s, then rest (one doubling per quarter turn, 1/8-doubling steps)."""
    S.frame(t0, "zoom", angle=angle0, buttons=0)
    S.sweep(t0 + 100, t0 + 1700, angle0, angle0 + TURN)
    S.step(t0 + 2000, angle=angle0 + TURN)
    return angle0 + TURN


def _held_sweep(S, t0, slot, button, angle0, span, hold_ms=2000, lit=None):
    """Button held + a turn, then the release: the slot returns to zoom and the cube settles (220 ms)."""
    S.held = lit
    S.frame(t0, slot, angle=angle0, buttons=button)
    S.sweep(t0 + 150, t0 + hold_ms - 450, angle0, angle0 + span)
    S.held = None
    S.frame(t0 + hold_ms - 300, "zoom", angle=angle0 + span, buttons=0)   # release: slot back to zoom
    S.step(t0 + hold_ms, angle=angle0 + span)
    return angle0 + span


def scene_zoom():
    S = Script("onshape-zoom", 2600)
    _zoom(S, 0)
    S.step(2600)
    return S


def scene_tilt():
    S = Script("onshape-tilt", 2400)
    _held_sweep(S, 0, "tilt", B1, 0, TURN // 8, lit=0)
    S.step(2400)
    return S


def scene_orbit():
    S = Script("onshape-orbit", 2400)
    _held_sweep(S, 0, "orbit", B2, 0, QUARTER + 3000, lit=1)      # ends off-pose: the ease to 135 deg shows
    S.step(2400)
    return S


def scene_pan():
    S = Script("onshape-pan", 2400)
    _held_sweep(S, 0, "pan", B4, 0, TURN // 3, lit=3)
    S.step(2400)
    return S


def scene_undo():
    """Tap 3 (held under 400 ms, no turn): Desk Dial sends Ctrl+Z and bumps `flash`; the knob shows F3 UNDO in
    amber for 260 ms while the key is lit."""
    S = Script("onshape-undo", 1400)
    S.frame(0, "zoom", angle=0, buttons=0)
    S.step(300, buttons=B3)
    S.flash(420, buttons=0)              # the release is the tap (onshape_app.up -> undo_seq += 1)
    S.step(1400)
    return S


def _wheel(S, t0, angle0):
    """Hold 3: the wheel appears 250 ms in (WHEEL_SHOW_S) on MODEL entry 1 (SKETCH), the turn walks the entries
    (12 per turn, onshape_app.WHEEL_ENTRIES_PER_TURN): SKETCH -> EXTRUDE -> REVOLVE -> back to EXTRUDE, and
    the release on EXTRUDE closes the wheel and enters parameter mode (EXTRUDE has a parameter, DEPTH)."""
    per = TURN // 12
    S.step(t0, angle=angle0, buttons=B3)
    S.again(t0 + 250, wheel={"ring": MODEL, "index": SKETCH_CMD})
    a = angle0
    for t, index in ((t0 + 950, EXTRUDE), (t0 + 1650, REVOLVE)):
        S.sweep(t - 200, t - 20, a, a + per)
        a += per
        S.again(t, angle=a, wheel={"ring": MODEL, "index": index})
    S.sweep(t0 + 2150, t0 + 2330, a, a - per)
    a -= per
    S.again(t0 + 2350, angle=a, wheel={"ring": MODEL, "index": EXTRUDE})
    return a


def _param(S, t, angle0, steps=((0, 100), (260, 200), (520, 300))):
    """Release 3 on EXTRUDE: parameter mode A (scroll) for DEPTH, value = the change in thousandths; the knob
    alone steps 0.1 (16 steps per turn, PARAM_STEPS_PER_TURN). Then a short press of 3 = OK (RELEASE: OK)."""
    S.again(t, angle=angle0, buttons=0, wheel=None,
            param={"ring": MODEL, "index": EXTRUDE, "mode": "A", "value": 0, "step": 1})
    per = TURN // 16
    a = angle0
    for dt, milli in steps:
        S.sweep(t + 300 + dt, t + 300 + dt + 200, a, a + per)
        a += per
        S.again(t + 300 + dt + 220, angle=a,
                param={"ring": MODEL, "index": EXTRUDE, "mode": "A", "value": milli, "step": 1})
    t_ok = t + 300 + steps[-1][0] + 600
    S.step(t_ok, buttons=B3)
    return t_ok + 120, a


def _echo_extrude(S, t, angle, buttons=0):
    """The command ran: the knob replays EXTRUDE's card for 1.1 s (kCCAppEchoMs) under the badge."""
    S.again(t, angle=angle, buttons=buttons, param=None)
    S.echo(t + 10, MODEL, EXTRUDE)


def scene_wheel():
    S = Script("onshape-wheel", 3200)
    S.frame(0, "zoom", angle=0, buttons=0)
    _wheel(S, 300, 0)
    S.step(3200)
    return S


def scene_param():
    S = Script("onshape-param", 2600)
    S.frame(0, "zoom", angle=0, buttons=B3, wheel={"ring": MODEL, "index": EXTRUDE})
    t_ok, a = _param(S, 400, 0)
    S.step(t_ok, buttons=0)
    S.step(2600)
    return S


def scene_echo():
    S = Script("onshape-echo", 1600)
    S.frame(0, "zoom", angle=0, buttons=0)
    _echo_extrude(S, 200, 0)
    S.step(1600)
    return S


def scene_idle():
    """No input for 5 s (kCCAppIdleMs): the plasma ripples out of the app badge; the capture starts 4.5 s in."""
    S = Script("onshape-idle", 3500, start_ms=4500)
    S.frame(0, "zoom", angle=0, buttons=0)
    S.step(8000)
    return S


def scene_combined():
    """The README loop (~9.8 s): zoom 2 s, tilt 2 s, wheel + cards 3 s, parameter mode 1.5 s, echo 1.3 s."""
    S = Script("onshape-knob", 9800)
    a = _zoom(S, 0)                                        # 0.0 - 2.0 s
    a = _held_sweep(S, 2000, "tilt", B1, a, TURN // 8, lit=0)  # 2.0 - 4.0 s (release at 3.7 s, settle 220 ms)
    a = _wheel(S, 4000, a)                                 # 4.0 - 6.35 s: wheel at 4.25, EXTRUDE 4.95, REVOLVE 5.65, EXTRUDE 6.35
    t_ok, a = _param(S, 6700, a)                           # 6.7 s: DEPTH, +0.10 / +0.20 / +0.30, OK pressed
    _echo_extrude(S, t_ok, a, buttons=0)                   # ~8.3 s: EXTRUDE's card replays
    S.step(9800)
    return S


SCENES = {"onshape-zoom": scene_zoom, "onshape-tilt": scene_tilt, "onshape-orbit": scene_orbit, "onshape-pan": scene_pan,
          "onshape-undo": scene_undo, "onshape-wheel": scene_wheel, "onshape-param": scene_param,
          "onshape-echo": scene_echo, "onshape-idle": scene_idle, "onshape-knob": scene_combined}


# ------------------------------------------------------------------ rendering
def frames(script, exe, work):
    """Runs app-canvas-anim on `script` (a Script or its dict) and returns the 240x240 RGB frames."""
    S = script if isinstance(script, dict) else script.script
    name = script.get("name", "onshape") if isinstance(script, dict) else script.name
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    sp = work / f"{name}.script.json"
    sp.write_text(json.dumps(S, ensure_ascii=False), encoding="utf-8")
    raw = work / f"{name}.rgb"
    subprocess.run([str(exe), str(sp), str(raw)], check=True)
    data = raw.read_bytes()
    n = len(data) // (240 * 240 * 3)
    return [Image.frombytes("RGB", (240, 240), data[k * 172800:(k + 1) * 172800]) for k in range(n)]


def capture_times(script):
    S = script if isinstance(script, dict) else script.script
    return [math.ceil(k * 1000 / S["fps"]) for k in range(math.ceil(S["duration_ms"] * S["fps"] / 1000))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--every", type=int, default=15, help="write every n-th frame as PNG")
    ap.add_argument("scenes", nargs="*")
    a = ap.parse_args()
    for name in a.scenes or SCENES:
        S = SCENES[name]()
        imgs = frames(S, a.exe, a.work)
        out = a.work / name
        out.mkdir(parents=True, exist_ok=True)
        times = capture_times(S)
        for k in range(0, len(imgs), a.every):
            imgs[k].save(out / f"{k:04d}-{times[k] + S.script['start_ms']:05d}ms.png")
        print(f"{name}: {len(imgs)} frames -> {out}")


if __name__ == "__main__":
    main()

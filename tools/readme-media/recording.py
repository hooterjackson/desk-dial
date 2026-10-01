"""From a true-to-app recording (capture.py, schema desk-dial-recording/1) to knob frames.

* lcd_frames(rec, knob_anim, work): the recording's wire frames, key edges and end-stop pushes become a
  knob-anim script (lcd/knob_anim.cpp: {"at","frame"} | {"at","keys"} | {"at","wall"}) and the firmware's
  own LCD renderer draws one 240 x 240 RGB frame per output tick.
* led_frames(rec): the "Warm · alive" engine's Python twin (control_center.alive_lights.AliveLights, the
  same engine as the firmware) is fed the same frames, detents, presses, releases and end-stop pushes at
  the same times, and rendered at the knob's 60 Hz plus every capture tick.
* knob_frames(rec, knob_anim, work, ...): both composited onto the knob (knob_scenes.KnobDevice).
* save_loop(frames, fps, stem, out, ...): animated WebP within a byte cap (quality stepped down) plus a
  GIF fallback within its cap.

Times: a recording's events are in ms relative to output time 0; output covers [0, duration_ms) at fps;
events may start at -preroll_ms. Covers and icons are resolved relative to the JSON file.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from PIL import Image

import knob_scenes as K
from companion import AliveLights

WEBP_CAP = 1_200_000
GIF_CAP = 2_900_000


def load(path):
    path = Path(path)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["_dir"] = path.parent
    rec["covers"] = {k: str((path.parent / v).resolve()) for k, v in rec.get("covers", {}).items()}
    rec["icons"] = {k: str((path.parent / v).resolve()) for k, v in rec.get("icons", {}).items()}
    return rec


def capture_times(rec):
    fps, dur = rec["fps"], rec["duration_ms"]
    return [math.ceil(k * 1000 / fps) for k in range(math.ceil(dur * fps / 1000))]


def _events(rec, kinds):
    order = {"frame": 1, "control": 1, "detent": 0, "kd": 0, "ku": 0, "kh": 0, "lim": 0, "haptic": 2, "note": 3}
    ev = [e for e in rec["events"] if e["kind"] in kinds]
    return sorted(ev, key=lambda e: (e["t"], order.get(e["kind"], 5)))


def script_for(rec, work, t_start=0, t_end=None):
    """The knob-anim script for the recording window [t_start, t_end) of output time."""
    pre = rec["preroll_ms"]
    dur = rec["duration_ms"] if t_end is None else (t_end - t_start)
    steps, keys = [], 0
    for e in _events(rec, ("frame", "kd", "ku", "lim")):
        at = e["t"] + pre - t_start
        if at < 0:
            # Anything before the window still has to be applied: collapse it to the first tick.
            at = 0
        if e["kind"] == "frame":
            steps.append({"at": at, "frame": e["frame"]})
        elif e["kind"] == "kd":
            keys |= 1 << e["slot"]
            steps.append({"at": at, "keys": keys})
        elif e["kind"] == "ku":
            keys &= ~(1 << e["slot"])
            steps.append({"at": at, "keys": keys})
        elif e["kind"] == "lim":
            steps.append({"at": at, "wall": int(e["dir"])})
    steps.sort(key=lambda s: s["at"])
    return {"fps": rec["fps"], "duration_ms": dur, "start_ms": pre, "covers": rec["covers"], "icons": rec["icons"],
            "steps": steps}


def lcd_frames(rec, knob_anim, work, t_start=0, t_end=None, tag=""):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    sp = work / f"{rec['name']}{tag}.script.json"
    sp.write_text(json.dumps(script_for(rec, work, t_start, t_end), ensure_ascii=False), encoding="utf-8")
    raw = work / f"{rec['name']}{tag}.rgb"
    subprocess.run([str(knob_anim), str(sp), str(raw)], check=True, stdout=subprocess.DEVNULL)
    data = raw.read_bytes()
    n = len(data) // (240 * 240 * 3)
    return [Image.frombytes("RGB", (240, 240), data[k * 172800:(k + 1) * 172800]) for k in range(n)]


def led_frames(rec, t_start=0, t_end=None):
    """(ring e x60, buttons e x4) per capture tick in [t_start, t_end): the twin at 60 Hz."""
    pre = rec["preroll_ms"]
    lights = AliveLights(0)
    lights.claim(0)
    ev = [(e["t"] + pre, e) for e in _events(rec, ("frame", "detent", "kd", "ku", "lim"))]
    caps = [pre + t_start + c for c in capture_times({"fps": rec["fps"], "duration_ms": (rec["duration_ms"] if t_end is None else t_end - t_start)})]
    last = caps[-1]
    ticks = sorted(set([round(j * 1000 / 60) for j in range(int((last + 1) * 60 / 1000) + 2)] + caps))
    frame, ei, out, capset = None, 0, {}, set(caps)
    for now in ticks:
        while ei < len(ev) and ev[ei][0] <= now:
            t, e = ev[ei]
            k = e["kind"]
            if k == "frame":
                frame = e["frame"]
            elif k == "detent":
                lights.detent(t, e["delta"])
            elif k == "kd":
                lights.press(t, e["slot"])
            elif k == "ku":
                lights.key_up(t, e["slot"])
            elif k == "lim":
                lights.limit(t, int(e["dir"]))
            ei += 1
        ring, buttons = lights.render(now, frame)
        if now in capset:
            out[now] = (list(ring), list(buttons))
    return [out[c] for c in caps]


def knob_frames(rec, knob_anim, work, scale=1.1, crop_ring=False, t_start=0, t_end=None, tag=""):
    lcd = lcd_frames(rec, knob_anim, work, t_start, t_end, tag)
    leds = led_frames(rec, t_start, t_end)
    dev = K.KnobDevice(scale=scale, crop_ring=crop_ring)
    n = min(len(lcd), len(leds))
    return [dev.compose(lcd[k], *leds[k]) for k in range(n)]


def save_loop(frames, fps, stem, out_dir, webp_cap=WEBP_CAP, gif_cap=GIF_CAP, colors=192):
    """Animated WebP at full size and rate, quality stepped down until it fits webp_cap; a GIF fallback
    (knob_scenes._gif ladder) within gif_cap. Returns (gif, webp)."""
    out_dir = Path(out_dir)
    dur = round(1000 / fps)
    webp = out_dir / f"{stem}.webp"
    for q in (82, 76, 70, 64, 58, 52):
        frames[0].save(webp, save_all=True, append_images=frames[1:], duration=dur, loop=0, quality=q, method=5)
        if webp.stat().st_size <= webp_cap:
            break
    gif = out_dir / f"{stem}.gif"
    for scale, step in ((1.0, 2), (0.85, 2), (0.75, 2), (0.66, 3), (0.6, 3), (0.5, 3), (0.45, 4)):
        if K._gif(frames, fps, gif, scale, step, colors) <= gif_cap:
            break
    return gif, webp

"""Feel-and-sound panels for the README: the torque and click strips under a knob recording, the static
feel gallery and the sound-bank sheet (panels.py drawing, haptic-trace / sound-dump physics).

feel-and-sound.webp (720 px wide): on top the knob from the music-volume recording (recording.knob_frames,
crop_ring: the climb 62 -> 100, the two refused pushes at the wall, ~0.7 s of flat rest; window -300..5440 ms); below it panels.torque_strip
and panels.sound_strip, both driven by the recording's own events:
  * the torque trace is the firmware's exact static law (haptic-trace, static, detent.value 67/turn, pos 4 of
    0..8) read at a shaft angle derived from the events: the shaft crosses one pitch per `detent` event
    (midpoint at the event, as the hysteresis gate fires), leans up to 2.6 deg into the wall on each `lim`
    event (the value wall reaches the 2.2 V cap within ~2.5 deg) and, 250 ms after it comes to rest, the output
    goes flat (the rest gate, cc_haptic_fx.h CCRestGate). The result is handed to torque_strip as a dynamic
    trace (Uq against time) with the static law as its left pane, the dot on the current tooth.
  * the sound strip plays the click bank (sound-dump): detent -> tock (wood), lim -> thud, haptic
    confirm.thump -> thump, confirm.tick -> tock, in a 1.4 s window sliding with the cursor.
feel-gallery.png / feel-gallery-dark.png: panels.feel_gallery over the five static traces (value / dimmer pos 4 of
0..8 span +-40; list pos 2 of 0..4 span +-60; coarse pos 2 of 0..4 span +-90; fine pos 4 of 0..8 span +-60),
laid out 2 x 3 at native size (760 x 942; the sixth cell holds the law note) and palette-quantised under 300 KB.
sound-bank.png / sound-bank-dark.png: panels.sound_bank_sheet, quantised under 300 KB.

Registry contract: SCENES = {name: (source label, fn)}; fn(ctx) returns the Paths it wrote, each tagged with
ctx.produced(path, source). Imports stay inside the functions. Nothing here touches a device or the network.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

FEEL = "firmware feel laws + knob model"
SOUND = "firmware sound bank"

WIDTH = 720                      # the README column
KNOB_SCALE = 0.9                 # crop_ring knob: 324 px square
TORQUE_H, SOUND_H = 215, 125
# The strips redraw every 2nd frame (15 Hz) under the 30 fps knob: each strip frame changes from the left pane's dot
# to the cursor and the readout (the sound strip scrolls whole), so at 30 Hz the loop needed WebP quality 16 to fit
# 1.2 MB (blocky); at 15 Hz it fits at a sane quality. The knob keeps every frame.
STRIP_EVERY = 2
FPS = 30
# the music-volume recording on its output clock: the climb 62 -> 97 (23..2942 ms), three slow detents to 100
# (3428..3754), the refused pushes (lim +1 at 3914 and 4164), then rest (flat from ~4.72 s); back down from 5464
# (left out: the window must end before it, or the end position and the wall pane are wrong).
WINDOW = (-300, 5440)
STILL_PX = 300_000

# the static specs (haptic-trace, mode static): feel -> (lo, hi, pos, span)
STATIC_SPECS = {
    "detent.value": (0, 8, 4, 40), "detent.dimmer": (0, 8, 4, 40), "detent.list": (0, 4, 2, 60),
    "detent.coarse": (0, 4, 2, 90), "detent.fine": (0, 8, 4, 60),
}

# the shaft model (degrees, ms): one pitch per detent crossing, the wall lean, the rest gate
MOVE_MS = 140                    # a detent crossing takes at most this long (less when the detents come faster)
LEAN_DEG, LEAN_RISE_MS, LEAN_FALL_MS = 2.6, 110, 200
REST_IDLE_MS = 250               # cc_haptic_fx.h: 250 ms still -> output 0
SAMPLE_MS = 5


# ------------------------------------------------------------------ the headless physics
def static_trace(ctx, feel, work):
    """Runs haptic-trace for one static spec (cached in work) and returns panels.load_trace of it."""
    import panels as P
    lo, hi, pos, span = STATIC_SPECS[feel]
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    stem = feel.replace(".", "_")
    spec = work / f"st_{stem}.json"
    out = work / f"st_{stem}.out.json"
    spec.write_text(json.dumps({"mode": "static", "feel": feel, "detents": 67, "lo": lo, "hi": hi, "pos": pos,
                                "span_deg": [-span, span], "step_deg": 0.05}), encoding="utf-8")
    subprocess.run([str(ctx.exe("haptic-trace")), str(spec), str(out)], check=True, stdout=subprocess.DEVNULL)
    return P.load_trace(out)


def sound_bank(ctx, work):
    import panels as P
    folder = Path(work) / "bank"
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ctx.exe("sound-dump")), str(folder)], check=True, stdout=subprocess.DEVNULL)
    return P.load_bank(folder)


# ------------------------------------------------------------------ the shaft from the events
def _smooth(f):
    f = max(0.0, min(1.0, f))
    return f * f * (3 - 2 * f)


def shaft_model(events, t0, t1, start_pos):
    """From the recording's detent / lim events (t in ms on the strip's clock) to callables of t:
    u(t) continuous position in detents, pen(t) wall penetration in degrees, still_since(t)."""
    detents = sorted(t for t, kind, _ in events if kind == "detent")
    lims = sorted((t, d) for t, kind, d in events if kind == "lim")
    moves = []                       # (t_start, duration, from_pos, to_pos)
    pos = start_pos
    for i, (t, kind, d) in enumerate(sorted(events)):
        if kind != "detent":
            continue
        gaps = []
        j = detents.index(t)
        if j > 0:
            gaps.append(t - detents[j - 1])
        if j + 1 < len(detents):
            gaps.append(detents[j + 1] - t)
        dur = min(MOVE_MS, 0.9 * min(gaps)) if gaps else MOVE_MS
        moves.append((t - dur / 2, dur, pos, pos + d))
        pos += d

    def u(t):
        p = start_pos
        for ts, dur, a, b in moves:
            if t >= ts + dur:
                p = b
            elif t > ts:
                return a + (b - a) * _smooth((t - ts) / dur)
            else:
                break
        return p

    def pen(t):
        total = 0.0
        for tl, d in lims:
            dt = t - tl
            if 0 <= dt < LEAN_RISE_MS:
                f = dt / LEAN_RISE_MS
                total += LEAN_DEG * (1 - (1 - f) ** 2) * d
            elif LEAN_RISE_MS <= dt < LEAN_RISE_MS + LEAN_FALL_MS:
                total += LEAN_DEG * (1 - _smooth((dt - LEAN_RISE_MS) / LEAN_FALL_MS)) * d
        return max(-3.0, min(3.0, total))

    # the shaft is "moving" inside a move or a lean; still otherwise
    busy = [(ts, ts + dur) for ts, dur, _, _ in moves] + [(tl, tl + LEAN_RISE_MS + LEAN_FALL_MS) for tl, _ in lims]
    busy.sort()

    def still_since(t):
        """How long the shaft has been still at t (ms); 0 while moving."""
        last_end = t0 - 10_000
        for a, b in busy:
            if a <= t < b:
                return 0
            if b <= t:
                last_end = max(last_end, b)
        return t - last_end

    return u, pen, still_since


def law_lookup(static):
    """uq(theta_deg) from the static trace's samples (linear interpolation, clamped to the span)."""
    S = static["samples"]
    th0, step = S[0]["theta_deg"], S[1]["theta_deg"] - S[0]["theta_deg"]
    n = len(S)

    def uq(theta):
        x = (theta - th0) / step
        i = int(math.floor(x))
        if i < 0:
            return S[0]["uq_volts"]
        if i >= n - 1:
            return S[-1]["uq_volts"]
        f = x - i
        return S[i]["uq_volts"] * (1 - f) + S[i + 1]["uq_volts"] * f
    return uq


def synth_trace(static, events, t0, t1, start_pos, end_pos):
    """A dynamic-shaped trace for panels.torque_strip: the static law read at the event-derived shaft angle.
    theta_deg is the angle in the static pane (0 = the committed detent at static pos; the end detent `end_pos`
    sits at static hi, so the wall lean lands in the shaded part)."""
    import panels as P
    w = static["detent_width_deg"]
    spos, shi = static["pos"], static["hi"]
    uq_of = law_lookup(static)
    u, pen, still = shaft_model(events, t0, t1, start_pos)
    # the static pane shows pos spos at 0 and the end detent at (shi - spos) * w; a position p maps there as
    # (p - end_pos + shi - spos) * w once it is within the pane's teeth, else to its offset from the nearest tooth
    pivot = end_pos - (shi - spos)                    # the position that sits at theta 0 of the pane

    def theta_of(t):
        p = u(t)
        if p >= pivot - 0.5:
            th = (p - pivot) * w
        else:
            th = ((p + 0.5) % 1.0 - 0.5) * w          # around the pane's centre tooth
        return th + pen(t)

    samples = []
    t = t0
    while t <= t1:
        th = theta_of(t)
        pn = pen(t)
        asleep = still(t) >= REST_IDLE_MS
        uq = 0.0 if asleep else uq_of(th)
        samples.append({"t_ms": t - t0, "theta_deg": th, "pos": int(round(u(t))), "uq_volts": uq,
                        "torque_model_mNm": uq * P.MNM_PER_VOLT, "asleep": asleep, "at_limit": abs(pn) > 0.05})
        t += SAMPLE_MS
    first_rest = next((s["t_ms"] for s in reversed(samples) if not s["asleep"]), 0) + SAMPLE_MS
    lims = sorted(t for t, k, _ in events if k == "lim")
    segments = [{"t_ms": 0, "kind": f"turn {start_pos} → {end_pos}", "ms": 0}]
    if lims:
        segments.append({"t_ms": lims[0] - t0, "kind": "refused", "ms": 0})
    if first_rest < t1 - t0:
        segments.append({"t_ms": first_rest, "kind": "rest", "ms": 0})
    trace = {k: static[k] for k in ("feel", "law", "kp_a_per_rad", "kd_a_per_rad_s", "detents_per_turn",
                                     "detent_width_deg", "lo", "hi")}
    trace.update({"mode": "dynamic", "pos": spos, "samples": samples, "segments": segments,
                  "note": "the static law read at an event-derived shaft angle (panel_scenes.synth_trace)"})
    return trace


def strip_events(rec, t_start, t_end):
    """(t on the strip clock, kind, payload) for the detent / lim / haptic events inside the window."""
    out = []
    for e in rec["events"]:
        t = e["t"] - t_start
        if not 0 <= t <= t_end - t_start:
            continue
        if e["kind"] == "detent":
            out.append((t, "detent", int(e["delta"])))
        elif e["kind"] == "lim":
            out.append((t, "lim", int(e["dir"])))
        elif e["kind"] == "haptic":
            out.append((t, "haptic", e.get("token", "")))
    return sorted(out)


def sound_events(events):
    """panels.sound_strip events from the strip events."""
    out = []
    for t, kind, p in events:
        if kind == "detent":
            out.append({"t_ms": t, "sound": "wood", "caption": "tock"})
        elif kind == "lim":
            out.append({"t_ms": t, "sound": "thud", "caption": "thud: refused"})
        elif kind == "haptic":
            if p == "confirm.thump":
                out.append({"t_ms": t, "sound": "thump", "caption": "thump"})
            elif p == "confirm.tick":
                out.append({"t_ms": t, "sound": "wood", "caption": "tock"})
    return out


def start_position(rec, t_start):
    """The knob position of the last control before the window (the controller's position = the volume)."""
    pos = 0
    for e in rec["events"]:
        if e["kind"] == "control" and e["t"] <= t_start:
            pos = e["control"].get("position", pos)
    return pos


def sound_strip_clean(bank, events, t_ms, size, theme, window_ms):
    """panels.sound_strip with its caption band redrawn: the fast climb's tocks sit ~40 px apart, so every
    caption + "5 ms (widened)" collided. Captions are placed thuds first, then tocks, each only where it does
    not overlap one already drawn; a widened tock is said once per strip ("5 ms, drawn 40 px")."""
    import panels as P
    from PIL import ImageDraw
    img = P.sound_strip(bank, events, t_ms, size, theme, window_ms=window_ms)
    W, H = size
    t = P.THEMES[theme]
    left, right, bottom = 16, 16, 40
    x0, x1, y1 = left, W - right, H - bottom
    d = ImageDraw.Draw(img)
    d.rectangle([0, y1 + 1, W, H], fill=t["bg"])
    w0, w1 = window_ms
    rate = bank["rate"]

    def x_of(ms):
        return x0 + (ms - w0) / max(1e-9, (w1 - w0)) * (x1 - x0)

    f_cap, f_det = P.font(11), P.font(9)
    placed = []                                       # (left, right) of drawn caption boxes
    said_widened = False
    order = sorted(events, key=lambda e: (e["sound"] != "thud", e["t_ms"]))
    for e in order:
        dur = len(bank["samples"][e["sound"]]) / rate * 1000
        xa = x_of(e["t_ms"])
        xb = max(x_of(e["t_ms"] + dur), xa + 40)
        if xb < x0 or xa > x1:
            continue
        widened = xb - x_of(e["t_ms"] + dur) > 1
        cap = e.get("caption") or bank["names"].get(e["sound"], e["sound"])
        det = f"{dur:.0f} ms" + (", drawn 40 px" if widened and not said_widened else "")
        cx = (xa + xb) / 2
        half = max(d.textlength(cap, font=f_cap), d.textlength(det, font=f_det)) / 2 + 4
        if cx - half < 0 or cx + half > W or any(cx - half < b and cx + half > a for a, b in placed):
            if widened and not said_widened:
                det = f"{dur:.0f} ms"
                half = max(d.textlength(cap, font=f_cap), d.textlength(det, font=f_det)) / 2 + 4
                if cx - half < 0 or cx + half > W or any(cx - half < b and cx + half > a for a, b in placed):
                    continue
            else:
                continue
        future = t_ms is not None and e["t_ms"] > t_ms
        d.text((cx, y1 + 6), cap, font=f_cap, fill=t["muted"] if future else t["text"], anchor="ma")
        d.text((cx, y1 + 21), det, font=f_det, fill=t["muted"], anchor="ma")
        said_widened = said_widened or "drawn" in det
        placed.append((cx - half, cx + half))
    return img


def save_loop_capped(frames, fps, stem, out_dir, cap=1_200_000):
    """recording.save_loop (WebP ladder 82..52 + the GIF ladder), then, if the WebP is still over the cap, a
    further quality ladder at method 4 (method 6 is ~13x slower for ~1 % less; the panels are flat colour, so low
    quality costs little on them). Returns (gif, webp, quality used)."""
    import recording
    gif, webp = recording.save_loop(frames, fps, stem, out_dir, webp_cap=cap)
    dur = round(1000 / fps)
    used = None
    for q in (46, 40, 34, 28, 22, 16):
        if webp.stat().st_size <= cap:
            break
        frames[0].save(webp, save_all=True, append_images=frames[1:], duration=dur, loop=0, quality=q, method=4)
        used = q
    return gif, webp, used


# ------------------------------------------------------------------ the scenes
def scene_feel_and_sound(ctx) -> list[Path]:
    import panels as P
    import recording
    import rec_scenes
    from PIL import Image

    work = Path(ctx.work) / "feel"
    rec = recording.load(rec_scenes.recording_path(ctx.work, "music-volume", ctx.log))
    t0, t1 = WINDOW
    knob = recording.knob_frames(rec, ctx.knob_anim, work, scale=KNOB_SCALE, crop_ring=True, t_start=t0, t_end=t1,
                                 tag="-feel")
    n = len(knob)
    events = strip_events(rec, t0, t1)
    start = start_position(rec, t0)
    end = start + sum(d for _, k, d in events if k == "detent")
    static = static_trace(ctx, "detent.value", work)
    trace = synth_trace(static, events, 0, t1 - t0, start, end)
    bank = sound_bank(ctx, work)
    snd = sound_events(events)
    ctx.log(f"{n} knob frames, {len(events)} events ({start} -> {end}), {len(snd)} clicks, "
            f"well peak {static['summary']['well_peak_volts']:.3f} V")

    kw, kh = knob[0].size
    H = kh + TORQUE_H + SOUND_H
    frames = []
    strips = None
    for k in range(n):
        t_ms = round(k * 1000 / rec["fps"])
        canvas = Image.new("RGB", (WIDTH, H), P.THEMES["dark"]["bg"])
        canvas.paste(knob[k], ((WIDTH - kw) // 2, 0))
        if k % STRIP_EVERY == 0:
            strips = (P.torque_strip(trace, t_ms, (WIDTH, TORQUE_H), "dark", static=static),
                      sound_strip_clean(bank, snd, t_ms, (WIDTH, SOUND_H), "dark", (t_ms - 1000, t_ms + 400)))
        canvas.paste(strips[0], (0, kh))
        canvas.paste(strips[1], (0, kh + TORQUE_H))
        frames.append(canvas)
    gif, webp, q = save_loop_capped(frames, rec["fps"], "feel-and-sound", ctx.out)
    if q is not None:
        ctx.log(f"webp over the cap at quality 52: re-encoded at quality {q}")
    frames[n // 2].save(work / "feel-and-sound-peek.png")
    ctx.log(f"{n} frames {WIDTH}x{H}: webp {webp.stat().st_size} B, gif {gif.stat().st_size} B")
    return [ctx.produced(webp, FEEL), ctx.produced(gif, FEEL)]


def _save_still(img, path, cap=STILL_PX):
    """PNG with an adaptive 256-colour palette (no dither; the panels are flat colour and text), stepping down
    the palette until the file fits the cap."""
    from PIL import Image
    for colors in (256, 192, 128, 96, 64):
        q = img.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        q.save(path, optimize=True)
        if path.stat().st_size <= cap:
            break
    return path


GALLERY_CELL = (380, 314)          # one panels.feel_gallery panel without its footer line
GALLERY_NOTE = [
    "How each feel pushes back, drawn from",
    "the knob firmware's own feel laws.",
    "",
    "x: knob angle around the current click.",
    "y: commanded voltage as % of the 2.2 V cap;",
    "right axis: model torque (Kt 0.04 N·m/A assumed).",
    "",
    "For makers: volume and brightness use a sine law,",
    "lists, windows and colour temperature a sawtooth",
    "limited to 0.4 A; the end stop stiffens to 3x over",
    "one click and is capped at 2.2 V.",
]


def feel_gallery_grid(traces, theme):
    """The five panels of panels.feel_gallery in a 2 x 3 grid (760 px: the README column, no downscale), the sixth
    cell carrying the law note that feel_gallery puts in its footer (that footer is cropped off each panel)."""
    import panels as P
    from PIL import Image, ImageDraw
    cw, ch = GALLERY_CELL
    order = [k for k in ("detent.value", "detent.dimmer", "detent.list", "detent.coarse", "detent.fine") if k in traces]
    t = P.THEMES[theme]
    img = Image.new("RGB", (2 * cw, 3 * ch), t["bg"])
    for n, key in enumerate(order):
        panel = P.feel_gallery({key: traces[key]}, theme).crop((0, 0, cw, ch))
        img.paste(panel, ((n % 2) * cw, (n // 2) * ch))
    d = ImageDraw.Draw(img)
    x, y = cw + 44, 2 * ch + 24
    for k, line in enumerate(GALLERY_NOTE):
        head = k < 2
        d.text((x, y), line, font=P.font(13 if head else 12), fill=t["text"] if head else t["muted"])
        y += 20
    return img


def scene_feel_gallery(ctx) -> list[Path]:
    work = Path(ctx.work) / "feel"
    traces = {feel: static_trace(ctx, feel, work) for feel in STATIC_SPECS}
    out = []
    for theme, name in (("light", "feel-gallery.png"), ("dark", "feel-gallery-dark.png")):
        img = feel_gallery_grid(traces, theme)
        p = _save_still(img, Path(ctx.out) / name)
        ctx.log(f"{name}: {img.size[0]}x{img.size[1]}, {p.stat().st_size} B")
        out.append(ctx.produced(p, FEEL))
    return out


def scene_sound_bank(ctx) -> list[Path]:
    import panels as P
    work = Path(ctx.work) / "feel"
    bank = sound_bank(ctx, work)
    out = []
    for theme, name in (("light", "sound-bank.png"), ("dark", "sound-bank-dark.png")):
        img = P.sound_bank_sheet(bank, theme)
        p = _save_still(img, Path(ctx.out) / name)
        ctx.log(f"{name}: {img.size[0]}x{img.size[1]}, {p.stat().st_size} B")
        out.append(ctx.produced(p, SOUND))
    return out


SCENES = {
    "feel-and-sound": (FEEL, scene_feel_and_sound),
    "feel-gallery": (FEEL, scene_feel_gallery),
    "sound-bank": (SOUND, scene_sound_bank),
}

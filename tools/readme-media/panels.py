"""Torque and sound panels for the README media, drawn with Pillow only (no matplotlib, no numpy).

Inputs are the two headless drivers' outputs (lcd/haptic_trace.cpp, lcd/sound_dump.cpp; built by build_lcd.py):
  load_trace(path)      a haptic-trace JSON (static: theta -> Uq; dynamic: t -> Uq, theta, pos, asleep, at_limit)
  load_bank(dir)        a sound-dump folder (bank.json + wood/fine/thud/thump.raw, int16 LE at 22050 Hz)

Panels (every one returns an RGB PIL image; `theme` is "dark" or "light", colours chosen to read on GitHub's pages):
  torque_strip(trace, t_ms, size, theme, static=None)
      the torque trace. A dynamic trace: Uq against time, the part up to t_ms bright, a time cursor and the moving
      dot, the rest-asleep spans marked; with `static` (the matching static trace) a left pane shows the teeth-and-
      cliff law with the dot at the shaft's angle. A static trace alone: the law against the shaft angle.
      Left axis "% of the 2.2 V cap", right axis "model torque, mN.m (Kt 0.04 assumed)".
  sound_strip(bank, events, t_ms, size, theme, window_ms=None)
      a waveform ribbon: each event {"t_ms", "sound": "wood"|"fine"|"thud"|"thump", "caption"?} draws its bank
      sample at its time (a 5 ms tock is widened to a legible minimum and marked so), captioned; events after
      t_ms are dim; a time cursor at t_ms.
  feel_gallery(static_traces, theme)       five panels (value, dimmer, list, coarse, fine) from static traces
  sound_bank_sheet(bank, theme)            the four sounds: waveform and a DFT magnitude spectrum, captioned

Everything is fictional-data free by construction: the inputs are physics from the firmware's own laws.
"""
from __future__ import annotations

import cmath
import json
import math
import os
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.dont_write_bytecode = True

CAP_VOLTS = 2.2
PHASE_OHMS = 5.3
KT_ASSUMED = 0.04
MNM_PER_VOLT = KT_ASSUMED / PHASE_OHMS * 1000.0      # 7.547 mN.m per commanded volt (no back-EMF: the static axis)
SOUND_ORDER = ("wood", "fine", "thud", "thump")
SS = 2                                                # supersampling for anti-aliased lines

THEMES = {
    "dark": dict(bg="#0d1117", panel="#161b22", grid="#30363d", axis="#484f58", text="#e6edf3", muted="#8b949e",
                 torque="#f0883e", torque_dim="#6e4a2e", wall="#f85149", wall_fill="#3a1c1f", dot="#58a6ff",
                 cursor="#58a6ff", sleep="#2d4f3a", sound="#3fb950", sound_dim="#2b4a34", spectrum="#a371f7",
                 cap="#8b949e"),
    "light": dict(bg="#ffffff", panel="#f6f8fa", grid="#d0d7de", axis="#8c959f", text="#1f2328", muted="#656d76",
                  torque="#bc4c00", torque_dim="#e8c7b0", wall="#cf222e", wall_fill="#ffe6e6", dot="#0969da",
                  cursor="#0969da", sleep="#dafbe1", sound="#1a7f37", sound_dim="#b7e3c3", spectrum="#8250df",
                  cap="#656d76"),
}

_FONT_CACHE: dict = {}


def _font_path() -> Path | None:
    app = os.environ.get("DESK_DIAL_APP")
    candidates = []
    if app:
        candidates.append(Path(app) / "assets" / "fonts" / "Archivo.ttf")
    candidates.append(Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Archivo.ttf")
    for c in candidates:
        if c.is_file():
            return c
    return None


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = size
    if key not in _FONT_CACHE:
        p = _font_path()
        try:
            _FONT_CACHE[key] = ImageFont.truetype(str(p), size) if p else ImageFont.load_default(size)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


# ------------------------------------------------------------------------------------------------------ inputs
def load_trace(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_bank(folder) -> dict:
    folder = Path(folder)
    bank = json.loads((folder / "bank.json").read_text(encoding="utf-8"))
    samples = {}
    for name in SOUND_ORDER:
        raw = (folder / f"{name}.raw").read_bytes()
        samples[name] = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    bank["samples"] = samples
    return bank


def dft_magnitude(samples, rate, f_max=6000.0, f_step=25.0) -> list[tuple[float, float]]:
    """(frequency Hz, magnitude) for a tiny signal (<= 1103 samples), direct DFT in pure Python."""
    n = len(samples)
    out = []
    f = 0.0
    while f <= f_max:
        w = -2j * math.pi * f / rate
        acc = 0j
        for i, s in enumerate(samples):
            acc += s * cmath.exp(w * i)
        out.append((f, abs(acc) / max(1, n)))
        f += f_step
    return out


# ------------------------------------------------------------------------------------------------------ helpers
class _Canvas:
    """A supersampled RGB drawing surface, downsampled at the end."""

    def __init__(self, size, theme):
        self.w, self.h = size
        self.t = THEMES[theme]
        self.im = Image.new("RGB", (self.w * SS, self.h * SS), self.t["bg"])
        self.d = ImageDraw.Draw(self.im)

    def rect(self, box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        self.d.rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=fill, outline=outline, width=width * SS)

    def line(self, pts, fill, width=1):
        if len(pts) < 2:
            return
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=fill, width=max(1, int(width * SS)), joint="curve")

    def dot(self, xy, r, fill, outline=None):
        x, y = xy
        self.d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=fill, outline=outline, width=SS)

    def text(self, xy, s, size, fill, anchor="la"):
        self.d.text((xy[0] * SS, xy[1] * SS), s, font=font(size * SS), fill=fill, anchor=anchor)

    def text_w(self, s, size):
        return self.d.textlength(s, font=font(size * SS)) / SS

    def vtext(self, xy, s, size, fill):
        """Vertical (rotated 90 degrees counter-clockwise) text centred at xy."""
        f = font(size * SS)
        w = int(self.d.textlength(s, font=f)) + 2 * SS
        h = int(size * SS * 1.4)
        tmp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((SS, 0), s, font=f, fill=fill)
        tmp = tmp.rotate(90, expand=True)
        self.im.paste(tmp, (int(xy[0] * SS - tmp.width / 2), int(xy[1] * SS - tmp.height / 2)), tmp)

    def finish(self) -> Image.Image:
        return self.im.resize((self.w, self.h), Image.LANCZOS)


def _volts_axes(c: _Canvas, box, vmax=CAP_VOLTS, left_label=True, right_label=True, size=11):
    """Draws the grid and both vertical axes of a torque panel: % of cap on the left, mN.m on the right."""
    x0, y0, x1, y1 = box
    t = c.t
    c.rect(box, fill=t["panel"])

    def y_of(v):
        return y1 - (v + vmax) / (2 * vmax) * (y1 - y0)

    for pct in (-100, -50, 0, 50, 100):
        v = pct / 100 * CAP_VOLTS
        if abs(v) > vmax + 1e-9:
            continue
        y = y_of(v)
        c.line([(x0, y), (x1, y)], t["grid"] if pct else t["axis"], 1)
        if left_label:
            c.text((x0 - 6, y), f"{pct:d}", size, t["muted"], anchor="rm")
    for mnm in (-15, -10, -5, 5, 10, 15):
        v = mnm / MNM_PER_VOLT
        if abs(v) > vmax:
            continue
        y = y_of(v)
        if right_label:
            c.text((x1 + 6, y), f"{mnm:d}", size, t["muted"], anchor="lm")
            c.line([(x1, y), (x1 + 3, y)], t["axis"], 1)
    # the cap lines
    for v in (vmax, -vmax):
        c.line([(x0, y_of(v)), (x1, y_of(v))], t["cap"], 1)
    return y_of


def _trace_title(tr) -> str:
    per = tr.get("detents_per_turn", "?")
    return f"{tr.get('feel', '')}   {tr.get('law', '')}   Kp {tr.get('kp_a_per_rad', 0):g} A/rad   {per}/turn"


def _draw_static_curve(c: _Canvas, tr, box, y_of, with_dot_theta=None, label_axis=True, size=11):
    """The static law inside `box`: wall penetrations shaded, the curve, detent centres ticked."""
    x0, y0, x1, y1 = box
    t = c.t
    S = tr["samples"]
    th0, th1 = S[0]["theta_deg"], S[-1]["theta_deg"]

    def x_of(deg):
        return x0 + (deg - th0) / (th1 - th0) * (x1 - x0)

    # wall shading
    wall_runs, run = [], None
    for s in S:
        if s["wall_pen_deg"] > 0:
            run = [s["theta_deg"], s["theta_deg"]] if run is None else [run[0], s["theta_deg"]]
        elif run:
            wall_runs.append(run)
            run = None
    if run:
        wall_runs.append(run)
    for a, b in wall_runs:
        c.rect((x_of(a), y0, x_of(b), y1), fill=t["wall_fill"])
    # detent centres
    w = tr.get("detent_width_deg", 0)
    if w:
        k = math.ceil(th0 / w)
        while k * w <= th1:
            x = x_of(k * w)
            c.line([(x, y0), (x, y1)], t["grid"], 1)
            k += 1
    pts = [(x_of(s["theta_deg"]), y_of(max(-CAP_VOLTS, min(CAP_VOLTS, s["uq_volts"])))) for s in S]
    # the wall part in red, the well part in the torque colour
    seg, col = [], None
    for s, p in zip(S, pts):
        k = t["wall"] if s["wall_pen_deg"] > 0 else t["torque"]
        if col is not None and k != col:
            seg.append(p)
            c.line(seg, col, 2)
            seg = []
        col = k
        seg.append(p)
    c.line(seg, col or t["torque"], 2)
    if label_axis:
        for deg in _nice_ticks(th0, th1, 6):
            x = x_of(deg)
            c.line([(x, y1), (x, y1 + 4)], t["axis"], 1)
            c.text((x, y1 + 6), f"{deg:g}°", size, t["muted"], anchor="ma")
    if with_dot_theta is not None:
        th = max(th0, min(th1, with_dot_theta))
        # nearest sample
        i = min(range(len(S)), key=lambda j: abs(S[j]["theta_deg"] - th))
        c.dot((x_of(th), y_of(max(-CAP_VOLTS, min(CAP_VOLTS, S[i]["uq_volts"])))), 5, t["dot"], outline=t["bg"])
    return x_of


def _nice_ticks(a, b, n):
    span = b - a
    if span <= 0:
        return [a]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((1, 2, 2.5, 5, 10), key=lambda m: abs(m * mag - raw)) * mag
    k0 = math.ceil(a / step)
    out = []
    while k0 * step <= b + 1e-9:
        out.append(round(k0 * step, 6))
        k0 += 1
    return out


# ------------------------------------------------------------------------------------------------------ panels
def torque_strip(trace, t_ms, size, theme, static=None) -> Image.Image:
    c = _Canvas(size, theme)
    t = c.t
    W, H = size
    top, bottom, left, right = 30, 34, 46, 46
    if trace.get("mode") == "static":
        box = (left, top, W - right, H - bottom)
        y_of = _volts_axes(c, box)
        _draw_static_curve(c, trace, box, y_of, with_dot_theta=None)
        c.text((left, 8), _trace_title(trace), 12, t["text"])
        c.text((W - right, 8), "shaft angle from the committed detent", 11, t["muted"], anchor="ra")
        c.vtext((14, (top + H - bottom) / 2), "% of the 2.2 V cap", 11, t["muted"])
        c.vtext((W - 12, (top + H - bottom) / 2), "model torque, mN·m (Kt 0.04 assumed)", 11, t["muted"])
        return c.finish()

    S = trace["samples"]
    t_end = S[-1]["t_ms"]
    t_ms = max(0, min(t_end, t_ms if t_ms is not None else t_end))
    i_now = min(range(len(S)), key=lambda j: abs(S[j]["t_ms"] - t_ms))
    now = S[i_now]
    gap = 54
    if static is not None:
        sw = int((W - left - right - gap) * 0.36)
        sbox = (left, top, left + sw, H - bottom)
        tbox = (left + sw + gap, top, W - right, H - bottom)
    else:
        sbox = None
        tbox = (left, top, W - right, H - bottom)

    # time pane
    x0, y0, x1, y1 = tbox
    y_of = _volts_axes(c, tbox, left_label=sbox is None, right_label=True)

    def x_of(ms):
        return x0 + ms / max(1, t_end) * (x1 - x0)

    # asleep spans
    run = None
    for s in S:
        if s["asleep"]:
            run = [s["t_ms"], s["t_ms"]] if run is None else [run[0], s["t_ms"]]
        elif run:
            c.rect((x_of(run[0]), y1 - 6, x_of(run[1]), y1), fill=t["sleep"])
            run = None
    if run:
        c.rect((x_of(run[0]), y1 - 6, x_of(run[1]), y1), fill=t["sleep"])
    # segments
    for seg in trace.get("segments", []):
        x = x_of(seg["t_ms"])
        c.line([(x, y0), (x, y1)], t["grid"], 1)
        label = {"drive": f"turn {seg.get('omega_rad_s', 0):g} rad/s", "free": "at rest" if seg["t_ms"] == 0 else "let go",
                 "effect": seg.get("token", "effect")}.get(seg["kind"], seg["kind"])
        c.text((x + 3, y0 + 3), label, 10, t["muted"])
    pts = [(x_of(s["t_ms"]), y_of(max(-CAP_VOLTS, min(CAP_VOLTS, s["uq_volts"])))) for s in S]
    c.line(pts, t["torque_dim"], 1.5)
    c.line(pts[: i_now + 1], t["torque"], 2)
    xc = x_of(t_ms)
    c.line([(xc, y0), (xc, y1)], t["cursor"], 1)
    c.dot(pts[i_now], 5, t["dot"], outline=t["bg"])
    for ms in _nice_ticks(0, t_end, 6):
        x = x_of(ms)
        c.line([(x, y1), (x, y1 + 4)], t["axis"], 1)
        c.text((x, y1 + 6), f"{ms / 1000:g} s", 11, t["muted"], anchor="ma")
    state = "asleep" if now["asleep"] else ("at the wall" if now["at_limit"] else "awake")
    c.text((x1, 8), f"t {t_ms / 1000:.2f} s   Uq {now['uq_volts']:+.2f} V   {now['torque_model_mNm']:+.1f} mN·m   "
                    f"pos {now['pos']}   {state}", 11, t["muted"], anchor="ra")
    c.vtext((W - 12, (y0 + y1) / 2), "model torque, mN·m (Kt 0.04 assumed)", 11, t["muted"])
    c.text((left, 8), _trace_title(trace), 12, t["text"])

    if sbox is not None:
        sy_of = _volts_axes(c, sbox, right_label=False)
        _draw_static_curve(c, static, sbox, sy_of, with_dot_theta=now["theta_deg"] - _origin_deg(trace, static, now))
        c.vtext((14, (y0 + y1) / 2), "% of the 2.2 V cap", 11, t["muted"])
        c.text((sbox[0], y1 + 20), "law around one detent, shaft angle", 10, t["muted"])
    else:
        c.vtext((14, (y0 + y1) / 2), "% of the 2.2 V cap", 11, t["muted"])
    return c.finish()


def _origin_deg(trace, static, now) -> float:
    """The static pane is drawn around the committed detent `pos` of the static spec; the dynamic shaft angle is
    relative to the dynamic start detent. Shift by the detent difference so the dot sits on the right tooth."""
    w = static.get("detent_width_deg") or trace.get("detent_width_deg") or 0.0
    return (static.get("pos", 0) - trace.get("pos", 0)) * w


def sound_strip(bank, events, t_ms, size, theme, window_ms=None) -> Image.Image:
    c = _Canvas(size, theme)
    t = c.t
    W, H = size
    rate = bank["rate"]
    left, right, top, bottom = 16, 16, 26, 40
    box = (left, top, W - right, H - bottom)
    x0, y0, x1, y1 = box
    c.rect(box, fill=t["panel"])
    mid = (y0 + y1) / 2
    c.line([(x0, mid), (x1, mid)], t["grid"], 1)
    if window_ms is None:
        last = max([e["t_ms"] + len(bank["samples"][e["sound"]]) / rate * 1000 for e in events] + [t_ms or 0, 1])
        window_ms = (0, last * 1.05)
    w0, w1 = window_ms

    def x_of(ms):
        return x0 + (ms - w0) / max(1e-9, (w1 - w0)) * (x1 - x0)

    min_px = 40
    amp = (y1 - y0) / 2 * 0.9
    for e in events:
        name = e["sound"]
        smp = bank["samples"][name]
        dur = len(smp) / rate * 1000
        xa = x_of(e["t_ms"])
        xb = max(x_of(e["t_ms"] + dur), xa + min_px)
        widened = xb - x_of(e["t_ms"] + dur) > 1
        future = t_ms is not None and e["t_ms"] > t_ms
        col = t["sound_dim"] if future else t["sound"]
        n = len(smp)
        px = max(2, int(xb - xa))
        pts = []
        for k in range(px + 1):
            i0 = int(k / px * (n - 1))
            i1 = max(i0 + 1, int((k + 1) / px * (n - 1)))
            chunk = smp[i0:i1] or [smp[i0]]
            # min/max envelope per pixel column keeps the 5 ms tock legible
            pts.append((xa + k, mid - max(chunk) / 32768 * amp))
            pts.append((xa + k, mid - min(chunk) / 32768 * amp))
        c.line(pts, col, 1)
        cap = e.get("caption") or bank["names"].get(name, name)
        c.text(((xa + xb) / 2, y1 + 6), cap, 11, t["muted"] if future else t["text"], anchor="ma")
        detail = f"{dur:.0f} ms" + (" (widened)" if widened else "")
        c.text(((xa + xb) / 2, y1 + 21), detail, 9, t["muted"], anchor="ma")
    if t_ms is not None:
        xc = x_of(max(w0, min(w1, t_ms)))
        c.line([(xc, y0), (xc, y1)], t["cursor"], 1)
    c.text((left, 6), f"click bank, {rate} Hz mono (audio/cc_sound.h)", 11, t["text"])
    c.text((W - right, 6), f"{(w1 - w0) / 1000:.1f} s window", 10, t["muted"], anchor="ra")
    return c.finish()


def feel_gallery(static_traces, theme) -> Image.Image:
    order = [k for k in ("detent.value", "detent.dimmer", "detent.list", "detent.coarse", "detent.fine") if k in static_traces]
    order += [k for k in static_traces if k not in order]
    pw, ph = 380, 300
    W, H = pw * len(order), ph + 40
    c = _Canvas((W, H), theme)
    t = c.t
    for n, key in enumerate(order):
        tr = static_traces[key]
        ox = n * pw
        box = (ox + 44, 48, ox + pw - 40, 48 + ph - 90)
        y_of = _volts_axes(c, box, left_label=True, right_label=True, size=10)
        _draw_static_curve(c, tr, box, y_of, size=10)
        c.text((ox + 44, 10), key, 14, t["text"])
        c.text((ox + 44, 28), f"{tr['law']}   Kp {tr['kp_a_per_rad']:g} A/rad   Kd {tr['kd_a_per_rad_s']:g}   "
                              f"{tr['detents_per_turn']}/turn ({tr['detent_width_deg']:.1f}°)", 10, t["muted"])
        peak = tr["summary"]["well_peak_volts"]
        c.text((ox + 44, box[3] + 24), f"well ±{peak:.2f} V ({peak / CAP_VOLTS * 100:.0f} % of cap, "
                                       f"{peak * MNM_PER_VOLT:.1f} mN·m)   wall to {tr['summary']['max_abs_volts']:.1f} V",
               10, t["text"])
        c.text((ox + 44, box[3] + 40), "pos {pos} of {lo}..{hi}; shaded: past the end, the wall".format(**tr), 10, t["muted"])
        c.vtext((ox + 12, (box[1] + box[3]) / 2), "% of the 2.2 V cap", 10, t["muted"])
        c.vtext((ox + pw - 10, (box[1] + box[3]) / 2), "mN·m (Kt 0.04 assumed)", 10, t["muted"])
    c.text((W - 16, H - 16), "firmware feel laws cc_haptic_fx.h: SINE A sin(2πe/w), A = Kp·w/2; SAW Kp·e, limited to 0.4 A (2.12 V); "
                             "wall Kp→3Kp over one pitch, capped at 2.2 V", 10, t["muted"], anchor="rm")
    return c.finish()


def sound_bank_sheet(bank, theme) -> Image.Image:
    rate = bank["rate"]
    rows = SOUND_ORDER
    rh, W = 150, 1100
    H = 44 + rh * len(rows) + 30
    c = _Canvas((W, H), theme)
    t = c.t
    c.text((16, 10), f"the click bank: four sounds rendered once at boot (audio/cc_sound.h, {rate} Hz, 16-bit mono)", 13, t["text"])
    c.text((W - 16, 12), "left: waveform (full scale ±32768)   right: DFT magnitude, 0..6 kHz, dB", 10, t["muted"], anchor="ra")
    for r, name in enumerate(rows):
        smp = bank["samples"][name]
        n = len(smp)
        dur = n / rate * 1000
        y0 = 44 + r * rh
        label = bank["names"].get(name, name)
        c.text((16, y0 + 8), f"{label}", 14, t["text"])
        c.text((16, y0 + 28), f"{name.upper()}  {n} samples  {dur:.0f} ms  peak {max(abs(v) for v in smp)}", 10, t["muted"])
        c.text((16, y0 + 44), _sound_blurb(name), 10, t["muted"])
        # waveform
        wb = (250, y0 + 10, 700, y0 + rh - 22)
        c.rect(wb, fill=t["panel"])
        mid = (wb[1] + wb[3]) / 2
        c.line([(wb[0], mid), (wb[2], mid)], t["grid"], 1)
        amp = (wb[3] - wb[1]) / 2 * 0.92
        px = wb[2] - wb[0]
        pts = []
        for k in range(px + 1):
            i0 = int(k / px * (n - 1))
            i1 = max(i0 + 1, int((k + 1) / px * (n - 1)))
            chunk = smp[i0:i1] or [smp[i0]]
            pts.append((wb[0] + k, mid - max(chunk) / 32768 * amp))
            pts.append((wb[0] + k, mid - min(chunk) / 32768 * amp))
        c.line(pts, t["sound"], 1)
        for ms in _nice_ticks(0, dur, 5):
            x = wb[0] + ms / dur * px
            c.line([(x, wb[3]), (x, wb[3] + 3)], t["axis"], 1)
            c.text((x, wb[3] + 5), f"{ms:g} ms", 9, t["muted"], anchor="ma")
        # spectrum
        sb = (760, y0 + 10, W - 40, y0 + rh - 22)
        c.rect(sb, fill=t["panel"])
        spec = dft_magnitude(smp, rate)
        top_mag = max(m for _, m in spec) or 1.0
        floor_db = -50.0
        pts = []
        for f, m in spec:
            db = 20 * math.log10(max(m, 1e-9) / top_mag)
            db = max(floor_db, db)
            x = sb[0] + f / 6000 * (sb[2] - sb[0])
            y = sb[3] - (db - floor_db) / -floor_db * (sb[3] - sb[1])
            pts.append((x, y))
        c.line(pts, t["spectrum"], 1.5)
        for khz in range(0, 7):
            x = sb[0] + khz / 6 * (sb[2] - sb[0])
            c.line([(x, sb[3]), (x, sb[3] + 3)], t["axis"], 1)
            c.text((x, sb[3] + 5), f"{khz} kHz", 9, t["muted"], anchor="ma")
        peak_f = max(spec, key=lambda p: p[1])[0]
        c.text((16, y0 + 60), f"strongest bin {peak_f:.0f} Hz", 10, t["muted"])
    c.text((16, H - 18), "pure-Python DFT at 25 Hz steps; levels are the bank at full scale, before each cue's level and the master volume",
           9, t["muted"])
    return c.finish()


def _sound_blurb(name) -> str:
    return {
        "wood": "2400 Hz chirp from 1.6x down, decay 1080 /s",
        "fine": "the tock at twice the pitch (4800 Hz)",
        "thud": "1800 Hz tick over a 330 Hz body, clipped",
        "thump": "110 Hz harmonics 2..6, 1.2 kHz attack",
    }.get(name, "")

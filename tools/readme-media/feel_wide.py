"""feel-wide.webp: the README's Feel and sound picture, 1280 x 720 (shown at 880), one loop of the volume climb.

Left, the knob (the music-volume recording through recording.knob_frames, the shared KnobDevice look). Right, two
strips that draw themselves left to right behind a cursor on the same clock:
  * "What you feel": the motor's output (panel_scenes.synth_trace: the firmware's static value law read at the
    event-derived shaft angle, flat once the rest gate puts the motor to sleep) as one bold line;
  * "What you hear": one mark per sound the knob's speaker plays (a tock per click, a thud per refused push at
    the wall), its height the sound's peak in the firmware's own bank (sound-dump).
A few large words fade in as their moment passes: clicks, wall, motor off; tock, thud. No axes and no small print:
the measured version, with its units, stays on docs/features/feel-and-sound.md (feel-and-sound.webp).

Only the area around the cursor changes from frame to frame, so the loop stays small.
Registry contract: SCENES = {"feel-wide": (FEEL, fn)}.
"""
from __future__ import annotations

from pathlib import Path

FEEL = "firmware feel laws + knob model"
W, H = 1280, 720
BG = (13, 14, 17)
INK = (245, 245, 247)
QUIET = (134, 134, 139)
ORANGE = (255, 132, 36)
KNOB_SCALE = 1.1                       # the device 418 x 484, left third
PANEL = (520, 1230)                    # x range of the strips
FEEL_BOX = (150, 360)                  # y range of the torque line
HEAR_BOX = (520, 630)                  # y range of the sound marks (baseline at the bottom)
HOLD_MS = 700                          # the finished picture holds this long before the loop restarts
WEBP_CAP = 1_200_000


def _x(t_ms, span_ms):
    return PANEL[0] + (PANEL[1] - PANEL[0]) * t_ms / span_ms


def _word(app, work, text, px, weight, colour):
    """One kerned word as an RGBA image (headlines.typeset), its baseline at 0.8 * height."""
    from PIL import Image, ImageDraw
    import headlines as T
    img = Image.new("RGBA", (int(px * len(text) * 0.75) + 20, int(px * 1.3)), (0, 0, 0, 0))
    w = T.typeset(ImageDraw.Draw(img), app, work, text, px, weight, (4, int(px * 1.0)), colour + (255,), tracking=-0.01)
    return img.crop((0, 0, int(w) + 10, img.height))


def render(ctx):
    import panel_scenes as PS
    import recording
    import rec_scenes
    from PIL import Image, ImageDraw

    work = Path(ctx.work) / "feel-wide"
    work.mkdir(parents=True, exist_ok=True)
    rec = recording.load(rec_scenes.recording_path(ctx.work, "music-volume", ctx.log))
    t0, t1 = PS.WINDOW
    span = t1 - t0
    knob = recording.knob_frames(rec, ctx.knob_anim, work, scale=KNOB_SCALE, t_start=t0, t_end=t1, tag="-feelwide")
    events = PS.strip_events(rec, t0, t1)
    start = PS.start_position(rec, t0)
    end = start + sum(d for _, k, d in events if k == "detent")
    static = PS.static_trace(ctx, "detent.value", work)
    trace = PS.synth_trace(static, events, 0, span, start, end)
    bank = PS.sound_bank(ctx, work)

    # ---- the finished picture, drawn once (4x supersampled lines)
    ss = 4
    line = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(line)
    S = trace["samples"]
    peak = max(abs(s["uq_volts"]) for s in S) or 1.0
    mid, amp = (FEEL_BOX[0] + FEEL_BOX[1]) / 2, (FEEL_BOX[1] - FEEL_BOX[0]) / 2
    pts = [(_x(s["t_ms"], span) * ss, (mid - s["uq_volts"] / peak * amp) * ss) for s in S]
    d.line(pts, fill=ORANGE + (255,), width=3 * ss, joint="curve")
    # the sounds: tock per detent, thud per refused push
    peaks = {}
    for name in ("wood", "thud"):
        smp = bank["samples"][name]
        peaks[name] = max(abs(v) for v in smp) or 1
    top = max(peaks.values())
    sounds = [(t, "wood") for t, k, _ in events if k == "detent"] + [(t, "thud") for t, k, _ in events if k == "lim"]
    for t, name in sounds:
        x = _x(t, span) * ss
        h = (HEAR_BOX[1] - HEAR_BOX[0]) * (0.35 + 0.65 * peaks[name] / top)
        colour = INK if name == "wood" else ORANGE
        half = 2 if name == "wood" else 5                  # a thud is a heavier mark than a tock
        d.rounded_rectangle((x - half * ss, (HEAR_BOX[1] - h) * ss, x + half * ss, HEAR_BOX[1] * ss), radius=2 * ss,
                            fill=colour + (255,))
    line = line.resize((W, H), Image.Resampling.LANCZOS)

    # ---- the static layer: labels and the faint baselines
    base = Image.new("RGB", (W, H), BG)
    bd = ImageDraw.Draw(base)
    bd.line((PANEL[0], mid, PANEL[1], mid), fill=(38, 39, 44), width=1)
    bd.line((PANEL[0], HEAR_BOX[1] + 1, PANEL[1], HEAR_BOX[1] + 1), fill=(38, 39, 44), width=1)
    for text, y in (("What you feel", FEEL_BOX[0] - 62), ("What you hear", HEAR_BOX[0] - 66)):
        img = _word(ctx.app, work, text, 34, 600, QUIET)
        base.paste(img, (PANEL[0], y), img)

    # ---- the words, each at its moment
    lims = sorted(t for t, k, _ in events if k == "lim")
    last_input = max([t for t, _k, _p in events] or [0])
    rest = next((s["t_ms"] for s in S if s["asleep"] and s["t_ms"] > last_input), None)
    climb_mid = (events[0][0] + (lims[0] if lims else span)) / 2 if events else span / 3
    words = [("clicks", climb_mid, FEEL_BOX[1] + 4, INK), ("tock", climb_mid, HEAR_BOX[1] + 8, INK)]
    if lims:
        words += [("wall", lims[0], FEEL_BOX[1] + 4, ORANGE), ("thud", lims[0], HEAR_BOX[1] + 8, ORANGE)]
    if rest is not None:
        words.append(("motor off", span, int(mid) - 62, QUIET))      # above the flat line, at the right end
    word_imgs = [(t, y, _word(ctx.app, work, text, 40, 700, colour)) for text, t, y, colour in words]
    if rest is not None:                     # "motor off" sits at the right end but appears when the rest begins
        word_imgs = [(rest + 120 if t == span else t, y, img) for t, y, img in word_imgs]
        word_x = {id(img): span for t, y, img in word_imgs if y == int(mid) - 62}
    else:
        word_x = {}

    # ---- frames
    fps = rec["fps"]
    n = len(knob)
    kw, kh = knob[0].size
    kx, ky = 40 + (440 - kw) // 2, (H - kh) // 2
    frames = []
    hold = round(HOLD_MS * fps / 1000)
    for k in range(n + hold):
        kk = min(k, n - 1)
        t_ms = min(span, kk * 1000 / fps)
        img = base.copy()
        img.paste(knob[kk], (kx, ky))
        cx = int(round(_x(t_ms, span)))
        img.paste(line.crop((0, 0, cx, H)), (0, 0), line.crop((0, 0, cx, H)))
        for t, y, wimg in word_imgs:
            if t_ms >= t:
                a = min(1.0, (t_ms - t) / 250)
                x = int(_x(word_x.get(id(wimg), t), span) - wimg.width / 2)
                x = max(PANEL[0], min(PANEL[1] - wimg.width, x))
                mask = wimg.getchannel("A").point(lambda v, a=a: int(v * a))
                img.paste(wimg, (x, y), mask)
        if k < n:
            ImageDraw.Draw(img).line((cx, FEEL_BOX[0] - 10, cx, HEAR_BOX[1]), fill=(90, 92, 98), width=2)
        frames.append(img)
    return frames, fps


def scene(ctx) -> list[Path]:
    import recording
    import knob_scenes as K
    frames, fps = render(ctx)
    frames = K.rounded(frames, 36)               # 24 CSS px at the 880 px display width
    frames[len(frames) * 2 // 3].save(Path(ctx.work) / "feel-wide-peek.png")
    gif, webp = recording.save_loop(frames, fps, "feel-wide", ctx.out, webp_cap=WEBP_CAP)
    ctx.log(f"feel-wide: {len(frames)} frames {W}x{H}, webp {webp.stat().st_size} B, gif {gif.stat().st_size} B")
    return [ctx.produced(webp, FEEL), ctx.produced(gif, FEEL)]


SCENES = {"feel-wide": (FEEL, scene)}

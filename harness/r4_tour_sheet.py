"""r4 motion tour sheet (design_handoff_nano_d_r4 README section 8, "use it as a visual test script"): one row per
tour step of the harness timeline `r4-tour` (main.cpp: the README's steps on the r3 screens, with the input moments
driven through cc_display_input / cc_display_wall as lcd_thread does), the knob LCD exactly as the firmware renders it
at +0 / +60 / +120 / +240 / +420 ms after the step, each masked to the round glass; plus a strip of the r4 moments
timeline (M1-M15) with the same captures. Below each row: what the step should show (the README column). A last
section draws the r4 LED moments (README 3.3 / 3.4, ALIVE.md 16) from the LED engine's float64 twin
(control_center.alive_lights, byte-checked against cc_alive.cpp by alive_tests.py): the 60-LED ring and the four button
LEDs as section 9 bytes (drive 150, dither off) for the wall glow, the 480 ms deny glow, the M12 domain-swap sweep and
the 50 ms easing of a volume jump.

Usage: .venv\\Scripts\\python.exe harness\\r4_tour_sheet.py <render-dir> [out.png]
       (default out: app/design-reference/r4-motion-tour-sheet.png)
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent
companion = root.parent / 'app'
FONT = companion / 'assets' / 'fonts' / 'Montserrat.ttf'
OUT = companion / 'design-reference' / 'r4-motion-tour-sheet.png'
OFFSETS = (0, 60, 120, 240, 420)
THUMB, GAP, LABEL_W, ROW_H = 150, 10, 330, 150 + 26
BG, FG, DIM = (22, 23, 25), (230, 230, 230), (150, 150, 150)

# What each tour step should show (README section 8's "Shows" column, per step label prefix).
SHOWS = {
    '0.6': 'M2, soft steps, arc flow', '2.6': 'M1, crumb', '3.5': 'M1, crumb (M15)', '4.4': 'M4, list clicks',
    '4.9': 'M4 back', '5.7': 'M13, end LEDs, wall', '7.0': 'M10, hold.tension', '8.05': 'M8, thump, M6',
    '9.2': 'tick, feel.fade', '10.2': 'tick, feel.fade', '11.2': 'M1 (reverse)', '12.1': 'M9, M8, tick',
    '13.3': 'M9, M8, tick', '14.4': 'M4 / M1', '15.3': 'M4, nudge', '16.3': 'M5', '17.4': 'hold arc (LEDs), M7',
    '18.0': 'M1 back, thump', '18.8': 'M10', '19.85': 'M12 (LED sweep), thump, feel.fade to dimmer',
    '20.6': 'heavier steps, M2', '21.3': 'M2, at 100 %', '21.8': 'M13', '23.6': 'M12', '25.2': 'coarse clicks, M1', '26.0': 'M4',
    '26.8': 'nudge, M7', '27.9': 'tick',
}


def round_mask(size):
    m = Image.new('L', (size * 4, size * 4), 0)
    ImageDraw.Draw(m).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def rows_of(tl, out_dir):
    steps = tl['steps']
    rows = []
    for k, s in enumerate(steps, start=1):     # the render index lists the steps after the baseline (step 1 on)
        caps = {c['offset']: c for c in tl['captures'] if c['step'] == k}
        files = [out_dir / caps[o]['file'] if o in caps else None for o in OFFSETS]
        rows.append((s['label'], s.get('render', {}), files))
    return rows


def draw_rows(rows, title, font, small):
    mask = round_mask(THUMB)
    width = LABEL_W + len(OFFSETS) * (THUMB + GAP) + GAP
    height = 60 + len(rows) * (ROW_H + GAP)
    sheet = Image.new('RGB', (width, height), BG)
    d = ImageDraw.Draw(sheet)
    d.text((GAP, 14), title, fill=FG, font=font)
    for i, o in enumerate(OFFSETS):
        d.text((LABEL_W + i * (THUMB + GAP) + THUMB // 2 - 14, 40), f'+{o} ms', fill=DIM, font=small)
    for r, (label, render, files) in enumerate(rows):
        y = 60 + r * (ROW_H + GAP)
        key = label.split(' ')[0]
        d.text((GAP, y + 10), label, fill=FG, font=small)
        if key in SHOWS:
            d.text((GAP, y + 30), 'shows: ' + SHOWS[key], fill=DIM, font=small)
        facts = [f'{name} {render[k]}' for name, k in (('slide', 'last_slide'), ('glide', 'glides'), ('pop', 'pops'),
                                                          ('morph', 'morphs'), ('fill', 'hold_fills'), ('press', 'presses'),
                                                          ('wall', 'wall_bounces'), ('landing', 'landings'))
                 if render.get(k)]
        if facts:
            d.text((GAP, y + 50), ', '.join(facts), fill=DIM, font=small)
        for i, f in enumerate(files):
            if f is None or not Path(f).exists():
                continue
            im = Image.open(f).convert('RGB').resize((THUMB, THUMB), Image.LANCZOS)
            sheet.paste(im, (LABEL_W + i * (THUMB + GAP), y), mask)
    return sheet


# ------------------------------------------------------------------------------------------------ LED moments
LED_OFFSETS = (0, 45, 90, 250, 435, 600)


def _led_engine():
    sys.path.insert(0, str(companion))
    sys.path.insert(0, str(companion / 'tests' / 'tools'))
    from control_center import alive_lights as al            # noqa: E402
    import make_alive_sequences as mas                      # noqa: E402
    return al, mas


def led_scripts():
    """(label, shows, [(offset, ring bytes, button bytes)]) per LED moment, rendered every 5 ms by the twin."""
    al, mas = _led_engine()
    out = []

    def run(label, shows, setup, event, frame_after=None, lead=0):
        """Settle on the setup frame until t - lead (lead: the event renders its own run-up), then the event."""
        eng = al.AliveLights(0)
        frame = setup(eng)
        t = 3000
        for now in range(0, t - lead + 1, 16):
            eng.render(now, frame[0], *frame[1])
        event(eng, t)
        after = frame_after or frame
        samples = []
        for now in range(t + 5, t + max(LED_OFFSETS) + 6, 5):
            ring, buttons = eng.render(now, after[0], *after[1])
            off = now - t - 5
            if off in LED_OFFSETS:
                lit_r, lit_b = eng.lit_masks()
                rb, bb = mas.reference_output(ring, buttons, mas.DEFAULT_DRIVE, lit_r, lit_b)
                samples.append((off, rb, bb))
        out.append((label, shows, samples))

    v100 = (mas.wire(mas.home(100)), (100, 100))
    run('wall: turn past 100 %', 'M13 end LEDs: the 5 at the arc end warm white L0.9, rise 90 / fall 420 ms',
        lambda e: (e.claim(0), v100)[1], lambda e, t: e.limit(t, 1))
    refused = mas.Raw(dict(mas.wire(mas.home(40)), feedback={"kind": "err", "seq": 2, "moment": "refused"}))
    v40 = (mas.wire(mas.home(40)), (40, 100))
    run('deny: an unavailable press', 'bottom LEDs 26-34 red 255,60,40 L0.9 for 480 ms, eased (a bloom, no flash)',
        lambda e: (e.claim(0), v40)[1], lambda e, t: None, (refused.frame, (40, 100)))
    held = mas.Raw(dict(mas.wire(mas.home(40)), holdMarker=True))
    landed = mas.Raw(dict(held.frame, feedback={"kind": "ok", "seq": 3}))
    lights = mas.Raw(dict(mas.wire(mas.lights5(60, 3000)), holdMarker=True, feedback={"kind": "ok", "seq": 3}))

    def hold4(e, t):                                        # button 4 held 1.1 s: matured, the landing window open
        e.press(t - 1100, 3)
        for now in range(t - 1100, t, 16):
            e.render(now, held.frame, 40, 100)
    run('M12: hold 4 lands on Home', 'the ring sweeps to the new domain from 12 o\'clock, LED i after i x 8.7 ms',
        lambda e: (e.claim(0), (held.frame, (40, 100)))[1], hold4, (lights.frame, (None, None)), lead=1116)
    v80 = (mas.wire(mas.home(80)), (80, 100))
    run('easing: volume 40 -> 80 in one frame', 'every LED eases (tau 50 ms): nothing steps',
        lambda e: (e.claim(0), v40)[1], lambda e, t: e.detent(t, 40), v80)
    return out


def ring_image(ring, buttons, size=THUMB):
    """The 60 LEDs on a circle (segment 0 at 12 o'clock, clockwise) and the four buttons below, gamma-lifted for
    the screen (the bytes are LED drive levels, drive 150 of 255)."""
    im = Image.new('RGB', (size, size), (10, 10, 12))
    d = ImageDraw.Draw(im)
    cx, cy, r = size / 2, size / 2 - 10, size / 2 - 22

    def lift(v):
        return tuple(min(255, int(255 * ((c / 150) ** 0.45))) if c else 26 for c in ((v >> 16) & 255, (v >> 8) & 255, v & 255))
    import math
    for i, v in enumerate(ring):
        a = math.radians(i * 6 - 90)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=lift(v))
    for j, v in enumerate(buttons):
        x = size / 2 - 42 + j * 28
        d.rectangle((x - 9, size - 16, x + 9, size - 10), fill=lift(v))
    return im


def draw_leds(font, small):
    rows = led_scripts()
    width = LABEL_W + len(LED_OFFSETS) * (THUMB + GAP) + GAP
    height = 60 + len(rows) * (ROW_H + GAP)
    sheet = Image.new('RGB', (width, height), BG)
    d = ImageDraw.Draw(sheet)
    d.text((GAP, 14), 'r4 LED moments (README 3.3 / 3.4; ALIVE.md 16): section 9 bytes of the engine twin', fill=FG, font=font)
    for i, o in enumerate(LED_OFFSETS):
        d.text((LABEL_W + i * (THUMB + GAP) + THUMB // 2 - 14, 40), f'+{o} ms', fill=DIM, font=small)
    for r, (label, shows, samples) in enumerate(rows):
        y = 60 + r * (ROW_H + GAP)
        d.text((GAP, y + 10), label, fill=FG, font=small)
        d.text((GAP, y + 30), 'shows: ' + shows, fill=DIM, font=small)
        for i, (_off, rb, bb) in enumerate(samples):
            sheet.paste(ring_image(rb, bb), (LABEL_W + i * (THUMB + GAP), y))
    return sheet


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    out_dir = Path(argv[0])
    target = Path(argv[1]) if len(argv) > 1 else OUT
    index = json.loads((out_dir / 'render-index.json').read_text(encoding='utf-8'))
    timelines = {t['id']: t for t in index['timelines']}
    for tl in timelines.values():                   # capture file names are relative to the render dir
        for c in tl['captures']:
            c['file'] = c.get('file') or c.get('png') or ''
    font = ImageFont.truetype(str(FONT), 20)
    small = ImageFont.truetype(str(FONT), 13)
    tour = draw_rows(rows_of(timelines['r4-tour'], out_dir),
                     'r4 motion tour (README 8) on the knob LCD: the firmware renderer (cc_display.cpp) in the LVGL harness', font, small)
    moments = draw_rows(rows_of(timelines['r4-moments'], out_dir), 'r4 moments M1-M15 (harness timeline r4-moments)', font, small)
    leds = draw_leds(font, small)
    sheet = Image.new('RGB', (max(tour.width, moments.width, leds.width), tour.height + moments.height + leds.height), BG)
    sheet.paste(tour, (0, 0))
    sheet.paste(moments, (0, tour.height))
    sheet.paste(leds, (0, tour.height + moments.height))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    print(f'wrote {target} ({sheet.width} x {sheet.height})')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

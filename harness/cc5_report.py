"""cc5 Stage 6 LCD regression checks over the LVGL harness renders.

Reads <out>/render-index.json (written by main.cpp through build.py), the case
PNGs and the design fixtures (tests/fixtures/cc5_frames.json), and writes
<out>/regression-checks.json plus <out>/contact-sheet.png (every case render)
and <out>/contact-sheet-timelines.png (the timeline captures).

Checks (contract v4 section 6, Knob Face.dc.html, plan "Decided defaults"):
  parse            every fixture case parsed by the firmware parser, none rejected
  safe_circle      text/icon ink (art-less twin renders) inside r104 around (120,120);
                   page-1 "RECENTLY ADDED" may use a documented <= 2 px tolerance
  heading_chain    headings verbatim when they fit; pages > 1 follow the fallback
                   chain (drop tracking, then "RECENT · P{n}")
  verbatim_text    every drawn line is the wire text (or its prefix + U+2026)
  ellipsis_honest  no label ends in U+2026 unless its full wire text cannot fit its
                   lines (harness oracle: box width clamped to the r104 chord, breaks
                   at spaces, a word wider than a line breaks by characters); a text
                   that fits is shown whole, one that does not is a prefix + U+2026
  label_bounds     no drawn line is wider than its label box
  footer_centres   20 px icons centred at x 56/99/141/184, rows 154..173
  icon_recolour    A8 icons drawn in their tone ink (LVGL 9.0 A8 recolour)
  idle_centres     26 px idle icons centred at x 51/97/143/189, top y 100; words under them
  digit_baseline   48 px digits and 22 px '%' share a baseline within 1 px, pair centred
  css_baselines    label baselines on the design's CSS baselines (+-1 px), the Windows
                   tile initial included (CSS 16/16 line centred in the 32 px tile: 64)
  windows_meta     Windows title line 2 ink ends above the meta ink
  status_home_only list/tracks/windows layouts draw meta, never the status line
  art_rules        art shown only where the contract allows it; artDim -> image_opa 112
  heap             peak LVGL heap <= 50 % of LV_MEM_SIZE (80 KB) (fragmentation reported)
  heartbeat        an identical frame starts no animation, sets no text, needs no redraw
  slides           slide direction per step: none on external volume / Tracks re-centre,
                   deeper screens from the right (+20), back from the left (-20)
  motion           volume reveal/hide, idle entry/exit stagger, screen change, late art
                   and art fades at the design's key times
  latency          non-animated changes are presented at once (lv_refr_now)

artwork2 (1.0.0-cc5.3, ARTWORK2.md section 7; harness-only cases and timelines):
  jpeg_glue        covers were decoded by the firmware's cc_jpeg.cpp through tjpgd_shim
                   (not the harness stand-in), and the binary was built from the real
                   NanoD_RatchetH1/src and lcd-preview/tjpgd_shim (paths recorded by main.cpp)
  a2_cover_exact   tolerance-free: every drawn 240 px cover pixel (cases, a swap back to the
                   back buffer, a cover decoded during a screen change, a cover after a
                   failed decode) equals cc_jpeg_decode_240's output for its key, mixed
                   over black at image_opa 112 exactly like LVGL ((opa + 4) >> 3) for artDim
  a2_cover_fullres 240 px JPEG covers on nowPlaying/recent/tracks, dim and not: the art
                   pixels (where the art-less twin is black) vs a Pillow decode rounded to
                   RGB565 (mixed at image_opa 112 like LVGL for artDim): luma PSNR >= 40 dB
                   and above a 120 px round trip's (the 1 px detail cover's round trip stays
                   below 30 dB), RGB PSNR >= 30 dB (channel order and placement); decoded,
                   never upscaled; the store pins the key
  a2_cover_none    a committed cover that cannot be decoded and a cover not committed yet
                   draw no art and hold no pin
  a2_icon          app icons fill the tile at (104,42) 32x32 with the payload's exact
                   pixels (letter hidden, tile background transparent); the closed entry
                   keeps the tile group at opa 89; the store pins the icon key
  a2_letter        every letter tile (no icon) shows the subtitle's first code point,
                   ASCII a-z upper-cased, on #444; no tile for an empty subtitle
  a2_media_pins    after every case render the store's displayed keys are exactly the
                   cover and icon drawn from it (none for v1 art, letter tiles, no art)
  a2_heartbeat     identical frames with a JPEG cover or an app icon: no decode, no icon
                   copy, no buffer swap (plus the heartbeat check's rules)
  a2_timelines     icon committed after its frame appears at once (no animation); a JPEG
                   committed after its frame fades in late (60 + 420 ms); front/back swap
                   and back-buffer reuse are instant; a decode failure shows no art, is
                   not retried on identical frames, only after the key changed; on
                   Windows the cover pin is released; a commit of other keys (prefetch)
                   leaves the pins as they were; a screen change onto a cover decoded
                   with a simulated 150 ms decode still starts its slide and fade at
                   their beginning (the decode runs before any animation starts)
  a2_handback      native handback (cc_display_release_media) releases the cover and
                   icon pins; the return re-pins without decoding; after the store
                   evicted the key the front buffer's exact pixels are still drawn
                   (displayed -1) while an icon needs the store (letter tile)
  a2_one_buffer    <out>/one-buffer (main.cpp --one-buffer, cc_display_create(front,
                   nullptr)): covers decoded in place and exact, no back-buffer reuse, a
                   failed in-place decode hides the art and the next key is decoded
                   again, identical frames stay inert, the handback return decodes nothing

Evidence from before this harness (no artwork2 / source-path / handback data in
render-index.json) fails every artwork2 check instead of stopping the report.

Usage: .venv python harness/cc5_report.py [out-dir]
Exit status 1 when any check fails.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
COMPANION = ROOT.parent / 'app'
FRAMES = COMPANION / 'tests' / 'fixtures' / 'cc5_frames.json'
FONT = COMPANION / 'assets' / 'fonts' / 'Montserrat.ttf'

SAFE_R = 104
HEADING_TOLERANCE_R = 106        # plan "Labels": page-1 "RECENTLY ADDED" may use <= 2 px
INK = 12                         # max channel above this counts as ink (RGB565 step is 8)
FOOTER_CX = [56, 99, 141, 184]
IDLE_CX = [51, 97, 143, 189]
LAYOUTS = ['nowPlaying', 'volume', 'idle', 'recent', 'tracks', 'windows', 'notice']
ELLIPSIS = '…'
# CSS line boxes of Knob Face.dc.html -> rounded CSS baseline (top + offset, Montserrat hhea).
CSS_BASELINES = {
    'heading': 43, 'home.title': 81, 'home.artist': 128, 'status': 145, 'volume.caption': 66,
    'volume.digits': 116, 'volume.percent': 116, 'list.title': 73, 'list.subtitle': 120,
    'list.meta': 138, 'tracks.title': 75, 'tracks.subtitle': 124, 'tracks.meta': 141,
    'windows.app': 94, 'windows.title': 116, 'windows.meta': 150, 'idle.word': 145,
    # Tile initial: 16px/16px line centred in the 32 px tile at y42 -> top 50, baseline 50 + 13.74.
    'windows.letter': 64,
    'notice.heading': 43, 'notice.title': 73, 'notice.subtitle': 120,
}


class Checks:
    def __init__(self):
        self.results = {}

    def add(self, name, passed, summary, failures=(), **details):
        entry = {'pass': bool(passed), 'summary': summary}
        if failures:
            entry['failures'] = list(failures)[:60]
            entry['failure_count'] = len(list(failures))
        entry.update(details)
        self.results[name] = entry
        print(f'{"PASS" if passed else "FAIL"} {name}: {summary}')
        for failure in list(failures)[:8]:
            print(f'      {failure}')


def visible(obj):
    return not obj['hidden'] and obj['opa_eff'] > 0


def objects(layout, role, only_visible=True):
    return [o for o in layout if o['role'] == role and (visible(o) or not only_visible)]


def load_rgb(path: Path):
    return Image.open(path).convert('RGB').tobytes()


def ring_indices():
    outside, tolerance = [], []
    for y in range(240):
        for x in range(240):
            r = math.hypot(x + 0.5 - 120, y + 0.5 - 120)
            if r > HEADING_TOLERANCE_R:
                outside.append((x, y, r))
            elif r > SAFE_R:
                tolerance.append((x, y, r))
    return outside, tolerance


def ink_at(data, x, y):
    i = (y * 240 + x) * 3
    return max(data[i], data[i + 1], data[i + 2])


def joined(lines):
    return [' '.join(lines), ''.join(lines)]


def verbatim(shown_lines, source):
    if not shown_lines:
        return source == ''
    for candidate in joined(shown_lines):
        if candidate == source:
            return True
        if candidate.endswith(ELLIPSIS):
            stem = candidate[:-1].rstrip()
            if source.startswith(stem) and len(stem) < len(source):
                return True
    return False


LABEL_SOURCES = {
    'home.title': 'title', 'home.artist': 'subtitle', 'status': 'status', 'list.title': 'title',
    'list.subtitle': 'subtitle', 'list.meta': 'meta', 'tracks.title': 'title', 'tracks.subtitle': 'subtitle',
    'tracks.meta': 'meta', 'windows.app': 'subtitle', 'windows.title': 'title', 'windows.meta': 'meta',
}

# Harness-only two-line fitting cases (main.cpp SYNTHETIC): case -> (role, full text fits two lines).
FIT_CASES = {
    'syn-win-handoff': ('windows.title', True),
    'syn-win-diag-log': ('windows.title', True),
    'syn-win-supercal': ('windows.title', True),
    'syn-win-late-word': ('windows.title', True),
    'syn-win-overflow': ('windows.title', False),
    'syn-win-words-overflow': ('windows.title', False),
    'syn-recent-long-word': ('list.title', True),
}


def wire_source(frame, role, ordinal):
    """The full wire text behind a label (None for labels without one)."""
    if role in LABEL_SOURCES:
        return frame.get(LABEL_SOURCES[role], '')
    if role == 'volume.caption':
        return frame.get('volumeCaption') or frame.get('title', '')
    if role == 'idle.word':
        buttons = frame.get('buttons') or []
        return buttons[ordinal].get('label', '') if ordinal < len(buttons) else ''
    return None


def main(argv) -> int:
    out = Path(argv[1]) if len(argv) > 1 else ROOT / 'cc5-handoff'
    index = json.loads((out / 'render-index.json').read_text(encoding='utf-8'))
    fixture = json.loads(FRAMES.read_text(encoding='utf-8'))
    frames = {c['id']: c['frame'] for c in fixture['cases']}
    checks = Checks()
    cases = index['cases']
    by_id = {c['id']: c for c in cases}

    # parse -------------------------------------------------------------------
    missing = [c['id'] for c in fixture['cases'] if c['id'] not in by_id]
    rejected = [c['id'] for c in cases if c['kind'] == 'rejected']
    checks.add('parse', not missing and not rejected and index['rejected_frames'] == 0,
               f'{len(fixture["cases"])} fixture cases through cc_parse_frame (+{sum(1 for c in cases if c["group"] == "synthetic")} '
               f'harness-only), {len(rejected)} rejected, {len(missing)} missing',
               [f'missing {m}' for m in missing] + [f'rejected {r}' for r in rejected])

    frame_cases = [c for c in cases if c['kind'] in ('frame', 'notice')]

    # safe circle -------------------------------------------------------------
    outside, tolerance = ring_indices()
    failures, tolerated, worst = [], [], {}
    for c in frame_cases:
        data = load_rgb(out / c['noart']['file'])
        bad = [(x, y, r) for x, y, r in outside if ink_at(data, x, y) > INK]
        near = [(x, y, r) for x, y, r in tolerance if ink_at(data, x, y) > INK]
        heading = next((o for o in objects(c['noart']['layout'], 'heading')), None)
        heading_text = heading['text'] if heading else ''
        in_heading_rows = all(heading and heading['y1'] - 2 <= y <= heading['y2'] + 2 for _x, y, _r in near)
        if bad:
            failures.append(f'{c["id"]}: {len(bad)} ink px beyond r{HEADING_TOLERANCE_R}, worst r={max(r for *_, r in bad):.1f} '
                            f'at {max(bad, key=lambda p: p[2])[:2]}')
        elif near:
            if heading_text == 'RECENTLY ADDED' and in_heading_rows:
                tolerated.append(f'{c["id"]}: {len(near)} px of "RECENTLY ADDED" within r104..r106')
            else:
                failures.append(f'{c["id"]}: {len(near)} ink px in r104..r106 (not the page-1 heading), '
                                f'worst r={max(r for *_, r in near):.1f} at {max(near, key=lambda p: p[2])[:2]}')
        if bad or near:
            worst[c['id']] = round(max(r for *_, r in bad + near), 2)
    checks.add('safe_circle', not failures,
               f'{len(frame_cases)} art-less renders: ink (max channel > {INK}) inside r{SAFE_R}; '
               f'{len(tolerated)} page-1 heading tolerance use(s)', failures, tolerated=tolerated, worst_radius=worst)

    # heading chain -----------------------------------------------------------
    failures, shown = [], {}
    for c in frame_cases:
        frame = frames.get(c['id']) or c.get('wire') or {}
        if c['kind'] == 'notice' or c['group'] == 'synthetic':
            continue
        wire = frame.get('heading', '')
        heading = next((o for o in objects(c['render']['layout'], 'heading')), None)
        text = heading['text'] if heading else ''
        shown[wire] = text
        if wire == 'RECENTLY ADDED' and text != wire:
            failures.append(f'{c["id"]}: page-1 heading changed to {text!r}')
        elif wire.startswith('RECENTLY ADDED · P'):
            ok = text == wire or text == 'RECENT · P' + wire.split(' · P', 1)[1]
            if not ok:
                failures.append(f'{c["id"]}: {wire!r} shown as {text!r}')
        elif text != wire and not verbatim([text], wire):
            failures.append(f'{c["id"]}: heading {wire!r} shown as {text!r}')
    syn = by_id.get('syn-recent-p12')
    if syn:
        heading = next((o for o in objects(syn['render']['layout'], 'heading')), None)
        shown['RECENTLY ADDED · P12'] = heading['text'] if heading else ''
        if not heading or heading['text'] not in ('RECENTLY ADDED · P12', 'RECENT · P12'):
            failures.append(f'syn-recent-p12: {heading and heading["text"]!r}')
    tracking = {w: next((o['letter_space'] for c in frame_cases for o in objects(c['render']['layout'], 'heading')
                         if o['text'] == t), None) for w, t in shown.items()}
    checks.add('heading_chain', not failures, 'headings: ' + '; '.join(f'{w!r} -> {t!r} (tracking {tracking[w]})'
                                                                     for w, t in shown.items()), failures)

    # verbatim text + label bounds -------------------------------------------
    failures, bounds_fail, counted = [], [], 0
    for c in frame_cases:
        frame = frames.get(c['id']) or c.get('wire')
        if frame is None:
            continue
        layout = c['render']['layout']
        for role, field in LABEL_SOURCES.items():
            for o in objects(layout, role):
                lines = [l['text'] for l in o['lines']]
                source = frame.get(field, '')
                counted += 1
                if not verbatim(lines, source):
                    failures.append(f'{c["id"]} {role}: {lines!r} vs wire {source!r}')
        cap = next((o for o in objects(layout, 'volume.caption')), None)
        if cap and not verbatim([l['text'] for l in cap['lines']], frame.get('volumeCaption') or frame.get('title', '')):
            failures.append(f'{c["id"]} volume.caption: {cap["text"]!r}')
        for o in layout:
            if o.get('type') == 'label' and visible(o) and o['role'] not in ('volume.digits', 'volume.percent'):
                for l in o['lines']:
                    if l['width'] and (l['x1'] < o['x1'] or l['x2'] > o['x2']):
                        bounds_fail.append(f'{c["id"]} {o["role"]}: line {l["text"]!r} {l["x1"]}..{l["x2"]} '
                                           f'outside box {o["x1"]}..{o["x2"]}')
    checks.add('verbatim_text', not failures, f'{counted} drawn labels equal the wire text or its prefix + U+2026 '
                                              f'(no invented copy)', failures)
    checks.add('label_bounds', not bounds_fail, 'every drawn line fits its label box (fitted before LVGL wraps)',
               bounds_fail)

    # ellipsis only when the full text cannot fit -------------------------------
    failures, labels, ellipsized, char_broken, fit_cases = [], 0, [], [], []
    for c in frame_cases:
        if c['kind'] != 'frame':
            continue
        frame = frames.get(c['id']) or c.get('wire') or {}
        for pass_name in ('noart', 'render'):
            ordinals = {}
            for o in c[pass_name]['layout']:
                if o.get('type') != 'label':
                    continue
                ordinal = ordinals.get(o['role'], 0)
                ordinals[o['role']] = ordinal + 1
                if 'fit' not in o or not visible(o):
                    continue
                fit, lines = o['fit'], [l['text'] for l in o['lines']]
                wire = wire_source(frame, o['role'], ordinal)
                where = f'{c["id"]} {pass_name} {o["role"]}'
                if wire is not None and wire != fit['source']:
                    failures.append(f'{where}: harness source {fit["source"]!r} is not the wire text {wire!r}')
                    continue
                source = fit['source']
                labels += 1
                whole = source in joined(lines)
                ends = bool(lines) and lines[-1].endswith(ELLIPSIS)
                over = [f'line {k} {l["width"]} > {fit["capacity"][k]}' for k, l in enumerate(o['lines'])
                        if k < len(fit['capacity']) and l['width'] > fit['capacity'][k]]
                if over:
                    failures.append(f'{where}: {lines!r} wider than the chord capacity ({", ".join(over)})')
                if fit['fits'] and not whole:
                    failures.append(f'{where}: {lines!r} although the full text {source!r} fits '
                                    f'(width {fit["source_width"]}, capacity {fit["capacity"]})')
                elif not fit['fits'] and not (ends and not whole and verbatim(lines, source)):
                    failures.append(f'{where}: {lines!r} for {source!r}, which cannot fit {fit["capacity"]}: '
                                    f'expected its prefix + U+2026')
                if pass_name != 'render':
                    continue
                if ends and not whole:
                    ellipsized.append(f'{c["id"]} {o["role"]}: {" / ".join(lines)!r} (full width '
                                      f'{fit["source_width"]}, capacity {fit["capacity"]})')
                if whole and len(lines) == 2 and ' '.join(lines) != source:
                    char_broken.append(f'{c["id"]} {o["role"]}: {" / ".join(lines)!r}')
                if FIT_CASES.get(c['id'], (None,))[0] == o['role']:
                    want = FIT_CASES[c['id']][1]
                    fit_cases.append(f'{c["id"]}: {" / ".join(lines)!r} (fits {fit["fits"]})')
                    shown_right = whole if want else (ends and not whole)
                    if fit['fits'] != want or not shown_right:
                        failures.append(f'{c["id"]} {o["role"]}: {lines!r}, fits {fit["fits"]} (expected '
                                        f'{"the whole text" if want else "a prefix + U+2026"})')
    failures += [f'harness case {k} missing' for k in FIT_CASES if k not in by_id]
    checks.add('ellipsis_honest', not failures and labels > 0 and len(fit_cases) == len(FIT_CASES),
               f'{labels} frame-driven labels (both passes) vs their full wire text: U+2026 only where the text '
               f'cannot fit its lines ({len(ellipsized)} ellipsized render labels), {len(char_broken)} over-wide '
               f'word(s) broken by characters; {len(fit_cases)}/{len(FIT_CASES)} harness fitting cases checked '
               f'(whole text / prefix + U+2026 as listed in FIT_CASES)',
               failures, ellipsized=ellipsized, char_broken=char_broken, fit_cases=fit_cases)

    # footer centres + icon recolour -----------------------------------------
    failures, recolour_fail, footers, icons_checked, recoloured = [], [], 0, 0, set()
    tone_ink = {'#E6E6E6', '#6ED996', '#FF8474', '#4A4A4A'}
    for c in frame_cases:
        if c['kind'] != 'frame':
            continue
        layout = c['noart']['layout']
        data = load_rgb(out / c['noart']['file'])
        foot = [o for o in layout if o['role'] == 'footer.icon']
        for slot, o in enumerate(foot):
            if not visible(o):
                continue
            footers += 1
            cx = (o['x1'] + o['x2'] + 1) / 2
            if cx != FOOTER_CX[slot] or o['y1'] != 154 or o['y2'] != 173:
                failures.append(f'{c["id"]} slot {slot}: centre {cx} rows {o["y1"]}..{o["y2"]}')
        for o in layout:
            if o.get('type') != 'image' or o.get('icon') in ('', 'art', 'app') or not visible(o) or o['opa_eff'] < 255:
                continue
            if o['role'] == 'footer.icon' and o['recolor'] not in tone_ink:
                recolour_fail.append(f'{c["id"]} footer ink {o["recolor"]} is not a tone ink')
            # A8 over black: pixel = ink * coverage / 255, so the brightest pixel is ink * mask peak / 255.
            ink = tuple(round(int(o['recolor'][k:k + 2], 16) * o['mask_max'] / 255) for k in (1, 3, 5))
            best = max(((data[(y * 240 + x) * 3], data[(y * 240 + x) * 3 + 1], data[(y * 240 + x) * 3 + 2])
                        for y in range(max(0, o['y1']), min(240, o['y2'] + 1))
                        for x in range(max(0, o['x1']), min(240, o['x2'] + 1))), key=sum)
            icons_checked += 1
            recoloured.add(o['recolor'])
            if any(abs(a - b) > 9 for a, b in zip(best, ink)):
                recolour_fail.append(f'{c["id"]} {o["role"]} {o["icon"]}: brightest px {best} vs ink {o["recolor"]} '
                                     f'x mask peak {o["mask_max"]}/255 = {ink}')
    checks.add('footer_centres', not failures and footers > 0,
               f'{footers} visible footer icons centred at x {FOOTER_CX}, rows 154..173', failures)
    checks.add('icon_recolour', not recolour_fail and icons_checked > 0,
               f'{icons_checked} opaque A8 icons drawn in their recolor ink (brightest px = ink x mask peak, '
               f'+-9 per channel for RGB565); inks seen {sorted(recoloured)}', recolour_fail)

    # idle centres ------------------------------------------------------------
    failures, idle_cases = [], 0
    for c in frame_cases:
        if c['kind'] != 'frame' or LAYOUTS[c['layout_id']] != 'idle':
            continue
        idle_cases += 1
        layout = c['render']['layout']
        icons = [o for o in layout if o['role'] == 'idle.icon']
        words = [o for o in layout if o['role'] == 'idle.word']
        for i, (icon, word) in enumerate(zip(icons, words)):
            if not visible(icon):
                continue
            cx = (icon['x1'] + icon['x2'] + 1) / 2
            if cx != IDLE_CX[i] or icon['y1'] != 100 or icon['y2'] != 125:
                failures.append(f'{c["id"]} item {i}: icon centre {cx}, rows {icon["y1"]}..{icon["y2"]}')
            line = word['lines'][0]
            wcx = (line['x1'] + line['x2'] + 1) / 2
            if abs(wcx - IDLE_CX[i]) > 1 or line['baseline'] != 145:
                failures.append(f'{c["id"]} word {i} {line["text"]!r}: centre {wcx}, baseline {line["baseline"]}')
    checks.add('idle_centres', not failures and idle_cases > 0,
               f'{idle_cases} idle renders: icons centred at x {IDLE_CX}, top 100; words centred under them, '
               f'baseline 145', failures)

    # digits / percent baseline ----------------------------------------------
    failures, volume_cases = [], 0
    for c in frame_cases:
        if c['kind'] != 'frame' or LAYOUTS[c['layout_id']] != 'volume':
            continue
        layout = c['noart']['layout']
        digits = next(iter(objects(layout, 'volume.digits')), None)
        percent = next(iter(objects(layout, 'volume.percent')), None)
        if not digits or not percent:
            failures.append(f'{c["id"]}: digits/percent not visible')
            continue
        volume_cases += 1
        d, p = digits['lines'][0], percent['lines'][0]
        data = load_rgb(out / c['noart']['file'])

        def bottom(x1, x2, y1, y2):
            rows = [y for y in range(y1, y2 + 1) if any(ink_at(data, x, y) > 128 for x in range(x1, x2 + 1))]
            return max(rows) if rows else None
        # Pixel baseline: the lowest solid row of '0'-'9' (no descenders) and of '%'.
        db = bottom(d['x1'], d['x2'], digits['y1'], digits['y2'])
        pb = bottom(p['x1'], p['x2'], percent['y1'], percent['y2'])
        centre = (d['x1'] + p['x2'] + 1) / 2
        if abs(d['baseline'] - p['baseline']) > 1 or db is None or pb is None or abs(db - pb) > 1 or abs(centre - 120) > 1:
            failures.append(f'{c["id"]}: baselines {d["baseline"]}/{p["baseline"]}, ink bottoms {db}/{pb}, centre {centre}')
    checks.add('digit_baseline', not failures and volume_cases > 0,
               f'{volume_cases} volume renders: digits and % on one baseline (layout and ink within 1 px), pair centred',
               failures)

    # CSS baselines -----------------------------------------------------------
    failures, measured = [], {}
    for c in frame_cases:
        for o in c['render']['layout']:
            if o.get('type') != 'label' or not visible(o) or o['role'] not in CSS_BASELINES:
                continue
            base = o['lines'][0]['baseline'] - o['ty']
            measured.setdefault(o['role'], set()).add(base)
            if abs(base - CSS_BASELINES[o['role']]) > 1:
                failures.append(f'{c["id"]} {o["role"]}: baseline {base} vs CSS {CSS_BASELINES[o["role"]]}')
    checks.add('css_baselines', not failures, 'label baselines vs rounded CSS baselines: ' + ', '.join(
        f'{r} {sorted(v)}/{CSS_BASELINES[r]}' for r, v in sorted(measured.items())), failures)

    # Windows title line 2 vs meta ---------------------------------------------
    failures, pairs = [], []
    for c in frame_cases:
        layout = c['noart']['layout']
        title = next(iter(objects(layout, 'windows.title')), None)
        meta = next(iter(objects(layout, 'windows.meta')), None)
        if not title or not meta:
            continue
        last = title['lines'][-1]
        m = meta['lines'][0]
        if 'ink_bottom' not in last or 'ink_top' not in m:
            continue
        gap = m['ink_top'] - last['ink_bottom'] - 1
        pairs.append(f'{c["id"]}: {len(title["lines"])} line(s), title ink ends {last["ink_bottom"]}, '
                     f'meta ink starts {m["ink_top"]} (gap {gap} px)')
        if gap < 0:
            failures.append(pairs[-1])
    two_line = [p for p in pairs if ': 2 line(s)' in p]
    checks.add('windows_meta', not failures and bool(two_line),
               f'{len(pairs)} Windows renders with meta, {len(two_line)} with a two-line title: no overlap', failures,
               pairs=pairs)

    # status only on home -------------------------------------------------------
    failures = []
    for c in frame_cases:
        if c['kind'] != 'frame':
            continue
        name = LAYOUTS[c['layout_id']]
        status = objects(c['render']['layout'], 'status')
        if name in ('recent', 'tracks', 'windows', 'notice') and status:
            failures.append(f'{c["id"]} ({name}) draws the status line {status[0]["text"]!r}')
    checks.add('status_home_only', not failures, 'list/tracks/windows/notice layouts draw meta, never status', failures)

    # art rules ------------------------------------------------------------------
    failures, shown_art = [], 0
    for c in frame_cases:
        if c['kind'] != 'frame':
            continue
        name = LAYOUTS[c['layout_id']]
        idle = name == 'idle' or (name == 'volume' and LAYOUTS[c['rest_layout_id']] == 'idle')
        art = next(o for o in c['render']['layout'] if o['role'] == 'art')
        expected = bool(c['art_key']) and bool(c.get('art')) and name in ('nowPlaying', 'volume', 'recent', 'tracks') and not idle
        if visible(art) != expected:
            failures.append(f'{c["id"]} ({name}, key {c["art_key"]!r}): art {"shown" if visible(art) else "hidden"}')
        if expected:
            shown_art += 1
            want = 112 if c['art_dim'] else 255
            if art['image_opa'] != want or art['opa_eff'] != 255:
                failures.append(f'{c["id"]}: image_opa {art["image_opa"]} (want {want}), opa {art["opa_eff"]}')
        noart = next(o for o in c['noart']['layout'] if o['role'] == 'art')
        if visible(noart):
            failures.append(f'{c["id"]}: the art-less twin shows art')
    checks.add('art_rules', not failures, f'art on nowPlaying/volume/recent/tracks only (never over idle, windows, '
                                          f'notice or without a key): {shown_art} renders with art; artDim -> 112',
               failures)

    # heap -------------------------------------------------------------------------
    heap = index['heap']
    peak = max(heap['max_used'], heap['peak_used_sampled'])
    checks.add('heap', peak <= heap['lv_mem_size'] // 2,
               f'peak {peak} B ({100 * peak / heap["lv_mem_size"]:.1f} % of {heap["lv_mem_size"]}; max_used '
               f'{heap["max_used"]}, sampled total-free {heap["peak_used_sampled"]}), fragmentation {heap["frag_pct"]} %, '
               f'free {heap["free_size"]} B at exit (x64 pointers: an upper bound for the ESP32-S3)')

    timelines = {t['id']: t for t in index['timelines']}

    # heartbeat ---------------------------------------------------------------------
    failures, beats = [], 0
    for t in index['timelines']:
        for s in t['steps']:
            if not s['expect'].get('identical'):
                continue
            beats += 1
            r = s['render']
            if r['animations'] or r['text_sets'] or r['changed'] or r['redraw_flushes'] or r['anims_running_after']:
                failures.append(f'{t["id"]} t={s["t"]}: {r}')
    checks.add('heartbeat', not failures and beats > 0,
               f'{beats} heartbeat-identical frame(s): 0 animations, 0 text sets, nothing changed, 0 redraw flushes',
               failures)

    # slides -------------------------------------------------------------------------
    failures, rows = [], []
    for t in index['timelines']:
        for s in t['steps']:
            if 'slide' not in s['expect']:
                continue
            want, got = s['expect']['slide'], s['render']['last_slide']
            rows.append(f'{t["id"]} t={s["t"]} {s["label"]}: {got:+d}')
            if want != got:
                failures.append(f'{t["id"]} t={s["t"]} {s["label"]}: slide {got:+d}, expected {want:+d}')
    ext = [s['render']['last_slide'] for s in timelines['external-volume']['steps']]
    skip = [s['render']['last_slide'] for s in timelines['tracks-skip-recentre']['steps'][1:]]
    deeper = [s for s in timelines['screen-deeper-back']['steps'] if s['expect'].get('slide')]
    checks.add('slides', not failures and not any(ext) and not any(skip) and deeper,
               f'{len(rows)} steps: external-volume re-enter {ext}, Tracks skip/re-centre {skip}, deeper/back '
               f'{[s["render"]["last_slide"] for s in deeper]}', failures, steps=rows)

    # motion at key times ------------------------------------------------------------
    failures, notes = [], []

    def cap(tid, step_label, offset, step_index=None):
        t = timelines[tid]
        labels = [s['label'] for s in t['steps']]
        index_ = step_index if step_index is not None else labels.index(step_label) + 1
        for cpt in t['captures']:
            if cpt['step'] == index_ and cpt['offset'] == offset:
                return {o['role'] + ('#%d' % k if o['role'] in ('idle.item', 'idle.icon', 'idle.word', 'footer.icon') else ''): o
                        for k, o in enumerate_roles(cpt['layout'])}
        raise KeyError(f'{tid} {step_label} +{offset}')

    def expect(cond, message):
        if not cond:
            failures.append(message)

    def val(objs, role, key):
        return objs[role][key]

    reveal = lambda off: cap('volume-reveal-hide', 'rot', off)  # noqa: E731
    r0, r150, r190, r230, r390, r460 = (reveal(o) for o in (0, 150, 190, 230, 390, 460))
    expect(val(r0, 'volume', 'opa') == 0 and val(r0, 'track', 'opa') == 255, 'reveal +0: volume layer waits 50 ms')
    expect(val(r150, 'track', 'opa') == 0, 'reveal +150: track layer faded (150 ms IN)')
    expect(val(r190, 'track', 'ty') == -8, 'reveal +190: track layer at -8 (190 ms IN)')
    expect(val(r230, 'volume', 'opa') == 255, 'reveal +230: volume opaque (50 + 180 ms OUT)')
    expect(val(r390, 'volume', 'ty') == 0 and val(r460, 'volume', 'ty') == 0, 'reveal +390: volume at rest (50 + 340 SPR)')
    spr = [cap('volume-reveal-hide', 'rot', o)['volume']['ty'] for o in (150, 190, 230, 340)]
    notes.append(f'volume translate_y during SPR: {spr} (overshoot below 0 allowed)')
    hide = lambda off: cap('volume-reveal-hide', 'volHide', off)  # noqa: E731
    expect(val(hide(170), 'volume', 'opa') == 0 and val(hide(190), 'volume', 'ty') == 6,
           'hide: volume opa 0 by +170, back at +6 by +190 (IN)')

    # idle-entry-exit: pIdle at 4420 ms, the next step (a turn) at 5000 ms, so
    # only captures before +580 show idle entry alone.
    idle = lambda off: cap('idle-entry-exit', 'pIdle', off)  # noqa: E731
    i0, i160, i245, i335, i560 = (idle(o) for o in (0, 160, 245, 335, 560))
    items = lambda objs: [objs[k]['opa'] for k in idle_items(objs)]  # noqa: E731
    lifts = lambda objs: [objs[k]['ty'] for k in idle_items(objs)]  # noqa: E731
    expect(val(i160, 'footer', 'opa') == 0, 'idle +160: footer hidden (160 ms IN)')
    expect(all(o == 0 for o in items(i0)) and all(t == 14 for t in lifts(i0)), f'idle +0: row waits at +14: {lifts(i0)}')
    expect(items(i245)[0] > 0 and items(i245)[1] == 0 and items(i245)[2] == 0,
           f'idle +245: only item 0 started (stagger 200 + 45 i): {items(i245)}')
    expect(items(i335)[2] > 0 and items(i335)[3] == 0, f'idle +335: items 0-2 started, item 3 at its start: {items(i335)}')
    expect(val(i560, 'art', 'opa') == 0 and 0 < val(i160, 'art', 'opa') < 255,
           f'idle: art fades out over 560 ms OUT ({val(i160, "art", "opa")} at +160, 0 at +560)')
    expect(items(i560)[:2] == [255, 255] and val(i560, 'track', 'ty') == -10 and val(i560, 'track', 'opa') == 0
           and val(i560, 'status', 'opa') == 0, f'idle +560: items 0-1 opaque, track at -10, status hidden')
    notes.append('idle row opacity at +245/+290/+335/+380: ' + ', '.join(
        str(items(idle(o))) for o in (245, 290, 335, 380)))
    notes.append('idle row translate_y (SPR) at +380/+560/+800: ' + ', '.join(
        str(lifts(idle(o))) for o in (380, 560, 800)))
    # Settled idle entry (harness timeline, next step 1800 ms later).
    settled = cap('art-late-idle', 'idle-enter', 1100)
    expect(all(o == 255 for o in items(settled)) and all(t == 0 for t in lifts(settled))
           and val(settled, 'track', 'ty') == -10 and val(settled, 'status', 'opa') == 0
           and val(settled, 'footer', 'opa') == 0 and val(settled, 'art', 'opa') == 0,
           'idle +1100 (settled): row at rest, track -10, status/footer/art hidden')
    back = lambda off: cap('idle-entry-exit', 'btn', off, step_index=7)  # noqa: E731
    expect(val(back(90), 'track', 'opa') == 0 and val(back(510), 'track', 'opa') == 255 and val(back(510), 'track', 'ty') == 0,
           'idle exit: track waits 90 ms, then 320/420 ms OUT')
    expect(val(back(510), 'art', 'opa') == 255 and val(back(510), 'footer', 'opa') == 255,
           'idle exit: art back (60 + 420 ms), footer back (140 + 280 ms)')

    slide_caps = []
    for step_index, s in enumerate(timelines['screen-deeper-back']['steps'], start=1):
        if not s['expect'].get('slide'):
            continue
        direction = s['expect']['slide']
        c0 = cap('screen-deeper-back', None, 0, step_index)
        c220 = cap('screen-deeper-back', None, 220, step_index)
        c380 = cap('screen-deeper-back', None, 380, step_index)
        slide_caps.append((s['label'], c0['content']['tx'], c0['stage']['opa'], c220['stage']['opa'], c380['content']['tx']))
        expect(c0['content']['tx'] == direction and c0['stage']['opa'] == 0,
               f'screen change t={s["t"]}: starts at {c0["content"]["tx"]:+d} / opa {c0["stage"]["opa"]}')
        expect(c220['stage']['opa'] == 255 and c380['content']['tx'] == 0,
               f'screen change t={s["t"]}: opa 255 by +220, translate 0 by +380')
        expect(c0['art']['tx'] == 0, 'the art layer never translates')
    notes.append(f'screen changes (label, tx@0, opa@0, opa@220, tx@380): {slide_caps}')

    late = lambda off: cap('art-late-idle', 'pixels-arrive', off)  # noqa: E731
    waiting = cap('art-late-idle', 'key-without-pixels', 0)
    expect(waiting['art']['hidden'] or waiting['art']['opa'] == 0, 'late art: nothing shown before the pixels exist')
    expect(val(late(0), 'art', 'opa') == 0 and val(late(60), 'art', 'opa') == 0, 'late art: 60 ms delay')
    expect(0 < val(late(270), 'art', 'opa') < 255 and val(late(480), 'art', 'opa') == 255, 'late art: 420 ms OUT fade')
    notes.append('late art opacity at +0/+60/+120/+270/+480: ' + str([val(late(o), 'art', 'opa') for o in (0, 60, 120, 270, 480)]))
    loaded = [s for s in timelines['screen-deeper-back']['steps'] if s['label'] == 'loaded']
    swaps = [cap('screen-deeper-back', None, 0, timelines['screen-deeper-back']['steps'].index(s) + 1)['art']['opa']
             for s in loaded]
    expect(all(o == 255 for o in swaps), f'cached cover swaps are instant: art opa at +0 {swaps}')
    checks.add('motion', not failures, 'volume reveal/hide, idle stagger/fades, screen change, late and cached art at '
                                       'the design key times', failures, notes=notes)

    # latency -------------------------------------------------------------------------
    lat = index['latency']
    checks.add('latency', lat['refr_now_flushes'] > 0 and not lat['animated_in_sample'],
               f'consecutive non-animated detents wait up to {lat["timer_wait_worst_ms"]} ms for the refresh timer '
               f'(gaps {lat["gap_ms"]} -> waits {lat["timer_wait_ms"]} ms; LV_DEF_REFR_PERIOD {lat["lv_def_refr_period_ms"]}); '
               f'lv_refr_now() presents at once ({lat["refr_now_flushes"]} flushes, host {lat["refr_now_host_us"]} us)')

    artwork2_checks(checks, out, index, frames, timelines)

    report = {
        'about': 'cc5 Stage 6 LCD regression checks (harness/cc5_report.py) over the LVGL 9.0 harness renders',
        'renders': str(out),
        'pass': all(r['pass'] for r in checks.results.values()),
        'checks': checks.results,
        'design_accepted_deviations': [
            'Art does not translate on a screen change; no decorative scale transforms (contract section 9.7).',
            'Host lost: native handback plus the restyled notice (NANO_D++ / Waiting for PC / Native controls active), '
            'not the model\'s seg-0 pattern (section 9.8).',
            'Label widths are clamped to the r104 safe chord of their own ink rows, so a long line can ellipsize '
            'a little earlier than the 170/180/192 px CSS box.',
            'Two-line titles use a balanced split at spaces (CSS text-wrap: balance) computed with LVGL text '
            'metrics. A word wider than a line breaks by characters (overflow-wrap), preferring a break after '
            '- _ / \\ . and balancing the two lines. U+2026 appears only when the whole text cannot fit two '
            'lines: then a full first line and a clamped second line (whole words + U+2026).',
            'Ellipsis is U+2026 placed by the renderer (CSS text-overflow), not LVGL LONG_DOT "..."; LONG_DOT '
            'stays set as a safety net with fixed label heights.',
        ],
    }
    (out / 'regression-checks.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    contact_sheets(out, index)
    print(f'cc5_report: {"PASS" if report["pass"] else "FAIL"} ({sum(r["pass"] for r in checks.results.values())}/'
          f'{len(checks.results)} checks) -> {out / "regression-checks.json"}')
    return 0 if report['pass'] else 1


# ------------------------------------------------------------------ artwork2 --
# Cover pixels vs Pillow (libjpeg). ARTWORK2.md section 10 asks for PSNR >= 40 dB after RGB565
# rounding; that figure is applied to luma, where a 4:2:0 cover's resolution lives. In RGB the
# knob's TJpgDec differs from libjpeg by its replicated (not "fancy") chroma upsampling and by
# rounding flips that a 5-bit channel turns into 8-unit steps: 33-44 dB on the fixtures, so
# RGB only has a floor that catches channel order and placement errors (a R/B swap: ~15 dB).
LUMA_PSNR_MIN_DB = 40.0
RGB_PSNR_MIN_DB = 30.0
DETAIL_ROUND_TRIP_MAX_DB = 30.0  # the detail cover really needs 240 px
TILE_BOX = (104, 42, 135, 73)  # Windows tile x1, y1, x2, y2 (32x32 at 104,42)
TILE_CLOSED_OPA = 89
CLOSED_TOLERANCE = 12          # per 8-bit channel: LVGL's 5-bit opacity mix vs c * 89 / 255
ART_DIM_OPA = 112
R5 = [(v * 31 + 127) // 255 for v in range(256)]
G6 = [(v * 63 + 127) // 255 for v in range(256)]
X5 = [c * 255 // 31 for c in range(32)]
X6 = [c * 255 // 63 for c in range(64)]


def lv_mix(value, opa):
    """LVGL 9.0 lv_color_16_16_mix() of one RGB565 channel over black: floor(c * ((opa + 4) >> 3) / 32)."""
    return value * ((opa + 4) >> 3) >> 5


def reference_565(rgb: bytes, opa: int = 255) -> bytes:
    """RGB888 -> RGB565 with the contract's rounding (mixed over black at opa like LVGL when
    opa < 255), expanded back to 8 bits exactly as main.cpp writePpm() does."""
    out = bytearray(len(rgb))
    for i in range(0, len(rgb), 3):
        r, g, b = R5[rgb[i]], G6[rgb[i + 1]], R5[rgb[i + 2]]
        if opa < 255:
            r, g, b = lv_mix(r, opa), lv_mix(g, opa), lv_mix(b, opa)
        out[i], out[i + 1], out[i + 2] = X5[r], X6[g], X5[b]
    return bytes(out)


def payload_rgb(raw: bytes) -> list:
    """32x32 RGB565 LE icon payload -> 8-bit RGB triples (writePpm expansion)."""
    out = []
    for i in range(0, len(raw), 2):
        v = raw[i] | (raw[i + 1] << 8)
        out.append((X5[(v >> 11) & 31], X6[(v >> 5) & 63], X5[v & 31]))
    return out


def psnr(a: bytes, b: bytes, pixels) -> tuple:
    """(RGB PSNR dB, luma PSNR dB, max |channel difference|, pixel count) over pixels."""
    se = se_luma = worst = n = 0
    for p in pixels:
        i = 3 * p
        for k in range(3):
            d = a[i + k] - b[i + k]
            se += d * d
            worst = max(worst, abs(d))
        dy = 0.299 * (a[i] - b[i]) + 0.587 * (a[i + 1] - b[i + 1]) + 0.114 * (a[i + 2] - b[i + 2])
        se_luma += dy * dy
        n += 1
    if not n:
        return 0.0, 0.0, 0, 0

    def db(mse):
        return 99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse)
    return db(se / (3 * n)), db(se_luma / n), worst, n


def by_role(layout):
    """First object of each role (the artwork2 checks only read single objects)."""
    roles = {}
    for o in layout:
        roles.setdefault(o['role'], o)
    return roles


def tile_initial(subtitle: str) -> str:
    if not subtitle:
        return ''
    first = subtitle[0]
    return first.upper() if 'a' <= first <= 'z' else first


# Every artwork2 check, and the render-index.json keys they need (main.cpp, cc5.3 fix round 1).
A2_CHECKS = ('jpeg_glue', 'a2_cover_exact', 'a2_cover_fullres', 'a2_cover_none', 'a2_icon', 'a2_letter',
             'a2_media_pins', 'a2_heartbeat', 'a2_timelines', 'a2_handback', 'a2_one_buffer')
A2_INDEX_KEYS = ('artwork2_fixtures', 'jpeg_glue', 'firmware_src', 'tjpgd_shim', 'artwork2_decoded',
                 'artwork2_aliases', 'handback', 'sim_decode_ms')
FIRMWARE_SRC = ROOT.parent / 'firmware' / 'src'
TJPGD_SHIM = ROOT / 'tjpgd_shim'
# Timeline captures whose cover pixels must be exact: (timeline, step label, offset, cover key,
# the artwork2 case with the same text, whose art-less twin gives the art-only pixels).
EXACT_CAPTURES = (
    ('a2-swap', 'back-to-a', 0, 'a2-swap-a', 'a2-recent-hall-dim'),           # back-buffer reuse (dim)
    ('a2-decode-fail', 'other-key', 0, 'a2-hall', 'a2-np-hall'),               # after a failed decode
    ('a2-slide-decode', 'slide-decode', 380, 'a2-slide', 'a2-recent-bright'),  # decoded during a slide
)


def same_dir(recorded, wanted: Path) -> bool:
    return bool(recorded) and os.path.normcase(os.path.realpath(recorded)) == os.path.normcase(os.path.realpath(wanted))


def art_only(twin: bytes) -> list:
    """Pixels where the art-less twin draws nothing (black): the cover alone shows there."""
    return [p for p in range(240 * 240) if not (twin[3 * p] or twin[3 * p + 1] or twin[3 * p + 2])]


def decoded_rgb(raw: bytes, opa: int = 255) -> bytes:
    """cc_jpeg_decode_240 output (native RGB565 LE) as the panel shows it: mixed over black at
    image_opa like LVGL 9.0 when opa < 255, expanded to 8 bits exactly as main.cpp writePpm()."""
    out = bytearray(240 * 240 * 3)
    for p in range(240 * 240):
        v = raw[2 * p] | (raw[2 * p + 1] << 8)
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        if opa < 255:
            r, g, b = lv_mix(r, opa), lv_mix(g, opa), lv_mix(b, opa)
        out[3 * p], out[3 * p + 1], out[3 * p + 2] = X5[r], X6[g], X5[b]
    return bytes(out)


def mismatches(render: bytes, expected: bytes, pixels) -> tuple:
    """(differing pixels, max |channel difference|) over pixels."""
    bad = worst = 0
    for p in pixels:
        i = 3 * p
        d = max(abs(render[i] - expected[i]), abs(render[i + 1] - expected[i + 1]), abs(render[i + 2] - expected[i + 2]))
        if d:
            bad += 1
            worst = max(worst, d)
    return bad, worst


def decoded_for(base: Path, idx, key):
    """The recorded decoder output for a cover key (aliases resolved), or None."""
    name = (idx.get('artwork2_aliases') or {}).get(key, key)
    file = (idx.get('artwork2_decoded') or {}).get(name)
    if not file or not (base / file).is_file():
        return None
    raw = (base / file).read_bytes()
    return raw if len(raw) == 240 * 240 * 2 else None


def find_capture(timeline, label, offset):
    index_ = [s['label'] for s in timeline['steps']].index(label) + 1
    for cpt in timeline['captures']:
        if cpt['step'] == index_ and cpt['offset'] == offset:
            return cpt
    raise KeyError(f'{timeline["id"]} {label} +{offset}')


def exact_covers(base: Path, idx) -> tuple:
    """Tolerance-free cover pixels of one harness run: (rows, failures, renders compared)."""
    rows, failures, compared = [], [], 0
    by_id = {c['id']: c for c in idx['cases'] if c['kind'] == 'frame'}
    timelines = {t['id']: t for t in idx['timelines']}
    targets = [(c['id'], c['render']['file'], c['art_key'], c) for c in by_id.values()
               if c.get('group') == 'artwork2' and c.get('art')]
    for tid, label, offset, key, case_id in EXACT_CAPTURES:
        try:
            targets.append((f'{tid}/{label}+{offset}', find_capture(timelines[tid], label, offset)['file'], key,
                            by_id[case_id]))
        except (KeyError, ValueError) as error:
            failures.append(f'missing capture for the exact check: {error!r}')
    for name, file, key, case in targets:
        raw = decoded_for(base, idx, key)
        if raw is None:
            failures.append(f'{name}: no recorded decoder output for {key!r}')
            continue
        opa = ART_DIM_OPA if case['art_dim'] else 255
        pixels = art_only(load_rgb(base / case['noart']['file']))
        bad, worst = mismatches(load_rgb(base / file), decoded_rgb(raw, opa), pixels)
        compared += 1
        rows.append(f'{name}: {key} {"x image_opa 112 " if opa < 255 else ""}{bad} of {len(pixels)} art-only px '
                    f'differ (max |d| {worst})')
        if bad or len(pixels) < 20000:
            failures.append(rows[-1])
    return rows, failures, compared


def artwork2_checks(checks, out, index, frames, timelines):
    absent = [k for k in A2_INDEX_KEYS if k not in index]
    if absent:
        # Evidence from before this harness (cc5.2, or the first cc5.3 round): report, do not crash.
        for name in A2_CHECKS:
            checks.add(name, False, f'evidence predates the cc5.3 harness (render-index.json has no '
                                    f'{", ".join(absent)}): rebuild with build.py <out>, then rerun cc5_report.py')
        return
    cases = index['cases']
    frame_cases = [c for c in cases if c['kind'] == 'frame']
    a2 = [c for c in frame_cases if c.get('group') == 'artwork2']
    fixtures = Path(index['artwork2_fixtures'])
    manifest = json.loads((fixtures / 'manifest.json').read_text(encoding='utf-8'))
    covers = {e['name']: Image.open(fixtures / e['file']).convert('RGB') for e in manifest['covers']}
    icons = {e['name']: (fixtures / e['file']).read_bytes() for e in manifest['icons']}

    glue = index.get('jpeg_glue')
    src_ok = same_dir(index.get('firmware_src'), FIRMWARE_SRC)
    shim_ok = same_dir(index.get('tjpgd_shim'), TJPGD_SHIM)
    checks.add('jpeg_glue', glue == 'cc_jpeg.cpp' and src_ok and shim_ok,
               f'artwork2 covers decoded by {glue!r} (required: the firmware\'s cc_jpeg.cpp through tjpgd_shim; '
               f'"standin" means fw-core\'s glue was not present at build time); built from '
               f'{index.get("firmware_src")!r} ({"the real src/" if src_ok else "NOT " + FIRMWARE_SRC.as_posix()}) '
               f'and {index.get("tjpgd_shim")!r} ({"the real shim" if shim_ok else "NOT " + TJPGD_SHIM.as_posix()})')

    # Exact cover pixels ------------------------------------------------------------
    rows, failures, compared = exact_covers(out, index)
    checks.add('a2_cover_exact', not failures and compared >= 7 + len(EXACT_CAPTURES),
               f'{compared} cover renders (cases, back-buffer reuse, after a failed decode, decoded during a slide): '
               f'every art-only pixel equals cc_jpeg_decode_240\'s output (artDim: LVGL mix at 112), 0 px differ',
               failures, covers=rows)

    # Full-resolution covers ------------------------------------------------------
    failures, rows, combos, detail_seen = [], [], set(), False
    drawn = [c for c in a2 if c.get('art')]
    for c in drawn:
        name, layout_name = c['art'], LAYOUTS[c['layout_id']]
        render, twin = load_rgb(out / c['render']['file']), load_rgb(out / c['noart']['file'])
        art_only = [p for p in range(240 * 240) if not (twin[3 * p] or twin[3 * p + 1] or twin[3 * p + 2])]
        opa = ART_DIM_OPA if c['art_dim'] else 255
        reference = reference_565(covers[name].tobytes(), opa)
        db, db_luma, worst, count = psnr(render, reference, art_only)
        # What a 120 px path could show at best: the reference reduced to 120 px and scaled back.
        small = covers[name].resize((120, 120), Image.Resampling.LANCZOS).resize((240, 240), Image.Resampling.BILINEAR)
        _, trip_luma, _, _ = psnr(reference_565(small.tobytes(), opa), reference, art_only)
        art = by_role(c['render']['layout'])['art']
        stats, media = c['render']['stats'], c['render'].get('media') or {}
        rows.append(f'{c["id"]} ({layout_name}{", artDim" if c["art_dim"] else ""}): {name} luma PSNR {db_luma:.1f} dB '
                    f'(a 120 px round trip: {trip_luma:.1f} dB), RGB {db:.1f} dB, max |d| {worst}, {count} art-only px')
        combos.add((layout_name, bool(c['art_dim'])))
        if not visible(art) or art['opa_eff'] != 255 or art['image_opa'] != opa:
            failures.append(f'{c["id"]}: art visible {visible(art)}, opa {art["opa_eff"]}, image_opa {art["image_opa"]} '
                            f'(want 255 / {opa})')
        if db_luma < LUMA_PSNR_MIN_DB or db_luma <= trip_luma or db < RGB_PSNR_MIN_DB or count < 20000:
            failures.append(f'{c["id"]}: luma {db_luma:.1f} dB (need >= {LUMA_PSNR_MIN_DB:.0f} and above the round '
                            f'trip {trip_luma:.1f}), RGB {db:.1f} dB (need >= {RGB_PSNR_MIN_DB:.0f}) over {count} px')
        if name == 'a2-detail' and trip_luma >= DETAIL_ROUND_TRIP_MAX_DB:
            failures.append(f'{c["id"]}: the detail cover survives a 120 px round trip ({trip_luma:.1f} dB): not a '
                            f'resolution probe')
        detail_seen = detail_seen or name == 'a2-detail'
        if stats['art_upscales'] or stats['art_decode_errors']:
            failures.append(f'{c["id"]}: {stats["art_upscales"]} upscale(s), {stats["art_decode_errors"]} decode error(s)')
        if media.get('cover') != c['art_key']:
            failures.append(f'{c["id"]}: store pin {media.get("cover")!r}, want {c["art_key"]!r}')
    want = {(l, d) for l in ('nowPlaying', 'recent', 'tracks') for d in (False, True)}
    missing = sorted(want - combos)
    checks.add('a2_cover_fullres', not failures and not missing and detail_seen,
               f'{len(drawn)} 240 px JPEG cover renders (nowPlaying/recent/tracks x artDim, plus the 1 px detail '
               f'cover) vs a Pillow decode rounded to RGB565: luma PSNR >= {LUMA_PSNR_MIN_DB:.0f} dB and above a '
               f'120 px round trip, RGB >= {RGB_PSNR_MIN_DB:.0f} dB; decoded, never upscaled, pinned',
               failures + [f'missing {m}' for m in missing] + ([] if detail_seen else ['missing the detail cover']),
               covers=rows)

    # Covers that cannot be drawn --------------------------------------------------
    failures, rows = [], []
    for c in a2:
        if c['layout_id'] == LAYOUTS.index('windows') or c.get('art'):
            continue
        art = by_role(c['render']['layout'])['art']
        stats, media = c['render']['stats'], c['render'].get('media') or {}
        failed = c['art_key'] in (c.get('commits') or [])
        rows.append(f'{c["id"]} ({"committed, undecodable" if failed else "not committed"}): art '
                    f'{"shown" if visible(art) else "hidden"}, decodes {stats["art_decodes"]}, errors '
                    f'{stats["art_decode_errors"]}, pin {media.get("cover")!r}')
        if visible(art) or media.get('cover') is not None:
            failures.append(rows[-1])
        if failed and (stats['art_decodes'] != 1 or stats['art_decode_errors'] != 1):
            failures.append(f'{c["id"]}: expected exactly one failed decode')
    checks.add('a2_cover_none', not failures and len(rows) >= 2,
               f'{len(rows)} renders whose cover cannot be drawn show no art and hold no store pin', failures, cases=rows)

    # App icons and letter tiles -------------------------------------------------------
    icon_fail, letter_fail, icon_rows, letters = [], [], [], []
    for c in frame_cases:
        if LAYOUTS[c['layout_id']] != 'windows':
            continue
        frame = frames.get(c['id']) or c.get('wire') or {}
        roles = by_role(c['render']['layout'])
        icon, letter, tile = roles.get('windows.icon'), roles.get('windows.letter'), roles.get('windows.tile')
        committed = c.get('commits') or []
        want_icon = bool(c.get('icon_key')) and c['icon_key'] in committed
        shown = bool(icon) and visible(icon)
        if want_icon != shown:
            icon_fail.append(f'{c["id"]}: icon {"shown" if shown else "not shown"} (iconKey {c.get("icon_key")!r}, '
                             f'committed {committed})')
            continue
        if shown:
            closed = tile['opa'] == TILE_CLOSED_OPA
            box = (icon['x1'], icon['y1'], icon['x2'], icon['y2'])
            data = load_rgb(out / c['render']['file'])
            expected = payload_rgb(icons[c['icon_key']])
            worst = 0
            for k, (er, eg, eb) in enumerate(expected):
                x, y = TILE_BOX[0] + k % 32, TILE_BOX[1] + k // 32
                i = (y * 240 + x) * 3
                if closed:
                    er, eg, eb = (round(v * TILE_CLOSED_OPA / 255) for v in (er, eg, eb))
                worst = max(worst, abs(data[i] - er), abs(data[i + 1] - eg), abs(data[i + 2] - eb))
            icon_rows.append(f'{c["id"]}: {c["icon_key"]} at {box}, opa {icon["opa_eff"]}, max |d| {worst} vs the payload'
                             f'{" x 89/255" if closed else ""}')
            # The tile group carries the closed opa; a child's recursive opa is LV_OPA_MIX2(255, 89) = 88.
            if box != TILE_BOX or not (TILE_CLOSED_OPA - 1 <= icon['opa_eff'] <= TILE_CLOSED_OPA if closed
                                       else icon['opa_eff'] == 255):
                icon_fail.append(icon_rows[-1])
            if worst > (CLOSED_TOLERANCE if closed else 0):
                icon_fail.append(f'{c["id"]}: icon pixels differ from the payload by up to {worst}')
            if letter and visible(letter):
                icon_fail.append(f'{c["id"]}: the letter {letter["text"]!r} is drawn under the icon')
            if 'bg' in tile:
                icon_fail.append(f'{c["id"]}: tile background {tile["bg"]} behind the icon (want transparent)')
            if (c['render'].get('media') or {}).get('icon') != c['icon_key']:
                icon_fail.append(f'{c["id"]}: store icon pin {(c["render"].get("media") or {}).get("icon")!r}')
            continue
        subtitle = frame.get('subtitle', '')
        want = tile_initial(subtitle)
        text = letter['text'] if letter and visible(letter) else ''
        tile_shown = bool(tile) and visible(tile)
        letters.append(f'{subtitle[:12]!r}->{text!r}')
        if text != want or tile_shown != bool(subtitle) or (tile_shown and tile.get('bg') != '#444444'):
            letter_fail.append(f'{c["id"]}: subtitle {subtitle!r}: letter {text!r} (want {want!r}), tile '
                               f'{"shown" if tile_shown else "hidden"} bg {tile.get("bg") if tile else None}')
    closed_icons = [r for r in icon_rows if 'x 89/255' in r]
    checks.add('a2_icon', not icon_fail and len(icon_rows) >= 3 and closed_icons,
               f'{len(icon_rows)} app icon renders (payload pixels exact when open, x 0.35 within '
               f'{CLOSED_TOLERANCE} when closed; letter hidden, tile transparent, icon pinned)', icon_fail, icons=icon_rows)
    lower = {'a2-win-letter-lower': 'S', 'a2-win-icon-miss': 'C', 'a2-win-letter-accent': 'é'}
    by_id = {c['id']: c for c in frame_cases}
    for cid, want in lower.items():
        letter = by_role(by_id[cid]['render']['layout']).get('windows.letter') if cid in by_id else None
        if not letter or letter['text'] != want or not visible(letter):
            letter_fail.append(f'{cid}: letter {letter and letter["text"]!r}, want {want!r}')
    checks.add('a2_letter', not letter_fail and len(letters) > 20,
               f'{len(letters)} letter tiles: the subtitle\'s first code point, ASCII a-z upper-cased, on #444 '
               f'(tile hidden without a subtitle)', letter_fail, samples=sorted(set(letters))[:40])

    # Store display pins ------------------------------------------------------------------
    failures, pinned = [], 0
    for c in frame_cases:
        roles = by_role(c['render']['layout'])
        media, twin_media = c['render'].get('media') or {}, c['noart'].get('media') or {}
        committed = c.get('commits') or []
        art, icon = roles.get('art'), roles.get('windows.icon')
        want_cover = c['art_key'] if art and visible(art) and c['art_key'] in committed else None
        want_icon = c.get('icon_key') if icon and visible(icon) else None
        pinned += bool(want_cover) + bool(want_icon)
        if media.get('cover') != want_cover or media.get('icon') != want_icon or twin_media.get('cover') is not None:
            failures.append(f'{c["id"]}: pins cover {media.get("cover")!r} icon {media.get("icon")!r} (twin cover '
                            f'{twin_media.get("cover")!r}); want {want_cover!r} / {want_icon!r}')
    standin = index.get('media_standin', {})
    checks.add('a2_media_pins', not failures and pinned > 0,
               f'{len(frame_cases)} case renders: the store pins exactly the cover and icon drawn from it '
               f'({pinned} pins; stand-in totals {standin})', failures)

    # Identical frames ------------------------------------------------------------------------
    failures, beats = [], 0
    a2_timelines = {k: t for k, t in timelines.items() if k.startswith('a2-')}
    for tid, t in a2_timelines.items():
        for s in t['steps']:
            if not s['expect'].get('identical'):
                continue
            beats += 1
            r = s['render']
            if r['art_decodes'] or r['icon_loads'] or r['art_reuses'] or r['art_decode_errors'] or r['animations'] \
                    or r['text_sets'] or r['changed'] or r['redraw_flushes']:
                failures.append(f'{tid} t={s["t"]} {s["label"]}: {r}')
    checks.add('a2_heartbeat', not failures and beats >= 5,
               f'{beats} identical artwork2 frames (JPEG cover, app icon, failed key): no decode, no icon copy, no '
               f'swap, no animation, no text set, no redraw', failures)

    # Timelines -------------------------------------------------------------------------------
    failures, notes = [], []

    def expect(cond, message):
        if not cond:
            failures.append(message)

    def step(tid, label):
        return next(s for s in timelines[tid]['steps'] if s['label'] == label)

    def cap(tid, label, offset):
        t = timelines[tid]
        index_ = [s['label'] for s in t['steps']].index(label) + 1
        for cpt in t['captures']:
            if cpt['step'] == index_ and cpt['offset'] == offset:
                return by_role(cpt['layout']), cpt
        raise KeyError(f'{tid} {label} +{offset}')

    try:
        before, _ = cap('a2-icon-late', 'letter-meanwhile', 0)
        arrived, arrived_cpt = cap('a2-icon-late', 'icon-arrives', 0)
        later, _ = cap('a2-icon-late', 'icon-arrives', 30)
        r = step('a2-icon-late', 'icon-arrives')['render']
        expect(visible(before['windows.letter']) and before['windows.letter']['text'] == 'V'
               and not visible(before['windows.icon']), 'icon late: the letter tile "V" until the icon is committed')
        expect(visible(arrived['windows.icon']) and not visible(arrived['windows.letter'])
               and 'bg' not in arrived['windows.tile'], 'icon late: the icon replaces the letter at +0')
        expect(r['icon_loads'] == 1 and r['animations'] == 0 and not r['animated'] and r['changed']
               and r['redraw_flushes'] > 0 and (r.get('media') or {}).get('icon') == 'ic-late',
               f'icon late: one copy, no animation, redrawn at once, pinned: {r}')
        expect(later['windows.icon']['opa_eff'] == 255 and arrived['windows.icon']['opa_eff'] == 255,
               'icon late: no fade (opa 255 at +0 and +30)')
        data = load_rgb(out / arrived_cpt['file'])
        expected = payload_rgb(icons['ic-late'])
        worst = max(abs(data[((TILE_BOX[1] + k // 32) * 240 + TILE_BOX[0] + k % 32) * 3 + j] - expected[k][j])
                    for k in range(1024) for j in range(3))
        expect(worst == 0, f'icon late: pixels at +0 differ from the payload by {worst}')

        waiting, _ = cap('a2-cover-late', 'key-without-pixels', 0)
        expect(not visible(waiting['art']), 'cover late: nothing drawn before the JPEG is committed')
        opas = {o: cap('a2-cover-late', 'cover-arrives', o)[0]['art']['opa'] for o in (0, 60, 120, 270, 480)}
        r = step('a2-cover-late', 'cover-arrives')['render']
        expect(opas[0] == 0 and opas[60] == 0 and 0 < opas[270] < 255 and opas[480] == 255,
               f'cover late: 60 ms delay + 420 ms fade, opa {opas}')
        expect(r['art_decodes'] == 1 and r['art_upscales'] == 0 and (r.get('media') or {}).get('cover') == 'a2-late',
               f'cover late: one decode on arrival, pinned: {r}')
        notes.append(f'late JPEG cover opacity at +0/+60/+120/+270/+480: {list(opas.values())}')

        b = step('a2-swap', 'decode-b')['render']
        a = step('a2-swap', 'back-to-a')['render']
        expect(b['art_decodes'] == 1 and b['art_reuses'] == 0, f'swap: B decoded into the back buffer: {b}')
        expect(a['art_decodes'] == 0 and a['art_reuses'] == 1, f'swap: back to A reuses the back buffer: {a}')
        for label in ('decode-b', 'back-to-a'):
            roles, _ = cap('a2-swap', label, 0)
            expect(visible(roles['art']) and roles['art']['opa'] == 255, f'swap: {label} is instant (opa 255 at +0)')

        fail = step('a2-decode-fail', 'decode-fails')['render']
        other = step('a2-decode-fail', 'other-key')['render']
        again = step('a2-decode-fail', 'key-again')['render']
        expect(fail['art_decodes'] == 1 and fail['art_decode_errors'] == 1 and not visible(cap('a2-decode-fail', 'decode-fails', 0)[0]['art'])
               and (fail.get('media') or {}).get('cover') is None, f'decode fail: no art, no pin: {fail}')
        expect(other['art_decodes'] == 0 and visible(cap('a2-decode-fail', 'other-key', 0)[0]['art']),
               f'decode fail: the previous cover (still in the front buffer) returns at once: {other}')
        expect(again['art_decodes'] == 1 and again['art_decode_errors'] == 1
               and not visible(cap('a2-decode-fail', 'key-again', 0)[0]['art']),
               f'decode fail: retried only after the key changed: {again}')
        slide = step('a2-heartbeat', 'windows')['render']['last_slide']
        expect(slide == 20, f'heartbeat timeline: Home -> Windows slides from the right ({slide:+d})')
        media = step('a2-heartbeat', 'windows')['render'].get('media')
        expect(media == {'cover': None, 'icon': 'ic-code'},
               f'heartbeat timeline: on Windows the cover pin is released and the icon pinned: {media}')
        # Prefetch commits of other keys re-render the same frame (lcd_thread follows cc_media_version()):
        # inert (a2_heartbeat's rules, expect "identical") and the pins stay on the frame's keys.
        for label, want in (('unrelated-commit-home', {'cover': 'a2-hall', 'icon': None}),
                            ('unrelated-commit-windows', {'cover': None, 'icon': 'ic-code'})):
            s = step('a2-heartbeat', label)
            expect(bool(s.get('commits')) and s['expect'].get('identical') and s['render'].get('media') == want,
                   f'{label}: commits {s.get("commits")} leave the pins at {want}: {s["render"].get("media")}')

        # A decode during a screen change (main.cpp simulates the knob's decode time on the tick).
        sim = index['sim_decode_ms']
        sd = step('a2-slide-decode', 'slide-decode')['render']
        sb = step('a2-slide-decode', 'slide-back')['render']
        at = {o: cap('a2-slide-decode', 'slide-decode', o)[0] for o in (0, 60, 110, 220, 380)}
        expect(sim > 0 and sd['render_ms'] == sim and sd['art_decodes'] == 1 and sd['last_slide'] == 20,
               f'decode + slide: one {sim} ms decode inside the render, slide +20: {sd}')
        expect(at[0]['content']['tx'] == 20 and at[0]['stage']['opa'] == 0,
               f'decode + slide: the slide and fade start at their beginning when the render returns (tx '
               f'{at[0]["content"]["tx"]:+d}, stage opa {at[0]["stage"]["opa"]} at +0; a decode after the tweens '
               f'would have advanced them by {sim} ms)')
        expect(at[220]['stage']['opa'] == 255 and at[380]['content']['tx'] == 0 and 0 < at[60]['content']['tx'] < 20,
               'decode + slide: full-length slide and fade (opa 255 by +220, translate 0 by +380)')
        expect(not at[0]['art']['hidden'] and at[0]['art']['opa'] == 255,
               'decode + slide: the new cover is on the art layer at once (it fades with the stage)')
        expect(sb['art_reuses'] == 1 and sb['art_decodes'] == 0 and sb['render_ms'] == 0 and sb['last_slide'] == -20,
               f'decode + slide: back to Home swaps to the back buffer, no decode: {sb}')
        notes.append('screen change after a %d ms decode, (content tx, stage opa) at +0/+60/+110/+220/+380: %s' % (
            sim, [(at[o]['content']['tx'], at[o]['stage']['opa']) for o in (0, 60, 110, 220, 380)]))
    except (KeyError, StopIteration, ValueError) as error:
        failures.append(f'missing artwork2 timeline data: {error!r}')
    checks.add('a2_timelines', not failures, 'late icon (instant), late JPEG cover (60 + 420 ms fade), front/back '
                                            'swap and reuse, decode failure without retry, cover pin released on '
                                            'Windows, unrelated commits inert, a decode never shortens a screen '
                                            'change', failures, notes=notes)

    # Native handback ------------------------------------------------------------------------
    rows, failures = handback_rows(index)
    checks.add('a2_handback', not failures and len(rows) == len(HANDBACK_EXPECT),
               'cc_display_release_media() releases the displayed cover and icon; the return re-pins and decodes '
               'nothing; after eviction the buffered cover is still drawn (displayed -1), an icon falls back to the '
               'letter tile', failures, steps=rows)

    # One art buffer ---------------------------------------------------------------------------
    one_buffer_checks(checks, out)


# Native handback steps (main.cpp): label -> (cover pin, icon pin, art drawn, icon drawn).
HANDBACK_EXPECT = {
    'host-cover': ('a2-hall', None, True, False),
    'handback-cover': (None, None, None, None),
    'return-cover': ('a2-hall', None, True, False),
    'host-icon': (None, 'ic-code', False, True),
    'handback-icon': (None, None, None, None),
    'return-evicted': (None, None, True, False),
    'windows-evicted': (None, None, False, False),
}


def handback_rows(idx) -> tuple:
    rows, failures = [], []
    steps = {s['label']: s for s in idx.get('handback') or []}
    previous = None
    for label, (cover, icon, art, app_icon) in HANDBACK_EXPECT.items():
        s = steps.get(label)
        if not s:
            failures.append(f'handback step {label!r} missing')
            continue
        media = s.get('media') or {}
        rows.append(f'{label}: pins {media.get("cover")!r}/{media.get("icon")!r}, art {s["art_shown"]}, icon '
                    f'{s["icon_shown"]}, decodes {s["art_decodes"]}, upscales {s["art_upscales"]}, releases {s["releases"]}')
        if media.get('cover') != cover or media.get('icon') != icon:
            failures.append(f'{label}: pins {media}, want cover {cover!r} icon {icon!r}')
        if art is not None and (s['art_shown'] != art or s['icon_shown'] != app_icon):
            failures.append(f'{label}: art drawn {s["art_shown"]} (want {art}), icon drawn {s["icon_shown"]} '
                            f'(want {app_icon})')
        if label.startswith('handback-') and previous:
            kind = 0 if label == 'handback-cover' else 1
            if s['releases'][kind] != previous['releases'][kind] + 1 or s['releases'][1 - kind] != previous['releases'][1 - kind]:
                failures.append(f'{label}: releases {previous["releases"]} -> {s["releases"]}: want exactly one '
                                f'{"cover" if kind == 0 else "icon"} release')
        if label.startswith('return-') and (s['art_decodes'] or s['art_upscales']):
            failures.append(f'{label}: the return decoded or upscaled ({s["art_decodes"]}/{s["art_upscales"]}); the '
                            f'pixels were still in the front buffer')
        previous = s
    return rows, failures


def one_buffer_checks(checks, out: Path):
    base = out / 'one-buffer'
    path = base / 'render-index.json'
    if not path.is_file():
        checks.add('a2_one_buffer', False, f'{path} missing: rebuild with build.py (it runs main.cpp --one-buffer)')
        return
    ob = json.loads(path.read_text(encoding='utf-8'))
    failures, notes = [], []

    def expect(cond, message):
        if not cond:
            failures.append(message)

    try:
        timelines = {t['id']: t for t in ob['timelines']}

        def step(tid, label):
            return next(s for s in timelines[tid]['steps'] if s['label'] == label)['render']

        def art_at(tid, label, offset=0):
            return by_role(find_capture(timelines[tid], label, offset)['layout'])['art']

        expect(ob.get('art_buffers') == 1, f'one-buffer run reports {ob.get("art_buffers")} art buffer(s)')
        rows, exact_fail, compared = exact_covers(base, ob)
        failures.extend(exact_fail)
        notes.extend(rows)
        expect(compared >= 7 + len(EXACT_CAPTURES), f'only {compared} cover renders compared')
        totals = ob.get('display_stats', {})
        expect(totals.get('art_reuses') == 0 and totals.get('art_decodes', 0) > 0,
               f'no back buffer, so no reuse: totals {totals}')
        b, a = step('a2-swap', 'decode-b'), step('a2-swap', 'back-to-a')
        expect(b['art_decodes'] == 1 and a['art_decodes'] == 1 and a['art_reuses'] == 0,
               f'swap: each cover change decodes again in place: {b} / {a}')
        expect(art_at('a2-swap', 'back-to-a')['opa'] == 255, 'swap: the in-place decode is still instant')
        fail, other, again = (step('a2-decode-fail', l) for l in ('decode-fails', 'other-key', 'key-again'))
        expect(fail['art_decodes'] == 1 and fail['art_decode_errors'] == 1
               and not visible(art_at('a2-decode-fail', 'decode-fails')),
               f'decode fail: the shown buffer is overwritten in place, so the art hides: {fail}')
        expect(other['art_decodes'] == 1 and other['art_decode_errors'] == 0
               and visible(art_at('a2-decode-fail', 'other-key')),
               f'decode fail: the previous key is decoded again (its buffer was overwritten) and drawn: {other}')
        expect(again['art_decodes'] == 1 and again['art_decode_errors'] == 1, f'decode fail: retried after a key change: {again}')
        back = step('a2-slide-decode', 'slide-back')
        expect(back['art_decodes'] == 1 and back['art_reuses'] == 0 and back['render_ms'] == ob['sim_decode_ms'],
               f'slide back: decoded again in place: {back}')
        beats = 0
        for tid, t in timelines.items():
            for s in t['steps']:
                if s['expect'].get('identical'):
                    beats += 1
                    r = s['render']
                    if r['art_decodes'] or r['icon_loads'] or r['art_reuses'] or r['animations'] or r['text_sets'] \
                            or r['changed'] or r['redraw_flushes']:
                        failures.append(f'{tid} {s["label"]}: identical frame not inert: {r}')
        expect(beats >= 5, f'only {beats} identical steps')
        hb_rows, hb_fail = handback_rows(ob)
        failures.extend(hb_fail)
        notes.extend(hb_rows)
    except (KeyError, StopIteration, ValueError) as error:
        failures.append(f'missing one-buffer data: {error!r}')
    checks.add('a2_one_buffer', not failures,
               'cc_display_create(front, nullptr): covers decoded in place (exact pixels), no reuse, a failed '
               'in-place decode hides the art and the next key decodes again, identical frames inert, handback '
               'return decodes nothing', failures, notes=notes)


def enumerate_roles(layout):
    counters = {}
    for o in layout:
        k = counters.get(o['role'], 0)
        counters[o['role']] = k + 1
        yield k, o


def idle_items(objs):
    return sorted(k for k in objs if k.startswith('idle.item#'))


def contact_sheets(out: Path, index):
    font = ImageFont.truetype(str(FONT), 11) if FONT.is_file() else ImageFont.load_default()
    cases = [c for c in index['cases'] if c['kind'] in ('frame', 'notice')]
    sheet(out / 'contact-sheet.png', [(c['render']['file'], c['id']) for c in cases], font, columns=10,
          title=f'cc5 Stage 6 LVGL harness: {len(cases)} case renders (firmware renderer + parser, fixture art)')
    tiles = []
    for t in index['timelines']:
        for cpt in t['captures']:
            tiles.append((cpt['file'], f'{t["id"][:16]} {Path(cpt["file"]).stem}'))
    sheet(out / 'contact-sheet-timelines.png', tiles, font, columns=12,
          title=f'cc5 Stage 6 timelines on the fake tick: {len(tiles)} captures (name = t-step+offset ms)')


def sheet(path: Path, tiles, font, columns, title):
    size, gap, label = 240, 10, 16
    rows = (len(tiles) + columns - 1) // columns
    width = columns * (size + gap) + gap
    height = 30 + rows * (size + label + gap) + gap
    image = Image.new('RGB', (width, height), (28, 30, 32))
    draw = ImageDraw.Draw(image)
    draw.text((gap, 8), title, fill=(220, 220, 220), font=font)
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    ring = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((120 - SAFE_R, 120 - SAFE_R, 120 + SAFE_R, 120 + SAFE_R), outline=(53, 208, 192, 70))
    for i, (file, name) in enumerate(tiles):
        x = gap + (i % columns) * (size + gap)
        y = 30 + (i // columns) * (size + label + gap)
        render = Image.open(path.parent / file).convert('RGB')
        image.paste(render, (x, y), mask)
        image.paste(ring, (x, y), ring)
        draw.text((x, y + size + 2), name, fill=(200, 200, 200), font=font)
    image.save(path, optimize=True)
    print(f'wrote {path} ({len(tiles)} renders)')


if __name__ == '__main__':
    sys.exit(main(sys.argv))

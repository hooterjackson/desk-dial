"""cc5.4 LCD regression checks (PRESENTATION_V5.md section 15.3, gate A4) over the LVGL harness renders.

Reads <out>/render-index.json (main.cpp through build.py), the renders, <out>/full-layers (the
CC_DISPLAY_FULL_LAYERS=1 run) and <out>/one-buffer, and writes <out>/regression-checks-cc54.json
and <out>/contact-sheet-cc54.png. Geometry-independent helpers come from cc5_report.py (the cc5.3
report, whose v4 geometry no longer applies).

Checks:
  parse             every frames_v5.json input a cc5.4 parser accepts (v5.accept) and every
                    cc5_frames.json case was rendered; nothing rejected
  safe_circle       text/icon ink of the art-less renders inside r104; heading ink inside r112
  heading_fit       the six v5 headings verbatim at 1 px tracking; legacy headings follow the chain
                    (drop tracking, "RECENTLY ADDED · P{n}" -> "RECENT · P{n}", then U+2026)
  verbatim_text     every drawn line is the wire text or its prefix + U+2026 (no invented copy)
  ellipsis_honest   U+2026 only where the full wire text cannot fit its lines (chord oracle)
  label_bounds      no drawn line wider than its label box
  css_baselines     every 8.5.1 box on its CSS baseline +-1 px (derived from the design's CSS tops
                    and line heights with Montserrat's hhea metrics, not from the renderer)
  footer_static     footer centres 56/99/141/184, rows 154..173; identical footer pixels in every
                    capture of a screen change whose buttons do not change; the footer never
                    translates; ink crossfade 160 ms; [r2.2] heart + lit on draws heartfill in #A3244A
  idle_row          idle icons centred at 51/97/143/189, top 100; words centred, baseline 145;
                    every v7 Home label <= 46 px (a v6 "Play/Pause" is reported)
  seek_digits       cc_font_48t, tracking -1, baseline 116; 0 px jitter: identical pens for every
                    m:ss of the same length; ':' drawn; detents start no animation
  windows_geometry  Windows title top 98 / meta top 140 (label y 99 / 139); title line 2 ink
                    above the meta ink
  art_rules         art only on the 8.4 layouts, artDim 112, never translates; 240 ms show/hide;
                    instant swaps over a visible cover; late arrival fades 240 ms without delay
  slides            the 8.7 flip table; no slide on detents, Seek on/off, id or Home layout changes
  motion            key times of 8.8: content 220/380, reveal, idle stagger, footer 160/280+140,
                    meta/status fades 160, at the harness's 1 ms fake tick
  reduced_motion    reducedMotion true: no translate in any capture; content fade 220 ms
  twins             exactly the twelve twins: black, text_opa 204, +1 px, same text/visibility
  twin_fade         content/track/volume fades vs a group-composited reference: differences only
                    inside label ink boxes (none outside), identical at opacity 0/255; in-box
                    differences are classed by what lies under the ink: the cover, <= 28 levels
                    per channel (K1 erratum of lead ruling R-b: P5-13's 15 plus LVGL's
                    per-primitive RGB565 blending), or the label of another layer that is fading
                    in the same capture (the volume reveals: the caption over the home title),
                    <= 36 (K1 erratum of lead ruling R-g, which closes deviation WP1-D1)
  art_async         R5 (12.5.7 a-h) with a fake decoder that behaves as the shipped one (a
                    cancel stops the decode at the next of 15 MCU bands, 12.5.4 step 2, R-f) and
                    completes through cc_art_decode_result(); (h) one decode time plus at most one
                    band at 46 / 120 / 154 ms decodes; the result mapping over its domain
  offline           the offline layer: copy and line counts (8.10), geometry, entry/native/exit
                    timelines (native input through cc_offline_input_update), pins, no
                    native-screen frame
  copy              every cc54_copy.json string (VOC section 9 incl. the firmware-local offline
                    strings, CC5 15.2-15.3) in its element fits its App C limit whole and on the
                    line count its element specifies (placeholders and 8.6.11 exceptions
                    reported; a line-count miss goes to K3 copy approval, WP1-D3)
  icons             every 9.1 token/size drawn at least once, heartfill@20, dotfill@16
  v5_bounded        bounded layers render the same pixels as full-size layers (every capture)
  heartbeat         identical frames: no animation, no text set, nothing changed, no redraw
  latency           non-animated changes are presented at once (lv_refr_now)
  lcd_cadence       lcdLateRefrs / lcdMaxGapMs on the animation cadence (cc_anim_cadence_poll,
                    12.3): 0 late through every v5 tween at 16 ms, an injected stall counted;
                    cc_offline_input_update vectors (8.10 first native input)
  heap              LVGL heap peak <= 34 KB used (x64 pointers: an upper bound for the ESP32-S3)
  vectors           cc_presentation.h mmss / accent_ink / 5.2 tones == the frames_v5.json vectors,
                    and accent_ink / sat over a colour grid == presentation.py
  mirror_parity     lcd_preview.compose draws the same strings, baselines, pens, inks, icons and art
                    decisions as the harness for every case
  jpeg_glue, a2_*   the artwork2 checks (cc5_report.py) with the v5 fades and the twin shadow
                    pixels excluded from the exact-cover comparison

The report also records `deviations` (WP1-D1..D4): measured departures from the contracts that
need a firmware owner's change, a contract erratum or the user's acceptance, with options.

Usage: .venv python harness/cc54_report.py [out-dir]   (default cc54-handoff)
Exit status 1 when any check fails.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import cc5_report as base

ROOT = Path(__file__).resolve().parent
COMPANION = ROOT.parent / 'app'
FRAMES = COMPANION / 'tests' / 'fixtures' / 'cc5_frames.json'
FRAMES_V5 = COMPANION / 'tests' / 'fixtures' / 'frames_v5.json'
sys.path.insert(0, str(COMPANION))
from control_center import presentation  # noqa: E402

LAYOUTS = ['nowPlaying', 'volume', 'idle', 'recent', 'tracks', 'windows', 'notice', 'seek', 'explorer', 'upnext']
ART_LAYOUTS = {'nowPlaying', 'volume', 'recent', 'tracks', 'seek', 'explorer', 'upnext'}
SAFE_R, HEADING_R, INK = 104, 112, 12
FOOTER_CX = [56, 99, 141, 184]
IDLE_CX = [51, 97, 143, 189]
ELLIPSIS = '…'
HEAP_LIMIT = 34 * 1024
# PRESENTATION_V5 15.3 twin_fade after the K1 errata of lead rulings R-b (2026-09-25, 16.7 E-b) and
# R-g (2026-09-26, 16.8 E-g). R-b: <= 28 levels per 8-bit channel inside label ink boxes (P5-13's float
# model gives <= 15; LVGL blends the twin and then the label into the RGB565 framebuffer, each blend
# rounded to 5/6-bit channels, 26 measured over the cover). R-g: a per-class bound of 36 where the
# labels of two fading layers overlap -- the volume caption over the home title in both volume
# reveals (K1 8.8: two text layers fading over 150-190 ms; 35 measured), where the ink under the
# caption is title ink, not the dark composite. R-g closes deviation WP1-D1; both bounds are
# confirmed by eye in the hardware window (K1 15.4).
TWIN_FADE_LIMIT = 28
TWIN_FADE_OVERLAP_LIMIT = 36
TWIN_ROLES = ('heading', 'home.title', 'home.artist', 'volume.caption', 'volume.digits', 'volume.percent',
              'list.title', 'list.subtitle', 'tracks.title', 'tracks.subtitle', 'seek.caption', 'seek.time')
V5_HEADINGS = ('RECENTLY ADDED', 'RECENT', 'FAVOURITES', 'UP NEXT', 'TRACKS', 'SEEK')
HOME_LABELS = ('Play', 'Pause', 'Browse', 'Tracks', 'Win')
# K1 8.10 offline sub after the Desk Dial rename (rename-desk-dial.md C1, 5.2 and 11.5): the firmware's
# OFFLINE_SUB holds the name together with a no-break space (U+00A0), so the balanced split is
# `Open Desk Dial` / `on your PC` (LVGL 114 / 80 px), never `Open Desk` / `Dial on your PC`.
OFFLINE_SUB_TEXT = 'Open Desk Dial on your PC'
OFFLINE_SUB_LINES = ('Open Desk Dial', 'on your PC')

# Section 8.5.1 CSS line boxes (BS:284-325): role -> (CSS top, font px, CSS line height). The
# expected baseline is round(top + (lh - 1.219 em) / 2 + 0.968 em) (Montserrat hhea 968 / -251).
CSS = {
    'heading': (32, 12, 14), 'home.title': (60, 22, 26), 'home.artist': (114, 14, 18), 'status': (134, 12, 14),
    'volume.caption': (52, 14, 18), 'volume.digits': (76, 48, 46), 'volume.percent': (76, 48, 46),
    'list.title': (52, 22, 26), 'list.subtitle': (106, 14, 18), 'list.meta': (127, 12, 14),
    'tracks.title': (54, 22, 26), 'tracks.subtitle': (110, 14, 18), 'tracks.meta': (130, 12, 14),
    'seek.caption': (52, 14, 18), 'seek.time': (76, 48, 46), 'seek.line': (128, 14, 18),
    'windows.app': (80, 14, 18), 'windows.title': (98, 16, 20), 'windows.meta': (140, 12, 14),
    'offline.title': (70, 22, 26), 'offline.subtitle': (104, 14, 18), 'idle.word': (134, 12, 14),
}


def css_baseline(role):
    top, size, lh = CSS[role]
    return round(top + (lh - 1.219 * size) / 2 + 0.968 * size)


LABEL_SOURCES = dict(base.LABEL_SOURCES, **{'seek.caption': 'title', 'seek.line': 'meta'})
visible = base.visible
objects = base.objects
load_rgb = base.load_rgb


def labels_of(layout, include_twins=False):
    return [o for o in layout if o.get('type') == 'label' and (include_twins or not o['role'].endswith('.twin'))]


def roles(layout):
    """role -> list of objects (in dump order)."""
    out = {}
    for o in layout:
        out.setdefault(o['role'], []).append(o)
    return out


def first(layout, role):
    return next((o for o in layout if o['role'] == role), None)


def eff(o):
    return 0 if o is None or o['hidden'] else o['opa_eff']


def wire_heading_ok(wire, text, tracking):
    """Section 8.5.2 chain: the wire at 1 px (or 0 px) tracking; RECENTLY ADDED · P{n} -> RECENT · P{n};
    then a prefix + U+2026 at tracking 0."""
    if text == wire:
        return True
    if wire.startswith('RECENTLY ADDED · P') and text == 'RECENT · P' + wire.split(' · P', 1)[1]:
        return True
    if wire.startswith('RECENTLY ADDED · P') and base.verbatim([text], 'RECENT · P' + wire.split(' · P', 1)[1]):
        return tracking == 0
    return base.verbatim([text], wire) and tracking == 0


def label_ink_boxes(layout, pad=1):
    """(x1, y1, x2, y2) of every visible label line's ink (twins included), padded by `pad` px."""
    boxes = []
    for o in labels_of(layout, include_twins=True):
        if not visible(o):
            continue
        for line in o['lines']:
            if line.get('width') and 'ink_top' in line:
                boxes.append((line['x1'] - pad, line['ink_top'] - pad, line['x2'] + pad, line['ink_bottom'] + pad))
    return boxes


def in_boxes(boxes, x, y):
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in boxes)


# The labels each twin-fade probe layer carries (cc_display.cpp tree, section 8.2): `content` holds
# every label; `track` the home title and artist; `volume` the caption, digits and percent.
def in_fade_layer(role, layer):
    base_role = role[:-5] if role.endswith('.twin') else role
    if layer == 'content':
        return True
    if layer == 'track':
        return base_role in ('home.title', 'home.artist')
    if layer == 'volume':
        return base_role.startswith('volume.')
    raise ValueError(f'unknown twin-fade layer {layer!r}')


def fading(o):
    """A visible label whose effective opacity (its own times its ancestors', LVGL 9) is strictly
    between 0 and 255 in this capture: it is being faded. Every label at rest draws at 255."""
    return visible(o) and o['opa_eff'] < 255


def twin_fade_boxes(layout, layer):
    """(every visible label ink box, the probed layer's, the boxes of labels of ANOTHER layer that is
    fading in the same capture) for one twin_fade probe."""
    labels = labels_of(layout, include_twins=True)
    own = [o for o in labels if in_fade_layer(o['role'], layer)]
    other = [o for o in labels if not in_fade_layer(o['role'], layer) and fading(o)]
    return label_ink_boxes(layout), label_ink_boxes(own), label_ink_boxes(other)


def twin_fade_probe(actual, full, under, a, boxes, own_boxes, other_boxes):
    """One twin_fade probe: each pixel's largest channel |actual - group reference| (the layer drawn
    at opacity 255, blended at `a` over what lies below it), classed by where it lies: inside a
    label ink box ('cover'), inside a box of the probed layer that is also inside a box of another
    fading layer's label ('overlap'), or outside every label ink box ('out'). Per class: the worst
    (|d|, brightest channel under it, (x, y)) and the worst excess over P5-13's float model at the
    same pixel (0.8a(1 - a) x what lies under the ink)."""
    worst = {'cover': (0, 0, None), 'overlap': (0, 0, None)}
    excess = {'cover': 0.0, 'overlap': 0.0}
    worst_out = out_px = overlap_px = 0
    f = a / 255
    for idx in range(240 * 240):
        j = 3 * idx
        d = max(abs(actual[j + k] - round((a * full[j + k] + (255 - a) * under[j + k]) / 255)) for k in range(3))
        if not d:
            continue
        x, y = idx % 240, idx // 240
        if in_boxes(boxes, x, y):
            kind = 'overlap' if in_boxes(own_boxes, x, y) and in_boxes(other_boxes, x, y) else 'cover'
            overlap_px += kind == 'overlap'
            under_px = max(under[j:j + 3])
            if d > worst[kind][0]:
                worst[kind] = (d, under_px, (x, y))
            excess[kind] = max(excess[kind], round(d - 0.8 * f * (1 - f) * under_px, 1))
        else:
            worst_out = max(worst_out, d)
            out_px += 1
    return dict(worst, out=worst_out, out_px=out_px, overlap_px=overlap_px, excess=excess)


def twin_fade_fails(result):
    """K1 15.3 twin_fade after the R-b and R-g errata: TWIN_FADE_LIMIT for every pixel inside the label
    ink boxes over the cover, TWIN_FADE_OVERLAP_LIMIT (R-g) only where a label ink box of the probed
    layer overlaps one of another layer fading in the same capture (the volume reveals), and no
    difference at all outside the boxes ("pixels differ only inside label ink boxes"; 0 measured on
    every probe)."""
    return (result['cover'][0] > TWIN_FADE_LIMIT or result['overlap'][0] > TWIN_FADE_OVERLAP_LIMIT
            or result['out'] > 0)


def twin_fade_self_test():
    """Failures of the twin_fade classifier and verdict on synthetic probes (black layer, black under,
    so the group reference is 0 everywhere): where two fading labels overlap, 35 (the measured worst)
    and 36 pass and 37 fails (R-g); over the cover 28 passes and 29 fails (R-b); a 1-level
    difference outside the ink boxes fails; a label of a layer at rest (opa_eff 255) makes no
    overlap, so 35 there is the cover class and fails."""
    def label(role, x1, top, x2, bottom, opa_eff):
        return {'type': 'label', 'role': role, 'hidden': False, 'opa_eff': opa_eff,
                'lines': [{'width': x2 - x1 + 1, 'x1': x1, 'x2': x2, 'ink_top': top, 'ink_bottom': bottom}]}

    def probe(layout, pixels):
        actual = bytearray(240 * 240 * 3)
        for (x, y), d in pixels.items():
            actual[3 * (y * 240 + x)] = d
        zero = bytes(240 * 240 * 3)
        return twin_fade_probe(actual, zero, zero, 128, *twin_fade_boxes(layout, 'volume'))

    caption = label('volume.caption', 60, 50, 180, 64, 108)
    title_fading, title_rest = label('home.title', 40, 60, 200, 80, 95), label('home.title', 40, 60, 200, 80, 255)
    failures = []
    overlap = probe([caption, title_fading], {(100, 62): 35})
    if overlap['overlap'][0] != 35 or twin_fade_fails(overlap):
        failures.append(f'self-test: a 35-level overlap pixel must be class overlap and pass (R-g): {overlap}')
    at_bound = probe([caption, title_fading], {(100, 52): TWIN_FADE_LIMIT, (100, 62): TWIN_FADE_OVERLAP_LIMIT})
    if (twin_fade_fails(at_bound) or at_bound['cover'][0] != TWIN_FADE_LIMIT
            or at_bound['overlap'][0] != TWIN_FADE_OVERLAP_LIMIT):
        failures.append(f'self-test: {TWIN_FADE_LIMIT} over the cover and {TWIN_FADE_OVERLAP_LIMIT} where two fading '
                        f'labels overlap must pass: {at_bound}')
    over = probe([caption, title_fading], {(100, 62): TWIN_FADE_OVERLAP_LIMIT + 1})
    if over['overlap'][0] != TWIN_FADE_OVERLAP_LIMIT + 1 or not twin_fade_fails(over):
        failures.append(f'self-test: {TWIN_FADE_OVERLAP_LIMIT + 1} levels where two fading labels overlap must fail: '
                        f'{over}')
    cover_over = probe([caption, title_fading], {(100, 52): TWIN_FADE_LIMIT + 1})
    if cover_over['cover'][0] != TWIN_FADE_LIMIT + 1 or not twin_fade_fails(cover_over):
        failures.append(f'self-test: {TWIN_FADE_LIMIT + 1} levels over the cover must fail (R-g bounds the overlap '
                        f'class only): {cover_over}')
    rest_35 = probe([caption, title_rest], {(100, 62): 35})
    if rest_35['cover'][0] != 35 or not twin_fade_fails(rest_35):
        failures.append(f'self-test: 35 levels under a label of a layer at rest are the cover class and must fail: '
                        f'{rest_35}')
    outside = probe([caption], {(5, 5): 1})
    if outside['out'] != 1 or not twin_fade_fails(outside):
        failures.append(f'self-test: a 1-level difference outside the ink boxes must fail: {outside}')
    rest = probe([caption, title_rest], {(100, 62): 20})
    if rest['overlap'][0] != 0 or rest['cover'][0] != 20:
        failures.append(f'self-test: a label of a layer at rest (opa_eff 255) makes no overlap: {rest}')
    return failures


def label_box_mask(layout):
    """Pixels a text-shadow twin or an icon can touch: every visible label line's ink box (twins
    included, padded 1 px) and every visible A8 icon box (their inks may be crossfading). Excluded
    from the art-only comparisons (a twin darkens the cover where it lies)."""
    mask = bytearray(240 * 240)
    boxes = label_ink_boxes(layout)
    boxes += [(o['x1'], o['y1'], o['x2'], o['y2']) for o in layout
              if o.get('type') == 'image' and visible(o) and '@' in o.get('icon', '')]
    for x0, y0, x1, y1 in boxes:
        for y in range(max(0, y0), min(240, y1 + 1)):
            for x in range(max(0, x0), min(240, x1 + 1)):
                mask[y * 240 + x] = 1
    return mask


# ------------------------------------------------------------------ artwork2 --
def exact_covers_v5(base_dir: Path, idx):
    """cc5_report.exact_covers with the twin shadow pixels excluded: art-only pixels are black in
    the art-less render AND outside every label box (a twin darkens the cover where it lies)."""
    rows, failures, compared = [], [], 0
    by_id = {c['id']: c for c in idx['cases'] if c['kind'] == 'frame'}
    timelines = {t['id']: t for t in idx['timelines']}
    targets = [(c['id'], c['render']['file'], c['art_key'], c, c['render']['layout']) for c in by_id.values()
               if c.get('group') == 'artwork2' and c.get('art')]
    for tid, label, offset, key, case_id in base.EXACT_CAPTURES:
        try:
            cpt = base.find_capture(timelines[tid], label, offset)
            targets.append((f'{tid}/{label}+{offset}', cpt['file'], key, by_id[case_id], cpt['layout']))
        except (KeyError, ValueError) as error:
            failures.append(f'missing capture for the exact check: {error!r}')
    for name, file, key, case, layout in targets:
        raw = base.decoded_for(base_dir, idx, key)
        if raw is None:
            failures.append(f'{name}: no recorded decoder output for {key!r}')
            continue
        opa = base.ART_DIM_OPA if case['art_dim'] else 255
        twin = load_rgb(base_dir / case['noart']['file'])
        mask = label_box_mask(layout)
        pixels = [p for p in range(240 * 240) if not (twin[3 * p] or twin[3 * p + 1] or twin[3 * p + 2]) and not mask[p]]
        bad, worst = base.mismatches(load_rgb(base_dir / file), base.decoded_rgb(raw, opa), pixels)
        compared += 1
        rows.append(f'{name}: {key} {"x image_opa 112 " if opa < 255 else ""}{bad} of {len(pixels)} art-only px '
                    f'differ (max |d| {worst})')
        if bad or len(pixels) < 20000:
            failures.append(rows[-1])
    return rows, failures, compared


base.exact_covers = exact_covers_v5
# v5: a cover hidden by a failed decode shows again over 240 ms (section 8.4), so its exact pixels
# are compared once the fade is over.
base.EXACT_CAPTURES = (
    ('a2-swap', 'back-to-a', 0, 'a2-swap-a', 'a2-recent-den-dim'),           # back-buffer reuse (dim)
    ('a2-decode-fail', 'other-key', 300, 'a2-den', 'a2-np-den'),             # after a failed decode
    ('a2-slide-decode', 'slide-decode', 380, 'a2-slide', 'a2-recent-bright'),  # decoded during a slide
)


def tile_expectation(frame):
    """Section 5.3: (tile bg, initial ink) of a Windows letter tile."""
    ring = frame.get('ring') or {}
    colors = ring.get('colors') or []
    first_ = ring.get('first', presentation.window_first(ring.get('index', 0), ring.get('count', 0)))
    k = ring.get('index', 0) - first_
    accent = colors[k] if 0 <= k < len(colors) else 0
    s = presentation.sat_rgb(accent) if accent else None
    if s is not None:
        return f'#{s:06X}', '#FFFFFF'
    return '#444444', '#F2F2F2'


def artwork2_checks(checks, out, index, frames, timelines):
    cases = index['cases']
    frame_cases = [c for c in cases if c['kind'] == 'frame']
    a2 = [c for c in frame_cases if c.get('group') == 'artwork2']
    fixtures = Path(index['artwork2_fixtures'])
    manifest = json.loads((fixtures / 'manifest.json').read_text(encoding='utf-8'))
    covers = {e['name']: Image.open(fixtures / e['file']).convert('RGB') for e in manifest['covers']}
    icons = {e['name']: (fixtures / e['file']).read_bytes() for e in manifest['icons']}

    glue = index.get('jpeg_glue')
    src_ok = base.same_dir(index.get('firmware_src'), base.FIRMWARE_SRC)
    shim_ok = base.same_dir(index.get('tjpgd_shim'), base.TJPGD_SHIM)
    checks.add('jpeg_glue', glue == 'cc_jpeg.cpp' and src_ok and shim_ok,
               f'covers decoded by {glue!r}; built from {index.get("firmware_src")!r} '
               f'({"the real src/" if src_ok else "NOT the real src/"}) and {index.get("tjpgd_shim")!r}')

    rows, failures, compared = exact_covers_v5(out, index)
    checks.add('a2_cover_exact', not failures and compared >= 7 + len(base.EXACT_CAPTURES),
               f'{compared} cover renders: every art-only pixel (outside the label and twin boxes) equals '
               f'cc_jpeg_decode_240\'s output (artDim: LVGL mix at 112), 0 px differ', failures, covers=rows)

    failures, rows, combos, detail_seen = [], [], set(), False
    for c in [c for c in a2 if c.get('art')]:
        name, layout_name = c['art'], LAYOUTS[c['layout_id']]
        render, twin = load_rgb(out / c['render']['file']), load_rgb(out / c['noart']['file'])
        mask = label_box_mask(c['render']['layout'])
        art_only = [p for p in range(240 * 240) if not (twin[3 * p] or twin[3 * p + 1] or twin[3 * p + 2]) and not mask[p]]
        opa = base.ART_DIM_OPA if c['art_dim'] else 255
        reference = base.reference_565(covers[name].tobytes(), opa)
        db, db_luma, worst, count = base.psnr(render, reference, art_only)
        small = covers[name].resize((120, 120), Image.Resampling.LANCZOS).resize((240, 240), Image.Resampling.BILINEAR)
        _, trip_luma, _, _ = base.psnr(base.reference_565(small.tobytes(), opa), reference, art_only)
        art = base.by_role(c['render']['layout'])['art']
        rows.append(f'{c["id"]} ({layout_name}{", artDim" if c["art_dim"] else ""}): luma {db_luma:.1f} dB (120 px '
                    f'round trip {trip_luma:.1f}), RGB {db:.1f} dB over {count} px')
        combos.add((layout_name, bool(c['art_dim'])))
        if not visible(art) or art['opa_eff'] != 255 or art['image_opa'] != opa:
            failures.append(f'{c["id"]}: art visible {visible(art)}, opa {art["opa_eff"]}, image_opa {art["image_opa"]}')
        if db_luma < base.LUMA_PSNR_MIN_DB or db_luma <= trip_luma or db < base.RGB_PSNR_MIN_DB or count < 20000:
            failures.append(rows[-1])
        if name == 'a2-detail' and trip_luma >= base.DETAIL_ROUND_TRIP_MAX_DB:
            failures.append(f'{c["id"]}: the detail cover survives a 120 px round trip')
        detail_seen = detail_seen or name == 'a2-detail'
        stats, media = c['render']['stats'], c['render'].get('media') or {}
        if stats['art_upscales'] or stats['art_decode_errors']:
            failures.append(f'{c["id"]}: upscales/errors {stats}')
        if media.get('cover') != c['art_key']:
            failures.append(f'{c["id"]}: store pin {media.get("cover")!r}')
    want = {(l, d) for l in ('nowPlaying', 'recent', 'tracks') for d in (False, True)}
    missing = sorted(want - combos)
    checks.add('a2_cover_fullres', not failures and not missing and detail_seen,
               'JPEG covers on nowPlaying/recent/tracks x artDim vs a Pillow decode: luma >= 40 dB and above a '
               '120 px round trip, RGB >= 30 dB; decoded, never upscaled, pinned',
               failures + [f'missing {m}' for m in missing], covers=rows)

    failures, rows = [], []
    for c in a2:
        if c['layout_id'] == LAYOUTS.index('windows') or c.get('art'):
            continue
        art = base.by_role(c['render']['layout'])['art']
        stats, media = c['render']['stats'], c['render'].get('media') or {}
        failed = c['art_key'] in (c.get('commits') or [])
        rows.append(f'{c["id"]}: art {"shown" if visible(art) else "hidden"}, decodes {stats["art_decodes"]}, '
                    f'errors {stats["art_decode_errors"]}, pin {media.get("cover")!r}')
        if visible(art) or media.get('cover') is not None:
            failures.append(rows[-1])
        if failed and (stats['art_decodes'] != 1 or stats['art_decode_errors'] != 1):
            failures.append(f'{c["id"]}: expected exactly one failed decode')
    checks.add('a2_cover_none', not failures and len(rows) >= 2,
               f'{len(rows)} renders whose cover cannot be drawn show no art and hold no pin', failures, cases=rows)

    icon_fail, letter_fail, icon_rows, letters = [], [], [], []
    for c in frame_cases:
        if LAYOUTS[c['layout_id']] != 'windows':
            continue
        frame = frames.get(c['id']) or c.get('wire') or {}
        r = base.by_role(c['render']['layout'])
        icon, letter, tile = r.get('windows.icon'), r.get('windows.letter'), r.get('windows.tile')
        committed = c.get('commits') or []
        want_icon = bool(c.get('icon_key')) and c['icon_key'] in committed
        shown = bool(icon) and visible(icon)
        if want_icon != shown:
            icon_fail.append(f'{c["id"]}: icon {"shown" if shown else "not shown"}')
            continue
        if shown:
            closed = tile['opa'] == base.TILE_CLOSED_OPA
            data = load_rgb(out / c['render']['file'])
            expected = base.payload_rgb(icons[c['icon_key']])
            worst = 0
            for k, (er, eg, eb) in enumerate(expected):
                x, y = base.TILE_BOX[0] + k % 32, base.TILE_BOX[1] + k // 32
                i = (y * 240 + x) * 3
                if closed:
                    er, eg, eb = (round(v * base.TILE_CLOSED_OPA / 255) for v in (er, eg, eb))
                worst = max(worst, abs(data[i] - er), abs(data[i + 1] - eg), abs(data[i + 2] - eb))
            box = (icon['x1'], icon['y1'], icon['x2'], icon['y2'])
            icon_rows.append(f'{c["id"]}: {c["icon_key"]} at {box}, opa {icon["opa_eff"]}, max |d| {worst}'
                             f'{" x 89/255" if closed else ""}')
            if box != base.TILE_BOX or worst > (base.CLOSED_TOLERANCE if closed else 0) or \
                    (letter and visible(letter)) or 'bg' in tile:
                icon_fail.append(icon_rows[-1])
            continue
        subtitle = frame.get('subtitle', '')
        want = base.tile_initial(subtitle)
        text = letter['text'] if letter and visible(letter) else ''
        tile_shown = bool(tile) and visible(tile)
        bg, initial = tile_expectation(frame)
        letters.append(f'{subtitle[:12]!r}->{text!r} on {tile.get("bg") if tile else None}')
        if text != want or tile_shown != bool(subtitle) or (tile_shown and (tile.get('bg') != bg or
                                                                             (letter and letter['color'] != initial))):
            letter_fail.append(f'{c["id"]}: subtitle {subtitle!r}: letter {text!r} (want {want!r}) ink '
                               f'{letter and letter["color"]} (want {initial}), tile bg {tile.get("bg") if tile else None} '
                               f'(want {bg})')
    checks.add('a2_icon', not icon_fail and len(icon_rows) >= 3 and any('89/255' in r for r in icon_rows),
               f'{len(icon_rows)} app icon renders (payload pixels exact open, x 0.35 closed)', icon_fail, icons=icon_rows)
    checks.add('a2_letter', not letter_fail and len(letters) > 20 and any('#444444' not in l and 'None' not in l
                                                                          for l in letters),
               f'{len(letters)} letter tiles: first code point (ASCII a-z upper-cased); tile sat(accent) with a '
               f'#FFFFFF initial when the selected entry has an accent, else #444 / #F2F2F2 (section 5.3)',
               letter_fail, samples=sorted(set(letters))[:40])

    failures, pinned = [], 0
    for c in frame_cases:
        r = base.by_role(c['render']['layout'])
        media, twin_media = c['render'].get('media') or {}, c['noart'].get('media') or {}
        committed = c.get('commits') or []
        art, icon = r.get('art'), r.get('windows.icon')
        want_cover = c['art_key'] if art and visible(art) and c['art_key'] in committed else None
        want_icon = c.get('icon_key') if icon and visible(icon) else None
        pinned += bool(want_cover) + bool(want_icon)
        if media.get('cover') != want_cover or media.get('icon') != want_icon or twin_media.get('cover') is not None:
            failures.append(f'{c["id"]}: pins {media} (twin {twin_media}); want {want_cover!r} / {want_icon!r}')
    checks.add('a2_media_pins', not failures and pinned > 0,
               f'{len(frame_cases)} case renders: the store pins exactly the cover and icon drawn from it ({pinned} pins)',
               failures)

    failures, beats = [], 0
    for tid, t in timelines.items():
        if not tid.startswith('a2-'):
            continue
        for s in t['steps']:
            if not s['expect'].get('identical'):
                continue
            beats += 1
            r = s['render']
            if r['art_decodes'] or r['icon_loads'] or r['art_reuses'] or r['art_decode_errors'] or r['animations'] \
                    or r['text_sets'] or r['changed'] or r['redraw_flushes']:
                failures.append(f'{tid} t={s["t"]} {s["label"]}: {r}')
    checks.add('a2_heartbeat', not failures and beats >= 5,
               f'{beats} identical artwork2 frames: no decode, icon copy, swap, animation, text set or redraw', failures)

    failures, notes = [], []

    def expect(cond, message):
        if not cond:
            failures.append(message)

    def step(tid, label):
        return next(s for s in timelines[tid]['steps'] if s['label'] == label)

    def cap(tid, label, offset):
        cpt = base.find_capture(timelines[tid], label, offset)
        return base.by_role(cpt['layout']), cpt

    try:
        before, _ = cap('a2-icon-late', 'letter-meanwhile', 0)
        arrived, arrived_cpt = cap('a2-icon-late', 'icon-arrives', 0)
        r = step('a2-icon-late', 'icon-arrives')['render']
        expect(visible(before['windows.letter']) and not visible(before['windows.icon']), 'icon late: letter first')
        expect(visible(arrived['windows.icon']) and not visible(arrived['windows.letter']), 'icon late: icon at +0')
        expect(r['icon_loads'] == 1 and r['animations'] == 0 and r['redraw_flushes'] > 0,
               f'icon late: one copy, no animation, redrawn at once: {r}')
        waiting, _ = cap('a2-cover-late', 'key-without-pixels', 0)
        expect(not visible(waiting['art']), 'cover late: nothing drawn before the JPEG is committed')
        opas = {o: cap('a2-cover-late', 'cover-arrives', o)[0]['art']['opa'] for o in (0, 60, 120, 240, 270)}
        expect(opas[0] == 0 and 0 < opas[60] < 255 and 0 < opas[120] < 255 and opas[240] == 255 and opas[270] == 255,
               f'cover late: 240 ms OUT fade from +0, no delay (section 8.4, P5-R3): {opas}')
        notes.append(f'late JPEG cover opacity at +0/+60/+120/+240/+270: {list(opas.values())}')
        b, a = step('a2-swap', 'decode-b')['render'], step('a2-swap', 'back-to-a')['render']
        expect(b['art_decodes'] == 1 and a['art_reuses'] == 1 and a['art_decodes'] == 0, f'swap/reuse: {b} / {a}')
        for label in ('decode-b', 'back-to-a'):
            expect(cap('a2-swap', label, 0)[0]['art']['opa'] == 255, f'swap: {label} instant')
        fail = step('a2-decode-fail', 'decode-fails')['render']
        other = step('a2-decode-fail', 'other-key')['render']
        again = step('a2-decode-fail', 'key-again')['render']
        expect(fail['art_decode_errors'] == 1 and not visible(cap('a2-decode-fail', 'decode-fails', 0)[0]['art']),
               f'decode fail hides: {fail}')
        expect(other['art_decodes'] == 0 and cap('a2-decode-fail', 'other-key', 0)[0]['art']['opa'] == 0
               and cap('a2-decode-fail', 'other-key', 300)[0]['art']['opa'] == 255,
               f'decode fail: the previous cover (still in the front buffer) shows again over 240 ms: {other}')
        expect(again['art_decodes'] == 1 and again['art_decode_errors'] == 1, f'decode fail: retried after a key change: {again}')
        slide = step('a2-heartbeat', 'windows')['render']
        expect(slide['last_slide'] == 20 and slide.get('media') == {'cover': None, 'icon': 'ic-code'},
               f'Home -> Windows slides +20 and releases the cover pin: {slide}')
        for label, want in (('unrelated-commit-home', {'cover': 'a2-den', 'icon': None}),
                            ('unrelated-commit-windows', {'cover': None, 'icon': 'ic-code'})):
            s = step('a2-heartbeat', label)
            expect(s['expect'].get('identical') and s['render'].get('media') == want, f'{label}: {s["render"].get("media")}')
        sim = index['sim_decode_ms']
        sd, sb = step('a2-slide-decode', 'slide-decode')['render'], step('a2-slide-decode', 'slide-back')['render']
        at = {o: cap('a2-slide-decode', 'slide-decode', o)[0] for o in (0, 60, 110, 220, 380)}
        expect(sd['render_ms'] == sim and sd['art_decodes'] == 1 and sd['last_slide'] == 20, f'decode + slide: {sd}')
        expect(at[0]['content']['tx'] == 20 and at[0]['content']['opa'] == 0 and at[220]['content']['opa'] == 255
               and at[380]['content']['tx'] == 0 and 0 < at[60]['content']['tx'] < 20,
               'decode + slide: the content slide and fade start at their beginning after a 150 ms decode')
        expect(at[0]['art']['opa'] == 255 and at[0]['art']['tx'] == 0, 'decode + slide: the new cover is swapped in at once')
        expect(sb['art_reuses'] == 1 and sb['art_decodes'] == 0 and sb['last_slide'] == -20, f'slide back: {sb}')
    except (KeyError, StopIteration, ValueError) as error:
        failures.append(f'missing artwork2 timeline data: {error!r}')
    checks.add('a2_timelines', not failures, 'late icon instant; late JPEG cover 240 ms fade; swap/reuse; decode '
                                            'failure; pins; a decode never shortens a screen change', failures, notes=notes)

    rows, failures = base.handback_rows(index)
    checks.add('a2_handback', not failures and len(rows) == len(base.HANDBACK_EXPECT),
               'cc_display_release_media() releases the pins; the return re-pins and decodes nothing', failures, steps=rows)
    one_buffer_checks(checks, out)


def one_buffer_checks(checks, out: Path):
    """cc5_report.one_buffer_checks with the v5 cover fades (a re-shown cover fades in 240 ms)."""
    ob_dir = out / 'one-buffer'
    path = ob_dir / 'render-index.json'
    if not path.is_file():
        checks.add('a2_one_buffer', False, f'{path} missing: rebuild with build.py (it runs main.cpp --one-buffer)')
        return
    ob = json.loads(path.read_text(encoding='utf-8'))
    failures, notes = [], []

    def expect(cond, message):
        if not cond:
            failures.append(message)

    try:
        tl = {t['id']: t for t in ob['timelines']}

        def step(tid, label):
            return next(s for s in tl[tid]['steps'] if s['label'] == label)['render']

        def art_at(tid, label, offset=0):
            return base.by_role(base.find_capture(tl[tid], label, offset)['layout'])['art']

        expect(ob.get('art_buffers') == 1, f'one-buffer run reports {ob.get("art_buffers")} art buffer(s)')
        rows, exact_fail, compared = exact_covers_v5(ob_dir, ob)
        failures.extend(exact_fail)
        notes.extend(rows)
        expect(compared >= 7 + len(base.EXACT_CAPTURES), f'only {compared} cover renders compared')
        totals = ob.get('display_stats', {})
        expect(totals.get('art_reuses') == 0 and totals.get('art_decodes', 0) > 0, f'no reuse: {totals}')
        b, a = step('a2-swap', 'decode-b'), step('a2-swap', 'back-to-a')
        expect(b['art_decodes'] == 1 and a['art_decodes'] == 1 and a['art_reuses'] == 0, f'in-place decodes: {b} / {a}')
        expect(art_at('a2-swap', 'back-to-a')['opa'] == 255, 'swap: the in-place decode is still instant')
        fail, other, again = (step('a2-decode-fail', label) for label in ('decode-fails', 'other-key', 'key-again'))
        expect(fail['art_decodes'] == 1 and fail['art_decode_errors'] == 1
               and not visible(art_at('a2-decode-fail', 'decode-fails')),
               f'decode fail: the overwritten buffer hides the art: {fail}')
        expect(other['art_decodes'] == 1 and other['art_decode_errors'] == 0
               and art_at('a2-decode-fail', 'other-key', 300)['opa'] == 255,
               f'decode fail: the previous key is decoded again in place and shown (240 ms): {other}')
        expect(again['art_decodes'] == 1 and again['art_decode_errors'] == 1, f'retried after a key change: {again}')
        back = step('a2-slide-decode', 'slide-back')
        expect(back['art_decodes'] == 1 and back['art_reuses'] == 0 and back['render_ms'] == ob['sim_decode_ms'],
               f'slide back decodes again in place: {back}')
        beats = 0
        for tid, tline in tl.items():
            for s in tline['steps']:
                if s['expect'].get('identical'):
                    beats += 1
                    r = s['render']
                    if (r['art_decodes'] or r['icon_loads'] or r['art_reuses'] or r['animations'] or r['text_sets']
                            or r['changed'] or r['redraw_flushes']):
                        failures.append(f'{tid} {s["label"]}: identical frame not inert: {r}')
        expect(beats >= 5, f'only {beats} identical steps')
        hb_rows, hb_fail = base.handback_rows(ob)
        failures.extend(hb_fail)
        notes.extend(hb_rows)
    except (KeyError, StopIteration, ValueError) as error:
        failures.append(f'missing one-buffer data: {error!r}')
    checks.add('a2_one_buffer', not failures,
               'cc_display_create(front, nullptr): covers decoded in place (exact pixels), no reuse, a failed in-place '
               'decode hides the art and the next key decodes again, identical frames inert, handback return decodes '
               'nothing', failures, notes=notes)


# ---------------------------------------------------------------------- main --
def main(argv) -> int:
    out = Path(argv[1]) if len(argv) > 1 else ROOT / 'cc54-handoff'
    index = json.loads((out / 'render-index.json').read_text(encoding='utf-8'))
    cc5 = json.loads(FRAMES.read_text(encoding='utf-8'))
    v5 = json.loads(FRAMES_V5.read_text(encoding='utf-8'))
    frames = {c['id']: c['frame'] for c in cc5['cases']}
    checks = base.Checks()
    deviations = []   # recorded deviations from the contracts (WP1-Dn), with measured values and options
    cases = index['cases']
    by_id = {c['id']: c for c in cases}
    frame_cases = [c for c in cases if c['kind'] == 'frame']
    drawn_cases = [c for c in cases if c['kind'] in ('frame', 'offline')]
    timelines = {t['id']: t for t in index['timelines']}

    def wire(c):
        return frames.get(c['id']) or c.get('wire') or {}

    # parse ----------------------------------------------------------------------
    accepted = [c['name'] for c in v5['cases'] if c['v5']['accept']]
    missing = [n for n in accepted if f'v5.{n}' not in by_id] + [c['id'] for c in cc5['cases'] if c['id'] not in by_id]
    rejected = [c['id'] for c in cases if c['kind'] == 'rejected']
    checks.add('parse', not missing and not rejected and index['rejected_frames'] == 0,
               f'{len(accepted)} frames_v5.json inputs a cc5.4 parser accepts and {len(cc5["cases"])} cc5_frames.json '
               f'cases rendered through cc_parse_frame (+{sum(1 for c in cases if c["group"] in ("v5syn", "synthetic"))} '
               f'harness frames); {len(rejected)} rejected, {len(missing)} missing',
               [f'missing {m}' for m in missing] + [f'rejected {r}' for r in rejected])

    # safe circle ------------------------------------------------------------------
    ring = [(x, y, math.hypot(x + 0.5 - 120, y + 0.5 - 120)) for y in range(240) for x in range(240)]
    beyond = [(x, y, r) for x, y, r in ring if r > SAFE_R]
    failures, heading_uses, worst = [], 0, 0.0
    for c in drawn_cases:
        data = load_rgb(out / c['noart']['file'])
        layout = c['noart']['layout']
        heading = first(layout, 'heading')
        rows_ok = set()
        if heading and visible(heading):
            rows_ok = set(range(heading['y1'] - 1, heading['y2'] + 3))
        bad = []
        for x, y, r in beyond:
            if base.ink_at(data, x, y) <= INK:
                continue
            worst = max(worst, r)
            if r <= HEADING_R and y in rows_ok:
                heading_uses += 1
                continue
            bad.append((x, y, r))
        if bad:
            w = max(bad, key=lambda p: p[2])
            failures.append(f'{c["id"]}: {len(bad)} ink px beyond r{SAFE_R} (heading rows allow r{HEADING_R}), worst '
                            f'r={w[2]:.1f} at {w[:2]}')
    checks.add('safe_circle', not failures,
               f'{len(drawn_cases)} art-less renders: text and icon ink inside r{SAFE_R}, heading ink inside r{HEADING_R} '
               f'({heading_uses} heading px between r104 and r112; worst radius {worst:.1f})', failures)

    # heading fit --------------------------------------------------------------------
    failures, seen = [], {}
    for c in frame_cases:
        w = wire(c).get('heading', '')
        h = first(c['render']['layout'], 'heading')
        if not w:
            if h and visible(h):
                failures.append(f'{c["id"]}: heading {h["text"]!r} without a wire heading')
            continue
        text, tracking = (h['text'], h['letter_space']) if h and visible(h) else ('', None)
        seen.setdefault(w, set()).add((text, tracking))
        if w in V5_HEADINGS:
            if text != w or tracking != 1:
                failures.append(f'{c["id"]}: v5 heading {w!r} drawn {text!r} at tracking {tracking}')
        elif not wire_heading_ok(w, text, tracking):
            failures.append(f'{c["id"]}: legacy heading {w!r} drawn {text!r} at tracking {tracking}')
    for c in index.get('copy', []):
        if c['element'] != 'heading':
            continue
        h = c['labels'][0] if c['labels'] else None
        if not h or h['text'] != c['text'] or h['letter_space'] != 1 or h['lines'][0]['width'] > 138:
            failures.append(f'copy {c["id"]}: {h and h["text"]!r} tracking {h and h["letter_space"]}')
    missing_v5 = [hd for hd in V5_HEADINGS if hd not in seen]
    checks.add('heading_fit', not failures and not missing_v5,
               'headings: ' + '; '.join(f'{w!r} -> {sorted(v, key=str)}' for w, v in sorted(seen.items())),
               failures + [f'v5 heading {m!r} never rendered' for m in missing_v5])

    # verbatim text + label bounds + ellipsis ------------------------------------------
    failures, bounds_fail, counted = [], [], 0
    for c in frame_cases:
        frame = wire(c)
        layout = c['render']['layout']
        for role, field in LABEL_SOURCES.items():
            for o in objects(layout, role):
                lines = [l['text'] for l in o['lines']]
                counted += 1
                if not base.verbatim(lines, frame.get(field, '')):
                    failures.append(f'{c["id"]} {role}: {lines!r} vs wire {frame.get(field, "")!r}')
        cap = next(iter(objects(layout, 'volume.caption')), None)
        if cap and not base.verbatim([l['text'] for l in cap['lines']], frame.get('volumeCaption') or frame.get('title', '')):
            failures.append(f'{c["id"]} volume.caption: {cap["text"]!r}')
        for o in labels_of(layout):
            if visible(o) and o['role'] not in ('volume.digits', 'volume.percent'):
                for l in o['lines']:
                    if l['width'] and (l['x1'] < o['x1'] or l['x2'] > o['x2']):
                        bounds_fail.append(f'{c["id"]} {o["role"]}: line {l["text"]!r} {l["x1"]}..{l["x2"]} '
                                           f'outside box {o["x1"]}..{o["x2"]}')
    checks.add('verbatim_text', not failures, f'{counted} drawn labels equal the wire text or its prefix + U+2026', failures)
    checks.add('label_bounds', not bounds_fail, 'every drawn line fits its label box', bounds_fail)

    failures, labels_n, ellipsized, fit_cases = [], 0, [], []
    for c in frame_cases:
        frame = wire(c)
        for pass_name in ('noart', 'render'):
            ordinals = {}
            for o in labels_of(c[pass_name]['layout']):
                ordinal = ordinals.get(o['role'], 0)
                ordinals[o['role']] = ordinal + 1
                if 'fit' not in o or not visible(o):
                    continue
                fit, lines = o['fit'], [l['text'] for l in o['lines']]
                source = fit['source']
                labels_n += 1
                whole = source in base.joined(lines)
                ends = bool(lines) and lines[-1].endswith(ELLIPSIS)
                over = [f'line {k} {l["width"]} > {fit["capacity"][k]}' for k, l in enumerate(o['lines'])
                        if k < len(fit['capacity']) and l['width'] > fit['capacity'][k]]
                where = f'{c["id"]} {pass_name} {o["role"]}'
                if over:
                    failures.append(f'{where}: {lines!r} wider than the chord capacity ({", ".join(over)})')
                if fit['fits'] and not whole:
                    failures.append(f'{where}: {lines!r} although {source!r} fits {fit["capacity"]}')
                elif not fit['fits'] and not (ends and not whole and base.verbatim(lines, source)):
                    failures.append(f'{where}: {lines!r} for {source!r}: expected a prefix + U+2026')
                if pass_name == 'render' and ends and not whole:
                    ellipsized.append(f'{c["id"]} {o["role"]}: {" / ".join(lines)!r}')
                if pass_name == 'render' and base.FIT_CASES.get(c['id'], (None,))[0] == o['role']:
                    want = base.FIT_CASES[c['id']][1]
                    fit_cases.append(f'{c["id"]}: {" / ".join(lines)!r}')
                    if fit['fits'] != want or not (whole if want else (ends and not whole)):
                        failures.append(f'{c["id"]} {o["role"]}: {lines!r}, fits {fit["fits"]}')
    checks.add('ellipsis_honest', not failures and labels_n > 0 and len(fit_cases) == len(base.FIT_CASES),
               f'{labels_n} frame-driven labels: U+2026 only where the text cannot fit ({len(ellipsized)} ellipsized); '
               f'{len(fit_cases)}/{len(base.FIT_CASES)} harness fitting cases', failures, ellipsized=ellipsized)

    # CSS baselines -------------------------------------------------------------------
    failures, measured = [], {}
    for c in drawn_cases:
        for o in labels_of(c['render']['layout']):
            if not visible(o) or o['role'] not in CSS:
                continue
            got = o['lines'][0]['baseline'] - o['ty']
            want = css_baseline(o['role'])
            measured.setdefault(o['role'], set()).add(got)
            if abs(got - want) > 1:
                failures.append(f'{c["id"]} {o["role"]}: baseline {got} vs CSS {want}')
    missing_roles = sorted(set(CSS) - set(measured))
    checks.add('css_baselines', not failures and not missing_roles,
               'baselines vs the CSS line boxes: ' + ', '.join(f'{r} {sorted(v)}/{css_baseline(r)}'
                                                             for r, v in sorted(measured.items())),
               failures + [f'role {r} never drawn' for r in missing_roles])

    # footer ----------------------------------------------------------------------------
    failures, footers, liked = [], 0, 0
    for c in frame_cases:
        foot = [o for o in c['noart']['layout'] if o['role'] == 'footer.icon']
        for slot, o in enumerate(foot):
            if not visible(o):
                continue
            footers += 1
            cx = (o['x1'] + o['x2'] + 1) / 2
            if cx != FOOTER_CX[slot] or o['y1'] != 154 or o['y2'] != 173:
                failures.append(f'{c["id"]} slot {slot}: centre {cx} rows {o["y1"]}..{o["y2"]}')
        buttons = wire(c).get('buttons') or []
        for slot, b in enumerate(buttons):
            if isinstance(b, dict) and b.get('icon') == 'heart' and b.get('lit') == 'on' and b.get('enabled'):
                liked += 1
                o = foot[slot] if slot < len(foot) else None
                if not o or o.get('icon') != 'heartfill@20' or o.get('recolor') != '#A3244A':
                    failures.append(f'{c["id"]}: liked heart drawn as {o and o.get("icon")} in {o and o.get("recolor")}')
    t = timelines.get('v5-footer-static')
    static_rows = []
    for k, s in enumerate(t['steps'] if t else [], start=1):
        if not s['expect'].get('footerStatic'):
            continue
        crops = [(cpt['offset'], Image.open(out / cpt['file']).convert('RGB').crop((44, 152, 196, 176)).tobytes())
                 for cpt in t['captures'] if cpt['step'] == k]
        same = len({data for _, data in crops}) == 1
        static_rows.append(f'{s["label"]}: {len(crops)} captures, footer pixels identical {same}')
        if not same or len(crops) < 5:
            failures.append(static_rows[-1])
    for tid, tl in timelines.items():
        for cpt in tl['captures']:
            f = first(cpt['layout'], 'footer')
            if f and (f['tx'] or f['ty']):
                failures.append(f'{tid} {cpt["file"]}: footer translated {f["tx"]},{f["ty"]}')
            step_ = tl['steps'][cpt['step'] - 1]
            idle_step = step_.get('layout') == LAYOUTS.index('idle') or (step_.get('layout') == LAYOUTS.index('volume')
                                                                          and step_.get('rest_layout') == LAYOUTS.index('idle'))
            if f and step_['expect'].get('slide') and not idle_step and f['opa'] != 255:
                failures.append(f'{tid} {cpt["file"]}: footer opacity {f["opa"]} during a screen change')
    ink_rows = []
    try:
        tl = timelines['v5-ink']
        for label, slot, old, new in (('like-lands', 2, '#E6E6E6', '#A3244A'), ('shuffle-on', 1, '#7A7A7A', '#FFFFFF')):
            inks = {}
            for off in (0, 40, 80, 120, 160, 200):
                cpt = base.find_capture(tl, label, off)
                foot = [o for o in cpt['layout'] if o['role'] == 'footer.icon']
                inks[off] = (foot[slot]['recolor'], foot[slot]['icon'])
            ink_rows.append(f'{label} slot {slot}: {inks}')
            mid = inks[80][0]
            if inks[0][0] != old or inks[160][0] != new or mid in (old, new):
                failures.append(f'{label}: ink {old} -> {new} over 160 ms: {inks}')
            if label == 'like-lands' and inks[0][1] != 'heartfill@20':
                failures.append(f'like-lands: the glyph swap is not instant: {inks[0][1]} at +0')
    except (KeyError, ValueError) as error:
        failures.append(f'v5-ink timeline: {error!r}')
    checks.add('footer_static', not failures and footers > 0 and liked >= 2 and len(static_rows) >= 2,
               f'{footers} footer icons at x {FOOTER_CX}, rows 154..173; {liked} liked hearts drawn heartfill #A3244A; '
               f'footer never translates, opaque during screen changes', failures, static=static_rows, inks=ink_rows)

    # idle row -----------------------------------------------------------------------------
    failures, idle_n, reported = [], 0, []
    for c in frame_cases:
        if LAYOUTS[c['layout_id']] != 'idle':
            continue
        idle_n += 1
        layout = c['render']['layout']
        icons_ = [o for o in layout if o['role'] == 'idle.icon']
        words = [o for o in layout if o['role'] == 'idle.word']
        for i, (icon, word) in enumerate(zip(icons_, words)):
            if not visible(icon):
                continue
            cx = (icon['x1'] + icon['x2'] + 1) / 2
            if cx != IDLE_CX[i] or icon['y1'] != 100 or icon['y2'] != 125:
                failures.append(f'{c["id"]} item {i}: icon centre {cx}, rows {icon["y1"]}..{icon["y2"]}')
            line = word['lines'][0]
            wcx = (line['x1'] + line['x2'] + 1) / 2
            if abs(wcx - IDLE_CX[i]) > 1 or line['baseline'] != 145:
                failures.append(f'{c["id"]} word {i} {line["text"]!r}: centre {wcx}, baseline {line["baseline"]}')
    widths = {}
    for c in index.get('copy', []):
        if c['element'] != 'idle_word' or not c['labels']:
            continue
        line = c['labels'][0]['lines'][0]
        widths[c['text']] = (line['text'], line['width'])
        if c['text'] in HOME_LABELS and (line['text'] != c['text'] or line['width'] > 46):
            failures.append(f'Home label {c["text"]!r} drawn {line["text"]!r} ({line["width"]} px > 46)')
        elif c['text'] not in HOME_LABELS:
            reported.append(f'{c["text"]!r} -> {line["text"]!r} ({line["width"]} px): {c.get("exception", "")}')
    missing_labels = [l for l in HOME_LABELS if l not in widths]
    checks.add('idle_row', not failures and idle_n > 0 and not missing_labels,
               f'{idle_n} idle renders; v7 Home labels ' + ', '.join(f'{k} {v[1]} px' for k, v in widths.items()
                                                                  if k in HOME_LABELS),
               failures + [f'label {l!r} not measured' for l in missing_labels], reported=reported)

    # Seek digits ---------------------------------------------------------------------------
    failures, samples = [], []
    groups = {}
    for source, layout, file in ([(c['id'], c['render']['layout'], c['render']['file']) for c in frame_cases] +
                                 [(f'{tid}/{cpt["file"]}', cpt['layout'], cpt['file'])
                                  for tid, tl in timelines.items() for cpt in tl['captures']]):
        o = first(layout, 'seek.time')
        if not o or not visible(o) or not o['text']:
            continue
        line = o['lines'][0]
        samples.append(o['text'])
        if o['font_name'] != 'cc_font_48t' or o['letter_space'] != -1 or line['baseline'] - o['ty'] != 116:
            failures.append(f'{source}: {o["text"]!r} font {o["font_name"]}, tracking {o["letter_space"]}, '
                            f'baseline {line["baseline"]}')
        groups.setdefault(len(o['text']), {}).setdefault((line['x1'], tuple(line['pens'])), set()).add(o['text'])
        if o['text'] in ('0:00', '1:14', '999:58') and file.endswith('.png') and '/' not in source:
            data = load_rgb(out / file)
            colon_x = line['pens'][o['text'].index(':')]
            if not any(base.ink_at(data, x, y) > 128 for x in range(colon_x, colon_x + 11) for y in range(81, 117)):
                failures.append(f'{source}: no ":" ink at x {colon_x}')
    jitter = {n: len(cells) for n, cells in groups.items()}
    for n, cells in groups.items():
        if len(cells) != 1:
            failures.append(f'{n}-character times use {len(cells)} different digit cells: '
                            f'{[(k[0], sorted(v)[:3]) for k, v in cells.items()]}')
    for need in (4, 5, 6):
        texts = set().union(*groups.get(need, {None: set()}).values()) if need in groups else set()
        if len(texts) < 2:
            failures.append(f'fewer than two distinct {need}-character times drawn')
    seek_steps = timelines.get('v5-seek', {}).get('steps', [])
    moving = [s['label'] for s in seek_steps[1:] if s['render']['animations'] or s['render']['screen_change']]
    if moving:
        failures.append(f'Seek detents animated: {moving}')
    checks.add('seek_digits', not failures and len(samples) > 20,
               f'{len(set(samples))} distinct Seek times: cc_font_48t, tracking -1, baseline 116; digit cells per '
               f'length {jitter} (1 = 0 px jitter); ":" drawn; detents start no animation', failures)

    # Windows geometry -----------------------------------------------------------------------
    failures, pairs = [], []
    for c in frame_cases:
        layout = c['noart']['layout']
        title, meta = first(layout, 'windows.title'), first(layout, 'windows.meta')
        if title and visible(title) and title['y1'] != 99:
            failures.append(f'{c["id"]}: windows.title y {title["y1"]} (CSS top 98 -> 99)')
        if meta and visible(meta) and meta['y1'] != 139:
            failures.append(f'{c["id"]}: windows.meta y {meta["y1"]} (CSS top 140 -> 139)')
        if not (title and meta and visible(title) and visible(meta)):
            continue
        last, m = title['lines'][-1], meta['lines'][0]
        if 'ink_bottom' in last and 'ink_top' in m:
            gap = m['ink_top'] - last['ink_bottom'] - 1
            pairs.append(f'{c["id"]}: {len(title["lines"])} lines, gap {gap}')
            if gap < 0:
                failures.append(pairs[-1])
    checks.add('windows_geometry', not failures and any(': 2 lines' in p for p in pairs),
               f'{len(pairs)} Windows renders with meta: title at 99 (top 98), meta at 139 (top 140), no overlap',
               failures, pairs=pairs)

    # art rules --------------------------------------------------------------------------------
    failures, shown_n = [], 0
    for c in frame_cases:
        name = LAYOUTS[c['layout_id']]
        idle = name == 'idle' or (name == 'volume' and LAYOUTS[c['rest_layout_id']] == 'idle')
        art = first(c['render']['layout'], 'art')
        want = bool(c['art_key']) and bool(c.get('art')) and name in ART_LAYOUTS and not idle
        if (eff(art) > 0) != want:
            failures.append(f'{c["id"]} ({name}, key {c["art_key"]!r}): art {"shown" if eff(art) else "hidden"}')
        if want:
            shown_n += 1
            if art['image_opa'] != (112 if c['art_dim'] else 255) or art['opa_eff'] != 255:
                failures.append(f'{c["id"]}: image_opa {art["image_opa"]}, opa {art["opa_eff"]}')
        if eff(first(c['noart']['layout'], 'art')) > 0:
            failures.append(f'{c["id"]}: the art-less twin shows art')
    for tid, tl in timelines.items():
        for cpt in tl['captures']:
            a = first(cpt['layout'], 'art')
            if a and (a['tx'] or a['ty']):
                failures.append(f'{tid} {cpt["file"]}: art translated')
    art_notes = []
    try:
        tl = timelines['v5-art']
        for label, direction in (('to-windows', -1), ('from-windows', 1), ('to-idle', -1), ('from-idle', 1),
                                 ('to-notice', -1), ('from-notice', 1), ('key-cleared', -1), ('key-back', 1)):
            opas = {o: first(base.find_capture(tl, label, o)['layout'], 'art')['opa'] for o in (0, 60, 120, 240, 300)}
            art_notes.append(f'{label}: {opas}')
            start, end = (255, 0) if direction < 0 else (0, 255)
            if not (opas[0] == start and 0 < opas[120] < 255 and opas[240] == end and opas[300] == end):
                failures.append(f'v5-art {label}: 240 ms OUT {start} -> {end}: {opas}')
        swap = base.find_capture(tl, 'instant-swap', 0)
        prev = base.find_capture(tl, 'key-back', 300)
        a0, ap = first(swap['layout'], 'art'), first(prev['layout'], 'art')
        if a0['opa'] != 255 or a0['art_src'] == ap['art_src']:
            failures.append(f'v5-art instant-swap: opa {a0["opa"]}, buffer {ap["art_src"]} -> {a0["art_src"]}')
        late = timelines['art-late-idle']
        opas = {o: first(base.find_capture(late, 'pixels-arrive', o)['layout'], 'art')['opa'] for o in (0, 60, 120, 240)}
        art_notes.append(f'late arrival: {opas}')
        if not (opas[0] == 0 and 0 < opas[60] < 255 and opas[240] == 255):
            failures.append(f'late arrival: 240 ms fade without delay: {opas}')
    except (KeyError, ValueError, TypeError) as error:
        failures.append(f'art timelines: {error!r}')
    checks.add('art_rules', not failures and shown_n > 0,
               f'art only on {sorted(ART_LAYOUTS)} (never idle, windows, notice, offline or without a key): {shown_n} '
               f'renders with art; artDim 112; never translates; show/hide 240 ms OUT; instant swaps',
               failures, notes=art_notes)

    # slides ---------------------------------------------------------------------------------------
    failures, rows_ = [], []
    for tid, tl in timelines.items():
        for s in tl['steps']:
            if 'slide' not in s['expect']:
                continue
            want, got = s['expect']['slide'], s['render']['last_slide']
            rows_.append(f'{tid} {s["label"]}: {got:+d}')
            if want != got:
                failures.append(f'{tid} t={s["t"]} {s["label"]}: slide {got:+d}, expected {want:+d}')
    flips = [s for s in timelines.get('v5-flips', {}).get('steps', [])]
    checks.add('slides', not failures and len(flips) >= 20,
               f'{len(rows_)} steps with an expected direction (the 8.7 flip table in v5-flips, the cc5 sequences, '
               f'artwork2 and v5 timelines)', failures, steps=rows_)

    # motion -----------------------------------------------------------------------------------------
    failures, notes = [], []

    def expect(cond, message):
        if not cond:
            failures.append(message)

    def at(tid, label, off, role, key='opa', ordinal=0, step_index=None):
        tl = timelines[tid]
        if step_index is None:
            cpt = base.find_capture(tl, label, off)
        else:
            cpt = next(c for c in tl['captures'] if c['step'] == step_index and c['offset'] == off)
        objs = [o for o in cpt['layout'] if o['role'] == role]
        return objs[ordinal][key] if len(objs) > ordinal else None

    try:
        for k, s in enumerate(timelines['v5-flips']['steps'], start=1):
            d = s['expect'].get('slide', 0)
            if not d:
                continue
            c0, c110 = at('v5-flips', None, 0, 'content', 'tx', step_index=k), at('v5-flips', None, 110, 'content', 'opa', step_index=k)
            o0, o220 = at('v5-flips', None, 0, 'content', 'opa', step_index=k), at('v5-flips', None, 220, 'content', 'opa', step_index=k)
            t380 = at('v5-flips', None, 380, 'content', 'tx', step_index=k)
            expect(c0 == d and o0 == 0 and 0 < c110 < 255 and o220 == 255 and t380 == 0,
                   f'v5-flips {s["label"]}: tx {c0}->{t380} (380 ms), opa {o0}->{c110}->{o220} (220 ms)')
        r = lambda off, role, key='opa': at('volume-reveal-hide', 'rot', off, role, key)  # noqa: E731
        expect(r(0, 'volume') == 0 and r(0, 'track') == 255 and r(150, 'track') == 0 and r(190, 'track', 'ty') == -8
               and r(230, 'volume') == 255 and r(390, 'volume', 'ty') == 0, 'reveal key times (150/190 IN, 50+180 OUT, 50+340 SPR)')
        h = lambda off, role, key='opa': at('volume-reveal-hide', 'volHide', off, role, key)  # noqa: E731
        expect(h(170, 'volume') == 0 and h(190, 'volume', 'ty') == 6, 'reveal out: 170 / 190 IN')
        i = lambda off, role, key='opa', o=0: at('idle-entry-exit', 'pIdle', off, role, key, o)  # noqa: E731
        expect(i(160, 'footer') == 0, 'idle in: footer out by +160 (IN)')
        expect(i(245, 'idle.item', o=0) > 0 and i(245, 'idle.item', o=1) == 0 and i(335, 'idle.item', o=2) > 0
               and i(335, 'idle.item', o=3) == 0, 'idle stagger 200 + 45 i')
        expect(0 < i(160, 'art') < 255 and i(245, 'art') == 0, f'idle in: art out over 240 ms OUT ({i(160, "art")} at +160)')
        b = lambda off, role, key='opa': at('idle-entry-exit', None, off, role, key, step_index=7)  # noqa: E731
        expect(b(90, 'track') == 0 and b(510, 'track') == 255 and b(510, 'track', 'ty') == 0, 'idle out: track 90 + 320/420')
        expect(b(140, 'footer') == 0 and 0 < b(280, 'footer') < 255 and b(420, 'footer') == 255, 'idle out: footer 140 + 280')
        expect(0 < b(90, 'art') < 255 and b(280, 'art') == 255, 'idle out: art back over 240 ms')
        for label, role in (('meta-change', 'list.meta'), ('status-change', 'status'), ('tracks-meta', 'tracks.meta'),
                            ('windows-meta', 'windows.meta')):
            vals = [at('v5-rest', label, off, role) for off in (0, 80, 160)]
            notes.append(f'{label} {role} opacity +0/+80/+160: {vals}')
            expect(vals[0] == 0 and 0 < vals[1] < 255 and vals[2] == 255, f'{label}: {role} fades in over 160 ms: {vals}')
        for label, role in (('title-change', 'list.title'), ('home-title', 'home.title'), ('seek-line', 'seek.line'),
                            ('seek-time', 'seek.time')):
            step_ = next(s for s in timelines['v5-rest']['steps'] if s['label'] == label)
            expect(at('v5-rest', label, 0, role) == 255 and step_['render']['line_fades'] == 0,
                   f'{label}: {role} swaps instantly (no fade)')
        step_ = next(s for s in timelines['v5-rest']['steps'] if s['label'] == 'meta-with-screen-change')
        expect(step_['render']['line_fades'] == 0 and at('v5-rest', 'meta-with-screen-change', 0, 'list.meta') == 255,
               'a meta change in a screen-change render does not fade on its own')
    except (KeyError, ValueError, StopIteration, TypeError, IndexError) as error:
        failures.append(f'motion data: {error!r}')
    checks.add('motion', not failures, 'content 220/380, reveal, idle stagger and fades, footer 160/280+140, '
                                       'meta/status 160 at rest, instant titles and Seek lines', failures, notes=notes)

    # reduced motion ----------------------------------------------------------------------------------
    failures, notes = [], []
    try:
        tl = timelines['v5-reduced']
        for k, s in enumerate(tl['steps'], start=1):
            if not s['expect'].get('reduced'):
                continue
            for cpt in [c for c in tl['captures'] if c['step'] == k]:
                for o in cpt['layout']:
                    # A hidden layer may keep its old offset (it is snapped to 0 when it shows).
                    if o['role'] in ('content', 'track', 'volume', 'idle.item') and eff(o) > 0 and (o['tx'] or o['ty']):
                        failures.append(f'{s["label"]} +{cpt["offset"]}: {o["role"]} translated {o["tx"]},{o["ty"]}')
            if s['expect'].get('screenFade'):
                vals = [at('v5-reduced', None, off, 'content', step_index=k) for off in (0, 110, 220)]
                notes.append(f'{s["label"]} content opacity +0/+110/+220: {vals}')
                if not (vals[0] == 0 and 0 < vals[1] < 255 and vals[2] == 255) or not s['render']['screen_change'] \
                        or s['render']['last_slide'] != 0:
                    failures.append(f'{s["label"]}: fade only ({vals}, {s["render"]})')
        vals = [at('v5-reduced', 'idle-in', off, 'idle.item', ordinal=idx) for idx, off in ((0, 245), (1, 245), (2, 335), (3, 335))]
        if not (vals[0] > 0 and vals[1] == 0 and vals[2] > 0 and vals[3] == 0):
            failures.append(f'reduced idle keeps the 200 + 45 i stagger: {vals}')
        full = next(s for s in tl['steps'] if s['label'] == 'full-motion-again')
        if full['render']['last_slide'] != 20:
            failures.append(f'reducedMotion false restores the slide: {full["render"]}')
    except (KeyError, ValueError, StopIteration, TypeError, IndexError) as error:
        failures.append(f'reduced-motion data: {error!r}')
    checks.add('reduced_motion', not failures, 'reducedMotion true: no translate in any capture (content, track, '
                                               'volume, idle row); content fade 220 ms; stagger kept', failures, notes=notes)

    # twins ---------------------------------------------------------------------------------------------
    failures, twinned = [], set()
    for c in drawn_cases:
        layout = c['render']['layout']
        by = roles(layout)
        for role, objs in by.items():
            if not role.endswith('.twin'):
                continue
            label_role = role[:-5]
            twinned.add(label_role)
            if label_role not in TWIN_ROLES:
                failures.append(f'{c["id"]}: unexpected twin {role}')
                continue
            for tw, lb in zip(objs, by.get(label_role, [])):
                if tw['color'] != '#000000' or tw['text_opa'] != 204 or tw['x1'] != lb['x1'] or tw['y1'] != lb['y1'] + 1 \
                        or tw['text'] != lb['text'] or tw['hidden'] != lb['hidden'] or tw['letter_space'] != lb['letter_space']:
                    failures.append(f'{c["id"]} {role}: {tw["color"]} opa {tw["text_opa"]} at {tw["x1"]},{tw["y1"]} '
                                    f'{tw["text"]!r} vs label {lb["x1"]},{lb["y1"]} {lb["text"]!r}')
        for role in TWIN_ROLES:
            for lb in by.get(role, []):
                if visible(lb) and lb['text'] and not any(visible(t) for t in by.get(role + '.twin', [])):
                    failures.append(f'{c["id"]}: {role} {lb["text"]!r} has no visible twin')
    missing_twins = sorted(set(TWIN_ROLES) - twinned)
    checks.add('twins', not failures and not missing_twins and index.get('text_twins') == 1,
               f'exactly the twelve twins ({", ".join(TWIN_ROLES)}): black, text_opa 204, +1 px, same text and '
               f'visibility; none elsewhere', failures + [f'twin {m} never drawn' for m in missing_twins])

    # twin fade --------------------------------------------------------------------------------------------
    # Every in-box pixel is classified: the fading layer's label ink over the cover (through the
    # scrim) only -- the case P5-13's bound (0.8a(1 - a) x the composite, <= 15) describes -- or
    # inside the ink box of a visible label of ANOTHER fading layer too. The second happens in both
    # volume reveals, where the volume caption and the home title cross-fade in the same place: in the
    # reveal-out the title (track layer, below) fades back in under the fading caption, so what lies
    # under the caption ink is title ink, not the dark composite; in the reveal-in the caption (volume
    # layer, above) fades in over the fading title, which a single-layer group reference does not
    # model either. P5-13 covers neither.
    # The overlap class is limited to labels of another layer that is fading in the same capture (K1
    # 8.5.3: "the labels of two fading layers"); the cover class has R-b's bound and the overlap class
    # R-g's (twin_fade_fails).
    failures, rows_ = list(twin_fade_self_test()), []
    probes = [(tid, cpt) for tid, tl in timelines.items() for cpt in tl['captures'] if cpt.get('probe')]
    seen_roles = set()
    worst_by = {}   # (role, 'cover' | 'overlap') -> {'worst', 'under', 'at', 'row'}
    excess_by = {'cover': 0.0, 'overlap': 0.0}   # worst |d| above P5-13's float model at the same pixel
    for tid, cpt in probes:
        p = cpt['probe']
        a = p['opa']
        result = twin_fade_probe(load_rgb(out / cpt['file']), load_rgb(out / p['full']), load_rgb(out / p['under']), a,
                                 *twin_fade_boxes(cpt['layout'], p['role']))
        worst = {kind: result[kind] for kind in ('cover', 'overlap')}
        worst_cover, worst_overlap, worst_out = result['cover'][0], result['overlap'][0], result['out']
        worst_in = max(worst_cover, worst_overlap)
        for kind in excess_by:
            excess_by[kind] = max(excess_by[kind], result['excess'][kind])
        seen_roles.add(p['role'])
        rows_.append(f'{tid} {p["role"]} opa {a} +{cpt["offset"]}: max |d| inside ink boxes {worst_in} (over the cover '
                     f'{worst_cover}; where a label of another fading layer overlaps {worst_overlap}, '
                     f'{result["overlap_px"]} px), outside {worst_out} ({result["out_px"]} px)')
        for kind, (d, under_px, pixel) in worst.items():
            if d > worst_by.get((p['role'], kind), {'worst': -1})['worst']:
                # P5-13's float model at that pixel: 0.8a(1 - a) x what lies under the label ink.
                model = round(0.8 * (a / 255) * (1 - a / 255) * under_px, 1)
                worst_by[(p['role'], kind)] = {'worst': d, 'under': under_px, 'model': model, 'at': pixel,
                                               'row': rows_[-1]}
        if a in (0, 255) and (worst_in or worst_out):
            failures.append(rows_[-1] + ' (must be identical at 0/255)')
        if twin_fade_fails(result):
            failures.append(rows_[-1])
    twin_worst = {f'{role}/{kind}': w['worst'] for (role, kind), w in sorted(worst_by.items()) if w['at']}
    checks.add('twin_fade', not failures and {'content', 'track', 'volume'} <= seen_roles,
               f'{len(probes)} probed frames of the content, track and volume fades vs a group-composited reference: '
               f'differences only inside label ink boxes (outside: none), there <= {TWIN_FADE_LIMIT} levels per channel '
               f'over the cover (K1 erratum R-b) and <= {TWIN_FADE_OVERLAP_LIMIT} where a label of another layer fading '
               f'in the same capture overlaps (the volume reveals; K1 erratum R-g), identical at 0/255; worst per '
               f'layer and what lies under the label ink: {twin_worst}',
               failures, probes=rows_, worst=twin_worst)
    deviations.append(twin_fade_deviation(worst_by, failures, excess_by))

    # art_async ---------------------------------------------------------------------------------------------
    failures, rows_ = [], []
    runs = {r['id']: r for r in index.get('art_async', [])}

    def shown_keys(run):
        return [k for _, k in run['shown']]

    try:
        for rid, run in runs.items():
            rows_.append(f'{rid}: shown {run["shown"]}, requests {run["requests"]}, aborts {run["aborts"]}, stale '
                         f'{run["stats"]["art_decode_stale"]}')
            if run['front_writes']:
                failures.append(f'{rid}: the front buffer changed while a decode ran (c)')
            # every transition shows the frame's current key at that moment (never a superseded one)
            steps_ = run['steps']
            for t_, key in run['shown'][1:]:
                current = [s for s in steps_ if s['t'] <= t_]
                cur = current[-1] if current else None
                if key and cur and cur.get('key') != key:
                    failures.append(f'{rid}: showed {key} at +{t_} while the frame asked for {cur.get("key")}')
        for rid, run in runs.items():
            if run.get('abort_model') != 'mcu-band' or not run.get('band_ms'):
                failures.append(f'{rid}: the fake decoder must stop at the next MCU band like the shipped one '
                                f'(abort_model {run.get("abort_model")!r}, band_ms {run.get("band_ms")})')
        a = runs['a-keys-inside-one-decode']
        if shown_keys(a) != ['a5-k39', 'a5-k02'] or a['final_shown'] != 'a5-k02':
            failures.append(f'(a) only C may appear: {a["shown"]}')
        b = runs['b-previous-stays']
        if b['shown'] != [[0, 'a5-k39'], [b['delay_ms'], 'a5-k03']]:
            failures.append(f'(b) previous cover until completion at {b["delay_ms"]} ms: {b["shown"]}')
        d = runs['d-stale-discarded']
        if 'a5-k04' in shown_keys(d) or d['final_shown'] != 'a5-k05' or d['stats']['art_decode_stale'] < 1:
            failures.append(f'(d) stale result discarded: {d["shown"]} {d["stats"]}')
        # B's frame lands while A decodes: A stops at its next band (aborted, discarded) and B is posted
        # at once; C's frame lands while B decodes: B stops too and C is posted -- 3 requests, 2 aborts
        # (the run-to-end decoder of cc5.4 phase 2a made 2 and 1: B was never posted).
        if (a['stats']['art_decode_aborts'], a['requests'], a['aborts']) != (2, 3, 2):
            failures.append(f'(d) aborted results discarded, band-abort decoder: aborts '
                            f'{a["stats"]["art_decode_aborts"]}, requests {a["requests"]} (want 2 and 3)')
        e = runs['e-failed-hides']
        if e['final_shown'] != '' or e['stats']['art_decode_errors'] < 1:
            failures.append(f'(e) a failed decode hides: {e["shown"]}')
        f1, f2 = runs['f-no-art-layout'], runs['f-release']
        if 'a5-k06' in shown_keys(f1) or f1['final_shown'] != '' or f1['aborts'] < 1:
            failures.append(f'(f) no-art layout during a decode: {f1["shown"]} aborts {f1["aborts"]}')
        if 'a5-k07' in shown_keys(f2) or f2['aborts'] < 1:
            failures.append(f'(f) release during a decode: {f2["shown"]} aborts {f2["aborts"]}')
        g = runs['g-spin-back']
        if g['final_shown'] != 'a5-k08' or g['requests'] != 1 or g['aborts'] != 0 or \
                g['shown'] != [[0, 'a5-k39'], [g['delay_ms'], 'a5-k08']]:
            failures.append(f'(g) spin back before the abort: {g["shown"]} requests {g["requests"]} aborts {g["aborts"]}')
        # (g) one pass too late: the decoder already stopped at a band. The abort is discarded, never
        # a failure (no hide, no failed key), and the key is posted again in the pass that consumed it.
        g2 = runs['g-spin-back-after-abort']
        g2_last = g2['steps'][-1]['t']
        if g2['final_shown'] != 'a5-k30' or shown_keys(g2) != ['a5-k39', 'a5-k30'] or g2['requests'] != 2 or \
                g2['aborts'] != 1 or g2['stats']['art_decode_aborts'] != 1 or g2['stats']['art_decode_errors'] != 0 or \
                g2['shown'][-1][0] > g2_last + g2['delay_ms'] + 1:
            failures.append(f'(g) spin back after the abort landed: {g2["shown"]} requests {g2["requests"]} aborts '
                            f'{g2["aborts"]} stats {g2["stats"]} (want I again at +{g2_last + g2["delay_ms"]})')
        # cc_art_decode_result() (the task's mapping, cc_art_decode.h) over its whole domain: an abort
        # the decoder saw stays aborted even when a spin back cleared `cancel` since; never failed.
        want_map = {('ok', False): 'ok', ('ok', True): 'aborted', ('failed', False): 'failed',
                    ('failed', True): 'failed', ('aborted', False): 'aborted', ('aborted', True): 'aborted'}
        got_map = {(r['decoded'], r['cancelled_at_end']): r['result'] for r in index.get('art_decode_result', [])}
        if got_map != want_map:
            failures.append(f'cc_art_decode_result: {got_map} (want {want_map})')
        # ... and the firmware task really uses the hook and that mapping (source scan; FreeRTOS code).
        failures += art_decode_wiring()
        # (h) K1 12.5.7(h): the resting cover within one decode time of the last detent. The decode in
        # flight at the last detent stops at its next MCU band (12.5.4 step 2: at most one band,
        # ceil(decode / 15) ms), so the bound is one decode time plus that band plus one loop pass.
        spins = []
        for rid in sorted(r for r in runs if r.startswith('h-spin-20-keys')):
            h = runs[rid]
            last = h['steps'][-1]
            spacing = h['steps'][1]['t'] - h['steps'][0]['t']
            arrival = h['shown'][-1][0] if h['shown'] else None
            limit = h['delay_ms'] + h['band_ms'] + 1
            bound = last['t'] + limit
            wait = None if arrival is None else arrival - last['t']
            spins.append({'run': rid, 'decode_ms': h['delay_ms'], 'band_ms': h['band_ms'], 'detent_ms': spacing,
                          'last_detent': last['t'], 'arrival': arrival, 'after_last_detent_ms': wait,
                          'k1_limit_ms': limit, 'meets_k1': arrival is not None and arrival <= bound})
            rows_.append(f'(h) {rid}: {h["delay_ms"]} ms decodes ({h["band_ms"]} ms bands), last detent +{last["t"]}, '
                         f'resting cover at +{arrival} ({wait} ms after it; K1 limit: one decode + one band + one pass '
                         f'= {limit} ms)')
            # Decodes longer than a detent: only the resting key may ever show.
            only_rest = h['delay_ms'] < spacing or len(shown_keys(h)) == 2
            if h['final_shown'] != last['key'] or arrival is None or arrival > bound or not only_rest:
                failures.append(f'(h) {rid}: {h["shown"]} (bound +{bound})')
        if len(spins) < 3:
            failures.append(f'(h) expected the 46 / 120 / 154 ms spins, got {[x["run"] for x in spins]}')
        deviations.append(art_async_deviation(spins, runs))
    except (KeyError, IndexError, TypeError) as error:
        failures.append(f'art_async data: {error!r}')
    checks.add('art_async', not failures and len(runs) >= 11,
               'R5 with a fake decoder that behaves as the shipped cc_art_decode.cpp with cc_jpeg.cpp\'s abort hook (a '
               'cancel stops the decode at the next of 15 MCU bands, K1 12.5.4 step 2, lead ruling R-f; results through '
               'cc_art_decode_result()): only the resting key ever shows (a), the previous cover stays (b), the front '
               'buffer is never written (c), stale and aborted results discarded (d), failures hide (e), no-art '
               'layouts and releases cancel (f), a spin back continues, and one after the abort landed re-posts the '
               'key (g), a 20-key spin ends with the resting cover within one decode time (+ one band) of the last '
               'detent (h); the result mapping over its domain; src/cc_art_decode.cpp decodes with &cancelled and maps '
               'through cc_art_decode_result() (source scan)',
               failures, runs=rows_)

    # offline -------------------------------------------------------------------------------------------
    failures, notes = [], []
    off_cases = [c for c in cases if c['kind'] == 'offline']
    natural = {c['text']: c.get('natural_width') for c in index.get('copy', []) if c['element'].startswith('offline')}
    for c in off_cases:
        layout = c['render']['layout']
        by = roles(layout)
        title, sub = first(layout, 'offline.title'), first(layout, 'offline.subtitle')
        # K1 8.10: the title on 1 line; `Open Desk Dial on your PC` (Desk Dial, the rename: a no-break space
        # holds the name together) on two balanced lines, `Open Desk Dial` / `on your PC`; after native
        # input `Knob controls still work` on ONE line (167.5 px in the design's metrics; 171 px with the
        # knob font, so the K1 erratum of lead ruling R-c draws it at -1 px tracking: 148 px).
        want_sub, want_lines = ('Knob controls still work', 1) if c.get('native') else (OFFLINE_SUB_TEXT, 2)
        want_ls = -1 if c.get('native') else 0
        if sub and sub.get('letter_space') != want_ls:
            failures.append(f'{c["id"]}: sub letter space {sub.get("letter_space")} (want {want_ls}, K1 8.10 R-c)')
        if not title or not visible(title) or title['text'] != 'Waiting for PC' or len(title['lines']) != 1 \
                or (title['x1'], title['y1']) != (35, 71):
            failures.append(f'{c["id"]}: title {title and title["text"]!r}')
        if not sub or not visible(sub) or ' '.join(l['text'] for l in sub['lines']) != want_sub \
                or (sub['x1'], sub['y1']) != (35, 105):
            failures.append(f'{c["id"]}: sub {sub and [l["text"] for l in sub["lines"]]!r} (want {want_sub!r})')
        elif not c.get('native') and [l['text'] for l in sub['lines']] != list(OFFLINE_SUB_LINES):
            failures.append(f'{c["id"]}: sub {[l["text"] for l in sub["lines"]]!r}: want {list(OFFLINE_SUB_LINES)!r} '
                            f'(the name is never split, rename-desk-dial.md 5.2 and 11.5)')
        elif len(sub['lines']) != want_lines:
            failures.append(f'{c["id"]}: sub {[l["text"] for l in sub["lines"]]!r} on {len(sub["lines"])} lines; K1 8.10 '
                            f'specifies {want_lines} ({want_sub!r} is {natural.get(want_sub)} px on one line with the knob '
                            f'font, box 170 px: for K3 copy approval, deviation WP1-D3)')
        notes.append(f'{c["id"]}: {[l["text"] for l in sub["lines"]] if sub else None}')
        for role in ('heading', 'art', 'footer'):
            o = first(layout, role)
            if o and eff(o) > 0 and (role != 'heading' or o['text']):
                failures.append(f'{c["id"]}: {role} visible on the offline screen')
        if any(visible(o) for r_ in ('home', 'list', 'tracks', 'seek', 'windows') for o in by.get(r_, [])):
            failures.append(f'{c["id"]}: host content visible under the offline layer')
    try:
        tl = timelines['v5-offline']
        v = lambda label, off, role, key='opa': at('v5-offline', label, off, role, key)  # noqa: E731
        expect(v('lease-expired', 0, 'content') == 0 and v('lease-expired', 220, 'content') == 255,
               'offline in: content 220 ms')
        expect(v('lease-expired', 160, 'footer') == 0 and v('lease-expired', 240, 'art') == 0 and
               0 < v('lease-expired', 80, 'art') < 255, 'offline in: footer 160 IN, cover 240 OUT')
        cap0 = base.find_capture(tl, 'lease-expired', 0)
        cap300 = base.find_capture(tl, 'lease-expired', 300)
        notes.append(f'pins at +0 {cap0["media"]}, at +300 {cap300["media"]}')
        expect(cap0['media'].get('cover') == 'a2-den' and cap300['media'] == {'cover': None, 'icon': None},
               f'offline: the display pins are released after the cover fade ({cap0["media"]} -> {cap300["media"]})')
        subs = [(v('native-input', off, 'offline.subtitle'), first(base.find_capture(tl, 'native-input', off)['layout'],
                                                                     'offline.subtitle')['text']) for off in (0, 80, 160)]
        expect(subs[0][0] == 0 and 0 < subs[1][0] < 255 and subs[2][0] == 255 and 'Knob controls' in subs[0][1],
               f'native input swaps the sub-line with a 160 ms fade: {subs}')
        claim = next(s for s in tl['steps'] if s['label'] == 'claim')
        expect(claim['render']['last_slide'] == 0 and v('claim', 0, 'content', 'tx') == 0 and v('claim', 0, 'content') == 0
               and v('claim', 220, 'content') == 255, f'claim: content fades in, no slide: {claim["render"]}')
        expect(v('claim', 0, 'art') == 0 and v('claim', 240, 'art') == 255, 'claim: cover shows over 240 ms')
        expect(v('claim', 140, 'footer') == 0 and v('claim', 420, 'footer') == 255, 'claim: footer 280 ms after 140')
        again = first(base.find_capture(tl, 'lease-expired-again', 300)['layout'], 'offline.subtitle')['text']
        expect(again.startswith(OFFLINE_SUB_LINES[0]), f'the native copy is kept only until the next claim: {again!r}')
        after = next(s for s in tl['steps'] if s['label'] == 'claim-after-handback')
        expect(after['render']['animations'] == 0 and v('claim-after-handback', 0, 'art') == 255,
               f'the first render after a handback snaps: {after["render"]}')
        roots = {cpt['layout'][0]['role'] for cpt in tl['captures']}
        expect(roots == {'screen'}, f'no native-screen frame in between: roots {roots}')
    except (KeyError, ValueError, StopIteration, TypeError, IndexError) as error:
        failures.append(f'offline timeline: {error!r}')
    checks.add('offline', not failures and len(off_cases) >= 3,
               f'{len(off_cases)} offline renders: Waiting for PC (1 line) / Open Desk Dial on your PC (two balanced '
               f'lines, Open Desk Dial / on your PC, the name never split) / Knob controls still work (1 line at -1 px tracking, K1 8.10 and R-c), no heading, footer or cover; entry 220/160/240, '
               f'native swap 160 (a native tap between two passes, through cc_offline_input_update), next claim '
               f'220/240/280+140, no slide, no native frame', failures, notes=notes)

    # copy ------------------------------------------------------------------------------------------------------
    failures, reported, rows_ = [], [], []
    for c in index.get('copy', []):
        label = c['labels'][0] if c['labels'] else None
        lines = [l['text'] for l in label['lines']] if label else []
        widths = [l['width'] for l in label['lines']] if label else []
        caps = label.get('fit', {}).get('capacity', []) if label else []
        whole = ' '.join(lines) == c['text'] or ''.join(lines) == c['text']
        fits = whole and all(w <= c['limit'] for w in widths) and all(w <= cap for w, cap in zip(widths, caps))
        # An element with a specified line count (the offline strings, K1 8.10): wrapping is a failure.
        if c.get('lines_want') and len(lines) != c['lines_want']:
            fits = False
        row = (f'{c["id"]} [{c["element"]}] {c["text"]!r}: {" / ".join(lines)!r} {widths} (limit {c["limit"]}, chord '
               f'{caps}; one line {c.get("natural_width")} px'
               + (f'; {c["lines_want"]} line(s) specified, {len(lines)} drawn' if c.get('lines_want') else '') + ')')
        rows_.append(row)
        if c.get('exception') or c.get('placeholder'):
            reported.append(row + (f' -- {c["exception"]}' if c.get('exception') else ' -- placeholder'))
        elif not fits:
            failures.append(row)
    checks.add('copy', not failures and len(rows_) > 100,
               f'{len(rows_)} knob strings (VOC section 9 incl. the firmware-local offline strings, CC5 15.2-15.3) '
               f'rendered in their elements: whole, within the App C limits and the chord, on the line count an '
               f'element specifies ({len(reported)} placeholder/exception rows reported)',
               failures, reported=reported, strings=rows_)

    # icons ---------------------------------------------------------------------------------------------------------
    seen_icons = set()
    for c in drawn_cases:
        for o in c['render']['layout']:
            if o.get('type') == 'image' and visible(o) and '@' in o.get('icon', ''):
                seen_icons.add(o['icon'])
    for tl in timelines.values():
        for cpt in tl['captures']:
            for o in cpt['layout']:
                if o.get('type') == 'image' and visible(o) and '@' in o.get('icon', ''):
                    seen_icons.add(o['icon'])
    tokens = [t for t in presentation.ICON_ENUM if t]
    want_icons = {f'{t}@20' for t in tokens} | {'heartfill@20', 'dotfill@16', 'prev@16', 'next@16'} | \
                 {f'{t}@26' for t in ('play', 'pause', 'list', 'win', 'tracks')}
    missing_icons = sorted(want_icons - seen_icons)
    stale = sorted(i for i in seen_icons if i.split('@')[0] in ('ok', 'dot', 'warn', 'usb'))
    checks.add('icons', not missing_icons and not stale,
               f'{len(seen_icons)} token/size masks drawn: every 9.1 wire token at 20 px, heartfill@20, the 26 px idle '
               f'set and prev/dotfill/next at 16 px (byte identity and fills: font_tests.py (g))',
               [f'never drawn: {m}' for m in missing_icons] + [f'stale mask drawn: {s}' for s in stale])

    # v5_bounded ----------------------------------------------------------------------------------------------------
    full_dir = out / 'full-layers'
    failures, compared = [], 0
    if not (full_dir / 'render-index.json').is_file():
        failures.append(f'{full_dir} missing: rebuild with build.py (it runs lcd-preview-full)')
    else:
        full_index = json.loads((full_dir / 'render-index.json').read_text(encoding='utf-8'))
        if full_index.get('full_layers') != 1:
            failures.append('the reference run was not built with CC_DISPLAY_FULL_LAYERS=1')
        for sub in ('cases', 'timelines'):
            for png in sorted((out / sub).rglob('*.png')):
                other = full_dir / png.relative_to(out)
                if not other.is_file():
                    failures.append(f'{png.relative_to(out)} missing in full-layers')
                    continue
                compared += 1
                if Image.open(png).convert('RGB').tobytes() != Image.open(other).convert('RGB').tobytes():
                    failures.append(f'{png.relative_to(out)} differs from the full-layer render')
    checks.add('v5_bounded', not failures and compared > 500,
               f'{compared} renders (cases, timeline captures, twin probes): bounded layers draw exactly the pixels '
               f'of 240 x 240 layers', failures)

    # heartbeat -------------------------------------------------------------------------------------------------------
    failures, beats = [], 0
    for tid, tl in timelines.items():
        for s in tl['steps']:
            if not s['expect'].get('identical'):
                continue
            beats += 1
            r = s['render']
            if r['animations'] or r['text_sets'] or r['changed'] or r['redraw_flushes'] or r['anims_running_after']:
                failures.append(f'{tid} {s["label"]}: {r}')
    checks.add('heartbeat', not failures and beats >= 8,
               f'{beats} identical frames: 0 animations, 0 text sets, nothing changed, 0 redraw flushes', failures)

    lat = index['latency']
    checks.add('latency', lat['refr_now_flushes'] > 0,
               f'a detent left to the refresh timer waits up to {lat["timer_wait_worst_ms"]} ms (LV_DEF_REFR_PERIOD '
               f'{lat["lv_def_refr_period_ms"]}; v5 detents animate their meta fade: {lat["animated_in_sample"]}); '
               f'lcd_thread presents every changed render with lv_refr_now(), animated or not, which draws it in the '
               f'same pass ({lat["refr_now_flushes"]} flushes; section 12.2 "detent text swap <= 5 ms")')

    # lcd_cadence -----------------------------------------------------------------------------------------------
    failures, notes = [], []
    try:
        cad = index['cadence']
        for v in cad['vectors']:
            if (v['late'], v['max_gap_ms']) != (v['want_late'], v['want_max_gap_ms']):
                failures.append(f'cc_anim_cadence_sample "{v["name"]}": late {v["late"]} max gap {v["max_gap_ms"]} (want '
                                f'{v["want_late"]} / {v["want_max_gap_ms"]})')
        perfect, stall = cad['perfect'], cad['stall']
        animated = [s['label'] for s in cad['steps'] if s['animated']]
        if perfect['late'] or perfect['max_gap_ms'] > perfect['period_ms'] + perfect['loop_ms'] \
                or perfect['anim_timer_runs'] < 100 or len(animated) < 12:
            failures.append(f'no-stall run: late {perfect["late"]}, worst interval {perfect["max_gap_ms"]} ms over '
                            f'{perfect["anim_timer_runs"]} animation-timer runs ({len(animated)} animated steps)')
        if stall['late'] < 1 or stall['max_gap_ms'] < stall['stall_ms']:
            failures.append(f'a {stall["stall_ms"]} ms stall was not counted: {stall}')
        for o in cad['offline_input']:
            if o['native'] != o['want']:
                failures.append(f'cc_offline_input_update "{o["name"]}": native {o["native"]} (want {o["want"]})')
        notes.append(f'the flush-to-flush measure lcd_thread used before (replayed on the same no-stall run): '
                     f'{perfect["flush_gap_late"]} late, worst {perfect["flush_gap_max_ms"]} ms')
        notes += [f'+{s["t"]} {s["label"]}: cadence late {s["late"]} / max {s["max_gap_ms"]} ms; flush-to-flush late '
                  f'{s["flush_gap_late"]} / max {s["flush_gap_max_ms"]} ms' for s in cad['steps']]
        summary = (f'lcdLateRefrs / lcdMaxGapMs on the animation cadence (cc_anim_cadence_poll, section 12.3) at '
                   f'{perfect["period_ms"]} ms: {perfect["late"]} late and a worst interval of {perfect["max_gap_ms"]} ms '
                   f'over {perfect["anim_timer_runs"]} animation-timer runs through slides, volume reveal/hide, idle, a '
                   f'detent 2 s after a slide, cover fades and offline in/out (the flush-to-flush measure it replaced: '
                   f'{perfect["flush_gap_late"]} late, worst {perfect["flush_gap_max_ms"]} ms on the same run); a '
                   f'{stall["stall_ms"]} ms stall counts {stall["late"]} ({stall["max_gap_ms"]} ms); '
                   f'{len(cad["vectors"])} sampler and {len(cad["offline_input"])} offline-input vectors')
    except (KeyError, TypeError) as error:
        failures.append(f'cadence data: {error!r}')
        summary = 'cadence data missing'
    checks.add('lcd_cadence', not failures, summary, failures, notes=notes)

    heap = index['heap']
    peak = max(heap['max_used'], heap['peak_used_sampled'])
    checks.add('heap', peak <= HEAP_LIMIT,
               f'LVGL heap peak {peak} B used ({100 * peak / heap["lv_mem_size"]:.1f} % of {heap["lv_mem_size"]}; limit '
               f'{HEAP_LIMIT} B, section 12.2), max_used {heap["max_used"]}, sampled {heap["peak_used_sampled"]}, '
               f'fragmentation {heap["frag_pct"]} %; x64 pointers: an upper bound for the ESP32-S3', lvgl_peak=peak)

    # vectors ----------------------------------------------------------------------------------------------------------
    failures = []
    vec = index.get('vectors', {})
    for (s, want), (s2, got) in zip(v5['vectors']['mmss'], vec.get('mmss', [])):
        if s != s2 or want != got or presentation.mmss(s) != want:
            failures.append(f'mmss({s}): {got!r} vs {want!r}')
    for (c, want), (c2, got) in zip(v5['vectors']['accentInk'], vec.get('accentInk', [])):
        if c != c2 or want != got:
            failures.append(f'accent_ink(0x{c:06X}): 0x{got:06X} vs 0x{want:06X}')
    for row in vec.get('tones', []):
        want = row['in']
        if row['tone'] != want['tone'] or row['ink'] != want['ink']:
            failures.append(f'tone {want}: C++ {row["tone"]} / 0x{row["ink"]:06X}')
    grid_bad = 0
    for c, ink, s in vec.get('accentGrid', []):
        ps = presentation.sat_rgb(c)
        if ink != presentation.accent_ink(c) or s != (-1 if ps is None else ps):
            grid_bad += 1
            if grid_bad <= 10:
                failures.append(f'grid 0x{c:06X}: C++ ink 0x{ink:06X} sat {s} vs Python 0x{presentation.accent_ink(c):06X} {ps}')
    n_vec = len(vec.get('mmss', [])) + len(vec.get('accentInk', [])) + len(vec.get('tones', []))
    checks.add('vectors', not failures and n_vec == len(v5['vectors']['mmss']) + len(v5['vectors']['accentInk']) +
               len(v5['vectors']['tones']) and len(vec.get('accentGrid', [])) > 4000,
               f'cc_mmss / cc_accent_ink / cc_button_tone + cc_button_ink == the frames_v5.json vectors ({n_vec}); '
               f'accent_ink and sat over {len(vec.get("accentGrid", []))} grid colours == presentation.py', failures)

    # mirror parity -----------------------------------------------------------------------------------------------------
    mirror_parity(checks, index, wire)

    artwork2_checks(checks, out, index, frames, timelines)

    deviations.append(copy_deviation(index))
    deviations.append(offline_button_gap())
    report = {
        'about': 'cc5.4 LCD regression checks (harness/cc54_report.py, PRESENTATION_V5.md 15.3) over the LVGL '
                 '9.0 harness renders of the v5 renderer',
        'renders': str(out),
        'pass': all(r['pass'] for r in checks.results.values()),
        'checks': checks.results,
        'deviations': deviations,
    }
    for d in deviations:
        print(f'{d["id"]} [{d["status"]}] {d["title"]}')
    (out / 'regression-checks-cc54.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    contact_sheet(out, index)
    print(f'cc54_report: {"PASS" if report["pass"] else "FAIL"} ({sum(r["pass"] for r in checks.results.values())}/'
          f'{len(checks.results)} checks) -> {out / "regression-checks-cc54.json"}')
    return 0 if report['pass'] else 1


# ------------------------------------------------------------------------------------ deviations --
# Recorded in regression-checks-cc54.json `deviations`: what the gates measured against the contracts
# where the firmware or the contract must change (or the user must accept), from the data of this run.

def twin_fade_deviation(worst_by, failures, excess_by=None):
    def worst(kind):
        rows = [dict(w, layer=role) for (role, k), w in worst_by.items() if k == kind and w['at']]
        return max(rows, key=lambda w: w['worst']) if rows else {'worst': 0, 'under': None, 'model': None, 'at': None,
                                                                  'row': None, 'layer': None}
    cover, overlap = worst('cover'), worst('overlap')
    per = {kind: {role: w['worst'] for (role, k), w in sorted(worst_by.items()) if k == kind and w['at']}
           for kind in ('cover', 'overlap')}
    excess_by = excess_by or {'cover': None, 'overlap': None}

    def within(value, limit):
        return 'within' if value <= limit else 'OVER'
    if not failures:
        status = (f'resolved: K1 errata of lead rulings R-b (<= {TWIN_FADE_LIMIT} over the cover) and R-g (<= '
                  f'{TWIN_FADE_OVERLAP_LIMIT} where the labels of two fading layers overlap, the volume reveals); '
                  'confirm both by eye in the hardware window (K1 15.4)')
    elif cover['worst'] <= TWIN_FADE_LIMIT and overlap['worst'] > TWIN_FADE_OVERLAP_LIMIT:
        status = ('open: where the labels of two fading layers overlap (the volume reveals) the difference exceeds '
                  f'R-g\'s bound ({overlap["worst"]} > {TWIN_FADE_OVERLAP_LIMIT}); over the cover it is within R-b\'s')
    else:
        status = 'open'
    return {
        'id': 'WP1-D1',
        'title': f'twin_fade: layer fades differ from the design\'s group fade by up to {cover["worst"]} levels over the '
                 f'cover ({within(cover["worst"], TWIN_FADE_LIMIT)} lead ruling R-b\'s bound of {TWIN_FADE_LIMIT}; 16 '
                 f'before the erratum) and {overlap["worst"]} where the labels of two fading layers overlap (the volume '
                 f'reveals; {within(overlap["worst"], TWIN_FADE_OVERLAP_LIMIT)} lead ruling R-g\'s bound of '
                 f'{TWIN_FADE_OVERLAP_LIMIT})',
        'check': 'twin_fade',
        'status': status,
        'contract': 'PRESENTATION_V5.md 8.5.3 / 16.1 P5-13 and 15.3 twin_fade after the R-b and R-g errata (16.7 E-b, '
                    f'16.8 E-g): <= {TWIN_FADE_LIMIT} per channel inside label ink boxes over the cover, <= '
                    f'{TWIN_FADE_OVERLAP_LIMIT} where a label ink box of another layer fading in the same capture '
                    'overlaps; no difference outside them',
        'ruling': f'R-g (2026-09-26): a per-class bound of {TWIN_FADE_OVERLAP_LIMIT} for the volume-reveal overlap class '
                  '(two text layers fading over 150-190 ms), R-b\'s bound unchanged for every other in-box pixel; the '
                  'first option below, with a flat measured bound instead of the per-pixel model; confirmed by eye in '
                  'the hardware window',
        'measured': {
            'over_the_cover': {'worst': cover['worst'], 'per_layer': per['cover'], 'under_at_worst': cover['under'],
                               'pixel': cover['at'], 'probe': cover['row'],
                               'worst_excess_over_the_float_model': excess_by['cover']},
            'where_fading_layers_overlap': {'worst': overlap['worst'], 'per_layer': per['overlap'],
                                          'under_at_worst': overlap['under'], 'pixel': overlap['at'],
                                          'probe': overlap['row'],
                                          'worst_excess_over_the_float_model': excess_by['overlap']},
            'failing_probes': len(failures),
        },
        'cause': [
            f'Over the cover (content, track and volume fades; worst {cover["worst"]} in the {cover["layer"]} fade, '
            f'with {cover["under"]} under the ink there): P5-13 models the error as 0.8a(1 - a) x what lies under the '
            f'label (<= 15 for the <= 74.5 composite), {cover["model"]} at that pixel. LVGL blends the twin and then '
            f'the label into the RGB565 framebuffer, each blend rounded to 5/6-bit channels (a 5-bit step is 8.2 '
            f'levels); the float model leaves that per-primitive arithmetic out, and it accounts for the rest.',
            f'Where the labels of two fading layers overlap (worst {overlap["worst"]} in the {overlap["layer"]} fade, '
            f'with {overlap["under"]} under the ink there; per layer {per["overlap"]}): the volume caption and the home '
            f'title cross-fade in the same place in both volume reveals (K1 8.8). Reveal-out: the volume layer fades '
            f'out over 170 ms while the track layer fades back in after 90 ms, so from +90 ms the caption lies over '
            f'partly visible title ink, not the dark composite: the float model alone gives {overlap["model"]} at '
            f'that pixel, above the 15 of P5-13 before any RGB565 rounding. Reveal-in: the caption fades in (after '
            f'50 ms) above the title fading out over 150 ms. P5-13 covers neither case, and a single bound set from '
            f'the over-the-cover worst would still fail here.'],
        'options': [
            f'A lead ruling for the overlap class only (R-b\'s {TWIN_FADE_LIMIT} stays for the cover): a separate bound '
            f'limited to labels of layers that fade in the same capture, derived from P5-13\'s model at each pixel '
            f'rather than from the measured worst -- |d| <= 0.8a(1 - a) x u + R, with u the brightest channel under '
            f'the label ink and R the RGB565 term (measured above the model: {excess_by["cover"]} over the cover, '
            f'{excess_by["overlap"]} in the overlap class); its worst case is the title ink under the caption at a = '
            f'0.5 (0.2 x 242 = 48.4, plus R). The difference is a slightly darker caption interior while the two '
            f'labels cross-fade (volume 180/170 ms), to be confirmed by eye with the rest of R-b.',
            f'Remove the overlap: sequence the volume reveals so the two layers never fade at once (reveal-in: the '
            f'volume fade-in after the track has faded out, delay 150 instead of 50 ms; reveal-out: the track fade-in '
            f'after the volume has faded out, delay 170 instead of 90 ms). A K1 8.8 motion change for the design '
            f'owner; the caption and title then no longer cross-fade, and R-b\'s one bound applies as written. Not '
            f'measured in the harness.',
            'Not an option: hiding the volume caption twin during the reveal-out. K1 8.5.3 rejected hiding twins '
            'during fades, and the shadow-edge pixels would then differ from the group reference by up to 0.8a x the '
            'ink under them, which fails the same check.'],
    }


def art_async_deviation(spins, runs):
    slow = [s for s in spins if not s['meets_k1']]
    waits = ', '.join(f'{s["after_last_detent_ms"]} ms with {s["decode_ms"]} ms decodes (limit {s["k1_limit_ms"]})'
                      for s in spins)
    return {
        'id': 'WP1-D2',
        'title': ('R5: a superseded cover decode stops at the next MCU band (K1 12.5.4 step 2, lead ruling R-f: '
                  'cc_art_decode.cpp decodes with &cancelled through cc_jpeg.cpp\'s abort hook), so after a fast spin '
                  'the resting cover arrives within one decode time plus one band of the last detent (K1 12.5.7(h))'
                  if not slow else
                  'R5: after a fast spin the resting cover takes longer than one decode time plus one MCU band '
                  '(K1 12.5.4 step 2, 12.5.7(h))'),
        'check': 'art_async (h)',
        'status': 'open' if slow else 'resolved',
        'contract': 'PRESENTATION_V5.md 12.5.4 step 2 (decode with &cancel; JDR_INTR at the next MCU band), 12.5.7 (h) '
                    'and 12.5.7\'s jpeg_tests.py abort-at-every-band case',
        'measured': {'spins': spins,
                     'aborts_in_run_a': runs['a-keys-inside-one-decode']['stats']['art_decode_aborts']},
        'cause': ('src/cc_art_decode.cpp run() decodes with cc_jpeg_decode_240(stage, bytes, dst, &cancelled) and maps '
                  'the result through cc_art_decode_result() (cc_art_decode.h: an abort the decoder saw stays aborted, '
                  'never failed); cc_jpeg.cpp polls the flag between MCU rows (JDR_INTR, CC_JPEG_ABORTED, the decoder '
                  'reusable; jpeg_tests.py aborts at every band of 24 samples). The harness fake stops at the next of '
                  '15 bands like it. Measured: ' + waits + '.')
                 if not slow else
                 ('the resting cover waited ' + waits + '; a fake or firmware decode that no longer stops at the next '
                  'band (12.5.4 step 2) makes the resting key wait for the superseded decode to finish.'),
        'options': [] if not slow else [
            'Restore 12.5.4 step 2: cc_art_decode.cpp passes &cancelled to cc_jpeg_decode_240 and maps the three '
            'results with cc_art_decode_result(); the harness fake stops at the next band.'],
    }


def copy_deviation(index):
    bad = []
    for c in index.get('copy', []):
        lines = [l['text'] for l in c['labels'][0]['lines']] if c.get('labels') else []
        if c.get('lines_want') and len(lines) != c['lines_want']:
            bad.append({'id': c['id'], 'text': c['text'], 'element': c['element'], 'natural_width': c.get('natural_width'),
                        'box': c['limit'], 'lines_specified': c['lines_want'], 'drawn': lines})
    title = '; '.join(f'{b["text"]!r} is {b["natural_width"]} px with the knob font (box {b["box"]}): drawn on '
                      f'{len(b["drawn"])} lines, K1 specifies {b["lines_specified"]}' for b in bad) or \
        'every string with a specified line count is drawn on it'
    return {
        'id': 'WP1-D3',
        'title': title,
        'check': 'copy, offline',
        'status': 'open (K3 copy approval)' if bad else 'resolved',
        'contract': 'PRESENTATION_V5.md 8.10 (`Knob controls still work`, 1 line, 167.5 px) and 8.6.11 (a string that '
                    'fails with the real font build goes to K3\'s copy approval pass, never to a smaller font)',
        'measured': bad,
        'cause': 'LVGL sums whole-pixel kerned advances (lv_text_get_width); the design\'s 167.5 px uses fractional '
                 'advances. The renderer then balances the text over two lines (no ellipsis).',
        'options': ['Approve two balanced lines for this string (an 8.6.11 exception; the knob already draws '
                    '`Knob controls` / `still work`).',
                    'Approve a shorter string in K3\'s copy pass that measures <= 170 px with the knob font '
                    '(lcd_preview.measure(text, 14) or this harness).'],
    }


def art_decode_wiring_failures(source):
    """K1 12.5.4 step 2 as wired in src/cc_art_decode.cpp (lead ruling R-f), which the host cannot run
    (FreeRTOS): the task decodes with the 4-argument flag form on the shared `volatile bool cancelled`,
    never with the run-to-end 3-argument form, and maps the result through cc_art_decode_result() (the
    mapping art_async checks through the fake). Comments are ignored."""
    code = re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S)
    failures = []
    if not re.search(r'\bvolatile\s+bool\s+cancelled\b', code):
        failures.append('cc_art_decode.cpp: `cancelled` is not a volatile bool (the decoder reads it between MCU rows)')
    if not re.search(r'\bcc_jpeg_decode_240\s*\(\s*stage\s*,\s*job\.bytes\s*,\s*job\.dst\s*,\s*&\s*cancelled\s*\)', code):
        failures.append('cc_art_decode.cpp: run() does not decode with cc_jpeg_decode_240(stage, job.bytes, job.dst, '
                        '&cancelled) (K1 12.5.4 step 2)')
    if re.search(r'\bcc_jpeg_decode_240\s*\(\s*[^,()]+,\s*[^,()]+,\s*[^,()]+\)', code):
        failures.append('cc_art_decode.cpp: a 3-argument cc_jpeg_decode_240 call (a cancelled decode would run to its end)')
    if not re.search(r'\bcc_art_decode_result\s*\(', code):
        failures.append('cc_art_decode.cpp: the result is not mapped through cc_art_decode_result() (an abort could '
                        'become failed)')
    return failures


def art_decode_wiring():
    """art_decode_wiring_failures over the real src/cc_art_decode.cpp, after a self-test on the phase-2a
    (run-to-end) form, which must be refused."""
    old = ('bool cancelled = false;\n  const bool ok = cc_jpeg_decode_240(stage, job.bytes, job.dst); // &cancelled\n'
           '  result = !ok ? CC_DECODE_FAILED : superseded ? CC_DECODE_ABORTED : CC_DECODE_OK;\n')
    failures = [] if len(art_decode_wiring_failures(old)) == 4 else [
        f'self-test: the run-to-end wiring must fail all four checks: {art_decode_wiring_failures(old)}']
    src = ROOT.parent / 'firmware' / 'src' / 'cc_art_decode.cpp'
    return failures + art_decode_wiring_failures(src.read_text(encoding='utf-8', errors='replace'))


def offline_button_gap():
    """K1 8.10's first native input includes a button state change while unclaimed: lcd_thread.cpp reads it
    through the HMI / control_center counter -- cc_native_button_seq() (control_center.h, WP4), or the
    earlier weak reference to cc_native_key_edges() -- which that side must define."""
    src = ROOT.parent / 'firmware' / 'src'
    pattern = re.compile(r'\buint32_t\s+cc_native_key_edges\s*\(\s*(void)?\s*\)\s*\{')
    defined = sorted(p.name for p in src.glob('*.cpp') if pattern.search(p.read_text(encoding='utf-8', errors='replace')))
    seq = re.compile(r'\buint32_t\s+cc_native_button_seq\s*\(\s*(void)?\s*\)\s*\{')
    lcd = (src / 'lcd_thread.cpp').read_text(encoding='utf-8', errors='replace')
    if re.search(r'\bcc_native_button_seq\s*\(\s*\)', lcd):
        defined += sorted(p.name for p in src.glob('*.cpp') if seq.search(p.read_text(encoding='utf-8', errors='replace')))
    return {
        'id': 'WP1-D4',
        'title': 'offline sub-line: a native button press ' + ('swaps it (counter defined in '
                                                                + ', '.join(defined) + ')' if defined else
                                                                'does not swap it yet; only a knob turn does'),
        'check': 'firmware source scan (the LCD side is covered by lcd_cadence offline_input and the offline timeline)',
        'status': 'resolved' if defined else 'open (HMI handoff)',
        'contract': 'PRESENTATION_V5.md 8.10: the first native input is an FOC position change or a button state change '
                    'while unclaimed (AL 8.1)',
        'measured': {'definitions': defined},
        'cause': 'The HMI sees native presses (hmi_thread.cpp sets native_button in its unclaimed branch) but exports '
                 'no counter; lcd_thread.cpp declares uint32_t cc_native_key_edges() weak and falls back to the FOC '
                 'position while it is not linked in.',
        'options': ['HMI / control_center owner: define uint32_t cc_native_key_edges() -- +1 for every debounced press '
                    'and release the unclaimed (native) button branch handles, since boot, wrapping, one aligned 32-bit '
                    'word readable from the LCD thread -- with exactly that signature; the LCD side needs no change.',
                    'Until then: list it as an open K1 8.10 gap in the release notes.'],
    }


# Harness label roles -> mirror TextRun roles (lcd_preview.compose).
MIRROR_ROLES = {
    'heading': 'heading', 'home.title': 'title', 'list.title': 'title', 'tracks.title': 'title',
    'windows.title': 'title', 'offline.title': 'title', 'home.artist': 'subtitle', 'list.subtitle': 'subtitle',
    'tracks.subtitle': 'subtitle', 'windows.app': 'subtitle', 'offline.subtitle': 'subtitle', 'status': 'status',
    'volume.caption': 'caption', 'volume.digits': 'digits', 'volume.percent': 'percent', 'idle.word': 'idle-word',
    'list.meta': 'meta', 'tracks.meta': 'meta', 'windows.meta': 'meta', 'windows.letter': 'tile-initial',
    'seek.caption': 'caption', 'seek.time': 'seek-time', 'seek.line': 'line',
}


def mirror_parity(checks, index, wire):
    try:
        from control_center import lcd_preview as lp
    except Exception as error:  # noqa: BLE001
        checks.add('mirror_parity', False, f'lcd_preview import failed: {error!r}')
        return
    failures, compared = [], 0
    for c in index['cases']:
        if c['kind'] not in ('frame', 'offline'):
            continue
        layout = c['render']['layout']
        knob = {}
        for o in labels_of(layout):
            if not visible(o) or o['role'] not in MIRROR_ROLES:
                continue
            for line in o['lines']:
                if line['text']:
                    knob.setdefault(MIRROR_ROLES[o['role']], []).append((line['text'], line['baseline'] - o['ty'],
                                                                         line['x1'], o['color']))
        frame = None if c['kind'] == 'offline' else wire(c)
        app_icon = eff(first(layout, 'windows.icon')) > 0
        scene = lp.compose(frame, window_icon=app_icon, artwork2=True, native=c.get('native', False))
        mirror = {}
        for run in scene.texts():
            mirror.setdefault(run.role, []).append((run.text, run.baseline, run.x, '#%02X%02X%02X' % run.ink))
        compared += 1
        if {r: [l[0] for l in v] for r, v in knob.items()} != {r: [l[0] for l in v] for r, v in mirror.items()}:
            failures.append(f'{c["id"]}: strings knob {knob} mirror {mirror}')
            continue
        for role, lines in knob.items():
            for (text, kb, kx, kc), (_, mb, mx, mc) in zip(lines, mirror[role]):
                if abs(kb - mb) > 1 or abs(kx - mx) > 1 or (role != 'tile-initial' and kc != mc):
                    failures.append(f'{c["id"]} {role} {text!r}: knob baseline {kb} x {kx} ink {kc}; mirror {mb} {mx} {mc}')
        k_icons = [(o['role'], o['icon'], o['recolor']) for o in layout if o.get('type') == 'image' and visible(o)
                   and '@' in o.get('icon', '') and o['opa_eff'] == 255]
        m_icons = [(i.role, f'{i.name}@{i.size}', '#%02X%02X%02X' % i.ink) for i in scene.icons()]
        role_map = {'footer.icon': 'footer', 'idle.icon': 'idle-icon', 'tracks.position': 'track-position'}
        if sorted((role_map.get(r, r), n, k) for r, n, k in k_icons) != sorted(m_icons):
            failures.append(f'{c["id"]}: icons knob {k_icons} mirror {m_icons}')
        art = first(layout, 'art')
        if c['kind'] == 'frame' and (eff(art) > 0) != (scene.art and bool(c.get('art'))):
            failures.append(f'{c["id"]}: art knob {eff(art) > 0} mirror {scene.art}')
    checks.add('mirror_parity', not failures and compared > 250,
               f'{compared} cases: lcd_preview.compose draws the same strings, baselines, pens (+-1 px), inks, icons '
               f'and art decisions as the harness', failures)


def contact_sheet(out: Path, index):
    font = ImageFont.load_default()
    cases = [c for c in index['cases'] if c['kind'] in ('frame', 'offline')]
    size, gap, label, columns = 240, 10, 16, 12
    rows = (len(cases) + columns - 1) // columns
    image = Image.new('RGB', (columns * (size + gap) + gap, 30 + rows * (size + label + gap) + gap), (28, 30, 32))
    draw = ImageDraw.Draw(image)
    draw.text((gap, 8), f'cc5.4 LVGL harness: {len(cases)} case renders (v5 renderer + parser)', fill=(220, 220, 220), font=font)
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    for i, c in enumerate(cases):
        x, y = gap + (i % columns) * (size + gap), 30 + (i // columns) * (size + label + gap)
        image.paste(Image.open(out / c['render']['file']).convert('RGB'), (x, y), mask)
        draw.text((x, y + size + 2), c['id'][:38], fill=(200, 200, 200), font=font)
    image.save(out / 'contact-sheet-cc54.png', optimize=True)


if __name__ == '__main__':
    sys.exit(main(sys.argv))

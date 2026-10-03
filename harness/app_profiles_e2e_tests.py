"""App profiles end to end (plan §6 "Round trip" and "Every profile x every view", S3). Python + MSVC (+ Pillow).

Desk Dial's REAL bundled profiles (profiles/karl/*.json + *.windows.json), compiled to DDAP by Desk Dial's own
compiler (control_center/app_profiles.py), go through the knob's REAL decoder, store and serial upload handler and are
drawn by the knob's REAL app canvas renderer. No fixtures, no store shim.

1. Builds app_profiles_e2e_tests.exe with MSVC /W4 /WX from the unchanged firmware units: cc_app_store.c,
   cc_app_onshape.c, cc_app_icons.c (C), cc_app_store_msg.cpp, cc_frame_parse.cpp and the renderer
   (cc_app_canvas.cpp, cc_app_gfx.cpp, cc_app_fonts.cpp, cc_app_shape.cpp, cc_app_cards.cpp, cc_app_screens.cpp).
   cc_app_canvas.cpp alone gets /Dcc_app_store_acquire=e2e_store_acquire (and _release): the driver's counting
   pass-throughs call the real store, so leases are counted without replacing it. The same driver is also built for
   x86 (ILP32, as the knob) for the decoded sizes.
2. Round trip, for all five bundled profiles: AppProfile.wire() -> cc_app_decode() -> the decoded struct as JSON,
   equal field by field (names, legend, slots, rings, commands with their Windows chords and flags, params, scenes,
   element arrays, icons by sha256, crc, features) to Desk Dial's reference decoder decode_wire() AND to the
   AppProfile model itself. Every pointer of the decoded profile lies inside its one allocation.
3. Features: each profile's wire features are what its model says (APP_PROFILES.md section 4) and a subset of what
   the knob advertises (appProfileFeatures = CC_APP_FEATURES_SUPPORTED = 31).
4. Upload: figma, plasticity, blender and autocad go into the store through cc_app_profile_command() as Desk Dial's
   device bridge sends them (list, begin, data chunks of APP_PROFILE_CHUNK_BYTES, end); every reply is checked and
   all four stay loaded through every render.
5. Renders, through the real store: for each uploaded profile the main screen at rest, each slot live, the tap
   flash, the refusals, the wheel on every ring (first and last command), the echo, the param screen of every
   command with a param (Plasticity's constrained ones also with an axis picked and as a plane / uniform) and the
   idle plasma; the built-in Onshape (id onshape, crc 0) on every view of app_canvas_tests.render_cases(), pixel-
   identical (sha256 of the raw RGB565 buffer) to the committed goldens/app_canvas/manifest.json. Each render checks
   the view, that it drew a full frame, the guard bands, that every acquire was released in its pass and that the
   store served the profile (never Loading).
6. The contact sheet (every real profile x view, labelled): <out>/app-profiles-e2e-contact-sheet.png, copied to
   the Desk Dial worktree's design-reference/app-profiles-contact-sheet.png (--no-copy to skip).

Usage: app_profiles_e2e_tests.py [--out DIR] [--no-copy]
No device, no USB. Exit status non-zero on any failure.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
# app_canvas_tests puts the Desk Dial companion (work.parent/app) on sys.path.
from app_canvas_tests import (GOLDENS, WRAP_TWIN_NAMES, arduinojson, companion, frame_hash, line,  # noqa: E402
                              msvc_env, render_cases, src, step, work)
from app_store_tests import msvc_env_x86  # noqa: E402
from control_center import app_profiles as ap  # noqa: E402
from control_center import device, keymap  # noqa: E402

UNITS_C = ('cc_app_store.c', 'cc_app_onshape.c', 'cc_app_icons.c')
UNITS_CPP = ('cc_app_store_msg.cpp', 'cc_frame_parse.cpp', 'cc_app_gfx.cpp', 'cc_app_fonts.cpp', 'cc_app_shape.cpp',
             'cc_app_cards.cpp', 'cc_app_screens.cpp')
CANVAS = 'cc_app_canvas.cpp'   # compiled on its own, its store calls renamed to the driver's pass-throughs
RENAME = ('/Dcc_app_store_acquire=e2e_store_acquire', '/Dcc_app_store_release=e2e_store_release')
SHEET_COPY = companion / 'design-reference' / 'app-profiles-contact-sheet.png'
UPLOADED = ('figma', 'plasticity', 'blender', 'autocad')


# ---------------------------------------------------------------------------------------------------- build / run
def build(out: Path, x86=False) -> Path:
    cl, env = msvc_env_x86() if x86 else msvc_env()
    tag = 'x86' if x86 else 'x64'
    obj = out / f'obj-{tag}'
    obj.mkdir(parents=True, exist_ok=True)
    common = ['/nologo', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS', f'/I{src}']
    cpp = ['/EHsc', '/std:c++14', f'/external:I{arduinojson}', '/external:W0']

    def run(args):
        r = subprocess.run([str(cl), *args], cwd=out, env=env, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout, r.stderr)
            raise SystemExit(f'FAIL: {tag} build')

    for unit in UNITS_C:   # C99 data and the decoder, compiled as C (/TC) as the device does
        run([*common, '/TC', '/std:c11', '/c', str(src / unit), f'/Fo{obj}\\'])
    run([*common, *cpp, *RENAME, '/c', str(src / CANVAS), f'/Fo{obj}\\'])
    exe = out / f'app_profiles_e2e_tests_{tag}.exe'
    run([*common, *cpp, str(root / 'app_profiles_e2e_tests.cpp'), *(str(src / u) for u in UNITS_CPP),
         *(str(obj / (Path(u).stem + '.obj')) for u in (*UNITS_C, CANVAS)), f'/Fo{obj}\\', f'/Fe{exe}'])
    return exe


def run_driver(exe: Path, payload, out: Path, name: str):
    path = out / f'{name}.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    r = subprocess.run([str(exe), str(path), str(out)], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-4000:], r.stderr[-4000:])
        raise SystemExit(f'FAIL: driver {exe.name} exited {r.returncode}')
    return [json.loads(text) for text in r.stdout.splitlines() if text.strip()]


class Checker:
    def __init__(self):
        self.passed = self.failed = 0

    def check(self, ok, what, detail=''):
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            print(f'FAIL {what}' + (f': {detail}' if detail else ''))
        return ok


# ---------------------------------------------------------------------------------------------------- expectations
def f32(v):
    return struct.unpack('<f', struct.pack('<f', v))[0]


def sha(data):
    return None if data is None else hashlib.sha256(bytes(data)).hexdigest()


def from_reference(d):
    """decode_wire()'s dict in the shape the driver prints the decoded C struct (icons as sha256)."""
    def scene(i):
        base, frames = d['scenes'][i]
        return {'base': [list(e) for e in base], 'frames': [{'ms': ms, 'el': [list(e) for e in els]}
                                                           for ms, els in frames]}

    def prm(i):
        p = d['params'][i]
        return {'label': p['label'], 'label_neg': p['label_neg'] or None, 'steps': [f32(v) for v in p['steps']],
                'free_step': f32(p['free_step']), 'start': f32(p['start']), 'min': f32(p['min']),
                'max': f32(p['max']), 'decimals': p['decimals'], 'flags': p['flags'], 'visual': p['visual'],
                'modes': p['modes'], 'axis_default': p['axis_default'], 'field': bool(p['field'])}

    rings = [{'name': r['name'], 'tab': r['tab'], 'slot': r['slot'],
              'cmds': [{'name': c['name'], 'search': bool(c['flags'] & ap.CMD_SEARCH),
                        'flags': (1 if c['flags'] & ap.CMD_DISABLED else 0) | (2 if c['flags'] & ap.CMD_MACRO else 0),
                        'mod': c['mod'], 'key': c['key'] or None,
                        'scene': None if c['scene'] == 0xFF else scene(c['scene']),
                        'param': None if c['param'] == 0xFF else prm(c['param'])} for c in r['cmds']]}
             for r in d['rings']]
    return {'id': d['id'], 'name': d['name'], 'legend': list(d['legend']), 'visual': d['visual'],
            'shape': d['shape'], 'style': d['shape_style'], 'stepped': bool(d['stepped']), 'plasma': list(d['plasma']),
            'icon24': sha(d['icon24']), 'icon48': sha(d['icon48']), 'has_slots': True,
            'slots': [dict(s) for s in d['slots']], 'search': dict(d['search']), 'rings': rings,
            'crc': d['crc'], 'features': d['features']}


def model_features(p):
    """APP_PROFILES.md section 4, from the AppProfile model (not from the wire)."""
    karl = p.raw_karl
    shape = karl.get('visual', 'label') == 'shape'
    bits = ap.F_SHAPE if shape else ap.F_LABEL_VISUAL
    if (shape and karl.get('shape', 'cube') != 'cube') or karl.get('shape_style', 'face') != 'face':
        bits |= ap.F_SHAPE_EXT
    params = [c.param for r in p.rings for c in r.commands if c.param is not None]
    if any(q.axes or q.planes or q.uniform for q in params):
        bits |= ap.F_PARAM_CONSTRAINTS
    if any(c.disabled for r in p.rings for c in r.commands):
        bits |= ap.F_DISABLED_CMDS
    return bits


def from_model(p):
    """The AppProfile (Karl JSON + Windows sidecar, merged) in the same shape: what the knob must end up holding."""
    karl = p.raw_karl
    visual = ap.VISUAL.index(karl.get('visual', 'label'))

    def chord(c):
        return (0, '') if c is None else (keymap.display_mods(c.mods), c.key.label)

    def prm(q):
        lo, hi = f32(q.min), f32(q.max)
        return {'label': q.label, 'label_neg': q.label_neg or None, 'steps': [f32(v) for v in q.steps],
                'free_step': f32(q.free_step), 'start': min(max(f32(q.start), lo), hi), 'min': lo, 'max': hi,
                'decimals': q.decimals, 'flags': (1 if q.deg else 0) | (2 if q.axes else 0) |
                (4 if q.planes else 0) | (8 if q.uniform else 0), 'visual': ap.PVISUAL.index(q.visual),
                'modes': q.modes, 'axis_default': q.axis_default, 'field': bool(p.param_keys.field)}

    def scene(i):
        base, frames = p.scenes[i]
        return {'base': [list(e) for e in base], 'frames': [{'ms': ms, 'el': [list(e) for e in els]}
                                                           for ms, els in frames]}

    rings = []
    for r in p.rings:
        cmds = []
        for c in r.commands:
            mod, key = chord(c.chord) if c.kind == 'keys' else (0, '')
            cmds.append({'name': c.name, 'search': c.kind == 'actions',
                         'flags': (1 if c.disabled else 0) | (2 if c.kind == 'macro' else 0), 'mod': mod,
                         'key': key or None, 'scene': None if c.scene is None else scene(c.scene),
                         'param': None if c.param is None else prm(c.param)})
        rings.append({'name': r.name, 'tab': r.tab, 'slot': ap.SLOTS.index(r.slot), 'cmds': cmds})
    slots = []
    for name in ap.SLOTS:
        s = p.slots[name]
        slots.append({'kind': ap.KIND.index(s.kind), 'fx': ap.FX.index(s.fx),
                      'button': 0xFF if s.button is None or s.kind == 'none' else s.button, 'label': s.label})
    mod, key = chord(p.search)
    icon = {k: ap._icon(karl[k], n) if k in karl else None
            for k, n in (('icon24', ap.ICON24_BYTES), ('icon48', ap.ICON48_BYTES))}
    return {'id': p.id, 'name': p.name, 'legend': list(p.legend), 'visual': visual,
            'shape': ap.SHAPE.index(karl.get('shape', 'cube')) if visual == 1 else 0,
            'style': ap.STYLE.index(karl.get('shape_style', 'face')), 'stepped': bool(karl.get('shape_stepped')),
            'plasma': [int(c) for c in karl.get('plasma') or (0, 0, 0)], 'icon24': sha(icon['icon24']),
            'icon48': sha(icon['icon48']), 'has_slots': True, 'slots': slots, 'search': {'mod': mod, 'key': key},
            'rings': rings, 'crc': p.wire_crc, 'features': model_features(p)}


def compare(path, want, got, problems):
    """Field-by-field equality; floats compared as float32; no extra or missing keys."""
    if isinstance(want, dict):
        if not isinstance(got, dict):
            problems.append(f'{path}: {got!r} is not an object')
            return
        for key in sorted(set(want) | set(got)):
            if key not in got:
                problems.append(f'{path}.{key}: missing in the decoded struct')
            elif key not in want:
                problems.append(f'{path}.{key}: not in the expectation')
            else:
                compare(f'{path}.{key}', want[key], got[key], problems)
    elif isinstance(want, list):
        if not isinstance(got, list) or len(got) != len(want):
            problems.append(f'{path}: length {len(got) if isinstance(got, list) else got!r} != {len(want)}')
            return
        for i, (w, g) in enumerate(zip(want, got)):
            compare(f'{path}[{i}]', w, g, problems)
    elif isinstance(want, float):
        if not isinstance(got, (int, float)) or f32(float(got)) != want:
            problems.append(f'{path}: {got!r} != {want!r}')
    elif want != got or type(want) is not type(got):
        problems.append(f'{path}: {got!r} != {want!r}')


def decoded_c(profile):
    """The driver's decoded struct with its icons hashed (the hex dump -> sha256)."""
    out = dict(profile)
    for k in ('icon24', 'icon48'):
        out[k] = None if out[k] is None else hashlib.sha256(bytes.fromhex(out[k])).hexdigest()
    return out


# ---------------------------------------------------------------------------------------------------- uploads
def upload_lines(p):
    """What Desk Dial's device bridge writes for one profile (device._app_profile_step): list, begin, data, end."""
    wire = p.wire()
    lines = [{'op': 'list'}, {'op': 'begin', 'id': p.id, 'bytes': len(wire), 'crc': p.wire_crc,
                              'wire': device.WIRE_VERSION_APP}]
    for off in range(0, len(wire), device.APP_PROFILE_CHUNK_BYTES):
        part = wire[off:off + device.APP_PROFILE_CHUNK_BYTES]
        lines.append({'op': 'data', 'off': off, 'b64': base64.b64encode(part).decode('ascii')})
    lines.append({'op': 'end'})
    return [json.dumps({'appProfile': m}, separators=(',', ':')) for m in lines]


def expected_replies(p, loaded_before):
    wire = p.wire()
    out = [{'loaded': loaded_before}, None]
    for off in range(0, len(wire), device.APP_PROFILE_CHUNK_BYTES):
        out.append({'ack': min(off + device.APP_PROFILE_CHUNK_BYTES, len(wire))})
    out.append({'id': p.id, 'crc': p.wire_crc, 'ok': True})
    return out


# ---------------------------------------------------------------------------------------------------- renders
def profile_cases(p):
    """(name, expected view, steps, label, extra) for every view of one uploaded profile. extra: what else to hold
    the render to (a twin it must differ from)."""
    pid, crc = p.id, p.wire_crc

    def a(slot='knob', **extra):
        return dict({'id': pid, 'crc': crc, 'slot': slot}, **extra)

    commands_button = next((s.button for s in p.slots.values() if s.kind == 'commands' and s.button is not None), 2)
    wheel_buttons = 1 << commands_button
    cases = [(f'{pid}-main', 'main', [step(0, a()), step(60)], 'main, at rest', None)]
    for name in ap.SLOTS:
        s = p.slots[name]
        if s.kind == 'none':
            continue
        buttons = 0 if s.button is None else 1 << s.button
        cases.append((f'{pid}-slot-{name}', 'main', [step(0, a(name), buttons=buttons), step(300, angle=2400),
                                                     step(400)],
                      f'{name.upper()} live: {s.label or "-"} ({s.kind}, fx {s.fx})', None))
    cases += [
        (f'{pid}-flash', 'main', [step(0, a()), step(100, a(flash=1)), step(160)], 'tap flash', None),
        (f'{pid}-refused', 'main', [step(0, a(refused=True)), step(60)], 'refused', None),
        (f'{pid}-refused-focus', 'main', [step(0, a(refused=True, refusedFocus=True)), step(60)],
         'refused (focus)', None),
    ]
    for r, ring in enumerate(p.rings):
        n = len(ring.commands)
        for index in sorted({1, n}):
            cmd = ring.commands[index - 1]
            cases.append((f'{pid}-wheel-r{r}-{index}', 'wheel',
                          [step(0, a(wheel={'ring': r, 'index': index}), buttons=wheel_buttons), step(1000)],
                          f'wheel {ring.name} {index}/{n}: {cmd.name}', None))
    if p.rings:
        cmd = p.rings[0].commands[0]
        cases.append((f'{pid}-echo', 'echo', [step(0, a()), step(100, a(echo={'ring': 0, 'index': 1, 'seq': 1})),
                                              step(500)], f'echo: {cmd.name} ran', None))
    for r, ring in enumerate(p.rings):
        for i, cmd in enumerate(ring.commands, start=1):
            q = cmd.param
            if q is None:
                continue
            lo, hi = f32(q.min), f32(q.max)
            start = min(max(f32(q.start), lo), hi)
            value = start + 0.25 * (hi - start) if hi > start else start
            value = max(-99999.999, min(99999.999, value))

            def prm(**extra):
                return a(param=dict({'ring': r, 'index': i, 'mode': 'B', 'value': int(round(value * 1000)),
                                     'step': 1}, **extra))
            base = f'{pid}-param-r{r}-{i}'
            cases.append((base, 'param', [step(0, prm()), step(200)],
                          f'param {cmd.name}: {q.label} {value:g}', None))
            if q.axes:
                axis = (q.axis_default + 1) % 3
                cases.append((f'{base}-axis{axis}', 'param', [step(0, prm(axis=axis)), step(200)],
                              f'param {cmd.name}: axis {"XYZ"[axis]}', base))
            if q.planes:
                cases.append((f'{base}-plane', 'param', [step(0, prm(axis=q.axis_default % 3, plane=True)),
                                                        step(200)],
                              f'param {cmd.name}: plane {"XYZ"[q.axis_default % 3]}', base))
            if q.uniform and q.axis_default != 3:   # a uniform default is the base case itself
                cases.append((f'{base}-uniform', 'param', [step(0, prm(axis=3)), step(200)],
                              f'param {cmd.name}: uniform', base))
    cases.append((f'{pid}-idle', 'idle', [step(0, a()), step(6500)], 'idle plasma (1.5 s in)', None))
    return cases


def frame_app(s):
    """The app object of a step's frame line (for the host reading check)."""
    return json.loads(s['line'])['frame'].get('app') if 'line' in s else None


# ---------------------------------------------------------------------------------------------------- sheet
def make_sheet(out: Path, sections, path: Path):
    from PIL import Image, ImageDraw, ImageFont
    tile, gap, label_h, head_h, cols = 240, 14, 44, 46, 8
    width = cols * tile + (cols + 1) * gap
    height = 80
    for _title, tiles in sections:
        height += head_h + ((len(tiles) + cols - 1) // cols) * (tile + label_h + gap) + gap
    sheet = Image.new('RGB', (width, height), (28, 30, 32))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('segoeui.ttf', 15)
        head = ImageFont.truetype('segoeuib.ttf', 24)
        title = ImageFont.truetype('segoeuib.ttf', 26)
    except OSError:
        font = head = title = ImageFont.load_default()
    draw.text((gap, 18), 'App profiles end to end: Desk Dial\'s real profiles -> its compiler -> the knob\'s C decoder '
              'and store -> the knob\'s app canvas', fill=(230, 230, 230), font=title)
    draw.text((gap, 52), 'Profiles adapted from Karl Malota (katbinaris), with permission. Onshape: the built-in '
              'canvas, pixel-identical to goldens/app_canvas. Rendered by harness/app_profiles_e2e_tests.py.',
              fill=(170, 170, 170), font=font)
    mask = Image.new('L', (tile, tile), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, tile - 1, tile - 1), fill=255)
    y = 80
    for heading, tiles in sections:
        draw.text((gap, y + 10), heading, fill=(255, 203, 74), font=head)
        y += head_h
        for i, (name, label) in enumerate(tiles):
            im = Image.open(out / f'{name}.png').convert('RGB')
            x = gap + (i % cols) * (tile + gap)
            ty = y + (i // cols) * (tile + label_h + gap)
            sheet.paste(im, (x, ty), mask)
            draw.ellipse((x, ty, x + tile - 1, ty + tile - 1), outline=(70, 72, 76))
            import textwrap
            for k, text in enumerate(textwrap.wrap(label, 30)[:2]):
                draw.text((x, ty + tile + 3 + 18 * k), text, fill=(210, 210, 210), font=font)
        y += ((len(tiles) + cols - 1) // cols) * (tile + label_h + gap) + gap
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, optimize=True)


# ---------------------------------------------------------------------------------------------------- main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=root / 'build' / 'app-profiles-e2e')
    parser.add_argument('--no-copy', action='store_true', help='do not copy the sheet into the Desk Dial worktree')
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    c = Checker()

    # Desk Dial's library, exactly as the app loads its bundled profiles.
    lib = ap.Library(companion / 'profiles')
    c.check(not lib.problems, 'Desk Dial library loads its bundled profiles', '; '.join(lib.problems))
    profiles = {p.id: p for p in lib.profiles()}
    c.check(tuple(profiles) == ap.ORDER, f'the five bundled profiles {ap.ORDER}', f'got {tuple(profiles)}')
    knob_features = int(re.search(r'#define CC_APP_FEATURES_SUPPORTED (0x[0-9A-Fa-f]+)u',
                                  (src / 'cc_app_profile.h').read_text(encoding='utf-8')).group(1), 16)
    advertised = 'c["appProfileFeatures"] = CC_APP_FEATURES_SUPPORTED;' in (src / 'control_center.cpp').read_text(
        encoding='utf-8')
    c.check(knob_features == 31 and advertised, 'the knob advertises appProfileFeatures = CC_APP_FEATURES_SUPPORTED '
            '= 31', f'0x{knob_features:X}, advertised {advertised}')

    exe = build(out)
    exe86 = build(out, x86=True)

    # ---- the round trip
    order = list(profiles)
    payload = {'decode': [base64.b64encode(profiles[pid].wire()).decode('ascii') for pid in order],
               'upload': [], 'render': []}
    decoded = [r for r in run_driver(exe, payload, out, 'decode') if r['kind'] == 'decode']
    decoded86 = [r for r in run_driver(exe86, payload, out, 'decode86') if r['kind'] == 'decode']
    sizes = {}
    for pid, r, r86 in zip(order, decoded, decoded86):
        p = profiles[pid]
        wire = p.wire()
        if not c.check(r['code'] == 0, f'{pid}: cc_app_decode code 0', f'code {r["code"]} @ {r["offset"]}'):
            continue
        c.check(r['bounds'], f'{pid}: every pointer inside the one allocation')
        got = decoded_c(r['profile'])
        try:
            ref = ap.decode_wire(wire)
        except ap.WireError as exc:
            c.check(False, f'{pid}: decode_wire accepts the blob', str(exc))
            continue
        for label, want in (('decode_wire', from_reference(ref)), ('the AppProfile model', from_model(p))):
            problems = []
            compare(pid, want, got, problems)
            c.check(not problems, f'{pid}: decoded struct == {label}, field by field',
                    '; '.join(problems[:8]) + (f' (+{len(problems) - 8} more)' if len(problems) > 8 else ''))
        c.check(got['crc'] == p.wire_crc == struct.unpack('<I', wire[-4:])[0], f'{pid}: crc')
        c.check(p.features == model_features(p), f'{pid}: wire features == the model\'s (section 4)',
                f'wire {p.features} model {model_features(p)}')
        c.check(p.features & ~knob_features == 0, f'{pid}: features {p.features} within the knob\'s {knob_features}')
        sizes[pid] = (len(wire), r['bytes'], r86.get('bytes'))
        print(f'PASS round trip {pid:10s} {len(wire):6d} B wire -> {r["bytes"]:6d} B decoded (x64), '
              f'{r86.get("bytes")} B (x86, as the knob); crc 0x{p.wire_crc:08X}, features {p.features}')

    # ---- uploads + renders, one process (one store)
    uploads, replies_want, loaded = [], [], []
    for pid in UPLOADED:
        lines = upload_lines(profiles[pid])
        uploads += lines
        replies_want += expected_replies(profiles[pid], list(loaded))
        loaded.insert(0, {'id': pid, 'crc': profiles[pid].wire_crc})   # most recently stored first
    cases, sections = [], []
    for pid in UPLOADED:
        pcases = profile_cases(profiles[pid])
        cases += [(n, v, s, lab, extra, pid) for n, v, s, lab, extra in pcases]
        sections.append((f'{profiles[pid].name} ({pid}, uploaded, crc 0x{profiles[pid].wire_crc:08X})',
                         [(n, lab) for n, _v, _s, lab, _e in pcases]))
    onshape = render_cases()
    cases += [(n, v, s, lab, None, 'onshape') for n, v, s, lab in onshape]
    sections.append(('Onshape (built-in canvas: id onshape, crc 0)',
                     [(n, lab) for n, _v, _s, lab in onshape if n not in WRAP_TWIN_NAMES]))
    for name, _v, steps, _lab, _e, pid in cases:   # Desk Dial's own reading of every app object it would send
        for s in steps:
            obj = frame_app(s)
            if obj is not None and not device.app_parse(obj)[1]:
                c.check(False, f'render {name}: device.app_parse accepts {obj}')
    payload = {'decode': [], 'upload': uploads,
               'render': [{'name': n, 'steps': s} for n, _v, s, _l, _e, _p in cases]}
    results = run_driver(exe, payload, out, 'cases')
    got_replies = [r['reply'] for r in results if r['kind'] == 'upload']
    def norm(reply):   # the list's order (most recently drawn first) is not what this checks
        if isinstance(reply, dict) and isinstance(reply.get('loaded'), list):
            return {'loaded': sorted((d.get('id'), d.get('crc')) for d in reply['loaded'])}
        return reply
    bad = [(i, w, g) for i, (w, g) in enumerate(zip(replies_want, got_replies)) if norm(w) != norm(g)]
    c.check(len(got_replies) == len(replies_want) and not bad,
            f'upload: {len(UPLOADED)} profiles, {len(uploads)} lines through cc_app_profile_command, every reply',
            '; '.join(f'line {i}: {g} != {w}' for i, w, g in bad[:4]))
    want_loaded = sorted((d['id'], d['crc']) for d in loaded)
    lists = [r['reply'] for r in results if r['kind'] == 'list']
    stayed = all(sorted((d['id'], d['crc']) for d in r['loaded']) == want_loaded for r in lists)
    c.check(stayed and len(lists) == len(cases), 'all four uploaded profiles stay loaded through every render')
    end = next(r for r in results if r['kind'] == 'end')
    c.check(end['lockErrors'] == 0 and end['lockDepth'] == 0, 'store lock hooks balanced, never nested', str(end))
    c.check(end['blocks'] == len(UPLOADED), f'store holds exactly {len(UPLOADED)} allocations at the end '
            '(the profiles; no staging buffer or leaked decode)', f'{end["blocks"]} blocks')

    from ppm_to_png import convert
    from PIL import Image, ImageChops
    rendered = {r['name']: r for r in results if r['kind'] == 'render'}
    for name, view, _steps, _label, _extra, pid in cases:
        r = rendered.get(name)
        if not c.check(r is not None, f'render {name}: rendered'):
            continue
        for frame in (name, *r['snaps']):
            convert(out / f'{frame}.ppm')
            (out / f'{frame}.ppm').unlink()
        problems = []
        if r['view'] != view:
            problems.append(f'view {r["view"]}, expected {view}')
        if r['frames'] < 1 or r['lastFills'] < 240 * 240:
            problems.append(f'drew {r["frames"]} frames, last {r["lastFills"]} px (a full frame is 57600)')
        if not r['guard']:
            problems.append('a write outside the 240 x 240 canvas (guard band changed)')
        if r['leaked'] or r['leases'] < 1:
            problems.append(f'leases {r["leases"]} {"LEAKED (an acquire not released in its pass)" if r["leaked"] else ""}')
        if r['nulls']:
            problems.append(f'the store answered {r["nulls"]} acquires with nothing (Loading)')
        c.check(not problems, f'render {pid} {name}', '; '.join(problems))
    # Twins: a picked axis / plane / uniform draws differently from the profile's default constraint.
    for name, _view, _steps, label, extra, pid in cases:
        if extra and name in rendered and extra in rendered:
            diff = ImageChops.difference(Image.open(out / f'{name}.png').convert('RGB'),
                                         Image.open(out / f'{extra}.png').convert('RGB')).getbbox()
            # APP_PROFILES.md section 8: the frame's param.axis / param.plane is the live constraint; the param
            # card's X / Y / Z chips (and a rotate's axis) must follow it, not only the profile's axis_default.
            c.check(diff is not None, f'render {name}: the live constraint ({label}) draws differently from the '
                    f'default one ({extra})', 'pixel-identical: the renderer ignores the frame\'s app.param axis / '
                    'plane (cc_app_canvas.cpp still draws axis_default: "The frame carries no live axis yet")')
    # Wheel first vs last command of a ring, and every view differs from the main screen.
    for pid in UPLOADED:
        for r, ring in enumerate(profiles[pid].rings):
            n = len(ring.commands)
            if n > 1:
                first = Image.open(out / f'{pid}-wheel-r{r}-1.png').convert('RGB')
                last = Image.open(out / f'{pid}-wheel-r{r}-{n}.png').convert('RGB')
                c.check(ImageChops.difference(first, last).getbbox() is not None,
                        f'{pid} wheel ring {r}: first and last command draw differently')
    # Onshape: the built-in through the real store == the goldens, byte for byte (every case and every snap).
    manifest = json.loads((GOLDENS / 'manifest.json').read_text(encoding='utf-8'))['frames']
    frames = [f for n, *_ in onshape if n in rendered for f in (n, *rendered[n]['snaps'])]
    hashes = {f: frame_hash(out / f'{f}.rgb565') for f in frames}
    bad = [f for f in frames if manifest.get(f) != hashes[f]]
    for f in bad:
        print(f'FAIL golden {f}: {"not in the manifest" if f not in manifest else "pixels differ"} '
              f'({out / (f + ".png")} vs {GOLDENS / (f + ".png")})')
    c.check(not bad and set(frames) == set(manifest),
            f'Onshape built-in through the real store == goldens/app_canvas ({len(frames) - len(bad)}/{len(manifest)} '
            'frames byte for byte)', f'missing {sorted(set(manifest) - set(frames))[:5]}' if not bad else '')
    views = {}
    for name, view, *_rest, pid in cases:
        views.setdefault(pid, {}).setdefault(view, 0)
        views[pid][view] += 1
    for pid, v in views.items():
        print(f'renders {pid:10s} ' + ', '.join(f'{k} {n}' for k, n in sorted(v.items())))

    sheet = out / 'app-profiles-e2e-contact-sheet.png'
    make_sheet(out, sections, sheet)
    print(f'Contact sheet: {sheet}')
    if not args.no_copy:
        shutil.copyfile(sheet, SHEET_COPY)
        print(f'Copied to: {SHEET_COPY}')
    print('decoded sizes: ' + ', '.join(f'{pid} {w} B wire -> {d} B (x64) / {d86} B (x86)'
                                         for pid, (w, d, d86) in sizes.items()))
    print(f'{"PASS" if not c.failed else "FAIL"} app profiles end to end: {c.passed} checks passed, '
          f'{c.failed} failed ({len(cases)} renders)')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())

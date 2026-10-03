"""App profiles harness (plan §6, S1 FW-A): the knob's DDAP decoder, profile store and appProfile upload.

1. Builds app_store_tests.exe with MSVC /W4 /WX from app_store_tests.cpp and the unchanged firmware units
   cc_app_store.c, cc_app_onshape.c, cc_app_icons.c (C, /std:c11), cc_app_store_msg.cpp and cc_frame_parse.cpp, and
   a second time with /fsanitize=address (the fuzz and the thread stress run under ASan).
2. A minimal DDAP encoder (APP_PROFILES.md section 3) written here from the spec, with the offset of every field.
3. Decoder accept cases (minimal, full with both icons, 8 rings x 32 commands, 128 scenes, 48 elements, 16 frames,
   32 params, exactly 32768 bytes) and a round trip: encoder -> the C decoder -> the decoded struct as JSON from C
   -> compared field by field with the encoder's model. One reject case (at least) per result code 1..14, each
   checked for its code and offset.
4. The store and the upload state machine through real {"appProfile":...} lines: LRU by last draw, the 4-slot
   and 128 KB limits, acquire pins across eviction and replacement (the free waits for the release), the built-in
   Onshape, begin / data / end order, sizes, crc, wire, the 2000 ms stall, a begin that aborts, base64 errors,
   busy, decode errors with their offset, list, and the internal-heap cost of a 3000-character data line.
5. Frame parse cases through the real cc_parse_frame (app.id, app.crc, knob / f1..f4, index 32).
6. A deterministic mutation fuzz (truncation, bit flips, length lies, count inflation, header fields, random runs):
   >= 100,000 cases on the /W4 build and >= 20,000 under ASan; nothing may be accepted unsound, leaked or read out
   of bounds. Then the LCD-vs-COM thread stress under ASan.

No device, no USB. Exit status non-zero on any failure. --quick runs a smaller fuzz.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import math
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from app_canvas_tests import BASE, msvc_env, src, arduinojson  # noqa: E402  (one MSVC setup for the harness)

OUT = root / 'build' / 'app-store'
UNITS_C = ('cc_app_store.c', 'cc_app_onshape.c', 'cc_app_icons.c')
UNITS_CPP = ('cc_app_store_msg.cpp', 'cc_frame_parse.cpp')

# ------------------------------------------------------------------------------------------------ encoder
FEAT_SHAPE, FEAT_SHAPE_EXT, FEAT_LABEL, FEAT_PARAM_CONSTRAINTS, FEAT_DISABLED = 1, 2, 4, 8, 16
CMD_SEARCH, CMD_DISABLED, CMD_MACRO = 1, 2, 4
APP_CMD_DISABLED, APP_CMD_MACRO = 1, 2   # the decoded app_cmd_t flags


def features_of(m):
    f = FEAT_SHAPE if m['visual'] == 1 else FEAT_LABEL
    if m['shape'] != 0 or m['style'] != 0:
        f |= FEAT_SHAPE_EXT
    if any(p['flags'] & 0x0E for p in m['params']):
        f |= FEAT_PARAM_CONSTRAINTS
    if any(c['flags'] & CMD_DISABLED for r in m['rings'] for c in r['cmds']):
        f |= FEAT_DISABLED
    return f


class Enc:
    """Appends wire fields and records the offset of each one by name (marks)."""

    def __init__(self):
        self.b = bytearray()
        self.marks = {}

    def mark(self, name):
        self.marks[name] = len(self.b)

    def u8(self, v, name=None):
        if name:
            self.mark(name)
        self.b += struct.pack('<B', v & 0xFF)

    def i8(self, v):
        self.b += struct.pack('<b', v)

    def u16(self, v, name=None):
        if name:
            self.mark(name)
        self.b += struct.pack('<H', v & 0xFFFF)

    def u32(self, v, name=None):
        if name:
            self.mark(name)
        self.b += struct.pack('<I', v & 0xFFFFFFFF)

    def f32(self, v, name=None):
        if name:
            self.mark(name)
        self.b += struct.pack('<f', v)

    def raw(self, data, name=None):
        if name:
            self.mark(name)
        self.b += data

    def str(self, s, name=None):
        data = s.encode('latin-1') if isinstance(s, str) else bytes(s)
        if name:
            self.mark(name)
        self.b += bytes([len(data) & 0xFF]) + data


def els(e: Enc, items, name):
    e.u8(len(items), name)
    for i, el in enumerate(items):
        e.mark(f'{name}.{i}')
        e.u8(el[0]); e.u8(el[1]); e.i8(el[2]); e.i8(el[3])
        for v in el[4:]:
            e.u8(v)


def encode(m, *, features=None, total=None, crc=None, wire=1, magic=b'DDAP', reserved=(0, 0), tail=b'',
           body_patch=None):
    """(blob, marks). Marks are absolute offsets. body_patch(bytearray) may edit the body before sealing."""
    e = Enc()
    e.raw(magic, 'magic'); e.u8(wire, 'wire'); e.u8(reserved[0], 'reserved8'); e.u16(reserved[1], 'reserved16')
    e.u32(0, 'total'); e.u32(features_of(m) if features is None else features, 'features')
    e.str(m['id'], 'id'); e.str(m['name'], 'name')
    for i, s in enumerate(m['legend']):
        e.str(s, f'legend{i}')
    e.u8(m['visual'], 'visual'); e.u8(m['shape'], 'shape'); e.u8(m['style'], 'style'); e.u8(m['stepped'], 'stepped')
    for i, c in enumerate(m['plasma']):
        e.u32(c, f'plasma{i}')
    icons = (1 if m['icon24'] is not None else 0) | (2 if m['icon48'] is not None else 0)
    e.u8(m.get('icons_byte', icons), 'icons')
    if m['icon24'] is not None:
        e.raw(m['icon24'], 'icon24')
    if m['icon48'] is not None:
        e.raw(m['icon48'], 'icon48')
    for i, s in enumerate(m['slots']):
        e.u8(s['kind'], f'slot{i}.kind'); e.u8(s['fx'], f'slot{i}.fx'); e.u8(s['button'], f'slot{i}.button')
        e.str(s['label'], f'slot{i}.label')
    e.u8(m['search']['mod'], 'search.mod'); e.str(m['search']['key'], 'search.key')
    e.u8(len(m['params']), 'params')
    for i, p in enumerate(m['params']):
        e.str(p['label'], f'p{i}.label'); e.str(p['label_neg'], f'p{i}.label_neg')
        for s, v in enumerate(p['steps']):
            e.f32(v, f'p{i}.steps{s}')
        e.f32(p['free_step'], f'p{i}.free_step'); e.f32(p['start'], f'p{i}.start')
        e.f32(p['min'], f'p{i}.min'); e.f32(p['max'], f'p{i}.max')
        e.u8(p['decimals'], f'p{i}.decimals'); e.u8(p['flags'], f'p{i}.flags'); e.u8(p['visual'], f'p{i}.visual')
        e.u8(p['modes'], f'p{i}.modes'); e.u8(p['axis_default'], f'p{i}.axis_default'); e.u8(p['field'], f'p{i}.field')
    e.u8(len(m['scenes']), 'scenes')
    for i, s in enumerate(m['scenes']):
        els(e, s['base'], f's{i}.base')
        e.u8(len(s['frames']), f's{i}.frames')
        for f, k in enumerate(s['frames']):
            e.u16(k['ms'], f's{i}.f{f}.ms')
            els(e, k['el'], f's{i}.f{f}.el')
    e.u8(len(m['rings']), 'rings')
    for i, r in enumerate(m['rings']):
        e.str(r['name'], f'r{i}.name'); e.str(r['tab'], f'r{i}.tab'); e.u8(r['slot'], f'r{i}.slot')
        e.u8(len(r['cmds']), f'r{i}.cmds')
        for c, cmd in enumerate(r['cmds']):
            e.str(cmd['name'], f'r{i}.c{c}.name'); e.u8(cmd['flags'], f'r{i}.c{c}.flags')
            e.u8(cmd['mod'], f'r{i}.c{c}.mod'); e.str(cmd['key'], f'r{i}.c{c}.key')
            e.u8(cmd['scene'], f'r{i}.c{c}.scene'); e.u8(cmd['param'], f'r{i}.c{c}.param')
    e.mark('end')
    b = e.b
    if body_patch:
        body_patch(b)
    b += tail
    size = len(b) + 4
    struct.pack_into('<I', b, 8, size if total is None else total)
    b += struct.pack('<I', zlib.crc32(bytes(b)) if crc is None else crc)
    return bytes(b), e.marks


def icon(n, seed):
    return bytes((i * 7 + seed) & 0xFF for i in range(n))


def slot(kind=0, fx=0, button=0xFF, label=''):
    return {'kind': kind, 'fx': fx, 'button': button, 'label': label}


def minimal(id='mini'):
    return {'id': id, 'name': 'M', 'legend': ['', '', '', ''], 'visual': 0, 'shape': 0, 'style': 0, 'stepped': 0,
            'plasma': [0, 0, 0], 'icon24': None, 'icon48': None, 'slots': [slot() for _ in range(5)],
            'search': {'mod': 0, 'key': ''}, 'params': [], 'scenes': [], 'rings': []}


def param(label='DEPTH', **kw):
    p = {'label': label, 'label_neg': '', 'steps': [0.01, 0.1, 1.0], 'free_step': 0.05, 'start': 1.5, 'min': -10.0,
         'max': 100.0, 'decimals': 2, 'flags': 0, 'visual': 2, 'modes': 0, 'axis_default': 0, 'field': 0}
    p.update(kw)
    return p


def cmd(name='CMD', flags=0, mod=0, key='E', scene=0xFF, param=0xFF):
    return {'name': name, 'flags': flags, 'mod': mod, 'key': key, 'scene': scene, 'param': param}


def full(id='figma'):
    """Every field with a non-default value, both icons."""
    m = minimal(id)
    m.update(name='FIGMA DESIGNER', legend=['ZOOM', 'ORBIT', '', 'PAN'], visual=1, shape=2, style=1, stepped=1,
             plasma=[0x0F9D8A, 0x64BC4F, 0xFFFFFF], icon24=icon(1152, 3), icon48=icon(4608, 9),
             slots=[slot(2, 1, 0xFF, 'ZOOM'), slot(1, 2, 0, 'ORBIT'), slot(5, 0, 1, ''),
                    slot(4, 4, 2, 'UNDO'), slot(3, 3, 3, 'PAN WITH A LONG LABEL!')],
             search={'mod': 0x0F, 'key': 'NUM1'})
    m['params'] = [param('DEPTH'), param('ANGLE', label_neg='ANGLE BACK', steps=[-1.0, 1e7, -1e7], free_step=0.0,
                                          start=-5.0, min=-5.0, max=-5.0, decimals=4, flags=0x0F, visual=9, modes=15,
                                          axis_default=3, field=1)]
    m['scenes'] = [
        {'base': [[0, 0, -128, 127, 0, 255, 1, 2, 3], [14, 4, 5, -6, 7, 8, 9, 10, 255]],
         'frames': [{'ms': 0, 'el': []}, {'ms': 60000, 'el': [[6, 3, 1, 2, 3, 4, 1, 0, 2]]}]},
        {'base': [], 'frames': []},
        {'base': [[3, 1, 10, 10, 20, 0, 0, 0, 0]], 'frames': []},
    ]
    m['rings'] = [
        {'name': 'DESIGN', 'tab': 'DESIGN', 'slot': 1,
         'cmds': [cmd('FRAME', 0, 0x01, 'F', 0, 0), cmd('SEARCHED', CMD_SEARCH, 0, '', 1, 1),
                  cmd('MACRO', CMD_MACRO, 0, '', 0xFF, 0xFF), cmd('GREY', CMD_DISABLED, 0x06, '/', 2, 0xFF),
                  cmd('ALL', CMD_SEARCH | CMD_DISABLED | CMD_MACRO, 0x08, '', 0, 1)]},
        {'name': 'X', 'tab': 'X', 'slot': 4, 'cmds': [cmd('ONE', 0, 0, '', 0xFF, 0)]},
    ]
    return m


def big_rings(id='rings'):
    m = minimal(id)
    m['visual'], m['shape'] = 1, 0
    m['scenes'] = [{'base': [[0, 1, 2, 3, 4, 5, 6, 7, 8]], 'frames': []}]
    m['params'] = [param()]
    m['rings'] = [{'name': f'RING {r}', 'tab': f'T{r}', 'slot': r % 5,
                   'cmds': [cmd(f'C{r}-{c}', 0, c & 0x0F, f'K{c}', 0 if c % 2 else 0xFF, 0 if c % 3 else 0xFF)
                            for c in range(32)]} for r in range(8)]
    return m


def many_scenes(id='scenes'):
    m = minimal(id)
    m['scenes'] = [{'base': [[i % 15, i % 5, i - 64, 64 - i, i, i, i, i, i]],
                    'frames': [{'ms': i, 'el': []}]} for i in range(128)]
    m['rings'] = [{'name': 'R', 'tab': 'R', 'slot': 0, 'cmds': [cmd(f'S{i}', 0, 0, '', i, 0xFF) for i in (0, 64, 127)]}]
    return m


def dense_scene(id='dense'):
    m = minimal(id)
    el48 = [[i % 15, i % 5, i, -i, 2 * i, i, 255 - i, i, i ^ 0x55] for i in range(48)]
    m['scenes'] = [{'base': copy.deepcopy(el48), 'frames': [{'ms': 100 * f, 'el': copy.deepcopy(el48)}
                                                           for f in range(16)]}]
    m['rings'] = [{'name': 'R', 'tab': 'R', 'slot': 0, 'cmds': [cmd('D', 0, 0, 'D', 0, 0xFF)]}]
    return m


def many_params(id='params'):
    m = minimal(id)
    m['params'] = [param(f'P{i}', start=float(i), min=0.0, max=31.0, visual=i % 10) for i in range(32)]
    m['rings'] = [{'name': 'R', 'tab': 'R', 'slot': 0, 'cmds': [cmd('Q', 0, 0, 'Q', 0xFF, 31)]}]
    return m


def exact_size(target=32768, id='max'):
    """A profile whose blob is exactly `target` bytes (scene elements fill it, slot label characters the rest)."""
    m = minimal(id)
    m['icon24'], m['icon48'] = icon(1152, 1), icon(4608, 2)
    m['visual'] = 1
    m['scenes'] = []
    blob, _ = encode(m)
    while target - len(blob) >= 2:   # a scene is 2 bytes plus 9 per element
        n = min(48, (target - len(blob) - 2) // 9)
        m['scenes'].append({'base': [[1, 1, 0, 0, 1, 1, 0, 0, 0]] * n, 'frames': []})
        blob, _ = encode(m)
    pad = target - len(blob)
    for i in range(5):
        if pad <= 0:
            break
        add = min(23 - len(m['slots'][i]['label']), pad)
        m['slots'][i]['label'] += 'L' * add
        pad -= add
    blob, _ = encode(m)
    return m, blob


# ------------------------------------------------------------------------------------------------ expectations
def f32(v):
    return struct.unpack('<f', struct.pack('<f', v))[0]


def expected_profile(m, blob):
    """The decoded struct app_store_tests.cpp writes, from the model."""
    def scene(i):
        s = m['scenes'][i]
        return {'base': [list(e) for e in s['base']], 'frames': [{'ms': k['ms'], 'el': [list(e) for e in k['el']]}
                                                                for k in s['frames']]}

    def prm(i):
        p = m['params'][i]
        return {'label': p['label'], 'label_neg': p['label_neg'] or None, 'steps': [f32(v) for v in p['steps']],
                'free_step': f32(p['free_step']), 'start': f32(p['start']), 'min': f32(p['min']),
                'max': f32(p['max']), 'decimals': p['decimals'], 'flags': p['flags'], 'visual': p['visual'],
                'modes': p['modes'], 'axis_default': p['axis_default'], 'field': bool(p['field'])}

    rings = []
    for r in m['rings']:
        cmds = []
        for c in r['cmds']:
            cmds.append({'name': c['name'], 'search': bool(c['flags'] & CMD_SEARCH),
                         'flags': (APP_CMD_DISABLED if c['flags'] & CMD_DISABLED else 0) |
                                  (APP_CMD_MACRO if c['flags'] & CMD_MACRO else 0),
                         'mod': c['mod'], 'key': c['key'] or None,
                         'scene': None if c['scene'] == 0xFF else scene(c['scene']),
                         'param': None if c['param'] == 0xFF else prm(c['param'])})
        rings.append({'name': r['name'], 'tab': r['tab'], 'slot': r['slot'], 'cmds': cmds})
    return {'id': m['id'], 'name': m['name'], 'legend': list(m['legend']), 'visual': m['visual'],
            'shape': m['shape'], 'style': m['style'], 'stepped': bool(m['stepped']), 'plasma': list(m['plasma']),
            'icon24': None if m['icon24'] is None else zlib.crc32(m['icon24']),
            'icon48': None if m['icon48'] is None else zlib.crc32(m['icon48']), 'has_slots': True,
            'slots': [dict(s) for s in m['slots']], 'search': dict(m['search']), 'rings': rings,
            'crc': struct.unpack('<I', blob[-4:])[0], 'features': features_of(m)}


def compare(path, want, got, problems):
    """Field-by-field equality; floats compared as float32."""
    if isinstance(want, dict):
        if not isinstance(got, dict):
            problems.append(f'{path}: {got!r} is not an object')
            return
        for key in want:
            if key not in got:
                problems.append(f'{path}.{key}: missing')
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


def shared_indexes(m, got, problems):
    """One wire scene / param index is one struct: equal index <-> equal offset."""
    for kind in ('scene', 'param'):
        seen = {}
        for r, ring in enumerate(m['rings']):
            for c, command in enumerate(ring['cmds']):
                index = command[kind]
                at = got['rings'][r]['cmds'][c][f'{kind}_at']
                if index == 0xFF:
                    continue
                if index in seen and seen[index] != at:
                    problems.append(f'{kind} {index}: two structs')
                seen[index] = at
        if len(set(seen.values())) != len(seen):
            problems.append(f'{kind}: two indexes share a struct')


# ------------------------------------------------------------------------------------------------ build / run
def msvc_env_x86():
    """The same MSVC, 32-bit target: ILP32 like the ESP32-S3, so ArduinoJson's slots and the decoded structs
    have the knob's sizes (heap and size figures only)."""
    cl, env = msvc_env()
    env['LIB'] = ';'.join(str(Path(entry).parent / 'x86') if Path(entry).name == 'x64' else entry
                          for entry in env['LIB'].split(';'))
    return cl.parent.parent / 'x86' / 'cl.exe', env


def build(out: Path, asan=False, x86=False) -> Path:
    cl, env = msvc_env_x86() if x86 else msvc_env()
    tag = 'asan' if asan else 'x86' if x86 else 'w4'
    obj = out / f'obj-{tag}'
    obj.mkdir(parents=True, exist_ok=True)
    extra = ['/fsanitize=address', '/Zi'] if asan else []
    for unit in UNITS_C:
        subprocess.run([str(cl), '/nologo', '/TC', '/std:c11', '/W4', '/WX', '/O2', *extra, '/c', f'/I{src}',
                        str(src / unit), f'/Fo{obj}\\'], cwd=out, env=env, check=True, capture_output=True)
    exe = out / f'app_store_tests_{tag}.exe'
    run = subprocess.run([str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', *extra,
                          '/D_CRT_SECURE_NO_WARNINGS', f'/I{src}', f'/external:I{arduinojson}', '/external:W0',
                          str(root / 'app_store_tests.cpp'), *(str(src / unit) for unit in UNITS_CPP),
                          *(str(obj / (Path(u).stem + '.obj')) for u in UNITS_C), f'/Fo{obj}\\', f'/Fe{exe}'],
                         cwd=out, env=env, capture_output=True, text=True)
    if run.returncode:
        print(run.stdout, run.stderr)
        raise SystemExit(f'FAIL: {tag} build')
    return exe


def run_env(asan):
    env = dict(os.environ)
    if asan:   # clang_rt.asan_dynamic-x86_64.dll sits next to cl.exe
        cl, _ = msvc_env()
        env['PATH'] = str(cl.parent) + os.pathsep + env.get('PATH', '')
        env['ASAN_OPTIONS'] = 'detect_leaks=0:halt_on_error=1'
    return env


def write_blobs(path: Path, blobs):
    data = bytearray()
    for blob, fail in blobs:
        data += struct.pack('<IB', len(blob), 1 if fail else 0) + blob
    path.write_bytes(bytes(data))


def decode_all(exe, blobs, out: Path):
    path = out / 'blobs.bin'
    write_blobs(path, blobs)
    run = subprocess.run([str(exe), 'decode', str(path)], capture_output=True, text=True)
    if run.returncode:
        raise SystemExit(f'FAIL decode run: {run.returncode} {run.stderr[-2000:]}')
    return [json.loads(line) for line in run.stdout.splitlines() if line.strip()]


def script(exe, ops, out: Path, name='script', env=None):
    path = out / f'{name}.jsonl'
    path.write_text('\n'.join(json.dumps(op, separators=(',', ':')) for op in ops) + '\n', encoding='utf-8')
    run = subprocess.run([str(exe), 'script', str(path)], capture_output=True, text=True, env=env)
    if run.returncode:
        raise SystemExit(f'FAIL script run: {run.returncode} {run.stderr[-2000:]}')
    results = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    if len(results) != len(ops):
        raise SystemExit(f'FAIL script {name}: {len(results)} results for {len(ops)} ops')
    return results


# ------------------------------------------------------------------------------------------------ cases
def reject_cases():
    """(name, blob, code, offset, fail_alloc)."""
    cases = []
    base = full()
    good, marks = encode(base)

    def mutate(name, code, at, patch=None, model=None, **kw):
        m = copy.deepcopy(model if model is not None else base)
        if patch:
            patch(m)
        blob, mk = encode(m, **kw)
        cases.append((name, blob, code, mk[at] if isinstance(at, str) else at(blob, mk), False))

    # 1 short: the body ends inside a field (total and crc right); a blob below the 4-byte magic.
    body = bytearray(good[:-4])
    cut = bytes(body[:-1])   # the last command's param byte is missing
    resealed = bytearray(cut) + b'\0\0\0\0'
    struct.pack_into('<I', resealed, 8, len(resealed))
    struct.pack_into('<I', resealed, len(resealed) - 4, zlib.crc32(bytes(resealed[:-4])))
    cases.append(('short-body', bytes(resealed), 1, len(resealed) - 4, False))
    cases.append(('short-2-bytes', b'DD', 1, 0, False))
    cases.append(('short-header', b'DDAP\x01\x00\x00\x00\x10\x00', 1, 8, False))
    tiny = b'DDAP\x01\x00\x00\x00' + struct.pack('<II', 19, 4) + b'\x00\x00\x00'
    cases.append(('short-under-20', tiny, 1, 19, False))
    # Count inflation without the bytes: one ring announced, none follows.
    lie, lmk = encode(minimal())
    lie = bytearray(lie[:-4])
    lie[lmk['rings']] = 1
    lie += b'\0\0\0\0'
    struct.pack_into('<I', lie, 8, len(lie))
    struct.pack_into('<I', lie, len(lie) - 4, zlib.crc32(bytes(lie[:-4])))
    cases.append(('short-ring-lie', bytes(lie), 1, len(lie) - 4, False))
    # 2 magic, 3 wire, 4 total.
    mutate('magic', 2, 'magic', magic=b'DDAQ')
    mutate('wire-2', 3, 'wire', wire=2)
    mutate('wire-0', 3, 'wire', wire=0)
    mutate('total-plus-1', 4, 'total', total=len(good) + 1)
    mutate('total-minus-1', 4, 'total', total=len(good) - 1)
    cases.append(('truncated', good[:-1], 4, 8, False))
    over = encode(exact_size(32768)[0], tail=b'\0')[0]
    cases.append(('total-32769', over, 4, 8, False))
    # 5 crc.
    mutate('crc', 5, lambda b, mk: len(b) - 4, crc=zlib.crc32(good[:-4]) ^ 1)
    flipped = bytearray(good)
    flipped[marks['name'] + 1] ^= 0x01
    cases.append(('crc-body-flip', bytes(flipped), 5, len(good) - 4, False))
    # 6 feature: an unknown bit, a bit the content does not use, a bit missing.
    mutate('feature-unknown', 6, 'features', features=features_of(base) | 0x20)
    mutate('feature-extra', 6, 'features', features=features_of(base) | FEAT_LABEL)
    mutate('feature-missing', 6, 'features', features=features_of(base) & ~FEAT_DISABLED)
    # 7 string.
    mutate('name-16', 7, 'name', patch=lambda m: m.update(name='N' * 16))
    mutate('name-empty', 7, 'name', patch=lambda m: m.update(name=''))
    mutate('legend-8', 7, 'legend2', patch=lambda m: m['legend'].__setitem__(2, 'L' * 8))
    mutate('name-del', 7, lambda b, mk: mk['name'] + 2, patch=lambda m: m.update(name='A\x7fB'))
    mutate('name-ctl', 7, lambda b, mk: mk['name'] + 1, patch=lambda m: m.update(name='\x1fB'))
    mutate('slot-label-24', 7, 'slot3.label', patch=lambda m: m['slots'][3].update(label='L' * 24))
    mutate('search-key-8', 7, 'search.key', patch=lambda m: m['search'].update(key='K' * 8))
    mutate('param-label-empty', 7, 'p0.label', patch=lambda m: m['params'][0].update(label=''))
    mutate('tab-7', 7, 'r0.tab', patch=lambda m: m['rings'][0].update(tab='T' * 7))
    mutate('cmd-name-24', 7, 'r1.c0.name', patch=lambda m: m['rings'][1]['cmds'][0].update(name='C' * 24))
    mutate('cmd-key-high', 7, lambda b, mk: mk['r0.c0.key'] + 1, patch=lambda m: m['rings'][0]['cmds'][0].update(key='\xe9'))
    # 8 range.
    mutate('reserved8', 8, 'reserved8', reserved=(1, 0))
    mutate('reserved16', 8, 'reserved16', reserved=(0, 0x100))
    mutate('visual-2', 8, 'visual', patch=lambda m: m.update(visual=2), features=features_of(base))
    mutate('label-shape', 8, 'shape', patch=lambda m: m.update(visual=0, shape=1))
    mutate('shape-3', 8, 'shape', patch=lambda m: m.update(shape=3))
    mutate('style-3', 8, 'style', patch=lambda m: m.update(style=3))
    mutate('stepped-2', 8, 'stepped', patch=lambda m: m.update(stepped=2))
    mutate('plasma-24bit', 8, 'plasma1', patch=lambda m: m['plasma'].__setitem__(1, 0x1000000))
    mutate('icons-bit2', 8, 'icons', patch=lambda m: m.update(icons_byte=4 | 3))
    mutate('slot-kind-6', 8, 'slot2.kind', patch=lambda m: m['slots'][2].update(kind=6))
    mutate('slot-fx-5', 8, 'slot2.fx', patch=lambda m: m['slots'][2].update(fx=5))
    mutate('slot-button-4', 8, 'slot2.button', patch=lambda m: m['slots'][2].update(button=4))
    mutate('search-mod-16', 8, 'search.mod', patch=lambda m: m['search'].update(mod=0x10))
    mutate('param-start-below-min', 8, 'p0.start', patch=lambda m: m['params'][0].update(start=-11.0))
    mutate('param-min-above-max', 8, 'p0.start', patch=lambda m: m['params'][0].update(min=200.0, start=200.0))
    mutate('param-decimals-5', 8, 'p0.decimals', patch=lambda m: m['params'][0].update(decimals=5))
    mutate('param-flags-16', 8, 'p0.flags', patch=lambda m: m['params'][0].update(flags=0x10))
    mutate('param-visual-10', 8, 'p0.visual', patch=lambda m: m['params'][0].update(visual=10))
    mutate('param-modes-16', 8, 'p0.modes', patch=lambda m: m['params'][0].update(modes=16))
    mutate('param-axis-4', 8, 'p0.axis_default', patch=lambda m: m['params'][0].update(axis_default=4))
    mutate('param-field-2', 8, 'p0.field', patch=lambda m: m['params'][0].update(field=2))
    mutate('el-op-15', 8, 's0.base.1', patch=lambda m: m['scenes'][0]['base'][1].__setitem__(0, 15))
    mutate('el-color-5', 8, lambda b, mk: mk['s0.base.0'] + 1,
           patch=lambda m: m['scenes'][0]['base'][0].__setitem__(1, 5))
    mutate('frame-el-op', 8, 's0.f1.el.0', patch=lambda m: m['scenes'][0]['frames'][1]['el'][0].__setitem__(0, 200))
    mutate('frame-ms-60001', 8, 's0.f1.ms', patch=lambda m: m['scenes'][0]['frames'][1].update(ms=60001))
    mutate('ring-slot-5', 8, 'r1.slot', patch=lambda m: m['rings'][1].update(slot=5))
    mutate('cmd-flags-8', 8, 'r0.c0.flags', patch=lambda m: m['rings'][0]['cmds'][0].update(flags=8))
    mutate('cmd-mod-16', 8, 'r0.c0.mod', patch=lambda m: m['rings'][0]['cmds'][0].update(mod=0x10))
    mutate('search-with-key', 8, 'r0.c1.key', patch=lambda m: m['rings'][0]['cmds'][1].update(key='S'))
    mutate('macro-with-key', 8, 'r0.c2.key', patch=lambda m: m['rings'][0]['cmds'][2].update(key='M'))
    # 9 count.
    mutate('params-33', 9, 'params', model=many_params(), patch=lambda m: m['params'].append(param('X')))
    mutate('scenes-129', 9, 'scenes', model=many_scenes(),
           patch=lambda m: m['scenes'].append({'base': [], 'frames': []}))
    mutate('base-49', 9, 's0.base', model=dense_scene(),
           patch=lambda m: m['scenes'][0]['base'].append([0] * 9))
    mutate('frames-17', 9, 's0.frames', model=dense_scene(),
           patch=lambda m: m['scenes'][0]['frames'].append({'ms': 1, 'el': []}))
    mutate('frame-el-49', 9, 's0.f3.el', model=dense_scene(),
           patch=lambda m: m['scenes'][0]['frames'][3]['el'].append([0] * 9))
    mutate('rings-9', 9, 'rings', model=big_rings(),
           patch=lambda m: m['rings'].append({'name': 'N', 'tab': 'N', 'slot': 0, 'cmds': [cmd()]}))
    mutate('cmds-33', 9, 'r7.cmds', model=big_rings(), patch=lambda m: m['rings'][7]['cmds'].append(cmd()))
    mutate('cmds-0', 9, 'r1.cmds', patch=lambda m: m['rings'][1].update(cmds=[]))
    # 10 index.
    mutate('scene-index', 10, 'r0.c0.scene', patch=lambda m: m['rings'][0]['cmds'][0].update(scene=3))
    mutate('param-index', 10, 'r1.c0.param', patch=lambda m: m['rings'][1]['cmds'][0].update(param=2))
    mutate('scene-index-254', 10, 'r0.c0.scene', patch=lambda m: m['rings'][0]['cmds'][0].update(scene=254))
    mutate('param-index-none-params', 10, 'r0.c0.param', model=minimal(),
           patch=lambda m: m.update(rings=[{'name': 'R', 'tab': 'R', 'slot': 0, 'cmds': [cmd(param=0)]}]))
    # 11 id.
    for name, ident in (('id-upper', 'Figma'), ('id-empty', ''), ('id-12', 'a' * 12), ('id-space', 'a b'),
                        ('id-dot', 'fig.ma'), ('id-nul', 'a\x00b')):
        mutate(name, 11, 'id', patch=lambda m, ident=ident: m.update(id=ident))
    # 12 trailing.
    mutate('trailing-1', 12, 'end', tail=b'\x00')
    mutate('trailing-4', 12, 'end', tail=b'\x01\x02\x03\x04')
    # 13 memory.
    cases.append(('no-memory', good, 13, 0, True))
    # 14 float.
    for name, field, value in (('nan', 'steps1', float('nan')), ('inf', 'free_step', float('inf')),
                               ('neg-inf', 'max', float('-inf')), ('big', 'min', -1.0000001e7),
                               ('big-step', 'steps2', 2e7)):
        def patch(m, field=field, value=value):
            p = m['params'][1]
            if field.startswith('steps'):
                p['steps'][int(field[-1])] = value
            else:
                p[field] = value
        mutate(f'float-{name}', 14, f'p1.{field}', patch=patch)
    return cases


def accept_models():
    m_exact, _ = exact_size(32768)
    return [('minimal', minimal()), ('full', full()), ('big-rings', big_rings()), ('many-scenes', many_scenes()),
            ('dense-scene', dense_scene()), ('many-params', many_params()), ('exact-32768', m_exact),
            ('label-icon24-only', dict(minimal('lbl'), icon24=icon(1152, 5))),
            ('shape-icon48-only', dict(minimal('shp'), visual=1, icon48=icon(4608, 6))),
            ('id-chars', dict(minimal('a-z_0-9xyzq'), name='~ !"#$%&\'()*+,')),
            ('float-edges', dict(minimal('fe'), params=[param(steps=[1e7, -1e7, 0.0], start=1e7, min=-1e7, max=1e7,
                                                             free_step=-0.0)]))]


# ------------------------------------------------------------------------------------------------ store
def msg(now, **request):
    return {'op': 'msg', 'now': now, 'line': json.dumps({'appProfile': request}, separators=(',', ':'))}


def upload_ops(blob, ident, now=0, chunk=2250, crc=None, bytes_=None):
    c = zlib.crc32(blob[:-4]) if crc is None else crc
    ops = [msg(now, op='begin', id=ident, bytes=len(blob) if bytes_ is None else bytes_, crc=c, wire=1)]
    for off in range(0, len(blob), chunk):
        ops.append(msg(now, op='data', off=off, b64=base64.b64encode(blob[off:off + chunk]).decode()))
    ops.append(msg(now, op='end'))
    return ops


def fat(ident, frames=16, scenes=128):
    """A profile whose decoded size is many times its wire size (empty keyframes, short commands)."""
    m = minimal(ident)
    m['scenes'] = [{'base': [], 'frames': [{'ms': 0, 'el': []}] * frames} for _ in range(scenes)]
    m['rings'] = [{'name': 'R', 'tab': 'R', 'slot': 0, 'cmds': [cmd('C', 0, 0, '') for _ in range(32)]}
                  for _ in range(8)]
    return m


class Checker:
    def __init__(self):
        self.failures = 0
        self.passes = 0

    def check(self, ok, name, detail=''):
        if ok:
            self.passes += 1
        else:
            self.failures += 1
            print(f'FAIL {name}{": " + detail if detail else ""}')


def store_tests(exe, out, c: Checker):
    """One script against one store: built-in, upload, replacement, LRU, pins across eviction, the budget, busy."""
    ops, checks = [], []
    handles = [0]

    def op(o, check=None, name=''):
        ops.append(o)
        checks.append((check, name))
        return len(ops) - 1

    def acquire(ident, crc, check=None, name=''):
        op({'op': 'acquire', 'id': ident, 'crc': crc}, check, name)
        handles[0] += 1
        return handles[0] - 1

    def upload(m, now=0, name=''):
        blob = encode(m)[0]
        seq = upload_ops(blob, m['id'], now)
        crc = zlib.crc32(blob[:-4])
        op(seq[0], lambda r: not r['sent'], f'{name}: begin {m["id"]}')
        for o in seq[1:-1]:
            op(o, lambda r: 'ack' in r['reply']['appProfile'], f'{name}: data {m["id"]}')
        op(seq[-1], lambda r: r['reply'] == {'appProfile': {'id': m['id'], 'crc': crc, 'ok': True}},
           f'{name}: end {m["id"]}')
        return crc

    def listed(ids):
        return lambda r: [x['id'] for x in r['loaded']] == ids

    def blocks(n):
        return lambda r: r['blocks'] == n and not r['active'] and r['depthErrors'] == 0

    op({'op': 'init'})
    sizes = op({'op': 'sizes'})
    # The built-in Onshape with nothing loaded.
    h = acquire('onshape', 0, lambda r: r['builtin'] and r['name'] == 'ONSHAPE', 'built-in for (onshape, 0)')
    op({'op': 'release', 'h': h})
    acquire('onshape', 5, lambda r: r['null'], '(onshape, 5) not loaded')
    acquire('figma', 0, lambda r: r['null'], 'unknown id')
    op({'op': 'acquire', 'null': True}, lambda r: r['null'], 'NULL id')
    handles[0] += 1
    op({'op': 'list'}, listed([]), 'empty list')
    # A full upload: begin silent, the acks, ok, list, acquire by crc.
    fig_blob = encode(full('figma'))[0]
    fig_crc = zlib.crc32(fig_blob[:-4])
    seq = upload_ops(fig_blob, 'figma', 10)
    op(seq[0], lambda r: not r['sent'] and r['active'], 'begin has no reply')
    acks = list(range(2250, len(fig_blob), 2250)) + [len(fig_blob)]
    for o, n in zip(seq[1:-1], acks):
        op(o, lambda r, n=n: r['reply'] == {'appProfile': {'ack': n}}, f'ack {n}')
    op(seq[-1], lambda r: r['reply'] == {'appProfile': {'id': 'figma', 'crc': fig_crc, 'ok': True}} and
       not r['active'], 'end ok')
    op({'op': 'list'}, lambda r: r['loaded'] == [{'id': 'figma', 'crc': fig_crc}], 'list one')
    op(msg(11, op='list'), lambda r: r['reply'] == {'appProfile': {'loaded': [{'id': 'figma', 'crc': fig_crc}]}},
       'list message')
    h_fig = acquire('figma', fig_crc, lambda r: r['name'] == 'FIGMA DESIGNER' and r['allocated'], 'acquire figma')
    acquire('figma', fig_crc ^ 1, lambda r: r['null'], 'crc mismatch -> NULL')
    acquire('figma', 0, lambda r: r['null'], 'crc 0 -> NULL for an upload')
    # Replacement while acquired: the old copy stays allocated and readable until its release.
    fig2 = full('figma')
    fig2['name'] = 'FIGMA TWO'
    fig2_crc = upload(fig2, 20, 'replace')
    acquire('figma', fig_crc, lambda r: r['null'], 'old crc gone after the replace')
    h_fig2 = acquire('figma', fig2_crc, lambda r: r['name'] == 'FIGMA TWO', 'the new copy')
    op({'op': 'list'}, lambda r: r['loaded'] == [{'id': 'figma', 'crc': fig2_crc}], 'one figma after the replace')
    op({'op': 'stats'}, blocks(2), 'the old copy is still allocated while acquired')
    op({'op': 'release', 'h': h_fig}, lambda r: r['readable'] and r['name'] == 'FIGMA DESIGNER',
       'the old copy is readable until its release')
    op({'op': 'stats'}, blocks(1), 'the old copy is freed at its release')
    op({'op': 'release', 'h': h_fig2})
    op({'op': 'release', 'h': h_fig2}, None, 'a second release is ignored')
    op({'op': 'stats'}, blocks(1), 'release balance')
    # An uploaded "onshape": (onshape, 0) stays the built-in, (onshape, C) is the upload.
    on = full('onshape')
    on['name'] = 'UP ONSHAPE'
    on_crc = upload(on, 30, 'onshape')
    h = acquire('onshape', 0, lambda r: r['builtin'], '(onshape, 0) is still the built-in')
    op({'op': 'release', 'h': h})
    h = acquire('onshape', on_crc, lambda r: r['name'] == 'UP ONSHAPE' and not r['builtin'], '(onshape, C) is the upload')
    op({'op': 'release', 'h': h})

    # LRU over 4 slots by last draw (an upload counts as a draw).
    op({'op': 'init'})
    crcs = {ident: upload(minimal(ident), 100 + i, 'lru') for i, ident in enumerate('abcd')}
    op({'op': 'list'}, listed(['d', 'c', 'b', 'a']), 'list: most recently drawn first')
    op({'op': 'list', 'max': 2}, listed(['d', 'c']), 'list max 2')
    h = acquire('a', crcs['a'], lambda r: not r['null'], 'draw a')
    op({'op': 'release', 'h': h})
    upload(minimal('e'), 110, 'lru')
    op({'op': 'list'}, listed(['e', 'a', 'd', 'c']), 'the 5th upload evicts b, the least recently drawn')
    # An acquired entry evicted: no longer found, still allocated and readable, freed at its release.
    h_c = acquire('c', crcs['c'], lambda r: not r['null'], 'pin c')
    for ident in 'fgh':
        upload(minimal(ident), 120, 'evict')
    op({'op': 'list'}, listed(['h', 'g', 'f', 'c']), 'c (drawn) outlives d, a, e')
    upload(minimal('i'), 121, 'evict')
    op({'op': 'list'}, listed(['i', 'h', 'g', 'f']), 'c evicted while acquired')
    op({'op': 'stats'}, blocks(5), 'the evicted c is not freed while acquired')
    acquire('c', crcs['c'], lambda r: r['null'], 'the evicted c is not found')
    op({'op': 'release', 'h': h_c}, lambda r: r['readable'] and r['name'] == 'M', 'the evicted c is readable to the end')
    op({'op': 'stats'}, blocks(4), 'c is freed at its release')

    # The 128 KB budget, with profiles that decode to many times their wire size.
    op({'op': 'init'})
    fat_crcs = {ident: upload(fat(ident), 200, 'budget') for ident in ('fa', 'fb')}
    two = op({'op': 'stats'})
    upload(fat('fc'), 201, 'budget')
    third = op({'op': 'list'})
    third_stats = op({'op': 'stats'})
    # Every slot pinned and no room: busy, and nothing changes.
    op({'op': 'init'})
    pins = {}
    for ident in ('pa', 'pb'):
        crc = upload(fat(ident), 300, 'busy')
        pins[ident] = acquire(ident, crc, lambda r: not r['null'], f'pin {ident}')
    pc_blob = encode(fat('pc'))[0]
    seq = upload_ops(pc_blob, 'pc', 301)
    for o in seq[:-1]:
        op(o)
    op(seq[-1], lambda r: r['reply'] == {'appProfile': {'error': 'busy'}}, 'busy: the pinned entries fill the budget')
    op({'op': 'list'}, listed(['pb', 'pa']), 'busy changes nothing')
    op({'op': 'stats'}, blocks(2), 'busy frees its staging buffer')
    # One pin released: the same upload fits by evicting that entry; the pinned one stays.
    op({'op': 'release', 'h': pins['pb']})
    upload(fat('pc'), 302, 'after busy')
    op({'op': 'list'}, listed(['pc', 'pa']), 'the released pb is evicted, the pinned pa stays')
    op({'op': 'release', 'h': pins['pa']})
    # PSRAM exhausted at the decode (an allocator limit stands in for it): no memory, nothing changes.
    seq = upload_ops(encode(full('toolong'))[0], 'toolong', 400)
    for o in seq[:-1]:
        op(o)
    op({'op': 'alloc', 'limit': 32768 + 1000})   # the staging buffer is allocated; the decode no longer fits
    op(seq[-1], lambda r: r['reply'] == {'appProfile': {'error': 'decode:13@0'}}, 'PSRAM exhausted -> decode:13@0')
    op({'op': 'list'}, listed(['pc', 'pa']), 'a failed decode changes nothing')
    op({'op': 'stats'}, lambda r: r['depthErrors'] == 0, 'the lock is never taken twice')

    results = script(exe, ops, out, 'store')
    for (check, name), o, r in zip(checks, ops, results):
        if check is None:
            continue
        try:
            ok = check(r)
        except Exception as error:  # noqa: BLE001
            ok, name = False, f'{name} ({error!r})'
        c.check(ok, f'store: {name}', f'{json.dumps(o)[:120]} -> {json.dumps(r)[:240]}')
    fat_bytes = results[two]['liveBytes'] // 2
    if 3 * fat_bytes > 128 * 1024 and 2 * fat_bytes <= 128 * 1024:
        c.check([x['id'] for x in results[third]['loaded']] == ['fc', 'fb'],
                'store: the budget evicts the least recently drawn', json.dumps(results[third]))
        c.check(results[third_stats]['liveBytes'] <= 128 * 1024, 'store: live bytes within 128 KB',
                json.dumps(results[third_stats]))
    else:
        c.check(False, 'store: the fat profiles do not exercise the budget', str(fat_bytes))
    del fat_crcs
    print(f'store: {sum(1 for ch, _ in checks if ch)} checks; a fat profile decodes to {fat_bytes} B from '
          f'{len(encode(fat("x"))[0])} B of wire (x64); sizeof(CCFrame) {results[sizes]["CCFrame"]} B, '
          f'sizeof(CCAppState) {results[sizes]["CCAppState"]} B (MSVC x64)')


def upload_tests(exe, out, c: Checker):
    """The state machine and the request layer, one scenario per list (a fresh store each)."""
    good_m = full('figma')
    good = encode(good_m)[0]
    crc = zlib.crc32(good[:-4])
    b64 = lambda data: base64.b64encode(data).decode()  # noqa: E731
    begin = lambda now=0, **kw: msg(now, **dict({'op': 'begin', 'id': 'figma', 'bytes': len(good), 'crc': crc,  # noqa: E731
                                                 'wire': 1}, **kw))
    data = lambda off, chunk, now=0: msg(now, op='data', off=off, b64=b64(chunk))  # noqa: E731
    end = lambda now=0: msg(now, op='end')  # noqa: E731
    err = lambda e: (lambda r: r['reply'] == {'appProfile': {'error': e}})  # noqa: E731
    ack = lambda n: (lambda r: r['reply'] == {'appProfile': {'ack': n}})  # noqa: E731
    silent = lambda r: not r['sent']  # noqa: E731
    inactive = lambda r: not r['active']  # noqa: E731
    stats_blocks = lambda n: (lambda r: r['blocks'] == n)  # noqa: E731

    bad_decode = encode(full('figma'), features=features_of(good_m) | 0x40)[0]
    bad_decode_crc = zlib.crc32(bad_decode[:-4])
    other_id = encode(full('other'))[0]
    scenarios = {
        'data-before-begin': [(data(0, good[:100]), err('order'))],
        'end-before-begin': [(end(), err('order'))],
        'wrong-offset': [(begin(), silent), (data(0, good[:300]), ack(300)), (data(301, good[300:600]), err('order')),
                         ({'op': 'stats'}, lambda r: not r['active'] and r['blocks'] == 0),
                         (data(300, good[300:600]), err('order'))],
        'repeat-offset': [(begin(), silent), (data(0, good[:300]), ack(300)), (data(0, good[:300]), err('order'))],
        'past-bytes': [(begin(bytes=100), silent), (data(0, good[:99]), ack(99)), (data(99, good[99:102]), err('size')),
                       ({'op': 'stats'}, stats_blocks(0))],
        'end-short': [(begin(), silent), (data(0, good[:300]), ack(300)), (end(), err('size')),
                      ({'op': 'stats'}, stats_blocks(0))],
        'crc-mismatch': [(begin(crc=crc ^ 0x80000000), silent), *[(data(o, good[o:o + 2250]), None)
                                                                  for o in range(0, len(good), 2250)],
                         (end(), err('crc')), ({'op': 'list'}, lambda r: r['loaded'] == [])],
        'wire-2': [(begin(wire=2), err('wire')), ({'op': 'stats'}, lambda r: not r['active'])],
        'wire-missing': [(msg(0, op='begin', id='figma', bytes=10, crc=1), err('wire'))],
        'bytes-0': [(begin(bytes=0), err('size'))],
        'bytes-32769': [(begin(bytes=32769), err('size'))],
        'bytes-32768': [(begin(bytes=32768), silent), ({'op': 'stats'}, lambda r: r['liveBytes'] == 32768)],
        'bytes-string': [(begin(bytes='100'), err('size'))],
        'bytes-float': [(begin(bytes=100.5), err('size'))],
        'crc-negative': [(begin(crc=-1), err('crc'))],
        'crc-bool': [(begin(crc=True), err('crc'))],
        'crc-max': [(begin(crc=0xFFFFFFFF), silent)],
        'crc-2^32': [(begin(crc=1 << 32), err('crc'))],
        'id-upper': [(begin(id='Figma'), err('order'))],
        'id-12': [(begin(id='a' * 12), err('order'))],
        'id-missing': [(msg(0, op='begin', bytes=10, crc=1, wire=1), err('order'))],
        'id-number': [(begin(id=7), err('order'))],
        'id-nul': [(begin(id='fig\u0000'), err('order'))],
        'op-unknown': [(msg(0, op='commit'), err('order'))],
        'op-missing': [(msg(0, id='x'), err('order'))],
        'not-object': [({'op': 'msg', 'now': 0, 'line': '{"appProfile":"list"}'}, err('order'))],
        'off-missing': [(begin(), silent), (msg(0, op='data', b64=b64(good[:3])), err('order')),
                        ({'op': 'stats'}, lambda r: not r['active'] and r['blocks'] == 0)],
        'off-negative': [(begin(), silent), (msg(0, op='data', off=-1, b64=b64(good[:3])), err('order'))],
        'b64-missing': [(begin(), silent), (msg(0, op='data', off=0), err('order'))],
        'b64-number': [(begin(), silent), (msg(0, op='data', off=0, b64=12), err('order'))],
        'b64-empty': [(begin(), silent), (msg(0, op='data', off=0, b64=''), err('size'))],
        'b64-3001': [(begin(), silent), (msg(0, op='data', off=0, b64='A' * 3001), err('size'))],
        'b64-3000': [(begin(), silent), (msg(0, op='data', off=0, b64=b64(good[:2250])), ack(2250))],
        'b64-not-multiple-4': [(begin(), silent), (msg(0, op='data', off=0, b64='QUJD' + 'QQ'), err('size'))],
        'b64-bad-char': [(begin(), silent), (msg(0, op='data', off=0, b64='QU*D'), err('size'))],
        'b64-url-alphabet': [(begin(), silent), (msg(0, op='data', off=0, b64='-_-_'), err('size'))],
        'b64-inner-pad': [(begin(), silent), (msg(0, op='data', off=0, b64='QQ==QUJD'), err('size'))],
        'b64-pad-3': [(begin(), silent), (msg(0, op='data', off=0, b64='Q==='), err('size'))],
        'b64-pad-1': [(begin(), silent), (msg(0, op='data', off=0, b64='QUI='), ack(2))],
        'b64-pad-2': [(begin(), silent), (msg(0, op='data', off=0, b64='QQ=='), ack(1))],
        'b64-null-c-api': [(begin(), silent), ({'op': 'data_null', 'off': 0}, lambda r: r['result'] == 'order'),
                           ({'op': 'stats'}, lambda r: not r['active'])],
        'stall-1999': [(begin(1000), silent), (data(0, good[:300], 2999), ack(300)),
                       (data(300, good[300:600], 4998), ack(600))],
        'stall-2000': [(begin(1000), silent), (data(0, good[:300], 3000), err('order')),
                       ({'op': 'stats'}, lambda r: not r['active'] and r['blocks'] == 0)],
        'stall-poll': [(begin(1000), silent), ({'op': 'poll', 'now': 2999}, lambda r: r['active']),
                       ({'op': 'poll', 'now': 3000}, inactive), ({'op': 'stats'}, stats_blocks(0)),
                       (end(3001), err('order'))],
        'stall-wraps': [(begin(0xFFFFFF00), silent), (data(0, good[:300], 0x100), ack(300)),
                        ({'op': 'poll', 'now': 0x100 + 1999}, lambda r: r['active']),
                        ({'op': 'poll', 'now': 0x100 + 2000}, inactive)],
        'begin-aborts': [(begin(), silent), (data(0, good[:300]), ack(300)), ({'op': 'stats'}, stats_blocks(1)),
                         (begin(), silent), ({'op': 'stats'}, stats_blocks(1)),
                         *[(data(o, good[o:o + 2250]), ack(min(o + 2250, len(good))))
                           for o in range(0, len(good), 2250)],
                         (end(), lambda r: r['reply']['appProfile'].get('ok') is True)],
        'begin-restarts-offset': [(begin(), silent), (data(0, good[:300]), ack(300)), (begin(), silent),
                                  (data(300, good[300:600]), err('order'))],
        'begin-bad-aborts': [(begin(), silent), (begin(wire=9), err('wire')), ({'op': 'stats'}, stats_blocks(0)),
                             (data(0, good[:3]), err('order'))],
        'staging-no-memory': [({'op': 'alloc', 'failNext': 1}, None), (begin(), err('busy')),
                              ({'op': 'stats'}, lambda r: not r['active'])],
        'decode-error': [(msg(0, op='begin', id='figma', bytes=len(bad_decode), crc=bad_decode_crc, wire=1), silent),
                         *[(msg(0, op='data', off=o, b64=b64(bad_decode[o:o + 2250])), None)
                           for o in range(0, len(bad_decode), 2250)],
                         (end(), err('decode:6@12')), ({'op': 'stats'}, stats_blocks(0))],
        'decode-id-mismatch': [(msg(0, op='begin', id='figma', bytes=len(other_id), crc=zlib.crc32(other_id[:-4]),
                                    wire=1), silent),
                               *[(msg(0, op='data', off=o, b64=b64(other_id[o:o + 2250])), None)
                                 for o in range(0, len(other_id), 2250)],
                               (end(), err('decode:11@16')), ({'op': 'stats'}, stats_blocks(0)),
                               ({'op': 'list'}, lambda r: r['loaded'] == [])],
        'decode-no-memory': [(begin(), silent), *[(data(o, good[o:o + 2250]), None) for o in range(0, len(good), 2250)],
                             ({'op': 'alloc', 'failNext': 1}, None), (end(), err('decode:13@0')),
                             ({'op': 'stats'}, stats_blocks(0))],
        'short-blob': [(msg(0, op='begin', id='figma', bytes=3, crc=0, wire=1), silent),
                       (msg(0, op='data', off=0, b64=b64(b'DDA')), ack(3)), (end(), err('decode:1@0'))],
        'one-byte-chunks': [(begin(), silent), *[(data(o, good[o:o + 1]), ack(o + 1)) for o in range(0, 40)]],
        'end-twice': [*[(o, None) for o in upload_ops(good, 'figma')], (end(), err('order'))],
        'list-not-active': [*[(o, None) for o in upload_ops(good, 'figma')],
                            (msg(0, op='list'), lambda r: r['reply'] == {'appProfile': {'loaded': [
                                {'id': 'figma', 'crc': crc}]}})],
    }
    total = 0
    for name, steps in scenarios.items():
        ops = [{'op': 'init'}] + [s[0] for s in steps] + [{'op': 'stats'}]
        results = script(exe, ops, out, 'upload')
        for (o, check), r in zip(steps, results[1:]):
            if check is not None:
                total += 1
                c.check(check(r), f'upload {name}', f'{json.dumps(o)[:160]} -> {json.dumps(r)[:200]}')
        # Nothing leaks: at the end only a stored profile (and a still-active staging buffer) is allocated.
        final = results[-1]
        c.check(final['depthErrors'] == 0, f'upload {name}: lock depth')
    print(f'upload: {len(scenarios)} scenarios, {total} checks')


def heap_tests(exe, out, c: Checker, label='x86, ILP32 as the knob', check=True):
    """The internal heap of the longest data line (3000 b64 characters), as ArduinoJson 7.0.2 allocates it."""
    chunk = bytes(range(256)) * 9
    line = json.dumps({'appProfile': {'op': 'data', 'off': 30000, 'b64': base64.b64encode(chunk[:2250]).decode()}},
                      separators=(',', ':'))
    ops = [{'op': 'init'}, msg(0, op='begin', id='heap', bytes=32768, crc=1, wire=1),
           {'op': 'heap', 'line': line, 'now': 0}]
    r = script(exe, ops, out, 'heap')[2]
    if check:
        c.check(r['parsePeakInternal'] <= 6 * 1024, 'heap: internal transient <= 6 KB', str(r))
    c.check(r['lineBytes'] <= 4096, 'heap: the longest data line fits the 4096 B line limit', str(r))
    print(f'heap ({label}): data line {r["lineBytes"]} B; ArduinoJson parse peak {r["parsePeak"]} B (all blocks), '
          f'{r["parsePeakInternal"]} B in blocks < 4096 B (internal RAM under the S3 malloc policy), largest block '
          f'{r["parseLargest"]} B, {r["heldAfterParse"]} B held after the parse ({r["heldInternal"]} B internal), '
          f'reply peak {r["replyPeak"]} B')
    return r


def frame_tests(exe, out, c: Checker):
    base = dict(BASE, id=7)

    def frame(app=None, raw=None):
        text = json.dumps({'frame': dict(base, **({'app': app} if app is not None else {}))}, separators=(',', ':'))
        if raw is not None:
            text = text[:-2] + ',"app":' + raw + '}}'
        return {'op': 'frame', 'line': text}

    def PRM(**kw):  # noqa: N802
        out_ = {'ring': 0, 'index': 1, 'mode': 'A', 'value': 0, 'step': 1}
        out_.update(kw)
        return out_

    def a(**kw):
        out_ = {'id': 'onshape', 'slot': 'zoom'}
        out_.update(kw)
        return out_

    cases = [
        ('legacy-onshape', frame(a()), True, {'id': 'onshape', 'crc': 0, 'slot': 0, 'present': True}),
        ('no-app', frame(), True, {'id': '', 'present': False}),
        ('figma-not-loaded', frame(a(id='figma')), True, {'id': 'figma', 'crc': 0}),
        ('id-11', frame(a(id='a-z_0123456')), True, {'id': 'a-z_0123456'}),
        ('id-1', frame(a(id='x')), True, {'id': 'x'}),
        ('id-12', frame(a(id='a' * 12)), False, None),
        ('id-empty', frame(a(id='')), False, None),
        ('id-upper', frame(a(id='Figma')), False, None),
        ('id-space', frame(a(id='fig ma')), False, None),
        ('id-dot', frame(a(id='fig.ma')), False, None),
        ('id-nul', frame(raw='{"id":"fig\\u0000","slot":"zoom"}'), False, None),
        ('id-number', frame(a(id=1)), False, None),
        ('id-null', frame(a(id=None)), False, None),
        ('id-missing', frame({'slot': 'zoom'}), False, None),
        ('id-non-ascii', frame(a(id='figmá')), False, None),
        ('crc-0', frame(a(crc=0)), True, {'crc': 0}),
        ('crc-max', frame(a(id='figma', crc=0xFFFFFFFF)), True, {'id': 'figma', 'crc': 0xFFFFFFFF}),
        ('crc-mid', frame(a(id='figma', crc=3735928559)), True, {'crc': 3735928559}),
        ('crc-2^32', frame(a(crc=1 << 32)), False, None),
        ('crc-negative', frame(a(crc=-1)), False, None),
        ('crc-float', frame(a(crc=1.5)), False, None),
        ('crc-string', frame(a(crc='1')), False, None),
        ('crc-bool', frame(a(crc=True)), False, None),
        ('crc-null', frame(a(crc=None)), False, None),
        *[(f'slot-{t}', frame(a(slot=t)), True, {'slot': v})
          for t, v in (('zoom', 0), ('orbit', 1), ('pan', 2), ('tilt', 3), ('knob', 4), ('f1', 5), ('f2', 6),
                       ('f3', 7), ('f4', 8))],
        ('slot-f5', frame(a(slot='f5')), False, None),
        ('slot-F1', frame(a(slot='F1')), False, None),
        ('slot-f0', frame(a(slot='f0')), False, None),
        ('slot-knob-upper', frame(a(slot='KNOB')), False, None),
        ('wheel-32', frame(a(wheel={'ring': 7, 'index': 32})), True, {'wheel': True, 'wheelRing': 7, 'wheelIndex': 32}),
        ('wheel-16', frame(a(wheel={'ring': 0, 'index': 16})), True, {'wheelIndex': 16}),
        ('wheel-33', frame(a(wheel={'ring': 0, 'index': 33})), False, None),
        ('wheel-ring-8', frame(a(wheel={'ring': 8, 'index': 0})), False, None),
        ('param-32', frame(a(param={'ring': 7, 'index': 32, 'mode': 'A', 'value': 1, 'step': 1})), True,
         {'param': True, 'paramIndex': 32, 'paramRing': 7}),
        ('param-33', frame(a(param={'ring': 0, 'index': 33, 'mode': 'A', 'value': 1, 'step': 1})), False, None),
        ('echo-32', frame(a(echo={'ring': 0, 'index': 32, 'seq': 3})), True, {'echoIndex': 32, 'echoSeq': 3}),
        ('echo-33', frame(a(echo={'ring': 0, 'index': 33, 'seq': 3})), False, None),
        ('unknown-key', frame(a(id='plasticity', crc=5, fx='zoom', future={'x': 1})), True,
         {'id': 'plasticity', 'crc': 5}),
        ('everything', frame(a(id='figma', crc=77, slot='f4', refused=True, flash=3,
                               wheel={'ring': 1, 'index': 20},
                               param={'ring': 2, 'index': 31, 'mode': 'B', 'value': -5, 'step': 2, 'bump': 4},
                               echo={'ring': 3, 'index': 30, 'seq': 9})), True,
         {'id': 'figma', 'crc': 77, 'slot': 8, 'refused': True, 'flash': 3, 'wheelIndex': 20, 'paramIndex': 31,
          'paramTyped': True, 'paramValue': -5, 'paramStep': 2, 'paramBump': 4, 'echoIndex': 30, 'echoSeq': 9}),
        # The live parameter constraint (S1, FW-B's request): axis 0..3 (absent -1), plane a bool (default false).
        ('param-no-axis', frame(a(param=PRM())), True, {'param': True, 'paramAxis': -1, 'paramPlane': False}),
        *[(f'param-axis-{n}', frame(a(param=PRM(axis=n))), True, {'paramAxis': n, 'paramPlane': False})
          for n in range(4)],
        ('param-axis-plane', frame(a(param=PRM(axis=2, plane=True))), True, {'paramAxis': 2, 'paramPlane': True}),
        ('param-plane-no-axis', frame(a(param=PRM(plane=True))), True, {'paramAxis': -1, 'paramPlane': True}),
        ('param-plane-false', frame(a(param=PRM(axis=0, plane=False))), True, {'paramAxis': 0, 'paramPlane': False}),
        ('param-axis-4', frame(a(param=PRM(axis=4))), False, None),
        ('param-axis-255', frame(a(param=PRM(axis=255))), False, None),
        ('param-axis-negative', frame(a(param=PRM(axis=-1))), False, None),
        ('param-axis-float', frame(a(param=PRM(axis=1.5))), False, None),
        ('param-axis-bool', frame(a(param=PRM(axis=True))), False, None),
        ('param-axis-string', frame(a(param=PRM(axis='x'))), False, None),
        ('param-axis-null', frame(a(param=PRM(axis=None))), False, None),
        ('param-plane-int', frame(a(param=PRM(plane=1))), False, None),
        ('param-plane-string', frame(a(param=PRM(plane='true'))), False, None),
        ('no-param-defaults', frame(a()), True, {'param': False, 'paramAxis': -1, 'paramPlane': False}),
        ('axis-outside-param-ignored', frame(a(axis=9, plane=1)), True, {'paramAxis': -1, 'paramPlane': False}),
        ('bad-slot-still-rejects', frame(a(id='figma', slot='idle')), False, None),
    ]
    ops = [case[1] for case in cases] + [{'op': 'sizes'}]
    results = script(exe, ops, out, 'frames')
    for (name, _o, accept, fields), r in zip(cases, results):
        ok = r.get('accept') == accept
        if ok and fields:
            ok = all(r['app'].get(k) == v for k, v in fields.items())
        c.check(ok, f'frame {name}', json.dumps(r)[:300])
    print(f'frame: {len(cases)} app cases through cc_parse_frame')


def decoder_tests(exe, out, c: Checker):
    accepts = accept_models()
    blobs = [(encode(m)[0], False) for _, m in accepts]
    rejects = reject_cases()
    blobs += [(b, fail) for _, b, _, _, fail in rejects]
    results = decode_all(exe, blobs, out)
    codes_seen = set()
    for (name, m), (blob, _), r in zip(accepts, blobs, results):
        problems = []
        if r['code'] != 0:
            problems.append(f'code {r["code"]}@{r["offset"]}')
        else:
            compare('profile', expected_profile(m, blob), r['profile'], problems)
            shared_indexes(m, r['profile'], problems)
            if not r['bounds']:
                problems.append('a pointer outside the allocation')
        c.check(not problems, f'accept {name} ({len(blob)} B wire, {r.get("bytes")} B decoded)', '; '.join(problems[:6]))
    sizes = {name: (len(b), r.get('bytes')) for (name, _), (b, _), r in zip(accepts, blobs, results)}
    for (name, blob, code, offset, _), r in zip(rejects, results[len(accepts):]):
        codes_seen.add(code)
        c.check(r['code'] == code and r['offset'] == offset and 'profile' not in r and r['live'] == 0,
                f'reject {name}', f'got {r["code"]}@{r["offset"]}, want {code}@{offset}')
    missing = set(range(1, 15)) - codes_seen
    c.check(not missing, 'reject: one case per result code', f'missing {sorted(missing)}')
    print(f'decoder: {len(accepts)} accept (round trip), {len(rejects)} reject cases, codes {sorted(codes_seen)}')
    print('decoder: wire -> decoded bytes (x64): ' + ', '.join(f'{n} {w}->{d}' for n, (w, d) in sizes.items()))
    return [b for b, _ in blobs[:len(accepts)]]


def fuzz(exe, corpus, out, count, seed, c: Checker, label, env=None):
    path = out / 'corpus.bin'
    write_blobs(path, [(b, False) for b in corpus])
    run = subprocess.run([str(exe), 'fuzz', str(path), str(count), str(seed)], capture_output=True, text=True, env=env)
    lines = [ln for ln in run.stdout.splitlines() if ln.strip().startswith('{')]
    summary = json.loads(lines[-1]) if lines else {}
    ok = run.returncode == 0 and summary.get('cases') == count and summary.get('unsound') == 0 and \
        summary.get('leaked') == 0
    c.check(ok, f'fuzz {label}', f'exit {run.returncode} {run.stdout[-500:]} {run.stderr[-1500:]}')
    print(f'fuzz {label}: {summary.get("cases")} cases, {summary.get("accepted")} accepted, unsound '
          f'{summary.get("unsound")}, codes {summary.get("codes")}')


def threads(exe, corpus, out, rounds, c: Checker, env):
    path = out / 'corpus-threads.bin'
    write_blobs(path, [(b, False) for b in corpus])
    run = subprocess.run([str(exe), 'threads', str(path), str(rounds)], capture_output=True, text=True, env=env)
    lines = [ln for ln in run.stdout.splitlines() if ln.strip().startswith('{')]
    summary = json.loads(lines[-1]) if lines else {}
    c.check(run.returncode == 0 and summary.get('other') == 0, 'threads (ASan)',
            f'exit {run.returncode} {run.stdout[-400:]} {run.stderr[-1500:]}')
    print(f'threads (ASan): {summary}')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--quick', action='store_true', help='10,000 / 2,000 fuzz cases')
    parser.add_argument('--fuzz', type=int, default=100_000)
    parser.add_argument('--asan-fuzz', type=int, default=20_000)
    parser.add_argument('--seed', type=int, default=20261003)
    parser.add_argument('--no-asan', action='store_true')
    args = parser.parse_args(argv)
    if args.quick:
        args.fuzz, args.asan_fuzz = 10_000, 2_000
    OUT.mkdir(parents=True, exist_ok=True)
    exe = build(OUT)
    c = Checker()
    corpus = decoder_tests(exe, OUT, c)
    store_tests(exe, OUT, c)
    upload_tests(exe, OUT, c)
    x86 = build(OUT, x86=True)
    heap_tests(x86, OUT, c)
    heap_tests(exe, OUT, c, 'x64 harness', check=False)
    sizes32 = script(x86, [{'op': 'sizes'}], OUT, 'sizes32')[0]
    print(f'sizes (x86, ILP32 as the knob): sizeof(CCFrame) {sizes32["CCFrame"]} B, sizeof(CCAppState) '
          f'{sizes32["CCAppState"]} B')
    accepts = accept_models()
    r32 = decode_all(x86, [(encode(m)[0], False) for _, m in accepts], OUT)
    print('decoder (x86, ILP32 as the knob): wire -> decoded bytes: ' +
          ', '.join(f'{n} {len(encode(m)[0])}->{r.get("bytes")}' for (n, m), r in zip(accepts, r32)) +
          f'; fat {len(encode(fat("x"))[0])}->{decode_all(x86, [(encode(fat("x"))[0], False)], OUT)[0].get("bytes")}')
    frame_tests(exe, OUT, c)
    corpus += [encode(fat('fz'))[0]]
    fuzz(exe, corpus, OUT, args.fuzz, args.seed, c, '/W4')
    if not args.no_asan:
        asan = build(OUT, asan=True)
        env = run_env(True)
        probe = subprocess.run([str(asan), 'probe', '16'], capture_output=True, text=True, env=env)
        caught = probe.returncode != 0 and 'AddressSanitizer' in probe.stderr
        c.check(caught, 'ASan self-test: a read one past a heap block is reported', probe.stdout + probe.stderr[-300:])
        print(f'self-test: ASan {"reports" if caught else "DOES NOT report"} a one-byte heap overread')
        fuzz(asan, corpus, OUT, args.asan_fuzz, args.seed + 1, c, 'ASan', env)
        threads(asan, [b for b in corpus if len(b) < 20000], OUT, 400, c, env)
    print(f'{"PASS" if not c.failures else "FAIL"} app store harness: {c.passes} checks passed, '
          f'{c.failures} failure(s)')
    return 1 if c.failures else 0


if __name__ == '__main__':
    sys.exit(main())

"""artwork2 media store parity (1.0.0-cc5.3, ARTWORK2.md section 4). Python stdlib + MSVC; the
xtensa toolchain for the gnu++11 gate. No device, no USB, no PlatformIO.

1. Builds the shared fixture media_store_traces.json from the scenarios below, played through
   this script's own reference model of ARTWORK2.md 4.3/4.4 (Model), and compares it with the
   file on disk (--write rewrites it). The fixture is authored here (track fw-core) and
   replayed by the companion's Python FakeKnob (tests/tools/capture_session_frames.py) too.
   Format: {"version":1,"cases":[{"name","config","steps"}]}, steps "control", "release",
   "frame" (artKey/iconKey[, noAdopt]), "adopt", "media" (req = the media object, ack = the
   exact mediaAck object) and "check" (slot tables [valid,key,stamp], displayed, clock and
   receiving: an upload context is active and is not a begin hit; both runners compare each part
   a check step carries). A kind's config may carry "available": false, a store that was never
   allocated (no slots: its table is []; every request of that kind answers "Media
   unavailable" before the control check, ARTWORK2.md 4.3 step 4).
   Runner rules (both runners): "frame" sets each kind's frame key, then adopts it, or sets
   displayed -1 when it is empty, unless noAdopt; after a successful miss commit whose key
   equals that kind's frame key the runner adopts it; "control" is a new active control ID and
   "release" leaves none (both cancel the upload); with validateJpeg false any cover bytes
   pass the decode check. The Model's cover check (jpeg_valid) is a marker pre-scan, right only
   for well-formed payloads, so every cover payload it judges is written out with its verdict
   and media_tests.cpp checks each against the compiled cc_jpeg_validate before the replay.
2. gnu++11 gate: cpp11_gate.py's header unit for src/cc_media_store.h (HEADER_UNITS, a tiny
   translation unit that odr-uses the store and the COM transport helpers; cpp11_gate.py runs
   it too) goes through cpp11_gate.py's check_unit: xtensa g++
   -std=gnu++11 -fsyntax-only -Wall -Wextra -Wpedantic, then an -O0 object and nm for
   undefined class data members.
3. Compiles media_tests.cpp with the unchanged firmware header src/cc_media_store.h and
   src/cc_jpeg.cpp (through tjpgd_shim/ and LVGL's TJpgDec R0.03), MSVC /W4 /WX, and runs it:
   the Model's cover verdicts, then every case replayed through CCMediaStore (same code as the
   firmware) with every ack compared byte for byte (key order included) and every check step
   compared exactly, then its direct assertions (CRC-32, base64, keys, parse replies, the COM
   thread's line transport from cc_media_store.h: the bad-line reply choice, line assembly with
   exactly one reply per oversize line and the 2 s expiry, and the ARTWORK2.md section 3 idle
   sleep rule; unavailable stores, pinning, adoption pointers, counters, the device
   configuration, and the capability object against the host's
   presentation.ARTWORK2_CAPABILITY byte for byte).
4. The same executable (CC_MEDIA_WIRING) links a verbatim copy of src/control_center.cpp with
   the real src/cc_media.cpp and src/cc_frame_parse.cpp against host stubs (WIRING_STUBS:
   Arduino/FreeRTOS, the heap, the preset manager, the FOC thread), and drives the media
   wiring through cc_handle_command, cc_take_request and cc_service: the capability object in
   the full reply, exactly one reply per media line (the mediaAck ahead of release, control and
   frame; capabilities, diag and art dispatched before media answer alone), frame keys from accepted controls
   and frames only (seen through pinning on the device configuration), the upload cancelled
   by a new control, a release and a lease expiry but not by a stale ID or a rejected
   control, and media lines never renewing the lease. Raw bytes routed as com_thread.cpp
   routes them: an oversize or non-JSON media line gets exactly one parse mediaAck (the real
   cc_media_parse_reply), counted in mediaErrors.

Integers in the fixture follow ARTWORK2.md 4.3 literally over the firmware's JSON integer
domain (ArduinoJson 7: -2^63..2^64-1; a longer number parses as a float): begin `bytes` and
`crc32` must be integers 0..0xFFFFFFFF ("Media size and CRC required" otherwise, the lead
ruling of 2026-09-24), and a `bytes` in that range is then range-checked for its kind
("Invalid media size"); any integer data `offset` gets "Media chunk bounds" only when
offset + length > bytes and "Media offset mismatch" otherwise. A miss begin cancels the upload in progress before choosing its victim, and a
cover must end with EOI (its last two bytes) to commit.

--firmware-syntax: also syntax-checks the firmware units this track changed with the exact
PlatformIO command lines of NanoD_RatchetH1/compile_commands.json (-fsyntax-only instead of
-o/-c; a new unit borrows cc_artwork.cpp's line).

Writes media_store_traces.json (only with --write or when absent) and build/media-tests/*.
Exit status is non-zero on any mismatch.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zlib

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
companion = root.parent / 'app'
arduinojson = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'ArduinoJson' / 'src'
tjpgd = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'lvgl' / 'src' / 'libs' / 'tjpgd'
shim = root / 'tjpgd_shim'
out_dir = root / 'build' / 'media-tests'
fixture_path = root / 'media_store_traces.json'

sys.path.insert(0, str(companion))
from control_center import presentation  # noqa: E402  (read-only: the artwork2 constants)

KEY = re.compile(r'[A-Za-z0-9_-]{1,24}\Z')
BASE64 = re.compile(r'(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z')
OPS = ('begin', 'data', 'commit', 'have')
KINDS = presentation.MEDIA_KINDS
MAX_ID = 0x7FFFFFFF

# Small store configurations keep the traces compact; REAL is the capability (section 1).
SMALL = {'cover': {'entries': 3, 'slotBytes': 64, 'maxBytes': 64},
         'icon': {'entries': 3, 'slotBytes': 16, 'bytes': 16},
         'chunkBytes': 8, 'haveKeys': 4, 'validateJpeg': False}
SMALL_JPEG = {'cover': {'entries': 3, 'slotBytes': 1024, 'maxBytes': 1024},
              'icon': {'entries': 3, 'slotBytes': 16, 'bytes': 16},
              'chunkBytes': 512, 'haveKeys': 4, 'validateJpeg': True}
_cap = presentation.ARTWORK2_CAPABILITY
REAL = {'cover': {'entries': _cap['cover']['entries'], 'slotBytes': _cap['cover']['maxBytes'],
                  'maxBytes': _cap['cover']['maxBytes']},
        'icon': {'entries': _cap['icon']['entries'], 'slotBytes': presentation.ICON_BYTES,
                 'bytes': presentation.ICON_BYTES},
        'chunkBytes': presentation.MEDIA_CHUNK_BYTES, 'haveKeys': presentation.MEDIA_HAVE_KEYS,
        'validateJpeg': True}


# ---------------------------------------------------------------------------
# Deterministic payloads.

def payload(label: str, size: int) -> bytes:
    out = b''
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(f'{label}:{counter}'.encode()).digest()
        counter += 1
    return out[:size]


def gray_jpeg(width: int, height: int) -> bytes:
    """A baseline JFIF JPEG, 4:2:0, every sample 128 (all DCT coefficients zero).

    Written by hand so the fixture never depends on an encoder version: one quantisation
    table, and for each class one Huffman table with a single 1-bit code (DC category 0,
    AC end-of-block), so every 8x8 block is the two bits "0" "0".
    """
    def segment(marker: int, body: bytes) -> bytes:
        return bytes((0xFF, marker)) + (len(body) + 2).to_bytes(2, 'big') + body
    one_code = bytes([1] + [0] * 15)
    out = b'\xFF\xD8'
    out += segment(0xE0, b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')
    out += segment(0xDB, bytes([0x00]) + bytes([1] * 64))
    out += segment(0xC0, bytes([8]) + height.to_bytes(2, 'big') + width.to_bytes(2, 'big')
                   + bytes([3, 1, 0x22, 0, 2, 0x11, 0, 3, 0x11, 0]))
    for table in (0x00, 0x10, 0x01, 0x11):            # DC0, AC0, DC1, AC1
        out += segment(0xC4, bytes([table]) + one_code + bytes([0x00]))
    out += segment(0xDA, bytes([3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0]))
    mcus = ((width + 15) // 16) * ((height + 15) // 16)
    bits = mcus * 6 * 2
    data = bytearray((bits + 7) // 8)
    if bits % 8:
        data[-1] = (1 << (8 - bits % 8)) - 1          # pad the last byte with 1 bits
    return out + bytes(data) + b'\xFF\xD9'


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


# ---------------------------------------------------------------------------
# Reference model of ARTWORK2.md 4.3/4.4 (independent of the C++ store).

def is_uint(value, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


# A JSON integer as the firmware's ArduinoJson 7 stores one: no fraction or exponent, within
# -2^63..2^64-1 (a longer integer parses as a float there), never a bool.
JSON_INT_MIN, JSON_INT_MAX = -2 ** 63, 2 ** 64 - 1


def is_json_int(value) -> bool:
    return is_uint(value, JSON_INT_MIN, JSON_INT_MAX)


def valid_key(value) -> bool:
    return isinstance(value, str) and KEY.match(value) is not None


def decode_base64(value, capacity: int):
    if not isinstance(value, str) or not value or len(value) % 4 or not BASE64.match(value):
        return None
    data = base64.b64decode(value, validate=True)
    return data if 0 < len(data) <= capacity else None


def jpeg_valid(data: bytes) -> bool:
    """The trace payloads' cover check: cc_jpeg_validate's marker pre-scan (SOI first, EOI as the
    last two bytes) plus 240x240.

    Only valid for well-formed payloads: it does not run the ROM decoder's prepare over the
    quantisation and Huffman tables, so a JPEG whose tables are damaged but whose segments are
    still delimited passes here while cc_jpeg_validate refuses it ("Media decode failed").
    Build fixture covers from gray_jpeg() (whole, cut or extended) or host-encoder output, or
    plain garbage. Every payload judged here is recorded in JPEG_VERDICTS, and media_tests.cpp
    checks each verdict against the compiled cc_jpeg_validate before it replays the fixture.
    """
    verdict = _jpeg_prescan(data)
    JPEG_VERDICTS.setdefault(bytes(data), verdict)
    return verdict


# payload -> jpeg_valid() verdict, for every cover payload the Model judged (build_fixture).
JPEG_VERDICTS: dict = {}


def _jpeg_prescan(data: bytes) -> bool:
    if len(data) < 4 or data[:2] != b'\xFF\xD8' or len(data) > presentation.COVER_MAX_BYTES:
        return False
    if data[-2:] != b'\xFF\xD9':
        return False
    at, size = 2, None
    while True:
        if len(data) - at < 4 or data[at] != 0xFF:
            return False
        marker, length = data[at + 1], int.from_bytes(data[at + 2:at + 4], 'big')
        if length <= 2 or length > len(data) - at - 2:
            return False
        body = data[at + 4:at + 2 + length]
        if marker == 0xC0:
            if size is not None or length < 8 or body[0] != 8 or body[5] != 3:
                return False
            size = (int.from_bytes(body[3:5], 'big'), int.from_bytes(body[1:3], 'big'))
        elif marker == 0xDA:
            return size == (presentation.COVER_SIZE, presentation.COVER_SIZE)
        elif marker in (0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF, 0xD9):
            return False
        at += 2 + length


class Slot:
    def __init__(self, size: int):
        self.valid, self.key, self.bytes, self.crc, self.stamp = False, '', 0, 0, 0
        self.data = bytearray(size)


class Kind:
    def __init__(self, entries: int, slot_bytes: int, lo: int, hi: int, available: bool = True):
        self.available = available      # False: never allocated (no slots; "Media unavailable")
        self.slots = [Slot(slot_bytes) for _ in range(entries + 1)] if available else []
        self.lo, self.hi, self.slot_bytes = lo, hi, slot_bytes
        self.clock, self.displayed, self.frame_key = 0, -1, ''

    def touch(self, index: int):
        self.clock += 1
        self.slots[index].stamp = self.clock

    def find(self, key) -> int:
        if not valid_key(key):
            return -1
        return next((i for i, s in enumerate(self.slots) if s.valid and s.key == key), -1)

    def pinned(self, index: int) -> bool:
        slot = self.slots[index]
        return index == self.displayed or (bool(self.frame_key) and slot.valid and slot.key == self.frame_key)

    def victim(self) -> int:
        for i, slot in enumerate(self.slots):
            if not slot.valid and not self.pinned(i):
                return i
        best = -1
        for i, slot in enumerate(self.slots):
            if slot.valid and not self.pinned(i) and (best < 0 or slot.stamp < self.slots[best].stamp):
                best = i
        return best


class Model:
    def __init__(self, config: dict):
        cover, icon = config['cover'], config['icon']
        self.kinds = {'cover': Kind(cover['entries'], cover['slotBytes'], 1, cover['maxBytes'],
                                    cover.get('available', True)),
                      'icon': Kind(icon['entries'], icon['slotBytes'], icon['bytes'], icon['bytes'],
                                   icon.get('available', True))}
        self.chunk, self.have_keys, self.validate = config['chunkBytes'], config['haveKeys'], config['validateJpeg']
        self.active_id = 0
        self.upload = None
        self.version = 0

    # Runner steps -------------------------------------------------------
    def control(self, control_id: int):
        self.active_id, self.upload = control_id, None

    def release(self):
        self.active_id, self.upload = 0, None

    def set_frame_key(self, kind: str, key):
        self.kinds[kind].frame_key = key if valid_key(key) else ''

    def adopt(self, kind: str, key) -> bool:
        store = self.kinds[kind]
        index = store.find(key)
        if index < 0:
            store.displayed = -1
            return False
        if store.displayed != index:
            store.displayed = index
            store.touch(index)
        return True

    def receiving(self) -> bool:
        return self.upload is not None and not self.upload['hit']

    def snapshot(self) -> dict:
        return {'do': 'check',
                'slots': {k: [[s.valid, s.key, s.stamp] for s in self.kinds[k].slots] for k in KINDS},
                'displayed': {k: self.kinds[k].displayed for k in KINDS},
                'clock': {k: self.kinds[k].clock for k in KINDS},
                'receiving': self.receiving()}

    # The media command ---------------------------------------------------
    def handle(self, req) -> dict:
        obj = req if isinstance(req, dict) else {}
        r = {'id': obj.get('id') if is_uint(obj.get('id'), 1, MAX_ID) else None,
             'op': obj.get('op') if obj.get('op') in OPS else None,
             'kind': obj.get('kind') if obj.get('kind') in KINDS else None,
             'key': obj.get('key') if valid_key(obj.get('key')) else None}

        def head() -> dict:
            ack = {}
            for field in ('id', 'op', 'kind'):
                if r[field] is not None:
                    ack[field] = r[field]
            if r['op'] != 'have' and r['key'] is not None:
                ack['key'] = r['key']
            return ack

        def fail(error: str, offset: int = 0) -> dict:
            ack = head()
            if r['op'] != 'have':
                ack['offset'] = offset
            ack['error'] = error
            return ack

        def ok(offset: int) -> dict:
            ack = head()
            ack['offset'] = offset
            return ack

        if r['op'] is None:
            return fail('Unknown media operation')
        if r['kind'] is None:
            return fail('Unknown media kind')
        store = self.kinds[r['kind']]
        if not store.available:
            return fail('Media unavailable')             # 4.3 step 4, before the control check
        if r['id'] is None or not self.active_id or r['id'] != self.active_id:
            return fail('Stale media control')
        up = self.upload
        matches = up is not None and r['key'] is not None and up['kind'] == r['kind'] and up['key'] == r['key']
        if r['op'] == 'have':
            keys = obj.get('keys')
            if (not isinstance(keys, list) or not keys or len(keys) > self.have_keys
                    or not all(valid_key(k) for k in keys)):
                return fail('Invalid media keys')
            result = []
            for key in keys:
                index = store.find(key)
                if index >= 0:
                    store.touch(index)
                result.append(index >= 0)
            ack = head()
            ack['have'] = result
            return ack
        if r['key'] is None:
            return fail('Invalid media key')
        if r['op'] == 'begin':
            size, crc = obj.get('bytes'), obj.get('crc32')
            if not is_uint(size, 0, 0xFFFFFFFF) or not is_uint(crc, 0, 0xFFFFFFFF):
                return fail('Media size and CRC required')
            if not store.lo <= size <= min(store.hi, store.slot_bytes):
                return fail('Invalid media size')
            for index, slot in enumerate(store.slots):
                if slot.valid and slot.key == r['key'] and slot.bytes == size and slot.crc == crc:
                    self.upload = {'kind': r['kind'], 'key': r['key'], 'slot': index, 'bytes': size, 'crc': crc,
                                   'received': size, 'hit': True, 'last': (0, 0), 'running': 0}
                    store.touch(index)
                    return ok(size)
            self.upload = None                          # a miss cancels any upload first
            index = store.victim()
            if index < 0:
                return fail('Media unavailable')
            store.slots[index].valid = False
            self.upload = {'kind': r['kind'], 'key': r['key'], 'slot': index, 'bytes': size, 'crc': crc,
                           'received': 0, 'hit': False, 'last': (0, 0), 'running': 0}
            return ok(0)
        if r['op'] == 'data':
            if not matches or up['hit']:
                return fail('No matching media upload')
            chunk = decode_base64(obj.get('data'), self.chunk)
            if chunk is None:
                return fail('Invalid media data', up['received'])
            offset = obj.get('offset')
            if not is_json_int(offset) or offset + len(chunk) > up['bytes']:
                return fail('Media chunk bounds', up['received'])
            slot = store.slots[up['slot']]
            if offset == up['received']:
                slot.data[offset:offset + len(chunk)] = chunk
                up['running'] = zlib.crc32(chunk, up['running'])
                up['received'] += len(chunk)
                up['last'] = (offset, len(chunk))
            elif not (offset >= 0 and offset == up['last'][0] and offset + len(chunk) == up['received']
                      and bytes(slot.data[offset:offset + len(chunk)]) == chunk):
                return fail('Media offset mismatch', up['received'])
            return ok(up['received'])
        # commit
        if not matches:
            return fail('No matching media upload')
        if up['hit']:
            self.upload = None
            return ok(up['bytes'])
        if up['received'] != up['bytes']:
            return fail('Media upload incomplete', up['received'])
        slot = store.slots[up['slot']]
        if up['running'] != up['crc']:
            self.upload = None
            return fail('Media checksum mismatch', up['received'])
        if r['kind'] == 'cover' and self.validate and not jpeg_valid(bytes(slot.data[:up['bytes']])):
            self.upload = None
            return fail('Media decode failed', up['received'])
        for index, other in enumerate(store.slots):
            if index != up['slot'] and other.valid and other.key == up['key']:
                other.valid = False
        slot.valid, slot.key, slot.bytes, slot.crc = True, up['key'], up['bytes'], up['crc']
        store.touch(up['slot'])
        self.version += 1
        self.upload = None
        return ok(up['bytes'])


# ---------------------------------------------------------------------------
# Scenario builder: every ack and check comes from the model; `expect` pins what the
# scenario is about, so a model mistake cannot slip into the fixture unnoticed.

class Trace:
    def __init__(self, name: str, config: dict):
        self.name, self.config, self.model, self.steps = name, config, Model(config), []
        self.id = 0

    def control(self, control_id: int):
        self.id = control_id
        self.model.control(control_id)
        self.steps.append({'do': 'control', 'id': control_id})

    def release(self):
        self.id = 0
        self.model.release()
        self.steps.append({'do': 'release'})

    def frame(self, art: str = '', icon: str = '', adopt: bool = True):
        step = {'do': 'frame', 'artKey': art, 'iconKey': icon}
        if not adopt:
            step['noAdopt'] = True
        self.model.set_frame_key('cover', art)
        self.model.set_frame_key('icon', icon)
        if adopt:
            for kind in KINDS:
                key = self.model.kinds[kind].frame_key
                if key:
                    self.model.adopt(kind, key)
                else:
                    self.model.kinds[kind].displayed = -1
        self.steps.append(step)

    def adopt(self, kind: str, key: str, expect: bool | None = None):
        hit = self.model.adopt(kind, key)
        if expect is not None:
            assert hit == expect, (self.name, 'adopt', kind, key, hit)
        self.steps.append({'do': 'adopt', 'kind': kind, 'key': key})

    def media(self, req, error=None, offset=None, have=None, **expect) -> dict:
        version = self.model.version
        ack = self.model.handle(req)
        where = (self.name, len(self.steps), req if len(json.dumps(req)) < 200 else '…', ack)
        assert ack.get('error') == error, where
        if offset is not None:
            assert ack.get('offset') == offset, where
        if have is not None:
            assert ack.get('have') == have, where
        for field, value in expect.items():
            assert ack.get(field, 'absent') == value, where
        if isinstance(req, dict) and req.get('op') == 'commit' and 'error' not in ack and self.model.version != version:
            kind = req['kind']
            if req['key'] == self.model.kinds[kind].frame_key:
                self.model.adopt(kind, req['key'])      # runner rule: a pinned key is adopted at its commit
        self.steps.append({'do': 'media', 'req': req, 'ack': ack})
        return ack

    def check(self, displayed=None, valid=None, receiving=None):
        snap = self.model.snapshot()
        if receiving is not None:
            assert snap['receiving'] == receiving, (self.name, 'receiving', snap['receiving'])
        if displayed is not None:
            assert snap['displayed'] == {**snap['displayed'], **displayed}, (self.name, 'displayed', snap['displayed'])
        if valid is not None:
            for kind, keys in valid.items():
                actual = sorted(s[1] for s in snap['slots'][kind] if s[0])
                assert actual == sorted(keys), (self.name, 'valid', kind, actual, keys)
        self.steps.append(snap)

    # Conveniences ---------------------------------------------------------
    def req(self, op: str, kind: str, **fields) -> dict:
        out = {'id': self.id, 'op': op, 'kind': kind}
        out.update(fields)
        return out

    def begin(self, kind, key, data: bytes, error=None, offset=None, crc=None):
        return self.media(self.req('begin', kind, key=key, bytes=len(data),
                                   crc32=zlib.crc32(data) if crc is None else crc), error, offset)

    def send(self, kind, key, data: bytes, offset: int, error=None, reply=None):
        return self.media(self.req('data', kind, key=key, offset=offset, data=b64(data)), error, reply)

    def commit(self, kind, key, error=None, offset=None):
        return self.media(self.req('commit', kind, key=key), error, offset)

    def upload(self, kind, key, data: bytes):
        """begin -> data... -> commit, all successful (a miss)."""
        self.begin(kind, key, data, offset=0)
        chunk = self.config['chunkBytes']
        for at in range(0, len(data), chunk):
            self.send(kind, key, data[at:at + chunk], at, reply=min(at + chunk, len(data)))
        self.commit(kind, key, offset=len(data))

    def have(self, kind, keys, result=None, error=None):
        return self.media(self.req('have', kind, keys=keys), error, have=result)

    def case(self) -> dict:
        return {'name': self.name, 'config': self.config, 'steps': self.steps}


def scenarios() -> list:
    cases = []
    A, B, C, D, E = (payload(f'cover-{n}', 20 + n) for n in range(5))
    I1, I2, I3, I4, I5 = (payload(f'icon-{n}', 16) for n in range(5))

    # 1. Miss upload, frame pin + adoption at commit, have, begin-hit.
    t = Trace('miss-upload-have-and-hit', SMALL)
    t.have('cover', ['c1'], error='Stale media control')          # no session yet
    t.control(7)
    t.frame(art='c1')
    t.check(displayed={'cover': -1, 'icon': -1})
    t.have('cover', ['c1'], [False])
    t.begin('cover', 'c1', A, offset=0)
    t.send('cover', 'c1', A[:8], 0, reply=8)
    t.send('cover', 'c1', A[8:16], 8, reply=16)
    t.send('cover', 'c1', A[16:], 16, reply=len(A))
    t.commit('cover', 'c1', offset=len(A))                       # the frame's key: adopted at its commit
    t.check(displayed={'cover': 0}, valid={'cover': ['c1']})
    t.have('cover', ['c1', 'zz', 'c1'], [True, False, True])      # hits touched in order (twice)
    t.check()
    t.begin('cover', 'c1', A, offset=len(A))                     # hit: same key, bytes and crc
    t.check(receiving=False)                                      # a hit context is not receiving
    t.send('cover', 'c1', A[:8], 0, error='No matching media upload')   # a hit has no receiving slot
    t.commit('cover', 'c1', offset=len(A))
    t.commit('cover', 'c1', error='No matching media upload')     # the context ended
    t.check()
    cases.append(t.case())

    # 2. LRU eviction order, touched by have, and a valid slot keeping its key when evicted.
    t = Trace('eviction-lru-order', SMALL)
    t.control(3)
    for key, data in (('k0', A), ('k1', B), ('k2', C), ('k3', D)):
        t.upload('cover', key, data)                              # S = 4 slots: 0..3
    t.check(displayed={'cover': -1}, valid={'cover': ['k0', 'k1', 'k2', 'k3']})
    t.have('cover', ['k2', 'k0', 'k3'], [True, True, True])       # k1 is now the oldest
    t.begin('cover', 'k4', E, offset=0)
    t.check(valid={'cover': ['k0', 'k2', 'k3']})                  # slot 1 evicted at begin, key kept
    t.upload('cover', 'k4', E)
    t.have('cover', ['k1'], [False])
    t.begin('cover', 'k5', A, offset=0)                           # oldest now k2 (slot 2)
    t.check(valid={'cover': ['k0', 'k3', 'k4']})
    t.begin('cover', 'k6', B, offset=0)                           # k5's slot is invalid: reused first
    t.check(valid={'cover': ['k0', 'k3', 'k4']})
    cases.append(t.case())

    # 3. Pins: the displayed slot and the frame key's slot are never victims.
    t = Trace('pin-displayed-and-frame-key', SMALL)
    t.control(11)
    for key, data in (('p0', A), ('p1', B), ('p2', C), ('p3', D)):
        t.upload('cover', key, data)
    t.adopt('cover', 'p0', expect=True)                           # displayed = 0 (touched)
    t.frame(art='p1', adopt=False)                                # frame key p1 (slot 1), not drawn
    t.have('cover', ['p3', 'p2', 'p0'], [True, True, True])       # p1 is the oldest, p0 not
    t.check(displayed={'cover': 0})
    t.begin('cover', 'q0', E, offset=0)                           # p1 pinned by the frame key: p3 goes
    t.check(valid={'cover': ['p0', 'p1', 'p2']})
    t.upload('cover', 'q0', E)
    t.have('cover', ['q0', 'p2'], [True, True])                   # q0 touched before p2
    t.begin('cover', 'q1', A, offset=0)                           # unpinned: q0 (older) and p2 -> q0 goes
    t.check(valid={'cover': ['p0', 'p1', 'p2']})
    t.frame(art='')                                               # no cover: displayed -1, no frame key
    t.check(displayed={'cover': -1})
    t.begin('cover', 'q2', B, offset=0)                           # q1's slot (invalid) is reused
    t.upload('cover', 'q2', B)
    t.begin('cover', 'q3', C, offset=0)                           # nothing pinned now: p1 is the oldest
    t.check(valid={'cover': ['p0', 'p2', 'q2']})
    cases.append(t.case())

    # 4. Identical retry, offset mismatch, bounds and invalid data.
    t = Trace('data-retry-mismatch-bounds', SMALL)
    t.control(5)
    t.begin('cover', 'r1', B, offset=0)
    t.send('cover', 'r1', B[:8], 0, reply=8)
    t.send('cover', 'r1', B[:8], 0, reply=8)                      # identical retry: accepted, no change
    t.send('cover', 'r1', B[:7], 0, error='Media offset mismatch', reply=8)   # not the same chunk
    t.send('cover', 'r1', bytes(8), 0, error='Media offset mismatch', reply=8)  # different bytes
    t.send('cover', 'r1', B[4:12], 4, error='Media offset mismatch', reply=8)
    t.send('cover', 'r1', B[16:21], 16, error='Media offset mismatch', reply=8)  # ahead
    # Integer offsets follow ARTWORK2.md 4.3 literally: offset + len <= bytes, so a negative
    # offset is a mismatch, not a bounds failure (the chunk is not stored).
    t.send('cover', 'r1', B[:8], -1, error='Media offset mismatch', reply=8)
    t.send('cover', 'r1', B[:8], -8, error='Media offset mismatch', reply=8)
    t.send('cover', 'r1', B[:8], -(2 ** 63), error='Media offset mismatch', reply=8)   # int64 minimum
    t.send('cover', 'r1', B[:8], -(2 ** 63) - 1, error='Media chunk bounds', reply=8)   # a float to ArduinoJson
    t.send('cover', 'r1', B[8:16], 8, reply=16)
    t.send('cover', 'r1', B[:8], 0, error='Media offset mismatch', reply=16)   # no longer the last chunk
    t.send('cover', 'r1', B[8:16], 8, reply=16)                   # the last chunk: identical retry
    t.send('cover', 'r1', B[16:], 16, reply=len(B))
    t.send('cover', 'r1', B[16:], 16, reply=len(B))               # retry at the end
    t.send('cover', 'r1', b'x', len(B), error='Media chunk bounds', reply=len(B))
    t.send('cover', 'r1', B[:8], len(B) - 7, error='Media chunk bounds', reply=len(B))
    t.media(t.req('data', 'cover', key='r1', offset=4294967295, data=b64(b'x')), 'Media chunk bounds', len(B))
    t.media(t.req('data', 'cover', key='r1', data=b64(b'x')), 'Media chunk bounds', len(B))   # offset absent
    t.media(t.req('data', 'cover', key='r1', offset='0', data=b64(b'x')), 'Media chunk bounds', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=-1, data=b64(b'x')), 'Media offset mismatch', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=2 ** 63 - 1, data=b64(b'x')), 'Media chunk bounds', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=2 ** 64 - 1, data=b64(b'x')), 'Media chunk bounds', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=2 ** 64, data=b64(b'x')), 'Media chunk bounds', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=0.0, data=b64(b'x')), 'Media chunk bounds', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=True, data=b64(b'x')), 'Media chunk bounds', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data=''), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data='@@@@'), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data='QQ'), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data='QUJD='), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data='QUI=QUI='), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data='QU JD'), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data=b64(bytes(9))), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B), data=5), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset=len(B)), 'Invalid media data', len(B))
    t.media(t.req('data', 'cover', key='r1', offset='x', data='%%'), 'Invalid media data', len(B))  # data first
    t.send('cover', 'r2', B[:8], 0, error='No matching media upload', reply=0)   # another key
    t.send('icon', 'r1', B[:8], 0, error='No matching media upload', reply=0)    # another kind
    t.commit('cover', 'r1', offset=len(B))
    t.check(valid={'cover': ['r1']})
    cases.append(t.case())

    # 5. Commit failures: incomplete (context kept), checksum (cancelled, slot invalid).
    t = Trace('commit-incomplete-and-checksum', SMALL)
    t.control(9)
    t.upload('cover', 's0', A)
    t.begin('cover', 's1', B, offset=0)
    t.send('cover', 's1', B[:8], 0, reply=8)
    t.commit('cover', 's1', error='Media upload incomplete', offset=8)
    t.send('cover', 's1', B[8:16], 8, reply=16)
    t.send('cover', 's1', B[16:], 16, reply=len(B))
    t.commit('cover', 's1', offset=len(B))
    t.begin('cover', 's2', C, offset=0, crc=zlib.crc32(C) ^ 1)
    for at in range(0, len(C), 8):
        t.send('cover', 's2', C[at:at + 8], at, reply=min(at + 8, len(C)))
    t.commit('cover', 's2', error='Media checksum mismatch', offset=len(C))
    t.send('cover', 's2', C[:8], 0, error='No matching media upload', reply=0)
    t.commit('cover', 's2', error='No matching media upload', offset=0)
    t.check(valid={'cover': ['s0', 's1']})
    t.begin('cover', 's2', C, offset=0)                           # the failed slot is reused first
    t.check(valid={'cover': ['s0', 's1']})
    cases.append(t.case())

    # 6. Duplicate-key invalidation, including a displayed slot that becomes invalid.
    t = Trace('duplicate-key-invalidation', SMALL)
    t.control(21)
    t.upload('cover', 'dup', A)                                   # slot 0
    t.upload('cover', 'd1', B)                                    # slot 1
    t.adopt('cover', 'dup', expect=True)                          # displayed 0
    t.begin('cover', 'dup', C, offset=0)                          # same key, other bytes: a miss (slot 2)
    t.check(valid={'cover': ['dup', 'd1']})
    for at in range(0, len(C), 8):
        t.send('cover', 'dup', C[at:at + 8], at, reply=min(at + 8, len(C)))
    t.commit('cover', 'dup', offset=len(C))                       # slot 0 invalidated, still displayed
    t.check(displayed={'cover': 0}, valid={'cover': ['dup', 'd1']})
    t.have('cover', ['dup'], [True])
    t.begin('cover', 'd3', D, offset=0)                           # slot 0 is invalid but displayed: slot 3
    t.check(valid={'cover': ['dup', 'd1']})
    t.upload('cover', 'd3', D)
    t.begin('cover', 'd4', E, offset=0)                           # 0 pinned (displayed): oldest valid d1
    t.check(valid={'cover': ['dup', 'd3']})
    t.adopt('cover', 'dup', expect=True)                          # displayed moves to slot 2
    t.begin('cover', 'd5', A, offset=0)                           # slot 0: invalid and no longer displayed
    t.check(displayed={'cover': 2}, valid={'cover': ['dup', 'd3']})
    cases.append(t.case())

    # 6b. A begin hit cancels any other upload (either kind); an invalidated duplicate of the
    # frame key is not pinned (only the valid slot holding the frame key is).
    t = Trace('hit-cancels-and-frame-key-duplicate', SMALL)
    t.control(80)
    t.frame(art='y1')
    t.upload('cover', 'y1', A)                                    # slot 0, adopted at its commit
    t.begin('icon', 'z1', I1, offset=0)
    t.send('icon', 'z1', I1[:8], 0, reply=8)
    t.begin('cover', 'y1', A, offset=len(A))                      # hit: cancels the icon upload
    t.send('icon', 'z1', I1[8:], 8, error='No matching media upload', reply=0)
    t.commit('cover', 'y1', offset=len(A))
    t.begin('cover', 'y2', B, offset=0)                           # slot 1
    t.send('cover', 'y2', B[:8], 0, reply=8)
    t.begin('cover', 'y1', A, offset=len(A))                      # hit: cancels y2 (slot 1 stays invalid)
    t.send('cover', 'y2', B[8:16], 8, error='No matching media upload', reply=0)
    t.commit('cover', 'y2', error='No matching media upload')
    t.commit('cover', 'y1', offset=len(A))
    t.check(displayed={'cover': 0}, valid={'cover': ['y1'], 'icon': []})
    t.begin('cover', 'y3', C, offset=0)                           # slot 1 again (lowest invalid)
    t.begin('cover', 'y1', D, offset=0)                           # same key, other bytes: a miss, slot 1
    for at in range(0, len(D), 8):
        t.send('cover', 'y1', D[at:at + 8], at, reply=min(at + 8, len(D)))
    t.commit('cover', 'y1', offset=len(D))                        # slot 0 invalidated; slot 1 adopted
    t.check(displayed={'cover': 1}, valid={'cover': ['y1']})
    t.begin('cover', 'y4', E, offset=0)                           # slot 0: invalid, keeps key y1, unpinned
    t.check(displayed={'cover': 1}, valid={'cover': ['y1']})
    t.commit('cover', 'y1', error='No matching media upload')     # the new begin ended y1's context
    for at in range(0, len(E), 8):
        t.send('cover', 'y4', E[at:at + 8], at, reply=min(at + 8, len(E)))
    t.commit('cover', 'y4', offset=len(E))
    t.check(displayed={'cover': 1}, valid={'cover': ['y1', 'y4']})
    assert t.model.kinds['cover'].slots[0].key == 'y4'              # the victim was slot 0, not slot 2
    cases.append(t.case())

    # 7. Cancellation: a new begin (other kind), a new control, a release; stale IDs.
    t = Trace('cancel-and-stale', SMALL)
    t.control(30)
    t.frame(art='x1', icon='i1')
    t.begin('cover', 'x1', A, offset=0)
    t.send('cover', 'x1', A[:8], 0, reply=8)
    t.begin('icon', 'i1', I1, offset=0)                           # cancels the cover upload
    t.send('cover', 'x1', A[8:16], 8, error='No matching media upload', reply=0)
    t.commit('cover', 'x1', error='No matching media upload')
    t.send('icon', 'i1', I1[:8], 0, reply=8)
    t.control(31)                                                 # a new control cancels it
    t.check(receiving=False)
    t.send('icon', 'i1', I1[8:], 8, error='No matching media upload', reply=0)
    t.id = 30
    t.send('icon', 'i1', I1[8:], 8, error='Stale media control', reply=0)
    t.id = 31
    t.check(valid={'cover': [], 'icon': []})
    t.upload('icon', 'i1', I1)                                    # the frame's icon key: adopted at commit
    t.check(displayed={'icon': 0}, valid={'icon': ['i1']})
    t.begin('cover', 'x1', A, offset=0)
    t.check(receiving=True)
    t.release()                                                   # a release cancels it
    t.check(receiving=False)                                      # observable before any other step
    t.media({'id': 31, 'op': 'data', 'kind': 'cover', 'key': 'x1', 'offset': 0, 'data': b64(A[:8])},
            'Stale media control', 0)
    t.control(32)
    t.send('cover', 'x1', A[:8], 0, error='No matching media upload', reply=0)
    t.media({'id': 33, 'op': 'have', 'kind': 'icon', 'keys': ['i1']}, 'Stale media control')
    t.media({'op': 'have', 'kind': 'icon', 'keys': ['i1']}, 'Stale media control')
    t.media({'id': '32', 'op': 'have', 'kind': 'icon', 'keys': ['i1']}, 'Stale media control')
    t.media({'id': True, 'op': 'begin', 'kind': 'icon', 'key': 'i2', 'bytes': 16, 'crc32': 1}, 'Stale media control', 0)
    t.media({'id': 0, 'op': 'commit', 'kind': 'cover', 'key': 'x1'}, 'Stale media control', 0)
    t.media({'id': 2147483648, 'op': 'commit', 'kind': 'cover', 'key': 'x1'}, 'Stale media control', 0)
    t.media({'id': 32.0, 'op': 'commit', 'kind': 'cover', 'key': 'x1'}, 'Stale media control', 0)
    t.have('icon', ['i1'], [True])
    t.check(displayed={'icon': 0})                                # committed slots survive releases
    cases.append(t.case())

    # 8. Operation, kind, key and size validation, in the order of ARTWORK2.md 4.3.
    t = Trace('validation-order', SMALL)
    t.control(40)
    t.media({'id': 40, 'op': 'delete', 'kind': 'cover', 'key': 'v1'}, 'Unknown media operation', 0)
    t.media({'id': 40, 'kind': 'cover', 'key': 'v1'}, 'Unknown media operation', 0)
    t.media({'id': 40, 'op': 'BEGIN', 'kind': 'banner', 'key': 'bad key'}, 'Unknown media operation', 0)
    t.media({'id': 40, 'op': 7, 'kind': 'icon'}, 'Unknown media operation', 0)
    t.media(5, 'Unknown media operation', 0)
    t.media([], 'Unknown media operation', 0)
    t.media({'id': 40, 'op': 'begin', 'kind': 'banner', 'key': 'v1', 'bytes': 4, 'crc32': 0}, 'Unknown media kind', 0)
    t.media({'id': 40, 'op': 'have', 'keys': ['v1']}, 'Unknown media kind')
    t.media({'id': 39, 'op': 'begin', 'kind': 'cover', 'key': 'bad/key'}, 'Stale media control', 0)
    t.media(t.req('begin', 'cover', key='bad/key', bytes=4, crc32=0), 'Invalid media key', 0)
    t.media(t.req('begin', 'cover', key='k' * 25, bytes=4, crc32=0), 'Invalid media key', 0)
    t.media(t.req('begin', 'cover', key='', bytes=4, crc32=0), 'Invalid media key', 0)
    t.media(t.req('begin', 'cover', bytes=4, crc32=0), 'Invalid media key', 0)
    t.media(t.req('begin', 'cover', key=5, bytes=4, crc32=0), 'Invalid media key', 0)
    t.media(t.req('begin', 'cover', key='k' * 24), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=4), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', crc32=4), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=4.0, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=True, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=4, crc32=-1), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=4, crc32=4294967296), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes='4', crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=-4), 'Media size and CRC required', 0)        # crc32 missing
    t.media(t.req('begin', 'cover', key='v1', bytes=2 ** 64, crc32=0), 'Media size and CRC required', 0)  # a float
    t.media(t.req('begin', 'cover', key='v1', bytes=-(2 ** 63) - 1, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=0, crc32=0), 'Invalid media size', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=65, crc32=0), 'Invalid media size', 0)       # maxBytes 64
    t.media(t.req('begin', 'cover', key='v1', bytes=4294967295, crc32=0), 'Invalid media size', 0)  # in 0..2^32-1
    # bytes outside 0..0xFFFFFFFF (ARTWORK2.md 4.3, lead ruling of 2026-09-24): negative and huge
    # sizes need size and CRC, like a missing or non-integer one.
    t.media(t.req('begin', 'cover', key='v1', bytes=-1, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=-4, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=-(2 ** 63), crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=4294967296, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=4294967360, crc32=0), 'Media size and CRC required', 0)  # 2^32 + 64
    t.media(t.req('begin', 'cover', key='v1', bytes=2 ** 63, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=2 ** 64 - 1, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'icon', key='v1', bytes=-16, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'icon', key='v1', bytes=2 ** 32 + 16, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'icon', key='v1', bytes=15, crc32=0), 'Invalid media size', 0)        # icons: exactly 16
    t.media(t.req('begin', 'icon', key='v1', bytes=17, crc32=0), 'Invalid media size', 0)
    t.media(t.req('begin', 'icon', key='v1', bytes=1, crc32=0), 'Invalid media size', 0)
    t.media(t.req('begin', 'cover', key='v1', bytes=64, crc32=4294967295), None, 0)              # largest cover
    t.media(t.req('data', 'cover', key='v/1', offset=0, data=b64(b'x')), 'Invalid media key', 0)
    t.media(t.req('commit', 'cover', key='v' * 25), 'Invalid media key', 0)
    t.media(t.req('begin', 'icon', key='v2', bytes=16, crc32=zlib.crc32(I2)), None, 0)
    t.check()
    cases.append(t.case())

    # 9. have validation and touch order.
    t = Trace('have-keys-and-touch-order', SMALL)
    t.control(50)
    for key, data in (('h0', I1), ('h1', I2), ('h2', I3)):
        t.upload('icon', key, data)
    t.have('icon', ['h2', 'h0', 'nope', 'h1'], [True, True, False, True])
    t.check()
    t.have('icon', ['h0', 'h1', 'h2', 'h0', 'h1'], error='Invalid media keys')   # 5 > haveKeys 4
    t.have('icon', [], error='Invalid media keys')
    t.have('icon', ['h0', 'bad key'], error='Invalid media keys')
    t.have('icon', ['h0', 'k' * 25], error='Invalid media keys')
    t.have('icon', ['h0', ''], error='Invalid media keys')
    t.have('icon', ['h0', 5], error='Invalid media keys')
    t.media(t.req('have', 'icon', keys='h0'), 'Invalid media keys')
    t.media(t.req('have', 'icon'), 'Invalid media keys')
    t.media(t.req('have', 'icon', keys=['h0'], key='h0'), None, have=[True])           # a key field is ignored
    t.check()                                                     # failed have queries touched nothing
    t.begin('icon', 'h3', I4, offset=0)                           # S = 4: slot 3 is free
    t.upload('icon', 'h3', I4)
    t.have('icon', ['h1'], [True])
    t.begin('icon', 'h4', I5, offset=0)                           # oldest: h2 (touched first above)
    t.check(valid={'icon': ['h0', 'h1', 'h3']})
    t.have('icon', ['h4'], [False])                               # in progress: not valid yet
    t.send('icon', 'h4', I5[:8], 0, reply=8)
    t.have('icon', ['h0'], [True])                                # have never cancels the upload
    t.send('icon', 'h4', I5[8:], 8, reply=16)
    t.commit('icon', 'h4', offset=16)
    t.check(valid={'icon': ['h0', 'h1', 'h3', 'h4']})
    cases.append(t.case())

    # 10. Frame keys: adoption at frame, a key committed later, noAdopt, invalid frame keys.
    t = Trace('frame-keys-and-adoption', SMALL)
    t.control(60)
    t.frame(art='f1', icon='g1')                                  # neither present: displayed -1
    t.check(displayed={'cover': -1, 'icon': -1})
    t.upload('icon', 'g1', I1)                                    # adopted at its commit
    t.upload('cover', 'f0', A)                                    # not the frame key: not adopted
    t.check(displayed={'cover': -1, 'icon': 0})
    t.upload('cover', 'f1', B)
    t.check(displayed={'cover': 1, 'icon': 0})
    t.frame(art='f0', icon='g1')                                  # f0 adopted (touched); g1 already displayed
    t.check(displayed={'cover': 0, 'icon': 0})
    t.frame(art='f1', icon='', adopt=False)                       # keys change, the LCD has not drawn yet
    t.check(displayed={'cover': 0, 'icon': 0})
    t.frame(art='k' * 64, icon='g1')                              # a v1-length artKey pins nothing
    t.check(displayed={'cover': -1, 'icon': 0})
    t.frame(art='f0', icon='bad key')
    t.check(displayed={'cover': 0, 'icon': -1})
    t.adopt('cover', 'f1', expect=True)
    t.adopt('cover', 'f1', expect=True)                           # unchanged: no touch
    t.adopt('icon', 'nope', expect=False)
    t.adopt('cover', '', expect=False)
    t.check(displayed={'cover': -1, 'icon': -1})
    t.begin('cover', 'f1', B, offset=len(B))                      # hit: no adoption rule at hit commits
    t.commit('cover', 'f1', offset=len(B))
    t.check(displayed={'cover': -1})
    cases.append(t.case())

    # 11. Decode check (validateJpeg true): a tiny invalid payload, a 16x16 JPEG, a 240x240 one.
    t = Trace('cover-decode-check', SMALL_JPEG)
    t.control(70)
    t.frame(art='jz')
    tiny = b'not a jpeg!!'
    t.begin('cover', 'jx', tiny, offset=0)
    t.send('cover', 'jx', tiny, 0, reply=len(tiny))
    t.commit('cover', 'jx', error='Media decode failed', offset=len(tiny))
    t.commit('cover', 'jx', error='No matching media upload')     # cancelled
    small = gray_jpeg(16, 16)
    t.begin('cover', 'jy', small, offset=0)
    t.send('cover', 'jy', small, 0, reply=len(small))
    t.commit('cover', 'jy', error='Media decode failed', offset=len(small))
    # A 240x240 JPEG must end with EOI as its last two bytes: cut short (EOI missing, or the
    # scan cut in half) or followed by a trailing byte, it fails the check.
    good = gray_jpeg(240, 240)
    chunk = SMALL_JPEG['chunkBytes']
    for key, bad in (('jn', good[:-2]), ('jc', good[:len(good) // 2]), ('jt', good + b'\x00')):
        t.begin('cover', key, bad, offset=0)
        for at in range(0, len(bad), chunk):
            t.send('cover', key, bad[at:at + chunk], at, reply=min(at + chunk, len(bad)))
        t.commit('cover', key, error='Media decode failed', offset=len(bad))
    t.check(valid={'cover': []})
    t.upload('cover', 'jz', good)                                 # the frame's key: adopted at commit
    t.check(displayed={'cover': 0}, valid={'cover': ['jz']})
    t.upload('icon', 'jicon', payload('garbage icon', 16))        # icons are never decoded
    t.check(valid={'icon': ['jicon']})
    cases.append(t.case())

    # 12. The real capability configuration (ARTWORK2.md section 1).
    t = Trace('real-capability-config', REAL)
    t.control(0x7FFFFFFF)
    t.frame(art='cover240', icon='icon0')
    good = gray_jpeg(240, 240)
    t.upload('cover', 'cover240', good)
    icons = [payload(f'real-icon-{n}', presentation.ICON_BYTES) for n in range(3)]
    for n, data in enumerate(icons):
        t.upload('icon', f'icon{n}', data)                        # one 2048-byte chunk each
    t.check(displayed={'cover': 0, 'icon': 0}, valid={'cover': ['cover240'], 'icon': ['icon0', 'icon1', 'icon2']})
    keys = [f'icon{n}' for n in range(24)]
    t.have('icon', keys, [n < 3 for n in range(24)])
    t.have('icon', keys + ['icon24'], error='Invalid media keys')
    t.media(t.req('begin', 'icon', key='iconX', bytes=2047, crc32=0), 'Invalid media size', 0)
    t.media(t.req('begin', 'icon', key='iconX', bytes=2049, crc32=0), 'Invalid media size', 0)
    t.media(t.req('begin', 'cover', key='coverX', bytes=32769, crc32=0), 'Invalid media size', 0)
    big = payload('big cover', presentation.COVER_MAX_BYTES)
    t.begin('cover', 'coverX', big, offset=0)
    t.media(t.req('data', 'cover', key='coverX', offset=0, data=b64(big[:2049])), 'Invalid media data', 0)
    t.send('cover', 'coverX', big[:2048], 0, reply=2048)
    t.commit('cover', 'coverX', error='Media upload incomplete', offset=2048)
    t.check()
    cases.append(t.case())

    # 13. Every slot pinned (entries 1: S = 2, the displayed slot and the frame key's slot): a
    # miss begin cancels the upload in progress first (ARTWORK2.md 4.4 step 2), then answers
    # "Media unavailable" and changes nothing else.
    one = {'cover': {'entries': 1, 'slotBytes': 64, 'maxBytes': 64},
           'icon': {'entries': 1, 'slotBytes': 16, 'bytes': 16},
           'chunkBytes': 8, 'haveKeys': 4, 'validateJpeg': False}
    t = Trace('all-pinned-miss-cancels-upload', one)
    t.control(90)
    t.upload('cover', 'a0', A)                                    # slot 0
    t.upload('cover', 'a1', B)                                    # slot 1
    t.adopt('cover', 'a0', expect=True)                           # displayed 0 (touched)
    t.frame(art='a1', adopt=False)                                # frame key a1: slot 1
    t.begin('icon', 'n1', I1, offset=0)                           # an icon upload in progress (slot 0)
    t.send('icon', 'n1', I1[:8], 0, reply=8)
    t.check(displayed={'cover': 0}, valid={'cover': ['a0', 'a1'], 'icon': []})
    t.begin('cover', 'a2', C, error='Media unavailable', offset=0)   # both cover slots pinned
    t.send('icon', 'n1', I1[8:], 8, error='No matching media upload', reply=0)   # it was cancelled first
    t.commit('icon', 'n1', error='No matching media upload')
    t.check(displayed={'cover': 0}, valid={'cover': ['a0', 'a1'], 'icon': []})
    t.begin('cover', 'a1', B, offset=len(B))                      # a hit on a pinned slot still works
    t.commit('cover', 'a1', offset=len(B))
    t.frame(art='')                                               # no pins left: displayed -1, no frame key
    t.begin('cover', 'a2', C, offset=0)                           # least recently touched: a0 (slot 0)
    t.check(displayed={'cover': -1}, valid={'cover': ['a1']})
    for at in range(0, len(C), 8):
        t.send('cover', 'a2', C[at:at + 8], at, reply=min(at + 8, len(C)))
    t.commit('cover', 'a2', offset=len(C))
    t.check(valid={'cover': ['a1', 'a2']})
    assert t.model.kinds['cover'].slots[0].key == 'a2'
    cases.append(t.case())

    # 14. A begin hit needs the same key, bytes AND crc (ARTWORK2.md 4.4): the same key and size
    # with another crc32 is a miss that takes a new victim; its commit invalidates the old slot.
    t = Trace('begin-hit-needs-the-same-crc', SMALL)
    t.control(95)
    t.upload('cover', 'h', A)                                     # slot 0
    t.begin('cover', 'h', A, offset=0, crc=zlib.crc32(A) ^ 1)     # same key and bytes, other crc: a miss
    t.check(valid={'cover': ['h']})                               # slot 1 taken; slot 0 still valid
    A2 = bytes(b ^ 0x5A for b in A)                               # same size, other bytes
    assert len(A2) == len(A) and zlib.crc32(A2) != zlib.crc32(A)
    t.upload('cover', 'h', A2)                                    # a miss again (slot 1), committed
    t.check(valid={'cover': ['h']})                               # slot 0 invalidated as a duplicate
    assert [s.valid for s in t.model.kinds['cover'].slots[:2]] == [False, True]
    t.begin('cover', 'h', A, offset=0)                            # the old crc no longer hits
    t.begin('cover', 'h', A2, offset=len(A2))                     # the new one does
    t.commit('cover', 'h', offset=len(A2))
    t.check(valid={'cover': ['h']})
    cases.append(t.case())

    # 15. A rejected begin changes no state (ARTWORK2.md 4.3): the upload in progress continues
    # after every begin that fails before its hit/miss step, then commits.
    t = Trace('rejected-begin-keeps-the-upload', SMALL)
    t.control(96)
    t.begin('cover', 'u1', B, offset=0)
    t.send('cover', 'u1', B[:8], 0, reply=8)
    t.media(t.req('begin', 'cover', key='bad key', bytes=4, crc32=0), 'Invalid media key', 0)
    t.media(t.req('begin', 'icon', key='u2', bytes=16), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='u2', bytes=-1, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='u2', bytes=0, crc32=0), 'Invalid media size', 0)
    t.media(t.req('begin', 'icon', key='u2', bytes=15, crc32=0), 'Invalid media size', 0)
    t.media({'id': 96, 'op': 'begin', 'kind': 'banner', 'key': 'u2', 'bytes': 4, 'crc32': 0},
            'Unknown media kind', 0)
    t.media({'id': 95, 'op': 'begin', 'kind': 'cover', 'key': 'u2', 'bytes': 4, 'crc32': 0},
            'Stale media control', 0)
    t.media({'id': 96, 'op': 'begun', 'kind': 'cover', 'key': 'u2', 'bytes': 4, 'crc32': 0},
            'Unknown media operation', 0)
    # Requests that name the live upload u1 (8 bytes received) but fail before an upload context
    # is matched carry offset 0, not the received count (ARTWORK2.md 4.2): a stale id (4.3 step 5
    # comes before any per-op check) and rejected begins for the same key.
    t.media({'id': 95, 'op': 'data', 'kind': 'cover', 'key': 'u1', 'offset': 8, 'data': b64(B[8:16])},
            'Stale media control', 0)
    t.media({'id': 95, 'op': 'commit', 'kind': 'cover', 'key': 'u1'}, 'Stale media control', 0)
    t.media(t.req('begin', 'cover', key='u1', bytes=-1, crc32=0), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='u1', bytes=len(B)), 'Media size and CRC required', 0)
    t.media(t.req('begin', 'cover', key='u1', bytes=0, crc32=0), 'Invalid media size', 0)
    t.media(t.req('begin', 'cover', key='u1', bytes=65, crc32=zlib.crc32(B)), 'Invalid media size', 0)
    t.check(valid={'cover': []}, receiving=True)
    t.send('cover', 'u1', B[8:16], 8, reply=16)                   # the same upload, from the same offset
    t.send('cover', 'u1', B[16:], 16, reply=len(B))
    t.commit('cover', 'u1', offset=len(B))
    t.check(valid={'cover': ['u1']})
    cases.append(t.case())

    # 16. The commit check reads the marker segments and prepares the decoder, but never decodes
    # the scan (ARTWORK2.md 4.3, CONTROL_CENTER.md "Cover check at commit"): an empty marker
    # segment before SOS is refused, a scan damaged in the middle that still ends with EOI commits
    # (its decode fails later on the LCD).
    t = Trace('cover-check-reads-headers-only', SMALL_JPEG)
    t.control(97)
    good = gray_jpeg(240, 240)
    empty = good[:2] + b'\xFF\xE1\x00\x02' + good[2:]            # an APP1 segment of length 2
    scan = good.index(b'\xFF\xDA') + 2 + int.from_bytes(good[good.index(b'\xFF\xDA') + 2:][:2], 'big')
    middle = (scan + len(good) - 2) // 2
    assert good[middle] == 0x00 and len(good) - 2 - scan > 64
    damaged = good[:middle] + b'\x55' + good[middle + 1:]         # headers and EOI intact
    chunk = SMALL_JPEG['chunkBytes']
    t.begin('cover', 'je', empty, offset=0)
    for at in range(0, len(empty), chunk):
        t.send('cover', 'je', empty[at:at + chunk], at, reply=min(at + chunk, len(empty)))
    t.commit('cover', 'je', error='Media decode failed', offset=len(empty))
    t.upload('cover', 'jd', damaged)
    t.check(valid={'cover': ['jd']})
    cases.append(t.case())

    # 17. An accepted frame never ends the upload (ARTWORK2.md 4.4 lists what does): frames naming
    # the key being uploaded, another key, or no key, with and without adoption, arrive between an
    # upload's lines; the upload continues from its offset, and a frame key committed later is
    # adopted at its commit (the runner rule), one that is not the frame key is not.
    t = Trace('frame-mid-upload-keeps-it', SMALL)
    t.control(98)
    t.frame(art='m0')                                             # m0 is not held: displayed -1
    t.begin('cover', 'm1', A, offset=0)                           # slot 0
    t.send('cover', 'm1', A[:8], 0, reply=8)
    t.frame(art='m1')                                             # names the key mid-upload
    t.check(displayed={'cover': -1}, receiving=True)              # slot 0 is not valid yet: no pin, no adoption
    t.send('cover', 'm1', A[8:16], 8, reply=16)
    t.frame(art='m0', icon='', adopt=False)
    t.frame(art='')
    t.check(displayed={'cover': -1, 'icon': -1}, receiving=True)
    t.frame(art='m1')
    t.send('cover', 'm1', A[16:], 16, reply=len(A))
    t.commit('cover', 'm1', offset=len(A))                        # the frame's key: adopted at its commit
    t.check(displayed={'cover': 0}, valid={'cover': ['m1']}, receiving=False)
    t.begin('icon', 'n1', I1, offset=0)
    t.send('icon', 'n1', I1[:8], 0, reply=8)
    t.frame(art='m1', icon='n2')                                  # another icon key: n1 goes on
    t.check(displayed={'cover': 0, 'icon': -1}, receiving=True)
    t.send('icon', 'n1', I1[8:], 8, reply=16)
    t.commit('icon', 'n1', offset=16)                             # not the frame's icon key: not adopted
    t.check(displayed={'cover': 0, 'icon': -1}, valid={'icon': ['n1']}, receiving=False)
    cases.append(t.case())

    # 18. A store that was never allocated (cc_media.cpp fail-soft; config "available": false)
    # answers "Media unavailable" to every request of its kind once the operation and kind are
    # known (4.3 steps 2-4), before the control check (step 5): with no session, with a stale id,
    # and with the active one. Its table is empty, a frame naming its key adopts nothing, the
    # other kind works normally, and a rejected request changes no state (the icon upload goes on).
    unallocated = {'cover': {'entries': 3, 'slotBytes': 64, 'maxBytes': 64, 'available': False},
                   'icon': {'entries': 3, 'slotBytes': 16, 'bytes': 16},
                   'chunkBytes': 8, 'haveKeys': 4, 'validateJpeg': False}
    t = Trace('unallocated-cover-store', unallocated)
    t.have('cover', ['c1'], error='Media unavailable')            # no session yet
    t.have('icon', ['i1'], error='Stale media control')           # the allocated kind: the control check
    t.control(99)
    t.frame(art='c1', icon='i1')
    t.check(displayed={'cover': -1, 'icon': -1}, valid={'cover': [], 'icon': []}, receiving=False)
    t.have('cover', ['c1'], error='Media unavailable')
    t.media({'id': 98, 'op': 'begin', 'kind': 'cover', 'key': 'c1', 'bytes': len(A), 'crc32': zlib.crc32(A)},
            'Media unavailable', 0)                               # a stale id: step 4 answers first
    t.begin('cover', 'c1', A, error='Media unavailable', offset=0)
    t.send('cover', 'c1', A[:8], 0, error='Media unavailable', reply=0)
    t.commit('cover', 'c1', error='Media unavailable', offset=0)
    t.media({'id': 99, 'op': 'nope', 'kind': 'cover', 'key': 'c1'}, 'Unknown media operation', 0)
    t.media({'id': 99, 'op': 'have', 'kind': 'banner', 'keys': ['c1']}, 'Unknown media kind')
    t.upload('icon', 'i1', I1)                                    # the frame's icon key: adopted at commit
    t.begin('icon', 'i2', I2, offset=0)
    t.send('icon', 'i2', I2[:8], 0, reply=8)
    t.begin('cover', 'c2', B, error='Media unavailable', offset=0)   # changes no state
    t.send('icon', 'i2', I2[8:], 8, reply=16)
    t.check(displayed={'cover': -1, 'icon': 0}, valid={'cover': [], 'icon': ['i1']}, receiving=True)
    t.commit('icon', 'i2', offset=16)
    t.check(valid={'cover': [], 'icon': ['i1', 'i2']}, receiving=False)
    cases.append(t.case())
    return cases


def build_fixture() -> dict:
    JPEG_VERDICTS.clear()
    return {'version': 1, 'cases': scenarios()}


def write_verdicts(build: Path) -> Path:
    """The Model's cover verdicts (JPEG_VERDICTS) as files plus a manifest for media_tests.cpp."""
    folder = build / 'model-covers'
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob('*.bin'):
        stale.unlink()
    lines = []
    for index, (data, verdict) in enumerate(JPEG_VERDICTS.items()):
        path = folder / f'{index:03d}.bin'
        path.write_bytes(data)
        lines.append(f'{int(verdict)} {path}\n')
    manifest = folder / 'verdicts.txt'
    manifest.write_text(''.join(lines), encoding='utf-8')
    return manifest


def dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(',', ':')).replace('{"name":', '\n{"name":') + '\n'


# ---------------------------------------------------------------------------
# Builds.

def msvc_env():
    msvc = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207')
    sdk = Path('C:/Program Files (x86)/Windows Kits/10')
    sdk_include = sorted((sdk / 'Include').iterdir(), key=lambda p: p.name)[-1]
    sdk_lib = sdk / 'Lib' / sdk_include.name
    env = {key.upper(): value for key, value in os.environ.items()}
    env['INCLUDE'] = ';'.join(str(path) for path in (
        msvc / 'include', sdk_include / 'ucrt', sdk_include / 'shared', sdk_include / 'um'))
    env['LIB'] = ';'.join(str(path) for path in (
        msvc / 'lib/x64', sdk_lib / 'ucrt/x64', sdk_lib / 'um/x64'))
    return msvc / 'bin/Hostx64/x64/cl.exe', env


def compile_tjpgd(build: Path) -> Path:
    """LVGL's TJpgDec R0.03, read-only from libdeps (third-party C: its own warnings are not ours)."""
    cl, env = msvc_env()
    obj = build / 'tjpgd.obj'
    subprocess.run([str(cl), '/nologo', '/c', '/O2', '/W0', str(tjpgd / 'tjpgd.c'), f'/Fo{obj}'],
                   cwd=build, env=env, check=True)
    return obj


def compile_runner(build: Path, source: Path, exe_name: str, includes=(), objects=(), defines=()) -> Path:
    """`source` + src/cc_jpeg.cpp (+ TJpgDec, + `objects`) with MSVC /W4 /WX. `includes` come
    before src/ (the wiring stubs must shadow src/foc_thread.h and src/HapticProfileManager.h)."""
    cl, env = msvc_env()
    obj = compile_tjpgd(build)
    exe = build / exe_name
    subprocess.run([
        str(cl), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2', '/D_CRT_SECURE_NO_WARNINGS',
        *(f'/D{define}' for define in defines), *(f'/I{path}' for path in includes),
        f'/I{firmware / "src"}', f'/I{shim}',
        # Third-party headers: their own warnings are not ours (the gnu++11 gate parses ArduinoJson).
        f'/external:I{arduinojson}', f'/external:I{tjpgd}', '/external:W0',
        str(source), str(firmware / 'src' / 'cc_jpeg.cpp'), str(obj), *(str(o) for o in objects),
        f'/Fo{build}\\', f'/Fe{exe}',
    ], cwd=build, env=env, check=True)
    return exe


# ---------------------------------------------------------------------------
# control_center.cpp wiring (media dispatch, control-ID binding, frame keys, lease), on the host.
# The unit is compiled from a byte-identical copy in build/media-tests/wiring/, so that its
# quoted includes of HapticProfileManager.h and foc_thread.h (firmware headers that pull in
# SimpleFOC, SPIFFS and FreeRTOS) find these stubs before src/; every other header it includes
# is the real one from src/. cc_media.cpp (the real ESP wrapper, with the real store) and
# cc_frame_parse.cpp are compiled from src/ unchanged. The stubs model only what those units
# call: a settable millis(), String, no-op critical sections and mutexes (one thread), malloc
# for PSRAM. media_tests.cpp (CC_MEDIA_WIRING) defines the stubbed functions and the other
# firmware functions the units link against (breadcrumbs, serial replies, v1 art, diag).

WIRING_STUBS = {
    'Arduino.h': '''#pragma once
// Host stub (media_tests.py wiring build): only what control_center.cpp, cc_media.cpp and
// cc_serial_out.h use. One thread: critical sections and mutexes do nothing.
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <string>
uint32_t millis();                                   // media_tests.cpp: a settable clock
class String {
public:
    String(const char* text = "") : text_(text ? text : "") {}
    const char* c_str() const { return text_.c_str(); }
private:
    std::string text_;
};
struct portMUX_TYPE { int unused; };
#define portMUX_INITIALIZER_UNLOCKED {0}
#define portENTER_CRITICAL(mux) ((void)(mux))
#define portEXIT_CRITICAL(mux) ((void)(mux))
typedef void* TaskHandle_t;
inline uint32_t uxTaskGetStackHighWaterMark(TaskHandle_t) { return 4096; }
inline TaskHandle_t xTaskGetHandle(const char*) { return nullptr; }
typedef void* SemaphoreHandle_t;
#define portMAX_DELAY 0xFFFFFFFFu
SemaphoreHandle_t xSemaphoreCreateMutex();
int xSemaphoreTake(SemaphoreHandle_t mutex, uint32_t ticks);
int xSemaphoreGive(SemaphoreHandle_t mutex);
''',
    'esp_heap_caps.h': '''#pragma once
// Host stub (media_tests.py wiring build): PSRAM is the host heap.
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#define MALLOC_CAP_8BIT (1u << 2)
#define MALLOC_CAP_SPIRAM (1u << 10)
#define MALLOC_CAP_INTERNAL (1u << 11)
inline void* heap_caps_malloc(size_t size, uint32_t) { return malloc(size); }
inline void heap_caps_free(void* block) { free(block); }
inline size_t heap_caps_get_free_size(uint32_t) { return 0; }
inline size_t heap_caps_get_minimum_free_size(uint32_t) { return 0; }
''',
    'HapticProfileManager.h': '''#pragma once
// Host stub (media_tests.py wiring build): one regular preset, as control_center.cpp reads it.
#include <Arduino.h>
#include "haptic_api.h"
struct CCWiringKnobValue { DetentProfile haptic; };
struct CCWiringKnob { uint8_t num; CCWiringKnobValue values[1]; };
struct CCWiringHmiConfig { CCWiringKnob knob; };
class HapticProfile {
public:
    CCWiringHmiConfig hmi_config;
};
class HapticProfileManager {
public:
    static HapticProfileManager& getInstance();
    HapticProfile* operator[](String name);        // "Regular", else nullptr
};
''',
    'foc_thread.h': '''#pragma once
// Host stub (media_tests.py wiring build).
#include <Arduino.h>
class FocThread {
public:
    TaskHandle_t getHandle() { return nullptr; }
};
extern FocThread foc_thread;
''',
    'common/foc_utils.h': '''#pragma once
// Host stub (media_tests.py wiring build): src/haptic_api.h includes SimpleFOC's foc_utils.h
// but uses nothing from it.
''',
}
WIRING_UNITS = ('control_center.cpp', 'cc_media.cpp', 'cc_frame_parse.cpp')


def compile_wiring(build: Path) -> tuple[Path, list]:
    """(stub include directory, objects) of the wiring units, MSVC /W4 /WX."""
    wiring = build / 'wiring'
    stubs = wiring / 'stubs'
    for name, text in WIRING_STUBS.items():
        path = stubs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    copy = wiring / 'control_center.cpp'
    copy.write_bytes((firmware / 'src' / 'control_center.cpp').read_bytes())   # verbatim
    cl, env = msvc_env()
    # control_center.cpp's cc5.2 control parsing narrows validated uint32_t values into uint8_t /
    # uint16_t fields (button order, windows button, profile bounds, position) without casts,
    # which MSVC reports as C4244 (xtensa g++ -Wall -Wextra does not): only that warning is off,
    # and only for that unit. cc_media.cpp and cc_frame_parse.cpp build with plain /W4 /WX.
    for sources, extra in (([copy], ['/wd4244']),
                           ([firmware / 'src' / 'cc_media.cpp', firmware / 'src' / 'cc_frame_parse.cpp'], [])):
        subprocess.run([
            str(cl), '/nologo', '/c', '/EHsc', '/std:c++14', '/W4', '/WX', *extra, '/O2', '/D_CRT_SECURE_NO_WARNINGS',
            f'/I{stubs}', f'/I{firmware / "src"}', f'/I{shim}',
            f'/external:I{arduinojson}', '/external:W0',
            *(str(source) for source in sources), f'/Fo{wiring}\\',
        ], cwd=wiring, env=env, check=True)
    return stubs, [wiring / (Path(unit).stem + '.obj') for unit in WIRING_UNITS]


def wiring_frame(build: Path) -> Path:
    """A valid windows-layout frame (frames_v4.json case v4-windows-icon-key) for the wiring test."""
    fixture = json.loads((companion / 'tests' / 'fixtures' / 'frames_v4.json').read_text(encoding='utf-8'))
    frame = next(case['input'] for case in fixture['cases'] if case['name'] == 'v4-windows-icon-key')
    path = build / 'wiring' / 'frame.json'
    path.write_text(json.dumps(frame), encoding='utf-8')
    return path




def gnu11_gate(build: Path) -> bool:
    """cpp11_gate.py's header unit for cc_media_store.h (HEADER_UNITS: a translation unit that
    odr-uses the store and the COM transport helpers), with the gate's own self-test first."""
    sys.path.insert(0, str(root))
    import cpp11_gate  # noqa: E402  (read-only: its compiler lines, checks and translation unit)
    with tempfile.TemporaryDirectory(prefix='media-gate-') as temp:
        scratch = Path(temp)
        if not cpp11_gate.self_test(scratch):
            return False
        return cpp11_gate.check_header_unit('cc_media_store.h', scratch)


# Firmware units of this track, syntax-checked with their PlatformIO command lines.
FIRMWARE_UNITS = ['cc_media.cpp', 'cc_jpeg.cpp', 'control_center.cpp', 'com_thread.cpp', 'cc_diag.cpp',
                  'main.cpp', 'cc_frame_parse.cpp']
TEMPLATE_UNIT = 'cc_artwork.cpp'


def firmware_syntax(units=FIRMWARE_UNITS) -> bool:
    """-fsyntax-only with the exact compile_commands.json line (the unit's own, or cc_artwork.cpp's)."""
    database = json.loads((firmware / 'compile_commands.json').read_text(encoding='utf-8'))
    entries = {Path(e['file']).as_posix(): e for e in database}
    ok = True
    for unit in units:
        own = entries.get(f'src/{unit}')
        entry = own or entries[f'src/{TEMPLATE_UNIT}']
        command = entry['command']
        source = Path(entry['file']).as_posix().replace('/', '\\')
        output = entry.get('output') or ''
        pattern = f'-o {output} -c '
        if pattern not in command or not command.endswith(' ' + source):
            print(f'FAIL {unit}: unexpected compile_commands.json line')
            return False
        command = command.replace(pattern, '-fsyntax-only -Wall -Wextra ', 1)
        # No dependency file: with -MMD and no -o, g++ writes <unit>.d into the firmware root,
        # which git ls-files --others would then list as a source file (package_nanod_cc5.py).
        command = command.replace(' -MMD ', ' ')
        command = command[:-len(source)] + f'src\\{unit}'
        started = time.time()
        result = subprocess.run(command, cwd=entry['directory'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        text = (result.stdout + result.stderr).strip()
        # Diagnostics from this unit or the headers of this track only (framework noise is not ours).
        ours = [line for line in text.splitlines() if re.match(r'^src[\\/][^:]+:\d+', line)]
        status = 'PASS' if result.returncode == 0 and not ours else 'FAIL'
        print(f'{status} {unit}: xtensa g++ -std=gnu++11 -fsyntax-only -Wall -Wextra '
              f'({"own line" if own else TEMPLATE_UNIT + " line"}) [{time.time() - started:.1f} s]')
        if status == 'FAIL':
            print(text[-6000:])
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--write', action='store_true', help='rewrite media_store_traces.json from the scenarios')
    parser.add_argument('--firmware-syntax', action='store_true',
                        help='also syntax-check the firmware units with their PlatformIO command lines')
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)   # keep our lines in order with the tools' output
    started = time.time()
    # 1. The shared fixture.
    text = dumps(build_fixture())
    if args.write or not fixture_path.is_file():
        fixture_path.write_text(text, encoding='utf-8', newline='\n')
        print(f'media_tests: wrote {fixture_path.name} ({len(text.encode())} bytes)')
    elif fixture_path.read_text(encoding='utf-8') != text:
        print(f'FAIL: {fixture_path.name} differs from the scenarios (run media_tests.py --write '
              'after a deliberate change, and tell the FakeKnob owners)')
        return 1
    data = json.loads(text)
    steps = sum(len(case['steps']) for case in data['cases'])
    media = sum(1 for case in data['cases'] for step in case['steps'] if step['do'] == 'media')
    print(f'media_tests: fixture {len(data["cases"])} case(s), {steps} step(s), {media} media request(s), '
          f'{len(JPEG_VERDICTS)} cover payload(s) judged by the Model', flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    verdicts = write_verdicts(out_dir)
    # 2. gnu++11 gate for the header-only store.
    if not gnu11_gate(out_dir):
        print('FAIL: cc_media_store.h is not valid gnu++11')
        return 1
    if args.firmware_syntax and not firmware_syntax():
        return 1
    # 3. The C++ replay, the direct assertions and the control_center.cpp wiring.
    stubs, objects = compile_wiring(out_dir)
    exe = compile_runner(out_dir, root / 'media_tests.cpp', 'media_tests.exe', includes=[stubs], objects=objects,
                         defines=['CC_MEDIA_WIRING'])
    capability = json.dumps(presentation.ARTWORK2_CAPABILITY, separators=(',', ':'))
    gray = out_dir / 'wiring' / 'gray240.jpg'
    gray.write_bytes(gray_jpeg(presentation.COVER_SIZE, presentation.COVER_SIZE))
    result = subprocess.run([str(exe), str(fixture_path), capability, str(wiring_frame(out_dir)), str(gray),
                             str(verdicts)])
    if result.returncode:
        return result.returncode
    print(f'PASS: media store parity and control_center.cpp media wiring [{time.time() - started:.1f} s]')
    return 0


if __name__ == '__main__':
    sys.exit(main())

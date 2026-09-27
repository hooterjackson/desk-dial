"""Firmware frame-parser parity tests (Stage 2). Python stdlib + MSVC only.

Compiles the unchanged firmware parser (src/cc_frame_parse.cpp) with MSVC
/W4 /WX and runs it over the shared fixtures
app/tests/fixtures/frames_v4.json:

- rules.firmwareOutput: every accepted case's expect.output must be accepted,
  with every text field stored byte-identically and every typed field equal
  to the contract default/derivation (layout from mode, derived ring.first,
  colours/mask kept only when relative to first 0, tone and footer ink).
- rules.firmwareRaw: every rawParity case's input must match expect.accept
  and, when accepted, store the text of every text field present in
  expect.output (plus the typed fields the host cannot legitimately change).
- Extra cases: recorded v2-companion frames without layout (and without
  icons), a 45-window legacy frame without first, the legacy label -> icon
  table (checked against controller.BUTTON_ICONS, or lcd_preview.LEGACY_ICON once the
  controller no longer defines it), and byte-level text rules
  (malformed UTF-8, embedded NUL, 4-byte code points at the capacity).
- 1.0.0-cc5.4 (ALIVE.md section 3): the same rules over
  app/tests/fixtures/frames_alive.json, plus
  rules.aliveRaw: every case's input must be accepted exactly when
  alive.accept and then store alive.stored (playing, feedbackSkip, clock,
  progress, ledDrive, ledDither). The Python reading (device.alive_parse) is
  checked against the same expectations first, so both parsers are held to
  one fixture; byte-level number spellings (-0, 1e3, overflow) are extra
  cases checked against both. Every other case also checks the section 3
  defaults (a frame without the fields stores playing -1, skip 0, nothing
  latched).
- 1.0.0-cc5.4 presentation 5 (PRESENTATION_V5.md section 15): the same rules
  over app/tests/fixtures/frames_v5.json, plus
  rules.v5Raw (every input accepted exactly when v5.accept, then storing
  v5.stored; device.v5_parse checked against the same expectations first) and
  rules.downgrade: every presentation < 5 host output is also fed to the
  cc5.3 (presentation 4) parser, taken from the cc5.3 source snapshot
  (app/firmware/nanod-control-center-1.0.0-cc5.3-source.zip)
  and built into a second runner with CC_V4_PARSER. Every other fixture's
  output also checks the v5 defaults. Byte-level number spellings of the v5
  fields are extra cases checked against both parsers.
- Tones and inks follow cc_presentation.h as it stands: the V4 tone table
  (presentation.button_tone) until cc_button_tone() carries the v5 rows, then
  presentation.button_tone_v5 / button_ink_v5 (incl. the [r2.2] derived tone
  `liked`, #A3244A). While the header derives the V4 tones its V4 dim ink
  (CCFooterInk::dim) is reported as PENDING and checked against the header's
  value; once it derives the v5 tones every ink, dim included, is checked
  against presentation (dim #5A5A5A) and a different CCFooterInk::dim fails.

First runs cpp11_gate.py so the parser also compiles in the device's gnu++11.
Reads the companion's fixtures and presentation constants; writes only under
harness/build/parse-tests. No device or USB access. Exit status is
non-zero on any mismatch.

--frames <capture.jsonl> [--out DIR]: replay a recorded companion session
(app/tests/tools/capture_session_frames.py) instead of
the fixtures. Every recorded `{"frame":…}` and `{"control":…}` line is fed,
byte for byte, to the real cc_parse_frame (plus the id/control checks
control_center.cpp applies before it). The runner reports accept/reject per
line and any stored text that differs from the input line (as ArduinoJson
decodes it, and as Python decodes it), and checks every typed field like the
firmwareOutput fixtures. Lines recorded against presentation < 4 firmware are
also parsed by the installed cc4 parser, excerpted verbatim from
app/firmware/nanod-control-center-1.0.0-cc4-source.zip
when that snapshot is available. The gnu++11 gate is not run in this mode.
Writes only under DIR (default harness/build/parse-frames).
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'
companion = root.parent / 'app'
fixtures_path = companion / 'tests' / 'fixtures' / 'frames_v4.json'
alive_fixtures_path = companion / 'tests' / 'fixtures' / 'frames_alive.json'   # 1.0.0-cc5.4
v5_fixtures_path = companion / 'tests' / 'fixtures' / 'frames_v5.json'         # presentation 5
cc53_source_zip = companion / 'firmware' / 'nanod-control-center-1.0.0-cc5.3-source.zip'   # the V4 parser
arduinojson = firmware / '.pio' / 'libdeps' / 'nanofoc_d' / 'ArduinoJson' / 'src'
out_dir = root / 'build' / 'parse-tests'
frames_out_dir = root / 'build' / 'parse-frames'
cc4_source_zip = companion / 'firmware' / 'nanod-control-center-1.0.0-cc4-source.zip'

sys.path.insert(0, str(companion))
from control_center import presentation  # noqa: E402  (read-only: constants and pure helpers)
from control_center import device  # noqa: E402  (read-only: alive_parse, the host's reading of ALIVE.md section 3)

TEXT_FIELDS = ('mode', 'target', 'value', 'detail', 'status', 'title', 'subtitle', 'counter',
               'volumeCaption', 'heading', 'meta', 'artKey', 'iconKey')   # iconKey: 1.0.0-cc5.3
LEGACY_LAYOUT = presentation.LEGACY_LAYOUT
ALIVE_FIELDS = ('playing', 'feedbackSkip', 'clock', 'progress', 'ledDrive', 'ledDither')
V5_FIELDS = ('ringNow', 'ringCard', 'lit', 'color', 'icon', 'feedbackKind', 'feedbackMoment', 'feedbackSide',
             'feedbackColor', 'reducedMotion', 'ledPink', 'ledVolFull')


def header_state(header: Path) -> tuple:
    """(v5 tones, CCFooterInk::dim) of a cc_presentation.h: whether cc_button_tone() derives the
    PRESENTATION_V5.md 5.2 tones (it mentions CC_TONE_ON), and its dim footer ink."""
    text = header.read_text(encoding='utf-8')
    start = text.find('inline uint8_t cc_button_tone(')
    body = text[start:text.find('\n}\n', start)] if start >= 0 else ''
    dim = re.search(r'namespace CCFooterInk \{[^}]*?\bdim = (0x[0-9A-Fa-f]+)', text, re.S)
    return 'CC_TONE_ON' in body, int(dim.group(1), 16) if dim else None


HEADER_V5_TONES, HEADER_DIM = header_state(firmware / 'src' / 'cc_presentation.h')


def button_expectation(slot: int, button: dict, layout: str, v5_tones: bool, dim_ink) -> tuple:
    """(tone, ink) the header derives for `button` (effective icon: the wire token or the label map).

    With the v5 tones every ink, dim included, is presentation.button_ink_v5's (PRESENTATION_V5.md
    5.2: dim #5A5A5A), so the C++ cc_button_ink() is compared with Python, never with the header
    itself. Only a header that still derives the V4 tones (the cc5.3 parser, or cc5.4 before the LCD
    package lands the 5.2 rows) is held to its own CCFooterInk::dim (V4's #4A4A4A, PENDING)."""
    icon, enabled = effective_icon(button), button['enabled']
    if v5_tones:
        tone = presentation.button_tone_v5(slot, icon, enabled, button.get('lit'), layout)
        ink = presentation.button_ink_v5(slot, icon, enabled, button.get('lit'), button.get('color', 0), layout)
    else:
        tone = presentation.button_tone(slot, icon, enabled)
        ink = presentation.FOOTER_INK.get(tone, 0)
        if tone == 'dim' and dim_ink is not None:
            ink = dim_ink   # V4 tones only: PENDING (reported once in main)
    return tone, ink


def dim_ink_verdict(v5_tones: bool, dim_ink) -> str:
    """'ok', 'pending' (V4 tones, the dim ink not moved yet) or 'fail' (v5 tones with a dim ink other
    than presentation.FOOTER_INK['dim'], or none found)."""
    if dim_ink == presentation.FOOTER_INK['dim']:
        return 'ok'
    return 'fail' if v5_tones else 'pending'


def self_test() -> None:
    """The gate's own rules, on synthetic headers (WP3-REV-3): a v5-tone header is never checked
    against its own dim ink, and a wrong one fails."""
    dim_button, v5_dim = {'label': 'X', 'enabled': False, 'icon': 'play'}, presentation.FOOTER_INK['dim']
    for wrong in (0x4A4A4A, v5_dim + 1):
        assert button_expectation(0, dim_button, 'recent', True, wrong) == ('dim', v5_dim), wrong
        assert button_expectation(0, dim_button, 'recent', False, wrong) == ('dim', wrong), wrong
        assert dim_ink_verdict(True, wrong) == 'fail' and dim_ink_verdict(False, wrong) == 'pending', wrong
    assert dim_ink_verdict(True, None) == 'fail'
    assert dim_ink_verdict(True, v5_dim) == 'ok' and dim_ink_verdict(False, v5_dim) == 'ok'
    liked = {'label': 'Like', 'enabled': True, 'icon': 'heart', 'lit': 'on'}
    assert button_expectation(2, liked, 'upnext', True, 0x4A4A4A) == ('liked', 0xA3244A)   # 5.2 row 4 [r2.2]


def v5_expected(frame: dict) -> dict:
    """PRESENTATION_V5.md 15.1 `stored` for a frame that is valid and in scope as sent (a host output):
    every v5 value as sent, the defaults when absent (an independent reading of section 3.6)."""
    ring, feedback = frame['ring'], frame.get('feedback')
    return {
        'ringNow': ring.get('now', -1), 'ringCard': ring.get('card', False),
        'lit': [button.get('lit') for button in frame['buttons']],
        'color': [button.get('color', 0) for button in frame['buttons']],
        'icon': [button.get('icon', '') for button in frame['buttons']],
        'feedbackKind': feedback['kind'] if feedback else None,
        'feedbackMoment': feedback.get('moment') if feedback else None,
        'feedbackSide': feedback.get('side', 0) if feedback else 0,
        'feedbackColor': feedback.get('color', 0) if feedback else 0,
        'reducedMotion': frame.get('reducedMotion'), 'ledPink': frame.get('ledPink'),
        'ledVolFull': frame.get('ledVolFull'),
    }


def controller_button_icons() -> dict:
    """The legacy label -> icon table, read from source (importing would pull in the runtime):
    controller.BUTTON_ICONS while the controller still defines it (v6 and earlier), else
    lcd_preview.LEGACY_ICON, the mirror of the firmware's cc_legacy_icon() table (the v7 controller
    always sends icons and no longer carries the table)."""
    for module, name in (('controller.py', 'BUTTON_ICONS'), ('lcd_preview.py', 'LEGACY_ICON')):
        tree = ast.parse((companion / 'control_center' / module).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
                return ast.literal_eval(node.value)
    raise SystemExit('legacy icon table not found (controller.BUTTON_ICONS / lcd_preview.LEGACY_ICON)')


BUTTON_ICONS = controller_button_icons()


def wire(frame) -> bytes:
    return json.dumps({'frame': frame}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def effective_icon(button: dict) -> str:
    return button['icon'] if 'icon' in button else BUTTON_ICONS.get(button['label'], '')


def expected_text(frame: dict) -> dict:
    text = {name: frame.get(name, '') for name in TEXT_FIELDS}
    for slot, button in enumerate(frame['buttons']):
        text[f'label{slot}'] = button['label']
    return text


def alive_expected(frame: dict) -> dict:
    """ALIVE.md section 3 as stored from a frame that is valid as sent (an independent reading:
    playing only on the Home layouts, skip only with kind ok, latched fields as sent, None = absent)."""
    layout = frame['layout'] if 'layout' in frame else LEGACY_LAYOUT.get(frame['mode'], 'nowPlaying')
    feedback = frame.get('feedback') or {}
    playing = frame.get('playing')
    progress = frame.get('progress')
    return {'playing': -1 if playing is None or layout not in presentation.ALIVE_PLAYING_LAYOUTS else int(playing),
            'feedbackSkip': feedback.get('skip', 0) if feedback.get('kind') == 'ok' else 0,
            'clock': frame.get('clock'),
            'progress': None if progress is None else {'pos': progress['pos'], 'dur': progress['dur']},
            'ledDrive': frame.get('ledDrive'), 'ledDither': frame.get('ledDither')}


def expected_fields(frame: dict, v4_parser: bool = False) -> dict:
    """Contract v4 defaults and derivations for a frame that is valid as sent (plus, for the cc5.4
    parser, the ALIVE.md section 3 and PRESENTATION_V5.md 15.1 values; `v4_parser`: the cc5.3 one)."""
    ring = frame['ring']
    index, count = ring['index'], ring['count']
    derived = presentation.window_first(index, count)
    relative = 'first' in ring or derived == 0
    fields = {
        'activity': frame.get('activity', 'idle'),
        'layout': frame['layout'] if 'layout' in frame else LEGACY_LAYOUT.get(frame['mode'], 'nowPlaying'),
        'restLayout': frame.get('restLayout', 'nowPlaying'),
        'titleTone': frame.get('titleTone', 'ink'),
        'metaTone': frame.get('metaTone', 'meta'),
        'statusTone': frame.get('statusTone', 'meta'),
        'ledStyle': frame.get('ledStyle', 'white'),
        'page': frame.get('page', 0),
        'artDim': frame.get('artDim', False),
        'confirmedVolume': frame.get('confirmedVolume', ring['value']),
        'feedback': frame.get('feedback'),
        'ringStyle': ring['style'], 'ringValue': ring['value'], 'ringIndex': index, 'ringCount': count,
        'ringFirst': ring.get('first', derived),
        'ringColors': ring.get('colors', []) if relative else [],
        'ringUnavailable': ring.get('unavailable', 0) if relative else 0,
        'ringMoreIndex': ring.get('moreIndex', -1),
        'ringExternal': ring.get('external', False),
    }
    v5_tones, dim_ink = (CC53_TONES, CC53_DIM) if v4_parser else (HEADER_V5_TONES, HEADER_DIM)
    for slot, button in enumerate(frame['buttons']):
        tone, ink = button_expectation(slot, button, fields['layout'], v5_tones, dim_ink)
        fields[f'enabled{slot}'] = button['enabled']
        fields[f'icon{slot}'] = button.get('icon', '')
        fields[f'iconSent{slot}'] = 'icon' in button
        fields[f'tone{slot}'] = tone
        fields[f'ink{slot}'] = ink
    if not v4_parser:
        fields.update(alive_expected(frame))   # 1.0.0-cc5.4: the defaults unless the frame carries them
        fields.update(v5_expected(frame))      # presentation 5: the defaults unless the frame carries them
    return fields


def entry(name, kind, line: bytes, accept, text=None, fields=None):
    return {'name': name, 'kind': kind, 'line_b64': base64.b64encode(line).decode('ascii'),
            'accept': accept, 'text': text or {}, 'fields': fields or {}}


def fixture_entries(fixtures) -> list:
    entries = []
    for case in fixtures['cases']:
        name, expect = case['name'], case['expect']
        output = expect.get('output')
        if expect['accept']:
            # rules.firmwareOutput: the host output is always a valid v4/v2 (or v5) frame.
            entries.append(entry(f'{name}/output', 'firmwareOutput', wire(output), True,
                                 expected_text(output), expected_fields(output)))
        if case['rawParity']:
            # rules.firmwareRaw: same decision; the text of every field present in the output.
            text = fields = None
            if expect['accept']:
                text = {k: v for k, v in expected_text(output).items()
                        if k.startswith('label') or k in output}
                fields = expected_fields(output)
                for home_only in ('confirmedVolume', 'restLayout'):
                    if home_only not in output:
                        del fields[home_only]  # slimmed outside Home; the raw input may carry any valid value
                if not (output.get('ledStyle') == 'color' and output['ring']['style'] == 'selection'):
                    del fields['ringColors']  # slimmed unless colour mode + selection
                if 'alive' in case or 'v5' in case:
                    for alive_field in ALIVE_FIELDS:
                        del fields[alive_field]  # the host gates them; rules.aliveRaw/v5Raw check the raw ones
                del fields['color']  # the host slims button colours; a raw input may carry any valid one
                if 'v5' in case:
                    for v5_field in V5_FIELDS:
                        fields.pop(v5_field, None)  # rules.v5Raw below checks the raw ones
            entries.append(entry(f'{name}/raw', 'firmwareRaw', wire(case['input']), expect['accept'], text, fields))
        if 'alive' in case:
            # rules.aliveRaw: what a 1.0.0-cc5.4 parser does with the input itself.
            verdict = case['alive']
            entries.append(entry(f'{name}/alive', 'aliveRaw', wire(case['input']), verdict['accept'], None,
                                 verdict.get('stored')))
        if 'v5' in case:
            # rules.v5Raw: what a cc5.4 parser does with the input itself (PRESENTATION_V5.md 15.1).
            verdict = case['v5']
            entries.append(entry(f'{name}/v5', 'v5Raw', wire(case['input']), verdict['accept'], None,
                                 verdict.get('stored')))
    return entries


def downgrade_entries(fixtures) -> list:
    """rules.downgrade: every presentation < 5 host output, for the cc5.3 (V4) parser."""
    entries = []
    for case in fixtures['cases']:
        output = case['expect'].get('output')
        if case['expect']['accept'] and case['capabilities'].get('presentation', 0) < presentation.PRESENTATION_V5:
            entries.append(entry(f"{case['name']}/downgrade", 'downgradeV4', wire(output), True,
                                 expected_text(output), expected_fields(output, v4_parser=True)))
    return entries


def check_python_v5(fixtures) -> int:
    """device.v5_parse (the host's reading of the cc5.4 parser) against rules.v5Raw."""
    checked = 0
    for case in fixtures['cases']:
        verdict = case['v5']
        stored, invalid = device.v5_parse(copy.deepcopy(case['input']))
        if (not invalid) != verdict['accept'] or (verdict['accept'] and stored != verdict['stored']):
            raise SystemExit(f"FAIL {case['name']}: device.v5_parse gives {stored} invalid {invalid}, "
                             f"the fixture says {verdict}")
        checked += 1
    return checked


def check_python_alive(fixtures) -> int:
    """device.alive_parse (the host's reading of ALIVE.md section 3) against rules.aliveRaw."""
    checked = 0
    for case in fixtures['cases']:
        verdict = case['alive']
        stored, invalid = device.alive_parse(copy.deepcopy(case['input']))
        if (not invalid) != verdict['accept'] or (verdict['accept'] and stored != verdict['stored']):
            raise SystemExit(f"FAIL {case['name']}: device.alive_parse gives {stored} invalid {invalid}, "
                             f"the fixture says {verdict}")
        checked += 1
    return checked


def legacy_frame() -> dict:
    """Recorded v2-companion Recent frame (cc4 era), before `layout` existed on the wire."""
    return {"id": 9, "mode": "RECENTLY ADDED", "target": "Den", "value": "Colombina", "detail": "Mari Froes",
            "title": "Colombina", "subtitle": "Mari Froes", "counter": "1 / 3", "activity": "idle", "status": "",
            "buttons": [{"label": "Back", "enabled": True, "color": 15789799},
                        {"label": "Home", "enabled": True, "color": 15789799},
                        {"label": "Win", "enabled": True, "color": 15789799},
                        {"label": "Play", "enabled": True, "color": 6736273}],
            "ring": {"style": "selection", "value": 0, "index": 0, "count": 3, "available": [True, True, True]}}


def extra_entries(fixtures) -> list:
    entries = []

    def add(name, frame, accept, text=None, fields=None, raw: bytes | None = None):
        entries.append(entry(name, 'extra', raw if raw is not None else wire(frame), accept, text, fields))

    def full(frame):
        return expected_text(frame), expected_fields(frame)

    # 1. Legacy (v2 companion, no layout): layout from mode, white LEDs, tones from labels.
    legacy = legacy_frame()
    text, fields = full(legacy)
    assert fields['layout'] == 'recent' and fields['tone3'] == 'go' and fields['tone0'] == 'nav'
    add('legacy-v2-recent-no-layout-no-icons', legacy, True, text, fields)

    recorded = {c['name']: c for c in fixtures['cases']}
    for source in ('v2-home-now-playing-to-cc5', 'v2-windows-to-cc5', 'v2-tracks-neutral-to-cc5',
                   'v2-recent-item-to-cc5', 'v2-home-idle-paused-to-cc5'):
        frame = copy.deepcopy(recorded[source]['input'])
        del frame['layout']
        text, fields = full(frame)
        add(f'legacy-{source}-no-layout', frame, True, text, fields)
        stripped = copy.deepcopy(frame)
        for button in stripped['buttons']:
            button.pop('icon', None)
        text, fields = full(stripped)
        add(f'legacy-{source}-no-layout-no-icons', stripped, True, text, fields)

    # 2. 45 windows, legacy (no layout, no first, no icons): first derived as clamp(30-9, 0, 25) = 21.
    windows = copy.deepcopy(recorded['v2-windows-long-to-cc5']['input'])
    del windows['layout']
    for button in windows['buttons']:
        button.pop('icon', None)
    text, fields = full(windows)
    assert fields['layout'] == 'windows' and fields['ringFirst'] == 21
    assert [fields[f'tone{i}'] for i in range(4)] == ['stop', 'nav', 'nav', 'go']
    add('legacy-45-windows-no-first', windows, True, text, fields)
    for index, first in ((0, 0), (9, 0), (10, 1), (34, 25), (44, 25)):
        frame = copy.deepcopy(windows)
        frame['ring']['index'] = index
        text, fields = full(frame)
        assert fields['ringFirst'] == first
        add(f'legacy-45-windows-index-{index}', frame, True, text, fields)

    # 3. Legacy label -> icon table (controller.BUTTON_ICONS) and tone rule 5.9, every slot.
    base = legacy_frame()
    for label in sorted(BUTTON_ICONS) + ['Custom', '']:
        for enabled in (True, False):
            frame = copy.deepcopy(base)
            frame['buttons'] = [{'label': label, 'enabled': enabled} for _ in range(4)]
            fields = {k: v for k, v in expected_fields(frame).items() if k[:-1] in ('tone', 'ink', 'icon', 'iconSent')}
            add(f'legacy-label-{label or "empty"}-{"on" if enabled else "off"}', frame, True, None, fields)
    # A v4 button that sends icon "" is tone none even with a mapped label.
    frame = copy.deepcopy(base)
    frame['buttons'][3]['icon'] = ''
    add('v4-empty-icon-no-label-fallback', frame, True, None,
        {'tone3': 'none', 'ink3': 0, 'icon3': '', 'iconSent3': True, 'tone0': 'nav'})

    # 4. Byte-level text rules (not expressible as JSON fixtures).
    sample = copy.deepcopy(recorded['v4-home-now-playing']['input'])
    line = wire(sample)

    def replaced(field_value: bytes) -> bytes:
        marker = json.dumps(sample['title'], ensure_ascii=False).encode('utf-8')
        assert line.count(marker) >= 1
        return line.replace(b'"title":' + marker, b'"title":' + field_value, 1)

    add('text-invalid-utf8-continuation', None, False, raw=replaced(b'"\xc3\x28"'))
    add('text-overlong-encoding', None, False, raw=replaced(b'"\xc0\xaf"'))
    add('text-encoded-surrogate', None, False, raw=replaced(b'"\xed\xa0\x80"'))
    add('text-above-u10ffff', None, False, raw=replaced(b'"\xf4\x90\x80\x80"'))
    add('text-truncated-sequence', None, False, raw=replaced(b'"ab\xe2\x80"'))
    add('text-embedded-nul', None, False, raw=replaced(b'"a\\u0000b"'))
    add('text-raw-tab', None, False, raw=replaced(b'"a\tb"'))
    add('text-escaped-newline', None, False, raw=replaced(b'"a\\nb"'))
    add('text-del-kept', None, True, {'title': 'a\x7fb'}, raw=replaced(b'"a\x7fb"'))
    add('text-c1-kept', None, True, {'title': 'a\u0085b'}, raw=replaced('"a\u0085b"'.encode('utf-8')))
    emoji = 'x' * 94 + '\U0001F3B5'  # 98 bytes into 96: the 4-byte code point is dropped whole
    add('text-4byte-at-capacity', None, True, {'title': 'x' * 94}, raw=replaced(json.dumps(emoji, ensure_ascii=False).encode('utf-8')))
    fits = 'x' * 92 + '\U0001F3B5'  # exactly 96 bytes: kept
    add('text-4byte-exact-capacity', None, True, {'title': fits}, raw=replaced(json.dumps(fits, ensure_ascii=False).encode('utf-8')))
    surrogate_pair = 'x' * 92 + '\\ud83c\\udfb5'  # the same code point as a JSON surrogate pair
    add('text-escaped-surrogate-pair', None, True, {'title': fits}, raw=replaced(f'"{surrogate_pair}"'.encode('ascii')))

    # 5. Strict optional fields and ring rules (contract section 4; the host strips these).
    def variant(name, mutate, accept, fields=None):
        frame = copy.deepcopy(sample)
        mutate(frame)
        add(name, frame, accept, None, fields)

    def ring_list(count, index, **extra):
        def mutate(frame):
            frame['layout'] = 'recent'
            frame['ring'] = {'style': 'selection', 'value': 0, 'index': index, 'count': count, **extra}
        return mutate

    variant('frame-id-absent', lambda f: f.pop('id'), True)
    variant('unknown-fields-ignored', lambda f: f.update({'windowIconKey': 'x', 'future': {'a': 1}}), True)
    variant('ring-v2-available-ignored', lambda f: f['ring'].update({'available': [True]}), True)
    variant('optional-null-rejected', lambda f: f.update({'heading': None}), False)
    variant('art-key-65-rejected', lambda f: f.update({'artKey': 'k' * 65}), False)
    variant('art-key-64-kept', lambda f: f.update({'artKey': 'k' * 64}), True)
    variant('present-first-small-count-rejected', ring_list(11, 2, first=1), False)
    variant('present-first-after-index-rejected', ring_list(45, 30, first=31), False)
    variant('present-first-window-miss-rejected', ring_list(45, 30, first=10), False)
    variant('present-first-valid', ring_list(45, 30, first=20, colors=[1] * 20, unavailable=(1 << 20) - 1), True,
            {'ringFirst': 20, 'ringColors': [1] * 20, 'ringUnavailable': (1 << 20) - 1})
    variant('colours-over-window-rejected', ring_list(11, 2, colors=[1] * 12), False)
    variant('colours-over-window-with-first-rejected', ring_list(45, 40, first=25, colors=[1] * 21), False)
    variant('mask-beyond-window-rejected', ring_list(11, 2, unavailable=1 << 11), False)
    variant('mask-at-window-kept', ring_list(11, 2, unavailable=(1 << 11) - 1), True, {'ringUnavailable': 2047})
    variant('absent-first-derived-zero-validates-colours', ring_list(45, 5, colors=[0x1000000]), False)
    variant('absent-first-derived-nonzero-ignores-colours', ring_list(45, 30, colors=['x'], unavailable=-1), True,
            {'ringFirst': 21, 'ringColors': [], 'ringUnavailable': 0})
    variant('more-index-past-count-rejected', ring_list(11, 2, moreIndex=11), False)
    variant('more-index-last-kept', ring_list(11, 2, moreIndex=10), True, {'ringMoreIndex': 10})
    variant('feedback-extra-keys-ignored', lambda f: f.update({'feedback': {'kind': 'err', 'seq': 5, 'x': 1}}), True,
            {'feedback': {'kind': 'err', 'seq': 5}})
    variant('button-color-optional', lambda f: [b.pop('color', None) for b in f['buttons']], True)

    # 6. iconKey (1.0.0-cc5.3, ARTWORK2.md section 6): [A-Za-z0-9_-]{0,24}, kept on the windows
    # layout only. A malformed value, or one on another layout, is stripped ("") and never rejects
    # the frame (the host strips it too: identical accept/strip results).
    windows = copy.deepcopy(recorded['v4-windows-window-rule']['input'])
    assert windows['layout'] == 'windows'
    for name, value, stored in (('icon-key-16-kept', 'a1B2c3D4e5F6g7H8', 'a1B2c3D4e5F6g7H8'),
                                ('icon-key-24-kept', 'k' * 24, 'k' * 24),
                                ('icon-key-dash-underscore-kept', '-_x', '-_x'),
                                ('icon-key-empty-kept', '', ''),
                                ('icon-key-25-stripped', 'k' * 25, ''),
                                ('icon-key-slash-stripped', 'bad/key', ''),
                                ('icon-key-space-stripped', 'a b', ''),
                                ('icon-key-non-ascii-stripped', 'caf\u00e9', ''),
                                ('icon-key-embedded-nul-stripped', 'a\x00b', ''),
                                ('icon-key-number-stripped', 5, ''),
                                ('icon-key-null-stripped', None, ''),
                                ('icon-key-list-stripped', ['k'], '')):
        frame = copy.deepcopy(windows)
        frame['iconKey'] = value
        add(name, frame, True, {'iconKey': stored})
    for layout in ('nowPlaying', 'recent', 'tracks', 'notice'):
        frame = copy.deepcopy(sample)
        frame['layout'] = layout
        frame['iconKey'] = 'k1'
        add(f'icon-key-{layout}-stripped', frame, True, {'iconKey': ''})
    legacy = copy.deepcopy(recorded['v2-windows-to-cc5']['input'])
    del legacy['layout']                      # mode WINDOWS: the derived layout is windows
    legacy['iconKey'] = 'k2'
    add('icon-key-legacy-windows-kept', legacy, True, {'iconKey': 'k2'}, {'layout': 'windows'})

    # 7. ALIVE.md section 3 number spellings a JSON fixture cannot hold, checked against BOTH
    # parsers: Python decodes the same bytes and device.alive_parse must agree.
    home_line = wire(copy.deepcopy(recorded['v4-home-now-playing']['input']))
    assert home_line.endswith(b'}}')

    def alive_raw(name, member: bytes, accept, fields=None):
        line = home_line[:-2] + b',' + member + b'}}'
        stored, invalid = device.alive_parse(json.loads(line)['frame'])
        if (not invalid) != accept or (accept and any(stored[k] != v for k, v in (fields or {}).items())):
            raise SystemExit(f'FAIL {name}: device.alive_parse gives {stored} invalid {invalid}')
        add(name, None, accept, None, fields, raw=line)

    alive_raw('alive-clock-minus-zero-kept', b'"clock":-0', True, {'clock': 0})
    alive_raw('alive-clock-exponent-rejected', b'"clock":1e3', False)
    alive_raw('alive-clock-fraction-rejected', b'"clock":1439.0', False)
    alive_raw('alive-clock-overflow-rejected', b'"clock":99999999999999999999', False)
    alive_raw('alive-drive-exponent-rejected', b'"ledDrive":2E2', False)
    alive_raw('alive-progress-exponent-rejected', b'"progress":{"pos":1e3,"dur":2000}', False)
    alive_raw('alive-progress-minus-zero-kept', b'"progress":{"pos":-0,"dur":0}', True,
              {'progress': {'pos': 0, 'dur': 0}})
    alive_raw('alive-skip-exponent-rejected', b'"feedback":{"kind":"ok","seq":3,"skip":1e0}', False)
    alive_raw('alive-skip-minus-one-kept', b'"feedback":{"kind":"ok","seq":3,"skip":-1}', True,
              {'feedbackSkip': -1})

    # 8. PRESENTATION_V5.md number spellings a JSON fixture cannot hold, checked against BOTH parsers.
    v5_cases = {c['name']: c for c in json.loads(v5_fixtures_path.read_text(encoding='utf-8'))['cases']}
    upnext_line = wire(copy.deepcopy(v5_cases['v5-upnext-p5']['input']))
    home_v5_line = wire(copy.deepcopy(v5_cases['v5-home-p5']['input']))
    windows_line = wire(copy.deepcopy(v5_cases['moment-snap-side-right']['input']))

    def v5_raw(name, line: bytes, old: bytes, new: bytes, accept, fields=None):
        assert line.count(old) == 1, (name, old)
        line = line.replace(old, new)
        stored, invalid = device.v5_parse(json.loads(line)['frame'])
        if (not invalid) != accept or (accept and any(stored[k] != v for k, v in (fields or {}).items())):
            raise SystemExit(f'FAIL {name}: device.v5_parse gives {stored} invalid {invalid}')
        add(name, None, accept, None, fields, raw=line)

    v5_raw('v5-now-minus-zero-kept', upnext_line, b'"now":4', b'"now":-0', True, {'ringNow': 0})
    v5_raw('v5-now-exponent-rejected', upnext_line, b'"now":4', b'"now":4e0', False)
    v5_raw('v5-now-fraction-rejected', upnext_line, b'"now":4', b'"now":4.0', False)
    v5_raw('v5-now-overflow-rejected', upnext_line, b'"now":4', b'"now":99999999999999999999', False)
    v5_raw('v5-now-int32-overflow-rejected', upnext_line, b'"now":4', b'"now":4294967300', False)
    v5_raw('v5-led-pink-exponent-rejected', home_v5_line, b'"id":77', b'"id":77,"ledPink":1e3', False)
    v5_raw('v5-led-pink-minus-zero-kept', home_v5_line, b'"id":77', b'"id":77,"ledPink":-0', True, {'ledPink': 0})
    v5_raw('v5-side-fraction-rejected', windows_line, b'"side":1', b'"side":1.0', False)
    v5_raw('v5-side-exponent-rejected', windows_line, b'"side":1', b'"side":1e0', False)
    v5_raw('v5-moment-embedded-nul-rejected', windows_line, b'"moment":"snap"', b'"moment":"snap\\u0000"', False)
    v5_raw('v5-lit-embedded-nul-rejected', upnext_line, b'"lit":"off"', b'"lit":"off\\u0000"', False)
    return entries


MSVC = Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207')
WINDOWS_SDK = Path('C:/Program Files (x86)/Windows Kits/10')


def compile_runner(build: Path, defines=(), includes=(), src: Path | None = None) -> Path:
    """Build parse_tests.exe in `build` (MSVC /W4 /WX) against the parser in `src` (default the
    firmware's src/) and return its path."""
    src = src or firmware / 'src'
    sdk_include = sorted((WINDOWS_SDK / 'Include').iterdir(), key=lambda p: p.name)[-1]
    sdk_lib = WINDOWS_SDK / 'Lib' / sdk_include.name
    env = {key.upper(): value for key, value in os.environ.items()}
    env['INCLUDE'] = ';'.join(str(path) for path in (
        MSVC / 'include', sdk_include / 'ucrt', sdk_include / 'shared', sdk_include / 'um'))
    env['LIB'] = ';'.join(str(path) for path in (
        MSVC / 'lib/x64', sdk_lib / 'ucrt/x64', sdk_lib / 'um/x64'))
    exe = build / 'parse_tests.exe'
    subprocess.run([
        str(MSVC / 'bin/Hostx64/x64/cl.exe'), '/nologo', '/EHsc', '/std:c++14', '/W4', '/WX', '/O2',
        '/D_CRT_SECURE_NO_WARNINGS', *(f'/D{name}' for name in defines),
        f'/I{src}', *(f'/I{path}' for path in includes),
        # ArduinoJson is third-party: its own warnings are not ours (the gnu++11 gate parses it too).
        f'/external:I{arduinojson}', '/external:W0',
        str(root / 'parse_tests.cpp'), str(src / 'cc_frame_parse.cpp'),
        f'/Fo{build}\\', f'/Fe{exe}',
    ], cwd=build, env=env, check=True)
    return exe


def compile_and_run(cases: Path) -> None:
    exe = compile_runner(out_dir)
    subprocess.run([str(exe), str(cases)], check=True)


def cc53_parser_source(build: Path) -> Path:
    """The cc5.3 (presentation 4) parser, header and presentation header, extracted verbatim from the
    cc5.3 source snapshot into build/cc53-src (rules.downgrade)."""
    target = build / 'cc53-src'
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cc53_source_zip) as archive:
        for name in ('cc_frame_parse.cpp', 'cc_frame_parse.h', 'cc_presentation.h'):
            (target / name).write_bytes(archive.read(f'NanoD_RatchetH1/src/{name}'))
    return target


CC53_SRC = cc53_parser_source(out_dir) if cc53_source_zip.is_file() else None
CC53_TONES, CC53_DIM = header_state(CC53_SRC / 'cc_presentation.h') if CC53_SRC else (False, None)


# ---------------------------------------------------------------------------
# --frames: a recorded companion session.

def cc4_parser_excerpt() -> str | None:
    """The installed cc4 frame parser, verbatim, wrapped in `namespace cc4`.

    Taken from the cc4 source snapshot (firmware/…-cc4-source.zip): the
    CCButton/CCActivity/CCFrame definitions of src/cc_presentation.h and
    text_field()/uint_field()/parse_frame() of src/control_center.cpp. None when
    the snapshot or either excerpt boundary is missing.
    """
    if not cc4_source_zip.is_file():
        return None
    try:
        with zipfile.ZipFile(cc4_source_zip) as archive:
            header = archive.read('NanoD_RatchetH1/src/cc_presentation.h').decode('utf-8').replace('\r\n', '\n')
            source = archive.read('NanoD_RatchetH1/src/control_center.cpp').decode('utf-8').replace('\r\n', '\n')
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError):
        return None
    types = re.search(r'^struct CCButton \{.*?^struct CCFrame \{.*?^\};\n', header, re.S | re.M)
    start = source.find('bool text_field(JsonVariant value')
    end = source.find('void release_locked(')
    if (not types or source.count('bool text_field(') != 1 or source.count('bool parse_frame(') != 1
            or not 0 <= start < source.find('bool parse_frame(') < end):
        return None
    return ('// Generated by parse_tests.py --frames: verbatim excerpts of the installed cc4\n'
            f'// firmware ({cc4_source_zip.name}: src/cc_presentation.h, src/control_center.cpp).\n'
            'namespace cc4 {\n' + types.group(0) + '\n' + source[start:end].rstrip() + '\n} // namespace cc4\n')


def capture_entries(capture: Path) -> tuple[list, dict]:
    """Runner entries for every frame/control line of a capture_session_frames.py JSONL."""
    entries, counts = [], {}
    for number, text in enumerate(capture.read_text(encoding='utf-8').splitlines(), 1):
        if not text.strip():
            continue
        record = json.loads(text)
        wire = record.get('kind')
        if wire not in ('frame', 'control'):
            continue
        line = record['line']
        message = json.loads(line)
        frame = message['frame'] if wire == 'frame' else message['control']['frame']
        session = record.get('session', 'session')
        legacy = record.get('presentation', presentation.PRESENTATION_V4) < presentation.PRESENTATION_V4
        name = f"{session}#{record.get('n', number)} {record.get('step', '')} ({wire})"
        entries.append({'name': name, 'kind': f'{session}-{wire}', 'wire': wire,
                        'line_b64': base64.b64encode(line.encode('utf-8')).decode('ascii'),
                        'accept': True, 'cc4': legacy,
                        'text': expected_text(frame), 'fields': expected_fields(frame)})
        counts[f'{session}-{wire}'] = counts.get(f'{session}-{wire}', 0) + 1
    return entries, counts


def run_frames(capture: Path, build: Path) -> int:
    entries, counts = capture_entries(capture)
    if not entries:
        print(f'FAIL: no frame or control lines in {capture}')
        return 1
    build.mkdir(parents=True, exist_ok=True)
    cases = build / 'capture_cases.jsonl'
    with cases.open('w', encoding='utf-8', newline='\n') as handle:
        for item in entries:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
    excerpt = cc4_parser_excerpt()
    defines = ()
    if excerpt is not None:
        (build / 'cc4_parser.inc').write_text(excerpt, encoding='utf-8', newline='\n')
        defines = ('CC4_PARSER',)
    print('parse_tests --frames: ' + ', '.join(f'{kind} {count}' for kind, count in counts.items())
          + f"; cc4 parser {'excerpted from ' + cc4_source_zip.name if excerpt else 'unavailable'}", flush=True)
    exe = compile_runner(build, defines, (build,) if excerpt else ())
    return subprocess.run([str(exe), '--frames', str(cases)]).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--frames', type=Path, help='replay a capture_session_frames.py JSONL capture')
    parser.add_argument('--out', type=Path, help='build directory for --frames (default build/parse-frames)')
    args = parser.parse_args()
    if args.frames is not None:
        return run_frames(args.frames.resolve(), (args.out or frames_out_dir).resolve())
    if args.out is not None:
        parser.error('--out applies to --frames only')
    # Fail fast if the parser (or another shared unit) is not valid gnu++11.
    subprocess.run([sys.executable, str(root / 'cpp11_gate.py')], check=True)
    fixtures = json.loads(fixtures_path.read_text(encoding='utf-8'))
    alive_fixtures = json.loads(alive_fixtures_path.read_text(encoding='utf-8'))
    v5_fixtures = json.loads(v5_fixtures_path.read_text(encoding='utf-8'))
    python_alive = check_python_alive(alive_fixtures)
    print(f'parse_tests: device.alive_parse matches rules.aliveRaw in all {python_alive} alive case(s)', flush=True)
    python_v5 = check_python_v5(v5_fixtures)
    print(f'parse_tests: device.v5_parse matches rules.v5Raw in all {python_v5} v5 case(s)', flush=True)
    print(f"parse_tests: cc_presentation.h tones {'v5 (5.2)' if HEADER_V5_TONES else 'V4 (5.9)'}", flush=True)
    self_test()
    verdict = dim_ink_verdict(HEADER_V5_TONES, HEADER_DIM)
    header_dim = 'none found' if HEADER_DIM is None else f'0x{HEADER_DIM:06X}'
    if verdict == 'fail':
        print(f"FAIL: cc_presentation.h derives the v5 tones but CCFooterInk::dim is {header_dim}; "
              f"PRESENTATION_V5 3.6 / 5.2 row 2 and presentation.FOOTER_INK: "
              f"0x{presentation.FOOTER_INK['dim']:06X}", flush=True)
        return 1
    if verdict == 'pending':
        print(f"parse_tests: PENDING (LCD package) cc_presentation.h CCFooterInk::dim {header_dim}, "
              f"PRESENTATION_V5 3.6 and presentation.FOOTER_INK: 0x{presentation.FOOTER_INK['dim']:06X}; "
              f"checked against the header's value only while cc_button_tone() derives the V4 tones", flush=True)
    entries = (fixture_entries(fixtures) + extra_entries(fixtures) + fixture_entries(alive_fixtures)
               + fixture_entries(v5_fixtures))
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = out_dir / 'parse_cases.jsonl'
    with cases.open('w', encoding='utf-8', newline='\n') as handle:
        for item in entries:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
    counts = {}
    for item in entries:
        counts[item['kind']] = counts.get(item['kind'], 0) + 1
    print(f"parse_tests: {len(fixtures['cases'])} + {len(alive_fixtures['cases'])} + {len(v5_fixtures['cases'])} "
          "fixture case(s) -> " + ', '.join(f'{kind} {count}' for kind, count in counts.items()), flush=True)
    compile_and_run(cases)
    # rules.downgrade: the presentation-4 outputs against the cc5.3 parser.
    if CC53_SRC is None:
        print(f'FAIL: {cc53_source_zip.name} not found; rules.downgrade needs the cc5.3 parser')
        return 1
    downgrade = downgrade_entries(v5_fixtures)
    v4_build = out_dir / 'cc53'
    v4_build.mkdir(parents=True, exist_ok=True)
    v4_cases = v4_build / 'downgrade_cases.jsonl'
    with v4_cases.open('w', encoding='utf-8', newline='\n') as handle:
        for item in downgrade:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f'parse_tests: rules.downgrade -> {len(downgrade)} presentation-4 output(s) for the cc5.3 parser '
          f'({cc53_source_zip.name})', flush=True)
    exe = compile_runner(v4_build, ('CC_V4_PARSER',), src=CC53_SRC)
    subprocess.run([str(exe), str(v4_cases)], check=True)
    print(f'PASS: parser parity over {len(entries)} case(s); cc5.3 parser accepts all {len(downgrade)} '
          'downgraded frame(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

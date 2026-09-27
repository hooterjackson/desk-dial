r"""Generate app/tests/fixtures/frames_v5.json (PRESENTATION_V5.md 15.1).

Every case is written by hand here: its input, the host verdict (accept) and hand-written
checks on the host output, the cc5.4 parser verdict (accept) and hand-written `stored` values
for the fields under test. The generator asserts all of them against device._frame() and
device.v5_parse() before it writes anything; the full `expect.output` / `v5.stored` recorded
are then what the C++ parser (parse_tests.py) and tests/test_cc_contract_v5.py (an independent
reading of the contract) check. rawParity is derived: the raw input behaves like the output
(same verdict; when accepted, no field stripped as invalid, identical text and v5 values).
`vectors.tones` is presentation.button_tone_v5 / button_ink_v5 over a grid (section 5.2, incl. the
[r2.2] derived tone `liked`).

From app:
    .venv\Scripts\python.exe -I tests\tools\make_frames_v5.py            (rewrites the fixture)
    .venv\Scripts\python.exe -I tests\tools\make_frames_v5.py --check    (exit 1 when it is stale)
Writes only the fixture. tests/test_cc_contract_v5.py imports this module (render()) to check that
the committed fixture is what the generator produces.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

COMPANION = Path(__file__).resolve().parents[2]
if str(COMPANION) not in sys.path:
    sys.path.insert(0, str(COMPANION))
from control_center import device, presentation as P  # noqa: E402

OUT = COMPANION / 'tests' / 'fixtures' / 'frames_v5.json'

ARTWORK1 = {"version": 1, "width": 120, "height": 120, "format": "RGB565_LE", "chunkBytes": 384,
            "cacheEntries": 8, "available": True, "composited": "scrim80"}
ALIVE = {"version": 1, "fps": 60, "drive": 150}
CAP_P5_ALIVE = {"controlCenter": 1, "presentation": 5, "glyphs": "latin-ext-a", "artwork": ARTWORK1,
                "artwork2": copy.deepcopy(P.ARTWORK2_CAPABILITY), "alive": ALIVE}          # cc5.4
CAP_P5 = {"controlCenter": 1, "presentation": 5, "glyphs": "latin-ext-a", "artwork": ARTWORK1,
          "artwork2": copy.deepcopy(P.ARTWORK2_CAPABILITY)}                               # defensive row
CAP_P4 = {"controlCenter": 1, "presentation": 4, "glyphs": "latin-ext-a", "artwork": ARTWORK1,
          "artwork2": copy.deepcopy(P.ARTWORK2_CAPABILITY)}                               # cc5.3
CAP_P4_ALIVE = {**CAP_P4, "alive": ALIVE}                                                 # round-2 build
CAP_P4_V1ART = {"controlCenter": 1, "presentation": 4, "glyphs": "latin-ext-a", "artwork": ARTWORK1}  # cc5.2
CAP_P2 = {"controlCenter": 1, "presentation": 2}                                          # cc4


def btn(label, icon, enabled=True, **extra):
    return {"label": label, "enabled": enabled, "icon": icon, **extra}


def base(mode, layout, buttons, ring, **fields):
    frame = {"id": 77, "mode": mode, "target": "Den", "value": "", "detail": "", "status": ""}
    if layout is not None:
        frame["layout"] = layout
    frame.update(fields)
    frame["buttons"] = buttons
    frame["ring"] = ring
    return frame


def home():
    return base("HOME", "nowPlaying", [btn("Pause", "pause"), btn("Browse", "list"), btn("Tracks", "tracks"),
                                       btn("Win", "win")],
                {"style": "level", "value": 54, "index": 0, "count": 101},
                value="54%", title="Colombina", subtitle="Mari Froes", ledStyle="color", artKey="cover_7f3a",
                confirmedVolume=54)


def recent(index=2, count=12):
    colors = [0x7A3B2C + 257 * k for k in range(min(count, 20))]
    return base("RECENTLY ADDED", "recent", [btn("Back", "back"), btn("Open", "expand"), btn("Play next", "playnext"),
                                             btn("Play", "play")],
                {"style": "selection", "value": 0, "index": index, "count": count, "colors": colors},
                heading="RECENTLY ADDED", title="Vespertine", subtitle="Björk", meta=f"{index + 1} / {count}",
                ledStyle="color", artKey="cover_a01")


def explorer(tab=0):
    return base("RECENTLY ADDED", "explorer",
                [btn("Back", "back"), btn("Recent", "clock", lit="on" if tab == 0 else "off"),
                 btn("Favourites", "playlists", lit="off" if tab == 0 else "on"), btn("Play", "play")],
                {"style": "selection", "value": 0, "index": 1, "count": 8, "colors": [0x204060] * 8},
                heading="RECENT" if tab == 0 else "FAVOURITES", page=tab, title="Homogenic",
                subtitle="Björk" if tab == 0 else "34 songs", meta="2 / 8", ledStyle="color", artKey="cover_b02")


def tracks():
    return base("TRACKS", "tracks", [btn("Back", "back"), btn("Up next", "expand"), btn("Seek", "seek"),
                                     btn("Next", "next")],
                {"style": "transport", "value": 0, "index": 2, "count": 3},
                heading="TRACKS", title="Hunter", subtitle="Next: Jóga", meta="Track 3 of 10", artKey="cover_c03")


def seek(target=74, duration=210, meta="of 3:30"):
    return base("TRACKS", "seek", [btn("Back", "back"), btn("Up next", "expand"), btn("Seek", "seek", lit="on"),
                                   btn("Next", "next", enabled=False)],
                {"style": "lap", "value": 0, "index": target, "count": duration},
                heading="SEEK", title="Hunter", meta=meta, artKey="cover_c03")


def upnext(now=4, count=12, card=False, index=5, liked=False):
    ring = {"style": "selection", "value": 0, "index": index, "count": count, "now": now,
            "colors": [0x336699 + k for k in range(min(count, 20))]}
    if card:
        ring["card"] = True
    return base("RECENTLY ADDED", "upnext",
                [btn("Back", "back"), btn("Shuffle", "shuffle", lit="off"),
                 btn("Like", "heart", **({"lit": "on"} if liked else {})), btn("Play", "play")],
                ring, heading="UP NEXT", title="All Is Full of Love", subtitle="Björk", meta=f"{index + 1} / {count}",
                ledStyle="color", artKey="cover_d04")


def windows(count=3, index=1):
    return base("WINDOWS", "windows",
                [btn("Back", "back"), btn("Left", "snapleft", lit="on", color=0x2B579A), btn("Right", "snapright"),
                 btn("Switch", "switch")],
                {"style": "selection", "value": 0, "index": index, "count": count,
                 "colors": [0x2B579A, 0x0F9D58, 0xD83B01][:count]},
                title="Quarterly report.docx", subtitle="Word", meta="Snapped left", ledStyle="color",
                iconKey="icon_word")


cases = []
seen = set()
BUDGET_REPORT = []


def raw_equivalent(inp, out):
    """rawParity: the raw input reads like the host output on a cc5.4 parser (text and v5 values),
    and the host stripped nothing as invalid."""
    s_in, bad_in = device.v5_parse(copy.deepcopy(inp))
    s_out, bad_out = device.v5_parse(copy.deepcopy(out))
    if bad_in or bad_out:
        return False
    for key in ('color',):
        s_in.pop(key), s_out.pop(key)   # the host slims button colours; firmwareRaw ignores them
    if s_in != s_out:
        return False
    for name in ('mode', 'target', 'value', 'detail', 'status', 'title', 'subtitle', 'counter', 'volumeCaption',
                 'heading', 'meta', 'artKey', 'iconKey'):
        if name in out and out[name] != inp.get(name, ''):
            return False
    return all(o['label'] == i['label'] for o, i in zip(out['buttons'], inp['buttons']))


def add(name, note, caps, inp, *, host=True, v5=True, stored=None, check=None, raw=None, strips=None):
    assert name not in seen, name
    seen.add(name)
    logged = []
    real_strip = device._strip
    device._strip = lambda field, reason, action='stripped': logged.append((field, reason, action))
    try:
        try:
            out = device._frame(copy.deepcopy(inp), caps)
            host_ok = True
        except ValueError:
            out, host_ok = None, False
    finally:
        device._strip = real_strip
    assert host_ok == host, (name, 'host', host_ok)
    if check is not None:
        check(out)
    if strips is not None:
        assert sorted(f for f, _r, _a in logged) == sorted(strips), (name, logged)
    got, invalid = device.v5_parse(copy.deepcopy(inp))
    assert (not invalid) == v5, (name, 'v5', invalid)
    if v5:
        for key, value in (stored or {}).items():
            assert got[key] == value, (name, key, got[key], value)
    level = device.presentation_level(caps)
    if raw is None:
        if not host_ok:
            raw = level >= 5 and not v5
        else:
            raw = level >= 5 and v5 and not [f for f, r, a in logged if a != 'shortened'] and \
                raw_equivalent(inp, out)
    case = {"name": name, "note": note, "capabilities": caps, "input": inp,
            "expect": {"accept": host_ok, **({"output": out} if host_ok else {})},
            "rawParity": raw, "v5": {"accept": v5, **({"stored": got} if v5 else {})}}
    cases.append(case)
    return out


def eq(expected):
    def check(out):
        assert out == expected, (out, expected)
    return check


def ring_is(expected):
    def check(out):
        assert out['ring'] == expected, out['ring']
    return check


def has_not(*paths):
    def check(out):
        for path in paths:
            node = out
            parts = path.split('.')
            for part in parts[:-1]:
                node = node[int(part)] if part.isdigit() else node[part]
            assert parts[-1] not in node, (path, node)
    return check


def all_of(*checks):
    def check(out):
        for c in checks:
            c(out)
    return check


def with_ring(frame, **ring):
    frame = copy.deepcopy(frame)
    frame['ring'].update(ring)
    return frame


def without(frame, *paths):
    frame = copy.deepcopy(frame)
    for path in paths:
        node = frame
        parts = path.split('.')
        for part in parts[:-1]:
            node = node[int(part)] if part.isdigit() else node[part]
        node.pop(parts[-1], None)
    return frame


def with_fields(frame, **fields):
    frame = copy.deepcopy(frame)
    frame.update(fields)
    return frame


def with_button(frame, slot, **fields):
    frame = copy.deepcopy(frame)
    frame['buttons'][slot].update(fields)
    for key, value in list(fields.items()):
        if value is DROP:
            del frame['buttons'][slot][key]
    return frame


DROP = object()


def with_feedback(frame, **feedback):
    return with_fields(frame, feedback=feedback)


# ---------------------------------------------------------------------------
# 1. New layout tokens: accepted on presentation 5, mapped on presentation 4 (section 2.2).
out = add('v5-seek-p5', 'Seek on a cc5.4 knob: lap ring (index = target s, count = D s), 14 px caption in title, '
          'the 14 px line in meta; the firmware draws m:ss from ring.index (4.3). count 210 > 20: first always sent '
          '(v5 rule clamp(74-10, 0, 190) = 64).', CAP_P5_ALIVE, seek(),
          stored={"layout": "seek", "ringStyle": "lap", "ringIndex": 74, "ringCount": 210, "lit": [None, None, "on", None],
                  "icon": ["back", "expand", "seek", "next"]},
          check=all_of(ring_is({"style": "lap", "value": 0, "index": 74, "count": 210, "first": 64}),
                       lambda o: (o['layout'] == 'seek' and o['buttons'][2]['lit'] == 'on') or
                       (_ for _ in ()).throw(AssertionError(o))))
add('v5-seek-p4', 'Section 2.2: seek -> tracks for cc5.3, title := mmss(74) = "1:14", subtitle := the song, '
    'meta/heading kept, ring := off index 1 count 3 (the position row centre dot), icons expand->more, '
    'seek->tracks, lit dropped.', CAP_P4, seek(),
    check=eq({"id": 77, "mode": "TRACKS", "target": "Den", "value": "", "detail": "", "status": "", "layout": "tracks",
              "heading": "SEEK", "title": "1:14", "meta": "of 3:30", "artKey": "cover_c03",
              "buttons": [btn("Back", "back"), btn("Up next", "more"), btn("Seek", "tracks"),
                          btn("Next", "next", enabled=False)],
              "ring": {"style": "off", "value": 0, "index": 1, "count": 3}, "subtitle": "Hunter"}),
    stored={"layout": "seek", "ringStyle": "lap"})
add('v5-explorer-tab0-p5', 'Explorer, Recently Added tab: page 0 (slimmed), clock lit on, playlists lit off.',
    CAP_P5_ALIVE, explorer(0), stored={"layout": "explorer", "page": 0, "lit": [None, "on", "off", None],
                                       "icon": ["back", "clock", "playlists", "play"]},
    check=has_not('page'))
add('v5-explorer-tab1-p5', 'Explorer, Favourite playlists tab: page 1 (VOC-N05).', CAP_P5_ALIVE, explorer(1),
    stored={"layout": "explorer", "page": 1, "lit": [None, "off", "on", None]},
    check=lambda o: o['page'] == 1 or (_ for _ in ()).throw(AssertionError(o)))
add('v5-explorer-tab0-p4', 'Section 2.2: explorer tab 0 -> recent page 1 (1 + tab); clock/playlists -> list; lit dropped.',
    CAP_P4, explorer(0),
    check=lambda o: (o['layout'], o['page'], [b['icon'] for b in o['buttons']], o['heading']) ==
    ('recent', 1, ['back', 'list', 'list', 'play'], 'RECENT') and all('lit' not in b for b in o['buttons'])
    or (_ for _ in ()).throw(AssertionError(o)))
add('v5-explorer-tab1-p4', 'Section 2.2: explorer tab 1 -> recent page 2 (P5-R18: Recent->Explorer +, tab 0->1 +).',
    CAP_P4, explorer(1),
    check=lambda o: (o['layout'], o['page'], o['heading']) == ('recent', 2, 'FAVOURITES')
    or (_ for _ in ()).throw(AssertionError(o)))
add('v5-upnext-p5', 'Up next mirror: selection + now (the now-playing row), heart not liked, shuffle lit off.',
    CAP_P5_ALIVE, upnext(), stored={"layout": "upnext", "ringNow": 4, "ringCard": False, "lit": [None, "off", None, None],
                                    "icon": ["back", "shuffle", "heart", "play"]},
    check=lambda o: o['ring'].get('now') == 4 and 'card' not in o['ring'] or (_ for _ in ()).throw(AssertionError(o)))
add('v5-upnext-p4', 'Section 2.2: upnext -> recent page 1; now dropped; shuffle->switch, heart->more; UP NEXT kept.',
    CAP_P4, upnext(),
    check=lambda o: (o['layout'], o['page'], [b['icon'] for b in o['buttons']], o['heading'], 'now' in o['ring']) ==
    ('recent', 1, ['back', 'switch', 'more', 'play'], 'UP NEXT', False) or (_ for _ in ()).throw(AssertionError(o)))
add('v5-tracks-p5', 'Tracks with the new expand/seek icons; transport ring unchanged from V4.', CAP_P5_ALIVE, tracks(),
    stored={"layout": "tracks", "icon": ["back", "expand", "seek", "next"]})
add('v5-tracks-p4', 'Section 2.2 icons on Tracks: expand->more, seek->tracks.', CAP_P4, tracks(),
    check=lambda o: [b['icon'] for b in o['buttons']] == ['back', 'more', 'tracks', 'next'] or
    (_ for _ in ()).throw(AssertionError(o)))
add('v5-windows-snap-p5', 'Windows with the left side assigned: lit on + raw app colour kept (VOC section 2.1); '
    'snapright nav without colour.', CAP_P5_ALIVE, windows(),
    stored={"layout": "windows", "lit": [None, "on", None, None], "color": [0, 0x2B579A, 0, 0],
            "icon": ["back", "snapleft", "snapright", "switch"]},
    check=lambda o: o['buttons'][1] == btn("Left", "snapleft", lit="on", color=0x2B579A) and o['iconKey'] == 'icon_word'
    or (_ for _ in ()).throw(AssertionError(o)))
add('v5-windows-snap-p4', 'Section 2.2: snapleft->prev, snapright->next (never slot 3, so never green); lit and colour '
    'dropped.', CAP_P4, windows(),
    check=lambda o: o['buttons'][1] == btn("Left", "prev") and o['buttons'][2] == btn("Right", "next")
    or (_ for _ in ()).throw(AssertionError(o)))
add('v5-home-p5', 'Home on cc5.4: level ring count 101 > 20, so first 0 is always sent (P5-R9).', CAP_P5_ALIVE, home(),
    check=ring_is({"style": "level", "value": 54, "index": 0, "count": 101, "first": 0}))
add('v5-home-p4', 'The same Home frame for cc5.3: V4 slimming omits first 0; byte-identical to desktop v6.', CAP_P4,
    home(), check=ring_is({"style": "level", "value": 54, "index": 0, "count": 101}))
add('v5-layout-invalid-token', 'An unknown layout: the host strips it (logged), the parser rejects it.', CAP_P5_ALIVE,
    with_fields(home(), layout="spiral"), v5=False, strips=['layout'], check=has_not('layout'))

# 2. lap (section 4.3).
add('lap-count-1', 'lap with D = 1 s, target 0.', CAP_P5_ALIVE, with_ring(seek(), index=0, count=1),
    stored={"ringStyle": "lap", "ringIndex": 0, "ringCount": 1, "ringFirst": 0})
add('lap-count-59999', 'lap at LAP_COUNT_MAX (999:58 target): first = clamp(59998-10, 0, 59979) = 59979.',
    CAP_P5_ALIVE, with_ring(seek(), index=59998, count=59999),
    stored={"ringStyle": "lap", "ringIndex": 59998, "ringCount": 59999},
    check=lambda o: o['ring']['first'] == 59979 or (_ for _ in ()).throw(AssertionError(o['ring'])))
add('lap-count-0', 'lap needs count >= 1: invalid ring (host ValueError, parser reject).', CAP_P5_ALIVE,
    with_ring(seek(), index=0, count=0), host=False, v5=False)
add('lap-count-60000', 'lap above LAP_COUNT_MAX.', CAP_P5_ALIVE, with_ring(seek(), index=10, count=60000),
    host=False, v5=False)
add('lap-index-equals-count', 'lap target must be < D.', CAP_P5_ALIVE, with_ring(seek(), index=210, count=210),
    host=False, v5=False)
add('lap-value-missing', 'value is still required on a lap ring (send 0).', CAP_P5_ALIVE,
    without(seek(), 'ring.value'), host=False, v5=False)
add('lap-on-tracks-p5', 'A lap ring on another layout is valid (LEDs only, 4.3).', CAP_P5_ALIVE,
    with_ring(tracks(), style="lap", index=30, count=200), stored={"layout": "tracks", "ringStyle": "lap"})
add('lap-on-tracks-p4', 'Section 2.2: lap on any other layout -> off 0/0/0.', CAP_P4,
    with_ring(tracks(), style="lap", index=30, count=200),
    check=ring_is({"style": "off", "value": 0, "index": 0, "count": 0}))
add('lap-seek-p4-at-zero', 'Seek downgrade at the start: mmss(0) = "0:00".', CAP_P4, with_ring(seek(), index=0),
    check=lambda o: (o['title'], o['subtitle']) == ('0:00', 'Hunter') or (_ for _ in ()).throw(AssertionError(o)))
add('lap-seek-p4-long', 'Seek downgrade of a long work: mmss(59998) = "999:58".', CAP_P4,
    with_ring(seek(), index=59998, count=59999),
    check=lambda o: o['title'] == '999:58' or (_ for _ in ()).throw(AssertionError(o)))
add('seek-p4-without-lap', 'A Seek frame whose ring is not a lap draws no time (4.3), so the downgrade title is "".',
    CAP_P4, with_ring(seek(), style="off", index=0, count=0),
    check=lambda o: (o['layout'], o['title'], o['subtitle'], o['ring']) ==
    ('tracks', '', 'Hunter', {"style": "off", "value": 0, "index": 1, "count": 3})
    or (_ for _ in ()).throw(AssertionError(o)))

# 3. now (section 4.4).
add('now-valid', 'now = the now-playing row on the Up next mirror.', CAP_P5_ALIVE, upnext(now=0, index=0),
    stored={"ringNow": 0})
add('now-minus-one-kept-as-none', 'now -1 = none: valid, stored -1, slimmed by the host.', CAP_P5_ALIVE,
    upnext(now=-1), stored={"ringNow": -1}, check=lambda o: 'now' not in o['ring'] or
    (_ for _ in ()).throw(AssertionError(o['ring'])))
add('now-minus-two', 'now below -1: host strips (logged), parser rejects.', CAP_P5_ALIVE, upnext(now=-2), v5=False,
    strips=['ring.now'], check=lambda o: 'now' not in o['ring'] or (_ for _ in ()).throw(AssertionError(o)))
add('now-equals-count', 'now = count is past the list.', CAP_P5_ALIVE, upnext(now=12), v5=False, strips=['ring.now'])
add('now-bool', 'now must be a JSON int, never a bool.', CAP_P5_ALIVE, with_ring(upnext(), now=True), v5=False,
    strips=['ring.now'])
add('now-float', 'now must be a JSON int, never a float.', CAP_P5_ALIVE, with_ring(upnext(), now=4.0), v5=False,
    strips=['ring.now'])
add('now-stripped-on-recent', 'A valid now outside upnext is stripped silently by both (3.3 rule 3).', CAP_P5_ALIVE,
    with_ring(recent(), now=1), stored={"ringNow": -1}, strips=[],
    check=lambda o: 'now' not in o['ring'] or (_ for _ in ()).throw(AssertionError(o)))
add('now-stripped-on-explorer', 'now on explorer: stripped silently.', CAP_P5_ALIVE, with_ring(explorer(), now=1),
    stored={"ringNow": -1}, strips=[])
add('now-stripped-on-transport', 'now on a transport ring: stripped silently.', CAP_P5_ALIVE,
    with_ring(tracks(), now=1), stored={"ringNow": -1}, strips=[])
add('now-stripped-on-level', 'now on a level ring (Home): stripped silently.', CAP_P5_ALIVE,
    with_ring(home(), now=0), stored={"ringNow": -1}, strips=[])
add('now-stripped-upnext-off-ring', 'now on layout upnext with an off ring (a loading list, 4.6): stripped silently.',
    CAP_P5_ALIVE, with_fields(upnext(), activity="loading", ring={"style": "off", "value": 0, "index": 0, "count": 0,
                                                                   "now": -1}),
    stored={"ringNow": -1, "ringStyle": "off"}, strips=[])
add('now-invalid-on-recent-rejects', 'Validated on every layout: an out-of-range now on recent still rejects.',
    CAP_P5_ALIVE, with_ring(recent(), now=40), v5=False, strips=['ring.now'])
big = upnext(now=40000, count=40002, card=True, index=40001)
big['ring']['first'] = 39982
big['ring']['colors'] = [0x336699] * 19 + [0]
add('now-large-int32', 'now 40,000 (int32 storage, P5-R25): count 40,002, index 40,001, first 39,982 (the v5 rule), '
    'card true (now == count - 2); the card colour slot is 0.', CAP_P5_ALIVE, big,
    stored={"ringNow": 40000, "ringCard": True, "ringFirst": 39982, "ringIndex": 40001, "ringCount": 40002},
    check=lambda o: (o['ring']['now'], o['ring']['card'], o['ring']['first']) == (40000, True, 39982)
    or (_ for _ in ()).throw(AssertionError(o['ring'])))

# 4. card (section 4.4).
add('card-valid', 'Sonos native shuffle: P = 7 rows (played + now), card at index 7; count = P + 1, now = P - 1.',
    CAP_P5_ALIVE, upnext(now=6, count=8, card=True, index=7), stored={"ringCard": True, "ringNow": 6})
add('card-h1-variant', 'CC5 OQ-2 H1: count 2, now 0, card at 1.', CAP_P5_ALIVE, upnext(now=0, count=2, card=True, index=1),
    stored={"ringCard": True, "ringNow": 0})
add('card-false-slimmed', 'card false is the default: kept by the parser, omitted by the host.', CAP_P5_ALIVE,
    with_ring(upnext(), card=False), stored={"ringCard": False},
    check=lambda o: 'card' not in o['ring'] or (_ for _ in ()).throw(AssertionError(o['ring'])))
add('card-now-not-count-minus-2', 'card:true needs now == count - 2: host strips card (logged), parser rejects.',
    CAP_P5_ALIVE, upnext(now=4, count=8, card=True, index=7), v5=False, strips=['ring.card'],
    check=lambda o: ('card' not in o['ring'] and o['ring']['now'] == 4) or (_ for _ in ()).throw(AssertionError(o)))
add('card-without-now', 'card:true without now (-1): rejected / stripped.', CAP_P5_ALIVE,
    without(upnext(now=6, count=8, card=True, index=7), 'ring.now'), v5=False, strips=['ring.card'])
add('card-count-below-2', 'card:true with count 1 (now -1 = count - 2 but count < 2): rejected / stripped.',
    CAP_P5_ALIVE, with_ring(upnext(now=-1, count=1, index=0), card=True), v5=False, strips=['ring.card'])
add('card-not-bool', 'card must be a JSON bool.', CAP_P5_ALIVE, with_ring(upnext(now=6, count=8, index=7), card=1),
    v5=False, strips=['ring.card'])
add('card-stripped-on-recent', 'card outside upnext is stripped silently (even true with a bad now).', CAP_P5_ALIVE,
    with_ring(recent(), card=True), stored={"ringCard": False}, strips=[])
add('card-stripped-on-upnext-off-ring', 'card on upnext with an off ring: stripped silently.', CAP_P5_ALIVE,
    with_fields(upnext(), activity="loading", ring={"style": "off", "value": 0, "index": 0, "count": 0, "card": True}),
    stored={"ringCard": False}, strips=[])
add('card-p4-dropped', 'Section 2.2: now and card are dropped for cc5.3; the card stays an ordinary last entry.',
    CAP_P4, upnext(now=6, count=8, card=True, index=7),
    check=lambda o: ('now' not in o['ring'] and 'card' not in o['ring'] and o['ring']['count'] == 8)
    or (_ for _ in ()).throw(AssertionError(o)))

# 5. unavailable on upnext (P5-R24).
add('unavailable-upnext-stripped', 'A valid unavailable mask on upnext is stripped silently by both (stored 0).',
    CAP_P5_ALIVE, with_ring(upnext(), unavailable=0b100), stored={"ringUnavailable": 0}, strips=[],
    check=lambda o: 'unavailable' not in o['ring'] or (_ for _ in ()).throw(AssertionError(o)))
add('unavailable-upnext-card-stripped', 'The card with its unavailable bit set (ALIVE_R2_DRAFT X9): the mask is stripped '
    '(stored 0) and the card is still identified by card:true.', CAP_P5_ALIVE,
    with_ring(upnext(now=6, count=8, card=True, index=7), unavailable=1 << 7),
    stored={"ringUnavailable": 0, "ringCard": True}, strips=[])
add('unavailable-upnext-beyond-window', 'A mask with bits beyond the window is still validated first: rejected / '
    'stripped (logged).', CAP_P5_ALIVE, with_ring(upnext(), unavailable=1 << 12), v5=False, strips=['ring.unavailable'])
add('unavailable-recent-kept', 'On recent the mask keeps its V4 meaning.', CAP_P5_ALIVE,
    with_ring(recent(), unavailable=0b10), stored={"ringUnavailable": 2})

# 6. lit (section 5.1) and 7. button colour.
add('lit-on-off', 'lit on and off on the explorer tab pair.', CAP_P5_ALIVE, explorer(0),
    stored={"lit": [None, "on", "off", None]}, raw=None)
add('lit-invalid-token', 'lit "yes": host strips (logged), parser rejects.', CAP_P5_ALIVE,
    with_button(explorer(0), 1, lit="yes"), v5=False, strips=['button.lit'], check=has_not('buttons.1.lit'))
add('lit-invalid-bool', 'lit true is not a token.', CAP_P5_ALIVE, with_button(explorer(0), 1, lit=True), v5=False,
    strips=['button.lit'])
add('lit-with-empty-icon', 'lit with icon "" is valid and stored (tone none wins, 5.2 row 1).', CAP_P5_ALIVE,
    with_button(explorer(0), 1, icon=""), stored={"lit": [None, "on", "off", None], "icon": ["back", "", "playlists", "play"]})
add('lit-with-disabled', 'lit with enabled false is stored (dim wins, 5.2 row 2).', CAP_P5_ALIVE,
    with_button(explorer(0), 2, enabled=False), stored={"lit": [None, "on", "off", None]})
add('color-without-lit-host-strips', 'A colour without lit on is meaningless: the host omits it (14.2), a raw parser '
    'stores it (parsed as before).', CAP_P5_ALIVE, with_button(windows(), 2, color=0x0F9D58),
    stored={"color": [0, 0x2B579A, 0x0F9D58, 0]}, check=has_not('buttons.2.color'))
add('color-lit-off-host-strips', 'lit off + colour: omitted by the host.', CAP_P5_ALIVE,
    with_button(windows(), 2, lit="off", color=0x0F9D58), check=has_not('buttons.2.color'))
add('color-zero-lit-on-slimmed', 'lit on + colour 0 (a monochrome app, P5-6): the colour is omitted (warm).',
    CAP_P5_ALIVE, with_button(windows(), 1, color=0), check=has_not('buttons.1.color'))
add('heart-lit-on-no-colour', 'Liked heart: lit on (the knob derives tone liked, the filled heart in #A3244A, '
    'r2.2); PINK is the knob\'s LED colour, so a colour is never sent with the heart.',
    CAP_P5_ALIVE, with_button(upnext(liked=True), 2, color=0xFF285A),
    stored={"lit": [None, "off", "on", None]}, check=has_not('buttons.2.color'))
add('color-out-of-range', 'A button colour above 0xFFFFFF: host strips (logged), parser rejects.', CAP_P5_ALIVE,
    with_button(windows(), 1, color=0x1000000), v5=False, strips=['button.color'])

# 8. Icons (section 9.1).
for index, token in enumerate(P.ICONS_V5):
    frame = recent()
    frame['buttons'][1]['icon'] = token
    add(f'icon-{token}-p5', f'v5 icon {token!r} on slot 1: accepted and stored.', CAP_P5_ALIVE, frame,
        stored={"icon": ["back", token, "playnext", "play"]})
    add(f'icon-{token}-p4', f'v5 icon {token!r} -> {P.ICON_DOWNGRADE[token]!r} for cc5.3 (2.2).', CAP_P4, frame,
        check=lambda o, t=token: o['buttons'][1]['icon'] == P.ICON_DOWNGRADE[t] or (_ for _ in ()).throw(AssertionError(o)))
for token in ('home', 'more', 'cancel'):
    frame = recent()
    frame['buttons'][0 if token == 'cancel' else 1]['icon'] = token
    add(f'icon-legacy-{token}', f'Legacy token {token!r} (v6 hosts) keeps its mask and meaning.', CAP_P5_ALIVE, frame)
add('icon-unknown', 'An unknown icon: replaced by "" on the host (logged), rejected by the parser.', CAP_P5_ALIVE,
    with_button(recent(), 1, icon="star"), v5=False, strips=['button.icon'],
    check=lambda o: o['buttons'][1]['icon'] == '' or (_ for _ in ()).throw(AssertionError(o)))

# 9. feedback moments (section 6).
for moment in P.FEEDBACK_MOMENTS:
    extra = {"side": -1} if moment == "snap" else {}
    add(f'moment-{moment}-ok', f'moment {moment!r} with ok: kept.', CAP_P5_ALIVE,
        with_feedback(upnext(), kind="ok", seq=9, moment=moment, **extra),
        stored={"feedbackKind": "ok", "feedbackMoment": moment, "feedbackSide": -1 if moment == "snap" else 0},
        check=lambda o, m=moment, e=extra: o['feedback'] == {"kind": "ok", "seq": 9, "moment": m, **e}
        or (_ for _ in ()).throw(AssertionError(o['feedback'])))
    add(f'moment-{moment}-err', f'moment {moment!r} with err: stripped silently by both.', CAP_P5_ALIVE,
        with_feedback(upnext(), kind="err", seq=9, moment=moment, **extra),
        stored={"feedbackKind": "err", "feedbackMoment": None, "feedbackSide": 0}, strips=[],
        check=lambda o: o['feedback'] == {"kind": "err", "seq": 9} or (_ for _ in ()).throw(AssertionError(o)))
    add(f'moment-{moment}-p4', f'moment {moment!r} for cc5.3 (2.2): ' +
        ('the whole feedback is omitted (P5-R16).' if moment == 'unlike' else 'a plain {kind: ok, seq} (V4 green flash).'),
        CAP_P4, with_feedback(upnext(), kind="ok", seq=9, moment=moment, **extra),
        check=(has_not('feedback') if moment == 'unlike' else
               lambda o: o['feedback'] == {"kind": "ok", "seq": 9} or (_ for _ in ()).throw(AssertionError(o))))
add('moment-invalid-token', 'An unknown moment: host strips it (logged), parser rejects.', CAP_P5_ALIVE,
    with_feedback(upnext(), kind="ok", seq=9, moment="wink"), v5=False, strips=['feedback.moment'],
    check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9} or (_ for _ in ()).throw(AssertionError(o)))
add('moment-with-skip-alive', 'skip and moment together with ok: the parser rejects; the host (alive) keeps skip and '
    'strips the moment (6.2 rule 2).', CAP_P5_ALIVE,
    with_feedback(tracks(), kind="ok", seq=9, skip=1, moment="queued"), v5=False, strips=['feedback.moment'],
    check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9, "skip": 1} or (_ for _ in ()).throw(AssertionError(o)))
add('moment-with-skip-err', 'skip and moment with err: both stripped silently (no combination check).', CAP_P5_ALIVE,
    with_feedback(tracks(), kind="err", seq=9, skip=1, moment="queued"),
    stored={"feedbackMoment": None, "feedbackSkip": 0}, strips=[])
add('moment-with-skip-no-alive', 'Without alive the host never sends skip, so the moment stays; the raw input is '
    'still rejected by a cc5.4 parser.', CAP_P5, with_feedback(tracks(), kind="ok", seq=9, skip=1, moment="queued"),
    v5=False, strips=[],
    check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9, "moment": "queued"} or (_ for _ in ()).throw(AssertionError(o)))
add('moment-snap-without-side', 'snap without side: parser rejects, host strips the moment (logged).', CAP_P5_ALIVE,
    with_feedback(windows(), kind="ok", seq=9, moment="snap"), v5=False, strips=['feedback.moment'],
    check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9} or (_ for _ in ()).throw(AssertionError(o)))
add('moment-snap-side-right', 'snap right with the app colour.', CAP_P5_ALIVE,
    with_feedback(windows(), kind="ok", seq=9, moment="snap", side=1, color=0x0F9D58),
    stored={"feedbackMoment": "snap", "feedbackSide": 1, "feedbackColor": 0x0F9D58})
add('moment-side-without-snap', 'side without snap: stripped silently by both.', CAP_P5_ALIVE,
    with_feedback(upnext(), kind="ok", seq=9, moment="like", side=1),
    stored={"feedbackMoment": "like", "feedbackSide": 0}, strips=[],
    check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9, "moment": "like"} or (_ for _ in ()).throw(AssertionError(o)))
add('moment-side-invalid', 'side 0 is not -1 or 1: rejected / stripped (logged); then snap has no side.', CAP_P5_ALIVE,
    with_feedback(windows(), kind="ok", seq=9, moment="snap", side=0), v5=False,
    strips=['feedback.side', 'feedback.moment'])
add('moment-side-bool', 'side true is not an int.', CAP_P5_ALIVE,
    with_feedback(windows(), kind="ok", seq=9, moment="snap", side=True), v5=False,
    strips=['feedback.side', 'feedback.moment'])
add('moment-color-started', 'started + colour (the started item\'s accent, VOC section 3.5): kept.', CAP_P5_ALIVE,
    with_feedback(home(), kind="ok", seq=9, moment="started", color=0x7A3B2C),
    stored={"feedbackMoment": "started", "feedbackColor": 0x7A3B2C},
    check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9, "moment": "started", "color": 0x7A3B2C}
    or (_ for _ in ()).throw(AssertionError(o)))
add('moment-color-snap', 'snap + colour: kept.', CAP_P5_ALIVE,
    with_feedback(windows(), kind="ok", seq=9, moment="snap", side=-1, color=0x2B579A),
    stored={"feedbackColor": 0x2B579A})
add('moment-color-like', 'like + colour: stripped silently (PINK is the knob\'s).', CAP_P5_ALIVE,
    with_feedback(upnext(), kind="ok", seq=9, moment="like", color=0xFF285A),
    stored={"feedbackMoment": "like", "feedbackColor": 0}, strips=[],
    check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9, "moment": "like"} or (_ for _ in ()).throw(AssertionError(o)))
add('moment-color-zero-slimmed', 'started + colour 0 (warm): the host omits the default.', CAP_P5_ALIVE,
    with_feedback(home(), kind="ok", seq=9, moment="started", color=0),
    stored={"feedbackColor": 0}, check=lambda o: 'color' not in o['feedback'] or (_ for _ in ()).throw(AssertionError(o)))
add('moment-color-out-of-range', 'feedback.color above 0xFFFFFF: rejected / stripped (logged).', CAP_P5_ALIVE,
    with_feedback(home(), kind="ok", seq=9, moment="started", color=0x1000000), v5=False, strips=['feedback.color'])
add('moment-color-without-moment', 'A colour with no moment: stripped silently.', CAP_P5_ALIVE,
    with_feedback(home(), kind="ok", seq=9, color=0x123456), stored={"feedbackColor": 0, "feedbackMoment": None},
    strips=[], check=lambda o: o['feedback'] == {"kind": "ok", "seq": 9} or (_ for _ in ()).throw(AssertionError(o)))
add('moment-invalid-with-err', 'Validated with any kind: an unknown moment with err still rejects.', CAP_P5_ALIVE,
    with_feedback(home(), kind="err", seq=9, moment="wink"), v5=False, strips=['feedback.moment'])

# 10. reducedMotion (section 7.1).
add('reduced-motion-true', 'reducedMotion true: latched field, stored present.', CAP_P5_ALIVE,
    with_fields(home(), reducedMotion=True), stored={"reducedMotion": True},
    check=lambda o: o['reducedMotion'] is True or (_ for _ in ()).throw(AssertionError(o)))
add('reduced-motion-false', 'reducedMotion false (a control frame always carries it).', CAP_P5, with_fields(recent(),
    reducedMotion=False), stored={"reducedMotion": False})
add('reduced-motion-invalid', 'reducedMotion 1 is not a bool: rejected / stripped (logged).', CAP_P5_ALIVE,
    with_fields(home(), reducedMotion=1), v5=False, strips=['reducedMotion'], check=has_not('reducedMotion'))
add('reduced-motion-p4', 'Never sent to a presentation-4 knob (stripped silently).', CAP_P4,
    with_fields(home(), reducedMotion=True), strips=[], check=has_not('reducedMotion'))

# 11/12. ledPink / ledVolFull (section 7.3).
for value, label in ((0, '0'), (1, '1'), (0xFFFFFF, 'max')):
    add(f'led-pink-{label}', f'ledPink {value}: valid (0 = the built-in PINK).', CAP_P5_ALIVE,
        with_fields(home(), ledPink=value), stored={"ledPink": value},
        check=lambda o, v=value: o['ledPink'] == v or (_ for _ in ()).throw(AssertionError(o)))
for value, label in ((-1, 'minus-one'), (0x1000000, 'over'), (True, 'bool'), ("#FF051A", 'string'), (1.5, 'float')):
    add(f'led-pink-invalid-{label}', f'ledPink {value!r}: rejected / stripped (logged).', CAP_P5_ALIVE,
        with_fields(home(), ledPink=value), v5=False, strips=['ledPink'], check=has_not('ledPink'))
for value in (True, False):
    add(f'led-vol-full-{str(value).lower()}', f'ledVolFull {value}: valid.', CAP_P5_ALIVE,
        with_fields(home(), ledVolFull=value), stored={"ledVolFull": value})
for value, label in ((1, 'int'), ("true", 'string')):
    add(f'led-vol-full-invalid-{label}', f'ledVolFull {value!r}: rejected / stripped (logged).', CAP_P5_ALIVE,
        with_fields(home(), ledVolFull=value), v5=False, strips=['ledVolFull'])
add('tuning-without-alive', 'A presentation-5 knob without alive: ledPink / ledVolFull (and every ALIVE field) are '
    'stripped silently; reducedMotion stays (v5).', CAP_P5,
    with_fields(home(), ledPink=5, ledVolFull=True, reducedMotion=True, clock=600, playing=True),
    stored={"ledPink": 5, "ledVolFull": True}, strips=[],
    check=all_of(has_not('ledPink', 'ledVolFull', 'clock', 'playing'),
                 lambda o: o['reducedMotion'] is True or (_ for _ in ()).throw(AssertionError(o))))
add('tuning-p4-alive', 'A presentation-4 knob with alive (the round-2 build): ALIVE fields kept, the tuning fields '
    'and reducedMotion never (7.3: absent from every presentation-4 output).', CAP_P4_ALIVE,
    with_fields(home(), ledPink=5, ledVolFull=True, reducedMotion=True, clock=600, playing=True),
    strips=[], check=all_of(has_not('ledPink', 'ledVolFull', 'reducedMotion'),
                            lambda o: (o['clock'], o['playing']) == (600, True) or (_ for _ in ()).throw(AssertionError(o))))
add('tuning-p4', 'cc5.3: no ALIVE, tuning or v5 latched field.', CAP_P4,
    with_fields(home(), ledPink=5, ledVolFull=True, reducedMotion=True, clock=600, playing=True), strips=[],
    check=has_not('ledPink', 'ledVolFull', 'reducedMotion', 'clock', 'playing'))

# 14. explorer page (0/1) covered in section 1; the raw parser keeps any page 0..255.
add('explorer-page-5-p4-clamped', 'A page outside 0/1 on explorer is still a valid page for the parser; the downgrade '
    'gives 1 + page (here 6).', CAP_P4, with_fields(explorer(1), page=5),
    check=lambda o: o['page'] == 6 or (_ for _ in ()).throw(AssertionError(o)))

# 15. Remaining section 2.2 rows.
add('downgrade-meta-error-kept', 'metaTone error is kept for cc5.3 (V4 draws #FF8A7A).', CAP_P4,
    with_fields(seek(meta="Didn’t jump · try again"), metaTone="error"),
    check=lambda o: (o['metaTone'], o['meta']) == ('error', 'Didn’t jump · try again')
    or (_ for _ in ()).throw(AssertionError(o)))
add('downgrade-p4-no-artwork2', 'cc5.2 (presentation 4 without artwork2): the same downgrade under v1 art rules.',
    CAP_P4_V1ART, seek(), check=lambda o: (o['layout'], o['title']) == ('tracks', '1:14')
    or (_ for _ in ()).throw(AssertionError(o)))
add('downgrade-cc4-seek', 'cc4 (presentation 2): V4 legacy rules after the 2.2 mapping; ASCII, colours kept, no v4 '
    'or v5 field.', CAP_P2, seek(),
    check=lambda o: (o['layout'], o['title'], o['subtitle'], [b['icon'] for b in o['buttons']], 'heading' in o, o['ring'])
    == ('tracks', '1:14', 'Hunter', ['back', 'more', 'tracks', 'next'], False,
        {"style": "off", "value": 0, "index": 1, "count": 3}) and all('lit' not in b for b in o['buttons'])
    or (_ for _ in ()).throw(AssertionError(o)))
add('downgrade-cc4-upnext', 'cc4: upnext -> recent (page dropped with every v4 field), heart -> more.', CAP_P2, upnext(),
    check=lambda o: (o['layout'], 'page' in o, o['buttons'][2]['icon'], 'now' in o['ring']) ==
    ('recent', False, 'more', False) or (_ for _ in ()).throw(AssertionError(o)))

# windowRule (section 4.2).
long_list = recent(index=10, count=45)
long_list['ring']['colors'] = [0x7A3B2C] * 20
add('window-v5-index-10', 'v5 host rule: first = clamp(10-10, 0, 25) = 0, always sent when count > 20 (P5-R9); '
    'the colours stay relative to 0. (V4 would derive 1 and drop them.)', CAP_P5_ALIVE, long_list,
    check=lambda o: (o['ring']['first'], len(o['ring']['colors'])) == (0, 20) or (_ for _ in ()).throw(AssertionError(o)))
add('window-v4-index-10', 'The same input for cc5.3: V4 derives first 1, so the colours (relative to 0) are dropped.',
    CAP_P4, long_list,
    check=lambda o: (o['ring']['first'], 'colors' in o['ring']) == (1, False) or (_ for _ in ()).throw(AssertionError(o)))
# A v7 controller builds v5 windows whatever the knob (section 2.2): at index 10 of a list longer than
# 20 its first is 0 where V4 derives 1. The presentation-4 output must keep that explicit 0 (P4 section 8
# slims first 0 only where the absent-first derivation is 0 too), or cc5.3 would shift the window by one
# and drop the colours and the mask (both relative to 0).
v5_window = recent(index=10, count=41)
v5_window['ring'].update(first=0, colors=[0x7A3B2C + 4099 * k for k in range(20)], unavailable=1 << 10)
for caps_name, caps in (('p4', CAP_P4), ('p4-alive', CAP_P4_ALIVE)):
    add(f'window-v5-first-0-index-10-{caps_name}', 'A v5-rule window (first 0, index 10, count 41, 20 colours, '
        'unavailable bit 10) for cc5.3: first 0 is kept (V4 would derive 1), so the colours and the mask stay '
        'relative to 0 on the V4 parser.', caps, v5_window,
        stored={"ringFirst": 0, "ringUnavailable": 1 << 10},
        check=lambda o: (o['ring'].get('first'), len(o['ring']['colors']), o['ring']['unavailable'])
        == (0, 20, 1 << 10) or (_ for _ in ()).throw(AssertionError(o['ring'])))
up_window = upnext(now=9, count=41, index=10)
up_window['ring']['first'] = 0
add('window-v5-first-0-index-10-upnext-p4', 'Up next at index 10 of 41 (v5 first 0) for cc5.3: upnext -> recent '
    'page 1 keeps first 0 and the 20 colours (now dropped by the 2.2 downgrade).', CAP_P4, up_window,
    stored={"ringFirst": 0, "ringNow": 9},
    check=lambda o: (o['layout'], o['ring'].get('first'), len(o['ring']['colors']), 'now' in o['ring'])
    == ('recent', 0, 20, False) or (_ for _ in ()).throw(AssertionError(o)))
for caps_name, caps in (('p4', CAP_P4), ('p5', CAP_P5_ALIVE)):
    near = recent(index=9, count=41)
    near['ring']['first'] = 0
    add(f'window-first-0-index-9-{caps_name}', 'first 0 at index 9 of 41: V4 derives 0 too, so presentation 4 '
        'still omits it (byte-identical to desktop v6); presentation 5 always sends it (count > 20).', caps, near,
        stored={"ringFirst": 0},
        check=lambda o, p5=caps is CAP_P5_ALIVE: ('first' in o['ring']) == p5
        or (_ for _ in ()).throw(AssertionError(o['ring'])))
mid = recent(index=30, count=45)
mid['ring'].pop('colors')
add('window-v5-index-30', 'v5 first = 20 (V4 would be 21).', CAP_P5_ALIVE, mid,
    check=lambda o: o['ring']['first'] == 20 or (_ for _ in ()).throw(AssertionError(o)))
add('window-absent-first-derived-v4', 'A raw input without first (a legacy sender): the parser derives V4\'s '
    'clamp(index-9) = 21 (rules.absentFirst).', CAP_P5_ALIVE, mid, stored={"ringFirst": 21}, raw=False)
mid_first = copy.deepcopy(mid)
mid_first['ring']['first'] = 20
add('window-present-first-v5', 'A present v5 first (20) passes the V4 window check and is stored as sent.',
    CAP_P5_ALIVE, mid_first, stored={"ringFirst": 20})

# 16. Budget (section 14.1).
def windows_worst(title, app, labels=("Back", "Left", "Right", "Switch")):
    frame = base("WINDOWS", "windows",
                 [btn(labels[0], "back"), btn(labels[1], "snapleft", lit="on", color=0xFFFFFE),
                  btn(labels[2], "snapright", lit="on", color=0xFFFFFD), btn(labels[3], "switch")],
                 {"style": "selection", "value": 0, "index": 44, "count": 45, "first": 25,
                  "colors": [0xFFFFFF - k for k in range(20)], "unavailable": (1 << 20) - 2},
                 activity="pending", title=title, subtitle=app,
                 meta="Couldn’t move this window · it may be running as administrator · try again" + "…" * 1,
                 ledStyle="color", iconKey="k" * 24,
                 feedback={"kind": "ok", "seq": 0x7FFFFFFF, "moment": "snap", "side": 1, "color": 0xFFFFFE})
    frame['target'] = frame['value'] = frame['detail'] = frame['status'] = ''
    frame['id'] = 0x7FFFFFFF
    return frame


title96 = ('Quarterly business review — final draft (revised) for the leadership offsite.docx' + 'x' * 40)
title96 = P.utf8_truncate(title96, 96)
app96 = P.utf8_truncate('Microsoft Word — Document collaboration and review tools for the whole team' + 'y' * 40, 96)
worst = windows_worst(title96, app96)
_, reserve = device.frame_budget(CAP_P5_ALIVE)


def fits_untouched(frame):
    def check(out):
        size = device.frame_line_bytes({**out, **reserve})
        assert size <= P.FRAME_BUDGET_BYTES_V5, size
        for name in ('title', 'subtitle', 'meta', 'volumeCaption', 'status', 'value'):
            assert out.get(name, '') == frame.get(name, ''), (name, out.get(name))
        BUDGET_REPORT.append(f"[budget] {frame['layout']}: {size} B with the latched reserve")
    return check


add('budget-windows-worst', 'Section 14.1 worst realistic Windows frame (20 colours, 96 B title and app name, a long '
    'snap meta, 24-char iconKey, two lit colour buttons, snap feedback, pending) plus the 148 B latched reserve '
    '(ALIVE worst, reducedMotion, ledPink/ledVolFull): <= 1,400 B with nothing shortened.', CAP_P5_ALIVE, worst,
    check=fits_untouched(worst), strips=[])
meta90 = P.utf8_truncate('Couldn’t move this window · it may be running as administrator · try again later ' * 2, 90)
maxed = windows_worst(title96, app96, labels=("B" * 16, "L" * 16, "R" * 16, "S" * 16))
maxed['meta'] = meta90
add('budget-windows-worst-16b-labels', 'The Windows worst case with every button label at its 16 B capacity and a 90 B '
    'meta: still <= 1,400 B with the latched reserve, nothing shortened.', CAP_P5_ALIVE, maxed,
    check=fits_untouched(maxed), strips=[])
quotes = windows_worst('"' * 96, '"' * 96)
add('budget-windows-escape-heavy', 'An escape-heavy Windows frame (title and app name of quotes, 1,500+ B): V4\'s '
    'trim order, then the longest drawn text is shortened to fit 1,400 B with the latched reserve.', CAP_P5_ALIVE,
    quotes, strips=['subtitle', 'title'],
    check=lambda o: device.frame_line_bytes({**o, **reserve}) <= P.FRAME_BUDGET_BYTES_V5 < device.frame_line_bytes(
        {**quotes, **reserve}) or (_ for _ in ()).throw(AssertionError(device.frame_line_bytes({**o, **reserve}))))
up_worst = upnext(now=39, count=41, card=True, index=40, liked=True)
up_worst['ring']['first'] = 21
up_worst['ring']['colors'] = [0xFFFFFF - k for k in range(19)] + [0]
up_worst.update(title=P.utf8_truncate('A very long song title — extended mix featuring many guests ' * 3, 96),
                subtitle=P.utf8_truncate('A long list of artists, featuring several collaborators ' * 3, 96),
                meta='41 / 41 · Shuffled by Sonos', activity='pending', id=0x7FFFFFFF,
                feedback={"kind": "ok", "seq": 0x7FFFFFFF, "moment": "like"})
add('budget-upnext-worst', 'Up next worst case (now, card, like, long title and sub) with the latched reserve.',
    CAP_P5_ALIVE, up_worst, check=fits_untouched(up_worst), strips=[])
ex_worst = explorer(1)
ex_worst['ring'].update(index=150, count=300, first=140, colors=[0xFFFFFF - k for k in range(20)])
ex_worst.update(title=P.utf8_truncate('Favourite playlist with a very long name for testing the budget ' * 3, 96),
                subtitle='1,234 songs', meta='151 / 300', id=0x7FFFFFFF, activity='pending',
                feedback={"kind": "ok", "seq": 0x7FFFFFFF, "moment": "started", "color": 0xFFFFFE})
add('budget-explorer-worst', 'Explorer worst case with the latched reserve.', CAP_P5_ALIVE, ex_worst,
    check=fits_untouched(ex_worst), strips=[])
home_worst = home()
home_worst.update(title=P.utf8_truncate('A very long song title — extended mix featuring many guests ' * 3, 96),
                  subtitle=P.utf8_truncate('A long list of artists, featuring several collaborators ' * 3, 96),
                  volumeCaption=P.utf8_truncate('A very long song title — extended mix ' * 4, 96),
                  status='Changed on Sonos', layout='volume', id=0x7FFFFFFF, activity='pending', playing=True,
                  feedback={"kind": "ok", "seq": 0x7FFFFFFF, "moment": "started", "color": 0xFFFFFE})
add('budget-home-worst', 'Home (volume reveal) worst case with the latched reserve.', CAP_P5_ALIVE, home_worst,
    check=fits_untouched(home_worst), strips=[])
seek_worst = seek(target=59998, duration=59999, meta='Didn’t jump · try again')
seek_worst.update(title=P.utf8_truncate('A very long song title — extended mix featuring many guests ' * 3, 96),
                  id=0x7FFFFFFF, activity='pending', metaTone='error')
add('budget-seek-worst', 'Seek worst case with the latched reserve.', CAP_P5_ALIVE, seek_worst,
    check=fits_untouched(seek_worst), strips=[])

# 17. Gating.
add('gating-p5-no-alive', 'Presentation 5 without a valid alive object: v5 fields, no ALIVE field (1; 2.1 row 2).',
    CAP_P5, with_fields(upnext(), playing=True, clock=100, progress={"pos": 1, "dur": 2}, ledDrive=9),
    strips=[], check=all_of(has_not('clock', 'progress', 'ledDrive', 'playing'),
                            lambda o: o['ring']['now'] == 4 or (_ for _ in ()).throw(AssertionError(o))))
add('gating-p4-no-v5', 'Presentation 4: no v5 field at all (every 2.2 row at once).', CAP_P4,
    with_fields(with_feedback(windows(), kind="ok", seq=3, moment="snap", side=-1, color=5), reducedMotion=True),
    strips=[], check=lambda o: device.v5_parse(o)[0]['lit'] == [None] * 4 and 'reducedMotion' not in o
    and o['feedback'] == {"kind": "ok", "seq": 3} and o['buttons'][1] == btn("Left", "prev")
    or (_ for _ in ()).throw(AssertionError(o)))
bad_alive = {**CAP_P5, "alive": {"version": True, "fps": 60, "drive": 150}}
add('gating-p5-malformed-alive', 'alive.version true is not 1: no ALIVE or tuning field.', bad_alive,
    with_fields(home(), ledPink=5, clock=10), strips=[], check=has_not('ledPink', 'clock'))

# Loading lists (4.6): the host and parser do nothing special.
add('loading-list-off-ring', 'A whole list loading: style off + activity loading (4.6, VOC-K1g).', CAP_P5_ALIVE,
    with_fields(recent(), activity="loading", title="", subtitle="", meta="Loading…",
                ring={"style": "off", "value": 0, "index": 0, "count": 0}),
    stored={"ringStyle": "off", "ringCount": 0})
unloaded = recent(index=5, count=12)
unloaded['ring']['colors'][5] = 0
unloaded.update(title="", subtitle="", meta="Loading…")
add('loading-unloaded-entry', 'An unloaded entry of a known list: colour 0 with the list\'s own activity (4.6).',
    CAP_P5_ALIVE, unloaded)

# Unknown fields stay ignored (3.3 rule 4).
add('unknown-v5-subfields', 'Unknown fields inside ring, buttons and feedback are ignored by the parser; the host '
    'logs and drops them.', CAP_P5_ALIVE,
    with_feedback(with_ring(with_button(upnext(), 1, glow=1), future=2), kind="ok", seq=3, moment="like", extra=1),
    strips=['button.glow', 'ring.future'])

# ---------------------------------------------------------------------------
vectors = {
    "mmss": [[s, P.mmss(s)] for s in (0, 5, 59, 60, 74, 599, 600, 3599, 3600, 35999, 59998)],
    "accentInk": [[c, P.accent_ink(c)] for c in (0, 0x000080, 0x0000FF, 0xFF0000, 0x00FF00, 0x2B579A, 0x0F9D58,
                                                  0xD83B01, 0x808080, 0x7F7F9C, 0x7F7F9D, 0x101010, 0x400040,
                                                  0x123456, 0xFFFFFF, 0x1E1E3C, 0x003300)],
    "tones": [],
}
for slot in range(4):
    for icon in ('', 'play', 'cancel', 'next', 'heart', 'snapleft', 'clock'):
        for enabled in (True, False):
            for lit in (None, 'on', 'off'):
                for color in (0, 0x2B579A):
                    for layout in ('nowPlaying', 'recent'):
                        vectors["tones"].append({
                            "slot": slot, "icon": icon, "enabled": enabled, "lit": lit, "color": color,
                            "layout": layout, "tone": P.button_tone_v5(slot, icon, enabled, lit, layout),
                            "ink": P.button_ink_v5(slot, icon, enabled, lit, color, layout)})

fixture = {
    "contract": "firmware/PRESENTATION_V5.md (frozen v5; 1.0.0-cc5.4 + desktop v7)",
    "about": ("Shared frame fixtures for presentation 5 (PRESENTATION_V5.md section 15.1). Same case format as "
              "frames_v4.json / frames_alive.json: name, note, capabilities {presentation 4|5, glyphs, artwork2?, "
              "alive?}, input, expect {accept, output?} describing the HOST (control_center/device.py _frame(input, "
              "capabilities)), rawParity, and v5 {accept, stored?}: what a 1.0.0-cc5.4 parser "
              "(src/cc_frame_parse.cpp) does with `input` itself. Generated from hand-written cases and checks "
              "(WP3-wire); `vectors` are the shared test vectors of mmss(), accent_ink() and the section 5.2 tone "
              "table (presentation.py; the cc_presentation.h mirrors must match them)."),
    "rules": {
        "host": "device._frame(input, capabilities) raises ValueError when expect.accept is false, otherwise returns "
                "exactly expect.output (key order irrelevant).",
        "firmwareOutput": "Every accepted expect.output is accepted by a cc5.4 parser, which stores its text "
                          "byte-identically and its v5 values as sent (defaults when absent).",
        "firmwareRaw": "When rawParity is true, a cc5.4 parser fed input directly matches expect.accept and, when "
                       "accepted, stores the same text and v5 values as for expect.output.",
        "v5Raw": "Every case: a cc5.4 parser fed input accepts exactly when v5.accept and then stores v5.stored "
                 "(layout, page, ringStyle, ringIndex, ringCount, ringFirst, ringNow, ringCard, ringUnavailable, "
                 "lit[4], color[4], icon[4], feedbackKind, feedbackMoment, feedbackSide, feedbackColor, feedbackSkip, "
                 "reducedMotion|null, ledPink|null, ledVolFull|null; null = absent). device.v5_parse(input) returns "
                 "the same stored values with no invalid field, or names the invalid field(s).",
        "downgrade": "Every presentation < 5 case's output is a valid V4 frame (no v5 token or field) that the cc5.3 "
                     "parser (the cc5.3 source snapshot) accepts with identical text (section 2.2).",
        "windowRule": "Presentation 5: first = clamp(index-10, 0, count-20), always sent when count > 20; an absent "
                      "first is still derived by the parser as clamp(index-9, 0, count-20). Presentation 4: a first "
                      "of 0 is omitted only where that derivation gives 0 too (an explicit v5-rule 0 at index 10 "
                      "is kept, so the colours and the mask stay relative to 0).",
        "card": "card:true only on a selection ring of layout upnext, with count >= 2 and now == count - 2; "
                "unavailable is stripped on upnext; now is int32 (40,000 stores as 40,000).",
        "moment": "moment only with ok (skip + moment or snap without side reject; the host strips); side only with "
                  "snap; color only with snap/started.",
        "lap": "lap: 1 <= count <= 59,999 and index < count; value required.",
        "budget": "Presentation 5: every output line with the latched reserve (ALIVE worst values, reducedMotion "
                  "false, ledPink 16777215, ledVolFull false) is <= 1,400 B; presentation 4 keeps 1,100 B.",
    },
    "cases": cases,
    "vectors": vectors,
}


def render() -> str:
    """The fixture file's exact text (UTF-8, LF line ends)."""
    return json.dumps(fixture, ensure_ascii=False, indent=1) + '\n'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--check', action='store_true', help='compare with the fixture instead of writing it')
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = OUT.read_bytes().decode('utf-8') if OUT.is_file() else None
        if current != text:
            print(f'STALE: {OUT} differs from the generator output; run tests/tools/make_frames_v5.py')
            return 1
        print(f'OK: {OUT} is up to date ({len(cases)} cases)')
        return 0
    for line in BUDGET_REPORT:
        print(line)
    OUT.write_bytes(text.encode('utf-8'))
    print(f'wrote {OUT} with {len(cases)} cases ({sum(c["rawParity"] for c in cases)} rawParity), '
          f'{len(vectors["tones"])} tone vectors')
    return 0


if __name__ == '__main__':
    sys.exit(main())

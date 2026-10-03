"""Write harness/fixtures/frames_v6.json: the presentation-6 parser fixture (PRESENTATION_V5.md section 19).

Desk Dial r3 release 1 appends to the presentation-5 contract: the layouts lights / lightsbig / scenes, the ring
styles bri / ctemp (ring.kelvin int 2200..6500, required there) and clusters (1 <= count <= 20, index < count),
ring.kelvin validated on every style and kept only on bri / ctemp, valueUnit ("%" | "K", kept on lightsbig),
prevTitle / nextTitle (text <= 64 B, kept on scenes) and the icons bulb thermo power wand house album. [r3.1] appends
the crumb `playlists`, the ring style `queue` (count >= 1, index < count; `now` kept on it) and `holdMarker` (bool).

Every case is a wire frame (``input``) that is valid presentation 5 apart from the presentation-6 content under
test, with the verdict written here by hand (an independent reading of section 19):
``expect.accept`` and, when accepted, ``expect.stored`` = {layout, ringStyle, ringKelvin, valueUnit, prevTitle,
nextTitle}. ``kelvin`` lists [K, r, g, b] for K = 2200..6500 (README r3 section 3, Tanner Helland, rounded half
up; CC_KELVIN_GAIN 255 = as designed) and ``kelvinTieMargin`` the smallest distance of a channel to a .5 tie
(the libm-independence margin, > 1e-6 required).

parse_tests.py holds both readings to it: ``control_center.lcd_preview.v6_parse`` (Python) and the firmware's
``cc_parse_frame`` (C++, MSVC /W4 /WX) including ``cc_kelvin_rgb`` for every K. Usage:
    .venv\\Scripts\\python.exe harness\\make_frames_v6.py [--check]
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import sys

OUTPUT = Path(__file__).resolve().parent / 'fixtures' / 'frames_v6.json'

BUTTONS = [{'label': 'Home', 'enabled': True, 'icon': 'house'}, {'label': 'Scenes', 'enabled': True, 'icon': 'wand'},
           {'label': 'Temp', 'enabled': True, 'icon': 'thermo'}, {'label': 'All off', 'enabled': True, 'icon': 'power'}]
SCENE_BUTTONS = [{'label': 'Back', 'enabled': True, 'icon': 'back'}, {'label': '', 'enabled': False, 'icon': ''},
                 {'label': '', 'enabled': False, 'icon': ''}, {'label': 'Run', 'enabled': True, 'icon': 'switch'}]
HOME_BUTTONS = [{'label': 'Music', 'enabled': True, 'icon': 'list'}, {'label': 'Windows', 'enabled': True, 'icon': 'win'},
                {'label': 'Lights', 'enabled': True, 'icon': 'bulb'}, {'label': 'Pause', 'enabled': True, 'icon': 'pause'}]


def lights(layout='lights', ring=None, **extra):
    frame = {'id': 41, 'mode': 'LIGHTS', 'target': 'Hall', 'value': '', 'detail': '', 'status': '', 'layout': layout,
             'heading': 'LIGHTS', 'title': 'Focus', 'subtitle': '62% · 3200 K', 'meta': 'Knob: temperature',
             'metaTone': 'secondary', 'ledStyle': 'color', 'buttons': copy.deepcopy(BUTTONS),
             'ring': ring or {'style': 'bri', 'value': 62, 'index': 0, 'count': 0, 'kelvin': 3200}}
    frame.update(extra)
    return frame


def big(style='bri', **extra):
    ring = ({'style': 'ctemp', 'value': 23, 'index': 0, 'count': 0, 'kelvin': 3200} if style == 'ctemp'
            else {'style': 'bri', 'value': 62, 'index': 0, 'count': 0, 'kelvin': 3200})
    frame = lights('lightsbig', ring, volumeCaption='Colour temperature' if style == 'ctemp' else 'Brightness',
                   value='3200' if style == 'ctemp' else '62')
    frame.update(extra)
    return frame


def scenes(count=5, index=2, **extra):
    frame = {'id': 42, 'mode': 'SCENES', 'target': 'Hall', 'value': '', 'detail': '', 'status': '', 'layout': 'scenes',
             'heading': 'SCENES', 'title': 'Movie', 'prevTitle': 'Evening', 'nextTitle': 'Reading',
             'meta': '3 / 5 · 12% · 2200 K', 'ledStyle': 'color', 'buttons': copy.deepcopy(SCENE_BUTTONS),
             'ring': {'style': 'clusters', 'value': 0, 'index': index, 'count': count}}
    frame.update(extra)
    return frame


def home(**extra):
    frame = {'id': 40, 'mode': 'HOME', 'target': 'Hall', 'value': '54%', 'detail': '', 'status': '', 'layout': 'nowPlaying',
             'title': 'Pressure Front', 'subtitle': 'Mira Vale', 'buttons': copy.deepcopy(HOME_BUTTONS),
             'ring': {'style': 'level', 'value': 54, 'index': 0, 'count': 101}}
    frame.update(extra)
    return frame


def ring_of(frame, **changes):
    out = copy.deepcopy(frame)
    out['ring'].update(changes)
    return out


def without(frame, *path):
    out = copy.deepcopy(frame)
    target = out
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return out


def stored(layout, style, kelvin=0, unit='%', prev='', nxt='', crumb='', hold=False, now=-1):
    return {'layout': layout, 'ringStyle': style, 'ringKelvin': kelvin, 'valueUnit': unit, 'prevTitle': prev,
            'nextTitle': nxt, 'crumb': crumb, 'holdMarker': hold, 'ringNow': now}


def tracks(**extra):
    """[r3.1] the whole-queue Tracks: a queue ring (focus 8 of 24, the playing row 6)."""
    frame = {'id': 44, 'mode': 'TRACKS', 'target': 'Hall', 'value': '', 'detail': '', 'status': '', 'layout': 'tracks',
             'heading': 'TRACKS', 'title': 'Stjarn-a-fold', 'subtitle': 'Skip to', 'meta': '9 / 24 \u00b7 4 plays',
             'crumb': 'tracks',
             'buttons': [{'label': 'Back', 'enabled': True, 'icon': 'back'},
                         {'label': 'Up next', 'enabled': True, 'icon': 'expand'},
                         {'label': 'Seek', 'enabled': True, 'icon': 'seek'},
                         {'label': 'Play', 'enabled': True, 'icon': 'play'}],
             'ring': {'style': 'queue', 'value': 0, 'index': 8, 'count': 24, 'first': 0, 'now': 6}}
    frame.update(extra)
    return frame


def windows(**extra):
    frame = {'id': 43, 'mode': 'WINDOWS', 'target': 'DESKTOP', 'value': '', 'detail': '', 'status': '',
             'layout': 'windows', 'title': 'Model training review', 'subtitle': 'Claude', 'meta': '2 / 8',
             'buttons': [{'label': 'Home', 'enabled': True, 'icon': 'house'},
                         {'label': 'Snap left', 'enabled': True, 'icon': 'snapleft'},
                         {'label': 'Snap right', 'enabled': True, 'icon': 'snapright'},
                         {'label': 'Switch', 'enabled': True, 'icon': 'switch'}],
             'ring': {'style': 'marker', 'value': 0, 'index': 1, 'count': 8}, 'crumb': 'windows'}
    frame.update(extra)
    return frame


LONG = 'Late evening, candles and a long quiet read by the windows ' + 'é' * 4   # 67 B; 63 B kept (whole code points)


def cases():
    out = []

    def add(name, note, frame, accept, expect=None):
        case = {'name': name, 'note': note, 'input': frame, 'expect': {'accept': accept}}
        if accept:
            case['expect']['stored'] = expect
        out.append(case)

    add('v6-lights-bri', 'Lights text screen: bri ring 62 % in 3200 K; the four new icons', lights(), True,
        stored('lights', 'bri', 3200))
    add('v6-lights-bri-2200', 'kelvin lower bound', ring_of(lights(), kelvin=2200), True, stored('lights', 'bri', 2200))
    add('v6-lights-bri-6500', 'kelvin upper bound', ring_of(lights(), kelvin=6500), True, stored('lights', 'bri', 6500))
    add('v6-lights-off', 'Lights off: ring off, no kelvin', lights(ring={'style': 'off', 'value': 0, 'index': 0, 'count': 0},
                                                                    title='Lights off', subtitle='Tap 4 to turn on'),
        True, stored('lights', 'off'))
    add('v6-lights-ctemp', 'Lights text screen in temperature mode: ctemp ring',
        lights(ring={'style': 'ctemp', 'value': 23, 'index': 0, 'count': 0, 'kelvin': 3200}), True,
        stored('lights', 'ctemp', 3200))
    add('v6-lightsbig-bri', 'the brightness reveal, valueUnit "%"', big(valueUnit='%'), True,
        stored('lightsbig', 'bri', 3200))
    add('v6-lightsbig-ctemp-k', 'the temperature reveal, valueUnit "K"', big('ctemp', valueUnit='K'), True,
        stored('lightsbig', 'ctemp', 3200, 'K'))
    add('v6-lightsbig-unit-absent', 'valueUnit absent = "%"', big('ctemp'), True, stored('lightsbig', 'ctemp', 3200))
    add('v6-unit-k-on-lights-stripped', 'a valid valueUnit outside lightsbig is stripped', lights(valueUnit='K'), True,
        stored('lights', 'bri', 3200))
    add('v6-unit-k-on-volume-stripped', 'a presentation-5 layout keeps "%"', home(layout='volume', valueUnit='K'), True,
        stored('volume', 'level'))
    add('v6-unit-lowercase-rejected', 'valueUnit is length-aware and case-sensitive', big('ctemp', valueUnit='k'), False)
    add('v6-unit-empty-rejected', 'valueUnit "" is not a unit', big(valueUnit=''), False)
    add('v6-unit-number-rejected', 'valueUnit must be a string token', big(valueUnit=1), False)
    add('v6-unit-invalid-on-home-rejected', 'invalid on every layout', home(valueUnit='%%'), False)
    add('v6-scenes', 'scenes list: prev / current / next, clusters 5 at 2', scenes(), True,
        stored('scenes', 'clusters', 0, '%', 'Evening', 'Reading'))
    add('v6-scenes-first', 'the first scene: no prevTitle', without(scenes(index=0), 'prevTitle'), True,
        stored('scenes', 'clusters', 0, '%', '', 'Reading'))
    add('v6-scenes-one', 'one scene: count 1, index 0, no neighbours',
        without(without(scenes(count=1, index=0), 'prevTitle'), 'nextTitle'), True, stored('scenes', 'clusters'))
    add('v6-scenes-twenty', 'count 20 (the clusters maximum), index 19', scenes(count=20, index=19, nextTitle=''), True,
        stored('scenes', 'clusters', 0, '%', 'Evening', ''))
    add('v6-scenes-long-prev', 'prevTitle over 64 B is cut at the last whole code point', scenes(prevTitle=LONG), True,
        stored('scenes', 'clusters', 0, '%', LONG.encode('utf-8')[:64].decode('utf-8', 'ignore'), 'Reading'))
    add('v6-titles-on-lights-stripped', 'prevTitle / nextTitle outside scenes are stripped',
        lights(prevTitle='Evening', nextTitle='Reading'), True, stored('lights', 'bri', 3200))
    add('v6-prev-number-rejected', 'prevTitle must be text', scenes(prevTitle=5), False)
    add('v6-next-control-rejected', 'a control character rejects (as every text field)', scenes(nextTitle='A\nB'), False)
    add('v6-prev-invalid-on-lights-rejected', 'validated on every layout', lights(prevTitle=None), False)
    add('v6-clusters-count-0-rejected', 'clusters needs count >= 1', ring_of(scenes(), count=0, index=0), False)
    add('v6-clusters-count-21-rejected', 'clusters needs count <= 20', ring_of(scenes(), count=21, index=3), False)
    add('v6-clusters-index-count-rejected', 'clusters needs index < count', ring_of(scenes(), count=5, index=5), False)
    add('v6-clusters-on-lights', 'a clusters ring is valid on any layout', lights(ring={'style': 'clusters', 'value': 0,
                                                                                         'index': 1, 'count': 3}),
        True, stored('lights', 'clusters'))
    add('v6-bri-no-kelvin-rejected', 'kelvin is required on bri', without(lights(), 'ring', 'kelvin'), False)
    add('v6-ctemp-no-kelvin-rejected', 'kelvin is required on ctemp', without(big('ctemp'), 'ring', 'kelvin'), False)
    add('v6-kelvin-2199-rejected', 'kelvin below 2200', ring_of(lights(), kelvin=2199), False)
    add('v6-kelvin-6501-rejected', 'kelvin above 6500', ring_of(lights(), kelvin=6501), False)
    add('v6-kelvin-string-rejected', 'kelvin must be an int', ring_of(lights(), kelvin='3200'), False)
    add('v6-kelvin-bool-rejected', 'kelvin must be an int, never a bool', ring_of(lights(), kelvin=True), False)
    add('v6-kelvin-float-rejected', 'kelvin must be an int, never a float', ring_of(lights(), kelvin=3200.5), False)
    add('v6-kelvin-on-level-stripped', 'a valid kelvin on another style is stripped (0)', ring_of(home(), kelvin=4000),
        True, stored('nowPlaying', 'level'))
    add('v6-kelvin-on-clusters-stripped', 'stripped on clusters', ring_of(scenes(), kelvin=4000), True,
        stored('scenes', 'clusters', 0, '%', 'Evening', 'Reading'))
    add('v6-kelvin-invalid-on-level-rejected', 'validated on every style', ring_of(home(), kelvin=100), False)
    add('v6-style-unknown-rejected', 'an unknown ring style', ring_of(lights(), style='hue'), False)
    add('v6-layout-unknown-rejected', 'an unknown layout', lights(layout='lamp'), False)
    add('v6-icon-unknown-rejected', 'an unknown icon token', lights(buttons=[dict(b, icon='lamp') if i == 0 else b
                                                                             for i, b in enumerate(BUTTONS)]), False)
    add('v6-home-r3-icons', 'Home (r3 launcher) with the bulb icon on a presentation-5 layout', home(), True,
        stored('nowPlaying', 'level'))
    # Section 19.9 (the r3 navigation): crumb, the warm tone, feedback.moment refused, the marker ring.
    for token in ('music', 'recent', 'onScreenRecent', 'onScreenPlaylists', 'tracks', 'upnext', 'windows', 'lights',
                  'scenes', 'playlists'):                     # r3.1 appends playlists (MUSIC › PLAYLISTS)
        add('v6-crumb-' + token, 'crumb "' + token + '" on a Home layout', home(crumb=token), True,
            stored('nowPlaying', 'level', crumb=token))
    add('v6-crumb-on-lights', 'crumb on a presentation-6 layout', lights(crumb='lights'), True,
        stored('lights', 'bri', 3200, crumb='lights'))
    add('v6-crumb-unknown-rejected', 'an unknown crumb token', home(crumb='home'), False)
    add('v6-crumb-empty-rejected', 'crumb "" is not a token (absent = none)', home(crumb=''), False)
    add('v6-crumb-case-rejected', 'crumb tokens are case-sensitive', home(crumb='Music'), False)
    add('v6-crumb-playlists-case-rejected', 'r3.1: `Playlists` is not the token', home(crumb='Playlists'), False)
    add('v6-crumb-playlist-singular-rejected', 'r3.1: `playlist` is not the token', home(crumb='playlist'), False)
    add('v6-crumb-number-rejected', 'crumb must be a string token', home(crumb=1), False)
    add('v6-tone-warm', 'metaTone / statusTone "warm"', lights(metaTone='warm', statusTone='warm'), True,
        stored('lights', 'bri', 3200))
    add('v6-tone-amber-rejected', 'an unknown line tone', lights(metaTone='amber'), False)
    add('v6-refused-err', 'feedback err + moment refused (the unavailable-press flash)',
        home(feedback={'kind': 'err', 'seq': 7, 'moment': 'refused'}), True, stored('nowPlaying', 'level'))
    add('v6-refused-ok-stripped', 'refused with kind ok is stripped (moment none)',
        home(feedback={'kind': 'ok', 'seq': 7, 'moment': 'refused'}), True, stored('nowPlaying', 'level'))
    add('v6-moment-unknown-rejected', 'an unknown moment', home(feedback={'kind': 'err', 'seq': 7, 'moment': 'deny'}),
        False)
    add('v6-marker', 'the r3 Windows screen: marker ring 1 of 8, crumb windows', windows(), True,
        stored('windows', 'marker', crumb='windows'))
    add('v6-marker-one', 'marker with one entry', windows(ring={'style': 'marker', 'value': 0, 'index': 0, 'count': 1}),
        True, stored('windows', 'marker', crumb='windows'))
    add('v6-marker-many', 'marker with 40 entries (the window rule applies to first as on every style)',
        windows(ring={'style': 'marker', 'value': 0, 'index': 39, 'count': 40, 'first': 20}), True,
        stored('windows', 'marker', crumb='windows'))
    add('v6-marker-count-0-rejected', 'marker needs count >= 1',
        windows(ring={'style': 'marker', 'value': 0, 'index': 0, 'count': 0}), False)
    add('v6-marker-index-rejected', 'marker needs index < count',
        windows(ring={'style': 'marker', 'value': 0, 'index': 8, 'count': 8}), False)
    # [r3.1] section 19.10: the queue ring (ring.now kept on it), holdMarker.
    add('v6-queue-tracks', 'r3.1 whole-queue Tracks: queue ring 9 of 24, now 6', tracks(), True,
        stored('tracks', 'queue', crumb='tracks', now=6))
    add('v6-queue-no-now', 'r3.1 queue without now: none playing (-1)', without(tracks(), 'ring', 'now'), True,
        stored('tracks', 'queue', crumb='tracks'))
    add('v6-queue-now-minus-one', 'r3.1 queue now -1 (none)', ring_of(tracks(), now=-1), True,
        stored('tracks', 'queue', crumb='tracks'))
    add('v6-queue-one', 'r3.1 queue of one row', ring_of(without(tracks(), 'ring', 'first'), count=1, index=0, now=0),
        True, stored('tracks', 'queue', crumb='tracks', now=0))
    add('v6-queue-upnext', 'r3.1 Up next on the queue ring, with holdMarker',
        tracks(layout='upnext', mode='UP NEXT', crumb='upnext', holdMarker=True), True,
        stored('upnext', 'queue', crumb='upnext', hold=True, now=6))
    add('v6-queue-count-0-rejected', 'r3.1 queue needs count >= 1',
        ring_of(without(tracks(), 'ring', 'first'), count=0, index=0, now=-1), False)
    add('v6-queue-index-rejected', 'r3.1 queue needs index < count', ring_of(tracks(), index=24, first=4), False)
    add('v6-queue-now-count-rejected', 'r3.1 queue now must be < count', ring_of(tracks(), now=24), False)
    add('v6-queue-now-minus-two-rejected', 'r3.1 queue now must be >= -1', ring_of(tracks(), now=-2), False)
    add('v6-queue-now-bool-rejected', 'r3.1 queue now must be an integer', ring_of(tracks(), now=True), False)
    add('v6-queue-kelvin-stripped', 'r3.1 ring.kelvin validated, stripped on queue', ring_of(tracks(), kelvin=3000),
        True, stored('tracks', 'queue', crumb='tracks', now=6))
    add('v6-now-on-marker-stripped', 'r3.1 now is validated on marker, not kept (only queue / the Up next mirror)',
        ring_of(windows(), now=2), True, stored('windows', 'marker', crumb='windows'))
    add('v6-hold-marker', 'r3.1 holdMarker true on the launcher Home', home(holdMarker=True), True,
        stored('nowPlaying', 'level', hold=True))
    add('v6-hold-marker-false', 'r3.1 holdMarker false = absent', home(holdMarker=False), True,
        stored('nowPlaying', 'level'))
    add('v6-hold-marker-on-lights', 'r3.1 holdMarker on the Home lights domain', lights(holdMarker=True), True,
        stored('lights', 'bri', 3200, hold=True))
    add('v6-hold-marker-string-rejected', 'r3.1 holdMarker must be a bool', home(holdMarker='true'), False)
    add('v6-hold-marker-number-rejected', 'r3.1 holdMarker 1 is not a bool', home(holdMarker=1), False)
    add('v6-home-plain-v5', 'a presentation-5 Home frame without any presentation-6 field',
        home(buttons=[{'label': 'Pause', 'enabled': True, 'icon': 'pause'}, {'label': 'Browse', 'enabled': True, 'icon': 'list'},
                      {'label': 'Tracks', 'enabled': True, 'icon': 'tracks'}, {'label': 'Win', 'enabled': True, 'icon': 'win'}]),
        True, stored('nowPlaying', 'level'))
    return out


def kelvin_table():
    """[K, r, g, b] for 2200..6500 and the smallest distance of a channel to a .5 tie."""
    rows, margin = [], 1.0
    for k in range(2200, 6501):
        t = k / 100
        channels = (255.0 if t <= 66 else 329.7 * math.pow(t - 60, -0.1332),
                    99.47 * math.log(t) - 161.12 if t <= 66 else 288.12 * math.pow(t - 60, -0.0755),
                    255.0 if t >= 66 else 138.52 * math.log(t - 10) - 305.04)
        rgb = []
        for c in channels:
            c = min(255.0, max(0.0, c))
            if 0.0 < c < 255.0:
                margin = min(margin, abs(c - math.floor(c) - 0.5))
            rgb.append(int(math.floor(c + 0.5)))
        rows.append([k] + rgb)
    return rows, margin


def build():
    rows, margin = kelvin_table()
    return {'contract': 'PRESENTATION_V5.md section 19 (presentation 6, Desk Dial r3 release 1)',
            'about': __doc__.split('\n\n')[1].replace('\n', ' '),
            'cases': cases(), 'kelvin': rows, 'kelvinTieMargin': margin}


def dumps(data):
    def one(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    lines = ['{' + f'"contract":{one(data["contract"])},"about":{one(data["about"])},'
             + f'"kelvinTieMargin":{one(data["kelvinTieMargin"])},"cases":[']
    lines.append(',\n'.join(one(c) for c in data['cases']) + '],')
    lines.append('"kelvin":[' + ',\n'.join(one(r) for r in data['kelvin']) + ']}')
    return '\n'.join(lines) + '\n'


def main(argv):
    text = dumps(build())
    if '--check' in argv:
        ok = OUTPUT.is_file() and OUTPUT.read_text(encoding='utf-8') == text
        print(f'{OUTPUT} is ' + ('up to date' if ok else 'out of date; run make_frames_v6.py'))
        return 0 if ok else 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding='utf-8', newline='\n')
    data = json.loads(text)
    print(f'wrote {OUTPUT} ({len(data["cases"])} case(s), {len(data["kelvin"])} kelvin row(s), '
          f'tie margin {data["kelvinTieMargin"]:.3g})')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

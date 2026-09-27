"""Native LCD contact sheets and geometric clipping checks (no rescaling)."""
from pathlib import Path
import json
import math
import sys
from ppm_to_png import convert

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'quiet-listening'
size, gap = 240, 24
background = bytes((28, 30, 32))

def pixels(name):
    magic, dimensions, maximum, data = (root / f'{name}.ppm').read_bytes().split(b'\n', 3)
    assert magic == b'P6' and dimensions == b'240 240' and maximum == b'255'
    return data

def sheet(names, cols, output):
    rows = (len(names) + cols - 1) // cols
    width, height = size * cols + gap * (cols + 1), size * rows + gap * (rows + 1)
    data = bytearray(background * width * height)
    for i, name in enumerate(names):
        source = pixels(name)
        for y in range(size):
            for x in range(size):
                if (x + .5 - 120) ** 2 + (y + .5 - 120) ** 2 > 120 ** 2:
                    continue
                start = (y * size + x) * 3
                dest = (((i // cols) * (size + gap) + gap + y) * width + (i % cols) * (size + gap) + gap + x) * 3
                data[dest:dest + 3] = source[start:start + 3]
    path = root / f'{output}.ppm'
    path.write_bytes(f'P6\n{width} {height}\n255\n'.encode() + data)
    print(convert(path))

names = ('volume', 'recent', 'tracks-neutral', 'windows', 'volume-pending', 'volume-long-max',
         'recent-long', 'recent-more', 'tracks-previous', 'tracks-next', 'recent-loading',
         'windows-error', 'volume-offline', 'windows-closed',
         'volume-normalized-accents', 'recent-normalized-punctuation')
sheet(names[:4], 2, 'quiet-four-controls')
sheet(names, 4, 'quiet-all-states')
report = {}
for name in names:
    data = pixels(name)
    radii = [math.hypot(x + .5 - 120, y + .5 - 120)
             for y in range(size) for x in range(size)
             if any(data[(y * size + x) * 3:(y * size + x) * 3 + 3])]
    report[name] = {'max_text_radius': round(max(radii, default=0), 2),
                    'pixels_outside_round_aperture': sum(radius > 120 for radius in radii)}
(root / 'geometry-checks.json').write_text(json.dumps(report, indent=2) + '\n')
assert not any(value['pixels_outside_round_aperture'] for value in report.values()), report
print('PASS: all rendered text stays within the physical round aperture.')

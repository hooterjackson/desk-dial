"""Check the home playback affordance and preserve all cc3 display scenarios."""
from pathlib import Path
import json
import math

root = Path(__file__).resolve().parent
current, baseline = root / 'cc4-play-pause', root / 'cc3-icons'
legacy = [p for p in baseline.glob('*.ppm')
          if (current / p.name).exists() and not p.name.startswith('icon-')]
assert len(legacy) == 32, 'Expected 16 native product and 16 old-renderer scenarios'
assert all(p.read_bytes() == (current / p.name).read_bytes() for p in legacy), \
    'An existing display scenario changed'

names = ('volume-playing', 'volume-paused', 'volume-pause-pending', 'volume-play-offline')
report = {'existing_scenarios_identical': len(legacy), 'home': {}}
for name in names:
    magic, dimensions, maximum, data = (current / f'{name}.ppm').read_bytes().split(b'\n', 3)
    assert (magic, dimensions, maximum) == (b'P6', b'240 240', b'255')
    points = [(x, y) for y in range(240) for x in range(240)
              if any(data[(y * 240 + x) * 3:(y * 240 + x) * 3 + 3])]
    radii = [math.hypot(x + .5 - 120, y + .5 - 120) for x, y in points]
    footer = [(x, y) for x, y in points if y >= 153]
    clearance = 120 - max(math.hypot(x + .5 - 120, y + .5 - 120) for x, y in footer)
    assert max(radii) < 120 and clearance >= 10, name
    report['home'][name] = {'pixels_outside_aperture': sum(r > 120 for r in radii),
                            'footer_min_clearance_px': round(clearance, 2)}
(current / 'regression-checks.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print('PASS: 32 prior renders unchanged; four home playback states retain >=10 px footer clearance.')

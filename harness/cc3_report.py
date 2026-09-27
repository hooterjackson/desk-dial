"""Compare actual cc2 and cc3 LCD rasters; no font or image packages required."""
from pathlib import Path
import json
import math

root = Path(__file__).resolve().parent
before, after = root / 'quiet-listening', root / 'cc3'
names = ('volume', 'recent', 'tracks-neutral', 'windows', 'volume-pending',
         'volume-long-max', 'recent-long', 'recent-more', 'tracks-previous',
         'tracks-next', 'recent-loading', 'windows-error', 'volume-offline',
         'windows-closed', 'volume-normalized-accents', 'recent-normalized-punctuation')


def measure(folder, name, footer_top):
    magic, size, maximum, data = (folder / f'{name}.ppm').read_bytes().split(b'\n', 3)
    assert (magic, size, maximum) == (b'P6', b'240 240', b'255')
    points = [(x, y) for y in range(240) for x in range(240)
              if any(data[(y * 240 + x) * 3:(y * 240 + x) * 3 + 3])]
    footer = [(x, y) for x, y in points if y >= footer_top]
    radii = [math.hypot(x + .5 - 120, y + .5 - 120) for x, y in points]
    footer_radius = max(math.hypot(x + .5 - 120, y + .5 - 120) for x, y in footer)
    return {
        'max_text_radius_px': round(max(radii), 2),
        'footer_max_radius_px': round(footer_radius, 2),
        'footer_min_radial_bezel_clearance_px': round(120 - footer_radius, 2),
        'footer_ink_bounds_xyxy': [min(x for x, y in footer), min(y for x, y in footer),
                                   max(x for x, y in footer), max(y for x, y in footer)],
        'pixels_outside_aperture': sum(radius > 120 for radius in radii),
    }


report = {
    'source': 'Unscaled 240x240 RGB565 output from the actual LVGL renderer',
    'scope': 'Raster geometry only; physical viewing-angle clearance requires user confirmation',
    'footer_font_px': {'cc2': 12, 'cc3': 14},
    'footer_top_px': {'cc2': 184, 'cc3': 160},
    'states': {name: {'cc2': measure(before, name, 184), 'cc3': measure(after, name, 160)}
               for name in names},
}
assert all(state['cc3']['footer_max_radius_px'] <= 110 for state in report['states'].values())
assert all(state['cc3']['pixels_outside_aperture'] == 0 for state in report['states'].values())
assert all(state['cc3']['footer_min_radial_bezel_clearance_px'] >
           state['cc2']['footer_min_radial_bezel_clearance_px'] for state in report['states'].values())
(after / 'cc2-cc3-clearance.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS: all 16 footer states have at least 10 px radial clearance; every state improves over cc2.')

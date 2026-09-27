"""Compare preserved cc2, the cc3 text draft, and the final icon footer rasters."""
from pathlib import Path
import json
import math

root = Path(__file__).resolve().parent
names = ('volume', 'recent', 'tracks-neutral', 'windows', 'volume-pending',
         'volume-long-max', 'recent-long', 'recent-more', 'tracks-previous',
         'tracks-next', 'recent-loading', 'windows-error', 'volume-offline',
         'windows-closed', 'volume-normalized-accents', 'recent-normalized-punctuation')
versions = {'cc2': ('quiet-listening', 184), 'cc3_text_draft': ('cc3', 160),
            'cc3_icons': ('cc3-icons', 153)}


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
    'scope': 'Raster geometry only; physical viewing-angle acceptance remains a user check',
    'footer_text_font_px': 14,
    'footer_icon_font_px': 16,
    'footer_center_pitch_px': 52,
    'footer_centers_x_px': [42, 94, 146, 198],
    'footer_text_top_px': 155,
    'footer_icon_top_px': 153,
    'states': {name: {version: measure(root / folder, name, top)
                      for version, (folder, top) in versions.items()} for name in names},
}
assert all(state['cc3_icons']['footer_max_radius_px'] <= 110 for state in report['states'].values())
assert all(state['cc3_icons']['pixels_outside_aperture'] == 0 for state in report['states'].values())
(root / 'cc3-icons/footer-clearance.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS: all 16 icon-footer states have at least 10 px radial clearance.')

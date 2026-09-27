"""Export 24px bundled LVGL footer glyph rasters for the companion preview."""
from pathlib import Path
import json
import struct
import sys
import zlib
from ppm_to_png import chunk

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'cc3-icons'
variants = {'white': 0xF0EEE7, 'red': 0xCE7474, 'green': 0x66C991, 'muted': 0x555650}
report = {}
for name in ('close', 'ok', 'play', 'pause'):
    magic, size, maximum, data = (root / f'icon-{name}-sheet.ppm').read_bytes().split(b'\n', 3)
    assert (magic, size, maximum) == (b'P6', b'240 240', b'255')
    lit = [(x - 108, y - 108) for y in range(108, 132) for x in range(108, 132)
           if any(data[(y * 240 + x) * 3:(y * 240 + x) * 3 + 3])]
    report[name] = {'canvas_size': [24, 24], 'native_font_px': 16,
                    'ink_bounds_xyxy': [min(x for x, y in lit), min(y for x, y in lit),
                                         max(x for x, y in lit), max(y for x, y in lit)],
                    'placement': 'Place canvas at footer center x minus 12, y153; do not vertically center the canvas'}
    for variant, color in variants.items():
        rows = []
        for y in range(108, 132):
            row = bytearray(b'\0')
            for x in range(108, 132):
                sample = data[(y * 240 + x) * 3:(y * 240 + x) * 3 + 3]
                # Recover anti-alias coverage from the pure-white glyph render.
                alpha = round(sum(sample) / 3)
                row.extend((color >> 16 & 255, color >> 8 & 255, color & 255, alpha))
            rows.append(row)
        png = b'\x89PNG\r\n\x1a\n'
        png += chunk(b'IHDR', struct.pack('>IIBBBBB', 24, 24, 8, 6, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(b''.join(rows), 9))
        png += chunk(b'IEND', b'')
        target = root / f'icon-{name}-{variant}.png'
        target.write_bytes(png)
        print(target)
(root / 'icon-raster-metrics.json').write_text(json.dumps(report, indent=2) + '\n')

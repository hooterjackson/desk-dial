"""Arrange the four actual LVGL rasters, masking only the physical round aperture."""
from pathlib import Path
import sys
from ppm_to_png import convert

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'rendered'
names = ('before-volume', 'before-recent', 'before-tracks-neutral', 'before-windows')
size, gap = 240, 24
width = height = size * 2 + gap * 3
background = bytes((28, 30, 32))
sheet = bytearray(background * (width * height))
for i, name in enumerate(names):
    magic, dimensions, maximum, pixels = (root / f'{name}.ppm').read_bytes().split(b'\n', 3)
    assert magic == b'P6' and dimensions == b'240 240' and maximum == b'255'
    round_pixels = bytearray(background * (size * size))
    for y in range(size):
        for x in range(size):
            if (x + .5 - size / 2) ** 2 + (y + .5 - size / 2) ** 2 > (size / 2) ** 2:
                continue
            source = (y * size + x) * 3
            round_pixels[source:source + 3] = pixels[source:source + 3]
            target = (((i // 2) * (size + gap) + gap + y) * width + (i % 2) * (size + gap) + gap + x) * 3
            sheet[target:target + 3] = pixels[source:source + 3]
    path = root / f'{name}-round.ppm'
    path.write_bytes(b'P6\n240 240\n255\n' + round_pixels)
    convert(path)
target = root / 'current-four-controls.ppm'
target.write_bytes(f'P6\n{width} {height}\n255\n'.encode() + sheet)
print(convert(target))

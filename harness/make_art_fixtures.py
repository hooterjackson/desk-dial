"""Create the artwork fixtures used by the LVGL harness.

v1 (120 px RGB565), written to app/assets/fixtures/ (data only):
- art-hall-120.rgb565: byte copy of the real Hall cover transfer captured by the
  artwork agent (previews/artwork-transport/hall-now-playing-120.rgb565).
- art-bright-120.rgb565: a synthetic bright, busy cover (saturated diagonal
  stripes plus a high-contrast checker band behind the title area). It is
  passed through the companion's own artwork.prepare_artwork() (imported
  read-only), so it carries the same 0.8 opacity + black readability scrim,
  LANCZOS 240->120 resample and RGB565 little-endian packing as a real
  transfer.
- *.png: 120 px previews decoded back from each .rgb565 file, for eyeballing.

artwork2 (1.0.0-cc5.3, ARTWORK2.md section 5), written to harness/artwork2/:
- cover-hall-240.jpg: the real Hall cover's 240 px composite
  (previews/artwork-transport/hall-now-playing-240.png, already 0.8 opacity +
  scrim) encoded like the host: Pillow JPEG, quality ladder, 4:2:0, optimize,
  baseline, first result <= COVER_MAX_BYTES.
- cover-bright-240.jpg: the synthetic bright cover's 240 px composite from
  prepare_artwork(), encoded the same way.
- cover-detail-240.jpg: a synthetic cover whose detail (1 px lines, a 2 px
  checker, 1 px diagonals) only survives at 240 px, through prepare_artwork()
  and the same encoder: the harness's proof that covers render at full
  resolution (a 120 px path cannot reproduce it).
- cover-progressive-240.jpg: the bright composite as a PROGRESSIVE JPEG, which
  TJpgDec cannot decode (the harness uses it to force an LCD decode failure).
- icon-*.rgb565: synthetic 32x32 RGBA app icons (drawn at 128 px, LANCZOS to
  32, as IconWorker's thumbnails), alpha-composited onto black and packed as
  RGB565 little endian with rounding: exactly 2048 bytes each.
- *.png previews decoded back from the payloads, and manifest.json (name =
  the key the harness frames use; sha_key = the key the host would send).

Constants come from control_center/presentation.py (COVER_*, ICON_*). When the
companion provides artwork.icon_payload(), each icon payload is cross-checked
against it. Deterministic: re-running produces byte-identical output for the
same companion code and Pillow build.

Usage: make_art_fixtures.py [--v1] [--artwork2]   (default: both)
"""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import shutil
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
COMPANION = WORKSPACE / 'app'
FIXTURES = COMPANION / 'assets' / 'fixtures'
DEN_SOURCE = COMPANION / 'previews' / 'artwork-transport' / 'hall-now-playing-120.rgb565'
DEN_240 = COMPANION / 'previews' / 'artwork-transport' / 'hall-now-playing-240.png'
ARTWORK2 = ROOT / 'artwork2'
SIZE, TRANSFER = 240, 120
BYTES = TRANSFER * TRANSFER * 2


def bright_source() -> bytes:
    image = Image.new('RGB', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    colors = [(255, 230, 0), (0, 229, 255), (255, 43, 214), (255, 255, 255), (124, 255, 0), (255, 122, 0)]
    stripe = 12
    for k in range(-SIZE // stripe, 2 * SIZE // stripe + 1):
        x0 = k * stripe
        draw.polygon([(x0, 0), (x0 + stripe, 0), (x0 + stripe - SIZE, SIZE), (x0 - SIZE, SIZE)],
                     fill=colors[k % len(colors)])
    cell = 10
    for y in range(40, 130, cell):
        for x in range(0, SIZE, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(255, 255, 255))
    draw.ellipse([150, 20, 230, 100], fill=(255, 255, 255))
    out = BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def detail_source() -> bytes:
    """A cover whose detail only survives at 240 px: 1 px luma lines, a 2 px checker and
    1 px diagonals in the rows the scrim keeps bright, over a soft two-colour gradient."""
    image = Image.new('RGB', (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        draw.line([(0, y), (SIZE - 1, y)], fill=(int(40 + 150 * t), int(90 + 60 * (1 - t)), int(160 - 80 * t)))
    for x in range(0, SIZE, 2):                              # 1 px vertical lines, rows 8..47
        draw.line([(x, 8), (x, 47)], fill=(250, 250, 250))
    for y in range(52, 92, 2):                               # 2 px checker, rows 52..91
        for x in range(0, SIZE, 4):
            dx = 0 if (y // 2) % 2 == 0 else 2
            draw.rectangle([x + dx, y, x + dx + 1, y + 1], fill=(255, 255, 255))
    for k in range(-SIZE, SIZE, 6):                          # 1 px diagonals, rows 96..139
        draw.line([(k, 96), (k + 44, 139)], fill=(10, 10, 10))
    out = BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def rgb565le_to_image(raw: bytes, side: int) -> Image.Image:
    pixels = bytearray()
    for i in range(0, len(raw), 2):
        value = raw[i] | (raw[i + 1] << 8)
        pixels += bytes((((value >> 11) & 31) * 255 // 31, ((value >> 5) & 63) * 255 // 63, (value & 31) * 255 // 31))
    return Image.frombytes('RGB', (side, side), bytes(pixels))


def preview(raw: bytes, target: Path) -> None:
    rgb565le_to_image(raw, TRANSFER).save(target)


def make_v1(prepare_artwork) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    den = FIXTURES / 'art-hall-120.rgb565'
    if DEN_SOURCE.stat().st_size != BYTES:
        raise SystemExit(f'{DEN_SOURCE} is not {BYTES} bytes')
    shutil.copyfile(DEN_SOURCE, den)
    _, bright_raw, _ = prepare_artwork(bright_source())[:3]
    if len(bright_raw) != BYTES:
        raise SystemExit(f'prepare_artwork returned {len(bright_raw)} bytes, expected {BYTES}')
    bright = FIXTURES / 'art-bright-120.rgb565'
    bright.write_bytes(bright_raw)
    for path in (den, bright):
        preview(path.read_bytes(), path.with_suffix('.png'))
        print(f'{path} ({path.stat().st_size} bytes)')


# ------------------------------------------------------------------ artwork2 --
def cover_jpeg(composite: Image.Image, p) -> tuple:
    """Section 5 host encoder: the first quality of the ladder that fits maxBytes."""
    if composite.size != (p.COVER_SIZE, p.COVER_SIZE) or composite.mode != 'RGB':
        raise SystemExit(f'cover composite must be {p.COVER_SIZE}x{p.COVER_SIZE} RGB, got {composite.size} {composite.mode}')
    for quality in p.COVER_JPEG_QUALITIES:
        out = BytesIO()
        composite.save(out, format='JPEG', quality=quality, subsampling=2, optimize=True, progressive=False)
        data = out.getvalue()
        if len(data) <= p.COVER_MAX_BYTES:
            return data, quality
    raise SystemExit('no quality of the ladder fits COVER_MAX_BYTES')


def icon_source(name: str, p) -> Image.Image:
    """A synthetic app icon: 128 px RGBA drawing, LANCZOS down to ICON_SIZE."""
    big = 128
    image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if name == 'ic-code':      # blue rounded square, white "</>"
        draw.rounded_rectangle([6, 6, big - 7, big - 7], radius=26, fill=(0, 120, 212, 255))
        draw.rounded_rectangle([6, 6, big - 7, 60], radius=26, fill=(58, 160, 255, 255))
        draw.rectangle([6, 40, big - 7, 64], fill=(30, 140, 235, 255))
        white = (255, 255, 255, 255)
        draw.line([(52, 40), (30, 64), (52, 88)], fill=white, width=10, joint='curve')
        draw.line([(76, 40), (98, 64), (76, 88)], fill=white, width=10, joint='curve')
        draw.line([(70, 34), (58, 94)], fill=white, width=8)
    elif name == 'ic-chat':    # orange disc, white speech bubble
        draw.ellipse([4, 4, big - 5, big - 5], fill=(255, 122, 26, 255))
        draw.rounded_rectangle([30, 36, 98, 82], radius=14, fill=(255, 255, 255, 255))
        draw.polygon([(44, 80), (40, 100), (62, 80)], fill=(255, 255, 255, 255))
        for x in (46, 64, 82):
            draw.ellipse([x - 5, 54, x + 5, 64], fill=(255, 122, 26, 255))
    elif name == 'ic-late':    # green diamond with a translucent halo
        draw.ellipse([2, 2, big - 3, big - 3], fill=(110, 217, 150, 90))
        draw.polygon([(64, 12), (116, 64), (64, 116), (12, 64)], fill=(46, 204, 113, 255))
        draw.rectangle([52, 52, 76, 76], fill=(255, 255, 255, 255))
    else:
        raise ValueError(name)
    return image.resize((p.ICON_SIZE, p.ICON_SIZE), Image.Resampling.LANCZOS)


def icon_payload(rgba: Image.Image, p) -> bytes:
    """Section 5: composite onto black (c' = round(c * a / 255); an exact .5 cannot
    occur, so (c * a + 127) // 255 is that rounding), then RGB565 LE with rounding."""
    if rgba.size != (p.ICON_SIZE, p.ICON_SIZE):
        raise SystemExit(f'icon must be {p.ICON_SIZE}x{p.ICON_SIZE}')
    out = bytearray()
    data = rgba.convert('RGBA').tobytes()
    for i in range(0, len(data), 4):
        a = data[i + 3]
        r, g, b = ((c * a + 127) // 255 for c in data[i:i + 3])
        value = (((r * 31 + 127) // 255) << 11) | (((g * 63 + 127) // 255) << 5) | ((b * 31 + 127) // 255)
        out += bytes((value & 0xFF, value >> 8))
    if len(out) != p.ICON_BYTES:
        raise SystemExit(f'icon payload is {len(out)} bytes, expected {p.ICON_BYTES}')
    return bytes(out)


def make_artwork2(prepare_artwork, p, companion_icon_payload) -> None:
    ARTWORK2.mkdir(parents=True, exist_ok=True)
    manifest = {'about': 'artwork2 harness fixtures (ARTWORK2.md section 5), written by make_art_fixtures.py',
                'covers': [], 'broken': [], 'icons': []}
    den = Image.open(DEN_240).convert('RGB')
    bright = prepare_artwork(bright_source())[0].convert('RGB')
    detail = prepare_artwork(detail_source())[0].convert('RGB')
    for name, file, composite in (('a2-hall', 'cover-hall-240.jpg', den), ('a2-bright', 'cover-bright-240.jpg', bright),
                                  ('a2-detail', 'cover-detail-240.jpg', detail)):
        data, quality = cover_jpeg(composite, p)
        (ARTWORK2 / file).write_bytes(data)
        manifest['covers'].append({'name': name, 'file': file, 'bytes': len(data), 'quality': quality,
                                   'sha_key': hashlib.sha256(data).hexdigest()[:p.COVER_KEY_CHARS]})
        print(f'{ARTWORK2 / file} ({len(data)} bytes, q{quality})')
    out = BytesIO()
    bright.save(out, format='JPEG', quality=p.COVER_JPEG_QUALITIES[0], subsampling=2, optimize=True, progressive=True)
    (ARTWORK2 / 'cover-progressive-240.jpg').write_bytes(out.getvalue())
    manifest['broken'].append({'name': 'a2-progressive', 'file': 'cover-progressive-240.jpg',
                               'bytes': len(out.getvalue()),
                               'why': 'progressive JPEG: TJpgDec cannot decode it (forces an LCD decode failure)'})
    for name in ('ic-code', 'ic-chat', 'ic-late'):
        rgba = icon_source(name, p)
        raw = icon_payload(rgba, p)
        if companion_icon_payload is not None:
            key, companion = companion_icon_payload(rgba)
            if companion != raw:
                raise SystemExit(f'{name}: artwork.icon_payload() differs from ARTWORK2.md section 5 as implemented here')
        file = f'icon-{name[3:]}.rgb565'
        (ARTWORK2 / file).write_bytes(raw)
        rgb565le_to_image(raw, p.ICON_SIZE).save(ARTWORK2 / f'icon-{name[3:]}.png')
        manifest['icons'].append({'name': name, 'file': file, 'bytes': len(raw),
                                  'sha_key': hashlib.sha256(raw).hexdigest()[:p.ICON_KEY_CHARS]})
        print(f'{ARTWORK2 / file} ({len(raw)} bytes)')
    (ARTWORK2 / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'{ARTWORK2 / "manifest.json"}')


def main(argv) -> int:
    sys.path.insert(0, str(COMPANION))
    from control_center import presentation  # read-only use of the host constants
    from control_center import artwork       # read-only use of the host pipeline
    wanted = {a for a in argv[1:]} or {'--v1', '--artwork2'}
    unknown = wanted - {'--v1', '--artwork2'}
    if unknown:
        raise SystemExit(f'unknown argument(s) {sorted(unknown)}; usage: make_art_fixtures.py [--v1] [--artwork2]')
    if '--v1' in wanted:
        make_v1(artwork.prepare_artwork)
    if '--artwork2' in wanted:
        make_artwork2(artwork.prepare_artwork, presentation, getattr(artwork, 'icon_payload', None))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

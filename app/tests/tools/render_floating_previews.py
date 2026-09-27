"""PNG previews of the desktop v5 floating knob (FLOATING_KNOB.md sections 2 and 3).

Renders the full floating knob, KnobFace + render_lcd at the overlay's scale, for
scenarios built from tests/fixtures/cc5_frames.json and the design covers and
app icons, at 100 % and 200 % DPI, each over a dark and a light wallpaper, the
way the layered window reaches the screen: KnobFace.compose -> premultiplied
BGRA (the UpdateLayeredWindow bytes) -> composited over the wallpaper, docked
24 logical px from the left edge. Also writes a before/after comparison for Now
Playing: the v4 Tk mirror (240 px LCD LANCZOS-upscaled 1.5x, aliased canvas
polygons) next to the floating knob at the same 1.5 px per design px.

Sample data only: no device, window, network or settings access.

Usage: .venv\\Scripts\\python.exe tests\\tools\\render_floating_previews.py [output_dir]
"""
from __future__ import annotations

from copy import deepcopy
from html import escape
import json
import math
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from control_center import knob_face as kf  # noqa: E402
from control_center import lcd_preview as lp  # noqa: E402
from control_center.artwork import icon_payload, prepare_artwork2  # noqa: E402
from control_center.presentation import RING_SEGMENTS  # noqa: E402
from control_center.preview_lights import PreviewLights  # noqa: E402

DEFAULT_OUT = Path(tempfile.gettempdir()) / 'desk-dial-previews' / 'v5-previews'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'cc5_frames.json'
DESIGN = ROOT / 'design-reference' / 'design_handoff_nano_d_artwork_color' / 'assets'
DPIS = (96, 192)
INSET_LOGICAL = 24          # the overlay's distance from the work area's left edge
HIRES_ICON = 128            # IconWorker's hi-res copy
WALLPAPERS = {
    'dark': ((16, 20, 31), (44, 56, 82), (92, 70, 120)),
    'light': ((242, 238, 230), (206, 214, 226), (236, 214, 190)),
}

# v4 Tk mirror geometry (ui.py before desktop v5): canvas 478 x 545, knob centre (239, 220), 1.5x.
V4_SIZE, V4_CENTRE, V4_SCALE = (478, 545), (239, 220), 1.5
V4_DEVICE_BG, V4_HAIRLINE = (0x14, 0x14, 0x14), (0x2D, 0x2B, 0x2B)
V4_BUTTON = (49, 336, 44, 22, 3)            # left, top, size, gap, strip height (design px, centre 170)
V4_BUTTON_FILL, V4_BUTTON_EDGE = (0x20, 0x20, 0x20), (0x2C, 0x2C, 0x2C)


# --------------------------------------------------------------------------
# Scenario inputs
# --------------------------------------------------------------------------
class Media:
    def __init__(self):
        self.covers = {name: prepare_artwork2((DESIGN / 'covers' / name).read_bytes())
                       for name in ('hounds-of-love.png', 'night-drive-chromatics-album-.jpg')}
        with Image.open(DESIGN / 'apps' / 'claude.png') as source:
            app = source.convert('RGBA')
        self.icon_hires = app.resize((HIRES_ICON, HIRES_ICON), Image.Resampling.LANCZOS)
        self.icon_32 = app.resize((32, 32), Image.Resampling.LANCZOS)   # IconWorker's payload source
        self.icon_key, self.icon_payload = icon_payload(self.icon_32)


def cases():
    data = json.loads(FIXTURES.read_text(encoding='utf-8'))
    return {case['id']: case['frame'] for case in data['cases']}


def volume(frame, percent):
    f = deepcopy(frame)
    f.update(value=f'{percent}%', confirmedVolume=percent)
    f['ring'] = dict(f['ring'], value=percent)
    return f


def scenarios(media):
    """[(name, title, frame, artwork, window_icon, hires_cover, hires_icon)] (artwork2 media)."""
    frames = cases()
    hounds, night = media.covers['hounds-of-love.png'], media.covers['night-drive-chromatics-album-.jpg']

    def with_cover(frame, cover):
        return dict(deepcopy(frame), artKey=cover.jpeg_key)

    def with_icon(frame):
        return dict(deepcopy(frame), iconKey=media.icon_key)

    return [
        ('now-playing', 'Now Playing, design cover (Hounds of Love)', with_cover(frames['home'], hounds),
         hounds.jpeg, None, hounds.hires_jpeg, None),
        ('volume-85', 'Volume 85 % (amber)', with_cover(volume(frames['led-vol-86'], 85), hounds),
         hounds.jpeg, None, hounds.hires_jpeg, None),
        ('volume-95', 'Volume 95 % (red)', with_cover(volume(frames['led-vol-86'], 95), hounds),
         hounds.jpeg, None, hounds.hires_jpeg, None),
        ('recent', 'Recent: coloured markers, hi-res cover', with_cover(frames['ra-night-drive'], night),
         night.jpeg, None, night.hires_jpeg, None),
        ('windows-open', 'Windows: hi-res app icon (open)', with_icon(frames['wi-brw']),
         None, media.icon_payload, None, media.icon_hires),
        ('windows-closed', 'Windows: hi-res app icon (closed)', with_icon(frames['wi-closed-claude']),
         None, media.icon_payload, None, media.icon_hires),
        ('tracks', 'Tracks', with_cover(frames['tr-neu'], hounds), hounds.jpeg, None, hounds.hires_jpeg, None),
        ('idle', 'Idle', with_cover(frames['home-pidle'], hounds), hounds.jpeg, None, hounds.hires_jpeg, None),
    ]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def wallpaper(kind, size):
    """A soft three-colour gradient (no external image)."""
    top, bottom, glow = WALLPAPERS[kind]
    width, height = size
    column = Image.new('RGB', (1, height))
    column.putdata([tuple(round(a + (b - a) * y / max(1, height - 1)) for a, b in zip(top, bottom))
                    for y in range(height)])
    image = column.resize(size)
    spot = Image.new('L', size, 0)
    ImageDraw.Draw(spot).ellipse((width // 2, -height // 3, width * 3 // 2, height // 2), fill=120)
    image.paste(glow, (0, 0), spot.filter(ImageFilter.GaussianBlur(max(width, height) / 10)))
    return image.convert('RGBA')


def on_screen(face_image, dpi, kind):
    """The frame as DWM shows it: the premultiplied BGRA bytes over a wallpaper, docked left."""
    width, height = face_image.size
    data = kf.premultiplied_bgra(face_image)
    premultiplied = Image.frombuffer('RGBA', (width, height), data, 'raw', 'BGRA', 0, 1)
    straight = Image.frombytes('RGBa', (width, height), premultiplied.tobytes()).convert('RGBA')
    unit = dpi / 96
    inset, margin = round(INSET_LOGICAL * unit), round(40 * unit)
    canvas = wallpaper(kind, (width + inset + round(160 * unit), height + 2 * margin))
    canvas.alpha_composite(straight, (inset, margin))
    return canvas.convert('RGB')


def render_face(face, scenario):
    _, _, frame, artwork, window_icon, hires_cover, hires_icon = scenario
    lcd = lp.render_lcd(frame, artwork, window_icon, artwork2=True, scale=face.scale,
                        hires_cover=hires_cover, hires_icon=hires_icon)
    drives, _ = PreviewLights().render(frame, 0, 0)
    return face.compose(lcd, kf.ring_colors(frame, drives))


def v4_mirror(scenario):
    """The v4 Tk canvas mirror: 240 px LCD LANCZOS-upscaled 1.5x, aliased polygons and oval."""
    _, _, frame, artwork, window_icon, _, _ = scenario
    image = Image.new('RGB', V4_SIZE, V4_DEVICE_BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, V4_SIZE[0] - 1, V4_SIZE[1] - 1), outline=V4_HAIRLINE, width=2)
    cx, cy = V4_CENTRE
    r = kf.DISC_RADIUS * V4_SCALE
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=kf.DISC_RGB, outline=kf.DISC_EDGE_RGB, width=1)
    lcd = lp.render_lcd(frame, artwork, window_icon, artwork2=True)
    px = round(240 * V4_SCALE)
    lcd = lcd.resize((px, px), Image.Resampling.LANCZOS)
    image.paste(lcd.convert('RGB'), (cx - px // 2, cy - px // 2), lcd.getchannel('A'))
    drives, buttons = PreviewLights().render(frame, 0, 0)
    palette = kf.ring_palette(frame)
    for index in range(RING_SEGMENTS):
        theta = math.radians(index * 6)
        cos, sin = math.cos(theta), math.sin(theta)
        points = [(cx + (lx * cos - ly * sin) * V4_SCALE, cy + (lx * sin + ly * cos) * V4_SCALE)
                  for lx, ly in ((-2, -143), (2, -143), (2, -133), (-2, -133))]
        draw.polygon(points, fill=kf.ring_display(drives[index], palette))
    left, top, size, gap, strip = V4_BUTTON
    for slot in range(4):
        x0 = cx + (left + slot * (size + gap) - 170) * V4_SCALE
        y0 = cy + (top - 170) * V4_SCALE
        x1, y1 = x0 + size * V4_SCALE, y0 + size * V4_SCALE
        draw.rectangle((x0, y0, x1, y1), fill=V4_BUTTON_FILL, outline=V4_BUTTON_EDGE)
        draw.rectangle((x0, y1, x1, y1 + strip * V4_SCALE), fill=kf.strip_display(buttons[slot]))
    return image


def place(layer, image, centre):
    """alpha_composite ``image`` centred on ``centre`` of ``layer``, clipped to the layer."""
    x, y = centre[0] - image.width // 2, centre[1] - image.height // 2
    box = (max(0, -x), max(0, -y), min(image.width, layer.width - x), min(image.height, layer.height - y))
    layer.alpha_composite(image.crop(box), (x + box[0], y + box[1]))


def caption(image, text, size=15):
    draw = ImageDraw.Draw(image)
    draw.text((12, 10), text, font=lp.font(size), fill=(235, 235, 235))


def before_after(scenario, out):
    """Side by side at the same 1.5 px per design px, plus 3x nearest-neighbour zooms."""
    before = v4_mirror(scenario)
    face = kf.KnobFace(V4_SCALE)
    after_face = render_face(face, scenario)
    layer = Image.new('RGBA', V4_SIZE, V4_DEVICE_BG + (255,))
    place(layer, after_face, V4_CENTRE)      # the same knob centre and px per design px as the v4 mirror
    after = layer.convert('RGB')
    cx, cy = V4_CENTRE
    zoom_box = (cx - 60, cy - 125, cx + 110, cy - 45)   # title text and the ring's top-right segments
    zoom = 3
    zw, zh = (zoom_box[2] - zoom_box[0]) * zoom, (zoom_box[3] - zoom_box[1]) * zoom
    gap = 16
    sheet = Image.new('RGB', (2 * V4_SIZE[0] + 3 * gap, 44 + V4_SIZE[1] + gap + 30 + zh + gap), (24, 24, 24))
    for column, (image, label) in enumerate(((before, 'Before: v4 mirror (240 LCD upscaled 1.5x, aliased ring)'),
                                             (after, 'After: floating knob (LCD painted at 1.5x, AA ring + glow)'))):
        x = gap + column * (V4_SIZE[0] + gap)
        panel = Image.new('RGB', (V4_SIZE[0], 40), (24, 24, 24))
        caption(panel, label, 13)
        sheet.paste(panel, (x, 4))
        sheet.paste(image, (x, 44))
        crop = image.crop(zoom_box).resize((zw, zh), Image.Resampling.NEAREST)
        label_panel = Image.new('RGB', (V4_SIZE[0], 30), (24, 24, 24))
        caption(label_panel, f'{zoom}x zoom (nearest neighbour)', 12)
        sheet.paste(label_panel, (x, 44 + V4_SIZE[1] + gap - 6))
        sheet.paste(crop, (x, 44 + V4_SIZE[1] + gap + 24))
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((x + zoom_box[0] - 1, 44 + zoom_box[1] - 1, x + zoom_box[2], 44 + zoom_box[3]),
                       outline=(255, 200, 0))
    path = out / 'now-playing-before-after.png'
    sheet.save(path)
    return path


def main(argv):
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    media = Media()
    rows, written = [], []
    started = time.perf_counter()
    faces = {dpi: kf.KnobFace(kf.scale_for(dpi)) for dpi in DPIS}
    for scenario in scenarios(media):
        name, title = scenario[:2]
        cells = []
        for dpi in DPIS:
            face = faces[dpi]
            image = render_face(face, scenario)
            for kind in WALLPAPERS:
                path = out / f'{name}-{dpi * 100 // 96}pct-{kind}.png'
                on_screen(image, dpi, kind).save(path)
                written.append(path)
                cells.append((f'{dpi * 100 // 96} % DPI, {kind}', path.name,
                              f'ring {round(286 * face.scale)} px, LCD {face.lcd_px} px, box {face.size[0]} px'))
        rows.append((title, cells))
    comparison = before_after(scenarios(media)[0], out)
    written.append(comparison)
    html = ['<!doctype html><meta charset="utf-8"><title>Nano_D++ floating knob previews</title>',
            '<style>body{background:#1b1a1a;color:#eee;font:14px Segoe UI,sans-serif;margin:24px}'
            'figure{display:inline-block;margin:0 16px 16px 0;vertical-align:top}'
            'img{max-width:100%;border:1px solid #333}figcaption{color:#aaa;margin:4px 0}</style>',
            '<h1>Floating knob previews (desktop v5)</h1>',
            f'<h2>Before / after</h2><img src="{escape(comparison.name)}">']
    for title, cells in rows:
        html.append(f'<h2>{escape(title)}</h2>')
        for label, name, detail in cells:
            html.append(f'<figure><figcaption>{escape(label)}: {escape(detail)}</figcaption>'
                        f'<img src="{escape(name)}"></figure>')
    (out / 'index.html').write_text('\n'.join(html) + '\n', encoding='utf-8')
    print(f'wrote {len(written)} PNGs and index.html to {out} in {time.perf_counter() - started:.1f} s')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

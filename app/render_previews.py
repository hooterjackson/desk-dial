"""Export cc5 mirror previews for every case in tests/fixtures/cc5_frames.json.

Writes to previews/cc5/:

* ``<id>-lcd.png``: ``lcd_preview.render_lcd`` at the knob's native 240 px, with
  the case's art fixture (assets/fixtures/<art>.rgb565) where the frame has one.
* ``<id>-device.png``: the desktop mirror composite at 2x: the 60 Knob Face ring
  segments (PreviewLights drive colours shown with the optical level mapping,
  the same helpers the Tk mirror uses), the bezel disc, the LCD and the four
  physical button strips.
* ``index.html``: a contact sheet of both.

Sample data only; no device, network or desktop access. The LEDs are the
settled state of a freshly reset PreviewLights (no decay or pulse phase). A
fresh renderer seeds lastSeq from the first frame without flashing (contract
section 5.8), so a frame carrying ``feedback`` (the flash-* cases) is drawn with
its flash instead: ``ring_pixels(frame, 0, kind)``, the flash drawn last over
the same settled ring. Both match the fixture's golden ``leds``.

Usage: .venv\\Scripts\\python.exe render_previews.py [output_dir]
"""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw

from control_center.lcd_preview import render_lcd
from control_center.preview_lights import PreviewLights, ring_pixels
from control_center.presentation import RING_SEGMENTS
from control_center.ui import (
    BG, BUTTON_EDGE, BUTTON_FILL, DEVICE_BG, DISC_EDGE, DISC_FILL, DISC_RADIUS, KNOB_CENTRE,
    LED_PALETTE, SECONDARY, STRIP_HEIGHT, TEXT, button_box, ring_display, ring_palette,
    segment_polygon, strip_display,
)

ROOT = Path(__file__).resolve().parent
FRAMES = ROOT / "tests" / "fixtures" / "cc5_frames.json"
OUT = ROOT / "previews" / "cc5"
DEVICE_SIZE = (340, 400)   # Knob Face device box; LCD at (50, 50), centre (170, 170)
SCALE = 2                  # exported device scale
SUPERSAMPLE = 4            # ring/buttons are drawn at SCALE * SUPERSAMPLE, then reduced


def load_art(name):
    """The case's 28,800-byte RGB565 art fixture, or None."""
    if not name:
        return None
    path = ROOT / "assets" / "fixtures" / f"{name}.rgb565"
    return path.read_bytes() if path.is_file() else None


def flash_kind(frame):
    """The flash a frame's ``feedback`` triggers ("ok" / "err"), or None (PreviewLights' validity rule)."""
    feedback = frame.get("feedback") if isinstance(frame, dict) else None
    if not isinstance(feedback, dict) or feedback.get("kind") not in ("ok", "err"):
        return None
    seq = feedback.get("seq")
    valid = isinstance(seq, int) and not isinstance(seq, bool) and 1 <= seq <= 0x7FFFFFFF
    return feedback["kind"] if valid else None


def lights(frame):
    """(60 ring, 4 button) drive colours for one frame; None = host lost (all dark).

    The settled state of a freshly reset PreviewLights; a feedback frame shows
    its flash (a fresh renderer would only seed lastSeq and never flash).
    """
    if not isinstance(frame, dict):
        return [0] * RING_SEGMENTS, [0] * 4
    ring, buttons = PreviewLights().render(frame, 0, 0)
    kind = flash_kind(frame)
    if kind:
        ring = ring_pixels(frame, 0, kind)
    return ring, buttons


def device_image(frame, art=None, scale=SCALE):
    """The mirror composite for one frame (RGB, DEVICE_SIZE * scale); None = host lost (all dark)."""
    ring, buttons = lights(frame)
    palette = ring_palette(frame or {})
    big = scale * SUPERSAMPLE
    width, height = DEVICE_SIZE[0] * big, DEVICE_SIZE[1] * big
    centre = (KNOB_CENTRE * big, KNOB_CENTRE * big)
    image = Image.new("RGB", (width, height), DEVICE_BG)
    draw = ImageDraw.Draw(image)
    for i in range(RING_SEGMENTS):
        points = segment_polygon(i, centre, big)
        draw.polygon(list(zip(points[::2], points[1::2])), fill=ring_display(ring[i], palette))
    radius = DISC_RADIUS * big
    draw.ellipse((centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius),
                 fill=DISC_FILL, outline=DISC_EDGE, width=big)
    for slot in range(4):
        x0, y0, x1, y1 = button_box(slot, centre, big)
        draw.rectangle((x0, y0, x1, y1), fill=BUTTON_FILL, outline=BUTTON_EDGE, width=big)
        draw.rectangle((x0, y1, x1, y1 + STRIP_HEIGHT * big), fill=strip_display(buttons[slot], LED_PALETTE))
    image = image.resize((DEVICE_SIZE[0] * scale, DEVICE_SIZE[1] * scale), Image.Resampling.LANCZOS)
    lcd = render_lcd(frame, art).resize((240 * scale, 240 * scale), Image.Resampling.LANCZOS)
    offset = (KNOB_CENTRE - 120) * scale
    image.paste(lcd, (offset, offset), lcd)
    return image


def main(out=OUT):
    data = json.loads(FRAMES.read_text(encoding="utf-8"))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in data["cases"]:
        frame, art = case["frame"], load_art(case.get("art"))
        name = case["id"]
        render_lcd(frame, art).save(out / f"{name}-lcd.png")
        device_image(frame, art).save(out / f"{name}-device.png")
        rows.append(f'<figure><img src="{escape(name)}-device.png" width="340" height="400">'
                    f'<img src="{escape(name)}-lcd.png" width="240" height="240">'
                    f'<figcaption>{escape(case.get("name", name))}<br><small>{escape(case.get("note", ""))}'
                    f'</small></figcaption></figure>')
    html = (f'<!doctype html><meta charset="utf-8"><title>Nano_D++ cc5 mirror previews</title>'
            f'<style>body{{background:{BG};color:{TEXT};font:14px Archivo,Segoe UI,sans-serif;margin:32px}}'
            f'main{{display:grid;grid-template-columns:repeat(auto-fill,620px);gap:24px}}'
            f'figure{{margin:0}}img{{vertical-align:top;margin-right:8px}}'
            f'figcaption{{padding:8px 0;color:{TEXT}}}small{{color:{SECONDARY}}}</style>'
            f'<h1>cc5 mirror previews</h1><p>Native 240 px render_lcd output and the desktop mirror composite '
            f'for each case in tests/fixtures/cc5_frames.json (settled LEDs, flash-* cases with their flash, '
            f'art fixtures).</p>'
            f'<main>{"".join(rows)}</main>')
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"Exported {len(rows)} cc5 cases to {out}")
    return len(rows)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else OUT)

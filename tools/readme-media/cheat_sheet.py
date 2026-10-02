"""The printable knob cheat sheet: one A4 page (2480 x 3508 px at 300 dpi) with every screen of `stills.json` as a
knob tile from the firmware's own LCD renderer next to its four buttons and holds from `button-maps.json`.

Outputs (render(knob_anim, work, out_dir, stills_json, button_maps_json)):
  <out_dir>/cheat-sheet.png        light theme, downscaled to 1240 px wide, under the 300 KB still cap
  <out_dir>/cheat-sheet-dark.png   the same page in the dark theme
  <out_dir>/../cheat-sheet.pdf     the light page at full size (Pillow PDF, 300 dpi) -> docs/cheat-sheet.pdf
The footer carries the literal text {{RELEASE}} for the release step to substitute. Fictional data only.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import stills as S

PAGE = (2480, 3508)
MARGIN = 150
COLS, ROWS = 2, 6
TILE = 330                     # LCD diameter on the page
HOLD_1 = "hold 1 (0.6 s) = Home from anywhere"
FOOTER_LEFT = "{{RELEASE}}"
FOOTER_RIGHT = "Desk Dial · a hold matures at 0.6 s (button 1) or 1.0 s (button 4) · fictional library"

THEMES = {
    "light": {"bg": (248, 248, 250), "ink": (24, 26, 32), "muted": (112, 117, 128), "accent": (178, 112, 34),
              "rule": (214, 216, 222), "bezel": (60, 62, 68), "card": (255, 255, 255)},
    "dark": {"bg": (13, 14, 17), "ink": (236, 238, 242), "muted": (150, 154, 164), "accent": (214, 160, 86),
             "rule": (44, 46, 52), "bezel": (70, 72, 78), "card": (22, 23, 27)},
}


def _page(items, lcds, maps, theme: dict) -> Image.Image:
    W, H = PAGE
    img = Image.new("RGB", PAGE, theme["bg"])
    d = ImageDraw.Draw(img)
    title_f = S.font("Montserrat", 112, "Bold")
    sub_f = S.font("Archivo", 46, "Regular")
    hold1_f = S.font("Archivo", 52, "Medium")
    name_f = S.font("Montserrat", 46, "SemiBold")
    btn_f = S.font("Archivo", 40, "Regular")
    digit_f = S.font("Montserrat", 40, "Bold")
    hold_f = S.font("Archivo", 34, "Medium")
    foot_f = S.font("Archivo", 34, "Regular")

    # header
    y = MARGIN
    d.text((MARGIN, y), "Desk Dial · knob cheat sheet", font=title_f, fill=theme["ink"])
    y += 140
    for line in ("Every screen of the knob with its four buttons (1 = left, 4 = right) and what a hold does.",
                 "Turn the knob to browse or set; press a button to act; a lit button marks the knob's current job."):
        d.text((MARGIN, y), line, font=sub_f, fill=theme["muted"])
        y += 62
    y += 20
    d.text((MARGIN, y), HOLD_1, font=hold1_f, fill=theme["accent"])
    y += 100
    d.line((MARGIN, y, W - MARGIN, y), fill=theme["rule"], width=3)
    y += 50

    # grid
    foot_y = H - MARGIN - 60
    grid_h = foot_y - 60 - y
    cell_w = (W - 2 * MARGIN) // COLS
    cell_h = grid_h // ROWS
    for k, (s, lcd) in enumerate(zip(items, lcds)):
        cx = MARGIN + (k % COLS) * cell_w
        cy = y + (k // COLS) * cell_h
        tile = S.lcd_disc(lcd, TILE, bezel=theme["bezel"], bezel_w=5)
        ty = cy + (cell_h - tile.height) // 2
        img.paste(tile, (cx + 20, ty), tile)
        if k // COLS:
            d.line((cx + 20, cy - 2, cx + cell_w - 40, cy - 2), fill=theme["rule"], width=2)
        m = maps.get(s["name"]) or {"buttons": [(b["label"], b["icon"], b["enabled"], b.get("lit"))
                                                for b in s["frame"]["buttons"]], "holdAction": ""}
        tx = cx + 20 + tile.width + 44
        hold = S.hold_line(s["name"], m["holdAction"])
        n_hold = len(hold.split("   ")) if hold else 0
        block_h = 72 + 4 * 54 + (8 + 44 * n_hold if n_hold else 0)
        # The text block is centred in its cell on its own (two hold lines make it taller than the tile), so it
        # never touches the rule over the next row.
        ly = cy + (cell_h - block_h) // 2
        d.text((tx, ly), s["name"], font=name_f, fill=theme["ink"])
        ly += 72
        for n, (label, _icon, enabled, lit) in enumerate(m["buttons"]):
            colour = theme["ink"] if (label and enabled) else theme["muted"]
            d.text((tx, ly), str(n + 1), font=digit_f, fill=theme["accent"])
            text = label or "—"
            if lit == "on":
                text += "  (lit)"
            d.text((tx + 46, ly), text, font=btn_f, fill=colour)
            ly += 54
        if hold:
            ly += 8
            for part in hold.split("   "):
                d.text((tx, ly), part, font=hold_f, fill=theme["accent"])
                ly += 44

    # footer
    d.line((MARGIN, foot_y - 40, W - MARGIN, foot_y - 40), fill=theme["rule"], width=3)
    d.text((MARGIN, foot_y), FOOTER_LEFT, font=foot_f, fill=theme["muted"])
    tw = d.textlength(FOOTER_RIGHT, font=foot_f)
    d.text((W - MARGIN - tw, foot_y), FOOTER_RIGHT, font=foot_f, fill=theme["muted"])
    return img


def render(knob_anim, work, out_dir, stills_json=None, button_maps_json=None, web_width=1240) -> list[Path]:
    work, out_dir = Path(work), Path(out_dir)
    if stills_json is None:
        import rec_scenes
        stills_json = rec_scenes.recording_path(work, "stills")
    if button_maps_json is None:
        button_maps_json = Path(stills_json).parent / "button-maps.json"
    items, lcds = S.render_lcds(knob_anim, work, stills_json)
    maps = S.load_button_maps(button_maps_json)
    paths = []
    light = _page(items, lcds, maps, THEMES["light"])
    dark = _page(items, lcds, maps, THEMES["dark"])
    for page, stem in ((light, "cheat-sheet"), (dark, "cheat-sheet-dark")):
        small = page.resize((web_width, round(page.height * web_width / page.width)), Image.Resampling.LANCZOS)
        p = S.save_png(small, out_dir / f"{stem}.png")
        print(f"{p.name}: {small.size} {p.stat().st_size // 1024} KB", flush=True)
        paths.append(p)
    pdf = out_dir.parent / "cheat-sheet.pdf"
    light.save(pdf, "PDF", resolution=300.0)
    print(f"{pdf.name}: {light.size} at 300 dpi, {pdf.stat().st_size // 1024} KB", flush=True)
    paths.append(pdf)
    return paths

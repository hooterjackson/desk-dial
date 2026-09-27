"""Width check of the Desk Dial knob copy (rename-desk-dial.md 5.2 and 14.4 item 3). Read only.

Moved here from the rename session's scratchpad so it survives it. Two methods, as PRESENTATION_V5.md:

- design: the contract's Notation (Montserrat.ttf instanced at wght 500, advance widths, no kerning);
- LVGL: font_tests.resolved_run_width over cc_font_<N> -> the kerned built-in lv_font_montserrat_<N>
  (the firmware's fallback for ASCII), plus lv_text_get_width's letter space (n - 1 gaps), against the
  r-chord of the line's ink rows (the firmware's safeHalf).

It reproduces the contract's four calibration values, measures DESK DIAL (a 12 px caps heading at
+1 px, in case a heading ever carries the name; K1 8.10 has none on the offline screen) and the
offline sub `Open Desk Dial on your PC` with the no-break space the firmware uses (OFFLINE_SUB), and
checks the desktop mirror's split (control_center.lcd_preview.fit_two_lines). Exit 0 when every
value matches rename-desk-dial.md 5.2, else 1.

    <desktop venv python> -I harness\\measure_desk_dial.py
"""
import sys
from pathlib import Path

LCD = Path(__file__).resolve().parent
WORK = LCD.parent
COMPANION = WORK / "app"
FW = WORK / "firmware"
BUILTIN = FW / ".pio" / "libdeps" / "nanofoc_d" / "lvgl" / "src" / "font"
sys.dont_write_bytecode = True
sys.path.insert(0, str(LCD))
sys.path.insert(1, str(COMPANION))

import gen_lvgl_font as gen  # noqa: E402
import font_tests as ft  # noqa: E402

NBSP = " "
FACES, FONTS = {}, {}


def design(text, size, tracking=0):
    """Contract Notation: unhinted advances at 1000 px (unitsPerEm 1000) scaled to the size."""
    face = FACES.setdefault(1000, gen.load_face(gen.FONT_PATH, 1000))
    return face.getlength(text) * size / 1000.0 + tracking * (len(text) - 1)


def lv(size):
    if size not in FONTS:
        FONTS[size] = (ft.parse_font_c(FW / "src" / "fonts" / f"cc_font_{size}.c"),
                       ft.parse_font_c(BUILTIN / f"lv_font_montserrat_{size}.c"))
    return FONTS[size]


def lvgl(text, size, tracking=0):
    ours, builtin = lv(size)
    width = ft.resolved_run_width(ours, builtin, text)
    return None if width is None else width + tracking * (len(text) - 1)


def ink_rows(text, size):
    ours, builtin = lv(size)
    ascent = ours["line_height"] - ours["base_line"]
    top, bottom = ascent, ascent - 1
    for ch in text:
        for font in (ours, builtin):
            gid = ft.lv_glyph_id(font, ord(ch))
            if gid:
                _, _, box_w, box_h, _, ofs_y = font["glyph_dsc"][gid]
                if box_w and box_h:
                    top = min(top, ascent - box_h - ofs_y)
                    bottom = max(bottom, ascent - ofs_y - 1)
                break
    return top, bottom


def safe_half(top, bottom, radius, center=120):
    half = center
    for y in range(top, bottom + 1):
        d = center - y if y < center else y + 1 - center
        half = min(half, 0 if d >= radius else int((radius * radius - d * d) ** 0.5))
    return half


def line_limit(text, size, y, box_w, radius):
    top, bottom = ink_rows(text, size)
    return min(box_w, 2 * safe_half(y + top, y + bottom, radius))


def main():
    problems = []

    def expect(name, got, want):
        ok = got == want
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
        if not ok:
            problems.append(name)

    # Calibration against the contract's quoted values (design px to one decimal; LVGL px).
    for text, size, want_design, want_lvgl in (("Open Nano_D++ on your PC", 14, 197.9, 202),
                                               ("Waiting for PC", 22, 163.6, 163),
                                               ("Knob controls still work", 14, 167.5, 171),
                                               ("Speaker group changed", 12, 147.6, 144)):
        expect(f"calibration {text!r} {size} px", (round(design(text, size), 1), lvgl(text, size)),
               (want_design, want_lvgl))
    # The name as a 12 px caps heading at +1 px tracking (HEADING {51, 31, 138}, r112).
    expect("heading 'DESK DIAL' 12 px +1", (round(design("DESK DIAL", 12, 1), 1), lvgl("DESK DIAL", 12, 1)), (74.8, 75))
    expect("heading limit (r112 chord vs the 138 px box)", line_limit("DESK DIAL", 12, 31, 138, 112), 138)
    # The offline sub (OFF_SUB {35, 105, 170}, 14/18 px, r104): whole, then the two balanced lines.
    sub = f"Open Desk{NBSP}Dial on your PC"
    line1, line2 = f"Open Desk{NBSP}Dial", "on your PC"
    expect("offline sub one line (NBSP)", (round(design(sub, 14), 1), lvgl(sub, 14)), (192.2, 198))
    expect("NBSP resolves in cc_font_14 like a space", (lvgl(NBSP, 14), lvgl(" ", 14)), (4, 4))
    expect("line 1 'Open Desk Dial'", (round(design(line1, 14), 1), lvgl(line1, 14)), (110.4, 114))
    expect("line 1 limit (y 105)", line_limit(line1, 14, 105, 170, 104), 170)
    expect("line 2 'on your PC'", (round(design(line2, 14), 1), lvgl(line2, 14)), (78.0, 80))
    expect("line 2 limit (y 123)", line_limit(line2, 14, 123, 170, 104), 170)
    # The desktop mirror splits where the firmware does (fitTwoLines breaks only at ASCII spaces).
    from control_center import lcd_preview
    expect("lcd_preview.OFFLINE['subtitle']", lcd_preview.OFFLINE["subtitle"], sub)
    expect("lcd_preview.fit_two_lines (NBSP)", lcd_preview.fit_two_lines(sub, 170, 170, 14), [line1, line2])
    expect("without the NBSP the name would split",
           lcd_preview.fit_two_lines(sub.replace(NBSP, " "), 170, 170, 14), ["Open Desk", "Dial on your PC"])
    print("measure_desk_dial:", "PASS" if not problems else f"FAIL ({len(problems)})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

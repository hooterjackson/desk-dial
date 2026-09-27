"""Post-cap hue report for cc5 LED accents (informational, never failing).

The firmware multiplies every drive colour by the global FastLED brightness
cap (setBrightness(51)), roughly ``c * 51 / 255`` per channel. At landmark
level L1 (15/255) a drive channel is at most 15, so after the cap it is at most
3: many accents collapse to <= 1 per channel or lose a channel (hue) unless
FastLED's temporal dithering (on by default, kept on for cc5) spreads the
remainder. This report lists, per sample accent and level, the pre-cap drive,
the undithered post-cap value and whether the hue survives.

Run directly to print the report; tests/test_cc_led_model.py writes it to
diagnostics/cc5-led-hue-report.json.
"""
from __future__ import annotations

import colorsys
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import presentation  # noqa: E402
from control_center.preview_lights import FASTLED_CAP, post_cap, scale  # noqa: E402

REPORT = ROOT / "diagnostics" / "cc5-led-hue-report.json"
PALETTE = {"W": presentation.LED_WHITE, "G": presentation.LED_GREEN, "R": presentation.LED_RED,
           "AMBER": presentation.LED_AMBER, "VRED": presentation.LED_VOLUME_RED}
# Where each level is used (section 5): L1 landmarks/bounds/pending span/dim buttons,
# L2 volume body/nav buttons/Windows unavailable cursor, LS odd-v shoulder, L3 cursor/endpoint.
LEVELS = {"L1": presentation.L1, "L2": presentation.L2, "LS": presentation.LEVEL_SHOULDER,
          "L3": presentation.L3, "L4": presentation.L4}
HUE_SHIFT_LIMIT = 20.0


def _channels(color):
    return [(color >> 16) & 255, (color >> 8) & 255, color & 255]


def _hsv(color):
    r, g, b = (c / 255 for c in _channels(color))
    return colorsys.rgb_to_hsv(r, g, b)


def _hue_distance(a, b):
    d = abs(a - b) * 360.0
    return min(d, 360.0 - d)


def assess(accent, level, cap=FASTLED_CAP):
    """One accent at one level: drive, post-cap value and hue verdict."""
    drive = scale(accent, level)
    capped = post_cap(drive, cap)
    exact = [round(c * cap / 255, 3) for c in _channels(drive)]
    h0, s0, _ = _hsv(accent)
    h1, s1, v1 = _hsv(capped)
    significant = [i for i, c in enumerate(_channels(accent)) if c >= max(_channels(accent)) // 4 and c]
    dropout = [("r", "g", "b")[i] for i in significant if _channels(capped)[i] == 0]
    low = [("r", "g", "b")[i] for i in significant if _channels(capped)[i] <= 1]
    collapse = max(_channels(capped)) <= 1
    saturated = s0 >= 0.2
    grey = v1 == 0 or s1 < 0.05
    shift = None if grey or not saturated else round(_hue_distance(h0, h1), 1)
    lost = saturated and (collapse or bool(dropout) or grey or (shift is not None and shift > HUE_SHIFT_LIMIT))
    return {
        "drive": f"#{drive:06X}", "postCap": f"#{capped:06X}", "postCapExact": exact,
        "collapse": collapse, "significantChannelsLe1": low, "dropout": dropout, "hueShiftDeg": shift,
        "losesHue": lost,
    }


def sample_accents(golden):
    """Unique non-zero accents from the golden's injected colours, plus the LED palette."""
    accents = {}
    for key, text in sorted(golden["constants"]["tints"].items()):
        if text:
            r, g, b = (int(p) for p in text.split(","))
            accents[key] = (r << 16) | (g << 8) | b
    for name, value in PALETTE.items():
        accents["palette:" + name] = value
    return accents


def build(golden):
    accents = sample_accents(golden)
    rows = []
    for name, accent in accents.items():
        row = {"name": name, "accent": f"#{accent:06X}"}
        for level_name, level in LEVELS.items():
            row[level_name] = assess(accent, level)
        rows.append(row)
    l1_lost = [r["name"] for r in rows if r["L1"]["losesHue"]]
    l1_collapsed = [r["name"] for r in rows if r["L1"]["collapse"]]
    return {
        "about": ("Informational. Undithered post-cap drive = per channel floor(drive * 51 / 255) "
                  "(FastLED setBrightness(51) roughly); drive = (c * level + 127) / 255. "
                  "FastLED temporal dithering (kept ON in cc5) averages the remainder across frames, "
                  "so 'losesHue' marks where the hue relies on dithering."),
        "cap": FASTLED_CAP,
        "levels": LEVELS,
        "summary": {
            "accents": len(rows),
            "L1_collapse_le1": l1_collapsed,
            "L1_significant_channel_le1": [r["name"] for r in rows if r["L1"]["significantChannelsLe1"]],
            "L1_loses_hue": l1_lost,
            "L2_loses_hue": [r["name"] for r in rows if r["L2"]["losesHue"]],
            "L3_loses_hue": [r["name"] for r in rows if r["L3"]["losesHue"]],
        },
        "rows": rows,
    }


def write(report, path=REPORT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    from knob_adapter import load_golden  # noqa: E402
    print(json.dumps(build(load_golden())["summary"], indent=1, ensure_ascii=False))

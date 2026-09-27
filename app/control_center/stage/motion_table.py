"""Every compositor-run motion tuple of DESKTOP_STAGE §7-§10 and §16 (App A, BS where App A is
silent), for the H3 curve-fit gate (§6.6) and for the scenes that build on the stage (WP8, WP7b).

Rows: (surface, element, property kind, curve, legs). ``legs`` is the duration in ms of a
single-leg tuple, or ((start_ms, dur_ms), ...) for a two-leg tuple read per leg (S5-31). The
floating knob's slide (ease-out / ease-in cubic, Python-stepped, §0.4) is not here: it is not a
DirectComposition animation.
"""
from __future__ import annotations

BUMP = ((0, 160), (160, 160))              # end bump: 0 -> -14*dir over 160, then back from +160 (S5-31)
HEART = ((0, 380), (420, 380))             # heart: 0.4 -> 1.5 over 380 SPR, then from +420 1.5 -> 1 (S5-31)

APP_A = (
    # §7.6 explorer
    ("explorer", "root.open", "opacity", "OUT", 340),
    ("explorer", "card.enter.rise", "offset", "OUT", 440),
    ("explorer", "card.enter.scale", "scale", "OUT", 440),
    ("explorer", "card.enter.opacity", "opacity", "OUT", 320),
    ("explorer", "root.close", "opacity", "OUT", 340),
    ("explorer", "card.turn.x", "offset", "OUT", 420),
    ("explorer", "card.turn.scale", "scale", "OUT", 420),
    ("explorer", "card.turn.opacity", "opacity", "OUT", 300),
    ("explorer", "shade.turn", "opacity", "OUT", 320),
    ("explorer", "shadow.crossfade", "opacity", "OUT", 320),
    ("explorer", "cover_l0.crossfade", "opacity", "OUT", 420),
    ("explorer", "marker.turn", "offset", "OUT", 420),
    ("explorer", "label.fade_in", "opacity", "OUT", 160),
    ("explorer", "ambient.crossfade", "opacity", "OUT", 600),
    ("explorer", "cards.end_bump", "offset", "OUT", BUMP),
    ("explorer", "card.exit.rise", "offset", "IN", 170),
    ("explorer", "card.exit.scale", "scale", "IN", 170),
    ("explorer", "card.exit.opacity", "opacity", "IN", 170),
    ("explorer", "label.fade_out", "opacity", "OUT", 160),
    ("explorer", "tab.label", "opacity", "OUT", 240),
    ("explorer", "tab.underline", "scale", "OUT", 320),
    ("explorer", "play.grow", "scale", "OUT", 380),
    ("explorer", "play.others", "opacity", "OUT", 300),
    ("explorer", "art.ready", "opacity", "OUT", 240),
    ("explorer", "state_block.fade", "opacity", "OUT", 160),
    # §8.5 Up next
    ("upnext", "root.open", "opacity", "OUT", 340),
    ("upnext", "left.rise", "offset", "OUT", 460),
    ("upnext", "left.opacity", "opacity", "OUT", 320),
    ("upnext", "row.enter.x", "offset", "OUT", 420),
    ("upnext", "row.enter.opacity", "opacity", "OUT", 300),
    ("upnext", "plate.open", "opacity", "OUT", 320),
    ("upnext", "root.close", "opacity", "OUT", 340),
    ("upnext", "row.turn.y", "offset", "OUT", 420),
    ("upnext", "row.turn.scale", "scale", "OUT", 420),
    ("upnext", "row.turn.opacity", "opacity", "OUT", 300),
    ("upnext", "cover.crossfade", "opacity", "OUT", 420),
    ("upnext", "ambient.crossfade", "opacity", "OUT", 600),
    ("upnext", "rows.end_bump", "offset", "OUT", BUMP),
    ("upnext", "shuffle.exit", "opacity", "IN", 160),
    ("upnext", "shuffle.enter.x", "offset", "OUT", 420),
    ("upnext", "shuffle.enter.opacity", "opacity", "OUT", 300),
    ("upnext", "shuffle_line.crossfade", "opacity", "EASE", 240),
    ("upnext", "heart.scale", "scale", "SPR", HEART),
    ("upnext", "heart.opacity", "opacity", "OUT", 200),
    ("upnext", "play.grow", "scale", "OUT", 420),
    ("upnext", "play.others", "opacity", "OUT", 300),
    ("upnext", "plate.play", "opacity", "OUT", 320),
    ("upnext", "row.data", "opacity", "OUT", 160),
    ("upnext", "sharpen.crossfade", "opacity", "OUT", 120),
    # §9.8 picker (the parts WP7b may move onto the stage, RF0 step 3)
    ("picker", "root.open", "opacity", "OUT", 280),
    ("picker", "card.enter.rise", "offset", "OUT", 420),
    ("picker", "card.enter.scale", "scale", "OUT", 420),
    ("picker", "card.enter.opacity", "opacity", "OUT", 420),
    ("picker", "card.turn.x", "offset", "OUT", 420),
    ("picker", "card.turn.scale", "scale", "OUT", 420),
    ("picker", "card.turn.opacity", "opacity", "OUT", 300),
    ("picker", "shade.turn", "opacity", "OUT", 320),
    ("picker", "frame.crossfade", "opacity", "OUT", 320),
    ("picker", "marker.turn", "offset", "OUT", 420),
    ("picker", "label.fade_in", "opacity", "OUT", 160),
    ("picker", "cards.end_bump", "offset", "OUT", BUMP),
    ("picker", "tray.rise", "offset", "SPR", 460),
    ("picker", "tray.scale", "scale", "SPR", 460),
    ("picker", "tray.opacity", "opacity", "OUT", 260),
    ("picker", "group.shift", "offset", "OUT", 460),
    ("picker", "slot.fill", "opacity", "OUT", 260),
    ("picker", "fly.move", "offset", "OUT", 460),
    ("picker", "fly.scale", "scale", "OUT", 460),
    ("picker", "fly.opacity", "opacity", "OUT", 220),
    ("picker", "root.close", "opacity", "OUT", 280),
    ("picker", "group.close", "opacity", "EASE", 220),
    ("picker", "slot.border", "opacity", "EASE", 260),
    ("picker", "slot.empty_glyph", "opacity", "EASE", 200),
    ("picker", "slot.badge", "opacity", "EASE", 260),
    # §10.2 toast
    ("toast", "in.rise", "offset", "OUT", 260),
    ("toast", "in.opacity", "opacity", "OUT", 260),
    ("toast", "in.scale", "scale", "SPR", 420),
    ("toast", "out.opacity", "opacity", "IN", 200),
    # §16 reduced motion
    ("any", "reduced.opacity", "opacity", "OUT", 200),
)

# Worst-case travel per property kind at k = 2 on the G93SC (the H3 extremes): offsets across
# the 32:9 table (2 x 1490 units x k); scales on the widest scaled element (the 900-unit label
# or toast column, 1800 px) through the heart's largest step (1.1); opacities over 0 -> 1.
H3_EXTREMES = {"offset": {"travel": 2 * 1490 * 2.0, "size": 1.0},
               "scale": {"travel": 1.1, "size": 1800.0},
               "opacity": {"travel": 1.0, "size": 1.0}}


def legs_of(row):
    """((start_ms, dur_ms), ...) of a table row."""
    legs = row[4]
    return ((0, legs),) if isinstance(legs, int) else legs

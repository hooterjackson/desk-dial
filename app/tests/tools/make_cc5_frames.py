"""Write tests/fixtures/cc5_frames.json: v4 design frames for the Stage 6 LCD harness.

Every frame comes from knob-model.js (via tests/fixtures/knob_golden.json and
tests/tools/knob_adapter.py) through the contract field map, in targeted-colour
LED style, and is then passed through the frozen host adapter
``control_center.device._frame`` for a presentation-4 knob (validation, text
capacities and section 8 slimming), so each stored frame is exactly the wire
frame. Renderers draw its text verbatim.

Per case: the model's id/name/note, the Stage 6 art fixture to load for the
frame's artKey ("art-hall-120" where the model shows a cover, "art-bright-120"
for one stress case, null where the model has no art), the Windows letter tile,
screenKey/depth for slide checks and the expected LED drive colours (pre-cap,
pulse phase 0, flash drawn).

Sequences replay the model's own step() timeline for animation checks, with an
``expect`` block per step (slide direction, identical heartbeat, volume reveal/
hide, idle entry/exit, art change).

Usage: .venv\\Scripts\\python.exe tests\\tools\\make_cc5_frames.py [--check]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for path in (str(ROOT), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from control_center import device, preview_lights  # noqa: E402
from knob_adapter import ART_BRIGHT, ART_HALL, Adapter, load_golden  # noqa: E402

OUTPUT = ROOT / "tests" / "fixtures" / "cc5_frames.json"
CAPABILITIES = {"presentation": 4, "glyphs": "latin-ext-a"}
LED_STYLE = "color"
# The volume sweep lives in knob_golden.json for the LED tests; the LCD harness
# gets the scenario/stress/state cases and the representative volume states.
SKIP_GROUPS = ("sweep",)


def wire(frame):
    return None if frame is None else device._frame(frame, CAPABILITIES)


def leds(frame):
    if frame is None:
        return None
    cells, cursor = preview_lights.ring_target(frame, 0, 0, frame.get("feedback", {}).get("kind"))
    return {"cursor": cursor, "ring": [preview_lights.cell_drive(c) for c in cells],
            "buttons": preview_lights.button_targets(frame)}


def _case(adapter, case, control_id):
    white = case["views"]["white"]
    frame = wire(adapter.case_frame(case, LED_STYLE, control_id))
    lcd = white["lcd"]
    entry = {
        "id": case["id"],
        "name": case["name"],
        "note": case["note"],
        "group": case["group"],
        "art": adapter.art(case["id"], case["st"], lcd) if frame else None,
        "screenKey": white["screenKey"],
        "depth": white["depth"],
        "frame": frame,
        "leds": leds(frame),
    }
    if lcd.get("layout") == "win":
        entry["tile"] = {"letter": lcd.get("iconL", ""), "opacity": lcd.get("iconOp", 1)}
    if frame is None:
        entry["note"] = (entry["note"] + " " if entry["note"] else "") + (
            "Deviation 8: no frame; firmware hands control back to the native UI "
            "(host-lost notice NANO_D++ / Waiting for PC / Native controls active).")
    return entry


def _layout_of(frame):
    return frame["layout"] if frame else None


def _base_idle(frame):
    """True when the resting Home base is the idle layout (art and footer hidden)."""
    if not frame:
        return False
    return frame["layout"] == "idle" or (frame["layout"] == "volume" and frame.get("restLayout") == "idle")


def _sequence(adapter, sequence):
    steps, previous, control_id, key = [], None, 0, None
    for step in sequence["steps"]:
        view = step["view"]["white"]
        act = step.get("act") or {}
        if view["screenKey"] != key or act.get("t") == "external":
            control_id += 1  # a new control is entered (screen change, or the external re-enter)
        frame = wire(adapter.frame(step["st"], view, LED_STYLE, control_id, sequence["id"]))
        expect = {"slide": 0, "identical": False}
        if previous is not None:
            prev_frame, prev_view = previous
            if view["screenKey"] != prev_view["screenKey"]:
                expect["slide"] = 20 if view["depth"] >= prev_view["depth"] else -20
            expect["identical"] = frame == prev_frame
            if _layout_of(frame) == "volume" and _layout_of(prev_frame) != "volume":
                expect["volumeReveal"] = True
            if _layout_of(prev_frame) == "volume" and _layout_of(frame) != "volume":
                expect["volumeHide"] = True
            if _base_idle(frame) and not _base_idle(prev_frame):
                expect["idleEnter"] = True
            if _base_idle(prev_frame) and not _base_idle(frame):
                expect["idleExit"] = True
            if (frame or {}).get("artKey", "") != (prev_frame or {}).get("artKey", ""):
                expect["artChange"] = True
            if (frame or {}).get("feedback") != (prev_frame or {}).get("feedback") and (frame or {}).get("feedback"):
                expect["flash"] = frame["feedback"]["kind"]
        steps.append({
            "t": step["t"],
            "action": step.get("act"),
            "command": step.get("cmd"),
            "art": adapter.art(sequence["id"], step["st"], view["lcd"]) if frame else None,
            "screenKey": view["screenKey"],
            "depth": view["depth"],
            "frame": frame,
            "expect": expect,
        })
        previous, key = (frame, view), view["screenKey"]
    return {"id": sequence["id"], "name": sequence["name"], "note": sequence["note"], "steps": steps}


def build(golden=None):
    golden = golden or load_golden()
    adapter = Adapter(golden)
    cases = [_case(adapter, case, number + 1)
             for number, case in enumerate(c for c in golden["cases"] if c["group"] not in SKIP_GROUPS)]
    return {
        "about": ("cc5 design frames for the Stage 6 LCD harness, generated by tests/tools/make_cc5_frames.py "
                  "from tests/fixtures/knob_golden.json (knob-model.js). Each frame is the presentation-4 wire "
                  "frame (control_center.device._frame output, slimmed), ledStyle 'color'. 'art' names the "
                  "fixture in assets/fixtures/<art>.rgb565 to load for the frame's artKey."),
        "contract": "firmware/PRESENTATION_V4.md",
        "capabilities": CAPABILITIES,
        "artFixtures": {ART_HALL: "assets/fixtures/art-hall-120.rgb565", ART_BRIGHT: "assets/fixtures/art-bright-120.rgb565"},
        "valueNote": ("value carries the volume digits plus '%' (contract section 3 example '54%'); "
                      "Knob Face draws the '%' at 22 px in ink2 after the 48 px digits."),
        "deviations": {
            "6": "Tracks with no Previous: title 'Previous track' (muted), meta 'Previous unavailable'.",
            "7": "Art does not translate on a screen change; no decorative scale transforms.",
            "8": "Disconnected: no frame (native handback); cases keep frame null.",
        },
        "cases": cases,
        "sequences": [_sequence(adapter, sequence) for sequence in golden["sequences"]],
    }


def dumps(data):
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv):
    text = dumps(build())
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != text:
            print(f"{OUTPUT} is out of date; run tests/tools/make_cc5_frames.py")
            return 1
        print(f"{OUTPUT} is up to date")
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""The Onshape SendInput goldens (app profiles, plan sections 4c and 6, S1 DD-B): scripted knob event sequences run
through the Onshape injector with a recording backend, every SendInput batch kept as the INPUT records Windows would
get (keys with vk + scan + flags, Unicode characters, absolute moves, buttons and wheel notches) with the time it went
out (so the tool-search and retype waits show), the injector's knob feedback and its final counters.

The goldens in tests/goldens/onshape_input/ were recorded from Desk Dial's tuned Onshape stack (onshape.py
OnshapeInjector + onshape_app.OnshapeApp, 7.3.2.0) BEFORE the generic app engine replaced it; the generic engine
running the Onshape profile must reproduce every one exactly (tests/test_onshape_input_goldens.py).

Regenerate (only when Onshape's behaviour is meant to change): python tests/onshape_input_golden.py --write
Headless: a fake user32 for the scan codes and the screen metrics; SendInput is never called.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cc5_support import Clock  # noqa: E402

GOLDENS = Path(__file__).resolve().parent / "goldens" / "onshape_input"
CONTROL = 7

# US set-1 scan codes of every virtual key the Onshape layout sends (the fake MapVirtualKeyExW).
SCANS = {0x10: 0x2A, 0x11: 0x1D, 0x12: 0x38, 0x0D: 0x1C, 0x1B: 0x01,
         **{ord(c): s for c, s in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                                      (0x1E, 0x30, 0x2E, 0x20, 0x12, 0x21, 0x22, 0x23, 0x17, 0x24, 0x25, 0x26, 0x32,
                                       0x31, 0x18, 0x19, 0x10, 0x13, 0x1F, 0x14, 0x16, 0x2F, 0x11, 0x2D, 0x15, 0x2C))},
         **{ord(c): s for c, s in zip("1234567890", range(0x02, 0x0C))}}
SCREEN = {76: 0, 77: 0, 78: 1920, 79: 1080}     # SM_X/YVIRTUALSCREEN, SM_CX/CYVIRTUALSCREEN


class FakeUser:
    """The few user32 calls Win32Backend._input makes (DD-SEC-004's scan code, the absolute move's metrics)."""

    def GetForegroundWindow(self):
        return 0x1234

    def GetWindowThreadProcessId(self, hwnd, pid):
        return 77

    def GetKeyboardLayout(self, thread):
        return 0x04090409

    def MapVirtualKeyExW(self, vk, kind, layout):
        return SCANS.get(int(vk), 0)

    def GetSystemMetrics(self, index):
        return SCREEN.get(index, 0)


def _converter():
    """Win32Backend's own INPUT builder over the fake user32 (never SendInput)."""
    import windows_actions as wa
    from control_center import onshape
    b = onshape.Win32Backend.__new__(onshape.Win32Backend)
    b._INPUT, b._INPUT_KEYBOARD, b._INPUT_MOUSE = wa.INPUT, wa.INPUT_KEYBOARD, wa.INPUT_MOUSE
    b._KEYUP, b._WHEEL = wa.KEYEVENTF_KEYUP, wa.MOUSEEVENTF_WHEEL
    b.u = FakeUser()
    b._layout = 0x04090409
    return b


def to_inputs(converter, events):
    out = []
    for event in events:
        item = converter._input(tuple(event))
        if item.type == 1:
            out.append({"type": "key", "vk": int(item.ki.wVk), "scan": int(item.ki.wScan),
                        "flags": int(item.ki.dwFlags)})
        else:
            out.append({"type": "mouse", "dx": int(item.mi.dx), "dy": int(item.mi.dy),
                        "data": int(item.mi.mouseData), "flags": int(item.mi.dwFlags)})
    return out


class RecordingBackend:
    """FakeBackend (test_onshape) plus: the time of each batch, a foreground window, a send that raises."""
    injects = True

    def __init__(self, clock):
        self.clock = clock
        self.cursor_pos = (500, 400)
        self.target = True
        self.focus = True
        self.is_swapped = False
        self.modifiers = False
        self.short_at = None             # the n-th batch (0-based) inserts one event less
        self.raise_at = None             # the n-th batch raises after it was recorded
        self.window = 0x1001
        self.batches = []

    def cursor(self):
        return self.cursor_pos

    def target_ok(self, point):
        return self.target

    def focus_ok(self, point):
        return self.focus

    def onshape_foreground(self):
        return True

    def foreground(self):
        return self.window

    def swapped(self):
        return self.is_swapped

    def drag_threshold(self):
        return 4

    def modifiers_held(self):
        return self.modifiers

    def send(self, events):
        index = len(self.batches)
        self.batches.append((self.clock(), [list(e) for e in events]))
        for event in events:
            if event[0] == "move":
                self.cursor_pos = (event[1], event[2])
        if self.raise_at is not None and index == self.raise_at:
            raise RuntimeError("SendInput failed")
        if self.short_at is not None and index == self.short_at:
            return len(events) - 1
        return len(events)


# --------------------------------------------------------------------------------------------- the scripts
# Steps: ("kd", raw) ("ku", raw) ("turn", delta[, times]) ("hold", slot) ("ready", mask) ("wait", seconds)
# ("activate", detents, app) ("deactivate", reason) ("release", reason) ("lifecycle", kind)
# ("set", attribute, value) on the backend.
def _wheel_open(extra=0.3):
    return [("kd", 2), ("wait", extra)]


SCRIPTS = {
    "zoom_both_ways_67": [("activate", 67, False), ("turn", 1, 5), ("turn", -1, 3), ("turn", 7), ("turn", -2),
                          ("turn", 1, 2), ("turn", -9)],
    "zoom_fractional_127": [("activate", 127, False), ("turn", 1, 7), ("turn", -1, 2), ("turn", 3), ("turn", -1, 11)],
    "zoom_refused_off_target": [("activate", 67, False), ("set", "target", False), ("turn", 1, 3),
                                ("set", "target", True), ("turn", 1, 3)],
    "tilt_drag_direction_change": [("activate", 67, False), ("kd", 0), ("turn", 1, 3), ("turn", -2), ("turn", -1, 2),
                                   ("ku", 0), ("turn", 1)],
    "orbit_drag_idle_release": [("activate", 67, False), ("kd", 1), ("turn", 1, 2), ("wait", 0.9), ("turn", 1),
                                ("turn", -1), ("ku", 1)],
    "pan_drag_swapped_buttons": [("activate", 67, False), ("set", "is_swapped", True), ("kd", 3), ("turn", 2),
                                 ("turn", -3), ("ku", 3), ("kd", 1), ("turn", 1), ("ku", 1)],
    "modifier_switch_mid_drag": [("activate", 67, False), ("kd", 1), ("turn", 1, 2), ("kd", 3), ("turn", 1),
                                 ("ku", 3), ("turn", -1), ("ku", 1), ("turn", 1)],
    "drag_refused_off_target": [("activate", 67, False), ("set", "target", False), ("kd", 1), ("turn", 1, 2),
                                ("ku", 1)],
    "undo_tap_a0": [("activate", 67, False), ("kd", 2), ("wait", 0.1), ("ku", 2), ("set", "modifiers", True),
                    ("kd", 2), ("ku", 2), ("set", "modifiers", False), ("set", "target", False), ("kd", 2),
                    ("ku", 2), ("set", "target", True), ("set", "focus", False), ("kd", 2), ("ku", 2)],
    "undo_tap_canvas": [("activate", 67, True), ("kd", 2), ("wait", 0.1), ("ku", 2), ("wait", 1.0),
                        ("set", "modifiers", True), ("kd", 2), ("wait", 0.1), ("ku", 2), ("set", "modifiers", False),
                        ("wait", 1.0), ("kd", 2), ("turn", 1), ("ku", 2)],
    "wheel_scroll_and_ring_jumps": [("activate", 67, True), *_wheel_open(), ("turn", 1, 12), ("turn", -1, 30),
                                    ("kd", 0), ("ku", 0), ("kd", 0), ("ku", 0), ("kd", 1), ("ku", 1), ("kd", 3),
                                    ("ku", 3), ("kd", 1), ("ku", 1), ("turn", 1, 6), ("ku", 2)],
    "wheel_key_command": [("activate", 67, True), *_wheel_open(), ("ku", 2), ("wait", 0.5), *_wheel_open(),
                          ("ku", 2), ("wait", 0.5), ("kd", 2), ("turn", 1), ("kd", 3), ("turn", 1, 17), ("ku", 3),
                          ("ku", 2)],
    "wheel_search_command": [("activate", 67, True), *_wheel_open(), ("turn", 1, 26), ("ku", 2), ("wait", 0.1),
                             ("wait", 0.2), ("turn", 1, 2), ("wait", 0.3), ("wait", 0.2), ("kd", 0), ("ku", 0),
                             ("wait", 0.5)],
    "wheel_cancel": [("activate", 67, True), *_wheel_open(), ("turn", -1, 20), ("ku", 2), ("wait", 0.5)],
    "param_mode_a": [("activate", 67, True), *_wheel_open(), ("turn", 1, 6), ("ku", 2), ("wait", 0.1),
                     ("turn", 1, 9), ("kd", 0), ("turn", 1, 5), ("turn", -1, 3), ("ku", 0), ("kd", 3), ("turn", 1, 9),
                     ("ku", 3), ("turn", -1, 4), ("kd", 2), ("wait", 0.1), ("ku", 2), ("wait", 0.5)],
    "param_mode_b": [("activate", 67, True), *_wheel_open(), ("turn", 1, 6), ("ku", 2), ("wait", 0.1), ("kd", 1),
                     ("ku", 1), ("turn", 1, 9), ("wait", 0.4), ("kd", 3), ("turn", 1, 30), ("ku", 3), ("turn", -1, 5),
                     ("kd", 2), ("wait", 0.1), ("ku", 2), ("wait", 0.5)],
    "param_mode_b_cancel_search": [("activate", 67, True), *_wheel_open(), ("turn", 1, 26), ("ku", 2), ("wait", 0.7),
                                   ("kd", 1), ("ku", 1), ("turn", -1, 9), ("wait", 0.4), ("turn", 1, 2), ("kd", 2),
                                   ("wait", 0.7), ("ku", 2), ("wait", 0.5)],
    "param_mode_a_modifier_held": [("activate", 67, True), *_wheel_open(), ("turn", 1, 6), ("ku", 2), ("wait", 0.1),
                                   ("set", "modifiers", True), ("turn", 1, 9), ("set", "modifiers", False),
                                   ("turn", 1, 9), ("kd", 2), ("ku", 2), ("wait", 0.5)],
    "home_chord_mid_drag": [("activate", 67, True), ("kd", 1), ("turn", 1, 2), ("kd", 2), ("turn", 1), ("kd", 3),
                            ("turn", 1, 3), ("kd", 0), ("wait", 1.1), ("ku", 0), ("ku", 1), ("ku", 2), ("ku", 3),
                            ("turn", 1)],
    "three_button_partial_chord": [("activate", 67, True), ("kd", 0), ("kd", 1), ("kd", 3), ("turn", 1, 3),
                                   ("ku", 3), ("ku", 1), ("turn", 1), ("ku", 0), ("turn", 1), ("kd", 2),
                                   ("wait", 0.1), ("ku", 2)],
    "wheel_closed_by_chord": [("activate", 67, True), *_wheel_open(), ("turn", 1, 6), ("kd", 0), ("kd", 1),
                              ("kd", 3), ("ku", 2), ("ku", 0), ("ku", 1), ("ku", 3), ("wait", 0.5)],
    "focus_loss_mid_drag": [("activate", 67, False), ("kd", 3), ("turn", 1, 3), ("release", "focus"), ("turn", 1),
                            ("ku", 3)],
    "session_change_mid_drag": [("activate", 67, False), ("kd", 1), ("turn", 1, 3), ("release", "session"),
                                ("turn", -1), ("ku", 1)],
    "foreground_change_mid_drag": [("activate", 67, False), ("kd", 0), ("turn", 1, 2), ("set", "window", 0x2002),
                                   ("turn", 1), ("turn", 1), ("ku", 0)],
    "short_send_mid_drag": [("activate", 67, False), ("kd", 1), ("turn", 1, 2), ("short", 1), ("turn", 1),
                            ("turn", 1), ("ku", 1)],
    "short_send_chord": [("activate", 67, True), *_wheel_open(), ("short", 0), ("ku", 2), ("wait", 0.5),
                         *_wheel_open(), ("ku", 2), ("wait", 0.5)],
    "exception_mid_drag": [("activate", 67, False), ("kd", 3), ("turn", 1, 2), ("raise", 1), ("turn", 1),
                           ("turn", 1), ("ku", 3)],
    "lifecycle_disconnect_mid_drag": [("activate", 67, True), ("kd", 1), ("turn", 1, 2), ("lifecycle", "disconnected"),
                                      ("turn", 1), ("ku", 1)],
    "deactivate_mid_param": [("activate", 67, True), *_wheel_open(), ("turn", 1, 6), ("ku", 2), ("wait", 0.1),
                             ("kd", 0), ("deactivate", "mode"), ("turn", 1), ("ku", 0)],
}


def run(script, make_injector):
    """Runs one script; returns the record (batches, feedback, counters). ``make_injector(backend, clock)`` builds the
    injector under test (start=False)."""
    clock = Clock(100.0)
    backend = RecordingBackend(clock)
    inj = make_injector(backend, clock)
    feedback = []

    def step():
        inj.step()
        feedback.extend(inj.take_events())

    def post(kind, **values):
        values.setdefault("id", CONTROL)
        inj.post(kind, values)
        step()

    for item in script:
        op = item[0]
        if op == "activate":
            inj.activate(CONTROL, [0, 1, 2, 3], item[1], app=item[2])
            step()
        elif op == "kd":
            post("button", button=item[1], index=item[1], pressed=True)
        elif op == "ku":
            post("release", button=item[1], index=item[1])
        elif op == "turn":
            for _ in range(item[2] if len(item) > 2 else 1):
                post("position", delta=item[1])
        elif op == "hold":
            post("hold", button=item[1])
        elif op == "ready":
            post("ready", held=item[1])
        elif op == "wait":
            # The injector thread wakes for every deadline it has (the macro waits, the wheel's 250 ms, B's rest);
            # the step-per-10 ms walk reproduces that cadence deterministically.
            end = clock() + item[1]
            while clock() < end - 1e-9:
                clock.advance(min(0.01, end - clock()))
                step()
        elif op == "deactivate":
            inj.deactivate(item[1])
            step()
        elif op == "release":
            inj.release_all(item[1])
            step()
        elif op == "lifecycle":
            inj.post(item[1], {})
            step()
        elif op == "set":
            setattr(backend, item[1], item[2])
        elif op == "short":
            backend.short_at = len(backend.batches) + item[1]
        elif op == "raise":
            backend.raise_at = len(backend.batches) + item[1]
        else:
            raise ValueError(op)
    converter = _converter()
    status = inj.status()
    status.pop("injects", None)
    return {"batches": [{"t": round(t - 100.0, 4), "events": events, "inputs": to_inputs(converter, events)}
                        for t, events in backend.batches],
            "feedback": feedback,
            "status": status}


def legacy_injector(backend, clock):
    from control_center.onshape import OnshapeInjector
    return OnshapeInjector(backend, clock=clock, start=False)


def canonical(record):
    """One batch per line (diffs stay readable)."""
    batches = record["batches"]
    lines = ["{", '"batches": [']
    for i, batch in enumerate(batches):
        lines.append(" " + json.dumps(batch, sort_keys=True) + ("," if i < len(batches) - 1 else ""))
    lines += ["],", '"feedback": ' + json.dumps(record["feedback"]) + ",",
              '"status": ' + json.dumps(record["status"], sort_keys=True), "}"]
    return "\n".join(lines) + "\n"


def write(make_injector=legacy_injector):
    import logging
    logging.disable(logging.CRITICAL)          # the exception script logs a traceback once by design
    GOLDENS.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, script in SCRIPTS.items():
        text = canonical(run(script, make_injector))
        (GOLDENS / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
        manifest[name] = {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                          "batches": text.count('"inputs"')}
    (GOLDENS / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=1) + "\n", encoding="utf-8",
                                           newline="\n")
    return manifest


if __name__ == "__main__":
    if "--write" in sys.argv:
        for name, entry in write().items():
            print(f"{name}: {entry['batches']} batches {entry['sha256'][:12]}")
    else:
        print(__doc__)

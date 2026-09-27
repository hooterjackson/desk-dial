"""On-device entry/frame checks and optional four-button mapping. No external actions."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import queue
import sys
import time

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
from control_center.device import DeviceBridge

parser = argparse.ArgumentParser()
parser.add_argument("--calibrate", action="store_true")
args = parser.parse_args()
bridge = DeviceBridge(APP / "backups")
report = {"entries": [], "external_actions": False}


def event(kind, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = bridge.events.get(timeout=.1)
        except queue.Empty:
            continue
        if value["kind"] == "error":
            raise RuntimeError(value["message"])
        if value["kind"] == kind:
            return value
    raise TimeoutError(f"No {kind} response")


def frame(value, index=0, count=4):
    return dict(mode="SETUP", target="NANO D++", value=value,
                detail="No speaker or desktop actions", status="Testing installed presets",
                buttons=[dict(label=str(i+1), enabled=False, color=0x74c9ff) for i in range(4)],
                ring=dict(style="selection", value=0, index=index, count=count))


def enter(control_id, profile, maximum, position, display, order=None):
    bridge.submit("enter", dict(id=control_id, profile=profile, min=0, max=maximum,
                  position=position, windowsButton=2, buttonOrder=order or [0, 1, 2, 3],
                  windowsHidEnabled=False, frame=display))
    reply = event("ready")
    assert reply["id"] == control_id and reply["position"] == position
    print(f"Ready {control_id}: {profile}, position {position}", flush=True)
    return reply


try:
    bridge.submit("connect", "COM8")
    connected = event("connected", 25)
    report["inventory"] = connected["backup"]
    report["capabilities"] = connected["capabilities"]
    for index, (name, profile, maximum, position) in enumerate([
            ("Volume", "BINARIS BEER", 100, 28),
            ("Recently Added", "MIDI SKIPPER", 10, 0),
            ("Windows", "MIDI SKIPPER", 3, 1),
            ("Tracks", "MIDI CLACK JONES", 2, 1)], 1):
        display = frame(name, index-1)
        started = time.monotonic()
        enter(index, profile, maximum, position, display)
        report["entries"].append(dict(control=name, profile=profile, ready=True,
                                      position=position, seconds=time.monotonic()-started))
        display["status"] = "Display update - same detent"
        bridge.submit("frame", {**display, "id": index})
        end = time.monotonic() + 1
        observed = []
        while time.monotonic() < end:
            try:
                item = bridge.events.get(timeout=.1)
                if item["kind"] in ("error", "released"):
                    raise RuntimeError(str(item))
                observed.append(item["kind"])
            except queue.Empty:
                pass
        report["entries"][-1]["events_after_frame_update"] = observed
    if args.calibrate:
        display = frame("Press button 1")
        display.update(detail="Far left", status="Buttons left to right")
        display["ring"]["style"] = "off"
        for legend in display["buttons"]:
            legend["enabled"] = True
        enter(5, "MIDI SKIPPER", 3, 0, display)
        print("CALIBRATION READY: press all four buttons once, left to right.", flush=True)
        mapping = []
        deadline = time.monotonic() + 300
        while len(mapping) < 4 and time.monotonic() < deadline:
            try:
                item = bridge.events.get(timeout=.1)
            except queue.Empty:
                continue
            if item["kind"] in ("error", "released"):
                raise RuntimeError(str(item))
            if item["kind"] != "button" or item["index"] in mapping:
                continue
            mapping.append(item["index"])
            print(f"Physical button {len(mapping)} = raw {item['index']}", flush=True)
            display["value"] = f"Press button {len(mapping)+1}" if len(mapping) < 4 else "Buttons mapped"
            display["detail"] = "Next button to the right" if len(mapping) < 4 else "Mapping saved on this PC"
            bridge.submit("frame", {**display, "id": 5})
        report["calibration_complete"] = len(mapping) == 4
        if len(mapping) == 4:
            settings_path = APP / "local/settings.json"
            settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
            settings.update(port="COM8", button_order=mapping, button_order_verified=True)
            settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            report["button_order"] = mapping
            print("Physical button mapping saved:", mapping, flush=True)
        else:
            print("Mapping timed out; no unverified order was saved.", flush=True)
    report["passed"] = True
except Exception as exc:
    report["passed"] = False
    report["error"] = str(exc)
    print("Hardware check failed:", str(exc), flush=True)
finally:
    bridge.submit("close")
    bridge._thread.join(timeout=5)
    report["port_closed"] = bridge.serial is None
    (APP / "diagnostics/device-entry-checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Check report saved; native control restored.", flush=True)
if not report.get("passed"):
    raise SystemExit(1)

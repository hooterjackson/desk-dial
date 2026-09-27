"""Exercise hardware host-lease expiry with no desktop or speaker integration."""
import json
from pathlib import Path
import sys
import time
import serial

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
from protocol import LineDecoder

report = {"external_actions": False}
decoder = LineDecoder()


def send(port, payload):
    port.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())


def wait(port, predicate, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for message in decoder.feed(port.read(4096)):
            if "error" in message:
                raise RuntimeError("Firmware rejected lease check")
            if predicate(message):
                return message
    raise TimeoutError("Expected device acknowledgment did not arrive")


display = dict(mode="SETUP", target="NANO D++", value="Connection test",
               detail="No speaker or desktop actions", status="Checking host timeout",
               buttons=[dict(label="", enabled=False, color=0x74c9ff) for _ in range(4)],
               ring=dict(style="off", value=0, index=0, count=0))
control = dict(id=1, profile="MIDI CLACK JONES", min=0, max=2, position=1,
               windowsButton=2, buttonOrder=[0, 1, 2, 3], windowsHidEnabled=False, frame=display)
with serial.Serial("COM8", 115200, timeout=.05, write_timeout=1) as port:
    try:
        send(port, {"control": control})
        wait(port, lambda m: m.get("ready") == 1 and m.get("p") == 1, 3)
        started = time.monotonic()
        reply = wait(port, lambda m: m.get("released") is True, 5)
        assert reply.get("reason") == "lease-expired", "Release was not a host timeout"
        report["lease_expiry_seconds_after_ready"] = time.monotonic() - started
        report["lease_expiry_acknowledged"] = True
        control["id"] = 2
        send(port, {"control": control})
        wait(port, lambda m: m.get("ready") == 2 and m.get("p") == 1, 3)
        report["reentry_after_expiry_acknowledged"] = True
        send(port, {"release": True})
        wait(port, lambda m: m.get("released") is True, 3)
        report["intentional_release_acknowledged"] = True
        report["passed"] = True
    finally:
        send(port, {"release": True})
(APP / "diagnostics/device-lease-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))

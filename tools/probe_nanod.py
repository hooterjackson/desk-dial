"""Read-only Nano_D++ handshake; never log complete settings or change profiles."""
import json
from pathlib import Path
import sys
import time

DEMO = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(DEMO / "vendor"))
import serial

result = {"port": "COM8"}
with serial.Serial("COM8", 115200, timeout=0.1, write_timeout=1) as device:
    device.write(b'{"settings":"?","profiles":"#all"}\n')
    deadline = time.monotonic() + 4
    pending = bytearray()
    while time.monotonic() < deadline:
        pending.extend(device.read(max(1, min(device.in_waiting, 4096))))
        while b"\n" in pending:
            raw, _, pending = pending.partition(b"\n")
            try:
                message = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("settings"), dict):
                settings = message["settings"]
                result["firmwareVersion"] = settings.get("firmwareVersion")
            if isinstance(message.get("profiles"), list):
                result["profile_count"] = len(message["profiles"])
                result["current_profile"] = message.get("current")
            if "firmwareVersion" in result and "profile_count" in result:
                break
        if "firmwareVersion" in result and "profile_count" in result:
            break
print(json.dumps(result, indent=2))

"""Read-only device inventory and profile export; never enters host control."""
import argparse
from pathlib import Path
import queue
import time
from control_center.device import DeviceBridge

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM8")
    args = parser.parse_args()
    bridge = DeviceBridge(Path(__file__).resolve().parent / "backups")
    bridge.submit("connect", args.port)
    end = time.monotonic() + 35
    try:
        while time.monotonic() < end:
            try:
                event = bridge.events.get(timeout=1)
            except queue.Empty:
                continue
            if event["kind"] == "connected":
                print("Inventory saved:", event["backup"], flush=True)
                print("Current preset:", event["current"], flush=True)
                print("Installed profiles:", ", ".join(event["profiles"]), flush=True)
                print("Control-center capability:", event["capabilities"].get("controlCenter", 0), flush=True)
                return
            if event["kind"] == "error":
                raise RuntimeError(event["message"])
        raise RuntimeError("Device inventory timed out")
    finally:
        bridge.submit("close")
        bridge._thread.join(timeout=5)

if __name__ == "__main__":
    main()

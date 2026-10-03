"""Read-only device inventory and profile export; never enters host control.

The knob's application port is found by its USB identity (239A:8010, serial NANO_D; exactly one), never by a
fixed COM name, so no other serial device is opened or sent a line; --port overrides the discovery. Desk Dial
must be quit first (it owns the knob): the script refuses while its single-instance mutex exists.
"""
import argparse
from pathlib import Path
import queue
import time
from control_center.device import DeviceBridge

APP_VID, APP_PID, APP_SERIAL = 0x239A, 0x8010, "NANO_D"
COMPANION_MUTEX = "Local\\NanoDControlCenter.App"      # standalone.py's single-instance mutex (Desk Dial)
SYNCHRONIZE = 0x00100000


def is_app_port(port):
    """The Nano_D application CDC port: 239A:8010 with serial NANO_D (any case)."""
    return ((getattr(port, "vid", None), getattr(port, "pid", None)) == (APP_VID, APP_PID)
            and (getattr(port, "serial_number", None) or "").upper() == APP_SERIAL)


def find_app_port(ports):
    """The device name of the single application port among `ports` (enumeration only, nothing is opened)."""
    matches = [p.device for p in ports if is_app_port(p)]
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one Nano_D application port (239A:8010, serial NANO_D), found "
                         f"{len(matches)}. Plug the knob in (or pass --port). Nothing was opened.")
    return matches[0]


def list_ports():
    from serial.tools.list_ports import comports
    return list(comports())


def companion_running(kernel=None):
    """True while Desk Dial runs (its single-instance mutex exists), False when it does not, None when this
    cannot be told (not Windows). Only opens the mutex by name to look; never creates it."""
    try:
        if kernel is None:
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
            kernel.OpenMutexW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    except (ImportError, AttributeError, OSError):
        return None
    handle = kernel.OpenMutexW(SYNCHRONIZE, False, COMPANION_MUTEX)
    if handle:
        kernel.CloseHandle(handle)
        return True
    return False


def main(argv=None, *, lister=list_ports, running=companion_running, bridge_factory=DeviceBridge, timeout=35.0):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", default=None,
                        help="the knob's application port (default: found by 239A:8010, serial NANO_D)")
    args = parser.parse_args(argv)
    if running():
        raise SystemExit("Desk Dial is running and owns the knob: quit it from the tray first. Nothing was opened.")
    port = args.port or find_app_port(lister())
    bridge = bridge_factory(Path(__file__).resolve().parent / "backups")
    bridge.submit("connect", port)
    end = time.monotonic() + timeout
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

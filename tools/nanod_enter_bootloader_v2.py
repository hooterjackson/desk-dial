"""Enter the ESP32-S3 ROM bootloader with ONE vendor 1200-bps touch; no flash commands.

Discovery only (no COM literals):
  * application port: VID 239A, PID 8010, serial NANO_D (compared case-insensitively);
  * ROM port: VID 303A, PID 1001, serial equal to the chip MAC 12:34:56:78:9A:BC.
Exactly one application port must match, or nothing is sent. If the matching ROM port
is already present (and no application port), the touch is skipped. The touch is one
open at 1200 bps, DTR driven false, then close (vendor use_1200bps_touch); it is never
retried. Enumeration is then polled for the MAC-matched ROM port.

Evidence: app/diagnostics/cc5-usb-boot-entry.json; when that
name already exists a timestamped sibling is written instead (older evidence is kept).
Quit the companion first: it must not own the application port.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402


def touch_1200(device, serial_module=None):
    """One open at 1200 bps with DTR false, then close. Returns the outcome text."""
    if serial_module is None:
        import serial as serial_module
    handle = serial_module.Serial()
    handle.port, handle.baudrate = device, 1200
    try:
        handle.open()
        handle.dtr = False
        return "opened at 1200 bps; DTR false; closed"
    except (serial_module.SerialException, OSError) as exc:
        # The device may re-enumerate before the open completes; that is the expected transition.
        return f"touch ended during USB transition: {type(exc).__name__}: {exc}"
    finally:
        if handle.is_open:
            handle.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait for the ROM port (default 15)")
    args = parser.parse_args(argv)
    t.console_utf8()
    report = {"method": "vendor board use_1200bps_touch (one open at 1200 bps, DTR false, close)",
              "startedUtc": t.utc_stamp(), "chipMac": t.CHIP_MAC, "touchSent": False, "changes": []}
    report["companionRunning"] = t.companion_running()
    before = t.list_ports()
    report["before"] = [t.port_info(p) for p in before]
    apps = [p for p in before if t.is_app_port(p)]
    roms = [p for p in before if t.is_rom_port(p)]
    try:
        if report["companionRunning"]:
            raise t.PortError(f"{t.COMPANION_IMAGE} is running; quit it first. No reset sent.")
        if not apps and len(roms) == 1:
            report["alreadyInBootloader"] = True
            report["romPort"] = roms[0].device
            print(f"ROM bootloader already present on {roms[0].device}; no touch sent.")
        else:
            app_port = t.find_app_port(before)  # exactly one or PortError
            if roms:
                raise t.PortError("Application and ROM ports are both present; inspect manually. No reset sent.")
            report["applicationPort"] = app_port
            print(f"Nano_D++ application port {app_port} confirmed. Sending one 1200-bps touch.", flush=True)
            report["touchSent"] = True
            report["touchResult"] = touch_1200(app_port)
            rom, observed = t.poll_ports(t.is_rom_port, args.timeout)
            report["changes"] = observed
            report["romPort"] = rom
        report["after"] = [t.port_info(p) for p in t.list_ports()]
        report["passed"] = bool(report.get("romPort"))
        if not report["passed"]:
            print("ROM bootloader port did not appear. Do not repeat the touch blindly; "
                  "see firmware/RECOVERY.md section 2.")
    except t.PortError as exc:
        report["passed"] = False
        report["error"] = str(exc)
        print(exc)
    finally:
        report["flashCommands"] = "none (no esptool, no write, no erase)"
        path = t.write_new_json(t.BOOT_ENTRY, report)
        print(f"Evidence: {path}")
    if report["passed"]:
        print(f"ROM bootloader: {report['romPort']} (serial {t.CHIP_MAC}).")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

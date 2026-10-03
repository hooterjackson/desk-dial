"""Enter the ESP32-S3 ROM bootloader with ONE vendor 1200-bps touch; no flash commands.

Discovery only (no COM literals):
  * application port: VID 239A, PID 8010, serial NANO_D (compared case-insensitively);
  * ROM port: VID 303A, PID 1001, serial equal to the chip MAC (CHIP_MAC in nanod_cc5_tooling.py).
Exactly one application port must match, or nothing is sent. Before the touch the
application port is opened at 115200 and {"settings":"?"} read: its serialNumber (the
firmware's getEfuseMac hex, little-endian; byte order normalised) must equal CHIP_MAC,
or nothing is sent (a knob with another MAC would be left in download mode, since the
ROM port poll waits only for this MAC); an unset or placeholder CHIP_MAC refuses too.
When the settings reply cannot be read (a firmware whose COM task does not answer, the
case a rollback is for), the script refuses unless --unverified-mac is given: then, with
exactly one application port present, the touch is sent and the report records
macMatched null and unverified true. A confirmed foreign MAC always refuses. The manual
alternative is firmware/RECOVERY.md section 2 (the knob's own BOOT/RESET entry).
If the matching ROM port is already present (and no application port), the touch is
skipped. A 303A:1001 port with another MAC appearing after a touch is reported. The touch is one
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


def chip_mac_problem(mac):
    """Why `mac` cannot pin the knob (unset or a placeholder), or None."""
    wanted = t.normalize_mac(mac)
    if len(wanted) != 12 or wanted in ("0" * 12, "f" * 12):
        return f"CHIP_MAC is unset or a placeholder ({mac!r}); set this knob's MAC in nanod_cc5_tooling.py"
    return None


def efuse_mac_matches(serial_number, mac):
    """True when the firmware's settings serialNumber (String(ESP.getEfuseMac(), HEX): the MAC as a little-endian
    integer, leading zeros dropped) names `mac`. The plain byte order is accepted too."""
    wanted = t.normalize_mac(mac)
    text = t.normalize_mac(serial_number if isinstance(serial_number, str) else "")
    if len(wanted) != 12 or not text or len(text) > 12:
        return False
    value = int(text, 16)
    little = value.to_bytes(6, "little").hex()
    return wanted in (little, text.zfill(12))


def read_serial_number(device, knob_factory=None, timeout=2.0):
    """Open the application port at 115200, read {"settings":"?"} once, close. Returns its serialNumber."""
    knob = (knob_factory or t.RawKnob)(device)
    try:
        knob.pump(0.3)
        reply = knob.request({"settings": "?"}, lambda m: isinstance(m.get("settings"), dict), timeout,
                             "settings")
        return reply["settings"].get("serialNumber")
    finally:
        knob.close()


def serial_number_readable(serial_number):
    """True when a settings serialNumber is a MAC-shaped hex value (1-12 hex digits) that can confirm or refute
    CHIP_MAC; a missing or malformed one says nothing about which knob this is."""
    text = t.normalize_mac(serial_number if isinstance(serial_number, str) else "")
    if not text or len(text) > 12:
        return False
    try:
        int(text, 16)
    except ValueError:
        return False
    return True


def foreign_rom_ports(ports, mac):
    """Port records of 303A:1001 ROM ports whose serial is not `mac`."""
    return [t.port_info(p) for p in ports
            if (getattr(p, "vid", None), getattr(p, "pid", None)) == (t.ROM_VID, t.ROM_PID)
            and not t.is_rom_port(p, mac)]


def main(argv=None, *, knob_factory=None, toucher=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait for the ROM port (default 15)")
    parser.add_argument("--unverified-mac", action="store_true",
                        help="send the touch even when the knob's settings cannot be read to check its MAC (only "
                             "with exactly one application port; a confirmed foreign MAC still refuses)")
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
            problem = chip_mac_problem(t.CHIP_MAC)
            if problem:
                raise t.PortError(f"{problem}. No reset sent.")
            # TL-BUG-004: this knob's MAC first. Every knob's application serial is NANO_D, so the port alone does
            # not say which knob it is; a foreign one would reboot into a ROM port this poll never matches.
            unreadable = None
            try:
                serial_number = read_serial_number(app_port, knob_factory)
                report["appSerialNumber"] = serial_number
                if not serial_number_readable(serial_number):
                    unreadable = f"its settings reply has no usable serialNumber ({serial_number!r})"
            except Exception as exc:
                report["appSerialNumber"] = None
                unreadable = f"its settings could not be read ({type(exc).__name__}: {exc})"
            if unreadable:
                report["macMatched"] = None
                if not args.unverified_mac:
                    raise t.PortError(
                        f"Could not check the MAC of the knob on {app_port}: {unreadable}. No reset sent. If this is "
                        "the only knob connected and its firmware no longer answers, run again with --unverified-mac "
                        "to send the touch anyway, or enter the bootloader by hand (firmware/RECOVERY.md section 2).")
                report["unverified"] = True
                print(f"Warning: {unreadable}; the MAC of the knob on {app_port} is NOT verified. --unverified-mac "
                      "given and it is the only application port: sending one 1200-bps touch.", flush=True)
            else:
                report["macMatched"] = efuse_mac_matches(serial_number, t.CHIP_MAC)
                if not report["macMatched"]:
                    raise t.PortError(f"The knob on {app_port} reports serialNumber {serial_number!r}, not this "
                                      f"knob's MAC {t.CHIP_MAC}. No reset sent.")
                print(f"Nano_D++ application port {app_port} confirmed (MAC matches). Sending one 1200-bps touch.",
                      flush=True)
            report["touchSent"] = True
            report["touchResult"] = (toucher or touch_1200)(app_port)
            rom, observed = t.poll_ports(t.is_rom_port, args.timeout)
            report["changes"] = observed
            report["romPort"] = rom
        after = t.list_ports()
        report["after"] = [t.port_info(p) for p in after]
        if report["touchSent"]:
            report["foreignRomPorts"] = foreign_rom_ports(after, t.CHIP_MAC)
            for info in report["foreignRomPorts"]:
                print(f"A ROM bootloader port with another MAC appeared: {info['port']} (serial "
                      f"{info['serial_number']!r}); it is not this knob.")
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

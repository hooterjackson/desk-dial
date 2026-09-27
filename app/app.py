"""Launch the Nano_D++ four-feature control center."""
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--live", action="store_true", help="Use configured Sonos, Apple Music and real Windows")
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--legacy", action="store_true", help="Open the original desktop input demo")
    args = parser.parse_args()
    if args.list_ports:
        from serial.tools.list_ports import comports
        for port in comports():
            print(f"{port.device}: {port.description}")
        return
    if args.legacy:
        import sys
        sys.argv = [sys.argv[0]] + (["--smoke-test"] if args.smoke_test else [])
        from legacy_app import main as legacy
        legacy()
        return
    if os.name == "nt":
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
    import tkinter as tk
    from control_center.ui import ControlCenterApp, apply_app_icon
    root = tk.Tk()
    apply_app_icon(root)   # APP_ICON.md item 3: before any Toplevel exists
    if args.smoke_test:
        root.withdraw()
    app = ControlCenterApp(root, smoke=args.smoke_test, live=args.live and not args.smoke_test)
    if args.smoke_test:
        root.after(500, app.close)
    root.mainloop()
    if args.smoke_test:
        print("Control center UI smoke passed; no serial port opened or real desktop/audio action sent.")


if __name__ == "__main__":
    main()

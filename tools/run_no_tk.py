"""Run companion test modules with windows, ports, browsers and hardware scripts blocked.

Usage (cwd = app): python run_no_tk.py test_a.py test_b.py ...
Blocked (raise instead of acting): tkinter.Tk / Toplevel / Tcl and the implicit default
root, pyserial port open and port enumeration, webbrowser.open, os.startfile, and any
child process whose command line names esptool, a hardware-window script, the installed
companion, Install-Desktop or --live. A module that needs any of them errors instead.
"""
import os
import subprocess
import sys
import unittest

import tkinter


class Blocked(RuntimeError):
    pass


def _blocked(what):
    def fail(*args, **kwargs):
        raise Blocked(f"{what} blocked by the test guard")
    return fail


tkinter.Tk.__init__ = _blocked("tkinter.Tk")
tkinter.Toplevel.__init__ = _blocked("tkinter.Toplevel")
tkinter.Tcl = _blocked("tkinter.Tcl")
tkinter.NoDefaultRoot()

import serial                        # noqa: E402  (pins the pyserial the tests will import)
import serial.tools.list_ports       # noqa: E402
from serial.tools import list_ports_windows  # noqa: E402
import serial.serialwin32            # noqa: E402
serial.serialwin32.Serial.open = _blocked("serial port open")
serial.tools.list_ports.comports = _blocked("serial port enumeration")
list_ports_windows.comports = _blocked("serial port enumeration")
list_ports_windows.iterate_comports = _blocked("serial port enumeration")

import webbrowser                    # noqa: E402
webbrowser.open = webbrowser.open_new = webbrowser.open_new_tab = _blocked("webbrowser.open")
if hasattr(os, "startfile"):
    os.startfile = _blocked("os.startfile")

DANGEROUS = ("esptool", "install_nanod", "rollback_nanod", "finalize_nanod", "backup_nanod", "check_nanod",
             "prepare_nanod", "nanod_enter_bootloader", "device_inventory", "Install-Desktop",
             "NanoDControlCenter", "--live", "read_mac", "write_flash", "COM8")
_real_popen_init = subprocess.Popen.__init__


def _guarded_popen(self, args, *a, **k):
    text = " ".join(map(str, args)) if isinstance(args, (list, tuple)) else str(args)
    for bad in DANGEROUS:
        if bad.lower() in text.lower():
            raise Blocked(f"subprocess blocked by the test guard: {text[:200]}")
    return _real_popen_init(self, args, *a, **k)


subprocess.Popen.__init__ = _guarded_popen

sys.path.insert(0, "tests")
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for pattern in sys.argv[1:]:
    found = loader.discover("tests", pattern=pattern, top_level_dir="tests")
    if not found.countTestCases():
        print(f"NO TESTS FOUND for {pattern}")
        sys.exit(2)
    suite.addTests(found)
result = unittest.TextTestRunner(verbosity=1).run(suite)
print(f"MODULES ({len(sys.argv) - 1}): {' '.join(sys.argv[1:])}")
print(f"RESULT: ran {result.testsRun}, failures {len(result.failures)}, errors {len(result.errors)}, "
      f"skipped {len(result.skipped)}")
for test, reason in result.skipped:
    print(f"SKIPPED: {test}: {reason}")
sys.exit(0 if result.wasSuccessful() else 1)

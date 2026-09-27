"""Imports from the Desk Dial companion (the app's source directory, which holds control_center/).

Set DESK_DIAL_APP to that directory (render_media.py does it from --app). Only pure modules are
used: the frame adapter, the artwork preparation, the LED engine twin and the floating-knob face.
Nothing here opens a serial port, a window or a network connection. No .pyc files are written into
the app's tree.
"""
import os
import sys

sys.dont_write_bytecode = True
_APP = os.environ.get("DESK_DIAL_APP")
if not _APP or not os.path.isdir(os.path.join(_APP, "control_center")):
    raise SystemExit("Set DESK_DIAL_APP to the companion source directory (the one holding control_center/)")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from control_center import device as dev  # noqa: E402,F401
from control_center import knob_face as kf  # noqa: E402,F401
from control_center.alive_lights import AliveLights  # noqa: E402,F401
from control_center.artwork import prepare_artwork2  # noqa: E402,F401

APP_DIR = _APP

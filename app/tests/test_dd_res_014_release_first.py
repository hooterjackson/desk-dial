"""DD-RES-014: ControlCenterApp.close releases the knob before the overlay, stage and
service joins, and the runtime does not submit a second device close.
No Tk window: close() runs on a stand-in object with a fake root, bridge and services."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import ui


class Root:
    def __init__(self, log):
        self.log = log

    def after_cancel(self, after_id):
        self.log.append("after_cancel")

    def after(self, ms, fn):
        # The 4 s release wait polls via after(); a bridge that never closes stops here.
        self.log.append("after")
        if self.log.count("after") < 3:
            fn()

    def destroy(self):
        self.log.append("destroy")


class Bridge:
    def __init__(self, log, refuse=False):
        self.log, self.refuse, self.closed = log, refuse, False

    def submit(self, command, value=None):
        if self.refuse:
            raise RuntimeError("Device bridge is closed")
        self.log.append("device." + command)
        if command == "close":
            self.closed = True


class Service:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def close(self):
        self.log.append(self.name + ".close")


class Runtime:
    def __init__(self, log, device):
        self.log, self.device = log, device

    def close(self):
        self.log.append("runtime.close")
        if self.device is not None:
            self.device.submit("close")

    def shutdown(self, close_device=False, join_timeout=None):
        self.log.append(("runtime.shutdown", close_device, join_timeout))
        if close_device and self.device is not None:
            self.device.submit("close")


class Auth:
    def __init__(self, log):
        self.log = log

    def stop(self):
        self.log.append("auth.stop")


def make_app(log, device, runtime_device="same"):
    app = type("App", (), {})()
    app.closing = False
    app._poll_id = "poll"
    app.root = Root(log)
    app.device = device
    app.overlay = Service(log, "overlay")
    app.stage = Service(log, "stage")
    app.runtime = Runtime(log, device if runtime_device == "same" else runtime_device)
    app.auth = Auth(log)
    return app


class ReleaseFirstTests(unittest.TestCase):
    def test_device_close_is_submitted_before_overlay_and_stage(self):
        log = []
        app = make_app(log, None)
        app.device = Bridge(log)
        app.runtime.device = app.device
        ui.ControlCenterApp.close(app)
        self.assertEqual(log[:4], ["after_cancel", "device.close", "overlay.close", "stage.close"])
        self.assertEqual(log.count("device.close"), 1)
        self.assertIn(("runtime.shutdown", False, ui.SHUTDOWN_JOIN_S), log)
        self.assertNotIn("runtime.close", log)
        self.assertEqual(log[-1], "destroy")

    def test_runtime_with_another_device_still_closes_its_own(self):
        log = []
        app = make_app(log, None)
        app.device = Bridge(log)
        other = Service(log, "sim")
        other.submit = lambda command, value=None: log.append("sim." + command)
        app.runtime.device = other
        ui.ControlCenterApp.close(app)
        self.assertLess(log.index("device.close"), log.index("overlay.close"))
        self.assertIn("runtime.close", log)
        self.assertIn("sim.close", log)

    def test_no_device_uses_runtime_close(self):
        log = []
        app = make_app(log, None)
        ui.ControlCenterApp.close(app)
        self.assertIn("runtime.close", log)
        self.assertEqual(log[-1], "destroy")

    def test_a_refusing_bridge_does_not_stop_the_close(self):
        log = []
        app = make_app(log, None)
        app.device = Bridge(log, refuse=True)
        app.runtime.device = None   # runtime close must not hit the refusing bridge again
        ui.ControlCenterApp.close(app)
        self.assertIn("overlay.close", log)
        self.assertIn("stage.close", log)
        self.assertIn("runtime.close", log)
        self.assertIn("auth.stop", log)

    def test_already_closed_bridge_is_not_resubmitted(self):
        log = []
        app = make_app(log, None)
        app.device = Bridge(log)
        app.device.closed = True
        app.runtime.device = None
        ui.ControlCenterApp.close(app)
        self.assertNotIn("device.close", log)

    def test_second_close_is_a_no_op(self):
        log = []
        app = make_app(log, None)
        app.device = Bridge(log)
        app.runtime.device = app.device
        ui.ControlCenterApp.close(app)
        n = len(log)
        ui.ControlCenterApp.close(app)
        self.assertEqual(len(log), n)


if __name__ == "__main__":
    unittest.main()

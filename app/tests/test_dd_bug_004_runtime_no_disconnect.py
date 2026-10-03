"""DD-BUG-004 end to end: the real Runtime and Controller, standalone's KnobConnector and lifecycle_item, and a
fake bridge that validates `enter` like DeviceBridge._enter (a profile missing from the knob's inventory is
refused with retry=False). A knob whose inventory lacks MIDI SKIPPER is never disconnected or reconnected over
5 simulated minutes, whether the controller maps the missing profile to a stand-in or the bridge refuses it.
No Tk, no port, no network, no thread pool (a stand-in executor)."""
from pathlib import Path
from queue import Queue
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import standalone
from connector_support import knob
from control_center import runtime as runtime_module
from control_center.controller import Controller
from control_center.runtime import Runtime
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos
from test_cc_touch import HotkeyWindows, InlineExecutor

REFUSAL = 'Choose an inventoried existing profile'


def inventory(*names):
    return {name: {"name": name, "knob": [{"haptic": {"detentCount": 67}}]} for name in names}


class FakeBridge:
    """DeviceBridge's event shape: every event reaches the runtime queue and, as main() wires it, the
    connector's lifecycle queue through standalone.lifecycle_item."""

    def __init__(self, profiles, lifecycle):
        self.events = Queue()
        self.lifecycle = lifecycle
        self.profiles = profiles
        self.serial = None
        self.media_capability = None
        self.commands = []

    def emit(self, kind, **values):
        if kind in ('connected', 'ready', 'released', 'disconnected', 'closed', 'error'):
            self.lifecycle.put(standalone.lifecycle_item(kind, values))
        self.events.put({"kind": kind, **values})

    def submit(self, command, value=None):
        self.commands.append(command)
        if command == 'connect':
            self.serial = object()
            self.emit('connected', profiles=dict(self.profiles), current=None,
                      capabilities={"controlCenter": 1}, port=value)
        elif command == 'enter' and self.serial is not None:
            if not isinstance(value, dict) or value.get('profile') not in self.profiles:
                self.emit('error', message=REFUSAL, error='ValueError', retry=False,
                          profile=value.get('profile') if isinstance(value, dict) else None)
            else:
                self.emit('ready', id=value.get('id'))
        elif command == 'disconnect' and self.serial is not None:
            self.serial = None
            self.emit('disconnected', message='Knob disconnected')


class RuntimeNoDisconnectTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The connector's fresh controller: keep the one attached to the runtime (its state is known at once).
        keep = patch.object(standalone, 'fresh_controller', lambda previous, runtime=None: previous)
        keep.start()
        self.addCleanup(keep.stop)

    def build(self, profiles):
        lifecycle = Queue()
        controller = Controller()
        controller.state_known = True
        bridge = FakeBridge(profiles, lifecycle)
        runtime = Runtime(controller, SimulatedSonos(), SimulatedAppleMusic(), HotkeyWindows(), bridge)
        self.addCleanup(runtime.shutdown)
        app = type('App', (), {})()
        app.controller, app.runtime, app.device = controller, runtime, bridge
        app.config = {'port': '', 'button_order': [0, 1, 2, 3]}
        policy = standalone.RetryPolicy()
        made = standalone.KnobConnector(app, policy, lifecycle, lambda: [knob('COM5')])
        return app, bridge, runtime, made, policy

    def run_minutes(self, app, bridge, runtime, made, minutes=5):
        for second in range(minutes * 60):
            made.step(float(second))
            runtime._device_events()
            runtime.dispatch()
            runtime._device_events()

    def count(self, bridge, command):
        return bridge.commands.count(command)

    def test_inventory_without_midi_skipper_maps_and_never_disconnects(self):
        app, bridge, runtime, made, policy = self.build(inventory("BINARIS BEER", "MIDI CLACK JONES"))
        self.run_minutes(app, bridge, runtime, made)
        self.assertEqual(self.count(bridge, 'connect'), 1)
        self.assertEqual(self.count(bridge, 'disconnect'), 0)
        self.assertTrue(runtime.device_connected)
        self.assertIn("MIDI SKIPPER", runtime.device_status)
        self.assertIsNone(made.refused)

    def test_a_refused_control_holds_without_disconnecting(self):
        app, bridge, runtime, made, policy = self.build(inventory("BINARIS BEER", "MIDI CLACK JONES"))
        # A controller without the inventory mapping (or any refusal the bridge marks retry=False).
        app.controller.set_installed_profiles = None
        # A (re)connect enters Home; let Home's control name the missing MIDI SKIPPER.
        from control_center import controller as controller_module
        with patch.dict(controller_module.PROFILES, {"home": "MIDI SKIPPER"}):
            self.run_minutes(app, bridge, runtime, made)
        self.assertEqual(self.count(bridge, 'connect'), 1)
        self.assertEqual(self.count(bridge, 'disconnect'), 0)
        self.assertGreaterEqual(self.count(bridge, 'enter'), 1)
        self.assertTrue(runtime.device_connected)
        self.assertEqual(made.refused, REFUSAL)
        self.assertIn(REFUSAL, runtime.device_status)
        self.assertEqual(policy.attempts, 0)


if __name__ == "__main__":
    unittest.main()

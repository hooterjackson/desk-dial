"""DD-BUG-005 (standalone side): a knob on stock firmware connects with capabilities lacking controlCenter == 1 and
never sends 'ready'. maintain used to disconnect it after the 40 s timeout and retry, about every 70 s, and every
connect wrote a new inventory backup. Now such a connect is terminal for this plug-in: no timeout, no back-off, no
reconnect until the knob's port has gone away and come back (or the owner chooses Connect). The backup half is
bounded in device.py (identical inventories reuse the newest backup)."""
from pathlib import Path
import sys
import unittest
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import standalone
from connector_support import connector, fake_app, fresh_controller, knob

STOCK_EVENT = {'profiles': {'BINARIS BEER': {}}, 'capabilities': {}}


def connects(app):
    return [c for c in app.device.submit.call_args_list if c.args and c.args[0] == 'connect']


def disconnects(app):
    return [c for c in app.device.submit.call_args_list if c == call('disconnect')]


class LifecycleItemTests(unittest.TestCase):
    def test_a_connect_without_control_center_is_stock(self):
        self.assertEqual(standalone.lifecycle_item('connected', STOCK_EVENT), ('stock', frozenset({'BINARIS BEER'})))
        self.assertEqual(standalone.lifecycle_item('connected', {'capabilities': {'controlCenter': 0}}),
                         ('stock', None))

    def test_a_control_center_connect_is_unchanged(self):
        self.assertEqual(standalone.lifecycle_item('connected', {'profiles': {'A': {}},
                                                                 'capabilities': {'controlCenter': 1}}),
                         ('connected', frozenset({'A'})))
        self.assertEqual(standalone.lifecycle_item('connected', {'profiles': {'A': {}}}), ('connected', frozenset({'A'})))
        self.assertEqual(standalone.lifecycle_item('connected', {}), 'connected')


class StockFirmwareTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(standalone, 'fresh_controller', fresh_controller)
        patcher.start()
        self.addCleanup(patcher.stop)

    def connect_stock(self, ports):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app, ports)
        app.controller.state['online'] = True
        made.step(0.0)                      # found: prepare a fresh controller
        app.controller.state['online'] = True
        made.step(1.0)                      # connect
        self.assertEqual(len(connects(app)), 1)
        app.device.serial = object()
        app.runtime.device_connected = True
        lifecycle.put(standalone.lifecycle_item('connected', STOCK_EVENT))
        made.step(2.0)
        return app, made, policy, lifecycle

    def test_stock_firmware_knob_is_not_reconnected_and_backups_are_bounded(self):
        ports = [knob('COM5')]
        app, made, policy, lifecycle = self.connect_stock(ports)
        for second in range(3, 603):        # 10 simulated minutes
            made.step(float(second))
        self.assertEqual(len(connects(app)), 1)   # one connect = at most one inventory backup
        self.assertEqual(disconnects(app), [])
        self.assertFalse(policy.inflight)
        self.assertEqual(policy.attempts, 0)

    def test_a_dropped_stock_link_waits_for_the_port_to_go_and_come_back(self):
        ports = [knob('COM5')]
        app, made, policy, lifecycle = self.connect_stock(ports)
        app.device.serial = None
        app.runtime.device_connected = False
        lifecycle.put('error')
        lifecycle.put('disconnected')
        for second in range(3, 303):        # still plugged: no retry, no back-off
            made.step(float(second))
        self.assertEqual(len(connects(app)), 1)
        self.assertEqual(policy.attempts, 0)
        self.assertEqual(app.runtime.device_status, standalone.STOCK_STATUS)
        ports.clear()                       # unplugged
        made.step(303.0)
        self.assertFalse(made.stock)
        made.step(304.0)
        self.assertEqual(len(connects(app)), 1)
        ports.append(knob('COM5'))          # plugged in again: one new attempt (at the next 3 s port check)
        for second in range(305, 315):
            app.controller.state['online'] = True
            made.step(float(second))
        self.assertEqual(len(connects(app)), 2)

    def test_manual_connect_clears_the_stock_hold(self):
        app, made, policy, lifecycle = self.connect_stock([knob('COM5')])
        app.device.serial = None
        app.runtime.device_connected = False
        lifecycle.put('disconnected')
        made.step(3.0)
        made.clear_stock()             # what manual_connect does, with policy.due = 0
        policy.due = 0
        app.controller.state['online'] = True
        made.step(4.0)
        app.controller.state['online'] = True
        made.step(5.0)
        self.assertEqual(len(connects(app)), 2)

    def test_a_control_center_knob_still_times_out_without_ready(self):
        app = fake_app()
        made, policy, lifecycle = connector(standalone, app, [knob('COM5')])
        app.controller.state['online'] = True
        made.step(0.0)
        app.controller.state['online'] = True
        made.step(1.0)
        app.device.serial = object()
        lifecycle.put(standalone.lifecycle_item('connected', {'profiles': {}, 'capabilities': {'controlCenter': 1}}))
        for second in range(2, 50):
            made.step(float(second))
        self.assertEqual(len(disconnects(app)), 1)
        self.assertEqual(policy.attempts, 1)


if __name__ == '__main__':
    unittest.main()

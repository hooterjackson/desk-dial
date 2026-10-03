"""A fake app for standalone.KnobConnector tests: no Tk, no serial port, no network."""
import queue
from types import SimpleNamespace
from unittest.mock import Mock


def knob(device):
    return SimpleNamespace(device=device, vid=0x239A, pid=0x8010, serial_number='NANO_D')


def other(device):
    return SimpleNamespace(device=device, vid=0x0001, pid=0x0002, serial_number='other')


def fake_app(port=''):
    controller = SimpleNamespace(state={'online': False}, state_known=False)
    runtime = SimpleNamespace(device_connected=False, device_status='Knob disconnected', button_order=[],
                              last_frame=None, invalidate_actions=Mock(), attach=Mock(),
                              windows=SimpleNamespace(hide=Mock(), set_hotkey_enabled=Mock()))
    device = SimpleNamespace(serial=None, submit=Mock())
    return SimpleNamespace(controller=controller, runtime=runtime, device=device,
                           config={'port': port, 'button_order': [0, 1, 2, 3]}, closing=False)


def fresh_controller(previous, runtime=None):
    """Stands in for standalone.fresh_controller: a controller whose Sonos state is not in yet."""
    return SimpleNamespace(state={'online': False}, state_known=False)


def connector(standalone, app, ports=()):
    """A KnobConnector over ``app`` whose comports() lists ``ports``, with its policy and lifecycle queue.
    Patch standalone.fresh_controller with ``fresh_controller`` above while stepping it."""
    policy = standalone.RetryPolicy()
    lifecycle = queue.Queue()
    made = standalone.KnobConnector(app, policy, lifecycle, lambda: list(ports))
    return made, policy, lifecycle

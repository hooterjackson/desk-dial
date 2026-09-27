"""Runtime.note_touch: the floating knob's touch hook (FLOATING_KNOB.md section 5).

A physical position change, a button down edge (also the calibration probe's and the
Windows button's, logical 3 in desktop v7, whose serial edge the runtime then skips on Home
with the hotkey, or whenever it carries `hid`), an end-stop push (`limit`, also a controller
input, CONTROL_CENTER_V5.md section 10.4) and the F24 hotkey each record exactly one touch. Frames, heartbeats, lifecycle events, Sonos state and
external volume, media/artwork events and simulated input never do. No Tk, no port,
no thread pool (a stand-in executor).
"""
from pathlib import Path
from queue import Queue
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import runtime as runtime_module
from control_center.controller import Controller
from control_center.runtime import Runtime
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows


class InlineExecutor:
    """ThreadPoolExecutor stand-in: jobs are recorded, never run."""
    def __init__(self, **kwargs):
        self.jobs = []

    def submit(self, function, *args, **kwargs):
        from concurrent.futures import Future
        self.jobs.append((function, args))
        return Future()

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class FakeDevice:
    def __init__(self):
        self.events = Queue()
        self.commands = []
        self.media_capability = None

    def submit(self, *command):
        self.commands.append(command)


class HotkeyWindows(SimulatedWindows):
    """The live adapter's shape: F24 is authoritative for the Windows button."""
    supports_hotkey = True

    def __init__(self):
        super().__init__()
        self.shown = 0

    def show(self, snapshot):
        self.shown += 1


class TouchCase(unittest.TestCase):
    windows_class = HotkeyWindows

    def setUp(self):
        patcher = patch.object(runtime_module, "ThreadPoolExecutor", InlineExecutor)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.c = Controller()
        self.device = FakeDevice()
        self.windows = self.windows_class()
        self.runtime = Runtime(self.c, SimulatedSonos(), SimulatedAppleMusic(), self.windows, self.device)
        self.addCleanup(self.runtime.shutdown)

    def events(self, *events):
        for event in events:
            self.device.events.put(event)
        self.runtime._device_events()

    def connect(self):
        """connected + ready: the knob is claimed and the controller accepts input."""
        self.events({"kind": "connected", "capabilities": {"controlCenter": 1}})
        self.events({"kind": "ready", "id": self.c.control_id})
        self.assertTrue(self.c.ready)
        return self.runtime.touch_seq

    def assert_touches(self, expected, kind=None):
        self.assertEqual(self.runtime.touch_seq, expected)
        if kind is not None:
            self.assertEqual(self.runtime.last_touch_kind, kind)


class NoteTouchTests(TouchCase):
    def test_note_touch_only_records(self):
        self.assertEqual((self.runtime.touch_seq, self.runtime.last_touch, self.runtime.last_touch_kind),
                         (0, None, ""))
        with patch.object(runtime_module.time, "monotonic", return_value=123.5):
            self.runtime.note_touch("turn")
        self.assertEqual((self.runtime.touch_seq, self.runtime.last_touch, self.runtime.last_touch_kind),
                         (1, 123.5, "turn"))
        self.runtime.note_touch("sim")
        self.assertEqual((self.runtime.touch_seq, self.runtime.last_touch_kind), (2, "sim"))
        self.assertEqual(self.device.commands, [], "recording a touch sends nothing")


class PositionTouchTests(TouchCase):
    def test_every_position_event_is_a_touch_first_thing(self):
        seq = self.connect()
        with patch.object(self.c, "position", wraps=self.c.position) as position:
            self.events({"kind": "position", "id": self.c.control_id, "p": 3, "position": 3, "delta": 1})
        self.assert_touches(seq + 1, "turn")
        position.assert_called_once_with(3, self.c.control_id)
        # A stale id or an unchanged value is still a physical detent: the controller
        # ignores it, the touch counts.
        self.events({"kind": "position", "id": -5, "p": 3})
        self.assert_touches(seq + 2, "turn")

    def test_a_position_during_the_button_probe_is_a_touch(self):
        seq = self.connect()
        self.runtime.on_button_probe = lambda raw: None
        with patch.object(self.c, "position") as position:
            self.events({"kind": "position", "id": self.c.control_id, "p": 7})
        position.assert_not_called()
        self.assert_touches(seq + 1, "turn")

    def test_a_position_before_connect_is_a_touch_too(self):
        # The bridge only emits position for the ready control; the hook never filters.
        self.events({"kind": "position", "id": 1, "p": 2})
        self.assert_touches(1, "turn")


class ButtonTouchTests(TouchCase):
    def test_down_edges_of_every_button_are_touches(self):
        seq = self.connect()
        for raw in (0, 1, 3):
            with self.subTest(raw=raw):
                self.events({"kind": "button", "id": self.c.control_id, "button": raw, "index": raw,
                             "pressed": True})
                seq += 1
                self.assert_touches(seq, "button")

    def test_the_windows_button_is_a_touch_although_its_serial_edge_is_skipped(self):
        seq = self.connect()
        self.assertEqual(self.runtime.button_order[3], 3)
        with patch.object(self.c, "button", wraps=self.c.button) as button:
            self.events({"kind": "button", "id": self.c.control_id, "button": 3, "index": 3, "pressed": True})
        button.assert_not_called()   # presentation 4 on Home: F24 is authoritative for Windows entry
        self.assert_touches(seq + 1, "button")

    def test_a_hid_tagged_edge_is_a_touch_and_skipped(self):
        seq = self.connect()
        self.runtime.presentation_level = 5
        with patch.object(self.c, "button") as button:
            self.events({"kind": "button", "id": self.c.control_id, "button": 3, "hid": True})
        button.assert_not_called()
        self.assert_touches(seq + 1, "button")

    def test_a_remapped_windows_button_is_a_touch(self):
        self.runtime.button_order = [3, 1, 0, 2]
        seq = self.connect()
        with patch.object(self.c, "button") as button:
            self.events({"kind": "button", "id": self.c.control_id, "button": 2})   # logical 3
        button.assert_not_called()
        self.assert_touches(seq + 1, "button")

    def test_a_probe_press_is_a_touch(self):
        seq = self.connect()
        probed = []
        self.runtime.on_button_probe = probed.append
        self.events({"kind": "button", "id": self.c.control_id, "button": 3})
        self.assertEqual(probed, [3])
        self.assert_touches(seq + 1, "button")

    def test_up_edges_and_invalid_indexes_are_not_touches(self):
        seq = self.connect()
        for event in ({"kind": "button", "button": 1, "edge": "up"},
                      {"kind": "button", "button": 1, "edge": "release"},
                      {"kind": "button", "ku": 1},
                      {"kind": "button", "button": 1, "ku": 1},
                      {"kind": "button", "button": 4},
                      {"kind": "button", "button": -1},
                      {"kind": "button", "button": None},
                      {"kind": "button", "button": "1"},
                      {"kind": "button"}):
            with self.subTest(event=event):
                self.events(dict(event, id=self.c.control_id))
                self.assert_touches(seq)


class SimulatorWindowsButtonTests(TouchCase):
    """Without a hotkey (the simulator's windows), logical 3 goes to the controller; still one touch."""
    windows_class = SimulatedWindows

    def test_logical_three_reaches_the_controller_and_is_one_touch(self):
        seq = self.connect()
        with patch.object(self.c, "button") as button:
            self.events({"kind": "button", "id": self.c.control_id, "button": 3})
        button.assert_called_once_with(3, self.c.control_id, False)
        self.assert_touches(seq + 1, "button")


class LimitTouchTests(TouchCase):
    def test_a_limit_is_a_touch_and_a_controller_input(self):
        seq = self.connect()
        with patch.object(self.c, "limit") as limit:
            self.events({"kind": "limit", "id": self.c.control_id, "dir": 1})
        limit.assert_called_once_with(1, self.c.control_id)
        self.assert_touches(seq + 1, "limit")
        self.assertEqual((self.runtime.limit_seq, self.runtime.last_limit_dir), (1, 1))


class HotkeyTouchTests(TouchCase):
    def test_the_hotkey_is_a_touch_after_its_guard(self):
        seq = self.connect()
        self.runtime.hotkey()
        self.assert_touches(seq + 1, "hotkey")
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertEqual(self.windows.shown, 1)

    def test_a_guarded_hotkey_is_not_a_touch(self):
        # Disconnected (never connected).
        self.runtime.hotkey()
        self.assert_touches(0)
        seq = self.connect()
        # Calibration probe active.
        self.runtime.on_button_probe = lambda raw: None
        self.runtime.hotkey()
        self.assert_touches(seq)
        self.runtime.on_button_probe = None
        # Unsupported (released).
        self.events({"kind": "released"})
        self.runtime.hotkey()
        self.assert_touches(seq)
        # Closed.
        self.runtime.device_supported = True
        self.runtime.closed = True
        self.runtime.hotkey()
        self.assert_touches(seq)

    def test_the_windows_button_counts_twice_harmlessly(self):
        seq = self.connect()
        self.events({"kind": "button", "id": self.c.control_id, "button": 3})
        self.runtime.hotkey()
        self.assert_touches(seq + 2, "hotkey")


class NonTouchTests(TouchCase):
    def test_lifecycle_media_and_unknown_events_are_never_touches(self):
        for event in ({"kind": "connected", "capabilities": {"controlCenter": 1}},
                      {"kind": "ready", "id": self.c.control_id, "p": 12},
                      {"kind": "artwork-ready", "id": 1, "key": "abc"},
                      {"kind": "artwork-error", "id": 1, "key": "abc", "reason": "timeout"},
                      {"kind": "media-ready", "media": "cover", "key": "a" * 24},
                      {"kind": "media-error", "media": "icon", "key": "b" * 24, "error": "x"},
                      {"kind": "error", "message": "Device error"},
                      {"kind": "released"},
                      {"kind": "disconnected", "message": "Knob disconnected"},
                      {"kind": "closed"},
                      {"kind": "heartbeat"},
                      {"kind": "frame", "id": 1},
                      {"kind": "volume", "value": 40}):
            with self.subTest(kind=event["kind"]):
                self.events(event)
                self.assert_touches(0)

    def test_frames_heartbeats_and_external_volume_are_never_touches(self):
        seq = self.connect()
        for _ in range(3):
            self.runtime.poll()                          # frames and heartbeats to the knob
        self.assertTrue(any(command[0] == "frame" for command in self.device.commands))
        state = self.runtime.sonos.read_state()
        state["volume"] = (state.get("volume") or 0) + 7   # another app changed the volume
        request = self.c.request("state")
        self.c.complete(request, state)
        self.runtime.poll()
        self.assert_touches(seq)

    def test_simulated_input_is_never_a_touch(self):
        seq = self.connect()
        self.c.turn(1)
        self.c.position(5, self.c.control_id)
        self.c.button(1)
        self.runtime.poll()
        self.assert_touches(seq)


if __name__ == "__main__":
    unittest.main()

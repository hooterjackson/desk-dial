"""TL-BUG-007: device_inventory.py finds the knob by USB identity (239A:8010, serial NANO_D), never opens another
serial device, refuses while Desk Dial runs, and keeps --port as an override. Fake ports and a fake bridge: no
port is enumerated or opened."""
from pathlib import Path
import io
import queue
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import device_inventory as inv  # noqa: E402


def port(device, vid=None, pid=None, serial=None):
    return SimpleNamespace(device=device, vid=vid, pid=pid, serial_number=serial)


OTHER = port("COM8", 0x1A86, 0x7523, None)                 # an unrelated USB-serial adapter
KNOB = port("COM5", 0x239A, 0x8010, "NANO_D")
ROM = port("COM9", 0x303A, 0x1001, "ROMSERIAL")


class FakeBridge:
    instances = []

    def __init__(self, folder):
        self.submitted, self.events = [], queue.Queue()
        self._thread = SimpleNamespace(join=lambda timeout=None: None)
        FakeBridge.instances.append(self)

    def submit(self, kind, *args):
        self.submitted.append((kind, *args))
        if kind == "connect":
            self.events.put({"kind": "connected", "backup": "b.json", "current": 0, "profiles": ["x"],
                             "capabilities": {"controlCenter": 1}})


class InventoryPortTests(unittest.TestCase):
    def setUp(self):
        FakeBridge.instances.clear()

    def run_main(self, argv, ports, running=False):
        with redirect_stdout(io.StringIO()):
            inv.main(argv, lister=lambda: ports, running=lambda: running, bridge_factory=FakeBridge, timeout=2)
        [bridge] = FakeBridge.instances
        return [args for kind, *args in bridge.submitted if kind == "connect"]

    def test_inventory_discovers_app_port_and_never_opens_unmatched(self):
        self.assertEqual(self.run_main([], [OTHER, KNOB, ROM]), [["COM5"]])

    def test_no_or_two_knobs_refuse_before_anything_is_opened(self):
        for ports in ([OTHER, ROM], [KNOB, port("COM6", 0x239A, 0x8010, "nano_d")]):
            with self.subTest(ports=[p.device for p in ports]):
                with self.assertRaises(SystemExit) as caught:
                    inv.main([], lister=lambda: ports, running=lambda: False, bridge_factory=FakeBridge)
                self.assertIn("Nothing was opened", str(caught.exception))
                self.assertEqual(FakeBridge.instances, [])

    def test_port_override_is_kept(self):
        self.assertEqual(self.run_main(["--port", "COM7"], []), [["COM7"]])

    def test_refuses_while_desk_dial_runs(self):
        with self.assertRaises(SystemExit) as caught:
            inv.main([], lister=lambda: [KNOB], running=lambda: True, bridge_factory=FakeBridge)
        self.assertIn("Desk Dial is running", str(caught.exception))
        self.assertEqual(FakeBridge.instances, [])

    def test_companion_check_reads_the_single_instance_mutex(self):
        opened, closed = [], []

        class Kernel:
            def __init__(self, exists):
                self.exists = exists

            def OpenMutexW(self, access, inherit, name):
                opened.append(name)
                return 1234 if self.exists else None

            def CloseHandle(self, handle):
                closed.append(handle)

        self.assertTrue(inv.companion_running(Kernel(True)))
        self.assertFalse(inv.companion_running(Kernel(False)))
        self.assertEqual(opened, [inv.COMPANION_MUTEX] * 2)
        self.assertEqual(closed, [1234])

    def test_no_fixed_com_default(self):
        source = (Path(inv.__file__)).read_text(encoding="utf-8")
        self.assertNotIn('default="COM', source)


if __name__ == "__main__":
    unittest.main()

"""DD-BUG-014: a device lost inside its own creation warm-up (DXGI_ERROR_DEVICE_REMOVED mid-TDR)
counts as a failed attempt, so the recreate cap (at most twice, 1 s apart) holds instead of a
tight recreate loop with a zero wait. Headless: the fake device, no window, no GPU."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
for p in (ROOT, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from control_center.stage import com  # noqa: E402
from control_center.stage.device import COLD, LOST, WARM, DevicePolicy  # noqa: E402
from test_stage_engine import Rig  # noqa: E402


def _lose_in_warm_up(rig):
    """Every new device fails its first GetFrameStatistics with DEVICE_REMOVED (the warm-up read)."""
    make = rig.engine.device_factory

    def factory():
        dev = make()
        dev.fail_next("GetFrameStatistics", com.DXGI_ERROR_DEVICE_REMOVED)
        return dev
    rig.engine.device_factory = factory


class EngineTests(unittest.TestCase):
    def test_device_lost_during_creation_respects_recreate_cap(self):
        r = Rig()
        _lose_in_warm_up(r)
        r.presenter.note_touch()
        waits = []
        for _ in range(50):
            waits.append(r.run())
            r.clk.advance(0.25)
        creates = r.engine.counters["device_creates"]
        self.assertLessEqual(creates, 3)
        self.assertGreaterEqual(creates, 2)                        # the one retry, 1 s later
        self.assertIsNone(r.engine.device)
        self.assertEqual(r.engine.policy.state, COLD)              # the next open tries again
        self.assertNotIn(0.0, waits[1:])                           # no zero-wait spin
        removed = [m for m in r.logs if "GetDeviceRemovedReason" in m]
        self.assertEqual(len(removed), 1)                          # once across back-to-back recreations

    def test_normal_loss_still_recreates_at_once(self):
        r = Rig()
        r.open()
        r.dev.fail_next("Commit", com.DXGI_ERROR_DEVICE_REMOVED)
        r.clk.advance(0.05)
        r.presenter.explorer_highlight({"index": 13, "control_id": 1})
        r.run()
        self.assertEqual(r.engine.policy.state, LOST)
        r.run()
        self.assertEqual(r.engine.policy.state, WARM)
        self.assertEqual(len(r.devices), 2)


class PolicyTests(unittest.TestCase):
    def test_loss_while_creating_keeps_the_attempt_count(self):
        p = DevicePolicy()
        p.created(0.0)
        p.lost(10.0)
        self.assertTrue(p.recreate_due(10.0))
        p.created(10.0)
        p.lost_while_creating(10.0)
        self.assertEqual(p.state, LOST)
        self.assertFalse(p.recreate_due(10.5))
        self.assertTrue(p.recreate_due(11.0))
        p.created(11.0)
        p.lost_while_creating(11.0)
        self.assertEqual(p.state, COLD)
        self.assertFalse(p.recreate_due(30.0))
        self.assertIsNone(p.next_wake())


if __name__ == "__main__":
    unittest.main()

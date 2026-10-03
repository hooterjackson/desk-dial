"""DD-RES-010 (runtime side): the Home Assistant lane's except handlers in Runtime log a code bug
with its traceback (exc_info), so a KeyError / TypeError in the adapter is not reduced to a bare
class name in the log."""
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center.runtime import Runtime  # noqa: E402

LOGGER = "control_center.runtime"


def _boom(*_a, **_k):
    raise KeyError("brightness")


class _Adapter:
    def __init__(self, close=None, start=None, read=None):
        self.close = close or (lambda: None)
        self.start = start or (lambda: None)
        self.read_state = read or (lambda: {"configured": True})
        self.set_listener = lambda fn: None


def _rt(old=None):
    return SimpleNamespace(ha=old, results=queue.Queue())


class RuntimeHaTracebackTests(unittest.TestCase):
    def _assert_traceback(self, cm, text):
        recs = [r for r in cm.records if text in r.getMessage()]
        self.assertEqual(len(recs), 1, [r.getMessage() for r in cm.records])
        self.assertEqual(recs[0].levelname, "WARNING")
        self.assertIsNotNone(recs[0].exc_info)
        self.assertIs(recs[0].exc_info[0], KeyError)

    def test_close_failure_carries_traceback(self):
        rt = _rt(old=_Adapter(close=_boom))
        with self.assertLogs(LOGGER, "WARNING") as cm:
            Runtime.set_home_assistant(rt, None)
        self._assert_traceback(cm, "adapter not closed")

    def test_start_failure_carries_traceback(self):
        rt = _rt()
        with self.assertLogs(LOGGER, "WARNING") as cm:
            Runtime.set_home_assistant(rt, _Adapter(start=_boom))
        self._assert_traceback(cm, "adapter not started")

    def test_read_failure_carries_traceback(self):
        rt = _rt()
        with self.assertLogs(LOGGER, "WARNING") as cm:
            Runtime.set_home_assistant(rt, _Adapter(read=_boom))
        self._assert_traceback(cm, "state not read")

    def test_resync_failure_carries_traceback(self):
        rt = SimpleNamespace(ha=_Adapter(read=_boom), _ha_resync_at=0.0,
                             controller=SimpleNamespace(lights_state=lambda s: None),
                             HA_RESYNC_S=Runtime.HA_RESYNC_S)
        with self.assertLogs(LOGGER, "WARNING") as cm:
            Runtime._ha_resync(rt, 1.0)
        self._assert_traceback(cm, "state not re-read")

    def test_healthy_adapter_logs_nothing(self):
        rt = _rt()
        with self.assertNoLogs(LOGGER, "WARNING"):
            Runtime.set_home_assistant(rt, _Adapter())
        self.assertEqual(rt.results.get_nowait(), ("lights_state", {"configured": True}))


if __name__ == "__main__":
    unittest.main()

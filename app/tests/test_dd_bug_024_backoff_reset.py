"""DD-BUG-024: a WebSocket drop after a healthy session (its first states arrived) starts the
reconnect back-off over, so the 5th nightly drop does not wait 30 s in REST fallback; each wait is
spread by +-20 % jitter. A session that never worked keeps backing off.

Offline: fake WebSocket server from test_cc_home_assistant (no network, no Tk)."""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402

import test_cc_home_assistant as base  # noqa: E402
from test_cc_home_assistant import AdapterCase, FakeServer, wait_for  # noqa: E402

setUpModule = base.setUpModule          # never a real WebSocket / HTTP session
tearDownModule = base.tearDownModule


class BackoffResetTests(AdapterCase):
    def test_the_backoff_resets_after_a_healthy_session(self):
        with patch.object(ha_module, "BACKOFF", (0.02, 5.0)):
            adapter = self.make(rest_poll=0.01)
            adapter.start()
            for drop in range(3):
                with self.subTest(drop=drop):
                    self.assertTrue(wait_for(lambda: len(self.server.sockets) == drop + 1
                                             and adapter.read_state()["transport"] == "ws"))
                    started = time.monotonic()
                    self.server.sockets[-1].close()
                    self.assertTrue(wait_for(lambda: len(self.server.sockets) == drop + 2, timeout=1.0),
                                    "the reconnect waited the second back-off step")
                    self.assertLess(time.monotonic() - started, 1.0)

    def test_a_missing_pong_after_a_healthy_session_also_resets(self):
        server = FakeServer(answer_pings=False)
        with patch.object(ha_module, "PING_SECONDS", 0.05), patch.object(ha_module, "PONG_TIMEOUT", 0.1), \
                patch.object(ha_module, "RECV_TIMEOUT", 0.02), patch.object(ha_module, "BACKOFF", (0.02, 5.0)):
            adapter = self.make(server, rest_poll=0.01)
            adapter.start()
            self.assertTrue(wait_for(lambda: len(server.sockets) >= 3, timeout=3))

    def test_reconnect_delay_is_jittered_within_twenty_percent(self):
        with patch.object(ha_module, "BACKOFF", (1.0, 2.0, 30.0)):
            for attempt, base_delay in ((0, 1.0), (1, 2.0), (2, 30.0), (9, 30.0)):
                values = [ha_module.reconnect_delay(attempt) for _ in range(200)]
                self.assertTrue(all(0.8 * base_delay <= v <= 1.2 * base_delay for v in values), (attempt, values[:5]))
                self.assertGreater(len(set(values)), 1, "jittered")


class AttemptSequenceTests(unittest.TestCase):
    def test_attempts_reset_on_ok_and_grow_on_failures(self):
        adapter = ha_module.HomeAssistantAdapter("http://homeassistant.local:8123", base.TOKEN, "light.den", (),
                                                 ws_factory=lambda url, timeout: None, http=base.FakeHttp())
        self.addCleanup(adapter.close)
        outcomes = ["error", "error", "ok", "error", "ok"]
        seen = []

        def session():
            if not outcomes:
                adapter._stop.set()
                return "error"
            return outcomes.pop(0)
        adapter._session_ws = session
        adapter._rest_refresh = lambda: True
        adapter._now = lambda: 0.0
        adapter._stop.wait = lambda seconds: False

        def recorded(attempt):
            seen.append(attempt)
            return 0.0                                  # no REST window
        with patch.object(ha_module, "reconnect_delay", recorded):
            adapter._run()
        self.assertEqual(seen, [0, 1, 0, 1, 0])


if __name__ == "__main__":
    unittest.main()

"""DD-BUG-049: a rejected Home Assistant token is not retried every 60 s forever.

Each auth_invalid (or REST 401) is a failed login in Home Assistant; with login_attempts_threshold
set the PC's IP gets banned. After a rejected token the reader backs off 60 s doubling up to 1 h (a
token saved in Settings builds a new adapter, which starts fresh), and a 403 (the ban) is its own
outcome, ``forbidden``, not "token rejected". Offline fakes only.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402
from control_center.home_assistant import HomeAssistantAdapter, HomeAssistantError, auth_backoff  # noqa: E402
from test_cc_home_assistant import FakeHttp, FakeServer  # noqa: E402

BASE = "http://homeassistant.local:8123"


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class BackoffScheduleTests(unittest.TestCase):
    def test_doubles_from_a_minute_to_an_hour(self):
        self.assertEqual([auth_backoff(n) for n in range(8)], [60, 120, 240, 480, 960, 1920, 3600, 3600])
        self.assertEqual(auth_backoff(10 ** 6), 3600)


class AuthBackoffTests(unittest.TestCase):
    def test_auth_invalid_does_not_retry_forever(self):
        server = FakeServer()
        times = []
        connect = server.connect
        server.connect = lambda url, timeout: (times.append(time.monotonic()), connect(url, timeout))[1]
        adapter = HomeAssistantAdapter(BASE, "wrong-token", "light.den", ws_factory=server.connect, http=FakeHttp())
        self.addCleanup(adapter.close)
        with patch.object(ha_module, "AUTH_BACKOFF", 0.1), patch.object(ha_module, "AUTH_BACKOFF_MAX", 100.0):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["reason"] == "auth"))
            time.sleep(1.0)
            count = len(server.sockets)
            adapter.close()
        self.assertLessEqual(count, 4, "a flat 0.1 s back-off would have made ~10 attempts")
        gaps = [b - a for a, b in zip(times, times[1:])]
        for before, after in zip(gaps, gaps[1:]):
            self.assertGreater(after, before * 1.5, gaps)
        self.assertEqual(adapter.read_state()["reason"], "auth")

    def test_a_rest_401_backs_off_too(self):
        http = FakeHttp(status=401)
        adapter = HomeAssistantAdapter(BASE, "wrong-token", "light.den", ws_factory=lambda url, timeout: None,
                                       http=http, rest_poll=0.02)
        self.addCleanup(adapter.close)
        with patch.object(ha_module, "AUTH_BACKOFF", 0.2), patch.object(ha_module, "AUTH_BACKOFF_MAX", 100.0), \
                patch.object(ha_module, "BACKOFF", (0.05,)):
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["reason"] == "auth"))
            time.sleep(1.0)
            adapter.close()
        refreshes = len([r for r in http.requests if r[0] == "GET"])
        self.assertLessEqual(refreshes, 4 * 4, "polling every 0.02 s would have made ~50 failed logins")


class ForbiddenTests(unittest.TestCase):
    def test_a_403_is_forbidden_not_a_rejected_token(self):
        adapter = HomeAssistantAdapter(BASE, "t0k", "light.den", ws_factory=lambda url, timeout: None,
                                       http=FakeHttp(status=403))
        self.addCleanup(adapter.close)
        with self.assertRaises(HomeAssistantError) as caught:
            adapter._rest("GET", "/api/")
        self.assertEqual(caught.exception.outcome, "forbidden")
        adapter._rest_refresh()
        self.assertEqual(adapter.read_state()["reason"], "forbidden")
        with self.assertRaises(HomeAssistantError) as caught:
            adapter.call_service("light", "turn_on", {"entity_id": "light.den", "brightness_pct": 30})
        self.assertEqual(caught.exception.outcome, "forbidden")
        result = adapter.test_connection()
        self.assertEqual((result["ok"], result["outcome"]), (False, "forbidden"))
        self.assertIn("403", result["message"])
        self.assertNotIn("token", result["message"].lower())


if __name__ == "__main__":
    unittest.main()

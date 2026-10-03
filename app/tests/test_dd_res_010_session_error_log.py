"""DD-RES-010: a bug inside the WebSocket session (say a KeyError from another Home Assistant's data
shape) is logged at WARNING with its traceback, once per exception type; a network drop keeps the
quiet INFO line without a traceback.

Offline: fake WebSocket server from test_cc_home_assistant (no network, no Tk)."""
import json
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import home_assistant as ha_module  # noqa: E402

import test_cc_home_assistant as base  # noqa: E402
from test_cc_home_assistant import TOKEN, AdapterCase, wait_for  # noqa: E402

setUpModule = base.setUpModule          # never a real WebSocket / HTTP session
tearDownModule = base.tearDownModule


class Keep(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class SessionErrorLogTests(AdapterCase):
    def setUp(self):
        self.keep = Keep()
        logger = logging.getLogger("control_center.home_assistant")
        old = logger.level
        logger.addHandler(self.keep)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(lambda: (logger.removeHandler(self.keep), logger.setLevel(old)))

    def session_lines(self):
        return [r for r in self.keep.records
                if r.getMessage().startswith(("Home Assistant session failed", "Home Assistant connection dropped"))]

    def test_a_programming_error_in_the_session_is_logged_with_traceback(self):
        with patch.object(ha_module, "BACKOFF", (0.02,)):
            adapter = self.make(rest_poll=0.01)

            def broken(states):                  # the session's get_states handling hits a bug
                raise KeyError("attributes")
            adapter._replace_states = broken
            adapter.start()
            self.assertTrue(wait_for(lambda: len(self.server.sockets) >= 3))
            adapter.close()
        lines = self.session_lines()
        warnings = [r for r in lines if r.levelno == logging.WARNING]
        self.assertEqual(len(warnings), 1, "once per exception type")
        self.assertIsNotNone(warnings[0].exc_info)
        self.assertIs(warnings[0].exc_info[0], KeyError)
        self.assertIn("KeyError", warnings[0].getMessage())
        later = [r for r in lines if r.levelno == logging.INFO]
        self.assertTrue(later and all(r.exc_info is None and "KeyError" in r.getMessage() for r in later),
                        "the repeats keep the short line")
        formatted = "\n".join(logging.Formatter().format(r) for r in self.keep.records)
        self.assertNotIn(TOKEN, formatted)

    def test_a_socket_drop_logs_only_the_info_line(self):
        with patch.object(ha_module, "BACKOFF", (0.02,)):
            adapter = self.make(rest_poll=0.01)
            adapter.start()
            self.assertTrue(wait_for(lambda: adapter.read_state()["transport"] == "ws"))
            self.server.sockets[0].close()                      # ConnectionError("closed")
            self.assertTrue(wait_for(lambda: len(self.server.sockets) >= 2))
            adapter.close()
        lines = self.session_lines()
        self.assertTrue(lines)
        self.assertTrue(all(r.levelno == logging.INFO and r.exc_info is None for r in lines), lines)

    def test_network_errors_are_recognised(self):
        class WebSocketConnectionClosedException(Exception):
            pass

        class WebSocketTimeoutException(WebSocketConnectionClosedException):
            pass
        for exc in (OSError("x"), ConnectionResetError(), TimeoutError(), WebSocketConnectionClosedException(),
                    WebSocketTimeoutException()):
            self.assertTrue(ha_module.is_network_error(exc), exc)
        try:
            json.loads("{")
        except ValueError as bad_frame:
            self.assertTrue(ha_module.is_network_error(bad_frame))
        for exc in (KeyError("a"), TypeError(), AttributeError(), IndexError()):
            self.assertFalse(ha_module.is_network_error(exc), exc)


if __name__ == "__main__":
    unittest.main()

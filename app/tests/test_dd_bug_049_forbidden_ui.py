"""DD-BUG-049 (UI side): Home Assistant's HTTP 403 ('forbidden', usually an IP ban after failed
logins) gets its own copy in the Settings strip and the Test connection result, not "can't reach".
No Tk, no network."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ui  # noqa: E402
from control_center.controller import LightsState  # noqa: E402
from control_center.home_assistant import FORBIDDEN_MESSAGE  # noqa: E402


class StripColumnTests(unittest.TestCase):
    def column(self, **lights):
        runtime = SimpleNamespace(ha=SimpleNamespace(read_state=lambda: {}),
                                  controller=SimpleNamespace(lights=LightsState(**lights)))
        return ui.ha_strip_column(runtime)

    def test_forbidden_is_blocked(self):
        column = self.column(configured=True, online=False, reason="forbidden", known=True)
        self.assertEqual(column["state"], "Blocked by Home Assistant")
        self.assertIn("ip_bans.yaml", column["detail"])
        self.assertTrue(column["primary"])
        self.assertFalse(column["ok"])

    def test_auth_and_offline_unchanged(self):
        self.assertEqual(self.column(configured=True, online=False, reason="auth", known=True)["state"],
                         "Token rejected")
        self.assertEqual(self.column(configured=True, online=False, reason="offline", known=True)["state"],
                         "Not reachable")


class SettingsTestModelTests(unittest.TestCase):
    def model(self):
        model = ui.HaSettingsModel({"ha_base_url": "http://homeassistant.local:8123"}, saved_token=True)
        address, error = model.begin_test()
        self.assertIsNotNone(address, error)
        return model

    def test_forbidden_uses_adapter_message(self):
        model = self.model()
        self.assertTrue(model.finish_test({"ok": False, "outcome": "forbidden", "message": FORBIDDEN_MESSAGE},
                                          model.generation))
        self.assertEqual(model.status, "error")
        self.assertEqual(model.error, FORBIDDEN_MESSAGE)
        self.assertNotEqual(model.error, ui.ha_unreachable(model.tested_address))

    def test_forbidden_without_message_has_copy(self):
        model = self.model()
        model.finish_test({"ok": False, "outcome": "forbidden"}, model.generation)
        self.assertEqual(model.error, ui.HA_FORBIDDEN_DETAIL)

    def test_auth_and_offline_unchanged(self):
        model = self.model()
        model.finish_test({"ok": False, "outcome": "auth"}, model.generation)
        self.assertEqual(model.error, ui.HA_TOKEN_REJECTED)
        model = self.model()
        model.finish_test({"ok": False, "outcome": "offline"}, model.generation)
        self.assertEqual(model.error, ui.ha_unreachable(model.tested_address))


if __name__ == "__main__":
    unittest.main()

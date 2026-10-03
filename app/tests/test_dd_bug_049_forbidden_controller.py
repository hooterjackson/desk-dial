"""DD-BUG-049 (controller side): a Home Assistant 403 ('forbidden', usually an IP ban) is handled
like a rejected token: the lights go offline with reason 'forbidden', the knob says it is blocked,
and the blocked view shows the error activity, not a generic 'Didn't change'."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r3_support import R3Fixture  # noqa: E402
from control_center.controller import COPY  # noqa: E402
from control_center.home_assistant import FORBIDDEN_MESSAGE, HomeAssistantError  # noqa: E402


class ForbiddenFailureTests(R3Fixture):
    def setUp(self):
        super().setUp()
        self.lights()

    def fail(self):
        self.c._lights_failure(HomeAssistantError(FORBIDDEN_MESSAGE, "forbidden"), "knob.meta.lights.failed")

    def test_forbidden_takes_the_lights_offline(self):
        self.fail()
        self.assertFalse(self.c.lights.online)
        self.assertEqual(self.c.lights.reason, "forbidden")
        self.assertEqual(self.c.feedback["kind"], "err")

    def test_forbidden_shows_the_blocked_transient(self):
        self.fail()
        self.assertEqual(self.transient(), COPY["knob.meta.lights.blocked"])
        self.assertNotEqual(self.transient(), COPY["knob.meta.lights.failed"])

    def test_blocked_view_uses_the_error_activity(self):
        self.fail()
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["activity"]),
                         ("Not connected", "Home Assistant", "error"))

    def test_auth_unchanged(self):
        self.c._lights_failure(HomeAssistantError("refused", "auth"), "knob.meta.lights.failed")
        self.assertEqual(self.c.lights.reason, "auth")
        self.assertEqual(self.transient(), COPY["knob.meta.lights.signin"])

    def test_copy_typography(self):
        text = COPY["knob.meta.lights.blocked"]
        self.assertNotIn("'", text)
        self.assertLessEqual(len(text), len(COPY["knob.meta.lights.signin"]))


if __name__ == "__main__":
    unittest.main()

"""DD-BUG-049: CONTROL_CENTER_V5.md describes the Home Assistant back-off and REST poll as coded."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from control_center import home_assistant as ha  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _adapter_paragraph():
    with open(os.path.join(ROOT, "CONTROL_CENTER_V5.md"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("- `HomeAssistantAdapter("):
                return line
    raise AssertionError("adapter paragraph missing from the spec")


class SpecMatchesCode(unittest.TestCase):
    def setUp(self):
        self.text = _adapter_paragraph()

    def test_auth_backoff_wording(self):
        self.assertNotIn("(60 s after `auth_invalid`)", self.text)
        self.assertIn("60 s doubling up to 1 h", self.text)
        self.assertIn("a 403 is reported as `forbidden`", self.text)
        self.assertEqual(ha.AUTH_BACKOFF, 60.0)
        self.assertEqual(ha.AUTH_BACKOFF_MAX, 3600.0)

    def test_rest_poll_wording(self):
        self.assertIn("one `GET /api/states`", self.text)
        self.assertIn("area template at most every 60 s", self.text)
        self.assertIn("every 2 s stretching to 10 s after 3 failed WebSocket attempts", self.text)
        self.assertEqual(ha.REGISTRY_POLL_SECONDS, 60.0)
        self.assertEqual(ha.REST_POLL_SECONDS, 2.0)
        self.assertEqual(ha.REST_POLL_SECONDS * ha.REST_POLL_STRETCH, 10.0)
        self.assertEqual(ha.REST_STRETCH_AFTER, 3)


if __name__ == "__main__":
    unittest.main()

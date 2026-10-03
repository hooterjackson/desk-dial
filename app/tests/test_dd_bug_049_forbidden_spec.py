"""DD-BUG-049 (spec side): CONTROL_CENTER_V5.md's Lights failures line covers the 'forbidden' reason
(HTTP 403) with the same copy the controller and the Settings page use. No Tk, no network."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from control_center import ui  # noqa: E402
from control_center.controller import COPY  # noqa: E402


def _failures_line():
    with open(os.path.join(ROOT, "CONTROL_CENTER_V5.md"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("- **Failures:** `offline` / `auth`"):
                return line
    raise AssertionError("Lights failures line missing from the spec")


class ForbiddenSpecTests(unittest.TestCase):
    def setUp(self):
        self.text = _failures_line()

    def test_forbidden_reason_is_specified(self):
        self.assertIn("`forbidden` (HTTP 403", self.text)
        self.assertIn("FORBIDDEN_MESSAGE", self.text)
        self.assertIn("ip_bans.yaml", self.text)

    def test_spec_copy_matches_code(self):
        self.assertIn(f"`{COPY['knob.meta.lights.blocked']}`", self.text)
        self.assertIn("ip_bans.yaml", ui.HA_FORBIDDEN_DETAIL)

    def test_auth_copy_still_specified(self):
        self.assertIn("`Home Assistant sign-in · Check the token in Settings`", self.text)
        self.assertIn("`Not allowed in Desk Dial`", self.text)


if __name__ == "__main__":
    unittest.main()

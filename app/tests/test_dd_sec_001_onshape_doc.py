"""DD-SEC-001 / DD-BUG-027: ONSHAPE.md documents that keystrokes need the keyboard focus inside the Onshape page
under the cursor (UI Automation), that a refusal shows the usual 'refused' feedback, and that the 'no keys while a
real modifier is held' rule covers parameter scrolls and typed values. Text-only: no Tk, no ports, no network."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


def section(number):
    text = (ROOT / "ONSHAPE.md").read_text(encoding="utf-8")
    match = re.search(r"^## %d\..*?(?=^## %d\.)" % (number, number + 1), text, re.S | re.M)
    assert match, "ONSHAPE.md has no section %d" % number
    return " ".join(match.group(0).split())


class KeyboardFocusDocTest(unittest.TestCase):
    def test_target_section_requires_focus_in_the_page(self):
        sec = section(6)
        self.assertIn("Keystrokes also need the keyboard focus in the page", sec)
        self.assertIn("UI Automation", sec)
        self.assertIn("browser_url.focus_in_page", sec)
        for keyed in ("Undo", "B-mode typing", "Ctrl / Shift parameter scrolls", "tool search"):
            self.assertIn(keyed, sec)
        for elsewhere in ("address bar", "find bar", "DevTools"):
            self.assertIn(elsewhere, sec)

    def test_a_focus_refusal_shows_the_usual_refused_feedback(self):
        sec = section(6)
        self.assertIn("usual `refused` feedback", sec)
        self.assertIn("once per burst", sec)
        self.assertIn("focusRefused", sec)

    def test_status_lists_the_focus_refused_count(self):
        self.assertIn("`focusRefused`", section(8))

    def test_modifier_rule_covers_scrolls_and_typed_values(self):
        sec = section(13)
        self.assertIn("keyboard focus inside that page", sec)
        self.assertIn("no keys while a real modifier is held", sec)
        self.assertIn("parameter scrolls", sec)
        self.assertIn("typed value", sec)
        self.assertIn("commandsSkipped", sec)

    def test_documented_names_exist_in_code(self):
        url = (ROOT / "control_center" / "browser_url.py").read_text(encoding="utf-8")
        self.assertIn("def focus_in_page(", url)
        # App profiles (DD-B): the injector's counters live in the engine onshape.py's injector runs on.
        source = "".join((ROOT / "control_center" / name).read_text(encoding="utf-8")
                         for name in ("onshape.py", "app_engine.py"))
        self.assertIn("KEY_FOCUS_CACHE_SECONDS = 0.25 ", source)
        self.assertIn('"focusRefused"', source)


if __name__ == "__main__":
    unittest.main()

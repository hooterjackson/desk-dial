"""DD-BUG-018 (tray side): Show knob is greyed out while nothing can show, and a click
(the default left click included) that shows nothing queues one explaining balloon."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import standalone  # noqa: E402
from standalone import (TrayState, build_tray_menu, peek_available, show_knob_request,  # noqa: E402
                        tray_menu_model)


class FakeApp:
    def __init__(self, shows, connected=False, available=True):
        self.shows, self.available = shows, available
        self.runtime = SimpleNamespace(device_connected=connected)
        self.tray_messages = []
        self.peeks = []

    def peek(self, seconds):
        self.peeks.append(seconds)
        return self.shows

    def peek_available(self):
        if isinstance(self.available, Exception):
            raise self.available
        return self.available


class MenuEnabledTests(unittest.TestCase):
    def test_model_greys_show_knob_only_when_nothing_can_show(self):
        self.assertTrue(tray_menu_model("", True, True)[2][2])
        model = tray_menu_model("", False, peek=False)
        self.assertEqual(model[2][:2], ("Show knob", "peek"))
        self.assertFalse(model[2][2])
        self.assertTrue(model[2][3])                 # still the default (left click)
        self.assertEqual([entry[2] for entry in model], [False, False, False, True, True, True, True])

    def test_pystray_item_reads_the_flag_when_the_menu_is_built(self):
        import pystray
        state, queued = TrayState("Knob disconnected", False, peek=False), []
        menu = build_tray_menu(SimpleNamespace(Menu=pystray.Menu, MenuItem=pystray.MenuItem), state, queued.append)
        items = list(menu.items)
        self.assertFalse(items[2].enabled)
        self.assertTrue(all(item.enabled for item in items[3:]))
        state.peek = True                           # the Tk tick refreshed it
        self.assertTrue(items[2].enabled)
        menu(object())                              # the left click still queues the request
        self.assertEqual(queued, ["peek"])

    def test_peek_available_is_false_when_the_app_fails(self):
        self.assertTrue(peek_available(FakeApp(True)))
        self.assertFalse(peek_available(FakeApp(True, available=False)))
        self.assertFalse(peek_available(FakeApp(True, available=RuntimeError("x"))))
        self.assertFalse(peek_available(SimpleNamespace()))


class ShowKnobRequestTests(unittest.TestCase):
    def test_a_peek_that_shows_queues_nothing(self):
        app = FakeApp(True, connected=True)
        self.assertTrue(show_knob_request(app, standalone.PEEK_SECONDS))
        self.assertEqual(app.peeks, [standalone.PEEK_SECONDS])
        self.assertEqual(app.tray_messages, [])

    def test_no_knob_gives_one_balloon_even_after_repeated_clicks(self):
        app = FakeApp(False, connected=False)
        self.assertFalse(show_knob_request(app))
        self.assertFalse(show_knob_request(app))
        self.assertEqual(app.tray_messages, [standalone.TRAY_PEEK_NO_KNOB])
        self.assertEqual(app.tray_messages[0], "Nothing to show: connect the knob")

    def test_connected_but_nothing_to_show_says_so(self):
        app = FakeApp(False, connected=True)
        app.tray_messages = ()                      # the class default before the first message
        show_knob_request(app)
        self.assertEqual(app.tray_messages, [standalone.TRAY_PEEK_NOTHING])

    def test_texts_fit_a_balloon(self):
        for text in (standalone.TRAY_PEEK_NO_KNOB, standalone.TRAY_PEEK_NOTHING):
            self.assertEqual(standalone.utf16_cut(text, standalone.BALLOON_TEXT_LIMIT), text)


if __name__ == "__main__":
    unittest.main()

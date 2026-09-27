"""Stage 4b runtime presentation, desktop v7 (K3 sections 10.4 and 11): targeted-colour
decoration, art rules and the accent/icon service wiring on the flat Recently Added list
(no pages, no More), per-mode accents and the v5 ring window (VOC-R03). Services are fakes:
no network, no Win32, no threads.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import device, presentation
from control_center.controller import Controller, Screen
from control_center.device import _frame
from control_center.presentation import window_first_v5
from control_center.runtime import Runtime
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows
from test_cc_controller import Clock, FakeDevice, ManualExecutor

P4 = {"controlCenter": 1, "presentation": 4, "glyphs": "latin-ext-a"}
P5 = {"controlCenter": 1, "presentation": 5, "glyphs": "latin-ext-a"}
EXE = "C:\\Program Files\\Secret Vendor\\private-app.exe"


def accent_url(i):
    return f"https://is1-ssl.mzstatic.com/image/thumb/a{i}/96x96bb.jpg"


class AccentApple(SimulatedAppleMusic):
    """Apple Music items as the real adapter shapes them: accent_url, no accent."""
    COUNT = 25

    def _library(self):
        return [{"id": f"al-{i}", "title": f"Album {i}", "artist": "Artist", "kind": "album",
                 "available": i != 3, "artwork_url": f"https://is1-ssl.mzstatic.com/image/thumb/a{i}/600x600bb.jpg",
                 "accent_url": accent_url(i)} for i in range(self.COUNT)]


class LongAccentApple(AccentApple):
    COUNT = 40


class IconWindows(SimulatedWindows):
    """Real-adapter-shaped windows: a private exe path and no accent."""
    COUNT = 4

    def snapshot(self):
        return {"items": [{"id": f"w{i}", "hwnd": 100 + i, "pid": 200 + i, "title": f"Window {i}",
                           "app": f"App {i}", "path": EXE, "available": True} for i in range(self.COUNT)],
                "index": 1, "origin": {"hwnd": 100, "pid": 200}}


class FakeAccents:
    def __init__(self):
        self.requests, self.results, self.closed = [], [], False

    def request_many(self, urls, token=None, *, speaker_host=None):
        self.requests.append((list(urls), token))
        return len(self.requests)

    def poll(self):
        results, self.results = self.results, []
        return results

    def clear(self):
        pass

    def close(self):
        self.closed = True


class FakeIcons:
    def __init__(self):
        self.requests, self.results, self.closed = [], [], False

    def request(self, items):
        self.requests.append(deepcopy(list(items)))
        return len(self.requests)

    def poll(self):
        results, self.results = self.results, []
        return results

    def close(self, timeout=None):
        self.closed = True


class Harness(unittest.TestCase):
    apple_class, windows_class = AccentApple, IconWindows

    def setUp(self):
        executor = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        executor.start()
        self.addCleanup(executor.stop)
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.sonos = SimulatedSonos()
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.c.drain()
        self.c.last_poll = self.clock()  # the fake clock never advances by itself: no polls
        self.accents, self.icons, self.device = FakeAccents(), FakeIcons(), FakeDevice()
        self.runtime = Runtime(self.c, self.sonos, self.apple_class(), self.windows_class(), self.device,
                               accents=self.accents, icons=self.icons)
        self.addCleanup(self.runtime.close)

    def load_recent(self):
        self.c.button(1)                  # Home 2: Browse (a new visit)
        self.runtime.dispatch()
        self.runtime.library.run_all()    # the page (an explorer visit may have queued favourites work)
        self.runtime.poll()
        self.assertEqual((self.c.screen.mode, self.c.recent.state), ("recent", "ready"))

    def home(self):
        while self.c.screen.mode != "home":
            self.c.button(0)              # Back
            self.runtime.dispatch()

    def token(self, controller=None):
        c = controller or self.c
        return ("recent", c.recent.visit, c.recent.rev)

    def colors(self):
        return self.runtime.frame()["ring"].get("colors")


class AccentWiringTests(Harness):
    def test_a_list_entry_asks_for_its_accent_urls_once(self):
        self.load_recent()
        self.assertEqual(self.accents.requests, [([accent_url(i) for i in range(25)], self.token())])
        for _ in range(3):
            self.runtime.poll()
        self.assertEqual(len(self.accents.requests), 1, "no request while the list stays")
        self.assertEqual(self.colors(), [0] * 20, "unknown accents are the 0 (warm) sentinel; 20-entry window")
        self.assertEqual(self.runtime.frame()["ring"]["first"], 0)

    def test_results_map_back_by_url(self):
        self.load_recent()
        token = self.token()
        self.accents.results = [(token, accent_url(0), 0x123456), (token, accent_url(1), None),
                                (token, accent_url(3), 0xABCDEF), (token, "https://unknown.example/x.jpg", 0x010101)]
        self.runtime.poll()
        self.assertEqual((self.runtime.accents[("recent", "al-0")], self.runtime.accents[("recent", "al-1")]),
                         (0x123456, None))
        colors = self.colors()
        self.assertEqual(colors[:5], [0x123456, 0, 0, 0xABCDEF, 0])
        self.assertFalse(self.c.recent.items[3]["available"])
        self.assertEqual(colors[3], 0xABCDEF, "an unavailable item keeps its accent; the renderer decides")
        self.assertEqual(self.runtime.frame()["ring"]["unavailable"], 1 << 3)

    def test_the_explorer_shares_the_list_and_a_new_visit_asks_again(self):
        self.load_recent()
        self.c.button(1)                  # Open: the explorer on the same list (no new request)
        self.runtime.dispatch()
        self.runtime.poll()
        self.assertEqual(self.c.screen.mode, "explorer")
        self.assertEqual(len(self.accents.requests), 1)
        self.home()
        self.runtime.poll()
        self.load_recent()                # a new visit: asked again (cached URLs cost nothing)
        self.assertEqual(len(self.accents.requests), 2)
        self.assertEqual(self.accents.requests[-1], ([accent_url(i) for i in range(25)], self.token()))

    def test_replacing_the_controller_asks_again(self):
        self.load_recent()
        other = Controller(clock=self.clock)
        other.complete(other.request("state"), self.sonos.read_state())
        other.screen = deepcopy(self.c.screen)
        other.recent = deepcopy(self.c.recent)
        self.runtime.attach(other)
        self.runtime.poll()
        self.assertEqual(len(self.accents.requests), 2)
        self.assertEqual(self.accents.requests[-1][1], self.token(other))

    def test_a_failing_service_never_stops_poll(self):
        def broken(*args, **kwargs):
            raise OSError("service down")
        self.accents.request_many = broken
        with self.assertLogs("control_center.runtime", "WARNING") as logs:
            self.load_recent()
            self.runtime.poll()
            self.home()
            self.runtime.poll()
            self.load_recent()
            self.runtime.poll()
        self.assertEqual(len(logs.output), 1, "logged once, by exception type only")
        self.assertNotIn("mzstatic", logs.output[0])
        self.assertEqual(self.c.screen.mode, "recent")
        self.assertEqual(self.colors(), [0] * 20)

    def test_close_stops_the_services(self):
        self.runtime.close()
        self.assertTrue(self.accents.closed and self.icons.closed)


class LongListAccentTests(Harness):
    apple_class = LongAccentApple

    def test_a_grown_list_asks_for_its_new_urls_and_late_results_still_fill_the_cache(self):
        self.load_recent()
        first = self.token()
        self.assertEqual((self.c.recent.total, len(self.c.recent.items)), (40, 25))
        self.c.position(12)               # within RECENT_AHEAD of the loaded end: the lookahead page
        self.runtime.dispatch()
        self.runtime.lookahead.run_all()
        self.runtime.poll()
        self.assertEqual(len(self.c.recent.items), 40)
        self.assertNotEqual(self.token(), first)
        self.assertEqual(self.accents.requests[-1], ([accent_url(i) for i in range(40)], self.token()))
        self.accents.results = [(first, accent_url(2), 0x00FF00)]
        self.runtime.poll()
        self.assertEqual(self.runtime.accents[("recent", "al-2")], 0x00FF00, "a late result still fills the cache")
        ring = self.runtime.frame()["ring"]
        self.assertEqual((ring["count"], ring["first"]), (40, window_first_v5(12, 40)))
        self.assertEqual(ring["colors"][2 - ring["first"]], 0x00FF00)

    def test_colour_arrival_changes_only_the_frame(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.load_recent()
        self.c.device_ready(self.c.control_id)
        self.runtime.poll()
        control_id = self.c.control_id
        self.device.commands.clear()
        self.accents.results = [(self.token(), accent_url(0), 0x123456)]
        self.runtime.poll()
        kinds = [command[0] for command in self.device.commands]
        self.assertEqual(kinds, ["frame"])
        self.assertEqual(self.device.commands[0][1]["ring"]["colors"][0], 0x123456)
        self.assertEqual(self.c.control_id, control_id)
        self.assertFalse([e for e in self.c.effects if e["kind"] == "device_enter"])


class SimulatorAccentTests(Harness):
    apple_class, windows_class = SimulatedAppleMusic, SimulatedWindows

    def test_simulator_items_carry_their_accent_and_use_no_service(self):
        self.load_recent()
        self.assertEqual(self.accents.requests, [])
        expected = [self.runtime.accent_of("recent", item) for item in self.c.recent.items[:20]]
        self.assertEqual(self.colors(), expected)
        self.assertEqual(expected[:3], [item["accent"] for item in self.c.recent.items[:3]])

    def test_simulator_windows_need_no_icon_worker(self):
        self.c.button(3)                  # Home 4: Win (no hotkey here)
        self.runtime.dispatch()
        self.runtime.poll()
        self.assertEqual(self.c.screen.mode, "windows")
        self.assertEqual(self.icons.requests, [])
        snapshot = SimulatedWindows().snapshot()
        self.assertEqual(self.colors(), [item["accent"] or 0 for item in snapshot["items"]])


class IconWiringTests(Harness):
    def open_by_hotkey(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.runtime.hotkey()
        self.assertEqual(self.c.screen.mode, "windows")

    def test_icons_are_requested_on_the_poll_after_the_picker_opened(self):
        self.open_by_hotkey()
        self.assertEqual(self.icons.requests, [], "never inside the WM_HOTKEY foreground path")
        self.runtime.poll()
        self.assertEqual(len(self.icons.requests), 1)
        self.assertEqual([item["id"] for item in self.icons.requests[0]], ["w0", "w1", "w2", "w3"])
        self.runtime.poll()
        self.assertEqual(len(self.icons.requests), 1, "one request per snapshot")

    def test_results_fill_accents_and_icons(self):
        self.open_by_hotkey()
        self.runtime.poll()
        icon = object()
        self.icons.results = [("w0", icon, 0x112233), ("w1", None, None), ("w2", None, 0x445566)]
        self.runtime.poll()
        self.assertIs(self.runtime.window_icons["w0"], icon)
        self.assertIsNone(self.runtime.window_icons["w1"])
        self.assertEqual(self.runtime.accents[("window", "w0")], 0x112233)
        self.assertEqual(self.colors(), [0x112233, 0, 0x445566, 0])

    def test_a_new_snapshot_asks_again_and_prunes_old_icons(self):
        self.open_by_hotkey()
        self.runtime.poll()
        self.icons.results = [("w0", object(), 0x112233), ("gone", object(), 0x010203)]
        self.runtime.poll()
        self.c.button(0)
        self.runtime.dispatch()
        self.runtime.poll()
        self.open_by_hotkey()
        self.runtime.poll()
        self.assertEqual(len(self.icons.requests), 2)
        self.assertNotIn("gone", self.runtime.window_icons)
        self.assertIn("w0", self.runtime.window_icons)

    def test_the_exe_path_never_reaches_a_frame_or_the_device(self):
        self.open_by_hotkey()
        self.runtime.poll()
        self.c.device_ready(self.c.control_id)
        self.runtime.poll()
        sent = json.dumps([command for command in self.device.commands], default=str)
        self.assertNotIn("Secret Vendor", sent)
        self.assertNotIn("Secret Vendor", json.dumps(self.runtime.frame()))


class DecorationTests(Harness):
    apple_class, windows_class = SimulatedAppleMusic, SimulatedWindows

    def windows_screen(self, count, index, closed=(), accent=lambda i: 0x010000 * (i + 1)):
        items = [{"id": f"w{i}", "title": f"Window {i}", "app": "App", "available": i not in closed,
                  "accent": accent(i)} for i in range(count)]
        self.c.screen = Screen(mode="windows", index=index, status="", windows={"items": items, "origin": {}})
        return items

    def test_colour_style_only_on_selection_rings(self):
        self.load_recent()
        self.assertIsNotNone(self.colors())
        self.runtime.led_style = "white"
        self.assertNotIn("colors", self.runtime.frame()["ring"])
        self.assertEqual(self.runtime.frame()["ledStyle"], "white")
        self.runtime.led_style = "color"
        self.home()                       # Home: a level ring
        self.assertEqual(self.runtime.frame()["ring"]["style"], "level")
        self.assertNotIn("colors", self.runtime.frame()["ring"])
        self.c.button(2)                  # Home 3: Tracks, transport is always white
        self.assertEqual(self.runtime.frame()["ring"]["style"], "transport")
        self.assertNotIn("colors", self.runtime.frame()["ring"])

    def test_ring_metadata_is_the_same_in_both_led_styles(self):
        self.windows_screen(21, 12, closed=(15,))
        colour = self.runtime.frame()["ring"]
        self.runtime.led_style = "white"
        white = self.runtime.frame()["ring"]
        self.assertEqual({k: v for k, v in colour.items() if k != "colors"}, white)
        self.assertEqual((white["first"], white["unavailable"]), (1, 1 << 14))
        self.assertNotIn("moreIndex", white, "v7 lists have no More (K3 section 5.2)")

    def test_twenty_entry_window_for_long_lists(self):
        # VOC-R03: first = clamp(index - 10, 0, count - 20), always sent when count > 20.
        for count, index, first in ((1, 0, 0), (11, 10, 0), (20, 19, 0), (21, 20, 1), (45, 30, 20), (45, 0, 0),
                                    (45, 44, 25)):
            with self.subTest(count=count, index=index):
                self.windows_screen(count, index)
                ring = self.runtime.frame()["ring"]
                self.assertEqual(ring["first"], first)
                width = min(20, count - first)
                self.assertEqual(ring["colors"], [0x010000 * (j + 1) for j in range(first, first + width)])
                for caps in (P4, P5):
                    sent = _frame({"id": 1, **self.runtime.frame()}, caps)
                    self.assertEqual(len(sent["ring"]["colors"]), width)

    def test_zero_sentinel_for_unknown_none_and_invalid(self):
        self.windows_screen(4, 0, accent=lambda i: (None, -1, 0x1000000, 0x00FF00)[i])
        self.assertEqual(self.colors(), [0, 0, 0, 0x00FF00])
        self.c.screen.windows.items[3].pop("accent")  # real adapter item, no icon result yet
        self.assertEqual(self.colors(), [0, 0, 0, 0])
        self.runtime.accents[("window", "w3")] = 0x0000FF
        self.assertEqual(self.colors(), [0, 0, 0, 0x0000FF])

    def test_closed_windows_keep_their_colour(self):
        self.windows_screen(5, 1, closed=(2, 3))
        ring = self.runtime.frame()["ring"]
        self.assertEqual(ring["unavailable"], 0b01100)
        self.assertEqual(ring["colors"], [0x010000 * (i + 1) for i in range(5)])

    def test_placeholder_loading_ring_has_no_colours(self):
        self.c.button(1)  # the list's first page requested, not loaded
        self.assertTrue(self.c.screen.loading)
        ring = self.runtime.frame()["ring"]
        self.assertEqual((ring["style"], ring["count"]), ("off", 0))
        self.assertNotIn("colors", ring)


def art(token, key="cover_key_0123456789abcd"):
    return SimpleNamespace(token=token, key=key, error="", rgb565=b"")


class ArtRuleTests(Harness):
    apple_class, windows_class = SimulatedAppleMusic, SimulatedWindows

    def key(self):
        frame = self.runtime.frame()
        return frame["artKey"], frame.get("artDim", False), frame["layout"]

    def playing_art(self):
        self.runtime.artwork_result = art(self.runtime._art_identity())

    def test_home_layouts_and_tracks_show_the_playing_cover(self):
        self.playing_art()
        self.assertEqual(self.key(), ("cover_key_0123456789abcd", False, "nowPlaying"))
        self.c.turn(1)
        self.assertEqual(self.key()[::2], ("cover_key_0123456789abcd", "volume"))
        self.c.tick()
        volume = next(e for e in self.c.drain() if e["kind"] == "volume")
        self.c.complete(volume["request"], {**self.sonos.read_state(), "volume": 29})
        self.c.complete(self.c.request("state"), {**self.sonos.read_state(), "volume": 29,
                                                  "playback": "PAUSED_PLAYBACK", "can_play": True, "can_pause": False})
        self.clock.advance(5)
        self.assertEqual(self.key()[::2], ("cover_key_0123456789abcd", "idle"),
                         "idle keeps the key so the firmware can fade it out")
        self.c.button(2)                  # Home 3: Tracks
        self.assertEqual(self.key(), ("cover_key_0123456789abcd", False, "tracks"))
        self.c.state["can_previous"] = False
        self.c.position(0)
        self.assertEqual(self.key(), ("cover_key_0123456789abcd", False, "tracks"),
                         "Tracks \u201cPrevious unavailable\u201d is not dimmed")

    def test_never_on_windows_notice_or_a_disconnected_knob(self):
        self.playing_art()
        self.c.button(3)                  # Home 4: Win
        self.runtime.dispatch()
        self.assertEqual(self.key()[::2], ("", "windows"))
        self.runtime.artwork_result = art(self.runtime._art_identity())
        self.assertEqual(self.key()[0], "")
        self.c.dismiss_windows()
        self.playing_art()
        self.c.complete(self.c.request("state"), {**self.sonos.read_state(), "online": False})
        self.assertEqual(self.key()[::2], ("", "notice"))
        self.c.complete(self.c.request("state"), self.sonos.read_state())
        self.assertEqual(self.key()[0], "cover_key_0123456789abcd")
        self.c.disconnected()
        self.assertEqual(self.key()[0], "")

    def test_looking_for_sonos_has_no_art(self):
        fresh = Controller(clock=self.clock)
        self.runtime.attach(fresh)
        self.runtime.artwork_result = art(self.runtime._art_identity())
        self.assertEqual(self.key()[::2], ("", "notice"))

    def test_recent_items_including_unavailable_but_never_an_unloaded_one(self):
        self.load_recent()
        first = self.c.recent.items[0]
        self.runtime.artwork_result = art(("recent", first["id"], ""))
        self.assertEqual(self.runtime._art_identity(), ("recent", first["id"], ""))
        self.assertEqual(self.key(), ("cover_key_0123456789abcd", False, "recent"))
        self.c.position(9)  # an unavailable library upload
        self.assertIs(self.c.recent.items[9]["available"], False)
        self.runtime.artwork_result = art(("recent", self.c.recent.items[9]["id"], ""))
        self.assertEqual(self.key(), ("cover_key_0123456789abcd", True, "recent"))
        self.assertEqual((self.c.recent.total, len(self.c.recent.items)), (26, 25))
        self.c.position(25)  # counted but not loaded yet: nothing shown
        self.assertEqual(self.runtime._art_identity(), ("recent", None, ""))
        self.runtime.artwork_result = art(self.runtime._art_identity())
        self.assertEqual(self.key(), ("", False, "recent"))
        self.home()
        self.c.button(1)  # a new visit loads
        self.assertTrue(self.c.screen.loading)
        self.runtime.artwork_result = art(("recent", first["id"], ""))
        self.assertEqual(self.key(), ("", False, "recent"))

    def test_partial_and_sonos_down_items_keep_their_cover(self):
        self.load_recent()
        self.runtime.artwork_result = art(self.runtime._art_identity())
        self.c.screen.status = "Playback partially failed"
        self.assertEqual(self.key()[0], "cover_key_0123456789abcd")
        self.c.complete(self.c.request("state"), {**self.sonos.read_state(), "online": False})
        self.assertEqual(self.key()[0], "cover_key_0123456789abcd")

    def test_empty_and_sign_in_have_no_art(self):
        from control_center.apple_music import AppleMusicError
        empty = {"items": [], "offset": 0, "limit": 25, "total": 0, "complete": True, "visit": 1}
        for result, error in ((empty, None),
                              (None, AppleMusicError("Apple Music authorization expired · reconnect in Setup",
                                                     status=401))):
            with self.subTest(error=error is not None):
                self.c.button(1)
                effect = next(e for e in self.c.drain() if e["kind"] == "recent")
                self.c.complete(effect["request"], result, error=error)
                self.assertEqual(self.c.recent.state, "signin" if error else "empty")
                self.runtime.artwork_result = art(self.runtime._art_identity())
                self.assertEqual(self.key(), ("", False, "recent"))
                self.home()

    def test_a_stale_cover_is_never_shown_for_the_next_item(self):
        # v7 retired the v6 pending freeze: the identity follows the highlight at once.
        self.load_recent()
        self.c.position(2)
        self.runtime.artwork_result = art(self.runtime._art_identity())
        self.assertEqual(self.key()[0], "cover_key_0123456789abcd")
        self.c.position(5)
        self.assertEqual(self.runtime._art_identity()[:2], ("recent", self.c.recent.items[5]["id"]))
        self.assertEqual(self.key()[0], "", "a stale cover is never shown for the new item")


class BudgetTests(Harness):
    """PRESENTATION_V5 section 14.1: the worst frames stay within 1,400 bytes on a presentation-5
    knob, and within V4's 1,100 bytes after the section 2.2 downgrade for an older one."""
    apple_class, windows_class = SimulatedAppleMusic, SimulatedWindows

    def line(self, caps=P4):
        sent = _frame({"id": 0x7FFFFFFF, **self.runtime.frame()}, caps)
        size = device.frame_line_bytes(sent)
        limit = presentation.FRAME_BUDGET_BYTES_V5 if caps is P5 else presentation.FRAME_BUDGET_BYTES
        self.assertLessEqual(size, limit, f"{size} B")
        return sent, size

    def failed_switch(self, items):
        self.c.screen = Screen(mode="windows", index=30, status="", windows={"items": items, "origin": {}})
        self.c.feedback_seq = 0x7FFFFFFF - 1
        request = self.c.request("windows_activate", item=items[30], index=30)
        self.c.screen.windows.switch_request = request
        self.c.complete(request, False)

    def test_windows_worst_case_with_96_byte_titles_and_app_names(self):
        title = ("Quarterly planning — draft review " * 4).encode()[:96].decode("utf-8", "ignore")
        for app in ("A" * 96, "É" * 48, "Ł" * 200, "Microsoft Visual Studio Code Insiders"):
            for closed_selected in (False, True):
                with self.subTest(app_bytes=len(app.encode()), closed=closed_selected):
                    items = [{"id": f"{i:08x}:{i + 1000}:0:0", "title": title, "app": app,
                              "available": i % 2 == 0 and not (closed_selected and i == 31),
                              "accent": 0xFFFFFF} for i in range(40)]
                    self.failed_switch(items)
                    if closed_selected:
                        self.c.position(31)
                        self.clock.advance(2.5)   # the failure transient (2400 ms) has ended
                    for caps in (P4, P5):
                        sent, size = self.line(caps)
                        self.assertEqual(len(sent["ring"]["colors"]), 20)
                        self.assertEqual(sent["subtitle"], presentation.utf8_truncate(app, 96),
                                         "the drawn app name is kept")
                        self.assertEqual(len(sent["title"].encode()), len(title.encode()))
                        meta = "Closed · can’t switch" if closed_selected else "Didn’t come forward · retry"
                        self.assertEqual(sent["meta"], meta)
                        self.assertIn(sent.get("detail", ""), ("", presentation.utf8_truncate(app, 96)))
                        self.assertEqual(sent["target"], "DESKTOP")

    def test_windows_worst_case_with_escaped_titles_and_app_names(self):
        # `"` and `\` are two bytes on the wire: the legacy title/app copies (value,
        # detail) go first; only escapes in both drawn texts shorten them (device._budget).
        bs = "\\"
        for title, app in (('"' * 96, "A" * 96), (bs * 96, "É" * 48), (bs * 96, bs * 96),
                           (('"' + bs) * 48, ('"' + bs) * 48)):
            with self.subTest(title=title[:2], app=app[:2]):
                items = [{"id": f"{i:08x}:{i + 1000}:0:0", "title": title, "app": app,
                          "available": i % 2 == 0, "accent": 0xFFFFFF} for i in range(40)]
                self.failed_switch(items)
                sent, size = self.line(P4)
                self.assertGreater(size, 1000)
                self.assertEqual((sent["value"], sent["detail"]), ("", ""))
                self.assertEqual((sent["meta"], len(sent["ring"]["colors"])), ("Didn’t come forward · retry", 20))
                self.assertTrue(title.startswith(sent["title"]) and sent["title"])
                if '"' not in app and bs not in app:
                    self.assertEqual((sent["title"], sent["subtitle"]), (title, app), "one escaped text is kept whole")
                sent, _ = self.line(P5)
                self.assertTrue(title.startswith(sent["title"]) and sent["title"])

    def test_recent_worst_case_with_art_and_colours(self):
        self.load_recent()
        title = "Ó" * 48
        for item in self.c.recent.items:
            item.update(title=title, artist="Ü" * 48, accent=0xFFFFFF, available=False)
        self.c.state["group_label"] = "R" * 64
        self.c.position(9)
        self.c.feedback_seq = 0x7FFFFFFF - 1
        self.c._feedback("err")
        self.runtime.artwork_result = art(self.runtime._art_identity(), key="f" * 24)
        for caps in (P4, P5):
            sent, _ = self.line(caps)
            self.assertEqual((sent["artKey"], sent["artDim"], sent["titleTone"]), ("f" * 24, True, "muted"))
            self.assertEqual(len(sent["ring"]["colors"]), 20)


if __name__ == "__main__":
    unittest.main()

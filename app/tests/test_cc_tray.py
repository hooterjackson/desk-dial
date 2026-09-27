"""Tray, status and smoke-test logic of the desktop v5 standalone app (FLOATING_KNOB.md
sections 6 and 7), as pure functions: no Tk, no tray icon, no window, no port.

The pystray menu is built from the real pystray.Menu/MenuItem (pure Python) over a
stand-in Icon class; the overlay window's smoke cycle runs against a stand-in
Win32Backend and KnobOverlay. Only smoke_overlay and SmokeOverlay use the real
renderers (Pillow). The app and tray icons (APP_ICON.md) are checked with a stand-in
loader and a stand-in winreg; the one test over pystray's real win32 Icon class never
constructs it the pystray way (no window class, no window, no Shell_NotifyIcon).
"""
import ast
import ctypes
import inspect
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import standalone
from standalone import (
    NoTray, NoticeBalloons, TrayPresenter, TrayState, build_tray_menu, connect_label, make_tray_icon,
    route_request, run_tray, start_tray, stop_tray, tray_fallback, tray_menu_model, tray_tooltip, utf16_cut,
)
from control_center.controller import Controller


class TextTests(unittest.TestCase):
    def test_utf16_cut_counts_utf16_units(self):
        self.assertEqual(utf16_cut("abc", 3), "abc")
        self.assertEqual(utf16_cut("abcdef", 4), "abc…")
        emoji = "\U0001F3B5" * 70                   # two UTF-16 units each
        cut = utf16_cut(emoji, 127)
        self.assertLessEqual(len(cut.encode("utf-16-le")) // 2, 127)
        self.assertTrue(cut.endswith("…"))

    def test_tooltip_is_the_knob_state(self):
        # APP_ICON.md section 5 supersedes FLOATING_KNOB.md section 6's device-status tooltip.
        self.assertEqual(tray_tooltip(True), "Desk Dial · Knob connected")
        self.assertEqual(tray_tooltip(False), "Desk Dial · Knob not found")
        for present in (True, False):
            self.assertLessEqual(len(tray_tooltip(present).encode("utf-16-le")) // 2, standalone.TRAY_TIP_LIMIT)
        self.assertEqual((standalone.tray_header(True), standalone.tray_header(False)),
                         ("Knob connected", "Knob not found"))

    def test_connect_label_follows_connected_or_connecting(self):
        self.assertEqual(connect_label(True), "Disconnect knob")
        self.assertEqual(connect_label(False), "Connect knob")


class MenuModelTests(unittest.TestCase):
    def test_the_menu_order_requests_and_default(self):
        model = tray_menu_model("Knob ready · installed profiles active", True, True)
        self.assertEqual([entry[0] for entry in model],
                         ["Knob connected", "Knob ready · installed profiles active", "Show knob", "Open Settings…",
                          "Disconnect knob", "Quit"])
        self.assertEqual([entry[1] for entry in model], [None, None, "peek", "settings", "connect", "quit"])
        self.assertEqual([entry[2] for entry in model], [False, False, True, True, True, True])
        self.assertEqual([entry[3] for entry in model], [False, False, True, False, False, False])
        self.assertEqual(tray_menu_model("", False)[0][0], "Knob not found")
        self.assertEqual(tray_menu_model("", False)[1][0], "Knob disconnected")
        self.assertEqual(tray_menu_model("", False)[4][0], "Connect knob")
        long = tray_menu_model("x" * 300, False)[1][0]
        self.assertLessEqual(len(long), standalone.MENU_STATUS_LIMIT)

    def test_the_pystray_menu_reads_the_state_when_built_and_only_queues(self):
        import pystray
        state, queued = TrayState("Knob disconnected", False), []
        fake = SimpleNamespace(Menu=pystray.Menu, MenuItem=pystray.MenuItem)
        menu = build_tray_menu(fake, state, queued.append)
        items = list(menu.items)
        self.assertEqual([item.text for item in items],
                         ["Knob not found", "Knob disconnected", "Show knob", "Open Settings…", "Connect knob", "Quit"])
        self.assertFalse(items[0].enabled)
        self.assertFalse(items[1].enabled)
        self.assertTrue(items[2].default)
        self.assertEqual([item.default for item in items].count(True), 1)
        # A state change shows the next time pystray builds the menu.
        state.status, state.connected, state.present = "Knob ready · installed profiles active", True, True
        self.assertEqual(items[0].text, "Knob connected")
        self.assertEqual(items[1].text, "Knob ready · installed profiles active")
        self.assertEqual(items[4].text, "Disconnect knob")
        icon = object()
        menu(icon)                                  # a left click: the default item
        for item in items:
            item(icon)                              # each item from the right-click menu
        self.assertEqual(queued, ["peek", "peek", "settings", "connect", "quit"])

    def test_the_icon_rebuilds_its_menu_on_the_tray_thread_before_it_opens(self):
        calls = []

        class Base:
            def __init__(self, name, image, title, menu=None):
                self.name, self.image, self.title, self.menu = name, image, title, menu

            def update_menu(self):
                calls.append("update")

            def _on_notify(self, wparam, lparam):
                calls.append(("notify", lparam))

        import pystray
        fake = SimpleNamespace(Icon=Base, Menu=pystray.Menu, MenuItem=pystray.MenuItem)
        state = TrayState("Knob ready", True, True)
        icon = make_tray_icon(fake, "image", state, lambda request: None)
        self.assertIsInstance(icon, Base)
        self.assertEqual((icon.name, icon.title), ("NanoDControlCenter", "Desk Dial · Knob connected"))
        icon._on_notify(0, standalone.WM_RBUTTONUP)
        icon._on_notify(0, 0x0202)                  # WM_LBUTTONUP: no rebuild before the default action
        self.assertEqual(calls, ["update", ("notify", standalone.WM_RBUTTONUP), ("notify", 0x0202)])

    def test_an_icon_class_without_the_hook_is_used_as_is(self):
        import pystray

        class Plain:
            def __init__(self, *args, **kwargs):
                self.args = args

        icon = make_tray_icon(SimpleNamespace(Icon=Plain, Menu=pystray.Menu, MenuItem=pystray.MenuItem),
                              None, TrayState(), lambda request: None)
        self.assertIs(type(icon), Plain)


class RequestRoutingTests(unittest.TestCase):
    def test_requests_run_their_handler_and_only_quit_stops(self):
        handlers = {name: Mock() for name in ("peek", "settings", "connect", "quit", "fallback")}
        for name in ("peek", "settings", "connect", "fallback"):
            self.assertFalse(route_request(name, handlers))
            handlers[name].assert_called_once_with()
        self.assertTrue(route_request("quit", handlers))
        handlers["quit"].assert_called_once_with()
        self.assertFalse(route_request("unknown", handlers))


class NoticeBalloonTests(unittest.TestCase):
    def test_rate_limited_newest_waits(self):
        now = [100.0]
        balloons = NoticeBalloons(interval=10, clock=lambda: now[0])
        self.assertIsNone(balloons.due())
        balloons.offer("Sonos did not answer")
        self.assertEqual(balloons.due(), "Sonos did not answer")
        balloons.offer("first")
        balloons.offer("  second\nerror ")
        self.assertIsNone(balloons.due(), "within the interval")
        now[0] = 109.9
        self.assertIsNone(balloons.due())
        now[0] = 110.0
        self.assertEqual(balloons.due(), "second error", "the newest notice")
        self.assertIsNone(balloons.due())
        balloons.offer("")
        now[0] = 200
        self.assertIsNone(balloons.due())

    def test_long_notices_fit_the_balloon(self):
        balloons = NoticeBalloons(interval=0, clock=lambda: 0.0)
        balloons.offer("x" * 1000)
        self.assertLessEqual(len(balloons.due()), standalone.BALLOON_TEXT_LIMIT)
        balloons.offer_message("y" * 1000)
        self.assertLessEqual(len(balloons.due()), standalone.BALLOON_TEXT_LIMIT)

    def test_app_messages_queue_ahead_of_notices_and_are_never_replaced(self):
        now = [100.0]
        balloons = NoticeBalloons(interval=10, clock=lambda: now[0])
        balloons.offer_message("Authorization incomplete")
        balloons.offer("Last action failed")                  # the same tick
        self.assertEqual(balloons.due(), "Authorization incomplete")
        balloons.offer_message("Apple Music connected · Home, then Browse")
        balloons.offer("Sonos unreachable")                   # replaces the waiting notice only
        balloons.offer_message("  ")                           # blank: nothing
        now[0] = 110.0
        self.assertEqual(balloons.due(), "Apple Music connected · Home, then Browse")
        now[0] = 115.0
        self.assertIsNone(balloons.due())
        now[0] = 120.0
        self.assertEqual(balloons.due(), "Sonos unreachable")
        now[0] = 200.0
        self.assertIsNone(balloons.due())
        for index in range(NoticeBalloons.MESSAGE_LIMIT + 2):    # no tray for a long time: bounded
            balloons.offer_message(f"message {index}")
        self.assertEqual(len(balloons.messages), NoticeBalloons.MESSAGE_LIMIT)
        self.assertEqual(balloons.due(), "message 2", "the oldest beyond the limit are dropped")


class FakeIcon:
    def __init__(self, visible=True):
        self.title = "Desk Dial · Knob not found"
        self.visible = visible
        self.titles, self.notes, self.files = [], [], []
        self._wanted_icon_file = str(standalone.tray_icon_file("dark", False))

    def set_icon_file(self, path):
        self.files.append(path)
        self._wanted_icon_file = path
        return True

    def __setattr__(self, name, value):
        if name == "title" and "titles" in self.__dict__:
            self.titles.append(value)
        super().__setattr__(name, value)

    def notify(self, message, title=None):
        self.notes.append((message, title))


class TrayPresenterTests(unittest.TestCase):
    def presenter(self, visible=True):
        now = [0.0]
        self.now = now
        self.icon = FakeIcon(visible)
        self.state = TrayState()
        return TrayPresenter(self.icon, self.state, NoticeBalloons(interval=10, clock=lambda: now[0]),
                             log=Mock())

    def test_tooltip_icon_and_header_switch_together_only_on_a_change(self):
        presenter = self.presenter()
        presenter.update("Knob disconnected", False, present=False)
        self.assertEqual((self.icon.titles, self.icon.files), ([], []), "unchanged")
        presenter.update("Connected · verifying control interface", True, present=True)
        presenter.update("Knob ready · installed profiles active", True, present=True)
        self.assertEqual(self.icon.titles, ["Desk Dial · Knob connected"])
        self.assertEqual(self.icon.files, [str(standalone.tray_icon_file("dark", True))])
        self.assertEqual(self.state.model()[0][0], "Knob connected")
        self.assertEqual(self.state.model()[1][0], "Knob ready · installed profiles active")
        self.assertEqual((self.state.status, self.state.connected, self.state.present),
                         ("Knob ready · installed profiles active", True, True))
        presenter.update("Knob disconnected", False, present=False)
        self.assertEqual(self.icon.titles[-1], "Desk Dial · Knob not found")
        self.assertEqual(self.icon.files[-1], str(standalone.tray_icon_file("dark", False)))
        self.assertEqual(self.state.model()[0][0], "Knob not found")
        self.assertEqual((len(self.icon.titles), len(self.icon.files)), (2, 2))
        presenter.update("Knob disconnected", True)       # present omitted: kept
        self.assertEqual((len(self.icon.titles), len(self.icon.files)), (2, 2))

    def test_the_taskbar_theme_swaps_the_icon_live(self):
        presenter = self.presenter()
        presenter.update("Knob ready", True, present=True)
        self.assertTrue(presenter.set_theme("light"))
        self.assertEqual(self.icon.files[-1], str(standalone.tray_icon_file("light", True)))
        self.assertFalse(presenter.set_theme("light"))
        self.assertEqual(len(self.icon.files), 2)
        self.assertEqual(self.icon.titles, ["Desk Dial · Knob connected"], "the theme never changes the tooltip")
        presenter.set_theme("unknown")                       # anything else is the dark set
        self.assertEqual(self.icon.files[-1], str(standalone.tray_icon_file("dark", True)))

    def test_app_messages_become_balloons(self):
        presenter = self.presenter()
        presenter.update("Knob ready", True, "", messages=["Apple Music connected · Home, then Browse"])
        self.assertEqual(self.icon.notes, [("Apple Music connected · Home, then Browse", standalone.BALLOON_TITLE)])
        hidden = self.presenter(visible=False)
        hidden.update("Knob ready", True, "", messages=["Authorization incomplete"])
        self.assertEqual(self.icon.notes, [])
        self.icon.visible = True
        hidden.update("Knob ready", True, "")
        self.assertEqual(self.icon.notes, [("Authorization incomplete", standalone.BALLOON_TITLE)])

    def test_a_notice_never_drops_an_authorization_balloon(self):
        # Same tick: the outcome and a fresh notice. Both are shown, the outcome first.
        presenter = self.presenter()
        presenter.update("Knob ready", True, "Last action failed", messages=["Authorization incomplete"])
        self.now[0] = 10.0
        presenter.update("Knob ready", True, "Last action failed")
        self.assertEqual([note for note, _ in self.icon.notes], ["Authorization incomplete", "Last action failed"])
        # Rate limited: a notice balloon 3 s earlier, then the outcome waits and a newer notice
        # arrives; the outcome still comes first, then the newest notice.
        presenter = self.presenter()
        presenter.update("Knob ready", True, "Sonos unreachable")
        self.now[0] = 3.0
        presenter.update("Knob ready", True, "Sonos unreachable",
                         messages=["Apple Music connected · Home, then Browse"])
        self.now[0] = 5.0
        presenter.update("Knob ready", True, "Last action failed")
        for moment in (10.0, 20.0):
            self.now[0] = moment
            presenter.update("Knob ready", True, "Last action failed")
        self.assertEqual([note for note, _ in self.icon.notes],
                         ["Sonos unreachable", "Apple Music connected · Home, then Browse", "Last action failed"])

    def test_each_notice_becomes_one_rate_limited_balloon(self):
        presenter = self.presenter()
        self.assertTrue(presenter.update("Knob ready", True, "Volume change failed (timeout)"))
        self.assertEqual(self.icon.notes, [("Volume change failed (timeout)", standalone.BALLOON_TITLE)])
        # The notice stays on the controller (the knob keeps "Last action failed"): the
        # presenter sees it on every tray tick and never offers it again.
        self.now[0] = 60.0
        for _ in range(5):
            self.assertFalse(presenter.update("Knob ready", True, "Volume change failed (timeout)"))
        self.assertEqual(len(self.icon.notes), 1)
        self.now[0] = 65.0
        self.assertTrue(presenter.update("Knob ready", True, "Skip failed"))
        self.assertEqual(self.icon.notes[-1][0], "Skip failed")
        self.assertTrue(presenter.update("Knob ready", True, "Play failed"))
        self.assertEqual(len(self.icon.notes), 2, "rate limited; the newest notice waits")
        self.assertFalse(presenter.update("Knob ready", True, "Play failed"))
        self.now[0] = 75.0
        presenter.update("Knob ready", True, "Play failed")
        self.assertEqual(self.icon.notes[-1][0], "Play failed")
        self.assertEqual(len(self.icon.notes), 3)

    def test_a_cleared_notice_makes_the_same_text_new_again(self):
        presenter = self.presenter()
        presenter.update("Knob ready", True, "Skip failed")
        self.assertFalse(presenter.update("Knob ready", True, ""))     # the next action cleared it
        self.now[0] = 20.0
        self.assertTrue(presenter.update("Knob ready", True, "Skip failed"))
        self.assertEqual([note for note, _ in self.icon.notes], ["Skip failed", "Skip failed"])

    def test_without_a_shown_icon_notices_wait_for_the_icon(self):
        presenter = self.presenter(visible=False)
        self.assertFalse(presenter.update("Knob ready", True, "Volume change failed"))
        self.assertEqual(self.icon.notes, [])
        self.icon.visible = True                 # the tray thread has shown the icon
        self.assertTrue(presenter.update("Knob ready", True, "Volume change failed"))
        self.assertEqual(self.icon.notes, [("Volume change failed", standalone.BALLOON_TITLE)])

    def test_the_tray_never_clears_the_controllers_notice(self):
        # v4 lifetime: the notice ends with the next action (or a dismiss in Settings);
        # the knob's "Last action failed" line depends on it.
        self.assertNotIn("clear_notice", inspect.getsource(standalone))

    def test_a_failing_icon_never_raises(self):
        presenter = self.presenter()
        self.icon.notify = Mock(side_effect=OSError("Shell_NotifyIcon"))
        self.assertTrue(presenter.update("Knob ready", True, "x"))


class TrayThreadTests(unittest.TestCase):
    """The tray thread and its fallback (FLOATING_KNOB.md section 6: the app is never
    invisible and unquittable)."""

    class Icon:
        def __init__(self, run=None):
            self._run = run
            self.stops = 0

        def run(self):
            if self._run is not None:
                self._run()

        def stop(self):
            self.stops += 1

    def test_a_failing_tray_queues_the_fallback(self):
        queued, log = [], Mock()
        icon = self.Icon(run=Mock(side_effect=OSError("Shell_NotifyIconW")))
        self.assertEqual(run_tray(icon, threading.Event(), queued.append, log), "fallback")
        self.assertEqual(queued, ["fallback"])
        log.exception.assert_called_once()

    def test_a_tray_that_stops_unasked_queues_the_fallback(self):
        queued, log = [], Mock()
        self.assertEqual(run_tray(self.Icon(), threading.Event(), queued.append, log), "fallback")
        self.assertEqual(queued, ["fallback"])
        log.warning.assert_called_once()

    def test_quit_and_shutdown_stop_the_tray_without_a_fallback(self):
        queued, stopping = [], threading.Event()
        icon = self.Icon(run=lambda: stop_tray(icon, stopping))    # Quit while the loop runs
        self.assertIsNone(run_tray(icon, stopping, queued.append, Mock()))
        self.assertEqual(queued, [])
        self.assertEqual(icon.stops, 1)
        self.assertTrue(stopping.is_set())

    def test_stop_tray_never_raises(self):
        stopping = threading.Event()
        icon = Mock()
        icon.stop.side_effect = OSError("PostMessageW")
        with self.assertLogs("nanod.tray", "WARNING"):
            stop_tray(icon, stopping)
        self.assertTrue(stopping.is_set())
        stop_tray(NoTray(), stopping)

    def test_start_tray_runs_the_icon_on_its_own_thread(self):
        started = []

        class Thread:
            def __init__(self, target, args, daemon, name):
                started.append((target, args, daemon, name))

            def start(self):
                started.append("start")
        icon, queued, stopping = self.Icon(), [], threading.Event()
        self.assertIs(start_tray(lambda: icon, stopping, queued.append, Mock(), Thread), icon)
        (target, args, daemon, name), step = started
        self.assertEqual((target, args[:3], daemon, name, step),
                         (run_tray, (icon, stopping, queued.append), True, "NanoD-tray", "start"))
        self.assertEqual(target(*args), "fallback", "the thread's body is run_tray")
        self.assertEqual(queued, ["fallback"])

    def test_start_tray_with_a_real_thread(self):
        queued, stopping = [], threading.Event()
        done = threading.Event()
        icon = self.Icon(run=lambda: (stopping.set(), done.set()))
        start_tray(lambda: icon, stopping, queued.append, Mock())
        self.assertTrue(done.wait(2))
        self.assertEqual(queued, [])

    def test_an_icon_that_cannot_be_created_falls_back_at_once(self):
        queued, log = [], Mock()
        thread = Mock()
        icon = start_tray(Mock(side_effect=OSError("RegisterClassExW")), threading.Event(), queued.append,
                          log, thread)
        self.assertIsInstance(icon, NoTray)
        self.assertEqual(queued, ["fallback"])
        thread.assert_not_called()
        log.exception.assert_called_once()
        # The presenter works on the stand-in: no tooltip or balloon, never an error.
        presenter = TrayPresenter(icon, TrayState(), log=Mock())
        self.assertFalse(presenter.update("Knob ready", True, "Skip failed"))

    def test_the_fallback_opens_settings_with_connect_and_quit(self):
        connected = [False]
        app = SimpleNamespace(setup_actions=None, setup=Mock())
        connect, quit_app = Mock(), Mock()
        handlers = {"fallback": lambda: tray_fallback(app, connect, quit_app, lambda: connected[0])}
        self.assertFalse(route_request("fallback", handlers))
        app.setup.assert_called_once_with()
        self.assertIs(app.setup_actions["connect"], connect)
        self.assertIs(app.setup_actions["quit"], quit_app)
        self.assertEqual(app.setup_actions["label"](), "Connect knob")
        connected[0] = True
        self.assertEqual(app.setup_actions["label"](), "Disconnect knob")


class FakeIconApi:
    """TrayIconApi stand-in: records loads, posts and destroys; loads nothing."""
    def __init__(self, size=20, handles=True):
        self.size, self.handles = size, handles
        self.loads, self.posts, self.destroyed = [], [], []
        self._next = 0x5000

    def small_icon_size(self):
        return self.size

    def load(self, path, size):
        self.loads.append((str(path), size))
        if not self.handles:
            return None
        self._next += 4
        return self._next

    def destroy(self, handle):
        self.destroyed.append(handle)
        return True

    def post(self, hwnd, message):
        self.posts.append((hwnd, message))
        return True

    def icon_count(self, path):
        return 1


class PystrayLikeIcon:
    """pystray 0.19.5 win32 Icon's handle lifecycle, without Win32 (see
    test_the_hooks_match_pystrays_win32_icon for the real class)."""
    def __init__(self, name, image, title, menu=None):
        self.name, self.icon, self.title, self.menu = name, image, title, menu
        self._icon_handle = None
        self._hwnd = None
        self.visible = False
        self._message_handlers = {}
        self.events = []

    def _assert_icon_handle(self):
        self.events.append("serialized_image")            # pystray re-serializes the PIL image here

    def _release_icon(self):
        if self._icon_handle:
            self.events.append(("DestroyIcon", self._icon_handle))
            self._icon_handle = None

    def _update_icon(self):
        self._release_icon()
        self._assert_icon_handle()
        self.events.append(("NIM_MODIFY", self._icon_handle))

    def _show(self):
        self._assert_icon_handle()
        self.events.append(("NIM_ADD", self._icon_handle, self.title))

    def _hide(self):
        self.events.append(("NIM_DELETE",))

    def _update_title(self):
        self.events.append(("NIM_MODIFY_TIP", self.title))


class TrayIconTests(unittest.TestCase):
    """APP_ICON.md item 4: the tray handle always comes from the .ico file."""

    def make(self, base=PystrayLikeIcon, path=None, api=None):
        import pystray
        self.api = api or FakeIconApi()
        fake = SimpleNamespace(Icon=base, Menu=pystray.Menu, MenuItem=pystray.MenuItem)
        path = path or standalone.tray_icon_file("dark", True, standalone_app_dir())
        return make_tray_icon(fake, "small PIL image", TrayState("Knob ready", True, True), lambda request: None,
                              icon_file=path, icon_api=self.api)

    def test_the_handle_comes_from_the_ico_at_the_small_icon_size(self):
        icon = self.make()
        self.assertEqual(type(icon).__name__, "TrayIcon")
        self.assertEqual(icon.icon, "small PIL image", "pystray still gets a PIL image")
        icon._assert_icon_handle()
        path = str(standalone.tray_icon_file("dark", True, standalone_app_dir()))
        self.assertEqual(self.api.loads, [(path, 20)])
        self.assertTrue(icon._icon_handle)
        self.assertNotIn("serialized_image", icon.events)
        icon._assert_icon_handle()                            # a handle exists: no-op
        self.assertEqual(len(self.api.loads), 1)

    def test_a_change_is_posted_and_swapped_on_the_tray_thread(self):
        icon = self.make()
        icon._assert_icon_handle()
        first = icon._icon_handle
        self.assertIs(icon._message_handlers[standalone.WM_TRAY_ICON_FILE].__func__, type(icon)._on_icon_file)
        light = str(standalone.tray_icon_file("light", False, standalone_app_dir()))
        self.assertFalse(icon.set_icon_file(str(standalone.tray_icon_file("dark", True, standalone_app_dir()))))
        icon._hwnd = 0x1234
        self.assertTrue(icon.set_icon_file(light))              # Tk thread: record + post only
        self.assertEqual(self.api.posts, [(0x1234, standalone.WM_TRAY_ICON_FILE)])
        self.assertEqual(len(self.api.loads), 1, "nothing is loaded on the Tk thread")
        self.assertEqual(icon._icon_handle, first)
        icon.visible = True
        self.assertEqual(icon._on_icon_file(0, 0), 0)            # the tray thread handles the post
        self.assertEqual(icon.events, [("DestroyIcon", first), ("NIM_MODIFY", icon._icon_handle)])
        self.assertEqual(self.api.loads[-1], (light, 20))
        icon._on_icon_file(0, 0)                                 # already current: nothing more
        self.assertEqual(len(icon.events), 2)

    def test_a_change_before_the_icon_is_added_swaps_the_loaded_handle(self):
        # pystray's setup thread loads the handle, then adds the icon, and only then sets
        # visible: a change handled in between must still reach the shell.
        icon = self.make()
        icon._assert_icon_handle()
        handle = icon._icon_handle
        light = str(standalone.tray_icon_file("light", True, standalone_app_dir()))
        icon.set_icon_file(light)
        icon._on_icon_file(0, 0)
        swapped = icon._icon_handle
        self.assertEqual(icon.events, [("DestroyIcon", handle), ("NIM_MODIFY", swapped)],
                         "NIM_MODIFY before NIM_ADD is a harmless no-op")
        self.assertEqual(self.api.loads[-1], (light, 20))
        icon._show()                                             # the setup thread's NIM_ADD
        self.assertEqual(icon.events[-1], ("NIM_ADD", swapped, "Desk Dial · Knob connected"))
        self.assertEqual(icon._icon_file, light)

    def test_a_change_with_no_handle_and_no_icon_waits_for_the_show(self):
        icon = self.make()
        light = str(standalone.tray_icon_file("light", True, standalone_app_dir()))
        icon.set_icon_file(light)
        icon._on_icon_file(0, 0)
        self.assertEqual((icon.events, self.api.loads), ([], []))
        icon._show()                                             # loads the wanted file
        self.assertEqual(self.api.loads, [(light, 20)])
        self.assertEqual(icon.events, [("NIM_ADD", icon._icon_handle, "Desk Dial · Knob connected")])

    def test_a_swap_waits_for_an_add_in_progress(self):
        # The startup race: the tray thread handles WM_TRAY_ICON_FILE while pystray's setup
        # thread is between loading the handle and NIM_ADD. The swap waits for the add, so
        # NIM_ADD never gets a destroyed handle and the shell ends with the wanted file.
        loading, release = threading.Event(), threading.Event()

        class SlowAdd(PystrayLikeIcon):
            def _show(self):
                self._assert_icon_handle()
                loading.set()
                release.wait(5)                                  # Shell_NotifyIcon on its way
                destroyed = ("DestroyIcon", self._icon_handle) in self.events
                self.events.append(("NIM_ADD", self._icon_handle, destroyed))

        icon = self.make(base=SlowAdd)
        light = str(standalone.tray_icon_file("light", True, standalone_app_dir()))
        setup = threading.Thread(target=icon._show)
        setup.start()
        self.assertTrue(loading.wait(5))
        first = icon._icon_handle
        icon.set_icon_file(light)
        tray = threading.Thread(target=icon._on_icon_file, args=(0, 0))
        tray.start()
        tray.join(0.2)
        self.assertTrue(tray.is_alive(), "the swap waits for NIM_ADD")
        release.set()
        setup.join(5)
        tray.join(5)
        self.assertEqual(icon.events, [("NIM_ADD", first, False), ("DestroyIcon", first),
                                       ("NIM_MODIFY", icon._icon_handle)])
        self.assertEqual(self.api.loads[-1], (light, 20))
        self.assertEqual(icon._icon_file, light)

    def test_a_tooltip_set_while_the_icon_is_added_is_not_lost(self):
        class LateTip(PystrayLikeIcon):
            def _show(self):
                super()._show()                                  # NIM_ADD read the old tooltip
                self.title = "Desk Dial · Knob not found"         # the Tk thread, before visible

        icon = self.make(base=LateTip)
        icon._show()
        self.assertEqual(icon.events[-2:], [("NIM_ADD", icon._icon_handle, "Desk Dial · Knob connected"),
                                            ("NIM_MODIFY_TIP", "Desk Dial · Knob not found")])
        icon.title = "Desk Dial · Knob connected"                 # added: sent at once
        self.assertEqual(icon.events[-1], ("NIM_MODIFY_TIP", "Desk Dial · Knob connected"))
        icon.title = "Desk Dial · Knob connected"                 # unchanged: nothing
        icon._hide()
        icon.title = "Desk Dial · Knob not found"                 # removed: nothing to modify
        self.assertEqual(icon.events[-1], ("NIM_DELETE",))
        self.assertEqual(icon.title, "Desk Dial · Knob not found")

    def test_a_failed_load_is_logged_and_never_falls_back_to_the_pil_image(self):
        icon = self.make(api=FakeIconApi(handles=False))
        with self.assertLogs("nanod.tray", "WARNING"):
            icon._assert_icon_handle()
        self.assertIsNone(icon._icon_handle)
        self.assertNotIn("serialized_image", icon.events)

    def test_without_an_ico_pystrays_own_handle_path_is_kept(self):
        import pystray
        fake = SimpleNamespace(Icon=PystrayLikeIcon, Menu=pystray.Menu, MenuItem=pystray.MenuItem)
        icon = make_tray_icon(fake, "image", TrayState(), lambda request: None)
        icon._assert_icon_handle()
        self.assertEqual(icon.events, ["serialized_image"])
        self.assertNotIn(standalone.WM_TRAY_ICON_FILE, icon._message_handlers)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_the_hooks_match_pystrays_win32_icon(self):
        # The real pystray 0.19.5 win32 Icon, subclassed exactly as the app does. It is never
        # constructed the pystray way: no window class, window, icon or Shell_NotifyIcon call.
        from pystray import _win32
        from pystray._util import win32

        class Base(_win32.Icon):
            def __init__(self, name, image, title, menu=None):
                self._name, self._icon, self._title, self._menu = name, image, title, menu
                self._visible, self._icon_valid = False, False
                self._icon_handle = self._hwnd = None
                self._message_handlers = {}

            def __del__(self):
                pass

        destroyed, messages = [], []
        with patch.object(_win32, "serialized_image", side_effect=AssertionError("PIL image re-serialized")), \
                patch.object(win32, "DestroyIcon", side_effect=lambda handle: destroyed.append(handle)), \
                patch.object(win32, "Shell_NotifyIcon", side_effect=lambda code, data: messages.append(code)):
            icon = self.make(base=Base)
            icon._assert_icon_handle()
            first = icon._icon_handle
            self.assertEqual(len(self.api.loads), 1)
            icon._hwnd = 0x1234
            icon._show()                                          # NIM_ADD, under the icon lock
            icon._visible = True
            icon.set_icon_file(str(standalone.tray_icon_file("light", True, standalone_app_dir())))
            icon._on_icon_file(0, 0)
            icon.title = "Desk Dial · Knob not found"              # NIM_MODIFY (tooltip)
            icon._hide()
            icon.title = "Desk Dial · Knob connected"              # removed: no message
        self.assertEqual(destroyed, [first], "pystray's _release_icon destroyed the old handle")
        self.assertEqual(messages, [win32.NIM_ADD, win32.NIM_MODIFY, win32.NIM_MODIFY, win32.NIM_DELETE])
        self.assertEqual(len(self.api.loads), 2)
        self.assertTrue(icon._icon_valid)
        for name in ("_show", "_hide", "_on_icon_file", "_assert_icon_handle"):
            self.assertIn(name, type(icon).__dict__, name)
        self.assertIsInstance(type(icon).__dict__["title"], property)


def standalone_app_dir():
    from control_center.ui import APP_DIR
    return APP_DIR


class TrayIconFileTests(unittest.TestCase):
    def test_theme_and_state_map_to_the_designers_files(self):
        app_dir = standalone_app_dir()
        for theme in ("dark", "light"):
            for present, state in ((True, "connected"), (False, "missing")):
                with self.subTest(theme=theme, present=present):
                    path = standalone.tray_icon_file(theme, present, app_dir)
                    self.assertEqual(path.name, f"nano-d-tray-{theme}-{state}.ico")
                    self.assertTrue(path.is_file())
                    png = standalone.tray_png(theme, present, app_dir)
                    self.assertEqual(png.name, f"nano-d-tray-{theme}-{state}-32.png")
                    self.assertTrue(png.is_file())
        self.assertEqual(standalone.tray_icon_file("sepia", True).name, "nano-d-tray-dark-connected.ico")

    def test_knob_present_is_device_connected(self):
        self.assertTrue(standalone.knob_present(SimpleNamespace(device_connected=True)))
        self.assertFalse(standalone.knob_present(SimpleNamespace(device_connected=False)))
        self.assertFalse(standalone.knob_present(SimpleNamespace()))


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_DWORD, REG_SZ = 4, 1

    def __init__(self, value=None, kind=4, fail=None):
        self.value, self.kind, self.fail = value, kind, fail
        self.opened = []

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path):
        self.opened.append((root, path))
        if self.fail == "open":
            raise FileNotFoundError(path)
        return self.Key()

    def QueryValueEx(self, key, name):
        if self.fail == "value" or self.value is None:
            raise FileNotFoundError(name)
        return self.value, self.kind


class TaskbarThemeTests(unittest.TestCase):
    def test_the_registry_value_maps_to_the_icon_set(self):
        registry = FakeWinreg(1)
        self.assertEqual(standalone.taskbar_theme(registry), "light")
        self.assertEqual(registry.opened, [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")])
        self.assertEqual(standalone.taskbar_theme(FakeWinreg(0)), "dark")
        self.assertEqual(standalone.taskbar_theme(FakeWinreg(None)), "dark", "a missing value means dark")
        self.assertEqual(standalone.taskbar_theme(FakeWinreg(fail="open")), "dark")
        self.assertEqual(standalone.taskbar_theme(FakeWinreg("1", kind=FakeWinreg.REG_SZ)), "dark")

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_the_real_registry_read_never_raises(self):
        self.assertIn(standalone.taskbar_theme(), ("dark", "light"))


class StartupCleanupTests(unittest.TestCase):
    """standalone.main (never run here: it takes the single-instance mutex and the knob).
    Its source must close the overlay on every exit path, startup failures included
    (FLOATING_KNOB.md section 4), and set the root's app icon before any Toplevel."""

    def main_body(self, path=None, name="main"):
        path = path or Path(standalone.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name).body

    @staticmethod
    def calls(nodes):
        found = []
        for node in nodes:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    function = child.func
                    found.append(function.id if isinstance(function, ast.Name)
                                 else function.attr if isinstance(function, ast.Attribute) else None)
        return found

    def test_everything_after_start_overlay_is_inside_the_try(self):
        body = self.main_body()
        index = next(i for i, node in enumerate(body)
                     if isinstance(node, ast.Assign) and self.calls([node]) == ["start_overlay"])
        rest = body[index + 1:]
        guarded = next(i for i, node in enumerate(rest) if isinstance(node, ast.Try))
        before = rest[:guarded]
        # Only plain assignments that cannot fail may sit between start_overlay() and the try.
        self.assertEqual([ast.unparse(node) for node in before],
                         ["icon = None", "stage = None", "tray_stopping = threading.Event()"])
        self.assertEqual(rest[guarded + 1:], [], "nothing runs after the protected region")
        try_node = rest[guarded]
        inside = self.calls(try_node.body)
        for name in ("start_stage", "install_picker_chrome", "ControlCenterApp", "credential_file_info",
                     "start_tray", "TrayPresenter", "open_settings", "mainloop"):
            self.assertIn(name, inside)
        # K4 4.1: the stage starts after the floating knob, inside the same try, before the app uses it.
        self.assertLess(inside.index("start_stage"), inside.index("ControlCenterApp"))
        # CAROUSEL.md 12.4: the picker's GPU chrome is installed once, right before the app (and so the
        # WindowsAdapter) exists.
        self.assertEqual(inside.count("install_picker_chrome"), 1)
        self.assertEqual(inside.index("install_picker_chrome") + 1, inside.index("ControlCenterApp"))
        self.assertEqual(try_node.handlers, [])
        final = try_node.finalbody
        self.assertEqual(ast.unparse(final[0]), "close_overlay(overlay)")
        self.assertEqual(ast.unparse(final[1]), "close_stage(stage)")
        self.assertEqual(ast.unparse(final[2]), "if icon is not None:\n    stop_tray(icon, tray_stopping)")
        self.assertIn("destroy", self.calls(final))
        self.assertIn("restore_process_settings", self.calls(final))

    def test_process_settings_come_before_any_thread_and_the_root(self):
        """K4 4.7.2: timer resolution, the power-throttling opt-out and the switch interval are set
        once, by the running instance, before Tk, the overlay and the stage exist."""
        body = self.main_body()
        calls = self.calls(body)
        self.assertEqual(calls.count("apply_process_settings"), 1)
        self.assertNotIn("apply_process_settings", self.from_the_root(body), "before the app's root exists")
        self.assertLess(calls.index("apply_process_settings"), calls.index("start_overlay"))
        self.assertLess(calls.index("CreateMutexW"), calls.index("apply_process_settings"))
        self.assertLess(calls.index("run_smoke_test"), calls.index("apply_process_settings"),
                        "a smoke test never changes the process settings of the machine's companion")

    def run_main(self, app_factory, start_tray=None, presenter=None, install=None):
        """standalone.main run for real until a startup failure, with everything that would touch
        the system replaced: a stand-in kernel32 (never the installed companion's mutex or Show
        event), a stand-in Tk root, no overlay window, no tray, no port, no credential file, logs in
        a temporary folder, and a stand-in for the picker's GPU chrome install (``install``; the real
        one would register the factory for the rest of this test process). Returns (error, root,
        overlay, kernel)."""
        import os
        import tempfile
        import tkinter
        from control_center import ui
        kernel = Mock(name="kernel32")
        kernel.CreateMutexW.return_value = 0x51
        kernel.CreateEventW.return_value = 0x52

        def win_dll(name, **kwargs):
            if name != "kernel32":
                raise AssertionError(f"main loaded {name!r}")
            return kernel
        fake_ctypes = SimpleNamespace(WinDLL=win_dll, windll=SimpleNamespace(user32=Mock(name="user32")),
                                      c_void_p=ctypes.c_void_p, c_bool=ctypes.c_bool, c_wchar_p=ctypes.c_wchar_p,
                                      c_uint32=ctypes.c_uint32, get_last_error=lambda: 0, WinError=ctypes.WinError)
        root, overlay, stage = Mock(name="root"), Mock(name="overlay"), Mock(name="stage")
        self.stage = stage
        error = None
        from contextlib import ExitStack
        with ExitStack() as stack:
            temp = stack.enter_context(tempfile.TemporaryDirectory())
            for patcher in (
                    patch.dict(os.environ, {"LOCALAPPDATA": temp}),
                    patch.object(sys, "argv", ["standalone.py", "--background"]),
                    patch.object(standalone, "ctypes", fake_ctypes),
                    patch.object(standalone, "RotatingFileHandler",
                                 lambda *args, **kwargs: standalone.logging.NullHandler()),
                    patch.object(standalone.logging, "basicConfig"),
                    patch.object(standalone, "enable_crash_diagnostics", return_value={}),
                    patch.object(standalone, "credential_file_info", return_value={"exists": False}),
                    patch.object(standalone, "taskbar_theme", return_value="dark"),
                    patch.object(standalone, "start_overlay", return_value=overlay),
                    patch.object(standalone, "start_stage", return_value=stage),
                    patch.object(standalone, "apply_process_settings", return_value={"timerPeriod1": False}),
                    patch.object(standalone, "start_tray", start_tray or Mock(side_effect=AssertionError("no tray"))),
                    patch.object(standalone, "TrayPresenter", presenter or Mock()),
                    patch.object(standalone, "install_picker_chrome", install or Mock(return_value=True)),
                    patch.object(tkinter, "Tk", return_value=root),
                    patch.object(ui, "ControlCenterApp", app_factory),
                    patch.object(ui, "apply_app_icon"), patch.object(ui, "register_fonts"),
                    patch.object(ui, "DATA_DIR", Path(temp) / "data")):
                stack.enter_context(patcher)
            restore = stack.enter_context(patch.object(standalone, "restore_process_settings"))
            try:
                standalone.main()
            except Exception as exc:
                error = exc
            self.restored = restore.call_args_list
        kernel.SetEvent.assert_not_called()
        return error, root, overlay, kernel

    def test_a_failing_app_still_closes_the_overlay_and_the_root(self):
        error, root, overlay, kernel = self.run_main(Mock(side_effect=RuntimeError("ControlCenterApp failed")))
        self.assertEqual(str(error), "ControlCenterApp failed")
        overlay.close.assert_called_once_with()
        self.stage.close.assert_called_once_with()          # the stage too (K4 4.1)
        root.destroy.assert_called_once_with()
        self.assertEqual(len(self.restored), 1, "timeEndPeriod on every exit path")
        self.assertEqual([call.args for call in kernel.CloseHandle.call_args_list], [(0x52,), (0x51,)])

    def test_a_failure_after_the_tray_started_also_stops_the_tray(self):
        runtime = SimpleNamespace(device_status="Knob disconnected", device_connected=False)
        app = SimpleNamespace(device=SimpleNamespace(_emit=Mock()), runtime=runtime)
        icon = Mock(name="tray icon")
        error, root, overlay, _kernel = self.run_main(
            Mock(return_value=app), start_tray=Mock(return_value=icon),
            presenter=Mock(side_effect=RuntimeError("TrayPresenter failed")))
        self.assertEqual(str(error), "TrayPresenter failed")
        overlay.close.assert_called_once_with()
        icon.stop.assert_called_once_with()
        root.destroy.assert_called_once_with()

    def test_main_installs_the_picker_chrome_once_before_the_windows_adapter_exists(self):
        """CAROUSEL.md 12.4, WP7c-D11 (lead decision 2026-09-26): main installs the GPU chrome once,
        after the stage and right before ControlCenterApp, whose runtime builds the WindowsAdapter and
        so the CarouselPresenter that reads the installed factory. A failing install never stops the
        start (install_picker_chrome never raises; its own tests are in test_standalone.py)."""
        order = []
        install = Mock(side_effect=lambda: order.append("install") or True)

        def app(*args, **kwargs):
            order.append(("app", kwargs.get("live"), kwargs.get("chrome")))
            raise RuntimeError("stop after the app")
        error, _root, overlay, _kernel = self.run_main(app, install=install)
        self.assertEqual(str(error), "stop after the app")
        self.assertEqual(order, ["install", ("app", True, False)])
        install.assert_called_once_with()
        overlay.close.assert_called_once_with()
        # a failing install (it logs and returns False) still builds the app
        order.clear()
        error, *_ = self.run_main(app, install=Mock(side_effect=lambda: order.append("install") or False))
        self.assertEqual(order, ["install", ("app", True, False)])

    def from_the_root(self, body):
        """The calls from ``root = tk.Tk()`` on, in statement order (--check-music's hidden
        diagnostic root, which shows no window, comes earlier and is not the app's)."""
        index = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign)
                     and [target.id for target in node.targets if isinstance(target, ast.Name)] == ["root"])
        return self.calls(body[index:])

    def test_the_app_icon_is_set_on_the_root_before_any_window(self):
        calls = self.from_the_root(self.main_body())
        self.assertEqual(calls[0], "Tk")
        self.assertLess(calls.index("apply_app_icon"), calls.index("start_overlay"))
        self.assertLess(calls.index("apply_app_icon"), calls.index("ControlCenterApp"))
        self.assertLess(calls.index("apply_app_icon"), calls.index("start_tray"))
        app_calls = self.from_the_root(self.main_body(Path(standalone.__file__).with_name("app.py")))
        self.assertEqual(app_calls[0], "Tk")
        self.assertLess(app_calls.index("apply_app_icon"), app_calls.index("ControlCenterApp"))

    def test_the_tray_follows_the_knob_state_and_the_theme(self):
        source = ast.unparse(ast.Module(body=self.main_body(), type_ignores=[]))
        self.assertIn("icon_file=tray_icon_file(theme, present, APP_DIR)", source)
        self.assertIn("present=knob_present(app.runtime), messages=app.take_tray_messages()", source)
        self.assertIn("presenter.set_theme(taskbar_theme())", source)
        self.assertIn("root.after(THEME_POLL_MS, poll_theme)", source)
        # K4 20.3: WM_SETTINGCHANGE "ImmersiveColorSet" on pystray's window queues 'theme'; the poll
        # is the 30 s backstop.
        self.assertIn("on_theme=lambda: requests.put('theme')", source)
        self.assertIn("'theme': lambda: presenter.set_theme(taskbar_theme())", source)
        self.assertEqual(standalone.THEME_POLL_MS, 30000)


class OverlayStatusTests(unittest.TestCase):
    def runtime(self):
        return SimpleNamespace(device_connected=False, device_status="Knob disconnected", led_style="color",
                               artwork_enabled=True, artwork_status=None,
                               apple=SimpleNamespace(credentials={}))

    def test_status_json_carries_the_overlay_metrics(self):
        overlay = SimpleNamespace(metrics=lambda: {"state": "hidden", "rect": (24, 496, 434, 434),
                                                   "gdi_objects": 5, "odd": object()})
        app = SimpleNamespace(runtime=self.runtime(), controller=Controller(), live=True, overlay=overlay,
                              overlay_submits=7)
        status = standalone.status_payload(app, standalone.RetryPolicy(), {"exists": False})
        self.assertEqual(status["overlay"]["state"], "hidden")
        self.assertEqual(status["overlay"]["rect"], [24, 496, 434, 434])
        self.assertEqual(status["overlay"]["scenesSubmitted"], 7)
        json.dumps(status)

    def test_no_overlay_or_failing_metrics(self):
        app = SimpleNamespace(runtime=self.runtime(), controller=Controller(), live=True)
        self.assertIsNone(standalone.status_payload(app, standalone.RetryPolicy(), {})["overlay"])
        app.overlay = SimpleNamespace(metrics=Mock(side_effect=RuntimeError("gone")))
        self.assertEqual(standalone.overlay_status(app), {"error": "RuntimeError", "scenesSubmitted": 0})


class OverlayStartTests(unittest.TestCase):
    def test_a_started_overlay_is_returned(self):
        overlay = Mock()
        overlay.start.return_value = True
        self.assertIs(standalone.start_overlay(lambda **kwargs: overlay, log=Mock()), overlay)

    def test_a_disabled_overlay_is_kept_and_its_reason_logged(self):
        overlay = Mock()
        overlay.start.return_value = False
        overlay.metrics.return_value = {"last_error": "CreateWindowExW failed (error 5)"}
        log = Mock()
        self.assertIs(standalone.start_overlay(lambda **kwargs: overlay, log=log), overlay)
        self.assertIn("CreateWindowExW failed", str(log.warning.call_args))

    def test_an_overlay_that_cannot_be_built_is_none(self):
        log = Mock()
        self.assertIsNone(standalone.start_overlay(Mock(side_effect=OSError("no user32")), log=log))
        log.exception.assert_called_once()

    def test_close_overlay_never_raises(self):
        standalone.close_overlay(None)
        overlay = Mock()
        overlay.close.side_effect = RuntimeError("late")
        with self.assertLogs("nanod.overlay", "ERROR"):
            standalone.close_overlay(overlay)
        overlay.close.assert_called_once_with()


class FakeBackend:
    """overlay.Win32Backend stand-in: records the lifecycle, creates nothing."""
    instances = []

    def __init__(self, present_ok=True):
        self.calls = []
        self.hwnd = None
        self.registered = False
        self.present_ok = present_ok
        self.thread = None
        FakeBackend.instances.append(self)

    def prepare_thread(self):
        self.thread = threading.current_thread().name
        self.calls.append("prepare")
        return 2

    def geometry(self):
        self.calls.append("geometry")
        return (0, 0, 5120, 1392), 96

    def create(self, handler, position, size):
        self.calls.append(("create", position, size))
        self.hwnd, self.registered = 1, True

    def resize(self, size):
        self.calls.append(("resize", tuple(size)))

    def present(self, frame, size, position, src_x, alpha):
        self.calls.append(("present", len(frame), size, src_x, alpha))
        return self.present_ok

    def is_visible(self):
        return False

    def destroy_window(self):
        self.calls.append("destroy")
        self.hwnd = None

    def pump(self):
        self.calls.append("pump")
        return False

    def unregister(self):
        self.calls.append("unregister")
        self.registered = False


class FakeKnob:
    started = stopped = True

    def __init__(self, **kwargs):
        self.state, self.wants_frames = "hidden", False
        self.closed = False

    def start(self):
        return type(self).started

    def metrics(self):
        return {"dpi": 96, "window_px": [434, 434], "lcd_px": 302, "dpi_awareness": 2, "last_error": None}

    def close(self):
        self.closed = True
        return type(self).stopped


def fake_overlay_module(present_ok=True, started=True, stopped=True):
    knob = type("Knob", (FakeKnob,), {"started": started, "stopped": stopped})
    return SimpleNamespace(Win32Backend=lambda: FakeBackend(present_ok), KnobOverlay=knob)


class SmokeOverlayWindowTests(unittest.TestCase):
    def setUp(self):
        FakeBackend.instances = []

    def test_a_module_smoke_check_is_used_when_present(self):
        module = SimpleNamespace(smoke_check=lambda: {"ulw": True})
        with patch.object(standalone, "gui_resources", return_value=(10, 3)):
            detail = standalone.smoke_overlay_window(module)
        self.assertEqual(detail, {"ulw": True, "gdi": [10, 10], "user": [3, 3]})

    def test_hidden_cycle_on_its_own_thread_then_a_knob_overlay_start_and_close(self):
        with patch.object(standalone, "gui_resources", return_value=(10, 3)):
            detail = standalone.smoke_overlay_window(fake_overlay_module())
        backend = FakeBackend.instances[0]
        self.assertEqual(backend.thread, "NanoD-overlay-smoke")
        names = [call if isinstance(call, str) else call[0] for call in backend.calls]
        self.assertEqual(names, ["prepare", "geometry", "create", "present", "resize", "present", "resize",
                                 "present", "destroy", "pump", "unregister"])
        _, length, size, src_x, alpha = backend.calls[3]
        self.assertEqual((src_x, alpha), (size[0], 0), "presented fully slid out and transparent")
        self.assertEqual(length, size[0] * size[1] * 4)
        # The app's geometry (overlay.window_rect): the box starts at the work area's left edge
        # and is the face plus the 24 px inset wide (FLOATING_KNOB.md section 9.11).
        self.assertEqual(backend.calls[2][1], (0, (1392 - size[1]) // 2))
        self.assertEqual(size, (434 + 24, 434))
        # Two DIB rebuilds (a DPI change and back), each presented, the counts unchanged.
        self.assertEqual([call[1] for call in backend.calls if call[0] == "resize"],
                         [(size[0] + 2, size[1] + 2), size])
        self.assertEqual([step["size"] for step in detail["window"]["dibRebuilds"]],
                         [[size[0] + 2, size[1] + 2], list(size)])
        self.assertTrue(detail["window"]["ulw"])
        self.assertEqual(detail["overlay"]["lcd_px"], 302)
        self.assertEqual((detail["gdi"], detail["user"]), ([10, 10], [3, 3]))

    def test_failures_fail_the_check(self):
        for module, message in ((fake_overlay_module(present_ok=False), "hidden window cycle"),
                                (fake_overlay_module(started=False), "did not start"),
                                (fake_overlay_module(stopped=False), "did not stop")):
            with self.subTest(message=message), patch.object(standalone, "gui_resources", return_value=(1, 1)):
                with self.assertRaisesRegex(RuntimeError, message):
                    standalone.smoke_overlay_window(module)

    def test_a_dib_rebuild_that_leaks_fails_the_check(self):
        counts = iter([(10, 3), (12, 4)] + [(13, 4)] * 1000)   # the replaced DIB was never deleted
        with patch.object(standalone, "gui_resources", side_effect=lambda: next(counts)), \
                patch.object(standalone, "GUI_BASELINE_SECONDS", 0.05), \
                patch.object(standalone, "DIB_REBUILD_SETTLE_SECONDS", 0.05):
            with self.assertRaisesRegex(RuntimeError, "DIB rebuilds"):
                standalone.smoke_overlay_window(fake_overlay_module())

    def test_a_briefly_counted_object_of_another_thread_is_not_a_leak(self):
        counts = iter([(10, 3), (12, 4), (13, 4), (12, 4), (12, 4)] + [(10, 3)] * 1000)
        with patch.object(standalone, "gui_resources", side_effect=lambda: next(counts)):
            detail = standalone.smoke_overlay_window(fake_overlay_module())
        self.assertEqual([step["objects"] for step in detail["window"]["dibRebuilds"]], [[12, 4], [12, 4]])

    def test_objects_left_behind_fail_the_check(self):
        counts = iter([(10, 3)] + [(11, 4)] * 1000)
        with patch.object(standalone, "gui_resources", side_effect=lambda: next(counts)), \
                patch.object(standalone, "GUI_BASELINE_SECONDS", 0.05):
            with self.assertRaisesRegex(RuntimeError, "leaked"):
                standalone.smoke_overlay_window(SimpleNamespace(smoke_check=lambda: {}))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_gui_resources_counts_this_processs_gdi_objects(self):
        # Memory DCs only: GDI objects of this process, no window.
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = ctypes.c_void_p, (ctypes.c_void_p,)
        gdi32.DeleteDC.restype, gdi32.DeleteDC.argtypes = ctypes.c_int, (ctypes.c_void_p,)
        seen = []
        for _attempt in range(3):              # another thread's GDI work may interleave
            before = standalone.gui_resources()
            dcs = [gdi32.CreateCompatibleDC(None) for _ in range(5)]
            try:
                self.assertTrue(all(dcs))
                during = standalone.gui_resources()
            finally:
                for dc in dcs:
                    if dc:
                        gdi32.DeleteDC(dc)
            after = standalone.gui_resources()
            seen.append((before, during, after))
            if during[0] - before[0] == 5 and after[0] == before[0]:
                break
        else:
            self.fail(f"GDI counts did not follow 5 memory DCs: {seen}")


class SmokeRendererTests(unittest.TestCase):
    """The PIL-only overlay checks of --smoke-test (real renderers, no window)."""

    def test_smoke_overlay_renders_both_dpis(self):
        detail = standalone.smoke_overlay()
        self.assertEqual(set(detail), {"dpi100", "dpi200", "hiresGlyphs"})
        self.assertEqual(detail["dpi100"]["lcd"], 302)
        self.assertEqual(detail["dpi200"]["lcd"], 604)
        self.assertGreater(detail["dpi200"]["window"][0], detail["dpi100"]["window"][0])
        from control_center.presentation import ICONS
        self.assertEqual(detail["hiresGlyphs"], len([name for name in ICONS if name]) * 3 * 2)

    def test_a_missing_hires_glyph_fails_the_overlay_check(self):
        # render_lcd would quietly upscale the 1x mask: the frozen gate must notice instead.
        from control_center import lcd_preview
        real = lcd_preview._hires_mask_source

        def missing_home_at_3x(name, size, factor):
            return None if (name, factor) == ("home", 3) else real(name, size, factor)
        with patch.object(lcd_preview, "_hires_mask_source", missing_home_at_3x):
            with self.assertRaisesRegex(RuntimeError, r"home-16@3x"):
                standalone.smoke_overlay()

    def test_smoke_overlay_composes_submitted_scenes(self):
        from PIL import Image
        from control_center.overlay import OverlayScene
        overlay = standalone.SmokeOverlay(dpi=96)
        self.assertEqual(overlay.lcd_px, 302)
        ring = ((255, 255, 255, 1.0),) * 60
        overlay.submit(OverlayScene("k", Image.new("RGBA", (302, 302), (1, 2, 3, 255)), ring))
        overlay.submit(OverlayScene(None, None, ring))
        self.assertEqual((overlay.scenes, overlay.errors), (2, []))
        overlay.submit(OverlayScene("k", Image.new("RGBA", (240, 240)), ring))
        overlay.submit(OverlayScene("k", None, ring[:10]))
        self.assertEqual(overlay.scenes, 2)
        self.assertEqual(len(overlay.errors), 2)
        self.assertTrue(overlay.wants_frames)
        overlay.touch()
        overlay.peek(2.5)
        overlay.set_suppressed("disconnected", True)
        overlay.close()
        self.assertEqual(overlay.metrics()["scenes"], 2)


if __name__ == "__main__":
    unittest.main()

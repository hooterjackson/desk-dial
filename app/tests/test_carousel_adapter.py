"""Desktop v6/v7 integration of the window picker (CAROUSEL.md sections 1, 6, 7, 10 and 12;
DESKTOP_STAGE.md 2.3, 9.5-9.7, 10, 15), without Tk, windows or native calls: the WindowsAdapter <->
presenter seam with a recording fake presenter (the v7 runtime interface: snap, half_rect,
close_pair, cancel(origin, complete=, reason=), foreground_hwnd, take_events, toast), the
IconWorker's facts channel and icon ladder with fake Win32 helpers, the runtime's facts plumbing,
the UI's picker wiring (stand-in app objects) and the smoke-test helpers with stand-in carousel
modules.

Fixture titles, paths, profile and monitor names are synthetic. Nothing here opens a port,
creates a window, changes the foreground or reads user data.
"""
from dataclasses import dataclass, replace
from datetime import date
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

import control_center
from control_center import ui
from control_center import windows as w
from test_cc_runtime_colours import FakeIcons, Harness as RuntimeHarness

SEP = " \u00b7 "
CLOSED = "Closed \u00b7 can\u2019t switch"
SECRET_PATH = r"C:\Program Files\Secret Vendor\chrome.exe"


# ----------------------------------------------------------------------------- fakes
@dataclass(frozen=True)
class FakeWindowFacts:
    exe: str
    app: str
    title: str
    class_name: str = ""
    minimized: bool = False
    audible: object = None
    profile: object = None
    monitor: object = None


@dataclass(frozen=True)
class FakeLabel:
    app: str
    title: str
    desc: str


def _fake_label_for(facts, today):
    desc = "In a call" if facts.audible else facts.exe
    if facts.minimized:
        desc += SEP + "Minimized"
    return FakeLabel(facts.app, facts.title, desc)


def _fake_disambiguate(facts_list, labels):
    out = list(labels)
    for index, label in enumerate(labels):
        twins = [i for i, other in enumerate(labels) if other == label]
        if len(twins) > 1:
            for attr in ("profile", "monitor"):
                values = [getattr(facts_list[i], attr) for i in twins]
                if all(values) and len(set(values)) > 1:
                    out[index] = replace(label, desc=label.desc + SEP + getattr(facts_list[index], attr))
                    break
    return out


def _fake_app_display_name(exe, package_name="", file_description="", product_name=""):
    return package_name or file_description or product_name or PureWindowsPath(exe).stem.title()


def _fake_profile(value):
    text = value if isinstance(value, str) else ""
    return text[:-len(" - Chrome")] if text.endswith(" - Chrome") and len(text) > len(" - Chrome") else None


LABELS = SimpleNamespace(WindowFacts=FakeWindowFacts, Label=FakeLabel, label_for=_fake_label_for,
                         disambiguate=_fake_disambiguate, app_display_name=_fake_app_display_name,
                         closed_label=lambda label: replace(label, desc=CLOSED),
                         profile_from_relaunch_name=_fake_profile)
HAS_LABELS = importlib.util.find_spec("control_center.window_labels") is not None


def record(hwnd, pid=20, title=None, **values):
    values.setdefault("app", "chrome")
    values.setdefault("path", r"C:\Apps\chrome.exe")
    values.setdefault("class_name", "Chrome_WidgetWin_1")
    return dict(hwnd=hwnd, pid=pid, id=f"{hwnd:x}:{pid}:0:0", title=title or f"Window {hwnd}",
                available=True, **values)


class FakeRoot:
    def __init__(self):
        self.timers, self.counter, self.errors = {}, 0, []

    def update_idletasks(self): pass
    def winfo_id(self): return 900

    def after(self, delay, callback):
        self.counter += 1
        self.timers[self.counter] = (delay, callback)
        return self.counter

    def after_cancel(self, timer):
        self.timers.pop(timer, None)

    def report_callback_exception(self, *error):
        self.errors.append(error)


class FakeNative:
    own_pid = 100

    def __init__(self, log):
        self.log = log
        self.windows = {r["hwnd"]: r for r in [record(1), record(2), record(3)]}
        self.windows[900] = record(900, pid=self.own_pid)
        self.windows[901] = record(901, pid=self.own_pid)
        self.foreground_hwnd = 1
        self.allow_focus = True
        self.closed = False
        self.hotkey_enabled = False
        self.last_focus = None

    def root_handle(self, hwnd): return hwnd

    def identity(self, hwnd):
        item = self.windows.get(hwnd)
        return {key: item[key] for key in ("hwnd", "pid", "id")} if item else None

    def foreground(self): return self.identity(self.foreground_hwnd)
    def records(self): return list(self.windows.values())
    def attach_hotkey(self, hwnd, callback, report_error): self.hotkey_callback = callback
    def watch(self, on_foreground, on_destroy): self.on_foreground = on_foreground

    def focus(self, hwnd, restore=False):
        self.log.append(("focus", hwnd, restore))
        if self.allow_focus:
            self.foreground_hwnd = hwnd
        self.last_focus = (self.allow_focus, 12.5, 3)   # what NativeWindows.focus records
        return self.allow_focus

    def hotkey(self, enabled): pass
    def close(self): self.closed = True


class FakePresenter:
    """The carousel presenter's protocol, recording every call in the shared log."""
    hwnd = 901

    def __init__(self, log, root, native, on_cancel):
        self.log, self.on_cancel = log, on_cancel
        self.visible = self.closed = False
        self.queue = []
        self.labels = self.icons = None
        self.backgrounds = []
        self.rect = None

    def show(self, snapshot):
        self.log.append(("show",))
        self.visible = True
        self.snapshot = snapshot

    def focus_local(self): self.log.append(("focus_local",))

    def highlight(self, index, bump=0):
        self.log.append(("highlight", index) + ((bump,) if bump else ()))

    # v7 (DESKTOP_STAGE.md 9, 10)
    def snap(self, effect):
        self.log.append(("snap", effect.get("side"), effect.get("index"), effect.get("target_rect"),
                         dict(effect.get("item") or {})))
        return True

    def complete_one_side(self, origin, side, rect=None):
        self.log.append(("complete_one_side", dict(origin), side, rect))
        return 77

    def raise_window(self, hwnd):
        self.log.append(("raise_window", hwnd))
        return True

    def half_rect(self, side):
        return {"left": (0, 0, 960, 1040), "right": (960, 0, 1920, 1040)}.get(side)

    def toast(self, text, exit=False):
        self.log.append(("toast", text, bool(exit)))
        return True

    def end_toast(self):
        self.log.append(("end_toast",))

    def set_reduced_motion(self, on):
        self.log.append(("reduced_motion", on))

    def play_pair_exit(self): self.log.append(("play_pair_exit",))

    def set_icons(self, icons):
        self.log.append(("set_icons",))
        self.icons = icons

    def set_labels(self, labels):
        self.log.append(("set_labels",))
        self.labels = labels

    def set_background(self, value):
        self.backgrounds.append(value)

    def take_events(self):
        events, self.queue = self.queue, []
        return events

    def play_switch_exit(self, toast_text): self.log.append(("play_switch_exit", toast_text))
    def play_cancel_exit(self): self.log.append(("play_cancel_exit",))

    def hide(self):
        self.log.append(("hide",))
        self.visible = False

    def close(self):
        self.log.append(("close",))
        self.closed = True


class MinimalPresenter:
    """Only the pre-v6 PickerOverlay protocol (no labels, background, events or exits)."""
    hwnd = 901

    def __init__(self, root, native, on_cancel): self.visible = False
    def show(self, snapshot): self.visible = True
    def focus_local(self): pass
    def highlight(self, index): pass
    def set_icons(self, icons): pass
    def hide(self): self.visible = False
    def close(self): pass


# ----------------------------------------------------------------------------- adapter
class AdapterCase(unittest.TestCase):
    presenter_class = FakePresenter

    def setUp(self):
        self.log, self.events = [], []
        self.root = FakeRoot()
        log = self.log
        presenter_class = self.presenter_class
        factory = (lambda root, native, on_cancel: presenter_class(log, root, native, on_cancel)) \
            if presenter_class is FakePresenter else presenter_class
        for patcher in (patch.object(w, "NativeWindows", lambda: FakeNative(log)),
                        patch.object(w, "PickerOverlay", factory),
                        patch.object(w, "_window_labels", lambda: LABELS)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.adapter = w.WindowsAdapter(
            self.root, lambda: self.events.append("hotkey"), lambda: self.events.append("cancel"),
            lambda: self.events.append("focus_lost"), lambda: self.events.append("closed"),
            on_switch=lambda: self.events.append("switch"), on_turn=lambda delta: self.events.append(("turn", delta)))
        self.adapter._today = lambda: date(2026, 9, 24)
        self.presenter = self.adapter.overlay
        self.native = self.adapter.native
        self.addCleanup(self.adapter.close)

    def open_picker(self):
        snapshot = self.adapter.snapshot()
        self.adapter.show(snapshot)
        return snapshot

    def names(self):
        return [entry[0] for entry in self.log]


class PresenterFactoryTests(unittest.TestCase):
    def test_the_module_global_factory_builds_the_carousel_presenter(self):
        made = []
        fake = ModuleType("control_center.carousel")

        class CarouselPresenter:
            def __init__(self, root, native, on_cancel):
                made.append((root, native, on_cancel))
        fake.CarouselPresenter = CarouselPresenter
        cancel = Mock()
        with patch.dict(sys.modules, {"control_center.carousel": fake}), \
                patch.object(control_center, "carousel", fake, create=True):
            presenter = w.PickerOverlay("root", "native", cancel)
        self.assertIsInstance(presenter, CarouselPresenter)
        self.assertEqual(made, [("root", "native", cancel)])

    def test_the_old_grid_overlay_is_gone(self):
        for name in ("picker_grid", "fit_caption", "_ui_family"):
            self.assertFalse(hasattr(w, name), name)
        self.assertTrue(callable(w.PickerOverlay))
        self.assertNotIsInstance(w.PickerOverlay, type, "a factory, not the Tk grid class")


class SeamTests(AdapterCase):
    def test_labels_follow_focus_and_no_icon_work_is_in_the_focus_path(self):
        self.open_picker()
        self.assertEqual(self.names(), ["show", "focus", "focus_local", "set_labels"])
        self.assertEqual(self.log[1], ("focus", 901, False))
        self.assertNotIn("set_icons", self.names(), "icons come from the UI tick, never the WM_HOTKEY path")

    def test_denied_focus_hides_and_pushes_nothing(self):
        self.native.allow_focus = False
        with self.assertRaisesRegex(OSError, "F24"):
            self.open_picker()
        self.assertEqual(self.names(), ["show", "focus", "hide"])
        self.assertFalse(self.adapter._visible)

    def test_a_presenter_that_cannot_come_up_is_hidden_and_the_error_propagates(self):
        self.presenter.show = Mock(side_effect=OSError("handshake timed out"))
        with self.assertRaisesRegex(OSError, "handshake"):
            self.open_picker()
        self.assertEqual(self.names(), ["hide"])
        self.assertFalse(self.adapter._visible)
        self.assertFalse([entry for entry in self.log if entry[0] == "focus"], "no focus without a presenter")

    def test_switch_is_focus_then_verify_then_exit_animation_then_hide(self):
        snapshot = self.open_picker()
        item = snapshot["items"][1]
        del self.log[:]
        self.assertTrue(self.adapter.activate(item))
        self.assertEqual(self.log, [("focus", item["hwnd"], True),
                                    ("play_switch_exit", "Chrome" + SEP + item["title"]), ("hide",)])

    def test_the_switch_toast_uses_the_label_the_picker_showed(self):
        snapshot = self.open_picker()
        item = snapshot["items"][1]
        self.adapter.set_window_facts({item["id"]: {"file_description": "Google Chrome"}})
        self.adapter.activate(dict(item))
        self.assertIn(("play_switch_exit", "Google Chrome" + SEP + item["title"]), self.log)

    def test_a_failed_or_stale_switch_plays_no_exit(self):
        snapshot = self.open_picker()
        self.native.allow_focus = False
        self.assertFalse(self.adapter.activate(snapshot["items"][1]))
        self.native.allow_focus = True
        stale = dict(snapshot["items"][2], id="recycled")
        self.assertFalse(self.adapter.activate(stale))
        self.assertNotIn("play_switch_exit", self.names())
        self.assertTrue(self.presenter.visible)

    def test_an_exit_animation_failure_never_changes_the_switch(self):
        snapshot = self.open_picker()
        self.presenter.play_switch_exit = Mock(side_effect=RuntimeError("presenter thread gone"))
        self.assertTrue(self.adapter.activate(snapshot["items"][1]))
        self.assertFalse(self.presenter.visible, "hidden all the same")

    def test_cancel_restores_then_plays_the_cancel_exit_then_hides(self):
        snapshot = self.open_picker()
        del self.log[:]
        self.assertTrue(self.adapter.cancel(snapshot["origin"]))
        self.assertEqual(self.log, [("focus", 1, True), ("play_cancel_exit",), ("hide",)])

    def test_a_cancel_that_restores_nothing_still_fades_out_and_answers_not_restored(self):
        # v7: the exit is the visual close of Back whatever the focus did (there is no "focus
        # restored" toast to protect any more, R:152), and cancel_result says what happened.
        snapshot = self.open_picker()
        self.native.windows[1] = record(1, pid=999)       # the origin was replaced
        del self.log[:]
        self.adapter.take_events()
        self.assertFalse(self.adapter.cancel(snapshot["origin"]))
        self.assertEqual(self.log, [("play_cancel_exit",), ("hide",)])
        self.assertEqual(self.adapter.take_events()[-1], {"kind": "cancel_result", "restored": False, "completed": False})

    def test_focus_loss_dismissals_get_no_exit_animation(self):
        snapshot = self.open_picker()
        self.native.foreground_hwnd = 3
        self.assertFalse(self.adapter.cancel(snapshot["origin"]))      # the focus-loss race
        self.adapter.show(self.adapter.snapshot())
        self.native.foreground_hwnd = 3
        self.adapter._check_focus_lost()
        self.assertNotIn("play_cancel_exit", self.names())
        self.assertNotIn("play_switch_exit", self.names())
        self.assertIn("focus_lost", self.events)

    def test_close_still_releases_native_before_the_presenter(self):
        self.open_picker()
        self.adapter.close()
        self.assertTrue(self.native.closed)
        self.assertEqual(self.names()[-2:], ["hide", "close"])

    def test_a_switch_or_cancel_reaching_a_hidden_picker_plays_no_exit(self):
        snapshot = self.open_picker()
        self.adapter.hide()                                   # e.g. a focus-loss dismissal first
        del self.log[:]
        self.assertTrue(self.adapter.cancel(snapshot["origin"]))
        self.assertTrue(self.adapter.activate(snapshot["items"][1]))
        self.assertEqual(self.names(), ["focus", "hide", "focus", "hide"], "no stale toast")


class FocusLogTests(AdapterCase):
    def test_every_focus_change_is_logged_with_its_timing_and_never_a_title(self):
        with self.assertLogs(w._log.name, "INFO") as logs:
            snapshot = self.open_picker()
            self.adapter.activate(snapshot["items"][1])
            snapshot = self.open_picker()
            self.adapter.cancel(snapshot["origin"])
            self.native.allow_focus = False
            with self.assertRaises(OSError):
                self.open_picker()
        self.assertEqual([record.getMessage() for record in logs.records], [
            "Picker open focus granted after 12.5 ms (3 checks)",
            "Picker switch focus granted after 12.5 ms (3 checks)",
            "Picker open focus granted after 12.5 ms (3 checks)",
            "Picker cancel focus granted after 12.5 ms (3 checks)",
            "Picker open focus NOT granted after 12.5 ms (3 checks)"])
        self.assertNotIn("Window", "\n".join(logs.output))

    def test_a_native_layer_without_timings_logs_nothing(self):
        self.native.last_focus = None
        self.native.focus = lambda hwnd, restore=False: True
        with patch.object(w._log, "info") as info:
            self.open_picker()
        info.assert_not_called()


class NoBackgroundAvailabilityTests(AdapterCase):
    def test_no_background_is_offered_only_off_the_plain_host(self):
        self.assertEqual(self.adapter.picker_backgrounds, ("glass", "none"))
        self.presenter.host_mode = "plain"
        self.assertEqual(self.adapter.picker_backgrounds, ("glass",))
        self.presenter.host_mode = "noredirection"
        self.assertEqual(self.adapter.picker_backgrounds, ("glass", "none"))
        del self.presenter.host_mode
        self.presenter.metrics = lambda: {"host_mode": "plain", "frames": 3}
        self.assertEqual(self.adapter.picker_backgrounds, ("glass",))
        self.presenter.metrics = Mock(side_effect=RuntimeError("presenter thread gone"))
        self.assertEqual(self.adapter.picker_backgrounds, ("glass", "none"))

    def test_the_plain_host_name_is_the_carousels(self):
        from control_center import carousel
        self.assertEqual(w.HOST_PLAIN_MODE, carousel.HOST_PLAIN)


class PresenterInputTests(AdapterCase):
    def test_input_waits_for_pump_on_the_tk_thread(self):
        self.open_picker()
        self.presenter.queue = [("switch", 1)]
        self.assertEqual(self.events, [], "the presenter thread only queues")
        thread = threading.Thread(target=self.adapter.pump)
        thread.start()
        thread.join()
        self.assertEqual(self.events, [], "never drained off the Tk thread")
        self.adapter.pump()
        self.assertEqual(self.events, ["switch"])
        self.adapter.pump()
        self.assertEqual(self.events, ["switch"], "each event runs once")

    def test_switch_cancel_and_turns(self):
        self.open_picker()
        self.presenter.queue = [("cancel", None), ("turn", 1), ("turn", -1), ("switch", None)]
        self.adapter.pump()
        self.assertEqual(self.events, ["cancel", ("turn", 1), ("turn", -1), "switch"])

    def test_a_switch_for_a_card_the_knob_has_left_is_ignored(self):
        snapshot = self.open_picker()
        self.presenter.queue = [("switch", snapshot["index"] + 1), ("switch", snapshot["index"])]
        self.adapter.pump()
        self.assertEqual(self.events, ["switch"])

    def test_malformed_events_are_skipped(self):
        self.open_picker()
        self.presenter.queue = [None, ("turn",), ("turn", True), ("turn", 0), ("turn", "1"), ("unknown", 3),
                                ("cancel", None)]
        self.adapter.pump()
        self.assertEqual(self.events, ["cancel"])

    def test_input_of_a_dismissed_picker_is_dropped(self):
        snapshot = self.open_picker()
        self.adapter.cancel(snapshot["origin"])
        self.presenter.queue = [("cancel", None), ("switch", None)]
        self.adapter.pump()
        self.assertEqual(self.events, [])
        self.presenter.queue = [("switch", None)]
        self.open_picker()                              # left over from an earlier picker: stale
        self.adapter.pump()
        self.assertEqual(self.events, [])

    def test_a_failing_event_queue_never_breaks_pump(self):
        self.open_picker()
        self.presenter.take_events = Mock(side_effect=RuntimeError("queue gone"))
        self.native.hotkey_enabled = True
        self.adapter._hotkey_pending = True
        self.adapter.pump()
        self.assertEqual(self.events, ["hotkey"])

    def test_callback_errors_are_reported_to_tk(self):
        self.open_picker()
        self.adapter.on_switch = Mock(side_effect=ValueError("controller broke"))
        self.presenter.queue = [("switch", None)]
        self.adapter.pump()
        self.assertIs(self.root.errors[0][0], ValueError)


class TurnWithoutHandlerTests(AdapterCase):
    def test_turns_without_on_turn_are_ignored(self):
        self.adapter.on_turn = None
        self.open_picker()
        self.presenter.queue = [("turn", 1), ("cancel", None)]
        self.adapter.pump()
        self.assertEqual(self.events, ["cancel"])


class LabelTests(AdapterCase):
    def labels(self):
        return self.presenter.labels

    def test_labels_come_from_the_snapshot_and_the_delivered_facts(self):
        snapshot = self.open_picker()
        ids = [item["id"] for item in snapshot["items"]]
        self.assertEqual({label.app for label in self.labels().values()}, {"Chrome"})
        self.adapter.set_window_facts({ids[0]: {"file_description": "Google Chrome", "monitor": "Display A"}})
        self.assertEqual(self.labels()[ids[0]].app, "Google Chrome")
        self.assertEqual(self.labels()[ids[0]].title, snapshot["items"][0]["title"])
        self.assertEqual(self.labels()[ids[0]].desc, "chrome.exe", "the process name, never its path")

    def test_other_windows_of_an_answered_exe_get_its_name_until_their_own_facts_arrive(self):
        snapshot = self.open_picker()
        ids = [item["id"] for item in snapshot["items"]]
        self.adapter.set_window_facts({ids[0]: {"file_description": "Google Chrome"}})
        self.assertEqual([self.labels()[i].app for i in ids], ["Google Chrome"] * 3)

    def test_facts_while_hidden_are_kept_for_the_next_open(self):
        self.adapter.set_window_facts({"another-window": {"file_description": "Google Chrome"}})
        self.assertNotIn("set_labels", self.names())
        snapshot = self.open_picker()
        self.assertEqual(self.labels()[snapshot["items"][0]["id"]].app, "Chrome")
        self.adapter.hide()
        self.adapter.set_window_facts({snapshot["items"][0]["id"]: {"package_name": "Chrome Beta"}})
        self.adapter.show(self.adapter.snapshot())
        self.assertEqual(self.labels()[snapshot["items"][0]["id"]].app, "Chrome Beta")

    def test_duplicates_are_disambiguated_per_snapshot(self):
        for hwnd in (2, 3):
            self.native.windows[hwnd]["title"] = "Calendar"
        snapshot = self.open_picker()
        by_hwnd = {item["hwnd"]: item["id"] for item in snapshot["items"]}
        self.adapter.set_window_facts({by_hwnd[2]: {"profile": "Profile A"}, by_hwnd[3]: {"profile": "Profile B"}})
        self.assertTrue(self.labels()[by_hwnd[2]].desc.endswith(SEP + "Profile A"))
        self.assertTrue(self.labels()[by_hwnd[3]].desc.endswith(SEP + "Profile B"))

    def test_meet_and_minimized_facts_reach_the_rules(self):
        self.native.windows[2]["minimized"] = True
        snapshot = self.open_picker()
        by_hwnd = {item["hwnd"]: item["id"] for item in snapshot["items"]}
        self.adapter.set_window_facts({by_hwnd[3]: {"audible": True}})
        self.assertEqual(self.labels()[by_hwnd[3]].desc, "In a call")
        self.assertTrue(self.labels()[by_hwnd[2]].desc.endswith(SEP + "Minimized"))

    def test_a_reopened_picker_forgets_the_last_snapshots_meet_answer(self):
        snapshot = self.open_picker()
        meet = snapshot["items"][1]["id"]
        self.adapter.set_window_facts({meet: {"file_description": "Google Chrome", "audible": True}})
        self.assertEqual(self.labels()[meet].desc, "In a call")
        self.assertTrue(self.adapter.cancel(snapshot["origin"]))
        del self.log[:]
        self.open_picker()                                 # the runtime has not pruned its copy yet
        self.assertEqual(self.names().count("set_labels"), 1)
        self.assertEqual(self.labels()[meet].desc, "chrome.exe", "not answered for this snapshot yet")
        self.assertEqual(self.labels()[meet].app, "Google Chrome", "every other fact is kept")
        self.adapter.set_window_facts({meet: {"file_description": "Google Chrome", "audible": True}})
        self.assertEqual(self.labels()[meet].desc, "In a call", "this snapshot's own answer")

    def test_a_closed_window_is_marked_when_the_poll_finds_it_gone(self):
        snapshot = self.open_picker()
        gone = snapshot["items"][2]
        del self.native.windows[gone["hwnd"]]
        del self.log[:]
        self.adapter._poll()
        self.assertEqual(self.labels()[gone["id"]].desc, CLOSED)
        self.assertEqual(self.names()[:2], ["highlight", "set_labels"])
        self.assertEqual(self.events, ["closed"])
        self.assertNotEqual(self.labels()[snapshot["items"][0]["id"]].desc, CLOSED)

    def test_a_closed_window_found_while_turning_is_marked_too(self):
        snapshot = self.open_picker()
        gone = snapshot["items"][0]
        del self.native.windows[gone["hwnd"]]
        self.adapter.highlight(2)
        self.assertEqual(self.labels()[gone["id"]].desc, CLOSED)
        del self.log[:]
        self.adapter.highlight(1)
        self.assertEqual(self.names(), ["highlight"], "no label work on an ordinary detent")

    def test_a_failing_label_module_never_breaks_the_picker(self):
        with patch.object(w, "_window_labels", Mock(side_effect=ImportError("no window_labels"))), \
                self.assertLogs(w._log.name, "WARNING") as logs:
            self.open_picker()
            self.adapter.set_window_facts({})
        self.assertTrue(self.presenter.visible)
        self.assertEqual(len(logs.records), 1, "logged once")
        self.assertNotIn("Window", logs.output[0], "no title in the log")

    def test_a_raising_rule_falls_back_to_a_plain_label(self):
        broken = SimpleNamespace(**vars(LABELS))
        broken.label_for = Mock(side_effect=ValueError("rule bug"))
        broken.disambiguate = Mock(side_effect=ValueError("rule bug"))
        with patch.object(w, "_window_labels", lambda: broken):
            snapshot = self.open_picker()
        label = self.presenter.labels[snapshot["items"][0]["id"]]
        self.assertEqual((label.app, label.title), ("Chrome", snapshot["items"][0]["title"]))


@unittest.skipUnless(HAS_LABELS, "window_labels not delivered yet")
class RealLabelModuleTests(AdapterCase):
    def setUp(self):
        super().setUp()
        from control_center import window_labels
        patcher = patch.object(w, "_window_labels", lambda: window_labels)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_real_rules_label_the_snapshot_and_mark_closed_windows(self):
        from control_center import window_labels
        snapshot = self.open_picker()
        labels = self.presenter.labels
        self.assertEqual(set(labels), {item["id"] for item in snapshot["items"]})
        self.assertTrue(all(isinstance(label, window_labels.Label) for label in labels.values()))
        gone = snapshot["items"][2]
        del self.native.windows[gone["hwnd"]]
        self.adapter._poll()
        self.assertEqual(self.presenter.labels[gone["id"]].desc, CLOSED)

    def test_a_meet_reads_meeting_until_this_snapshots_check_answers(self):
        self.native.windows[2]["title"] = "Meet - abc-defg-hij - Google Chrome"    # synthetic
        snapshot = self.open_picker()
        meet = next(item["id"] for item in snapshot["items"] if item["hwnd"] == 2)
        self.adapter.set_window_facts({meet: {"file_description": "Google Chrome", "audible": True}})
        self.assertTrue(self.presenter.labels[meet].desc.startswith("In a call"))
        self.adapter.cancel(snapshot["origin"])
        self.open_picker()                                 # the call has ended; no check answered yet
        self.assertTrue(self.presenter.labels[meet].desc.startswith("Meeting"), self.presenter.labels[meet].desc)


class BackgroundAndPrewarmTests(AdapterCase):
    def test_the_switcher_background_reaches_the_presenter(self):
        self.adapter.set_picker_background("none")
        self.adapter.set_picker_background("glass")
        self.adapter.set_picker_background("blur")
        self.assertEqual(self.presenter.backgrounds, ["none", "glass", "glass"])
        self.assertEqual(self.adapter.picker_background, "glass")
        self.presenter.set_background = Mock(side_effect=RuntimeError("presenter gone"))
        self.adapter.set_picker_background("none")        # presentation only: never raises
        self.adapter.close()
        self.adapter.set_picker_background("glass")       # after close: ignored
        self.adapter.set_window_facts({})

    def test_prewarm_items_are_the_eligible_windows_without_titles(self):
        items = self.adapter.prewarm_items()
        self.assertEqual([item["hwnd"] for item in items], [1, 2, 3])
        self.assertTrue(all(set(item) == {"id", "hwnd", "pid", "path", "app", "class_name"} for item in items))
        self.assertEqual([entry for entry in self.log if entry[0] == "focus"], [], "read-only")


class MinimalPresenterTests(AdapterCase):
    presenter_class = MinimalPresenter

    def test_a_presenter_with_only_the_old_protocol_still_works(self):
        snapshot = self.open_picker()
        self.adapter.pump()
        self.adapter.set_window_facts({snapshot["items"][0]["id"]: {"file_description": "Google Chrome"}})
        self.adapter.set_picker_background("none")
        self.assertTrue(self.adapter.activate(snapshot["items"][1]))
        self.assertFalse(self.presenter.visible)


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 50.0, []

    def perf_counter(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class NativeFocusTests(unittest.TestCase):
    """NativeWindows.focus with a stand-in user32 (Mock: nothing reaches Windows) and a fake
    clock: the verify waits for an activation another thread completes asynchronously."""

    OWN_PID = 4242

    def native(self, foregrounds, iconic=False, pids=None):
        native = object.__new__(w.NativeWindows)
        native.u = Mock()
        native.own_pid = self.OWN_PID
        owners = dict(pids or {})                              # hwnd -> pid; this process by default

        def owner(hwnd, ref):
            ref._obj.value = owners.get(hwnd, self.OWN_PID)
            return 1
        native.u.GetWindowThreadProcessId.side_effect = owner
        native.u.GetAncestor.side_effect = lambda hwnd, flag: hwnd
        native.u.IsIconic.return_value = iconic
        native.u.SetForegroundWindow.return_value = 0         # its return value is never trusted
        sequence = list(foregrounds)
        native.u.GetForegroundWindow.side_effect = lambda: sequence.pop(0) if len(sequence) > 1 else sequence[0]
        native.last_focus = None
        self.clock = FakeClock()
        patcher = patch.object(w, "time", SimpleNamespace(perf_counter=self.clock.perf_counter,
                                                          sleep=self.clock.sleep, monotonic=time.monotonic))
        patcher.start()
        self.addCleanup(patcher.stop)
        return native

    def test_a_window_that_is_already_the_foreground_returns_at_the_first_check(self):
        native = self.native([0x5001])
        self.assertTrue(native.focus(0x5001))
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(native.last_focus, (True, 0.0, 1))

    def test_a_cross_thread_activation_is_awaited(self):
        # NULL while the carousel thread has not read its queue yet, then the thread's previously
        # active window, then the host.
        native = self.native([0, 0, 0x7777, 0x5001])
        self.assertTrue(native.focus(0x5001))
        self.assertEqual(self.clock.sleeps, [w.FOCUS_POLL_SECONDS] * 3)
        self.assertEqual(native.last_focus, (True, round(3 * w.FOCUS_POLL_SECONDS * 1000, 1), 4))

    def test_a_denied_request_gives_up_after_the_bound_without_spinning(self):
        native = self.native([0x3333])                         # the origin keeps the foreground
        self.assertFalse(native.focus(0x5001))
        self.assertTrue(self.clock.sleeps)
        self.assertTrue(all(seconds == w.FOCUS_POLL_SECONDS for seconds in self.clock.sleeps), "never a spin")
        self.assertGreaterEqual(sum(self.clock.sleeps), w.FOCUS_VERIFY_SECONDS - 1e-9)
        self.assertLess(sum(self.clock.sleeps), w.FOCUS_VERIFY_SECONDS + w.FOCUS_POLL_SECONDS + 1e-9)
        granted, ms, checks = native.last_focus
        self.assertFalse(granted)
        self.assertEqual(checks, len(self.clock.sleeps) + 1)
        native.u.SetForegroundWindow.assert_called_once_with(0x5001)

    def test_the_bounds(self):
        self.assertTrue(0.002 <= w.FOCUS_POLL_SECONDS <= 0.005)
        self.assertTrue(0.15 <= w.FOCUS_VERIFY_SECONDS <= 0.3)
        self.assertTrue(0.06 <= w.FOCUS_VERIFY_OTHER_SECONDS <= 0.1)

    def test_a_switch_or_cancel_target_of_another_process_gets_the_short_verify(self):
        # Review finding: every Switch and Cancel used to wait up to 250 ms on a hung target or
        # one that activates an owned dialog (GA_ROOT != target); v5 checked once.
        native = self.native([0x3333], pids={0x2002: 999})
        self.assertFalse(native.focus(0x2002, restore=True))
        self.assertTrue(all(seconds == w.FOCUS_POLL_SECONDS for seconds in self.clock.sleeps), "never a spin")
        self.assertGreaterEqual(sum(self.clock.sleeps), w.FOCUS_VERIFY_OTHER_SECONDS - 1e-9)
        self.assertLess(sum(self.clock.sleeps), w.FOCUS_VERIFY_OTHER_SECONDS + w.FOCUS_POLL_SECONDS + 1e-9)
        self.assertFalse(native.last_focus[0])
        # a slow but live target is still awaited (NULL first, then the target)
        native = self.native([0, 0, 0x2002], pids={0x2002: 999})
        self.assertTrue(native.focus(0x2002))
        self.assertEqual(native.last_focus, (True, round(2 * w.FOCUS_POLL_SECONDS * 1000, 1), 3))
        # the carousel host (this process) keeps the long verify
        native = self.native([0x3333])
        self.assertFalse(native.focus(0x5001))
        self.assertGreaterEqual(sum(self.clock.sleeps), w.FOCUS_VERIFY_SECONDS - 1e-9)

    def test_restore_shows_an_iconic_window_before_asking_for_the_foreground(self):
        native = self.native([0x2002], iconic=True)
        self.assertTrue(native.focus(0x2002, restore=True))
        names = [entry[0] for entry in native.u.method_calls]
        self.assertLess(names.index("ShowWindowAsync"), names.index("SetForegroundWindow"))
        native.u.ShowWindowAsync.assert_called_once_with(0x2002, 9)


class RealPresenterSeamTests(AdapterCase):
    """The real CarouselPresenter (the presenter tests' fake backend and capture, its engine
    stepped inline on this thread) behind the real WindowsAdapter: open and focus, labels,
    presenter input -> pump -> the controller's paths, the switch and cancel exits releasing
    the thumbnails and toasting, closed windows marked, and no toast for a hidden picker."""

    def setUp(self):
        from control_center import carousel, carousel_render
        from test_carousel_presenter import Clock, FakeBackend, FakeCapture
        self.c, self.R = carousel, carousel_render
        self.FakeBackend, self.FakeCapture = FakeBackend, FakeCapture
        self.clock = Clock()
        self.backend = FakeBackend()                 # a 1280 x 720 monitor: k = 1
        self.capture = FakeCapture(self.backend)

        def factory(root, native, on_cancel):
            return carousel.CarouselPresenter(root, native, on_cancel, backend=self.backend, capture=self.capture,
                                              clock=self.clock, inline=True)
        self.presenter_class = factory
        super().setUp()
        self.native.windows[self.backend.hwnd_host] = record(self.backend.hwnd_host, pid=FakeNative.own_pid)

    def step(self, seconds=0.0, dt=1 / 60):
        end = self.clock.t + seconds
        self.presenter._step_inline()
        while self.clock.t < end - 1e-9:
            self.clock.t = min(end, self.clock.t + dt)
            self.presenter._step_inline()

    def open_carousel(self):
        snapshot = self.open_picker()
        self.step()
        if self.capture.jobs:
            self.capture.complete()                  # the glass capture
        self.step(0.4)
        return snapshot

    def registered(self):
        return set(self.backend.thumbs.values())

    def test_open_focuses_the_host_and_the_labels_reach_the_engine(self):
        snapshot = self.open_carousel()
        self.assertIsInstance(self.presenter, self.c.CarouselPresenter)
        self.assertIn(("focus", self.backend.hwnd_host, False), self.log)
        self.assertIn("host", self.backend.visible)
        self.assertEqual(self.presenter.rect, (70, 92, 1140, 560), "the stage's card area (ui._carousel_open)")
        self.assertEqual(set(self.presenter._engine._labels), {item["id"] for item in snapshot["items"]})
        self.assertEqual(self.registered(), {1, 2, 3})

    def test_enter_switches_through_pump_then_the_exit_releases_without_a_toast_of_its_own(self):
        snapshot = self.open_carousel()
        self.backend.on_input(self.c.IN_KEY, self.c.VK_RETURN, 0)
        self.assertEqual(self.events, [], "only queued on the presenter's thread")
        self.adapter.pump()
        self.assertEqual(self.events, ["switch"])
        item = snapshot["items"][snapshot["index"]]
        self.assertTrue(self.adapter.activate(item))
        self.assertFalse(self.presenter.visible)
        self.step(0.45)
        self.assertEqual(self.registered(), set(), "released by the end of the exit")
        self.assertIsNone(self.presenter._engine.toast, "K3 raises toast.switch through toast() at +360")
        self.assertIn({"kind": "closed", "surface": "picker", "reason": "switch"}, self.adapter.take_events())
        self.adapter.toast("Chrome" + SEP + item["title"], exit=True)
        self.step()
        self.assertEqual(self.presenter._engine.toast.text, "Chrome" + SEP + item["title"])

    def test_escape_cancels_through_pump_then_the_exit_without_a_toast(self):
        snapshot = self.open_carousel()
        self.backend.on_input(self.c.IN_KEY, self.c.VK_ESCAPE, 0)
        self.adapter.pump()
        self.assertEqual(self.events, ["cancel"])
        self.assertTrue(self.adapter.cancel(snapshot["origin"]))
        self.step(0.45)
        self.assertEqual(self.registered(), set())
        self.assertIsNone(self.presenter._engine.toast)
        self.assertIn({"kind": "cancel_result", "restored": True, "completed": False}, self.adapter.take_events())

    def test_arrow_keys_become_turns_for_on_turn_only(self):
        self.open_carousel()
        self.backend.on_input(self.c.IN_KEY, self.c.VK_RIGHT, 0)
        self.backend.on_input(self.c.IN_KEY, self.c.VK_LEFT, 0)
        self.adapter.pump()
        self.assertEqual(self.events, [("turn", 1), ("turn", -1)])

    def test_a_closed_window_is_marked_and_released(self):
        snapshot = self.open_carousel()
        gone = snapshot["items"][2]
        del self.native.windows[gone["hwnd"]]
        self.adapter._poll()
        self.step(0.1)
        self.assertEqual(self.presenter._engine._labels[gone["id"]].desc, CLOSED)
        self.assertNotIn(gone["hwnd"], self.registered())
        self.assertEqual(self.events, ["closed"])

    def test_a_cancel_after_a_focus_loss_hide_shows_no_toast(self):
        snapshot = self.open_carousel()
        self.adapter.hide()
        self.step()
        mark = len(self.backend.calls)
        self.assertTrue(self.adapter.cancel(snapshot["origin"]))
        self.step(0.5)
        self.assertIsNone(self.presenter._engine.toast)
        self.assertNotIn("toast_alloc", [entry[0] for entry in self.backend.calls[mark:]])

    def test_the_floating_knob_is_suppressed_from_open_through_the_exit_with_either_background(self):
        # Section 11: reason 'carousel' holds for the whole open -> exit, with either background
        # and wherever the knob is, and lifts once the exit has torn the carousel down.
        for background in ("glass", "none"):
            with self.subTest(background=background):
                sent = []
                screen = SimpleNamespace(mode="home", index=1)
                app = bare_app(SimpleNamespace(windows=self.adapter, controller=SimpleNamespace(screen=screen)))
                app.overlay = SimpleNamespace(rect=(24, 479, 434, 434),       # far from the pane
                                              set_suppressed=lambda reason, on: sent.append((reason, on)))

                def held():
                    app._update_suppression(True)
                    return app._suppressed.get("carousel")
                self.assertFalse(held())
                self.adapter.set_picker_background(background)
                snapshot = self.open_picker()
                screen.mode = "windows"
                self.assertTrue(held(), "from the show() handshake")
                self.step()
                if self.capture.jobs:
                    self.capture.complete()
                self.step(0.4)
                self.assertTrue(held())
                item = snapshot["items"][snapshot["index"]]
                self.assertTrue(self.adapter.activate(item))
                screen.mode = "home"                                           # Windows mode ended
                self.step(0.1)
                self.assertTrue(held(), "through the exit animation")
                self.step(0.15)
                self.assertTrue(held())
                self.step(0.2)
                self.assertIsNone(self.presenter.rect)
                self.assertFalse(held(), "lifted once the exit tore the carousel down")
                self.assertEqual([entry for entry in sent if entry[0] == "carousel"],
                                 [("carousel", False), ("carousel", True), ("carousel", False)])
                self.assertNotIn(("picker", True), sent)
                self.step(2.0)

    def test_the_plain_host_offers_only_glass(self):
        self.assertEqual(self.adapter.picker_backgrounds, ("glass", "none"))
        backend = self.FakeBackend(host_mode=self.c.HOST_PLAIN)
        plain = self.c.CarouselPresenter(None, None, lambda: None, backend=backend,
                                         capture=self.FakeCapture(backend), clock=self.clock, inline=True)
        self.addCleanup(plain.close)
        previous, self.adapter.overlay = self.adapter.overlay, plain
        try:
            self.assertEqual(self.adapter.picker_backgrounds, ("glass",))
        finally:
            self.adapter.overlay = previous


class V7RuntimeInterfaceTests(AdapterCase):
    """The v7 runtime's view of the adapter (K3 9.9; K4 2.3): snap, half_rect, close_pair,
    cancel(origin, complete=, reason=), foreground_hwnd, take_events and the toast service."""

    def events_of(self, kind):
        return [event for event in self.adapter.take_events() if event.get("kind") == kind]

    def test_open_and_hide_post_opened_and_closed(self):
        self.open_picker()
        self.assertEqual(self.adapter.take_events(), [{"kind": "opened", "surface": "picker"}])
        self.adapter.hide(reason="focus_lost")
        self.adapter.hide()
        self.assertEqual(self.adapter.take_events(), [{"kind": "closed", "surface": "picker", "reason": "focus_lost"}])

    def test_snap_posts_the_item_identity_and_the_work_area_half(self):
        snapshot = self.open_picker()
        effect = {"kind": "windows_snap", "t0": 5.0, "index": 1, "side": "right", "target_rect": None,
                  "place_at_ms": 360, "item": {"id": snapshot["items"][1]["id"], "hwnd": 2, "pid": 20}}
        self.assertTrue(self.adapter.snap(effect))
        call = [entry for entry in self.log if entry[0] == "snap"][-1]
        self.assertEqual(call[1:4], ("right", 1, (960, 0, 1920, 1040)))
        self.assertEqual(call[4]["class_name"], "Chrome_WidgetWin_1")
        self.assertEqual(call[4]["hwnd"], snapshot["items"][1]["hwnd"])
        self.assertEqual(self.adapter.half_rect("left"), (0, 0, 960, 1040))
        self.assertIsNone(self.adapter.half_rect("up"))

    def test_snap_results_become_k4_events(self):
        self.open_picker()
        self.adapter.take_events()
        self.presenter.queue = [("snap_result", ("left", "accepted")), ("snap_result", ("left", "ok")),
                                ("snap_result", "bad")]
        self.adapter.pump()
        self.assertEqual(self.adapter.take_events(), [{"kind": "snap_result", "side": "left", "outcome": "accepted"},
                                                      {"kind": "snap_result", "side": "left", "outcome": "ok"}])
        self.assertEqual(self.events, [], "results are not input")

    def test_a_snap_without_an_open_picker_or_presenter_support_is_rejected(self):
        self.assertFalse(self.adapter.snap({"side": "left", "index": 0}))
        self.assertEqual(self.events_of("snap_result"), [{"kind": "snap_result", "side": "left",
                                                          "outcome": "move_rejected"}])

    def test_back_with_one_side_completes_first_then_focuses_then_fades(self):
        snapshot = self.open_picker()
        self.adapter.take_events()
        del self.log[:]
        self.assertIsNone(self.adapter.cancel(snapshot["origin"], complete="right"))
        self.assertEqual(self.names(), ["complete_one_side"], "no focus, exit or hide before the completion")
        origin = self.log[0][1]
        self.assertEqual((origin["hwnd"], origin["class_name"]), (1, "Chrome_WidgetWin_1"))
        self.assertEqual(self.log[0][2:], ("right", (960, 0, 1920, 1040)))
        self.presenter.queue = [("switch", None), ("cancel", None)]
        self.adapter.pump()
        self.assertEqual(self.events, [], "the closing picker takes no input")
        self.presenter.queue = [("complete_result", (77, True))]
        self.adapter.pump()
        self.assertEqual(self.names()[1:], ["focus", "play_cancel_exit", "hide"])
        self.assertEqual(self.events_of("cancel_result"), [{"kind": "cancel_result", "restored": True, "completed": True}])

    def test_lock_and_sleep_hide_at_once_and_never_restore_focus(self):
        for reason in ("lock", "sleep"):
            with self.subTest(reason=reason):
                snapshot = self.open_picker()
                del self.log[:]
                self.adapter.cancel(snapshot["origin"], complete="left", reason=reason)
                self.assertEqual(self.names(), ["hide", "complete_one_side"])
                self.presenter.queue = [("complete_result", (77, False))]
                self.adapter.pump()
                self.assertNotIn("focus", self.names())
                self.assertEqual(self.events_of("cancel_result")[-1], {"kind": "cancel_result", "restored": False,
                                                                       "completed": False})

    def test_idle_restores_focus_first_then_hides_and_completes(self):
        snapshot = self.open_picker()
        del self.log[:]
        self.adapter.cancel(snapshot["origin"], complete="left", reason="idle")
        self.assertEqual(self.names(), ["focus", "hide", "complete_one_side"])

    def test_the_runtimes_reasonless_idle_cancel_hides_at_once(self):
        """WP7b-R8 (K4 9.7, 15: idle is instant): the runtime calls cancel(origin, complete=)
        without a reason (K3's windows_cancel has none). 60 s after the last knob-driven call
        the adapter takes it as K3's idle close: no exit animation, no picker left up during
        the completion. A Back soon after input still plays the exit."""
        for complete, expected in ((None, ["focus", "hide"]), ("left", ["focus", "hide", "complete_one_side"])):
            with self.subTest(complete=complete):
                snapshot = self.open_picker()
                self.adapter.highlight(1)
                self.adapter._last_input -= w.IDLE_INFER_SECONDS + 0.5      # 60 s without knob input
                del self.log[:]
                self.adapter.cancel(snapshot["origin"], complete=complete)   # exactly as runtime.py calls it
                self.assertEqual(self.names(), expected)
                self.assertNotIn("play_cancel_exit", self.names())
                self.assertFalse(self.adapter._visible, "hidden in the same call (instant)")
                if complete:
                    self.presenter.queue = [("complete_result", (77, True))]
                    self.adapter.pump()
                    self.assertNotIn("play_cancel_exit", self.names())
                self.assertEqual(self.events_of("cancel_result")[-1]["kind"], "cancel_result")
        snapshot = self.open_picker()
        self.adapter.highlight(2)                                             # a Back right after a turn
        del self.log[:]
        self.adapter.cancel(snapshot["origin"])
        self.assertEqual(self.names(), ["focus", "play_cancel_exit", "hide"])

    def test_a_lost_foreground_on_a_locked_desktop_closes_as_lock(self):
        self.open_picker()
        self.adapter.take_events()
        self.native.input_desktop_is_default = lambda: False
        self.native.foreground_hwnd = 3
        self.adapter._check_focus_lost()
        self.assertEqual(self.adapter.take_events(), [{"kind": "closed", "surface": "picker", "reason": "lock"},
                                                      {"kind": "system", "what": "lock"}])
        self.assertNotIn("focus_lost", self.events)
        snapshot = self.adapter._snapshot
        del self.log[:]
        self.adapter.cancel(snapshot["origin"], complete="left")          # the controller's close_overlay("lock")
        self.assertNotIn("focus", self.names())

    def test_the_completion_bound_closes_without_a_result(self):
        snapshot = self.open_picker()
        self.adapter.cancel(snapshot["origin"], complete="left")
        self.adapter._cancel_job["started"] -= w.CANCEL_RESULT_BACKSTOP_SECONDS
        self.adapter.pump()
        self.assertEqual(self.events_of("cancel_result"), [{"kind": "cancel_result", "restored": True,
                                                            "completed": False}])

    def test_close_pair_raises_the_first_focuses_the_last_then_fades(self):
        snapshot = self.open_picker()
        left, right = snapshot["items"][1], snapshot["items"][2]
        del self.log[:]
        self.assertTrue(self.adapter.close_pair(left["id"], right["id"], "right"))
        self.assertEqual(self.log, [("raise_window", left["hwnd"]), ("focus", right["hwnd"], False),
                                    ("play_pair_exit",), ("hide",)])
        self.assertIn({"kind": "closed", "surface": "picker", "reason": "pair"}, self.adapter.take_events())

    def test_a_display_close_from_the_presenter(self):
        self.open_picker()
        self.adapter.take_events()
        self.presenter.queue = [("closed", "display")]
        self.adapter.pump()
        self.assertFalse(self.adapter._visible)
        self.assertEqual(self.adapter.take_events(), [{"kind": "closed", "surface": "picker", "reason": "display"}])

    def test_foreground_hwnd(self):
        self.assertEqual(self.adapter.foreground_hwnd(), 1)
        self.native.foreground_hwnd = 0
        self.assertIsNone(self.adapter.foreground_hwnd())

    def test_toasts_never_show_over_an_open_overlay(self):
        surfaces = set()
        self.adapter.set_overlay_registry(lambda: surfaces)
        self.assertTrue(self.adapter.toast("Playing Promises"))
        surfaces.add("explorer")
        self.assertFalse(self.adapter.toast("Playing Promises"))
        self.assertFalse(self.adapter.toast("Playing Promises", exit=True), "another overlay is open")
        surfaces.clear()
        self.open_picker()
        self.assertFalse(self.adapter.toast("Queued"), "over the open picker")
        self.adapter.hide()
        surfaces.add("picker")                                        # the registry still lists the closing picker
        self.assertTrue(self.adapter.toast("Slack left · Chrome right", exit=True), "the picker's own exit toast")
        self.assertEqual([entry for entry in self.log if entry[0] == "toast"],
                         [("toast", "Playing Promises", False), ("toast", "Slack left · Chrome right", True)])

    def test_an_overlay_that_opens_ends_a_showing_toast(self):
        surfaces = set()
        self.adapter.set_overlay_registry(lambda: surfaces)
        self.adapter.pump()
        self.assertNotIn("end_toast", self.names())
        surfaces.add("upnext")
        self.adapter.pump()
        self.adapter.pump()
        self.assertEqual(self.names().count("end_toast"), 1)

    def test_labels_carry_the_display_app_name_into_the_snapshot_items(self):
        snapshot = self.adapter.snapshot()
        self.adapter.set_window_facts({snapshot["items"][0]["id"]: {"file_description": "Google Chrome"}})
        self.adapter.show(snapshot)
        self.assertEqual(snapshot["items"][0]["label_app"], "Google Chrome")
        self.assertEqual(snapshot["items"][1]["label_app"], "Google Chrome", "the answered exe lends its name")

    def test_highlight_forwards_the_knobs_end_bump(self):
        self.open_picker()
        self.adapter.highlight(1, bump=1)
        self.adapter.highlight(1)
        self.assertEqual([entry for entry in self.log if entry[0] == "highlight"], [("highlight", 1, 1), ("highlight", 1)])

    def test_the_reduced_motion_setting_reaches_the_presenter(self):
        self.adapter.set_reduced_motion(True)
        self.assertIn(("reduced_motion", True), self.log)

    def test_a_knob_touch_warms_the_gpu_chrome_and_the_chrome_mode_passes_through(self):
        """CAROUSEL.md 12.4: note_touch() posts the GPU chrome's warm-up; set_chrome_mode() is the
        support switch; both optional on the presenter (the v6 protocol has neither)."""
        self.assertFalse(self.adapter.note_touch())                   # the fake presenter has no GPU chrome
        self.assertIsNone(self.adapter.set_chrome_mode("cpu"))
        self.presenter.note_touch = lambda: self.log.append(("note_touch",)) or True
        self.presenter.set_chrome_mode = lambda mode: self.log.append(("chrome_mode", mode)) or mode
        self.assertTrue(self.adapter.note_touch())
        self.assertEqual(self.adapter.set_chrome_mode("cpu"), "cpu")
        self.assertIn(("note_touch",), self.log)
        self.assertIn(("chrome_mode", "cpu"), self.log)

        def broken():
            raise OSError("gone")
        self.presenter.note_touch = broken
        self.assertFalse(self.adapter.note_touch())


class HelperTests(unittest.TestCase):
    def test_browser_profile_comes_from_the_labels_module(self):
        with patch.object(w, "_window_labels", lambda: LABELS):
            self.assertEqual(w.browser_profile("Profile A - Chrome"), "Profile A")
            self.assertIsNone(w.browser_profile("Slack"))
        with patch.object(w, "_window_labels", Mock(side_effect=ImportError("not delivered"))):
            self.assertIsNone(w.browser_profile("Profile A - Chrome"))

    @unittest.skipUnless(HAS_LABELS, "window_labels not delivered yet")
    def test_browser_profile_with_the_real_rules(self):
        self.assertEqual(w.browser_profile("Profile A - Chrome"), "Profile A")
        for value in (None, "", "@{chrome.exe,-1}", "Slack", 7):
            self.assertIsNone(w.browser_profile(value), value)

    @unittest.skipUnless(HAS_LABELS, "window_labels not delivered yet")
    def test_only_a_browsers_meet_page_is_a_call(self):
        chrome = {"path": r"C:\Apps\chrome.exe", "app": "chrome", "class_name": "Chrome_WidgetWin_1"}
        self.assertTrue(w.meet_call(dict(chrome, title="Meet - abc-defg-hij - Google Chrome")))
        self.assertFalse(w.meet_call(dict(chrome, title="Meeting notes - Google Chrome")))
        self.assertFalse(w.meet_call({"path": r"C:\Apps\memo.exe", "app": "memo",
                                      "title": "Meet - abc-defg-hij - Memo"}))
        self.assertFalse(w.meet_call(dict(chrome, title=None)))

    def test_window_exe_is_a_name_never_a_path(self):
        self.assertEqual(w.window_exe({"path": SECRET_PATH, "app": "chrome"}), "chrome.exe")
        self.assertEqual(w.window_exe({"path": None, "app": "ApplicationFrameHost"}), "ApplicationFrameHost.exe")
        self.assertEqual(w.window_exe({}), "")

    def test_picker_icons_prefer_the_master_then_the_hires_copy_then_the_32px_icon(self):
        small = {k: Image.new("RGBA", (32, 32)) for k in ("a", "b", "c")}
        small["d"] = None
        master, hires = Image.new("RGBA", (128, 128)), Image.new("RGBA", (128, 128))
        facts = {"a": {"icon": master}, "b": {"profile": "x"}, "e": {"icon": master}}
        icons = w.picker_icons(small, facts, lambda item_id: hires if item_id == "b" else None)
        self.assertIs(icons["a"], master)
        self.assertIs(icons["b"], hires)
        self.assertIs(icons["c"], small["c"])
        self.assertIsNone(icons["d"])
        self.assertIs(icons["e"], master, "a UWP window's package logo without a 32 px icon")
        self.assertEqual(w.picker_icons(small, None, Mock(side_effect=OSError())), small)


# ----------------------------------------------------------------------------- IconWorker
def solid(colour, size=32):
    return Image.new("RGBA", (size, size), colour + (255,))


class Api:
    """IconApi stand-in: every window's own icon is ``source``; the exe's jumbo icon ``big``."""
    def __init__(self, source=None, reference=None, big=None):
        self.source, self.reference, self.big = source, reference, big
        self.hires_calls = []

    def co_initialize(self): return False
    def co_uninitialize(self): pass
    def window_icon(self, hwnd, kind): return 101 if self.source is not None and kind == w.ICON_BIG else 0
    def icon_image(self, handle): return self.source.copy()
    def class_icon(self, hwnd, index): return 0
    def file_icon(self, path): return 0
    def destroy_icon(self, handle): pass

    def hires_icon(self, path):
        self.hires_calls.append(path)
        return (self.big, self.reference) if self.big is not None else None


class NoHiresApi(Api):
    hires_icon = None


class Facts:
    """window_facts stand-in, recording calls in order (paths only in memory, never checked out)."""
    def __init__(self, **values):
        self.calls, self.values = [], values
        self.gate = values.get("gate")

    def _record(self, *call):
        self.calls.append(call)
        if self.gate is not None and call[0] == "version_strings" and len(self.calls) == 1:
            self.gate.wait(3)

    def version_strings(self, path):
        self._record("version_strings", path)
        return self.values.get("strings", {}).get(path, {})

    def window_property_store(self, hwnd):
        self._record("window_property_store", hwnd)
        return self.values.get("stores", {}).get(hwnd, {})

    def process_aumid(self, hwnd):
        self._record("process_aumid", hwnd)
        return self.values.get("aumids", {}).get(hwnd)

    def package_display_name(self, aumid):
        self._record("package_display_name", aumid)
        return self.values.get("package_names", {}).get(aumid)

    def package_logo(self, aumid, px=128):
        self._record("package_logo", aumid, px)
        return self.values.get("logos", {}).get(aumid)

    def relaunch_icon(self, resource, px=128):
        self._record("relaunch_icon", px)
        return self.values.get("relaunch")

    def monitor_friendly_name(self, hwnd):
        self._record("monitor_friendly_name", hwnd)
        return self.values.get("monitor")

    def audible_pids(self):
        self._record("audible_pids")
        return self.values.get("audible", set())

    def letter_tile(self, name, px, radius=0):
        self._record("letter_tile", name, px)
        return solid((30, 60, 90), px)


def item(index, path=r"C:\Apps\app.exe", app="app", title=None, **values):
    return dict(id=f"w{index}", hwnd=10 + index, pid=500 + index, path=path, app=app,
                title=title or f"Window {index}", class_name="Frame", **values)


class WorkerCase(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(w, "_window_labels", lambda: LABELS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def worker(self, api, facts=None, **options):
        worker = w.IconWorker(api_factory=lambda: api, facts=True, facts_api=facts, **options)
        self.addCleanup(worker.close, 2)
        return worker

    @staticmethod
    def collect(poll, count, timeout=3.0):
        found, until = [], time.monotonic() + timeout
        while len(found) < count and time.monotonic() < until:
            found.extend(poll())
            time.sleep(0.005)
        return found

    def facts_by_id(self, worker, count):
        merged = {}
        for item_id, facts in self.collect(worker.poll_facts, count):
            merged.setdefault(item_id, {}).update(facts)
        return merged

    def nothing_more(self, worker):
        worker.poll()                     # the snapshot's 32 px icons (always delivered before any fact)
        time.sleep(0.05)
        self.assertEqual((worker.poll(), worker.poll_facts()), ([], []))


class WorkerContractTests(WorkerCase):
    def test_the_default_worker_has_no_facts_channel(self):
        facts = Facts()
        worker = w.IconWorker(api_factory=lambda: Api(solid((200, 30, 30))), facts_api=facts)
        self.addCleanup(worker.close, 2)
        worker.request([item(0)])
        self.assertEqual(len(self.collect(worker.poll, 1)), 1)
        self.nothing_more(worker)
        self.assertEqual(facts.calls, [])
        worker.prewarm([item(0)])
        self.nothing_more(worker)
        self.assertEqual(facts.calls, [])

    def test_the_32px_icons_come_first_and_unchanged_then_the_facts(self):
        from control_center.artwork import attached_icon_payload, icon_payload
        source = solid((200, 30, 30), 48)
        worker = self.worker(NoHiresApi(source), Facts())
        worker.request([item(i) for i in range(3)])
        icons = self.collect(worker.poll, 3)
        self.assertEqual([result[0] for result in icons], ["w0", "w1", "w2"])
        for result in icons:
            self.assertEqual(len(result), 3)
            self.assertFalse(getattr(result, "hires", False))
            self.assertEqual(result[1].size, (32, 32))
            self.assertEqual(attached_icon_payload(result[1]), icon_payload(w.icon_thumbnail(source)))
        facts = self.facts_by_id(worker, 3)
        self.assertEqual(set(facts), {"w0", "w1", "w2"})
        self.nothing_more(worker)

    def test_facts_are_ordered_by_distance_from_the_entry_selection(self):
        facts = Facts()
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(i, path=fr"C:\Apps\app{i}.exe") for i in range(5)])
        self.facts_by_id(worker, 5)
        order = [call[1] for call in facts.calls if call[0] == "version_strings"]
        self.assertEqual(order, [fr"C:\Apps\app{i}.exe" for i in (1, 0, 2, 3, 4)])

    def test_prioritize_reorders_the_remaining_facts(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        facts = Facts(gate=gate)
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(i, path=fr"C:\Apps\app{i}.exe") for i in range(6)])
        until = time.monotonic() + 2
        while not facts.calls and time.monotonic() < until:
            time.sleep(0.005)                          # inside the first facts job (index 1)
        worker.prioritize(5)
        gate.set()
        self.facts_by_id(worker, 6)
        order = [call[1] for call in facts.calls if call[0] == "version_strings"]
        self.assertEqual(order, [fr"C:\Apps\app{i}.exe" for i in (1, 5, 4, 3, 2, 0)])

    def test_a_new_snapshot_drops_the_old_facts(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        facts = Facts(gate=gate)
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(0), item(1)])
        until = time.monotonic() + 2
        while not facts.calls and time.monotonic() < until:
            time.sleep(0.005)
        worker.request([dict(item(7), id="new")])
        gate.set()
        found = self.facts_by_id(worker, 1)
        self.assertEqual(set(found), {"new"})
        self.nothing_more(worker)

    def wait_inside_the_first_helper_call(self, facts):
        until = time.monotonic() + 2
        while not facts.calls and time.monotonic() < until:
            time.sleep(0.005)
        self.assertTrue(facts.calls, "the worker reached its first helper call")

    def test_a_running_facts_job_gives_way_to_a_new_snapshots_icons(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        facts = Facts(gate=gate)
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(0), item(1)])
        self.wait_inside_the_first_helper_call(facts)   # the facts job of index 1 (hwnd 11)
        worker.request([dict(item(7), id="new")])
        gate.set()
        self.assertEqual([result[0] for result in self.collect(worker.poll, 1)], ["new"])
        self.assertEqual(set(self.facts_by_id(worker, 1)), {"new"})
        self.nothing_more(worker)
        self.assertEqual([call[1] for call in facts.calls if call[0] == "window_property_store"], [17],
                         "the old job made no helper call after the new request")

    def test_a_prewarm_job_gives_way_to_a_snapshot_then_resumes(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        facts = Facts(gate=gate, strings={r"C:\Apps\app.exe": {"FileDescription": "Vendor Tool"}})
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.prewarm([item(0), item(1)])
        self.wait_inside_the_first_helper_call(facts)   # the prewarm of hwnd 10
        worker.request([item(5)])
        gate.set()
        found = self.facts_by_id(worker, 3)
        self.assertEqual(set(found), {"w0", "w1", "w5"})
        self.assertEqual(found["w5"]["icon_source"], "window")
        self.assertEqual(found["w0"], {"file_description": "Vendor Tool"}, "re-queued, then delivered")
        self.nothing_more(worker)
        self.assertEqual([call[1] for call in facts.calls if call[0] == "window_property_store"], [15, 10, 11],
                         "the snapshot first, then the prewarm where it stopped")

    def test_a_yielded_prewarm_of_a_replaced_list_is_not_requeued(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        facts = Facts(gate=gate, strings={r"C:\Apps\app.exe": {"FileDescription": "Vendor Tool"}})
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.prewarm([item(0)])
        self.wait_inside_the_first_helper_call(facts)
        worker.prewarm([item(3)])
        worker.request([item(5)])
        gate.set()
        self.assertEqual(set(self.facts_by_id(worker, 2)), {"w3", "w5"})
        self.nothing_more(worker)
        self.assertEqual([call[1] for call in facts.calls if call[0] == "window_property_store"], [15, 13])

    def test_facts_never_carry_a_path(self):
        facts = Facts(strings={SECRET_PATH: {"FileDescription": "Google Chrome", "ProductName": "Google Chrome"}},
                      stores={10: {"relaunch_display_name": "Profile A - Chrome", "relaunch_icon": SECRET_PATH}},
                      monitor="Display A")
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(0, path=SECRET_PATH, app="chrome")])
        found = self.facts_by_id(worker, 1)["w0"]
        self.assertEqual({key: found[key] for key in ("file_description", "product_name", "profile", "monitor")},
                         {"file_description": "Google Chrome", "product_name": "Google Chrome",
                          "profile": "Profile A", "monitor": "Display A"})
        text = json.dumps({key: value for key, value in found.items() if key != "icon"})
        self.assertNotIn("Secret Vendor", text)
        self.assertNotIn("aumid", found)

    def test_missing_helpers_leave_only_their_facts_out(self):
        worker = self.worker(NoHiresApi(solid((200, 30, 30), 48)), object())
        worker.request([item(0)])
        found = self.facts_by_id(worker, 1)["w0"]
        self.assertEqual(found["icon_source"], "window")
        self.assertEqual(found["icon"].size, (128, 128))

    def test_without_the_facts_module_the_ladder_still_runs(self):
        worker = w.IconWorker(api_factory=lambda: NoHiresApi(solid((200, 30, 30), 48)), facts=True)
        self.addCleanup(worker.close, 2)
        with patch.object(w, "_window_facts", Mock(side_effect=ImportError("not delivered"))):
            worker.request([item(0), item(1, app="ApplicationFrameHost", path="")])
            found = self.facts_by_id(worker, 2)
        self.assertEqual(found["w0"]["icon_source"], "window")
        self.assertEqual((found["w1"]["icon"], found["w1"]["icon_source"]), (None, None))

    def test_prewarm_delivers_label_facts_without_icons_and_warms_the_caches(self):
        facts = Facts(aumids={10: "Vendor.App_1!App"}, package_names={"Vendor.App_1!App": "Vendor App"},
                      logos={"Vendor.App_1!App": solid((10, 200, 10), 64)},
                      strings={r"C:\Apps\app.exe": {"FileDescription": "Vendor Tool"}})
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.prewarm([item(0), item(1)])
        found = self.facts_by_id(worker, 2)
        self.assertEqual(found["w0"], {"file_description": "Vendor Tool", "package_name": "Vendor App"})
        self.assertEqual(found["w1"], {"file_description": "Vendor Tool"})
        self.assertFalse([call for call in facts.calls if call[0] in ("letter_tile", "relaunch_icon")],
                         "no icon ladder before a snapshot")
        self.nothing_more(worker)
        worker.request([item(0)])
        found = self.facts_by_id(worker, 1)["w0"]
        self.assertEqual((found["package_name"], found["icon_source"]), ("Vendor App", "package"))
        names = [call[0] for call in facts.calls]
        self.assertEqual(names.count("package_display_name"), 1, "cached per AUMID")
        self.assertEqual(names.count("package_logo"), 1, "warmed by the prewarm, used by the ladder")

    def test_prewarm_skips_the_windows_of_the_current_snapshot(self):
        facts = Facts(strings={r"C:\Apps\app.exe": {"FileDescription": "Vendor Tool"}})
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(0)])
        worker.prewarm([item(0), item(1)])
        found = dict(self.collect(worker.poll_facts, 2))
        self.assertEqual(set(found), {"w0", "w1"})
        self.assertEqual(found["w0"]["icon_source"], "window", "w0's own facts job, not a prewarm")
        self.assertEqual(found["w1"], {"file_description": "Vendor Tool"})
        self.nothing_more(worker)
        self.assertEqual([call[1] for call in facts.calls if call[0] == "window_property_store"], [10, 11],
                         "w0 read once, by its own job")

    def test_a_failed_package_lookup_is_asked_again_by_the_next_snapshot(self):
        """A None from package_display_name/package_logo (shell:AppsFolder not ready at logon) is
        never pinned: window_facts retries after FAILURE_TTL_SECONDS, so the worker asks again."""
        facts = Facts(aumids={10: "Vendor.App_1!App"}, strings={r"C:\Apps\app.exe": {"FileDescription": "Vendor Tool"}})
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.prewarm([item(0)])
        self.assertNotIn("package_name", self.facts_by_id(worker, 1)["w0"])
        worker.request([item(0)])
        found = self.facts_by_id(worker, 1)["w0"]
        self.assertNotIn("package_name", found)
        self.assertEqual(found["icon_source"], "window")
        facts.values["package_names"] = {"Vendor.App_1!App": "Vendor App"}
        facts.values["logos"] = {"Vendor.App_1!App": solid((10, 200, 10), 64)}
        worker.request([item(0)])
        found = self.facts_by_id(worker, 1)["w0"]
        self.assertEqual((found["package_name"], found["icon_source"]), ("Vendor App", "package"))
        worker.request([item(0)])
        self.facts_by_id(worker, 1)
        names = [call[0] for call in facts.calls]
        self.assertEqual(names.count("package_display_name"), 3, "asked until it answered, then cached")
        self.assertEqual(names.count("package_logo"), 3, "asked until it answered, then cached")

    def test_relaunch_icons_are_read_again_so_a_changed_profile_picture_shows(self):
        """window_facts caches relaunch icons per file mtime; the worker keeps no copy of its own."""
        store = {10: {"relaunch_icon": r"C:\Profile\Profile.ico", "relaunch_display_name": "Profile A - Chrome"}}
        red = (200, 30, 30)
        facts = Facts(stores=store)
        worker = self.worker(NoHiresApi(solid(red)), facts)
        worker.request([item(0)])
        self.assertEqual(self.facts_by_id(worker, 1)["w0"]["icon_source"], "window")
        facts.values["relaunch"] = solid(red, 256)
        worker.request([item(0)])
        self.assertEqual(self.facts_by_id(worker, 1)["w0"]["icon_source"], "relaunch")

    def test_close_stops_the_worker(self):
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), Facts())
        worker.close(2)
        self.assertFalse(worker._thread.is_alive())
        worker.request([item(0)])
        worker.prewarm([item(0)])
        self.assertEqual((worker.poll(), worker.poll_facts()), ([], []))


class LadderTests(WorkerCase):
    red, blue = (200, 30, 30), (30, 30, 200)

    def master(self, api, facts, entry=None):
        worker = self.worker(api, facts)
        worker.request([entry or item(0)])
        return self.facts_by_id(worker, 1)["w0"]

    def test_1_the_package_logo(self):
        facts = Facts(aumids={10: "Vendor.App_1!App"}, package_names={"Vendor.App_1!App": "Vendor App"},
                      logos={"Vendor.App_1!App": solid((10, 200, 10), 64)})
        found = self.master(Api(solid(self.red), solid(self.red), solid(self.red, 256)), facts)
        self.assertEqual((found["icon_source"], found["icon"].size, found["package_name"]),
                         ("package", (128, 128), "Vendor App"))
        self.assertEqual(found["icon"].getpixel((64, 64)), (10, 200, 10, 255))

    def test_a_desktop_apps_window_aumid_names_no_package(self):
        facts = Facts(stores={10: {"aumid": "Chrome.Profile"}}, package_names={"Chrome.Profile": "Google Chrome"},
                      logos={"Chrome.Profile": solid((10, 200, 10), 64)})
        found = self.master(NoHiresApi(solid(self.red, 48)), facts)
        self.assertNotIn("package_name", found)
        self.assertEqual(found["icon_source"], "window")

    def test_a_uwp_frame_uses_the_aumid_its_window_carries(self):
        facts = Facts(stores={10: {"aumid": "Vendor.App_1!App"}}, package_names={"Vendor.App_1!App": "Vendor App"},
                      logos={"Vendor.App_1!App": solid((10, 200, 10), 64)})
        found = self.master(Api(), facts, item(0, app="ApplicationFrameHost", path=""))
        self.assertEqual((found["icon_source"], found["package_name"]), ("package", "Vendor App"))

    def test_2_the_relaunch_icon_only_when_it_matches(self):
        store = {10: {"relaunch_icon": r"C:\Profile\Profile.ico", "relaunch_display_name": "Profile A - Chrome"}}
        found = self.master(NoHiresApi(solid(self.red)), Facts(stores=store, relaunch=solid(self.red, 256)))
        self.assertEqual((found["icon_source"], found["profile"]), ("relaunch", "Profile A"))
        other = self.master(NoHiresApi(solid(self.red)), Facts(stores=store, relaunch=solid(self.blue, 256)))
        self.assertEqual(other["icon_source"], "window", "another picture than the knob's icon")

    def test_3_the_v5_hires_copy_only_when_it_matches(self):
        found = self.master(Api(solid(self.red), solid(self.red), solid(self.red, 256)), Facts())
        self.assertEqual(found["icon_source"], "hires")
        other = self.master(Api(solid(self.red), solid(self.blue), solid(self.blue, 256)), Facts())
        self.assertEqual(other["icon_source"], "window")

    def test_4_the_windows_own_icon_upscaled(self):
        found = self.master(NoHiresApi(solid(self.red, 48)), Facts())
        self.assertEqual((found["icon_source"], found["icon"].size), ("window", (128, 128)))
        self.assertEqual(found["icon"].getpixel((64, 64)), self.red + (255,))

    def test_5_a_letter_tile_named_after_the_app(self):
        facts = Facts(aumids={10: "Vendor.App_1!App"}, package_names={"Vendor.App_1!App": "Vendor App"})
        found = self.master(Api(), facts, item(0, app="ApplicationFrameHost", path=""))
        self.assertEqual((found["icon_source"], found["icon"].size), ("letter", (128, 128)))
        self.assertIn(("letter_tile", "Vendor App", 128), facts.calls)


class MeetTests(WorkerCase):
    def test_only_a_meet_title_asks_core_audio(self):
        facts = Facts(audible={501})
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(0), item(1, title="Meet - abc-defg-hij - Google Chrome"),
                        item(2, title="Meet \u2013 xyz-abcd-efg")])
        found = self.facts_by_id(worker, 5)
        self.assertIs(found["w1"]["audible"], True)
        self.assertIs(found["w2"]["audible"], False)
        self.assertNotIn("audible", found["w0"])
        self.assertEqual([call[0] for call in facts.calls].count("audible_pids"), 1)

    def test_no_meet_title_no_audio_check_and_an_unanswered_check_says_nothing(self):
        facts = Facts()
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(0, title="Meeting notes")])
        self.facts_by_id(worker, 1)
        self.nothing_more(worker)
        self.assertNotIn(("audible_pids",), facts.calls)
        facts = Facts(audible=None)
        worker = self.worker(NoHiresApi(solid((200, 30, 30))), facts)
        worker.request([item(0, title="Meet - abc-defg-hij")])
        self.assertNotIn("audible", self.facts_by_id(worker, 1)["w0"])
        self.nothing_more(worker)


# ----------------------------------------------------------------------------- runtime
class FactsIcons(FakeIcons):
    def __init__(self):
        super().__init__()
        self.facts = []

    def poll_facts(self):
        facts, self.facts = self.facts, []
        return facts


class RuntimeFactsTests(RuntimeHarness):
    def setUp(self):
        super().setUp()
        self.runtime.icons = self.icons = FactsIcons()

    def open_by_hotkey(self):
        self.runtime.device_connected = self.runtime.device_supported = True
        self.runtime.hotkey()
        self.runtime.poll()

    def test_facts_merge_per_window_and_key(self):
        self.open_by_hotkey()
        revision = self.runtime.window_facts_revision
        icon = object()
        self.icons.facts = [("w0", {"file_description": "App", "icon": icon}), ("w0", {"audible": True}),
                            ("w1", "not a dict")]
        self.runtime.poll()
        self.assertEqual(self.runtime.window_facts, {"w0": {"file_description": "App", "icon": icon, "audible": True}})
        self.assertEqual(self.runtime.window_facts_revision, revision + 2)
        self.runtime.poll()
        self.assertEqual(self.runtime.window_facts_revision, revision + 2, "unchanged without news")

    def test_a_new_snapshot_prunes_facts_of_windows_that_left(self):
        self.open_by_hotkey()
        self.icons.facts = [("w0", {"monitor": "Display A"}), ("gone", {"monitor": "Display B"})]
        self.runtime.poll()
        self.c.button(0)
        self.runtime.dispatch()
        self.runtime.poll()
        self.open_by_hotkey()
        self.assertEqual(set(self.runtime.window_facts), {"w0"})

    def test_a_new_snapshot_forgets_the_meet_answer_of_the_last_one(self):
        self.open_by_hotkey()
        self.icons.facts = [("w0", {"monitor": "Display A", "audible": True})]
        self.runtime.poll()
        self.c.button(0)
        self.runtime.dispatch()
        self.runtime.poll()
        revision = self.runtime.window_facts_revision
        self.open_by_hotkey()
        self.assertEqual(self.runtime.window_facts, {"w0": {"monitor": "Display A"}},
                         "'Meeting' until this snapshot's own Core Audio check answers")
        self.assertGreater(self.runtime.window_facts_revision, revision)

    def test_a_failing_facts_channel_is_logged_once_and_the_tick_goes_on(self):
        self.open_by_hotkey()
        self.icons.poll_facts = Mock(side_effect=OSError("worker"))
        icon = object()
        self.icons.results = [("w0", icon, 0x112233)]
        with self.assertLogs("control_center.runtime", "WARNING") as logs:
            self.runtime.poll()
            self.runtime.poll()
        self.assertEqual(len(logs.records), 1)
        self.assertIs(self.runtime.window_icons["w0"], icon, "the icons still arrived")

    def test_a_worker_without_the_channel_is_fine(self):
        self.runtime.icons = self.icons = FakeIcons()
        self.open_by_hotkey()
        self.runtime.poll()
        self.assertEqual(self.runtime.window_facts, {})


# ----------------------------------------------------------------------------- UI wiring
class FakePickerTop:
    def __init__(self, rect, mapped=True): self.rect_, self.mapped = rect, mapped
    def winfo_ismapped(self): return self.mapped
    def winfo_rootx(self): return self.rect_[0]
    def winfo_rooty(self): return self.rect_[1]
    def winfo_width(self): return self.rect_[2]
    def winfo_height(self): return self.rect_[3]


class RecordingWorker:
    def __init__(self):
        self.priorities, self.prewarmed = [], []

    def prioritize(self, index): self.priorities.append(index)
    def prewarm(self, items): self.prewarmed.append(items)


class RecordingWindows:
    def __init__(self, overlay=None):
        self.overlay = overlay if overlay is not None else SimpleNamespace(icons=[], set_icons=lambda icons: None)
        self.facts, self.backgrounds, self.prewarm_calls = [], [], 0

    def set_window_facts(self, facts): self.facts.append(dict(facts))
    def set_picker_background(self, value): self.backgrounds.append(value)

    def prewarm_items(self):
        self.prewarm_calls += 1
        return [{"id": "w0"}]


def bare_app(runtime, config=None):
    app = object.__new__(ui.ControlCenterApp)
    app.runtime, app.config = runtime, dict(config or {})
    app.controller = runtime.controller
    app._reset_mirror_state()
    return app


class UiPickerTests(unittest.TestCase):
    def runtime(self, **values):
        screen = SimpleNamespace(mode="windows", index=1)
        values.setdefault("windows", RecordingWindows())
        values.setdefault("window_icons", {})
        values.setdefault("window_facts", {})
        values.setdefault("window_facts_revision", 0)
        values.setdefault("window_hires_icon", lambda item_id: None)
        values.setdefault("icons", RecordingWorker())
        values.setdefault("controller", SimpleNamespace(screen=screen, hardware=False, turn=Mock(), button=Mock()))
        return SimpleNamespace(**values)

    def test_the_picker_rect_prefers_the_carousels_pane(self):
        overlay = SimpleNamespace(rect=(1420, 184, 2280, 1120), top=FakePickerTop((0, 0, 5120, 1440)))
        app = bare_app(self.runtime(windows=SimpleNamespace(overlay=overlay)))
        self.assertEqual(app._picker_rect(), (1420, 184, 2280, 1120), "the stage's card area, not the monitor")
        overlay.rect = None
        self.assertIsNone(app._picker_rect(), "hidden")
        overlay.rect = (0, 0, 0, 10)
        self.assertIsNone(app._picker_rect())
        overlay.rect = "broken"
        self.assertIsNone(app._picker_rect())

    def test_a_picker_without_rect_is_measured_through_its_top(self):
        overlay = SimpleNamespace(top=FakePickerTop((10, 20, 300, 200)))
        app = bare_app(self.runtime(windows=SimpleNamespace(overlay=overlay)))
        self.assertEqual(app._picker_rect(), (10, 20, 300, 200))
        overlay.top = FakePickerTop((10, 20, 300, 200), mapped=False)
        self.assertIsNone(app._picker_rect())
        self.assertIsNone(bare_app(self.runtime(windows=SimpleNamespace()))._picker_rect())

    def test_a_raising_rect_counts_as_no_picker(self):
        class Raising:
            @property
            def rect(self):
                raise RuntimeError("presenter thread gone")
        app = bare_app(self.runtime(windows=SimpleNamespace(overlay=Raising())))
        self.assertIsNone(app._picker_rect())
        app.overlay = SimpleNamespace(rect=(0, 0, 5120, 1440))
        self.assertFalse(app._picker_overlaps())
        self.assertFalse(app._carousel_open())

    def test_the_carousel_suppresses_the_knob_while_open_wherever_the_knob_is(self):
        # Section 11: reason 'carousel' replaces the pane-overlap test.
        picker = SimpleNamespace(rect=(1420, 184, 2280, 1120))
        runtime = self.runtime(windows=SimpleNamespace(overlay=picker))
        app = bare_app(runtime)
        app.overlay = SimpleNamespace(rect=(24, 479, 434, 434))       # clear of the pane: held anyway
        self.assertTrue(app._carousel_open())
        self.assertFalse(app._picker_overlaps(), "no pane-overlap test for the carousel")
        app.overlay = SimpleNamespace(rect=(1500, 300, 434, 434))     # under the pane: the same reason
        self.assertFalse(app._picker_overlaps())
        self.assertTrue(app._carousel_open())
        runtime.controller.screen.mode = "home"      # activate()/cancel() returned; the exit still plays
        self.assertTrue(app._carousel_open(), "not keyed to the controller's mode")
        picker.rect = None                           # the exit ended: the carousel tore down
        self.assertFalse(app._carousel_open())
        picker.rect = "broken"
        self.assertFalse(app._carousel_open())
        runtime.windows = SimpleNamespace(overlay=None)
        self.assertFalse(app._carousel_open())
        runtime.windows = SimpleNamespace(overlay=SimpleNamespace(top=FakePickerTop((0, 0, 50, 50))))
        self.assertFalse(app._carousel_open(), "a Tk picker is not the carousel")

    def test_a_picker_without_rect_counts_only_in_windows_mode(self):
        class Top(FakePickerTop):
            reads = 0

            def winfo_ismapped(self):
                Top.reads += 1
                return self.mapped
        runtime = self.runtime(windows=SimpleNamespace(overlay=SimpleNamespace(top=Top((0, 100, 1200, 820)))))
        app = bare_app(runtime)
        app.overlay = SimpleNamespace(rect=(24, 479, 434, 434))
        self.assertTrue(app._picker_overlaps())
        runtime.controller.screen.mode = "home"
        reads = Top.reads
        self.assertFalse(app._picker_overlaps())
        self.assertEqual(Top.reads, reads, "a Tk picker is not measured outside Windows mode")

    def test_icons_prefer_the_master_and_are_sent_only_when_they_change(self):
        sent = []
        windows = RecordingWindows(SimpleNamespace(set_icons=sent.append))
        small, master = Image.new("RGBA", (32, 32)), Image.new("RGBA", (128, 128))
        runtime = self.runtime(windows=windows, window_icons={"w0": small, "w1": None})
        app = bare_app(runtime)
        app._sync_picker_icons()
        app._sync_picker_icons()
        self.assertEqual(len(sent), 1)
        self.assertIs(sent[0]["w0"], small)
        runtime.window_facts = {"w0": {"icon": master}}
        runtime.window_facts_revision = 1
        app._sync_picker_icons()
        self.assertEqual(len(sent), 2)
        self.assertIs(sent[1]["w0"], master)
        self.assertEqual(windows.facts, [{}, {"w0": {"icon": master}}], "facts only when their revision moved")

    def test_the_worker_follows_the_selection_and_prewarms_once(self):
        runtime = self.runtime()
        app = bare_app(runtime)
        app._sync_picker_icons()
        runtime.controller.screen.index = 3
        app._sync_picker_icons()
        app._sync_picker_icons()
        runtime.controller.screen.mode = "volume"
        app._sync_picker_icons()
        runtime.controller.screen.mode = "windows"
        app._sync_picker_icons()
        self.assertEqual(runtime.icons.priorities, [1, 3, 3])
        self.assertEqual(runtime.icons.prewarmed, [[{"id": "w0"}]])
        self.assertEqual(runtime.windows.prewarm_calls, 1)

    def test_the_floating_knob_is_kept_out_of_the_glass_capture(self):
        """KnobOverlay.hwnd goes to the picker's set_capture_exclusions once the knob window
        exists, again only when it or the picker changes, and () when the knob is gone."""
        sent = []
        picker = SimpleNamespace(set_icons=lambda icons: None, set_capture_exclusions=sent.append)
        runtime = self.runtime(windows=RecordingWindows(picker))
        app = bare_app(runtime)
        app._sync_picker_icons()
        self.assertEqual(sent, [()], "no floating knob (chrome=True): nothing to exclude")
        app.overlay = SimpleNamespace(hwnd=0)
        app._sync_picker_icons()
        self.assertEqual(sent, [()], "the knob window does not exist yet")
        app.overlay.hwnd = 0x1234
        app._sync_picker_icons()
        app._sync_picker_icons()
        self.assertEqual(sent, [(), (0x1234,)], "sent once the window exists, not every tick")
        other = SimpleNamespace(set_icons=lambda icons: None, set_capture_exclusions=sent.append)
        runtime.windows.overlay = other                  # a new runtime's picker
        app._sync_picker_icons()
        self.assertEqual(sent[-1], (0x1234,))
        self.assertEqual(len(sent), 3)
        app.overlay.hwnd = 0                             # the knob was torn down
        app._sync_picker_icons()
        self.assertEqual(sent[-1], ())

    def test_a_knob_without_hwnd_and_a_picker_without_exclusions_are_fine(self):
        runtime = self.runtime()
        app = bare_app(runtime)
        app.overlay = SimpleNamespace()
        app._sync_picker_icons()
        sent = []
        runtime.windows.overlay = SimpleNamespace(set_icons=lambda icons: None, set_capture_exclusions=sent.append)
        app._sync_picker_icons()
        self.assertEqual(sent, [()])

    def test_workers_and_windows_without_the_extensions_are_fine(self):
        runtime = self.runtime(windows=SimpleNamespace(overlay=None), icons=None)
        app = bare_app(runtime)
        app._sync_picker_icons()
        runtime = self.runtime(windows=SimpleNamespace(), icons=SimpleNamespace())
        bare_app(runtime)._sync_picker_icons()

    def test_the_switcher_background_is_applied_to_the_windows_provider(self):
        runtime = self.runtime()
        app = bare_app(runtime, {"picker_background": "none"})
        app._apply_presentation()
        app.config["picker_background"] = "bogus"
        app._apply_presentation()
        self.assertEqual(runtime.windows.backgrounds, ["none", "glass"])
        bare_app(SimpleNamespace(controller=None), {})._apply_presentation(SimpleNamespace())

    def test_host_turns_never_move_a_knob_session(self):
        runtime = self.runtime()
        app = bare_app(runtime)
        app._picker_turn(1)
        runtime.controller.turn.assert_called_once_with(1)
        runtime.controller.hardware = True
        app._picker_turn(-1)
        runtime.controller.turn.assert_called_once_with(1)

    def test_live_providers_wire_switch_turn_and_cancel_to_the_controller(self):
        built = {}

        class Adapter:
            def __init__(self, root, **callbacks):
                built.update(callbacks, root=root)

        class Store:
            def __init__(self, *args): pass
            def load(self): return None
        app = bare_app(self.runtime(), {"speaker_ip": "192.0.2.7", "room_uid": ""})
        app.root = "root"
        app.controller = Mock()
        with patch("control_center.windows.WindowsAdapter", Adapter), \
                patch("control_center.sonos.SonosAdapter", Mock()), \
                patch("control_center.apple_music.AppleMusicClient", Mock()), \
                patch("control_center.credentials.CredentialStore", Store):
            app.providers(True)
        built["on_switch"]()
        app.controller.button.assert_called_with(3)
        built["on_cancel"]()
        app.controller.button.assert_called_with(0)
        self.assertEqual(built["on_turn"].__func__, ui.ControlCenterApp._picker_turn)

    def test_the_switcher_background_setting_loads_with_a_default(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(ui, "DATA_DIR", Path(temp)):
            self.assertEqual(ui.ControlCenterApp.load_config()["picker_background"], "glass")
            for stored, expected in (("none", "none"), ("glass", "glass"), ("None", "glass"), (0, "glass"),
                                     (None, "glass"), (["none"], "glass")):
                (Path(temp) / "settings.json").write_text(json.dumps({"picker_background": stored}), encoding="utf-8")
                self.assertEqual(ui.ControlCenterApp.load_config()["picker_background"], expected, stored)

    def test_settings_offer_frosted_and_no_background(self):
        # CAROUSEL.md section 11 names the two backgrounds Frosted and No background.
        self.assertEqual(ui.PICKER_BACKGROUND_CHOICES, (("Frosted", "glass"), ("No background", "none")))
        self.assertIn("switcher background apply when saved", ui.SETUP_SUBTITLE)

    def test_no_background_is_offered_only_where_the_picker_can_show_it(self):
        self.assertEqual(bare_app(self.runtime())._picker_backgrounds_available(), ("glass", "none"))
        plain = SimpleNamespace(picker_backgrounds=("glass",))
        self.assertEqual(bare_app(self.runtime(windows=plain))._picker_backgrounds_available(), ("glass",))

        class Raising:
            @property
            def picker_backgrounds(self):
                raise RuntimeError("presenter thread gone")
        for windows in (Raising(), SimpleNamespace(picker_backgrounds=("bogus",)), SimpleNamespace(),
                        SimpleNamespace(picker_backgrounds=None)):
            with self.subTest(windows=windows):
                self.assertEqual(bare_app(self.runtime(windows=windows))._picker_backgrounds_available(),
                                 ("glass", "none"))
        self.assertIn("Frosted", ui.PICKER_BACKGROUND_FALLBACK_NOTE)


# ----------------------------------------------------------------------------- smoke helpers
def fake_render_modules(glass=None, tile=None, label=None, missing=None):
    def default_glass(image, k):
        return image.convert("RGBA").point(lambda value: value // 2)

    def default_label(label_value, icon, k, background):
        image = Image.new("RGBA", (round(900 * k), round(80 * k)), (0, 0, 0, 0))
        image.paste(Image.new("RGBA", (40, 40), (255, 255, 255, 255)), (10, 10))
        return image

    render = ModuleType("control_center.carousel_render")
    render.glass = glass or default_glass
    render.render_label = label or default_label
    if missing is not None:
        render.missing_glyphs = missing
    facts = ModuleType("control_center.window_facts")

    def default_tile(name, px, radius=0):
        image = Image.new("RGBA", (px, px), (40, 60, 120, 255))
        image.paste(Image.new("RGBA", (px // 3, px // 2), (255, 255, 255, 255)), (px // 3, px // 4))
        return image
    facts.letter_tile = tile or default_tile
    labels = ModuleType("control_center.window_labels")
    labels.Label = FakeLabel
    return {"control_center.carousel_render": render, "control_center.window_facts": facts,
            "control_center.window_labels": labels}


class SmokeHelperTests(unittest.TestCase):
    def run_render(self, **fakes):
        import standalone
        modules = fake_render_modules(**fakes)
        patches = [patch.dict(sys.modules, modules)]
        for name, module in modules.items():
            patches.append(patch.object(control_center, name.rsplit(".", 1)[1], module, create=True))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return standalone.smoke_carousel_render()

    def test_the_carousel_render_check_passes_with_working_modules(self):
        detail = self.run_render(missing=lambda text: "")
        self.assertEqual(detail["glass"]["size"], [2560, 1440], "the stage-sized frost (section 11)")
        self.assertEqual(set(detail["label"]), {"glass", "none"})
        self.assertGreaterEqual(detail["letterTile"]["contrast"], 3.0)
        self.assertTrue(detail["fallbackCoverage"])
        json.dumps(detail)

    def test_the_carousel_render_check_fails_on_each_broken_part(self):
        def pale(name, px, radius=0):       # the design's gold with a white letter: 1.87:1
            image = Image.new("RGBA", (px, px), (0xE8, 0xB6, 0x4A, 255))
            image.paste(Image.new("RGBA", (px // 3, px // 2), (255, 255, 255, 255)), (px // 3, px // 4))
            return image
        cases = {"unchanged": dict(glass=lambda image, k: image.convert("RGBA")),
                 "RGBA": dict(glass=lambda image, k: image),
                 "no white letter": dict(tile=lambda name, px, radius=0: Image.new("RGBA", (px, px), (9, 9, 9, 255))),
                 "square and opaque": dict(tile=lambda name, px, radius=0: Image.new("RGBA", (px, px))),
                 "below 3:1": dict(tile=pale),
                 "drew nothing": dict(label=lambda *args: Image.new("RGBA", (10, 10))),
                 "not a label image": dict(label=lambda *args: b"premultiplied"),
                 "tofu": dict(missing=lambda text: "\u7159")}
        for message, fakes in cases.items():
            with self.subTest(case=message):
                with self.assertRaisesRegex(RuntimeError, message):
                    self.run_render(**fakes)

    def test_the_carousel_window_check_uses_the_modules_smoke_check_and_the_baseline(self):
        import standalone
        module = ModuleType("carousel")
        module.smoke_check = lambda: {"thumbnails": 1}
        with patch.object(standalone, "gui_resources", Mock(side_effect=[(10, 20), (10, 20)])):
            detail = standalone.smoke_carousel_window(module)
        self.assertEqual(detail, {"thumbnails": 1, "gdi": [10, 10], "user": [20, 20]})
        with patch.object(standalone, "gui_resources", Mock(side_effect=[(10, 20)] + [(12, 20)] * 1000)), \
                patch.object(standalone, "GUI_BASELINE_SECONDS", 0.05):
            with self.assertRaisesRegex(RuntimeError, "leaked"):
                standalone.smoke_carousel_window(module)
        with self.assertRaisesRegex(RuntimeError, "smoke_check"):
            standalone.smoke_carousel_window(ModuleType("carousel"))

    def test_without_smoke_check_the_presenter_lifecycle_runs_hidden(self):
        import standalone
        made = []

        class Presenter:
            hwnd, rect, disabled, last_error, joined = 4242, None, False, None, True

            def __init__(self, root, native, on_cancel):
                made.append(self)
                self.shown = self.closed = False

            def show(self, snapshot): self.shown = True
            def metrics(self): return {"host_mode": "layered", "dpi_awareness": 2, "rect": None}

            def close(self):
                self.closed = True
                return self.joined
        module = ModuleType("carousel")
        module.CarouselPresenter = Presenter
        counts = patch.object(standalone, "gui_resources", Mock(return_value=(10, 20)))
        with counts, patch.object(standalone, "_window_visible", return_value=False):
            detail = standalone.smoke_carousel_window(module)
        self.assertEqual(detail, {"hostMode": "layered", "dpiAwareness": 2, "gdi": [10, 10], "user": [20, 20]})
        self.assertTrue(made[0].closed)
        self.assertFalse(made[0].shown, "never shown")
        for change, message in ((dict(disabled=True), "did not start"), (dict(hwnd=0), "did not start"),
                                (dict(rect=(0, 0, 10, 10)), "shown before"), (dict(joined=False), "did not stop")):
            with self.subTest(change=change):
                broken = type("Broken", (Presenter,), change)
                module.CarouselPresenter = broken
                with patch.object(standalone, "gui_resources", Mock(return_value=(10, 20))), \
                        patch.object(standalone, "_window_visible", return_value=False), \
                        self.assertRaisesRegex(RuntimeError, message):
                    standalone.smoke_carousel_window(module)
                self.assertTrue(made[-1].closed, "closed on every path")
        module.CarouselPresenter = Presenter
        with patch.object(standalone, "gui_resources", Mock(return_value=(10, 20))), \
                patch.object(standalone, "_window_visible", return_value=True), \
                self.assertRaisesRegex(RuntimeError, "shown before"):
            standalone.smoke_carousel_window(module)

    def test_the_carousel_window_check_runs_the_self_test_then_the_presenter_lifecycle(self):
        import standalone
        calls, made = [], []

        class Presenter:
            hwnd, rect, disabled, last_error = 4242, None, False, None

            def __init__(self, root, native, on_cancel): made.append(self)
            def metrics(self): return {"host_mode": "noredirection", "dpi_awareness": 2}
            def close(self): return True

        def self_test(hidden_windows=False, k=2.0):
            calls.append((hidden_windows, k))
            return {"ok": True, "glass_ok": True, "windows": {"ok": True, "thumbnail": True, "ulw": True}}
        module = ModuleType("carousel")
        module.self_test, module.CarouselPresenter = self_test, Presenter
        with patch.object(standalone, "gui_resources", Mock(return_value=(10, 20))), \
                patch.object(standalone, "_window_visible", return_value=False):
            detail = standalone.smoke_carousel_window(module)
        self.assertEqual(calls, [(True, standalone.SMOKE_STAGE_SCALE)], "hidden windows at the user's k")
        self.assertTrue(detail["selfTest"]["windows"]["thumbnail"])
        self.assertEqual((detail["hostMode"], detail["gdi"]), ("noredirection", [10, 10]))
        self.assertEqual(len(made), 1)
        json.dumps(detail)
        for report in ({"ok": False, "windows": {"ok": False, "thumbnail": False}}, None, {"ok": "yes"}):
            with self.subTest(report=report):
                module.self_test = lambda hidden_windows=False, k=2.0, report=report: report
                with patch.object(standalone, "gui_resources", Mock(return_value=(10, 20))), \
                        self.assertRaisesRegex(RuntimeError, "self-test failed"):
                    standalone.smoke_carousel_window(module)
        only = ModuleType("carousel")
        only.self_test = self_test
        with patch.object(standalone, "gui_resources", Mock(return_value=(10, 20))):
            self.assertEqual(set(standalone.smoke_carousel_window(only)), {"selfTest", "gdi", "user"})

    def test_the_smoke_test_runs_the_carousel_render_check_and_no_window_without_ui(self):
        import standalone
        with tempfile.TemporaryDirectory() as temp, \
                patch("tkinter.Tk", side_effect=RuntimeError("no Tk in this test")), \
                patch("control_center.ui.register_fonts", return_value={}), \
                patch.object(standalone, "smoke_carousel_render", return_value={"ok": True}), \
                patch.object(standalone, "smoke_carousel_window") as window:
            out = Path(temp) / "logs"
            standalone.run_smoke_test(out, ui=False)
            report = json.loads((out / "smoke-test.json").read_text(encoding="utf-8"))
        self.assertEqual(report["checks"]["carouselRender"], {"passed": True, "detail": {"ok": True}})
        self.assertNotIn("carouselWindow", report["checks"])
        window.assert_not_called()

    def test_contrast_ratio(self):
        import standalone
        self.assertAlmostEqual(standalone.contrast_ratio((255, 255, 255), (0, 0, 0)), 21.0, places=3)
        self.assertAlmostEqual(standalone.contrast_ratio((255, 255, 255), (255, 255, 255)), 1.0)
        self.assertLess(standalone.contrast_ratio((255, 255, 255), (0xE8, 0xB6, 0x4A)), 3.0, "the design's gold")


if __name__ == "__main__":
    unittest.main()

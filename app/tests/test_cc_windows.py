"""Window selection tests: no keys, foreground changes, or native UI are used.

The subprocess tests run a withdrawn Tk root in a child process and post
WM_HOTKEY to its own hidden window: no window is shown, focus never changes, F24
is never registered (the running companion owns it) and a deliberate abort()
exits quietly (no Windows Error Reporting).
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_center import windows as w


def record(hwnd, pid=20, title=None, **values):
    return dict(hwnd=hwnd, pid=pid, id=f"{hwnd:x}:{pid}:0:0",
                title=title or f"Window {hwnd}", app="Example", available=True,
                **values)


class FakeRoot:
    def __init__(self):
        self.timers = {}
        self.counter = 0
        self.errors = []

    def update_idletasks(self):
        pass

    def winfo_id(self):
        return 900

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

    def __init__(self):
        self.windows = {r["hwnd"]: r for r in [record(1), record(2), record(3)]}
        self.windows[900] = record(900, pid=self.own_pid)
        self.windows[901] = record(901, pid=self.own_pid)
        self.foreground_hwnd = 1
        self.focus_calls = []
        self.hotkey_calls = []
        self.allow_focus = True
        self.closed = False

    def root_handle(self, hwnd):
        return hwnd

    def identity(self, hwnd):
        item = self.windows.get(hwnd)
        return {key: item[key] for key in ("hwnd", "pid", "id")} if item else None

    def foreground(self):
        return self.identity(self.foreground_hwnd)

    def records(self):
        return list(self.windows.values())

    def attach_hotkey(self, hwnd, callback, report_error):
        self.hotkey_owner, self.hotkey_callback = hwnd, callback

    def watch(self, on_foreground, on_destroy):
        self.on_foreground, self.on_destroy = on_foreground, on_destroy

    def focus(self, hwnd, restore=False):
        self.focus_calls.append((hwnd, restore))
        if self.allow_focus:
            self.foreground_hwnd = hwnd
        return self.allow_focus

    def hotkey(self, enabled):
        self.hotkey_calls.append(enabled)

    def close(self):
        self.closed = True


class FakeOverlay:
    hwnd = 901

    def __init__(self, root, native, on_cancel):
        self.on_cancel = on_cancel
        self.visible = False
        self.closed = False
        self.highlights = []

    def show(self, snapshot):
        self.snapshot = snapshot
        self.visible = True

    def highlight(self, index):
        self.highlights.append(index)

    def focus_local(self):
        pass

    def hide(self):
        self.visible = False

    def close(self):
        self.visible = False
        self.closed = True


class SelectionTests(unittest.TestCase):
    def test_minimized_application_is_included(self):
        self.assertTrue(w.eligible(record(1, minimized=True), 100))

    def test_shell_tools_hidden_cloaked_and_own_windows_excluded(self):
        for changes in ({"pid": 100}, {"visible": False}, {"cloaked": True},
                        {"exstyle": w.WS_EX_TOOLWINDOW}, {"exstyle": w.WS_EX_NOACTIVATE},
                        {"owner": 2}, {"class_name": "Shell_TrayWnd"}, {"title": "  "}):
            with self.subTest(changes=changes):
                item = record(1)
                item.update(changes)
                self.assertFalse(w.eligible(item, 100))

    def test_appwindow_can_have_owner(self):
        self.assertTrue(w.eligible(record(1, owner=2, exstyle=w.WS_EX_APPWINDOW), 100))

    def test_current_is_zero_mru_other_is_initial_one(self):
        records = [record(1), record(2), record(3)]
        snapshot = w.make_snapshot(records, records[0], [records[2]["id"], records[1]["id"]], 100)
        self.assertEqual([r["hwnd"] for r in snapshot["items"]], [1, 3, 2])
        self.assertEqual(snapshot["index"], 1)

    def test_no_current_candidate_starts_at_best_other(self):
        records = [record(1), record(2), record(3)]
        snapshot = w.make_snapshot(records, record(900, pid=100), [records[2]["id"]], 100)
        self.assertEqual([r["hwnd"] for r in snapshot["items"]], [3, 1, 2])
        self.assertEqual(snapshot["index"], 0)

    def test_empty_and_single_window_snapshots(self):
        for items in ([], [record(1)]):
            snapshot = w.make_snapshot(items, record(1), [], 100)
            self.assertEqual(snapshot["index"], 0)
            self.assertEqual(len(snapshot["items"]), len(items))

    def test_snapshot_is_detached_from_enumeration_records(self):
        original = record(1)
        snapshot = w.make_snapshot([original], original, [], 100)
        original["title"] = "Renamed"
        self.assertEqual(snapshot["items"][0]["title"], "Window 1")

    def test_identity_rejects_reused_handle_pid_and_generation(self):
        item = record(1)
        for identity in (None, record(2), record(1, pid=21), dict(item, id="replacement")):
            self.assertFalse(w.same_identity(item, identity))
        self.assertTrue(w.same_identity(item, dict(item, title="Renamed")))

    def test_unavailable_entry_never_recovers_by_coincidence(self):
        self.assertFalse(w.same_identity(dict(record(1), available=False), record(1)))

    def test_minimal_origin_verifies_both_handle_and_pid(self):
        self.assertTrue(w.same_identity({"hwnd": 1, "pid": 20}, record(1)))
        self.assertFalse(w.same_identity({"hwnd": 1, "pid": 21}, record(1)))

    def test_native_structs_use_windows_widths_on_every_platform(self):
        # RECT/MONITORINFO/THUMBNAIL_PROPERTIES left with the grid overlay's placement and
        # thumbnail helpers (desktop v6: the carousel declares its own, test_carousel_presenter).
        self.assertEqual(ctypes.sizeof(w.FILETIME), 8)
        self.assertEqual(ctypes.sizeof(w.BITMAPINFOHEADER), 40)
        self.assertEqual(ctypes.sizeof(w.GUID), 16)
        self.assertEqual(ctypes.sizeof(w.LPARAM), ctypes.sizeof(ctypes.c_void_p))


# Desktop v6 (CAROUSEL.md section 1): the Tk grid overlay is replaced by the carousel
# presenter. GridTests retired with picker_grid/fit_caption. The presentation invariants of
# ThumbnailLifecycleTests and OverlayDismissalTests (register once, never retry a failure,
# release on closed/off-screen/hide; nothing draws or registers after hide/close, thumbnails
# released before the window goes, idempotent close, show-after-close raises) are ported to
# the carousel's presenter tests (fake backend); the adapter's side of the seam (focus ->
# verify -> exit animation -> hide, presenter input drained by pump(), labels and icons
# never in the WM_HOTKEY/focus path) is in test_carousel_adapter.py.


class AdapterHarness(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.events = []
        self.patch_native = patch.object(w, "NativeWindows", FakeNative)
        self.patch_overlay = patch.object(w, "PickerOverlay", FakeOverlay)
        self.patch_native.start()
        self.patch_overlay.start()
        self.addCleanup(self.patch_native.stop)
        self.addCleanup(self.patch_overlay.stop)
        self.adapter = w.WindowsAdapter(self.root, lambda: self.events.append("hotkey"),
                                        lambda: self.events.append("cancel"),
                                        lambda: self.events.append("focus_lost"),
                                        lambda: self.events.append("closed"))
        self.addCleanup(self.adapter.close)

    def open_picker(self):
        snapshot = self.adapter.snapshot()
        self.adapter.show(snapshot)
        return snapshot


class AdapterTests(AdapterHarness):
    def test_constructor_does_not_enable_hotkey_or_change_focus(self):
        self.assertEqual(self.adapter.native.hotkey_calls, [])
        self.assertEqual(self.adapter.native.focus_calls, [])

    def test_hotkey_opt_in_and_callback(self):
        self.adapter.set_hotkey_enabled(True)
        self.adapter.native.hotkey_callback()   # a native call outside Tk's event loop
        self.assertEqual(self.events, [], "no tkinter-reaching work inside the native callback")
        self.adapter.pump()
        self.assertEqual(self.adapter.native.hotkey_calls, [True])
        self.assertEqual(self.events, ["hotkey"])
        self.adapter.pump()
        self.assertEqual(self.events, ["hotkey"], "each press runs once")

    def test_hotkey_from_the_event_loop_runs_synchronously_through_tcl(self):
        invoker = self.adapter._invoker = Mock(return_value=True)
        self.adapter.native.hotkey_callback(event_loop=True)
        invoker.assert_called_once_with()
        self.assertFalse(self.adapter._hotkey_pending)
        self.adapter._run_hotkey()              # what Tcl runs for the invoker
        self.assertEqual(self.events, ["hotkey"])
        self.adapter.pump()
        self.assertEqual(self.events, ["hotkey"])

    def test_hotkey_falls_back_to_pump_when_tcl_cannot_run_it(self):
        for invoker, event_loop in ((Mock(return_value=False), True), (None, True),
                                    (Mock(return_value=True), False)):
            with self.subTest(invoker=invoker, event_loop=event_loop):
                self.events.clear()
                self.adapter._invoker = invoker
                self.adapter.native.hotkey_callback(event_loop=event_loop)
                if invoker is not None and not event_loop:
                    invoker.assert_not_called()   # never evaluated outside the event loop
                self.assertTrue(self.adapter._hotkey_pending)
                self.assertEqual(self.events, [])
                self.adapter.pump()
                self.assertEqual(self.events, ["hotkey"])

    def test_deferred_hotkey_is_dropped_once_the_hotkey_is_disabled(self):
        self.adapter.native.hotkey_enabled = False
        self.adapter.native.hotkey_callback()
        self.adapter.pump()
        self.assertEqual(self.events, [])
        self.assertFalse(self.adapter._hotkey_pending)

    def test_snapshot_and_mru_monitoring_are_read_only(self):
        self.adapter.native.foreground_hwnd = 3
        self.adapter.native.on_foreground(3)
        self.adapter.native.foreground_hwnd = 1
        self.adapter.native.on_foreground(1)
        snapshot = self.adapter.snapshot()
        self.assertEqual([r["hwnd"] for r in snapshot["items"]], [1, 3, 2])
        self.assertEqual(self.adapter.native.focus_calls, [])

    def test_highlighting_never_activates_external_window(self):
        snapshot = self.open_picker()
        self.adapter.highlight(2)
        self.adapter.highlight(0)
        self.assertEqual(snapshot["index"], 0)
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])

    def test_second_show_keeps_original_snapshot(self):
        first = self.open_picker()
        self.adapter.show({"items": [], "origin": {"hwnd": 4, "pid": 55}, "index": 0})
        self.assertIs(self.adapter._snapshot, first)
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])

    def test_closed_entries_remain_in_place_and_notify_once(self):
        snapshot = self.open_picker()
        del self.adapter.native.windows[2]
        self.adapter._poll()
        self.assertEqual([r["hwnd"] for r in snapshot["items"]], [1, 2, 3])
        self.assertFalse(snapshot["items"][1]["available"])
        self.assertEqual(self.events, ["closed"])
        self.adapter._poll()
        self.assertEqual(self.events, ["closed"])

    def test_recycled_identity_is_not_activated(self):
        snapshot = self.open_picker()
        item = snapshot["items"][1]
        self.adapter.native.windows[2] = dict(record(2), id="same-process-new-window")
        self.assertFalse(self.adapter.activate(item))
        self.assertFalse(item["available"])
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])

    def test_confirm_changes_focus_only_after_identity_check(self):
        snapshot = self.open_picker()
        self.assertTrue(self.adapter.activate(snapshot["items"][1]))
        self.assertEqual(self.adapter.native.focus_calls, [(901, False), (2, True)])
        self.assertFalse(self.adapter.overlay.visible)
        self.assertEqual(self.events, [])

    def test_failed_foreground_request_keeps_picker_open(self):
        snapshot = self.open_picker()
        self.adapter.native.allow_focus = False
        self.assertFalse(self.adapter.activate(snapshot["items"][1]))
        self.assertTrue(self.adapter.overlay.visible)

    def test_cancel_restores_valid_origin(self):
        snapshot = self.open_picker()
        self.assertTrue(self.adapter.cancel(snapshot["origin"]))
        self.assertEqual(self.adapter.native.focus_calls[-1], (1, True))
        self.assertFalse(self.adapter.overlay.visible)

    def test_cancel_does_not_restore_reused_origin(self):
        snapshot = self.open_picker()
        self.adapter.native.windows[1] = record(1, pid=999)
        self.assertFalse(self.adapter.cancel(snapshot["origin"]))
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])
        self.assertFalse(self.adapter.overlay.visible)

    def test_external_focus_loss_hides_without_restoring_origin(self):
        self.open_picker()
        self.adapter.native.foreground_hwnd = 3
        self.adapter.native.on_foreground(3)
        self.adapter._check_focus_lost()
        self.assertEqual(self.events, ["focus_lost"])
        self.assertFalse(self.adapter.overlay.visible)
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])

    def test_cancel_focus_loss_race_does_not_steal_focus(self):
        snapshot = self.open_picker()
        self.adapter.native.foreground_hwnd = 3
        self.assertFalse(self.adapter.cancel(snapshot["origin"]))
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])
        self.assertFalse(self.adapter.overlay.visible)

    def test_confirm_focus_loss_race_cancels_without_switching(self):
        snapshot = self.open_picker()
        self.adapter.native.foreground_hwnd = 3
        self.assertFalse(self.adapter.activate(snapshot["items"][1]))
        self.assertEqual(self.events, ["focus_lost"])
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])

    def test_foreground_identity_is_verified_after_successful_request(self):
        snapshot = self.open_picker()
        original_focus = self.adapter.native.focus
        def replaced_during_focus(hwnd, restore=False):
            result = original_focus(hwnd, restore)
            self.adapter.native.windows[hwnd] = record(hwnd, pid=999)
            return result
        self.adapter.native.focus = replaced_during_focus
        self.assertFalse(self.adapter.activate(snapshot["items"][1]))
        self.assertTrue(self.adapter.overlay.visible)

    def test_hide_alone_has_no_focus_action(self):
        self.open_picker()
        self.adapter.hide()
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)])

    def test_denied_overlay_focus_is_clear_and_reversible(self):
        self.adapter.native.allow_focus = False
        with self.assertRaisesRegex(OSError, "F24"):
            self.open_picker()
        self.assertFalse(self.adapter._visible)
        self.assertFalse(self.adapter.overlay.visible)

    def test_ui_thread_enforced_without_native_calls(self):
        errors = []
        def other_thread():
            try:
                self.adapter.snapshot()
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(self.adapter.native.focus_calls, [])

    def test_close_is_idempotent_and_cleans_resources(self):
        self.adapter.close()
        self.adapter.close()
        self.assertTrue(self.adapter.native.closed)
        self.assertTrue(self.adapter.overlay.closed)
        self.assertEqual(self.root.timers, {})

    def test_callback_errors_are_reported_to_tk(self):
        def failure():
            raise ValueError("callback failed")
        self.adapter.on_hotkey = failure
        self.adapter.native.hotkey_callback()
        self.adapter.pump()
        self.assertEqual(self.root.errors[0][0], ValueError)


class ForegroundEventTests(AdapterHarness):
    """The WinEvent hook only queues; pump() (the UI tick) decides, on the Tk thread."""

    def advance(self, seconds):
        now = w.time.monotonic() + seconds
        return patch.object(w, "time", SimpleNamespace(monotonic=lambda: now))

    def test_the_hook_calls_neither_tkinter_nor_native_lookups(self):
        self.open_picker()
        timers = dict(self.root.timers)
        with patch.object(self.adapter.native, "identity", wraps=self.adapter.native.identity) as identity:
            self.adapter.native.on_foreground(3)
            identity.assert_not_called()
        self.assertEqual(self.root.timers, timers, "no Tk timer scheduled from the hook")
        self.assertEqual(list(self.adapter._foreground_events), [3])

    def test_external_foreground_change_dismisses_after_settling(self):
        self.open_picker()
        self.adapter.native.foreground_hwnd = 3
        self.adapter.native.on_foreground(3)
        self.adapter.pump()
        self.assertTrue(self.adapter.overlay.visible, "re-checked only after it settles")
        with self.advance(w.FOCUS_SETTLE_SECONDS + 0.01):
            self.adapter.pump()
        self.assertEqual(self.events, ["focus_lost"])
        self.assertFalse(self.adapter.overlay.visible)
        self.assertEqual(self.adapter.native.focus_calls, [(901, False)], "no focus action")

    def test_focus_regained_before_the_check_keeps_the_picker(self):
        self.open_picker()
        self.adapter.native.foreground_hwnd = 3
        self.adapter.native.on_foreground(3)
        self.adapter.pump()
        self.adapter.native.foreground_hwnd = 901   # back on the picker
        with self.advance(1):
            self.adapter.pump()
        self.assertEqual(self.events, [])
        self.assertTrue(self.adapter.overlay.visible)

    def test_own_windows_never_dismiss(self):
        self.open_picker()
        self.adapter.native.on_foreground(901)
        with self.advance(1):
            self.adapter.pump()
        self.assertIsNone(self.adapter._focus_due)
        self.assertTrue(self.adapter.overlay.visible)

    def test_late_events_after_dismissal_do_nothing(self):
        snapshot = self.open_picker()
        self.adapter.cancel(snapshot["origin"])
        self.adapter.native.foreground_hwnd = 3
        self.adapter.native.on_foreground(3)
        with self.advance(1):
            self.adapter.pump()
        self.assertEqual(self.events, [])
        self.assertIsNone(self.adapter._focus_due)

    def test_hide_cancels_a_pending_focus_check(self):
        self.open_picker()
        self.adapter.native.foreground_hwnd = 3
        self.adapter.native.on_foreground(3)
        self.adapter.pump()
        self.assertIsNotNone(self.adapter._focus_due)
        self.adapter.hide()
        self.assertIsNone(self.adapter._focus_due)
        with self.advance(1):
            self.adapter.pump()
        self.assertEqual(self.events, [])

    def test_snapshot_sees_every_queued_foreground_change(self):
        for hwnd in (2, 3, 1):
            self.adapter.native.on_foreground(hwnd)
        self.adapter.native.foreground_hwnd = 1
        snapshot = self.adapter.snapshot()
        self.assertEqual([r["hwnd"] for r in snapshot["items"]], [1, 3, 2])
        self.assertEqual(list(self.adapter._foreground_events), [])

    def test_a_vanished_window_in_the_queue_is_skipped(self):
        self.adapter.native.on_foreground(77)       # unknown: identity None
        with patch.object(self.adapter.native, "identity", side_effect=[OSError("gone"), None]):
            self.adapter.native.on_foreground(78)
            self.adapter.pump()
        self.assertEqual(list(self.adapter._foreground_events), [])

    def test_the_queue_is_bounded(self):
        for hwnd in range(w.FOREGROUND_EVENT_LIMIT * 2):
            self.adapter.native.on_foreground(hwnd)
        self.assertEqual(len(self.adapter._foreground_events), w.FOREGROUND_EVENT_LIMIT)

    def test_pump_off_the_tk_thread_or_after_close_does_nothing(self):
        self.adapter.native.hotkey_callback()
        thread = threading.Thread(target=self.adapter.pump)
        thread.start()
        thread.join()
        self.assertEqual(self.events, [])
        self.adapter.close()
        self.adapter.pump()
        self.adapter.hide()                          # idempotent after close, never raises
        self.assertEqual(self.events, [])
        self.assertFalse(self.adapter._hotkey_pending)
        self.assertEqual(list(self.adapter._foreground_events), [])
        self.adapter.native.on_foreground(3)         # a WinEvent racing the unhook
        self.assertEqual(list(self.adapter._foreground_events), [])

    def test_backstop_poll_pumps_and_reschedules(self):
        self.adapter.native.hotkey_callback()
        self.adapter._poll()
        self.assertEqual(self.events, ["hotkey"])
        self.assertIsNotNone(self.adapter._poll_id)

    def test_close_releases_the_invoker_and_native_before_the_overlay(self):
        order = Mock()
        self.adapter._invoker = order.invoker
        self.adapter.native.close = order.native_close
        self.adapter.overlay.close = order.overlay_close
        self.adapter.close()
        self.assertEqual(order.mock_calls, [call.invoker.close(), call.native_close(), call.overlay_close()])

    def test_overlay_closes_even_when_native_close_fails(self):
        self.adapter.native.close = Mock(side_effect=OSError("user32"))
        with self.assertRaises(OSError):
            self.adapter.close()
        self.assertTrue(self.adapter.overlay.closed)


class NativeHotkeyTests(unittest.TestCase):
    def setUp(self):
        self.native = object.__new__(w.NativeWindows)
        self.native.u = Mock()
        self.native._hotkey_owner = 900
        self.native._hotkey_enabled = False

    def test_registration_uses_f24_no_repeat_and_is_idempotent(self):
        self.native.u.RegisterHotKey.return_value = True
        self.native.hotkey(True)
        self.native.hotkey(True)
        self.native.u.RegisterHotKey.assert_called_once_with(900, w.HOTKEY_ID, w.MOD_NOREPEAT, w.VK_F24)
        self.assertTrue(self.native._hotkey_enabled)

    def test_conflict_is_explicit_and_does_not_mark_enabled(self):
        self.native.u.RegisterHotKey.return_value = False
        with patch.object(w.C, "get_last_error", return_value=1409, create=True):
            with self.assertRaisesRegex(OSError, "Another application"):
                self.native.hotkey(True)
        self.assertFalse(self.native._hotkey_enabled)

    def test_disabling_unregisters_exactly_once(self):
        self.native._hotkey_enabled = True
        self.native.hotkey(False)
        self.native.hotkey(False)
        self.native.u.UnregisterHotKey.assert_called_once_with(900, w.HOTKEY_ID)
        self.assertFalse(self.native._hotkey_enabled)


def bare_native():
    native = object.__new__(w.NativeWindows)
    native.u = Mock()
    native.u.SetWinEventHook.side_effect = [11, 12]
    native.u.CallWindowProcW.return_value = 0      # an LRESULT the thunk can return
    native.set_long = Mock(return_value=4242)     # Tk's original window procedure
    native.get_long = Mock()
    native.generations = {}
    native._hooks, native._event_callbacks = [], []
    native._wndproc = native._old_proc = None
    native._hotkey_owner, native._hotkey_enabled = 0, False
    native._hotkey_handler = native._hotkey_report = None
    native._on_foreground = native._on_destroy = None
    return native


class NativeCallbackTests(unittest.TestCase):
    """The real ctypes thunks, called from Python the way Windows would call them."""
    def test_the_window_procedure_passes_the_event_loop_flag(self):
        native, calls = bare_native(), []
        native.attach_hotkey(900, lambda **flags: calls.append(flags), Mock())
        native._hotkey_enabled = True
        self.assertEqual(native._wndproc(900, w.WM_HOTKEY, w.HOTKEY_ID, 0), 0)
        self.assertEqual(calls, [{"event_loop": False}], "called from a test frame, not tkinter's loop")
        native._wndproc(900, 0x0010, 0, 0)            # any other message goes to Tk
        native.u.CallWindowProcW.assert_called_once_with(4242, 900, 0x0010, 0, 0)

    def test_handler_errors_are_reported_and_never_unwind_into_user32(self):
        native, report = bare_native(), Mock()
        def failing(**_flags):
            raise ValueError("handler failed")
        native.attach_hotkey(900, failing, report)
        native._hotkey_enabled = True
        self.assertEqual(native._wndproc(900, w.WM_HOTKEY, w.HOTKEY_ID, 0), 0)
        self.assertIs(report.call_args[0][0], ValueError)

    def test_closing_retires_the_thunks_and_cuts_them_off(self):
        native, calls, seen = bare_native(), [], []
        native.attach_hotkey(900, lambda **flags: calls.append(flags), Mock())
        native.watch(seen.append, Mock())
        procedure, events = native._wndproc, list(native._event_callbacks)
        native.u.IsWindow.return_value = True
        native.get_long.return_value = ctypes.cast(procedure, w.HANDLE).value   # still ours
        native._hotkey_enabled = True
        native.close()
        native.set_long.assert_called_with(900, -4, 4242)
        self.assertIsNone(native._wndproc)
        for thunk in [procedure] + events:
            self.assertIn(thunk, w._RETIRED_CALLBACKS)
        # A late message or queued WinEvent reaches no adapter; messages still reach Tk.
        procedure(900, w.WM_HOTKEY, w.HOTKEY_ID, 0)
        procedure(900, 0x0010, 0, 0)
        events[0](11, 3, 1234, 0, 0, 0, 0)
        self.assertEqual((calls, seen), ([], []))
        native.u.CallWindowProcW.assert_called_with(4242, 900, 0x0010, 0, 0)
        native.close()                                 # idempotent
        self.assertEqual(native.set_long.call_count, 2, "attach + one restore")

    def test_a_newer_subclass_is_left_in_place(self):
        native = bare_native()
        native.attach_hotkey(900, lambda **flags: None, Mock())
        native.u.IsWindow.return_value = True
        native.get_long.return_value = 9999           # another procedure chained on top
        native.close()
        self.assertEqual(native.set_long.call_count, 1, "only the attach")

    def test_winevent_thunks_record_and_swallow_errors(self):
        native, seen = bare_native(), []
        destroyed = Mock()
        native.watch(seen.append, destroyed)
        foreground, destroy = native._event_callbacks
        foreground(11, 3, 1234, 0, 0, 0, 0)
        self.assertEqual(seen, [1234])
        native._on_foreground = Mock(side_effect=RuntimeError("never escapes"))
        foreground(11, 3, 1235, 0, 0, 0, 0)
        native.generations[77] = 0
        destroy(12, 0x8001, 77, 0, 0, 0, 0)
        destroyed.assert_called_once_with(77)
        self.assertEqual(native.generations[77], 1)

    def test_event_loop_frames_are_recognised(self):
        frames = []
        grab = lambda *_args: frames.append(sys._getframe(1))
        fake = SimpleNamespace(tk=SimpleNamespace(mainloop=grab, call=grab))
        tk.Misc.mainloop(fake)
        tk.Misc.update(fake)
        tk.Misc.wait_window(fake, SimpleNamespace(_w=".x"))
        self.assertTrue(all(w.called_from_tk_event_loop(frame) for frame in frames))
        self.assertEqual(len(frames), 3)
        tk.Misc.update_idletasks(fake)             # runs idle handlers only: not a message loop
        self.assertFalse(w.called_from_tk_event_loop(frames[-1]))
        self.assertFalse(w.called_from_tk_event_loop(sys._getframe()))
        self.assertFalse(w.called_from_tk_event_loop(None))

    def test_no_invoker_without_a_real_tk_interpreter(self):
        self.assertIsNone(w._make_invoker(FakeRoot(), lambda: None))


CHILD = r"""
import ctypes as C, json, sys, threading, time
C.CDLL("ucrtbase")._set_abort_behavior(0, 3)      # abort(): quiet _exit(3), no WER report
C.windll.kernel32.SetErrorMode(0x8003)
sys.path.insert(0, sys.argv[1])
import tkinter as tk
from control_center import windows as w
mode = sys.argv[2]
if mode == "direct":                               # the cc4 behaviour: tkinter straight from the callback
    class Direct:
        def __init__(self, widget, func): self.func = func
        def __call__(self): self.func(); return True
        def close(self): pass
    w._make_invoker = Direct
class StubPresenter:                               # the F24/Tcl regression needs no carousel thread
    def __init__(self, root, native, on_cancel): self.hwnd = native.root_handle(root.winfo_id())
    def show(self, snapshot): pass
    def focus_local(self): pass
    def highlight(self, index): pass
    def set_icons(self, icons): pass
    def hide(self): pass
    def close(self): pass
w.PickerOverlay = StubPresenter
root = tk.Tk()
root.withdraw()
ticks, hotkeys, flags = [0], [0], []
def tick():
    ticks[0] += 1
    root.after(2, tick)
def on_hotkey():                                   # tkinter work, as dispatch -> picker show does
    hotkeys[0] += 1
    root.after(50, lambda: None)
    root.tk.call("set", "::nanod_probe", hotkeys[0])
adapter = w.WindowsAdapter(root, on_hotkey, lambda: None, lambda: None)
handler = adapter.native._hotkey_handler
def recording(event_loop=False):
    flags.append(event_loop)
    handler(event_loop=event_loop)
adapter.native._hotkey_handler = recording
adapter.native._hotkey_enabled = True             # no RegisterHotKey: F24 belongs to the companion
u = C.WinDLL("user32")
u.PostMessageW.argtypes = (C.c_void_p, C.c_uint, C.c_size_t, C.c_ssize_t)
u.PostMessageW.restype = C.c_int
def sender():
    for _ in range(30):
        time.sleep(0.01)
        u.PostMessageW(adapter._owner, w.WM_HOTKEY, w.HOTKEY_ID, 0)
threading.Thread(target=sender, daemon=True).start()
root.after(2, tick)
root.after(1200, root.quit)
root.mainloop()
adapter.native._hotkey_enabled = False
result = {"hotkeys": hotkeys[0], "ticks": ticks[0], "flags": flags,
          "invoker": adapter._invoker is not None, "pending": adapter._hotkey_pending}
adapter.close()
root.destroy()
print(json.dumps(result), flush=True)
"""


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class TkThreadStateTests(unittest.TestCase):
    """Regression for the cc4 crash (0xc0000409 fast-fail 7 in ucrtbase, picker open).

    A tkinter call from a ctypes callback that Tcl's notifier dispatched leaves
    _tkinter's thread state NULL; the next Python ``after`` callback in the same
    Tcl_DoOneEvent then hits PyEval_RestoreThread(NULL) -> Py_FatalError -> abort().
    """
    def run_child(self, mode):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "child.py"
            script.write_text(CHILD, encoding="utf-8")
            return subprocess.run([sys.executable, str(script), str(ROOT), mode], capture_output=True,
                                  text=True, timeout=120, cwd=temp,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_f24_runs_through_tcl_and_the_tk_thread_survives(self):
        child = self.run_child("invoker")
        self.assertEqual(child.returncode, 0, child.stderr[-2000:])
        result = json.loads(child.stdout.strip().splitlines()[-1])
        self.assertTrue(result["invoker"])
        self.assertEqual(result["hotkeys"], 30)
        self.assertEqual(result["flags"], [True] * 30, "entered straight from tkinter's mainloop")
        self.assertFalse(result["pending"])
        self.assertGreater(result["ticks"], 20, "Python after-callbacks kept running")

    def test_the_cc4_pattern_aborts_the_process(self):
        child = self.run_child("direct")
        self.assertEqual(child.returncode, 3, "abort() (fast-fail 7 without the quiet abort)")
        self.assertIn("PyEval_RestoreThread", child.stderr)


if __name__ == "__main__":
    unittest.main()

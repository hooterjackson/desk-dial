"""Real hidden-window lifecycle of the floating knob overlay (FLOATING_KNOB.md sections 4 and 7).

SKIPPED unless NANOD_OVERLAY_LIVE_TESTS=1 (Windows only). It creates the real
layered window on a dedicated thread, exactly like the application, but NEVER
shows it: no touch, no peek, no SetWindowPos/ShowWindow show path. It presents a
frame to the hidden window with SourceConstantAlpha 0 (invisible even if it were
shown), rebuilds the DIB twice as a DPI change does (Win32Backend.resize: old
bitmap selected back, old DIB deleted, new DIB created and selected) with the GDI
and USER counts unchanged after each rebuild, checks the window stayed hidden,
destroys everything in the strict order and asserts the process's GDI and USER
object counts return to baseline.

Run it only with the go-ahead for the stage that allows a hidden window:
    set NANOD_OVERLAY_LIVE_TESTS=1
    .venv\\Scripts\\python.exe <guard>\\run_no_tk.py test_cc_overlay_live.py
"""
from pathlib import Path
import math
import os
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from control_center import knob_face  # noqa: E402
from control_center import overlay as ov  # noqa: E402

LIVE = sys.platform == "win32" and os.environ.get("NANOD_OVERLAY_LIVE_TESTS") == "1"
SKIP_REASON = "set NANOD_OVERLAY_LIVE_TESTS=1 (Windows) to create a hidden, never-shown layered window"


def gui_counts(api):
    process = api.k.GetCurrentProcess()
    return (int(api.u.GetGuiResources(process, ov.GR_GDIOBJECTS)),
            int(api.u.GetGuiResources(process, ov.GR_USEROBJECTS)))


def settle_counts(api, baseline, timeout=1.0):
    deadline = time.monotonic() + timeout
    counts = gui_counts(api)
    while counts != baseline and time.monotonic() < deadline:
        time.sleep(0.02)
        counts = gui_counts(api)
    return counts


@unittest.skipUnless(LIVE, SKIP_REASON)
class HiddenWindowLifecycle(unittest.TestCase):
    def setUp(self):
        self.api = ov.OverlayApi()

    def run_on_thread(self, body, timeout=10.0):
        """Run ``body`` on its own thread (it owns the window), re-raising its failure."""
        outcome = {}

        def target():
            try:
                outcome["value"] = body()
            except BaseException as exc:      # reported on the test thread
                outcome["error"] = exc

        thread = threading.Thread(target=target, name="NanoD-overlay-live-test", daemon=True)
        thread.start()
        thread.join(timeout)
        self.assertFalse(thread.is_alive(), "the window thread did not finish")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def test_backend_create_present_hidden_destroy_returns_to_baseline(self):
        baseline = gui_counts(self.api)

        def body():
            result = {}
            backend = ov.Win32Backend()
            try:
                result["awareness"] = backend.prepare_thread()
                work, dpi = backend.geometry()
                result["dpi"] = dpi
                side = 2 * math.ceil(170 * knob_face.scale_for(dpi))
                x, y, width, height, inset = ov.window_rect(work, dpi, (side, side))
                events = []
                backend.create(events.append, (x, y), (width, height))
                result["visible_after_create"] = backend.is_visible()

                def frame_of(box_width, box_height):
                    image = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
                    ImageDraw.Draw(image).ellipse((inset + 8, 8, box_width - 8, box_height - 8),
                                                  fill=(17, 17, 17, 235))
                    return knob_face.premultiplied_bgra(image)
                frame = frame_of(width, height)
                # SourceConstantAlpha 0: nothing could be seen even if the window were visible.
                result["present_full"] = backend.present(frame, (width, height), (x, y), 0, 0)
                result["present_slid"] = backend.present(frame, (width, height), (x, y), width, 0)
                result["visible_after_present"] = backend.is_visible()
                result["during"] = gui_counts(backend.api)
                # A DPI change rebuilds the DIB (FLOATING_KNOB.md section 4): at most one DIB is
                # alive, so the counts stay at "during" after each rebuild and its present.
                rebuilds = []
                for grow in (2, 0):
                    size = (width + grow, height + grow)
                    backend.resize(size)
                    rebuilt = frame_of(*size)
                    presented = backend.present(rebuilt, size, (x, y), 0, 0)
                    rebuilds.append((size, bool(presented), gui_counts(backend.api), backend.is_visible()))
                result["rebuilds"] = rebuilds
                result["notification_state"] = backend.notification_state()
                backend.destroy_window()
                result["quit_posted"] = not backend.pump()     # WM_DESTROY -> PostQuitMessage
                backend.unregister()
                result["events"] = list(events)
            finally:
                backend.destroy()
            return result

        result = self.run_on_thread(body)
        self.assertEqual(result["awareness"], ov.DPI_AWARENESS_PER_MONITOR_AWARE)
        self.assertGreaterEqual(result["dpi"], 96)
        self.assertFalse(result["visible_after_create"])
        self.assertTrue(result["present_full"])
        self.assertTrue(result["present_slid"])
        self.assertFalse(result["visible_after_present"])
        self.assertGreaterEqual(result["during"][0], baseline[0] + 2)   # memory DC + DIB section
        self.assertGreaterEqual(result["during"][1], baseline[1] + 1)   # the window
        self.assertEqual(len(result["rebuilds"]), 2)
        for size, presented, counts, visible in result["rebuilds"]:
            with self.subTest(size=size):
                self.assertTrue(presented)
                self.assertEqual(counts, result["during"], "a DIB rebuild leaked or lost a GDI/USER object")
                self.assertFalse(visible)
        self.assertTrue(result["quit_posted"])
        after = settle_counts(self.api, baseline)
        print(f"\n[overlay live] backend: dpi {result['dpi']}, GDI/USER baseline {baseline}, "
              f"during {result['during']}, after DIB rebuilds "
              f"{[(size, counts) for size, _ok, counts, _v in result['rebuilds']]}, after {after}, "
              f"visible after create/present {result['visible_after_create']}/{result['visible_after_present']}",
              flush=True)
        self.assertEqual(after, baseline)

    def test_knob_overlay_start_and_close_never_show_and_return_to_baseline(self):
        baseline = gui_counts(self.api)
        for _round in range(2):                     # the second round re-registers the class
            overlay = ov.KnobOverlay()      # the real knob_face.KnobFace
            try:
                self.assertTrue(overlay.start(), overlay.metrics()["last_error"])
                self.assertEqual(overlay.state, ov.HIDDEN)
                self.assertFalse(overlay.wants_frames)
                self.assertEqual(overlay._thread.name, "NanoD-overlay")
                backend = overlay._backend
                self.assertFalse(backend.is_visible())
                self.assertTrue(overlay.hwnd)                        # the carousel's capture exclusion
                self.assertEqual(overlay.hwnd, backend.hwnd)
                metrics = overlay.metrics()
                during = (metrics["gdi_objects"], metrics["user_objects"])
                self.assertEqual(metrics["dpi_awareness"], ov.DPI_AWARENESS_PER_MONITOR_AWARE)
                self.assertGreater(metrics["gdi_objects"], baseline[0])
                x, y, width, height = overlay.rect
                self.assertEqual((width, height), tuple(metrics["window_px"]))
                # A scene submitted while hidden is stored, never presented.
                lcd = Image.new("RGBA", (overlay.lcd_px, overlay.lcd_px), (0, 0, 0, 255))
                overlay.submit(ov.OverlayScene(("live", overlay.lcd_px), lcd, ov.BLANK_RING))
                time.sleep(0.1)
                self.assertFalse(backend.is_visible())
                self.assertEqual(overlay.metrics()["frames_presented"], 0)
                started = time.monotonic()
                self.assertTrue(overlay.close())
                self.assertLessEqual(time.monotonic() - started, ov.CLOSE_TIMEOUT_SECONDS + 0.1)
                self.assertFalse(overlay._thread.is_alive())
                self.assertIsNone(backend.hwnd)
                self.assertEqual(overlay.hwnd, 0)
                self.assertFalse(backend.registered)
            finally:
                overlay.close()
            after = settle_counts(self.api, baseline)
            print(f"\n[overlay live] KnobOverlay round {_round + 1}: dpi {metrics['dpi']}, window {metrics['window_px']}, "
                  f"lcd {metrics['lcd_px']}, GDI/USER baseline {baseline}, during {during}, after {after}, "
                  f"frames presented {metrics['frames_presented']}", flush=True)
            self.assertEqual(after, baseline)


if __name__ == "__main__":
    unittest.main()

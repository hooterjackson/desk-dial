"""App profiles in the runtime and the controller (plan sections 1c / 1f / 3 / 6, S1 DD-B): per-app Auto from the
detector, the injector activated with the app's profile, the upload on the first activation and the canvas once the
knob confirmed it (text screens before, on failure and on older knobs), Onshape always on its built-in canvas,
re-upload after a reconnect, Off releasing at once, reload, the Settings / tray interface, status.json `app`, and the
privacy rule: no title, URL or host in any log or status. Simulated device and fake windows: no port, no window, no
SendInput."""
from pathlib import Path
import io
import json
import logging
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cc5_support import Clock, FakeDevice, ManualExecutor  # noqa: E402
from test_onshape import FakeBackend  # noqa: E402

from control_center import app_detect, device  # noqa: E402
from control_center.app_profiles import Library  # noqa: E402
from control_center.controller import Controller  # noqa: E402
from control_center.onshape import OnshapeInjector  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import (SimControls, SimulatedAppleMusic, SimulatedHomeAssistant,  # noqa: E402
                                       SimulatedSonos, SimulatedWindows)

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
CAPS_CANVAS = {"controlCenter": True, "presentation": 6, "appCanvas": 1}
CAPS_PROFILES = dict(CAPS_CANVAS, appProfiles=1, appProfileSlots=4, appProfileMaxBytes=32768, appProfileFeatures=31)


class FakeDetector:
    """app_detect.AppDetector's contract: detect(now, profiles) -> (id, matched_by) among `profiles`."""

    def __init__(self, value=(None, None)):
        self.value = value
        self.calls = 0
        self.paused = 0
        self.seen = []

    def detect(self, now, profiles):
        self.calls += 1
        ids = [p.id for p in profiles]
        self.seen.append(ids)
        return self.value if self.value[0] in ids else (None, None)

    def pause(self):
        self.paused += 1

    def close(self):
        pass


class Harness:
    def __init__(self, testcase, caps=CAPS_PROFILES, modes=None, detector=None, rules=None, order=None,
                 injector=True):
        patcher = patch("control_center.runtime.ThreadPoolExecutor", ManualExecutor)
        patcher.start()
        testcase.addCleanup(patcher.stop)
        self.device = FakeDevice()
        self.c = Controller(clock=Clock(), rng=random.Random(3))
        self.backend = FakeBackend()
        self.injector = OnshapeInjector(self.backend, start=False) if injector else None
        self.detector = detector if detector is not None else FakeDetector()
        self.library = Library(PROFILES)
        self.runtime = Runtime(self.c, SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), self.device,
                               ha=SimulatedHomeAssistant(SimControls()), onshape=self.injector,
                               onshape_focus=self.detector, app_library=self.library,
                               app_modes=modes if modes is not None else {"onshape": "auto", "figma": "auto",
                                                                          "plasticity": "manual"},
                               app_rules=rules, app_order=order)
        testcase.addCleanup(self.runtime.shutdown)
        self.connect(caps)

    def connect(self, caps):
        inventory = {name: {"knob": [{"haptic": {"detentCount": count}}]}
                     for name, count in (("BINARIS BEER", 67), ("MIDI SKIPPER", 24), ("MIDI CLACK JONES", 12))}
        self.device.events.put({"kind": "connected", "profiles": inventory, "capabilities": caps})
        self.runtime.poll()
        self.ready()

    def ready(self, held=0):
        self.device.events.put({"kind": "ready", "id": self.c.control_id, "held": held})
        self.runtime.poll()

    def event(self, kind, **values):
        values.setdefault("id", self.c.control_id)
        self.device.events.put({"kind": kind, **values})
        self.runtime.poll()

    def tick(self, now):
        with patch("control_center.runtime.time.monotonic", return_value=now):
            self.runtime.poll()

    def uploads(self):
        return [c[1] for c in self.device.commands if c[0] == "app_profile"]

    def loaded(self, pid):
        profile = self.library.get(pid)
        self.event("app-profile", id=pid, crc=profile.wire_crc, state="loaded", bytes=len(profile.wire()), ms=120)

    def frame(self):
        return self.c.frame()


class FigmaAutoTests(unittest.TestCase):
    def test_auto_enters_uploads_then_draws_the_canvas(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        self.assertEqual((h.c.screen.mode, h.c.app_id()), ("onshape", "figma"))
        h.injector.step()
        self.assertEqual(h.injector.app_status()["profile"], "figma")
        frame = h.frame()
        self.assertEqual((frame["heading"], frame["title"]), ("FIGMA", "ZOOM"))
        self.assertEqual(frame["subtitle"], "UNDO · DEPTH · WHEEL · FRAME")
        self.assertNotIn("app", frame, "uploading: the text screen")
        uploads = h.uploads()
        profile = h.library.get("figma")
        self.assertEqual([(u["id"], u["crc"], u["wire"]) for u in uploads],
                         [("figma", profile.wire_crc, profile.wire())])
        self.assertEqual(h.runtime.app_status()["upload"]["state"], "uploading")
        h.tick(1000.1)
        self.assertEqual(len(h.uploads()), 1, "one upload, not one per tick")
        h.loaded("figma")
        h.tick(1000.2)
        frame = h.frame()
        self.assertEqual(frame["app"], {"id": "figma", "crc": profile.wire_crc, "slot": "knob", "flash": 0})
        self.assertIn("app", device._frame(dict(frame, id=3), CAPS_PROFILES))
        self.assertNotIn("app", device._frame(dict(frame, id=3), CAPS_CANVAS), "never to an older parser")
        self.assertEqual(h.runtime.app_status()["upload"], {"state": "loaded", "id": "figma",
                                                            "bytes": len(profile.wire()), "ms": 120, "error": None})

    def test_the_held_slot_is_the_frame_slot(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        h.loaded("figma")
        h.event("button", button=3, index=3)
        h.injector.step()                        # the injector thread publishes its state
        h.tick(1000.1)
        self.assertEqual(h.frame()["app"]["slot"], "f4")
        self.assertEqual(h.frame()["title"], "FRAMES")

    def test_focus_loss_leaves_after_500_ms_and_releases_at_once(self):
        detector = FakeDetector(("figma", "exe"))
        h = Harness(self, detector=detector)
        h.tick(1000.0)
        h.injector.step()
        detector.value = (None, None)
        h.tick(1000.1)
        self.assertEqual(h.c.app_id(), "figma", "not at once")
        h.injector.step()
        self.assertEqual(h.injector.status()["releases"], {}, "nothing was held")
        h.tick(1000.7)
        self.assertNotEqual(h.c.screen.mode, "onshape")

    def test_a_user_exit_suppresses_auto_until_focus_is_lost_and_regained(self):
        detector = FakeDetector(("figma", "exe"))
        h = Harness(self, detector=detector)
        h.tick(1000.0)
        self.assertIsNone(h.runtime.toggle_app("figma"))
        h.tick(1000.1)
        self.assertNotEqual(h.c.screen.mode, "onshape")
        h.tick(1001.0)
        self.assertNotEqual(h.c.screen.mode, "onshape", "suppressed while it stays in front")
        self.assertEqual(h.runtime.app_status()["suppressed"], ["figma"])
        detector.value = (None, None)
        h.tick(1001.5)
        detector.value = ("figma", "exe")
        h.tick(1002.0)
        self.assertEqual(h.c.app_id(), "figma")

    def test_auto_switches_between_two_auto_apps(self):
        detector = FakeDetector(("figma", "exe"))
        h = Harness(self, detector=detector, modes={"figma": "auto", "plasticity": "auto"})
        h.tick(1000.0)
        detector.value = ("plasticity", "exe")
        h.tick(1000.1)
        self.assertEqual(h.c.app_id(), "plasticity")
        h.injector.step()
        self.assertEqual(h.injector.app_status()["profile"], "plasticity")

    def test_manual_apps_never_enter_by_themselves(self):
        h = Harness(self, detector=FakeDetector(("plasticity", "exe")))
        h.tick(1000.0)
        self.assertNotEqual(h.c.screen.mode, "onshape")
        self.assertEqual(h.runtime.app_status()["focused"], "plasticity")
        self.assertIsNone(h.runtime.toggle_app("plasticity"))
        self.assertEqual(h.c.app_id(), "plasticity")


class KnobCapabilityTests(unittest.TestCase):
    def test_onshape_always_draws_the_built_in_canvas(self):
        h = Harness(self, detector=FakeDetector(("onshape", "host")))
        h.tick(1000.0)
        self.assertEqual(h.c.app_id(), "onshape")
        h.injector.step()
        h.tick(1000.1)
        frame = h.frame()
        self.assertEqual(frame["app"]["id"], "onshape")
        self.assertNotIn("crc", frame["app"])
        self.assertIn(frame["app"]["slot"], ("zoom", "orbit", "pan", "tilt"))
        self.assertEqual(h.uploads(), [], "Onshape is never uploaded")
        self.assertEqual(frame["heading"], "ONSHAPE")

    def test_a_knob_without_app_profiles_gets_text_screens(self):
        h = Harness(self, caps=CAPS_CANVAS, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        h.tick(1000.1)
        self.assertEqual(h.c.app_id(), "figma")
        self.assertEqual(h.uploads(), [])
        self.assertNotIn("app", h.frame())
        self.assertEqual(h.frame()["heading"], "FIGMA")

    def test_an_older_knob_without_the_canvas_too(self):
        h = Harness(self, caps={"controlCenter": True, "presentation": 6}, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        self.assertEqual(h.c.app_id(), "figma")
        self.assertEqual(h.uploads(), [])

    def test_a_failed_upload_releases_and_keeps_the_text_screen(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        h.injector.step()
        h.event("button", button=1, index=1)
        profile = h.library.get("figma")
        h.event("app-profile", id="figma", crc=profile.wire_crc, state="failed", bytes=10, ms=2000, error="timeout")
        h.injector.step()
        h.tick(1000.2)
        self.assertNotIn("app", h.frame())
        self.assertEqual(h.runtime.app_status()["upload"]["state"], "failed")
        self.assertEqual(len(h.uploads()), 1, "not retried on this connection")

    def test_a_reconnect_uploads_again(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        h.loaded("figma")
        h.event("disconnected")
        h.connect(CAPS_PROFILES)
        h.tick(1001.0)
        h.tick(1001.1)
        self.assertEqual(len(h.uploads()), 2, "the knob's store is RAM only")


class ModesAndInterfaceTests(unittest.TestCase):
    def test_off_releases_at_once(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        h.injector.step()
        h.event("button", button=1, index=1)
        h.runtime.set_app_mode("figma", "off")
        self.assertNotEqual(h.c.screen.mode, "onshape")
        h.injector.step()
        self.assertFalse(h.injector.status()["active"])
        self.assertEqual(h.runtime.app_modes()["figma"], "off")

    def test_every_app_off_reads_nothing(self):
        detector = FakeDetector(("figma", "exe"))
        h = Harness(self, detector=detector, modes={"onshape": "off"})
        for t in range(20):
            h.tick(1000.0 + t * 0.3)
        self.assertEqual(detector.calls, 0)
        h.runtime.set_app_mode("figma", "auto")
        h.tick(1010.0)
        self.assertEqual(detector.calls, 1)
        self.assertEqual(detector.seen[-1], ["figma"], "only the apps that are on")
        h.runtime.toggle_app("figma")
        h.runtime.set_app_mode("figma", "off")
        h.tick(1011.0)
        self.assertGreaterEqual(detector.paused, 1)

    def test_app_rows_menu_and_messages(self):
        h = Harness(self)
        rows = {r["id"]: r for r in h.runtime.app_rows()}
        self.assertEqual(list(rows), ["onshape", "figma", "plasticity", "blender", "autocad"])
        figma = rows["figma"]
        self.assertEqual(set(figma), {"id", "name", "status", "source", "mode", "detect_summary", "active", "focused",
                                      "warnings", "icon24"})
        self.assertEqual((figma["name"], figma["status"], figma["source"], figma["mode"]),
                         ("Figma", "community", "bundled", "auto"))
        self.assertEqual(len(figma["icon24"]), 24 * 24 * 2)
        self.assertIn("Figma.exe", figma["detect_summary"])
        self.assertEqual(rows["autocad"]["name"], "AutoCAD")
        self.assertEqual(h.runtime.app_menu()[0], ("onshape", "Onshape", False))
        self.assertIn("Settings", h.runtime.toggle_app("blender"))
        self.assertIsNone(h.runtime.toggle_app("figma"))
        self.assertEqual(dict((i, c) for i, _l, c in h.runtime.app_menu())["figma"], True)
        self.assertTrue({r["id"]: r for r in h.runtime.app_rows()}["figma"]["active"])
        self.assertIsNone(h.runtime.toggle_app("figma"), "the second toggle leaves")
        self.assertNotEqual(h.c.screen.mode, "onshape")

    def test_rules_and_order(self):
        detector = FakeDetector(("figma", "exe"))
        h = Harness(self, detector=detector, rules={"figma": {"exe": ["FigmaBeta.exe"]}},
                    order=["plasticity", "figma", "onshape"])
        self.assertEqual([p for p, _l, _c in h.runtime.app_menu()][:3], ["plasticity", "figma", "onshape"])
        h.tick(1000.0)
        figma = next(p for p in detector.seen and h.runtime._app_candidates(None) if p.id == "figma")
        self.assertIn("FigmaBeta.exe", figma.detect.exe)
        self.assertIn("FigmaBeta.exe", {r["id"]: r for r in h.runtime.app_rows()}["figma"]["detect_summary"])

    def test_reload_releases_first(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        h.injector.step()
        h.event("button", button=1, index=1)
        self.assertEqual(h.runtime.reload_profiles(), [])
        h.injector.step()
        self.assertEqual(h.c.app_id(), "figma")
        self.assertIsNotNone(h.runtime.app_status()["active"])

    def test_the_legacy_onshape_interface_still_works(self):
        h = Harness(self, modes={})
        self.assertIn("Settings", h.runtime.toggle_onshape())
        h.runtime.set_onshape_mode("manual")
        self.assertEqual(h.runtime.app_modes()["onshape"], "manual")
        self.assertIsNone(h.runtime.toggle_onshape())
        self.assertEqual(h.runtime.onshape_menu_text(), "Leave Onshape mode")
        self.assertEqual(set(h.runtime.onshape_status()), {"mode", "active", "pending", "focused", "suppressed",
                                                            "profile", "refusals", "injector"})

    def test_app_status_fields(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        status = h.runtime.app_status()
        self.assertEqual(set(status), {"mode_by_id", "active", "pending", "focused", "matched_by", "suppressed",
                                       "profile", "upload", "injector"})
        self.assertEqual((status["active"], status["focused"], status["matched_by"]), ("figma", "figma", "exe"))
        self.assertEqual(status["profile"], "BINARIS BEER")
        self.assertIn("keyboardRefused", status["injector"])

    def test_bounds_and_feel_for_every_app(self):
        h = Harness(self, detector=FakeDetector(("plasticity", "exe")), modes={"plasticity": "auto"})
        h.tick(1000.0)
        self.assertEqual(h.c.bounds(), (0, 60000, 30000))
        self.assertEqual(h.c.feel(), "fluid.light", "Plasticity's knob drags (zoom)")
        h2 = Harness(self, detector=FakeDetector(("figma", "exe")))
        h2.tick(1000.0)
        self.assertEqual((h2.c.bounds(), h2.c.feel()), ((0, 60000, 30000), "detent.value"))
        self.assertEqual(h2.c.control()["profile"], "BINARIS BEER")

    def test_the_home_chord_leaves_any_app(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        with patch("control_center.runtime.time.monotonic", return_value=1000.0):
            h.runtime.poll()
        for raw in range(4):
            h.event("button", button=raw, index=raw)
        h.c.clock.advance(1.1)
        h.tick(1001.2)
        self.assertNotEqual(h.c.screen.mode, "onshape")
        self.assertEqual(h.runtime.app_status()["suppressed"], ["figma"])


class RefusalCopyTests(unittest.TestCase):
    """The new refusals say why on the knob: the text screen, even over a canvas (COPY knob.*.keyboard_refused /
    disabled_refused)."""

    def test_an_app_shows_not_on_this_keyboard_and_not_on_windows(self):
        h = Harness(self, detector=FakeDetector(("figma", "exe")))
        h.tick(1000.0)
        h.loaded("figma")
        h.injector.step()
        h.tick(1000.1)
        self.assertIn("app", h.frame())
        h.c.onshape_input("keyboard_refused")
        frame = h.frame()
        self.assertEqual((frame["title"], frame["subtitle"]), ("Not on this keyboard", "Its key needs another layout"))
        self.assertNotIn("app", frame, "the canvas gives way to the text for the moment")
        h.c.clock.advance(2.1)
        self.assertIn("app", h.frame())
        h.c.onshape_input("disabled_refused")
        self.assertEqual(h.frame()["title"], "Not on Windows")
        h.c.clock.advance(2.1)
        h.c.onshape_input("refused")
        self.assertEqual(h.frame()["title"], "Point at the app")
        self.assertTrue(h.frame()["app"]["refused"])

    def test_onshape_too(self):
        h = Harness(self, detector=FakeDetector(("onshape", "host")))
        h.tick(1000.0)
        h.injector.step()
        h.tick(1000.1)
        self.assertIn("app", h.frame())
        h.c.onshape_input("keyboard_refused")
        self.assertEqual(h.frame()["title"], "Not on this keyboard")
        self.assertNotIn("app", h.frame())


class PrivacyTests(unittest.TestCase):
    """A fake window titled SECRET-TITLE whose address bar reads https://secret.example/path: neither (nor the host)
    reaches any log handler or app_status / onshape_status."""

    TITLE, URL = "SECRET-TITLE", "https://secret.example/path"

    class Windows:
        def __init__(self, title, url, hosts):
            self.title, self.url, self.hosts = title, url, hosts
            self.u = None

        def foreground(self):
            return 0x1234

        def pid(self, hwnd):
            return 42

        def exe(self, pid):
            return "chrome.exe"

        def title_key(self, hwnd):
            return (int(hwnd), hash(self.title))

        def host(self, hwnd):
            return self.hosts.lookup(hwnd, self.title_key(hwnd))

        def onshape_title(self, hwnd):
            return False

    def test_no_title_url_or_host_anywhere(self):
        from control_center.browser_url import host_of
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        hosts = app_detect.AddressHosts(reader=lambda hwnd: host_of(self.URL))
        windows = self.Windows(self.TITLE, self.URL, hosts)
        detector = app_detect.AppDetector(windows, hook=False)
        rules = {"figma": {"host": ["secret.example"]}}
        h = Harness(self, detector=detector, rules=rules)
        h.backend.cursor = lambda: (_ for _ in ()).throw(RuntimeError(self.TITLE + " " + self.URL))
        for t in range(12):
            h.tick(1000.0 + t * 0.3)
            if hosts._thread is not None:
                hosts._thread.join(0.05)
        self.assertEqual(h.c.app_id(), "figma", "matched by the host")
        self.assertEqual(h.runtime.app_status()["matched_by"], "host")
        h.injector.post("position", {"id": h.c.control_id, "delta": 1})
        h.injector.step()                        # the backend raises with the secret text: logged by type only
        h.runtime.reload_profiles()
        h.tick(1010.0)
        handler.flush()
        text = stream.getvalue() + json.dumps(h.runtime.app_status()) + json.dumps(h.runtime.onshape_status()) \
            + json.dumps(h.runtime.app_rows(), default=lambda b: None) + repr(h.runtime.app_menu())
        self.assertIn("RuntimeError", stream.getvalue(), "the exception's type is logged")
        for secret in (self.TITLE, self.URL, "secret.example/path"):
            self.assertNotIn(secret, text)
        logged = stream.getvalue() + json.dumps(h.runtime.app_status()) + json.dumps(h.runtime.onshape_status())
        self.assertNotIn("secret.example", logged, "not even the host")


if __name__ == "__main__":
    unittest.main()

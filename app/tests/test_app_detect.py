"""App detection and the per-app window gates (plan sections 3a / 3b / 6, S1 DD-B): program then host matching, a
host rule beating a program rule, ties by Settings order, exclusions, the owner's rules, the detector's poll / cache /
pause (nothing read with no apps), Onshape's strict title fallback, and the cursor / keyboard gates for browser and
desktop apps over fake window primitives. Headless: no window is read."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import app_detect as D  # noqa: E402
from control_center.app_profiles import load_pair  # noqa: E402
from control_center.onshape import host_is_onshape  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"


def bundled(pid):
    return load_pair(PROFILES / "karl" / f"{pid}.json", PROFILES / f"{pid}.windows.json")


ALL = [bundled(pid) for pid in ("onshape", "figma", "plasticity", "blender", "autocad")]


class MatchTests(unittest.TestCase):
    def test_programs(self):
        self.assertEqual(D.match_app(ALL, r"C:\Program Files\Blender\blender.exe", None), ("blender", "exe"))
        self.assertEqual(D.match_app(ALL, "Plasticity.exe", None), ("plasticity", "exe"))
        self.assertEqual(D.match_app(ALL, "acad.exe", None), ("autocad", "exe"))
        self.assertEqual(D.match_app(ALL, "notepad.exe", None), (None, None))
        self.assertEqual(D.match_app(ALL, "", None), (None, None))

    def test_hosts_in_chromium_browsers_only(self):
        for exe in ("chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe", "Chrome.EXE"):
            self.assertEqual(D.match_app(ALL, exe, "cad.onshape.com"), ("onshape", "host"), exe)
            self.assertEqual(D.match_app(ALL, exe, "www.figma.com"), ("figma", "host"), exe)
        self.assertEqual(D.match_app(ALL, "firefox.exe", "cad.onshape.com"), (None, None), "Firefox is out of v1")
        self.assertEqual(D.match_app(ALL, "notepad.exe", "cad.onshape.com"), (None, None))

    def test_exclusions_are_honoured(self):
        for host in ("www.onshape.com", "learn.onshape.com", "forum.onshape.com", "help.figma.com", "evilonshape.com",
                     "cad.onshape.com.evil.net"):
            self.assertEqual(D.match_app(ALL, "chrome.exe", host), (None, None), host)
        for host in ("cad.onshape.com", "acme.onshape.com", "www.onshape.com", "figma.com"):
            self.assertEqual(D.match_app(ALL[:1], "chrome.exe", host)[0] == "onshape", host_is_onshape(host), host)

    def test_a_host_rule_beats_a_program_rule_and_order_breaks_ties(self):
        figma, onshape = bundled("figma"), bundled("onshape")
        # The owner adds chrome.exe to Figma's programs: Onshape's host rule still wins in an Onshape tab.
        greedy = D.with_rules(figma, {"figma": {"exe": ["chrome.exe"]}})
        self.assertEqual(D.match_app([greedy, onshape], "chrome.exe", "cad.onshape.com"), ("onshape", "host"))
        self.assertEqual(D.match_app([greedy, onshape], "chrome.exe", "example.com"), ("figma", "exe"))
        both = D.with_rules(onshape, {"onshape": {"host": ["www.figma.com"]}})
        self.assertEqual(D.match_app([figma, both], "chrome.exe", "www.figma.com"), ("figma", "host"))
        self.assertEqual(D.match_app([both, figma], "chrome.exe", "www.figma.com"), ("onshape", "host"),
                         "a tie goes to the earlier one in Settings")

    def test_rules_merge_without_duplicates(self):
        figma = bundled("figma")
        merged = D.with_rules(figma, {"figma": {"exe": ["Figma.exe", "FigmaBeta.exe"], "host": ["*.figma.site"]}})
        self.assertEqual(merged.detect.exe, ("Figma.exe", "FigmaBeta.exe"))
        self.assertEqual(merged.detect.host, ("figma.com", "www.figma.com", "*.figma.site"))
        self.assertIs(D.with_rules(figma, {}), figma)
        self.assertIs(D.with_rules(figma, {"figma": {"exe": ["Figma.exe"]}}), figma)

    def test_ordered_and_summary(self):
        self.assertEqual([p.id for p in D.ordered(ALL, ["autocad", "figma"])],
                         ["autocad", "figma", "onshape", "plasticity", "blender"])
        self.assertEqual(D.detect_summary(bundled("plasticity")), "Plasticity.exe")
        self.assertIn("cad.onshape.com", D.detect_summary(bundled("onshape")))


class FakeWindows:
    """The primitives AppDetector and gate_target read; every call counted."""

    def __init__(self):
        self.fg, self.pids, self.exes, self.hosts = 0x100, {0x100: 7, 0x200: 8}, {7: "chrome.exe", 8: "blender.exe"}, {}
        self.reads = 0
        self.under = 0x101            # the window under the cursor
        self.roots = {0x101: 0x100, 0x201: 0x200}
        self.classes = {0x101: "Chrome_RenderWidgetHostHWND", 0x201: "GHOST_WindowClass"}
        self.title_onshape = False
        self.focus = 7
        self.u = None

    def foreground(self):
        self.reads += 1
        return self.fg

    def pid(self, hwnd):
        return self.pids.get(hwnd, 0)

    def exe(self, pid):
        return self.exes.get(pid, "")

    def host(self, hwnd):
        return (True, self.hosts.get(hwnd)) if hwnd in self.hosts else (True, None)

    def onshape_title(self, hwnd):
        return self.title_onshape

    def window_from_point(self, point):
        return self.under

    def root(self, hwnd):
        return self.roots.get(hwnd, 0)

    def class_name(self, hwnd):
        return self.classes.get(hwnd, "")

    def focus_pid(self):
        return self.focus


class DetectorTests(unittest.TestCase):
    def make(self):
        self.now = [100.0]
        self.w = FakeWindows()
        return D.AppDetector(self.w, clock=lambda: self.now[0], hook=False)

    def test_nothing_is_read_without_apps(self):
        detector = self.make()
        for _ in range(10):
            self.assertEqual(detector.detect(None, []), (None, None))
        self.assertEqual(self.w.reads, 0)

    def test_the_poll_reads_every_250_ms_and_a_new_app_list_at_once(self):
        detector = self.make()
        self.w.hosts[0x100] = "www.figma.com"
        self.assertEqual(detector.detect(None, ALL), ("figma", "host"))
        self.now[0] += 0.1
        detector.detect(None, ALL)
        self.assertEqual(self.w.reads, 1)
        self.now[0] += 0.2
        detector.detect(None, ALL)
        self.assertEqual(self.w.reads, 2)
        detector.detect(None, ALL[:1])
        self.assertEqual(self.w.reads, 3, "another set of apps: read again")

    def test_a_desktop_app_by_its_program(self):
        detector = self.make()
        self.w.fg = 0x200
        self.assertEqual(detector.detect(None, ALL), ("blender", "exe"))

    def test_onshape_title_fallback_only_when_the_address_is_unreadable(self):
        detector = self.make()
        self.w.title_onshape = True
        self.assertEqual(detector.detect(None, ALL), ("onshape", "host"))
        self.now[0] += 1
        self.w.hosts[0x100] = "www.onshape.com"
        self.assertEqual(detector.detect(None, ALL), (None, None), "DD-SEC-002: the host decides")

    def test_focused_keeps_the_focus_watcher_contract(self):
        detector = self.make()
        self.w.hosts[0x100] = "cad.onshape.com"
        self.assertTrue(detector.focused(None))
        self.now[0] += 1
        self.w.hosts[0x100] = "example.com"
        self.assertFalse(detector.focused(None))

    def test_pause_forgets(self):
        detector = self.make()
        self.w.hosts[0x100] = "cad.onshape.com"
        detector.detect(None, ALL)
        detector.pause()
        detector.detect(None, ALL)
        self.assertEqual(self.w.reads, 2)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.w = FakeWindows()

    def test_a_browser_app_needs_the_content_widget_the_host_and_the_foreground(self):
        figma = bundled("figma")
        self.w.hosts[0x100] = "www.figma.com"
        self.assertTrue(D.gate_target(self.w, figma, (1, 1)))
        self.w.classes[0x101] = "Chrome_WidgetWin_1"            # the tab strip
        self.assertFalse(D.gate_target(self.w, figma, (1, 1)))
        self.w.classes[0x101] = "Chrome_RenderWidgetHostHWND"
        self.w.hosts[0x100] = "help.figma.com"
        self.assertFalse(D.gate_target(self.w, figma, (1, 1)))
        self.w.hosts[0x100] = "www.figma.com"
        self.w.fg = 0x200                                        # another window in front
        self.assertFalse(D.gate_target(self.w, figma, (1, 1)))

    def test_a_desktop_app_needs_its_program(self):
        blender = bundled("blender")
        self.w.fg, self.w.under = 0x200, 0x201
        self.assertTrue(D.gate_target(self.w, blender, (1, 1)))
        self.assertFalse(D.gate_target(self.w, bundled("plasticity"), (1, 1)))
        self.assertFalse(D.gate_target(self.w, bundled("onshape"), (1, 1)), "no host rule in Blender")
        self.w.under = 0x101                                     # the cursor over another window
        self.assertFalse(D.gate_target(self.w, blender, (1, 1)))

    def test_a_sidecar_content_class_narrows_a_desktop_app(self):
        from dataclasses import replace
        from control_center.app_profiles import Detect
        blender = bundled("blender")
        narrow = replace(blender, detect=Detect(exe=("blender.exe",), content_class=("GHOST_WindowClass",)))
        self.w.fg, self.w.under = 0x200, 0x201
        self.assertTrue(D.gate_target(self.w, narrow, (1, 1)))
        self.w.classes[0x201] = "Popup"
        self.assertFalse(D.gate_target(self.w, narrow, (1, 1)))

    def test_desktop_keyboard_focus_must_be_in_the_apps_process(self):
        windows = D.AppWindows.__new__(D.AppWindows)
        windows.profile = bundled("blender")
        windows.foreground = lambda: 0x200
        windows.pid = lambda hwnd: 8
        windows.exe = lambda pid: "blender.exe"
        windows.focus_pid = lambda: 8
        self.assertTrue(windows.keyboard_ok((1, 1)))
        windows.focus_pid = lambda: 9                            # a dialog of another process has the focus
        self.assertFalse(windows.keyboard_ok((1, 1)))


if __name__ == "__main__":
    unittest.main()

"""Carousel labels (control_center.window_labels) against CAROUSEL.md section 6.

Pure: no ctypes, no Tk, no windows. Every string here is either a README example or a
synthetic string shaped like the real titles the mapping probes observed (redacted
shapes only; no real title, profile or monitor name appears in this file).

Deliberate differences from the scratch draft (CAROUSEL.md is normative):
- the generic description is the app name (the README said the process name);
- Meet reads "In a call · <app>" / "Meeting · <app>" with the app display name
  ("Google Chrome");
- a browser page without a trailing site segment is described by the app name
  (the draft said "Web page"); the tab badge needs 2..99 (so "404 - ..." is a page).
"""
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center import window_labels as wl  # noqa: E402
from control_center.window_labels import (  # noqa: E402
    CLOSED_DESC, Label, WindowFacts as F, app_display_name, closed_label, disambiguate, label_for,
    meet_window, normalize_title, profile_from_relaunch_name, title_case_stem,
)

TODAY = date(2026, 9, 24)
CHROME = ("chrome.exe", "Google Chrome")
EDGE = ("msedge.exe", "Microsoft Edge")
CAL ="Riot Games - Calendar - Week of September 22, 2026 - Google Chrome"


def L(exe, app, title, **kw):
    lab = label_for(F(exe, app, title, **kw), TODAY)
    return lab.title, lab.desc


def A(exe, app, title, **kw):
    return label_for(F(exe, app, title, **kw), TODAY).app


class ReadmeTable(unittest.TestCase):
    """Every row of the handoff README's title table (and the prototype's samples)."""

    def test_slack_dm(self):
        self.assertEqual(L("Slack.exe", "Slack", "Danny Lewis (DM) - Riot Games - Slack"),
                         ("Danny Lewis", "Direct message · Riot Games"))

    def test_slack_channel(self):
        self.assertEqual(L("Slack.exe", "Slack", "#channel - Workspace - Slack"), ("#channel", "Channel · Workspace"))

    def test_chrome_calendar(self):
        self.assertEqual(L(*CHROME, CAL), ("Calendar · Week of Sep 22", "Riot Games · Google Calendar"))

    def test_chrome_tab_count(self):
        self.assertEqual(L(*CHROME, "9 - Understand the PCB - Engineering docs - Google Chrome"),
                         ("Understand the PCB", "Engineering docs · 9 tabs"))

    def test_chrome_meet_audible(self):
        self.assertEqual(L(*CHROME, "Meet - abc-defg-hij - Google Chrome", audible=True),
                         ("Google Meet", "In a call · Google Chrome"))

    def test_chrome_meet_not_answered_yet(self):
        self.assertEqual(L(*CHROME, "Meet - abc-defg-hij - Google Chrome", audible=None),
                         ("Google Meet", "Meeting · Google Chrome"))

    def test_chrome_meet_answered_silent(self):
        self.assertEqual(L(*CHROME, "Meet - abc-defg-hij - Google Chrome", audible=False),
                         ("Google Meet", "Meeting · Google Chrome"))

    def test_bambu_unsaved(self):
        self.assertEqual(L("bambu-studio.exe", "Bambu Studio", "*Rack_Base(2) - BambuStudio"),
                         ("Rack_Base(2)", "Unsaved changes · 3D print project"))

    def test_explorer_minimized(self):
        self.assertEqual(L("explorer.exe", "File Explorer", "Downloads - File Explorer",
                           class_name="CabinetWClass", minimized=True), ("Downloads", "Folder · Minimized"))

    def test_claude_conversation(self):
        self.assertEqual(L("claude.exe", "Claude", "Nano D Control Center"),
                         ("Nano D Control Center", "Conversation · desktop app"))

    def test_chatgpt_conversation(self):
        self.assertEqual(L("ChatGPT.exe", "ChatGPT", "PCB layout questions"),
                         ("PCB layout questions", "Conversation · desktop app"))

    def test_claude_blank_title(self):
        self.assertEqual(L("claude.exe", "Claude", ""), ("Claude", "Desktop app"))

    def test_fallback_is_title_and_app_name(self):
        self.assertEqual(L("Discord.exe", "Discord", "general - Discord"), ("general", "Discord"))

    def test_fallback_minimized(self):
        self.assertEqual(L("Discord.exe", "Discord", "general - Discord", minimized=True),
                         ("general", "Discord · Minimized"))

    def test_steam_description_override(self):   # prototype: Steam / Library / Game launcher · Minimized
        self.assertEqual(L("steamwebhelper.exe", "Steam", "Library", minimized=True),
                         ("Library", "Game launcher · Minimized"))

    def test_app_row_is_the_display_name(self):
        self.assertEqual(A(*CHROME, CAL), "Google Chrome")
        self.assertEqual(A("explorer.exe", "File Explorer", "Downloads - File Explorer", class_name="CabinetWClass"),
                         "File Explorer")


class ObservedFormats(unittest.TestCase):
    """Synthetic strings shaped like the titles seen on the user's PC (redacted shapes)."""

    def test_slack_view_with_marker_and_count(self):     # "! <view> - <workspace> - N new items - Slack"
        self.assertEqual(L("Slack.exe", "Slack", "! Activity - Acme Robotics Worldwide - 3 new items - Slack"),
                         ("Activity", "Acme Robotics Worldwide"))

    def test_slack_mention_marker(self):
        self.assertEqual(L("Slack.exe", "Slack", "* Threads - Acme - Slack"), ("Threads", "Acme"))

    def test_slack_channel_suffix_form(self):
        self.assertEqual(L("Slack.exe", "Slack", "general (Channel) - Acme - Slack"), ("#general", "Channel · Acme"))

    def test_slack_private_channel_and_group(self):
        self.assertEqual(L("Slack.exe", "Slack", "ops (Private channel) - Acme - Slack"),
                         ("#ops", "Private channel · Acme"))
        self.assertEqual(L("Slack.exe", "Slack", "Ann, Bo (Group DM) - Acme - Slack"),
                         ("Ann, Bo", "Group message · Acme"))

    def test_slack_without_conversation(self):
        self.assertEqual(L("Slack.exe", "Slack", "Slack"), ("Slack", "Desktop app"))
        self.assertEqual(L("Slack.exe", "Slack", "Home - Slack"), ("Home", "Slack"))

    def test_chrome_meet_landing_is_a_page(self):
        self.assertEqual(L(*CHROME, "Google Meet - Google Chrome"), ("Google Meet", "Google Chrome"))

    def test_chrome_generic_site(self):
        self.assertEqual(L(*CHROME, "Issue 42 - Tracker - Google Chrome"), ("Issue 42", "Tracker"))

    def test_chrome_unread_badge_not_tabs(self):
        self.assertEqual(L(*CHROME, "(3) Inbox - Gmail - Google Chrome"), ("Inbox", "Gmail"))

    def test_chrome_long_trailing_segment_is_page_text(self):
        long_tail = "a segment that is clearly longer than a site name"
        self.assertEqual(L(*CHROME, f"Notes - {long_tail} - Google Chrome"),
                         (f"Notes - {long_tail}", "Google Chrome"))

    def test_chrome_numbers_that_are_not_tab_badges(self):
        self.assertEqual(L(*CHROME, "404 - Not Found - Example - Google Chrome"), ("404 - Not Found", "Example"))
        self.assertEqual(L(*CHROME, "1 - Intro - Course - Google Chrome"), ("1 - Intro", "Course"))

    def test_chrome_tab_badge_without_site(self):
        self.assertEqual(L(*CHROME, "9 - Understand the PCB - Google Chrome"),
                         ("Understand the PCB", "Google Chrome · 9 tabs"))

    def test_chrome_single_segment(self):
        self.assertEqual(L(*CHROME, "New Tab - Google Chrome"), ("New Tab", "Google Chrome"))
        self.assertEqual(L(*CHROME, "Google Chrome"), ("Google Chrome", "Desktop app"))

    def test_calendar_other_year_keeps_year(self):
        self.assertEqual(L(*CHROME, "Google Calendar - Week of January 5, 2027 - Google Chrome"),
                         ("Calendar · Week of Jan 5, 2027", "Google Calendar"))

    def test_calendar_day_view(self):
        self.assertEqual(L(*CHROME, "Google Calendar - Monday, September 22, 2026 - Google Chrome")[0],
                         "Calendar · Mon, Sep 22")

    def test_calendar_needs_a_date(self):
        self.assertEqual(L(*CHROME, "Team - Calendar - Planning - Google Chrome"), ("Team - Calendar", "Planning"))

    def test_calendar_minimized_duplicates_shape(self):     # 2-3 identical Calendar windows were open
        self.assertEqual(L(*CHROME, CAL, minimized=True),
                         ("Calendar · Week of Sep 22", "Riot Games · Google Calendar · Minimized"))

    def test_bambu_saved(self):
        self.assertEqual(L("bambu-studio.exe", "Bambu Studio", "Rack_Base(2) - BambuStudio"),
                         ("Rack_Base(2)", "3D print project"))

    def test_bambu_trailing_star_and_no_project(self):
        self.assertEqual(L("bambu-studio.exe", "Bambu Studio", "Rack_Base(2)* - BambuStudio"),
                         ("Rack_Base(2)", "Unsaved changes · 3D print project"))
        # No project open: the title equals the app name, so section 6's "Desktop app".
        self.assertEqual(L("bambu-studio.exe", "Bambu Studio", "BambuStudio"), ("Bambu Studio", "Desktop app"))
        self.assertEqual(L("bambu-studio.exe", "Bambu Studio", "Bambu Studio"), ("Bambu Studio", "Desktop app"))
        self.assertEqual(L("bambu-studio.exe", "Bambu Studio", "* - BambuStudio"),
                         ("Bambu Studio", "Unsaved changes · 3D print project"))

    def test_explorer_tabs(self):
        self.assertEqual(L("explorer.exe", "File Explorer", "Downloads and 2 more tabs - File Explorer",
                           class_name="CabinetWClass"), ("Downloads", "Folder · 3 tabs"))

    def test_explorer_places(self):
        self.assertEqual(L("explorer.exe", "File Explorer", "Home - File Explorer", class_name="CabinetWClass"),
                         ("Home", "Location"))
        self.assertEqual(L("explorer.exe", "File Explorer", "This PC - File Explorer", class_name="CabinetWClass"),
                         ("This PC", "Location"))

    def test_explorer_full_path_title(self):
        self.assertEqual(L("explorer.exe", "File Explorer", "C:\\Data\\Projects - File Explorer",
                           class_name="CabinetWClass"), ("Projects", "Folder"))

    def test_explorer_non_cabinet_falls_back(self):
        self.assertEqual(L("explorer.exe", "File Explorer", "Run", class_name="#32770"), ("Run", "File Explorer"))

    def test_assistant_title_is_its_own_name_but_app_differs(self):
        # ChatGPT.exe's FileDescription is "Codex" (AppsFolder name unresolved): the window's
        # own title "ChatGPT" stays the title row; only a blank title uses the app name.
        self.assertEqual(label_for(F("ChatGPT.exe", "Codex", "ChatGPT"), TODAY),
                         Label("Codex", "ChatGPT", "Desktop app"))
        self.assertEqual(label_for(F("ChatGPT.exe", "Codex", "  "), TODAY), Label("Codex", "Codex", "Desktop app"))
        self.assertEqual(L("ChatGPT.exe", "Codex", "Codex"), ("Codex", "Desktop app"))
        self.assertEqual(L("ChatGPT.exe", "Codex", "ChatGPT - ChatGPT"), ("ChatGPT", "Desktop app"))
        self.assertEqual(L("claude.exe", "Claude", "Claude"), ("Claude", "Desktop app"))
        self.assertEqual(L("ChatGPT.exe", "Codex", "PCB layout questions - ChatGPT"),
                         ("PCB layout questions", "Conversation · desktop app"))

    def test_title_equals_app_name(self):
        self.assertEqual(L("ChatGPT.exe", "ChatGPT", "ChatGPT"), ("ChatGPT", "Desktop app"))
        self.assertEqual(L("Discord.exe", "Discord", "Discord"), ("Discord", "Desktop app"))
        self.assertEqual(L("SnippingTool.exe", "Snipping Tool", "Snipping Tool"), ("Snipping Tool", "Desktop app"))

    def test_steam_main_window(self):
        self.assertEqual(L("steamwebhelper.exe", "Steam", "Steam"), ("Steam", "Game launcher"))
        self.assertEqual(L("steamwebhelper.exe", "Steam", "Friends List"), ("Friends List", "Game launcher"))

    def test_edge_zero_width_space(self):
        self.assertEqual(L("msedge.exe", "Microsoft Edge", "Docs - Microsoft\u200b Edge"), ("Docs", "Microsoft Edge"))
        self.assertEqual(L("msedge.exe", "Microsoft Edge", "Q3 plan - Wiki - Microsoft\u200b Edge"), ("Q3 plan", "Wiki"))

    # Edge: "<page>[ and N more pages][ - <profile>] - Microsoft\u200b Edge" (shape from Edge's
    # documented caption format; not sampled on this PC, which runs Chrome).
    def test_edge_more_pages_and_profile(self):
        self.assertEqual(L(*EDGE, "Search and 3 more pages - Personal - Microsoft\u200b Edge"),
                         ("Search", "Microsoft Edge \u00b7 4 tabs"))
        self.assertEqual(L(*EDGE, "Issue 42 - Tracker and 1 more page - Acme - Microsoft\u200b Edge"),
                         ("Issue 42", "Tracker \u00b7 2 tabs"))
        self.assertEqual(L(*EDGE, "Issue 42 - Tracker and 2 more pages - Microsoft\u200b Edge"),
                         ("Issue 42", "Tracker \u00b7 3 tabs"))
        self.assertEqual(L(*EDGE, "New tab and 2 more pages - [InPrivate] - Microsoft\u200b Edge"),
                         ("New tab", "Microsoft Edge \u00b7 3 tabs"))

    def test_edge_single_tab_profile_segment(self):
        self.assertEqual(L(*EDGE, "Q3 plan - Wiki - Acme Team - Microsoft\u200b Edge", profile="Acme Team"),
                         ("Q3 plan", "Wiki"))
        self.assertEqual(L(*EDGE, "Search - Work - Microsoft\u200b Edge"), ("Search", "Microsoft Edge"))
        self.assertEqual(L(*EDGE, "Search - Profile 2 - Microsoft\u200b Edge"), ("Search", "Microsoft Edge"))
        self.assertEqual(L(*EDGE, "Search - [InPrivate] - Microsoft\u200b Edge", profile="Acme"),
                         ("Search", "Microsoft Edge"))
        # A known profile that differs: the trailing segment is the page's site.
        self.assertEqual(L(*EDGE, "Issue 42 - Work - Microsoft\u200b Edge", profile="Acme"), ("Issue 42", "Work"))

    def test_edge_calendar_and_meet_with_profile(self):
        self.assertEqual(L(*EDGE, "Riot Games - Calendar - Week of September 22, 2026 - Acme - Microsoft\u200b Edge",
                           profile="Acme"), ("Calendar \u00b7 Week of Sep 22", "Riot Games \u00b7 Google Calendar"))
        self.assertEqual(L(*EDGE, "Meet - abc-defg-hij and 1 more page - Personal - Microsoft\u200b Edge",
                           audible=True), ("Google Meet", "In a call \u00b7 Microsoft Edge"))

    def test_edge_rules_stay_with_edge(self):
        self.assertEqual(L(*CHROME, "Search - Work - Google Chrome"), ("Search", "Work"))
        self.assertEqual(L(*CHROME, "Cats and 3 more pages - Google Chrome"), ("Cats and 3 more pages", "Google Chrome"))

    def test_firefox_em_dash(self):
        self.assertEqual(L("firefox.exe", "Firefox", "Release notes \u2014 Mozilla Firefox"), ("Release notes", "Firefox"))

    def test_en_dash_separator(self):
        self.assertEqual(L("slack.exe", "Slack", "Danny Lewis (DM) \u2013 Riot Games \u2013 Slack"),
                         ("Danny Lewis", "Direct message · Riot Games"))

    def test_dash_inside_a_word_is_kept(self):
        self.assertEqual(L("notepad.exe", "Notepad", "2020\u20132021 plan.txt - Notepad"),
                         ("2020\u20132021 plan.txt", "Notepad"))

    def test_uwp_frame(self):
        self.assertEqual(label_for(F("ApplicationFrameHost.exe", "Calculator", "Calculator"), TODAY),
                         Label("Calculator", "Calculator", "Desktop app"))
        # Unresolved package name: a one-segment title names the app.
        unresolved = app_display_name("ApplicationFrameHost.exe", "", "Application Frame Host", "")
        self.assertEqual(label_for(F("ApplicationFrameHost.exe", unresolved, "Settings"), TODAY),
                         Label("Settings", "Settings", "Desktop app"))

    def test_uwp_frame_title_with_page_text_is_not_an_app_name(self):
        unresolved = app_display_name("ApplicationFrameHost.exe", "", "Application Frame Host", "")
        for title in ("Inbox - Person Name", "Photos - IMG_0001.jpg", "Mail: Inbox", "Page | Site", "A" * 49,
                      "", "Application", "IMG_0001.jpg", "Notes.txt", "Report 2026.docx"):
            lab = label_for(F("ApplicationFrameHost.exe", unresolved, title), TODAY)
            self.assertEqual(lab.app, wl.UNRESOLVED_FRAME_APP, title[:12])
            self.assertEqual(lab.title, title or wl.UNRESOLVED_FRAME_APP)
        self.assertEqual(L("ApplicationFrameHost.exe", unresolved, "Inbox - Person Name"),
                         ("Inbox - Person Name", "Windows app"))
        self.assertEqual(L("ApplicationFrameHost.exe", "", "Calculator"), ("Calculator", "Desktop app"))


class Normalisation(unittest.TestCase):
    def test_nfc(self):
        self.assertEqual(normalize_title("Cafe\u0301 - Notes"), "Caf\u00e9 - Notes")

    def test_invisible_and_bidi_characters_removed(self):
        self.assertEqual(normalize_title("\u200eA\u200bB\u2066C\u2069\ufeff"), "ABC")

    def test_controls_and_whitespace_collapsed(self):
        self.assertEqual(normalize_title("  A\tB\r\n C  "), "A B C")

    def test_dash_separators(self):
        self.assertEqual(normalize_title("A \u2013 B \u2014 C"), "A - B - C")

    def test_today_is_injected(self):
        other = label_for(F(*CHROME, CAL), date(2025, 1, 1))
        self.assertEqual(other.title, "Calendar · Week of Sep 22, 2026")


class AppNames(unittest.TestCase):
    def test_overrides(self):
        self.assertEqual(app_display_name(r"C:\Windows\explorer.exe", file_description="Windows Explorer"),
                         "File Explorer")
        self.assertEqual(app_display_name("steamwebhelper.exe", file_description="Steam Client WebHelper"), "Steam")
        self.assertEqual(app_display_name("bambu-studio.exe", file_description="BambuStudio"), "Bambu Studio")

    def test_override_beats_package_name(self):
        self.assertEqual(app_display_name("explorer.exe", package_name="Something"), "File Explorer")

    def test_package_name_wins(self):
        self.assertEqual(app_display_name("ChatGPT.exe", package_name="ChatGPT", file_description="Codex"), "ChatGPT")

    def test_positional_arguments(self):
        self.assertEqual(app_display_name("ChatGPT.exe", "ChatGPT", "Codex", "Codex"), "ChatGPT")

    def test_description_before_product(self):
        self.assertEqual(app_display_name("Slack.exe", "", "Slack", "Slack Technologies App"), "Slack")

    def test_description_equal_to_filename_rejected(self):
        self.assertEqual(app_display_name("SnippingTool.exe", file_description="SnippingTool.exe",
                                          product_name="Snipping Tool"), "Snipping Tool")

    def test_file_names_rejected(self):
        self.assertEqual(app_display_name("acme.exe", file_description="setup.exe"), "Acme")

    def test_boilerplate_product_rejected(self):
        self.assertEqual(app_display_name("foo-bar.exe", product_name="Microsoft\u00ae Windows\u00ae Operating System"),
                         "Foo Bar")

    def test_generic_rejected(self):
        self.assertEqual(app_display_name("acme-notes.exe", file_description="Electron", product_name="Acme Notes"),
                         "Acme Notes")
        self.assertEqual(app_display_name("tool.exe", file_description="Java(TM) Platform SE binary"), "Tool")

    def test_too_long_rejected(self):
        self.assertEqual(app_display_name("acme.exe", file_description="A" * 49, product_name="Acme"), "Acme")
        self.assertEqual(app_display_name("acme.exe", file_description="A" * 48), "A" * 48)

    def test_trademarks_stripped(self):
        self.assertEqual(app_display_name("x.exe", file_description="Acme\u2122 Studio\u00ae"), "Acme Studio")

    def test_zero_width_in_names(self):
        self.assertEqual(app_display_name("msedge.exe", file_description="Microsoft\u200b Edge"), "Microsoft Edge")

    def test_stem(self):
        self.assertEqual(title_case_stem("bambu-studio.exe"), "Bambu Studio")
        self.assertEqual(title_case_stem(r"C:\Apps\my_tool.v2.exe"), "My Tool V2")
        self.assertEqual(title_case_stem(""), "Application")

    def test_uwp_host_ignores_its_own_version_strings(self):
        self.assertEqual(app_display_name("ApplicationFrameHost.exe", "Calculator", "Application Frame Host"),
                         "Calculator")
        self.assertEqual(app_display_name("ApplicationFrameHost.exe", "", "Application Frame Host"),
                         "ApplicationFrameHost")

    def test_never_raises(self):
        self.assertEqual(app_display_name(None), "Application")
        self.assertEqual(app_display_name(123, object(), None, 5), "123")


class Duplicates(unittest.TestCase):
    def run_d(self, *facts):
        return [lab.desc for lab in disambiguate(list(facts), [label_for(f, TODAY) for f in facts])]

    def test_profiles(self):
        self.assertEqual(self.run_d(F(*CHROME, CAL, profile="Work", minimized=True),
                                    F(*CHROME, CAL, profile="Home", minimized=True)),
                         ["Riot Games · Google Calendar · Work · Minimized",
                          "Riot Games · Google Calendar · Home · Minimized"])

    def test_minimized_already_distinct(self):
        self.assertEqual(self.run_d(F(*CHROME, CAL, profile="Work"), F(*CHROME, CAL, profile="Home", minimized=True)),
                         ["Riot Games · Google Calendar", "Riot Games · Google Calendar · Minimized"])

    def test_monitors_when_same_profile(self):
        self.assertEqual(self.run_d(F(*CHROME, CAL, profile="Work", monitor="Monitor A"),
                                    F(*CHROME, CAL, profile="Work", monitor="Monitor B")),
                         ["Riot Games · Google Calendar · Monitor A", "Riot Games · Google Calendar · Monitor B"])

    def test_monitors_when_profile_unknown(self):
        self.assertEqual(self.run_d(F(*CHROME, CAL, profile="Work", monitor="Monitor A"),
                                    F(*CHROME, CAL, profile=None, monitor="Monitor B")),
                         ["Riot Games · Google Calendar · Monitor A", "Riot Games · Google Calendar · Monitor B"])

    def test_profile_then_monitor(self):
        self.assertEqual(self.run_d(F(*CHROME, CAL, profile="Work", monitor="Monitor A"),
                                    F(*CHROME, CAL, profile="Work", monitor="Monitor B"),
                                    F(*CHROME, CAL, profile="Home", monitor="Monitor A")),
                         ["Riot Games · Google Calendar · Work · Monitor A",
                          "Riot Games · Google Calendar · Work · Monitor B",
                          "Riot Games · Google Calendar · Home"])

    def test_indistinguishable_left_alone(self):
        self.assertEqual(self.run_d(F(*CHROME, CAL, profile="Work", monitor="M"),
                                    F(*CHROME, CAL, profile="Work", monitor="M")),
                         ["Riot Games · Google Calendar"] * 2)

    def test_only_identical_labels_are_touched(self):
        self.assertEqual(self.run_d(F(*CHROME, CAL, profile="Work"),
                                    F(*CHROME, "Issue 42 - Tracker - Google Chrome", profile="Home")),
                         ["Riot Games · Google Calendar", "Tracker"])

    def test_bad_input_returns_labels_unchanged(self):
        labels = [Label("A", "B", "C")]
        self.assertEqual(disambiguate([], labels), labels)
        self.assertEqual(disambiguate([object(), object()], [labels[0], None]), [labels[0], None])
        self.assertIsNot(disambiguate([], labels), labels)


class Meet(unittest.TestCase):
    def test_meet_window(self):
        self.assertTrue(meet_window(F(*CHROME, "Meet - abc-defg-hij - Google Chrome")))
        self.assertTrue(meet_window(F("msedge.exe", "Microsoft Edge", "Meet - abc-defg-hij - Microsoft\u200b Edge")))
        self.assertFalse(meet_window(F(*CHROME, "Google Meet - Google Chrome")))
        self.assertFalse(meet_window(F("Slack.exe", "Slack", "Meet - x - Slack")))
        self.assertFalse(meet_window(F(None, None, None)))

    def test_edge_meet_names_edge(self):
        self.assertEqual(L("msedge.exe", "Microsoft Edge", "Meet - abc-defg-hij - Microsoft Edge", audible=True),
                         ("Google Meet", "In a call · Microsoft Edge"))


class Profiles(unittest.TestCase):
    def test_relaunch_names(self):
        self.assertEqual(profile_from_relaunch_name("Work - Chrome"), "Work")
        self.assertEqual(profile_from_relaunch_name("Person 1 - Google Chrome"), "Person 1")
        self.assertEqual(profile_from_relaunch_name("  Work  -  Chrome Beta "), "Work")
        self.assertEqual(profile_from_relaunch_name("Personal - Microsoft Edge"), "Personal")

    def test_no_profile(self):
        for value in (None, "", "Google Chrome", "Chrome", "@{Package?ms-resource://x}", "Work - Slack", 42):
            self.assertIsNone(profile_from_relaunch_name(value))


class ClosedAndRobustness(unittest.TestCase):
    def test_closed_label(self):
        lab = closed_label(label_for(F(*CHROME, CAL, minimized=True), TODAY))
        self.assertEqual((lab.app, lab.title, lab.desc),
                         ("Google Chrome", "Calendar · Week of Sep 22", "Closed \u00b7 can\u2019t switch"))
        self.assertEqual(CLOSED_DESC, "Closed · can’t switch")

    def test_rule_exception_falls_back(self):
        def boom(f, core, today):
            raise ValueError("rule bug")
        original = wl.RULES
        wl.RULES = (wl.Rule("broken", frozenset({"slack"}), ("Slack",), boom),) + original
        try:
            self.assertEqual(L("Slack.exe", "Slack", "Danny Lewis (DM) - Riot Games - Slack"),
                             ("Danny Lewis (DM) - Riot Games", "Slack"))
        finally:
            wl.RULES = original

    def test_rule_returning_none_falls_back(self):
        self.assertEqual(L("explorer.exe", "File Explorer", "File Explorer", class_name="CabinetWClass"),
                         ("File Explorer", "Desktop app"))

    def test_odd_facts_never_raise(self):
        for facts in (F(None, None, None), F("", "", ""), F(5, 6, 7), F("x.exe", "X", "\x00\x01"),
                      F("chrome.exe", "Google Chrome", "  - Google Chrome"), object(), None):
            lab = label_for(facts, TODAY)
            self.assertIsInstance(lab, Label)
            self.assertTrue(lab.app and lab.title and lab.desc)

    def test_default_today(self):
        self.assertTrue(label_for(F(*CHROME, CAL)).title.startswith("Calendar · "))

    def test_module_is_pure(self):
        import ast
        tree = ast.parse(Path(wl.__file__).read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.module}
        self.assertLessEqual(imported, {"__future__", "re", "unicodedata", "dataclasses", "datetime", "pathlib",
                                        "typing"})
        calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)}
        self.assertNotIn("print", calls)

    def test_reprs_hide_personal_strings(self):
        facts = F(*CHROME, "Secret Title", profile="Private Profile", monitor="Desk Monitor")
        text = repr(facts) + repr(label_for(facts, TODAY))
        for secret in ("Secret", "Private", "Desk"):
            self.assertNotIn(secret, text)
        self.assertIn("chrome.exe", text)

    def test_label_repr_hides_an_app_row_taken_from_a_title(self):
        unresolved = app_display_name("ApplicationFrameHost.exe", "", "Application Frame Host", "")
        for title in ("Secret", "Inbox - Secret Person"):
            text = repr(label_for(F("ApplicationFrameHost.exe", unresolved, title), TODAY))
            self.assertNotIn("Secret", text)
            self.assertTrue(text.startswith("Label(app=<"), "lengths only")


if __name__ == "__main__":
    unittest.main(verbosity=1)

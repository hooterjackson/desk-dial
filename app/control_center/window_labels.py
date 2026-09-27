"""Window carousel labels (CAROUSEL.md section 6): (app, title, description) per window.

Pure and table-driven: no ctypes, no Tk, no I/O and no logging. The adapter gathers
``WindowFacts`` (window_facts.py reads the Win32/COM parts on the IconWorker thread);
this module turns them into ``Label`` rows for the centre card.

- App name: ``app_display_name`` (override table by exe stem, then the packaged app's
  AppsFolder name, FileDescription, ProductName without boilerplate, then the
  title-cased exe stem). ``item['app']`` (the exe stem the knob uses) is never changed.
- Titles are normalised first (NFC, zero-width and bidi controls removed, en/em dash
  separators mapped to " - "), then the first matching rule of ``RULES`` parses them.
  ``today`` is injected so calendar dates are testable.
- A rule that raises (or returns None) falls back to the generic rule; ``label_for``
  itself never raises, so a label can never break the picker.
- Description fallbacks: a per-app override (Steam: "Game launcher"), else "Desktop
  app" when the title equals the app name, else the trailing site segment for
  browsers, else the app name. Minimized windows append " · Minimized"; closed
  windows read "Closed · can’t switch" (``closed_label``).
- Duplicates (``disambiguate``): identical labels get the browser profile when the
  profiles differ, otherwise the monitor name when the monitors differ; otherwise
  they stay identical.
- Meet: "In a call · <browser>" only when the Core Audio check answered True
  (``WindowFacts.audible``); until then (None) and when it answered False the
  description reads "Meeting · <browser>".
- Edge writes "<page>[ and N more pages][ - <profile>] - Microsoft Edge": the tab
  count becomes " · N+1 tabs" and the profile segment is dropped before the browser
  rule looks for a trailing site segment.
- A UWP frame whose package name is unknown takes its app name from a one-segment
  title ("Calculator"); a longer title or a bare file name ("IMG_0001.jpg") is page or
  document text, so the app row reads "Windows app" instead.
- Claude/ChatGPT: a title that is only an assistant's name stays the title row
  ("the title, or the app name if blank"), described as "Desktop app".

Privacy: titles, profile names and monitor names are personal. They are shown on
screen only; ``WindowFacts`` reprs report their lengths, never the text, and ``Label``
reprs report only lengths (a label's app name can come from a title).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date
from pathlib import PureWindowsPath
from typing import Callable, Optional

__all__ = [
    "WindowFacts", "Label", "Rule", "RULES", "label_for", "disambiguate", "closed_label",
    "app_display_name", "title_case_stem", "normalize_title", "strip_suffix", "short_date",
    "find_rule", "meet_window", "profile_from_relaunch_name",
    "SEP", "MINIMIZED", "CLOSED_DESC", "DESKTOP_APP", "APP_NAME_OVERRIDES", "DESC_OVERRIDES",
    "MAX_APP_NAME", "UNRESOLVED_FRAME_APP",
]

SEP = " · "                       # " · "
MINIMIZED = "Minimized"
CLOSED_DESC = "Closed · can’t switch"   # the knob's wording, typographic apostrophe
DESKTOP_APP = "Desktop app"
UNRESOLVED_FRAME_APP = "Windows app"   # a UWP frame whose package and title name no app
MAX_APP_NAME = 48                      # longer version strings are not display names
MAX_SITE = 32                          # a trailing browser segment longer than this is page text
MAX_PROFILE = 64

# Zero-width, soft-hyphen, bidi embedding/isolate and BOM characters (Edge writes
# "Microsoft​ Edge"). Removed from every title and name before matching.
_INVISIBLE = dict.fromkeys(map(ord, (
    "­᠎​‌‍‎‏‪‫‬‭‮"
    "⁠⁡⁢⁣⁤⁦⁧⁨⁩﻿")))
_DASH_SEPARATOR = re.compile(r"\s+[–—]\s+")   # en/em dash separators -> " - "
_TRADEMARKS = re.compile(r"[®™©]")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTH_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\b")
_DAY_RE = re.compile(r"\b(" + "|".join(DAYS) + r")\b")


# ------------------------------------------------------------------ text helpers
def _text(value) -> str:
    """NFC, invisible characters removed, control characters and runs of whitespace
    collapsed to one space. Never raises."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).translate(_INVISIBLE)
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        text = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in text)
    return " ".join(text.split())


def _name(value) -> str:
    """A display-name candidate: _text() without the (R), TM and (C) marks."""
    return " ".join(_TRADEMARKS.sub("", _text(value)).split())


def _key(value) -> str:
    """Case- and space-insensitive comparison key."""
    return re.sub(r"\s+", "", _text(value)).casefold()


def normalize_title(title) -> str:
    """NFC, zero-width characters removed, en/em dash separators mapped to " - "."""
    return _DASH_SEPARATOR.sub(" - ", _text(title))


def strip_suffix(title: str, *names: str) -> str:
    """Remove a trailing " - <name>" or " | <name>" (case and space insensitive).

    A title that is only one of the names becomes "".
    """
    keys = {_key(n) for n in names if n}
    keys.discard("")
    for sep in (" - ", " | "):
        head, found, tail = title.rpartition(sep)
        if found and _key(tail) in keys:
            return head.strip()
    return "" if _key(title) in keys else title


def _split(core: str) -> list:
    return [part.strip() for part in core.split(" - ")]


def short_date(text: str, today: date) -> str:
    """'Week of September 22, 2026' -> 'Week of Sep 22' (the year is kept when it is
    not ``today``'s year); weekday names are shortened too."""
    text = re.sub(r",\s*" + str(today.year) + r"\b", "", text)
    text = _MONTH_RE.sub(lambda m: m.group(1)[:3], text)
    return _DAY_RE.sub(lambda m: m.group(1)[:3], text)


# ------------------------------------------------------------------ app names
APP_NAME_OVERRIDES = {          # exe stem (lower case) -> display name; wins over everything
    "explorer": "File Explorer",          # FileDescription says "Windows Explorer"
    "bambu-studio": "Bambu Studio",       # FileDescription says "BambuStudio"
    "steamwebhelper": "Steam",            # FileDescription says "Steam Client WebHelper"
}
GENERIC_NAMES = frozenset({
    "", "application", "app", "electron", "program", "launcher", "main", "client", "host",
    "desktop", "window", "unknown", "n/a", "none", "null", "wrapper", "stub", "runtime",
})
_GENERIC_PATTERNS = re.compile(r"^java\(tm\) platform|\.(exe|dll|bat|cmd)$", re.I)
_BOILERPLATE = re.compile(r"operating system|microsoft\s*windows\b", re.I)
UWP_HOST_STEMS = frozenset({"applicationframehost"})


def title_case_stem(exe) -> str:
    """'bambu-studio.exe' -> 'Bambu Studio'; never empty."""
    try:
        stem = PureWindowsPath(str(exe or "")).stem
    except Exception:
        stem = ""
    words = [w for w in re.split(r"[-_.\s]+", _text(stem)) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or "Application"


def _usable_name(value: str, filename: str, allow_boilerplate: bool) -> bool:
    low = value.casefold()
    return bool(value) and low not in GENERIC_NAMES and low != filename \
        and len(value) <= MAX_APP_NAME and not _GENERIC_PATTERNS.search(value) \
        and (allow_boilerplate or not _BOILERPLATE.search(value))


def app_display_name(exe, package_name="", file_description="", product_name="") -> str:
    """The app row's name (section 6), in this order: the override table by exe stem,
    the packaged app's AppsFolder display name, FileDescription, ProductName (boilerplate
    such as "Microsoft Windows Operating System" rejected), the title-cased exe stem.

    Candidates are cleaned (NFC, invisible characters and (R)/TM/(C) removed) and
    rejected when empty, generic, equal to the whole file name, a file name themselves,
    or longer than 48 characters. For the UWP frame host only the package name counts:
    its own version strings describe the host, not the app. Never raises."""
    try:
        path = PureWindowsPath(str(exe or ""))
        stem, filename = path.stem.casefold(), path.name.casefold()
        if stem in APP_NAME_OVERRIDES:
            return APP_NAME_OVERRIDES[stem]
        def text(value):
            return _name(value) if isinstance(value, str) else ""

        candidates = [(text(package_name), True)]
        if stem not in UWP_HOST_STEMS:
            candidates += [(text(file_description), True), (text(product_name), False)]
        for value, allow_boilerplate in candidates:
            if _usable_name(value, filename, allow_boilerplate):
                return value
    except Exception:
        pass
    return title_case_stem(exe)


def profile_from_relaunch_name(value) -> Optional[str]:
    """The browser profile from a window's RelaunchDisplayNameResource
    ("<profile> - Chrome"), or None. Indirect "@..." resource strings and values
    without a browser suffix give None (Chrome may omit or change it: degrade)."""
    try:
        text = _text(value)
        if not text or text.startswith("@"):
            return None
        m = re.fullmatch(r"(?P<name>.+?)\s+-\s+(?:Google\s+)?(?:Chrome|Chromium|Microsoft\s+Edge|Edge|Brave|"
                         r"Vivaldi)(?:\s+(?:Beta|Dev|Canary|SxS))?", text)
        name = m.group("name").strip() if m else ""
        return name[:MAX_PROFILE] if name else None
    except Exception:
        return None


# ------------------------------------------------------------------ facts / label
def _redacted(value) -> str:
    return "None" if value is None else f"<{len(str(value))} chars>"


@dataclass(frozen=True, repr=False)
class WindowFacts:
    exe: str                        # process base name (or path), e.g. "chrome.exe"
    app: str                        # app_display_name()
    title: str                      # raw GetWindowText
    class_name: str = ""
    minimized: bool = False
    audible: Optional[bool] = None  # Core Audio call signal; None = not answered yet
    profile: Optional[str] = None   # browser profile display name (duplicates; Edge's title segment)
    monitor: Optional[str] = None   # monitor friendly name (duplicates only)

    @property
    def stem(self) -> str:
        try:
            return PureWindowsPath(str(self.exe or "")).stem.casefold()
        except Exception:
            return ""

    def __repr__(self):  # titles, profiles and monitor names are personal
        return (f"WindowFacts(exe={self.exe!r}, app={self.app!r}, title={_redacted(self.title)}, "
                f"class_name={self.class_name!r}, minimized={self.minimized!r}, audible={self.audible!r}, "
                f"profile={_redacted(self.profile)}, monitor={_redacted(self.monitor)})")


@dataclass(frozen=True, repr=False)
class Label:
    app: str
    title: str
    desc: str

    def __repr__(self):  # the app row can come from a title (an unresolved UWP frame): lengths only
        return f"Label(app={_redacted(self.app)}, title={_redacted(self.title)}, desc={_redacted(self.desc)})"


def closed_label(label: Label) -> Label:
    """The same app and title with the closed description (Switch is disabled)."""
    try:
        return Label(label.app, label.title, CLOSED_DESC)
    except Exception:
        return Label("Application", "Application", CLOSED_DESC)


# ------------------------------------------------------------------ rules
Parse = Callable[[WindowFacts, str, date], Optional[tuple]]


def slack(f: WindowFacts, core: str, today: date):
    core = re.sub(r"^(?:! |\* )", "", core)              # unread / mention markers
    parts = _split(core)
    if parts and re.fullmatch(r"\d+ new items?", parts[-1]):
        parts = parts[:-1]
    parts = [p for p in parts if p]
    if not parts:
        return None
    if len(parts) < 2:
        return parts[0], f.app                            # a view without a workspace
    conv, workspace = parts[0], " - ".join(parts[1:])
    m = re.fullmatch(r"(.+?) \((DM|Group DM|Channel|Private channel|Private Channel)\)", conv)
    if m:
        name, kind = m.groups()
        if kind in ("DM", "Group DM"):
            return name, ("Direct message" if kind == "DM" else "Group message") + SEP + workspace
        kind_text = "Private channel" if kind.lower() == "private channel" else "Channel"
        return "#" + name.lstrip("#"), kind_text + SEP + workspace
    if conv.startswith("#"):
        return conv, "Channel" + SEP + workspace
    return conv, workspace                                 # a view: Activity, Home, DMs, Later...


_MEET = re.compile(r"Meet - .+")
_CALENDAR = re.compile(r"(?:(?P<org>.+?) - )?(?:Google )?Calendar - (?P<when>.+)")
_TAB_COUNT = re.compile(r"(?P<n>\d{1,2}) - (?P<rest>.+)")   # README: a leading count is a tab badge
MIN_TAB_BADGE = 2
EDGE_STEMS = frozenset({"msedge"})
# Edge: "<page> and N more pages - <profile>" (the " - Microsoft Edge" suffix already gone).
# Only the profile can follow the page count, so everything after it is dropped.
_EDGE_PAGES = re.compile(r"(?P<page>.+?) and (?P<n>\d{1,3}) more pages?(?: - .+)?")
_EDGE_INPRIVATE = re.compile(r"\[?InPrivate\]?", re.I)
# Edge's default profile names: a single tab's trailing segment that reads like one is the
# profile when the window's own profile is unknown (no RelaunchDisplayNameResource).
_EDGE_DEFAULT_PROFILES = re.compile(r"Profile \d{1,3}|Personal|Work|Guest|Default", re.I)


def _edge_core(f: WindowFacts, core: str):
    """Edge's title core -> (page core, tab count or None): " and N more pages" becomes
    N+1 tabs and the profile segment after it is dropped; a single tab's trailing
    segment is dropped when it is the window's profile (WindowFacts.profile), InPrivate,
    or, with the profile unknown, one of Edge's default profile names."""
    m = _EDGE_PAGES.fullmatch(core)
    if m:
        return m.group("page").strip(), int(m.group("n")) + 1
    parts = _split(core)
    if len(parts) > 1:
        tail, profile = parts[-1], _text(f.profile)
        if (profile and _key(tail) == _key(profile)) or _EDGE_INPRIVATE.fullmatch(tail) \
                or (not profile and _EDGE_DEFAULT_PROFILES.fullmatch(tail)):
            return " - ".join(parts[:-1]), None
    return core, None


def browser(f: WindowFacts, core: str, today: date):
    count = None
    if f.stem in EDGE_STEMS:
        core, count = _edge_core(f, core)
    if not core:
        return None                                        # the browser's own name: generic rule
    m = _CALENDAR.fullmatch(core)
    if m and (_MONTH_RE.search(m.group("when")) or _DAY_RE.search(m.group("when"))
              or re.search(r"\d", m.group("when"))):
        org = m.group("org")
        return ("Calendar" + SEP + short_date(m.group("when"), today),
                (org + SEP if org else "") + "Google Calendar")
    if _MEET.fullmatch(core):
        return "Google Meet", ("In a call" if f.audible is True else "Meeting") + SEP + f.app
    m = _TAB_COUNT.fullmatch(core)
    if count is None and m and int(m.group("n")) >= MIN_TAB_BADGE:
        count, core = int(m.group("n")), m.group("rest")
    core = re.sub(r"^\(\d+\)\s+", "", core)                # "(3) Inbox": a page unread badge
    parts = _split(core)
    if len(parts) > 1 and parts[-1] and len(parts[-1]) <= MAX_SITE and " - ".join(parts[:-1]):
        title, desc = " - ".join(parts[:-1]), parts[-1]    # the trailing site segment
    else:
        title, desc = core, f.app
    if count is not None:
        desc += SEP + f"{count} tabs"
    return title or f.app, desc


def bambu(f: WindowFacts, core: str, today: date):
    unsaved = core.startswith("*") or core.endswith("*")
    project = core.strip("*").strip()
    if not project:
        # No project open: the title is the app name, so the generic rule gives
        # "Desktop app" (section 6). A bare "*" is an untitled project with changes.
        return (f.app, "Unsaved changes" + SEP + "3D print project") if unsaved else None
    return project, ("Unsaved changes" + SEP if unsaved else "") + "3D print project"


EXPLORER_PLACES = frozenset({"Home", "This PC", "Gallery", "Network", "Recycle Bin", "Quick access",
                             "Control Panel", "Linux"})


def explorer(f: WindowFacts, core: str, today: date):
    if not core:
        return None
    m = re.fullmatch(r"(?P<folder>.+) and (?P<n>\d+) more tabs?", core)
    folder, tabs = (m.group("folder"), int(m.group("n")) + 1) if m else (core, 0)
    if re.match(r"^(?:[A-Za-z]:\\|\\\\)", folder):         # "full path in the title bar" option
        folder = PureWindowsPath(folder).name or folder
    kind = "Location" if folder in EXPLORER_PLACES else "Folder"
    return folder, kind + (SEP + f"{tabs} tabs" if tabs else "")


def assistant(f: WindowFacts, core: str, today: date):
    """README: "the title, or the app name if blank". A title that is only an assistant's
    name ("ChatGPT") is the home view: it stays the title row (even when the app row
    reads another name, e.g. ChatGPT.exe's FileDescription "Codex" when the AppsFolder
    name is unresolved) and the description is "Desktop app"."""
    names = {_key(f.app), f.stem, "claude", "chatgpt", "codex"}
    if not core:
        return normalize_title(f.title) or f.app, DESKTOP_APP
    if _key(core) in names:
        return core, DESKTOP_APP
    return core, "Conversation" + SEP + "desktop app"


@dataclass(frozen=True)
class Rule:
    name: str
    stems: frozenset
    suffixes: tuple            # window-title suffixes the app appends (" - <suffix>")
    parse: Parse
    class_names: frozenset = frozenset()


BROWSER_STEMS = frozenset({"chrome", "msedge", "brave", "vivaldi", "firefox", "opera", "arc"})
BROWSER_SUFFIXES = (
    "Google Chrome", "Google Chrome Beta", "Google Chrome Dev", "Google Chrome Canary",
    "Google Chrome for Testing", "Chromium", "Microsoft Edge", "Microsoft Edge Beta",
    "Microsoft Edge Dev", "Microsoft Edge Canary", "Brave", "Vivaldi", "Mozilla Firefox", "Firefox",
    "Firefox Developer Edition", "Firefox Nightly", "Opera", "Arc",
)

RULES = (
    Rule("slack", frozenset({"slack"}), ("Slack",), slack),
    Rule("browser", BROWSER_STEMS, BROWSER_SUFFIXES, browser),
    Rule("bambu", frozenset({"bambu-studio"}), ("BambuStudio", "Bambu Studio"), bambu),
    Rule("explorer", frozenset({"explorer"}), ("File Explorer",), explorer, frozenset({"CabinetWClass"})),
    Rule("assistant", frozenset({"claude", "chatgpt"}), ("Claude", "ChatGPT", "Codex"), assistant),
)

DESC_OVERRIDES = {              # exe stem -> description for every window of that app
    "steamwebhelper": "Game launcher",
    "steam": "Game launcher",
}


def find_rule(f: WindowFacts) -> Optional[Rule]:
    stem = f.stem
    for rule in RULES:
        if stem in rule.stems and (not rule.class_names or (f.class_name or "") in rule.class_names):
            return rule
    return None


_FRAME_TITLE_SEPARATORS = re.compile(r" [-|·:] |: ")
_FILE_NAME = re.compile(r"\.[A-Za-z0-9]{2,5}$")       # "IMG_0001.jpg": a document, not an app


def _resolve_app(f: WindowFacts, raw: str) -> str:
    app = _name(f.app)
    if f.stem in UWP_HOST_STEMS and (not app or _key(app) in {"applicationframehost", "applicationframehost.exe"}):
        # An unresolved UWP frame. A one-segment title is the app's name ("Calculator",
        # "Settings"); a title with separators carries a page, mail subject or file name
        # (personal, and not an app name), and so does a bare file name, so a fixed name
        # stands in.
        name = _name(raw)
        if name and not _FRAME_TITLE_SEPARATORS.search(name) and not _FILE_NAME.search(name) \
                and _usable_name(name, "applicationframehost.exe", allow_boilerplate=True):
            return name
        return UNRESOLVED_FRAME_APP
    return app or title_case_stem(f.exe)


def _generic(f: WindowFacts, raw: str) -> tuple:
    exe = PureWindowsPath(str(f.exe or ""))
    core = strip_suffix(raw, f.app, f.stem, exe.stem, exe.name)
    title = core or f.app
    override = DESC_OVERRIDES.get(f.stem)
    if override:
        return title, override
    return title, (DESKTOP_APP if _key(title) == _key(f.app) else f.app)


def _label(facts: WindowFacts, today: date) -> Label:
    raw = normalize_title(facts.title)
    app = _resolve_app(facts, raw)
    f = facts if app == facts.app else replace(facts, app=app)
    rule = find_rule(f)
    parsed = None
    if rule is not None:
        try:
            parsed = rule.parse(f, strip_suffix(raw, *rule.suffixes, app), today)
        except Exception:
            parsed = None      # a rule never breaks the picker: fall back
    if parsed is None:
        parsed = _generic(f, raw)
    title, desc = parsed
    title, desc = _text(title) or app, _text(desc) or app
    if f.minimized:
        desc = desc + SEP + MINIMIZED
    return Label(app, title, desc)


def _safe_label(facts) -> Label:
    try:
        app = _name(getattr(facts, "app", "")) or title_case_stem(getattr(facts, "exe", ""))
    except Exception:
        app = "Application"
    try:
        title = _text(getattr(facts, "title", "")) or app
    except Exception:
        title = app
    return Label(app, title, app)


def label_for(facts: WindowFacts, today: Optional[date] = None) -> Label:
    """The three label rows for one window. Never raises: any failure gives the
    generic label (the app name, the full title, the app name)."""
    try:
        return _label(facts, today if isinstance(today, date) else date.today())
    except Exception:
        return _safe_label(facts)


def meet_window(facts: WindowFacts) -> bool:
    """True for a browser window on a Meet call page ("Meet - <code>"): only these need
    the lazy, off-Tk-thread Core Audio check (window_facts.audible_pids)."""
    try:
        rule = find_rule(facts)
        if rule is None or rule.parse is not browser:
            return False
        app = _resolve_app(facts, "")
        core = strip_suffix(normalize_title(facts.title), *rule.suffixes, app)
        return bool(_MEET.fullmatch(core))
    except Exception:
        return False


def _with_extra(label: Label, extra: str) -> Label:
    tail = SEP + MINIMIZED
    desc = label.desc
    base, mini = (desc[:-len(tail)], tail) if desc.endswith(tail) else (desc, "")
    return Label(label.app, label.title, base + SEP + extra + mini)


def disambiguate(facts: list, labels: list) -> list:
    """Identical labels get the browser profile when the profiles differ, otherwise the
    monitor name when the monitors differ (inserted before " · Minimized"); anything
    still identical stays identical. Returns a new list; never raises (on any failure,
    or when the lists differ in length, the labels come back unchanged)."""
    try:
        out = list(labels)
        if len(facts) != len(out):
            return out
        for attr in ("profile", "monitor"):
            groups = {}
            for index, label in enumerate(out):
                groups.setdefault((label.app, label.title, label.desc), []).append(index)
            for members in groups.values():
                if len(members) < 2:
                    continue
                values = [_text(getattr(facts[i], attr, None)) for i in members]
                if all(values) and len(set(values)) > 1:
                    for index, value in zip(members, values):
                        out[index] = _with_extra(out[index], value)
        return out
    except Exception:
        return list(labels)

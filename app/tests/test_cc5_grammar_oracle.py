"""K3 section 17: the button grammar against the design's own footer.

tests/fixtures/grammar_oracle_bs.json is produced by tests/js/grammar_oracle.cjs from the [r2.2]
master's "Browse and Snap.dc.html": renderVals()'s `foot` (the BS glyph key and tone of each of the
four slots) for every state-picker combination that reaches the footer (BS:1352-1365): every source,
Sonos shuffle, the Starting… and Play next spans, Seek idle / jumping / failed, every Up next kind x
like state x companion shuffle x focus x liked, the explorer tabs x favourites x a loading list, and
the picker's snap slots.

Each case is rebuilt on the v7 controller through its public inputs (presses, turns, completions,
presenter events: the K3 section 17 fixtures' way) and its frame's buttons are compared slot by slot
after the VOC-N06 token map (BS `note` = Browse `list`, `list` = `tracks`, `tracks` = skip `next`,
`next` = `playnext`, `queue` = `playlists`, `check` = `switch`, `rect` + HALF = `snapleft` /
`snapright`), the tone derived as the knob does (PRESENTATION_V5 5.2, ``button_tone_v5``; r2.2's liked
heart, `on` + PINK, is the tone `liked`, VOC section 2.3 row 4).

Every difference must be a listed deviation (DEVIATIONS; each names its contract source) and every
listed deviation must still occur; the PC-not-connected footer (the knob's own firmware profile) is not
a companion frame and is not compared (NOT_TESTED).

Regenerate after a deliberate design change (node is needed only for the golden):
    node tests\\js\\grammar_oracle.cjs design-reference\\design_handoff_nano_d_master_r2.2\\prototypes tests\\fixtures\\grammar_oracle_bs.json
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(Path(__file__).resolve().parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cc5_support import Clock, fail, queue_state, recent_page, window_result  # noqa: E402
from control_center import presentation as P  # noqa: E402
from control_center.controller import Controller  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "grammar_oracle_bs.json"
GENERATOR = ROOT / "tests" / "js" / "grammar_oracle.cjs"
DESIGN = ROOT / "design-reference" / "design_handoff_nano_d_master_r2.2" / "prototypes"
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))
PINK = GOLDEN["constants"]["PINK"]
WARM = GOLDEN["constants"]["WARM"]

# VOC-N06: BS glyph keys -> the A04 meaning tokens the wire carries.
TOKEN = {"note": "list", "list": "tracks", "tracks": "next", "next": "playnext", "queue": "playlists",
         "check": "switch", "rect-left": "snapleft", "rect-right": "snapright"}

DEVIATIONS = {
    "VOC-R14": "VOC-R14 / VOC section 2.6 `nothing_playing`: with nothing playing Home 1 and Home 3 dim (S03 idle "
               "row) and Home 1's token follows the confirmed transport (STOPPED: play); BS keeps them lit",
    "C5-61": "K2 M31 / C5-61 (K3 sections 3.2, 5.2.3): Recent 3/4 dim `loading` while the list loads; BS's knob "
             "list is never loading (its 'Loading list' option only dims the explorer)",
    "C5-4": "C5-4 / K3 section 2.3: the busy codes reach Tracks 3/4 (`starting`) and Tracks 4 (`queueing`); BS's "
            "Tracks footer ignores `busy`",
    "skip_unavailable": "K3 section 3.2 `skip_unavailable`: with nothing playing Sonos offers no Next / Previous, so "
                        "Tracks 4 dims; BS models no transport capabilities",
}
NOT_TESTED = {
    "home-pc-off": "PC not connected: the knob's own firmware profile draws the footer; the companion sends no frame",
}


def deviation(case, slot):
    """The listed deviation allowed at (case, slot), or None."""
    bs = case["bs"]
    mode, sim = bs["mode"], bs.get("sim", {})
    if mode == "home" and sim.get("source") == "none" and slot in (0, 2):
        return "VOC-R14"
    if mode == "recent" and sim.get("art") == "list" and slot in (2, 3):
        return "C5-61"
    if mode == "tracks" and not bs.get("seek"):
        if bs.get("busy") and slot in (2, 3):
            return "C5-4"
        if sim.get("source") == "none" and bs.get("tPos") and slot == 3:
            return "skip_unavailable"
    return None


def bs_slot(slot):
    token = TOKEN.get(slot["key"], slot["key"])
    tone = slot["tone"]
    if tone == "on" and token == "heart" and slot.get("c") == PINK:
        tone = "liked"                        # r2.2 (R22 BS:1268): VOC section 2.3 row 4
    return token, tone


# ------------------------------------------------------------------ the host side
def sonos_state(bs, **extra):
    """The Sonos state of a BS state (fresh(): row 5 of 12, playing)."""
    sim = bs.get("sim", {})
    source = sim.get("source", "queue")
    value = queue_state(position_s=74, duration_s=210)
    if not bs.get("playing", True):
        value.update(playback="PAUSED_PLAYBACK", can_play=True, can_pause=False)
    if sim.get("sonosShuffle") == "on":
        value.update(play_mode="SHUFFLE_NOREPEAT", shuffle=True)
    if source in ("airplay", "radio", "linein"):
        value.update(source=source, queue_length=0, playlist_position=0, can_seek=False, duration_s=0)
    elif source == "none":
        value.update(source="none", playback="STOPPED", can_play=False, can_pause=False, can_next=False,
                     can_previous=False, queue_length=0, playlist_position=0, title="", artist="", track_id="",
                     can_seek=False, duration_s=0, song_id=None)
    value.update(extra)
    return value


def bs_windows():
    """BS's window set (BS:727-735) as a snapshot; the warm marker is sent as no accent (M26)."""
    items = []
    for i, w in enumerate(GOLDEN["windows"]):
        c = w["c"]
        accent = None if c == WARM else (c[0] << 16) | (c[1] << 8) | c[2]
        items.append({"id": f"w{i}", "hwnd": 100 + i, "pid": 200 + i, "title": f"Window {i}", "app": w["app"],
                      "available": True, "accent": accent})
    return items


FAVOURITES = {
    "real": [{"id": "pl-fav", "title": "Favorite Songs", "kind": "playlist"},
             {"id": "pl-mm", "title": "PAPER LANTERN Ep. 1", "kind": "playlist"}],
    "empty": [],
    "many": [{"id": f"pl-{i}", "title": f"Playlist {i}", "kind": "playlist"} for i in range(6)],
}


class Host:
    """A v7 controller driven into a BS state through its public inputs."""

    def __init__(self, initial=None):
        self.clock = Clock()
        self.c = Controller(clock=self.clock, rng=random.Random(7))
        self.publish(initial or queue_state(position_s=74, duration_s=210))
        self.c.last_poll = self.clock()
        self.c.drain()

    def publish(self, value):
        self.c.complete(self.c.request("state"), value)

    def pending(self, kind):
        found = [e for e in self.c.pending.values() if e["kind"] == kind]
        return found[-1] if found else None

    def complete(self, kind, result=None, error=None):
        effect = self.pending(kind)
        if effect is None:
            raise AssertionError(f"no pending {kind}")
        self.c.complete(effect["request"], result, error)
        return effect

    def press(self, logical):
        self.c.button(logical, self.c.control_id)

    def turn(self, index):
        self.c.position(index, self.c.control_id)

    def expect_mode(self, mode):
        if self.c.screen.mode != mode:
            raise AssertionError(f"expected {mode}, at {self.c.screen.mode}")

    # spans
    def start_pending(self):
        self.press(1)                                   # Home 2: Browse
        self.complete("recent", recent_page(0, 60))
        self.press(3)                                   # Recent 4: Play (Home at once, Starting…)
        self.expect_mode("home")
        assert self.c.start is not None

    def playnext_pending(self):
        self.press(1)
        self.complete("recent", recent_page(0, 60))
        self.press(2)                                   # Recent 3: Play next
        assert self.c.play_next_job is not None

    def footer(self):
        frame = self.c.frame()
        return [(b.get("icon", ""), P.button_tone_v5(i, b.get("icon", ""), b.get("enabled") is True, b.get("lit"),
                                                     frame.get("layout", "")))
                for i, b in enumerate(frame["buttons"])]


def build_home(bs):
    host = Host()
    if bs.get("busy"):
        host.start_pending()
    host.publish(sonos_state(bs))
    host.expect_mode("home")
    return host


def build_tracks(bs):
    host = Host()
    busy = bs.get("busy") or {}
    if busy.get("kind") == "start":
        host.start_pending()
    elif busy.get("kind") == "pn":
        host.playnext_pending()
        host.press(0)                                   # Back: Home, the job still out
    host.press(2)                                       # Home 3: Tracks
    host.expect_mode("tracks")
    host.turn(bs.get("tPos", 0) + 1)
    host.publish(sonos_state(bs))                       # the source as the case has it (it may change here)
    return host


def build_seek(bs):
    host = Host()
    host.press(2)
    host.press(2)                                       # Tracks 3: Seek
    host.expect_mode("seek")
    if bs.get("seekState") in ("jump", "fail"):
        host.turn(20)
        host.clock.advance(0.3)
        host.c.tick()
        effect = host.pending("seek")
        assert effect is not None and host.c.screen.seek.busy
        if bs["seekState"] == "fail":
            host.c.complete(effect["request"], None, fail("Seek not confirmed", outcome="not_confirmed"))
            assert host.c.clock() < host.c.screen.seek.fail_until
    return host


def build_upnext(bs):
    sim = bs["sim"]
    kind, like = sim["upnext"], sim["like"]
    extra = {"companion_shuffle": bool(bs.get("shuffle"))}
    T = 12
    if kind == "longshuffle":                           # > 60 upcoming under Sonos shuffle: the card
        T = 80
        extra.update(play_mode="SHUFFLE_NOREPEAT", shuffle=True, queue_length=T)
    state = queue_state(position_s=74, duration_s=210, **extra)
    host = Host(state)
    host.press(2)
    host.press(1)                                       # Tracks 2: Up next
    host.expect_mode("upnext")
    if kind == "loading":
        host.turn(bs["qSel"])
        return host
    qsel = bs["qSel"]
    liked = {str(1000 + qsel + 1)} if bs.get("liked") else set()

    def settle():
        for _ in range(20):
            effect = next((e for e in host.c.pending.values()
                           if e["kind"] in ("queue_window", "catalog_songs", "ratings")), None)
            if effect is None:
                return
            if effect["kind"] == "queue_window":
                host.c.complete(effect["request"], window_result(effect["start"], effect["count"], T,
                                                                 revision=host.c.state.get("queue_revision", "rev-1")))
            elif effect["kind"] == "catalog_songs":
                host.c.complete(effect["request"], {
                    song: {"catalog": not (kind == "foreign" and (int(song) - 1001) % 3 == 2), "album": "Album",
                           "accent": 0x445566}
                    for song in effect["ids"]})
            elif like == "loading":
                host.c.complete(effect["request"], None, fail("Apple Music did not answer.", status=503))
            else:
                host.c.complete(effect["request"], {song: 1 for song in effect["ids"] if song in liked})
        raise AssertionError("Up next never settled")

    settle()
    host.turn(qsel)
    settle()
    return host


def build_recent(bs):
    host = Host()
    busy = bs.get("busy") or {}
    loading = bs["sim"].get("art") == "list"
    if busy.get("kind") == "start":
        host.start_pending()
        host.press(1)                                   # Browse again: a new visit, the start still out
    elif busy.get("kind") == "pn":
        host.playnext_pending()
        if loading:
            host.press(0)
            host.press(1)                               # a new visit whose list is still loading
    else:
        host.press(1)
    host.expect_mode("recent")
    if not loading and host.pending("recent") is not None:
        host.complete("recent", recent_page(0, 60))
    host.publish(sonos_state(bs))
    return host


def build_explorer(bs):
    sim = bs["sim"]
    loading = sim.get("art") == "list"
    host = Host()
    host.press(1)                                       # Browse
    if not (loading and bs["src"] == "recent"):
        host.complete("recent", recent_page(0, 60))
    host.press(1)                                       # Recent 2: Open (the explorer, recent tab)
    host.expect_mode("explorer")
    if bs["src"] == "playlists":
        host.clock.advance(0.5)                         # past the opening (a tab press inside it is ignored)
        host.c.tick()
        host.press(2)                                   # Explorer 3: the Playlists tab
        host.clock.advance(0.2)                         # the 190 ms tab swap (BS:1036)
        host.c.tick()
        assert host.c.screen.explorer.source == "favourites"
        if not loading:
            host.complete("favourite_playlists", [dict(p) for p in FAVOURITES[sim.get("favs", "real")]])
    return host


def build_windows(bs):
    host = Host()
    host.press(3)                                       # Home 4: Win
    items = bs_windows()
    host.complete("windows_open", {"items": items, "index": bs["sel"], "origin": {"hwnd": 100, "pid": 200}})
    host.expect_mode("windows")
    for side, logical in (("left", 1), ("right", 2)):
        index = bs.get(side)
        if index is None:
            continue
        host.turn(index)
        host.press(logical)
        host.c.snap_result(side, "accepted")
        host.c.snap_result(side, "ok")
    host.turn(bs["sel"])
    return host


def build(case):
    bs = case["bs"]
    mode = bs["mode"]
    if mode == "home":
        return build_home(bs)
    if mode == "tracks":
        return build_seek(bs) if bs.get("seek") else build_tracks(bs)
    if mode == "queue":
        return build_upnext(bs)
    if mode == "recent":
        return build_recent(bs)
    if mode == "explore":
        return build_explorer(bs)
    if mode == "windows":
        return build_windows(bs)
    raise AssertionError(f"unknown BS mode {mode}")


# ------------------------------------------------------------------ tests
class GrammarOracleTests(unittest.TestCase):
    def test_every_footer_matches_or_is_a_listed_deviation(self):
        used, compared, problems = Counter(), 0, []
        for case in GOLDEN["cases"]:
            if case["name"] in NOT_TESTED:
                continue
            host = build(case)
            got = host.footer()
            for slot, bs in enumerate(case["foot"]):
                compared += 1
                want = bs_slot(bs)
                if got[slot] == want:
                    continue
                tag = deviation(case, slot)
                if tag is None:
                    problems.append(f"{case['name']} slot {slot}: host {got[slot]} != BS {want}")
                else:
                    used[tag] += 1
        self.assertEqual(problems, [], f"{len(problems)} untagged differences")
        self.assertEqual(set(used), set(DEVIATIONS), "every listed deviation must still occur")
        self.assertGreater(compared, 900)

    def test_the_golden_covers_every_mode_and_state_picker_group(self):
        cases = GOLDEN["cases"]
        modes = {c["bs"]["mode"] for c in cases}
        self.assertEqual(modes, {"home", "tracks", "queue", "recent", "explore", "windows"})
        sims = Counter()
        for c in cases:
            for key, value in c["bs"].get("sim", {}).items():
                sims[(key, value)] += 1
        for key, values in (("source", ("queue", "airplay", "radio", "linein", "none")), ("sonosShuffle", ("on",)),
                            ("like", ("ok", "loading", "expired")),
                            ("upnext", ("normal", "loading", "foreign", "longshuffle")),
                            ("favs", ("real", "empty", "many")), ("art", ("list",)), ("pc", ("off",))):
            for value in values:
                self.assertTrue(sims[(key, value)], (key, value))
        busy = {(c["bs"]["mode"], (c["bs"].get("busy") or {}).get("kind")) for c in cases}
        self.assertTrue({("home", "start"), ("recent", "start"), ("recent", "pn"), ("tracks", "pn")} <= busy)
        self.assertTrue({c["bs"].get("seekState") for c in cases if c["bs"].get("seek")} >= {None, "jump", "fail"})
        self.assertTrue(any(c["bs"].get("liked") for c in cases))
        self.assertTrue(any(s.get("c") == PINK for c in cases for s in c["foot"]), "r2.2's liked heart")

    def test_the_token_map_covers_every_bs_key(self):
        keys = {s["key"] for c in GOLDEN["cases"] for s in c["foot"]} - {""}
        tokens = {TOKEN.get(k, k) for k in keys}
        self.assertLessEqual(tokens, set(P.ICONS), "every mapped token is a wire icon")
        self.assertEqual(keys & {"note", "list", "tracks", "next", "queue", "check", "rect-left", "rect-right"},
                         set(TOKEN), "every VOC-N06 remap is exercised")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    @unittest.skipUnless(DESIGN.is_dir(), "the r2.2 master is not present")
    def test_the_fixture_is_what_the_generator_produces(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "grammar.json"
            done = subprocess.run([shutil.which("node"), str(GENERATOR), str(DESIGN), str(out)],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            self.assertEqual(out.read_text(encoding="utf-8"), FIXTURE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

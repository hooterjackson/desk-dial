"""Desk Dial r3.1 (the 2026-09-29 feedback round, Job A): hold 4, the Playlists toggle, whole-queue
Tracks, paused Now Playing and the Home lights domain, with their Navigator cards.

- Paused keeps the Now Playing layout (artwork + buttons); STOPPED / no media still rest on idle.
- Button 4 acts on its RELEASE; the firmware's 1.0 s hold of slot 3 (`kh`) cancels the tap and fires
  the screen's secondary action: the launcher's knob domain swap (volume <-> the Lights area's
  brightness, 4 = All off / Turn on there), Play next in Recently Added / Playlists and the explorer,
  `move_next` in Up next; elsewhere the hold is simply the press.
- Recently Added 3 toggles the list's source Recently Added <-> Favourite playlists (crumb `playlists`,
  heading PLAYLISTS, icons `playlists` / `clock`), synchronised with the explorer.
- Tracks browses the whole queue (MIDI SKIPPER, rows 1..T from the playing row, a paged row cache,
  4 = `jump` to the focused row).
Headless: the controller on the cc5 fake clock, the runtime on manual lanes; no port, no window.
"""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import (Clock, FakeDevice, ManualExecutor, fail, queue_state, recent_page,  # noqa: E402
                         window_result)
from r3_support import CAPS_V6, R3Fixture  # noqa: E402
from control_center import device, navigator_model as NM, presentation, runtime as runtime_module  # noqa: E402
from control_center.controller import COPY, Controller  # noqa: E402
from control_center.runtime import Runtime  # noqa: E402
from control_center.simulation import SimulatedAppleMusic, SimulatedSonos, SimulatedWindows  # noqa: E402

PAUSED = dict(playback="PAUSED_PLAYBACK", can_play=True, can_pause=False)
AREA = {"configured": True, "online": True, "reason": "", "on": True, "bri": 62, "kelvin": 3200, "min_k": 2200,
        "max_k": 6500, "supports_ct": True, "available": True, "name": "Demo", "count": 3, "scenes": []}


def playlists(n=3):
    return [{"id": f"pl-{i}", "title": f"Playlist {i}", "artist": "", "kind": "playlist", "available": True,
             "accent": 0x300000 + i, "favourite": True, "art_template": ""} for i in range(n)]


def content(fixture, pressed=None):
    return NM.build_content(NM.read_snapshot(fixture.c, fixture.c.frame()), pressed=pressed)


class Base(R3Fixture):
    def hold4(self):
        self.c.hold(3, self.c.control_id)

    def music(self):
        self.press(0)

    def recent(self, total=30):
        self.music()
        self.press(1)
        self.complete("recent", recent_page(0, total))
        self.c.drain()

    def playlists(self, n=3):
        self.press(2)
        self.complete("favourite_playlists", playlists(n))


# ------------------------------------------------------------------ paused keeps Now Playing
class PausedTests(Base):
    def test_paused_keeps_now_playing_with_its_art_and_buttons(self):
        self.publish(dict(self.c.state, **PAUSED))
        self.tick(30)
        frame = self.wire()
        self.assertEqual((frame["layout"], frame["restLayout"], frame["status"]), ("nowPlaying", "nowPlaying", "Paused"))
        self.assertEqual(frame["buttons"][3]["icon"], "play")
        self.music()
        self.tick(30)
        self.assertEqual(self.frame()["layout"], "nowPlaying", "the Music space too")

    def test_stopped_and_no_media_still_rest_on_idle(self):
        self.publish(dict(self.c.state, playback="STOPPED"))
        self.assertEqual(self.frame()["layout"], "idle")
        self.publish(dict(self.c.state, playback="STOPPED", title="", queue_length=0, can_play=False,
                          can_pause=False, can_next=False, can_previous=False, source="none"))
        self.assertEqual(self.frame()["layout"], "idle")


# ------------------------------------------------------------------ hold 4 on Home: the knob domain
class HomeDomainTests(Base):
    def area(self):
        """Answer the lights_read the swap asked for with an area state (Demo, three lights)."""
        for effect in [e for e in self.c.pending.values() if e["kind"] == "lights_read"]:
            self.c.complete(effect["request"], dict(AREA))

    def test_hold_4_swaps_the_knob_to_the_lights_and_back(self):
        self.c.lights_state(AREA)
        self.hold4()
        self.area()
        self.assertEqual((self.c.screen.mode, self.c.home_domain), ("launcher", "lights"))
        control = self.c.control()
        self.assertEqual((control["profile"], control["min"], control["max"], control["position"]),
                         ("BINARIS BEER", 0, 99, 61))
        wire = self.wire()
        self.assertEqual((wire["layout"], wire["heading"], wire["title"], wire["subtitle"]),
                         ("lights", "LIGHTS", "Demo", "Demo · 62% · 3200 K"))
        self.assertEqual((wire["meta"], wire["metaTone"]), ("Knob sets brightness", "warm"))
        self.assertNotIn("crumb", wire, "the launcher has no crumb")
        self.assertEqual([(b["icon"], b["label"]) for b in wire["buttons"]],
                         [("list", "Music"), ("win", "Win"), ("bulb", "Lights"), ("power", "All off")])
        self.turn_to(69)                       # 70 % (while on, position = level - 1)
        self.tick(0.2)
        effects = self.c.drain()
        self.assertFalse([e for e in effects if e["kind"] == "volume"], "the knob no longer sets the volume")
        self.serve([e for e in effects])
        self.assertEqual(self.ha.bri, 70)
        self.assertEqual(self.frame()["layout"], "lightsbig")
        self.hold4()
        self.assertEqual(self.c.home_domain, "volume")
        self.assertEqual((self.frame()["layout"], self.frame()["status"], self.frame()["statusTone"]),
                         ("nowPlaying", "Knob sets volume", "warm"))
        self.turn_to(40)
        self.assertEqual(self.c.desired_volume, 40)

    def test_button_4_is_power_in_the_lights_domain(self):
        self.hold4()
        self.serve()
        self.press(3)
        effects = self.c.drain()
        self.assertEqual([e["on"] for e in effects if e["kind"] == "lights_power"], [False])
        self.assertFalse([e for e in effects if e["kind"] == "transport"], "not Play / Pause")
        self.serve(effects)
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["buttons"][3]["label"]),
                         ("Lights off", "Tap 4 to turn on", "Turn on"))

    def test_the_domain_is_remembered(self):
        self.hold4()
        self.serve()
        self.music()
        self.assertEqual(self.c.bounds()[2], self.c.display_volume, "Music keeps the volume knob")
        self.c.hold(0, self.c.control_id)
        self.assertEqual((self.c.screen.mode, self.c.home_domain), ("launcher", "lights"))
        self.assertEqual(self.wire()["layout"], "lights")
        self.c.disconnected()
        self.c.set_hardware(True)
        self.assertEqual(self.c.home_domain, "lights", "kept across a reconnect")

    def test_an_area_without_lights(self):
        self.c.lights_state(dict(AREA, count=0))
        self.hold4()
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"]), ("No lights in Demo", "Add them in Home Assistant"))
        self.assertFalse(wire["buttons"][3]["enabled"])
        self.press(3)
        self.assertEqual(self.frame()["meta"], "No lights in Demo")
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "lights_power"])

    def test_the_adapters_no_lights_and_area_missing_states(self):
        # Job C's area bridge reports both as offline states with a `detail`.
        base = dict(AREA, online=False, reason="unavailable", available=False)
        self.c.lights_state(dict(base, detail="no_lights", count=0))
        self.hold4()
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"]), ("No lights in Demo", "Add them in Home Assistant"))
        self.press(3)
        self.assertEqual(self.frame()["meta"], "No lights in Demo")
        self.c.lights_state(dict(base, detail="area_missing", count=None, name=""))
        self.tick(3)
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"]), ("Area not found", "Pick the area in Settings"))
        self.press(3)
        self.assertEqual(self.frame()["meta"], "Area not found")
        self.c.lights_state(AREA)
        self.assertEqual(self.wire()["title"], "Demo", "a light added to the Demo brings it back")

    def test_the_simulated_demo_area(self):
        from control_center.simulation import SimControls, SimulatedHomeAssistant
        try:
            self.ha = SimulatedHomeAssistant(SimControls(), clock=self.clock, sleep=self.clock.advance, area="demo")
        except TypeError:
            self.skipTest("a release-1 simulator without areas")
        self.c.lights_state(self.ha.read_state())
        self.hold4()
        self.serve()
        wire = self.wire()
        self.assertEqual((wire["heading"], wire["title"]), ("LIGHTS", "Demo"))
        self.assertTrue(wire["subtitle"].startswith("Demo · "), wire["subtitle"])
        self.press(3)
        self.serve()
        self.assertEqual(self.wire()["title"], "Lights off")

    def test_lights_not_set_up_is_shown_in_the_domain(self):
        self.c.lights_state({"configured": False, "online": False, "reason": "not_configured", "scenes": []})
        self.hold4()
        self.assertEqual((self.frame()["title"], self.frame()["subtitle"]),
                         ("Not connected", "Home Assistant"))

    def test_hold_4_where_there_is_no_secondary_action_is_the_press(self):
        self.music()
        self.hold4()
        self.assertEqual(self.one("transport")["direction"], "pause", "Music 4 = Play / Pause")

    def test_r22_ignores_hold_4(self):
        self.c.set_spaces(False)
        self.c._reenter("r2.2")
        self.c.drain()
        self.hold4()
        self.assertEqual(self.c.home_domain, "volume")
        self.assertEqual(self.c.drain(), [], "an r2.2 knob never sends it; ignored")


# ------------------------------------------------------------------ Recently Added <-> Playlists
class PlaylistsToggleTests(Base):
    def test_button_3_toggles_the_list_source(self):
        self.recent()
        self.turn_to(4)
        self.assertEqual([(b["icon"], b["label"]) for b in self.frame()["buttons"]],
                         [("back", "Back"), ("expand", "Full screen"), ("playlists", "Playlists"), ("play", "Play")])
        self.press(2)
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.loading"])
        self.complete("favourite_playlists", playlists(3))
        self.assertTrue([e for e in self.c.pending.values() if e["kind"] == "playlist_meta"])
        wire = self.wire()
        self.assertEqual((wire["heading"], wire["crumb"], wire["title"], wire["subtitle"]),
                         ("PLAYLISTS", "playlists", "Playlist 0", "Favourite playlist"))
        self.assertEqual((wire["meta"], wire["metaTone"]), ("Favourite playlists", "warm"), "1.2 s")
        self.tick(1.3)
        self.assertEqual(self.frame()["meta"], "1 / 3")
        self.assertEqual([(b["icon"], b["label"], b.get("lit")) for b in wire["buttons"]],
                         [("back", "Back", None), ("expand", "Full screen", None), ("playlists", "Recent", "on"),
                          ("play", "Play", None)])
        self.assertEqual(self.c.bounds(), (0, 2, 0))
        self.turn_to(2)
        self.press(2)
        self.assertEqual((self.c.screen.index, self.frame()["crumb"], self.frame()["meta"]),
                         (0, "recent", "Recently Added"), "r3.1 design: the toggle starts at item 1")
        self.tick(1.3)
        self.assertEqual(self.frame()["meta"], "1 / 30 · Artist")
        self.press(2)
        self.assertEqual((self.c.screen.index, self.frame()["title"]), (0, "Playlist 0"))

    def test_a_new_visit_starts_on_recently_added(self):
        self.recent()
        self.playlists()
        self.press(0)
        self.press(1)
        self.assertEqual((self.c.list_source, self.frame()["crumb"]), ("recent", "recent"))

    def test_play_a_playlist_from_the_knob_list(self):
        self.recent()
        self.playlists()
        self.turn_to(1)
        self.press(3)
        start = self.one("play_items")
        self.assertEqual((start["item_kind"], start["item"]["id"], start["lenient"]), ("playlist", "pl-1", True))
        self.assertEqual(self.c.screen.mode, "home")

    def test_hold_4_queues_an_album_or_a_playlist(self):
        self.recent()
        self.turn_to(3)
        self.hold4()
        job = self.one("play_next")
        self.assertEqual((job["item"]["id"], job["item_kind"]), ("album-3", "album"))
        self.complete("play_next", queue_state())
        self.playlists()
        self.hold4()
        job = self.one("play_next")
        self.assertEqual((job["item"]["id"], job["item_kind"], job["accent"]), ("pl-0", "playlist", 0x300000))

    def test_hold_4_takes_play_nexts_dims(self):
        self.publish(queue_state(shuffle=True, play_mode="SHUFFLE"))
        self.recent()
        self.hold4()
        effects = self.c.drain()
        self.assertFalse([e for e in effects if e["kind"] == "play_next"])
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.playnext.shuffle"])
        self.assertEqual([e["text"] for e in effects if e["kind"] == "toast"], [COPY["toast.playnext.shuffle"]])
        self.publish(queue_state(source="radio", queue_length=0, playlist_position=0))
        self.tick(3)
        self.hold4()
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.playnext.radio"])

    def test_the_explorer_opens_on_the_lists_source_and_returns_to_it(self):
        self.recent()
        self.playlists()
        self.turn_to(2)
        self.c.drain()
        self.press(1)
        opened = self.one("explorer_open")
        self.assertEqual((opened["source"], opened["index"]), ("favourites", 2))
        self.assertEqual(self.frame()["crumb"], "onScreenPlaylists")
        self.hold4()
        self.assertEqual(self.one("play_next")["item_kind"], "playlist", "hold 4 queues in the explorer too")
        self.complete("play_next", queue_state())
        self.press(0)
        self.assertEqual((self.c.screen.mode, self.c.list_source, self.c.screen.index), ("recent", "favourites", 2))
        self.assertEqual(self.frame()["crumb"], "playlists")
        self.press(1)                                   # open again, switch to the Recent tab, Back
        self.press(1)
        self.tick(0.3)
        self.press(0)
        self.assertEqual((self.c.list_source, self.frame()["crumb"]), ("recent", "recent"))

    def test_r22_recent_3_stays_play_next(self):
        self.c.set_spaces(False)
        self.c._reenter("r2.2")
        self.press(1)
        self.complete("recent", recent_page(0, 30))
        self.press(2)
        self.assertEqual(self.one("play_next")["item"]["id"], "album-0")


# ------------------------------------------------------------------ Up next hold 4
class UpNextHoldTests(Base):
    def test_hold_4_moves_the_focused_row_next(self):
        self.music()
        self.upnext()
        self.turn_to(self.c.screen.index + 3)
        row = self.c._upnext_focus_row()
        self.hold4()
        move = self.one("move_next")
        self.assertEqual((move["row"], move["expected_update_id"]), (row["row"], "rev-1"))
        self.assertEqual(self.c.screen.mode, "upnext")


# ------------------------------------------------------------------ whole-queue Tracks
class TracksQueueTests(Base):
    def enter(self):
        self.music()
        self.press(2)

    def page(self):
        read = [e for e in self.c.pending.values() if e["kind"] == "queue_window" and e.get("purpose") == "tracks_page"]
        for effect in read:
            self.c.complete(effect["request"], window_result(effect["start"], effect["count"], 12))

    def test_the_knob_browses_the_whole_queue_from_the_playing_row(self):
        self.enter()
        control = self.c.control()
        self.assertEqual((control["profile"], control["min"], control["max"], control["position"]),
                         ("MIDI SKIPPER", 0, 11, 4))
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["meta"]),
                         ("Pressure Front", "Mira Vale", "Turn to browse the queue"))
        self.assertEqual((wire["ring"]["style"], wire["ring"]["index"], wire["ring"]["count"], wire["ring"]["now"]),
                         ("queue", 4, 12, 4))   # r3.1 (19.10): the queue ring, the playing row as `now`
        self.assertEqual([b["label"] for b in wire["buttons"]], ["Back", "Up next", "Seek", "Play"])
        self.assertFalse(wire["buttons"][3]["enabled"], "4 on the playing row is unavailable")
        self.page()
        self.turn_to(8)
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["meta"], wire["metaTone"]),
                         ("Song 9", "Artist", "Skip to 9 / 12 · 4 plays", "success"))
        self.turn_to(1)
        self.assertEqual(self.frame()["meta"], "Back to 2 / 12 · 4 plays")

    def test_4_jumps_to_the_focused_row_and_stays_on_tracks(self):
        self.enter()
        self.page()
        self.turn_to(8)
        self.press(3)
        jump = self.one("jump")
        self.assertEqual((jump["row"], jump["name"], jump["expected_update_id"]), (9, "Song 9", "rev-1"))
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.tracks.skipping"])
        self.complete("jump", queue_state(P=9, title="Song 9"))
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 8))
        self.assertEqual((self.frame()["meta"], self.frame()["metaTone"]), ("Playing 9 / 12", "success"))
        self.tick(2.1)
        self.assertEqual(self.frame()["meta"], COPY["knob.meta.tracks.browse"])
        self.assertIsNone(self.c.start)

    def test_the_focus_follows_the_playing_row_when_it_was_on_it(self):
        self.enter()
        self.publish(queue_state(P=6))
        self.tick(0.5)
        self.assertEqual(self.c.screen.index, 5)
        self.assertEqual(self.c.bounds()[2], 5)
        self.turn_to(9)
        self.publish(queue_state(P=7))
        self.assertEqual(self.c.screen.index, 9, "a browsed focus stays where the user put it")

    def test_a_longer_queue_re_enters_with_the_new_bounds(self):
        self.enter()
        self.c.drain()
        self.publish(queue_state(T=30, queue_revision="rev-2"))
        self.tick(0.5)
        enters = [e for e in self.c.drain() if e["kind"] == "device_enter"]
        self.assertEqual(enters[-1]["control"]["max"], 29)

    def test_a_stream_keeps_the_transport_control(self):
        self.publish(queue_state(source="radio", queue_length=0, playlist_position=0))
        self.enter()
        control = self.c.control()
        self.assertEqual((control["profile"], control["max"]), ("MIDI CLACK JONES", 2))
        self.assertEqual(self.wire()["ring"]["style"], "transport")

    def test_queue_titles_come_from_the_page_cache(self):
        self.enter()
        self.page()
        self.assertEqual(self.c.queue_titles([1, 5, 12]), {1: "Song 1", 5: "Pressure Front", 12: "Song 12"})


# ------------------------------------------------------------------ the runtime: button 4 on release
class RuntimeButton4Tests(unittest.TestCase):
    def make(self, level=6, order=(0, 1, 2, 3)):
        with patch.object(runtime_module, "ThreadPoolExecutor", ManualExecutor):
            self.device = FakeDevice()
            controller = Controller(clock=Clock(), rng=random.Random(3))
            runtime = Runtime(controller, SimulatedSonos(), SimulatedAppleMusic(), SimulatedWindows(), self.device)
        self.addCleanup(runtime.shutdown)
        runtime.button_order = list(order)
        self.device.events.put({"kind": "connected", "capabilities": {"controlCenter": True, "presentation": level}})
        runtime.poll()
        c = runtime.controller
        request = c.request("state")
        c.complete(request, queue_state())
        c.device_ready(c.control_id)       # the knob's `ready` for the control the state re-entered
        c.drain()
        return runtime

    def event(self, runtime, **event):
        self.device.events.put({"id": runtime.controller.control_id, **event})
        runtime.poll()

    def transports(self, runtime):
        return [e for e in runtime.controller.pending.values() if e["kind"] == "transport"]

    def test_button_4_acts_on_its_release(self):
        runtime = self.make()
        self.event(runtime, kind="button", button=3)
        self.assertFalse(self.transports(runtime), "nothing on the press")
        self.event(runtime, kind="release", button=3)
        self.assertEqual([e["direction"] for e in self.transports(runtime)], ["pause"])

    def test_a_hold_cancels_the_tap_and_fires_the_hold(self):
        runtime = self.make()
        self.event(runtime, kind="button", button=3)
        self.event(runtime, kind="hold", button=3, raw=3)
        self.assertEqual(runtime.controller.home_domain, "lights")
        self.event(runtime, kind="release", button=3)
        self.assertFalse(self.transports(runtime), "the tap never fires after a hold")

    def test_a_lost_release_is_recovered_by_ready(self):
        runtime = self.make()
        self.event(runtime, kind="button", button=3)
        self.device.events.put({"kind": "ready", "id": runtime.controller.control_id, "held": 0})
        runtime.poll()
        self.assertEqual(len(self.transports(runtime)), 1)

    def test_holds_of_buttons_2_and_3_are_ignored(self):
        runtime = self.make()
        with patch.object(runtime.controller, "hold") as hold:
            self.event(runtime, kind="hold", button=1, raw=1)
            self.event(runtime, kind="hold", button=2, raw=2)
        hold.assert_not_called()

    def test_the_raw_button_of_slot_3_follows_the_button_order(self):
        runtime = self.make(order=(2, 0, 3, 1))
        self.event(runtime, kind="button", button=1)       # raw 1 = logical 3
        self.assertFalse(self.transports(runtime))
        self.event(runtime, kind="release", button=1)
        self.assertEqual(len(self.transports(runtime)), 1)

    def test_presentation_5_keeps_the_press(self):
        runtime = self.make(level=5)
        self.event(runtime, kind="button", button=0)       # r2.2 Home 1 = Play / Pause, on the press
        self.assertEqual(len(self.transports(runtime)), 1)


# ------------------------------------------------------------------ the Navigator cards
class NavigatorTests(Base):
    def test_home_lights_domain_card(self):
        self.c.lights_state(AREA)
        self.hold4()
        c = content(self)
        self.assertEqual((c.kind, c.path, c.caption, c.big, c.unit),
                         ("lights", "Home › Demo", "Brightness", "62", "%"))
        self.assertEqual([k.label for k in c.keys], ["Music", "Windows", "Lights", "Lights off"])
        self.assertEqual((c.hold_hint, c.hold_text), (True, "4 Knob to music"))

    def test_playlists_card(self):
        self.recent()
        c = content(self)
        self.assertEqual([k.label for k in c.keys], ["Back", "Full screen", "Playlists", "Play"])
        self.assertEqual(c.hold_text, "1 Home · 4 Queue")
        self.playlists()
        meta = next(e for e in self.c.pending.values() if e["kind"] == "playlist_meta" and e["playlist_id"] == "pl-0")
        self.c.complete(meta["request"], {"id": "pl-0", "count": 12, "mosaic": []})
        self.tick(1.3)                                  # the toggle's `Favourite playlists` line
        c = content(self)
        self.assertEqual((c.kind, c.path, c.title, c.artist, c.status),
                         ("covers", "Music › Playlists", "Playlist 0", "Favourite playlist", "1 / 3 · 12 songs"))
        self.assertEqual([k.label for k in c.keys], ["Back", "Full screen", "Recent", "Play"])
        self.assertEqual([cv.key for cv in c.covers], ["pl-0", "pl-1", "pl-2"])

    def test_playlist_covers_take_the_explorer_identity(self):
        from control_center import scene_music as SM
        from control_center.stage.scenes.navigator_covers import plan_for
        item = {"id": "pl-1", "title": "Playlist 1", "kind": "playlist"}
        key, plan = plan_for(item, "favourites")
        self.assertEqual(plan.kind, "pending", "the tile until playlist_meta lands")
        self.assertEqual(key, SM.explorer_plan(item, "favourites").key)
        key2, plan2 = plan_for(dict(item, mosaic=[], art_state="none"), "favourites")
        self.assertEqual(plan2.kind, "generated")

    def test_tracks_queue_card_keys(self):
        self.music()
        self.press(2)
        self.turn_to(7)
        c = content(self)
        self.assertEqual([(k.label, k.enabled) for k in c.keys][3], ("Play", True))
        self.assertEqual(c.status, "8 / 12 · Press 4 to play")


class ContractTests(unittest.TestCase):
    def test_the_playlists_crumb_is_appended(self):
        self.assertEqual(presentation.CRUMBS[-1], "playlists")
        self.assertEqual(presentation.CRUMBS[:9], ("music", "recent", "onScreenRecent", "onScreenPlaylists",
                                                   "tracks", "upnext", "windows", "lights", "scenes"))



class FrameContractTests(Base):
    def test_every_new_frame_passes_the_bridge(self):
        self.c.lights_state(AREA)
        self.hold4()
        self.wire()                                     # Home, lights domain
        self.turn_to(69)                       # 70 % (while on, position = level - 1)
        self.wire()                                     # ... its big value
        self.hold4()
        self.recent()
        self.playlists()
        self.wire()                                     # MUSIC › PLAYLISTS
        self.press(0)
        self.press(2)
        self.turn_to(9)
        self.wire()                                     # whole-queue Tracks


# ------------------------------------------------------------------ Claude Design r3.1 (the delta adopted)
MEMBERS = [{"entity_id": "light.ceiling", "name": "Ceiling", "on": True, "bri": 80, "kelvin": 3000, "available": True},
           {"entity_id": "light.desk", "name": "Desk lamp", "on": True, "bri": 44, "kelvin": 3400, "available": True},
           {"entity_id": "light.shelf", "name": "Shelf strip", "on": False, "bri": 0, "kelvin": None,
            "available": True}]


class DesignDeltaTests(Base):
    def test_hold_4_exists_only_where_the_design_has_it(self):
        self.assertEqual(self.c.hold_action(), "Knob to lights")
        self.music()
        self.assertEqual(self.c.hold_action(), "", "Music: 4 acts on release, no hold")
        self.press(2)
        self.assertEqual(self.c.hold_action(), "", "Tracks")
        self.press(0)
        self.press(1)
        self.complete("recent", recent_page(0, 30))
        self.assertEqual(self.c.hold_action(), "Queue")

    def test_hold_marker_on_the_frames_with_hold_4(self):
        from r3_support import CAPS_V5
        self.assertIs(self.wire()["holdMarker"], True, "Home")
        self.assertNotIn("holdMarker", self.wire(CAPS_V5), "never to an older knob")
        self.music()
        self.assertNotIn("holdMarker", self.wire(), "Music: no hold 4")
        self.press(1)
        self.complete("recent", recent_page(0, 30))
        self.assertIs(self.wire()["holdMarker"], True, "Recently Added")

    def test_landing_feedback_at_the_hold(self):
        # Job B's landings: the swap = plain ok on the swapped frame; queue = ok/queued at the hold (not
        # the result); a refusal = err/refused.
        self.hold4()
        self.assertEqual(self.frame()["feedback"], {"kind": "ok", "seq": self.c.feedback_seq})
        self.hold4()
        self.recent()
        self.hold4()
        self.assertEqual(self.frame()["feedback"]["moment"], "queued")
        seq = self.c.feedback_seq
        self.complete("play_next", queue_state())
        self.assertEqual(self.c.feedback_seq, seq, "no second flash on the result")
        self.music()
        self.upnext()
        self.hold4()                                    # the playing row: refused
        self.assertEqual((self.frame()["feedback"]["kind"], self.frame()["feedback"]["moment"]), ("err", "refused"))

    def test_the_queue_ring_on_the_wire_and_for_older_knobs(self):
        from r3_support import CAPS_V5
        self.music()
        self.upnext()
        ring = self.wire()["ring"]
        self.assertEqual((ring["style"], ring["now"]), ("queue", self.c.screen.upnext.P - 1))
        down = self.wire(CAPS_V5)["ring"]
        self.assertEqual(down["style"], "selection")
        self.assertEqual(device.v5_parse(self.wire(CAPS_V5))[1], [])
        with self.assertRaises(ValueError):
            device._frame({"id": 1, "mode": "TRACKS", "target": "Demo", "value": "", "detail": "", "status": "",
                           "layout": "tracks", "buttons": [{"label": "Back", "enabled": True, "icon": "back"}] * 4,
                           "ring": {"style": "queue", "value": 0, "index": 5, "count": 5}}, CAPS_V6)

    def test_recently_added_subtitle_is_not_the_artist_again(self):
        self.recent()
        frame = self.frame()
        self.assertEqual((frame["subtitle"], frame["meta"]), ("Album", "1 / 30 · Artist"))

    def test_queued_copy(self):
        self.recent()
        self.turn_to(3)
        self.hold4()
        self.complete("play_next", queue_state())
        frame = self.frame()
        self.assertEqual((frame["meta"], frame["metaTone"]), ("Queued \u00b7 Album 3", "success"))
        self.tick(2.3)
        self.assertNotEqual(self.frame()["meta"], "Queued \u00b7 Album 3", "2.2 s")

    def test_up_next_hold_4_plays_next_or_is_already_playing(self):
        self.music()
        self.upnext()
        P = self.c.screen.upnext.P
        self.assertEqual(self.c.screen.index, P - 1, "Up next opens on the Tracks focus (the playing row)")
        self.hold4()
        self.assertEqual((self.frame()["meta"], self.frame()["metaTone"]), ("Already playing", "error"))
        self.assertFalse([e for e in self.c.drain() if e["kind"] == "move_next"])
        self.turn_to(P + 1)
        row = self.c._upnext_focus_row()
        self.hold4()
        move = self.one("move_next")
        self.c.complete(move["request"], queue_state())
        self.assertEqual(self.frame()["meta"], "Plays next \u00b7 " + row["title"])

    def test_up_next_and_tracks_share_the_focused_row(self):
        self.music()
        self.press(2)
        self.turn_to(8)
        self.press(1)                                   # Up next on the same row
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("upnext", 8))
        self.turn_to(9)
        self.press(0)                                   # Back: Tracks takes that row
        self.assertEqual((self.c.screen.mode, self.c.screen.index), ("tracks", 9))
        self.press(2)                                   # Seek, then Cancel: back on the playing row
        self.press(0)
        self.assertEqual(self.c.screen.index, self.c._position()[0] - 1)

    def test_nothing_loaded(self):
        self.publish(dict(self.c.state, playback="STOPPED", title="", artist="", queue_length=0,
                          playlist_position=0, can_play=False, can_pause=False, can_next=False, can_previous=False,
                          source="none"))
        self.press(3)
        self.assertEqual(self.frame()["status"], "Nothing loaded \u00b7 pick in Recent")
        self.music()
        self.press(2)
        self.assertEqual((self.c.screen.mode, self.frame()["status"]), ("home", "Nothing loaded"))
        c = content(self)
        self.assertEqual((c.title, c.artist), ("Nothing playing", "Pick an album in Recent"))

    def test_the_runtime_lets_a_hold_pass_where_there_is_none(self):
        runtime = RuntimeButton4Tests("test_button_4_acts_on_its_release")
        runtime.addCleanup = self.addCleanup
        rt = runtime.make()
        c = rt.controller
        c.button(0, c.control_id)                       # Music
        c.device_ready(c.control_id)
        c.drain()
        runtime.event(rt, kind="button", button=3)
        runtime.event(rt, kind="hold", button=3, raw=3)
        self.assertFalse(runtime.transports(rt), "no hold on Music: the kh passes")
        self.assertEqual(rt.held_for().get(3) is not None, True)
        runtime.event(rt, kind="release", button=3)
        self.assertEqual([e["direction"] for e in runtime.transports(rt)], ["pause"], "the release is the tap")
        self.assertEqual(rt.held_for(), {})

    def test_lights_area_lines_and_turn_targets(self):
        self.c.lights_state(dict(AREA, lights=MEMBERS, on_count=2, bri=62, kelvin=3200))
        self.press(2)
        self.c.drain()
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["meta"], wire["metaTone"]),
                         ("Demo", "62% \u00b7 3200 K", "2 of 3 on \u00b7 average", "secondary"))
        self.turn_to(69)                       # 70 % (while on, position = level - 1)
        self.assertEqual(self.frame()["volumeCaption"], "Brightness \u00b7 average")
        self.tick(0.2)
        write = self.one("lights_set")
        self.assertEqual(write["targets"], ["light.ceiling", "light.desk"], "only the lights that are on")
        c = content(self)
        self.assertEqual((c.path, c.area_line), ("Lights \u203a Demo", "3 lights \u00b7 2 on"))
        self.assertEqual([(r.name, r.value) for r in c.lights_rows],
                         [("Ceiling", "80% \u00b7 3000 K"), ("Desk lamp", "44% \u00b7 3400 K"), ("Shelf strip", "Off")])
        self.assertEqual(c.geometry(), "lights+3")

    def test_an_unavailable_light(self):
        members = [dict(m, on=True, bri=62, kelvin=3200) for m in MEMBERS]
        members[2].update(available=False)
        self.c.lights_state(dict(AREA, lights=members, on_count=2))
        self.hold4()
        self.assertEqual((self.frame()["meta"], self.frame()["metaTone"]), ("Knob sets brightness", "warm"))
        self.tick(2)
        self.assertEqual((self.frame()["meta"], self.frame()["metaTone"]), ("Shelf strip unavailable", "error"))
        c = content(self)
        self.assertEqual((c.area_line, c.area_rgb), ("3 lights \u00b7 2 on \u00b7 1 unavailable", NM.ERROR))
        self.c.lights_state(dict(AREA, lights=[dict(m, available=False) for m in MEMBERS], on_count=0,
                                 online=False, reason="unavailable", detail="lights_unavailable"))
        wire = self.wire()
        self.assertEqual((wire["title"], wire["subtitle"], wire["meta"]),
                         ("Lights unavailable", "Demo \u00b7 3 lights", "Check them in Home Assistant"))
        self.turn_to(40)
        self.assertEqual(self.frame()["meta"], "Lights unavailable", "a turn is denied with the reason")

    def test_all_off_turn_goes_to_the_whole_area(self):
        self.c.lights_state(dict(AREA, on=False, bri=0, lights=[dict(m, on=False) for m in MEMBERS], on_count=0))
        self.press(2)
        self.c.drain()
        self.turn_to(3)
        self.tick(0.2)
        self.assertIsNone(self.one("lights_set")["targets"], "all off: every available light turns on")

    def test_scenes_carry_their_kind_and_no_scenes_is_named(self):
        self.lights()
        self.press(1)
        c = content(self)
        self.assertEqual([r.tag for r in c.rows][:3], ["Scene", "Scene", "Script"])
        self.press(0)
        self.c.lights_state(dict(self.ha.read_state(), scenes=[]))
        self.press(1)
        self.assertEqual(self.frame()["meta"], "No scenes in Demo")

    def test_hold_chips_fill_with_the_hold(self):
        from control_center.navigator import Navigator

        class Backend:
            def __init__(self):
                self.posts = []

            def post(self, state):
                self.posts.append(state)

        class Runtime:
            presentation_level = 6
            device_connected = True
            touch_seq = 0
            open_surfaces = ()
            reduced_motion = False

            def __init__(self, c):
                self.controller = c
                self.held = {}

            def held_for(self):
                return dict(self.held)

            def lcd_media(self, *a, **k):
                raise RuntimeError

        backend = Backend()
        nav = Navigator(backend, mode="pinned")
        rt = Runtime(self.c)
        nav.update(rt, self.c.frame())
        self.assertEqual(backend.posts[-1]["content"].holds, (("4", "Knob to lights", 0.0),))
        rt.held = {3: 0.5}
        nav.update(rt, self.c.frame())
        self.assertEqual(backend.posts[-1]["content"].holds, (("4", "Knob to lights", 0.5),))
        self.recent()
        rt.held = {0: 0.3}
        nav.update(rt, self.c.frame())
        self.assertEqual(backend.posts[-1]["content"].holds, (("1", "Home", 0.5), ("4", "Queue", 0.0)))

    def test_the_hold_row_and_area_block_render(self):
        from control_center.stage.scenes import navigator as NS
        self.assertAlmostEqual(NS.card_height("rows", True) - NS.card_height("rows", False), 24.0)
        self.assertGreater(NS.content_height("lights+3"), NS.content_height("lights"))
        spr = NS.hold_sprite(2.0, (("1", "Home", 0.6), ("4", "Queue", 0.0)))
        self.assertEqual(spr.size, (int(round(NS.INNER * 2)), int(round(NS.HOLD_H * 2))))
        self.c.lights_state(dict(AREA, lights=MEMBERS, on_count=2))
        self.press(2)
        c = content(self)
        area = NS.area_sprite(c, 2.0)
        self.assertEqual(area.size[1], int(round(NS.area_block_height(3) * 2)))



class CompactLightsCardTests(Base):
    """r3.1.1 (design_handoff_nano_d_r3.1.1_lights_card): the compact Navigator Lights card."""

    def lights(self, **state):
        self.c.lights_state(dict(AREA, **state))
        self.press(2)
        self.c.drain()
        return content(self)

    def test_uniform_area(self):
        members = [dict(m, on=True, bri=62, kelvin=3200) for m in MEMBERS]
        c = self.lights(lights=members, on_count=3)
        self.assertEqual((c.bri_caption, c.bri_text, c.temp_text), ("Brightness", "62%", "3200 K"))
        self.assertEqual((c.summary_bold, c.summary_rest), ("Demo", "3 lights · 3 on"))
        self.assertEqual((c.bri_a, c.temp_a), (1.0, 0.5))
        self.assertEqual(c.lights_rows, (), "no per-light rows while the area is uniform")
        self.assertEqual(c.geometry(), "lights+0")

    def test_mixed_area_shows_the_rows_and_avg(self):
        c = self.lights(lights=MEMBERS, on_count=2)
        self.assertEqual(c.bri_caption, "Brightness · avg")
        self.assertEqual(len(c.lights_rows), 3)
        self.assertEqual(c.geometry(), "lights+3")

    def test_all_off(self):
        members = [dict(m, on=False, bri=0) for m in MEMBERS]
        c = self.lights(lights=members, on_count=0, on=False, bri=0)
        self.assertEqual((c.bri_text, c.bri_frac, c.bri_a, c.temp_a), ("Off", 0.0, 1.0, 0.5))

    def test_one_unavailable_is_red_with_rows(self):
        members = [dict(m, on=True, bri=62, kelvin=3200) for m in MEMBERS]
        members[2].update(available=False)
        c = self.lights(lights=members, on_count=2)
        self.assertEqual((c.summary_rest, c.summary_rgb), ("3 lights · 2 on · 1 unavailable", NM.ERROR))
        self.assertEqual(len(c.lights_rows), 3)

    def test_the_running_scene_leads_the_summary(self):
        members = [dict(m, on=True, bri=62, kelvin=3200) for m in MEMBERS]
        self.c.lights_state(dict(AREA, lights=members, on_count=3))
        self.press(2)
        snap = NM.read_snapshot(self.c, self.c.frame())
        snap["lights"].update(scene_label="Focus", adjusted=False)
        self.assertEqual(NM.build_content(snap).summary_bold, "Focus")
        snap["lights"].update(adjusted=True)
        self.assertEqual(NM.build_content(snap).summary_bold, "Demo", "the area name after a manual change")

    def test_not_connected(self):
        self.c.lights_state(dict(AREA, online=False, reason="offline"))
        self.press(2)
        c = content(self)
        self.assertEqual((c.bri_text, c.temp_text, c.bri_a, c.temp_a), ("—", "—", 0.3, 0.3))
        self.assertEqual((c.summary_bold, c.summary_rgb), ("Home Assistant", NM.ERROR))


class CompactCardStabilityTests(Base):
    """User 2026-09-29: turning the Demo (4 lights) flickered the card between the per-light rows and the one
    summary line: the lights report one by one mid-fade. Drift within LIGHTS_NEAR is uniform, and the look
    holds while the knob drives the lights; a real mix still shows once they settle."""

    FOUR = [{"entity_id": f"light.l{i}", "name": f"L{i}", "on": True, "bri": 62, "kelvin": 3200, "available": True}
            for i in range(4)]

    def report(self, levels, kelvins=None):
        members = [dict(m, bri=b, kelvin=(kelvins[i] if kelvins else 3200)) for i, (m, b) in
                   enumerate(zip(self.FOUR, levels))]
        self.c.lights_state(dict(AREA, count=4, lights=members, on_count=4, bri=levels[0]))

    def test_staggered_reports_mid_turn_keep_the_compact_card(self):
        self.report([62, 62, 62, 62])
        self.press(2)
        self.c.drain()
        self.assertEqual(content(self).lights_rows, ())
        self.turn_to(80)
        self.tick(0.3)
        self.c.drain()
        self.report([80, 71, 66, 62])                 # mid-fade: the lights report one by one
        self.assertEqual(content(self).lights_rows, (), "held while the knob drives the lights")
        self.assertEqual(content(self).bri_caption, "Brightness")
        self.tick(3.0)
        self.report([80, 79, 80, 78])                 # settled, a little drift: still uniform
        self.tick(0.1)
        self.assertEqual(content(self).lights_rows, ())

    def test_a_real_mix_shows_once_quiet(self):
        self.report([80, 44, 80, 80])
        self.press(2)
        self.c.drain()
        self.tick(3.0)
        self.assertEqual(len(content(self).lights_rows), 4)
        self.assertEqual(content(self).bri_caption, "Brightness · avg")

if __name__ == "__main__":
    unittest.main()

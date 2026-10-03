"""Timed handoff presentation follows confirmed state without changing haptics.

Desktop v7 (CONTROL_CENTER_V5.md): Home is Play/Pause · Browse · Tracks · Win (section 3.1);
v5 buttons carry no colour (the section 2.2 downgrade adds one for an older knob); the
desktop-only text is ``controller.notice`` and never reaches the knob (section 2.4)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.controller import Controller, Screen


class Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def state(volume=28, **kwargs):
    data = dict(online=True, volume=volume, group_revision="hall-group", group_label="Hall",
                playback="PLAYING", can_pause=True, can_play=False, can_next=True,
                can_previous=True, title="Pressure Front", artist="Mira Vale", queue_length=4,
                track_id="track-1")
    data.update(kwargs)
    return data


class HandoffPresentationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.c = Controller(clock=self.clock)
        self.publish(state())
        self.c.last_poll = self.clock()
        self.c.drain()

    def publish(self, value):
        self.c.complete(self.c.request("state"), value)

    def command(self, kind):
        return next(e for e in self.c.drain() if e["kind"] == kind)

    def confirm_volume(self, value):
        self.c.tick()
        effect = self.command("volume")
        self.c.complete(effect["request"], state(value))

    def pause(self):
        self.publish(state(playback="PAUSED_PLAYBACK", can_pause=False, can_play=True))

    def test_initial_sync_has_no_volume_flash_and_all_four_icons(self):
        frame = self.c.frame()
        self.assertEqual(frame["layout"], "nowPlaying")
        self.assertFalse(frame["volumeVisible"])
        self.assertEqual([b["icon"] for b in frame["buttons"]], ["pause", "list", "tracks", "win"])
        self.assertEqual([b["label"] for b in frame["buttons"]], ["Pause", "Browse", "Tracks", "Win"])
        self.assertTrue(all("color" not in b for b in frame["buttons"]), "v5 buttons carry no colour")

    def test_reveal_hides_1_4_seconds_after_last_detent_without_reentry(self):
        control = self.c.control_id
        self.c.turn(1)
        self.confirm_volume(29)
        self.clock.advance(1.0)
        self.assertEqual(self.c.frame()["layout"], "volume")
        self.c.turn(1)
        self.confirm_volume(30)
        self.clock.advance(1.399)
        self.assertEqual(self.c.frame()["layout"], "volume")
        self.clock.advance(.002)
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.assertEqual(self.c.control_id, control)
        self.assertFalse(any(e["kind"] == "device_enter" for e in self.c.drain()))

    def test_pending_after_deadline_waits_for_actual_confirmation(self):
        self.c.turn(1)
        self.c.tick()
        effect = self.command("volume")
        self.clock.advance(8)
        self.assertEqual(self.c.frame()["layout"], "volume")
        self.assertEqual(self.c.frame()["confirmedVolume"], 28)
        self.assertEqual(self.c.frame()["activity"], "pending")
        self.c.complete(effect["request"], state(29))
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")

    def test_external_change_reveals_2_6_seconds_but_polling_does_not_extend(self):
        self.publish(state(65))
        self.assertEqual(self.c.frame()["status"], "Changed on Sonos")
        self.clock.advance(2.0)
        self.publish(state(65))
        self.assertEqual(self.c.frame()["layout"], "volume")
        self.clock.advance(.601)
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")

    def test_local_readback_never_becomes_an_external_reveal(self):
        self.c.turn(1)
        self.clock.advance(1.5)
        self.confirm_volume(29)
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.assertNotEqual(self.c.frame()["status"], "Changed on Sonos")

    def test_paused_keeps_now_playing_after_browse_and_ordinary_polls(self):
        # r3.1 (2026-09-29): paused keeps the Now Playing layout (artwork + buttons), never idle.
        self.pause()
        self.clock.advance(2)
        self.pause()
        self.c.button(1)
        self.clock.advance(2.001)
        self.c.home()
        frame = self.c.frame()
        self.assertEqual((frame["layout"], frame["restLayout"]), ("nowPlaying", "nowPlaying"))
        self.assertEqual(frame["buttons"][0]["icon"], "play")
        self.assertTrue(frame["buttons"][0]["enabled"])

    def test_first_paused_readback_stays_now_playing(self):
        self.c = Controller(clock=self.clock)
        self.pause()
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.clock.advance(60)
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")

    def test_turn_while_paused_temporarily_reveals_then_returns(self):
        self.pause()
        self.clock.advance(4)
        self.c.turn(1)
        self.assertEqual(self.c.frame()["layout"], "volume")
        self.assertEqual(self.c.frame()["volumeCaption"], "Paused · Pressure Front")
        self.c.tick()
        effect = self.command("volume")
        self.c.complete(effect["request"], state(29, playback="PAUSED_PLAYBACK", can_play=True, can_pause=False))
        self.clock.advance(1.401)
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")

    def test_resume_press_exits_idle_immediately_and_success_resets_pause_age(self):
        self.pause()
        self.clock.advance(5)
        self.c.button(0)
        effect = self.command("transport")
        self.assertEqual(effect["direction"], "play")
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.assertEqual(self.c.frame()["activity"], "pending")
        self.c.complete(effect["request"], state())
        self.clock.advance(20)
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.pause()
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")

    def test_no_media_has_immediate_central_view_but_stream_and_stopped_resume_work(self):
        self.publish(state(playback="STOPPED", title="", artist="", queue_length=0,
                           can_pause=False, can_play=False, can_next=False, can_previous=False))
        frame = self.c.frame()
        self.assertEqual(frame["layout"], "idle")
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [False, True, False, True])
        self.c.button(2)                  # Tracks, dimmed with nothing playing: refused in place
        self.assertEqual(self.c.screen.mode, "home")
        self.publish(state(playback="STOPPED", title="Stream", queue_length=0, can_play=True,
                           can_pause=False, can_next=False, can_previous=False))
        self.assertTrue(self.c.frame()["buttons"][0]["enabled"])
        self.publish(state(title="", queue_length=0, can_next=False, can_previous=False))
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.assertTrue(self.c.frame()["buttons"][0]["enabled"])

    def test_offline_error_and_host_disconnect_never_look_like_empty_music(self):
        self.c.screen.status = "Playback partially failed"   # desktop-only text (section 2.4)
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.assertEqual((self.c.frame()["activity"], self.c.frame()["status"]), ("idle", ""))
        self.c.screen.status = ""
        self.pause()
        self.clock.advance(10)
        self.publish(state(online=False))
        # Sonos offline is the Home notice (list geometry), never the empty-music idle view.
        frame = self.c.frame()
        self.assertEqual((frame["layout"], frame["activity"]), ("notice", "offline"))
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"]),
                         ("Sonos unavailable", "Looking for Sonos…", "Windows still works"))
        self.assertEqual((frame["ring"]["style"], frame["ring"]["value"]), ("level", frame["confirmedVolume"]))
        self.publish(state())
        self.c.disconnected()
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")

    def test_a_failure_keeps_the_paused_now_playing_view(self):
        # knob-model: a failure only flashes `err`; r3.1: paused rests on Now Playing (art + buttons).
        self.pause()
        self.clock.advance(10)
        self.c.screen.status = "Playback partially failed"
        frame = self.c.frame()
        self.assertEqual((frame["layout"], frame["restLayout"], frame["status"], frame["activity"]),
                         ("nowPlaying", "nowPlaying", "Paused", "idle"))
        self.assertEqual((frame["buttons"][0]["icon"], frame["buttons"][0]["enabled"]), ("play", True),
                         "the paused view, not the empty-music one")
        self.assertEqual(self.c.screen.status, "Playback partially failed", "the desktop keeps the reason")

    def test_failed_volume_does_not_wait_forever_and_flashes_err(self):
        # knob-model has no sticky Home error: the failed write is the `err` flash, the
        # resting copy is the model's own, and the desktop keeps the full reason.
        self.c.turn(1)
        self.c.tick()
        effect = self.command("volume")
        self.clock.advance(8)
        self.c.complete(effect["request"], error="Volume was not confirmed")
        frame = self.c.frame()
        self.assertEqual((frame["layout"], frame["status"], frame["statusTone"], frame["activity"]),
                         ("nowPlaying", "", "meta", "idle"))
        self.assertEqual(frame["feedback"]["kind"], "err")
        self.assertIsNone(self.c.desired_volume)
        self.assertEqual(self.c.notice, "Volume was not confirmed", "the desktop keeps the reason")
        entry = [e for e in self.c.drain() if e["kind"] == "device_enter"][-1]["control"]["frame"]
        self.assertEqual(entry["feedback"], frame["feedback"], "the entry frame carries the flash")

    def test_discarded_or_obsolete_volume_write_does_not_flash(self):
        self.c.turn(1)
        self.c.tick()
        effect = self.command("volume")
        self.c.complete(effect["request"], error="Pending volume discarded after connection changed")
        self.assertIsNone(self.c.feedback)
        self.c.turn(1)
        self.clock.advance(0.2)  # the 100 ms write spacing
        self.c.tick()
        effect = self.command("volume")
        self.publish(state(12, group_revision="new-group"))  # the write now targets an old group
        self.c.complete(effect["request"], error="The Sonos group changed.")
        self.assertIsNone(self.c.feedback)
        self.assertEqual(self.c.frame()["status"], "Speaker group changed", "r2.2 copy (C5-70)")

    def test_group_change_and_reconnection_do_not_reveal_stale_volume(self):
        self.c.turn(1)
        self.publish(state(12, group_revision="new-group"))
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")
        self.c.disconnected()
        self.c.ready = True
        self.c.screen.status = ""
        self.c.state["online"] = False
        self.publish(state(41))
        self.assertEqual(self.c.frame()["layout"], "nowPlaying")

    def test_frame_is_pure_and_never_creates_haptic_or_network_effects(self):
        self.pause()
        self.c.drain()
        control, screen = self.c.control_id, self.c.screen.view_id
        self.clock.advance(5)
        for _ in range(10):
            self.assertEqual(self.c.frame()["layout"], "nowPlaying")   # r3.1: paused keeps Now Playing
        self.assertEqual(self.c.drain(), [])
        self.assertEqual((self.c.control_id, self.c.screen.view_id), (control, screen))

    def test_icons_distinguish_back_open_and_the_mode_actions(self):
        self.c.screen = Screen(mode="recent", status="", pages=[{"items": [
            {"title": "Album", "id": "one", "kind": "album", "available": True}], "next": None}])
        frame = self.c.frame()
        self.assertEqual(frame["layout"], "recent")
        self.assertEqual([b["icon"] for b in frame["buttons"]], ["back", "expand", "playnext", "play"])
        self.assertTrue(all("color" not in b for b in frame["buttons"]))
        self.c.screen = Screen(mode="windows", status="", windows={"items": [
            {"id": "w", "title": "A window", "available": True}]})
        self.assertEqual([b["icon"] for b in self.c.frame()["buttons"]], ["back", "snapleft", "snapright", "switch"])

if __name__ == "__main__":
    unittest.main()

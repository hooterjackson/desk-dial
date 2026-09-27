"""Home playback uses confirmed capabilities and absolute, non-replayed commands.

Desktop v7 (CONTROL_CENTER_V5.md section 3.1): Home 1 dims only for its listed codes
(`sonos_unavailable`, `starting`, `transport_pending`, `nothing_playing`); an unstable
transport or a missing capability leaves it enabled and its press is ignored silently
(never a blind toggle). v5 buttons carry no colour; the desktop text is `notice`."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.controller import Controller
from control_center.simulation import SimulatedSonos
from control_center.sonos import SonosAdapter, SonosError, GroupChanged, TrackChanged
from test_cc_music import FakeSpeaker, MemoryStore


class HomePlaybackTests(unittest.TestCase):
    def setUp(self):
        self.sonos = SimulatedSonos()
        self.c = Controller()
        self.c._state(self.sonos.read_state())
        self.c.screen.status = ""
        self.c.drain()

    def press(self):
        self.c.button(0)
        return [effect for effect in self.c.drain() if effect["kind"] == "transport"]

    def test_pause_resume_keeps_home_volume_and_profile_without_reentry(self):
        control = self.c.control()
        for direction, label, status in (("pause", "Play", "Paused"), ("play", "Pause", "")):
            with self.subTest(direction=direction):
                effect, = self.press()
                self.assertEqual(effect["direction"], direction)
                self.assertFalse(self.c.frame()["buttons"][0]["enabled"])
                self.assertEqual(self.c.frame()["activity"], "pending")
                self.assertNotEqual(self.c.frame()["status"], "Skipping...")
                result = self.sonos.transport(direction, effect["expected_group_revision"], effect["expected_track_id"])
                self.c.complete(effect["request"], result)
                frame = self.c.frame()
                self.assertEqual(frame["buttons"][0], {"label": label, "enabled": True, "icon": label.lower()})
                self.assertEqual((frame["activity"], frame["status"]), ("idle", status))
                self.assertEqual((self.c.control_id, self.c.bounds(), self.c.control()["profile"]),
                                 (control["id"], (0, 100, 28), control["profile"]))
                self.assertEqual(self.c.drain(), [])

    def test_pending_home_press_does_not_queue_duplicate_or_invert_action(self):
        effect, = self.press()
        self.assertEqual(effect["direction"], "pause")
        for _ in range(8):
            self.assertEqual(self.press(), [])
        self.assertEqual(self.c.state["playback"], "PLAYING")

    def test_offline_unknown_transitioning_or_missing_capability_cannot_dispatch(self):
        for change in ({"online": False}, {"playback": "UNKNOWN"},
                       {"playback": "TRANSITIONING"}, {"can_pause": False},
                       {"playback": "STOPPED", "can_play": False}):
            with self.subTest(change=change):
                self.c.state.update(self.sonos.read_state())
                self.c.state.update(change)
                if change == {"online": False}:
                    self.assertFalse(self.c.frame()["buttons"][0]["enabled"], "sonos_unavailable dims it")
                self.assertEqual(self.press(), [])
                self.assertIsNone(self.c.command_request)

    def test_playback_failure_keeps_confirmed_state_and_error_visible(self):
        # knob-model playAck(fail): playReq = playing, flash('err'). The failure is the
        # `err` flash, never a sticky Home error: the rest is the confirmed state's own
        # copy. The desktop keeps the full text.
        resting = Controller()
        resting._state(self.sonos.read_state())
        resting.screen.status = ""
        effect, = self.press()
        self.c.complete(effect["request"], error="Pause was not confirmed. Refresh the room state before retrying.")
        self.assertEqual(self.c.state["playback"], "PLAYING")
        frame = self.c.frame()
        self.assertEqual(frame["feedback"]["kind"], "err")
        fields = ("layout", "status", "statusTone", "activity")
        self.assertEqual(tuple(frame[name] for name in fields), ("nowPlaying", "", "meta", "idle"))
        self.assertEqual(tuple(frame[name] for name in fields), tuple(resting.frame()[name] for name in fields),
                         "the resting model state, as if nothing had been pressed")
        self.assertEqual((frame["buttons"][0]["label"], frame["buttons"][0]["enabled"]), ("Pause", True))
        self.assertIn("not confirmed", self.c.notice)

    def test_completion_after_browse_does_not_replace_library_screen(self):
        effect, = self.press()
        self.c.button(1)
        status = self.c.screen.status
        self.c.complete(effect["request"], self.sonos.transport("pause", effect["expected_group_revision"]))
        self.assertEqual((self.c.screen.mode, self.c.screen.status), ("recent", status))
        self.assertEqual(self.c.state["playback"], "PAUSED_PLAYBACK")

    def test_completion_under_windows_updates_home_state_without_changing_picker(self):
        effect, = self.press()
        self.c.button(3)                  # Home 4: Win
        opened = [e for e in self.c.drain() if e["kind"] == "windows_open"][0]
        self.c.complete(opened["request"], {"items": [{"id": "w", "title": "Window", "available": True}],
                                           "origin": {"hwnd": 1, "pid": 2}})
        view = self.c.screen.view_id
        self.c.complete(effect["request"], self.sonos.transport("pause", effect["expected_group_revision"]))
        self.assertEqual((self.c.screen.mode, self.c.screen.view_id), ("windows", view))
        self.assertEqual(self.c.state["playback"], "PAUSED_PLAYBACK")
        self.c.dismiss_windows()
        self.assertEqual((self.c.screen.mode, self.c.frame()["status"]), ("home", "Paused"))

    def test_non_home_left_button_remains_back(self):
        self.c.button(2)                  # Home 3: Tracks
        self.assertEqual(self.c.frame()["buttons"][0]["label"], "Back")
        self.assertEqual(self.press(), [])
        self.assertEqual(self.c.screen.mode, "home")


class PlaybackSpeaker(FakeSpeaker):
    def __init__(self):
        super().__init__()
        self.playback = "PLAYING"
        self.available_actions += ["Pause"]
        self.playback_commands = []
        self.readbacks = []
        self.confirm = True
        self.avTransport.Pause = lambda arguments, **kwargs: self.change_playback("pause", arguments)
        self.avTransport.Play = lambda arguments, **kwargs: self.change_playback("play", arguments)

    def change_playback(self, direction, arguments):
        self.playback_commands.append((direction, dict(arguments)))
        if self.confirm:
            self.playback = "PLAYING" if direction == "play" else "PAUSED_PLAYBACK"

    def get_current_transport_info(self):
        if self.playback_commands and self.readbacks:
            self.playback = self.readbacks.pop(0)
        return {"current_transport_state": self.playback}


class SonosPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.speaker = PlaybackSpeaker()
        self.adapter = SonosAdapter("192.168.1.50", soco_factory=lambda host: self.speaker,
                                    share_link_factory=lambda value: value, recovery_store=MemoryStore())
        self.state = self.adapter.read_state()

    def send(self, direction):
        return self.adapter.transport(direction, self.state["group_revision"], self.state["track_id"])

    def test_read_capabilities_and_execute_pause_then_resume_without_queue_changes(self):
        self.assertTrue(self.state["can_pause"])
        self.assertFalse(self.state["can_play"])
        paused = self.send("pause")
        self.assertEqual(paused["playback"], "PAUSED_PLAYBACK")
        self.assertTrue(paused["can_play"])
        self.assertFalse(paused["can_pause"])
        self.assertEqual(self.send("play")["playback"], "PLAYING")
        self.assertEqual(self.speaker.playback_commands,
                         [("pause", {"InstanceID": 0}), ("play", {"InstanceID": 0, "Speed": 1})])
        self.assertEqual(self.speaker.removals, [])
        self.assertEqual(self.speaker.seeks, [])
        self.assertEqual(self.speaker.skips, [])

    def test_external_pause_or_play_already_satisfied_never_toggles_or_replays(self):
        self.speaker.playback = "PAUSED_PLAYBACK"
        self.speaker.available_actions.remove("Pause")
        self.assertEqual(self.send("pause")["playback"], "PAUSED_PLAYBACK")
        self.speaker.playback = "PLAYING"
        self.assertEqual(self.send("play")["playback"], "PLAYING")
        self.assertEqual(self.speaker.playback_commands, [])

    def test_missing_capability_or_transitioning_state_does_not_issue_command(self):
        self.speaker.available_actions.remove("Pause")
        with self.assertRaisesRegex(SonosError, "does not currently support Pause"):
            self.send("pause")
        self.speaker.playback = "TRANSITIONING"
        with self.assertRaisesRegex(SonosError, "does not currently support Play"):
            self.send("play")
        self.assertEqual(self.speaker.playback_commands, [])

    def test_group_and_track_guards_prevent_stale_playback_action(self):
        self.speaker.track["uri"] = "song:changed"
        with self.assertRaises(TrackChanged):
            self.send("pause")
        self.speaker.group.uid = "NEWGROUP"
        with self.assertRaises(GroupChanged):
            self.send("pause")
        self.assertEqual(self.speaker.playback_commands, [])

    def test_delayed_readback_is_confirmed_without_sending_pause_again(self):
        self.speaker.readbacks = ["PLAYING", "TRANSITIONING", "PAUSED_PLAYBACK"]
        now = [0.0]
        with patch("control_center.sonos.time.monotonic", side_effect=lambda: now[0]), \
             patch("control_center.sonos.time.sleep", side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            result = self.send("pause")
        self.assertEqual(result["playback"], "PAUSED_PLAYBACK")
        self.assertEqual(len(self.speaker.playback_commands), 1)
        self.assertGreaterEqual(now[0], 0.1)

    def test_unconfirmed_playback_reports_failure_without_replaying(self):
        self.speaker.confirm = False
        now = [0.0]
        with patch("control_center.sonos.time.monotonic", side_effect=lambda: now[0]), \
             patch("control_center.sonos.time.sleep", side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            with self.assertRaisesRegex(SonosError, "Pause was not confirmed"):
                self.send("pause")
        self.assertEqual(len(self.speaker.playback_commands), 1)
        self.assertEqual(now[0], 2.0)
        self.assertEqual(self.adapter._last_state["playback"], "PLAYING")

    def test_group_change_after_command_aborts_readback(self):
        original = self.speaker.avTransport.Pause
        def pause(arguments, **kwargs):
            original(arguments, **kwargs)
            self.speaker.group.uid = "EXTERNAL_GROUP"
        self.speaker.avTransport.Pause = pause
        with self.assertRaises(GroupChanged):
            self.send("pause")
        self.assertEqual(len(self.speaker.playback_commands), 1)


if __name__ == "__main__":
    unittest.main()

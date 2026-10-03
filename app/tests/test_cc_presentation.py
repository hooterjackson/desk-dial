"""Presentation must preserve control state and expose actionable exceptions (desktop v7).

PresentationTests was the v6 (v4 grammar) suite; it is rewritten for the v7 controller:
CONTROL_CENTER_V5.md (K3) sections 2.3-2.4 (busy codes, the copy line), 3.1-3.4 (the button
map, dims, the Head shake, silent guards), 5.1-5.7 (frames per mode), 8 (confirmation), 9.10
(outcome copy) and 13.4 (reconnect); PRESENTATION_V5.md (K1) sections 3.1 (legacy `counter`),
5.2 (tones and LCD inks), 8.6.11 (status width) and 14.2 (slimming).

Button colours are asserted through K1's v5 tone rule and LCD inks (presentation.button_tone_v5 /
button_ink_v5). A v5 frame carries no LED colour for a button (only an assigned snap side's
accent, with lit "on", K1 5.1); the LED level of each tone is K2's (the alive suites), not this
module's.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cc5_support import COPY, Fixture, copy_text, fail, queue_state, recent_page, windows_snapshot  # noqa: E402
from control_center.controller import measure  # noqa: E402
from control_center.device import _frame  # noqa: E402
from control_center.presentation import FOOTER_INK, accent_ink, button_ink_v5, button_tone_v5  # noqa: E402

CAPS_P5 = {"controlCenter": 1, "leaseMs": 2000, "presentation": 5, "glyphs": "latin-ext-a"}
CAPS_P2 = {"controlCenter": 1, "leaseMs": 2000, "presentation": 2}


class PresentationTests(Fixture):
    """Home, PLAYING row 5 of 12 (`Pressure Front` · `Mira Vale`, volume 28), a fake clock."""

    def palette(self, frame=None):
        frame = frame if frame is not None else self.frame()
        layout = frame["layout"]
        buttons = list(enumerate(frame["buttons"]))
        tones = [button_tone_v5(i, b["icon"], b["enabled"], b.get("lit"), layout) for i, b in buttons]
        inks = [button_ink_v5(i, b["icon"], b["enabled"], b.get("lit"), b.get("color", 0), layout)
                for i, b in buttons]
        return tones, inks

    def assert_palette(self, tones):
        """Tones follow K1 5.2; with no accent, each LCD ink is that tone's footer ink, and no
        button carries a colour."""
        frame = self.frame()
        got, inks = self.palette(frame)
        self.assertEqual(got, tones)
        self.assertEqual(inks, [FOOTER_INK[tone] for tone in tones])
        self.assertFalse([b for b in frame["buttons"] if "color" in b], "a button colour only with a snap side")

    def refused(self, logical, copy_id):
        """K3 3.3: a dimmed press never acts; it shows its reason and plays the Head shake."""
        seq = self.c.feedback_seq
        self.press(logical)
        self.assertEqual(self.c.feedback_seq, seq + 1)
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.c.transient.copy_id, copy_id)

    def ignored(self, logical):
        """K3 3.2 / 3.4: a press that only plays the knob's Press moment (no shake, no copy, no effect)."""
        seq, transient = self.c.feedback_seq, self.transient()
        self.press(logical)
        self.assertEqual(self.c.feedback_seq, seq)
        self.assertEqual(self.transient(), transient)

    # ------------------------------------------------------------------ Home
    def test_content_first_frame_has_no_routine_status_or_control_mutation(self):
        self.c.screen.status = "Volume confirmed"   # desktop-side text (K3 2.2), never knob copy
        before = (self.c.control_id, deepcopy(self.c.state), deepcopy(self.c.screen))
        frame = _frame(self.frame(), CAPS_P5)
        self.assertEqual((frame["title"], frame["subtitle"], frame["value"]), ("Pressure Front", "Mira Vale", "28%"))
        self.assertEqual((frame["status"], frame.get("activity", "idle")), ("", "idle"))
        self.assertNotIn("counter", frame, "K1 3.1: the legacy counter is never sent (slimmed, 14.2)")
        self.assertEqual(before, (self.c.control_id, self.c.state, self.c.screen))
        self.assertEqual(self.c.drain(), [])

    def test_pending_volume_shows_confirmed_value_until_readback(self):
        # K3 5.1.3 / 8: the requested value is big, `Setting…` until Sonos confirms; the confirmed
        # value travels as confirmedVolume (the LED's confirmed span).
        self.turn_to(31)
        frame = self.frame()
        self.assertEqual((frame["value"], frame["status"], frame["statusTone"], frame["activity"]),
                         ("31%", "Setting…", "meta", "pending"))
        self.assertEqual((frame["confirmedVolume"], frame["layout"]), (28, "volume"))
        self.tick(0.1)
        request = self.c.volume_request
        self.assertIsNotNone(request)
        self.c.complete(request, {**self.c.state, "volume": 31, "_applied_volume": 31})
        frame = self.frame()
        self.assertEqual((frame["activity"], frame["status"], frame["confirmedVolume"]), ("idle", "", 31))

    def test_error_is_compact_and_full_reason_is_retained(self):
        """K3 8 / 9.10 / 12.6: a failed start shows the short approved copy on the status line (error
        tone, <= 160 px, K1 8.6.11) with the Head shake and a toast; the full reason stays on the
        desktop notice, never on the knob."""
        self.browse()
        self.press(3)
        reason = "Playback partially failed after an external queue change; recovery needs review"
        self.complete("play_items", error=fail(reason, partial=True))
        frame = self.frame()
        self.assertEqual((frame["status"], frame["statusTone"]), (COPY["knob.status.start_failed"], "error"))
        self.assertLessEqual(measure(frame["status"], 12), 160)
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assertEqual(self.c.notice, reason)
        self.assertNotIn("recovery needs review", json.dumps(frame, ensure_ascii=False))
        self.assertEqual([t["text"] for t in self.effects("toast")], [copy_text("toast.start.failed", name="Album 0")])
        self.tick(2.7)                                 # start_fail_status_ms 2600
        self.assertEqual(self.frame()["status"], "")

    def test_connection_recovery_clears_only_connection_notices(self):
        self.c.disconnected()
        self.c.set_hardware(True)
        frame = self.frame()
        self.assertEqual((frame["status"], frame["activity"]), (COPY["knob.status.connecting"], "loading"))
        self.c.device_ready(self.c.control_id)
        frame = self.frame()
        self.assertEqual((self.c.screen.mode, frame["layout"], frame["activity"]), ("home", "nowPlaying", "idle"))
        self.publish(queue_state(online=False))
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["activity"], frame["title"], frame["status"]),
                         ("notice", "offline", "Sonos unavailable", "Sonos unavailable"))
        self.publish(queue_state())
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["activity"], frame["title"], frame["status"]),
                         ("nowPlaying", "idle", "Pressure Front", ""))

    def test_a_failure_line_survives_a_sonos_recovery(self):
        """A failure line is not a connection notice: it keeps its own 2600 ms through a recovery."""
        self.browse()
        self.press(3)
        self.complete("play_items", error=fail("Sonos did not start"))
        self.publish(queue_state(online=False))
        self.publish(queue_state())
        self.assertEqual(self.frame()["status"], COPY["knob.status.start_failed"])
        self.tick(2.7)
        self.assertEqual(self.frame()["status"], "")

    def test_home_and_track_action_tones(self):
        # Pause, Browse, Tracks, Win: navigation (K1 5.2 row 10); only Button 4's confirms are green.
        self.assertEqual([b["label"] for b in self.frame()["buttons"]], ["Pause", "Browse", "Tracks", "Win"])
        self.assert_palette(["nav", "nav", "nav", "nav"])
        # Paused Home Play is the one green outside Button 4 (row 9).
        self.publish(queue_state(playback="PAUSED_PLAYBACK", can_play=True, can_pause=False))
        self.assert_palette(["go", "nav", "nav", "nav"])
        self.publish(queue_state())
        self.tracks()
        # Back, Up next, Seek, Skip: Skip at Neutral is dim (`neutral`, ignored).
        self.assert_palette(["nav", "nav", "nav", "dim"])
        self.ignored(3)
        self.turn_to(2)
        self.assert_palette(["nav", "nav", "nav", "go"])
        self.press(3)
        self.assertEqual(self.frame()["activity"], "pending")
        self.assert_palette(["nav", "nav", "nav", "dim"])              # `transport_pending`
        self.complete("transport", error=fail("Could not skip"))
        # A failure alone neither colours a button nor removes the retry.
        self.assertEqual(self.c.feedback["kind"], "err")
        self.assert_palette(["nav", "nav", "nav", "go"])
        # Next not offered in the middle of the queue: dim `skip_unavailable`, with its reason.
        self.publish(queue_state(can_next=False))
        self.assert_palette(["nav", "nav", "nav", "dim"])
        self.refused(3, "knob.meta.skip.next_unavailable")

    # ------------------------------------------------------------------ Recently Added
    def test_unavailable_item_and_the_end_of_the_list_keep_their_meanings(self):
        """v6's paged list ended in a `More` entry and counted `1 / 1` in the legacy counter; v7's
        flat list (K3 5.2) ends on its last real item (`· end`), and `counter` is never sent."""
        self.browse(total=2, count=2, overrides={0: {"available": False}})
        frame = self.frame()
        self.assertEqual((frame["title"], frame["titleTone"], frame.get("artDim")), ("Album 0", "muted", True))
        self.assertEqual((frame["meta"], frame["activity"]), ("1 / 2", "idle"))
        self.assertEqual((frame["ring"]["style"], frame["ring"].get("unavailable")), ("selection", 1),
                         "the landmark of the unavailable entry is omitted (VOC-R05)")
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [True, True, False, False])
        self.refused(3, "knob.meta.item_unavailable")
        self.assertEqual(self.transient(), "Not available")
        self.assertFalse(self.effects("play_items"), "a dimmed press never acts")
        self.assertNotIn("counter", _frame(self.frame(), CAPS_P5))
        self.assertEqual(_frame(self.frame(), CAPS_P2)["counter"], "", "a cc4 knob keeps the field, never a count")
        self.tick(2.1)                                                   # reason_meta_ms 2000
        self.turn_to(1)
        frame = self.frame()
        self.assertEqual((frame["title"], frame["meta"], frame.get("artDim")), ("Album 1", "2 / 2 · end", None))
        self.assertEqual(self.c.control()["max"], 1, "no extra More entry after the last item")

    def test_recent_play_and_disabled_action_tones(self):
        self.press(1)
        self.c.drain()
        # First page loading: Play next and Play dim `loading` (ignored); Open works (K3 3.1).
        self.assert_palette(["nav", "nav", "dim", "dim"])
        self.ignored(3)
        self.complete("recent", recent_page(0, total=3, count=3, overrides={1: {"available": False}}))
        # Recent Play is the green confirm; Play next is never green.
        self.assertEqual([b["label"] for b in self.frame()["buttons"]], ["Back", "Open", "Play next", "Play"])
        self.assert_palette(["nav", "nav", "nav", "go"])
        self.turn_to(1)
        self.assert_palette(["nav", "nav", "dim", "dim"])              # `item_unavailable`
        self.turn_to(2)
        self.assertEqual(self.frame()["meta"], "3 / 3 · end")
        self.assert_palette(["nav", "nav", "nav", "go"])

    def test_library_failure_is_not_presented_as_an_empty_library(self):
        # K3 5.2.3: error, sign-in and empty are three different screens.
        self.press(1)
        self.complete("recent", error=fail("Apple Music could not be reached. Check the connection and retry.",
                                           status=500))
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"]), ("Library not loaded", "Home, then Browse"))
        self.assertEqual((frame["meta"], frame["metaTone"], frame["activity"], frame["ring"]["style"]),
                         ("Windows still works", "secondary", "error", "off"))
        self.assertNotEqual(frame["title"], COPY["knob.title.recent_empty"])
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [True, False, False, False])
        self.refused(3, "knob.meta.library_error")
        self.press(0)
        self.press(1)
        self.complete("recent", error=fail("Apple Music authorization expired or access was denied.",
                                           outcome="signin_expired", status=401))
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"], frame["metaTone"], frame["activity"]),
                         ("Apple Music sign-in expired", "Renew on your PC", "Windows still works", "secondary",
                          "error"))
        self.refused(3, "knob.meta.signin_expired")
        self.assertEqual(self.c.transient.tone, "error")
        self.press(0)
        self.press(1)
        self.complete("recent", recent_page(0, total=0, count=0))
        frame = self.frame()
        self.assertEqual((frame["title"], frame["subtitle"], frame["meta"], frame["activity"]),
                         ("Nothing recently added", "Apple Music library", "", "idle"))
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [True, True, False, False])
        self.ignored(3)                                                  # `empty`: explained on screen

    def test_recent_start_goes_home_and_dims_only_what_would_race_it(self):
        """v6 kept Recent open and dimmed its Back while a play was out; v7 goes Home at once with
        `Starting…` (K3 8, U11), dims Home 1 (`starting`, ignored there) and never dims a Back."""
        self.browse()
        self.press(3)
        self.assertEqual(self.c.screen.mode, "home")
        frame = self.frame()
        self.assertEqual((frame["status"], frame["activity"]), ("Starting…", "pending"))
        self.assert_palette(["dim", "nav", "nav", "nav"])
        self.ignored(0)
        self.press(1)                                                    # Browse during the start
        self.complete("recent", recent_page(0, 60))
        self.assert_palette(["nav", "nav", "dim", "dim"])                # Play next / Play: `starting`
        self.refused(3, "knob.meta.busy.starting")                       # elsewhere: reason + shake
        self.press(0)
        self.assertEqual(self.c.screen.mode, "home", "Back is never dimmed")

    def test_rotating_during_a_skip_keeps_pending_feedback(self):
        self.tracks()
        self.turn_to(2)
        self.press(3)
        self.turn_to(0)
        frame = self.frame()
        self.assertEqual((frame["activity"], frame["meta"]), ("pending", "Skipping…"))
        self.assertFalse(frame["buttons"][3]["enabled"])
        self.ignored(3)                                                  # its own skip: ignored
        self.assertEqual(len([e for e in self.c.pending.values() if e["kind"] == "transport"]), 1)

    def test_turning_during_a_start_keeps_starting(self):
        """K3 2.4: on Home `Starting…` outranks the volume reveal's own status."""
        self.browse()
        self.press(3)
        self.turn_to(31)
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["value"], frame["status"], frame["activity"]),
                         ("volume", "31%", "Starting…", "pending"))

    # ------------------------------------------------------------------ Windows (K3 5.7)
    def test_pending_sonos_does_not_animate_windows(self):
        self.turn_to(31)                                                 # a volume write is out
        self.assertEqual(self.frame()["activity"], "pending")
        self.open_windows(1)
        frame = self.frame()
        self.assertEqual((frame["layout"], frame["activity"], frame["title"]), ("windows", "idle", "Window 0"))
        self.assertNotIn("counter", _frame(frame, CAPS_P5))

    def test_pending_window_switch_is_a_silent_guard(self):
        """v6 dimmed Switch while it was out; K3 3.4 makes the sub-second switch a silent guard (a
        dim would flicker): every button stays enabled and every press is ignored."""
        self.open_windows(2)
        self.press(3)
        self.one("windows_activate")
        frame = self.frame()
        self.assertEqual((frame["activity"], frame["meta"]), ("pending", "Switching…"))
        self.assertEqual([b["enabled"] for b in frame["buttons"]], [True, True, True, True])
        for logical in (3, 1, 2, 0):
            self.ignored(logical)
        self.assertEqual([e["kind"] for e in self.effects() if e["kind"].startswith("windows_")], [])
        self.assertEqual(self.c.screen.mode, "windows")

    def test_window_switch_snap_and_closed_tones(self):
        self.press(3)
        snapshot = windows_snapshot(3)
        snapshot["items"][2]["available"] = False
        self.c.complete(self.one("windows_open")["request"], snapshot)
        self.c.drain()
        self.assertEqual([b["label"] for b in self.frame()["buttons"]], ["Back", "Snap left", "Snap right", "Switch"])
        # Back is never red (v7 has no Cancel); Switch is the green confirm.
        self.assert_palette(["nav", "nav", "nav", "go"])
        self.press(1)
        self.one("windows_snap")
        self.c.snap_result("left", "accepted")
        frame = self.frame()
        tones, inks = self.palette(frame)
        self.assertEqual(tones, ["nav", "on", "nav", "go"])
        self.assertEqual((frame["buttons"][1]["lit"], frame["buttons"][1]["color"]), ("on", 0x204061))
        self.assertEqual(inks[1], accent_ink(0x204061), "the assigned side's LCD ink (K1 5.3)")
        self.c.snap_result("left", "ok")
        self.turn_to(2)                                                  # a closed window
        frame = self.frame()
        self.assertEqual(self.palette(frame)[0], ["nav", "dim", "dim", "dim"], "`closed`; enabled false wins")
        self.assertEqual(frame["meta"], "Left: App1 · pick right")
        self.refused(3, "knob.meta.windows.closed")

    # ------------------------------------------------------------------ the host adapter
    def test_utf8_bounds_and_invalid_activity_stripped(self):
        value = self.frame()
        value["title"] = "é" * 100
        self.assertEqual(len(_frame(value)["title"].encode()), 96)
        # Contract v4 section 7: activity is optional; an invalid value is stripped
        # (the knob then uses its default, idle) instead of rejecting the frame.
        for activity in ("pulse", None, 1, {"state": "idle"}):
            value["activity"] = activity
            self.assertNotIn("activity", _frame(value))

    def test_lcd_font_fallback_does_not_change_source_strings(self):
        value = self.frame()
        value["title"] = "Renée Lys — Maré Alta…"
        value["subtitle"] = "L'œuvre d’aujourd’hui"
        normalized = _frame(value)
        self.assertEqual(normalized["title"], "Renee Lys - Mare Alta...")
        self.assertEqual(normalized["subtitle"], "L'oeuvre d'aujourd'hui")
        self.assertEqual(value["title"], "Renée Lys — Maré Alta…")
        v5 = _frame(deepcopy(value), CAPS_P5)                           # latin-ext-a keeps them
        self.assertEqual((v5["title"], v5["subtitle"]), ("Renée Lys — Maré Alta…", "L'œuvre d’aujourd’hui"))


class PresentationV5ConstantTests(unittest.TestCase):
    """PRESENTATION_V5.md section 3.6 (Python storage), 4.2, 4.3 and 5.3: constants and pure helpers."""

    def test_section_3_6_constants(self):
        from control_center import presentation as P
        self.assertEqual(P.LAYOUTS[7:], ("seek", "explorer", "upnext"))
        self.assertEqual(P.LAYOUTS[:7], P.LAYOUTS_V4)
        self.assertEqual(P.RING_STYLES, P.RING_STYLES_V4 + ("lap",))
        self.assertEqual(P.ICON_ENUM[13:], ("expand", "clock", "playlists", "playnext", "seek", "shuffle", "heart",
                                            "snapleft", "snapright"))
        self.assertEqual(set(P.ICONS), set(P.ICON_ENUM))
        self.assertEqual(P.BUTTON_LIT, ("on", "off"))
        self.assertEqual(P.FEEDBACK_MOMENTS, ("queued", "shuffle", "like", "unlike", "snap", "started"))
        self.assertEqual((P.LAP_COUNT_MAX, P.FRAME_BUDGET_BYTES_V5, P.FRAME_BUDGET_BYTES), (59999, 1400, 1100))
        self.assertEqual((P.INK_ERROR, P.FOOTER_INK["dim"], P.FOOTER_INK["on"], P.FOOTER_INK["off"],
                          P.FOOTER_INK["liked"]),
                         (0xFF8474, 0x5A5A5A, 0xFFFFFF, 0x7A7A7A, 0xA3244A))   # [r2.2] liked (3.6)
        # OQ-5 [r2.2]: #FF285A is only the desktop row heart, never an LCD ink.
        self.assertNotIn(0xFF285A, P.FOOTER_INK.values())
        self.assertFalse(hasattr(P, "INK_HEART"))
        self.assertEqual(P.ICON_DOWNGRADE, {"expand": "more", "clock": "list", "playlists": "list",
                                            "playnext": "more", "seek": "tracks", "shuffle": "switch",
                                            "heart": "more", "snapleft": "prev", "snapright": "next"})
        self.assertTrue(set(P.ICON_DOWNGRADE.values()) <= set(P.ICONS_V4))

    def test_the_firmware_header_appends_the_same_enums(self):
        header = (Path(__file__).resolve().parents[2] / "firmware" / "src" / "cc_presentation.h")
        if not header.is_file():
            self.skipTest("firmware tree not present")
        text = header.read_text(encoding="utf-8")
        self.assertIn("CC_LAYOUT_SEEK, CC_LAYOUT_EXPLORER, CC_LAYOUT_UPNEXT", text)
        self.assertIn("CC_RING_LAP", text)
        self.assertIn("CC_ICON_EXPAND, CC_ICON_CLOCK, CC_ICON_PLAYLISTS, CC_ICON_PLAYNEXT, CC_ICON_SEEK,\n"
                      "    CC_ICON_SHUFFLE, CC_ICON_HEART, CC_ICON_SNAPLEFT, CC_ICON_SNAPRIGHT", text)
        self.assertIn("constexpr uint16_t CC_LAP_COUNT_MAX = 59999;", text)
        self.assertIn("int32_t ringNow = -1;", text)
        # [r2.2] 3.6: CCButtonTone appends 7 CC_TONE_LIKED after on / off (append-only).
        self.assertRegex(text, r"CC_TONE_NONE, CC_TONE_DIM, CC_TONE_STOP, CC_TONE_GO, CC_TONE_NAV,\s+"
                               r"CC_TONE_ON, CC_TONE_OFF,[^\n]*\n\s+CC_TONE_LIKED\b")

    def test_window_rules(self):
        from control_center.presentation import window_first, window_first_v5
        for index, count, v4, v5 in ((0, 20, 0, 0), (19, 20, 0, 0), (10, 45, 1, 0), (30, 45, 21, 20),
                                     (44, 45, 25, 25), (40001, 40002, 39982, 39982), (5, 101, 0, 0)):
            self.assertEqual((window_first(index, count), window_first_v5(index, count)), (v4, v5), (index, count))

    def test_mmss(self):
        from control_center.presentation import mmss
        self.assertEqual([mmss(s) for s in (0, 9, 74, 600, 3599, 59998)],
                         ["0:00", "0:09", "1:14", "10:00", "59:59", "999:58"])

    def test_sat_matches_the_led_engine(self):
        from control_center.presentation import sat_rgb
        from control_center.alive_lights import sat
        import random
        rng = random.Random(54)
        colors = [rng.randrange(1 << 24) for _ in range(20000)] + [0x000080, 0x808080, 0x7F7F9C, 0x7F7F9D, 0xFFFFFF]
        for color in colors:
            expected = sat(((color >> 16) & 255, (color >> 8) & 255, color & 255))
            got = sat_rgb(color)
            self.assertEqual(got, None if expected is None else expected[0] << 16 | expected[1] << 8 | expected[2],
                             hex(color))

    def test_accent_ink(self):
        from control_center.presentation import accent_ink, relative_luminance
        self.assertEqual(accent_ink(0x000080), 0x4040FF)          # the contract's example
        self.assertEqual(accent_ink(0), 0xFFFFFF)                 # no colour: the plain `on` ink
        self.assertEqual(accent_ink(0x808080), 0xFFFFFF)          # sat() falls back to WARM
        self.assertEqual(accent_ink(0x00FF00), 0x00FF00)          # already >= 3:1
        for color in (0x0000FF, 0x2B579A, 0x400040, 0x123456, 0xD83B01):
            ink = accent_ink(color)
            self.assertGreaterEqual(relative_luminance(ink), 0.10, hex(color))

    def test_v5_tone_table(self):
        from control_center.presentation import button_ink_v5, button_tone_v5
        rows = [  # (slot, icon, enabled, lit, color, layout) -> (tone, ink): section 5.2, first match wins
            ((0, "", True, "on", 0, "recent"), ("none", 0)),
            ((1, "clock", False, "on", 0, "explorer"), ("dim", 0x5A5A5A)),
            ((0, "cancel", True, "on", 0, "windows"), ("stop", 0xFF8474)),
            ((2, "heart", True, "on", 0x123456, "upnext"), ("liked", 0xA3244A)),   # [r2.2] row 4, never sat()
            ((2, "heart", True, "on", 0, "upnext"), ("liked", 0xA3244A)),
            ((2, "heart", False, "on", 0, "upnext"), ("dim", 0x5A5A5A)),        # enabled false always wins
            ((2, "heart", True, "off", 0, "upnext"), ("off", 0x7A7A7A)),
            ((2, "heart", True, None, 0, "upnext"), ("nav", 0xE6E6E6)),
            ((1, "snapleft", True, "on", 0x000080, "windows"), ("on", 0x4040FF)),
            ((2, "seek", True, "on", 0, "seek"), ("on", 0xFFFFFF)),
            ((2, "playlists", True, "off", 0, "explorer"), ("off", 0x7A7A7A)),
            ((3, "play", True, "on", 0, "recent"), ("on", 0xFFFFFF)),
            ((3, "next", True, None, 0, "tracks"), ("go", 0x6ED996)),
            ((0, "play", True, None, 0, "idle"), ("go", 0x6ED996)),   # paused Home Play
            ((0, "play", True, None, 0, "recent"), ("nav", 0xE6E6E6)),
            ((3, "win", True, None, 0, "nowPlaying"), ("nav", 0xE6E6E6)),
        ]
        for args, expected in rows:
            slot, icon, enabled, lit, color, layout = args
            self.assertEqual((button_tone_v5(slot, icon, enabled, lit, layout),
                              button_ink_v5(slot, icon, enabled, lit, color, layout)), expected, args)


if __name__ == "__main__":
    unittest.main()

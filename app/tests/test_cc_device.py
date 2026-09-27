import json
import base64
from copy import deepcopy
import zlib
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.device import DeviceBridge, PacedSerial, _frame


def frame(style="selection", count=3):
    return {"mode": "WINDOWS", "target": "Chrome", "value": "Research", "detail": "Preview", "status": "2/3",
            "buttons": [{"label": name, "enabled": True, "color": color} for name, color in
                        (("Music", 0x74C9FF), ("Back", 0xFF7B7B), ("Win", 0x74C9FF), ("Select", 0x75D69A))],
            "ring": {"style": style, "value": 0, "index": 1 if count > 1 else 0, "count": count}}


def control(ident=1, position=1):
    return {"id": ident, "profile": "MIDI CLACK JONES", "min": 0, "max": 20, "position": position,
            "windowsButton": 2, "frame": frame()}


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class FakeSerial:
    def __init__(self, clock, capabilities=True):
        self.clock = clock
        self.capabilities = capabilities
        self.writes = []
        self.reads = []
        self.buffer = bytearray()
        self.closed = False
        self.auto_ready = True
        self.profiles = {"MIDI CLACK JONES": {"name": "MIDI CLACK JONES", "desc": "original", "keys": [{"pressed": []}] * 4,
                         "knob": [{"haptic": {"mode": 0, "startPos": 0, "endPos": 8, "detentCount": 8, "outputRamp": 10000}}]}}
    def inject(self, message):
        self.buffer.extend((json.dumps(message) + "\n").encode())
    def write(self, raw):
        message = json.loads(raw)
        self.writes.append(message)
        if message == {"profiles": "#all"}:
            self.inject({"profiles": list(self.profiles), "current": "MIDI CLACK JONES"})
        elif "profile" in message:
            # Fail loudly if code ever guesses a name: real firmware would create it.
            self.inject({"profile": self.profiles[message["profile"]]})
        elif message == {"settings": "?"}:
            self.inject({"settings": {"serialNumber": "test", "firmwareVersion": "1.0.0-cc1", "wifiPassword": "do-not-back-up"}})
        elif message == {"capabilities": "?"} and self.capabilities:
            self.inject({"capabilities": {"controlCenter": 1, "leaseMs": 2000}})
        elif "control" in message and self.auto_ready:
            value = message["control"]
            self.inject({"ready": value["id"], "p": value["position"]})
        elif message == {"release": True}:
            self.inject({"released": True})
        return len(raw)
    @property
    def in_waiting(self):
        return len(self.buffer)
    def read(self, size):
        self.reads.append(size)
        self.clock.now += 0.01
        data = bytes(self.buffer[:size]); del self.buffer[:size]
        return data
    def close(self): self.closed = True


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.serial = FakeSerial(self.clock)
        self.bridge = DeviceBridge(self.temp.name, lambda port: self.serial, request_timeout=0.1, autostart=False, clock=self.clock)
    def tearDown(self): self.temp.cleanup()
    def events(self):
        output = []
        while True:
            try: output.append(self.bridge.events.get_nowait())
            except queue.Empty: return output
    def connect(self): self.bridge._connect("COM-FAKE")

    def test_paced_usb_writes_preserve_bytes_and_bound_bursts(self):
        class Port:
            def __init__(self): self.parts = []
            def write(self, data): self.parts.append(data); return len(data)
        port, sleeps = Port(), []
        paced = PacedSerial(port, sleep=sleeps.append)
        payload = ('{"title":"Beyoncé","padding":"' + 'a' * 900 + '"}\n').encode()
        self.assertEqual(paced.write(payload), len(payload))
        self.assertEqual(b''.join(port.parts), payload)
        self.assertTrue(all(len(part) <= 64 for part in port.parts))
        self.assertEqual(sleeps, [0.005] * (len(port.parts) - 1))

    def test_paced_partial_write_stops_without_sending_tail(self):
        class Port:
            def __init__(self): self.calls = 0
            def write(self, data): self.calls += 1; return 3
        port = Port()
        paced = PacedSerial(port, sleep=lambda _: self.fail('Sleep after short write'))
        self.assertEqual(paced.write(b'a' * 200), 3)
        self.assertEqual(port.calls, 1)

    def test_frame_coalescing_preserves_control_and_disconnect_boundaries(self):
        for item in [('frame', {'id': 1, 'value': 'old'}), ('frame', {'id': 1, 'value': 'latest'}),
                     ('enter', control(2)), ('frame', {'id': 2}), ('disconnect', None)]:
            self.bridge.commands.put(item)
        self.assertEqual(self.bridge._next_command(), ('frame', {'id': 1, 'value': 'latest'}))
        self.assertEqual(self.bridge._next_command(), ('enter', control(2)))
        self.assertEqual(self.bridge._next_command(), ('frame', {'id': 2}))
        self.assertEqual(self.bridge._next_command(), ('disconnect', None))

    def test_media_lists_are_a_no_op_without_artwork2_and_never_join_frame_coalescing(self):
        # ARTWORK2.md section 9: set_media_wanted is a no-op unless artwork2 was negotiated.
        self.connect()
        self.assertIsNone(self.bridge.media_capability)
        self.bridge.set_media_wanted("cover", [("key", b"jpeg")])
        self.assertTrue(self.bridge.commands.empty())
        items = [('frame', {'id': 1, 'value': 'a'}), ('media', ('icon', [], 0)), ('frame', {'id': 1, 'value': 'b'})]
        for item in items: self.bridge.commands.put(item)
        self.assertEqual([self.bridge._next_command() for _ in items], items)

    def test_coalescing_does_not_hide_malformed_or_different_control_frames(self):
        items = [('frame', {'id': 1}), ('frame', None), ('frame', {'id': 2})]
        for item in items: self.bridge.commands.put(item)
        self.assertEqual([self.bridge._next_command() for _ in items], items)

    def test_inventory_is_read_only_and_backup_is_complete_but_filtered(self):
        self.connect()
        self.assertEqual(self.serial.writes, [{"profiles": "#all"}, {"profile": "MIDI CLACK JONES"}, {"settings": "?"}, {"capabilities": "?"}])
        saved = json.loads(self.bridge.backup_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["profiles"], self.serial.profiles)
        self.assertNotIn("wifiPassword", saved["settings"])
        self.assertEqual(self.events()[0]["kind"], "connected")

    def test_missing_capability_connects_but_never_enters_control(self):
        self.serial.capabilities = False
        self.connect()
        before = list(self.serial.writes)
        with self.assertRaisesRegex(RuntimeError, "lacks control-center"):
            self.bridge._enter(control())
        self.assertEqual(self.serial.writes, before)
        self.assertEqual(self.events()[0]["kind"], "connected")

    def test_unknown_profile_does_not_query_or_create(self):
        self.connect(); before = list(self.serial.writes)
        payload = control(); payload["profile"] = "TYPO"
        with self.assertRaisesRegex(ValueError, "inventoried"):
            self.bridge._enter(payload)
        self.assertEqual(self.serial.writes, before)

    def test_backup_must_exist_before_enter(self):
        self.connect(); self.bridge.backup_path.unlink()
        with self.assertRaisesRegex(RuntimeError, "backup"):
            self.bridge._enter(control())

    def test_button_order_is_preserved_and_invalid_permutation_never_writes(self):
        self.connect()
        payload = {**control(), "buttonOrder": [3, 1, 0, 2], "windowsButton": 0}
        self.bridge._enter(payload)
        self.assertEqual(self.serial.writes[-1]["control"]["buttonOrder"], [3, 1, 0, 2])
        previous = len(self.serial.writes)
        with self.assertRaises(ValueError):
            self.bridge._enter({**control(2), "buttonOrder": [0, 1, 1, 3]})
        self.assertEqual(len(self.serial.writes), previous)

    def test_ready_is_not_movement_and_large_deltas_are_not_clipped(self):
        self.connect(); self.events()
        self.bridge._enter(control())
        self.assertEqual([e["kind"] for e in self.events()], ["ready"])
        self.bridge._consume({"id": 1, "p": 19})
        self.assertEqual(self.events()[0]["delta"], 18)
        self.bridge._consume({"id": 1, "p": 2})
        self.assertEqual(self.events()[0]["delta"], -17)

    def test_windows_hid_can_be_disabled_without_disabling_serial_buttons(self):
        self.connect(); self.events()
        self.bridge._enter({**control(), "windowsHidEnabled": False})
        self.assertIs(self.serial.writes[-1]["control"]["windowsHidEnabled"], False)
        self.events()
        self.bridge._consume({"id": 1, "kd": 2, "ks": 4})
        self.assertEqual(self.events()[0]["index"], 2)
        self.bridge._enter(control(2))
        self.assertIs(self.serial.writes[-1]["control"]["windowsHidEnabled"], True)

    def test_windows_hid_rejects_non_booleans_before_writing(self):
        self.connect(); before = len(self.serial.writes)
        for invalid in (None, 0, 1, "false", [], {}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "boolean"):
                self.bridge._enter({**control(), "windowsHidEnabled": invalid})
        self.assertEqual(len(self.serial.writes), before)

    def test_stale_inputs_and_ready_are_ignored_across_mode_change(self):
        self.connect(); self.bridge._enter(control(1)); self.events()
        self.bridge._enter(control(2, 5)); self.events()
        for message in ({"id": 1, "p": 10}, {"id": 1, "kd": 0, "ks": 1}, {"ready": 1, "p": 0}, {"ready": 2, "p": 5}):
            self.bridge._consume(message)
        self.assertEqual(self.events(), [])
        self.bridge._consume({"id": 2, "p": 6})
        self.assertEqual(self.events()[0]["delta"], 1)

    def test_wrong_initial_position_cannot_arm(self):
        self.connect(); self.events()
        self.serial.auto_ready = False
        self.serial.inject({"ready": 1, "p": 17})
        with self.assertRaises(TimeoutError): self.bridge._enter(control())
        self.assertIsNone(self.bridge.ready_id)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.serial.writes[-1], {"release": True})

    def test_button_zero_and_edges_are_deduplicated(self):
        self.connect(); self.bridge._enter(control()); self.events()
        for message in ({"id": 1, "kd": 0, "ks": 1}, {"id": 1, "kd": 0, "ks": 1}, {"id": 1, "ku": 0, "ks": 0}, {"id": 1, "kd": 0, "ks": 1}):
            self.bridge._consume(message)
        self.assertEqual([e["index"] for e in self.events()], [0, 0])

    def test_heartbeat_uses_latest_frame_and_does_not_reenter_control(self):
        self.connect(); self.bridge._enter(control()); self.events()
        latest = {**frame(), "id": 1, "value": "Claude"}
        self.bridge._frame(latest)
        self.clock.now += 0.51
        self.bridge._heartbeat()
        self.assertEqual(self.serial.writes[-1], {"frame": latest})
        self.assertEqual(sum("control" in w for w in self.serial.writes), 1)

    def test_stale_frame_is_rejected_without_write(self):
        self.connect(); self.bridge._enter(control()); before = len(self.serial.writes)
        with self.assertRaises(ValueError): self.bridge._frame({**frame(), "id": 99})
        self.assertEqual(len(self.serial.writes), before)

    def test_release_and_reconnect_cannot_replay_old_input(self):
        self.connect(); self.bridge._enter(control()); self.events()
        self.bridge._consume({"released": True, "reason": "lease-expired"})
        self.bridge._consume({"id": 1, "p": 8})
        self.assertEqual([e["kind"] for e in self.events()], ["released"])
        count = len(self.serial.writes); self.clock.now += 2; self.bridge._heartbeat()
        self.assertEqual(len(self.serial.writes), count)
        self.bridge._disconnect()
        self.assertTrue(self.serial.closed)
        self.assertIsNone(self.bridge.position)

    def test_disconnect_releases_before_closing(self):
        self.connect(); self.bridge._enter(control()); self.events()
        self.bridge._disconnect()
        self.assertEqual(self.serial.writes[-1], {"release": True})
        self.assertTrue(self.serial.closed)
        self.assertEqual([e["kind"] for e in self.events()], ["released", "disconnected"])

    def test_utf8_truncation_does_not_split_codepoints(self):
        payload = frame(); payload["target"] = "家庭" * 40
        normalized = _frame(payload)
        self.assertLessEqual(len(normalized["target"].encode()), 64)
        self.assertNotIn("\ufffd", normalized["target"])

    def test_empty_selection_requires_off_style(self):
        with self.assertRaises(ValueError): _frame(frame(count=0))
        self.assertEqual(_frame(frame(style="off", count=0))["ring"]["style"], "off")

    def test_frame_updates_never_write_profiles(self):
        self.connect(); self.bridge._enter(control()); self.serial.writes.clear()
        for name in ("Chrome", "Claude", "Codex"):
            payload = {**frame(), "id": 1, "target": name}
            self.bridge._frame(payload)
        self.assertTrue(all(list(w) == ["frame"] for w in self.serial.writes))

    def test_daemon_worker_runs_commands_serially_and_disarms_invalid_frame(self):
        self.bridge._thread.start()
        def wait_kind(kind):
            end = time.monotonic() + 2
            while time.monotonic() < end:
                event = self.bridge.events.get(timeout=1)
                if event["kind"] == kind:
                    return event
            self.fail(f"Missing {kind}")
        try:
            self.bridge.submit("connect", "COM-FAKE")
            wait_kind("connected")
            self.bridge.submit("enter", control())
            wait_kind("ready")
            self.bridge.submit("frame", {**frame(), "id": 99})
            wait_kind("error")
            wait_kind("released")
            self.assertIsNone(self.bridge.ready_id)
        finally:
            self.bridge.submit("close")
            wait_kind("closed")
            self.bridge._thread.join(timeout=1)
        self.assertTrue(self.serial.closed)

    def setup_artwork(self, key="coverA"):
        self.connect()
        self.bridge.capabilities["artwork"] = {"version": 1, "width": 120, "height": 120,
                                             "format": "RGB565_LE", "chunkBytes": 384}
        self.bridge._enter({**control(), "frame": {**frame(), "artKey": key}})
        self.events()
        raw = b"\x34\x12" * (120 * 120)
        self.bridge._queue_artwork({"id": 1, "key": key, "data": raw})
        return raw

    def test_artwork_ack_flow_is_bounded_and_inputs_heartbeats_remain_live(self):
        raw = self.setup_artwork()
        received = bytearray()
        self.bridge._artwork_step()
        begin = self.serial.writes[-1]["art"]
        self.assertEqual(begin, {"id": 1, "key": "coverA", "op": "begin", "bytes": len(raw), "crc32": zlib.crc32(raw)})
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "begin", "offset": 0}})
        for offset in range(0, len(raw), 384):
            self.bridge._artwork_step()
            packet = self.serial.writes[-1]["art"]
            self.assertEqual(packet["op"], "data")
            self.assertEqual(packet["offset"], offset)
            part = base64.b64decode(packet["data"])
            self.assertLessEqual(len(part), 384)
            received.extend(part)
            before = len(self.serial.writes)
            self.bridge._artwork_step()
            self.assertEqual(len(self.serial.writes), before, "one outstanding chunk only")
            self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "data", "offset": offset + len(part)}})
            if offset == 384:
                self.bridge._consume({"id": 1, "p": 17})
                self.assertEqual(self.events()[0]["delta"], 16)
                self.clock.now += .51
                self.bridge._heartbeat()
                self.assertIn("frame", self.serial.writes[-1])
        self.bridge._artwork_step()
        self.assertEqual(self.serial.writes[-1]["art"]["op"], "commit")
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "commit", "offset": len(raw)}})
        self.assertEqual(bytes(received), raw)
        self.assertIsNone(self.bridge._artwork)
        self.assertEqual(self.events()[-1]["kind"], "artwork-ready")
        self.assertEqual(self.bridge.ready_id, 1)

    def test_artwork_new_selection_or_mode_discards_old_upload(self):
        self.setup_artwork()
        self.bridge._artwork_step()
        self.bridge._frame({**frame(), "id": 1, "artKey": "coverB"})
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "begin", "offset": 0}})
        before = len(self.serial.writes)
        self.bridge._artwork_step()
        self.assertEqual(len(self.serial.writes), before)
        self.assertIsNone(self.bridge._artwork)
        self.bridge._queue_artwork({"id": 1, "key": "coverA", "data": bytes(28800)})
        self.assertIsNone(self.bridge._artwork)
        self.bridge._queue_artwork({"id": 1, "key": "coverB", "data": bytes(28800)})
        self.bridge._enter(control(2))
        self.assertIsNone(self.bridge._artwork)

    def test_artwork_timeout_and_rejection_do_not_disarm_controls(self):
        self.setup_artwork()
        self.bridge._artwork_step()
        self.clock.now += .11
        self.bridge._artwork_step()
        self.assertEqual(self.events()[-1]["kind"], "artwork-error")
        self.assertEqual(self.bridge.ready_id, 1)
        self.bridge._queue_artwork({"id": 1, "key": "coverA", "data": bytes(28800)})
        self.bridge._artwork_step()
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "begin", "offset": 0, "error": "no-memory"}})
        self.assertEqual(self.events()[-1]["kind"], "artwork-error")
        self.assertEqual(self.bridge.ready_id, 1)

    def test_artwork_missing_capability_keeps_text_controls_usable(self):
        self.setup_artwork()
        self.bridge._artwork = None
        self.bridge.capabilities.pop("artwork")
        self.bridge._queue_artwork({"id": 1, "key": "coverA", "data": bytes(28800)})
        self.assertEqual(self.events()[-1]["kind"], "artwork-error")
        self.assertEqual(self.bridge.ready_id, 1)

    def test_artwork_cache_begin_can_skip_complete_immutable_image(self):
        raw = self.setup_artwork()
        self.bridge._artwork_step()
        self.bridge._consume({"artAck": {"id": 1, "key": "coverA", "op": "begin", "offset": len(raw)}})
        self.bridge._artwork_step()
        self.assertEqual(self.serial.writes[-1]["art"]["op"], "commit")

    def test_artwork_frame_keys_and_layout_are_validated(self):
        # Contract v4 section 7: an invalid optional artKey is stripped, never fatal.
        for invalid in (None, "x" * 65, "foo/bar", "a\nb"):
            with self.subTest(invalid=invalid):
                self.assertNotIn("artKey", _frame({**frame(), "artKey": invalid}))
        for layout in ("nowPlaying", "volume", "idle", "recent", "tracks", "windows"):
            self.assertEqual(_frame({**frame(), "layout": layout})["layout"], layout)



# ---------------------------------------------------------------------------
# Presentation 5 (firmware/PRESENTATION_V5.md, 1.0.0-cc5.4 + desktop v7): capability
# gates, the latched reducedMotion / ledPink / ledVolFull, kh -> hold, hid, ks in ready, the budget.
ALIVE_CAP = {"version": 1, "fps": 60, "drive": 150}
CAPS_P5_ALIVE = {"controlCenter": 1, "leaseMs": 2000, "presentation": 5, "glyphs": "latin-ext-a", "alive": ALIVE_CAP}
CAPS_P5 = {"controlCenter": 1, "leaseMs": 2000, "presentation": 5, "glyphs": "latin-ext-a"}
CAPS_P4_ALIVE = {"controlCenter": 1, "leaseMs": 2000, "presentation": 4, "glyphs": "latin-ext-a", "alive": ALIVE_CAP}
CAPS_P4 = {"controlCenter": 1, "leaseMs": 2000, "presentation": 4, "glyphs": "latin-ext-a"}
LATCHED_V5 = ("reducedMotion", "ledPink", "ledVolFull")


def upnext_frame():
    return {"mode": "RECENTLY ADDED", "target": "Den", "value": "", "detail": "", "status": "", "layout": "upnext",
            "heading": "UP NEXT", "title": "Hunter", "subtitle": "Björk", "meta": "5 / 12",
            "buttons": [{"label": "Back", "enabled": True, "icon": "back"},
                        {"label": "Shuffle", "enabled": True, "icon": "shuffle", "lit": "off"},
                        {"label": "Like", "enabled": True, "icon": "heart", "lit": "on"},
                        {"label": "Play", "enabled": True, "icon": "play"}],
            "ring": {"style": "selection", "value": 0, "index": 4, "count": 12, "now": 3}}


class CapabilitySerial(FakeSerial):
    """FakeSerial answering `capabilities` with `caps`, and `ready` with `ks` when `ready_ks` is set."""

    def __init__(self, clock, caps):
        super().__init__(clock)
        self.caps = caps
        self.ready_ks = None

    def write(self, raw):
        message = json.loads(raw)
        if message == {"capabilities": "?"}:
            self.writes.append(message)
            self.inject({"capabilities": self.caps})
            return len(raw)
        if "control" in message and self.auto_ready and self.ready_ks is not None:
            self.writes.append(message)
            value = message["control"]
            self.inject({"ready": value["id"], "p": value["position"], "ks": self.ready_ks})
            return len(raw)
        return super().write(raw)


class PresentationV5BridgeTests(unittest.TestCase):
    def bridge_for(self, caps):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.serial = CapabilitySerial(self.clock, caps)
        self.bridge = DeviceBridge(self.temp.name, lambda port: self.serial, request_timeout=0.1, autostart=False,
                                   clock=self.clock, local_minute=lambda: 600)
        self.bridge._connect("COM-FAKE")
        self.events()
        return self.bridge

    def events(self):
        output = []
        while True:
            try: output.append(self.bridge.events.get_nowait())
            except queue.Empty: return output

    def enter(self, ident=1, order=None, frame_value=None):
        payload = {"id": ident, "profile": "MIDI CLACK JONES", "min": 0, "max": 20, "position": 1,
                   "windowsButton": 3, "windowsHidEnabled": False, "frame": frame_value or upnext_frame()}
        if order is not None:
            payload["buttonOrder"] = order
        self.bridge._enter(payload)
        return self.serial.writes[-1]["control"]["frame"]

    def frame_line(self, **fields):
        self.bridge._frame({**upnext_frame(), "id": self.bridge.ready_id, **fields})
        return self.serial.writes[-1]["frame"]

    # Section 1: negotiation.
    def test_presentation_levels_and_the_v4_gates(self):
        from control_center.device import alive_capability, artwork2_capability, presentation_level, _device_text
        from control_center import presentation as P
        self.assertEqual((P.PRESENTATION_V4, P.PRESENTATION_V5, P.PRESENTATION_VERSION), (4, 5, 5))
        art2 = {"artwork2": deepcopy(P.ARTWORK2_CAPABILITY)}
        for caps in (CAPS_P4_ALIVE, CAPS_P5_ALIVE):
            with self.subTest(presentation=caps["presentation"]):
                # A cc5.3 knob (presentation 4) keeps artwork2, alive, the Latin glyphs and the v4 fields.
                self.assertIsNotNone(artwork2_capability({**caps, **art2}))
                self.assertIsNotNone(alive_capability(caps))
                self.assertEqual(_device_text("Björk · “Jóga”", caps, 96), "Björk · “Jóga”")
                self.assertEqual(_frame({**frame(), "heading": "WINDOWS", "meta": "2 / 3"}, caps)["heading"], "WINDOWS")
        self.assertEqual(presentation_level({"presentation": True}), 0)
        self.assertIsNone(artwork2_capability({"presentation": 3, **art2}))
        self.assertEqual(_device_text("Björk", {"presentation": 3, "glyphs": "latin-ext-a"}, 96), "Bjork")

    def test_presentation_5_frames_keep_v5_fields_and_older_knobs_get_the_downgrade(self):
        v5 = _frame(upnext_frame(), CAPS_P5)
        self.assertEqual((v5["layout"], v5["ring"]["now"], v5["buttons"][2]["lit"]), ("upnext", 3, "on"))
        v4 = _frame(upnext_frame(), CAPS_P4)
        self.assertEqual((v4["layout"], v4["page"], [b["icon"] for b in v4["buttons"]], "now" in v4["ring"]),
                         ("recent", 1, ["back", "switch", "more", "play"], False))

    def test_presentation_4_keeps_a_v5_first_0_where_v4_derives_1(self):
        """Section 4.2 (WP3-REV-1): the v5 window at index 10 of 41 starts at 0, V4's derivation for an
        absent first gives 1; cc5.3 must get the explicit 0, or its colours and mask would be dropped."""
        from control_center.device import v5_parse
        up = upnext_frame()
        up["ledStyle"] = "color"
        up["ring"] = {"style": "selection", "value": 0, "index": 10, "count": 41, "first": 0, "now": 9,
                      "colors": list(range(1, 21))}
        recent = {**deepcopy(up), "layout": "recent"}
        recent["ring"] = {**{k: v for k, v in up["ring"].items() if k != "now"}, "unavailable": 1 << 10}
        for caps in (CAPS_P4, CAPS_P4_ALIVE):
            for source in (up, recent):
                with self.subTest(presentation=caps["presentation"], alive="alive" in caps, layout=source["layout"]):
                    ring = _frame(deepcopy(source), caps)["ring"]
                    self.assertEqual((ring["first"], ring["colors"]), (0, list(range(1, 21))))
                    stored, invalid = v5_parse({**_frame(deepcopy(source), caps)})
                    self.assertEqual((invalid, stored["ringFirst"]), ([], 0))
                    self.assertEqual(ring.get("unavailable", 0), source["ring"].get("unavailable", 0))
        # Where V4 derives 0 as well (index 9), presentation 4 still slims it: byte-identical to desktop v6.
        v6 = deepcopy(recent)
        v6["ring"].update(index=9)
        self.assertNotIn("first", _frame(deepcopy(v6), CAPS_P4)["ring"])
        self.assertEqual(_frame(deepcopy(v6), CAPS_P5)["ring"]["first"], 0)   # P5-R9: always sent when count > 20

    # Section 7.1 / 14.2: reducedMotion.
    def test_reduced_motion_rides_every_control_frame_and_the_next_frame_after_a_change(self):
        self.bridge_for(CAPS_P5)
        self.assertIs(self.enter()["reducedMotion"], False)
        self.assertNotIn("reducedMotion", self.frame_line())
        self.bridge.set_reduced_motion(True)
        self.assertIs(self.frame_line()["reducedMotion"], True)
        self.assertNotIn("reducedMotion", self.frame_line())
        self.clock.now += 0.51
        self.bridge._heartbeat()
        self.assertNotIn("reducedMotion", self.serial.writes[-1]["frame"])
        self.assertIs(self.enter(2)["reducedMotion"], True)   # every control (the knob resets it at a claim)
        self.bridge.set_reduced_motion("yes")                  # ignored (logged), never sent
        self.assertNotIn("reducedMotion", self.frame_line())
        self.assertNotIn("reducedMotion", self.bridge.latest_frame)

    def test_a_submitted_reduced_motion_is_the_setting_not_content(self):
        self.bridge_for(CAPS_P5)
        self.enter()
        self.assertIs(self.frame_line(reducedMotion=True)["reducedMotion"], True)
        self.assertNotIn("reducedMotion", self.bridge.latest_frame)
        self.assertNotIn("reducedMotion", self.frame_line(reducedMotion=True))   # unchanged: not repeated
        self.assertIs(self.frame_line(reducedMotion=False)["reducedMotion"], False)

    # Section 7.3: ledPink / ledVolFull.
    def test_led_tuning_fields_go_in_every_control_frame_of_an_alive_presentation_5_knob(self):
        self.bridge_for(CAPS_P5_ALIVE)
        self.bridge.set_led_tuning(200, None, pink="#FF051A", vol_full=True)
        control = self.enter()
        self.assertEqual((control["ledDrive"], control["ledPink"], control["ledVolFull"], control["clock"]),
                         (200, 0xFF051A, True, 600))
        line = self.frame_line()
        self.assertFalse({"ledDrive", "ledPink", "ledVolFull"} & set(line))
        self.bridge.set_led_tuning(200, None, pink=0, vol_full=True)   # 0 = the built-in PINK
        # 14.2 (WP3-REV-4): control frames only, never the plain frame line after a change; ledDrive keeps
        # ALIVE 10.2's once-after-a-change.
        line = self.frame_line()
        self.assertFalse({"ledPink", "ledVolFull"} & set(line))
        self.assertEqual(line["ledDrive"], 200)
        self.assertFalse({"ledDrive", "ledPink", "ledVolFull"} & set(self.frame_line()))
        control = self.enter(2)
        self.assertEqual((control["ledPink"], control["ledVolFull"]), (0, True))
        self.bridge.set_led_tuning(200, None, pink=None, vol_full=None)
        self.assertFalse({"ledPink", "ledVolFull"} & set(self.enter(3)))

    def test_led_tuning_and_reduced_motion_are_gated(self):
        for caps, sent in ((CAPS_P5, {"reducedMotion"}), (CAPS_P4_ALIVE, {"ledDrive"}), (CAPS_P4, set())):
            with self.subTest(presentation=caps["presentation"], alive="alive" in caps):
                self.bridge_for(caps)
                self.bridge.set_led_tuning(200, None, pink=5, vol_full=True)
                self.bridge.set_reduced_motion(True)
                control = self.enter()
                self.assertEqual({"reducedMotion", "ledDrive", "ledPink", "ledVolFull"} & set(control), sent)

    def test_led_pink_setting_values(self):
        from control_center.device import led_pink_value
        for raw, value in ((0, 0), (1, 1), (0xFFFFFF, 0xFFFFFF), ("#FF051A", 0xFF051A), ("#ff285a", 0xFF285A)):
            self.assertEqual(led_pink_value(raw), value)
        for raw in (-1, 0x1000000, True, 1.5, "FF051A", "#FFF", "#FF051AA", "#GG0000", None, [255]):
            self.assertIsNone(led_pink_value(raw), raw)

    def test_submitted_tuning_fields_are_ignored(self):
        self.bridge_for(CAPS_P5_ALIVE)
        control = self.enter(frame_value={**upnext_frame(), "ledPink": 7, "ledVolFull": True})
        self.assertFalse({"ledPink", "ledVolFull"} & set(control))

    # Section 11: ks in ready, hid, kh.
    def test_ready_ks_reseeds_the_pressed_mask_and_reports_logical_held(self):
        self.bridge_for(CAPS_P5)
        self.serial.ready_ks = 0b1000                       # raw 3 held at ready
        self.enter(order=[3, 1, 0, 2])
        ready = self.events()
        self.assertEqual(ready, [{"kind": "ready", "id": 1, "p": 1, "position": 1, "held": 0b0001}])
        self.bridge._consume({"id": 1, "ks": 8, "kd": 3})    # already down at ready: no second press
        self.assertEqual(self.events(), [])
        self.bridge._consume({"id": 1, "ks": 0, "ku": 3})
        self.bridge._consume({"id": 1, "ks": 8, "kd": 3})
        self.assertEqual(self.events(), [{"kind": "button", "id": 1, "index": 3, "button": 3, "pressed": True,
                                          "hid": False}])
        for invalid in (16, -1, True, None):
            self.serial.ready_ks = invalid
            self.enter(ident=2 + [16, -1, True, None].index(invalid))
            self.assertEqual(self.events()[0]["held"], 0)

    def test_hid_marks_the_press_that_also_sent_f24(self):
        self.bridge_for(CAPS_P5)
        self.enter(order=[0, 1, 2, 3])
        self.events()
        self.bridge._consume({"id": 1, "ks": 8, "kd": 3, "hid": 1})
        self.bridge._consume({"id": 1, "ks": 0, "ku": 3})
        self.bridge._consume({"id": 1, "ks": 4, "kd": 2})
        self.bridge._consume({"id": 1, "ks": 5, "kd": 0, "hid": True})   # not the JSON integer 1
        self.assertEqual([(e["button"], e["hid"]) for e in self.events()], [(3, True), (2, False), (0, False)])

    def test_kh_is_a_hold_of_the_logical_button(self):
        self.bridge_for(CAPS_P5)
        self.enter(order=[3, 1, 0, 2])
        self.events()
        self.bridge._consume({"id": 1, "ks": 8, "kd": 3})
        self.bridge._consume({"id": 1, "ks": 8, "kh": 3})
        self.assertEqual(self.events(), [
            {"kind": "button", "id": 1, "index": 3, "button": 3, "pressed": True, "hid": False},
            {"kind": "hold", "id": 1, "button": 0, "raw": 3}])
        for ignored in ({"id": 2, "ks": 8, "kh": 3}, {"id": 1, "ks": 8, "kh": 4}, {"id": 1, "ks": 8, "kh": True},
                        {"id": 1, "ks": 8, "kh": -1}, {"ready": 1, "p": 1, "kh": 3}):
            self.bridge._consume(ignored)
        self.assertEqual(self.events(), [])

    def test_a_deferred_kh_right_after_ready_needs_no_kd(self):
        # K1 11.2 step 5: a long press that matured while entering arrives just after `ready`.
        self.bridge_for(CAPS_P5)
        self.serial.ready_ks = 0b0001
        self.enter()
        self.assertEqual(self.events()[0]["held"], 1)
        self.bridge._consume({"id": 1, "ks": 1, "kh": 0})
        self.assertEqual(self.events(), [{"kind": "hold", "id": 1, "button": 0, "raw": 0}])
        self.bridge._enter({"id": 2, "profile": "MIDI CLACK JONES", "min": 0, "max": 20, "position": 1,
                            "windowsButton": 3, "frame": upnext_frame()})
        self.events()
        self.bridge._consume({"id": 1, "ks": 1, "kh": 0})     # the old control's id: never replayed
        self.assertEqual(self.events(), [])

    def test_lim_still_emits_limit_on_presentation_5(self):
        self.bridge_for(CAPS_P5_ALIVE)
        self.enter()
        self.events()
        self.bridge._consume({"id": 1, "lim": 1})
        self.bridge._consume({"id": 1, "lim": 2})
        self.assertEqual(self.events(), [{"kind": "limit", "id": 1, "dir": 1}])

    # Section 14.1: budget.
    def test_frame_budget_per_presentation(self):
        from control_center.device import frame_budget
        limit, reserve = frame_budget(CAPS_P5_ALIVE)
        self.assertEqual(limit, 1400)
        self.assertEqual(set(reserve), {"clock", "progress", "ledDrive", "ledDither", "reducedMotion", "ledPink",
                                        "ledVolFull"})
        self.assertEqual(frame_budget(CAPS_P5), (1400, {"reducedMotion": False}))
        self.assertEqual(frame_budget(CAPS_P4)[0], 1100)
        self.assertIsNone(frame_budget(CAPS_P4)[1])
        big = {**upnext_frame(), "detail": "d" * 96, "target": "t" * 64, "title": "T" * 96, "subtitle": "S" * 96,
               "meta": "M" * 96, "ring": {**upnext_frame()["ring"], "colors": [0xFFFFFF] * 12}, "ledStyle": "color"}
        big["buttons"] = [{**b, "label": "L" * 16} for b in big["buttons"]]
        on5 = _frame(big, CAPS_P5_ALIVE)
        self.assertEqual((on5["detail"], on5["target"]), ("d" * 96, "t" * 64))   # fits 1,400 B untouched
        on4 = _frame(big, CAPS_P4_ALIVE)
        self.assertEqual(on4["detail"], "")                                        # V4's 1,100 B trims it


if __name__ == "__main__": unittest.main()

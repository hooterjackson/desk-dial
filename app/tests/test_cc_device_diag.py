"""DeviceBridge.request_diag(): the read-only `{"diag":"?"}` request and the typed read of its reply.

PRESENTATION_V5.md 12.3 (VOC-K1c; the `diag` capability stays 1) and 12.6 (binary A / B / C),
ALIVE.md 10.1 (the LED fields, VOC section 6.1), CONTROL_CENTER_V5.md 6.5 (the runtime logs
enterMsLast / enterMsMax once a minute; WP5-R11). The request never renews the lease: only
controls and frames do (CC; P4 section 0). A fake knob answers on an in-memory port: no port,
network or window is touched.
"""
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import device, presentation  # noqa: E402
from control_center.device import DeviceBridge  # noqa: E402

CAPS_CC54 = {"controlCenter": 1, "leaseMs": 2000, "presentation": 5, "glyphs": "latin-ext-a", "diag": 1,
             "alive": {"version": 1, "fps": 60, "drive": 150}}
CAPS_CC4 = {"controlCenter": 1, "leaseMs": 2000, "presentation": 2}   # no diag capability


def cc54_diag(**overrides):
    """A cc5.4 `{"diag":…}` object as control_center.cpp builds it (binary A), private-free."""
    diag = {"lvglFree": 38000, "lvglMinFree": 31000, "heapMinFree": 79000, "stackLcd": 6700, "stackCom": 3100,
            "stackHmi": 2900, "stackFoc": 1800, "stackUsbd": 2200, "heapFree": 90000, "psramFree": 7000000,
            "txStalls": 0, "txDroppedBytes": 0, "resetReason": "poweron", "resetCode": 1, "bootCount": 7,
            "rtcReset": [1, 1], "previous": {"lcd": {"step": "wait"}}, "hmiAgeMs": 3, "lcdAgeMs": 5,
            "comAgeMs": 0, "hmiStep": "wait", "lcdStep": "wait", "comOp": "diag", "comStage": "line",
            "wdtTasks": ["hmi", "lcd", "com"], "ledFps": 60, "ledRenderUsMax": 1450, "ledRenderUsAvg": 610,
            "ledMode": "alive", "ledShowGapMsMax": 17, "ledLateShows": 0, "sessionPhase": "ready",
            "releasePendingMs": 0, "forcedReleases": 0, "lastForced": [], "led": {"ring": {"frames": 10}},
            "ledTxTimeouts": 0, "ledWriteErrors": 0, "rxQueueBytes": 8192, "mediaCommits": 4,
            "mediaErrors": 0, "mediaEvictions": 0, "jpegDecodes": 4, "jpegDecodeErrors": 0,
            "jpegDecodeMsMax": 151, "jpegDecodeMsLast": 88,
            "enterMsLast": 84, "enterMsMax": 131, "holdEvents": 3, "holdDeferred": 1,
            "lcdFps": 60, "lcdFpsAnimMin": 57, "lcdRefrUsMax": 9800, "lcdRefrUsAvg": 4100, "lcdRenderUsMax": 2100,
            "lcdFlushUs": 310000, "lcdPxPerRefr": 15600, "lcdFullRefrs": 12, "lcdLateRefrs": 0, "lcdMaxGapMs": 21,
            "lcdBusyPct": 38, "core0IdlePct": 51, "lcdSpiHz": 80000000, "lcdDma": True, "lcdPeriodMs": 16,
            "artAsync": True, "artDecodeRequests": 9, "artDecodeAborts": 2, "artDecodeStale": 1, "stackArtDec": 2500}
    diag.update(overrides)
    return diag


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class DiagKnob:
    """In-memory knob: inventory, capabilities, control/ready, release, and (optionally) diag replies."""

    def __init__(self, clock, caps, answer_diag=True):
        self.clock, self.caps, self.answer_diag = clock, caps, answer_diag
        self.writes, self.raw = [], []
        self.buffer = bytearray()
        self.diag = cc54_diag()

    def inject(self, message):
        self.buffer.extend((json.dumps(message) + "\n").encode())

    def write(self, raw):
        self.raw.append(bytes(raw))
        message = json.loads(raw)
        self.writes.append(message)
        if message == {"profiles": "#all"}:
            self.inject({"profiles": ["MIDI CLACK JONES"], "current": "MIDI CLACK JONES"})
        elif "profile" in message:
            self.inject({"profile": {"name": "MIDI CLACK JONES", "keys": [], "knob": []}})
        elif message == {"settings": "?"}:
            self.inject({"settings": {"serialNumber": "diag-test", "firmwareVersion": "1.0.0-cc5.4"}})
        elif message == {"capabilities": "?"}:
            self.inject({"capabilities": self.caps})
        elif "control" in message:
            self.inject({"ready": message["control"]["id"], "p": message["control"]["position"], "ks": 0})
        elif message == {"release": True}:
            self.inject({"released": True})
        elif message == {"diag": "?"} and self.answer_diag:
            self.inject({"diag": self.diag})
        return len(raw)

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, size):
        self.clock.now += 0.001
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def close(self):
        pass

    def diag_lines(self):
        return [w for w in self.writes if w == {"diag": "?"}]


def home_frame():
    return {"mode": "HOME", "target": "Hall", "value": "28%", "detail": "", "status": "", "layout": "nowPlaying",
            "title": "Pressure Front", "subtitle": "Mira Vale",
            "buttons": [{"label": "Pause", "enabled": True, "icon": "pause"},
                        {"label": "Browse", "enabled": True, "icon": "list"},
                        {"label": "Tracks", "enabled": True, "icon": "tracks"},
                        {"label": "Win", "enabled": True, "icon": "win"}],
            "ring": {"style": "level", "value": 28, "index": 0, "count": 101}}


class BridgeCase(unittest.TestCase):
    caps = CAPS_CC54
    answer_diag = True

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.clock = Clock()
        self.knob = DiagKnob(self.clock, self.caps, self.answer_diag)
        self.bridge = DeviceBridge(temp.name, lambda port: self.knob, request_timeout=0.2, autostart=False,
                                   clock=self.clock, local_minute=lambda: 600)

    def connect(self):
        self.bridge._connect("COM-FAKE")
        self.events()

    def enter(self, ident=1):
        self.bridge._enter({"id": ident, "profile": "MIDI CLACK JONES", "min": 0, "max": 100, "position": 28,
                            "windowsButton": 3, "windowsHidEnabled": True, "frame": home_frame()})
        self.events()

    def events(self, kind=None):
        output = []
        while True:
            try:
                event = self.bridge.events.get_nowait()
            except queue.Empty:
                return [e for e in output if kind is None or e["kind"] == kind]
            output.append(event)

    def service(self, passes=3):
        for _ in range(passes):
            self.bridge._service()


class RequestTests(BridgeCase):
    def test_one_read_only_line_on_the_next_pass_and_the_reply_is_an_event(self):
        self.connect()
        self.enter()
        before = len(self.knob.writes)
        self.assertTrue(self.bridge.request_diag())
        self.assertEqual(self.knob.writes[before:], [], "the caller's thread never writes")
        self.service()
        self.assertEqual(self.knob.writes[before:], [{"diag": "?"}])
        self.assertEqual(self.knob.raw[before], b'{"diag":"?"}\n', "the exact firmware command (VOC 6.1)")
        (event,) = self.events("diag")
        self.assertEqual((event["diag"]["enterMsLast"], event["diag"]["enterMsMax"]), (84, 131))
        self.assertEqual(event["binary"], "A")
        self.assertEqual(event["invalid"], [])

    def test_calls_before_the_pass_coalesce_into_one_line(self):
        self.connect()
        for _ in range(5):
            self.bridge.request_diag()
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 1)
        self.assertEqual(len(self.events("diag")), 1)

    def test_diag_works_without_a_claim_and_needs_no_ready_control(self):
        """12.3: diag is answered in every session phase; the bridge asks whenever a knob is connected."""
        self.connect()
        self.bridge.request_diag()
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 1)
        self.assertEqual(len(self.events("diag")), 1)

    def test_thread_safe_request_from_another_thread(self):
        self.connect()
        worker = threading.Thread(target=self.bridge.request_diag)
        worker.start()
        worker.join()
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 1)

    def test_a_request_while_one_is_unanswered_waits_for_the_reply(self):
        self.connect()
        self.knob.answer_diag = False
        self.bridge.request_diag()
        self.service()
        self.bridge.request_diag()
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 1, "one outstanding request at a time")
        self.clock.now += self.bridge.request_timeout + 0.01   # the first one is given up (no event, no error)
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 2, "the waiting request goes out after the timeout")
        self.assertEqual(self.events("error"), [])
        self.knob.answer_diag = True
        self.bridge.request_diag()
        self.knob.inject({"diag": cc54_diag()})    # the late answer to line 2 retires it
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 3, "a reply frees the slot at once")

    def test_a_request_racing_the_write_is_never_lost(self):
        """The runtime may ask again while the bridge thread is writing the previous line."""
        self.connect()
        original, raced = self.knob.write, []

        def write(raw):
            if bytes(raw) == b'{"diag":"?"}\n' and not raced:
                raced.append(True)
                self.bridge.request_diag()          # another thread, mid-write
            return original(raw)
        self.knob.write = write
        self.bridge.request_diag()
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 2)
        self.assertEqual(len(self.events("diag")), 2)

    def test_disconnected_or_closed_requests_are_dropped(self):
        self.bridge.request_diag()           # never connected: nothing to ask
        self.service()
        self.connect()
        self.service()
        self.assertEqual(self.knob.diag_lines(), [], "a request made while disconnected is not replayed")
        self.bridge.closed = True
        self.assertFalse(self.bridge.request_diag())

    def test_reconnect_forgets_a_request_and_an_outstanding_line(self):
        self.connect()
        self.knob.answer_diag = False
        self.bridge.request_diag()
        self.service()
        self.bridge.request_diag()
        self.bridge._disconnect()
        self.events()
        self.knob.answer_diag = True
        self.connect()
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 1, "the pending request died with the connection")
        self.bridge.request_diag()
        self.service()
        self.assertEqual(len(self.knob.diag_lines()), 2, "no outstanding line carried over")

    def test_the_bridge_thread_serves_a_request_from_another_thread(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        bridge = DeviceBridge(temp.name, lambda port: self.knob, request_timeout=0.2, clock=self.clock)
        self.addCleanup(lambda: bridge.closed or bridge.submit("close"))
        bridge.submit("connect", "COM-FAKE")

        def wait_for(kind):
            while True:
                event = bridge.events.get(timeout=5)
                self.assertNotEqual(event["kind"], "error", event.get("message"))
                if event["kind"] == kind:
                    return event
        wait_for("connected")
        self.assertTrue(bridge.request_diag())
        self.assertEqual(wait_for("diag")["diag"]["holdEvents"], 3)
        bridge.submit("close")
        bridge._thread.join(5)
        self.assertEqual(len(self.knob.diag_lines()), 1)
        self.assertFalse(bridge.request_diag(), "closed: nothing will be asked")


class LeaseTests(BridgeCase):
    def test_diag_never_renews_the_lease(self):
        """The heartbeat (a frame line) keeps its schedule however many diag lines go out."""
        self.connect()
        self.enter()
        start = self.bridge.last_heartbeat
        frames = lambda: [w for w in self.knob.writes if "frame" in w]   # noqa: E731
        sent = len(frames())
        for step in range(4):                     # 0.1 s apart, all inside one heartbeat period
            self.clock.now = start + 0.1 * (step + 1)
            self.bridge.request_diag()
            self.service(1)
        self.assertEqual(self.bridge.last_heartbeat, start, "a diag line is not a heartbeat")
        self.assertEqual(len(frames()), sent)
        self.assertGreaterEqual(len(self.knob.diag_lines()), 1)
        self.clock.now = start + self.bridge.HEARTBEAT_SECONDS
        self.service(1)
        self.assertEqual(len(frames()), sent + 1, "the heartbeat frame is still due at 0.5 s")

    def test_diag_counts_against_the_artwork2_receive_budget_and_waits_for_room(self):
        caps = {**CAPS_CC54, "artwork2": dict(presentation.ARTWORK2_CAPABILITY)}
        self.knob.caps = caps
        self.connect()
        self.assertIsNotNone(self.bridge.media_capability)
        room = self.bridge.media_capability["rxBytes"] - self.bridge.TX_RESERVE_BYTES
        self.bridge._tx_log.append((self.clock(), room, None))     # the knob's queue is full
        self.bridge.request_diag()
        self.bridge._diag_step()
        self.assertEqual(self.knob.diag_lines(), [], "waits like a frame line")
        self.clock.now += self.bridge.TX_READ_SECONDS + 0.001
        self.bridge._diag_step()
        self.assertEqual(len(self.knob.diag_lines()), 1)
        self.assertEqual(self.knob.raw[-1], b'{"diag":"?"}\n', "one whole line (ARTWORK2 section 3)")
        self.assertEqual(self.bridge._tx_log[-1][1:], (len(b'{"diag":"?"}\n'), None))

    def test_a_reply_read_while_entering_is_still_delivered(self):
        self.connect()
        self.bridge.request_diag()
        self.bridge._diag_step()                     # the line is out; its reply is read inside _enter
        self.bridge._enter({"id": 1, "profile": "MIDI CLACK JONES", "min": 0, "max": 100, "position": 28,
                            "windowsButton": 3, "windowsHidEnabled": True, "frame": home_frame()})
        self.assertEqual(self.bridge.ready_id, 1)
        kinds = [e["kind"] for e in self.events()]
        self.assertIn("diag", kinds)
        self.assertIn("ready", kinds)
        self.assertIsNone(self.bridge._diag_sent_at, "the reply retired the line")


class NoDiagCapabilityTests(BridgeCase):
    caps = CAPS_CC4

    def test_a_knob_without_diag_is_never_asked(self):
        self.connect()
        self.bridge.request_diag()
        self.service()
        self.assertEqual(self.knob.diag_lines(), [])
        self.bridge.capabilities = dict(CAPS_CC4, diag=True)      # 1 only, never a bool
        self.bridge.request_diag()
        self.service()
        self.assertEqual(self.knob.diag_lines(), [])


class ParseTests(unittest.TestCase):
    def test_every_12_3_and_10_1_field_is_read_with_its_type(self):
        fields, invalid = device.diag_parse(cc54_diag())
        self.assertEqual(invalid, [])
        for name in device.DIAG_LCD_FIELDS + device.DIAG_LED_FIELDS + device.DIAG_MEMORY_FIELDS:
            self.assertIn(name, fields, name)
        self.assertEqual(set(device.DIAG_LCD_FIELDS),
                         {"lcdFps", "lcdFpsAnimMin", "lcdRefrUsMax", "lcdRefrUsAvg", "lcdRenderUsMax", "lcdFlushUs",
                          "lcdPxPerRefr", "lcdFullRefrs", "lcdLateRefrs", "lcdMaxGapMs", "lcdBusyPct",
                          "core0IdlePct", "lcdSpiHz", "enterMsLast", "enterMsMax", "holdEvents", "holdDeferred",
                          "lcdDma", "lcdPeriodMs", "artAsync", "artDecodeRequests", "artDecodeAborts",
                          "artDecodeStale", "stackArtDec"}, "K1 12.3, all 24 (VOC 6.1)")
        self.assertEqual(device.DIAG_LED_FIELDS, ("ledFps", "ledRenderUsMax", "ledRenderUsAvg", "ledMode",
                                                  "ledShowGapMsMax", "ledLateShows"))
        self.assertIs(fields["lcdDma"], True)
        self.assertEqual((fields["ledMode"], fields["holdEvents"], fields["holdDeferred"]), ("alive", 3, 1))

    def test_only_known_fields_pass_nothing_private_or_nested(self):
        fields, _ = device.diag_parse(cc54_diag(title="secret", settings={"wifiPassword": "x"}))
        known = set(device.DIAG_LCD_FIELDS + device.DIAG_LED_FIELDS + device.DIAG_MEMORY_FIELDS)
        self.assertLessEqual(set(fields), known)
        for name in ("resetReason", "previous", "led", "lastForced", "wdtTasks", "title", "settings", "sessionPhase"):
            self.assertNotIn(name, fields)

    def test_malformed_values_are_dropped_and_named_never_raised(self):
        bad = cc54_diag(enterMsLast=-1, enterMsMax=True, lcdFps=1.5, lcdDma=1, artAsync="yes", ledMode="?",
                        lcdBusyPct=101, holdEvents=1 << 32, stackArtDec=None)
        fields, invalid = device.diag_parse(bad)
        for name in ("enterMsLast", "enterMsMax", "lcdFps", "lcdDma", "artAsync", "ledMode", "lcdBusyPct",
                     "holdEvents", "stackArtDec"):
            self.assertNotIn(name, fields, name)
            self.assertIn(name, invalid, name)
        self.assertEqual(invalid, sorted(invalid, key=list(device.DIAG_FIELDS).index), "contract order")
        self.assertEqual(fields["lcdFpsAnimMin"], 57)
        self.assertEqual(device.diag_parse("?"), ({}, []))
        self.assertEqual(device.diag_parse(None), ({}, []))

    def test_a_cc53_reply_has_no_v5_fields_and_no_binary(self):
        older = {k: v for k, v in cc54_diag().items() if k not in device.DIAG_LCD_FIELDS + device.DIAG_LED_FIELDS}
        fields, invalid = device.diag_parse(older)
        self.assertEqual(invalid, [])
        self.assertEqual(set(fields), set(device.DIAG_MEMORY_FIELDS))
        self.assertIsNone(device.diag_binary(fields))

    def test_binary_a_b_c(self):
        """12.6 / P5-R12: A may run at the measured scan period; B and C at 33 ms."""
        cases = [({"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True}, "A"),
                 ({"lcdDma": True, "lcdPeriodMs": 20, "artAsync": True}, "A"),
                 ({"lcdDma": True, "lcdPeriodMs": 33, "artAsync": False}, "B"),
                 ({"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False}, "C"),
                 ({"lcdDma": False, "lcdPeriodMs": 16, "artAsync": True}, None),
                 ({"lcdDma": True, "artAsync": True}, None), ({}, None)]
        for flags, expected in cases:
            with self.subTest(flags=flags):
                self.assertEqual(device.diag_binary(flags), expected)
                if len(flags) == 3:                    # the same through a full reply
                    self.assertEqual(device.diag_binary(device.diag_parse(cc54_diag(**flags))[0]), expected)
        self.assertIsNone(device.diag_binary({"lcdDma": 1, "lcdPeriodMs": 33, "artAsync": 0}), "1 is not True")
        self.assertIsNone(device.diag_binary(None))

    def test_the_tooling_agrees_on_the_binary(self):
        """work/nanod_cc5_tooling.lcd_binary is the hardware window's reading of the same flags."""
        tooling = Path(__file__).resolve().parents[2] / "tools" / "nanod_cc5_tooling.py"
        if not tooling.is_file():
            self.skipTest("work tree not present")
        import importlib.util
        spec = importlib.util.spec_from_file_location("nanod_cc5_tooling_for_diag", tooling)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(set(module.LCD_DIAG_FIELDS), set(device.DIAG_LCD_FIELDS))
        self.assertEqual(module.ALIVE_DIAG_FIELDS, device.DIAG_LED_FIELDS)
        for period in (16, 20, 33):
            for dma in (True, False):
                for asynchronous in (True, False):
                    flags = {"lcdDma": dma, "lcdPeriodMs": period, "artAsync": asynchronous}
                    self.assertEqual(device.diag_binary(flags), module.lcd_binary(flags), flags)

    def test_malformed_reply_objects_never_emit_or_raise(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        clock = Clock()
        knob = DiagKnob(clock, CAPS_CC54)
        bridge = DeviceBridge(temp.name, lambda port: knob, request_timeout=0.2, autostart=False, clock=clock)
        bridge._connect("COM-FAKE")
        for reply in ({"diag": "?"}, {"diag": [1, 2]}, {"diag": None}):
            knob.inject(reply)
        knob.inject({"diag": {"enterMsLast": "84; drop table", "lcdFps": 60}})
        for _ in range(3):
            bridge._service()
        events = []
        while not bridge.events.empty():
            events.append(bridge.events.get_nowait())
        diag = [e for e in events if e["kind"] == "diag"]
        self.assertEqual(len(diag), 1)
        self.assertEqual((diag[0]["diag"], diag[0]["invalid"]), ({"lcdFps": 60}, ["enterMsLast"]))
        self.assertNotIn("error", [e["kind"] for e in events])


class RuntimeSeamTests(unittest.TestCase):
    """End to end on one fake clock: Runtime._poll_diag (once a minute, K3 6.5) -> the real
    DeviceBridge -> the knob -> the `diag` event -> Runtime._diag_event's debug line (WP5-R11)."""

    def test_the_runtime_asks_the_real_bridge_and_logs_the_enter_timings(self):
        from unittest.mock import patch
        from cc5_support import Clock as FakeClock, Harness
        clock = FakeClock(1000.0)
        timer = patch("control_center.runtime.time.monotonic", clock)
        timer.start()
        self.addCleanup(timer.stop)
        h = Harness(self)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        knob = DiagKnob(clock, CAPS_CC54)
        bridge = DeviceBridge(temp.name, lambda port: knob, request_timeout=0.2, autostart=False, clock=clock)
        h.runtime.device = bridge
        bridge._connect("COM-FAKE")                  # emits `connected`
        h.runtime.poll()                             # the runtime's first diag is due a minute later
        bridge._service()
        self.assertEqual(knob.diag_lines(), [])
        clock.advance(61.0)
        h.runtime.poll()                             # _poll_diag -> request_diag (the runtime's thread)
        self.assertEqual(knob.diag_lines(), [], "only the bridge thread writes")
        bridge._service()
        bridge._service()
        self.assertEqual(len(knob.diag_lines()), 1)
        with self.assertLogs("control_center.runtime", level="DEBUG") as logs:
            h.runtime.poll()
        self.assertEqual(h.runtime.last_diag[:2], (84, 131))
        self.assertTrue(any("enterMsLast 84 ms, enterMsMax 131 ms" in line for line in logs.output))
        clock.advance(30.0)
        h.runtime.poll()
        bridge._service()
        self.assertEqual(len(knob.diag_lines()), 1, "once a minute, not every poll")


if __name__ == "__main__":
    unittest.main()

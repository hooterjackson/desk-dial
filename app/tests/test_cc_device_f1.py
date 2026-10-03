"""1.0.0-cc5.5 F1 (safety and measurement) on the host side: the clear-only `ks` of position lines and the
new diag fields, for the Desk Dial bridge (control_center/device.py) and for the installed Desk Dial v7.

Firmware (firmware/src/com_thread.cpp handleEvents(), control_center.cpp
cc_position_key_state()): a position line of the ready control carries `ks` = the key mask the knob last
reported (on a kd / ku / kh / ready line) AND its live mask, read before the key queue is checked; while a
key event is still queued the mask is reported unchanged. The HMI publishes a press before queueing its kd
and a release only after queueing its ku (hmi_thread.cpp). So a position line can clear a bit (a key-up lost
to a full queue, now 16 events) but never set one.

The installed Desk Dial v7 copies any `ks` into its pressed mask (DeviceBridge._consume: `if state is not
None: self._pressed = state`, read from device.py before this change; V7Model below is that rule). With a
`ks` that could set bits, a position line arriving before its kd would pre-set the bit and swallow the kd;
with the clear-only `ks` it cannot, and no ku is pre-empted either (FirmwareModel below replays the firmware's
ordering, with the two tasks interleaved at every step). The new bridge uses a position line's `ks` only to
clear bits, emitting `release` for each, before the turn the line carries.

No port, window or network is used: the bridge runs on an in-memory serial (test_cc_device.CapabilitySerial).
"""
from pathlib import Path
import queue
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_center import device  # noqa: E402
from control_center.device import DeviceBridge  # noqa: E402
from test_cc_device import CAPS_P5, CapabilitySerial, Clock, upnext_frame  # noqa: E402

KEY_QUEUE = 16          # hmi_thread.cpp _q_keyevt_out (1.0.0-cc5.5; 5 before)


def _mask_ok(value):
    return type(value) is int and 0 <= value <= 15


class V7Model:
    """The key handling of the installed Desk Dial v7 (device.py before 1.0.0-cc5.5), rule for rule:
    `ready` re-seeds the pressed mask from `ks`; a `ku` clears its bit (a release when it was set); a `kd`
    presses when `ks` has its bit (or is absent) and the bit is clear; then ANY line's valid `ks` becomes
    the pressed mask."""

    def __init__(self):
        self.pressed, self.events = 0, []

    def consume(self, message):
        if "ready" in message:
            self.pressed = message["ks"] if _mask_ok(message.get("ks")) else 0
            return
        state = message.get("ks") if _mask_ok(message.get("ks")) else None
        up, down = message.get("ku"), message.get("kd")
        if type(up) is int and 0 <= up <= 3:
            was = self.pressed & (1 << up)
            self.pressed &= ~(1 << up)
            if was:
                self.events.append(("release", up))
        if type(down) is int and 0 <= down <= 3:
            mask = 1 << down
            if (state is None or state & mask) and not self.pressed & mask:
                self.pressed |= mask
                self.events.append(("button", down))
        if state is not None:
            self.pressed = state


class FirmwareModel:
    """The knob's side, as micro-steps the scheduler interleaves: the HMI task (press: publish, then queue
    the kd; release: queue the ku, then publish) and the COM task (send one queued key line; a position line
    in two steps: read the live mask, then check the queue and send). `naive` models the rejected design
    (a position line's ks = the live mask)."""

    def __init__(self, naive=False, capacity=KEY_QUEUE):
        self.naive, self.capacity = naive, capacity
        self.physical = self.live = self.reported = 0
        self.queue, self.lines, self.dropped = [], [], []
        self.position, self.live_read = 0, None
        self.lines.append({"ready": 1, "p": 0, "ks": 0})

    # HMI task
    def publish(self):
        self.live = self.physical

    def enqueue(self, kind, raw):
        event = {"id": 1, "ks": self.physical, kind: raw}
        if len(self.queue) < self.capacity:
            self.queue.append(event)
        else:
            self.dropped.append(event)

    def hmi_steps(self, raw, press):
        """The two micro-steps of one edge, in the firmware's order."""
        bit = 1 << raw

        def edge():
            self.physical = self.physical | bit if press else self.physical & ~bit
        if press:
            return [lambda: (edge(), self.publish()), lambda: self.enqueue("kd", raw)]
        return [lambda: (edge(), self.enqueue("ku", raw)), self.publish]

    # COM task
    def send_key(self):
        if self.queue:
            line = self.queue.pop(0)
            self.lines.append(line)
            self.reported = line["ks"]

    def read_live(self):
        self.live_read = self.live

    def send_position(self):
        live, self.live_read = self.live if self.live_read is None else self.live_read, None
        self.position += 1
        if self.naive:
            ks = live
        else:
            if not self.queue:
                self.reported &= live
            ks = self.reported
        self.lines.append({"id": 1, "p": self.position, "ks": ks})

    def drain(self):
        while self.queue:
            self.send_key()
        self.read_live()
        self.send_position()


def schedule(rng, firmware, edges=6):
    """One random interleaving of `edges` physical edges with COM key and position steps."""
    hmi = []
    down = set()
    for _ in range(edges):
        raw = rng.randrange(4)
        press = raw not in down
        (down.add if press else down.discard)(raw)
        hmi.extend(firmware.hmi_steps(raw, press))
    com_pending = []
    while hmi or com_pending:
        choice = rng.random()
        if hmi and (choice < 0.45 or not com_pending and choice < 0.7):
            hmi.pop(0)()
        elif com_pending:
            com_pending.pop(0)()
        elif rng.random() < 0.5:
            firmware.send_key()
        else:
            com_pending = [firmware.read_live, firmware.send_position]
    firmware.drain()


class BridgeHarness:
    def __init__(self, test):
        temp = tempfile.TemporaryDirectory()
        test.addCleanup(temp.cleanup)
        self.clock = Clock()
        self.serial = CapabilitySerial(self.clock, CAPS_P5)
        self.serial.ready_ks = 0
        self.bridge = DeviceBridge(temp.name, lambda port: self.serial, request_timeout=0.1, autostart=False,
                                   clock=self.clock, local_minute=lambda: 600)
        self.bridge._connect("COM-FAKE")
        self.bridge._enter({"id": 1, "profile": "MIDI CLACK JONES", "min": 0, "max": 100, "position": 0,
                            "windowsButton": 3, "windowsHidEnabled": False, "buttonOrder": [0, 1, 2, 3],
                            "frame": upnext_frame()})
        self.events()

    def events(self):
        output = []
        while True:
            try:
                output.append(self.bridge.events.get_nowait())
            except queue.Empty:
                return output

    def feed(self, lines):
        for line in lines:
            if "ready" not in line:
                self.bridge._consume(line)
        return [(e["kind"], e.get("button", e.get("index"))) for e in self.events()
                if e["kind"] in ("button", "release")]


class PositionKeyStateTests(unittest.TestCase):
    def setUp(self):
        self.h = BridgeHarness(self)

    def test_a_position_line_before_its_kd_never_swallows_the_kd(self):
        # The race: the HMI published the press, the COM task sent a turn before the kd. Firmware cc5.5 never
        # puts that bit in the position line's ks; even a line that did would not pre-set it here.
        self.h.bridge._consume({"id": 1, "p": 3, "ks": 2})
        self.assertEqual(self.h.bridge._pressed, 0)
        events = self.h.events()
        self.assertEqual([e["kind"] for e in events], ["position"])
        self.h.bridge._consume({"id": 1, "ks": 2, "kd": 1})
        self.assertEqual(self.h.events(), [{"kind": "button", "id": 1, "index": 1, "button": 1, "pressed": True,
                                            "hid": False}])

    def test_a_position_line_clears_a_lost_key_up_and_releases_it_before_the_turn(self):
        self.h.bridge._consume({"id": 1, "ks": 0b0110, "kd": 2})
        self.h.events()
        self.h.bridge._consume({"id": 1, "ks": 0b0110, "kd": 1})   # ks names 1 and 2 (the knob's mask)
        self.h.events()
        self.assertEqual(self.h.bridge._pressed, 0b0110)
        self.h.bridge._consume({"id": 1, "p": 4, "ks": 0b0010})     # button 2's ku was lost
        self.assertEqual(self.h.events(), [{"kind": "release", "id": 1, "index": 2, "button": 2},
                                           {"kind": "position", "id": 1, "p": 4, "position": 4, "delta": 4}])
        self.assertEqual(self.h.bridge._pressed, 0b0010)
        self.h.bridge._consume({"id": 1, "ks": 0b0010, "ku": 2})    # a late ku of it: no second release
        self.h.bridge._consume({"id": 1, "p": 5, "ks": 0b0010})
        self.assertEqual([e["kind"] for e in self.h.events()], ["position"])

    def test_invalid_or_absent_position_ks_changes_nothing(self):
        self.h.bridge._consume({"id": 1, "ks": 1, "kd": 0})
        self.h.events()
        for ks in (None, 16, -1, True, "0"):
            line = {"id": 1, "p": 7}
            if ks is not None:
                line["ks"] = ks
            self.h.bridge._consume(line)
            self.assertEqual(self.h.bridge._pressed, 1, ks)
        self.h.bridge._consume({"id": 2, "p": 8, "ks": 0})           # another control's line: ignored
        self.assertEqual(self.h.bridge._pressed, 1)

    def test_key_lines_still_reseed_the_pressed_mask(self):
        self.h.bridge._consume({"id": 1, "ks": 0b1001, "kd": 3})
        self.assertEqual(self.h.bridge._pressed, 0b1001)
        self.h.bridge._consume({"id": 1, "ks": 0b1001, "kh": 3})
        self.assertEqual(self.h.bridge._pressed, 0b1001)

    def test_a_cc54_position_line_has_no_ks_and_keeps_the_pressed_mask(self):
        self.h.bridge._consume({"id": 1, "ks": 4, "kd": 2})
        self.h.bridge._consume({"id": 1, "p": 2})
        self.assertEqual(self.h.bridge._pressed, 4)


class FirmwareOrderingTests(unittest.TestCase):
    """The firmware's clear-only ks against both hosts, over random interleavings of the two tasks."""

    def check_run(self, seed, naive=False):
        rng = random.Random(seed)
        firmware = FirmwareModel(naive=naive)
        schedule(rng, firmware, edges=rng.randrange(2, 9))
        kd_lines = [line["kd"] for line in firmware.lines if "kd" in line]
        ku_lines = [line["ku"] for line in firmware.lines if "ku" in line]
        v7 = V7Model()
        for line in firmware.lines:
            v7.consume(line)
        return firmware, kd_lines, ku_lines, v7

    def test_v7_never_loses_a_kd_or_a_ku_with_the_clear_only_ks(self):
        for seed in range(3000):
            firmware, kd_lines, ku_lines, v7 = self.check_run(seed)
            self.assertFalse(firmware.dropped, seed)
            presses = [raw for kind, raw in v7.events if kind == "button"]
            releases = [raw for kind, raw in v7.events if kind == "release"]
            self.assertEqual(presses, kd_lines, f"seed {seed}: a kd was swallowed ({firmware.lines})")
            self.assertEqual(releases, ku_lines, f"seed {seed}: a ku was pre-empted ({firmware.lines})")
            self.assertEqual(v7.pressed, firmware.physical, seed)

    def test_the_new_bridge_sees_every_edge_once(self):
        for seed in range(400):
            firmware, kd_lines, ku_lines, _ = self.check_run(seed)
            events = BridgeHarness(self).feed(firmware.lines)
            self.assertEqual([raw for kind, raw in events if kind == "button"], kd_lines, seed)
            self.assertEqual([raw for kind, raw in events if kind == "release"], ku_lines, seed)

    def test_a_live_mask_ks_would_swallow_kds_on_v7(self):
        """Why the ks is clear-only: the rejected design (ks = the live mask) loses presses on v7."""
        swallowed = 0
        for seed in range(3000):
            _, kd_lines, _, v7 = self.check_run(seed, naive=True)
            swallowed += len(kd_lines) - len([1 for kind, _ in v7.events if kind == "button"])
        self.assertGreater(swallowed, 0)

    def test_a_key_up_lost_to_a_full_queue_is_healed_by_the_next_position_line(self):
        firmware = FirmwareModel(capacity=2)
        for step in firmware.hmi_steps(0, True) + firmware.hmi_steps(1, True):
            step()
        firmware.drain()                                   # kd 0, kd 1 sent; reported 0b11
        for step in firmware.hmi_steps(2, True) + firmware.hmi_steps(2, False) + firmware.hmi_steps(0, False):
            step()                                         # kd 2, ku 2 queued; ku 0 dropped (full)
        self.assertEqual([e.get("ku") for e in firmware.dropped], [0])
        firmware.drain()
        self.assertEqual(firmware.lines[-1], {"id": 1, "p": 2, "ks": 0b0010})
        events = BridgeHarness(self).feed(firmware.lines)
        self.assertEqual(events, [("button", 0), ("button", 1), ("button", 2), ("release", 2), ("release", 0)])
        v7 = V7Model()
        for line in firmware.lines:
            v7.consume(line)
        self.assertEqual(v7.pressed, 0b0010)              # v7: no stuck button 0 either (no release event)


class F1DiagTests(unittest.TestCase):
    CC55 = {"lcdDma": True, "lcdPeriodMs": 12, "artAsync": True, "lcdMosiSig": 103, "build": "F",
            "focLoopHz": 6200, "focLoopUsMax": 480, "uqAbsMax": 2120, "uqCapMs": 0, "uqCapMv": 2200,
            "pdRead": True, "pdPdo": 2, "pdVolts": 9, "pdRdo": 0x2004B12C, "usbMidiOk": True, "usbHidOk": True,
            "hidRetries": 3, "resetReason": "poweron"}

    def test_the_f1_fields_parse_with_their_types(self):
        fields, invalid = device.diag_parse(self.CC55)
        self.assertEqual(invalid, [])
        for name in device.DIAG_F1_FIELDS + device.DIAG_BUILD_FIELDS:
            self.assertEqual(fields[name], self.CC55[name], name)
        self.assertNotIn("resetReason", fields)
        self.assertEqual(device.diag_binary(fields), "F")

    def test_malformed_f1_values_are_dropped_and_named(self):
        bad = dict(self.CC55, pdPdo=8, pdVolts=-1, pdRead=1, usbHidOk="yes", uqAbsMax=2.2, build="G", hidRetries=None)
        fields, invalid = device.diag_parse(bad)
        for name in ("pdPdo", "pdVolts", "pdRead", "usbHidOk", "uqAbsMax", "build", "hidRetries"):
            self.assertIn(name, invalid)
            self.assertNotIn(name, fields)
        self.assertEqual(invalid, sorted(invalid, key=list(device.DIAG_FIELDS).index))

    def test_binaries_by_build_letter_and_pipeline(self):
        d = {"lcdDma": True, "lcdPeriodMs": 16, "artAsync": True}
        e = {"lcdDma": False, "lcdPeriodMs": 33, "artAsync": False}
        f = {"lcdDma": True, "lcdPeriodMs": 12, "artAsync": True}
        self.assertEqual(device.diag_binary({**d, "build": "D"}), "D")
        self.assertEqual(device.diag_binary({**e, "build": "E"}), "E")
        self.assertEqual(device.diag_binary({**f, "build": "F"}), "F")
        self.assertEqual(device.diag_binary({**d, "build": "F"}), "F")      # D's pipeline at any period (P5-R12)
        self.assertIsNone(device.diag_binary({**e, "build": "F"}))          # F's letter on E's pipeline
        self.assertIsNone(device.diag_binary({**d, "build": "Z"}))
        self.assertEqual(device.diag_binary(d), "A")                        # no build field: A, B or C
        self.assertEqual(device.diag_binary(f), "A")

    def test_a_cc54_reply_has_no_f1_fields(self):
        from test_cc_device_diag import cc54_diag
        fields, invalid = device.diag_parse(cc54_diag())
        self.assertEqual(invalid, [])
        self.assertFalse(set(device.DIAG_F1_FIELDS) & set(fields))

    def test_the_tooling_reads_the_same_fields(self):
        tooling = Path(__file__).resolve().parents[2] / "tools" / "nanod_cc5_tooling.py"
        if not tooling.is_file():
            self.skipTest("work tree not present")
        import importlib.util
        spec = importlib.util.spec_from_file_location("nanod_cc5_tooling_for_f1", tooling)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.F1_DIAG_FIELDS, device.DIAG_F1_FIELDS)
        self.assertEqual(module.LCD_FIX_DIAG_FIELDS, device.DIAG_BUILD_FIELDS)
        for letter, flags in device.DIAG_BINARIES.items():
            self.assertEqual(module.LCD_BINARIES[letter], flags, letter)
            self.assertEqual(module.lcd_binary({**flags, "build": letter}) if letter in "DEF" else module.lcd_binary(flags),
                             device.diag_binary({**flags, "build": letter}) if letter in "DEF" else device.diag_binary(flags))


if __name__ == "__main__":
    unittest.main()

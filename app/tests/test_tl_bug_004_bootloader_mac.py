"""TL-BUG-004: nanod_enter_bootloader_v2.py reads the knob's settings serialNumber (getEfuseMac hex, byte order
normalised) on the application port and sends the 1200-bps touch only when it names CHIP_MAC; a foreign knob, an
unreadable reply or an unset/placeholder CHIP_MAC send nothing. A 303A:1001 port with another MAC after a touch is
reported. Ports, the knob and the touch are fakes: nothing is opened."""
import contextlib
import io
import unittest
from unittest import mock

import test_cc5_tooling as base

t = base.t


def efuse_hex(mac):
    """String(ESP.getEfuseMac(), HEX) for `mac`: the little-endian integer, leading zeros dropped."""
    return format(int.from_bytes(bytes.fromhex(t.normalize_mac(mac)), "little"), "X")


def other_mac(mac):
    """A MAC that is not `mac` (every byte changed)."""
    raw = bytes(b ^ 0x5A for b in bytes.fromhex(t.normalize_mac(mac)))
    return ":".join(f"{b:02X}" for b in raw)


class FakeSettingsKnob:
    def __init__(self, serial_number=None, fail=None):
        self.serial_number, self.fail, self.sent, self.closed = serial_number, fail, [], False

    def pump(self, seconds=0.0):
        return []

    def request(self, payload, predicate, timeout=2.0, what="reply"):
        self.sent.append(payload)
        if self.fail:
            raise self.fail
        reply = {"settings": {"serialNumber": self.serial_number, "deviceName": "Nano_x"}}
        assert predicate(reply)
        return reply

    def close(self):
        self.closed = True


@base.needs_tooling
class BootloaderMacTests(unittest.TestCase):
    def setUp(self):
        self.script = base.load_script("nanod_enter_bootloader_v2.py")
        st = self.script.t
        self.written, self.touches = [], []
        self.ports = [base.APP()]
        self.after = [base.APP()]
        self.lists = 0
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, value in (("companion_running", lambda *a, **k: False),
                            ("list_ports", self.list_ports),
                            ("write_new_json", lambda path, data: self.written.append(data) or "evidence.json"),
                            ("poll_ports", lambda predicate, timeout: (None, [])),
                            ("console_utf8", lambda: None)):
            stack.enter_context(mock.patch.object(st, name, value))
        self.out = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def list_ports(self):
        self.lists += 1
        return self.ports if self.lists == 1 else self.after

    def run_main(self, knob):
        code = self.script.main([], knob_factory=lambda device: knob,
                                toucher=lambda device: self.touches.append(device) or "touched")
        [report] = self.written
        return code, report

    def test_enter_bootloader_refuses_foreign_mac_before_touch(self):
        knob = FakeSettingsKnob(efuse_hex(other_mac(t.CHIP_MAC)))
        code, report = self.run_main(knob)
        self.assertEqual(code, 1)
        self.assertEqual(self.touches, [])
        self.assertFalse(report["touchSent"])
        self.assertFalse(report["macMatched"])
        self.assertIn("No reset sent", report["error"])
        self.assertEqual(knob.sent, [{"settings": "?"}])
        self.assertTrue(knob.closed)

    def test_matching_mac_sends_one_touch(self):
        for serial in (efuse_hex(t.CHIP_MAC), efuse_hex(t.CHIP_MAC).lower(), t.CHIP_MAC):
            with self.subTest(serial=serial):
                self.written, self.touches, self.lists = [], [], 0
                code, report = self.run_main(FakeSettingsKnob(serial))
                self.assertEqual(self.touches, ["COMA"])
                self.assertTrue(report["touchSent"])
                self.assertTrue(report["macMatched"])

    def test_unreadable_settings_or_placeholder_mac_send_nothing(self):
        code, report = self.run_main(FakeSettingsKnob(fail=TimeoutError("No settings within 2.0 s")))
        self.assertEqual((code, self.touches, report["touchSent"]), (1, [], False))
        self.assertIn("No reset sent", report["error"])
        for placeholder in ("", "XX:XX:XX:XX:XX:XX", "00:00:00:00:00:00"):
            with self.subTest(placeholder=placeholder):
                self.written, self.lists = [], 0
                knob = FakeSettingsKnob(efuse_hex(t.CHIP_MAC))
                with mock.patch.object(self.script.t, "CHIP_MAC", placeholder):
                    code, report = self.run_main(knob)
                self.assertEqual((code, self.touches, report["touchSent"]), (1, [], False))
                self.assertEqual(knob.sent, [])                    # the port is not even opened
                self.assertIn("placeholder", report["error"])

    def test_foreign_rom_port_after_touch_is_reported(self):
        self.after = [base.ROM(serial=other_mac(t.CHIP_MAC), device="COMF")]
        code, report = self.run_main(FakeSettingsKnob(efuse_hex(t.CHIP_MAC)))
        self.assertEqual(code, 1)
        self.assertEqual([p["port"] for p in report["foreignRomPorts"]], ["COMF"])
        self.assertIn("another MAC appeared: COMF", self.out.getvalue())

    def test_efuse_byte_order(self):
        match = self.script.efuse_mac_matches
        self.assertTrue(match(efuse_hex(t.CHIP_MAC), t.CHIP_MAC))
        self.assertFalse(match(efuse_hex(other_mac(t.CHIP_MAC)), t.CHIP_MAC))
        self.assertFalse(match(None, t.CHIP_MAC))
        self.assertFalse(match("not hex", t.CHIP_MAC))
        self.assertFalse(match("1" * 13, t.CHIP_MAC))


if __name__ == "__main__":
    unittest.main()

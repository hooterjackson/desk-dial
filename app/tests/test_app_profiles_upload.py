"""The app-profile upload on the device bridge (APP_PROFILES.md section 7; plan sections 1c / 6, S1 DD-B): list first
(an id + crc already loaded is skipped), begin, data lines of <= 3000 base64 characters each waiting for its ack, end;
a failure retries the whole upload once, then fails; the 500 ms frame heartbeat keeps going in between; the store is
RAM only, so a reconnect uploads again. A fake knob speaks the protocol; no port is opened."""
from pathlib import Path
import base64
import json
import queue
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cc5_support import Clock  # noqa: E402
from test_cc_device import FakeSerial, upnext_frame  # noqa: E402

from control_center.app_profiles import load_pair  # noqa: E402
from control_center.device import DeviceBridge  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
CAPS = {"controlCenter": 1, "leaseMs": 2000, "presentation": 6, "appCanvas": 1, "appProfiles": 1,
        "appProfileSlots": 4, "appProfileMaxBytes": 32768, "appProfileFeatures": 31}


def figma():
    return load_pair(PROFILES / "karl" / "figma.json", PROFILES / "figma.windows.json")


class KnobSerial(FakeSerial):
    """A knob with the appProfile store: replies come `delay` seconds after the line (the fake clock moves 10 ms a
    read), in the order of the lines (one serial port: a slow reply holds back the later ones). `fail` lists replies
    to turn into errors ("begin", "data", "end"); `silent` drops acks; `late` maps a data offset to extra seconds
    before its ack (once). As the firmware (cc_app_store_msg.cpp): a begin aborts any earlier upload, a failed begin
    answers an error, and a data line with no upload in progress answers "order"."""

    def __init__(self, clock, caps=CAPS, delay=0.0):
        super().__init__(clock)
        self.caps = caps
        self.delay = delay
        self.store = {}
        self.staging = None
        self.pending = []
        self.fail = []
        self.silent = False
        self.late = {}
        self.lines = []

    def later(self, message, extra=0.0):
        self.pending.append((self.clock.now + self.delay + extra, message))

    def write(self, raw):
        message = json.loads(raw)
        self.lines.append(message)
        if message == {"capabilities": "?"}:
            self.writes.append(message)
            self.inject({"capabilities": self.caps})
            return len(raw)
        up = message.get("appProfile")
        if not isinstance(up, dict):
            return super().write(raw)
        self.writes.append(message)
        op = up.get("op")
        if op == "list":
            self.later({"appProfile": {"loaded": [{"id": k, "crc": v[0]} for k, v in self.store.items()]}})
        elif op == "begin":
            self.staging = None
            if "begin" in self.fail:
                self.fail.remove("begin")
                self.later({"appProfile": {"error": "busy"}})
            else:
                self.staging = {"id": up["id"], "crc": up["crc"], "bytes": up["bytes"], "data": bytearray()}
        elif op == "data":
            if self.staging is None:
                self.later({"appProfile": {"error": "order"}})
            elif "data" in self.fail:
                self.fail.remove("data")
                self.later({"appProfile": {"error": "order"}})
                self.staging = None
            elif not self.silent:
                part = base64.b64decode(up["b64"])
                assert up["off"] == len(self.staging["data"]), "offsets in order"
                self.staging["data"] += part
                self.later({"appProfile": {"ack": len(self.staging["data"])}}, self.late.pop(up["off"], 0.0))
        elif op == "end":
            data = bytes(self.staging["data"])
            if "end" in self.fail:
                self.fail.remove("end")
                self.later({"appProfile": {"error": "decode:5@120"}})
            elif zlib.crc32(data[:-4]) & 0xFFFFFFFF != self.staging["crc"]:
                self.later({"appProfile": {"error": "crc"}})
            else:
                self.store[self.staging["id"]] = (self.staging["crc"], data)
                self.later({"appProfile": {"id": self.staging["id"], "crc": self.staging["crc"], "ok": True}})
            self.staging = None
        return len(raw)

    def read(self, size):
        while self.pending and self.pending[0][0] <= self.clock.now:
            self.inject(self.pending.pop(0)[1])
        return super().read(size)


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.serial = KnobSerial(self.clock)
        self.bridge = DeviceBridge(self.temp.name, lambda port: self.serial, request_timeout=0.1, autostart=False,
                                   clock=self.clock)
        self.bridge._connect("COM-FAKE")
        self.events()
        self.profile = figma()
        self.request = {"id": "figma", "crc": self.profile.wire_crc, "wire": self.profile.wire()}

    def events(self, kind=None):
        out = []
        while True:
            try:
                event = self.bridge.events.get_nowait()
            except queue.Empty:
                return [e for e in out if kind is None or e["kind"] == kind]
            out.append(event)

    def run_passes(self, n=400):
        for _ in range(n):
            self.bridge._service()
            if self.bridge._app_upload is None and not self.bridge._app_uploads:
                break

    def upload(self):
        self.bridge._dispatch("app_profile", self.request)
        self.run_passes()
        return self.events("app-profile")

    def test_list_begin_data_end_and_the_bytes_arrive(self):
        events = self.upload()
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["id"], events[0]["crc"], events[0]["state"]), ("figma", self.profile.wire_crc,
                                                                                    "loaded"))
        self.assertEqual(events[0]["bytes"], len(self.profile.wire()))
        self.assertEqual(self.serial.store["figma"], (self.profile.wire_crc, self.profile.wire()))
        ops = [m["appProfile"]["op"] for m in self.serial.lines if "appProfile" in m]
        self.assertEqual(ops[:2], ["list", "begin"])
        self.assertEqual(ops[-1], "end")
        datas = [m["appProfile"] for m in self.serial.lines if m.get("appProfile", {}).get("op") == "data"]
        self.assertGreater(len(datas), 1)
        self.assertTrue(all(len(d["b64"]) <= 3000 for d in datas))
        self.assertEqual([d["off"] for d in datas], [i * 2250 for i in range(len(datas))])
        begin = next(m["appProfile"] for m in self.serial.lines if m.get("appProfile", {}).get("op") == "begin")
        self.assertEqual(begin, {"op": "begin", "id": "figma", "bytes": len(self.profile.wire()),
                                 "crc": self.profile.wire_crc, "wire": 1})
        for message in self.serial.lines:
            self.assertLessEqual(len(json.dumps(message, separators=(",", ":"))) + 1, 4096)

    def test_an_id_and_crc_already_loaded_is_not_sent_again(self):
        self.upload()
        self.serial.lines.clear()
        events = self.upload()
        self.assertEqual(events[0]["state"], "present")
        self.assertEqual([m["appProfile"]["op"] for m in self.serial.lines if "appProfile" in m], ["list"])

    def test_a_failure_retries_the_whole_upload_once(self):
        self.serial.fail = ["data"]
        events = self.upload()
        self.assertEqual(events[0]["state"], "loaded")
        ops = [m["appProfile"]["op"] for m in self.serial.lines if "appProfile" in m]
        self.assertEqual(ops.count("begin"), 2, "the retry starts again from begin")
        self.assertEqual(ops.count("list"), 2, "the retry first drains the stale replies with a list (DD-6)")

    def test_a_second_failure_reports_failed(self):
        self.serial.fail = ["end", "end"]
        events = self.upload()
        self.assertEqual((events[0]["state"], events[0]["error"]), ("failed", "decode:5@120"))
        self.assertNotIn("figma", self.serial.store)

    def test_a_missing_ack_times_out_per_chunk(self):
        self.serial.silent = True
        start = self.clock.now
        events = self.upload()
        self.assertEqual((events[0]["state"], events[0]["error"]), ("failed", "timeout"))
        self.assertGreaterEqual(self.clock.now - start, 2.0, "1 s per chunk, then the one retry")
        self.assertLess(self.clock.now - start, 3.0)

    def test_an_unknown_error_text_is_never_echoed(self):
        self.serial.fail = []
        self.bridge._dispatch("app_profile", self.request)
        self.bridge._service()
        self.bridge._app_upload["waiting"] = "end"
        self.bridge._app_upload["retried"] = True
        self.bridge._app_profile_reply({"error": "C:\\Users\\someone\\secret"})
        events = self.events("app-profile")
        self.assertEqual(events[0]["error"], "error")

    def test_the_heartbeat_keeps_going_during_an_upload(self):
        self.serial.delay = 0.06                     # a slow knob: the upload outlasts a heartbeat period
        self.bridge._enter({"id": 1, "profile": "MIDI CLACK JONES", "min": 0, "max": 60000, "position": 30000,
                            "windowsButton": 3, "windowsHidEnabled": False, "frame": upnext_frame()})
        self.serial.lines.clear()
        self.upload()
        kinds = ["frame" if "frame" in m else m.get("appProfile", {}).get("op") for m in self.serial.lines]
        first, last = kinds.index("begin"), len(kinds) - 1 - kinds[::-1].index("end")
        self.assertIn("frame", kinds[first:last], "a heartbeat frame between the data lines")

    def test_a_reconnect_starts_empty(self):
        self.bridge._dispatch("app_profile", self.request)
        self.bridge._service()
        self.bridge._disconnect()
        self.assertIsNone(self.bridge._app_upload)
        self.assertFalse(self.bridge._app_uploads)

    def test_a_knob_without_app_profiles_never_gets_a_line(self):
        self.bridge._disconnect()
        self.serial = KnobSerial(self.clock, caps={"controlCenter": 1, "presentation": 6, "appCanvas": 1})
        self.bridge.serial_factory = lambda port: self.serial
        self.bridge._connect("COM-FAKE")
        self.events()
        events = self.upload()
        self.assertEqual((events[0]["state"], events[0]["error"]), ("failed", "unsupported"))
        self.assertFalse([m for m in self.serial.lines if "appProfile" in m])

    def test_bad_requests_are_ignored(self):
        for bad in (None, {"id": "Figma", "crc": 1, "wire": b"x"}, {"id": "figma", "crc": -1, "wire": b"x"},
                    {"id": "figma", "crc": 1, "wire": b""}, {"id": "figma", "crc": 1, "wire": "text"}):
            self.bridge._dispatch("app_profile", bad)
        self.assertIsNone(self.bridge._app_upload)
        self.assertFalse(self.bridge._app_uploads)
        self.assertEqual(self.events("app-profile"), [])

    def test_submit_accepts_the_command(self):
        self.bridge.submit("app_profile", self.request)
        self.assertEqual(self.bridge.commands.get_nowait()[0], "app_profile")


if __name__ == "__main__":
    unittest.main()

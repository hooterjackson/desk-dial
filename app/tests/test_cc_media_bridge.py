"""artwork2 in the DeviceBridge (ARTWORK2.md sections 1, 3, 4 and 9) against the FakeKnob.

The knob is tests/tools/capture_session_frames.FakeKnob: the section 4.4 media store model
and, for the transport tests, the byte-level CDC model (the 8192-byte receive queue,
per-tick COM drains, injected 30-100 ms COM stalls; a byte that does not fit is dropped
and its line becomes a JSON parse error). One fake clock drives the bridge and the knob.
No port, window or network is touched.
"""
import base64
from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import queue
import random
import sys
import tempfile
import threading
import time
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tests" / "tools"
for _path in (str(ROOT), str(TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import device, presentation  # noqa: E402
from control_center.device import DeviceBridge, PacedSerial, artwork2_capability  # noqa: E402
from capture_session_frames import (CC4_CAPABILITIES, CC5_CAPABILITIES, CC53_CAPABILITIES, CdcModel,  # noqa: E402
                                    Clock, FakeKnob, Recorder)

PROFILE = "NANO_D DEFAULT"
CAP = presentation.ARTWORK2_CAPABILITY
BUDGET = CAP["rxBytes"] - DeviceBridge.TX_RESERVE_BYTES
# A timed-out media line stays answerable this long; no other media line competes with it.
GRACE = DeviceBridge.MEDIA_LINE_GRACE * presentation.MEDIA_ACK_TIMEOUT_SECONDS


def payload(seed, size):
    return random.Random(seed).randbytes(size)


def covers(count, size=6000, prefix="cov"):
    return [(f"{prefix}{i:02d}", payload(f"{prefix}{i}", size)) for i in range(count)]


def icons(count, prefix="ico"):
    return [(f"{prefix}{i:02d}", payload(f"{prefix}{i}", presentation.ICON_BYTES)) for i in range(count)]


BUTTONS = [{"label": "Cancel", "enabled": True, "icon": "cancel"}, {"label": "Home", "enabled": True, "icon": "home"},
           {"label": "Win", "enabled": True, "icon": "win"}, {"label": "Switch", "enabled": True, "icon": "switch"}]


def frame(art_key="", icon_key="", title="Research notes", app="Chrome", index=2, count=11, layout="windows"):
    value = {"mode": "WINDOWS", "target": "DESKTOP", "value": title, "detail": app, "status": "", "title": title,
             "subtitle": app, "layout": layout, "ledStyle": "color", "buttons": deepcopy(BUTTONS),
             "ring": {"style": "selection", "value": 0, "index": index, "count": count}}
    if art_key:
        value["artKey"] = art_key
    if icon_key:
        value["iconKey"] = icon_key
    return value


def big_frame(n, art_key="", icon_key=""):
    """A ~1 KB Windows frame (long title and app, 45 windows, accents): the transport worst case."""
    index = n % 45
    value = frame(art_key, icon_key, title=("Quarterly planning — draft review of item %d " % n) * 2,
                  app="Microsoft Visual Studio Code Insiders · " + "x" * 50, index=index, count=45)
    first = presentation.window_first(index, 45)
    value["ring"].update(first=first, colors=[0x46E178 + n] * 20, unavailable=(1 << 19) | 1)
    return value


def at(record):
    return record["t"] + 1000.0  # Recorder times are relative to the Clock's 1000.0 start


PASS = object()  # ScriptedKnob.replies: send the real reply


class ScriptedKnob(FakeKnob):
    """FakeKnob whose media replies a test can hold back, replace, drop or turn into errors,
    whose written lines a test can lose or damage on the wire, and whose replies (all of
    them, in line order) a test can delay."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hold = False       # media replies are held back
        self.hold_all = False   # every reply is held back, in line order (a late knob)
        self.held = []
        self.replies = deque()  # for the next media replies: a replacement message, PASS or None (lost)
        self.fail = {}          # (op, key) -> the error text answered instead (the knob cancels the upload)
        self.lose = []          # predicates on written lines: the first match is lost (each one once)
        self.lost = []          # (time, line) of every lost line
        self.damage = []        # (predicate, transform) on written lines: the first match arrives transformed
        self.damaged = []       # (time, line) of every damaged line, as written

    def write(self, data):
        for index, predicate in enumerate(self.lose):
            if predicate(bytes(data)):
                del self.lose[index]
                self.lost.append((self.clock(), bytes(data)))
                return len(data)
        for index, (predicate, transform) in enumerate(self.damage):
            if predicate(bytes(data)):
                del self.damage[index]
                self.damaged.append((self.clock(), bytes(data)))
                super().write(transform(bytes(data)))
                return len(data)
        return super().write(data)

    def inject(self, message):
        if self.hold_all:
            self.held.append(message)
        else:
            super().inject(message)

    def _media(self, value, record):
        if self.media is None or not isinstance(value, dict):
            return super()._media(value, record)
        op, key = value.get("op"), value.get("key")
        if (op, key) in self.fail:
            self.media.upload = None
            ack = {"id": value.get("id"), "op": op, "kind": value.get("kind"), "key": key, "offset": 0,
                   "error": self.fail[(op, key)]}
        else:
            ack = self.media.media(value)
        self.media_acks[ack.get("op", "?")] += 1
        message = {"mediaAck": ack}
        if self.replies:
            replacement = self.replies.popleft()
            if replacement is None:
                return
            if replacement is not PASS:
                message = replacement
        if self.hold:
            self.held.append(message)
            return
        self.inject(message)

    def release_held(self, count=None):
        """Send the first `count` held replies (all when None), in order."""
        count = len(self.held) if count is None else count
        release, self.held = self.held[:count], self.held[count:]
        for message in release:
            FakeKnob.inject(self, message)


class Rig:
    """A DeviceBridge (autostart off) on a ScriptedKnob behind PacedSerial, run pass by pass."""

    def __init__(self, test, capabilities=CC53_CAPABILITIES, **knob_options):
        self.test = test
        self.clock = Clock()
        self.recorder = Recorder(self.clock)
        self.knob = ScriptedKnob(self.clock, deepcopy(capabilities), self.recorder, "1.0.0-cc5.3", **knob_options)
        self.sleeps = []
        self.port = PacedSerial(self.knob, sleep=self.sleeps.append)
        temp = tempfile.TemporaryDirectory()
        test.addCleanup(temp.cleanup)
        self.bridge = DeviceBridge(temp.name, lambda port: self.port, request_timeout=1.5, autostart=False,
                                   clock=self.clock)
        self.events = []
        self.control_id = 0

    def connect(self):
        self.bridge._connect("COM-TEST")
        self.collect()
        return self

    def enter(self, first_frame=None):
        self.control_id += 1
        self.bridge._enter({"id": self.control_id, "profile": PROFILE, "min": 0, "max": 40, "position": 0,
                            "windowsButton": 2, "frame": first_frame or frame()})
        self.collect()
        return self

    def show(self, value):
        """What the runtime does on a poll: the frame first, then the changed wanted lists."""
        self.bridge.submit("frame", {**value, "id": self.control_id})

    def want(self, kind, items):
        self.bridge.set_media_wanted(kind, items)

    def step(self):
        bridge = self.bridge
        waiting = bridge._deferred_command is not None or not bridge.commands.empty()
        command, value = bridge._next_command() if waiting else (None, None)
        bridge._dispatch(command, value)
        bridge._service()
        self.collect()

    def run(self, *, until=None, seconds=None, driver=None, limit=400000):
        end = None if seconds is None else self.clock() + seconds
        for _ in range(limit):
            if driver is not None:
                driver(self)
            self.step()
            if until is not None and until(self):
                return
            if end is not None and self.clock() >= end:
                return
        self.test.fail("the rig did not finish")

    def collect(self):
        while True:
            try:
                self.events.append(self.bridge.events.get_nowait())
            except queue.Empty:
                return

    def kinds(self):
        return [event["kind"] for event in self.events]

    def media_events(self, name):
        return [event for event in self.events if event["kind"] == name]

    def records(self, *kinds):
        return [r for r in self.recorder.records if r["kind"] in kinds]

    def media_records(self, op=None, key=None):
        return [r for r in self.records("media") if (op is None or r["op"] == op) and (key is None or r["key"] == key)]

    def have_keys(self):
        return [json.loads(r["line"])["media"]["keys"] for r in self.media_records("have")]

    def on_knob(self, kind, key):
        return self.knob.media.stores[kind].find(key) >= 0

    def all_on_knob(self, kind, items):
        return all(self.on_knob(kind, key) for key, _data in items)


def settled(kind, items):
    return lambda rig: rig.all_on_knob(kind, items) and rig.bridge._media_wait is None


def preload(knob, kind, key, data, ident=1):
    """Commit `key` on the knob directly (a previous session's upload survives)."""
    model, chunk = knob.media, CAP["chunkBytes"]
    model.media({"id": ident, "op": "begin", "kind": kind, "key": key, "bytes": len(data),
                 "crc32": zlib.crc32(data)})
    for offset in range(0, len(data), chunk):
        model.media({"id": ident, "op": "data", "kind": kind, "key": key, "offset": offset,
                     "data": base64.b64encode(data[offset:offset + chunk]).decode("ascii")})
    ack = model.media({"id": ident, "op": "commit", "kind": kind, "key": key})
    assert "error" not in ack, ack


# ---------------------------------------------------------------------------

class GatingTests(unittest.TestCase):
    """Section 1: exactly the frozen capability negotiates artwork2."""

    def test_cc53_negotiates_and_cc52_cc4_do_not(self):
        for caps, negotiated in ((CC53_CAPABILITIES, True), (CC5_CAPABILITIES, False), (CC4_CAPABILITIES, False)):
            with self.subTest(presentation=caps.get("presentation"), artwork2="artwork2" in caps):
                rig = Rig(self, caps).connect()
                self.assertEqual(rig.bridge.media_capability, CAP if negotiated else None)
                self.assertEqual(rig.bridge.media_status()["cover"]["wanted"], 0)
                rig.want("cover", covers(2))
                self.assertEqual(rig.bridge.commands.qsize(), 1 if negotiated else 0, "a no-op without artwork2")

    def test_malformed_artwork2_is_not_negotiated(self):
        def variant(path, value):
            caps = deepcopy(CC53_CAPABILITIES)
            target = caps["artwork2"]
            for name in path[:-1]:
                target = target[name]
            if value is KeyError:
                del target[path[-1]]
            else:
                target[path[-1]] = value
            return caps
        variants = [(("version",), 2), (("version",), True), (("version",), 1.0), (("available",), False),
                    (("available",), 1), (("composited",), "none"), (("paced",), True), (("paced",), 0),
                    (("rxBytes",), 4096), (("rxBytes",), "8192"), (("chunkBytes",), 4096), (("haveKeys",), 25),
                    (("cover", "maxBytes"), 65536), (("cover", "format"), "PNG"), (("cover", "entries"), 24.0),
                    (("cover", "width"), 120), (("icon", "entries"), 47), (("icon", "background"), "white"),
                    (("icon", "format"), "RGB565"), (("icon", "bytes"), KeyError), (("cover",), KeyError),
                    (("cover",), [240, 240])]
        for path, value in variants:
            with self.subTest(field=".".join(path), value=value):
                self.assertIsNone(artwork2_capability(variant(path, value)))
        for caps in ({**CC53_CAPABILITIES, "presentation": 3}, {**CC53_CAPABILITIES, "presentation": True},
                     {**CC53_CAPABILITIES, "presentation": "4"}, {**CC53_CAPABILITIES, "artwork2": []},
                     {**CC53_CAPABILITIES, "artwork2": None}, None, {}):
            with self.subTest(caps=None if caps is None else {k: caps[k] for k in ("presentation",) if k in caps}):
                self.assertIsNone(artwork2_capability(caps))
        extra = deepcopy(CC53_CAPABILITIES)
        extra["artwork2"].update(future=1)
        extra["artwork2"]["cover"]["hdr"] = False
        self.assertEqual(artwork2_capability(extra), CAP, "unknown extra fields are ignored")
        rig = Rig(self, variant(("available",), False)).connect()
        self.assertIsNone(rig.bridge.media_capability)

    def test_malformed_artwork2_knob_keeps_v1_art_paced(self):
        caps = deepcopy(CC53_CAPABILITIES)
        caps["artwork2"]["chunkBytes"] = 4096
        rig = Rig(self, caps).connect().enter(frame(art_key="coverA", layout="nowPlaying"))
        self.assertIsNone(rig.bridge.media_capability)
        rig.bridge._queue_artwork({"id": 1, "key": "coverA", "data": b"\x12\x34" * 14400})
        rig.run(until=lambda r: r.bridge._artwork is None)
        self.assertEqual([e["kind"] for e in rig.events if e["kind"].startswith("artwork")], ["artwork-ready"])
        self.assertEqual(rig.knob.max_write_bytes, PacedSerial.CHUNK_BYTES, "v1 art stays paced")
        self.assertEqual(rig.records("media"), [])


class TransportTests(unittest.TestCase):
    """Section 3: whole-line writes and no v1 art only when negotiated."""

    def test_whole_line_writes_only_when_negotiated(self):
        big = big_frame(1)
        for caps, whole in ((CC53_CAPABILITIES, True), (CC5_CAPABILITIES, False)):
            with self.subTest(artwork2=whole):
                rig = Rig(self, caps).connect().enter(big)
                rig.show(big_frame(2))
                rig.run(seconds=1.2)
                frames = rig.records("frame", "control")
                self.assertGreaterEqual(len(frames), 3, "the entry, a frame and heartbeats")
                self.assertTrue(all(r["bytes"] > PacedSerial.CHUNK_BYTES for r in frames))
                if whole:
                    self.assertEqual(rig.knob.whole_line_writes, rig.knob.write_calls)
                    self.assertEqual(rig.sleeps, [], "no 5 ms gaps")
                    self.assertEqual(rig.knob.write_calls, len(rig.recorder.records), "one write per line")
                else:
                    self.assertEqual(rig.knob.max_write_bytes, PacedSerial.CHUNK_BYTES)
                    self.assertTrue(rig.sleeps and set(rig.sleeps) == {PacedSerial.GAP_SECONDS})

    def test_no_v1_art_line_with_artwork2(self):
        rig = Rig(self).connect().enter(frame(art_key="coverA", layout="nowPlaying"))
        rig.bridge.submit("artwork", {"id": 1, "key": "coverA", "data": b"\x12\x34" * 14400})
        rig.run(seconds=0.5)
        self.assertEqual(rig.records("art"), [])
        self.assertFalse([e for e in rig.events if e["kind"].startswith("artwork")], "not even an error event")

    def test_media_lines_are_stop_and_wait(self):
        rig = Rig(self).connect().enter()
        rig.knob.hold = True
        rig.want("cover", covers(3))
        rig.run(seconds=0.6)
        self.assertEqual(len(rig.records("media")), 1, "one media line outstanding at most")
        self.assertTrue(rig.bridge._busy(), "no 20 ms command-queue wait while a media line is out")
        for count in range(2, 6):
            rig.knob.release_held()
            rig.run(until=lambda r, n=count: len(r.records("media")) >= n)
            rig.run(seconds=0.1)
            self.assertEqual(len(rig.records("media")), count)

    def test_heartbeat_continues_while_a_media_line_is_outstanding(self):
        rig = Rig(self).connect().enter()
        rig.knob.hold = True
        rig.want("icon", icons(1))
        rig.run(until=lambda r: r.records("media"))
        start = rig.clock()
        rig.run(seconds=1.2)
        beats = [r for r in rig.records("frame") if r["t"] >= start - 1000.0]
        self.assertGreaterEqual(len(beats), 2, "heartbeat frames flow while the media line waits")
        self.assertEqual(rig.bridge.ready_id, 1)

    def test_frames_wait_for_the_receive_queue_and_the_latest_wins(self):
        rig = Rig(self).connect().enter()
        # The knob has not read 7 KB yet (as during a COM stall): the next frame waits.
        rig.bridge._tx_log.append((rig.clock(), BUDGET - 200, None))
        rig.show(big_frame(1))
        rig.show(big_frame(2))
        rig.step()
        rig.step()
        self.assertTrue(rig.bridge._frame_pending)
        self.assertEqual(rig.records("frame"), [], "nothing written over the budget")
        rig.want("icon", icons(1))
        rig.run(seconds=0.05)
        self.assertEqual(rig.records("media"), [], "no media line before the pending frame")
        rig.run(until=lambda r: r.records("media"))
        frames = rig.records("frame")
        self.assertEqual(len(frames), 1, "coalesced")
        self.assertIn("item 2 ", frames[0]["line"], "the latest frame")
        self.assertLess(frames[0]["n"], rig.records("media")[0]["n"])

    def test_requests_fit_the_reserve_whatever_the_frame_cadence(self):
        # The largest request: a control with a budget-trimmed ~1.1 KB Windows frame.
        bridge = Rig(self).connect().bridge
        control = {"id": 0x7FFFFFFF, "profile": "P" * 20, "min": 0, "max": 65535, "position": 65535,
                   "windowsButton": 3, "windowsHidEnabled": True, "buttonOrder": [3, 2, 1, 0],
                   "frame": {**device._frame(big_frame(7, "k" * 64, "i" * 24), bridge.capabilities),
                             "id": 0x7FFFFFFF}}
        self.assertLess(len(bridge._encode({"control": control})) + len(bridge._encode({"release": True})),
                        DeviceBridge.TX_RESERVE_BYTES)
        # Frames fill the whole frame/media budget while the knob reads nothing (as if written
        # back to back during a COM stall); a new control is still written at once and fits.
        rig = Rig(self, cdc=CdcModel()).connect().enter(big_frame(1))
        bridge, model = rig.bridge, rig.knob.cdc
        rig.run(seconds=0.2)
        model.stall(rig.clock(), 0.100)
        for n in range(2, 40):
            bridge._frame({**big_frame(n), "id": 1})
            if bridge._frame_pending:
                break
        self.assertTrue(bridge._frame_pending, "the frame budget is full")
        self.assertGreater(len(model.queue), BUDGET - presentation.FRAME_BUDGET_BYTES)
        writes, write = [], rig.knob.write
        rig.knob.write = lambda data: writes.append((rig.clock(), bytes(data))) or write(data)
        start = rig.clock()
        rig.enter(big_frame(99))
        (written_at, _line), = [w for w in writes if w[1].startswith(b'{"control"')]
        self.assertEqual(written_at, start, "not delayed")
        self.assertGreater(model.high_water, BUDGET, "the reserve held it")
        self.assertEqual(model.dropped_bytes, 0)
        self.assertEqual(bridge.ready_id, 2)
        self.assertNotIn("error", rig.kinds())


class ProbeAndOrderTests(unittest.TestCase):
    """Section 9: the have probe, the upload order, preemption and the order of writes."""

    def test_have_probe_contents_and_order(self):
        rig = Rig(self).connect().enter()
        a, b, c, d = covers(4)
        preload(rig.knob, "cover", *b)  # the knob already holds b
        rig.want("cover", [a, b, c])
        rig.run(until=settled("cover", [a, b, c]))
        self.assertEqual(rig.have_keys(), [[a[0], b[0], c[0]]])
        self.assertEqual([r["key"] for r in rig.media_records("begin")], [a[0], c[0]], "b was confirmed present")
        rig.want("cover", [b, a, c])  # a new index 0, every key confirmed: index 0 only
        rig.run(seconds=0.2)
        self.assertEqual(rig.have_keys()[-1], [b[0]])
        rig.want("cover", [b, a, c, d])  # same index 0, one unconfirmed key
        rig.run(until=settled("cover", [a, b, c, d]))
        self.assertEqual(rig.have_keys()[-1], [b[0], d[0]])
        probes = len(rig.have_keys())
        rig.want("cover", [b, a, c, d])  # unchanged: no probe
        rig.run(seconds=0.3)
        self.assertEqual(len(rig.have_keys()), probes)
        self.assertEqual(rig.bridge.media_status()["cover"]["hits"], 1)

    def test_have_is_capped_at_have_keys(self):
        rig = Rig(self).connect().enter()
        wanted = icons(30)
        rig.want("icon", wanted)
        rig.run(until=settled("icon", wanted))
        first, second = rig.have_keys()[:2]
        self.assertEqual(first, [key for key, _ in wanted[:CAP["haveKeys"]]])
        self.assertEqual(second, [wanted[0][0]] + [key for key, _ in wanted[CAP["haveKeys"]:]])
        self.assertTrue(all(len(keys) <= CAP["haveKeys"] for keys in rig.have_keys()))

    def test_covers_first_then_alternating_by_list_position(self):
        rig = Rig(self).connect().enter()
        wanted_covers, wanted_icons = covers(3), icons(3)
        rig.want("icon", wanted_icons)
        rig.want("cover", wanted_covers)
        rig.run(until=lambda r: settled("cover", wanted_covers)(r) and settled("icon", wanted_icons)(r))
        self.assertEqual([r["media"] for r in rig.media_records("have")], ["cover", "icon"])
        self.assertEqual([r["key"] for r in rig.media_records("begin")],
                         ["cov00", "ico00", "cov01", "ico01", "cov02", "ico02"])
        self.assertEqual(len(rig.media_events("media-ready")), 6)
        self.assertEqual(rig.media_events("media-error"), [])

    def test_upload_lines_and_payload(self):
        rig = Rig(self).connect().enter()
        cover = ("jpeg0123456789abcdef0123", payload("big", CAP["cover"]["maxBytes"]))
        rig.want("cover", [cover])
        rig.run(until=settled("cover", [cover]))
        data = rig.media_records("data")
        self.assertEqual([r["offset"] for r in data], list(range(0, len(cover[1]), CAP["chunkBytes"])))
        self.assertTrue(all(r["bytes"] <= device.DeviceBridge.READ_LIMIT for r in rig.records("media")))
        self.assertTrue(all(r["id"] == 1 for r in rig.records("media")))
        store = rig.knob.media.stores["cover"]
        slot = store.slots[store.find(cover[0])]
        self.assertEqual(bytes(slot.data[:slot.bytes]), cover[1])
        ready, = rig.media_events("media-ready")
        self.assertEqual((ready["media"], ready["key"], ready["hit"]), ("cover", cover[0], False))

    def test_begin_hit_skips_the_transfer(self):
        rig = Rig(self).connect().enter()
        wanted = covers(1)
        rig.want("cover", wanted)
        rig.run(until=settled("cover", wanted))
        rig.bridge._media_kinds["cover"].mirror.clear()  # the host lost track; the knob did not
        rig.bridge._media_kinds["cover"].known.clear()
        rig.want("cover", [])
        rig.run(seconds=0.1)
        rig.knob.replies.append({"mediaAck": {"id": 1, "op": "have", "kind": "cover", "have": [False]}})
        rig.want("cover", wanted)
        rig.run(until=lambda r: len(r.media_events("media-ready")) == 2)
        self.assertEqual(rig.media_events("media-ready")[-1]["hit"], True)
        self.assertEqual(len(rig.media_records("begin")), 2)
        self.assertEqual(len(rig.media_records("commit")), 1, "a hit needs no transfer and no commit")

    def test_frame_is_written_before_the_media_lines_of_its_selection(self):
        rig = Rig(self).connect().enter(frame(icon_key="ico00"))
        wanted = icons(4)
        rig.show(frame(icon_key="ico00"))
        rig.want("icon", wanted)
        rig.run(until=settled("icon", wanted))
        for position in (2, 3, 1):  # each selection change: the frame, then its wanted list
            order = wanted[position:] + wanted[:position]
            mark = len(rig.recorder.records)
            rig.show(frame(icon_key=order[0][0], index=position))
            rig.want("icon", order)
            rig.run(seconds=0.2)
            new = rig.recorder.records[mark:]
            kinds = [r["kind"] for r in new]
            self.assertEqual(kinds[:2], ["frame", "media"], "the frame, then the probe for its new index 0")
            self.assertEqual(json.loads(new[0]["line"])["frame"]["iconKey"], order[0][0])
            self.assertEqual(json.loads(new[1]["line"])["media"]["keys"], [order[0][0]])
        new = ("ico99", payload("ico99", presentation.ICON_BYTES))
        rig.show(frame(icon_key=new[0]))
        rig.want("icon", [new] + wanted)
        rig.run(until=settled("icon", [new]))
        named = next(r for r in rig.records("frame") if json.loads(r["line"])["frame"].get("iconKey") == new[0])
        first_media = next(r for r in rig.records("media") if r.get("key") == new[0]
                           or (r["op"] == "have" and new[0] in json.loads(r["line"])["media"]["keys"]))
        self.assertLess(named["n"], first_media["n"])
        self.assertEqual(rig.knob.media.stores["icon"].displayed,
                         rig.knob.media.stores["icon"].find(new[0]), "adopted at its commit")

    def test_new_missing_index0_preempts_an_upload_after_the_current_line(self):
        rig = Rig(self).connect().enter()
        present, big = covers(1)[0], ("big00", payload("big", CAP["cover"]["maxBytes"]))
        rig.want("cover", [present])
        rig.run(until=settled("cover", [present]))
        rig.want("cover", [present, big])  # a prefetch, 16 data lines
        rig.run(until=lambda r: len(r.media_records("data", "big00")) >= 3)
        new = ("new00", payload("new", 5000))
        mark = len(rig.records("media"))
        rig.show(frame(art_key=new[0], layout="nowPlaying"))
        rig.want("cover", [new, present, big])
        rig.run(until=settled("cover", [new, present, big]))
        tail = [(r["op"], r.get("key"), r.get("offset")) for r in rig.records("media")][mark:]
        self.assertEqual(tail[0][0], "have", "the probe for the new index 0")
        self.assertEqual(tail[1], ("begin", "new00", None), "then its fresh begin, before any more big00 data")
        resumed = tail.index(("begin", "big00", None))
        self.assertEqual(tail[resumed + 1], ("data", "big00", 0), "the old upload restarts from a fresh begin")
        self.assertEqual(rig.media_events("media-error"), [])

    def test_upload_leaving_the_list_is_abandoned(self):
        rig = Rig(self).connect().enter()
        big = ("big00", payload("big", CAP["cover"]["maxBytes"]))
        rig.want("cover", [big])
        rig.run(until=lambda r: len(r.media_records("data", "big00")) >= 2)
        rig.want("cover", [])
        rig.run(seconds=0.3)
        self.assertLessEqual(len(rig.media_records("data", "big00")), 3, "at most the current line")
        self.assertIsNone(rig.bridge._media_upload)
        self.assertEqual(rig.media_events("media-error"), [])


class MirrorTests(unittest.TestCase):
    """The mirror follows the knob's LRU store (section 4.4): it never lists a key the knob evicted,
    so prefetch keeps working when pages are revisited, and `present` never exceeds the store."""

    def assert_mirror_held(self, rig):
        bridge = rig.bridge
        for kind, state in bridge._media_kinds.items():
            self.assertLessEqual(len(state.mirror), CAP[kind]["entries"] - 3, "present never exceeds the store")
            if bridge._media_wait is None:  # no reply the engine still waits for
                store = rig.knob.media.stores[kind]
                held = {slot.key for slot in store.slots if slot.valid}
                self.assertLessEqual(set(state.mirror), held, f"{kind}: the mirror lists an evicted key")

    def test_revisited_pages_are_uploaded_again_where_the_knob_evicted(self):
        rig = Rig(self).connect().enter()
        cover_pages = [covers(20, size=3000, prefix="a"), covers(20, size=3000, prefix="b")]
        icon_pages = [icons(44, prefix="i"), icons(44, prefix="j")]
        for number in (0, 1, 0):
            page, icon_page = cover_pages[number], icon_pages[number]
            rig.show(frame(art_key=page[0][0], icon_key=icon_page[0][0]))
            rig.want("cover", page)
            rig.want("icon", icon_page)
            rig.run(until=lambda r: settled("cover", page)(r) and settled("icon", icon_page)(r),
                    driver=self.assert_mirror_held)
            self.assert_mirror_held(rig)
            status = rig.bridge.media_status()
            self.assertEqual((status["cover"]["wanted"], status["icon"]["wanted"]), (20, 44))
            self.assertLessEqual(status["cover"]["present"], CAP["cover"]["entries"])
            self.assertLessEqual(status["icon"]["present"], CAP["icon"]["entries"])
        for kind, prefix, size in (("cover", "a", 20), ("icon", "i", 44)):
            begins = [r["key"] for r in rig.media_records("begin") if r["media"] == kind and r["key"][0] == prefix]
            self.assertGreater(len(begins), size, f"{kind}: the evicted part of the first page went again")
        self.assertEqual(rig.media_events("media-error"), [])

    def test_the_mirror_never_lists_an_evicted_key_under_losses(self):
        # Random selection moves (a frame naming the new index 0 of both kinds, then the lists),
        # new controls, lines lost on the wire and replies lost after the knob handled the line.
        checked = evictions = 0
        for seed in range(3):
            rng, loss = random.Random(seed), random.Random(100 + seed)
            rig = Rig(self).connect().enter()
            knob = rig.knob
            write, handle = knob.write, knob._media

            def lossy_write(data, write=write, loss=loss):
                return len(data) if data.startswith(b'{"media"') and loss.random() < 0.01 else write(data)

            def lossy_media(value, record, handle=handle, loss=loss, knob=knob):
                if loss.random() < 0.01:
                    knob.replies.append(None)
                return handle(value, record)
            knob.write, knob._media = lossy_write, lossy_media
            cover_pool, icon_pool = covers(60, size=1500, prefix="c"), icons(110, prefix="i")

            def check(r):
                nonlocal checked
                if r.bridge._media_wait is None:  # no reply still on its way
                    checked += 1
                    for kind, state in r.bridge._media_kinds.items():
                        store = r.knob.media.stores[kind]
                        held = {slot.key for slot in store.slots if slot.valid}
                        self.assertLessEqual(set(state.mirror), held, f"seed {seed} {kind}")
            for _move in range(40):
                start_c, start_i = rng.randrange(60), rng.randrange(110)
                page_c = [cover_pool[(start_c + k) % 60] for k in range(rng.randint(1, 20))]
                page_i = [icon_pool[(start_i + k) % 110] for k in range(rng.randint(1, 44))]
                rng.shuffle(page_c)
                rng.shuffle(page_i)
                shown = frame(art_key=page_c[0][0], icon_key=page_i[0][0])
                if rng.random() < 0.1:
                    rig.enter(shown)
                rig.show(shown)
                rig.want("cover", page_c)
                rig.want("icon", page_i)
                rig.run(seconds=rng.choice([0.01, 0.05, 0.2, 1.0, 3.5]), driver=check)
            evictions += knob.media.evictions
        self.assertGreater(checked, 1000)
        self.assertGreater(evictions, 100, "the stores were under pressure")

    def evict_and_revisit(self, middle):
        """Page a (20 covers) uploaded, `middle`, page b uploaded (the knob evicts most of a),
        page a again; the mirror is checked after every pass."""
        rig = Rig(self).connect().enter()
        a, b = covers(20, size=1500, prefix="a"), covers(20, size=1500, prefix="b")
        rig.want("cover", a)
        rig.run(until=settled("cover", a), driver=self.assert_mirror_held)
        middle(rig, a)
        for page in (b, a):
            rig.want("cover", page)
            rig.run(until=settled("cover", page), driver=self.assert_mirror_held)
        return rig

    def test_frame_adoption_counts_as_a_touch(self):
        def shown_without_a_probe(rig, a):  # the LCD adopts (touches) keys the host never probes
            for key, _payload in a[1:8]:
                rig.show(frame(art_key=key))
                rig.run(seconds=0.05, driver=self.assert_mirror_held)
        self.evict_and_revisit(shown_without_a_probe)

    def test_a_timed_out_have_counts_as_touches(self):
        def lost_have_replies(rig, a):  # the knob touches each new index 0; the replies are lost
            for position in range(1, 8):
                rig.knob.replies.append(None)
                rig.want("cover", a[position:] + a[:position])
                rig.run(until=lambda r, n=position: len(r.media_events("media-error")) == n,
                        driver=self.assert_mirror_held)
                rig.run(seconds=GRACE, driver=self.assert_mirror_held)
        rig = self.evict_and_revisit(lost_have_replies)
        self.assertEqual({e["op"] for e in rig.media_events("media-error")}, {"have"})

    def test_a_confirmation_counts_from_when_its_line_was_written(self):
        def frames_while_a_have_is_answered(rig, a):  # adoptions after the knob touched a19
            rig.knob.hold = True
            rig.want("cover", [a[19]] + a[:19])
            rig.run(until=lambda r: r.knob.held, driver=self.assert_mirror_held)
            rig.knob.hold = False
            for key, _payload in a[1:8]:
                rig.show(frame(art_key=key))
                rig.run(seconds=0.05, driver=self.assert_mirror_held)
            rig.knob.release_held()
            rig.run(seconds=0.2, driver=self.assert_mirror_held)
        self.evict_and_revisit(frames_while_a_have_is_answered)

    def test_touches_while_the_first_have_is_out_still_count(self):
        # A previous session's covers fill the knob. The connection's first `have` is answered
        # late while frames adopt four other keys, touches the knob makes after the have's: they
        # are recorded while the mirror is still empty and must still count against its answers.
        rig = Rig(self).connect().enter()
        old = covers(24, size=1500, prefix="p")
        for key, data in old:
            preload(rig.knob, "cover", key, data)
        rig.knob.hold = True
        rig.want("cover", old[:20])
        rig.run(until=lambda r: r.knob.held)
        rig.knob.hold = False
        for key, _payload in old[20:]:
            rig.show(frame(art_key=key, layout="nowPlaying"))
            rig.run(seconds=0.02, driver=self.assert_mirror_held)
        rig.knob.release_held()
        rig.run(seconds=0.2, driver=self.assert_mirror_held)
        new = covers(2, size=1500, prefix="n")
        rig.want("cover", [new[0]] + old[1:20])  # n00 takes the free slot
        rig.run(until=settled("cover", [new[0]]), driver=self.assert_mirror_held)
        rig.want("cover", [new[0], new[1]] + old[1:19])  # n01's begin evicts the knob's least recent key
        rig.run(until=lambda r: r.media_records("data", "n01"), driver=self.assert_mirror_held)
        final = [new[0]] + old[1:19] + [old[0]]  # n01 is dropped; p00 is wanted again as a prefetch
        rig.want("cover", final)
        rig.run(until=settled("cover", final), driver=self.assert_mirror_held)
        self.assertGreaterEqual(rig.knob.media.evictions, 1, "the store was full")
        self.assertTrue(rig.all_on_knob("cover", final))
        self.assertEqual(rig.media_events("media-error"), [])

    def test_a_have_that_finds_a_listed_key_missing_rechecks_the_list(self):
        rig = Rig(self).connect().enter()
        a, b, c = covers(3)
        rig.want("cover", [a, b, c])
        rig.run(until=settled("cover", [a, b, c]))
        store = rig.knob.media.stores["cover"]
        for key in (a[0], c[0]):  # evicted behind the host's back (touches it could not see)
            store.slots[store.find(key)].valid = False
        rig.want("cover", [c, a, b])  # a new index 0: probed
        rig.run(until=settled("cover", [a, b, c]))
        self.assertEqual(rig.have_keys()[1:], [[c[0]], [c[0], a[0], b[0]]], "c missing: the whole list re-checked")
        self.assertEqual([r["key"] for r in rig.media_records("begin")][3:], [c[0], a[0]])
        self.assertEqual(list(rig.bridge._media_kinds["cover"].mirror), [b[0], c[0], a[0]])
        self.assertEqual(rig.media_events("media-error"), [])


class RetryTests(unittest.TestCase):
    """Section 9: retry once after 1.0 s, then the key fails for the connection."""

    def test_error_retries_once_after_a_second_then_the_key_fails(self):
        rig = Rig(self).connect().enter()
        bad, good = covers(2)
        rig.knob.fail[("commit", bad[0])] = "Media decode failed"
        rig.want("cover", [bad, good])
        rig.run(until=lambda r: r.media_events("media-error"))
        first, = rig.media_events("media-error")
        failed_at = rig.clock()
        self.assertEqual((first["media"], first["key"], first["op"], first["error"], first["retrying"], first["failed"]),
                         ("cover", bad[0], "commit", "Media decode failed", True, False))
        rig.run(until=lambda r: len(r.media_records("begin", bad[0])) == 2)
        self.assertGreaterEqual(rig.clock() - failed_at, presentation.MEDIA_RETRY_SECONDS)
        self.assertTrue(rig.on_knob("cover", good[0]), "other keys continue meanwhile")
        rig.run(until=lambda r: len(r.media_events("media-error")) == 2)
        second = rig.media_events("media-error")[-1]
        self.assertEqual((second["retrying"], second["failed"]), (False, True))
        rig.run(seconds=4.0)
        self.assertEqual(len(rig.media_records("begin", bad[0])), 2, "not retried again in this connection")
        status = rig.bridge.media_status()["cover"]
        self.assertEqual((status["failedKeys"], status["errors"], status["lastError"], status["uploads"]),
                         ([bad[0]], 2, "Media decode failed", 1))
        self.assertEqual(rig.bridge.ready_id, 1)
        self.assertNotIn("error", rig.kinds())
        # It drops out of the list and re-enters: tried again.
        del rig.knob.fail[("commit", bad[0])]
        rig.want("cover", [good])
        rig.run(seconds=0.2)
        rig.want("cover", [bad, good])
        rig.run(until=settled("cover", [bad, good]))
        self.assertEqual(rig.bridge.media_status()["cover"]["failedKeys"], [])

    def test_timeout_is_a_failure_and_a_late_reply_is_harmless(self):
        rig = Rig(self).connect().enter()
        wanted = icons(1)
        rig.want("icon", wanted)
        rig.run(until=lambda r: r.media_records("begin"))
        rig.knob.hold = True
        rig.run(until=lambda r: r.media_events("media-error"))
        event, = rig.media_events("media-error")
        self.assertEqual((event["error"], event["op"], event["retrying"]), ("timeout", "data", True))
        rig.knob.hold = False
        rig.knob.release_held()  # the reply arrives after all
        rig.run(until=settled("icon", wanted))
        self.assertEqual(len(rig.media_events("media-error")), 1)
        self.assertNotIn("error", rig.kinds())
        self.assertEqual(rig.bridge.media_status()["icon"]["uploads"], 1)

    def test_failed_keys_are_retried_after_a_reconnect(self):
        rig = Rig(self).connect().enter()
        bad = covers(1)
        rig.knob.fail[("begin", bad[0][0])] = "Media unavailable"
        rig.want("cover", bad)
        rig.run(until=lambda r: len(r.media_events("media-error")) == 2)
        self.assertEqual(rig.bridge.media_status()["cover"]["failedKeys"], [bad[0][0]])
        rig.bridge._disconnect()
        self.assertIsNone(rig.bridge.media_capability)
        rig.want("cover", bad)
        self.assertTrue(rig.bridge.commands.empty(), "a no-op while disconnected")
        rig.knob.fail.clear()
        rig.connect().enter()
        self.assertEqual(rig.bridge.media_status()["cover"]["failedKeys"], [])
        rig.want("cover", bad)  # the runtime hands its lists over again after `connected`
        rig.run(until=settled("cover", bad))
        self.assertEqual(rig.have_keys()[-1], [bad[0][0]], "the mirror restarts empty: probed again")


class LostLineTests(unittest.TestCase):
    """A line with no reply at all (sections 4 and 9): replies carry no sequence number and a
    retry repeats its line's id/op/kind/key, so no media line may compete with a timed-out one
    until it is answered or its grace has passed; every reply then answers the line it belongs to."""

    def test_a_lost_begin_is_retried_once_and_the_retry_uploads(self):
        rig = Rig(self).connect().enter()
        wanted = covers(1)
        rig.knob.lose.append(lambda data: b'"op":"begin"' in data)
        rig.want("cover", wanted)
        rig.run(until=settled("cover", wanted))
        (lost_at, _line), = rig.knob.lost
        errors = rig.media_events("media-error")
        self.assertEqual([(e["key"], e["op"], e["error"], e["retrying"], e["failed"]) for e in errors],
                         [("cov00", "begin", "timeout", True, False)])
        retry, = rig.media_records("begin")  # the lost one never reached the knob
        self.assertGreaterEqual(at(retry) - lost_at, GRACE - 0.001, "nothing competes with the lost line")
        self.assertLess(at(retry) - lost_at, GRACE + 0.2)
        status = rig.bridge.media_status()["cover"]
        self.assertEqual((status["failedKeys"], status["uploads"], status["errors"]), ([], 1, 1))
        self.assertEqual(len(rig.media_events("media-ready")), 1)

    def test_a_lost_have_does_not_take_the_next_haves_answers(self):
        rig = Rig(self).connect().enter()
        a, b, c = covers(3)
        preload(rig.knob, "cover", *c)  # the knob already holds c
        rig.knob.lose.append(lambda data: b'"op":"have"' in data)
        rig.want("cover", [a, b])
        rig.run(until=lambda r: r.knob.lost)
        rig.run(seconds=0.5)
        rig.want("cover", [b, c])  # the list changes while the lost `have` is outstanding
        rig.run(until=settled("cover", [b, c]))
        state = rig.bridge._media_kinds["cover"]
        self.assertEqual(list(state.mirror), [c[0], b[0]], "what the knob holds, in its touch order")
        self.assertEqual(rig.have_keys(), [[b[0], c[0]]])
        self.assertEqual([r["key"] for r in rig.media_records("begin")], [b[0]], "b is uploaded, c is not")
        errors = rig.media_events("media-error")
        self.assertEqual([(e["op"], e["error"]) for e in errors], [("have", "timeout")], "one timeout, not two")
        self.assertEqual(rig.bridge.media_status()["cover"]["hits"], 1)

    def test_a_parse_reply_with_only_an_id_answers_the_live_line(self):
        rig = Rig(self).connect().enter()
        wanted = covers(1)
        rig.knob.lose.append(lambda data: b'"op":"begin"' in data)  # the first begin never arrives
        rig.knob.replies.extend([PASS, {"mediaAck": {"op": "parse", "error": "parse", "id": 1}}])
        rig.want("cover", wanted)
        rig.run(until=lambda r: len(r.media_events("media-error")) == 2)
        failed_at = rig.clock()
        first, second = rig.media_events("media-error")
        self.assertEqual((first["error"], first["retrying"]), ("timeout", True))
        self.assertEqual((second["op"], second["error"], second["retrying"], second["failed"]),
                         ("begin", "parse", False, True), "the retry's own parse reply fails it")
        retry, = rig.media_records("begin")
        self.assertLess(failed_at - at(retry), 0.2, "at once, not after another ack timeout")
        self.assertEqual(rig.bridge.media_status()["cover"]["failedKeys"], ["cov00"])
        self.assertNotIn("error", rig.kinds())

    def test_a_late_reply_retires_the_timed_out_line_and_media_resumes(self):
        rig = Rig(self).connect().enter()
        wanted = covers(2)
        rig.knob.replies.extend([PASS, None])  # the knob handles cov00's begin; its reply is lost
        rig.want("cover", wanted)
        rig.run(until=lambda r: r.media_events("media-error"))
        begin, = rig.media_records("begin")
        rig.run(seconds=0.5)
        self.assertEqual(len(rig.media_records()), 2, "not even cov01 while the begin may still be answered")
        # A parse reply carrying only the id answers the timed-out begin (the only line it can answer).
        rig.knob.inject({"mediaAck": {"op": "parse", "error": "parse", "id": 1}})
        injected_at = rig.clock()
        rig.run(until=settled("cover", wanted))
        following = rig.media_records()[2]
        self.assertEqual((following["op"], following["key"]), ("begin", "cov01"))
        self.assertLess(at(following) - injected_at, 0.1, "resumed as soon as the reply retired the line")
        self.assertLess(at(following) - at(begin), GRACE)
        retry = rig.media_records("begin", "cov00")[1]
        self.assertGreaterEqual(at(retry) - at(begin), presentation.MEDIA_ACK_TIMEOUT_SECONDS
                                + presentation.MEDIA_RETRY_SECONDS - 0.001)
        self.assertEqual(len(rig.media_events("media-error")), 1)
        status = rig.bridge.media_status()["cover"]
        self.assertEqual((status["failedKeys"], status["uploads"]), ([], 2))

    def test_a_late_ready_reply_is_not_reported_twice(self):
        rig = Rig(self).connect().enter()
        wanted = icons(1)
        rig.want("icon", wanted)
        rig.run(until=settled("icon", wanted))
        bridge, key = rig.bridge, wanted[0][0]
        state = bridge._media_kinds["icon"]
        before = (state.uploads, state.hits, len(rig.media_events("media-ready")))
        for op in ("commit", "begin"):  # replies to lines no longer live (timed out or cancelled)
            line = {"seq": 10 ** 6, "id": 1, "op": op, "kind": "icon", "key": key, "keys": None, "expected": None,
                    "bytes": presentation.ICON_BYTES, "upload": None, "tick": bridge._media_next_tick()}
            bridge._media_answered(line, {"id": 1, "op": op, "kind": "icon", "key": key,
                                          "offset": presentation.ICON_BYTES})
        rig.collect()
        self.assertEqual((state.uploads, state.hits, len(rig.media_events("media-ready"))), before)
        self.assertIn(key, state.mirror)


class ControlBindingTests(unittest.TestCase):
    def test_a_control_change_cancels_the_upload_without_a_failure(self):
        rig = Rig(self).connect().enter()
        big = ("big00", payload("big", CAP["cover"]["maxBytes"]))
        rig.want("cover", [big])
        rig.run(until=lambda r: len(r.media_records("data", "big00")) >= 3)
        rig.enter()
        self.assertEqual(rig.bridge.ready_id, 2)
        before = len(rig.records("media"))
        rig.run(until=settled("cover", [big]))
        after = rig.records("media")[before:]
        self.assertEqual((after[0]["op"], after[0]["id"]), ("begin", 2), "a fresh begin under the new id")
        self.assertEqual(after[1]["offset"], 0)
        self.assertTrue(all(r["id"] == 2 for r in after))
        self.assertEqual(rig.media_events("media-error"), [])

    def test_stale_media_control_is_not_a_failure(self):
        rig = Rig(self).connect().enter()
        wanted = icons(2)
        stale = {"mediaAck": {"id": 1, "op": "have", "kind": "icon", "error": "Stale media control"}}
        rig.knob.replies.append(stale)  # the knob no longer holds control 1 (its release is on the way)
        rig.want("icon", wanted)
        rig.run(until=lambda r: r.knob.media_acks)
        stale_at = rig.clock()
        rig.run(until=settled("icon", wanted))
        probes = rig.media_records("have")
        self.assertEqual(len(probes), 2, "probed again")
        self.assertGreaterEqual(probes[1]["t"] + 1000.0 - stale_at, presentation.MEDIA_RETRY_SECONDS - 0.06,
                                "paused, not retried at once")
        self.assertEqual(rig.media_events("media-error"), [])
        self.assertEqual(rig.bridge.media_status()["icon"]["errors"], 0)

    def test_stale_reply_for_an_older_control_just_reevaluates(self):
        rig = Rig(self).connect().enter()
        wanted = icons(2)
        rig.knob.hold = True
        rig.want("icon", wanted)
        rig.run(until=lambda r: r.knob.held)
        rig.knob.hold = False
        rig.enter()  # a new control while the have of control 1 is still unanswered
        rig.knob.held = [{"mediaAck": {"id": 1, "op": "have", "kind": "icon", "error": "Stale media control"}}]
        rig.knob.release_held()
        mark = rig.clock()
        rig.run(until=settled("icon", wanted))
        self.assertLess(rig.clock() - mark, 0.5, "no pause: the engine re-evaluates with the new id")
        self.assertEqual([r["id"] for r in rig.media_records("have")], [1, 2])
        self.assertEqual({r["id"] for r in rig.records("media")[1:]}, {2})
        self.assertEqual(rig.media_events("media-error"), [])

    def test_a_release_stops_media(self):
        rig = Rig(self).connect().enter()
        rig.knob.inject({"released": True, "reason": "lease-expired"})
        rig.step()
        self.assertIn("released", rig.kinds())
        rig.want("icon", icons(2))
        rig.run(seconds=0.5)
        self.assertEqual(rig.records("media"), [], "no media line without a ready control")


class ParseMappingTests(unittest.TestCase):
    """Section 4.3: parse/oversize replies to a media line are media-errors, never a disconnect."""

    def begin_answered_with(self, reply):
        rig = Rig(self).connect().enter()
        wanted = covers(1)
        rig.knob.replies.extend([PASS, reply])  # the have is answered, the begin gets `reply`
        rig.want("cover", wanted)
        rig.run(until=lambda r: r.media_events("media-error"))
        event, = rig.media_events("media-error")
        self.assertEqual((event["key"], event["op"], event["error"], event["retrying"]), ("cov00", "begin", "parse", True))
        self.assertIsNotNone(rig.bridge.serial)
        self.assertNotIn("error", rig.kinds())
        rig.run(until=settled("cover", wanted))
        self.assertEqual(rig.bridge.ready_id, 1)
        return rig

    def test_media_parse_reply(self):
        self.begin_answered_with({"mediaAck": {"op": "parse", "error": "parse", "id": 1, "key": "cov00"}})
        self.begin_answered_with({"mediaAck": {"op": "parse", "error": "parse"}})

    def test_bare_parse_and_oversize_errors_while_a_media_line_is_outstanding(self):
        for reply in ({"error": "JSON parse error", "msg": "InvalidInput"}, {"error": "Command too large"}):
            rig = self.begin_answered_with(reply)
            # A bare error may answer an earlier line: the begin stays answerable for its grace.
            first, retry = rig.media_records("begin")
            self.assertGreaterEqual(at(retry) - at(first), GRACE - 0.001)
            self.assertLess(at(retry) - at(first), GRACE + 0.2)
        with self.assertRaises(OSError):  # nothing outstanding: as fatal as before
            rig.bridge._consume({"error": "JSON parse error"})

    def late_have_after_a_damaged_frame(self, rig, a):
        """A frame damaged on the wire, then have [a]; the knob answers late, in line order."""
        rig.knob.damage.append((lambda data: data.startswith(b'{"frame"'), lambda data: b"#" + data[1:]))
        rig.knob.hold_all = True
        rig.show(frame(art_key=a[0], layout="nowPlaying"))
        rig.want("cover", [a])
        rig.run(until=lambda r: r.media_records("have"))
        self.assertEqual(len(rig.knob.damaged), 1)
        self.assertEqual(rig.knob.held[0], {"error": "JSON parse error"}, "the frame's reply comes first")

    def assert_answers_went_to_their_lines(self, rig, a, b):
        rig.want("cover", [b])  # the selection moves on before the have's own reply
        rig.run(seconds=0.3)
        self.assertEqual(len(rig.media_records()), 1, "no media line competes with the have")
        rig.knob.hold_all = False
        rig.knob.release_held()  # the have's own reply: [true]
        rig.run(until=settled("cover", [b]))
        state = rig.bridge._media_kinds["cover"]
        held = {slot.key for slot in rig.knob.media.stores["cover"].slots if slot.valid}
        self.assertLessEqual(set(state.mirror), held, "the mirror lists only what the knob holds")
        self.assertEqual(list(state.mirror), [a[0], b[0]])
        self.assertEqual(rig.have_keys(), [[a[0]], [b[0]]])
        self.assertEqual([r["key"] for r in rig.media_records("begin")], [b[0]], "b is uploaded")
        self.assertIsNotNone(rig.bridge.serial)
        self.assertNotIn("error", rig.kinds())

    def test_a_bare_error_for_an_earlier_line_does_not_retire_the_have(self):
        rig = Rig(self).connect().enter()
        a, b = covers(2)
        preload(rig.knob, "cover", *a)  # the knob holds a, not b
        self.late_have_after_a_damaged_frame(rig, a)
        rig.knob.release_held(1)  # the frame's bare error, while the have is out
        rig.step()
        event, = rig.media_events("media-error")
        self.assertEqual((event["op"], event["error"], event["retrying"]), ("have", "parse", False))
        self.assert_answers_went_to_their_lines(rig, a, b)
        self.assertEqual(len(rig.media_events("media-error")), 1)

    def test_a_bare_error_does_not_end_a_timed_out_lines_grace(self):
        rig = Rig(self).connect().enter()
        a, b = covers(2)
        preload(rig.knob, "cover", *a)
        self.late_have_after_a_damaged_frame(rig, a)
        rig.run(until=lambda r: r.media_events("media-error"))  # later than the ack timeout
        event, = rig.media_events("media-error")
        self.assertEqual((event["op"], event["error"]), ("have", "timeout"))
        rig.knob.release_held(1)  # the frame's bare error, within the have's grace
        with self.assertLogs("control_center.device", "INFO") as logs:
            rig.step()
        self.assertEqual(len(rig.media_events("media-error")), 1, "the have is not reported again")
        self.assertTrue(any("Bare JSON parse error reply consumed" in line for line in logs.output),
                        "consumed, but never invisible")
        self.assert_answers_went_to_their_lines(rig, a, b)
        self.assertEqual(len(rig.media_events("media-error")), 1)

    def test_other_errors_stay_fatal(self):
        rig = Rig(self).connect().enter()
        rig.knob.hold = True
        rig.want("cover", covers(1))
        rig.run(until=lambda r: r.records("media"))
        with self.assertRaises(OSError):
            rig.bridge._consume({"error": "Invalid control frame"})

    def test_a_late_parse_reply_after_a_timeout_is_not_fatal(self):
        rig = Rig(self).connect().enter()
        rig.knob.hold = True
        rig.want("cover", covers(1))
        rig.run(until=lambda r: r.media_events("media-error"))
        rig.knob.held = [{"error": "JSON parse error", "msg": "InvalidInput"}]
        rig.knob.hold = False
        rig.knob.release_held()
        rig.step()
        self.assertIsNotNone(rig.bridge.serial)
        self.assertNotIn("error", rig.kinds())


class WantedListTests(unittest.TestCase):
    def test_entries_minus_four_cap_duplicates_and_invalid_items(self):
        rig = Rig(self).connect().enter()
        with self.assertLogs("control_center.device", "INFO") as logs:
            rig.want("cover", covers(30))
            rig.want("icon", icons(50))
        self.assertTrue(any("capped at 20" in line and "10 dropped" in line for line in logs.output))
        self.assertTrue(any("capped at 44" in line and "6 dropped" in line for line in logs.output))
        rig.run(seconds=0.05)
        status = rig.bridge.media_status()
        self.assertEqual((status["cover"]["wanted"], status["cover"]["dropped"]), (20, 10))
        self.assertEqual((status["icon"]["wanted"], status["icon"]["dropped"]), (44, 6))
        good = covers(2)
        items = [good[0], good[0], ("bad key", b"x"), ("toolong" * 4, b"x"), ("empty", b""),
                 ("huge", bytes(CAP["cover"]["maxBytes"] + 1)), ("text", "not bytes"), ("short",), None,
                 ("ba", bytearray(b"ok")), good[1]]
        with self.assertLogs("control_center.device", "WARNING") as logs:
            rig.want("cover", items)
        self.assertTrue(any("7 invalid" in line for line in logs.output))
        rig.run(seconds=0.05)
        self.assertEqual([key for key, _ in rig.bridge._media_kinds["cover"].wanted], ["cov00", "ba", "cov01"])
        with self.assertLogs("control_center.device", "WARNING"):
            rig.want("icon", [("ico", b"x" * 100)])
        with self.assertRaises(ValueError):
            rig.want("art", [])

    def test_the_cap_is_logged_once_per_change_not_per_detent(self):
        """Every Windows detent reorders the icon list (by distance); with more than 44 icons each
        reorder is a new list over the cap. app.log gets one line per change of the dropped count,
        not one per detent; status.json keeps the count."""
        rig = Rig(self).connect().enter()
        wanted = icons(50)
        with self.assertLogs("control_center.device", "INFO") as logs:
            for shift in range(6):                   # the first list and five detents
                rig.want("icon", wanted[shift:] + wanted[:shift])
        capped = [line for line in logs.output if "Media icon list capped at 44 item(s); 6 dropped" in line]
        self.assertEqual(len(capped), 1, logs.output)
        rig.run(seconds=0.05)
        self.assertEqual(rig.bridge.media_status()["icon"]["dropped"], 6)
        with self.assertNoLogs("control_center.device", "INFO"):
            rig.want("icon", wanted[7:] + wanted[:7])
        with self.assertLogs("control_center.device", "INFO") as logs:
            rig.want("icon", wanted[:47])            # the count changed: logged again
        self.assertTrue(any("capped at 44" in line and "3 dropped" in line for line in logs.output))
        with self.assertNoLogs("control_center.device", "INFO"):
            rig.want("icon", wanted[:40])            # under the cap: nothing to log
        with self.assertLogs("control_center.device", "INFO") as logs:
            rig.want("icon", wanted)                 # over it again
        self.assertTrue(any("6 dropped" in line for line in logs.output))
        with self.assertLogs("control_center.device", "WARNING") as logs:
            rig.want("cover", [("bad key", b"x")] + covers(2))
        with self.assertNoLogs("control_center.device", "WARNING"):
            rig.want("cover", covers(2) + [("bad key", b"x")])
        self.assertEqual(sum("1 invalid" in line for line in logs.output), 1)

    def test_set_media_wanted_is_queued_to_the_bridge_thread(self):
        rig = Rig(self).connect().enter()
        worker = threading.Thread(target=rig.want, args=("icon", icons(2)))
        worker.start()
        worker.join()
        self.assertEqual(rig.bridge._media_kinds["icon"].wanted, [], "applied only on the bridge thread")
        self.assertEqual(rig.bridge.commands.qsize(), 1)
        rig.step()
        self.assertEqual(len(rig.bridge._media_kinds["icon"].wanted), 2)

    def test_media_status_counters(self):
        rig = Rig(self).connect().enter()
        wanted = covers(3)
        rig.want("cover", wanted)
        rig.run(until=settled("cover", wanted))
        status = rig.bridge.media_status()
        self.assertEqual(set(status), {"cover", "icon"})
        self.assertEqual(status["cover"], {"wanted": 3, "present": 3, "uploads": 3, "hits": 0, "errors": 0,
                                           "failedKeys": [], "lastError": "", "dropped": 0})
        self.assertEqual(status["icon"]["present"], 0)
        rig.bridge._disconnect()
        self.assertEqual(rig.bridge.media_status()["cover"]["present"], 0)


class CdcModelTests(unittest.TestCase):
    """Sections 3 and 10: the unpaced stop-and-wait engine against the knob's receive queue."""

    def runtime_driver(self, wanted_covers, wanted_icons, rotate_until):
        """A Tk-poll stand-in: a ~1 KB frame every 25 ms (frame first, then changed lists) and a
        selection change (a new index 0) every 0.4 s until `rotate_until`."""
        state = {"next": None, "n": 0, "rotate": None, "shift": 0}

        def drive(rig):
            now = rig.clock()
            if state["next"] is None:
                state["next"] = state["rotate"] = now
            if now < state["next"]:
                return
            state["next"] = now + 0.025
            state["n"] += 1
            rotate = now >= state["rotate"] and now < rotate_until
            if rotate:
                state["rotate"] = now + 0.4
                state["shift"] += 1
            shift = state["shift"] % len(wanted_covers)
            order = wanted_covers[shift:] + wanted_covers[:shift]
            icon_order = wanted_icons[shift:] + wanted_icons[:shift]
            rig.show(big_frame(state["n"], art_key=order[0][0], icon_key=icon_order[0][0]))
            if rotate or state["n"] == 1:
                rig.want("cover", order)
                rig.want("icon", icon_order)
        return drive

    def transfer(self, cdc):
        rig = Rig(self, cdc=cdc, lease=True).connect().enter()
        wanted_covers = [(f"cov{i:02d}", payload(i, random.Random(i).randint(8000, CAP["cover"]["maxBytes"])))
                         for i in range(20)]
        wanted_icons = icons(44)
        start = rig.clock()
        driver = self.runtime_driver(wanted_covers, wanted_icons, rotate_until=start + 3.0)
        mirror = rig.bridge._media_kinds

        def done(r):
            return (r.clock() > start + 3.0 and len(mirror["cover"].mirror) >= 20 and len(mirror["icon"].mirror) >= 44
                    and r.all_on_knob("cover", wanted_covers) and r.all_on_knob("icon", wanted_icons))
        rig.run(driver=driver, until=done)
        model = rig.knob.cdc
        self.assertEqual((model.dropped_bytes, model.damaged_writes), (0, 0), "never overflowed")
        self.assertLessEqual(model.high_water, BUDGET)
        self.assertGreater(len(model.stall_log), 5)
        self.assertEqual(rig.knob.refusals, [])
        self.assertEqual(rig.media_events("media-error"), [])
        self.assertEqual(rig.knob.lease_expiries, 0)
        self.assertNotIn("error", rig.kinds())
        self.assertEqual(rig.knob.whole_line_writes, rig.knob.write_calls)
        status = rig.bridge.media_status()
        self.assertEqual((status["cover"]["present"], status["icon"]["present"]), (20, 44))
        return rig

    def test_no_overflow_with_stalls_and_one_tick_drains(self):
        self.transfer(CdcModel(random_stalls={"gap": (0.05, 0.3), "duration": (0.030, 0.100), "seed": 1}))

    def test_no_overflow_with_stalls_and_ten_tick_drains(self):
        rig = self.transfer(CdcModel(active_ticks=10, random_stalls={"gap": (0.05, 0.3), "duration": (0.030, 0.100),
                                                                     "seed": 2}))
        self.assertGreater(len(rig.records("frame")), 40)

    def test_the_model_overflows_for_a_writer_without_flow_control(self):
        # Not vacuous: three data lines and two frames written during one 100 ms stall do not fit.
        rig = Rig(self, cdc=CdcModel()).connect().enter()
        knob, model = rig.knob, rig.knob.cdc
        model.stall(rig.clock(), 0.100)
        line = json.dumps({"media": {"id": 1, "op": "data", "kind": "cover", "key": "k", "offset": 0,
                                     "data": "A" * 2732}}).encode() + b"\n"
        frame_line = json.dumps({"frame": {**frame(), "id": 1}}).encode() + b"\n"
        for data in [line] * 3 + [frame_line] * 2:
            knob.write(data)
        self.assertGreater(model.dropped_bytes, 0)
        self.assertEqual(model.high_water, CAP["rxBytes"])
        rig.clock.advance(0.2)
        knob.write(frame_line)  # the next line completes the damaged one
        replies = []
        for _ in range(100):
            replies += [json.loads(x) for x in knob.read(4096).splitlines() if x]
        parse = [r["mediaAck"] for r in replies if r.get("mediaAck", {}).get("op") == "parse"]
        self.assertEqual(parse, [{"id": 1, "key": "k", "op": "parse", "error": "parse"}],
                         "the line that lost its tail fails to parse")

    def corrupted(self, how, errors=1):
        """One media line damaged on the way (section 10: recovery through the retry rule)."""
        class Corrupting(CdcModel):
            done = False
            damaged_size = None

            def receive(self, data, now):
                if not self.done and b'"op":"data"' in data and b'"key":"cov01"' in data:
                    self.done = True
                    data = {"garbled": data[:30] + data[90:], "truncated": data[:len(data) // 2],
                            "prefix": b"#" + data[1:], "lost": b"", "newline": data[:-1]}[how]
                    self.damaged_size = len(data)
                super().receive(data, now)
        rig = Rig(self, cdc=Corrupting(random_stalls={"gap": (0.2, 0.5), "duration": (0.03, 0.1), "seed": 3}),
                  lease=True).connect().enter()
        wanted = covers(3, size=12000)
        rig.want("cover", wanted)
        rig.run(until=settled("cover", wanted))
        self.assertIsNotNone(rig.knob.cdc.damaged_size, "the data line was damaged")
        media_errors = rig.media_events("media-error")
        self.assertEqual(len(media_errors), errors, how)
        if errors:
            self.assertEqual((media_errors[0]["key"], media_errors[0]["retrying"]), ("cov01", True))
            self.assertEqual(media_errors[0]["error"], "timeout" if how == "lost" else "parse")
        self.assertIsNotNone(rig.bridge.serial)
        self.assertNotIn("error", rig.kinds())
        self.assertEqual(rig.bridge.ready_id, 1)
        self.assertEqual(rig.knob.lease_expiries, 0)
        return rig

    def test_recovery_from_a_garbled_data_line(self):
        rig = self.corrupted("garbled")
        self.assertEqual(rig.knob.refusals, [])
        ack = rig.knob.media_errors[0]["ack"]
        self.assertEqual(ack, {"id": 1, "op": "parse", "error": "parse"})
        self.assertEqual(list(ack), ["op", "error", "id"], "cc_media_parse_ack's key order")

    def test_recovery_from_a_line_that_lost_its_tail(self):
        # What an overflow does: the tail and its newline are dropped, so the line is glued
        # to the next one (a heartbeat frame); it is still recognised as a media line.
        rig = self.corrupted("truncated")
        self.assertEqual(rig.knob.refusals, [])
        ack = rig.knob.media_errors[0]["ack"]
        self.assertEqual(ack, {"id": 1, "key": "cov01", "op": "parse", "error": "parse"})
        self.assertEqual(list(ack), ["op", "error", "id", "key"], "cc_media_parse_ack's key order")

    def test_recovery_from_a_line_that_lost_only_its_newline(self):
        # The firmware's deserializeJson reads a line's first JSON value and ignores the rest: a
        # data line whose newline was lost is answered normally once the next line (a heartbeat
        # frame) completes it, and that glued frame is dropped without any reply. Nothing fails:
        # no media error, no refusal, and the next heartbeat keeps the lease.
        rig = self.corrupted("newline", errors=0)
        self.assertEqual(rig.knob.refusals, [])
        self.assertEqual(rig.knob.media_errors, [])
        # Data lines differ by a few offset digits at most; a glued frame adds hundreds of bytes.
        glued = [size for _t, kind, size in rig.knob.processed
                 if kind == "media" and size > rig.knob.cdc.damaged_size + 100]
        self.assertEqual(len(glued), 1, "one media line carried the next line glued to it")
        self.assertEqual(rig.bridge.media_status()["cover"]["errors"], 0)

    def test_recovery_from_a_damaged_prefix(self):
        rig = self.corrupted("prefix")  # not recognisable as media: a bare parse error
        self.assertEqual([r["why"] for r in rig.knob.refusals], ["JSON parse error"])

    def test_recovery_from_a_lost_line(self):
        self.corrupted("lost")

    def test_lease_heartbeat_continues_during_a_long_transfer(self):
        rig = Rig(self, cdc=CdcModel(active_ticks=10, random_stalls={"gap": (0.1, 0.4), "duration": (0.03, 0.1),
                                                                     "seed": 4}),
                  lease=True).connect().enter()
        wanted = [(f"cov{i:02d}", payload(f"lease{i}", CAP["cover"]["maxBytes"])) for i in range(20)]
        start = rig.clock()
        rig.want("cover", wanted)
        rig.run(until=settled("cover", wanted))
        elapsed = rig.clock() - start
        self.assertGreater(elapsed, 3.0, "a transfer longer than the 2 s lease")
        beats = [t for t, kind, _size in rig.knob.processed if kind == "frame" and t >= start]
        gaps = [b - a for a, b in zip([start] + beats, beats + [rig.clock()])]
        self.assertLess(max(gaps), 0.8, "a heartbeat frame reaches the knob at least every 0.5 s + a stall")
        self.assertGreaterEqual(len(beats), int(elapsed / 0.5) - 1)
        self.assertEqual(rig.knob.lease_expiries, 0)
        self.assertNotIn("released", rig.kinds())
        self.assertEqual(rig.bridge.ready_id, 1)
        self.assertEqual(rig.knob.cdc.dropped_bytes, 0)


class FakeKnobFidelityTests(unittest.TestCase):
    """The FakeKnob reads lines as the cc5.3 firmware does (com_thread.cpp, cc_frame_parse.cpp,
    cc_media_store.h), so the bridge tests exercise the knob's real recovery paths."""

    def knob(self):
        clock = Clock()
        knob = FakeKnob(clock, deepcopy(CC53_CAPABILITIES), Recorder(clock), "1.0.0-cc5.3")
        knob.write(b'{"control":' + json.dumps({"id": 7, "position": 0, "frame": frame()}).encode() + b"}\n")
        self.assertEqual(self.replies(knob), [{"ready": 7, "p": 0}])
        return knob

    @staticmethod
    def replies(knob):
        raw = bytes(knob.buffer)
        del knob.buffer[:]
        return [json.loads(line) for line in raw.splitlines() if line]

    @staticmethod
    def raw_replies(knob):
        raw = bytes(knob.buffer)
        del knob.buffer[:]
        return [line for line in raw.splitlines() if line]

    def test_icon_key_counts_only_on_the_windows_layout(self):
        """cc_parse_frame keeps iconKey only on the windows layout (after the legacy mode
        derivation); elsewhere the icon frame key is "" and pins or adopts nothing."""
        knob = self.knob()
        preload(knob, "icon", "ic1", payload("ic1", presentation.ICON_BYTES), ident=7)
        store = knob.media.stores["icon"]
        cases = [({"layout": "windows"}, "ic1"), ({"layout": "nowPlaying"}, ""), ({"layout": "recent"}, ""),
                 ({"layout": "tracks"}, ""), ({"layout": None, "mode": "WINDOWS"}, "ic1"),
                 ({"layout": None, "mode": "VOLUME"}, ""), ({"layout": None, "mode": "RECENTLY ADDED"}, ""),
                 ({"layout": None, "mode": "SOMETHING ELSE"}, "")]
        for change, expected in cases:
            with self.subTest(change=change):
                value = {**frame(icon_key="ic1"), "id": 7, **change}
                if change.get("layout") is None:
                    del value["layout"]
                knob.write(json.dumps({"frame": value}).encode() + b"\n")
                self.assertEqual(self.replies(knob), [], "an accepted frame has no reply")
                self.assertEqual(store.frame_key, expected)
                self.assertEqual(store.displayed, 0 if expected else -1, "adopted only on the windows layout")
        knob.write(json.dumps({"frame": {**frame(icon_key="ic1", layout="recent"), "id": 7}}).encode() + b"\n")
        self.assertEqual(store.pinned(), set(), "a non-windows frame pins no icon slot")

    def test_only_the_first_json_value_of_a_line_is_read(self):
        """ArduinoJson's deserializeJson stops after the first value: a line glued to the next one
        (its newline lost) is handled as its first command, and the rest is dropped silently."""
        knob = self.knob()
        cover = payload("glued", 64)
        preload(knob, "cover", "cg1", cover, ident=7)
        have = {"media": {"id": 7, "op": "have", "kind": "cover", "keys": ["cg1"]}}
        glued_frame = {"frame": {**frame(art_key="cg1", layout="nowPlaying"), "id": 7}}
        knob.write(json.dumps(have).encode() + json.dumps(glued_frame).encode() + b"\n")
        self.assertEqual(self.replies(knob), [{"mediaAck": {"id": 7, "op": "have", "kind": "cover", "have": [True]}}])
        self.assertEqual(knob.media.stores["cover"].frame_key, "", "the glued frame was dropped, not applied")
        knob.write(b' \t{"capabilities":"?"}{"release":true} trailing\n')
        [reply] = self.replies(knob)
        self.assertIn("capabilities", reply)
        self.assertTrue(knob.claimed, "the glued release was dropped")
        self.assertEqual(knob.refusals, [])
        for bad in (b'[{"release":true}]\n', b'x{"release":true}\n', b'\n', b'{"release":tru\n'):
            with self.subTest(line=bad):
                knob.write(bad)
                self.assertEqual(self.replies(knob), [{"error": "JSON parse error"}])
        self.assertTrue(knob.claimed)

    def test_the_media_parse_reply_matches_the_firmware_bytes(self):
        """{"mediaAck":{"op":"parse","error":"parse","id":…,"key":…}}: cc_media_parse_ack's key
        order (media_tests.cpp parse_replies), not only the same fields."""
        knob = self.knob()
        knob.write(b'{"media":{"id":7,"op":"data","kind":"cover","key":"abc_-9","offset":0,"data":"QQ\n')
        self.assertEqual(self.raw_replies(knob),
                         [b'{"mediaAck":{"op":"parse","error":"parse","id":7,"key":"abc_-9"}}'])
        knob.write(b'{"media":{"id":7\n')
        self.assertEqual(self.raw_replies(knob), [b'{"mediaAck":{"op":"parse","error":"parse"}}'])
        knob.write(b'{"art":{"id":7,"key":"k1","op":"data"\n')   # v1 art keeps art_parse_reply's order
        self.assertEqual(self.raw_replies(knob), [b'{"artAck":{"id":7,"key":"k1","op":"parse","error":"parse"}}'])

    def test_a_release_ends_the_upload(self):
        """ARTWORK2.md 4.4: a release (like a new control) ends the upload context, so the COM
        model stops treating the knob as receiving (the 1-tick idle rule)."""
        knob = self.knob()
        data = payload("rel", 4096)
        knob.write(json.dumps({"media": {"id": 7, "op": "begin", "kind": "cover", "key": "rel1", "bytes": len(data),
                                         "crc32": zlib.crc32(data)}}).encode() + b"\n")
        self.assertEqual(self.replies(knob)[0]["mediaAck"]["offset"], 0)
        self.assertTrue(knob.media.receiving() and knob.media_receiving())
        knob.write(b'{"release":true}\n')
        self.assertEqual(self.replies(knob), [{"released": True}])
        self.assertFalse(knob.media.receiving() or knob.media_receiving())
        self.assertIsNone(knob.media.upload)
        knob.write(json.dumps({"control": {"id": 8, "position": 0, "frame": frame()}}).encode() + b"\n")
        self.replies(knob)
        knob.write(json.dumps({"media": {"id": 8, "op": "data", "kind": "cover", "key": "rel1", "offset": 0,
                                         "data": base64.b64encode(data[:2048]).decode()}}).encode() + b"\n")
        self.assertEqual(self.replies(knob)[0]["mediaAck"]["error"], "No matching media upload")


class FaultTests(unittest.TestCase):
    def test_an_engine_fault_is_presentation_only(self):
        rig = Rig(self).connect().enter()
        wanted = icons(2)
        bridge = rig.bridge
        probe_keys, success = bridge._media_probe_keys, bridge._media_success
        faults = []

        def broken_probe(state):
            if not faults:
                faults.append("step")
                raise KeyError("boom")
            return probe_keys(state)

        def broken_success(line, ack, current):
            if len(faults) == 1:
                faults.append("ack")
                raise TypeError("boom")
            return success(line, ack, current)
        bridge._media_probe_keys, bridge._media_success = broken_probe, broken_success
        with self.assertLogs("control_center.device", "WARNING") as logs:
            rig.want("icon", wanted)
            rig.run(until=settled("icon", wanted))
        self.assertEqual(faults, ["step", "ack"])
        self.assertTrue(any("Media engine fault (KeyError)" in line for line in logs.output))
        self.assertTrue(any("Media engine fault (TypeError)" in line for line in logs.output))
        self.assertNotIn("error", rig.kinds())
        self.assertEqual(bridge.ready_id, 1)


class BridgeLoopTests(unittest.TestCase):
    def test_the_worker_thread_pushes_media(self):
        rig = Rig(self).connect().enter()
        wanted = icons(3)
        worker = threading.Thread(target=rig.bridge._run, daemon=True)
        worker.start()
        try:
            rig.want("icon", wanted)
            rig.show(frame(icon_key=wanted[0][0]))
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not rig.bridge.media_status()["icon"]["uploads"] == 3:
                time.sleep(0.01)
        finally:
            rig.bridge.submit("close")
            worker.join(timeout=20)
        self.assertFalse(worker.is_alive())
        rig.collect()
        self.assertTrue(rig.all_on_knob("icon", wanted))
        self.assertIn("closed", rig.kinds())
        self.assertNotIn("error", rig.kinds())
        self.assertEqual(rig.records("release")[-1]["line"], '{"release":true}')


if __name__ == "__main__":
    unittest.main()

"""Media store parity (ARTWORK2.md sections 4.3, 4.4 and 10) on the host side.

harness/media_store_traces.json is the shared trace fixture: the firmware store
(src/cc_media_store.h, through harness/media_tests.py) and the Python reference
the FakeKnob runs (tests/tools/capture_session_frames.MediaStoreModel) must give identical
mediaAck replies and identical slot tables after every step. These tests replay every case
through the Python model and compare each `media` and `check` step exactly. A missing
fixture fails loudly ("fixture missing"); it is never skipped.

The remaining tests check the model itself against the contract text, independently of
the fixture: eviction at begin, pinning, identical retries, cancellation, `have` touches,
adoption at commit, the validation order, the base64 rule, the parse-reply prefix scan and
the cover JPEG check. No port, window or network is touched.
"""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tests" / "tools"
for _path in (str(ROOT), str(TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from control_center import presentation  # noqa: E402
import capture_session_frames as tool  # noqa: E402
from capture_session_frames import MediaStoreModel, run_media_trace  # noqa: E402

TRACES = ROOT.parent / "harness" / "media_store_traces.json"
STEPS = {"control", "release", "frame", "adopt", "media", "check"}
CHECK_PARTS = ("slots", "displayed", "clock", "receiving")
ERRORS = {"Unknown media operation", "Unknown media kind", "Media unavailable", "Stale media control",
          "Invalid media keys", "Invalid media key", "Media size and CRC required", "Invalid media size",
          "No matching media upload", "Invalid media data", "Media chunk bounds", "Media offset mismatch",
          "Media upload incomplete", "Media checksum mismatch", "Media decode failed"}


def real_config():
    """The trace config of a knob advertising the frozen artwork2 capability."""
    cap = presentation.ARTWORK2_CAPABILITY
    return {"cover": {"entries": cap["cover"]["entries"], "slotBytes": cap["cover"]["maxBytes"],
                      "maxBytes": cap["cover"]["maxBytes"]},
            "icon": {"entries": cap["icon"]["entries"], "slotBytes": cap["icon"]["bytes"], "bytes": cap["icon"]["bytes"]},
            "chunkBytes": cap["chunkBytes"], "haveKeys": cap["haveKeys"], "validateJpeg": True}


class TraceParityTests(unittest.TestCase):
    """The shared fixture, replayed through the FakeKnob's store model."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(TRACES.read_text(encoding="utf-8")) if TRACES.is_file() else None

    def traces(self):
        if self.doc is None:
            self.fail(f"fixture missing: {TRACES} (media_store_traces.json, authored with the firmware store)")
        return self.doc

    def test_fixture_format(self):
        doc = self.traces()
        self.assertEqual(doc["version"], 1)
        names = [case["name"] for case in doc["cases"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 5)
        for case in doc["cases"]:
            with self.subTest(case=case["name"]):
                config = case["config"]
                self.assertEqual(set(config), {"cover", "icon", "chunkBytes", "haveKeys", "validateJpeg"})
                self.assertLessEqual(set(config["cover"]), {"entries", "slotBytes", "maxBytes", "available"})
                self.assertLessEqual(set(config["icon"]), {"entries", "slotBytes", "bytes", "available"})
                self.assertIsInstance(config["validateJpeg"], bool)
                for step in case["steps"]:
                    self.assertIn(step["do"], STEPS)
                    if step["do"] == "media":
                        self.assertIn("req", step)
                        self.assertIsInstance(step["ack"], dict)
                    if step["do"] == "check":
                        self.assertTrue({"slots", "displayed", "clock", "receiving"} & set(step))
                        self.assertLessEqual(set(step) - {"do"}, set(CHECK_PARTS))
                        if "receiving" in step:
                            self.assertIsInstance(step["receiving"], bool)
                self.assertTrue(any(step["do"] == "check" for step in case["steps"]), "slot tables are compared")
        self.assertIn(real_config(), [case["config"] for case in doc["cases"]],
                      "at least one case runs the real capability configuration")

    def test_every_ack_and_check_matches_the_python_model(self):
        doc = self.traces()
        compared = 0
        for case in doc["cases"]:
            with self.subTest(case=case["name"]):
                for index, step, actual in run_media_trace(case):
                    compared += 1
                    if step["do"] == "media":
                        expected = step["ack"]
                    else:
                        expected = {part: step[part] for part in CHECK_PARTS if part in step}
                    self.assertEqual(actual, expected, f"{case['name']} step {index} ({step['do']}): "
                                     f"{json.dumps(step.get('req'))[:200]}")
        self.assertGreater(compared, 100)

    def test_traces_cover_the_contract(self):
        doc = self.traces()
        acks = [step["ack"] for case in doc["cases"] for step in case["steps"] if step["do"] == "media"]
        errors = {ack["error"] for ack in acks if "error" in ack}
        self.assertLessEqual(errors, ERRORS, "only the section 4.3 error strings")
        self.assertEqual(ERRORS - errors, set(), "every section 4.3 error string is compared")
        # "Media unavailable" from a miss with every slot pinned (S = 2): the miss cancelled the
        # upload in progress first (4.4), which the trace shows as a later "No matching media upload".
        pinned = [case for case in doc["cases"] if case["config"]["cover"]["entries"] == 1
                  and any(step["do"] == "media" and step["ack"].get("error") == "Media unavailable"
                          for step in case["steps"])]
        self.assertTrue(pinned, "a trace with S = 2 and both slots pinned")
        # A release (4.4 cancellation) is observable on its own: a check right before it shows an
        # upload receiving and a check right after it shows none, with no other step between.
        released = [case["name"] for case in doc["cases"] for i, step in enumerate(case["steps"][1:-1], 1)
                    if step["do"] == "release" and case["steps"][i - 1].get("receiving") is True
                    and case["steps"][i + 1].get("receiving") is False]
        self.assertTrue(released, "a release between two receiving checks")
        # A frame in the middle of an upload keeps it (4.4): receiving after the frame, then more data.
        framed = [case["name"] for case in doc["cases"] for i, step in enumerate(case["steps"][:-2])
                  if step["do"] == "frame" and case["steps"][i + 1].get("receiving") is True
                  and case["steps"][i + 2]["do"] == "media" and case["steps"][i + 2]["req"].get("op") == "data"
                  and "error" not in case["steps"][i + 2]["ack"]]
        self.assertTrue(framed, "a frame mid-upload, then the upload continues")
        # A store that was never allocated answers "Media unavailable" before the control check.
        unallocated = [case for case in doc["cases"] if case["config"]["cover"].get("available") is False]
        self.assertTrue(unallocated, "a case with an unallocated store")
        self.assertTrue(any(step["do"] == "media" and step["ack"].get("error") == "Media unavailable"
                            and step["req"].get("id") != next((s["id"] for s in case["steps"] if s["do"] == "control"), None)
                            for case in unallocated for step in case["steps"]), "unavailable wins over a stale id")
        # A rejected request naming the live upload carries offset 0 (4.2: no context was matched).
        self.assertTrue(any(step["do"] == "media" and step["req"].get("op") in ("data", "commit")
                            and step["ack"].get("error") == "Stale media control" and step["ack"]["offset"] == 0
                            and case["steps"][i + 1:] and any(s.get("receiving") is True for s in case["steps"][i + 1:i + 9])
                            for case in doc["cases"] for i, step in enumerate(case["steps"])),
                        "a stale data/commit for the live upload answers offset 0")
        ok = [ack for ack in acks if "error" not in ack]
        self.assertEqual({ack["op"] for ack in ok}, {"begin", "data", "commit", "have"})
        self.assertTrue(any(True in ack.get("have", ()) and False in ack.get("have", ()) for ack in ok))
        self.assertTrue(any(case["config"]["validateJpeg"] for case in doc["cases"]))


# ---------------------------------------------------------------------------
# The model against the contract text.

def small(entries=3, slot=64, chunk=8, have=4, validate=False):
    return MediaStoreModel.from_config({"cover": {"entries": entries, "slotBytes": slot, "maxBytes": slot},
                                        "icon": {"entries": entries, "slotBytes": 16, "bytes": 16},
                                        "chunkBytes": chunk, "haveKeys": have, "validateJpeg": validate})


def b64(data):
    import base64
    return base64.b64encode(data).decode("ascii")


class Driver:
    """Section 4.1 requests against one model, as the bridge would send them."""

    def __init__(self, model, ident=7):
        self.model, self.ident = model, ident
        model.control(ident)

    def req(self, op, kind="cover", **fields):
        return self.model.media({"id": self.ident, "op": op, "kind": kind, **fields})

    def begin(self, key, payload, kind="cover"):
        return self.req("begin", kind, key=key, bytes=len(payload), crc32=zlib.crc32(payload))

    def upload(self, key, payload, kind="cover", chunk=8):
        acks = [self.begin(key, payload, kind)]
        if acks[0].get("offset") == len(payload):
            return acks
        for offset in range(0, len(payload), chunk):
            acks.append(self.req("data", kind, key=key, offset=offset, data=b64(payload[offset:offset + chunk])))
        acks.append(self.req("commit", kind, key=key))
        return acks

    def have(self, keys, kind="cover"):
        return self.req("have", kind, keys=list(keys))["have"]


def blob(tag, size=24):
    return (tag.encode() * size)[:size]


class StoreSemanticsTests(unittest.TestCase):
    def test_upload_commit_and_hit(self):
        d = Driver(small())
        acks = d.upload("c1", blob("a"))
        self.assertEqual(acks[0], {"id": 7, "op": "begin", "kind": "cover", "key": "c1", "offset": 0})
        self.assertEqual([a["offset"] for a in acks[1:-1]], [8, 16, 24])
        self.assertEqual(acks[-1], {"id": 7, "op": "commit", "kind": "cover", "key": "c1", "offset": 24})
        self.assertEqual(d.have(["c1", "c2"]), [True, False])
        hit = d.begin("c1", blob("a"))
        self.assertEqual(hit["offset"], 24, "same key, bytes and crc: a hit")
        self.assertEqual(d.req("data", key="c1", offset=0, data=b64(b"x"))["error"], "No matching media upload")
        self.assertEqual(d.req("commit", key="c1")["offset"], 24, "a hit context commits at once")
        slot = d.model.stores["cover"].slots[0]
        self.assertEqual((slot.valid, slot.key, bytes(slot.data[:24])), (True, "c1", blob("a")))

    def test_eviction_happens_at_begin_lru_first_and_pins_are_kept(self):
        d = Driver(small(entries=2))  # S = 3 slots
        for key in ("a", "b", "c"):
            d.upload(key, blob(key))
        store = d.model.stores["cover"]
        self.assertEqual([s.key for s in store.slots], ["a", "b", "c"])
        d.have(["a"])  # touches a: b is now the least recently used
        d.begin("d", blob("d"))
        self.assertEqual([s.valid for s in store.slots], [True, False, True], "b evicted at begin")
        d.model.control(8)  # a new control cancels the upload; the evicted slot stays invalid
        d.ident = 8
        self.assertFalse(store.slots[1].valid)
        d.model.frame("c", "")  # c is the frame's key and displayed: pinned twice
        d.upload("e", blob("e"))
        self.assertEqual(store.slots[1].key, "e", "the invalid slot is taken first")
        d.begin("f", blob("f"))
        self.assertTrue(store.slots[2].valid and store.slots[2].key == "c", "the pinned slot survives")
        self.assertFalse(store.slots[0].valid, "a (older than e) is the victim")

    def test_data_retry_mismatch_and_bounds(self):
        d = Driver(small())
        payload = blob("r", 20)
        d.begin("r", payload)
        self.assertEqual(d.req("data", key="r", offset=0, data=b64(payload[:8]))["offset"], 8)
        self.assertEqual(d.req("data", key="r", offset=0, data=b64(payload[:8]))["offset"], 8, "identical retry")
        self.assertEqual(d.req("data", key="r", offset=0, data=b64(b"X" * 8))["error"], "Media offset mismatch")
        self.assertEqual(d.req("data", key="r", offset=16, data=b64(payload[16:]))["error"], "Media offset mismatch")
        bounds = d.req("data", key="r", offset=16, data=b64(b"12345678"))
        self.assertEqual((bounds["error"], bounds["offset"]), ("Media chunk bounds", 8))
        self.assertEqual(d.req("data", key="r", offset=8, data="not base64")["error"], "Invalid media data")
        self.assertEqual(d.req("data", key="r", offset=8, data=b64(b"x" * 9))["error"], "Invalid media data")
        self.assertEqual(d.req("data", key="r", data=b64(b"x"))["error"], "Media chunk bounds", "no offset")
        self.assertEqual(d.req("data", key="r", offset=8.0, data=b64(b"x"))["error"], "Media chunk bounds")
        self.assertEqual(d.req("data", key="r", offset=-1, data=b64(b"x"))["error"], "Media offset mismatch",
                         "a negative offset within bounds is a mismatch (4.3 literally)")
        self.assertEqual(d.req("data", key="r", offset=2 ** 40, data=b64(b"x"))["error"], "Media chunk bounds")
        self.assertEqual(d.req("commit", key="r")["error"], "Media upload incomplete")
        d.req("data", key="r", offset=8, data=b64(payload[8:16]))
        d.req("data", key="r", offset=16, data=b64(payload[16:]))
        self.assertEqual(d.req("commit", key="r")["offset"], 20)

    def test_checksum_failure_cancels_and_the_slot_stays_invalid(self):
        d = Driver(small())
        payload = blob("k", 8)
        d.req("begin", key="k", bytes=8, crc32=(zlib.crc32(payload) + 1) & 0xFFFFFFFF)
        d.req("data", key="k", offset=0, data=b64(payload))
        failed = d.req("commit", key="k")
        self.assertEqual((failed["error"], failed["offset"]), ("Media checksum mismatch", 8))
        self.assertEqual(d.req("commit", key="k")["error"], "No matching media upload", "the upload ended")
        self.assertFalse(d.model.stores["cover"].slots[0].valid)

    def test_a_begin_hit_needs_the_same_crc(self):
        d = Driver(small())
        payload = blob("h")
        d.upload("h", payload)
        store = d.model.stores["cover"]
        miss = d.req("begin", key="h", bytes=len(payload), crc32=zlib.crc32(payload) ^ 1)
        self.assertEqual(miss["offset"], 0, "same key and bytes, another crc32: a miss (4.4)")
        self.assertEqual([s.valid for s in store.slots[:2]], [True, False], "a new victim; the old slot stays")
        other = bytes(b ^ 0x5A for b in payload)
        d.upload("h", other)
        self.assertEqual([s.valid for s in store.slots[:2]], [False, True], "the duplicate is invalidated")
        self.assertEqual(d.begin("h", payload)["offset"], 0)
        self.assertEqual(d.begin("h", other)["offset"], len(other))

    def test_a_rejected_begin_keeps_the_upload(self):
        d = Driver(small())
        payload = blob("u", 16)
        d.begin("u", payload)
        d.req("data", key="u", offset=0, data=b64(payload[:8]))
        rejected = [({"key": "bad key", "bytes": 4, "crc32": 0}, "Invalid media key"),
                    ({"key": "v", "bytes": 4}, "Media size and CRC required"),
                    ({"key": "v", "bytes": -1, "crc32": 0}, "Media size and CRC required"),
                    ({"key": "v", "bytes": 0, "crc32": 0}, "Invalid media size")]
        for fields, error in rejected:
            with self.subTest(fields=fields):
                self.assertEqual(d.req("begin", **fields)["error"], error)
        self.assertEqual(d.model.media({"id": 7, "op": "begin", "kind": "art", "key": "v", "bytes": 4,
                                        "crc32": 0})["error"], "Unknown media kind")
        self.assertEqual(d.model.media({"id": 6, "op": "begin", "kind": "cover", "key": "v", "bytes": 4,
                                        "crc32": 0})["error"], "Stale media control")
        self.assertEqual(d.req("data", key="u", offset=8, data=b64(payload[8:]))["offset"], 16,
                         "a failed check changes no state (4.3): the upload continues")
        self.assertEqual(d.req("commit", key="u")["offset"], 16)

    def test_have_touches_in_order_and_never_cancels(self):
        d = Driver(small())
        for key in ("a", "b"):
            d.upload(key, blob(key))
        d.begin("c", blob("c"))
        store = d.model.stores["cover"]
        clock = store.clock
        self.assertEqual(d.have(["b", "x", "a", "b"]), [True, False, True, True])
        self.assertEqual((store.slots[0].stamp, store.slots[1].stamp), (clock + 2, clock + 3))
        self.assertEqual(d.req("data", key="c", offset=0, data=b64(blob("c")[:8]))["offset"], 8,
                         "the upload in progress continues")
        self.assertEqual(d.req("have", keys=[])["error"], "Invalid media keys")
        self.assertEqual(d.req("have", keys=["a"] * 5)["error"], "Invalid media keys")
        self.assertNotIn("offset", d.req("have", keys=["bad key"]), "have replies never carry offset")

    def test_a_frame_named_key_is_adopted_at_its_commit(self):
        d = Driver(small())
        d.model.frame("late", "")
        store = d.model.stores["cover"]
        self.assertEqual(store.displayed, -1)
        d.upload("late", blob("l"))
        self.assertEqual(store.displayed, 0)
        d.model.frame("", "")
        self.assertEqual(store.displayed, -1)
        d.model.frame("toolongkey_" * 3, "")
        self.assertEqual(store.frame_key, "", "a key that cannot name a slot pins nothing")

    def test_every_slot_pinned_cancels_the_upload_then_media_unavailable(self):
        d = Driver(small(entries=1))  # S = 2 slots
        d.upload("a", blob("a"))
        d.upload("b", blob("b"))
        store = d.model.stores["cover"]
        d.model.frame("a", "")               # displayed: a's slot
        d.model.frame("b", "", adopt=False)  # frameKey b; the LCD still shows a: both slots pinned
        self.assertEqual(store.pinned(), {0, 1})
        d.req("begin", "icon", key="i", bytes=16, crc32=zlib.crc32(blob("i", 16)))  # an upload in progress
        before = store.table()
        miss = d.begin("c", blob("c"))
        self.assertEqual(miss, {"id": 7, "op": "begin", "kind": "cover", "key": "c", "offset": 0,
                                "error": "Media unavailable"})
        self.assertIsNone(d.model.upload, "the miss cancelled the upload first (4.4)")
        self.assertEqual(d.req("data", "icon", key="i", offset=0, data=b64(blob("i", 8)))["error"],
                         "No matching media upload")
        self.assertEqual(store.table(), before, "no slot changed")

    def test_an_unallocated_store_is_media_unavailable(self):
        model = MediaStoreModel.from_config({"cover": {"entries": 3, "slotBytes": 64, "maxBytes": 64, "available": False},
                                             "icon": {"entries": 3, "slotBytes": 16, "bytes": 16},
                                             "chunkBytes": 8, "haveKeys": 4, "validateJpeg": False})
        model.control(3)
        self.assertEqual(model.media({"id": 3, "op": "have", "kind": "cover", "keys": ["a"]}),
                         {"id": 3, "op": "have", "kind": "cover", "error": "Media unavailable"})
        self.assertEqual(model.media({"id": 9, "op": "begin", "kind": "cover", "key": "k", "bytes": 4, "crc32": 0}),
                         {"id": 9, "op": "begin", "kind": "cover", "key": "k", "offset": 0,
                          "error": "Media unavailable"}, "checked before the control id (4.3 steps 4, 5)")
        self.assertEqual(model.media({"id": 3, "op": "have", "kind": "icon", "keys": ["a"]})["have"], [False])
        self.assertEqual(model.snapshot()["slots"]["cover"], [])

    def test_stale_control_and_release(self):
        model = small()
        self.assertEqual(model.media({"id": 1, "op": "have", "kind": "cover", "keys": ["a"]}),
                         {"id": 1, "op": "have", "kind": "cover", "error": "Stale media control"})
        model.control(5)
        stale = model.media({"id": 4, "op": "begin", "kind": "icon", "key": "i", "bytes": 16, "crc32": 0})
        self.assertEqual(stale, {"id": 4, "op": "begin", "kind": "icon", "key": "i", "offset": 0,
                                 "error": "Stale media control"})
        self.assertNotIn("id", model.media({"id": True, "op": "have", "kind": "cover", "keys": ["a"]}))
        model.media({"id": 5, "op": "begin", "kind": "cover", "key": "r", "bytes": 8, "crc32": 0})
        self.assertTrue(model.receiving())
        model.release()
        self.assertFalse(model.receiving(), "a release ends the upload (4.4)")
        self.assertIsNone(model.upload)
        self.assertEqual(model.media({"id": 5, "op": "have", "kind": "cover", "keys": ["a"]})["error"],
                         "Stale media control")
        model.control(6)
        self.assertEqual(model.media({"id": 6, "op": "data", "kind": "cover", "key": "r", "offset": 0,
                                      "data": b64(b"12345678")})["error"], "No matching media upload")
        model.media({"id": 6, "op": "begin", "kind": "cover", "key": "r", "bytes": 8, "crc32": 0})
        model.frame("r", "")
        self.assertTrue(model.receiving(), "an accepted frame keeps the upload (4.4)")
        model.control(7)
        self.assertFalse(model.receiving(), "a new control ends it")

    def test_validation_order(self):
        model = small()
        model.control(3)
        cases = [({}, {"offset": 0, "error": "Unknown media operation"}),
                 ("text", {"offset": 0, "error": "Unknown media operation"}),
                 ({"id": 3, "op": "BEGIN", "kind": "x", "key": "k"},
                  {"id": 3, "kind": None, "key": "k", "offset": 0, "error": "Unknown media operation"}),
                 ({"id": 3, "op": "begin", "kind": "art", "key": "k"},
                  {"id": 3, "op": "begin", "key": "k", "offset": 0, "error": "Unknown media kind"}),
                 ({"id": 9, "op": "begin", "kind": "cover", "key": "k"},
                  {"id": 9, "op": "begin", "kind": "cover", "key": "k", "offset": 0, "error": "Stale media control"}),
                 ({"id": 3, "op": "begin", "kind": "cover", "key": "k/1", "bytes": 1, "crc32": 0},
                  {"id": 3, "op": "begin", "kind": "cover", "offset": 0, "error": "Invalid media key"}),
                 ({"id": 3, "op": "begin", "kind": "cover", "key": "k", "bytes": 1},
                  {"id": 3, "op": "begin", "kind": "cover", "key": "k", "offset": 0,
                   "error": "Media size and CRC required"}),
                 ({"id": 3, "op": "begin", "kind": "icon", "key": "k", "bytes": 15, "crc32": 0},
                  {"id": 3, "op": "begin", "kind": "icon", "key": "k", "offset": 0, "error": "Invalid media size"}),
                 ({"id": 3, "op": "begin", "kind": "cover", "key": "k", "bytes": 65, "crc32": 0},
                  {"id": 3, "op": "begin", "kind": "cover", "key": "k", "offset": 0, "error": "Invalid media size"})]
        # 4.3 literally (lead ruling of 2026-09-24): a `bytes` or `crc32` that is not an integer
        # (as the firmware's JSON stores one: not a float, a bool or a string) or is outside
        # 0..0xFFFFFFFF needs size and CRC, negative and huge sizes included; a `bytes` in that
        # range but outside the kind's range is an invalid size.
        required = [{"bytes": 4.0}, {"bytes": True}, {"bytes": "4"}, {"bytes": 2 ** 64}, {"bytes": -2 ** 63 - 1},
                    {"bytes": -1}, {"bytes": -4}, {"bytes": 2 ** 32}, {"bytes": -2 ** 63}, {"bytes": 2 ** 64 - 1},
                    {"crc32": -1}, {"crc32": 2 ** 32}, {"crc32": True}, {"crc32": None}]
        invalid = [{"bytes": 0}, {"bytes": 65}, {"bytes": 2 ** 32 - 1}]
        changes = ([(c, "Media size and CRC required") for c in required]
                   + [(c, "Invalid media size") for c in invalid])
        for change, error in changes:
            request = {"id": 3, "op": "begin", "kind": "cover", "key": "k", "bytes": 4, "crc32": 0, **change}
            cases.append((request, {"id": 3, "op": "begin", "kind": "cover", "key": "k", "offset": 0,
                                    "error": error}))
        for request, expected in cases:
            with self.subTest(request=request):
                expected = {k: v for k, v in expected.items() if v is not None}
                self.assertEqual(model.media(deepcopy(request)), expected)

    def test_decode_chunk_is_the_firmware_base64_rule(self):
        self.assertEqual(tool.decode_chunk("QUJD", 8), b"ABC")
        self.assertEqual(tool.decode_chunk("QQ==", 8), b"A")
        self.assertEqual(tool.decode_chunk("QUI=", 8), b"AB")
        self.assertEqual(tool.decode_chunk("QR==", 8), b"A", "unused low bits are ignored")
        for text in ("", "QQ", "QQ=", "Q===", "====", "QQ=A", "QU J", "QUJD\n", "QUJDRA==" * 2, None, 5):
            with self.subTest(text=text):
                self.assertIsNone(tool.decode_chunk(text, 8))
        self.assertIsNone(tool.decode_chunk("QUJDRA==", 3), "over capacity")

    def test_parse_reply_prefix_scan(self):
        line = b'{"media":{"id":17,"op":"data","kind":"cover","key":"abc_DEF-9","offset":0,"data":"%%"'
        self.assertEqual(tool.prefix_scan(line, 24), {"id": 17, "key": "abc_DEF-9"})
        self.assertEqual(tool.prefix_scan(b'{"media":{"id":017,"key":"' + b"k" * 25 + b'"', 24), {})
        self.assertEqual(tool.prefix_scan(b" " * 190 + b'{"media":{"id":5,', 24), {}, "only the first 192 bytes")

    def test_prefix_scan_reads_only_the_first_member(self):
        # cc_media_scan_member: the first `"name"` followed by optional spaces and ':'; that member
        # alone is validated, and a malformed one is omitted, never replaced by a later one.
        scan = tool.prefix_scan
        self.assertEqual(scan(b'{"media":{"id":"x","op":"have","q":{"id":5,"key":"bad key","key":"good"}', 24), {})
        self.assertEqual(scan(b'{"media":{"note":"id","id":7,"key" : "k1"}', 24), {"id": 7, "key": "k1"},
                         'a "id" that is not followed by a colon is not a member')
        self.assertEqual(scan(b'{"media":{"id" : 5 ,"keys":["a"],"key":"k2"}', 24), {"id": 5, "key": "k2"})
        cases = [(b'{"media":{"id":2147483647}', {"id": 2147483647}), (b'{"media":{"id":2147483648}', {}),
                 (b'{"media":{"id":12345678901}', {}), (b'{"media":{"id":0}', {}), (b'{"media":{"id":5.0}', {}),
                 (b'{"media":{"id":5', {}), (b'{"media":{"id":-5}', {}),
                 (b'{"media":{"key":"' + b"k" * 24 + b'"}', {"key": "k" * 24}),
                 (b'{"media":{"key":"' + b"k" * 25 + b'"}', {}), (b'{"media":{"key":""}', {}),
                 (b'{"media":{"key":k1}', {}), (b'{"media":{"key":"k1', {})]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(scan(raw, 24), expected)
        self.assertEqual(scan(b'{"art":{"key":"' + b"a" * 64 + b'","id":3}', 64), {"id": 3, "key": "a" * 64})
        closing = b'{"media":{"id":9,"key":"' + b"k" * 20 + b'"'
        padded = b" " * (tool.SCAN_BYTES - len(closing) + 1) + closing
        self.assertEqual(scan(padded, 24), {"id": 9}, "a key whose closing quote is past the 192 bytes: omitted")
        self.assertEqual(scan(padded[1:], 24), {"id": 9, "key": "k" * 20})


def seg(marker, body):
    return bytes((0xFF, marker)) + (len(body) + 2).to_bytes(2, "big") + body


def dht(table, counts=(1,) + (0,) * 15, values=b"\x00"):
    return seg(0xC4, bytes([table]) + bytes(counts) + values)


def sof0(components=b"\x01\x22\x00\x02\x11\x00\x03\x11\x00", width=240, height=240, precision=8, count=3):
    return seg(0xC0, bytes([precision]) + height.to_bytes(2, "big") + width.to_bytes(2, "big") + bytes([count])
               + components)


APP0 = seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
DQT = seg(0xDB, b"\x00" + bytes([1] * 64))
DHTS = dht(0x00) + dht(0x10) + dht(0x01) + dht(0x11)   # DC0, AC0, DC1, AC1: one 1-bit code each
SOS = seg(0xDA, b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00")
BIG_AC = dht(0x11, (0,) * 15 + (250,), bytes(250))      # 16 + 500 + 252 bytes of the work area
_BITS = 225 * 6 * 2                                     # 4:2:0 240x240: 225 MCUs of six "0" "0" blocks
SCAN = bytes(_BITS // 8) + bytes([(1 << (8 - _BITS % 8)) - 1])


def hand_jpeg(*segments, scan=SCAN):
    """SOI, the segments up to SOS, a scan in which every block has all coefficients zero, EOI."""
    return b"\xFF\xD8" + b"".join(segments) + scan + b"\xFF\xD9"


class JpegCheckTests(unittest.TestCase):
    """The FakeKnob's model of cc_jpeg_validate (ARTWORK2.md sections 4.3 and 5): src/cc_jpeg.cpp's
    marker pre-scan, then the ROM TJpgDec R0.01b jd_prepare in cc_jpeg.cpp's 4 KB work area."""

    def check(self, *segments, **options):
        return tool.jpeg_baseline_240(hand_jpeg(*segments, **options))

    def test_hand_written_covers(self):
        self.assertTrue(self.check(APP0, DQT, sof0(), DHTS, SOS))
        self.assertTrue(self.check(APP0, seg(0xFE, b"note" * 300), DQT, seg(0xDD, b"\x00\x04"), sof0(), DHTS, SOS),
                        "a long comment is skipped, DRI is read")
        self.assertTrue(self.check(DQT, DHTS, sof0(), SOS), "tables before the frame, no APP0")
        self.assertTrue(self.check(DQT, sof0(b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"), DHTS, SOS), "4:4:4")
        self.assertTrue(self.check(DQT, sof0(b"\x01\x21\x00\x02\x11\x00\x03\x11\x00"), DHTS, SOS), "4:2:2")
        chroma_q1 = sof0(b"\x01\x22\x00\x02\x11\x01\x03\x11\x01")
        self.assertFalse(self.check(DQT, chroma_q1, DHTS, SOS), "quantisation table 1 is not loaded")
        self.assertTrue(self.check(DQT, seg(0xDB, b"\x01" + bytes([2] * 64)), chroma_q1, DHTS, SOS))

    def test_marker_prescan_rejections(self):
        for name, segments in (
                ("an empty segment (length 2)", (APP0, seg(0xE1, b""), DQT, sof0(), DHTS, SOS)),
                ("a fill byte before a marker", (APP0, b"\xFF", DQT, sof0(), DHTS, SOS)),
                ("EOI before SOS", (APP0, b"\xFF\xD9", DQT, sof0(), DHTS, SOS)),
                ("SOF1", (DQT, b"\xFF\xC1" + sof0()[2:], DHTS, SOS)),
                ("SOF2 (progressive)", (DQT, b"\xFF\xC2" + sof0()[2:], DHTS, SOS)),
                ("two SOF0", (DQT, sof0(), sof0(), DHTS, SOS)),
                ("12-bit samples", (DQT, sof0(precision=12), DHTS, SOS)),
                ("one component", (DQT, sof0(b"\x01\x11\x00", count=1), DHTS, SOS)),
                ("no frame", (DQT, DHTS, SOS)),
                ("a length past the data", (DQT, sof0(), DHTS, b"\xFF\xFE\xFF\xFF", SOS))):
            with self.subTest(name):
                self.assertFalse(tool.jpeg_prescan(hand_jpeg(*segments)), "refused by the pre-scan")
        good = hand_jpeg(DQT, sof0(), DHTS, SOS)
        self.assertFalse(tool.jpeg_baseline_240(good[:-2]), "no EOI")
        self.assertFalse(tool.jpeg_baseline_240(good + b"\x00"), "a byte after EOI")
        self.assertFalse(tool.jpeg_baseline_240(b"\x00" + good), "leading garbage")
        padded = good[:2] + seg(0xFE, b" " * (presentation.COVER_MAX_BYTES - len(good) - 4)) + good[2:]
        self.assertEqual(len(padded), presentation.COVER_MAX_BYTES)
        self.assertTrue(tool.jpeg_baseline_240(padded))
        over = good[:2] + seg(0xFE, b" " * (presentation.COVER_MAX_BYTES - len(good) - 3)) + good[2:]
        self.assertEqual(len(over), presentation.COVER_MAX_BYTES + 1)
        self.assertFalse(tool.jpeg_baseline_240(over), "32769 bytes")

    def test_decoder_prepare_rejections(self):
        for name, segments in (
                ("luma 1x2", (DQT, sof0(b"\x01\x12\x00\x02\x11\x00\x03\x11\x00"), DHTS, SOS)),
                ("chroma 2x2", (DQT, sof0(b"\x01\x22\x00\x02\x22\x00\x03\x11\x00"), DHTS, SOS)),
                ("quantisation table id 4", (DQT, sof0(b"\x01\x22\x04\x02\x11\x00\x03\x11\x00"), DHTS, SOS)),
                ("a 16-bit quantisation table", (seg(0xDB, b"\x10" + bytes(128)), DQT, sof0(), DHTS, SOS)),
                ("a short quantisation table", (seg(0xDB, b"\x00" + bytes(63)), DQT, sof0(), DHTS, SOS)),
                ("a segment over the 512-byte stream buffer",
                 (seg(0xDB, (b"\x00" + bytes([1] * 64)) * 8), sof0(), DHTS, SOS)),
                ("Huffman class 2", (DQT, sof0(), DHTS, dht(0x20), SOS)),
                ("Huffman table 2", (DQT, sof0(), DHTS, dht(0x02), SOS)),
                ("a DC category over 11", (DQT, sof0(), DHTS, dht(0x00, values=b"\x0c"), SOS)),
                ("a Huffman table shorter than its counts", (DQT, sof0(), DHTS, dht(0x10, (2,) + (0,) * 15), SOS)),
                ("no chroma AC table", (DQT, sof0(), dht(0x00), dht(0x10), dht(0x01), SOS)),
                ("SOS table ids 0x01", (DQT, sof0(), DHTS, seg(0xDA, b"\x03\x01\x01\x02\x11\x03\x11\x00\x3f\x00"))),
                ("SOS with one component", (DQT, sof0(), DHTS, seg(0xDA, b"\x01\x01\x00\x00\x3f\x00"))),
                ("a width of 0", (DQT, sof0(width=0), DHTS, SOS)),
                ("not 240x240", (DQT, sof0(width=241), DHTS, SOS))):
            with self.subTest(name):
                data = hand_jpeg(*segments)
                self.assertTrue(tool.jpeg_prescan(data), "the pre-scan passes it")
                size = tool.tjpgd_prepare(data, bytearray(tool.JD_SZBUF))
                self.assertEqual(size, (241, 240) if name == "not 240x240" else None, "the decoder's prepare decides")
                self.assertFalse(tool.jpeg_baseline_240(data))
        # The 4 KB work area (R0.01b alloc_pool, 4-byte aligned): 512 stream buffer + 256 table +
        # 4 x 24 Huffman + 576 IDCT/RGB + 384 MCU = 1824 B, plus 768 B per 250-code AC table.
        self.assertTrue(self.check(DQT, sof0(), DHTS, BIG_AC * 2, SOS), "3360 B")
        self.assertFalse(self.check(DQT, sof0(), DHTS, BIG_AC * 3, SOS), "4128 B > 4096 B")

    def test_the_scan_is_not_decoded(self):
        # As on the knob: prescan + prepare only; a damaged scan still ending with EOI passes the
        # commit check and fails later on the LCD (jpegDecodeErrors).
        damaged = SCAN[:40] + b"\xFF\xD0\x12\xFF\x00\x34" + SCAN[46:]
        self.assertTrue(self.check(DQT, sof0(), DHTS, SOS, scan=damaged))
        good = self.encode(subsampling=2)
        start = good.index(b"\xFF\xDA")
        start += 2 + int.from_bytes(good[start + 2:start + 4], "big")
        garbled = good[:start] + bytes([0xFF, 0x00] * 8) + b"\xFF\xD0\x12\x34" + good[start + 20:]
        self.assertTrue(tool.jpeg_baseline_240(garbled))
        model = MediaStoreModel.from_config(real_config())
        driver = Driver(model)
        acks = driver.upload("garbled", garbled, chunk=presentation.ARTWORK2_CAPABILITY["chunkBytes"])
        self.assertEqual(acks[-1], {"id": 7, "op": "commit", "kind": "cover", "key": "garbled",
                                    "offset": len(garbled)})

    def test_the_stream_buffer_persists_like_the_static_work_area(self):
        # A SOF0 of 6 content bytes right after SOI: the decoder reads its sampling factors and
        # table ids (bytes 7..14) from what an earlier segment or validation left in its buffer.
        short = hand_jpeg(seg(0xC0, b"\x08\x00\xF0\x00\xF0\x03"), DQT, DHTS, SOS)
        self.assertFalse(tool.jpeg_baseline_240(short), "a zeroed buffer (just after boot): factor 0")
        primed = bytearray(tool.JD_SZBUF)
        primed[7:15] = b"\x22\x00\x02\x11\x00\x03\x11\x00"
        self.assertTrue(tool.jpeg_baseline_240(short, primed))
        model = MediaStoreModel.from_config(real_config())
        buffer = model.jpeg_inbuf
        Driver(model).upload("gray", hand_jpeg(APP0, DQT, sof0(), DHTS, SOS),
                             chunk=presentation.ARTWORK2_CAPABILITY["chunkBytes"])
        self.assertIs(model.jpeg_inbuf, buffer)
        self.assertTrue(any(buffer), "one buffer for every commit check of this knob (a boot)")

    def encode(self, size=(240, 240), **options):
        from PIL import Image
        image = Image.new("RGB", size, (200, 40, 90))
        for x in range(0, size[0], 16):
            image.paste((x % 255, 100, 255 - x % 255), (x, 0, x + 8, size[1]))
        output = io.BytesIO()
        image.save(output, format="JPEG", **{"quality": 85, "optimize": True, "progressive": False, **options})
        return output.getvalue()

    def test_host_encoder_output_passes(self):
        for subsampling in (2, 0):  # 4:2:0 (the host's) and 4:4:4
            with self.subTest(subsampling=subsampling):
                self.assertTrue(tool.jpeg_baseline_240(self.encode(subsampling=subsampling)))
        self.assertTrue(tool.jpeg_baseline_240(tool.cover_jpeg("capture-key")))

    def test_rejections(self):
        good = self.encode(subsampling=2)
        self.assertFalse(tool.jpeg_baseline_240(self.encode(progressive=True, subsampling=2)), "progressive")
        self.assertFalse(tool.jpeg_baseline_240(self.encode(size=(239, 240))), "not 240x240")
        self.assertFalse(tool.jpeg_baseline_240(self.encode(size=(240, 120))), "not 240x240")
        self.assertFalse(tool.jpeg_baseline_240(good[:len(good) // 2]), "truncated")
        self.assertFalse(tool.jpeg_baseline_240(b"\x00" * 64), "not a JPEG")
        from PIL import Image
        gray = io.BytesIO()
        Image.new("L", (240, 240), 128).save(gray, format="JPEG")
        self.assertFalse(tool.jpeg_baseline_240(gray.getvalue()), "one component")


if __name__ == "__main__":
    unittest.main()

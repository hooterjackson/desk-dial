"""App profiles on the device link (plan sections 1c / 1f / 6, S1 DD-B): device.app_parse mirrors the knob's frame
`app` rules (APP_PROFILES.md section 8, cc_frame_parse.cpp parse_app), the appProfiles capability, and the _frame
gate: a knob without appProfiles never receives the new fields (the old-firmware parse matrix), one with it does.
Headless."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r3_support import CAPS_V6  # noqa: E402

from control_center import device  # noqa: E402

CAPS_APP = dict(CAPS_V6, appCanvas=1)
CAPS_PROFILES = dict(CAPS_APP, appProfiles=1, appProfileSlots=4, appProfileMaxBytes=32768, appProfileFeatures=31)


def app(slot="zoom", **extra):
    return {"id": "onshape", "slot": slot, **extra}


PARAM = {"ring": 0, "index": 1, "mode": "A", "value": 0, "step": 1}


class ParseRuleTests(unittest.TestCase):
    """The seven rules the knob enforces, case by case (the harness's profile cases plus axis / plane)."""

    CASES = [
        ("profile-id", {"id": "figma", "slot": "zoom"}, True),
        ("profile-id-crc", {"id": "figma", "crc": 4294967295, "slot": "f4"}, True),
        ("id-11", {"id": "abcdefghijk", "slot": "knob"}, True),
        ("id-dash-underscore-digit", {"id": "my_app-2", "slot": "f1"}, True),
        ("slot-knob", app("knob"), True),
        ("slot-f1", app("f1"), True),
        ("slot-f2", app("f2"), True),
        ("slot-f3", app("f3"), True),
        ("slot-f4", app("f4"), True),
        ("wheel-index-32", app(wheel={"ring": 7, "index": 32}), True),
        ("param-index-32", app(param=dict(PARAM, index=32)), True),
        ("echo-index-32", app(echo={"ring": 0, "index": 32, "seq": 1}), True),
        ("crc-zero", app(crc=0), True),
        ("axis-0", app(param=dict(PARAM, axis=0)), True),
        ("axis-3-plane", app(param=dict(PARAM, axis=3, plane=True)), True),
        ("plane-false", app(param=dict(PARAM, plane=False)), True),
        ("unknown-id-accepted", {"id": "notloaded", "crc": 7, "slot": "knob"}, True),
        ("unknown-key-ignored", app(future={"x": 1}), True),
        ("bad-id-upper", {"id": "Figma", "slot": "zoom"}, False),
        ("bad-id-empty", {"id": "", "slot": "zoom"}, False),
        ("bad-id-long", {"id": "abcdefghijkl", "slot": "zoom"}, False),
        ("bad-id-number", {"id": 1, "slot": "zoom"}, False),
        ("bad-id-space", {"id": "fig ma", "slot": "zoom"}, False),
        ("bad-id-unicode", {"id": "figmä", "slot": "zoom"}, False),
        ("crc-negative", app(crc=-1), False),
        ("crc-high", app(crc=4294967296), False),
        ("crc-string", app(crc="1"), False),
        ("crc-bool", app(crc=True), False),
        ("crc-null", app(crc=None), False),
        ("crc-float", app(crc=1.0), False),
        ("slot-f5", app("f5"), False),
        ("slot-upper", app("KNOB"), False),
        ("wheel-index-33", app(wheel={"ring": 0, "index": 33}), False),
        ("wheel-ring-8", app(wheel={"ring": 8, "index": 0}), False),
        ("param-index-33", app(param=dict(PARAM, index=33)), False),
        ("echo-index-33", app(echo={"ring": 0, "index": 33, "seq": 1}), False),
        ("axis-4", app(param=dict(PARAM, axis=4)), False),
        ("axis-negative", app(param=dict(PARAM, axis=-1)), False),
        ("axis-bool", app(param=dict(PARAM, axis=True)), False),
        ("axis-null", app(param=dict(PARAM, axis=None)), False),
        ("plane-int", app(param=dict(PARAM, plane=1)), False),
        ("plane-null", app(param=dict(PARAM, plane=None)), False),
    ]

    def test_the_table(self):
        for name, value, accept in self.CASES:
            with self.subTest(name):
                stored, ok = device.app_parse(value)
                self.assertEqual(ok, accept)
                if accept:
                    self.assertEqual(stored["id"], value["id"])
                    self.assertEqual(stored["crc"], value.get("crc", 0))
                    self.assertEqual(stored["slot"], device.APP_SLOTS[value["slot"]])
                else:
                    self.assertIsNone(stored)

    def test_slot_numbers_follow_the_firmware(self):
        self.assertEqual([device.APP_SLOTS[t] for t in ("knob", "f1", "f2", "f3", "f4")], [4, 5, 6, 7, 8])
        self.assertEqual([device.APP_SLOTS[t] for t in ("zoom", "orbit", "pan", "tilt")], [0, 1, 2, 3])

    def test_the_stored_keys_are_the_harness_print(self):
        stored, _ = device.app_parse(app(param=dict(PARAM, axis=2, plane=True)))
        self.assertEqual(set(stored), {"id", "crc", "slot", "refused", "flash", "wheel", "wheelRing", "wheelIndex",
                                       "param", "paramRing", "paramIndex", "paramTyped", "paramStep", "paramValue",
                                       "paramBump", "echoSeq", "echoRing", "echoIndex"})


class CapabilityTests(unittest.TestCase):
    def test_app_profiles_capability(self):
        self.assertEqual(device.app_profiles_capability(CAPS_PROFILES),
                         {"slots": 4, "maxBytes": 32768, "features": 31})
        self.assertIsNone(device.app_profiles_capability(CAPS_APP))
        self.assertIsNone(device.app_profiles_capability(dict(CAPS_PROFILES, appCanvas=0)), "needs the canvas")
        self.assertIsNone(device.app_profiles_capability(dict(CAPS_PROFILES, appProfiles=True)))
        self.assertIsNone(device.app_profiles_capability(dict(CAPS_PROFILES, appProfileFeatures="31")))
        self.assertIsNone(device.app_profiles_capability(None))


class FrameGateTests(unittest.TestCase):
    """The old-firmware parse matrix: today's parser never receives the new fields."""
    FRAME = {"mode": "APP", "target": "App", "value": "", "detail": "", "status": "", "layout": "nowPlaying",
             "buttons": [{"label": "Home", "enabled": True, "icon": "house"}] * 4,
             "ring": {"style": "off", "value": 0, "index": 0, "count": 0}}

    def gate(self, raw, caps):
        return device._frame(dict(self.FRAME, app=raw), caps).get("app")

    def test_a_profile_knob_gets_everything(self):
        for raw in ({"id": "figma", "crc": 123, "slot": "f2", "wheel": {"ring": 1, "index": 20}},
                    app("knob", crc=0, param=dict(PARAM, index=17, axis=1, plane=True)),
                    app("tilt", flash=3)):
            self.assertEqual(self.gate(raw, CAPS_PROFILES), raw)

    def test_a_legacy_knob_gets_the_legacy_object_only(self):
        self.assertEqual(self.gate(app("orbit", flash=2), CAPS_APP), app("orbit", flash=2))
        self.assertEqual(self.gate(app("orbit", crc=0), CAPS_APP), app("orbit"), "crc 0 is the default: dropped")
        self.assertEqual(self.gate(app(param=dict(PARAM, axis=1, plane=False)), CAPS_APP), app(param=PARAM))
        for raw in ({"id": "figma", "crc": 123, "slot": "knob"}, {"id": "figma", "slot": "zoom"},
                    app("knob"), app("f3"), app(crc=5), app(wheel={"ring": 0, "index": 16}),
                    app(param=dict(PARAM, index=16)), app(echo={"ring": 0, "index": 20, "seq": 1})):
            with self.subTest(raw=raw):
                self.assertIsNone(self.gate(raw, CAPS_APP))
                self.assertTrue(device.app_parse(raw)[1], "valid for a profile knob")

    def test_the_gate_never_changes_the_callers_object(self):
        raw = app(crc=0, param=dict(PARAM, axis=1))
        self.gate(raw, CAPS_APP)
        self.assertEqual(raw, app(crc=0, param=dict(PARAM, axis=1)))

    def test_no_canvas_no_app(self):
        self.assertIsNone(self.gate(app(), CAPS_V6))
        self.assertIsNone(self.gate({"id": "figma", "slot": "knob"}, dict(CAPS_V6, appProfiles=1)))


if __name__ == "__main__":
    unittest.main()

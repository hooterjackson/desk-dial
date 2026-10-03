"""Desk Dial r3 release 1: the presentation-6 frame contract on the host (device._frame, presentation.py).

The knob (presentation 6) rejects a bri / ctemp ring without an int ring.kelvin 2200..6500, a clusters
ring outside 1 <= count <= 20 / index < count, an unknown layout / style / icon / valueUnit token and
invalid prevTitle / nextTitle text; the host never sends such a frame (it fills, strips or refuses).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import device, presentation as P  # noqa: E402

CAPS_V6 = {"controlCenter": True, "presentation": 6, "glyphs": "latin-ext-a"}
CAPS_V5 = {"controlCenter": True, "presentation": 5, "glyphs": "latin-ext-a"}
BUTTONS = [{"label": "Home", "enabled": True, "icon": "house"}, {"label": "Scenes", "enabled": True, "icon": "wand"},
           {"label": "Temp", "enabled": True, "icon": "thermo", "lit": "on"},
           {"label": "All off", "enabled": True, "icon": "power"}]


def frame(layout="lights", ring=None, **extra):
    out = {"id": 7, "mode": "LIGHTS", "target": "Hall", "value": "", "detail": "", "status": "", "layout": layout,
           "heading": "LIGHTS", "title": "Focus", "subtitle": "62% · 3200 K", "buttons": [dict(b) for b in BUTTONS],
           "ring": ring or {"style": "bri", "value": 62, "index": 0, "count": 0, "kelvin": 3200}}
    out.update(extra)
    return out


class V6FrameTests(unittest.TestCase):
    def test_lights_frames_pass_unchanged(self):
        for value in (frame(), frame("lightsbig", {"style": "ctemp", "value": 23, "index": 0, "count": 0,
                                                    "kelvin": 3200}, volumeCaption="Colour temperature",
                                     value="3200", valueUnit="K"),
                      frame("scenes", {"style": "clusters", "value": 0, "index": 0, "count": 5}, title="Focus",
                            prevTitle="", nextTitle="Evening", meta="1 / 5 · running now")):
            with self.subTest(layout=value["layout"]):
                self.assertEqual(device._frame(dict(value), CAPS_V6), value)

    def test_a_missing_or_invalid_kelvin_is_filled(self):
        for kelvin in (None, 2199, 6501, "3200", True, 3200.0):
            ring = {"style": "bri", "value": 62, "index": 0, "count": 0}
            if kelvin is not None:
                ring["kelvin"] = kelvin
            with self.subTest(kelvin=kelvin):
                out = device._frame(frame(ring=ring), CAPS_V6)
                self.assertEqual(out["ring"]["kelvin"], P.RING_KELVIN_DEFAULT)

    def test_kelvin_is_kept_only_on_bri_and_ctemp(self):
        out = device._frame(frame("scenes", {"style": "clusters", "value": 0, "index": 1, "count": 3,
                                             "kelvin": 3000}), CAPS_V6)
        self.assertNotIn("kelvin", out["ring"])

    def test_clusters_bounds(self):
        for count, index in ((0, 0), (21, 0), (5, 5)):
            with self.subTest(count=count, index=index), self.assertRaises(ValueError):
                device._frame(frame("scenes", {"style": "clusters", "value": 0, "index": index, "count": count}),
                              CAPS_V6)

    def test_value_unit_and_titles(self):
        out = device._frame(frame("lightsbig", valueUnit="°C", value="62", volumeCaption="Brightness"), CAPS_V6)
        self.assertNotIn("valueUnit", out)
        self.assertEqual(out["volumeCaption"], "Brightness", "lightsbig keeps its caption")
        out = device._frame(frame("scenes", {"style": "clusters", "value": 0, "index": 0, "count": 2},
                                  prevTitle="bad\nline", nextTitle="x" * 80), CAPS_V6)
        self.assertNotIn("prevTitle", out)
        self.assertEqual(len(out["nextTitle"].encode("utf-8")), 64)

    def test_the_warm_line_tone(self):
        # Section 19.9 (the r3 navigation, 2026-09-29): `warm` #FFBE69 is a presentation-6 token; a
        # presentation-5 knob gets "secondary".
        out = device._frame(frame(meta="Knob: temperature", metaTone="warm"), CAPS_V6)
        self.assertEqual(out["metaTone"], "warm")
        out = device._frame(frame(meta="Knob: temperature", metaTone="warm"), CAPS_V5)
        self.assertEqual(out["metaTone"], "secondary")

    def test_downgrade_for_presentation_5(self):
        out = device._frame(frame("lightsbig", value="62", valueUnit="%", volumeCaption="Brightness"), CAPS_V5)
        self.assertEqual(out["layout"], "recent")
        self.assertEqual(out["ring"]["style"], "off")
        self.assertEqual([b["icon"] for b in out["buttons"]], ["home", "more", "more", "more"])
        self.assertNotIn("valueUnit", out)
        self.assertEqual(device.v5_parse(out)[1], [])

    def test_the_v5_vocabulary_is_unchanged(self):
        self.assertEqual(P.PRESENTATION_VERSION, 5)
        self.assertNotIn("lights", P.LAYOUTS)
        self.assertEqual(P.LAYOUTS_V6[-3:], ("lights", "lightsbig", "scenes"))
        self.assertEqual(P.ICON_ENUM_V6[len(P.ICON_ENUM):], ("bulb", "thermo", "power", "wand", "house", "album"))


class KelvinTests(unittest.TestCase):
    def test_readme_samples(self):
        self.assertEqual(P.kelvin_rgb(2200), 0xFF9227)     # 255,146,39
        self.assertEqual(P.kelvin_rgb(6500), 0xFFFEFA)     # 255,254,250
        # README's "3200 K ~ 255,183,112" is a rounded sample; its own formula gives 255,184,123 (the
        # firmware fixture harness/fixtures/frames_v6.json agrees for every K 2200..6500).
        self.assertEqual(P.kelvin_rgb(3200), 0xFFB87B)
        self.assertEqual(P.kelvin_rgb(100), P.kelvin_rgb(2200), "clamped")


if __name__ == "__main__":
    unittest.main()

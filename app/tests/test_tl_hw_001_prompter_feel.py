"""TL-HW-001: the knob prompter can send the r4 control fields (feel, reducedHaptics, sound, soundVolume), built by
Desk Dial's own DeviceBridge._feel_fields for the live capabilities and validated before anything is sent; without
them the control line is byte-identical to the legacy one. check_nanod_cc5.push_test enters its Seek control with
the Seek feel. No port, no Tk: a fake knob records what would be written."""
import inspect
import json
import unittest

import test_cc5_tooling as base

t = base.t


class RecordingKnob:
    def __init__(self):
        self.messages, self.entered, self.frames = [], [], []
        self.control_id = None

    def enter(self, control):
        self.entered.append(control)
        self.control_id = control["id"]

    def frame(self, frame):
        self.frames.append(frame)

    def now(self):
        return 0.0


def legacy_control(ident, profile, maximum, position, frame, windows_button=2, windows_hid=False):
    """raw_control as it was before TL-HW-001 (the reference for byte identity)."""
    return {"id": ident, "profile": profile, "min": 0, "max": maximum, "position": position,
            "windowsButton": windows_button, "buttonOrder": [0, 1, 2, 3], "windowsHidEnabled": bool(windows_hid),
            "frame": {**frame, "id": ident}}


@base.needs_tooling
class PrompterFeelFieldsTests(unittest.TestCase):
    def prompter(self):
        ids = iter(range(100, 200))
        knob = RecordingKnob()
        p = t.KnobPrompter(knob, lambda: next(ids), plan=[t.DISPLAY_STEP, "pushes"], log=lambda text: None)
        p.confirmed = True
        return knob, p

    def test_prompter_enter_carries_feel_fields(self):
        knob, p = self.prompter()
        extra = {"feel": "fluid.scrub", "reducedHaptics": False, "sound": 0, "soundVolume": 0}
        cid = p.enter(None, say="End stop test", extra=extra)
        [control] = knob.entered
        for key, value in extra.items():
            self.assertEqual(control[key], value)
        for key in ("id", "profile", "min", "max", "position", "windowsButton", "buttonOrder", "windowsHidEnabled",
                    "frame"):
            self.assertIn(key, control)
        self.assertEqual(control["id"], cid)
        self.assertEqual(control["frame"]["id"], cid)

    def test_without_extra_the_line_is_byte_identical(self):
        knob, p = self.prompter()
        p.enter(None, say="End stop test")
        [control] = knob.entered
        expected = legacy_control(control["id"], t.PROMPT_PROFILE, t.PROMPT_MAX, t.PROMPT_POSITION, control["frame"])
        self.assertEqual(json.dumps(control), json.dumps(expected))
        frame = {"layout": "home", "title": "x"}
        for extra in (None, {}):
            self.assertEqual(json.dumps(t.raw_control(7, "P", 10, 3, frame, extra=extra)),
                             json.dumps(legacy_control(7, "P", 10, 3, frame)))

    def test_invalid_extra_fields_raise_before_anything_is_sent(self):
        for bad in ({"feel": ""}, {"sound": 4}, {"soundVolume": 101}, {"soundVolume": True},
                    {"reducedHaptics": 1}, {"wall": 3}):
            knob, p = self.prompter()
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                p.enter(None, say="x", extra=bad)
            self.assertEqual(knob.entered, [])
            self.assertEqual(knob.frames, [])

    def test_feel_fields_follow_the_live_capabilities(self):
        device = base.companion_device()
        self.assertEqual(t.feel_fields(device, {}, "fluid.scrub"), {})          # older knob: nothing added
        r4 = {"feel": 1, "knobVolume": 1}
        self.assertEqual(t.feel_fields(device, r4, "fluid.scrub"),
                         {"feel": "fluid.scrub", "reducedHaptics": False, "sound": 0, "soundVolume": 0})
        fields = t.feel_fields(device, r4, "fluid.scrub", volume=50, reduced_haptics=True)
        self.assertEqual(fields["soundVolume"], 50)
        self.assertTrue(fields["reducedHaptics"])
        self.assertEqual(t.control_extra_problems(fields), [])

    def test_push_test_enters_seek_with_the_seek_feel(self):
        check = base.load_script("check_nanod_cc5.py")
        self.assertEqual(check.SEEK_FEEL, "fluid.scrub")
        source = inspect.getsource(check.push_test)
        self.assertIn("extra=t.feel_fields(device, live_caps, SEEK_FEEL)", source)


if __name__ == "__main__":
    unittest.main()
